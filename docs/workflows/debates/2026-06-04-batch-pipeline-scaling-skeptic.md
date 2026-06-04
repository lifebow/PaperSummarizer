# Batch Pipeline Scaling — Skeptic Argument

**Date:** 2026-06-04  
**Role:** Skeptic  
**Model:** opencode/mimo-v2.5-free

---

## Recommendation

**Không thực hiện bất kỳ thay đổi nào cho đến khi có bằng chứng về bottleneck thực tế.** Nếu buộc phải thay đổi, chỉ thêm `concurrent.futures` đơn giản cho PDF download + LLM calls song song, giữ nguyên 3 LLM prompts riêng biệt, bỏ qua stage abstraction.

Thay vì đề xuất 5 thay đổi cùng lúc, hãy làm từng bước nhỏ:
1. Đo thời gian thực tế cho mỗi paper trong pipeline hiện tại
2. Nếu LLM calls là bottleneck → thêm parallel cho HTTP calls
3. Nếu download PDF là bottleneck → thêm parallel downloads
4. **Không bao giờ gộp summary + QA prompts**

---

## Main Argument

### 1. Stage abstraction là over-engineering cho personal tool

Pipeline hiện tại chỉ ~105 dòng code cho `run_once()`. Đơn giản, dễ đọc, dễ debug. Đề xuất thêm stage abstraction, ThreadPoolExecutor, connection-per-thread cho SQLite... đây là **production pipeline orchestration** cho một tool chạy trên máy cá nhân.

20 papers × 30s/paper = 10 phút. Daemon sleep 60 phút. Còn **50 phút idle time** mỗi run. Ở đâu ra bottleneck?

### 2. Gộp summary + QA prompts phá vỡ independent verification

Pipeline hiện tại có thiết kế đúng đắn:
- `build_summary_prompt` yêu cầu LLM tóm tắt paper
- `build_qa_prompt` yêu cầu LLM **kiểm tra lại** summary đó
- `passes_quality_gate` kiểm tra 3 scores

QA step đóng vai trò **independent reviewer**. Khi gộp thành 1 prompt:
- Model **tự tóm tắt rồi tự chấm** → loại bỏ independent verification
- Prompt lớn hơn → vượt payload limit
- Kết quả JSON phức tạp hơn → dễ parse sai

Đây là **anti-pattern kinh điển**: "để model tự chấm điểm chính nó".

### 3. Keyword pre-filter không đủ tin cậy

Paper về "AI safety" có thể dùng từ "alignment", "harmlessness" trong abstract mà không chứa chữ "safety". Keyword matching có **false negatives cao**.

### 4. SQLite write contention: serial writes đơn giản hơn

Thay vì connection-per-thread + WAL checkpoint, chỉ cần: collect kết quả vào list, write tuần tự sau batch. Không cần thread-safe DB writes.

### 5. Chi phí thực tế không đáng lo

300 calls × ~1K tokens = ~300K tokens/day = ~$0.03-$0.30/day. Gộp prompts tiết kiệm ~$0.01-$0.10/day. Không đáng thay đổi architecture.

---

## Risks

1. **SQLITE_BUSY errors**: Concurrent writes gây race conditions khó debug
2. **LLM rate limits**: 4-8 workers gọi đồng thời có thể trigger rate limits
3. **Prompt merge failure**: Mất cả summary và QA nếu merged prompt fail
4. **Config complexity**: User phải understand threading concepts để config đúng
5. **Debugging khó hơn**: Errors interleaved giữa threads
6. **Test non-determinism**: Race conditions không reproducible

---

## Testability

- Concurrent pipeline: race conditions không deterministic, test có thể pass 99 lần rồi fail lần 100
- Stage abstraction cần test matrix 3-5x lớn hơn
- SQLite concurrent writes cần real database, không mock được

---

## Simplicity and Reuse

Alternative đơn giản hơn:

```python
from concurrent.futures import ThreadPoolExecutor, as_completed

# Parallel PDF downloads (I/O bound), sequential LLM + DB writes
with ThreadPoolExecutor(max_workers=4) as executor:
    futures = {executor.submit(download_and_extract, paper): paper for paper in papers}
    for future in as_completed(futures):
        paper, extracted_text = future.result()
        process_paper_sequentially(paper, extracted_text)
```

~15 dòng code thay vì toàn bộ stage abstraction.

---

## Refactor Impact

- `run_once()` return type thay đổi
- `DefaultPaperLlm` interface thay đổi nếu merge prompts
- Config dataclass thêm fields
- 129 tests cần refactor cho concurrent behavior
- Estimate: 300-500 dòng code mới, 50+ lines config, 20+ test modifications

---

## Deployment Impact

Cần thêm structured logging với thread IDs, timing metrics, alerting. Operational overhead cho personal tool.

---

## What Would Change My Mind

1. **Bằng chứng bottleneck thực tế**: Measure >30 phút cho 100 papers
2. **Rate limit data**: Biết chính xác LLM endpoint rate limits
3. **Cost concern verified**: Chi phí LLM >$5/day thực tế
4. **User request trực tiếp**: "Tôi muốn 200 papers/ngày và pipeline quá chậm"
5. **Simple alternative bị reject**: Nếu "parallel downloads + sequential LLM" bị reject

**Tóm tắt**: Implement simplest possible parallelism (parallel I/O, sequential compute), giữ 3 LLM prompts riêng biệt, không thêm stage abstraction.
