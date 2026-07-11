# Rubric 7D — 7 Dimensions + 1-4 Anchors + ACCEPT/STRONG-ACCEPT Derivation

> The canonical 7-dimension rubric from venue module §4.1 and §4.3.
> Used by venue-reviewer-persona to score each dimension (1-4 scale, NeurIPS anchor).
> Used by venue-selector to populate `venue_profile.dimension_weights`.
> Used by area-chair-synthesizer to derive the verdict via `accept_condition`.

---

## Score scale

All dimensions use the **1-4 NeurIPS anchor scale**:

| Score | Label | Meaning |
|-------|-------|---------|
| 4 | Excellent | No significant weakness; exceeds typical standard for this venue |
| 3 | Good | Minor weaknesses; meets the standard for this venue |
| 2 | Fair | Significant weaknesses; below the standard; revision likely needed |
| 1 | Poor | Fundamental weakness; rejection likely even with revision |

---

## D1 — Soundness / Correctness

**What it measures**: Claims are supported by sufficient, valid evidence. Proofs are correct.
Experimental design is valid. Statistical treatment is appropriate.

| Score | Anchor |
|-------|--------|
| 4 | All core claims have strong, reproducible evidence. Proofs (if any) are correct and complete. Statistics are correct and well-powered. |
| 3 | Claims are well-supported. Minor proof gaps or underpowered sub-claims but main contribution holds. |
| 2 | One significant claim is weakly supported or relies on questionable evidence. Proof gap that could be fixed. |
| 1 | Core claim is unsupported or proof is incorrect. The paper's main contribution does not stand. |

**Gating**: YES — all tiers. A D1=1 always fires RT-D1-OVERCLAIM or RT-D1-PROOF.

---

## D2 — Significance / Impact

**What it measures**: The problem matters. Solving it will influence how others think or work.
Others will build on this result.

| Score | Anchor |
|-------|--------|
| 4 | Addresses a major open problem; result will change the field's direction or standard practice. |
| 3 | Clear importance; work will be cited and used as a baseline by others in the area. |
| 2 | Useful contribution but narrow; impact limited to a small sub-community. |
| 1 | Problem is not important or already solved in a clearly superior way. |

**Gating**: Journals (Nature-family) — YES (conceptual advance required). Conference — NO
(resolves with D3 via the OR condition). Medical imaging — NO for methodological; partially
for application-clinical.

---

## D3 — Originality / Novelty

**What it measures**: New method, new combination with real insight, new theoretical result,
or genuinely new evaluation framework. Not "same method, new dataset."

| Score | Anchor |
|-------|--------|
| 4 | Genuinely new idea or insight that reframes the problem or opens new directions. |
| 3 | Meaningful novelty — new combination, new application domain with non-trivial adaptation, or solid methodological improvement. |
| 2 | Incremental advance over directly-cited prior work; contribution is narrowly scoped. |
| 1 | Essentially same as published work; no new insight; straightforward application of known method. |

**Gating**: TMI/MedIA — YES (hard scope gate). Nature-family journals — YES (conceptual
advance gate). Conferences — NO (non-fatal if D1/D4 strong).

---

## D4 — Evaluation Rigor / Fairness

**What it measures**: Baselines are strong and fairly compared. No test-set tuning or leakage.
Ablation studies demonstrate each component's contribution. Metrics are appropriate. Dataset
coverage is sufficient.

| Score | Anchor |
|-------|--------|
| 4 | Comprehensive evaluation. All baselines from literature, well-tuned. No leakage. Ablation is thorough. Metrics appropriate. Multi-dataset validation where relevant. |
| 3 | Solid evaluation. Minor gaps (e.g., one missing ablation, one slightly outdated baseline) but main claims supported. |
| 2 | Notable gaps: weak baselines, unclear protocol, or concerning leakage risk. Evaluation is not convincing on its own. |
| 1 | Evaluation is fundamentally flawed: unfair baselines, test-set tuning evident, or metrics are inappropriate. |

**Gating**: Not a hard schema gate, but **#1 reject driver** — the highest weighted dimension.
A D4=1 almost certainly fires RT-D4-BASELINE.

---

## D5 — Reproducibility

**What it measures**: A competent expert in the field could reproduce the main results.
Code and data are publicly available (or manuscript is sufficient).

| Score | Anchor |
|-------|--------|
| 4 | Code in public repo with README; data publicly available; exact commands provided; all hyperparameters documented. |
| 3 | Code available but some setup friction; manuscript has sufficient detail for reproduction with effort. |
| 2 | No public code; manuscript has partial detail; reproduction requires guesswork. |
| 1 | "Code available upon request" or no implementation detail; reproduction not feasible. |

**Gating**: Nature-family journals — YES (hard gate). TPAMI — strong expectation. Conferences
(NeurIPS) — checklist item, not strict gate. Medical imaging (TMI/MedIA) — strong expectation.

---

## D6 — Clarity / Presentation

**What it measures**: The paper is clearly written. Method is understandable. Figures are
informative. Claims are precisely stated. Related work is fairly placed.

| Score | Anchor |
|-------|--------|
| 4 | Exemplary clarity. Method can be understood without external references. Figures directly support claims. Related work is comprehensive and fair. |
| 3 | Clear and readable with minor issues. A careful reader can follow the method. |
| 2 | Multiple clarity problems; method hard to follow; key figures are confusing; related work is incomplete. |
| 1 | Paper is not understandable. Major sections are unclear or contradictory. |

**Gating**: NO — medium weight, not a gate. A D6=1 may trigger ABS-2 check (is it really just
small fixable issues?).

---

## D7 — Clinical / Domain Validity

**What it measures**: Appropriate gold standard. Clinically meaningful endpoint. For
`application-clinical`: external validation, multi-center or prospective data, in-human
evidence where required.

| Score | Anchor |
|-------|--------|
| 4 | Multi-center / prospective data; clinically meaningful endpoint with regulatory-grade validation; external validation set with different demographics. |
| 3 | Single-center but large and representative; clinically relevant endpoint; reproducible protocol. |
| 2 | Limited clinical validity: single-center, small, or endpoint of unclear clinical meaning. |
| 1 | No clinical validation or endpoint is clinically meaningless; fundamentally insufficient for application claims. |

**Active only when**: `paper_type = application-clinical` AND `tier ∈ {med, journal}` (or Nature Medicine).
**D7 = N/A (weight=0, gating=false)** for all `methodological` papers and all conf-ML papers.

---

## Non-scoring mandatory checks (NeurIPS/ICML style)

These are not scored on the 1-4 scale but must be flagged if violated:

1. **Limitations section**: Is it present and substantive? Superficial "broader impact" boilerplate
   does not count. A missing limitations section should be flagged as a revision request, not scored.
2. **Ethics / dual-use**: Any human subjects research? Any potential for misuse? Ethics approval documented?
   Violation fires RT-ETHICS (hard reject, not a score).

---

## ACCEPT-condition (exact derivation rule)

```
ACCEPT requires ALL of:
  D1 >= 3
  AND D4 >= 3
  AND (D3 >= 3 OR D2 >= 3)
  AND no reject-trigger fire
  AND (tier == "journal" => D5 >= 3)
  AND (paper_type == "application-clinical" => D7 >= 3)
```

Note: `D1 >= 3 AND D4 >= 3` is the soundness+fairness floor; the OR on D3/D2 means
either novelty or significance must be clear.

## STRONG-ACCEPT requires additionally:

```
  D1 == 4
  AND D4 == 4
  AND (D2 == 4 OR D3 == 4)
  AND D5 >= 3
```

---

## BORDERLINE condition

```
  All mandatory conditions met EXCEPT exactly one non-gating dimension is 2
  (e.g. D6 = 2, or D5 = 2 at conf where D5 is not gating)
```

If TWO or more non-gating dimensions are below threshold, verdict is NOT-YET or WRONG-PATH
depending on which dimensions are affected.

---

## score → verdict decision table

| D1 | D4 | D3 or D2 | Trigger? | Tier/type checks | Verdict |
|----|----|-----------|---------:|-----------------|---------|
| >=3 | >=3 | at least one >=3 | None | All pass | MEETS-BAR |
| >=3 | >=3 | at least one >=3 | None | Journal: D5>=3; Clin: D7>=3 | MEETS-BAR |
| >=3 | >=3 | at least one >=3 | None | One non-gating dim = 2 | BORDERLINE |
| Any | Any | Any | FIRED | Any | NOT-YET or WRONG-PATH (never MEETS-BAR) |
| <3 (gating) | Any | Any | None | Any | NOT-YET / WRONG-PATH |
| Any | <3 (#1 driver) | Any | None | Any | NOT-YET (usually) |
| Multiple gating dims <=2, D3<3 AND D2<3 | | | Any | Any | WRONG-PATH (structural weakness) |
