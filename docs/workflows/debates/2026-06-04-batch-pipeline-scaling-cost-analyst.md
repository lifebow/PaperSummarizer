# Batch Pipeline Scaling — Cost Analyst Argument

**Date:** 2026-06-04  
**Role:** Cost Analyst  
**Model:** acbpro/gpt-5.5

## Recommendation

**Không coi parallelism là giải pháp tiết kiệm tiền.** Parallelism giảm latency, không giảm cost. Chiến lược tối ưu chi phí:

1. **Cache relevance/result cho rejected papers** — tránh trả tiền lại khi rerun
2. **Cost guard theo estimated tokens + call count** — chặn hóa đơn bất ngờ
3. **Two-phase ranking** — relevance toàn bộ cheap, chỉ summarize top-N
4. **Keyword pre-filter mềm** — giảm candidates nếu nguồn quá rộng
5. **Thử merged summary+QA** — có thể giảm 10-25% token, cần A/B test
6. **Parallelism SAU khi guard đúng** — concurrency default 2-4

## Main Argument

### Token estimation hiện tại

| Call | Input chars | Input tokens | Output tokens |
|------|---:|---:|---:|
| Relevance | 1,500-3,000 | 375-750 | 50-150 |
| Summary | 5,000-9,000 | 1,250-2,250 | 700-1,500 |
| QA | 2,000-5,000 | 500-1,250 | 150-400 |
| **Tổng/accepted paper** | 8,500-17,000 | 2,125-4,250 | 900-2,050 |

### Daily cost scenarios

| Scenario | Papers/day | Pass relevance | Daily tokens |
|---|---:|---:|---:|
| Conservative | 100 | 20% | ~100K-170K |
| Medium | 150 | 40% | ~250K-420K |
| Expensive | 200 | 70% | ~600K-900K |

### Merge summary+QA: tiết kiệm ~10-25%, không phải 50%

API tính theo token, không theo call. Merged prompt tiết kiệm overhead nhưng output JSON lớn hơn. Cần A/B test trước khi kết luận.

### Cache rejected papers = ROI cao nhất

Paper bị reject ở relevance không được lưu → bị re-score trong run sau. Nếu 20-40% candidates lặp giữa hourly runs, cache tiết kiệm ngay 20-40% relevance spend.

### Priority ranking (theo ROI)

1. Cache relevance/rejected candidates
2. Budget guard theo estimated tokens
3. Two-phase ranking (summarize chỉ top-N)
4. Keyword/metadata pre-filter mềm
5. Merged summary+QA (A/B test)
6. Parallelism (latency only)

## Risks

- **Merge làm giảm QA độc lập**: model tự chấm chính nó → tăng false positive
- **Token saving bị phóng đại**: giảm call count ≠ giảm tiền
- **Parallel workers vượt budget**: thread race trên budget counter
- **Keyword filter mất recall**: paper hay không chứa keyword chính xác
- **413 errors**: merged prompt có thể vượt payload limit

## Testability

- Token estimate guard test: fake prompts dài → verify stop khi vượt budget
- Call count guard test: fake LLM đếm calls → verify không vượt max
- Cache test: rejected paper không bị re-score
- Merged prompt test: fake response có đủ fields → digest render đúng

## Simplicity

- Thêm `RunBudget` object trong daemon với `reserve_call(estimated_tokens)`
- Log counters cuối run: calls, tokens, skipped_by_budget
- Char-based token estimate (1 token ≈ 4 chars)
- **Không thêm** tokenizer dependency, billing system, hay queue

## Refactor Impact

- `config.py`: thêm cost guard params
- `daemon.py`: tách pipeline thành budget-able phases
- `db.py`: lưu rejected candidates để cache
- `llm.py`: thêm merged prompt (optional)
- **Không đổi**: telegram, digest, extraction, retrieval

## Deployment Impact

```yaml
filters:
  max_llm_calls_per_run: 80
  max_summary_candidates_per_run: 20
  max_estimated_input_tokens_per_run: 120000
```

Default conservative, backward compatible. Config cũ vẫn load được.

## What Would Change My Mind

- **Merge OK** nếu A/B test cho thấy token giảm 25-35%, quality không giảm
- **Concurrency 8 OK** nếu telemetry cho thấy rate limit chịu được
- **Bỏ keyword filter** nếu sample thực tế có nhiều paper hay không match
- **Thêm tokenizer** nếu daily tokens vượt vài triệu
