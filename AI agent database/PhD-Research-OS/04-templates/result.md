---
title: ""               # e.g., "<model> – <dataset> – <prompt> – <metric>"
type: result
status: active
confidence: medium
created: YYYY-MM-DD
updated: YYYY-MM-DD
project: <project-slug>
rq: []
contrib: []
domain: []
tags: []                # add `ablation-only`, `historical-reference`, `rq1-finding` as applicable
related: []
source:
aliases: []
evidence-class: EXP-RESULT
owner: <agent-id-or-name>
reviewed:
review-cycle: none

# Data fields (the row itself)
model: ""               # [[model-slug]]
dataset: ""             # [[dataset-slug]]
prompt: ""              # canonical prompt fingerprint, e.g. point-1-zs
metric: ""              # dice | hd95 | cldice | ... — defined per project
value:                  # numeric value
unit: ""                # dice | hd95-mm | cldice | rate | mm | s | gb
table: ""               # e.g., T1 | T2 | T-S1
split: test             # val | test
std:
ci95:
n-cases:
mean-or-aggregate: mean
experiment: ""          # [[experiment-slug]]
run: ""                 # [[run-slug]] — provenance to a specific run

# Validity-governance fields (citation gate)
result-status: provisional   # provisional | frozen | invalid | superseded | missing-audit | diagnostic-only
can-cite-thesis: false       # DERIVED — must equal (result-status==frozen ∧ leakage==pass ∧ fairness==pass)
eval-frame: unknown          # raw-frame | processing-frame | unknown — project-specific
metric-source: ""            # path / commit / repo+file producing `value`
leakage-audit: missing       # pass | fail | missing
fairness-audit: missing      # pass | fail | missing
reproducibility-audit: missing  # pass | fail | missing — only enforced if reproducibility_level: full
superseded-by: ""            # required iff result-status: superseded
invalidated-by: ""           # required iff result-status: invalid
evidence-artifact: ""        # path to metrics.json / log / commit hash
---

# {Title}

## Number

**{value} {unit}** — {prompt} on {dataset} ({split}, n={n-cases})

## Provenance
- Experiment: [[experiment-slug]]
- Run: [[run-slug]]
- Code: git@{git-commit-from-run}
- Data: {data-version-from-run}
- Metric source: {metric-source}
- Evidence artifact: {evidence-artifact}

## Audits
- Leakage: {leakage-audit} — <evidence or pending>
- Fairness: {fairness-audit} — <evidence or pending>
- Reproducibility: {reproducibility-audit} — <evidence or pending>

## Status reasoning
<why this row is in its current `result-status`. If `frozen`, name the audits that passed. If `provisional`, name what's pending. If `invalid` / `superseded`, name the slug it was replaced by and why.>

## Thesis citation phrasing

| Status | Phrasing for thesis text |
|---|---|
| `frozen` | {value} Dice |
| `provisional` | {value} Dice (provisional — pending review) |
| `invalid` | Earlier {value} Dice — invalidated by [[<pm-slug>]] |
| `superseded` | Historical {value} Dice — superseded by [[<replacement-slug>]] |
| `missing-audit` | {value} Dice (subject to <audit-name> audit) |

## Links
- [[experiment-slug]]
- [[run-slug]]
- [[<model>-benchmark]]
- [[results-validity-policy]] (if exists)
