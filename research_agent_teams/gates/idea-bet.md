---
name: idea-bet
kind: human-gate
disable-model-invocation: true
stage: IDEATE
reads: idea_backlog
writes: adr (the recorded bet)
---

# /idea-bet — Director Gate (human-only; model never invoked)

## Purpose

The `/idea-bet` gate is the ONLY place in the M3-a spine where a research idea is selected
for pursuit. It is **human-only**: `disable-model-invocation: true` means the model is never
invoked during this gate. The director reviews the ranked `idea_backlog` menu produced by
`feasibility-reranker` and picks exactly ONE `idea_id` to bet on.

## Invariant (non-negotiable)

**The model never self-bets.**

The `idea_backlog` schema is closed (`additionalProperties: false`) and deliberately contains
NO `selected`, `chosen`, `bet`, `winner`, or `director_*` field. Any attempt by the model to
inject a pick into `idea_backlog` is structurally rejected by the schema.

The `/idea-bet` gate is the SOLE writer of the bet, and it is executed only by the director.

## Presentation (AskUserQuestion — director lock 2026-06-16)

When the orchestrator pauses at this gate it surfaces the ranked `idea_backlog` as a Claude Code
**AskUserQuestion** (selectable options), not a prose menu: one option per ranked idea
(`IDEA-xxx: <summary> (rank N)`) PLUS the standing **PIVOT** option ("none of these — re-scope the
direction"). The director clicks + submits; the orchestrator then records the pick as the adr below.
Presentation only — the invariant stands: the model NEVER self-bets (`disable-model-invocation`; the
`idea_backlog` schema has no `selected`/`chosen` field). See research-orchestrator SKILL §0.5.

## What the director does

1. Open the `idea_backlog` artifact at
   `runs/<run>/evidence/IDEATE/idea-backlog.artifact.json`.
2. Review the ranked ideas (rank 1 = highest feasibility score).
3. Pick ONE `idea_id` to bet on.
4. Record the decision as an `adr` (Architecture/Decision Record):
   - `decision_id`: a new `ADR-NNNN` identifier.
   - `question`: `"Which idea to bet on for run <run_id>?"`
   - `options`: one `"<idea_id>: <summary>"` string per idea in the backlog, PLUS a standing
     `"PIVOT: do not bet on any listed idea — re-scope the direction"` option, ALWAYS appended.
     The PIVOT option guarantees `options >= 2` (so even a single-idea backlog yields a valid adr)
     AND gives the director a real "none of these" choice — the human is never forced to bet.
   - `chosen_option`: the `idea_id` and summary of the chosen idea.
   - `reason`: the director's rationale for the pick (strategic fit, resource constraints,
     domain priority, or any other factor not captured by the feasibility rubric).
   - `status`: `"approved"`.
   - `approved_by`: director identifier (e.g. `"director"`).
   - `approved_at`: ISO-8601 timestamp of approval.
   - Optional: `downstream_locked_artifacts` — list any artifact_types that are now
     locked by this decision (e.g. `["idea_backlog"]`).
5. Write the `adr` to `runs/<run>/evidence/IDEATE/idea-bet.adr.json`.
6. Validate the written `adr` against `adr.schema.json` before proceeding.

## ADR shape (example)

```json
{
  "decision_id": "ADR-0100",
  "question": "Which idea to bet on for run r-20260609-001?",
  "options": [
    "IDEA-001: Contrastive pre-training on unlabelled CT volumes to close the annotation gap",
    "IDEA-002: Cross-modal transfer from natural images to medical scans via domain-adversarial training",
    "PIVOT: do not bet on any listed idea — re-scope the direction"
  ],
  "chosen_option": "IDEA-001: Contrastive pre-training on unlabelled CT volumes to close the annotation gap",
  "reason": "Lower compute demand and public data availability; aligns with Q3 GPU budget ceiling.",
  "status": "approved",
  "approved_by": "director",
  "approved_at": "2026-06-09T10:00:00Z",
  "downstream_locked_artifacts": ["idea_backlog"]
}
```

## What happens after the bet

The approved `adr` is the signal that IDEATE is complete and the spine may proceed.
The orchestrator reads the `chosen_option` field to route the selected idea into the
DESIGN stage (e.g. for `rq-architect` to decompose into a hypothesis chain).

## Safety note

The standing **PIVOT** option guarantees the `adr` `options` list always has >= 2 entries, so even a
single-idea backlog yields a valid `/idea-bet` adr — and the director always has a real "none of these,
re-scope" choice. The human is structurally never forced to bet on a thin menu.
