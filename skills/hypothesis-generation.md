# hypothesis-generation — structured hypothesis formulation (machine skill, absorption wave 1)

> Adapted from K-Dense `scientific-agent-skills/hypothesis-generation` v1.0 (MIT) on 2026-06-10.
> Stripped: LaTeX report template, mandatory figures, bio-vertical search routes. Absorbed: the
> 8-step workflow and the 7-criterion hypothesis quality rubric — rewired to the machine's
> IDEATE ring (hypothesis-generator / idea-evolver workers) and its artifact contracts
> (hypothesis_set: falsifiable_prediction REQUIRED; evidence_ref REQUIRED).

## Who uses this

IDEATE workers (hypothesis-generator, idea-evolver) and the new_direction / ideate_ring modes.

## The 8-step workflow (adapted)

1. **Understand the phenomenon** — restate the gap (from `gap_classification`) precisely: what
   is observed, what is unexplained, in which scope; what is known (vault, by `[[slug]]`) vs
   genuinely open.
2. **Search before inventing** — vault recall + the sanctioned live channel
   (`inbox/search-results.json` / `tools/paper_search.py`). A hypothesis that ignores a
   published answer is dead on arrival; the grounding signal
   (`no_semantic_neighbor_found`) is evidence, not a license to skip the search.
3. **Synthesize the evidence** — established mechanisms that may apply, conflicting findings,
   analogous systems in adjacent fields (cross-domain transfer is a first-class gap type here).
4. **Generate COMPETING hypotheses** — 3-5 per gap, mechanistic (not descriptive),
   DISTINGUISHABLE from each other; vary the level of explanation (data / loss / architecture /
   optimization / evaluation for ML work). Strategies: transplant a mechanism from an analogous
   system; invert an assumption (contrarian gaps); combine known mechanisms novelly.
5. **Evaluate against the 7 criteria** — testability, falsifiability, parsimony, explanatory
   power, scope, consistency with established results, novelty. State each hypothesis's
   weakest criterion explicitly — hiding it just moves the failure to the review panel.
6. **Design the test** — what experiment discriminates between the competitors? (comparisons,
   controls, datasets, metrics — feeds `design_experiment` downstream).
7. **Formulate testable predictions** — the machine's hard rule: every
   `falsifiable_prediction` names a concrete metric + numeric threshold + dataset/condition,
   and states what result would FALSIFY it. "Improves accuracy" is schema-rejected by review.
8. **Emit the structured artifact** — `hypothesis_set` entries with `evidence_ref` to real
   GAP-ids / `[[slug]]`s; ideas derived from hypotheses carry `from_hypothesis_ref`. No
   self-bet anywhere: ranking is the tournament's job, the bet is the director's (/idea-bet).

## Quality bar (absorbed + machine-hardened)

- Mechanism over correlation: a hypothesis explains WHY, not just THAT.
- Each competing hypothesis must be falsifiable by an experiment the director could run next
  quarter (feasibility triple honest: compute / data / time).
- Calibration caveat (novelty-scorer card): plausible rationale ≠ accurate score; LLM-favored
  "novel" ideas skew less feasible — the feasibility signal and the human bet carry the
  decision, never your enthusiasm.
