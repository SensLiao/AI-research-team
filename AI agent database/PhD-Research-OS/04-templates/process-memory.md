---
title: ""                       # short bug-class name
type: process-memory
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

# PM-specific
pm-id: PM-NNNN          # sequential, never renumbered
bug-class: ""           # category name; should match an entry in bug-class-index
discovered-in: ""       # [[run-slug]] or [[experiment-slug]] where this was first seen
pm-status: draft        # draft | active | confirmed | retired
affected-rows: []       # [[result-slug]] rows that became invalid because of this PM
superseded-by: ""       # [[pm-slug]] if this PM was replaced
---

# PM-{NNNN}: {Bug-class title}

> Postmortem of a recurring failure pattern. Cited by future agents to avoid the same mistake.

## Symptom

<exactly what the agent / human saw — file path, log line, metric value, observed behavior>

## Root cause

<the underlying mechanism, not the surface behavior>

## How this was caught

<inspection commands that would have surfaced this earlier>

## Permanent rule (do this)

<the one-line rule that prevents future recurrence>

## Permanent ban (don't do this)

<the one-line anti-pattern>

## Affected past results

| Result | Status before PM | Status after PM | Replacement |
|---|---|---|---|
| [[result-slug]] | provisional | invalid | [[<replacement-slug>]] |

## Required check (going forward)

<concrete check the agent must run before declaring related work done>

```bash
# example check command
```

## Related PMs
- [[pm-NNNN-...]] — related root cause
- [[pm-NNNN-...]] — related symptom but different cause

## Update history
- YYYY-MM-DD: discovered in [[run-slug]]
- YYYY-MM-DD: confirmed against [[run-slug-2]]
- YYYY-MM-DD: pm-status: draft → active
