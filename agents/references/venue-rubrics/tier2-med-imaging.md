# Tier 2 — Medical Imaging Venues Rubric

> Venues: **MICCAI · TMI (IEEE Transactions on Medical Imaging) · MedIA (Medical Image Analysis)**
> Confidence: MEDIUM — MICCAI form changes annually; TMI/MedIA login-gated.
> **Login-state re-check REQUIRED before submission** (see _index.md).

---

## 1. paper_type two-track (the defining feature of tier 2)

The `paper_type` rocker is the most important dial for medical imaging venues:

| paper_type | D3 (novelty) | D7 (clinical) | Validation bar | Scope gate |
|------------|-------------|---------------|----------------|------------|
| `methodological` | NEW METHOD required (hard scope gate at TMI/MedIA) | OFF — small PoC / pilot acceptable | Technical novelty + small-sample feasibility | Strict at TMI/MedIA: no method advance → reject |
| `application-clinical` | Application of existing methods acceptable IF clinical contribution clear | ON — gating: multi-center / external validation / in-human evidence required | Clinical significance + external validation | Moderate: clinical contribution must be documented |

> **Key invariant**: `application-clinical` papers at TMI/MedIA must have external validation
> (multi-center or prospective). Single-center retrospective data = D7 reject-trigger.

---

## 2. MICCAI

- Review form: **paper_type-aware** — form prompts clinical-validity questions only if paper type is application.
- Score scale: **Accept / Reject** + meta-review score (varies by year; typically 1-5 or 1-6 internally).
- **D3 scope gate**: "Does the paper present methodological novelty? If the paper applies existing methods
  to a new dataset without methodological contribution, the scope gate fires." (method-first rule)
- **D4 emphasis**: Baselines must include standard state-of-the-art segmentation / detection / classification
  methods. Unfair comparisons are top reject cause.
- **D7 for application**: "Is the clinical endpoint meaningful? Is the evaluation on data representative of
  clinical deployment conditions?"
- **D5**: Code encouraged but not strictly required; data availability expected for reproducibility.
- **Rebuttal window**: ~1 week. Reviewers asked to reconsider after rebuttal.
- **Conference note**: MICCAI is selective (~30% acceptance). Single blind (authors visible to reviewers).

### MICCAI dimension calibration

```
D1: weight=0.20, gating=true
D2: weight=0.12, gating=false
D3: weight=0.20, gating=true  ← scope gate for methodological papers
D4: weight=0.24, gating=false
D5: weight=0.10, gating=false
D6: weight=0.10, gating=false
D7: weight=0.04, gating=false  ← ON only for application-clinical; gating=true when ON
```

---

## 3. TMI (IEEE Transactions on Medical Imaging)

- SIER framework: **Significance · Innovation · Evaluation · Reproducibility** — the 4 explicit criteria.
- Score scale: **Accept / Minor Revision / Major Revision / Reject** (tiered journal review).
- **D3 hard scope gate**: "Does the paper present a new method, algorithm, or substantial theoretical
  contribution? Papers that apply existing methods — even on important clinical problems — without
  methodological innovation fall outside scope." This is the most distinctive TMI rule.
- **D4**: "Is the evaluation rigorous? Are baselines from the peer-reviewed literature and well-tuned?
  Is the test set used only for final reporting?" — leakage is acute concern.
- **D5 (Reproducibility — SIER 'R')**: "Is the code publicly available or described in sufficient detail
  for an expert to reproduce?" — strong expectation, not strict gate, but major deficiency noted.
- **D7 for application**: "If this is a clinical application paper, is there multi-center or external
  validation? Does the study use clinically meaningful endpoints?" — gating for application-clinical.
- **D2 (Significance — SIER 'S')**: "Does this work advance the field significantly? Will others build on it?"

### TMI dimension calibration

```
D1: weight=0.18, gating=true
D2: weight=0.15, gating=false
D3: weight=0.22, gating=true  ← hard scope gate (no method advance → out of scope)
D4: weight=0.22, gating=false
D5: weight=0.12, gating=false  ← strong expectation, not strict gate
D6: weight=0.07, gating=false
D7: weight=0.04, gating=true   ← gating=true for application-clinical; OFF for methodological
```

---

## 4. MedIA (Medical Image Analysis — Elsevier)

- Editorial philosophy: **method-first, clinical applications welcome IF method is the point**.
- Closely mirrors TMI in scope gate; slightly more open to novel applications if the methods section is strong.
- Score: **Accept / Minor / Major / Reject** (Elsevier review workflow).
- **D3**: Similar TMI scope gate: "Is there a novel method or substantial algorithmic contribution?
  Dataset papers accepted if benchmark design is methodologically novel."
- **D4**: "Are baselines fairly chosen and well-implemented? Is the evaluation protocol reproducible?
  Are metrics appropriate for the task?"
- **D5 (Reproducibility)**: "Is code or implementation detail sufficient for reproduction by a
  competent researcher?" — expectation rising; major deficiency is comment-worthy.
- **D7**: Same two-track as TMI. Application-clinical papers need external validation.
- **MedIA note on D6**: Longer format accepted; clarity of the method pipeline is especially weighted.

### MedIA dimension calibration

```
D1: weight=0.18, gating=true
D2: weight=0.14, gating=false
D3: weight=0.22, gating=true  ← scope gate (method-first)
D4: weight=0.20, gating=false
D5: weight=0.13, gating=false
D6: weight=0.09, gating=false
D7: weight=0.04, gating=true   ← gating=true for application-clinical
```

---

## 5. Reject-triggers active at tier 2 (med)

All 7 standard triggers apply. Most commonly fired at medical imaging venues:
- **RT-D4-BASELINE** — unfair or untuned baselines; test-set leakage (most common real reject cause)
- **RT-D3-SCOPE** — no methodological novelty (scope gate at TMI/MedIA; lethal)
- **RT-D7-CLINICAL** — single-center only / no external validation (application-clinical papers)
- **RT-D5-REPRO** — code "available upon request" or reproduction impossible
- **RT-D1-OVERCLAIM** — results overclaimed relative to evidence

---

## 6. Anti-bias suppressors in force at tier 2

All 6 standard suppressors apply. Additional tier-2 note:
- Do NOT reject a methodological paper solely because the clinical dataset is small (PoC is acceptable
  if the methodological contribution is real).
- Do NOT treat "no external validation" as automatically fatal for methodological papers — only for
  application-clinical papers.
