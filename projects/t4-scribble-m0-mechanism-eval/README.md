# T4 Scribble–M0 Mechanism Council Evaluation

This example validates the upgraded research-agent control plane. It does not run the PET/CT experiment, train a model, query a server, produce a metric, or create a scientific result.

## What was tested

The example asks whether multiple independently owned roles can turn one cross-disciplinary intuition into a traceable chain:

```text
state-relative scribble hypothesis
→ implementable mechanism
→ falsifiable full-vs-no_M0 experiment
→ independent challenger
→ precommitted three-agent blind review
→ replicated defects
→ targeted repair
→ independent re-review
```

The frozen scientific contract is:

- `operation={ADD,REMOVE}`;
- `target={SAME,NEW}`;
- `scope={LOCAL,COMPLETE}`;
- six legal joints, with both `NEW_LOCAL` joints illegal;
- simple-first 17-channel P2T as the primary model;
- `full` versus exhaustive `no_M0` as the primary state-dependence comparison;
- cross-attention deferred to future work.

## What actually happened

- Six distinct contributors covered mathematical, domain, cognitive, curriculum, engineering, and causal views; a seventh agent compiled them.
- A separate challenger saw the frozen brief but not the council outputs.
- Three judges precommitted independently, reviewed anonymous X/Y candidates, and all preferred X/challenger.
- Four design defects on Y/council were independently replicated by all three judges.
- The first targeted repair closed only two defects and correctly received `FAIL`.
- A second minimal repair froze the remaining ambiguity-strata and training-schedule algorithms.
- An independent targeted re-review returned `PASS`: 4/4 defects closed, 6/6 regression checks true, and no fatal defect.

This is evidence that the local dispatch, review, and fail-closed repair contracts operated on one design-only example. It is not evidence that the scientific method is effective, novel, publication-ready, or superior.

## Council shape

The implemented council is a functional superset of the original five-specialist-plus-compiler brief:

```text
5 required scientific perspectives
+ 1 supplemental engineering contributor
+ 1 compiler
= 7 native agent roles
```

Do not describe it as an exact six-role council.

## Read in this order

1. [`TASKS-DASHBOARD.md`](TASKS-DASHBOARD.md) — current status and truth boundary.
2. [`inputs/frozen-brief.md`](inputs/frozen-brief.md) — immutable scientific input.
3. [`native-eval/reviews/reconciliation.json`](native-eval/reviews/reconciliation.json) — three-judge descriptive reconciliation.
4. [`native-eval/reviews/targeted-re-review.json`](native-eval/reviews/targeted-re-review.json) — preserved first re-review `FAIL`.
5. [`native-eval/candidates/council-repaired-r3.md`](native-eval/candidates/council-repaired-r3.md) — final prospective design candidate.
6. [`native-eval/reviews/targeted-re-review-r2.json`](native-eval/reviews/targeted-re-review-r2.json) — final independent targeted `PASS`.
7. [`native-eval/preflight/contract-dry-run.json`](native-eval/preflight/contract-dry-run.json) — CPU-only dry-run evidence and remaining real-execution blockers.

The full platform audit is at `research_agent_teams/_design/review/t4-research-agent-team-upgrade-2026-08-01.md`.
