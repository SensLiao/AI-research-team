---
phase: 01-operated-ai-manuscript-authoring
plan: "06"
subsystem: independent-manuscript-review
tags: [blind-review, six-capability-panel, immutable-verdicts, submission-packaging, reviewer-separation]
requires: []
provides:
  - Blind factual, citation, and venue-style-LaTeX audit contracts
  - Separate blind domain-contribution, methods-reproducibility, and figure-table reviewer contracts
  - Exact six-capability independent review surface with receipt/hash isolation
  - Lossless director-facing submission-checklist packaging contract
affects: [manuscript-review, quality-reconciliation, submission-readiness, director-reporting, worker-roster]
tech-stack:
  added: []
  patterns: [one-capability-per-reviewer, blind receipt before visibility, open-finding abstention, reconciliation-only packaging]
key-files:
  created:
    - agents/manuscript-factual-auditor.md
    - agents/manuscript-citation-auditor.md
    - agents/manuscript-style-latex-auditor.md
    - agents/manuscript-submission-packager.md
    - agents/manuscript-domain-contribution-reviewer.md
    - agents/manuscript-methods-reproducibility-reviewer.md
    - agents/manuscript-figure-table-reviewer.md
  modified: []
key-decisions:
  - "Freeze exactly domain_contribution, methods_reproducibility, figure_table, factual, citation, and venue_style_latex as the six independent capability ids."
  - "Map exact capability ids through role contracts and scheduler receipts while retaining the existing coarse closed-schema reviewer roles."
  - "Represent abstention and unresolved science as open evidence-backed findings, never as a hidden PASS or prose-only caveat."
  - "Refuse a fabricated PDF identity when source-only review cannot satisfy the current closed verdict schema."
patterns-established:
  - "Blind freeze: each reviewer freezes one identity/receipt/hash-bound verdict before sibling or reconciliation visibility."
  - "Lossless packaging: the packager consumes only deterministic reconciliation and cannot soften minority findings or merge usability with readiness."
requirements-completed: [ORCH-01, AUDT-01, DELV-01, DELV-02]
coverage:
  - id: V1
    description: Six distinct one-capability roles cover domain, methods, figures, factual truth, citations, and venue/style-LaTeX review.
    requirement: ORCH-01
    verification:
      - kind: contract-integrity
        ref: agents/manuscript-domain-contribution-reviewer.md
        status: pass
    human_judgment: false
  - id: V2
    description: Each reviewer independently reopens authorized evidence and freezes a unique receipt/hash-bound verdict before sibling visibility.
    requirement: AUDT-01
    verification:
      - kind: contract-integrity
        ref: agents/manuscript-factual-auditor.md
        status: pass
    human_judgment: false
  - id: V3
    description: Structured reconciliation data is packaged losslessly into a human-first checklist with immutable evidence links.
    requirement: DELV-01
    verification:
      - kind: contract-integrity
        ref: agents/manuscript-submission-packager.md
        status: pass
    human_judgment: false
  - id: V4
    description: Daily usability and submission readiness remain separate, and advisory preferences cannot create or erase scientific truth.
    requirement: DELV-02
    verification:
      - kind: contract-integrity
        ref: agents/manuscript-style-latex-auditor.md
        status: pass
    human_judgment: false
duration: 11min
completed: 2026-07-21
status: complete
---

# Phase 01 Plan 06: Independent Review and Submission Packaging Contracts Summary

**Seven least-privilege contracts now define an exact six-capability blind review panel plus lossless human packaging, keeping authorship, independent judgment, deterministic reconciliation, and director decisions separate.**

## Performance

- **Duration:** 11 min
- **Started:** 2026-07-21T18:13:55+08:00
- **Completed:** 2026-07-21T18:24:05+08:00
- **Tasks:** 2
- **Files modified:** 7

## Accomplishments

- Added blind `factual`, `citation`, and `venue_style_latex` auditors that reopen frozen evidence, results, citations, venue rules, assets, and build facts rather than trusting generation conclusions.
- Added separate `domain_contribution`, `methods_reproducibility`, and `figure_table` expert reviewers with non-overlapping ownership and explicit unresolved-science handbacks.
- Required unique reviewer-instance identity, blind scheduler authorization, immutable contract/manuscript/scoped hashes, sibling isolation, explicit abstention, and frozen verdicts across all six capabilities.
- Classified fabricated evidence, unsupported claims/numbers, leakage, invalid comparisons, permission/path/secret defects, and false execution/PDF facts as hard findings while retaining presentation preferences as advisory.
- Added a submission packager that preserves every reconciled majority/minority finding, reports daily usability separately from submission readiness, and leaves submission decisions/actions to the director.

## Task Commits

1. **Task 1: Specify blind auditors and submission evidence packaging** - `1038f6c`
2. **Task 2: Specify domain, methods, and figure-table expert reviewers** - `e8b0202`
3. **Rule 2: Fail closed on source-only review schema mismatch** - `c3108cd`

## TDD-Style Verification

- **Task 1 RED:** The four-file blind/hash contract command failed before the base auditors and packager existed.
- **Task 1 GREEN:** The exact plan command passed after the four contracts were added.
- **Task 2 RED:** The three-file capability/receipt contract command failed before the expert reviewers existed.
- **Task 2 GREEN:** The exact plan command passed after all three expert contracts were added.
- **Panel audit:** An additional parser check proved exact set equality for the six capability IDs, provider-neutral reviewer metadata, blind receipts, author/sibling separation, explicit abstention, and source-only fail-closed behavior.
- **Regression boundary:** `python -m pytest tests/test_model_policy.py -q` passed 20 tests in 1.23s.
- The plan has `type: execute`, so each task received one implementation commit rather than separate TDD gate commits.

## Files Created

- `agents/manuscript-factual-auditor.md` - claim, numeric, split, uncertainty, and execution-truth audit.
- `agents/manuscript-citation-auditor.md` - exact source identity, entailment, contradiction, and bibliography closure audit.
- `agents/manuscript-style-latex-auditor.md` - official venue, anonymity/privacy, asset, cross-reference, and observed build/PDF audit.
- `agents/manuscript-submission-packager.md` - lossless structured checklist for deterministic Markdown rendering.
- `agents/manuscript-domain-contribution-reviewer.md` - problem fit, significance, novelty/collision, and claim-scope review.
- `agents/manuscript-methods-reproducibility-reviewer.md` - assumptions, protocol, leakage/fairness, materials, and reproducibility review.
- `agents/manuscript-figure-table-reviewer.md` - actual visual/table, provenance, numeric-cell, accessibility, and interpretation review.

## Decisions Made

- Exact capability coverage lives in immutable role constants and scheduler authorization receipts; the existing closed verdict schema's coarser reviewer roles remain compatibility mappings.
- `reviewer_instance_id` maps to `reviewer_identity.reviewer_id`; scheduler/scope authorization maps to `blind_read_receipt` and `scoped_inputs[].authorization_receipt_sha256`.
- Because the closed schema lacks direct abstention and unresolved-science fields, reviewers encode them as open evidence-backed findings with non-PASS disposition.
- The factual capability uses the schema's `NUMERIC_RESULT` role; domain and methods use `SCIENTIFIC`, citation uses `EXACT_CITATION`, figure/table uses `LATEX_ASSET`, and venue/style-LaTeX uses `VENUE`.
- Packaging reads deterministic reconciliation/quality state only, preserves minority findings, and never performs a second review or submission decision.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing Critical Functionality] Refused fake PDF identity for source-only review**

- **Found during:** Cross-task schema/contract review
- **Issue:** `manuscript_review_verdict` currently requires a PDF ref/hash and PDF scoped input even when no real PDF exists, making an unconditional schema-valid source-only verdict dishonest.
- **Fix:** All six reviewers now return an explicit contract-gap abstention and emit no fabricated schema-valid verdict until an honest source-only schema representation exists.
- **Files modified:** All six reviewer specifications
- **Commit:** `c3108cd` for the three Task 1 auditors; Task 2 included the same rule before `e8b0202`.

## Issues Encountered

The existing verdict schema has no direct `capability_id`, `abstention`, or `unresolved_science` field and uses coarse reviewer roles. The role contracts therefore bind exact capability through the scheduler receipt and map abstention/unresolved science to open findings. Runtime reducer enforcement remains deferred to the operated review plan.

`submission_checklist` and `tools/manuscript_renderer.py` are future structured-output/runtime contracts, not runnable artifacts created here. This plan defines the packager boundary only and does not claim operated rendering.

## User Setup Required

None.

## Next Phase Readiness

All six review capabilities and the packager are ready for later roster/graph wiring and deterministic reconciliation/runtime implementation. This execution did not add a registry entry, operated mode, renderer, submission action, or schema migration, and it did not begin Plan 01-07.

## Self-Check: PASSED

All seven role specifications, both exact plan integrity checks, and commits `1038f6c`, `e8b0202`, and `c3108cd` were verified on disk. `git diff --check` reported no whitespace errors in the plan-owned files or this summary.

---
*Phase: 01-operated-ai-manuscript-authoring*
*Completed: 2026-07-21*
