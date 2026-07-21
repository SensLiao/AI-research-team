---
phase: 01-operated-ai-manuscript-authoring
plan: "02"
subsystem: delivery-contracts
tags: [json-schema, latex, asset-provenance, quality-gates, blind-review]
requires: []
provides:
  - Receipt-derived manuscript compiler truth
  - Immutable-input and run-owned figure/table provenance
  - Separate daily-usability and submission-readiness states
  - Frozen-input independent blind-review verdicts
affects: [manuscript-build, manuscript-assets, quality-audit, manuscript-review, delivery]
tech-stack:
  added: []
  patterns: [Draft 2020-12 closed objects, receipt-bound terminal states, dual-axis delivery status]
key-files:
  created:
    - schemas/manuscript_build_receipt.schema.json
    - schemas/manuscript_asset_manifest.schema.json
    - schemas/manuscript_quality_report.schema.json
    - schemas/manuscript_review_verdict.schema.json
    - tests/test_manuscript_delivery_schemas.py
  modified: []
key-decisions:
  - "Only COMPILED may expose a nonempty PDF fact, and it must carry source, process, log, recorder, and PDF hashes."
  - "Asset outputs are run-owned CREATE_NEW records whose immutable inputs and permissions remain explicit."
  - "Daily usability and strict submission readiness are derived from separate finding effects."
  - "Review verdicts require independent identity, blind authorization, and frozen contract/manuscript/PDF hashes."
patterns-established:
  - "Terminal-state exclusivity: conditional schemas require and forbid state-specific facts."
  - "Status calibration: advisory findings cannot manufacture BLOCK and submission-only hard deficits need not hide readable work."
requirements-completed: [OPER-02, LATX-02, ASST-01, AUDT-01, DELV-02, VERI-04]
coverage:
  - id: D1
    description: Compiled, missing-toolchain, and failed-build states require mutually consistent receipt facts and reject false PDF claims.
    requirement: LATX-02
    verification:
      - kind: unit
        ref: tests/test_manuscript_delivery_schemas.py
        status: pass
    human_judgment: false
  - id: D2
    description: Every visible asset requires immutable sources, run-owned output, render or external provenance, permission, claims, results, and accessibility text.
    requirement: ASST-01
    verification:
      - kind: unit
        ref: tests/test_manuscript_delivery_schemas.py
        status: pass
    human_judgment: false
  - id: D3
    description: Hard and advisory findings deterministically derive four daily states while submission readiness remains a separate strict axis.
    requirement: DELV-02
    verification:
      - kind: unit
        ref: tests/test_manuscript_delivery_schemas.py
        status: pass
    human_judgment: false
  - id: D4
    description: Review verdicts are bound to frozen contract, manuscript, PDF, reviewer identity, blind-read receipt, and authorized input slices.
    requirement: OPER-02
    verification:
      - kind: unit
        ref: tests/test_manuscript_delivery_schemas.py
        status: pass
    human_judgment: false
  - id: D5
    description: Negative paths reject unsafe refs, fabricated build facts, ambiguous asset overwrites, advisory escalation, and unbound review evidence.
    requirement: VERI-04
    verification:
      - kind: unit
        ref: tests/test_manuscript_delivery_schemas.py
        status: pass
    human_judgment: false
duration: 15min
completed: 2026-07-21
status: complete
---

# Phase 01 Plan 02: Auditable Manuscript Delivery Contracts Summary

**Four closed delivery schemas now make compiler truth, visible-asset ownership, calibrated delivery status, and independent blind review machine-checkable.**

## Performance

- **Duration:** 15 min
- **Started:** 2026-07-21T17:11:21+08:00
- **Completed:** 2026-07-21T17:25:42+08:00
- **Tasks:** 1
- **Files modified:** 5

## Accomplishments

- Defined mutually exclusive `COMPILED`, `TOOLCHAIN_MISSING`, and `COMPILE_FAILED` records; only a safe, successful, fully hashed receipt can expose a PDF.
- Required every figure/table to retain immutable source hashes, run-owned non-overwrite output facts, claims/results, caption ownership, permission, and reproducible or external provenance.
- Encoded deterministic daily-state derivation separately from submission readiness, including a valid readable draft with a PDF-required submission blocker.
- Bound independent review dispositions to reviewer identity, blind scheduler authorization, scoped inputs, and frozen contract/manuscript/PDF hashes.

## Task Commits

1. **Task 1 RED: executable delivery-schema expectations** - `2c63b17`
2. **Task 1 GREEN: four closed delivery contracts** - `d260d13`

## TDD Gate Compliance

- **RED:** `python -m pytest tests/test_manuscript_delivery_schemas.py -q` produced 95 expected failures because all four contracts were absent.
- **GREEN:** the focused suite passed all 95 cases after the four schemas were implemented.
- **Regression boundary:** `python -m pytest tests/test_manuscript_delivery_schemas.py tests/test_validate_artifact.py -q` passed 120 tests in 0.71s.
- **REFACTOR:** no behavior-neutral cleanup commit was needed.

## Files Created/Modified

- `schemas/manuscript_build_receipt.schema.json` - safe process, source, log, recorder, failure, and PDF receipt states.
- `schemas/manuscript_asset_manifest.schema.json` - complete visible-asset provenance, permission, ownership, and non-overwrite facts.
- `schemas/manuscript_quality_report.schema.json` - hard/advisory findings plus independently derived daily and submission outputs.
- `schemas/manuscript_review_verdict.schema.json` - independent blind review bound to frozen and scheduler-authorized inputs.
- `tests/test_manuscript_delivery_schemas.py` - 95 positive and negative delivery-contract cases.

## Decisions Made

- A missing required PDF is an explicit hard submission blocker, but it does not automatically collapse a readable source draft into daily `BLOCK`.
- Advisory defects may derive `USABLE_WITH_CAVEATS` or `NEEDS_SUPPLEMENT`; they cannot encode daily `BLOCK` or a hard submission effect.
- Generated and external assets use distinct, mutually exclusive provenance branches while sharing immutable source and run-owned output requirements.
- Reviewer conclusions and generation artifacts remain unavailable as independent evidence inside the blind-read receipt.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

The repository Python runtime does not support `zip(strict=True)`. The test helper was made version-compatible before the RED gate was recorded; the meaningful RED result remained 95 missing-contract failures. The GSD progress command computed 10% but left two stale 0% displays in `STATE.md`, so those two values were aligned with its returned result.

## User Setup Required

None.

## Next Phase Readiness

The delivery schema family is ready for later runtime consumers and central registration. Registration remains intentionally deferred to Plan 01-09; this plan did not add an operated recipe, compiler adapter, or vault write.

---
*Phase: 01-operated-ai-manuscript-authoring*
*Completed: 2026-07-21*

## Self-Check: PASSED

All five plan artifacts and both TDD gate commits were found after the final verification run.
