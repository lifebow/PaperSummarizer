# Enrichment Pipeline Debate Brief

**Date:** 2026-06-03  
**Status:** Draft  
**Backend:** opencode  

## Question

How should we implement the enrichment pipeline for archived papers?

## Context

- Project: `paper_radar` archive expansion
- Existing behavior: Historical crawl v1 stores metadata only (title, abstract, categories, dates)
- Constraints: Keep SQLite, reuse existing extraction layer, bounded eager enrichment
- Non-goals: Vector DB, real-time sync, full PDF storage

## User Model Selection Gate

```yaml
debate:
  backend: opencode
  user_selected: true
  panel:
    - role: architect
      model: USER_CHOSEN_MODEL
    - role: skeptic
      model: USER_CHOSEN_MODEL
    - role: implementer
      model: USER_CHOSEN_MODEL
  judge:
    role: final_decision
    model: USER_CHOSEN_JUDGE_MODEL
```

## Independent Arguments

Each debate model must write independently. Required sections:

- Recommendation:
- Main argument:
- Schema proposal:
- Risks:
- Testability:
- What would change my mind:

## Enrichment Modes

1. **Eager**: every harvested paper gets extraction and intro embedding
2. **Bounded eager**: process every harvested paper, but only up to configured daily/hourly limits
3. **Filtered lazy**: harvest all metadata, but extract/embed only papers matching configured broad filters

Current recommendation from spec: bounded eager

## Output Files

```text
docs/workflows/debates/2026-06-03-enrichment-brief.md
docs/workflows/debates/2026-06-03-enrichment-architect.md
docs/workflows/debates/2026-06-03-enrichment-skeptic.md
docs/workflows/debates/2026-06-03-enrichment-implementer.md
docs/workflows/debates/2026-06-03-enrichment-final-decision.md
```
