---
phase: 01-operated-ai-manuscript-authoring
plan: "19"
subsystem: operated-manuscript-registry
tags: [operate, registry, catalog, connectivity]
status: complete
completed: 2026-07-22
---

# Phase 01 Plan 19: Operated Registry Promotion Summary

`manuscript_authoring` and `manuscript_review` are now two distinct, truthful one-button operated modes. The runtime registry, YAML catalog, connectivity checks, and capability catalog agree on exactly twelve operated modes.

## Delivered

- Registered the two concrete Python recipes separately in `operate/modes/__init__.py`.
- Promoted only their corresponding YAML records to `operated: true` and removed their obsolete spec-only maturity declarations.
- Added exact runtime/YAML/catalog parity checks, including rejection of a YAML-only operated claim and the obsolete `manuscript_review_pack` id.
- Updated operated inventory and role-connectivity tests without changing the existing modes or requiring a fixed manuscript worker count.
- Closed two real lifecycle-wiring gaps found by the new generic smoke test: every authoring prompt now carries the NORTH STAR/capability tier, and an unfrozen fresh run exposes no fabricated ANALYZE panel.

## Verification

- `python -m pytest tests/test_operate_manuscript_authoring.py tests/test_operate_manuscript_review.py tests/test_operate_wiring.py tests/test_operate_wave1_modes.py -q` — 96 passed.
- `python -m pytest tests/test_agent_connectivity.py tests/test_capability_catalog.py tests/test_operate_wiring.py -q` — 56 passed.

## Task Commits

1. `d3beb03` — make the authoring wiring stage-safe.
2. `bc2785e` — declare authoring worker capabilities.
3. `13d6c8e` — register the two operated manuscript modes and synchronize the catalog.

## Boundaries Preserved

- The authoring and review recipes remain separate run ids, evidence namespaces, lifecycles, and director-facing products.
- The obsolete `manuscript_review_pack` alias does not exist.
- This registry promotion does not write the vault, submit a paper, execute GPU work, or claim a compiled PDF without its receipt.

## Next Readiness

Plan 20 owns environment pins, entry-point documentation, cross-platform evidence, and the final completion gate.
