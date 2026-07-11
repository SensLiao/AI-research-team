# Tier 1 — Top ML Conferences Rubric

> Venues: **NeurIPS · ICML · ICLR · CVPR · ICCV · ECCV**
> Confidence: HIGH — sourced from public reviewer guidelines.
> Login-state re-check: not required (public).

---

## 1. Dimension weights (conf defaults)

| Dim | Name | Weight | Gating? | Notes |
|-----|------|--------|---------|-------|
| D1 | Soundness/correctness | HIGH | Hard gate (all tiers) | Claims must have sufficient evidence; proofs/experiments must hold |
| D2 | Significance/impact | MEDIUM | No — resolved jointly with D3 | Problem must matter; others must build on it |
| D3 | Originality/novelty | HIGH | No (CVPR/ICLR: non-fatal with strong D1/D4) | New method OR new combination with new insight; not "same method, new dataset" |
| D4 | Evaluation rigor/fairness | HIGHEST | Hard gate — #1 reject driver | Strong fair baselines; no test-set tuning; ablation; right metrics; enough data |
| D5 | Reproducibility | MEDIUM | Scored, not gating | Code/data encouraged; NeurIPS checklist since 2020 |
| D6 | Clarity/presentation | MEDIUM | No | Writing, figures, readability |
| D7 | Clinical/domain validity | OFF | N/A | Only for med-imaging / Nature Medicine |

**paper_type = `application-clinical`**: rarely used for conf-ML; if used, D7 scored but not gating.

---

## 2. Per-venue dimension anchors

### NeurIPS

- Score scale: **1-10** (Reject=1-3; Borderline=4-5; Accept=6-7; Strong Accept=8-10)
- **D3 novelty**: "Originality: Are the problems or approaches novel? Is this a novel combination of
  familiar techniques? Is it clear how this work differs from previous contributions? Are previously
  published papers by the authors, if any, clearly acknowledged?" (NeurIPS Reviewer Guide)
- **D4 evaluation**: "Experimental validation: Is the validation thorough and insightful? Are the
  experiments well-designed? Are the results statistically significant?"
- **D1 quality**: "Is the paper technically sound?" — core soundness question.
- **Checklist** (NeurIPS 2020+): Limitations, Societal Impact, Code submission — not scored but required.
- **Anti-leaderboard**: Explicitly states reviewers should not reject solely because SOTA is not beaten
  if the contribution is otherwise clear.

### ICML

- Score scale: **1-6** (Strong Reject=1; Reject=2; Weak Reject=3; Weak Accept=4; Accept=5; Strong Accept=6)
- **D4 emphasis**: "Is the evaluation sound and comprehensive? Are baselines fair and well-tuned?"
- **D3 anchor**: "Originality/novelty: New application areas, problem formulations, or algorithmic
  approaches count. Combinations of known ideas must have new insights."
- **Argument-based synthesis**: "Reviewers should not simply average scores; they should resolve
  disagreements by argument." (ICML Review Guidelines — this is the not-take-mean mandate)
- **Pre-commitment**: Reviewers asked to commit to standards before reading; changes require justification.

### ICLR

- Score scale: **1-10** (1=strong reject; 10=strong accept); publicly visible on OpenReview.
- **D4 fairness**: "Are baselines from the published literature? Are they properly tuned? Is the
  test set only used for final evaluation?"
- **D3**: "Is the claimed contribution new? Are there papers in the bibliography that actually make the
  same contribution?"
- **Confidence**: 1-5 scale (1=unsure; 5=expert). Calibration expected.
- **Rebuttal**: Authors may respond; reviewers MUST re-read and state whether recommendation changes.
  Not changing after a substantive rebuttal = poor practice. (Key anti-anchoring rule.)
- **Anti-arXiv bias**: Do not reject because a preprint was not cited as a published peer-reviewed work.

### CVPR / ICCV / ECCV

- Score scale: varies by year but typically **1-5 or 1-6**.
- **D3 novelty for CVPR/ICCV**: "If the paper is a new application of known techniques, is the
  application sufficiently non-trivial? Incremental work on a well-studied problem is not a rejection
  reason alone if the gains are significant."
- **D4**: "Experiments: Are comparisons made against baselines that are fair and appropriately tuned?
  Are there ablations demonstrating each component's contribution?"
- **ECCV community note**: "Authors should be compared to the best published results on standard
  benchmarks, not arXiv preprints." (anti-arXiv as mandatory comparison protection)
- **Limitations section**: Expected in camera-ready; reviewers should not penalise for honest limitations.

---

## 3. Reject-triggers active at tier 1 (conf)

All 7 standard triggers apply. Most commonly fired:
- **RT-D4-BASELINE** — weak/unfair baseline; test-set tuning / leakage (most common real reject cause)
- **RT-D1-OVERCLAIM** — claim not supported by evidence
- **RT-D3-INCR** — purely incremental (but note: at conf, non-fatal if D1/D4 strong; becomes fatal at journal)
- **RT-D7-SCOPE** — N/A at conf (D7 is off)

---

## 4. Anti-bias suppressors in force at tier 1

All 6 standard suppressors apply. Explicitly noted in public guidelines for NeurIPS/ICLR/CVPR:
- Do NOT reject solely because SOTA not beaten
- Do NOT reject solely because of missing arXiv preprint citation
- Do NOT demand large extra experiments in rebuttal and then penalise for not doing them
- "Just a combination" is NOT a rejection reason if the combination has insight

---

## 5. Overall dimension calibration (conf typical)

```
D1: weight=0.22, gating=true
D2: weight=0.12, gating=false
D3: weight=0.18, gating=false
D4: weight=0.28, gating=false  ← highest weight
D5: weight=0.10, gating=false
D6: weight=0.10, gating=false
D7: weight=0.00, gating=false  ← OFF
```

> These are representative defaults for `venue-selector` to instantiate. The agent should
> adjust based on venue-specific emphasis (e.g. NeurIPS D5 weight slightly higher after
> 2020 checklist; CVPR D6 slightly higher for vision clarity standards).
