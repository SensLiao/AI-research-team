# scientific-critical-thinking — rigor evaluation frameworks (machine skill, absorption wave 1)

> Adapted from K-Dense `scientific-agent-skills/scientific-critical-thinking` v1.1 (MIT) on
> 2026-06-10. Stripped: figure plumbing, clinical/GRADE bio-emphasis (kept as named frameworks
> only). Absorbed: the methodology-critique, bias-detection, and statistical-evaluation
> checklists — rewired as WORKING MATERIAL for this machine's judgment seats
> (scientific-critic, adversarial-reviewer, methodology-reviewer, venue personas,
> result-sanity-checker prompts).

## Who uses this

VERIFY-stage reviewer seats and ANALYZE-stage auditors. These checklists structure YOUR reading;
verdict-shaped outputs still go through the deterministic gates (panel_review / venue_review
schemas; `venue_score.py` derives meets-bar — never you).

## 1. Methodology critique checklist

- **Design fit**: can this design support the causal claim being made? Experimental vs
  observational justified? Comparison groups adequate?
- **Validity x4**: internal (randomization/confounding/selection/attrition), external
  (does the benchmark setting match the claimed application?), construct (do the metrics
  measure the claimed property — e.g. Dice for continuity claims is a construct mismatch),
  statistical-conclusion (power, assumptions, test choice).
- **Control discipline**: in ML terms — seeds fixed?, splits frozen before training?, identical
  preprocessing across compared methods?, tuning budget equalized? (the machine's DESIGN
  auditors enforce these; YOUR job is catching the ones the artifacts cannot see).
- **Measurement quality**: metric implementation canonical (`metric-implementation-auditor`)?,
  aggregation correct?, multiple metrics triangulating or one cherry-picked?

## 2. Bias detection sweep (run all five families)

1. **Researcher-cognitive**: confirmation bias (only supporting findings highlighted),
   HARKing (hypothesis after results), cherry-picking, missing preregistration/protocol.
2. **Selection**: unrepresentative benchmark choice, dataset survivorship, differential
   exclusion of hard cases.
3. **Measurement**: observer/instrument bias — eval code written by the method's authors with
   method-favoring defaults; test-time augmentation only for "ours".
4. **Analysis**: p-hacking, outcome switching, subgroup fishing without correction, selective
   reporting (planned-vs-reported comparison).
5. **Confounding**: what third variable could produce the delta? (hardware, library version,
   training budget, data version — the machine's parity/journal artifacts are your evidence).

## 3. Statistical evaluation checklist

- Power/sample size: significant results from tiny samples = inflated-effect flag.
- Test appropriateness + assumption checks; paired vs independent matched to design.
- Multiple comparisons corrected? primary vs exploratory outcomes distinguished?
- P-value discipline: non-significance ≠ no effect; significance ≠ practical importance;
  suspicious clustering just below .05.
- Effect sizes + CIs reported, interpreted in-domain.
- Missing data: how much, what mechanism, how handled.
- Modeling: overfit (no cross-validation), extrapolation, leakage via preprocessing.
- Classic pitfalls: correlation-as-causation, regression to the mean, base-rate neglect,
  Texas sharpshooter, Simpson's paradox.

## 4. Claim evaluation discipline (the machine's framing)

For every claim: state the claim → list the evidence FOR (with loci) → list what would
FALSIFY it → check whether the falsifier was looked for → grade support honestly. A claim
whose falsifier was never tested is "supported", never "validated". When uncertain, say
uncertain — calibrated doubt outranks confident error (the review_calibration harness measures
exactly this).
