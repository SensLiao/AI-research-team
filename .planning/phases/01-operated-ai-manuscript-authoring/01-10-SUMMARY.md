---
phase: 01-operated-ai-manuscript-authoring
plan: "10"
subsystem: manuscript-orchestration-contracts
tags: [roster, stage-graph, sparse-dag, spec-only, blind-review, capability-catalog]
requires:
  - 01-04 reconnaissance and pre-draft worker contracts
  - 01-05 adaptive section, asset, and integration worker contracts
  - 01-06 independent manuscript review worker contracts
provides:
  - Seventeen manuscript roles connected to one legal roster group and graph stage
  - Distinct manuscript_authoring and manuscript_review declarative products
  - Adaptive paper-type section fixtures and sparse dependency groups
  - Cross-run identity, authorization-receipt, and blind-scope isolation
affects: [router, scheduler, capability-catalog, manuscript-authoring-recipe, manuscript-review-recipe]
tech-stack:
  added: []
  patterns: [registry-routable-spec-only, sparse-dependency-groups, adaptive-section-ownership, cross-run-review-isolation]
key-files:
  created: []
  modified:
    - orchestrator/roster.yaml
    - orchestrator/graph.yaml
    - orchestrator/mode_registry.yaml
    - tests/test_agent_connectivity.py
    - tests/test_capability_catalog.py
key-decisions:
  - "Keep manuscript_authoring and manuscript_review declarative and absent from the Python operate REGISTRY until their recipes, reducers, renderers, and operated tests exist."
  - "Derive non-specialized section instances from each frozen required_sections set while preserving four specialized owners and exact-one candidate closure before integration."
  - "Allow reusable audit role definitions across products only through distinct run, authorization-receipt, and blind-scope instances; authoring evidence can never count as independent review evidence."
patterns-established:
  - "Connectivity closure: every non-control capability resolves through roster, graph stage, and at least one honest declarative mode."
  - "Spec-only honesty: YAML routability never implies a one-button operated recipe."
requirements-completed: [OPER-02, ORCH-01, ORCH-02]
coverage:
  - id: C1
    description: All seventeen manuscript roles have their intended group, sole graph stage, and authoring/review mode membership.
    requirement: ORCH-01
    verification:
      - kind: integration
        ref: tests/test_agent_connectivity.py#test_manuscript_roles_have_exact_roster_graph_and_mode_connectivity
        status: pass
    human_judgment: false
  - id: C2
    description: Adaptive authoring preserves specialized ownership and exact required-section closure without a fixed section or worker-instance count.
    requirement: ORCH-02
    verification:
      - kind: contract
        ref: tests/test_capability_catalog.py#test_manuscript_authoring_contract_is_sparse_adaptive_and_section_complete
        status: pass
    human_judgment: false
  - id: C3
    description: Review requires six capability-bound blind verdicts, fresh cross-run identities, and deterministic-gated reconciliation before packaging.
    requirement: OPER-02
    verification:
      - kind: contract
        ref: tests/test_capability_catalog.py#test_manuscript_review_contract_requires_blind_capability_closure_and_join
        status: pass
    human_judgment: false
duration: 23min
completed: 2026-07-21
status: complete
---

# Phase 01 Plan 10: Manuscript Orchestration Contracts Summary

**Seventeen manuscript capabilities now form two distinct, adaptive sparse-DAG products whose YAML contracts are routable and testable while remaining explicitly non-operated until real recipes exist.**

## Performance

- **Duration:** 23 min
- **Started:** 2026-07-21T11:47:37Z
- **Completed:** 2026-07-21T12:10:29Z
- **Tasks:** 2
- **Files modified:** 5

## Accomplishments

- Added one stage home for each of seventeen manuscript capabilities: 1 DISCOVER, 2 DESIGN, 7 ANALYZE, 6 VERIFY, and 1 REPORT role.
- Raised connectivity baselines to 157 roster agents and 151 non-control, graph-connected, and mode-connected agents while keeping six infrastructure roles out of ordinary dispatch.
- Replaced the conflated `manuscript_review_pack` with separate `manuscript_authoring` and `manuscript_review` contracts, both `registry_routable_spec_only` and absent from `operate/modes/__init__.py::REGISTRY`.
- Defined sparse dependency groups, dynamic section-role instantiation, four specialized section owners, exact-one candidate closure, and varying empirical/theory/dataset/survey/system fixtures.
- Required the exact six review capabilities, frozen input hashes, at least two distinct blind receipts, capability-bound verdict receipts, deterministic-gated meta-review, and preserved minority findings.
- Closed AppSec's cross-mode identity concern with separate authoring/review run, receipt, and blind-scope namespaces plus explicit reuse prohibitions.

## Task Commits

1. **Task 1: Connect manuscript roles to stage graph** - `2028ba7`
2. **Task 2: Define honest manuscript mode contracts** - `bee70e5`
3. **Security fix: Isolate authoring and review identities** - `a1ac6cb`

## Verification

- `python -m pytest tests/test_agent_connectivity.py tests/test_capability_catalog.py tests/test_graph_spec.py -q` passed all 35 tests.
- `python -m pytest tests/test_router.py tests/test_panel_scheduler.py -q -p no:cacheprovider` passed all 30 routing/scheduler regressions.
- Capability catalog remains aligned with the unchanged ten-mode Python operated registry; spec-only totals are 16 overall and 6 registry-routable.
- AppSec rereview of the isolation fix returned 0 Critical, 0 High, and 0 Medium findings.

## Files Modified

- `orchestrator/roster.yaml` - seventeen roles added to their single capability group.
- `orchestrator/graph.yaml` - the same roles added only to their legal FSM stage.
- `orchestrator/mode_registry.yaml` - distinct authoring/review contracts, sparse groups, adaptive fixtures, blind-review closure, and explicit productization gaps.
- `tests/test_agent_connectivity.py` - exact baseline-plus-delta and role/stage/mode authorization assertions.
- `tests/test_capability_catalog.py` - spec-only honesty, maturity counts, adaptive section, evidence separation, and review-isolation regressions.

## Decisions Made

- Authoring and review share selected reusable role definitions but never a run identity, authorization receipt, blind scope, worker instance, or evidentiary status. Authoring quality checks are explicitly ineligible as independent review evidence.
- `manuscript-section-author` is instantiated once per remaining frozen required section rather than according to a global worker count. Introduction, related work, methods, and results retain specialized ownership.
- The integrator remains the only canonical source owner and cannot author missing prose; integration waits for exact required-section candidate closure.
- Review remains a separate VERIFY/REPORT product with six required capability IDs and a deterministic reducer before meta-review or submission packaging.
- Both YAML modes remain `record_only`, have no `operated` flag, and are deliberately absent from the executable Python registry.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Satisfied Task 1's planned cross-task connectivity dependency**

- **Found during:** Task 1 verification preparation
- **Issue:** The existing connectivity validator requires every rostered non-control agent to have mode membership, but Task 2 owns the two modes that make Task 1's seventeen additions valid.
- **Fix:** Prepared both tasks in one working tree, verified full connectivity, then committed the Task 1 and Task 2 file sets separately in plan order.
- **Files modified:** The five planned files only.
- **Verification:** The exact three-suite plan command passed after both declarative contracts were present.
- **Committed in:** `2028ba7`, `bee70e5`

**2. [Rule 3 - Blocking] Replaced nonexistent product evidence references**

- **Found during:** Task 2 verification
- **Issue:** Two initially named product-maturity evidence files did not exist, causing the capability catalog to fail closed with one test failure.
- **Fix:** Pointed authoring and review maturity evidence to the existing manuscript schema/delivery suites.
- **Files modified:** `orchestrator/mode_registry.yaml`
- **Verification:** The suite advanced from 1 failure / 34 passes to 35 passes.
- **Committed in:** `bee70e5`

**3. [Rule 2 - Missing Critical Security] Isolated reusable authoring and review instances**

- **Found during:** Mandatory AppSec review
- **Issue:** Reusable factual/citation/style audit roles and the packager could have reused authoring-run identities or receipts in a later blind review, weakening D-01 independence.
- **Fix:** Added distinct run, authorization-receipt, and blind-scope namespaces; forbade cross-mode instance/receipt reuse; rejected authoring receipts and instance IDs in review; and required a capability-bound receipt per verdict.
- **Files modified:** `orchestrator/mode_registry.yaml`, `tests/test_capability_catalog.py`
- **Verification:** Focused plan suite passed 35 tests; AppSec rereview closed F-001 with no remaining Medium finding.
- **Committed in:** `a1ac6cb`

**4. [Rule 3 - Blocking] Corrected stale SDK progress rendering**

- **Found during:** Final GSD metadata update
- **Issue:** `state.update-progress` returned 10/20 and 50%, but the generated STATE frontmatter reset `percent` to 0 and retained the prior 45% body label.
- **Fix:** Updated both stale fields to the SDK's returned 50% result.
- **Files modified:** `.planning/STATE.md`
- **Verification:** STATE records Plan 10 of 20 and 50% in both machine-readable and human-readable fields.
- **Committed in:** Final plan metadata commit.

---

**Total deviations:** 4 auto-fixed (3 blocking issues, 1 missing critical security control)
**Impact on plan:** All corrections stay within the five planned files and strengthen the planned connectivity and author/review separation without creating a recipe or operated claim.

## Issues Encountered

- `orchestrator/mode_registry.yaml` began with an unrelated 17-addition/9-deletion working diff. Both Task 2 and the security fix were staged hunk-by-hunk; after each commit the original 17/9 baseline remained exclusively in the working diff.

## Deferred Issues

- **Accepted Low, hard pre-operation gate:** the distinct authoring/review evidence namespaces are declarative metadata today. Before either mode becomes operated, routing must freeze both namespaces into the closed task-frame contract and the scope guard must enforce path ownership, traversal rejection, and cross-namespace isolation. This is recorded in the mode's productization gaps and has no current runtime exposure because neither recipe exists.

## Known Stubs

- `manuscript_authoring` is intentionally `registry_routable_spec_only`; its operated recipe, deterministic reducers, renderer, and operated tests remain future work required by D-02.
- `manuscript_review` is intentionally `registry_routable_spec_only`; its separate review recipe, receipt verifier, reconciliation reducer, renderer, and operated tests remain future work required by D-02.

These stubs are the explicit output of this contract plan and do not prevent its goal; neither is presented as push-button functionality.

## User Setup Required

None - this plan changes declarative routing contracts and tests only.

## Next Phase Readiness

Later recipe plans can consume stable roster, stage, sparse-DAG, adaptive-section, evidence-namespace, and blind-review contracts. They must satisfy every recorded productization gap and the namespace enforcement gate before adding either mode to the Python operated registry.

## Self-Check: PASSED

All five planned files and this summary exist on disk; all three implementation/security commits resolve as commits; the exact 35-test plan command and 30-test routing/scheduler regression passed; summary whitespace validation passed; and the unrelated `mode_registry.yaml` 17-addition/9-deletion baseline remains isolated in the working diff.

---
*Phase: 01-operated-ai-manuscript-authoring*
*Completed: 2026-07-21*
