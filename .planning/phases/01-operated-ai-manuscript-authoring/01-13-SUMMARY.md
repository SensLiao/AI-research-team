---
phase: 01-operated-ai-manuscript-authoring
plan: "13"
subsystem: manuscript-authoring
tags: [python, latex, provenance, atomic-publish, appsec]

requires:
  - phase: 01-02
    provides: frozen manuscript contract and snapshot identity
  - phase: 01-03
    provides: section-bundle and integration schemas
  - phase: 01-08
    provides: shared path, secret, and TeX security validators
  - phase: 01-09
    provides: frozen result and asset provenance contracts
provides:
  - deterministic reduction of authorized section bundles into one native LaTeX source candidate
  - capability-bound, create-once atomic publication of the canonical run-owned source tree
  - receipt-bound result and generated-asset verification with immutable director-asset copying
  - fail-closed BibTeX, binary-secret, and inert-SVG validation
affects: [manuscript-delivery, manuscript-verification, canonical-source]

tech-stack:
  added: []
  patterns:
    - in-memory validated candidate before atomic directory publication
    - injected external authority verifiers bound to exact frozen facts
    - descriptor-stable reads for trust-boundary files

key-files:
  created:
    - tools/manuscript_integrator.py
    - tools/_manuscript_integrator_security.py
    - tests/test_manuscript_integration.py
  modified: []

key-decisions:
  - "Canonical source publication requires an ephemeral process-issued candidate capability bound to one exact run and integration hash."
  - "Scheduler, frozen-result, and generated-command authenticity is delegated to explicit external verifiers that must echo the exact bound facts."
  - "SVG assets use an inert structural allowlist, while default secret signatures are scanned directly across text and binary bytes."

patterns-established:
  - "Validate then publish: build and hash the complete candidate in memory before obtaining the single-writer lock."
  - "Trusted-kind derivation: asset input kind comes from the frozen source inventory, never the manifest's self-declaration."

requirements-completed: [ORCH-02, LATX-01, ASST-01, VERI-01, VERI-04]

coverage:
  - id: D1
    description: Authorized frozen section bundles deterministically produce one coherent native LaTeX source candidate.
    requirement: ORCH-02
    verification:
      - kind: integration
        ref: "tests/test_manuscript_integration.py#deterministic integration and reconciliation tests"
        status: pass
    human_judgment: false
  - id: D2
    description: Only one capability-bound integrator can atomically create the current run's canonical source tree.
    requirement: LATX-01
    verification:
      - kind: integration
        ref: "tests/test_manuscript_integration.py#single-writer, cross-run, path, and rollback tests"
        status: pass
    human_judgment: false
  - id: D3
    description: Director and generated assets retain frozen provenance, trusted input kinds, and receipt-bound execution facts.
    requirement: ASST-01
    verification:
      - kind: integration
        ref: "tests/test_manuscript_integration.py#asset provenance and receipt tests"
        status: pass
    human_judgment: false
  - id: D4
    description: Unsafe TeX, secrets, active SVG, stale receipts, and mutable file races fail before publication.
    requirement: VERI-04
    verification:
      - kind: integration
        ref: "python -m pytest tests/test_manuscript_integration.py tests/test_manuscript_security.py tests/test_manuscript_schema_contracts.py -q (122 passed)"
        status: pass
    human_judgment: false

duration: 64min
completed: 2026-07-21
status: complete
---

# Phase 01 Plan 13: Deterministic Manuscript Integration Summary

**Receipt-authorized section bundles now reduce into one provenance-complete LaTeX tree with capability-bound atomic publication and fail-closed asset security.**

## Performance

- **Duration:** 64 min
- **Started:** 2026-07-21T13:46:23Z
- **Completed:** 2026-07-21T14:49:43Z
- **Tasks:** 1
- **Files modified:** 3

## Accomplishments

- Implemented deterministic ordering and reconciliation of exact-one required section bundles against the frozen manuscript contract, claim ledger, bibliography, notation, results, and assets.
- Added a single canonical `source/` writer that validates a process-issued candidate capability, stages a complete tree, verifies hashes, and atomically publishes with create-once lock ownership.
- Bound scheduler authorization, frozen result receipts, generated commands, and asset inputs to exact trusted facts; director assets are copied from stable descriptors without mutating originals.
- Enforced fail-closed TeX/BibTeX checks, text and binary secret scans, safe path ownership, and an inert SVG element/attribute allowlist.

## Task Commits

Task 1 followed TDD with supplemental security RED/GREEN gates:

1. **Initial RED — integration contract** - `604eec5` (`test`)
2. **Initial GREEN — canonical manuscript integration** - `277a90d` (`feat`)
3. **Security RED — integration boundary regressions** - `4eef761` (`test`)
4. **Security GREEN — trust-boundary hardening** - `72903f2` (`fix`)
5. **Residual asset RED** - `0b91ba7` (`test`)
6. **Residual asset GREEN** - `2db2606` (`fix`)
7. **Final scanner RED** - `237be08` (`test`)
8. **Final scanner GREEN** - `e9d2fa8` (`fix`)

## Files Created/Modified

- `tools/manuscript_integrator.py` - deterministic reducer, reconciliation, candidate construction, and atomic canonical-tree publisher.
- `tools/_manuscript_integrator_security.py` - private stable-read, receipt, trusted-input, secret, and SVG validators.
- `tests/test_manuscript_integration.py` - deterministic, provenance, authorization, path, rollback, and security regression coverage.

## Decisions Made

- Kept the integration manifest schema unchanged; bounded JSON-repair evidence is recorded through existing `reconciliation_findings`.
- Used injected verifier capabilities rather than self-hashed receipts as the external trust anchor for scheduler, result, and generated-command facts.
- Rejected ambiguous asset-input kinds and active SVG constructs rather than inferring trust from model-authored manifest fields.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing Critical] Added external authority and candidate-capability enforcement**

- **Found during:** Task 1 AppSec review
- **Issue:** Self-hashed scheduler/result records and caller-constructed candidates could spoof authorization or cross run boundaries.
- **Fix:** Required exact-fact external verifiers, verified result receipt bytes, bound candidates to one process/run/hash, and preserved incumbent lock ownership.
- **Files modified:** `tools/manuscript_integrator.py`, `tools/_manuscript_integrator_security.py`, `tests/test_manuscript_integration.py`
- **Verification:** Exact suite passed; AppSec re-review confirmed prior F-002 through F-005 and F-008 closed.
- **Committed in:** `4eef761`, `72903f2`

**2. [Rule 2 - Missing Critical] Closed TeX, repair, and asset provenance gaps**

- **Found during:** Task 1 AppSec review
- **Issue:** BibTeX skipped TeX validation, JSON repair could alter structure, asset inputs trusted manifest kinds, and binary/SVG content could bypass secret or active-content checks.
- **Fix:** Included `.bib` in TeX validation, constrained repair to punctuation/whitespace with normalized hashes, derived source kinds from the frozen inventory, descriptor-read every supported input, bound generated-command facts, scanned raw binary patterns, and allowlisted inert SVG XML.
- **Files modified:** `tools/manuscript_integrator.py`, `tools/_manuscript_integrator_security.py`, `tests/test_manuscript_integration.py`
- **Verification:** `122 passed`; final same-reviewer AppSec verdict PASS with zero remaining Critical/High in the reviewed scope.
- **Committed in:** `0b91ba7`, `2db2606`, `237be08`, `e9d2fa8`

**3. [Rule 2 - AGENTS.md Compliance] Extracted private security helpers**

- **Found during:** Task 1 security hardening
- **Issue:** Inline boundary hardening pushed the main module above the project's roughly 800-line split threshold.
- **Fix:** Moved only private security validation into `tools/_manuscript_integrator_security.py`; the public integration module remains 795 lines.
- **Files modified:** `tools/manuscript_integrator.py`, `tools/_manuscript_integrator_security.py`
- **Verification:** Python compilation, diff check, and the exact 122-test suite passed after extraction.
- **Committed in:** `72903f2`

---

**Total deviations:** 3 auto-fixed (3 Rule 2 correctness/security requirements)
**Impact on plan:** All changes enforce the plan's declared trust boundaries and AGENTS.md size rule; no product scope or persisted schema was added.

## Issues Encountered

- The initial AppSec review found two Critical and seven High findings. Bounded TDD remediation and repeated scope-limited re-review reduced these to zero; the final verdict was PASS.

## TDD Gate Compliance

- RED commit exists before implementation: `604eec5`.
- GREEN commit follows RED: `277a90d`.
- Each AppSec remediation round also has a failing regression commit before its corresponding fix commit.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Canonical native LaTeX source construction is deterministic, provenance-complete, and protected by the final AppSec PASS.
- No blocker remains for downstream manuscript build and verification work.

## Self-Check: PASSED

- All three implementation/test files and this summary exist.
- All eight TDD and remediation commits resolve to commit objects.
- Summary diff validation reported no whitespace errors.

---
*Phase: 01-operated-ai-manuscript-authoring*
*Completed: 2026-07-21*
