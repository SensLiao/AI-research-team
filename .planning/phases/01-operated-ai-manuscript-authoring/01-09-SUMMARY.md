---
phase: 01-operated-ai-manuscript-authoring
plan: "09"
subsystem: manuscript-schema-registry
tags: [json-schema, artifact-validation, manuscript, truth-gates, tdd]
requires:
  - 01-01 manuscript pre-draft schema family
  - 01-02 manuscript delivery schema family
provides:
  - One authoritative central registry path for all eight manuscript artifact contracts
  - Public-boundary valid, invalid, closed-object, hash, state, and conditional-truth coverage
  - Deterministic unknown-type rejection with no mode-local schema loader
affects: [manuscript-scheduler, run-store, manuscript-integration, manuscript-audit]
tech-stack:
  added: []
  patterns: [static-schema-registry, public-boundary-contract-testing, fail-closed-artifact-validation]
key-files:
  created:
    - tests/test_manuscript_schema_contracts.py
  modified:
    - tools/validate_artifact.py
    - tests/test_validate_artifact.py
key-decisions:
  - "Register all manuscript payloads as fixed artifact-type-to-schema mappings in the existing PAYLOAD_SCHEMAS authority; do not add a cache, alternate validator, dynamic path, or mode-local loader."
  - "Exercise every manuscript schema through validate_payload with canonical builders and field-specific negative assertions so unknown-type rejection cannot masquerade as truth-gate coverage."
patterns-established:
  - "Registry parity: the eight manuscript artifact keys map one-to-one to the complete manuscript schema family."
  - "Truth-sensitive negative tests assert the expected failing field or path, not merely the presence of any validation error."
requirements-completed: [PREP-02, EVID-01, ORCH-02, LATX-02, ASST-01, AUDT-01, OPER-02, VERI-05]
coverage:
  - id: D1
    description: Every manuscript artifact type resolves exactly once to its committed schema through the central registry.
    requirement: ORCH-02
    verification:
      - kind: unit
        ref: tests/test_manuscript_schema_contracts.py#test_registry_and_schema_files_have_exact_one_to_one_manuscript_parity
        status: pass
      - kind: integration
        ref: python -m pytest tests/test_manuscript_schema_contracts.py tests/test_validate_artifact.py -q
        status: pass
    human_judgment: false
  - id: D2
    description: Valid and invalid pre-draft, section, integration, build, asset, quality, and review payloads cross the same public validation boundary.
    requirement: VERI-05
    verification:
      - kind: unit
        ref: tests/test_manuscript_schema_contracts.py#public-boundary valid and invalid matrix
        status: pass
    human_judgment: false
  - id: D3
    description: Unknown types, missing and additional fields, malformed hashes, illegal states, and inconsistent conditional truths fail deterministically.
    requirement: AUDT-01
    verification:
      - kind: unit
        ref: tests/test_validate_artifact.py#test_unknown_manuscript_payload_type_remains_rejected_centrally
        status: pass
      - kind: unit
        ref: tests/test_manuscript_schema_contracts.py#truth-sensitive negative matrix
        status: pass
    human_judgment: false
duration: 10min
completed: 2026-07-21
status: complete
---

# Phase 01 Plan 09: Central Manuscript Schema Registry Summary

**All eight manuscript artifact families now cross the repository's existing fail-closed `validate_payload` boundary through fixed, one-to-one schema registrations backed by a truth-sensitive regression matrix.**

## Performance

- **Duration:** 10 min
- **Started:** 2026-07-21T11:31:37Z
- **Completed:** 2026-07-21T11:41:37Z
- **Tasks:** 1
- **Files modified:** 3

## Accomplishments

- Registered `manuscript_contract`, `local_literature_coverage`, `manuscript_section_bundle`, `manuscript_integration`, `manuscript_build_receipt`, `manuscript_asset_manifest`, `manuscript_quality_report`, and `manuscript_review_verdict` in the existing central schema authority.
- Added exact one-to-one registry/file parity checks and proved one canonical valid payload per artifact type through `validate_payload`.
- Added missing-field and closed-object coverage for every type plus targeted malformed-hash, illegal-state, exhaustive-search, official-policy, build/PDF, asset ownership, quality-state, and independent-review truth failures.
- Preserved deterministic unknown-type rejection and verified that validation does not mutate caller inputs.
- Passed the mandatory AppSec review with 0 Critical, 0 High, 0 Medium, and 0 Low findings.

## Task Commits

1. **RED: Add failing manuscript registry matrix** - `e449e85`
2. **GREEN: Register manuscript artifact schemas** - `7349a68`

## TDD Gate Compliance

- **RED:** `python -m pytest tests/test_manuscript_schema_contracts.py tests/test_validate_artifact.py -q -p no:cacheprovider` produced the expected `37 failed, 26 passed`; all failures traced to the eight absent registry entries.
- **GREEN:** after adding only the central mappings and correcting three inaccurate negative-test expectations, the same focused matrix passed all 63 tests.
- **Plan verification:** the exact plan command `python -m pytest tests/test_manuscript_schema_contracts.py tests/test_validate_artifact.py -q` passed all 63 tests.
- **Family regressions:** both source schema suites passed all 155 tests.
- Git history contains the `test(01-09)` RED commit before the `feat(01-09)` GREEN commit.

## Files Created

- `tests/test_manuscript_schema_contracts.py` - cross-family public-boundary parity and truth-sensitive invalid matrix for all eight manuscript artifacts.

## Files Modified

- `tools/validate_artifact.py` - eight fixed manuscript artifact-to-schema mappings in `PAYLOAD_SCHEMAS`.
- `tests/test_validate_artifact.py` - central mapping uniqueness/file-existence and unknown-type rejection regressions.

## Decisions Made

- The existing `PAYLOAD_SCHEMAS` dictionary and `validate_payload` function remain the sole schema dispatch authority; no second validator, schema cache, dynamic filename construction, or mode-local validation path was introduced.
- Canonical builders from the pre-draft and delivery schema suites are reused so registry tests cannot drift into an alternative payload model.
- Invalid tests identify their intended field/path. This prevents the registry's unknown-type failure from accidentally satisfying a broad `assert errors` assertion.
- `requires_pdf` itself remains venue-dependent; the official-policy truth test instead proves that `hard_field_policy.requires_pdf.weakenable` cannot be changed from `false`.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Corrected three inaccurate negative-test expectations**

- **Found during:** Task 1 GREEN verification
- **Issue:** Quality and review conditional failures were reported at `daily_state` and `disposition`, not `<root>`; setting a venue's `requires_pdf` value to `false` is valid because the field is venue-dependent.
- **Fix:** Asserted the actual conditional error paths and tested the intended official hard-policy invariant by setting `hard_field_policy.requires_pdf.weakenable` to `true`.
- **Files modified:** `tests/test_manuscript_schema_contracts.py`
- **Verification:** The focused suite advanced from 3 failures / 60 passes to 63 passes.
- **Committed in:** `7349a68`

**2. [Rule 3 - Blocking] Corrected stale SDK progress rendering**

- **Found during:** Final GSD metadata update
- **Issue:** `state.update-progress` returned 9/20 and 45%, but the generated STATE frontmatter reset `percent` to 0 and retained the prior 40% body label.
- **Fix:** Updated both stale fields to the SDK's returned 45% result.
- **Files modified:** `.planning/STATE.md`
- **Verification:** STATE records Plan 9 of 20 and 45% in both machine-readable and human-readable fields.
- **Committed in:** Final plan metadata commit.

---

**Total deviations:** 2 auto-fixed (1 bug, 1 blocking metadata defect)
**Impact on plan:** The corrections keep truth-sensitive coverage aligned with the authoritative schemas and planning state aligned with the SDK result; no production scope or alternate validation behavior was added.

## Issues Encountered

- `tools/validate_artifact.py` already contained an unrelated two-line uncommitted `document_promotion_*` registry baseline. The manuscript hunk was staged interactively and the index was inspected before commit; the two original lines remain exclusively in the working diff.

## Deferred Issues

None. Runtime truth gates still complement structural validation as designed; this registry plan does not claim that manuscript modes are operated.

## Known Stubs

None. Every new mapping targets an existing schema and is exercised with both valid and invalid payloads through the public validator.

## User Setup Required

None - this plan uses the existing `jsonschema` validation boundary and committed schema files.

## Next Phase Readiness

Schedulers, run-store writers, manuscript integrators, builders, and auditors can now submit every manuscript payload type to one deterministic schema authority before dependency visibility. This plan establishes validation connectivity only; it does not claim that later operated-mode recipes or GPU/PDF execution have run.

## Self-Check: PASSED

All three planned files and this summary exist on disk; both RED/GREEN commits resolve as commits; the exact 63-test plan command and 155-test schema-family regression passed; summary whitespace validation passed; and the unrelated two-line `document_promotion_*` baseline remains isolated in the working diff.

---
*Phase: 01-operated-ai-manuscript-authoring*
*Completed: 2026-07-21*
