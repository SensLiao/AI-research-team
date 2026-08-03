---
phase: 01-operated-ai-manuscript-authoring
plan: "15"
subsystem: manuscript-build
tags: [latex, latexmk, pdflatex, bibtex, biber, subprocess, receipts, windows]

requires:
  - phase: 01-02
    provides: manuscript artifact schemas and closed build-receipt contract
  - phase: 01-03
    provides: gold cases and deterministic fixture conventions
  - phase: 01-08
    provides: manuscript source integration and canonical source-tree inventory
  - phase: 01-09
    provides: shared path, TeX, and secret safety policies
provides:
  - readiness-tested latexmk selection with direct pdflatex plus bibliography fallback
  - private source staging and bounded shell-free native compilation
  - schema-valid COMPILED, COMPILE_FAILED, and TOOLCHAIN_MISSING receipts
  - real Windows LaTeX evidence binding fresh PDF, source, process, log, and recorder hashes
affects: [01-16, manuscript-audit, submission-readiness, verification]

tech-stack:
  added: [Python standard-library subprocess adapter]
  patterns: [same-sanitized-environment readiness, immutable private staging, descriptor-stable output hashing, total build deadline]

key-files:
  created:
    - tools/latex_build.py
    - tools/_latex_sandbox.py
    - tests/test_latex_build.py
  modified: []

key-decisions:
  - "Select latexmk only after its Perl-backed readiness probe succeeds under the exact sanitized environment used for compilation; otherwise probe the direct pipeline."
  - "Compile descriptor-verified source bytes from a private run-owned staging tree and publish only stable, freshly hashed PDF and recorder bytes."
  - "Treat TOOLCHAIN_MISSING as a truthful non-PDF state and keep real-host compilation mandatory whenever RAT_REQUIRE_REAL_LATEX=1."

patterns-established:
  - "Native build pattern: argv list + shell=false + explicit no-shell-escape + bounded streaming + one total deadline."
  - "Build truth pattern: source snapshot, process receipt, redacted log, recorder, and PDF hashes must close before COMPILED."

requirements-completed: [LATX-01, LATX-02, ASST-01, PLAT-01, VERI-01, VERI-04]

coverage:
  - id: D1
    description: "Readiness-tested latexmk selection and healthy direct pdflatex plus bibtex/biber fallback"
    requirement: LATX-01
    verification:
      - kind: unit
        ref: "tests/test_latex_build.py#test_driver_readiness_uses_build_sanitized_environment"
        status: pass
      - kind: unit
        ref: "tests/test_latex_build.py#test_latexmk_present_without_perl_falls_back_to_direct_pipeline"
        status: pass
    human_judgment: false
  - id: D2
    description: "Shell-free bounded compilation from private immutable source staging with fail-closed safety checks"
    requirement: ASST-01
    verification:
      - kind: unit
        ref: "tests/test_latex_build.py (19 adapter tests)"
        status: pass
      - kind: integration
        ref: "tests/test_manuscript_security.py"
        status: pass
    human_judgment: false
  - id: D3
    description: "Fresh real PDF bound to source, process, log, recorder, and PDF hashes"
    requirement: VERI-01
    verification:
      - kind: integration
        ref: "tests/test_latex_build.py real-host gate (the rolling windows-targeted.xml release artifact is superseded by Plan 20 final evidence)"
        status: pass
      - kind: integration
        ref: ".planning/evidence/phase-01/windows/real-build-receipt.json (COMPILED, 24321-byte PDF)"
        status: pass
    human_judgment: false
  - id: D4
    description: "Truthful isolated TOOLCHAIN_MISSING outcome without a PDF assertion"
    requirement: LATX-02
    verification:
      - kind: unit
        ref: "tests/test_latex_build.py#test_toolchain_missing_is_truthful"
        status: pass
    human_judgment: false

duration: 76min
completed: 2026-07-21
status: complete
---

# Phase 01 Plan 15: Receipt-Bound LaTeX Build Summary

**Cross-platform LaTeX compilation now selects only readiness-proven drivers, builds a private frozen source copy, and emits truthful hash-bound PDF or failure receipts.**

## Performance

- **Duration:** 76 min
- **Started:** 2026-07-21T15:54:15Z
- **Completed:** 2026-07-21T17:10:00Z
- **Tasks:** 1
- **Files modified:** 5

## Accomplishments

- Added sanitized, cross-platform discovery that selects `latexmk` only with a working Perl runtime and otherwise falls through to a probed direct TeX/bibliography pipeline.
- Added private immutable source staging, explicit `-no-shell-escape`, bounded output and process-tree timeout handling, source/tool/output identity checks, and full scratch cleanup on secret detection.
- Produced schema-valid receipts for all three build states and a real Windows `COMPILED` receipt with fresh PDF, recorder, source, process, and log hashes.
- Kept the isolated missing-toolchain branch mandatory alongside real-host compilation, preventing local tool availability from hiding the unavailable-path behavior.

## Task Commits

1. **Task 1 RED: bounded LaTeX build contract** - `2bd13e7` (test)
2. **Task 1 GREEN: receipt-bound LaTeX builds** - `16c64cd` (feat)
3. **Security RED: native build boundary attacks** - `01648de` (test)
4. **Security GREEN: hardened execution boundary** - `2850ef8` (fix)

## Files Created/Modified

- `tools/latex_build.py` - Public detector/build state machine, validation, receipt construction, and durable redacted evidence.
- `tools/_latex_sandbox.py` - Private descriptor-stable filesystem, staging, bounded streaming subprocess, and process-tree cleanup primitives.
- `tests/test_latex_build.py` - Hermetic platform, fallback, failure, identity, staging, secret, deadline, and real-toolchain regressions.
- `.planning/evidence/phase-01/windows-targeted.xml` - Rolling targeted JUnit evidence; its current contents are owned by the final Plan 20 release gate rather than this historical Plan 15 summary.
- `.planning/evidence/phase-01/windows/real-build-receipt.json` - Sanitized real-host `latexmk.exe` build receipt.

## Verification Evidence

- `python -m pytest tests/test_latex_build.py tests/test_manuscript_security.py -q` — 76 passed, 1 explicitly conditional real-host test skipped.
- The original Plan 15 real-host gate was green. Its former 61-test count is historical only: the rolling JUnit path is regenerated by Plan 20 and must be read through the final release-evidence verifier.
- Real receipt — `COMPILED`, `latexmk.exe`, argument-safe argv, 24,321-byte PDF, and current source/process/log/recorder/PDF hashes.
- `python -m py_compile tools/latex_build.py tools/_latex_sandbox.py` — passed.

## Decisions Made

- Driver presence alone is insufficient: selection requires a bounded readiness probe under the frozen build environment.
- The compiler never consumes the mutable authoring tree directly; it consumes verified bytes copied into a random private workspace.
- Direct fallback is represented by a closed aggregate process receipt while every actual pass and exit status remains bound through the redacted log hash.
- Positive PDF truth is published only after stable descriptor reads, source revalidation, recorder input checking, and schema validation.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Corrected real-host readiness and final-reference detection**
- **Found during:** Mandatory Windows real-LaTeX verification
- **Issue:** MiKTeX required an explicitly allowlisted home environment, and aggregate latexmk output retained transient first-pass reference warnings after the final pass had resolved them.
- **Fix:** Preserved the minimum required home variables in the sanitized environment and evaluated unresolved references from the final engine log.
- **Files modified:** `tools/latex_build.py`
- **Verification:** Mandatory real gate reached `COMPILED` with zero skipped tests.
- **Committed in:** `16c64cd`

**2. [Rule 2 - Missing Critical] Hardened the native compiler boundary after adversarial review**
- **Found during:** Post-GREEN AppSec review of the plan threat model
- **Issue:** Direct compilation of the mutable source tree, pathname-only output checks, unbounded capture, and retained secret-bearing scratch artifacts left Critical/High execution-boundary risks.
- **Fix:** Added private immutable staging, executable/support-file controls, explicit shell-escape denial, descriptor-stable reads and hashes, bounded streaming with process-tree termination and a total deadline, recorder input checks, and guaranteed scratch cleanup.
- **Files modified:** `tools/latex_build.py`, `tools/_latex_sandbox.py`, `tests/test_latex_build.py`
- **Verification:** Five new attack regressions pass; ordinary suite is 76 passed plus one conditional skip. The historical real-targeted count is superseded by the Plan 20 release evidence rather than asserted against the rolling JUnit path.
- **Committed in:** `01648de`, `2850ef8`

---

**Total deviations:** 2 auto-fixed (1 Rule 1 bug, 1 Rule 2 missing critical security boundary)
**Impact on plan:** Both changes were necessary for truthful real-host operation and the plan's declared Critical/High threat mitigations; no product scope was added.

## Issues Encountered

- The installed MiKTeX executables are legitimate installation hardlinks. Stable executable hashing therefore permits hardlinks for native tools while output/source artifacts remain single-link only.
- `latexmk` includes transient first-pass warnings in aggregate output; only its final engine log is authoritative for unresolved-reference closure.

## Deferred Issues

- Injected test runners create self-consistent fixture receipts but remain non-promotable without the independent trusted attestation supplied by Plan 01-14.
- Windows environment-key case aliases are not separately normalized; the adapter constructs and uses one explicit sanitized `PATH`, but a future hardening pass may canonicalize every allowed key.
- The canonical latest build receipt is atomically overwriteable; immutable historical receipt indexing is deferred to the run ledger/evidence lifecycle.

## Known Stubs

None.

## User Setup Required

None. The real-host gate resolves MiKTeX from environment-derived locations and Perl from `RAT_LATEX_DRIVER_RUNTIME_CANDIDATES`; no credential or repository configuration is required.

## Next Phase Readiness

- Downstream manuscript audit can consume closed, schema-valid build states and independently attest real `COMPILED` receipts.
- No blocker remains for the next plan; this executor did not inspect or run Plan 01-16.

## Self-Check: PASSED

All five deliverable/evidence files exist and all four task/security commits resolve in Git.

---
*Phase: 01-operated-ai-manuscript-authoring*
*Completed: 2026-07-21*
