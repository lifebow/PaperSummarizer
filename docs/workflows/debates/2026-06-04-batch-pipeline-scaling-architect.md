# Batch Pipeline Scaling — Argument của Architect

**Ngày:** 2026-06-04  
**Vai trò:** Architect  
**Mô hình:** opencode/deepseek-v4-flash-free

---

## 1. Recommendation

Tôi đề xuất kiến trúc **Pipeline 2 pha với Stage Abstraction** — tách `run_once()` thành một pipeline gồm các stage riêng biệt, mỗi stage có interface đồng nhất, cho phép parallel hóa ở cấp độ stage, và giữ nguyên module boundaries hiện tại.

Cụ thể:
1. **Trích xuất PipelineOrchestrator** — lớp mới chịu trách nhiệm chạy các stage theo thứ tự, quản lý thread pool, và thu thập kết quả.
2. **Stage abstraction** — mỗi công đoạn là một class/namedtuple với `name`, `run(papers, context)`, `is_parallelizable`.
3. **2 pha rõ ràng**: Phase 1 (relevance, cheap) → Phase 2 (summary+QA, expensive). Mỗi phase chạy parallel bên trong, sequential giữa các phase.
4. **Merged summary+QA: CÓ, nhưng opt-in** — mặc định giữ tách rời, thêm config flag để merge. Cho phép A/B testing.
5. **SQLite connection pool** — `queue.Queue` chứa `max_workers + 1` connections, tránh tạo connection mới mỗi lần gọi `_connect()`.

---

## 2. Main Argument (Architecture)

### Vấn đề hiện tại

`PaperRadarService.run_once()` (daemon.py:65-166) là một **monolith 100 dòng**:
- Trộn lẫn orchestration (vòng lặp, error handling, counters) với business logic (LLM calls, DB writes, digest).
- `process_pdf_with_cleanup` dùng closure — khó parallel hóa vì closure capture biến từ vòng lặp.
- 3 LLM calls per paper, tất cả sequential — không scale.
- Module boundaries mờ: daemon.py gọi trực tiếp extraction, llm, db, digest, telegram.

### Kiến trúc đề xuất

```
PaperRadarService.run_once()
  └─ PipelineOrchestrator.run(papers)
       ├─ Stage 1: AuthorEnrichment        [sequential, batch]
       ├─ Stage 2: Deduplication           [sequential, batch]
       ├─ Stage 3: KeywordPreFilter        [parallel, cheap, CPU]
       ├─ Stage 4: RelevanceScoring        [parallel, LLM, title+abstract only]
       ├─ Stage 5: PdfDownload+Extract     [parallel, network+CPU]
       ├─ Stage 6: SummarizeAndQA          [parallel, LLM, full text]
       ├─ Stage 7: QualityGate             [parallel, cheap, no LLM]
       ├─ Stage 8: DbWrite                 [sequential, serialized]
       └─ Stage 9: DigestAndTelegram       [sequential, after pipeline]
```

Mỗi stage implement interface:

```python
@dataclass
class PipelineStage:
    name: str
    is_parallelizable: bool
    is_llm_call: bool  # for cost tracking
    max_concurrency: int | None = None

class StageRunner(ABC):
    @abstractmethod
    def run_batch(self, papers: list[Paper], context: PipelineContext) -> StageResult: ...
```

**Tại sao abstraction này quan trọng:**

- **Testability**: Mỗi stage test riêng, không cần mock toàn bộ pipeline.
- **Extensibility**: Thêm stage mới (keyword filter, caching check, embedding) chỉ cần viết 1 class + insert vào stage list.
- **Reconfigurability**: Thay đổi thứ tự stage, bật/tắt stage, thay đổi concurrency — tất cả từ config.
- **Observability**: Mỗi stage report metrics (papers in, papers out, errors, latency).

### Module boundaries

- **PipelineOrchestrator** → file mới `paper_radar/pipeline.py`
- **Stage classes** → có thể ở `pipeline.py` hoặc mỗi stage một file (nếu phức tạp)
- **Config mới** → thêm `PipelineConfig` dataclass vào `config.py`
- **DaemonService** → giữ `run_once()` như thin wrapper gọi orchestrator
- **LLM layer** → không thay đổi interface, chỉ thay đổi cách gọi (parallel)
- **DB layer** → thêm connection pool, interface giữ nguyên

### Merged summary+QA — phân tích kiến trúc

**Lý do nên merge (giảm 33% LLM calls):**
- 100 papers × 3 calls → 300 calls/ngày
- 100 papers × 2 calls → 200 calls/ngày
- Tiết kiệm ~33% chi phí LLM

**Rủi ro kiến trúc:**
1. **Prompt size**: Summary prompt (~10K chars) + QA prompt (~10K chars) → merged prompt ~15K+. Chạm ngưỡng 15K limit, dễ 413 error.
2. **Coupling**: Summary quality ảnh hưởng QA quality. Nếu summary sai, QA sai theo — khó debug.
3. **Không thể tune riêng**: Không thể thay đổi summary prompt mà không ảnh hưởng QA.

**Giải pháp kiến trúc:**
- Tạo merged prompt — ghép 2 prompt thành 1, nhưng có flag tách riêng.
- Config: `merge_summary_qa: bool = false` — mặc định tách, cho phép bật merge.
- Metric: log tỉ lệ 413 errors khi merge vs tách.

### Keyword pre-filter

**Vị trí trong pipeline:** Stage 3, trước RelevanceScoring.

**Thiết kế:**
- Filter function: kiểm tra abstract chứa keyword từ topics.queries.
- O(1) per paper, không LLM call.
- Nếu filter pass → vào Stage 4 (LLM relevance). Nếu không → loại luôn, không tốn LLM.
- Config: `keyword_prefilter: bool = true`, `keyword_prefilter_match_all: bool = false` (mặc định match ANY).

**Hiệu quả ước tính:** ~40-60% papers bị loại ngay từ keyword filter → giảm 40-60% LLM calls ở Phase 1.

### Relevance caching

**Cache key:** hash của `title + abstract` (SHA256).
**Storage:** Thêm cột `relevance_hash TEXT` và `cached_relevance_score REAL` vào bảng `papers`.

**Flow:**
1. Tính hash của title+abstract.
2. Kiểm tra DB: nếu hash tồn tại và có cached score → dùng luôn, skip LLM.
3. Nếu không → LLM relevance scoring → lưu hash + score vào DB.

---

## 3. Risks (Architectural Risks)

### Risk 1: SQLite write contention

**Giải pháp kiến trúc:**
1. **Single writer pattern:** Tất cả DB writes đi qua một `WriteQueue` — single thread xử lý tuần tự.
2. **Connection pool:** Thay vì tạo connection mới mỗi lần gọi `_connect()`, dùng pool với `max_connections = concurrency + 1`.
3. **Batch writes:** Gom nhiều record_result vào một INSERT statement.

### Risk 2: Thread safety trong prompt merging

**Giải pháp:**
- Dùng `ThreadPoolExecutor` với `max_workers` configurable, default 4.
- Thêm rate limit wrapper — nếu nhận 429/413, retry với exponential backoff.

### Risk 3: PDF download bottleneck

**Giải pháp:**
- Giới hạn concurrency riêng cho PDF download stage: `max_concurrent_downloads = 3`.
- Timeout cho mỗi download: 30s.

### Risk 4: Error isolation

**Giải pháp:**
- Mỗi stage có `run_safe()` wrapper: catch exception → log → trả về error result.
- Pipeline không stop nếu một paper fail. Chỉ stop nếu critical stage fail.

---

## 4. Testability

1. **PipelineOrchestrator test:** Mock tất cả stages, verify thứ tự stage, verify parallel stages chạy concurrent.
2. **Stage tests:** Mỗi stage test riêng với mock dependencies.
3. **SQLite thread safety test:** Tạo N threads cùng insert → verify không SQLITE_BUSY.
4. **Config test:** `max_workers=1` → sequential behavior (backward compatible).

---

## 5. Simplicity and Reuse

**Không over-engineer:**
- ❌ Không dùng event bus, message queue, workflow engine.
- ✅ Stage là class đơn giản, 1 file `pipeline.py`.
- ✅ Config là dataclass, không cần YAML schema mới.

**Code ước tính:**
- `pipeline.py`: ~150-200 dòng
- `config.py`: +20 dòng
- `daemon.py`: -50 dòng
- `db.py`: +20 dòng

**Tổng: ~±200 dòng thay đổi.**

---

## 6. Refactor Impact

### Files thay đổi

| File | Thay đổi |
|---|---|
| `paper_radar/pipeline.py` | **MỚI** — PipelineOrchestrator, Stage classes |
| `paper_radar/daemon.py` | Sửa — `run_once()` gọi pipeline |
| `paper_radar/config.py` | Thêm — PipelineConfig |
| `paper_radar/db.py` | Thêm — connection pool, relevance caching |
| `paper_radar/llm.py` | Thêm — merged prompt (optional) |
| `tests/test_pipeline.py` | **MỚI** — pipeline tests |

### Backward compatibility

- `max_workers=1` → behavior giống hệt sequential hiện tại.
- `merge_summary_qa=False` → pipeline vẫn gọi 3 LLM calls như cũ.
- Tất cả config cũ vẫn hoạt động.

---

## 7. Deployment Impact

### Performance (dự tính)

| Config | 20 papers | 100 papers |
|---|---|---|
| Sequential (hiện tại) | ~10 min | ~50 min |
| Parallel w=4, no merge | ~2.5 min | ~12.5 min |
| Parallel w=4, merged | ~1.7 min | ~8.3 min |
| Parallel w=8, merged + prefilter | ~1 min | ~5 min |

### Cost (dự tính)

| Config | LLM calls/20 papers | Cost |
|---|---|---|
| Hiện tại (3 calls) | 60 | baseline |
| Keyword prefilter + cache | ~25-35 | ~50% reduction |
| Merged summary+QA | 40 | 33% reduction |
| All combined | ~15-25 | ~60-70% reduction |

---

## 8. What Would Change My Mind

1. **Prompt merging làm giảm quality >10%** — cần A/B test trên 50 papers.
2. **SQLite write contention thực tế >100ms** — cần PostgreSQL.
3. **Keyword pre-filter loại bỏ >80% papers** — relevance scoring gần như vô dụng.
4. **User muốn real-time processing** — cần thay đổi orchestrator.
5. **LLM endpoint rate limit rất thấp** (< 5 RPM) — cần TokenBucketRateLimiter.
6. **Relevance caching không hiệu quả** (>90% papers mỗi run là mới).
