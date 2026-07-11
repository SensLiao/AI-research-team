# scholar-evaluation — dimension-based scholarly assessment (machine skill, absorption wave 1)

> Adapted from K-Dense `scientific-agent-skills/scholar-evaluation` v1.0 (MIT) on 2026-06-10
> (their packaging of the ScholarEval framework — the same framework absorbed as
> `tools/idea_grounding.py` for ideas; THIS skill covers whole-work assessment).
> Stripped: figure plumbing, their scoring script. Absorbed: the 8-dimension rubric and the
> staged evaluation workflow — rewired to the machine's VERIFY panel (panel_review /
> venue_review artifacts; `venue_score.py` derives verdicts).

## Who uses this

verify_result / venue_readiness reviewer seats evaluating a synthesis, draft, or result bundle;
the area-chair-synthesizer structuring its meta-review.

## The 8 evaluation dimensions (absorbed)

1. **Problem formulation** — clarity/specificity of the RQ; significance; scope feasibility;
   contribution potential (map to the vault's rq/contribution registries when present).
2. **Literature grounding** — coverage, critical synthesis vs summary, gap identification,
   currency; missing-SOTA is the baseline-scout's lens, lineage errors the historian's.
3. **Methodology & design** — fit to RQ, rigor, reproducibility, limitations honesty (lean on
   `skills/scientific-critical-thinking.md` §1).
4. **Data & sources** — dataset appropriateness, splits/freezing discipline, provenance
   (journal_entry / parity artifacts are the machine's ground truth here).
5. **Analysis & interpretation** — method appropriateness, alternative explanations considered,
   results-claims alignment (claim-strength-calibrator territory).
6. **Results & findings** — presentation clarity, statistical rigor, visualization honesty
   (figure-vlm-critic), implications scoped to the evidence.
7. **Writing & presentation** — organization, clarity, accessibility (the AAAI clarity pass).
8. **Citations & references** — completeness, accuracy (citation_existence three-state check),
   balance; every external ref resolvable, every vault ref a real `[[slug]]`.

## Staged workflow (adapted)

1. **Scope first**: what kind of work (result bundle / synthesis / draft) and which dimensions
   apply; say so explicitly in your review.
2. **Dimension-by-dimension**: 2-3 specific strengths + 2-3 specific weaknesses each, every
   point anchored (file/section/table — the panel_review schema requires anchor + evidence).
3. **Score 1-5 per dimension** (5 = top-venue exemplary, 3 = adequate-with-issues, 1 = broken),
   with the asymmetric-cost rule: uncertain → score LOW (a wrongly-high score wastes a
   submission cycle; a wrongly-low one is recoverable).
4. **Synthesize**: 3-5 major strengths, 3-5 critical weaknesses, prioritized actionable fixes
   (each: what, where, how). Aggregate by ARGUMENT, not numeric mean (area-chair rule;
   H-Max anchoring when well-evidenced reviews disagree).
5. **Context modifiers**: early draft → conceptual issues first; submission-ready →
   comprehensive; venue-targeted → that venue's reject-triggers dominate.

## Boundaries (machine rules)

No verdict/meets_bar/accept field from any seat — `venue_score.py` derives readiness; the
director decides at /venue-pick and /venue-decide. Prestige is never a ground (anti-bias
suppressors); planted-error recall (`tools/review_calibration.py`) measures whether these
evaluations actually catch what they claim to catch.
