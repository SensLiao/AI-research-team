---
phase: 01-operated-ai-manuscript-authoring
plan: "14"
subsystem: manuscript-verification
tags: [python, scientific-truth, receipts, provenance, appsec]

requires:
  - phase: 01-02
    provides: frozen manuscript contract and venue requires_pdf authority
  - phase: 01-03
    provides: closed manuscript delivery schemas
  - phase: 01-08
    provides: shared path, secret, and TeX security validators
  - phase: 01-09
    provides: frozen result and executor-receipt contracts
provides:
  - deterministic claim, citation, number, bibliography, structure, venue, safety, and build audits
  - receipt-bound raw-result metric reconstruction and trusted build attestation
  - independent four-state daily delivery and strict submission-readiness reducers
affects: [manuscript-delivery, manuscript-review, submission-gating]

tech-stack:
  added: []
  patterns:
    - derive truth from receipt-bound bytes rather than model-authored facts
    - keep readable delivery independent from strict submission readiness
    - use descriptor-stable no-follow reads at file trust boundaries

key-files:
  created:
    - tools/manuscript_audit.py
    - tests/test_manuscript_audit.py
  modified: []

key-decisions:
  - "Numeric manuscript claims are compared only with metrics parsed from signed-receipt-bound raw JSON bytes."
  - "A self-hashed COMPILED record cannot satisfy readiness; a trusted build verifier must bind run, snapshot, current source, process, and PDF facts."
  - "Build-only deficits block submission but preserve readable daily delivery; truth, permission, secret, corrupt-input, and false-execution defects block both."
  - "The closed quality schema represents absent build evidence with a deterministic TOOLCHAIN_MISSING observation sentinel."

patterns-established:
  - "Independent truth derivation: untrusted manuscript values and self-reported verdicts never upgrade audit status."
  - "Single-descriptor verification: lstat, no-follow open, fstat identity, bounded read, and hash/size checks occur on one descriptor."

requirements-completed: [AUDT-01, DELV-02, SAFE-03, VERI-04]

coverage:
  - id: D1
    description: Complete deterministic manuscript audit registry emits stable schema-valid findings and four-state daily delivery.
    requirement: AUDT-01
    verification:
      - kind: unit
        ref: "tests/test_manuscript_audit.py#claim, citation, structure, terminology, label, venue, and reducer matrix"
        status: pass
    human_judgment: false
  - id: D2
    description: PDF-required and PDF-optional submissions derive readiness only from frozen venue authority and admissible build evidence.
    requirement: DELV-02
    verification:
      - kind: unit
        ref: "tests/test_manuscript_audit.py#requires_pdf x build-state matrix"
        status: pass
    human_judgment: false
  - id: D3
    description: Numeric, execution, PDF, path, and secret claims fail closed against trusted byte-level evidence.
    requirement: SAFE-03
    verification:
      - kind: integration
        ref: "python -m pytest tests/test_manuscript_audit.py tests/test_manuscript_security.py tests/test_execution_receipt_import.py -q (87 passed)"
        status: pass
    human_judgment: false
  - id: D4
    description: Daily readability and submission readiness remain separate deterministic outputs.
    requirement: VERI-04
    verification:
      - kind: unit
        ref: "tests/test_manuscript_audit.py#advisory and build-only reducer regressions"
        status: pass
    human_judgment: false

duration: 50min
completed: 2026-07-21
status: complete
---

# Phase 01 Plan 14: Deterministic Manuscript Truth Audit Summary

**Receipt-bound scientific truth audits now produce schema-valid four-state daily delivery while keeping submission readiness independently fail-closed.**

## Performance

- **Duration:** 50 min
- **Started:** 2026-07-21T14:55:03Z
- **Completed:** 2026-07-21T15:44:45Z
- **Tasks:** 1
- **Files modified:** 2

## Accomplishments

- Audited claim closure, exact evidence/citation support, frozen numbers, bibliography, terminology, notation, labels, assets, anonymity, venue rules, paths, secrets, TeX, builds, and explicit PDF claims in a stable registry order.
- Rebuilt numeric facts from signed-receipt-bound raw JSON bytes and ignored manuscript-provided metric values.
- Required trusted build attestation plus current-source and descriptor-stable PDF verification before a required-PDF manuscript can become submission-ready.
- Reduced findings deterministically to `USABLE`, `USABLE_WITH_CAVEATS`, `NEEDS_SUPPLEMENT`, or `BLOCK`, separately from submission readiness.

## Task Commits

Task 1 followed TDD with a supplemental AppSec RED/GREEN gate:

1. **Initial RED - audit and delivery-state contract** - `e3b1dab` (`test`)
2. **Initial GREEN - deterministic manuscript audit** - `34739b9` (`feat`)
3. **Security RED - provenance trust regressions** - `64ba1a3` (`test`)
4. **Security GREEN - trusted byte and build attestation binding** - `4e939db` (`fix`)

## Files Created/Modified

- `tools/manuscript_audit.py` - deterministic audit registry, receipt-bound truth checks, and separate daily/submission reducers.
- `tests/test_manuscript_audit.py` - 24 tests spanning the complete audit, build-state, reducer, and security matrix.

## Decisions Made

- Treated only receipt-bound raw bytes as the source of numeric truth; manuscript-provided result values remain untrusted input.
- Required an injected trusted build verifier for `COMPILED` readiness because schema validity and a recomputable self-hash are not authenticity evidence.
- Kept honest build absence/failure/staleness submission-only, while explicit false execution/PDF claims and other D-22 truth violations block daily use.
- Used a deterministic no-build sentinel because the closed quality-report schema requires a build summary and has no null/no-receipt state.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing Critical] Bound scientific numbers to receipt-verified raw result bytes**

- **Found during:** Task 1 AppSec review
- **Issue:** Receipt verification initially proved a file hash but numeric comparison still trusted manuscript-supplied values.
- **Fix:** Required contract/ref/hash closure, securely read the receipt-listed result file, parsed its bounded JSON metrics, and compared claims only with those derived values.
- **Files modified:** `tools/manuscript_audit.py`, `tests/test_manuscript_audit.py`
- **Verification:** Exact 87-test suite passed; targeted AppSec re-review confirmed closure.
- **Committed in:** `64ba1a3`, `4e939db`

**2. [Rule 2 - Missing Critical] Replaced self-authenticated build success with trusted attestation**

- **Found during:** Task 1 AppSec review
- **Issue:** A caller could construct a schema-valid self-hashed `COMPILED` receipt and arbitrary PDF.
- **Fix:** Required a trusted verifier to bind receipt, run, snapshot, PDF requirement, current/source-tree hashes, process receipt, PDF facts, and signature/source/PDF verification flags.
- **Files modified:** `tools/manuscript_audit.py`, `tests/test_manuscript_audit.py`
- **Verification:** Unsigned compiled receipts remain readable but not submission-ready; targeted AppSec re-review passed.
- **Committed in:** `64ba1a3`, `4e939db`

**3. [Rule 1 - Security Bug] Removed path-reopen TOCTOU from result and PDF verification**

- **Found during:** Task 1 AppSec review
- **Issue:** Path validation followed by `Path.read_bytes()` allowed a swap between validation and content hashing.
- **Fix:** Added bounded lstat/no-follow-open/fstat identity checks and hash/size verification on one stable descriptor; explicit PDF claims reuse the verified build fact without reopening.
- **Files modified:** `tools/manuscript_audit.py`, `tests/test_manuscript_audit.py`
- **Verification:** Stable-descriptor regression passed; targeted AppSec re-review reported zero remaining Critical/High.
- **Committed in:** `64ba1a3`, `4e939db`

---

**Total deviations:** 3 auto-fixed (2 Rule 2 security requirements, 1 Rule 1 security bug)
**Impact on plan:** The fixes close declared truth and file-boundary threats without changing persisted schemas or product scope.

## Issues Encountered

- Initial AppSec review found two Critical and one High provenance weaknesses. One bounded security TDD round closed all three; the same reviewer returned PASS with zero remaining Critical/High.
- The first GREEN test encoded an incorrect assumption that advisory-only findings block submission. The assertion was corrected to match the frozen policy that advisories cannot independently block submission.

## TDD Gate Compliance

- Initial RED precedes GREEN: `e3b1dab` -> `34739b9`.
- Security RED precedes remediation: `64ba1a3` -> `4e939db`.

## Known Stubs

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- The deterministic quality report and submission gate are ready for downstream review orchestration.
- No blocker remains; the exact plan suite and final AppSec review both pass.

## Self-Check: PASSED

- Both implementation/test files and this summary exist.
- All four TDD and security-remediation commits resolve to commit objects.

---
*Phase: 01-operated-ai-manuscript-authoring*
*Completed: 2026-07-21*
