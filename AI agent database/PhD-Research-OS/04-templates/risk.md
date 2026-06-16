---
title: ""
type: risk
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
evidence-class: ASSUMPTION
owner: <agent-id-or-name>
reviewed:
review-cycle: 30

# Risk-specific
risk-status: open                # open | mitigated | accepted | invalidated
severity: medium                 # high | medium | low
affects-claim: []                # [[claim-slug]] entries this risk threatens
mitigation: ""
surfaced-by: ""                  # [[meeting-slug]] | [[decision-slug]] | [[run-slug]]
---

# Risk: {short risk title}

## Description
<one paragraph: what could go wrong, why, and what consequence>

## Severity rationale
- Severity: {severity}
- Why this severity:

## What it threatens
| Affected | Type | How |
|---|---|---|
| [[claim-slug]] | claim | |
| [[experiment-slug]] | experiment | |

## Mitigation strategy
<if status: mitigated, describe the mitigation in place>

## Triggers (signals this risk is materializing)
- 
- 

## Acceptance reasoning (if status: accepted)
<why we accept this risk as residual rather than mitigating further>

## Update history
- YYYY-MM-DD: surfaced (status: open)
- YYYY-MM-DD: status: open → mitigated (mitigation: ...)
