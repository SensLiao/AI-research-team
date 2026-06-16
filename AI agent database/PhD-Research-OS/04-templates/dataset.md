---
title: ""
type: dataset
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
evidence-class: DATA-CITE
owner: <agent-id-or-name>
reviewed:
review-cycle: 90

# Dataset-specific
size: ""                # e.g., "1000 samples" or "500 hours"
modality: ""            # e.g., "CT", "text", "audio", "tabular"
classes: []
split-policy: ""        # e.g., "patient-level 80/10/10"
preprocessing: ""       # one-line summary; details in body
source-url: ""
license: ""
local-path: ""
version: ""             # release / git tag / DVC version
data-hash: ""           # for reproducibility
---

# {Dataset Name}

## What it is
<one-paragraph description>

## Provenance
- Source: <institution / paper / challenge>
- License: {license}
- Version: {version}
- Local copy: {local-path}
- Data hash: {data-hash}

## Composition
- Total size: {size}
- Modality: {modality}
- Classes: {classes}

## Splits
| split | n | source |
|---|---|---|
| train | | |
| val | | |
| test | | |

Split policy: {split-policy}

## Preprocessing
{preprocessing details — voxel size, normalization, augmentation}

## Caveats
- Known biases:
- Annotation provenance:
- Drift / version notes:

## Why this dataset for this project
<RQ alignment, contribution support>

## Why NOT this dataset (limitations)
<things this dataset cannot answer>

## Used by
- [[experiment-slug]] — <brief result>

## Links
- Source paper: [[paper-slug]]
- Challenge / benchmark suite: [[entity-slug]] (if applicable)
