---
title: ""
type: model
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
review-cycle: 60

# Model-specific
family: ""              # sam | unet | transformer | hybrid | other
native-dim: ""          # 1D | 2D | 2.5D | 3D | nD
params: ""              # e.g., "175B" or "12M"
prompt-modes: []        # e.g., [point, box, text, mask]
training-data: ""
license: ""
official-repo: ""
paper: ""               # [[paper-slug]]
---

# {Model Name}

## What it is
<one-paragraph description>

## Architecture summary
- Encoder:
- Decoder / output head:
- Prompt encoder (if applicable):
- Memory / state (if applicable):

## Native input/output
- Input: <modality, dimensionality, expected size>
- Output: <type, dimensionality>

## Frozen vs trainable boundary
<which components are typically frozen, which are typically fine-tuned>

## Prompt interface
<how prompts are fed; tokenization; fusion path>

## Training data + protocol
- Pre-training data:
- Fine-tuning data:
- Loss(es):
- Key hyperparameters:

## Strengths for this project
- 

## Weaknesses for this project
- 

## Implementation notes
- Official repo:
- Local checkpoint paths (if used):
- Known wrapper footguns: see [[<model-name>-footgun-index]] (if exists)

## Links
- [[paper-slug]]
- [[<model-name>-benchmark]] (when results land)
