---
title: ""
type: synthesis
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
review-cycle: 90

# Synthesis-specific
covers: []                       # [[slug]] — pages this synthesis pulls together
for-chapter: ""                  # e.g., "ch3-related-work" | "ch5-method" | empty
claim-chain: []                  # [[claim-slug]] in argument order — used by render_claim_chain.py
required-evidence-status: thesis-citable   # citation gate level required for rendering
---

# {Synthesis Title}

> A cross-cutting writeup that pulls together evidence from multiple typed pages.
>
> **Use this template for:** thesis chapter drafts, multi-paper literature syntheses, multi-experiment analyses, multi-agent roundtables, postmortems spanning multiple incidents.

---

## Purpose

<What question does this synthesis answer? What is the single takeaway?>

## Scope

- **Includes:** <topics covered>
- **Excludes:** <topics deliberately left out>

## Claim chain (for thesis rendering)

The `claim-chain:` field above lists ordered claims this synthesis argues. The renderer (`06-scripts/render_claim_chain.py`) walks this chain and produces a draft thesis paragraph.

| # | Claim | Evidence-for status | Render? |
|---|---|---|---|
| 1 | [[claim-slug-1]] | <count> citable | <yes/no> |
| 2 | [[claim-slug-2]] | <count> citable | <yes/no> |
| 3 | [[claim-slug-3]] | <count> citable | <yes/no> |

If any claim is not yet rendering, this synthesis stays `status: draft`.

## Evidence pulled

### Pages this synthesis covers
| Page | Type | Why included |
|---|---|---|
| [[slug-1]] | <type> | |
| [[slug-2]] | <type> | |

## Argument

### Section 1 — {sub-topic}
<text with inline `[[slug]]` citations>

### Section 2 — {sub-topic}

### Section 3 — {sub-topic}

## Headline takeaway

<the single sentence a reader should remember>

## Open questions surfaced

- 
- 

## Decisions enabled by this synthesis

- [[dec-NNNN-...]] — decision this synthesis supported

## If this is a chapter draft

When ready for thesis rendering:
1. Set `required-evidence-status: thesis-citable`
2. Run `python 06-scripts/render_claim_chain.py <synthesis-slug>`
3. The renderer will refuse to produce output if any cited row has `can-cite-thesis: false`
4. If any claim is not yet `thesis-ready`, mark this synthesis `status: draft` and revisit
