---
phase: 01-operated-ai-manuscript-authoring
plan: "11"
subsystem: manuscript-contracts
tags: [paper-design-tokens, canonical-json, provenance, official-rules, atomic-freeze, tdd]
requires:
  - 01-03 hermetic manuscript gold cases and targeted invalidation expectations
  - 01-09 centrally registered closed manuscript_contract schema
provides:
  - Deterministic five-layer Paper Design Token resolution with replayable override provenance
  - Locked generic truth-hard and official venue-hard policy enforcement
  - Canonical, source-closed, create-once frozen manuscript contract snapshots
  - Domain-neutral base, six paper-type, and AI-research advisory token profiles
affects: [manuscript-authoring-recipe, section-dispatch, integration, review, build]
tech-stack:
  added: []
  patterns: [rich-resolver-schema-projection, injected-freshness-policy, injected-receipt-verifier, atomic-create-once]
key-files:
  created:
    - tools/manuscript_contract.py
    - tools/_manuscript_contract_validation.py
    - tests/test_manuscript_contract.py
    - profiles/paper_design_tokens/base.yaml
    - profiles/paper_design_tokens/paper_types.yaml
    - profiles/paper_design_tokens/ai_research.yaml
  modified: []
key-decisions:
  - "Resolve tokens only in base -> paper_type -> venue -> project -> run order; freeze requires replayable resolver provenance while projecting only registered schema fields into the contract."
  - "Keep six generic truth controls locked at base and accept venue hard tokens only from the frozen current official rule/template pair; all prose and presentation preferences remain advisory."
  - "Require injected freshness and result/receipt verification facts, keeping current venue data and cryptographic executor verification outside this deterministic reducer."
  - "Publish immutable contracts with unique temporary files and create-once atomic hard links, so concurrent writers cannot overwrite the first frozen snapshot."
patterns-established:
  - "Closed-schema projection: rich deterministic reducer evidence is replayed and verified before its schema-safe snapshot is persisted."
  - "Authority-preserving cascade: hard values have an explicit owner and source class; advisory conflicts stay visible and nonblocking."
requirements-completed: [PREP-01, PREP-02, PREP-03, PREP-04, PLAT-02, VERI-03]
coverage:
  - id: T1
    description: Paper Design Tokens resolve in the exact five-layer order with stable hashes, per-override prior values, and nonblocking advisory caveats.
    requirement: PREP-03
    verification:
      - kind: unit
        ref: tests/test_manuscript_contract.py#test_token_layers_are_exact_and_resolution_ignores_input_mapping_order
        status: pass
      - kind: unit
        ref: tests/test_manuscript_contract.py#test_every_override_records_full_provenance_and_prior_value
        status: pass
    human_judgment: false
  - id: T2
    description: Generic truth-hard and official venue requires_pdf policy cannot be changed, deleted, reclassified, weakened, or sourced from lower-authority overlays.
    requirement: PREP-04
    verification:
      - kind: unit
        ref: tests/test_manuscript_contract.py#test_inherited_hard_rule_cannot_be_changed_deleted_reclassified_or_weakened
        status: pass
      - kind: unit
        ref: tests/test_manuscript_contract.py#test_freeze_rejects_venue_hard_token_without_official_source
        status: pass
    human_judgment: false
  - id: T3
    description: A complete D-12 contract is schema-valid, cross-reference closed, receipt-verifier bound, canonically hashed, and atomically frozen once.
    requirement: PREP-02
    verification:
      - kind: integration
        ref: tests/test_manuscript_contract.py#test_freeze_validates_complete_contract_and_writes_canonical_snapshot
        status: pass
      - kind: integration
        ref: tests/test_manuscript_contract.py#test_concurrent_freeze_is_create_once_and_leaves_no_temporary_files
        status: pass
    human_judgment: false
  - id: T4
    description: Dated official venue sources, paper type, evidence/results, dependency slices, and explicit descendant invalidation fail closed under invalid or stale inputs.
    requirement: VERI-03
    verification:
      - kind: unit
        ref: "python -m pytest tests/test_manuscript_contract.py tests/test_manuscript_schema_contracts.py -q (73 passed)"
        status: pass
    human_judgment: false
  - id: T5
    description: Shipped base, paper-type, and AI-research profiles are data-driven, domain-neutral, and keep presentation style advisory.
    requirement: PLAT-02
    verification:
      - kind: unit
        ref: tests/test_manuscript_contract.py#test_profiles_contain_no_transient_or_host_specific_control_plane_constants
        status: pass
    human_judgment: false
duration: 42min
completed: 2026-07-21
status: complete
---

# Phase 01 Plan 11: Paper Design Tokens and Frozen Contract Summary

**A replayable five-layer token cascade now freezes one source-closed manuscript contract while preserving official hard policy, nonblocking style discretion, verified result boundaries, and concurrent create-once immutability.**

## Performance

- **Duration:** 42 min
- **Started:** 2026-07-21T12:16:41Z
- **Completed:** 2026-07-21T12:58:08Z
- **Tasks:** 1
- **Files modified:** 6 new files

## Accomplishments

- Implemented exact `base -> paper_type -> venue -> project -> run` resolution independent of input mapping order, with canonical token hashes, prior-value history, source provenance, and visible nonblocking advisory caveats.
- Locked the six generic truth controls to exact base values and restricted venue hard policy—including both `requires_pdf=true` and `requires_pdf=false`—to the current frozen official rule/template source pair.
- Added complete contract freeze validation for official-source freshness, schema completeness, evidence/result/source closure, outline integrity, immutable dependency slices, replayed token provenance, and injected verified result/receipt facts.
- Replaced overwrite-capable persistence with unique temporary files and atomic create-once publication; identical retries are idempotent and different concurrent snapshots cannot replace the first freeze.
- Added domain-neutral base tokens, all six registered paper-type overlays, and AI-research defaults whose structure/voice/caption/visual choices remain advisory under the 90/10 usability boundary.

## Task Commits

1. **TDD RED: Define manuscript contract behavior gates** - `3ef6967`
2. **TDD GREEN: Implement resolver, profiles, and frozen contract** - `a8e84b0`
3. **Security fix: Close provenance, receipt, and concurrent-freeze bypasses** - `15f16e1`

## Verification

- `python -m pytest tests/test_manuscript_contract.py tests/test_manuscript_schema_contracts.py -q` passed all 73 tests.
- `python -m pytest tests/test_manuscript_contract.py -q` passed all 37 new behavior/security tests.
- `python -m pytest tests/test_manuscript_schema_contracts.py -q` passed all 36 central schema regressions.
- `ruff check tools/manuscript_contract.py tools/_manuscript_contract_validation.py tests/test_manuscript_contract.py` passed.
- `python -m compileall -q tools/manuscript_contract.py tools/_manuscript_contract_validation.py` passed.
- Mandatory AppSec rereview returned PASS with all three original High findings closed inside the 01-11 boundary.

## Files Created

- `tools/manuscript_contract.py` - public token resolver, profile loader, canonical contract hash, verified freeze boundary, and explicit descendant closure.
- `tools/_manuscript_contract_validation.py` - focused semantic/source validation plus create-once atomic persistence; split keeps the public module below 800 lines.
- `tests/test_manuscript_contract.py` - 37 cascade, authority, hash, freshness, closure, path, concurrency, secret, and invalidation regressions.
- `profiles/paper_design_tokens/base.yaml` - small generic truth-hard core and portable advisory presentation defaults.
- `profiles/paper_design_tokens/paper_types.yaml` - advisory overlays for `METHOD`, `EMPIRICAL`, `DATASET`, `SYSTEMS`, `THEORY`, and `POSITION_SURVEY`.
- `profiles/paper_design_tokens/ai_research.yaml` - AI-research advisory defaults without venue dates, credentials, host paths, or model/provider constants.

## Decisions Made

- The registered closed schema remains unchanged. `resolve_paper_design_tokens()` returns rich replayable provenance/caveats, while `freeze_manuscript_contract()` deterministically replays it and persists only the schema-authorized resolved snapshot plus all hashed source references.
- The 90/10 rule is treated as a usability boundary, not a hard/advisory token-count ratio: scientific truth and official submission rules fail closed; prose and presentation preferences produce caveats only.
- Official-source staleness is caller policy through injected `now` and `max_official_age`; the reducer does not invent a permanent venue freshness interval.
- Result authenticity is accepted only through an injected verifier returning exact verified result/receipt refs and hashes. This plan does not duplicate the separate cryptographic executor-verification implementation.
- Contract publication uses a filesystem create-once primitive; if the filesystem cannot provide it, freeze fails instead of silently falling back to overwrite semantics.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing Critical Security] Closed post-resolution contract forgery paths**

- **Found during:** Mandatory AppSec review after the GREEN commit
- **Issue:** A caller could have supplied a handcrafted resolved-token snapshot, self-certified frozen result/receipt hashes, or raced two overwrite-capable freezes.
- **Fix:** Required deterministic resolver replay and complete override-source closure, added exact hard-token authority/value enforcement, required injected verified result/receipt facts, broadened secret scanning, and implemented unique create-once atomic publication.
- **Files modified:** `tools/manuscript_contract.py`, `tools/_manuscript_contract_validation.py`, `tests/test_manuscript_contract.py`
- **Verification:** The suite increased from 67 to 73 passing tests; AppSec rereview returned PASS with no remaining blocker.
- **Committed in:** `15f16e1`

**2. [Rule 2 - AGENTS.md compliance] Split semantic validation from the public resolver**

- **Found during:** GREEN implementation quality check
- **Issue:** The first single-file implementation exceeded the repository's roughly 800-line limit.
- **Fix:** Moved semantic/source validation and secure create-once persistence into a private focused helper; the public module is 797 lines and the helper is 440 lines.
- **Files modified:** `tools/manuscript_contract.py`, `tools/_manuscript_contract_validation.py`
- **Verification:** Ruff, compileall, and all 73 focused tests pass after the split.
- **Committed in:** `a8e84b0`, `15f16e1`

---

**Total deviations:** 2 auto-fixed (2 missing critical correctness/security requirements)
**Impact on plan:** Both changes enforce the plan's stated threat model and repository quality rules without modifying the registered schema, adding a dependency, or expanding into a later plan.

## Issues Encountered

- The closed schema has no fields for full override history or advisory caveats. The resolver therefore retains rich provenance for audit/replay, and freeze verifies that evidence before projecting the schema-safe token snapshot; no semantic data is hidden inside a token value.
- The research specification does not define a universal numerical staleness interval. Freshness is explicitly injected per run rather than hardcoded into the generic control plane.

## Known Stubs

None. The injected result/receipt verifier is an intentional trust-boundary dependency: any contract containing results fails closed when verified facts are not supplied.

## User Setup Required

None - no package, credential, server, or external service configuration was added.

## Next Phase Readiness

Subsequent authoring work can consume one canonical contract hash, schema-safe resolved tokens, explicit dependency slices, and targeted descendant invalidation. A real operated recipe must inject current venue freshness policy and the existing external executor receipt-verification boundary before freezing contracts that reference results.

## Self-Check: PASSED

All six implementation/test/profile files and this summary exist on disk; RED `3ef6967`, GREEN `a8e84b0`, and security fix `15f16e1` resolve as commits; the final 73-test command, Ruff, compileall, AppSec rereview, and summary whitespace checks passed.

---
*Phase: 01-operated-ai-manuscript-authoring*
*Completed: 2026-07-21*
