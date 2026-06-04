# Batch Pipeline Scaling — Final Decision

**Date:** 2026-06-04  
**Role:** Final Judge  
**Model:** acbpro/gpt-5.5  
**Status:** Final decision pending user approval

## 1. Tóm tắt điểm mạnh nhất của từng panelist

### Architect (deepseek)
Đề xuất 2 pha rõ ràng: relevance trước, summarize/QA sau. Đúng hướng — tách phần rẻ khỏi phần đắt. Stage abstraction đầy đủ quá lớn cho v1 nhưng ý tưởng serialization cho DB writes đúng.

### Skeptic (mimo)
**Cảnh báo đúng về gộp summary+QA mất tính kiểm tra độc lập.** QA là bước đánh giá lại summary, không chỉ format. Gộp = model tự chấm chính nó. Cảnh báo over-engineering cho personal tool đúng.

### Implementer (nemotron)
Giữ giải pháp triển khai nhỏ: ThreadPoolExecutor, config guard, không thêm dependency. Định hướng thực dụng cần giữ.

### Performance (glm)
**Chọn đúng mục tiêu: parallelism giảm latency, KHÔNG giảm cost.** Concurrency mặc định 4, KHÔNG gộp summary+QA, giữ SQLite đơn giản. Cần sort accepted papers trước digest.

### Cost Analyst (gpt-5.5)
**Tách rõ cost vs latency optimization.** Cache rejected papers = ROI cao nhất. Budget guard theo tokens, không chỉ call count. Merge tiết kiệm 10-25% thực tế, không phải 50%.

## 2. Đồng thuận

- Cost guard phải có TRƯỚC hoặc CÙNG LÚC parallelism
- Concurrency configurable, default 2-4
- `ThreadPoolExecutor` đủ, không cần queue/engine
- DB writes tuần tự trong v1
- Backward compatible qua `concurrency=1`
- Cần metrics/counters trước khi tối ưu sâu hơn

## 3. Mâu thuẫn đã giải quyết

| Vấn đề | Quyết định | Lý do |
|--------|-----------|-------|
| Gộp summary+QA | **KHÔNG** | Mất QA độc lập, 413 risk, tiết kiệm chỉ 10-25% |
| Stage abstraction | **KHÔNG v1** | Over-engineering, tách helper khi cần |
| Keyword pre-filter | **Soft mode** | Ưu tiên match, không hard drop |
| SQLite writes | **Tuần tự** | Đơn giản, tránh contention |
| Concurrency default | **4** | Balance throughput vs rate limit risk |

## 4. Quyết định cuối

**Two-phase guarded parallel pipeline. Không gộp summary+QA. DB writes tuần tự. Relevance cache + budget guard.**

### Phase 1: Relevance filtering (cheap, parallel)
- Deduplicate
- Check relevance cache
- LLM relevance scoring song song, 4 workers
- Lưu cả rejected để cache
- Budget guard trước mỗi call

### Phase 2: Summarize + QA (expensive, parallel)
- Top-N candidates theo relevance + recency
- Download/extract PDF song song (concurrency riêng = 3)
- Summary → QA → quality gate (giữ sequence trong mỗi paper)
- Thu kết quả → sort deterministic → DB/digest/Telegram tuần tự

## 5. Phương án bị loại

- ❌ Full stage abstraction v1 — quá nhiều code
- ❌ Merged summary+QA — mất QA độc lập, 413 risk
- ❌ Concurrent DB writes — phức tạp không cần thiết
- ❌ Hard keyword drop — false negatives cao
- ❌ Concurrency 8 default — rate limit unknown

## 6. Thứ tự triển khai

### Bước 1: Guard + Cache + Instrumentation
- `RunBudget` object quản lý call count + estimated tokens
- Char-based token estimate (`ceil(chars/4)`)
- Counters cuối run
- Relevance cache cho cả accepted và rejected
- Tests cho budget limits

### Bước 2: Two-phase parallel relevance
- ThreadPoolExecutor với configurable workers
- Reserve budget trước mỗi call
- Exception isolation per paper
- Sort kết quả trước khi chuyển Phase 2

### Bước 3: Parallel summarize/QA + top-N
- Top-N candidates theo relevance score
- PDF download/extract song song (concurrency riêng)
- Summary → QA sequence giữ nguyên trong mỗi paper
- Thu kết quả, sort, ghi tuần tự

## 7. Config values

```yaml
pipeline:
  llm_concurrency: 4
  download_concurrency: 3
  max_papers_per_run: 50
  max_llm_calls_per_run: 80
  max_summary_candidates_per_run: 20
  enable_relevance_cache: true
  keyword_prefilter_mode: soft
  merge_summary_qa: false
```

## 8. Follow-up tests

- Budget guard: stop đúng limit, parallel workers không vượt
- Relevance cache: reuse cho cả accepted/rejected
- Two-phase: relevance trước, summarize/QA sau
- Parallel: mock slow LLM, verify faster than sequential
- DB: writes tuần tự, không SQLITE_BUSY
- Digest: deterministic order
- Keyword prefilter: soft mode không drop paper
- Regression: `ruff check`, `ruff format --check`, `unittest discover`

## Summary

| Decision | Choice |
|----------|--------|
| ThreadPoolExecutor | ✅ Yes |
| Two phases | ✅ Yes |
| Relevance cache | ✅ Yes |
| Budget guard (calls + tokens) | ✅ Yes |
| Top-N before summary | ✅ Yes |
| Soft keyword prefilter | ✅ Yes |
| Sequential DB writes | ✅ Yes |
| Deterministic output | ✅ Yes |
| Merge summary+QA v1 | ❌ No |
| Stage abstraction v1 | ❌ No |
| Concurrent DB writes | ❌ No |
| Hard keyword drop | ❌ No |
| Concurrency 8 default | ❌ No |
