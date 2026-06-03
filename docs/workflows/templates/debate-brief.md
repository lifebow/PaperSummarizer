# DEBATE_TOPIC Debate Brief

**Date:** YYYY-MM-DD  
**Status:** Draft  
**Backend:** opencode  

## Question

State the decision that needs debate.

## Context

- Project:
- Existing behavior:
- Constraints:
- Non-goals:

## User Model Selection Gate

The user must choose the debate models and the final judge model before any
automated debate starts.

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

Do not replace these placeholders with hardcoded defaults unless the user has
chosen those exact models.

## Independent Arguments

Each debate model must write independently. Do not show one model another
model's argument until all first-pass arguments are complete.

Required sections per debater:

- Recommendation:
- Main argument:
- Risks:
- Testability:
- Simplicity and reuse:
- Refactor impact:
- Deployment impact:
- What would change my mind:

## Final Judge

The final judge uses `USER_CHOSEN_JUDGE_MODEL`.

The judge must:

- compare all panel arguments,
- identify agreements and conflicts,
- cite or summarize each model's strongest point,
- choose a decision,
- list rejected alternatives,
- list follow-up tests or experiments,
- avoid inventing evidence not present in the brief or arguments.

## User Approval Gate

The final decision does not become a plan until the user approves it.

If the user rejects the decision:

1. revise the question or constraints,
2. rerun debate with selected models or a new user-selected panel,
3. write a new final decision.

## Output Files

Expected files for a debate run:

```text
docs/workflows/debates/YYYY-MM-DD-DEBATE_TOPIC-brief.md
docs/workflows/debates/YYYY-MM-DD-DEBATE_TOPIC-architect.md
docs/workflows/debates/YYYY-MM-DD-DEBATE_TOPIC-skeptic.md
docs/workflows/debates/YYYY-MM-DD-DEBATE_TOPIC-implementer.md
docs/workflows/debates/YYYY-MM-DD-DEBATE_TOPIC-final-decision.md
```
