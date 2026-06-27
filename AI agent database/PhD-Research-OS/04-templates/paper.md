---
title: ""
type: paper
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
source: 01-raw/papers/<filename>.pdf       # or .md if you've extracted text
aliases: []
evidence-class: PAPER-CITE
owner: <agent-id-or-name>
reviewed:
review-cycle: none

# Paper-specific
authors: []
year:
venue: ""
doi: ""
url: ""
reading-status: to-read    # to-read | skimmed | read | deep-read | cited | deprecated  (this is the DEPTH DIAL)
relevance: adjacent        # direct | adjacent | background
paper-type:                # method | theory | empirical | dataset-benchmark | tool | review | position
read-purpose:              # idea | method | baseline | related-work | reproduce | review
reading-objective: ""      # one line — what this read must establish for the thesis
key-claims: []
serves-claim: []           # [[claim-slug]] this paper supports / contradicts
---

# {Paper Title}

> Cite as: {Author et al., Year — Venue}

<!-- SECTION GRADUATION — LINT (06-scripts/lint_vault.py) keys required sections on reading-status:
       skimmed   → Stage 0 + Pass 1                        (the honest minimum)
       read      → + Pass 2 (claim-evidence table + method + results)
       deep-read → + Figure reading + Pass 3 appraisal + Stage 4
       cited     → same as deep-read (render_claim_chain.py already gates citation on read/deep-read/cited)
     A deliberately-shallow page keeps a shallow reading-status; don't fake depth. -->

## Stage 0 — Positioning   <!-- required: skimmed+ -->
- **Why I'm reading this (purpose)**: <idea | method | baseline | related-work | reproduce | review>
- **Paper type**: <method | theory | empirical | dataset-benchmark | tool | review | position>
- **Relation to my thesis**: <A-core | B-related | C-background>
- **Reading objective (1 line)**:

## TL;DR   <!-- required: skimmed+ -->
<2-4 sentences: what the paper IS, what it CHANGES vs prior work, why it matters for this project.>

## Pass 1 — Contract & big picture   <!-- required: skimmed+ -->

**Paper contract (one sentence):**
> In **{problem}**, this paper proposes **{method / theory / data}**; vs **{prior work}** it **{closes which gap}**; supported by **{evidence}**; valid under **{conditions / assumptions}**.

- **Category** (what kind of result):
- **Context** (which line of work / prior art):
- **Correctness** (do the assumptions look sound, first read?):
- **Contributions** (the minimal incompressible ones — not the authors' bullet list):
- **Clarity** (is it worth a deeper pass?):

## Pass 2 — Method & evidence teardown   <!-- required: read+ -->

### Claim → evidence ledger
*(One row per claim. Directness = how the evidence relates to the claim. Risk = how much I'd bet it's wrong/overstated.)*

| # | Claim | Evidence (Fig/Table/§) | Dataset / n | Metric | Directness | Supports? | Risk |
|---|-------|------------------------|-------------|--------|------------|-----------|------|
| 1 | | | | | direct \| indirect \| proxy \| assumed | yes \| partial \| no | hi/med/lo — why |

### Method breakdown
- **Problem definition** (input / output / target / task boundary):
- **Core assumptions** (what must hold for this to work):
- **Representation / what it changes** (structure / search space / objective):
- **Objective / loss — per term, and what deleting it does**:
  - `L_term` — role — ablate-it effect:
- **Training flow** / **Inference flow** / **train-infer consistency**:
- **Data** (source / scale / splits / leakage risk):
- **Cost** (compute / data / annotation / deployment):
- **Essential difference vs baseline** (the one mechanism that actually changed):

### Results worth remembering
<at least one key results table re-stated with numbers from raw; cite page anchors>

| Setting | Metric | Number | Notes |
|---|---|---|---|
| ... | ... | ... | (p. N) |

## Pass 2b — Figure reading   <!-- required: deep-read+ -->
- **{Figure N}** — axes: / controls: / error bars: / take-home: / what I distrust:

## Pass 3 — Critical appraisal (reviewer mode)   <!-- required: deep-read+ -->

**7-dimension scores (1-4):** Soundness _ · Significance _ · Originality _ · Eval-rigor _ · Reproducibility _ · Clarity _ · Domain-validity _

- **Implicit assumptions** (not stated, but load-bearing):
- **Limitations the paper acknowledges**:
- **Limitations it does NOT acknowledge but matter here**:
- **Baseline fairness** (strongest baselines? same budget? fair tuning? no leakage?):
- **Ablation sufficiency** (is each key module actually isolated?):
- **Statistical robustness** (variance / CI / seeds / significance?):
- **Selective reporting** (hidden failures / cherry-picked datasets / quiet filtering?):
- **Reproducibility gaps** (code / data / seeds / hyperparams / env?):
- **Generalization** (other datasets / scale / real setting?):
- **Reviewer questions** (what I'd ask the authors):
- **Formal checklist** (<NeurIPS | CASP | Cochrane RoB2 | STROBE | TRIPOD+AI | PRISMA | CONSORT | none>) — met / partial / unmet:

### Reproducibility checklist   <!-- required only at reproduce-level depth -->
- code / data / seeds / hyperparameters / environment / exact commands — present or missing:

## Stage 4 — Concept network & trend   <!-- required: deep-read+ -->

### Typed relations (this paper ↔ others)
- **inherits** [[slug]] — builds on / continues
- **refutes** [[slug]] — contradicts a result/claim
- **unifies** [[slug]] [[slug]] — merges two lines
- **replaces** [[slug]] — supersedes
- **opens** [[slug]] — creates a new problem/direction
- **extends / uses** [[slug]] — typed edge to method/dataset

### Trend & opportunity
- **Shifts** (problem / method / representation / assumption / evaluation / resource — from → to):
- **Failure modes the field keeps hitting**:
- **Mechanism vs result** (does it explain WHY it works, or just report THAT it works?):
- **My opportunity** (improve / transfer / refute / unify / redefine — and where I'd attack):

## Direct relevance to thesis   <!-- required: read+ -->
- **Which RQ / contribution**:
- **What it offers (method / dataset / baseline / θ\*)**:
- **Thesis citation draft (paste-ready, 1-2 sentences)**:
  > "..."
- **What it does NOT solve for this project**:

## Links
- [[related-slug-1]] — why related
- [[related-slug-2]]

## Reading log
- YYYY-MM-DD: <skimmed | read | deep-read> — <one-line takeaway>
