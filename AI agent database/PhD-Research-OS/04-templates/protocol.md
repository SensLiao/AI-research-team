---
title: ""
type: protocol
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
evidence-class: VAULT-CITE
owner: <agent-id-or-name>
reviewed:
review-cycle: 90

# Protocol-specific
protocol-type: ""             # experimental | evaluation | ablation | deployment
protocol-version: ""          # e.g., "v1.0"
applies-to: []                # [[experiment-slug]] | [[dataset-slug]] entries
superseded-by: ""             # [[protocol-slug]] if a newer version exists
rationale-doc: ""             # [[dec-NNNN-...]] that locked this protocol
---

# {Protocol Name} — {protocol-type} v{protocol-version}

## Purpose

<one sentence: what this protocol fixes / what variability it removes>

## Scope

- Applies to: {applies-to}
- Out of scope: <what this protocol does NOT cover>

## Protocol

### Inputs (what must be provided)
- 

### Steps (what must happen, in order)
1. 
2. 
3. 

### Outputs (what must be produced)
- 

### Forbidden variations
- 

## Rationale

<why this protocol was locked; refer to [[dec-NNNN-...]] decision page>

## Validation

How to confirm a run followed this protocol:

```bash
# example validation command
```

## Related protocols
- [[<previous-protocol-version>]] (if this supersedes one)
- [[<related-protocol>]] (parallel scope)

## Update history
- YYYY-MM-DD: v1.0 ratified (see [[dec-NNNN-...]])
