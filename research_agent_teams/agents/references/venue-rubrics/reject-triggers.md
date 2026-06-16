# Reject-Triggers (7 canonical + empirical top causes)

> These are the 7 structural reject-triggers from venue module §4.2. Any one of these firing
> means the venue-reviewer-persona CANNOT recommend Accept. The area-chair-synthesizer
> surfaces all unresolved triggers; any unresolved trigger forces verdict ≠ MEETS-BAR.
>
> `trigger_id` values below are the canonical IDs for `venue_profile.reject_triggers[]`.

---

## The 7 Structural Reject-Triggers

### RT-D4-BASELINE (Dimension: D4)

**Condition**: Weak, missing, or unfair baseline comparison; baselines not tuned to published
levels; comparison methods run at suboptimal hyperparameters; **test-set tuning or leakage**
(adjusted hyperparameters on test data).

**Why it's #1**: The most common real-world reject cause across all tiers. Reviewers can
programmatically check for this; it is easy to fire and hard to rebut.

**Venue-specific severity**:
- All tiers: fatal
- Nature Methods: named explicitly as top reject cause

**How to clear**: Show all baselines are from published literature and run at their published
hyperparameters (or re-optimized under identical compute budget). Confirm test set used ONLY
for final evaluation. Provide leakage-free protocol.

---

### RT-D1-OVERCLAIM (Dimension: D1)

**Condition**: A core claim in the paper is not sufficiently supported by the evidence presented.
The conclusion extends beyond what the experiments demonstrate.

**Venue-specific severity**: Hard gate at all tiers (D1 is always gating).

**How to clear**: Scope claims to what the experiments actually show; add a "limitations" section
acknowledging what is NOT shown; downgrade universal claims to "in our setting" claims.

---

### RT-D5-REPRO (Dimension: D5)

**Condition**: Code/data not publicly available and not reproducible from the manuscript alone.
"Available upon request" is no longer acceptable. An expert following the methods section cannot
reproduce the main results.

**Venue-specific severity**:
- Journals (Nature-family, TPAMI): **HARD GATE** — paper is rejected without appeal
- Conferences (NeurIPS, ICLR): major penalty; NeurIPS checklist failure
- TMI/MedIA: strong expectation; deficiency noted as major concern

**How to clear**: Deposit code in a public repository (GitHub, Zenodo, etc.) before submission.
Provide a README with exact commands to reproduce main results. Data: use public datasets or deposit
with a DOI; if private data, provide sample data and all preprocessing scripts.

---

### RT-D3-INCR (Dimension: D3)

**Condition**: The paper applies existing methods to a new dataset or domain without any
methodological advance. "New application of old method" without new insight.

**Venue-specific severity**:
- TMI/MedIA: **HARD GATE** (scope rejection — out of venue scope)
- Journal (Nature-family): **HARD GATE** (D2/D3 gating: conceptual advance required)
- CVPR/ICLR conf: **non-fatal** if D1/D4 strong and gains significant (discuss carefully)
- MICCAI: **non-fatal** for methodological papers if gain is real; fatal for pure application
  papers without clinical contribution

**How to clear**: Identify the genuine methodological novelty. If none exists, pivot to
`application-clinical` paper_type and ensure D7 clinical contribution is strong (only viable
at med/clinical venues). For conf: emphasize the insight gained, not just the application.

---

### RT-D1-PROOF (Dimension: D1)

**Condition**: Experimental design is invalid, proof is incorrect, or statistical analysis is
flawed (wrong test, p-hacking, underpowered study reported as definitive).

**Venue-specific severity**: Hard gate at all tiers. Distinct from RT-D1-OVERCLAIM —
this is about methodological invalidity, not scope of claim.

**How to clear**: Fix the experimental design; re-run with corrected statistics; use a
statistician if needed. This is often an unrecoverable issue requiring major revision.

---

### RT-D7-CLINICAL (Dimension: D7)

**Condition**: An `application-clinical` paper has only single-center data with no external
validation; or uses a clinically meaningless endpoint; or (for Nature Medicine) does not
include human subject evidence.

**Venue-specific severity**:
- `paper_type = application-clinical` at TMI/MedIA/Nature Medicine: **HARD GATE**
- `paper_type = methodological`: **NOT APPLICABLE** — D7 is off for methodological papers

**How to clear**: Add external/multi-center validation. If human data is not available,
reclassify as `methodological` and ensure the method is genuinely novel (then RT-D3-INCR check).
For Nature Medicine: human evidence is structurally required — no workaround.

---

### RT-ETHICS (Non-dimensional — forced check)

**Condition**: Ethics violation; duplicate/parallel submission; plagiarism detected; clinical trial
not registered; IRB approval missing for human subjects research.

**Venue-specific severity**: **ABSOLUTE REJECT at all venues** — not scoreable, not rebuttal-able.

**How to clear**: For ethics approval: obtain IRB before resubmission. For duplicate submission:
withdraw from one venue. Plagiarism: not correctable by revision.

---

## Empirical Top-Reject Causes (by frequency in published post-mortems)

These are the most commonly cited reject reasons across venue tiers, summarized from
reviewer guidelines and community post-mortems:

1. **Weak/unfair baseline** (D4) — fires RT-D4-BASELINE. Most common single cause.
2. **Test-set leakage or tuning** (D4) — sub-case of RT-D4-BASELINE; often covert.
3. **Overclaiming beyond data** (D1) — fires RT-D1-OVERCLAIM.
4. **Reproducibility failure** (D5) — fires RT-D5-REPRO; now enforced at journals.
5. **Incrementalism without insight** (D3) — fires RT-D3-INCR; lethal at journals and TMI/MedIA.
6. **Single-center clinical data** (D7) — fires RT-D7-CLINICAL for application-clinical.
7. **Invalid proof/stats** (D1) — fires RT-D1-PROOF; rare but absolute.

---

## Trigger → accept_condition interaction

The `accept_condition` in `venue_profile` always contains the clause:

```
... AND no reject-trigger fire
```

This means any fired trigger structurally blocks MEETS-BAR regardless of dimension scores.
The `area-chair-synthesizer` enforces this via the `allOf` derivation in `venue_readiness_verdict`.
