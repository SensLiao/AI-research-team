---
title: ""                        # e.g., "Method A vs Method B — head-to-head"
type: comparison
status: active
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
evidence-class: VAULT-CITE
owner: <agent-id-or-name>
reviewed:
review-cycle: 90

# Comparison-specific
compares: []                     # [[slug]] entries — must have ≥2
dimensions: []                   # axes of comparison

# Bi-temporal validity (optional — absorption wave 1; invalidate, NEVER delete)
valid-at:                        # YYYY-MM-DD — when this comparison's verdict started holding
invalid-at:                      # YYYY-MM-DD — when it stopped (REQUIRES invalidated-by; LINT-enforced)
invalidated-by:                  # [[slug]] of the page that obsoleted it (new result / new method)
superseded-by:                   # [[comparison-slug]] of the refreshed comparison
---

# {A} vs {B} — Comparison

## Items compared
- [[slug-A]]
- [[slug-B]]

## Why this comparison matters
<one sentence: which decision or claim hinges on this comparison>

## Comparison table

| Dimension | A | B | Winner |
|---|---|---|---|
| | | | |
| | | | |

## Key trade-offs
- 
- 

## Verdict for this project
<which one this project chose / leaning toward; pointer to [[dec-NNNN-...]] if a decision was filed>

## Caveats
- 
- 

## Links
- [[dec-NNNN-...]] — decision based on this comparison
- [[claim-slug]] — claim that depends on this comparison
