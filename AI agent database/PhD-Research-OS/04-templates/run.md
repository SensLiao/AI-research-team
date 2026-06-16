---
title: ""
type: run
status: draft         # draft | running | completed | failed | aborted
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
evidence-class: EXP-RESULT
owner: <agent-id-or-name>
reviewed:
review-cycle: none

# Run-specific (REQUIRED for reproducibility — fill all of these)
experiment: ""              # [[experiment-slug]]
run-id: ""                  # e.g., run-exp-t50-003
seed: 42
git-commit: ""              # full 40-char SHA
data-version: ""            # DVC hash, dataset release, or git-annex hash
env-lock: ""                # [[env-lock-slug]] or path to conda-lock / uv.lock
container-digest: ""        # sha256:... if applicable; empty otherwise
started: ""                 # ISO 8601 datetime
finished: ""                # ISO 8601 datetime
wallclock-hours: 0.0
hardware: ""                # e.g., "1x RTX A6000 48GB" or cloud SKU
metrics-file: ""            # path to metrics.json or wikilink
log-file: ""                # path to training/inference log
notes: ""
superseded-by: ""           # [[run-slug]] if this run was redone
---

# {Run Title}

> Single execution of [[experiment-slug]]. This page is the **birth certificate** for the run.

## Provenance summary

| field | value |
|---|---|
| Experiment | [[experiment-slug]] |
| Seed | {seed} |
| Code | git@{git-commit} |
| Data | {data-version} |
| Env | {env-lock} |
| Container | {container-digest or N/A} |
| Hardware | {hardware} |
| Wallclock | {wallclock-hours} h |

## Status

- Started: {started}
- Finished: {finished or "running"}
- Status: {status}

## What was run

<command / script / config — paste the actual launch command>

```bash
# launch command
```

## Metrics summary

(brief — full numbers in the linked `result` pages)

| Metric | Split | Value |
|---|---|---|
| | | |

## Result pages produced
- [[result-slug-1]]
- [[result-slug-2]]

## Issues / anomalies during the run
- 

## Notes
{notes}
