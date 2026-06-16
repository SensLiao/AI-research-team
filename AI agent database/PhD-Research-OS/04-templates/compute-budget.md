---
title: ""                # e.g., "Compute budget — 2026-05"
type: compute-budget
status: active
confidence: high
created: YYYY-MM-DD
updated: YYYY-MM-DD
project: <project-slug>
rq: []
contrib: []
domain: []
tags: []
related: []
source:
aliases: []
evidence-class: EXP-RESULT
owner: <agent-id-or-name>
reviewed:
review-cycle: none

# Budget-specific
period: ""                       # e.g., "2026-05" or "2026-Q2"
gpu-hours-budgeted: 0.0
gpu-hours-used: 0.0
failed-run-hours: 0.0
successful-run-hours: 0.0
estimated-cost: ""               # e.g., "$0 (university cluster)" or "$420 (cloud)"
hardware: ""                     # e.g., "2x RTX A6000"
bottleneck: ""                   # e.g., "data loading" | "memory" | "queue wait"
risk: ""                         # e.g., "ablation expansion will exceed weekly budget"
---

# {Period} — Compute Budget

## Summary

| Metric | Value |
|---|---|
| Budgeted | {gpu-hours-budgeted} h |
| Used | {gpu-hours-used} h |
| Successful runs | {successful-run-hours} h |
| Failed runs | {failed-run-hours} h |
| Failed-run % | {derived: failed / used} |
| Estimated cost | {estimated-cost} |
| Hardware | {hardware} |

## Top spenders this period

| Run | Hours | Status | Result |
|---|---|---|---|
| [[run-slug-1]] | | | [[result-slug]] |
| [[run-slug-2]] | | | [[result-slug]] |

## Failed-run analysis

| Run | Hours | Failure mode | Negative-result page |
|---|---|---|---|
| [[run-slug]] | | | [[negative-result-slug]] |

## Bottleneck

{bottleneck description; cite EXP-RESULT or CODE-LIVE evidence}

## Risk

{risk — what would cause budget overrun next period}

## Links
- [[<previous-period-budget>]]
- [[<next-period-budget>]] (if forecast exists)
