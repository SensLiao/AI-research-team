---
title: ""
type: experiment
status: draft
confidence: medium
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

# Experiment-specific
experiment-id: ""        # e.g., exp-tNN-<short>
model: ""                # [[model-slug]]
dataset: ""              # [[dataset-slug]]
protocol: ""             # [[protocol-slug]]
serves-rq: []            # which RQ this experiment slice answers
serves-contrib: []       # which contributions this serves
expected-outputs: []
stop-conditions: []
runs: []                 # [[run-slug]] entries — populated as runs happen
result-pages: []         # [[result-slug]] entries — populated as results land
---

# {Experiment Title}

## Research question
<the specific narrow question this experiment answers — 1-2 sentences>

## Variables
| Variable | Held constant | Changed across runs |
|---|---|---|
| Model | | |
| Dataset | | |
| Prompt / protocol | | |
| Seed | | |
| Hyperparameter | | |

## Hypothesis
<what you predict will happen and why>

## Methodology
### Inputs
<data / model / prompt sources>

### Procedure
<step-by-step procedure>

### Stop conditions
<when to declare the experiment "complete" — N runs, N hours, convergence criterion>

## Expected outputs
- Metrics: <list>
- Result pages: <expected slugs>
- Negative-result pages (if applicable): <expected slugs>

## Pre-launch checklist
- [ ] Data version frozen (`data-version` recorded)
- [ ] Code commit pinned (`git-commit` recorded)
- [ ] Env locked (`env-lock` recorded)
- [ ] Smoke test (1 case) passed
- [ ] Compute budget allocated (see `[[cb-YYYY-MM]]`)
- [ ] Result pages pre-allocated as `result-status: provisional`

## Runs
(populated as runs happen)

| run-slug | seed | started | finished | status | metrics-summary |
|---|---|---|---|---|---|
| | | | | | |

## Result pages
(populated as runs produce results)

- [[result-slug-1]]
- [[result-slug-2]]

## Open questions
- 

## Decision log for this experiment
- [[dec-NNNN-...]]
