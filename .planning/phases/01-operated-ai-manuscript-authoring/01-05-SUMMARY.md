---
phase: 01-operated-ai-manuscript-authoring
plan: "05"
subsystem: manuscript-production-contracts
tags: [section-ownership, canonical-writer, asset-provenance, scientific-truth, adaptive-dag]
requires: []
provides:
  - Specialized methods and results candidate-author contracts
  - Parameterized author contract for every remaining frozen required section
  - Immutable figure/table provenance and run-owned output contract
  - Exact-one completeness gate and singular canonical integration ownership
affects: [manuscript-authoring, section-scheduling, manuscript-assets, source-integration, worker-roster]
tech-stack:
  added: []
  patterns: [dynamic required-section set equality, receipt-bound numeric prose, deterministic-adapter canonical writes]
key-files:
  created:
    - agents/manuscript-methods-author.md
    - agents/manuscript-results-author.md
    - agents/manuscript-figure-table-engineer.md
    - agents/manuscript-integrator.md
    - agents/manuscript-section-author.md
  modified: []
key-decisions:
  - "Derive section completeness from frozen required_sections and require exact multiset equality with candidate section IDs."
  - "Reserve introduction, related work, methods, and results for specialized roles; parameterize every other required section without a fixed count."
  - "Make manuscript-integrator the sole canonical owner while allowing physical source writes only through the deterministic atomic adapter."
patterns-established:
  - "Candidate-only production: section and asset workers write evidence artifacts, never shared source or build state."
  - "No-backfill integration: a missing or duplicate required section blocks canonical writing instead of triggering generated filler."
requirements-completed: [ORCH-01, ORCH-02, LATX-01, ASST-01]
coverage:
  - id: P1
    description: Methods, results, asset engineering, parameterized sections, and integration are distinct adaptive capabilities.
    requirement: ORCH-01
    verification:
      - kind: contract-integrity
        ref: agents/manuscript-integrator.md
        status: pass
    human_judgment: false
  - id: P2
    description: Frozen required sections and candidate IDs must have exact-one adaptive ownership with hash-matched scheduler authorization.
    requirement: ORCH-02
    verification:
      - kind: contract-integrity
        ref: agents/manuscript-section-author.md
        status: pass
    human_judgment: false
  - id: P3
    description: Only the integrator capability may request a final source write, and only through the deterministic atomic adapter.
    requirement: LATX-01
    verification:
      - kind: contract-integrity
        ref: agents/manuscript-integrator.md
        status: pass
    human_judgment: false
  - id: P4
    description: Figure/table candidates require immutable sources, run-owned CREATE_NEW outputs, stable labels/captions, receipts, permissions, and accessibility facts.
    requirement: ASST-01
    verification:
      - kind: contract-integrity
        ref: agents/manuscript-figure-table-engineer.md
        status: pass
    human_judgment: false
duration: 8min
completed: 2026-07-21
status: complete
---

# Phase 01 Plan 05: Manuscript Production and Integration Contracts Summary

**Five provider-neutral worker contracts now cover methods, results, adaptive required sections, immutable assets, and one exact-one-gated canonical integration owner without shared mutable TeX state.**

## Performance

- **Duration:** 8 min
- **Started:** 2026-07-21T18:02:48+08:00
- **Completed:** 2026-07-21T18:10:01+08:00
- **Tasks:** 1
- **Files modified:** 5

## Accomplishments

- Defined methods and results authors that bind every scientific claim, procedure, number, comparison, and execution statement to exact evidence or frozen receipt-backed results.
- Defined one parameterized section capability for abstract, discussion, conclusion, limitations/ethics, appendix, and arbitrary venue-required sections not owned by specialized roles.
- Required one invocation, one assignment, and one candidate bundle per frozen required `section_id`, without imposing a fixed section or worker count.
- Defined figure/table provenance with immutable inputs, stable labels/captions, numeric source cells, permissions, accessibility text, deterministic receipts, and run-owned `CREATE_NEW` outputs.
- Made the integrator the only canonical owner, with exact required-section set equality and deterministic-adapter-only source writes; missing content remains unresolved instead of being invented.

## Task Commits

1. **Task 1: Specify scoped section, asset, and integration roles** - `02fb47f`
2. **Rule 2: Fail closed on existing closed-schema gaps** - `d33ce85`

## TDD-Style Verification

- **RED:** The plan's agent-contract integrity command failed before the five required role files existed.
- **GREEN:** The same command passed after all five schema-bound specifications were added.
- **Contract audit:** A YAML/parser check verified provider-neutral frontier capability maps, candidate write denial, supported parameterized sections, exact-one ownership, immutable asset provenance, and singular deterministic canonical writing.
- **Regression boundary:** `python -m pytest tests/test_model_policy.py -q` passed 20 tests in 1.06s.
- The plan has `type: execute`, so it required one implementation commit rather than separate TDD gate commits.

## Files Created

- `agents/manuscript-methods-author.md` - evidence-bound procedural candidate author.
- `agents/manuscript-results-author.md` - receipt-bound numeric and result candidate author.
- `agents/manuscript-figure-table-engineer.md` - immutable asset provenance candidate role.
- `agents/manuscript-section-author.md` - one-invocation/one-required-section parameterized author.
- `agents/manuscript-integrator.md` - exact-one completeness gate and sole canonical source owner.

## Decisions Made

- `required_sections` is a frozen dynamic set; the integrator compares it with the candidate `section_id` multiset and rejects missing, duplicate, unknown, optional-only, or unauthorized bundles.
- Specialized roles retain introduction, related-work, methods, and results ownership; the parameterized role covers every remaining required section without a global fixed list.
- The integrator is the only capability that may request final-source creation, while `tools/manuscript_integrator.py` remains the sole physical, path-fenced, atomic writer.
- The asset manifest's schema field `manuscript_sha256` is bound to `manuscript_snapshot_sha256` at candidate time, and `source_inputs[].sha256` is the authoritative `source_sha256` provenance value.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing Critical Functionality] Made schema-only gaps fail closed**

- **Found during:** Post-implementation contract cross-check
- **Issue:** The closed section schema requires nonempty claim support even for potentially claim-free required sections, while the asset schema requires result/numeric provenance even for potentially conceptual assets.
- **Fix:** Both roles now request a contract/schema supplement and refuse to fabricate claim or numeric provenance merely to satisfy the schema.
- **Files modified:** `agents/manuscript-section-author.md`, `agents/manuscript-figure-table-engineer.md`
- **Commit:** `d33ce85`

## Issues Encountered

The GSD progress command returned 25% but retained stale percentages in `STATE.md`; those displays were aligned with its authoritative 5/20 result.

## User Setup Required

None.

## Next Phase Readiness

The five contracts are ready for later roster/graph wiring and deterministic integration implementation. This plan intentionally added no runtime code, registry entry, operated recipe, TeX build, or physical asset rendering, and it did not begin Plan 01-06.

---
*Phase: 01-operated-ai-manuscript-authoring*
*Completed: 2026-07-21*

## Self-Check: PASSED

All five role specifications, the exact plan integrity command, and task commits `02fb47f` and `d33ce85` were verified after the final contract run.
