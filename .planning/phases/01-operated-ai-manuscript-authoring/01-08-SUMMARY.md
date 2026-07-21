---
phase: 01-operated-ai-manuscript-authoring
plan: "08"
subsystem: manuscript-security
tags: [path-security, latex, secret-scanning, execution-truth, tdd]
requires: []
provides:
  - Run-owned path validation with vault, director-asset, scope, symlink, reparse, hardlink, Unicode, and cross-platform fences
  - Bounded TeX validation with control-sequence, environment, package, and document-class allowlists
  - Caller-supplied secret sentinel and pattern scanning for every durable manuscript channel
  - Fail-closed execution prose validation that separates disclosed synthetic fixtures from externally reverified results
affects: [manuscript-integration, manuscript-build, manuscript-audit, operated-authoring-recipes]
tech-stack:
  added: []
  patterns: [pure-boundary-validation, caller-supplied-trust-roots, bounded-tex-allowlist, execution-reverification-gate]
key-files:
  created:
    - tools/manuscript_security.py
    - tests/test_manuscript_security.py
  modified: []
key-decisions:
  - "Resolve every relative target against an explicit run root, reject all link-like output aliases, and permit director assets only as explicitly declared hash-checked reads."
  - "Treat generated TeX as a bounded language: unknown controls, environments, packages, classes, local shadows, dynamic construction, and external references fail closed."
  - "Permit only explicitly disclosed synthetic-fixture execution prose here; every external or real execution receipt remains blocked until independent signature and file reverification."
  - "Scan only caller-supplied text, sentinels, and patterns so the security validator never opens secret files or discovers environment values."
patterns-established:
  - "Pure validator contract: validation returns JSON-compatible evidence and never creates, writes, compiles, downloads, promotes, or executes."
  - "Layered execution truth: 01-08 rejects unverified real claims; the existing receipt verifier remains the cryptographic authority consumed by the later audit layer."
requirements-completed: [SAFE-01, SAFE-02, SAFE-03, PLAT-01, VERI-04]
coverage:
  - id: D1
    description: Run-owned paths accept portable Unicode and ASCII spaces while rejecting traversal, external roots, vault writes, scope violations, symlinks, reparse points, hardlinks, and director-asset writes.
    requirement: SAFE-01
    verification:
      - kind: unit
        ref: tests/test_manuscript_security.py#path ownership and immutable asset tests
        status: pass
      - kind: integration
        ref: python -m pytest tests/test_manuscript_security.py tests/test_scope_guard.py tests/test_path_boundaries.py -q -p no:cacheprovider
        status: pass
    human_judgment: false
  - id: D2
    description: TeX validation admits only bounded run-relative sources and rejects unsafe directives, obfuscation, unknown controls, external references, and local class/package shadowing.
    requirement: SAFE-03
    verification:
      - kind: unit
        ref: tests/test_manuscript_security.py#TeX allowlist and negative-path matrix
        status: pass
    human_judgment: false
  - id: D3
    description: Durable URL, error, TeX, BibTeX, build, log, and Markdown text detects caller-identified secrets without reading environment or secret files.
    requirement: SAFE-02
    verification:
      - kind: unit
        ref: tests/test_manuscript_security.py#persisted secret sentinel matrix
        status: pass
    human_judgment: false
  - id: D4
    description: Scripts-only, plan-only, model-authored, mixed-language, undisclosed-fixture, and unverified real execution prose fails closed.
    requirement: VERI-04
    verification:
      - kind: unit
        ref: tests/test_manuscript_security.py#execution truth matrix
        status: pass
    human_judgment: false
duration: 35min
completed: 2026-07-21
status: complete
---

# Phase 01 Plan 08: Manuscript Security Boundary Summary

**A pure manuscript trust boundary now fences run-owned paths, generated TeX, durable secret-bearing text, and unsupported execution prose with portable, JSON-evidenced failures.**

## Performance

- **Duration:** 35 min
- **Started:** 2026-07-21T10:51:12Z
- **Completed:** 2026-07-21T11:25:53Z
- **Tasks:** 1
- **Files modified:** 2

## Accomplishments

- Added `validate_run_owned_path()` with explicit run ownership, vault fencing, scoped-output enforcement, director-asset hash reads, future-output validation, and symlink/reparse/hardlink rejection across Windows and Linux path forms.
- Added `validate_tex_sources()` with bounded literal include parsing plus fail-closed command, environment, package, and document-class allowlists; local `.sty`/`.cls` shadowing is rejected.
- Added secret-safe durable-text scanning across all declared channels using only caller-supplied material, including single-layer URL/form decoding without environment or secret-file discovery.
- Added execution-truth validation that admits only disclosed, canonical-hash-closed synthetic fixture evidence as non-publishable and sends every real/external receipt to independent reverification.
- Closed every Critical/High item found by the mandatory AppSec review; final reviewer verdict was 0 Critical / 0 High.

## Task Commits

1. **RED: Add failing manuscript security matrix** - `802f864`
2. **GREEN: Enforce manuscript trust boundaries** - `2d35b71`
3. **RED: Add security bypass regressions** - `f8a5db9`
4. **GREEN: Close path, scope, TeX, secret, and execution bypasses** - `d9a9bf1`
5. **RED: Add fail-closed prose and TeX regressions** - `55646ed`
6. **GREEN: Make prose and TeX validation fail closed** - `5c90dc7`
7. **RED: Add TeX class/package shadow regressions** - `2a052aa`
8. **GREEN: Reject TeX class and package shadowing** - `65db895`

## TDD Gate Compliance

- **Initial RED:** `tests/test_manuscript_security.py` failed collection because `tools.manuscript_security.py` did not exist.
- **Initial GREEN:** the focused matrix passed 38 tests and the plan regression command passed 53 tests.
- **Security RED/GREEN cycles:** AppSec-derived matrices demonstrated 13, 7, and 3 expected failures before their corresponding fixes.
- **Final GREEN:** `python -m pytest tests/test_manuscript_security.py tests/test_scope_guard.py tests/test_path_boundaries.py -q -p no:cacheprovider` passed all 72 tests.
- Git history contains each `test(01-08)` RED commit before its corresponding implementation/fix commit.

## Files Created

- `tools/manuscript_security.py` - pure path, TeX, secret-persistence, and execution-truth validators with stable policy-specific exceptions and JSON-compatible findings.
- `tests/test_manuscript_security.py` - adversarial Windows/Linux, traversal, link, Unicode/space, vault, scope, TeX, secret, and execution regression matrix.

## Decisions Made

- External absolute paths are rejected lexically before filesystem resolution; declared director inputs and the protected vault are classified explicitly so a UNC path cannot trigger network resolution.
- Existing output files with more than one hard link are rejected; later writers must still use run-owned atomic replacement and revalidate at the write boundary.
- TeX is validated as a deliberately bounded subset. Unknown controls/environments and unapproved packages/classes are errors, while class/package names found under the run source root are rejected as untrusted shadows.
- A plain mapping cannot prove a real executor signature. `SIGNED_EXTERNAL_EXECUTOR` and every non-fixture result therefore return `EXECUTION_REVERIFY_REQUIRED`; Plan 01-14 remains responsible for calling the existing Ed25519/file-binding verifier.
- A synthetic fixture may support only prose that explicitly says `synthetic fixture`, `test-only`, or `fixture-only`; the result carries `evidence_class: synthetic_fixture` and `publishable: false`.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Blocked numbered TeX write streams**

- **Found during:** Initial Task 1 GREEN run
- **Issue:** A word-boundary expression did not recognize `\\openout1` because the stream number is a word character.
- **Fix:** Accepted a numeric stream suffix explicitly while retaining the write-directive classification.
- **Files modified:** `tools/manuscript_security.py`
- **Verification:** The focused `openout` regression passed.
- **Committed in:** `2d35b71`

**2. [Rule 2 - Missing Critical Security] Closed static filesystem and encoded-text bypasses**

- **Found during:** Mandatory AppSec review
- **Issue:** Hardlink aliases, falsy scope roots, TeX character rewriting/file primitives, single-layer encoded URL sentinels, mixed negation, and self-asserted real receipts could bypass the first implementation.
- **Fix:** Rejected hardlinks; forced deterministic scope roots; expanded explicit TeX hard blocks; decoded URL/form text before sentinel comparison; removed global-negation suppression; and rejected all external/non-fixture receipts pending independent reverification.
- **Files modified:** `tools/manuscript_security.py`, `tests/test_manuscript_security.py`
- **Verification:** Added RED matrix failed 13 cases, then the expanded plan suite passed 63 tests.
- **Committed in:** `f8a5db9`, `d9a9bf1`

**3. [Rule 2 - Missing Critical Security] Replaced open-ended prose and TeX denylist decisions with fail-closed policy**

- **Found during:** AppSec rereview
- **Issue:** Unlisted execution synonyms/languages and package-provided or internal TeX input aliases could evade finite denylist matching; fixture identity was not visible in admitted prose.
- **Fix:** Only the exact no-execution template bypasses evidence checks; all other non-empty prose requires evidence. Added TeX command/environment/package allowlists and mandatory fixture disclosure with non-publishable evidence metadata.
- **Files modified:** `tools/manuscript_security.py`, `tests/test_manuscript_security.py`
- **Verification:** Added RED matrix failed 7 cases, then the expanded plan suite passed 69 tests.
- **Committed in:** `55646ed`, `5c90dc7`

**4. [Rule 2 - Missing Critical Security] Rejected TeX class/package shadowing**

- **Found during:** Final AppSec rereview
- **Issue:** An arbitrary document class or a run-local `.cls`/`.sty` with an approved name could be loaded after source validation.
- **Fix:** Added an explicit document-class allowlist and rejected local class/package shadows under the source root.
- **Files modified:** `tools/manuscript_security.py`, `tests/test_manuscript_security.py`
- **Verification:** Added RED matrix failed 3 cases; final plan suite passed 72 tests and AppSec returned 0 Critical / 0 High.
- **Committed in:** `2a052aa`, `65db895`

**5. [Rule 3 - Blocking] Corrected stale SDK progress rendering**

- **Found during:** Final GSD metadata update
- **Issue:** `state.update-progress` returned 8/20 and 40%, but the generated STATE frontmatter reset `percent` to 0 and left the prior 35% body label.
- **Fix:** Updated the two stale fields to the SDK's returned 40% result.
- **Files modified:** `.planning/STATE.md`
- **Verification:** STATE now records Plan 8 of 20 and 40% in both machine-readable and human-readable fields.
- **Committed in:** Final plan metadata commit.

---

**Total deviations:** 5 auto-fixed (1 bug, 3 missing critical security controls, 1 blocking metadata defect)
**Impact on plan:** Every change remains inside the two planned files and directly closes the plan's declared path, TeX, secret, or execution-truth threat model; no package, writer, compiler, network, promotion, GPU, or 01-09 work was added.

## Issues Encountered

- The first AppSec pass correctly distinguished syntactically self-consistent receipt facts from cryptographic authenticity. The plan-local resolution is fail-closed: real/external claims cannot pass 01-08, and the existing receipt verifier is intentionally consumed by Plan 01-14 rather than duplicated here.
- UNC rejection was moved ahead of `Path.resolve()` after a Windows regression showed that resolving an untrusted UNC path could attempt network access.

## Deferred Issues

- This pure validator cannot eliminate validate-then-open races by itself. Every later writer must revalidate immediately before a run-owned atomic replacement; the isolated build/write adapters own that enforcement.
- Secret sentinel scanning covers literal and one decoded URL/form layer, not arbitrary recursive/base64 encodings. Durable sinks must continue minimizing persisted inputs and apply channel-specific encoding controls.
- TeX compilation trust roots, disabled shell escape, cleared external search paths, no-network execution, timeouts, and source/PDF receipts remain build-layer responsibilities; no compilation occurs in this plan.

## Known Stubs

None. All four public validators are implemented and connected to named tests; external execution and TeX compilation are explicitly rejected/deferred boundaries, not mocked success paths.

## User Setup Required

None - the implementation uses the Python standard library plus the existing path and scope guards.

## Next Phase Readiness

Later manuscript integration, renderer, audit, and build tools can import one stable security boundary instead of adding divergent substring or path checks. Real execution claims remain blocked until the existing receipt verifier is invoked by the audit layer, and real TeX compilation remains blocked until the isolated build adapter supplies its own runtime controls.

## Self-Check: PASSED

Both planned files and this summary exist on disk; all eight RED/GREEN/security-fix commits resolve as commits; the exact 72-test plan command passed; summary whitespace validation passed; and both implementation targets are clean in the working tree.

---
*Phase: 01-operated-ai-manuscript-authoring*
*Completed: 2026-07-21*
