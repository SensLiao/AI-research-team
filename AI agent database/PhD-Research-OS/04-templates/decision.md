---
title: ""                       # short decision title
type: decision
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
evidence-class: DECISION-CITE
owner: <agent-id-or-name>
reviewed:
review-cycle: none

# Decision-specific (ADR-style)
decision-status: proposed       # proposed | accepted | rejected | superseded | revisit-needed
date: YYYY-MM-DD
decision-owner: <human-or-team-name>
context: ""
options-considered: []
chosen: ""
rationale: ""
consequences: []
risks: []
revisitable-when: []
superseded-by: ""               # [[dec-NNNN-...]] if this decision was replaced
---

# DEC-{NNNN}: {Decision Title}

> ADR (Architectural Decision Record) for: {one-sentence summary}.
>
> **Status:** {decision-status} · **Date:** {date} · **Owner:** {decision-owner}

---

## Context

<What triggered this decision? What constraints exist? What is at stake?>

## Options considered

### Option A — {name}
- Pros:
- Cons:
- Estimated cost / risk:

### Option B — {name}
- Pros:
- Cons:
- Estimated cost / risk:

### Option C — {name}
- Pros:
- Cons:
- Estimated cost / risk:

## Decision

**Chosen:** {chosen option, name}.

## Rationale

<Why this option won. Explicitly: which constraints does it satisfy, which trade-offs are accepted.>

## Consequences

What we lock in by accepting this decision:

- 
- 
- 

## Risks

What could go wrong if this decision turns out to be wrong:

- 
- 

## Revisit when

Conditions that should reopen this decision:

- 
- 

## Related

- [[claim-slug]] — claim this decision supports
- [[experiment-slug]] — experiment that surfaced this need
- [[meeting-slug]] — where this was discussed
- [[dec-NNNN-...]] — earlier related decision

## Update history
- YYYY-MM-DD: proposed
- YYYY-MM-DD: accepted by {decision-owner}
