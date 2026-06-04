# Batch Pipeline Scaling — Performance Argument

**Date:** 2026-06-04  
**Role:** Performance  
**Model:** acbpro/glm-5.1

## Recommendation

Áp dụng song song hóa hai pha với `ThreadPoolExecutor`, concurrency mặc định **4 worker**. **KHÔNG** gộp summary+QA. Chạy relevance song song (Phase 1), summary+QA song song (Phase 2). Thêm keyword pre-filter.

## Main Argument

### Thời gian thực tế — LLM là bottleneck duy nhất

| Bước | Thời gian ước tính |
|------|-------------------|
| Relevance LLM | 5-15s |
| PDF Download | 3-10s |
| Text extraction | 1-3s |
| Summary LLM | 10-25s |
| QA LLM | 10-25s |
| DB + Telegram | <3s |

**Tổng: 30-80s/paper, LLM chiếm 70-85%.**

### Speedup ước tính (20 papers)

- Sequential: ~496s (8.3 phút)
- Parallel w=4: ~124s (2.1 phút) = **4x speedup**

### Tại sao KHÔNG gộp summary+QA

1. **Payload >15K chars** → 413 errors (đã verified trong brief)
2. **Latency tăng**: 1 call 20K chars ~40-60s vs 2 calls × 15s = 30s song song
3. **Thất bại toàn phần**: Mất cả summary + QA nếu merged call fail
4. **Giảm concurrency hiệu quả**: Worker busy lâu hơn với 1 call lớn

### Độ đồng thời tối ưu

**Default 4, configurable 2-8.** Trên 8 workers gần như không có lợi ích cho 20 papers/batch, và tăng rủi ro rate limit.

### Keyword pre-filter

Loose keyword match trên abstract trước LLM relevance → giảm 20-50% LLM calls cho Phase 1.

### SQLite: không cần thay đổi

Connection-per-call hiện tại đã đủ với WAL mode. Write contention <100ms, không đáng kể.

## Risks

1. **LLM rate limit unknown** → thêm configurable concurrency, default 4
2. **UNIQUE constraint violation** khi 2 threads cùng insert → fix `upsert_paper` dùng ON CONFLICT
3. **Reordering** → sort accepted papers trước khi write digest

## Testability

- Mock LLM với `time.sleep()` → đo tổng thời gian, assert parallel faster
- DB contention test → 4 workers concurrent writes, verify no SQLITE_BUSY
- Keyword filter test → false negative rate thấp

## Simplicity

~80-120 dòng thay đổi trong daemon.py. ThreadPoolExecutor là stdlib. Không thêm dependency.

## Refactor Impact

- `daemon.py`: refactor chính
- `config.py`: thêm `concurrency`, `keyword_pre_filter`
- `db.py`: fix UNIQUE constraint
- Không đổi: llm.py, extraction.py, retrieval.py, telegram.py, digest.py

## Deployment Impact

- Backward compatible (`concurrency=1` = sequential)
- Thêm timing metrics vào `runs` table
- Cost: không đổi (giữ 3 calls/paper), keyword filter giảm -10 đến -30%

## What Would Change My Mind

1. LLM endpoint rate limit >50 req/s → tăng concurrency
2. Merged call latency thực tế <20s → ủng hộ gộp
3. SQLite contention cao hơn dự kiến → cần connection pool
4. Keyword pre-filter false negative >20% → bỏ filter
5. LLM latency thực tế <5s → không cần parallel
