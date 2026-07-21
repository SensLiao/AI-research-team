---
phase: 01-operated-ai-manuscript-authoring
plan: "03"
subsystem: test-fixtures
tags: [hermetic-fixtures, manuscript-authoring, scientific-truth, receipt-binding, negative-paths]
requires: []
provides:
  - Exact seventeen-case hermetic manuscript evaluation matrix across nine fixture families
  - Exact-span local evidence and receipt-bound synthetic frozen-result evidence
  - Immutable director-owned figure and dated venue profiles for PDF-required and source-only tracks
  - Deterministic expected calls, bundles, hard findings, delivery states, and submission outcomes
affects: [literature-gates, authoring-dag, scientific-audits, asset-safety, manuscript-build, blind-review, end-to-end-verification]
tech-stack:
  added: []
  patterns: [fixture-local external-state injection, hash-bound evidence, explicit negative-path expectations]
key-files:
  created:
    - tests/fixtures/manuscript/gold_cases.json
    - tests/fixtures/manuscript/local_evidence.md
    - tests/fixtures/manuscript/frozen_result.json
    - tests/fixtures/manuscript/director_figure.svg
    - tests/fixtures/manuscript/venue_profile.json
  modified: []
key-decisions:
  - "Keep the gold set at exactly seventeen top-level cases while representing paired provider, compiler, path, and bundle failure variants inside their assigned cases."
  - "Bind all referenced fixture artifacts and synthetic executor evidence with deterministic SHA-256 values."
  - "Disable real network, vault, GPU, credentials, and host TeX access; compiler behavior is injected through deterministic fixture drivers only."
patterns-established:
  - "Hermetic manifest: every case declares frozen inputs and forbidden external dependencies before expected behavior."
  - "Truth-first fixtures: observed synthetic evidence is explicitly distinct from plan, script, metadata, and real-research execution claims."
requirements-completed: [VERI-01, VERI-02, VERI-03, VERI-04]
coverage:
  - id: F1
    description: Local sufficiency suppresses retrieval while named deficits activate only the injected existing-search boundary.
    requirement: VERI-02
    verification:
      - kind: fixture-integrity
        ref: tests/fixtures/manuscript/gold_cases.json
        status: pass
    human_judgment: false
  - id: F2
    description: Token precedence, official hard overrides, and targeted snapshot invalidation have deterministic expected outcomes.
    requirement: VERI-03
    verification:
      - kind: fixture-integrity
        ref: tests/fixtures/manuscript/gold_cases.json
        status: pass
    human_judgment: false
  - id: F3
    description: Bundle closure, bounded repair, scientific truth, safe paths, immutable assets, build truth, and blind-review separation cover required negative paths.
    requirement: VERI-04
    verification:
      - kind: fixture-integrity
        ref: tests/fixtures/manuscript/gold_cases.json
        status: pass
    human_judgment: false
  - id: F4
    description: One local-first end-to-end case specifies frozen context through authoring, integration, LaTeX source, audits, director Markdown, and honest build status.
    requirement: VERI-01
    verification:
      - kind: fixture-integrity
        ref: tests/fixtures/manuscript/gold_cases.json
        status: pass
    human_judgment: false
duration: 11min
completed: 2026-07-21
status: complete
---

# Phase 01 Plan 03: Hermetic Manuscript Gold Set Summary

**An exact seventeen-case, hash-bound gold set now specifies local-first manuscript behavior from evidence selection through honest build and independent review without touching network, vault, GPU, credentials, or host TeX.**

## Performance

- **Duration:** 11 min
- **Started:** 2026-07-21T17:32:57+08:00
- **Completed:** 2026-07-21T17:43:20+08:00
- **Tasks:** 1
- **Files modified:** 5

## Accomplishments

- Added exactly 17 cases in the planned 2/2/2/2/3/2/2/1/1 family distribution for local evidence, retrieval, tokens/snapshots, bundle/DAG behavior, scientific truth, asset/path safety, build truth, blind-review separation, and end-to-end authoring.
- Added exact-span local evidence, a synthetic receipt-bound frozen result, an immutable director-owned SVG, and dated PDF-required/source-only venue profiles.
- Made each case independently inspectable through its input manifest, expected tool calls, expected bundles, expected hard findings, expected status, and rationale.
- Kept all external dependencies injected or disabled and used visibly synthetic evidence that cannot be mistaken for a real GPU experiment.

## Task Commit

1. **Task 1: Create the exact hermetic manuscript fixture corpus** - `64af1da`

## TDD-Style Verification

- **RED:** The plan's automated fixture command failed with `FileNotFoundError` before `gold_cases.json` existed.
- **GREEN:** The same command passed after the five planned fixtures were created and confirmed exactly 17 structurally complete cases.
- **Regression boundary:** `python -m pytest tests/test_scholar_clients.py tests/test_scope_guard.py -q` passed 26 tests in 0.22s.
- The plan is fixture-only and has `type: execute`, so no separate RED test artifact or TDD gate commit was required.

## Files Created

- `tests/fixtures/manuscript/gold_cases.json` - exact case matrix with frozen inputs and deterministic expected behavior.
- `tests/fixtures/manuscript/local_evidence.md` - synthetic local source with stable exact spans.
- `tests/fixtures/manuscript/frozen_result.json` - synthetic observed result bound to raw bytes and a deterministic non-LLM receipt.
- `tests/fixtures/manuscript/director_figure.svg` - accessible immutable director-owned figure fixture.
- `tests/fixtures/manuscript/venue_profile.json` - dated official-source snapshots for PDF-required and source-only venue variants.

## Decisions Made

- Paired failure modes remain explicit subvariants inside their assigned top-level case so the contractual corpus stays at exactly 17 cases.
- Hashes in the gold set bind every companion fixture, and the frozen result separately binds raw-result bytes to executor-receipt bytes.
- The fake compiler is a deterministic fixture driver only; it does not claim or require a host LaTeX installation.
- Empty expected-call, bundle, or finding arrays are deliberate test expectations, not unwired product stubs.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

The GSD progress command correctly returned 15% but wrote a stale frontmatter percentage and retained the prior 10% display in `STATE.md`; both displays were aligned with its returned 3/20 result.

## User Setup Required

None.

## Next Phase Readiness

The fixture corpus is ready for the later literature, contract, orchestration, audit, build, review, and end-to-end test plans to consume. This plan intentionally adds no operated recipe, runtime implementation, registry entry, real retrieval, vault access, GPU execution, or real TeX invocation.

---
*Phase: 01-operated-ai-manuscript-authoring*
*Completed: 2026-07-21*

## Self-Check: PASSED

All five fixture files, the exact seventeen-case integrity command, and task commit `64af1da` were verified after the final regression run.
