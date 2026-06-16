# AAAI-26 staged criterion rubric (absorption wave 1)

> Source pattern: the AAAI-26 AI Review Pilot (arXiv 2604.13940) — five-criterion STAGED review
> with a self-critique pass, validated on 22,977 real submissions. Absorbed as the pass
> structure for `venue-reviewer-persona` (§2b) and the criterion taxonomy for
> `tools/review_calibration.py` (SPECS-lite planted-error recall). This file is rubric
> CONTENT — the protocol lives in the persona card; the calibration math lives in the tool.

## The five passes (run in order; one criterion per pass; never mix)

### Pass 1 — clarity
- Is every term defined before use? Are the method figures self-contained?
- Can a competent reader reconstruct WHAT was done without guessing?
- Findings look like: undefined symbol, contradictory notation, figure/text mismatch,
  missing problem statement.

### Pass 2 — novelty
- What EXACTLY is new relative to the cited prior work — mechanism, setting, scale, or claim?
- Is "first to X" scoped honestly? (Check against the sub-domain-historian's lineage when present.)
- A new combination of existing techniques IS valid novelty (anti-bias suppressor applies);
  the finding is when the delta is misstated, not when it is small-but-honest.

### Pass 3 — soundness
- Do the experiments support the claims at the claimed strength?
- Leakage, unfair baselines, test-set tuning, wrong metric aggregation, missing variance,
  cherry-picked conditions. Open the eval code when available — never trust prose alone.

### Pass 4 — significance
- Who, concretely, would change what they do because of this result?
- Inflated-impact findings: claims that generalize beyond the evidenced scope, "real-world
  ready" without deployment evidence, benchmark deltas inside noise presented as advances.

### Pass 5 — reproducibility
- Could a third party re-run this: data availability, splits, seeds, configs, compute budget,
  code state? Missing ANY of {split definition, seed policy, config provenance} is a finding.

## The self-critique pass (mandatory, after the five)

Re-read your OWN findings as a hostile meta-reviewer:
- delete findings with no evidence anchor;
- merge duplicates that surfaced in two passes;
- check each BLOCK-severity finding: would a fair rebuttal dissolve it? If yes, downgrade.
The AAAI pilot's measured quality gain came mostly from this pass — do not skip it.

## Calibration hook

`tools/review_calibration.py` seeds known per-criterion errors into fixture copies and scores
the panel's planted-error recall (`calibration_report` artifact). When a prompt/model change
drops recall on a criterion, that change regressed — fix the prompt, never relax the harness.
