---
phase: 01-operated-ai-manuscript-authoring
plan: "04"
subsystem: manuscript-agent-contracts
tags: [least-privilege, sparse-dag, evidence-provenance, section-bundles, provider-neutral]
requires: []
provides:
  - Official venue and six-axis local-corpus reconnaissance contract
  - Frozen manuscript architecture and role-specific dependency-slice contract
  - Exact-span and receipt-bound evidence admission contract
  - Candidate-only introduction and related-work author contracts
affects: [manuscript-authoring, worker-roster, manuscript-contract, literature-routing, section-integration]
tech-stack:
  added: []
  patterns: [provider-neutral capability requirements, scheduler-authorized frozen slices, schema-fragment handbacks]
key-files:
  created:
    - agents/manuscript-venue-corpus-scout.md
    - agents/manuscript-architect.md
    - agents/manuscript-evidence-steward.md
    - agents/manuscript-introduction-author.md
    - agents/manuscript-related-work-author.md
  modified: []
key-decisions:
  - "Reconnaissance performs bounded recall and emits deficit-only query authorization; it never calls a scholarly provider directly."
  - "The evidence steward binds its handback to the existing claim-evidence schema and the evidence/result/bibliography fragments of the frozen manuscript contract."
  - "Section authors receive exactly one frozen global contract plus declared predecessor slices and can emit candidates only."
patterns-established:
  - "Schema-bound handback: every role returns artifact refs, hashes, and the shared manuscript snapshot hash."
  - "Canonical-tree mutex: section workers cannot write main.tex, refs.bib, canonical assets, sibling bundles, or run infrastructure."
requirements-completed: [PREP-01, EVID-01, EVID-02, ORCH-01, ORCH-02]
coverage:
  - id: R1
    description: Current official venue authority and paper-type inputs are captured before drafting without making a venue decision for the director.
    requirement: PREP-01
    verification:
      - kind: contract-integrity
        ref: agents/manuscript-venue-corpus-scout.md
        status: pass
    human_judgment: false
  - id: R2
    description: Six local coverage axes precede narrow deficit-only query authorization, and metadata remains noncitable.
    requirement: EVID-01
    verification:
      - kind: contract-integrity
        ref: agents/manuscript-venue-corpus-scout.md
        status: pass
    human_judgment: false
  - id: R3
    description: Exact-span local evidence and frozen receipt-bound results are the only admissible support paths.
    requirement: EVID-02
    verification:
      - kind: contract-integrity
        ref: agents/manuscript-evidence-steward.md
        status: pass
    human_judgment: false
  - id: R4
    description: Reconnaissance, architecture, evidence stewardship, and two specialized section-author capabilities have explicit stage and output contracts.
    requirement: ORCH-01
    verification:
      - kind: contract-integrity
        ref: agents/manuscript-architect.md
        status: pass
    human_judgment: false
  - id: R5
    description: Frozen common context, scheduler receipts, declared predecessor slices, and candidate-only outputs enforce sparse-DAG authorship.
    requirement: ORCH-02
    verification:
      - kind: contract-integrity
        ref: agents/manuscript-introduction-author.md
        status: pass
    human_judgment: false
duration: 9min
completed: 2026-07-21
status: complete
---

# Phase 01 Plan 04: Initial Manuscript Worker Contracts Summary

**Five schema-bound, least-privilege worker contracts now separate reconnaissance, architecture, evidence admission, and candidate section writing before any manuscript recipe can dispatch them.**

## Performance

- **Duration:** 9 min
- **Started:** 2026-07-21T17:49:52+08:00
- **Completed:** 2026-07-21T17:58:15+08:00
- **Tasks:** 1
- **Files modified:** 5

## Accomplishments

- Defined official-rule and local-corpus reconnaissance with the required authority order, six independent coverage axes, bounded recall first, and deficit-only query authorization for the existing search port.
- Defined a frontier architecture role that freezes the complete D-12 manuscript contract and minimal, hash-bound dependency slices.
- Defined evidence stewardship that admits only exact local loci or frozen results bound to non-LLM executor receipts.
- Defined introduction and related-work authors that consume one frozen snapshot plus authorized predecessor slices and emit only `manuscript_section_bundle` candidates.
- Denied every role vault writes, promotion, downloaders, arbitrary shell/subprocess use, GPU execution, secrets, run infrastructure, and canonical-tree mutation.

## Task Commit

1. **Task 1: Specify reconnaissance, architecture, evidence, and section roles** - `1f2fece`

## TDD-Style Verification

- **RED:** The plan's integrity command failed before the five required role files existed.
- **GREEN:** The same command passed after all five contracts included frontmatter, `permission_scope`, North-star discipline, explicit `never` scopes, and schema-bound Handbacks.
- **Contract audit:** An additional parser check verified required metadata, provider-neutral strong/frontier capability maps, stages, six coverage axes, frozen-slice rules, evidence truth, and canonical-tree denial.
- **Regression boundary:** `python -m pytest tests/test_model_policy.py -q` passed 20 tests in 1.03s.
- The plan has `type: execute`, so it required one implementation commit rather than separate TDD gate commits.

## Files Created

- `agents/manuscript-venue-corpus-scout.md` - official authority, bounded recall, coverage, and deficit routing.
- `agents/manuscript-architect.md` - complete frozen contract, outline/claim plan, and sparse dependency slices.
- `agents/manuscript-evidence-steward.md` - exact-span evidence, frozen results, and bibliography admission.
- `agents/manuscript-introduction-author.md` - introduction/contribution candidate bundle.
- `agents/manuscript-related-work-author.md` - evidence-bound prior-art positioning candidate bundle.

## Decisions Made

- Logical `sonnet`/`opus` workload aliases remain in the compatible `model` field, while each role explicitly declares provider-neutral strong/frontier, long-context, tool-use requirements.
- The venue scout returns `local_literature_coverage` plus a venue payload bound to the venue-profile fragment of `manuscript_contract`; it does not perform retrieval itself.
- Because no dedicated manuscript-evidence-slice schema exists, the evidence steward binds its wrapper to `claim_evidence_map` and the existing `manuscript_contract` evidence/result/bibliography fragments.
- The implemented section-bundle contract uses its authoritative `claim_support_refs` field rather than the older `claim_uses` wording in AI-SPEC prose.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

The AI-SPEC prose names `claim_uses`, while the implemented closed schema names the field `claim_support_refs`; the role specifications follow the authoritative schema. The coverage schema also represents provider failure inside a deficit's query-authorization outcome rather than as a top-level axis status, so the scout preserves that existing contract.

The GSD progress command returned 20% but retained stale percentages in `STATE.md`; those displays were aligned with its authoritative 4/20 result.

## User Setup Required

None.

## Next Phase Readiness

The five contracts are ready for later roster/graph wiring and operated recipe consumption. Per the plan, connectivity is deferred until all manuscript role files exist in Plan 01-10; this execution did not register or operate the roles and did not begin Plan 01-05.

---
*Phase: 01-operated-ai-manuscript-authoring*
*Completed: 2026-07-21*

## Self-Check: PASSED

All five role specifications, the plan integrity command, and task commit `1f2fece` were found after the final verification run.
