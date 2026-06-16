---
title: ""               # one short imperative sentence — the claim itself
type: claim
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
evidence-class: VAULT-CITE
owner: <agent-id-or-name>
reviewed:
review-cycle: 60         # claims drift; review every 60 days

# Claim-specific
claim-status: draft      # draft | supported | contested | validated | thesis-ready | deprecated
serves-rq: []
supports-contrib: []     # MUST point to at least one Cn from contribution-registry
evidence-for: []         # [[result-slug]] or [[paper-slug]]
evidence-against: []

# Bi-temporal validity (optional — absorption wave 1, Graphiti pattern; invalidate, NEVER delete)
valid-at:                # YYYY-MM-DD — when this claim started holding (empty = since created)
invalid-at:              # YYYY-MM-DD — when it stopped holding. Setting this REQUIRES invalidated-by (LINT-enforced).
invalidated-by:          # [[slug]] of the refuting / superseding page (the provenance of the invalidation)
superseded-by:           # [[claim-slug]] of the successor claim, if one replaces this one

# Typed edges (optional — absorption wave 1; supports/refutes already live in evidence-for/-against)
extends: []              # [[claim-slug]] this claim narrows / extends
uses: []                 # [[method-slug]] / [[dataset-slug]] this claim's evidence depends on
audit:
  leakage: missing       # pass | fail | missing
  fairness: missing
  reproducibility: missing
chapter: ""              # e.g., "ch4-results"
paragraph-draft: ""      # paste-ready thesis sentence(s)
risks: []                # [[risk-slug]]
---

# {Claim Title — paste-ready single sentence}

## Statement

> {one-sentence statement of the claim, exactly as it would appear in the thesis intro / chapter intro}

## Why this claim matters

- Serves RQ: {serves-rq}
- Supports contribution: {supports-contrib}
- Position in thesis: {chapter}, {paragraph context}

## Evidence chain

### Supporting (`evidence-for`)
| Source | Type | Status | Strength |
|---|---|---|---|
| [[result-slug]] | result | frozen / provisional / ... | strong / moderate / weak |
| [[paper-slug]] | paper | deep-read / cited / ... | strong / moderate / weak |

### Counter (`evidence-against`)
| Source | Type | Status | What it shows |
|---|---|---|---|
| | | | |

## Audit summary

| Audit | Status | Evidence |
|---|---|---|
| Leakage | {leakage} | <link or pending> |
| Fairness | {fairness} | <link or pending> |
| Reproducibility | {reproducibility} | <link or pending> |

## Citation-gate check

```
this claim is thesis-ready iff:
  - claim-status: thesis-ready
  - all evidence-for items have can-cite-thesis: true (for results) or reading-status >= read (for papers)
  - all 3 audits: pass
  - no live evidence-against items with stronger evidence than evidence-for
```

## Paragraph draft

{paragraph-draft — 2-4 sentence draft for the thesis chapter; rendered into thesis via 06-scripts/render_claim_chain.py}

## Risks
- [[risk-slug]] — what could invalidate this claim

## Decision log
- [[dec-NNNN-...]] — decisions that bear on this claim

## Update history
- YYYY-MM-DD: <change> (claim-status: <old> → <new>)
