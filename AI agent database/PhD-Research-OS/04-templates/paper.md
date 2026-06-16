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
reading-status: to-read    # to-read | skimmed | read | deep-read | cited | deprecated
relevance: adjacent        # direct | adjacent | background
key-claims: []
serves-claim: []           # [[claim-slug]] this paper supports / contradicts
---

# {Paper Title}

> Cite as: {Author et al., Year — Venue}

## TL;DR
<2-4 sentences. What the paper IS, what it CHANGES vs prior work, why it matters for this project.>

## Pass 1 — Big picture
- **Problem**:
- **Core idea**:
- **Key figures/tables**:
- **Conclusion claims**:

## Pass 2 — Method
### Architecture
<text description; replace any architectural diagram by writing what it shows>

### Training objective
<loss(es), supervision signal, frozen vs trainable, prompt format>

### Data & setup
<datasets, splits, batch, optimizer, image size, key hyperparameters>

### Inference protocol
<how prompts are fed at test time, post-processing, special tricks>

## Results worth remembering
<at least one key results table re-stated with numbers from raw; cite page anchors>

| Setting | Metric | Number | Notes |
|---|---|---|---|
| ... | ... | ... | (p. N) |

## Pass 3 — Critique & relevance to this project

### Limitations the paper itself acknowledges
- 

### Limitations the paper does NOT acknowledge but matter for this project
- 

### Direct relevance to thesis
- **Which RQ**:
- **Which contribution**:
- **What this paper offers (theta_*, method, dataset, baseline)**:
- **Thesis citation draft (1-2 sentences, paste-ready)**:
  > "..."

### What this paper does NOT solve for this project
- 

## Links
- [[related-slug-1]] — why related
- [[related-slug-2]]

## Reading log
- YYYY-MM-DD: <skimmed | read | deep-read> — <one-line takeaway>
