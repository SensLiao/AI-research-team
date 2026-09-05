---
name: manuscript-integrator
spec_version: "1.0.0"
model: none
capability_requirements:
  reasoning_quality: frontier
  context_requirement: long
  tool_use: true
  provider: any
stage: ANALYZE
kind: deterministic adapter specification
tools: []
produces: manuscript_integration
permission_scope:
  read: [task_frame, scheduler authorization receipt, frozen manuscript contract, every authorized manuscript_section_bundle, manuscript synthesis revision, manuscript_asset_manifest, official template and token snapshot, deterministic validation receipts]
  write: [runs/<run>/evidence/ANALYZE/ integration proposal, runs/<run>/source/ only through validated tools/manuscript_integrator.py atomic adapter]
  never: [direct or unmanaged filesystem writes, build/, director-review/, vault writes, promotion, downloader or direct network access, secrets or credential stores, arbitrary shell or subprocess, GPU execution, run infrastructure, reviewer conclusions, unauthorized bundles or assets, drafting missing prose evidence results citations or numbers, PDF or build claims]
---

# manuscript-integrator - single canonical integration owner

This is the contract for the deterministic `tools/manuscript_integrator.py` adapter, not an LLM seat. The serial synthesis editor has already finished prose. The adapter reads the direct LaTeX/TSV/Markdown/BibTeX working tree, performs necessary structural checks once at the freeze boundary, and atomically publishes canonical `source/`.

## North-star discipline

Read the north star, required outline, terminology, notation, bibliography, asset plan, official template, and tokens from the frozen `manuscript_contract`. Improve coherence only within those facts. Do not silently change the paper's claim, scope, evidence, execution status, or venue contract.

## Exact-one completeness gate

Before any integration proposal or canonical write request:

1. Derive `required_sections` from every frozen outline entry with `required: true`; do not use a hardcoded section count.
2. Require exactly one candidate `manuscript_section_bundle` for every required `section_id`.
3. Require the multiset of candidate `section_id` values to equal the required-section set exactly: reject missing, duplicate, unknown, optional-only, mismatched, or unauthorized IDs.
4. Verify each bundle's assigned worker role, scheduler receipt, bundle sha256, `content_hash`, dependency refs, and identical `manuscript_snapshot_sha256`.
5. Preserve specialized ownership for introduction, related work, methods, and results; accept parameterized bundles only for their explicitly assigned remaining sections.
6. Verify every referenced asset against the provenance manifest, stable label, source/result refs, permission, output facts, and sha256 values.

Any exact-one, hash, authorization, or required-asset failure blocks the canonical write. Never fill a missing section with generated transition text and never silently omit it.

## Reconciliation and canonical-write contract

1. Read the released `draft/synthesis/sections/*.tex`, `draft/refs.bib`, `MANUSCRIPT-ONTOLOGY.md`, and closure handoff directly from disk; never accept manuscript prose or `bibliography_text` embedded in JSON.
2. Derive citations, labels, cross-references, file inventory, and the one stage receipt from those files. Do not ask an agent to duplicate them.
3. Apply the frozen template and safe structural normalization only; never create evidence, results, citation identity, labels, or scientific prose.
4. Atomically publish one run-owned canonical tree. Hash only this freeze boundary, not every prose handoff.
5. The tree inventory must contain exactly one `main.tex`, exactly one `refs.bib`, all required section files, the asset manifest, and their sha256 values. A new tree yields a new immutable `source_tree_sha256` and invalidates reviews bound to an older hash.
6. Do not invoke TeX, write `build/` or `director-review/`, or assert a PDF. Build truth belongs to the isolated build adapter.

## Claim-surface and citation closure

1. Enforce the frozen `claim_surface_owner` ledger: every load-bearing claim has **one canonical locus**. A repeated abstract/conclusion compression must point back to that locus and retain the same boundary; every other **duplicate claim** becomes a **cross-reference**, a genuinely section-specific implication, or an unresolved interface. Never inflate perceived evidence by repeating one claim with different wording.
2. Build a `citation_adjacency_ledger` over the integrated text. Each factual or comparative sentence records its sentence/paragraph anchor, claim ID, citation key(s), and exact admitted evidence loci. Citations must be **sentence-adjacent** to the proposition they support; a paragraph-end **citation dump**, orphan citation, or one key stretched over heterogeneous claims is unresolved.
3. Materialize every used key as an **actual BibTeX entry** in `refs.bib` from the verified identity record: entry type, authors, title, year, venue/publisher, DOI/URL or stable identifier when available, version, and provenance hash. Do not emit placeholders, prose bibliography rows, guessed fields, duplicate identities under different keys, or unused decorative entries.
4. Require bidirectional closure before the adapter writes: every in-text key resolves to exactly one `refs.bib` entry; every entry is cited; every load-bearing cited sentence resolves through the adjacency ledger to an admitted exact locus; bibliography identity and claim entailment both pass independently.

## Output contract

The adapter emits one `manuscript_integration` stage receipt conforming to `schemas/manuscript_integration.schema.json`. It is derived from disk and binds the final canonical inventory/source-tree hash; no LLM authors this JSON.

## Quality Bar

- Required-section ownership and bundle presence are exact-one, adaptive, and deterministically checkable.
- All candidate and asset hashes close before any canonical write.
- No unresolved interface is hidden or “resolved” with invented content.
- Claim-surface ownership, duplicate-claim disposition, actual BibTeX identity, and sentence-adjacent citation closure are complete.
- Only this capability through the deterministic adapter can create or replace the final run-owned source tree.
- Canonical source creation remains separate from build, review, report, vault, and promotion paths.

## Handback

Hand back the `manuscript_integration` schema artifact ref and sha256, `integration_hash`, `manuscript_snapshot_sha256`, complete section/asset hash inventory, `source_tree_sha256` if the adapter wrote a valid tree, and all unresolved interfaces. Report whether the exact-one gate passed; never draft or backfill a missing section.
