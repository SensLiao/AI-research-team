---
name: venue-decide
kind: human-gate
disable-model-invocation: true
stage: VERIFY
reads: venue_readiness_verdict
writes: adr (the recorded publish/iterate/pivot decision)
---

# /venue-decide — Director Gate (human-only; model never invoked)

## Purpose

The `/venue-decide` gate is the **only publication decision point** in the system. It is
**human-only**: `disable-model-invocation: true` means the model is never invoked during this gate.
The director reads the `venue_readiness_verdict` produced by `area-chair-synthesizer` and decides
what to actually DO: publish / add experiments / change methods / pivot.

## Invariant (non-negotiable)

**The model never decides to publish (or to pivot).**

`area-chair-synthesizer` produces a *verdict* (`MEETS-BAR` / `BORDERLINE` / `NOT-YET` / `WRONG-PATH` /
`DEGRADED-REVIEW`), DERIVED mechanically by `venue_score.py` from the 7-dimension scores and the fired
reject-triggers — but it carries no `status` and authorizes no action. The decision to submit, to burn
more GPU on additional experiments, or to abandon the direction is the director's alone. This is the
crown-jewel red line: a more capable model still does not get to publish its own work or kill its own
direction.

The `/venue-decide` gate is the SOLE writer of the publish/iterate/pivot decision, and it is executed
only by the director.

## What the director does

1. Open the `venue_readiness_verdict` artifact at
   `runs/<run>/evidence/VERIFY/venue-readiness-verdict.artifact.json`.
2. Read the derived `verdict` and its derivation chain (dimension synthesis, unresolved reject-triggers,
   gaps→stage→fix list, strengths, shore-up items).
3. Decide ONE action, informed by (but not dictated by) the verdict:
   - **MEETS-BAR / BORDERLINE** → typically *submit* (optionally after the listed shore-up items).
   - **NOT-YET** → *add experiments / change methods* per the gap→stage list (route back to S2/S3/S4 —
     not a patch; the verdict names which stage owns each fix).
   - **WRONG-PATH** → *pivot* (back to the IDEATE `/idea-bet` gate or the GAP backlog — save the GPU
     and the writing time).
   - **DEGRADED-REVIEW** → *re-run the panel* (the reviews were not independent / all low-confidence;
     no publication decision is admissible yet).
4. Record the decision as an `adr`:
   - `decision_id`: a new `ADR-NNNN` identifier.
   - `question`: `"Publish / iterate / pivot for run <run_id> targeting <venue_id>?"`
   - `options`: `["SUBMIT", "ADD-EXPERIMENTS", "CHANGE-METHOD", "PIVOT", "RE-REVIEW"]` (or the subset the
     verdict makes admissible — always >= 2).
   - `chosen_option`: the chosen action.
   - `reason`: the director's rationale, citing the verdict's derivation where relevant.
   - `status`: `"approved"`.
   - `approved_by`: director identifier (e.g. `"director"`).
   - `approved_at`: ISO-8601 timestamp of approval.
   - Optional: `downstream_locked_artifacts` — e.g. `["venue_readiness_verdict"]`.
5. Write the `adr` to `runs/<run>/evidence/VERIFY/venue-decide.adr.json`.
6. Validate the written `adr` against `adr.schema.json` before proceeding.

## Hard rule on the verdict ↔ decision relationship

A fired, unresolved reject-trigger can NEVER yield a `MEETS-BAR` verdict — that is structural (the
`venue_readiness_verdict` schema's `allOf` and `venue_score.py` both enforce it). So the director can
never be shown a green "ready to publish" verdict while a real rejection risk is still open. The gate
does not relax that: it only chooses what to do given an honest verdict.

## Safety note

The options list always carries >= 2 admissible actions, so the director always has a real choice and
is never funnelled into "publish" by the machine. Publication is a human act recorded as an `adr`; the
machine's job ends at producing the honest, derived verdict.
