---
name: venue-pick
kind: human-gate
disable-model-invocation: true
stage: VERIFY
reads: venue_candidates
writes: adr (the recorded venue choice)
---

# /venue-pick — Director Gate (human-only; model never invoked)

## Purpose

The `/venue-pick` gate is the ONLY place a target venue is chosen for a piece of work. It is
**human-only**: `disable-model-invocation: true` means the model is never invoked during this
gate. The director reviews the ranked `venue_candidates` nominated by `venue-selector` (the B
path) and picks exactly ONE `venue_id` to target. The chosen venue then drives `venue-selector`'s
C path, which instantiates that venue's rubric into a `venue_profile` scorecard.

## Invariant (non-negotiable)

**The model never self-picks a venue.**

The `venue_candidates` schema is closed (`additionalProperties: false`) and deliberately contains
NO `selected`, `chosen`, `picked`, or `director_*` field. Any attempt by the model to inject a pick
into `venue_candidates` is structurally rejected by the schema. Choosing the publication arena is a
director decision (the operating-model red line — the same class as `/idea-bet` and `/venue-decide`),
not a model decision.

The `/venue-pick` gate is the SOLE writer of the venue choice, and it is executed only by the director.

## What the director does

1. Open the `venue_candidates` artifact at
   `runs/<run>/evidence/VERIFY/venue-candidates.artifact.json`.
2. Review the ranked candidates. Each carries: `tier`, `paper_type`, `hit_reason`, and the
   `deadliest_reject_trigger` (the one rejection risk most likely to sink the work at that venue).
3. Pick ONE `venue_id` to target — or decline all and re-scope.
4. Record the decision as an `adr`:
   - `decision_id`: a new `ADR-NNNN` identifier.
   - `question`: `"Which venue to target for run <run_id>?"`
   - `options`: one `"<venue_id> (<tier>/<paper_type>): <hit_reason>"` string per candidate, PLUS a
     standing `"HOLD: do not target any listed venue — re-scope or strengthen first"` option, ALWAYS
     appended. The HOLD option guarantees `options >= 2` (even a single-candidate list yields a valid
     adr) AND gives the director a real "none of these" choice — the human is never forced to pick a venue.
   - `chosen_option`: the `venue_id` and descriptor of the chosen venue (or the HOLD option).
   - `reason`: the director's rationale (strategic fit, deadline, audience, risk appetite, or any
     factor not captured by the candidate ranking).
   - `status`: `"approved"`.
   - `approved_by`: director identifier (e.g. `"director"`).
   - `approved_at`: ISO-8601 timestamp of approval.
   - Optional: `downstream_locked_artifacts` — e.g. `["venue_candidates"]`.
5. Write the `adr` to `runs/<run>/evidence/VERIFY/venue-pick.adr.json`.
6. Validate the written `adr` against `adr.schema.json` before proceeding.

## What happens after the pick

The approved `adr` signals which venue `venue-selector` should instantiate (the C path → `venue_profile`).
The blind-review panel (`venue-reviewer-persona` ×N, calibrated to that profile) then runs, and
`area-chair-synthesizer` derives the `venue_readiness_verdict`. The publish decision on that verdict is
a SEPARATE human gate, `/venue-decide`.

## Safety note

The standing **HOLD** option guarantees the `adr` `options` list always has >= 2 entries, so even a
single-candidate nomination yields a valid `/venue-pick` adr — and the director always has a real
"none of these, re-scope" choice. The human is structurally never forced to target a venue.
