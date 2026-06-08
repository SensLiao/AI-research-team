# Anti-Bias Suppressors (6 not-valid-grounds for rejection)

> These 6 suppressors encode the `not-valid-grounds` for rejection that are explicitly
> documented in venue guidelines (CVPR/ICLR/NeurIPS/ICML/Nature-family). They are loaded
> into `venue_profile.anti_bias_suppressors[]` and stated to every reviewer persona.
>
> A reviewer persona MUST NOT use any of these as the **sole** reason to recommend rejection.
> They may still be part of a balanced critique — the constraint is "sole reason".

---

## The 6 Anti-Bias Suppressors

### ABS-1: Did not beat SOTA

**Statement**: "This paper did not beat state-of-the-art on all benchmarks" is NOT a valid
sole rejection reason.

**Rationale**: Documented in NeurIPS Reviewer Guide and ICLR/CVPR guidelines. A paper may
be a genuine contribution — new method, new insight, new evaluation framework — without
outperforming every prior result. Especially relevant when SOTA comparison is cherry-picked
or uses private/inaccessible data.

**When it IS valid (as part of balanced critique)**: If the ONLY claim of the paper is
"outperforms SOTA" and that claim is not supported. Then D1 (not this suppressor) fires.

---

### ABS-2: Small fixable issues

**Statement**: "The paper has small, easily-fixable issues (typos, minor presentation gaps,
small missing ablation)" is NOT a valid sole rejection reason.

**Rationale**: NeurIPS, ICML, and ICLR guidelines explicitly note that minor presentation
issues should not drive rejection; they should drive revision requests or weak-accept with
author note.

**When it IS valid**: A paper with pervasive clarity failures (D6 = 1 across the board,
method incomprehensible) is a legitimate concern — that is D6 failure, not this suppressor.

---

### ABS-3: Missing arXiv preprint citation

**Statement**: "This paper does not cite / does not surpass [arXiv preprint X]" is NOT a
valid sole rejection reason.

**Rationale**: CVPR/ICCV and ICLR guidelines explicitly protect against this. Unpublished
arXiv preprints are not required comparisons; published peer-reviewed work is the standard.
A reviewer cannot demand comparison to their own or others' concurrent arXiv submissions.

**When it IS valid**: If a published peer-reviewed paper (not arXiv) is directly relevant
and not cited — that is a legitimate concern under D1/D6 (completeness of related work).

---

### ABS-4: Rebuttal demand for large new experiments

**Statement**: "Reject because the authors did not run the large additional experiment I
requested in the review (and there was no time to do so)" is NOT a valid sole rejection reason.

**Rationale**: ICLR review guidelines explicitly state that reviewers should not demand
experiments that cannot be completed in the rebuttal period, and should not penalize
authors for not complying. A reviewer who demands an extra GPU-month experiment in a 1-week
rebuttal and then maintains rejection is acting against guidelines.

**When it IS valid**: If an experiment is trivially fast AND the paper's core claim hinges
on it AND the authors refuse to address the concern even in rebuttal — then the concern may
feed into D1/D4 via a legitimate argue-not-answer pattern.

---

### ABS-5: Just a combination of known techniques

**Statement**: "This is just a combination of known techniques / not a new idea, just
assembling existing parts" is NOT a valid sole rejection reason.

**Rationale**: NeurIPS and CVPR review guidelines explicitly state that a novel combination
of known techniques constitutes legitimate originality if the combination yields new insights
or capabilities. "Known parts assembled cleverly" is a recognized form of novelty (D3).

**When it IS valid**: If the combination is trivial, yields no new insight, and is presented
as a grand breakthrough without supporting evidence — that is RT-D3-INCR (at journals) or
D3-weak at conf. But combination alone is not a rejection reason.

---

### ABS-6: Acceptance-rate quota filling

**Statement**: "I am giving this a low score to help the committee hit the acceptance-rate
target" or "We already have enough papers on this topic" is NOT a valid rejection reason.

**Rationale**: ICML and NeurIPS guidelines explicitly state that papers must be evaluated
on their scientific merit, not on venue capacity or topic distribution. Quota-based scoring
is explicitly flagged as biased reviewing.

**When it IS valid**: Never. There is no scientific version of this rationale.

---

## Using suppressors in venue_profile

When `venue-selector` instantiates a `venue_profile`, it populates
`anti_bias_suppressors` with short identifier strings referencing these suppressors,
for example:

```json
"anti_bias_suppressors": [
  "ABS-1: did-not-beat-SOTA is not sole grounds",
  "ABS-2: small fixable issues are not sole grounds",
  "ABS-3: missing arXiv citation is not sole grounds",
  "ABS-4: rebuttal demand for large experiments not penalisable",
  "ABS-5: known-technique combination is legitimate novelty",
  "ABS-6: no quota-based scoring"
]
```

Each reviewer persona restates the relevant suppressors before scoring to activate
the anti-bias guardrail. The adversarial persona is specifically tasked with checking
that OTHER reviewer personas are not violating suppressors.
