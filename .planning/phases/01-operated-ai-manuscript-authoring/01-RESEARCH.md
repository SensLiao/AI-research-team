# Phase 1: Operated AI Manuscript Authoring - Research

**Researched:** 2026-07-21  
**Domain:** Native operated multi-agent scientific manuscript authoring, deterministic evidence auditing, and truthful LaTeX delivery  
**Confidence:** HIGH

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

#### Product and evidence boundaries

- **D-01:** `manuscript_authoring` and manuscript review/rebuttal are separate operated products. They may share deterministic utilities and schemas, but generation evidence and independent review evidence remain distinct.
- **D-02:** A mode becomes `operated` only after a concrete `operate/modes/` recipe, registry mirror, worker contract, deterministic reducer, director-facing renderer, and operated tests exist. Registry-only entries remain spec-only.
- **D-03:** Authoring reads the sibling PhD-Research-OS only through bounded recall/reference paths. It never writes the database and never invokes promotion; drafts and build artifacts remain run scratch.
- **D-04:** The phase adds no OpenAlex PDF/content downloader, bulk acquisition, or automatic PDF fetch. OpenAlex remains an optional metadata provider inside the existing search engine.

#### Venue and local-first literature

- **D-05:** Paper type and a realistic top-tier venue family are frozen before drafting. Official current venue requirements are authoritative; community rankings and CCF A-class or equivalent labels guide candidate selection but are not hardcoded as permanent truth.
- **D-06:** Local evidence coverage is explicit, not assumed. The assessment covers at least related comparison, technical method, implementation detail, dataset, metric/evaluation, and relevant industry prior art, with traceable local source references.
- **D-07:** Only a named coverage deficit creates a targeted query plan for the existing `paper_search` path. A network/provider failure is recorded separately from a genuine no-result state and cannot be interpreted as evidence absence.
- **D-08:** Search results are references for follow-up evidence work, not manuscript-ready support by default. No retrieved metadata row may silently become an entailed citation or a locally owned full-text source.

#### Paper Design Tokens and frozen context

- **D-09:** Resolve and hash Paper Design Tokens in the order `base -> paper type -> venue -> project -> run override`. The resolved snapshot, provenance of every override, and source hashes are frozen before author waves begin.
- **D-10:** The small hard-rule set covers official template/anonymity, claim-number-citation traceability, terminology/notation consistency, figure/table provenance, compile/cross-reference integrity, and no fabrication. A lower layer or run override cannot weaken these rules.
- **D-11:** Section shape, paragraph rhythm, voice, rhetorical pattern, caption preference, visual taste, and most formatting guidance are advisory. Advisory conflicts produce a recommendation or caveat, not a daily-delivery block.
- **D-12:** The frozen manuscript snapshot contains the paper brief, paper type, venue profile, outline, claim ledger, evidence/result references, terminology and notation glossary, bibliography state, figure/table plan, resolved tokens, and dependency slices.

#### Parallel authoring and integration

- **D-13:** Required capabilities include venue/corpus reconnaissance, paper architecture, evidence stewardship, section authorship, figure/table engineering, manuscript integration, independent factual/citation/style/LaTeX audit, and submission packaging. These are capability roles, not a requirement for one fixed worker per label.
- **D-14:** Use a sparse dependency DAG and scheduler authorization receipts. Each worker receives the frozen common snapshot plus only declared predecessor slices; independent auditors do not see conclusions they are meant to judge blindly.
- **D-15:** One integrator owns the canonical manuscript state and reconciles cross-section terminology, notation, claims, citations, numbers, labels, figures, and narrative flow. Section agents never write directly into the integrated manuscript tree.
- **D-16:** Exact worker count, wave count, and section partition may adapt to paper type and complexity, provided the required capabilities, independence boundaries, and deterministic contracts remain satisfied.

#### LaTeX, figures, and build truth

- **D-17:** Produce a native, run-owned LaTeX source tree with `main.tex`, `refs.bib`, section files, figure/table manifests, build metadata, and a deterministic quality report.
- **D-18:** Detect an external LaTeX engine at runtime and invoke it through an argument-safe subprocess contract. A successful build must bind the PDF hash, command receipt, log, and source snapshot; missing tooling yields `TOOLCHAIN_MISSING` and never a fabricated PDF claim.
- **D-19:** Local director-owned figure sources are immutable inputs. The run copies or renders into run-owned paths, records source hashes and reproducible commands, and never silently overwrites the original asset.
- **D-20:** Every included figure/table owns a stable label, caption, source/result references, and provenance entry. Cross-reference and asset-existence checks run before a submission-ready verdict.

#### Delivery and quality policy

- **D-21:** Daily delivery states are `USABLE`, `USABLE_WITH_CAVEATS`, `NEEDS_SUPPLEMENT`, and `BLOCK`. Readable manuscript output remains visible when only advisory style, completeness, or toolchain issues exist.
- **D-22:** Missing/fabricated core sources, unsupported core claims or numbers, false execution/PDF claims, permission/path violations, secret leakage, or irrecoverably corrupt inputs hard-block daily delivery. Submission readiness separately requires every official, scientific, citation, anonymity, cross-reference, and compilation requirement that applies.
- **D-23:** Human-first Markdown under `director-review/` is the entry point. JSON bundles, source hashes, logs, LaTeX trees, and PDFs are evidence/archive products referenced by the Markdown packet.
- **D-24:** The end-to-end fixture must exercise a sufficient-local-evidence branch and a documented-deficit branch, plus compiler-present or deterministic fake-compiler behavior and a real `TOOLCHAIN_MISSING` branch.

### the agent's Discretion

- Choose the exact LaTeX engine priority order, subprocess timeout defaults, source-tree module names, schema filenames, and renderer module boundaries using existing repository conventions and cross-platform tests.
- Choose section-role granularity and optional specialist skips from paper type and evidence state; required capability coverage and independent truth audits may not be skipped.
- Choose advisory prose defaults and AI-research token overlay values from current official/top-paper evidence gathered in the AI integration phase; do not hardcode transient venue dates or rules into generic control-plane code.

### Deferred Ideas (OUT OF SCOPE)

- Lawful automatic open-access acquisition or large corpus construction is not part of this phase.
- Live GPU experiment execution remains gated by the existing external executor/server path.
- Autonomous venue submission and automatic vault promotion remain director-only decisions outside authoring.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| OPER-01 | The director can start and resume a one-button `manuscript_authoring` run through the existing validated, checkpointed, tamper-evident operated lifecycle. | Extend the native recipe/registry/spine pattern; mirror-test operated status. [VERIFIED: `.planning/REQUIREMENTS.md`, `operate/modes/__init__.py`] |
| OPER-02 | The director can run manuscript review/rebuttal through a distinct operated recipe that consumes a manuscript without conflating review evidence with generation evidence. | Add a separate `manuscript_review.py` recipe bound to a frozen manuscript hash and read-only review inputs. [VERIFIED: `01-CONTEXT.md`, `01-AI-SPEC.md`] |
| OPER-03 | Capability facts and the mode registry expose authoring or review as operated only when the corresponding concrete recipe exists and is runnable. | Reuse the executable-registry mirror invariant and its wiring/catalog tests. [VERIFIED: `operate/modes/__init__.py`, `PLATFORM-FACTS.md`] |
| PREP-01 | Before drafting, the run selects and freezes a paper type and realistic target-venue family, prioritizing current top AI or CCF A-class-equivalent venues while treating official venue rules as authoritative. | Freeze a dated, hash-bound `venue_profile` and paper-type contract before author dispatch. [VERIFIED: `01-CONTEXT.md`, `01-AI-SPEC.md`] |
| PREP-02 | Before parallel authoring, the run freezes a manuscript snapshot containing the paper brief, outline, claim ledger, evidence/result references, terminology/notation, venue profile, bibliography state, figure/table plan, and resolved Paper Design Tokens. | Introduce a schema-validated canonical snapshot and make its hash part of every worker input contract. [VERIFIED: `01-AI-SPEC.md`] |
| PREP-03 | Paper Design Tokens resolve deterministically with precedence `base -> paper type -> venue -> project -> run override`. | Implement a pure merge/provenance/hash reducer with table-driven TDD. [VERIFIED: `01-CONTEXT.md`] |
| PREP-04 | The resolved token contract distinguishes the small hard-rule set—official template/anonymity, traceability, terminology/notation, figure provenance, compile/cross-reference integrity, and no fabrication—from advisory structure, voice, caption, rhetoric, and formatting guidance. | Type every token as hard or advisory and reject downstream weakening only for hard rules. [VERIFIED: `01-CONTEXT.md`, `01-AI-SPEC.md`] |
| EVID-01 | Each authoring run recalls and reads relevant papers and notes from the read-only PhD-Research-OS database first, then emits an explicit local-literature coverage assessment. | Use the existing recall seam and a six-dimension local coverage artifact before any network fallback. [VERIFIED: `.planning/REQUIREMENTS.md`, `tools/recall.py` boundary documented in codebase map] |
| EVID-02 | Only a documented comparison, implementation, method, dataset, metric, or industry-prior-art deficit activates the existing paper-search engine, and network/search failure remains distinguishable from genuine evidence absence. | Add an explicit coverage state machine: `sufficient`, `deficit`, `provider_failure`, `unverified`; only `deficit` may call `paper_search`. [VERIFIED: `01-AI-SPEC.md`, `.planning/codebase/CONVENTIONS.md`] |
| EVID-03 | The authoring and review paths contain no OpenAlex PDF downloader, bulk-download/content API, corpus-construction, or automatic PDF acquisition path; OpenAlex may remain metadata-only inside the existing search engine. | Keep retrieval behind the existing metadata-only port and add negative tool-trace/code-path tests. [VERIFIED: `PLATFORM-FACTS.md`, `.planning/codebase/CONCERNS.md`] |
| ORCH-01 | Authoring runs use a sparse dependency DAG with explicit venue/corpus reconnaissance, paper architecture, evidence stewardship, section author, figure/table, integration, independent factual/citation/style/LaTeX audit, and submission-packaging roles. | Copy the `READ_PAPER_PARALLEL_GROUPS`/`WORKER_DEPENDENCIES` pattern, with explicit capability coverage and `group_barriers=False`. [VERIFIED: `operate/modes/read_paper_deep.py`] |
| ORCH-02 | Each section author receives the frozen shared context plus only its declared dependency slice, and one integrator owns terminology, notation, claim, citation, number, figure, and cross-section coherence. | Reuse scheduler input contracts and enforce a single canonical writer for `source/`. [VERIFIED: `operate/modes/read_paper_deep.py`, `01-AI-SPEC.md`] |
| LATX-01 | The run produces a native LaTeX project containing `main.tex`, `refs.bib`, section files, figure/table manifests, build metadata, and a deterministic quality report. | Define a run-owned source/build split and schema-bind all emitted files and hashes. [VERIFIED: `01-CONTEXT.md`, `01-AI-SPEC.md`] |
| LATX-02 | The run detects an available LaTeX engine and builds a real PDF when possible; otherwise it reports `TOOLCHAIN_MISSING`, delivers the complete source project, and never claims that a PDF was compiled. | Use argument-list subprocesses, bounded multipass builds, and a receipt-gated build state. [VERIFIED: supplied local LaTeX command evidence, `01-AI-SPEC.md`] |
| ASST-01 | Every included figure and table has provenance, caption/label ownership, source/result references, and either a local source asset or reproducible generation/rendering command, without silently overwriting director-owned assets. | Copy/hash director inputs into run-owned paths; validate manifest ownership, labels, refs, commands, and non-overwrite. [VERIFIED: `01-CONTEXT.md`, `01-AI-SPEC.md`] |
| AUDT-01 | Deterministic audits cover abstract/body/conclusion claim closure, claim-evidence entailment references, result numbers against frozen sources, BibTeX/in-text citation closure, terminology/notation, labels/cross-references, required sections, anonymity, official venue constraints, LaTeX compilation, and PDF existence whenever compilation is claimed. | Split deterministic audit functions by truth domain, then reduce them against one immutable manuscript hash. [VERIFIED: `01-AI-SPEC.md`] |
| DELV-01 | The run delivers human-first outputs under `director-review/` plus machine evidence bundles, including a manuscript overview, local-literature coverage report, authoring plan, LaTeX source tree, compiled PDF when available, quality report, reviewer report, and submission checklist. | Reuse Markdown-first packet assembly and add manuscript-specific renderers; JSON remains evidence/archive. [VERIFIED: `PLATFORM-FACTS.md`, `operate/modes/read_paper_deep.py`] |
| DELV-02 | The run reports `USABLE`, `USABLE_WITH_CAVEATS`, `NEEDS_SUPPLEMENT`, or `BLOCK`; readable work survives advisory defects, only truth/permission/irrecoverable-input/false-execution defects hard-block daily delivery, and submission readiness remains strict. | Implement a pure status reducer with exhaustive truth-table tests and a separate strict submission-ready predicate. [VERIFIED: `01-CONTEXT.md`, `operate/modes/read_paper_deep.py`] |
| SAFE-01 | Authoring and review keep PhD-Research-OS read-only and never copy a draft, search result, manuscript, or PDF into it without a later explicit top-level `/promote-to-vault` command. | Route reads through recall; fence all writes to the run; assert vault tree unchanged in negative tests. [VERIFIED: `AGENTS.md`, `01-CONTEXT.md`] |
| SAFE-02 | Secrets never appear in request URLs, error artifacts, logs, generated LaTeX, build metadata, or director-review outputs. | Repair scholar URL sanitization first and apply one deterministic secret scan before commit/report. [VERIFIED: `.planning/codebase/CONCERNS.md`] |
| SAFE-03 | The capability does not run GPU experiments and accepts execution claims only from frozen, auditable result artifacts rather than scripts, model-authored metrics, or unsupported prose. | Do not bind `execute/`; validate result refs and forbid execution language inconsistent with frozen receipts. [VERIFIED: `PLATFORM-FACTS.md`, `01-AI-SPEC.md`] |
| PLAT-01 | The local CLI, path handling, fixtures, and optional LaTeX tool detection operate on the repository's supported Python runtime on Windows and Linux. | Use `pathlib`, portable relative refs, environment-derived MiKTeX discovery, `shell=False`, and platform/fake-toolchain tests. [VERIFIED: `.planning/codebase/CONVENTIONS.md`, supplied local toolchain evidence] |
| PLAT-02 | The control plane remains domain-general, with AI-research defaults supplied through profile or Paper Design Token overlays rather than hardcoded domain rules. | Put paper/venue/domain settings in overlays and keep orchestration generic. [VERIFIED: `AGENTS.md`, `.planning/codebase/ARCHITECTURE.md`] |
| VERI-01 | A local-first end-to-end fixture reaches frozen context, dependency-safe authoring bundles, integration, LaTeX generation, quality gates, director-review Markdown, and honest PDF build status. | Build one hermetic authoring fixture and assert every durable output plus build-state truth. [VERIFIED: `01-AI-SPEC.md`] |
| VERI-02 | Automated tests prove sufficient local evidence suppresses online search, explicit deficits activate only the existing search engine, search failures remain explicit, and no OpenAlex download code path exists. | Use injected transports/call capture; never contact live providers. [VERIFIED: `.planning/codebase/TESTING.md`] |
| VERI-03 | Automated tests prove token cascade precedence and hard-rule versus advisory-rule separation. | Use table/property-style tests before implementing the resolver. [VERIFIED: `01-AI-SPEC.md`] |
| VERI-04 | Negative-path tests reject or surface unsupported citations/numbers, false execution claims, database writes, unsafe paths, missing required roles, inconsistent terminology/labels, secret leakage, and false PDF claims at the correct gate. | Create a failure matrix over deterministic validators and operated recipe transitions. [VERIFIED: `01-AI-SPEC.md`] |
| VERI-05 | Relevant unit, integration, operated-mode, AI-eval, security, and completion verification commands pass and leave inspectable evidence artifacts. | Define focused per-task commands, mode integration commands, and the final full-suite gate below. [VERIFIED: `.planning/codebase/TESTING.md`] |
</phase_requirements>

## Summary

Phase 1 should be implemented as two native operated products—`manuscript_authoring` and `manuscript_review`—that share deterministic contracts but never share authorship and independent-review evidence. The repository already has the necessary control-plane primitives: executable recipe registration, sparse dependency scheduling, frozen input receipts, schema validation, hash-linked supplements, resumable run state, bounded vault recall, and Markdown-first reporting. The strongest implementation analogue is `operate/modes/read_paper_deep.py`, especially its `ARTIFACT_PLAN`, `READ_PAPER_PARALLEL_GROUPS`, `WORKER_DEPENDENCIES`, `_worker_input_contract()`, `llm_step()`, `_load_worker_bundles()`, `_discover_dets()`, `_report()`, and `run_dets_with_repair()` boundaries. [VERIFIED: `operate/modes/read_paper_deep.py`, `.planning/codebase/ARCHITECTURE.md`]

The implementation should add no runtime package and no second agent framework. The existing Draft 2020-12 `jsonschema` registry remains authoritative; worker output is candidate data, deterministic reducers own truth and status, and one integrator alone writes the canonical LaTeX tree. Local vault evidence is assessed first across six coverage dimensions. Only an explicit `deficit` may invoke the existing metadata search port; metadata cannot become citation support without a hash-bound local source and exact support. [VERIFIED: `01-AI-SPEC.md`, `01-CONTEXT.md`, `PLATFORM-FACTS.md`]

LaTeX delivery must be receipt-driven. On this Windows host, a real `latexmk` build has already demonstrated a successful toolchain; other hosts must still exercise and preserve `TOOLCHAIN_MISSING`, and a bounded direct `pdflatex`/bibliography fallback must remain available. A complete source tree is always deliverable, but only a real process exit, existing PDF, source/build receipt, and PDF SHA-256 may claim a compiled artifact. [VERIFIED: orchestrator-supplied local toolchain command evidence, `01-AI-SPEC.md`]

**Primary recommendation:** Build contract and truth reducers TDD-first, then wire the authoring DAG, canonical integrator/build adapter, separate blind review recipe, human renderer, and finally operated-status mirrors; do not mark either mode operated until its end-to-end and mirror tests pass.

## Project Constraints (from AGENTS.md)

- Keep THE MACHINE (`research_agent_teams/`) and THE DATABASE (`../AI agent database/PhD-Research-OS/`) separate; the machine reads by reference and writes the database only through an explicit top-level `/promote-to-vault`. [VERIFIED: `AGENTS.md`]
- Drafts, LaTeX trees, logs, PDFs, and machine evidence remain under run scratch; the primary human product is Markdown under `director-review/`. [VERIFIED: `AGENTS.md`, `PLATFORM-FACTS.md`]
- Never read or expose `.env`, private keys, credential stores, or token values; secret handling is fail-closed and outputs must redact sensitive request parameters. [VERIFIED: `AGENTS.md`, `.planning/codebase/CONCERNS.md`]
- Do not claim real GPU execution from scripts or model-authored numbers; this phase does not operate the external executor. [VERIFIED: `AGENTS.md`, `PLATFORM-FACTS.md`]
- Keep the control plane domain-general; domain rigor belongs in profiles and token overlays. [VERIFIED: `AGENTS.md`, `.planning/codebase/ARCHITECTURE.md`]
- Use durable run artifacts and command evidence for “done,” “compiled,” “secure,” or “release-ready” claims. [VERIFIED: `AGENTS.md`]
- Preserve the dirty worktree and isolate changes; do not bundle runtime ledgers, caches, generated artifacts, local databases, or secrets into commits. [VERIFIED: `AGENTS.md`, `.planning/codebase/CONCERNS.md`]
- New production core logic requires tests proportional to risk; validation, state, transformation, path, citation, build, and status logic should be planned TDD-first. [VERIFIED: `AGENTS.md`, `.planning/codebase/TESTING.md`]

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|--------------|----------------|-----------|
| Start/resume and operated truth | Operated workflow adapter | Run store | Recipe registration provides the product surface; manifest/ledger/checkpoints provide resumability and evidence. [VERIFIED: `.planning/codebase/ARCHITECTURE.md`] |
| Paper/venue contract and Paper Design Tokens | Deterministic domain tools | Operated recipe | Pure resolution, provenance, hashing, and hard-rule protection belong outside prompts; the recipe sequences them. [VERIFIED: `01-AI-SPEC.md`] |
| Local literature coverage | Deterministic domain tools | Vault recall/search ports | The reducer decides coverage state; vault recall supplies local refs and `paper_search` is a deficit-only fallback. [VERIFIED: `01-AI-SPEC.md`] |
| Parallel section authoring | Operated recipe/scheduler | Worker specifications | The recipe declares dependencies and slices; the external harness executes only scheduler-authorized workers. [VERIFIED: `operate/modes/read_paper_deep.py`] |
| Canonical manuscript integration | Deterministic integrator | Run-owned storage | Exactly one integrator reconciles bundles and atomically owns `source/`; workers remain inbox-only. [VERIFIED: `01-CONTEXT.md`] |
| LaTeX source/build truth | Deterministic build adapter | External TeX toolchain | Python owns safe discovery, invocation, receipts, hashes, and status; TeX executables only perform the isolated build. [VERIFIED: `01-AI-SPEC.md`] |
| Scientific/citation/number/venue audit | Deterministic audit tools | Independent review recipe | Mechanical closure is deterministic; scoped independent reviewers add scientific judgment against the same manuscript hash. [VERIFIED: `01-AI-SPEC.md`] |
| Human delivery | Manuscript renderer/director packet | Evidence store | Markdown is the entry point and links hash-verified source/PDF/evidence products. [VERIFIED: `PLATFORM-FACTS.md`] |
| Vault knowledge | Database/storage, read-only | Recall port | The phase may resolve references but has no write or promotion capability. [VERIFIED: `AGENTS.md`] |

## Standard Stack

### Core

| Library/tool | Version | Purpose | Why Standard |
|--------------|---------|---------|--------------|
| Native `research_agent_teams` operated framework | Repository contract v1/source hashes | Recipe, scheduler, run store, checkpoints, bounded repair, registry truth | It already owns the validated state and evidence model; a second framework would create conflicting sources of truth. [VERIFIED: `01-AI-SPEC.md`] |
| Python | 3.9.13 observed | Deterministic reducers, filesystem boundaries, subprocess adapter, CLI | This is the observed supported runtime for the repository. [VERIFIED: `01-AI-SPEC.md`] |
| `jsonschema` | 4.25.1 observed | Authoritative Draft 2020-12 payload validation | `PAYLOAD_SCHEMAS` and `validate_payload()` are the existing cross-runtime authority. [VERIFIED: `01-AI-SPEC.md`, `.planning/codebase/CONVENTIONS.md`] |
| PyYAML | 6.0.2 observed | Existing mode/profile/registry configuration | Existing registries use YAML; no replacement is needed. [VERIFIED: `01-AI-SPEC.md`] |
| pytest | 8.4.2 observed | Unit, contract, operated-mode, boundary, and end-to-end tests | Repository discovery and fixtures already use pytest. [VERIFIED: `.planning/codebase/TESTING.md`] |

### External/Supporting

| Tool | Version/availability | Purpose | Use policy |
|------|----------------------|---------|------------|
| MiKTeX | 25.12, per-user install | Windows TeX distribution | Optional external toolchain; record version and distribution in every real build receipt. [VERIFIED: orchestrator-supplied local command evidence] |
| Strawberry Perl | 5.42.2.1 | `latexmk` runtime on this host | External environment fact, not a Python dependency. [VERIFIED: orchestrator-supplied local command evidence] |
| `latexmk` | 4.88 | Preferred bounded multipass build driver | First choice when available; invoke with argument list, `shell=False`, no shell escape, recorder, and run-owned output. [VERIFIED: orchestrator-supplied local command evidence, `01-AI-SPEC.md`] |
| `pdflatex`, `xelatex`, `lualatex` | Available | TeX engines | Default direct fallback is bounded `pdflatex`; select Xe/Lua only when the frozen venue/token contract requires it. [VERIFIED: orchestrator-supplied local command evidence] |
| `bibtex`, `biber` | Available | Bibliography passes | Choose from the frozen bibliography contract and verify closure after bounded multipass compilation. [VERIFIED: orchestrator-supplied local command evidence] |
| `chktex` | Available; smoke exit 0 | Advisory/static LaTeX diagnostics | Record diagnostics; venue/scientific/build truth remains owned by deterministic gates. [VERIFIED: orchestrator-supplied local command evidence] |

### Explicitly Excluded

| Candidate | Disposition | Reason |
|-----------|-------------|--------|
| LangGraph, CrewAI, provider-native agent SDK | Do not add | They duplicate the native scheduler/checkpoint/evidence boundary and create a second control plane. [VERIFIED: `01-AI-SPEC.md`] |
| Pydantic v2 | Do not add in Phase 1 | It may be a future optional typing adapter, but JSON Schema remains authoritative and this phase authorizes no new runtime dependency. [VERIFIED: `01-AI-SPEC.md`] |
| New vector DB, embedding stack, tracing/eval service | Do not add | Existing recall/search/run-store/pytest boundaries cover the phase. [VERIFIED: `01-AI-SPEC.md`] |
| OpenAlex/full-text downloader or corpus builder | Prohibited | The locked scope permits metadata-only OpenAlex through the existing search engine. [VERIFIED: `01-CONTEXT.md`] |
| FlowCopilot or an external paper-agent framework | Do not add | Borrow concepts only; Research Agent Teams remains the sole control plane. [VERIFIED: `01-CONTEXT.md`, `01-AI-SPEC.md`] |

**Installation:** None. This phase must not add a runtime package or publish an invented `pip install` command. External TeX detection is optional runtime capability, not a repository dependency. [VERIFIED: `01-AI-SPEC.md`]

## Package Legitimacy Audit

This phase installs no external package, so the package-legitimacy gate is not applicable. Existing observed packages are not newly recommended installations, and no registry lookup was used to elevate package provenance. [VERIFIED: phase constraint and bounded research scope]

**Packages removed due to `[SLOP]` verdict:** none.  
**Packages flagged as suspicious `[SUS]`:** none.  
**Planner rule:** any later proposal to add a package is a scope change and must run the package-legitimacy protocol plus a human verification checkpoint before installation.

## Existing Analogs and Proposed Ownership

### Exact existing files and symbols to reuse

| Existing file | Exact symbol/boundary | Reuse |
|---------------|-----------------------|-------|
| `operate/modes/read_paper_deep.py` | `ARTIFACT_PLAN`, `READ_PAPER_PARALLEL_GROUPS`, `WORKER_DEPENDENCIES`, `OPTIONAL_SPECIALISTS` | Declare explicit capability artifacts, sparse release hints, data dependencies, and justified specialist skips. [VERIFIED: file inspection] |
| `operate/modes/read_paper_deep.py` | `_active_worker_agents()`, `_write_shared_paper_representation()`, `_worker_input_contract()`, `llm_step()` | Materialize frozen shared facts, generate least-privilege input slices, and expose a scheduler-ready worker panel. [VERIFIED: file inspection] |
| `operate/modes/read_paper_deep.py` | `_load_worker_bundles()`, `_data_descendants()`, `_validate_all_payloads()` | Resolve effective supplements, compute refresh descendants, and preserve readable output around non-truth schema advisories. [VERIFIED: file inspection] |
| `operate/modes/read_paper_deep.py` | `_discover_dets()`, `_write_markdown_card()`, `_delivery_advisory_summary()`, `_report()`, `run_dets()`, `run_dets_with_repair()` | Separate worker ingestion, deterministic truth, readable rendering, report state, and bounded targeted repair. [VERIFIED: file inspection] |
| `operate/modes/read_paper_deep.py` | `_shared.extract_worker_bundle_value()`, `_shared.normalize_worker_payload()`, `_shared.run_drift_gate()`, `_shared.run_existence_gate()`, `_shared.budget()` | Reuse shared gates and normalization rather than recreating mode-local variants. [VERIFIED: file inspection] |
| `operate/panel_scheduler.py` | `schedule_next_wave()` | Authorize dependency-safe work; `parallel_groups` remain hints, not execution. [VERIFIED: `01-AI-SPEC.md`] |
| `operate/artifacts.py` | `GateBlock`, `TargetedGateBlock`, `write_artifact()` | Fail closed on truth violations, target repairable defects, and write validated envelopes. [VERIFIED: `operate/modes/read_paper_deep.py`] |
| `operate/bounded_repair.py` | `attempt_with_repair()` | Limit structural/targeted retries and retain hash-linked supplements. [VERIFIED: `operate/modes/read_paper_deep.py`] |
| `operate/output_versions.py` | `resolve_effective_output()` | Resolve immutable original-plus-supplement lineage. [VERIFIED: `operate/modes/read_paper_deep.py`] |
| `tools/validate_artifact.py` | `PAYLOAD_SCHEMAS`, `validate_payload()` | Register and enforce every new JSON Schema before dependency visibility and commit. [VERIFIED: `01-AI-SPEC.md`, `.planning/codebase/CONVENTIONS.md`] |
| `tools/runstore.py` | `read_manifest()` plus existing atomic manifest/ledger/checkpoint boundary | Bind contract, manuscript, build, and review hashes to resumable state. [VERIFIED: `01-AI-SPEC.md`, `.planning/codebase/ARCHITECTURE.md`] |
| `tools/paper_search.py` | `search_many()` and existing injected transport boundary | Execute only coverage-authorized query plans and preserve provider failure separately from no result. [VERIFIED: `.planning/codebase/CONVENTIONS.md`, `.planning/codebase/TESTING.md`] |
| `tools/scholar_clients.py` | `ScholarLookupError`, `default_transport()`, `_fetch_parse()`, `_openalex_params()` | Preserve lookup-error semantics and fix URL redaction before persistence. [VERIFIED: `.planning/codebase/CONVENTIONS.md`, `.planning/codebase/CONCERNS.md`] |
| `tools/recall.py` | Bounded read-only recall port | Read vault evidence by reference only. [VERIFIED: `.planning/codebase/ARCHITECTURE.md`] |
| `tools/director_packet.py` | Existing director-packet assembly boundary | Keep `director-review/00-REVIEW-PACKET.md` as the primary entry point. [VERIFIED: `01-CONTEXT.md`, `.planning/codebase/ARCHITECTURE.md`] |
| `tools/path_boundaries.py`, `tools/scope_guard.py` | Existing run/vault path fences | Reject traversal, vault writes, symlink/reparse escapes, and unowned outputs. [VERIFIED: `01-CONTEXT.md`, `.planning/codebase/ARCHITECTURE.md`] |
| `operate/modes/__init__.py` | `REGISTRY` | Add each mode only after its complete operated product exists. [VERIFIED: file inspection] |
| `tests/test_operate_read_paper_deep.py` | Nearest operated-panel regression suite | Copy test shape for waves, bundles, targeted supplements, readable delivery, and report products. [VERIFIED: `.planning/codebase/CONVENTIONS.md`, `.planning/codebase/CONCERNS.md`] |
| `tests/test_operate_wiring.py`, `tests/test_capability_catalog.py` | Registry/fact mirror gates | Prevent spec-only capability from being reported as operated. [VERIFIED: `operate/modes/__init__.py`, `01-AI-SPEC.md`] |
| `tests/test_panel_scheduler.py`, `tests/test_validate_artifact.py`, `tests/test_scope_guard.py` | Scheduler, schema, and path boundary suites | Extend native contracts rather than mocking them. [VERIFIED: `.planning/codebase/ARCHITECTURE.md`] |
| `schemas/task_frame.schema.json`, `schemas/artifact_envelope.schema.json`, `schemas/run_manifest.schema.json`, `schemas/panel_synthesis.schema.json` | Existing schema family | Match naming, Draft 2020-12 validation, and envelope/receipt structure. [VERIFIED: `.planning/codebase/ARCHITECTURE.md`, `.planning/codebase/STRUCTURE.md`] |

### Proposed files and symbols

| Proposed ownership | Proposed symbols/contracts | Responsibility |
|--------------------|----------------------------|----------------|
| `operate/modes/manuscript_authoring.py` | `STAGES`, `ARTIFACT_PLAN`, `MANUSCRIPT_PARALLEL_GROUPS`, `WORKER_DEPENDENCIES`, `llm_step()`, `run_dets()`, `run_dets_with_repair()` | Thin operated recipe that sequences pre-draft freeze, author bundles, integration, internal audits, and report without accumulating all deterministic logic. [VERIFIED: native recipe pattern] |
| `operate/modes/manuscript_review.py` | `STAGES`, `REVIEW_PARALLEL_GROUPS`, `WORKER_DEPENDENCIES`, `llm_step()`, `run_dets()`, `run_dets_with_repair()` | Distinct review/rebuttal product consuming a frozen manuscript/PDF hash without authoring mutations. [VERIFIED: D-01 and AI-SPEC target layout] |
| `tools/manuscript_contract.py` | `resolve_paper_design_tokens()`, `freeze_manuscript_contract()`, `canonical_contract_hash()` | Pure cascade/provenance/hard-rule reducer and immutable snapshot builder. [VERIFIED: PREP contract] |
| `tools/manuscript_literature.py` | `assess_local_literature_coverage()`, `build_deficit_query_plan()`, `route_literature_fallback()` | Six-dimension local coverage state machine and deficit-only search authorization. [VERIFIED: EVID contract] |
| `tools/manuscript_integrator.py` | `integrate_section_bundles()`, `write_canonical_source_tree()`, `compute_manuscript_hash()` | Sole canonical writer; validates hashes/refs, reconciles cross-section state, and writes atomically. [VERIFIED: D-15] |
| `tools/latex_build.py` | `discover_latex_toolchain()`, `build_latex_project()`, `verify_build_receipt()` | Cross-platform safe discovery, bounded multipass build, log/recorder capture, PDF hash, and exact build-state derivation. [VERIFIED: D-18 and AI-SPEC] |
| `tools/manuscript_audit.py` | `audit_claim_closure()`, `audit_numeric_truth()`, `audit_bibliography_closure()`, `audit_notation_and_labels()`, `audit_assets()`, `audit_venue_contract()`, `derive_delivery_status()`, `is_submission_ready()` | Focused deterministic checks and one pure status reducer; no worker score may override them. [VERIFIED: AUDT-01 and DELV-02] |
| `tools/manuscript_renderer.py` | `render_overview()`, `render_coverage_report()`, `render_authoring_plan()`, `render_quality_report()`, `render_reviewer_report()`, `render_submission_checklist()` | Manuscript-specific Markdown, referencing hash-verified evidence products. [VERIFIED: DELV-01] |
| `schemas/manuscript_contract.schema.json` | `manuscript_contract` | Frozen paper/venue/source/result/token/outline/glossary/asset/build policy contract. [VERIFIED: `01-AI-SPEC.md`] |
| `schemas/manuscript_section_bundle.schema.json` | `manuscript_section_bundle` | Structured candidate section, claim uses, refs, LaTeX fragment, labels, assets, uncertainties, and content hash. [VERIFIED: `01-AI-SPEC.md`] |
| `schemas/manuscript_integration.schema.json` | `manuscript_integration` | Canonical tree inventory, reconciliation results, source hash, and unresolved interfaces. [VERIFIED: `01-AI-SPEC.md`] |
| `schemas/manuscript_build_receipt.schema.json` | `manuscript_build_receipt` | Tool versions, argv, environment facts, return code, log/recorder refs, source/PDF hashes, and build state. [VERIFIED: `01-AI-SPEC.md`] |
| `schemas/manuscript_review_verdict.schema.json` | `manuscript_review_verdict` | Independent review verdict bound to manuscript/PDF/contract hashes and reviewer isolation receipt. [VERIFIED: `01-AI-SPEC.md`] |
| `schemas/local_literature_coverage.schema.json`, `schemas/manuscript_asset_manifest.schema.json`, `schemas/manuscript_quality_report.schema.json` | Corresponding registry keys | Coverage routing, asset provenance, and deterministic audit/status outputs. [VERIFIED: phase requirements] |
| `tests/test_manuscript_contract.py`, `tests/test_manuscript_literature.py`, `tests/test_latex_build.py`, `tests/test_manuscript_audit.py` | TDD unit suites | Drive core transformation, validation, build-state, and status logic before recipes consume it. [VERIFIED: project testing convention] |
| `tests/test_manuscript_schema_contracts.py`, `tests/test_operate_manuscript_authoring.py`, `tests/test_operate_manuscript_review.py`, `tests/test_manuscript_security.py` | Contract/operated/security suites | Prove schema closure, end-to-end products, product separation, secret/path/vault/tool boundaries. [VERIFIED: AI-SPEC evaluation plan] |

## Architecture Patterns

### System Architecture Diagram

```text
Director CLI: begin/resume manuscript_authoring
        |
        v
Operated spine + run store ----> manifest / ledger / checkpoints / hashes
        |
        v
DISCOVER: bounded vault recall (READ ONLY) --> six-dimension local coverage
        |                                      |
        | sufficient                           | explicit deficit only
        |                                      v
        |                              existing paper_search metadata port
        |                              | success | provider failure
        |                              v         v
        |                         follow-up refs explicit failure state
        +-----------------------------+---------+
                                      |
                                      v
DESIGN: freeze paper type + venue profile + outline + claim ledger
        + bibliography/asset plan + resolved token cascade + snapshot hash
                                      |
                                      v
ANALYZE: scheduler-authorized sparse waves
        venue/corpus -> architect/evidence steward -> section/figure workers
                                      |
                                      v
                    ONE integrator owns canonical run/source/
                    (main.tex, refs.bib, sections, manifests)
                                      |
                                      v
                 deterministic audit + isolated LaTeX adapter
                       /                |                 \
                  COMPILED        COMPILE_FAILED     TOOLCHAIN_MISSING
                  PDF+hash        logs+source        complete source only
                       \                |                 /
                                      v
VERIFY: separate manuscript_review operated run
        frozen manuscript/PDF hash -> blind reviewers -> deterministic meta-review
                                      |
                                      v
REPORT: director-review/ Markdown first + linked evidence/source/PDF

Forbidden boundaries: no vault write; no promotion; no GPU execution;
no OpenAlex/content/PDF downloader; no author worker writes canonical source.
```

[VERIFIED: `01-CONTEXT.md`, `01-AI-SPEC.md`, `.planning/codebase/ARCHITECTURE.md`]

### Recommended Project Structure

```text
operate/modes/
├── manuscript_authoring.py       # thin orchestration recipe
└── manuscript_review.py          # independent review/rebuttal recipe
tools/
├── manuscript_contract.py        # token resolution and frozen snapshot
├── manuscript_literature.py      # local coverage and deficit routing
├── manuscript_integrator.py      # sole canonical source writer
├── latex_build.py                # safe build and receipt truth
├── manuscript_audit.py           # deterministic truth/status gates
└── manuscript_renderer.py        # manuscript-specific Markdown outputs
schemas/
├── manuscript_contract.schema.json
├── manuscript_section_bundle.schema.json
├── manuscript_integration.schema.json
├── manuscript_build_receipt.schema.json
├── manuscript_review_verdict.schema.json
├── local_literature_coverage.schema.json
├── manuscript_asset_manifest.schema.json
└── manuscript_quality_report.schema.json
tests/
├── test_manuscript_contract.py
├── test_manuscript_literature.py
├── test_latex_build.py
├── test_manuscript_audit.py
├── test_manuscript_schema_contracts.py
├── test_operate_manuscript_authoring.py
├── test_operate_manuscript_review.py
└── test_manuscript_security.py
runs/<project>/<run_id>/
├── inbox/                         # immutable worker bundles/supplements
├── source/                        # integrator-owned canonical LaTeX
├── build/                         # external-tool output/logs/recorder
├── evidence/                      # validated receipts and verdicts
└── director-review/manuscript/    # human-first delivery
```

[VERIFIED: `01-AI-SPEC.md` target layout plus codebase structure conventions]

### Pattern 1: Frozen contract before generation

Resolve official venue data and Paper Design Tokens, classify hard versus advisory rules, canonicalize the complete manuscript contract, hash it, and require every author/reviewer bundle to name that hash. A changed contract invalidates only its explicit descendants; no worker reads “latest.” [VERIFIED: `01-AI-SPEC.md`, `operate/modes/read_paper_deep.py`]

### Pattern 2: Sparse DAG with explicit context receipts

Declare `WORKER_DEPENDENCIES`; set `group_barriers=False`; have the external harness dispatch only `schedule_next_wave()` output. Every worker receives a common frozen snapshot and declared predecessor slices. Reviewers remain blind until their verdicts are immutable, and the deterministic meta-review is the first join. [VERIFIED: `operate/modes/read_paper_deep.py`, `01-AI-SPEC.md`]

### Pattern 3: Candidate bundles, one canonical integrator

Section agents write JSON bundles to `inbox/`, never `main.tex`, `refs.bib`, figure destinations, or another worker's bundle. The integrator verifies contract/input/content hashes, reconciles references and terminology, and atomically writes `source/`. A canonical change emits a new manuscript hash and invalidates previous review/build receipts. [VERIFIED: D-15, `01-AI-SPEC.md`]

### Pattern 4: Local-first evidence state machine

Coverage dimensions are comparison, method, implementation, dataset, metric/evaluation, and industry/application prior art. Each becomes exactly `sufficient`, `deficit`, `provider_failure`, or `unverified`; only `deficit` authorizes `paper_search`. Search metadata remains `claim_support: none` until a local/hash-bound source and exact support are admitted. [VERIFIED: D-06–D-08, `01-AI-SPEC.md`]

### Pattern 5: Receipt-gated build truth

The build adapter takes a frozen source directory, resolves an executable without shell interpolation, runs within a bounded timeout, captures command/version/log/recorder/source hashes, and derives one state. A zero process exit alone is insufficient: `COMPILED` also requires required reference closure, an existing non-empty PDF, and a PDF hash. [VERIFIED: D-18, `01-AI-SPEC.md`]

### Pattern 6: Separate readable delivery from submission readiness

`USABLE`, `USABLE_WITH_CAVEATS`, `NEEDS_SUPPLEMENT`, and `BLOCK` describe daily delivery. A separate `is_submission_ready()` predicate requires all applicable official, scientific, citation, anonymity, asset, cross-reference, independent-review, and compile gates. Presentation-only defects cannot produce `BLOCK`; a reviewer score cannot downgrade a hard failure. [VERIFIED: D-21–D-22, `01-AI-SPEC.md`]

### Recommended implementation waves

| Wave | Scope | Exit evidence |
|------|-------|---------------|
| 0 | TDD foundations: schemas/registry, token resolver, contract hash, coverage state machine, scholar URL redaction, status reducer | Focused unit/schema/security tests green; no recipe yet. [VERIFIED: risk-first testing policy] |
| 1 | Pre-draft authoring: bounded recall, local coverage, deficit-only search, venue/type/token/snapshot freeze | PREP/EVID contract tests and hermetic provider tests green. [VERIFIED: dependency order] |
| 2 | Sparse authoring panel: role specs, dependencies, input contracts, worker bundles, scheduler receipts | Panel/scheduler/required-role tests green; canonical source still absent. [VERIFIED: operated recipe pattern] |
| 3 | Integrator, asset manifest, canonical LaTeX tree, deterministic audits, status reducer | Integration/asset/claim/number/citation/label tests green. [VERIFIED: D-15–D-20] |
| 4 | Safe LaTeX adapter and truthful build receipts, including fake/compiler-present/missing branches | `test_latex_build.py` green plus recorded real local smoke. [VERIFIED: D-18, D-24] |
| 5 | Separate review/rebuttal recipe, blind review receipts, deterministic meta-review | Product-separation and manuscript-hash immutability tests green. [VERIFIED: D-01] |
| 6 | Human renderers, CLI/registry/catalog/facts mirrors, end-to-end fixtures, full security/eval suite | Both modes only then enter `REGISTRY`; packet and evidence artifacts inspectable. [VERIFIED: D-02, OPER-03] |

### Anti-Patterns to Avoid

- **Monolithic recipe:** do not grow another 2,000-line mode; keep recipes thin and deterministic responsibilities in focused `tools/` modules. [VERIFIED: `.planning/codebase/CONCERNS.md`]
- **Registry-first operation claim:** never set `operated: true` or edit platform facts before recipe, reducers, renderer, and tests exist. [VERIFIED: `operate/modes/__init__.py`]
- **Group-barrier serialization:** do not use `parallel_groups` as scientific dependencies; explicit `depends_on` owns freshness and data flow. [VERIFIED: `operate/modes/read_paper_deep.py`]
- **Shared manuscript writes:** section agents cannot edit the canonical tree or bibliography. [VERIFIED: D-15]
- **Schema-as-truth:** schema validity does not prove citation entailment, numeric accuracy, real execution, or compile success. [VERIFIED: `01-AI-SPEC.md`]
- **Shell build strings:** never interpolate project/request/path text or use `shell=True`; never enable TeX shell escape. [VERIFIED: `01-AI-SPEC.md`]
- **Search failure laundering:** never turn timeout/provider failure into “no evidence” or novelty. [VERIFIED: `.planning/codebase/CONVENTIONS.md`]
- **Readable-output suppression:** do not hide complete source/Markdown for advisory style or missing-toolchain caveats. [VERIFIED: D-21]

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Agent graph/checkpointing | New workflow framework or second state store | Native operated recipe, `schedule_next_wave()`, spine, run store | Existing authorization receipts and hash-chained resume semantics are product invariants. [VERIFIED: `01-AI-SPEC.md`] |
| Artifact validation | Dataclasses-only, regex JSON checks, or prompt-enforced shapes | Draft 2020-12 schemas through `PAYLOAD_SCHEMAS`/`validate_payload()` | One authoritative cross-runtime contract already exists. [VERIFIED: `01-AI-SPEC.md`] |
| Retry/repair lineage | Overwrite failed bundles or rerun the whole panel | `attempt_with_repair()` plus immutable supplements and `resolve_effective_output()` | Preserves scientific lineage and refreshes only affected consumers. [VERIFIED: `operate/modes/read_paper_deep.py`] |
| Vault access | Direct filesystem traversal or general-purpose writer | `tools/recall.py` by reference; no write path in this phase | Protects the machine/database seam and director promotion gate. [VERIFIED: `AGENTS.md`] |
| Literature acquisition | New downloader, crawler, content API, or local corpus builder | Existing `paper_search` metadata port after an explicit deficit | Locked scope prohibits automatic full-text acquisition. [VERIFIED: D-04, EVID-03] |
| Citation truth | Metadata match, title overlap, or model confidence | Existing existence/attribution tools plus exact local spans and independent audit | Existence is not entailment and summaries are noncitable. [VERIFIED: `01-AI-SPEC.md`] |
| Canonical manuscript collaboration | Multiple agents editing TeX files | Structured section bundles plus one integrator | Avoids nondeterministic conflicts and cross-section drift. [VERIFIED: D-15] |
| LaTeX build orchestration | Shell command strings or one-pass success inference | Focused safe adapter around `latexmk` and bounded direct fallback | Handles bibliography/reference passes, timeouts, logs, and truthful states. [VERIFIED: `01-AI-SPEC.md`] |
| Cryptography/receipts | Custom digest format or signature scheme | Existing SHA-256/run-store conventions and non-LLM executor evidence rules | Custom crypto risks inconsistent provenance; this phase does not invent execution proof. [VERIFIED: `.planning/codebase/ARCHITECTURE.md`, `PLATFORM-FACTS.md`] |
| Human packet | JSON as primary output or a second packet system | Existing `tools/director_packet.py` plus manuscript Markdown renderer | The established product boundary is Markdown-first. [VERIFIED: `PLATFORM-FACTS.md`] |

**Key insight:** the new value is the manuscript-specific contract, integration, build, and audit layer; scheduler, persistence, schema, recall, repair, security, and director-delivery infrastructure already exist and should remain single-source.

## LaTeX Build Contract

### Engine priority and discovery

1. Prefer `latexmk` using a safe argument list and a run-owned output directory. The production command should incorporate the proven flags and the AI-SPEC drift controls: `latexmk -norc -gg -pdf -interaction=nonstopmode -halt-on-error -file-line-error -recorder -outdir=<run-build> main.tex`. [VERIFIED: supplied smoke command plus `01-AI-SPEC.md`]
2. If `latexmk` is absent but the frozen contract selects the ordinary PDF route, use a bounded direct sequence: `pdflatex`, then the selected `bibtex` or `biber`, then two `pdflatex` passes; each is an argv list with `shell=False`, the same run-owned `cwd`, bounded timeout, and captured logs. [VERIFIED: phase discretion resolved from supplied toolchain facts and AI-SPEC multipass requirement]
3. Use `xelatex` or `lualatex` only when the frozen venue/template/token contract selects it; do not silently substitute an engine that changes output semantics. [VERIFIED: `01-AI-SPEC.md`]
4. If any required executable, official template, or package is unavailable, emit `TOOLCHAIN_MISSING`; if the toolchain starts but TeX/bibliography/reference/timeout checks fail, emit `COMPILE_FAILED`. Only complete success emits `COMPILED`. [VERIFIED: `01-AI-SPEC.md`]

On Windows, discovery must check `shutil.which()` first and then the per-user MiKTeX candidate derived from `LOCALAPPDATA / Programs / MiKTeX / miktex / bin / x64`; never hardcode a username or mutate global `PATH`. Record the resolved executable path in the receipt after redacting user-sensitive path content from director-facing output. [VERIFIED: supplied environment requirement and project path conventions]

### Verified local toolchain evidence

| Fact | Evidence |
|------|----------|
| MiKTeX 25.12 is installed per-user; AutoInstall is `yes`. | [VERIFIED: orchestrator-supplied local command evidence] |
| Strawberry Perl 5.42.2.1 and `latexmk` 4.88 are available. | [VERIFIED: orchestrator-supplied local command evidence] |
| `pdflatex`, `xelatex`, `lualatex`, `bibtex`, `biber`, and `chktex` are available. | [VERIFIED: orchestrator-supplied local command evidence] |
| Real command `latexmk -gg -pdf -interaction=nonstopmode -halt-on-error -file-line-error main.tex` exited 0. | [VERIFIED: orchestrator-supplied local command evidence] |
| Resulting PDF size is 35,362 bytes; SHA-256 is `19b1639769b2b0e8d79c85fae1a74cab8b5aa0429de69755a9927d7e1d0eb13b`; unresolved-reference count is zero. | [VERIFIED: orchestrator-supplied local command evidence] |
| `chktex` exited 0 for the smoke fixture. | [VERIFIED: orchestrator-supplied local command evidence] |

This evidence proves the current host branch only. It does not permit tests or other hosts to assume a compiler, package cache, network, or identical TeX distribution. Preserve a deterministic fake-compiler branch and a genuine `TOOLCHAIN_MISSING` branch. MiKTeX `AutoInstall=yes` must be recorded but cannot be treated as a hermetic dependency guarantee. [VERIFIED: D-24 and supplied environment evidence]

## Common Pitfalls

### Pitfall 1: Operation truth outruns executable wiring

**What goes wrong:** YAML/catalog/docs claim authoring works while no complete Python recipe and product evidence exist.  
**How to avoid:** update `REGISTRY`, declarative registry, capability catalog, and `PLATFORM-FACTS.md` only in the final wiring wave after end-to-end tests.  
**Warning sign:** mode appears in a catalog but not `operate/modes/__init__.py::REGISTRY`. [VERIFIED: current spec-only `manuscript_review_pack` state]

### Pitfall 2: Parallel authors share mutable context

**What goes wrong:** authors read “latest” bundles or edit the same TeX tree, causing unreproducible terminology, labels, numbers, and citations.  
**How to avoid:** hash the frozen snapshot and every dependency slice; keep authors inbox-only and use one integrator.  
**Warning sign:** worker prompts expose undeclared bundles or canonical paths. [VERIFIED: D-14–D-15]

### Pitfall 3: Local coverage collapses failure into absence

**What goes wrong:** provider timeout or weak local evidence becomes “no prior art,” enabling unsupported novelty claims.  
**How to avoid:** exhaustive coverage-state enums and injected transport tests.  
**Warning sign:** empty results lack a provider/error/search-completion field. [VERIFIED: `.planning/codebase/CONVENTIONS.md`, EVID-02]

### Pitfall 4: Metadata becomes manuscript evidence

**What goes wrong:** OpenAlex/arXiv/Crossref/Semantic Scholar rows acquire citation or entailment authority.  
**How to avoid:** keep `claim_support: none` until a hash-bound accessible source and exact span are validated.  
**Warning sign:** a bibliography or claim ledger points only to a search-result row. [VERIFIED: `PLATFORM-FACTS.md`, D-08]

### Pitfall 5: Schema-valid output is treated as scientifically true

**What goes wrong:** structurally valid citations, numbers, assets, or execution statements bypass independent deterministic checks.  
**How to avoid:** separate JSON Schema validation from claim, numeric, execution, bibliography, asset, and build gates.  
**Warning sign:** a worker verdict directly sets delivery or submission status. [VERIFIED: `01-AI-SPEC.md`]

### Pitfall 6: Generated TeX is called a PDF build

**What goes wrong:** a source tree, zero exit, stale PDF, or fake path is reported as compiled.  
**How to avoid:** clean/run-owned output, source snapshot hash, process receipt, current non-empty PDF, PDF hash, and reference closure.  
**Warning sign:** `COMPILED` lacks log/argv/tool/source/PDF fields. [VERIFIED: D-18, LATX-02]

### Pitfall 7: Windows-only discovery becomes a hardcoded user path

**What goes wrong:** the current MiKTeX install works for one username but fails elsewhere or leaks local identity.  
**How to avoid:** derive the candidate from `LOCALAPPDATA`, prefer `shutil.which()`, store portable relative refs, and test spaces/Unicode.  
**Warning sign:** source code contains `C:\\Users\\<name>` or mutates global PATH. [VERIFIED: PLAT-01 and AI-SPEC Windows guidance]

### Pitfall 8: TeX becomes a code-execution or file-read boundary

**What goes wrong:** generated/untrusted TeX invokes shell escape or reads/writes outside the run.  
**How to avoid:** never enable shell escape; validate `\input`, `\include`, bibliography, and asset paths; use run-owned `cwd`/output; timeout every process.  
**Warning sign:** absolute paths, `..`, `\write18`, arbitrary command fragments, or files outside receipt inventory. [VERIFIED: AI-SPEC guardrails]

### Pitfall 9: Review mutates authorship evidence

**What goes wrong:** review is an authoring substage, reviewers see one another's conclusions, or rebuttal overwrites the reviewed manuscript.  
**How to avoid:** separate recipe/run, frozen manuscript hash, blind input contracts, immutable verdicts, deterministic first join.  
**Warning sign:** review output changes `source/` or references a different manuscript hash. [VERIFIED: D-01]

### Pitfall 10: Secret-bearing scholarly errors propagate

**What goes wrong:** OpenAlex `api_key`/`mailto` query values enter `source_errors`, ledger, build metadata, TeX, or packets.  
**How to avoid:** sanitize at exception construction and again at persistence/output boundaries; add sentinel tests.  
**Warning sign:** persisted URL contains query values rather than provider/host/path/status/request id. [VERIFIED: `.planning/codebase/CONCERNS.md`]

### Pitfall 11: Advisory defects hard-block useful work

**What goes wrong:** prose rhythm, heading balance, visual polish, or missing local compiler hides an otherwise readable manuscript/source tree.  
**How to avoid:** keep delivery status and submission readiness separate; target supplements instead of rerunning the panel.  
**Warning sign:** cosmetic-only finding maps to `BLOCK`. [VERIFIED: D-21–D-22]

### Pitfall 12: Dirty-worktree evidence is mistaken for reproducible release state

**What goes wrong:** command receipts refer only to HEAD while substantial uncommitted changes determine behavior.  
**How to avoid:** record source/diff hashes for build/eval evidence and inspect changed files before commit/ship.  
**Warning sign:** build receipt has repository commit but no source snapshot hash. [VERIFIED: `.planning/codebase/CONCERNS.md`]

## Code Examples

### Deterministic token cascade with hard-rule protection

```python
# Source: 01-AI-SPEC.md §4.4; repository JSON artifacts remain authoritative.
TOKEN_LAYERS = ("base", "paper_type", "venue", "project", "run")


def resolve_paper_design_tokens(layers: dict[str, dict]) -> dict:
    resolved: dict[str, object] = {}
    provenance: dict[str, dict] = {}
    for layer in TOKEN_LAYERS:
        for key, entry in sorted((layers.get(layer) or {}).items()):
            previous = provenance.get(key)
            if previous and previous["hard"] and entry["value"] != resolved[key]:
                raise ValueError(f"hard token {key!r} cannot be weakened by {layer}")
            resolved[key] = entry["value"]
            provenance[key] = {
                "layer": layer,
                "source_sha256": entry["source_sha256"],
                "hard": bool(entry.get("hard", False)) or bool(previous and previous["hard"]),
            }
    return {"resolved": resolved, "provenance": provenance}
```

Write failing tests first for precedence, canonical ordering/hash stability, unknown mandatory tokens, hard-rule weakening, and advisory override acceptance. [VERIFIED: PREP-03, PREP-04]

### Safe LaTeX discovery without hardcoded username

```python
# Source: 01-AI-SPEC.md §4.6/§4.10 plus verified local MiKTeX layout requirement.
from __future__ import annotations

import os
import shutil
from pathlib import Path


def discover_executable(name: str) -> Path | None:
    found = shutil.which(name)
    if found:
        return Path(found).resolve()
    local_app_data = os.environ.get("LOCALAPPDATA")
    if os.name == "nt" and local_app_data:
        candidate = (
            Path(local_app_data)
            / "Programs" / "MiKTeX" / "miktex" / "bin" / "x64"
            / f"{name}.exe"
        )
        if candidate.is_file():
            return candidate.resolve()
    return None
```

The build adapter must validate that source, output, log, recorder, included TeX, bibliography, and asset paths remain inside the run root before invocation. [VERIFIED: SAFE-01, PLAT-01]

### Receipt-gated `latexmk` invocation

```python
# Source: 01-AI-SPEC.md §4.6; no shell interpolation or shell escape.
argv = [
    str(latexmk_path),
    "-norc",
    "-gg",
    "-pdf",
    "-interaction=nonstopmode",
    "-halt-on-error",
    "-file-line-error",
    "-recorder",
    f"-outdir={build_dir}",
    "main.tex",
]
completed = subprocess.run(
    argv,
    cwd=source_dir,
    shell=False,
    timeout=timeout_seconds,
    capture_output=True,
    text=True,
    encoding="utf-8",
    errors="replace",
)
```

Derive `COMPILED` only after validating exit code, output freshness, PDF existence/size/hash, required reference closure, and receipt/schema validity. [VERIFIED: LATX-02]

### Deficit-only search routing

```python
# Source: 01-AI-SPEC.md §4.3.
VALID_COVERAGE = {"sufficient", "deficit", "provider_failure", "unverified"}


def route_literature_fallback(coverage_rows: list[dict], search_port) -> list[dict]:
    if any(row["status"] not in VALID_COVERAGE for row in coverage_rows):
        raise ValueError("invalid coverage status")
    plans = [row["query_plan"] for row in coverage_rows if row["status"] == "deficit"]
    return search_port(plans) if plans else []
```

Injected transports must assert zero network calls for sufficient, provider-failure, and unverified rows. [VERIFIED: EVID-02, VERI-02]

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|-------------|-----------|---------|----------|
| Python | Native framework/tests | ✓ | 3.9.13 observed | Planner must preserve compatibility; no new-runtime syntax assumption. [VERIFIED: `01-AI-SPEC.md`] |
| `jsonschema` | All new payload contracts | ✓ | 4.25.1 observed | None; authoritative existing dependency. [VERIFIED: `01-AI-SPEC.md`] |
| PyYAML | Registry/profile mirrors | ✓ | 6.0.2 observed | None for existing YAML configuration. [VERIFIED: `01-AI-SPEC.md`] |
| pytest | TDD and phase gates | ✓ | 8.4.2 observed | None; existing framework. [VERIFIED: `.planning/codebase/TESTING.md`] |
| Sibling PhD-Research-OS | Local-first bounded recall | ✓ in workspace | Separate repository | If a referenced source is unavailable, mark coverage `unverified`/`deficit`; never broaden permissions. [VERIFIED: `AGENTS.md`] |
| MiKTeX | Real Windows LaTeX build | ✓ | 25.12 per-user; AutoInstall=yes | Complete source plus honest status on hosts without required tooling. [VERIFIED: supplied evidence] |
| Strawberry Perl | `latexmk` on this Windows host | ✓ | 5.42.2.1 | Direct bounded engine/bibliography passes. [VERIFIED: supplied evidence] |
| `latexmk` | Preferred multipass build | ✓ | 4.88 | Direct `pdflatex` + `bibtex`/`biber` + two `pdflatex` passes; otherwise `TOOLCHAIN_MISSING`. [VERIFIED: supplied evidence] |
| `pdflatex`/`xelatex`/`lualatex` | Engine selection | ✓ | Version captured at runtime | Missing selected engine -> `TOOLCHAIN_MISSING`. [VERIFIED: supplied evidence] |
| `bibtex`/`biber` | Bibliography closure | ✓ | Version captured at runtime | Missing required bibliography tool -> `TOOLCHAIN_MISSING`. [VERIFIED: supplied evidence] |
| `chktex` | Advisory diagnostics | ✓ | Version captured at runtime | Skip with visible caveat; never substitute for compilation/audit. [VERIFIED: supplied evidence] |
| Network scholarly providers | Explicit-deficit metadata fallback only | Optional/unreliable by design | Provider-specific | Preserve `provider_failure`; local-first run continues with bounded claims. [VERIFIED: `PLATFORM-FACTS.md`] |
| GPU/external executor | Out of scope | Not required | — | None; author only from frozen auditable results. [VERIFIED: SAFE-03] |

**Missing dependencies with no fallback:** none for readable source/Markdown delivery. A selected venue may make a specific official template/engine/package mandatory for submission readiness; absence then yields `TOOLCHAIN_MISSING`, not a false pass. [VERIFIED: LATX-02]

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest 8.4.2 observed [VERIFIED: `.planning/codebase/TESTING.md`] |
| Config file | none; pytest default discovery over `tests/test_*.py` [VERIFIED: `.planning/codebase/TESTING.md`] |
| Shared fixtures | `tests/conftest.py` provides hermetic network/vault defaults [VERIFIED: `.planning/codebase/TESTING.md`] |
| Quick existing run | `python -m pytest tests/test_operate_wiring.py tests/test_capability_catalog.py tests/test_panel_scheduler.py tests/test_validate_artifact.py -q` |
| Full suite | `python -m pytest tests -q` |

### TDD ownership

Write tests before implementation for token merge/hash, frozen contract transitions, literature routing, secret-safe errors, schema registration, path ownership, section/integration transformation, citation/number/label closure, build-state derivation, receipt verification, delivery status, and submission readiness. Recipe prompt text and renderer prose do not require strict unit-first implementation, but their contracts and output paths require operated integration tests. [VERIFIED: AGENTS TDD rule and AI-SPEC evaluation plan]

### Phase Requirements → Test Map

| Req IDs | Behavior | Test type | Automated command | File exists? |
|---------|----------|-----------|-------------------|--------------|
| PREP-01–PREP-04, PLAT-02 | venue/type/token/snapshot freeze, provenance, hard/advisory separation | unit/property/schema | `python -m pytest tests/test_manuscript_contract.py tests/test_manuscript_schema_contracts.py -q` | ❌ Wave 0 |
| EVID-01–EVID-03, SAFE-02, VERI-02 | local-first recall/coverage, deficit-only search, error distinction, no downloader, redaction | unit/contract/security | `python -m pytest tests/test_manuscript_literature.py tests/test_scholar_clients.py tests/test_paper_search.py tests/test_manuscript_security.py -q` | ❌ new manuscript files; existing boundary tests present |
| ORCH-01–ORCH-02 | sparse dependencies, legal context slices, single integrator | unit/contract/integration | `python -m pytest tests/test_panel_scheduler.py tests/test_operate_manuscript_authoring.py -q` | ❌ authoring test Wave 2 |
| LATX-01–LATX-02, ASST-01 | canonical source/assets, compiler/fake/missing states, hashes, non-overwrite | unit/integration | `python -m pytest tests/test_latex_build.py tests/test_manuscript_audit.py -q` | ❌ Wave 3–4 |
| AUDT-01, DELV-02, SAFE-03, VERI-03–VERI-04 | deterministic closure, execution truth, status calibration, negative matrix | unit/property/security | `python -m pytest tests/test_manuscript_audit.py tests/test_manuscript_contract.py tests/test_manuscript_security.py -q` | ❌ Wave 0–4 |
| OPER-02 | distinct review recipe, frozen hash, no author mutation, blind verdict join | operated integration | `python -m pytest tests/test_operate_manuscript_review.py -q` | ❌ Wave 5 |
| OPER-01, DELV-01, VERI-01 | start/resume, full authoring fixture, human-first products, honest build | operated E2E | `python -m pytest tests/test_operate_manuscript_authoring.py -q` | ❌ Wave 6 |
| OPER-03 | executable/declarative/catalog/platform fact mirrors | integration | `python -m pytest tests/test_operate_wiring.py tests/test_capability_catalog.py -q` | ✅ extend in Wave 6 |
| SAFE-01, PLAT-01 | vault unchanged, traversal/reparse/path portability, Unicode/spaces, tool discovery | security/cross-platform | `python -m pytest tests/test_scope_guard.py tests/test_manuscript_security.py tests/test_latex_build.py -q` | ❌ manuscript-specific Wave 0–4 |
| VERI-05 | focused, operated, AI-eval/security, and full completion evidence | release gate | `python -m pytest tests -q` | ✅ command exists; phase coverage pending |

### Required 16-case hermetic set

- 2 local-corpus cases: sufficient means zero network; named deficit calls only existing search. [VERIFIED: `01-AI-SPEC.md`]
- 2 retrieval-truth cases: `SEARCH_FAILED`/provider failure is not evidence absence; valid exhaustive search may produce traced no-evidence. [VERIFIED: `01-AI-SPEC.md`]
- 2 token/snapshot cases: precedence and hard-rule override rejection; changed upstream hash invalidates descendants only. [VERIFIED: `01-AI-SPEC.md`]
- 2 bundle/DAG cases: maximum two format repairs; unauthorized/orphan dependency fails closed. [VERIFIED: `01-AI-SPEC.md`]
- 3 scientific-truth cases: unsupported claim, citation identity/entailment mismatch, numeric/receipt mismatch, including false execution language. [VERIFIED: `01-AI-SPEC.md`]
- 2 asset/path cases: traversal rejected; director asset remains unchanged with original hash. [VERIFIED: `01-AI-SPEC.md`]
- 2 build cases: real or deterministic fake compiler produces hashed PDF; missing toolchain preserves complete source and truthful status. [VERIFIED: `01-AI-SPEC.md`]
- 1 product-separation case: review consumes frozen hash, mutates no authoring files, emits its own packet. [VERIFIED: `01-AI-SPEC.md`]
- 1 end-to-end authoring case: all required tree/report/evidence/status products exist. [VERIFIED: `01-AI-SPEC.md`]

### Sampling Rate

- **Per task commit:** run the smallest owning new test module plus affected existing boundary test.
- **Per wave merge:** run all manuscript-focused tests plus `test_operate_wiring.py`, `test_capability_catalog.py`, `test_panel_scheduler.py`, `test_validate_artifact.py`, `test_scope_guard.py`, `test_scholar_clients.py`, and `test_paper_search.py`.
- **Phase gate:** `python -m pytest tests -q`, AI-eval/security review evidence, real local build receipt, deterministic missing-toolchain evidence, rendered director packet, and inspected changed-file list.

### Wave 0 Gaps

- [ ] `tests/test_manuscript_contract.py` — PREP-01 through PREP-04 and VERI-03.
- [ ] `tests/test_manuscript_literature.py` — EVID-01 through EVID-03 and VERI-02.
- [ ] `tests/test_manuscript_schema_contracts.py` — every valid and truth-sensitive invalid payload.
- [ ] `tests/test_manuscript_audit.py` — AUDT-01, DELV-02, SAFE-03, VERI-04.
- [ ] `tests/test_latex_build.py` — LATX-01/LATX-02, fake success/failure, real conditional smoke, genuine missing branch.
- [ ] `tests/test_manuscript_security.py` — SAFE-01/SAFE-02, paths, TeX directives, vault writes, sentinel secrets.
- [ ] `tests/test_operate_manuscript_authoring.py` and `tests/test_operate_manuscript_review.py` — operated/E2E/product separation.
- [ ] Register all new schemas in `PAYLOAD_SCHEMAS`; do not install a test framework or alternate validator.

## Security Domain

Security enforcement is treated as enabled because this phase handles untrusted documents, generated TeX, filesystem writes, scholarly URLs, a read-only sibling database, and truth-sensitive build/execution claims. [VERIFIED: `01-AI-SPEC.md`, `AGENTS.md`]

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|------------------|
| V2 Authentication | No new authentication surface | Preserve existing CLI/project identity boundaries; do not add auth logic. [VERIFIED: phase scope] |
| V3 Session Management | No web session surface | Run manifest/checkpoints, not sessions, own resume state. [VERIFIED: `.planning/codebase/ARCHITECTURE.md`] |
| V4 Access Control | Yes | Scheduler read scopes, run-root fencing, vault read-only recall, integrator-only canonical writes, top-level promotion exclusion. [VERIFIED: `AGENTS.md`, `operate/modes/read_paper_deep.py`] |
| V5 Input Validation | Yes | Draft 2020-12 JSON Schema, path validation, enum/state validation, citation/result/asset/build closure, untrusted-data prompt delimiters. [VERIFIED: `01-AI-SPEC.md`] |
| V6 Cryptography | Yes, provenance only | Existing SHA-256/source hashes and run-store ledger conventions; never hand-roll cryptography or infer execution signatures. [VERIFIED: `.planning/codebase/ARCHITECTURE.md`] |
| V8 Data Protection | Yes | Secret-safe URLs/errors/logs/TeX/packets; no `.env` reads; private/sensitive data remains within project permissions. [VERIFIED: `AGENTS.md`, `.planning/codebase/CONCERNS.md`] |
| V10 Malicious Code | Yes | Never execute model-generated code/shell; no shell escape; no downloader; external TeX invoked through a fixed allowlisted adapter. [VERIFIED: `01-AI-SPEC.md`] |
| V12 Files and Resources | Yes | Run-owned paths, symlink/reparse defense, immutable asset inputs, size/time limits, atomic writes. [VERIFIED: D-19, AI-SPEC guardrails] |

### Known Threat Patterns

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Paper/web/README/LaTeX prompt injection changes role or tools | Elevation of Privilege / Tampering | Treat all source text as delimited untrusted data; immutable system/tool/read/write contract; generated commands never execute. [VERIFIED: `01-AI-SPEC.md`] |
| Path traversal, symlink/reparse escape, absolute TeX include | Elevation of Privilege / Tampering | Resolve and fence every read/write/include beneath run root; reuse path/scope guards; reject `..` and unowned targets. [VERIFIED: D-22, codebase architecture] |
| TeX `\write18` or arbitrary shell/process invocation | Elevation of Privilege | No shell escape, fixed executable allowlist, `shell=False`, argument arrays, bounded timeout and resource policy. [VERIFIED: `01-AI-SPEC.md`] |
| Secret-bearing scholarly URL or exception persisted downstream | Information Disclosure | Sanitize query values at `ScholarLookupError` construction and persistence; sentinel-secret scan every artifact/packet/build log. [VERIFIED: `.planning/codebase/CONCERNS.md`] |
| Direct/indirect vault write or implicit promotion | Tampering | No vault writer/import in either mode; recall by reference; scope-guard and unchanged-tree tests. [VERIFIED: SAFE-01, `AGENTS.md`] |
| Search outage represented as absence/novelty | Tampering / Repudiation | Typed coverage/search states and complete query/provider trace. [VERIFIED: EVID-02] |
| Unsupported/model-authored metric represented as executed result | Tampering / Repudiation | Only frozen result refs and existing non-LLM receipt semantics; false execution language hard-blocks. [VERIFIED: SAFE-03, `PLATFORM-FACTS.md`] |
| Stale/fabricated PDF represented as current compile | Tampering / Repudiation | Clean run-owned build path, source hash, command receipt, fresh PDF existence/size/hash, reference closure. [VERIFIED: LATX-02] |
| Director-owned figure overwritten | Tampering | Copy/render to run-owned target; bind input/output hashes and reject overwrite. [VERIFIED: ASST-01] |
| Reviewer contamination or self-review presented as independent | Spoofing / Repudiation | Separate recipe/run, frozen hash, blind input contracts, reviewer identity/receipt, deterministic first join. [VERIFIED: OPER-02] |
| TeX expansion/resource exhaustion | Denial of Service | Per-process timeout, bounded passes, run-owned output, log size bounds, typed `COMPILE_FAILED`. [VERIFIED: AI-SPEC build guidance] |

### Required security regressions

1. Sentinel `api_key`/`mailto` values never appear in raised exceptions, `source_errors`, ledger, TeX/BibTeX, build logs/metadata, or Markdown packet. [VERIFIED: known codebase gap]
2. Absolute, parent-relative, symlink, reparse-point, and director-asset overwrite attempts fail at the earliest correct gate. [VERIFIED: SAFE-01, ASST-01]
3. `\write18`, out-of-run `\input`/`\includegraphics`, arbitrary executable, and `shell=True` paths are rejected. [VERIFIED: AI-SPEC guardrails]
4. Review cannot mutate author source and authoring cannot manufacture independent review evidence. [VERIFIED: D-01]
5. The sibling vault tree hash/file inventory is unchanged after successful and failed authoring/review fixtures. [VERIFIED: SAFE-01]

## State of the Art

| Old/current gap | Phase 1 target | Impact |
|-----------------|----------------|--------|
| `manuscript_review_pack` is registry-routable spec-only and no manuscript authoring recipe is in `REGISTRY`. | Two concrete native operated recipes with mirror-tested status. | Prevents capability claims from outrunning runnable products. [VERIFIED: `PLATFORM-FACTS.md`, `operate/modes/__init__.py`] |
| Existing operated products primarily render Markdown/evidence; active code has no native LaTeX build chain. | Run-owned native LaTeX source plus truthful external build receipts. | Enables a real manuscript source/PDF product without false compile claims. [VERIFIED: `.planning/codebase/CONCERNS.md`] |
| `read_paper_deep` demonstrates 12 sparse waves, immutable supplements, blind review, and usable-first delivery. | Reuse those control patterns for adaptive author/reviewer capabilities and one integrator. | Reduces new orchestration risk while avoiding a monolithic paper-writing worker. [VERIFIED: `operate/modes/read_paper_deep.py`, `PLATFORM-FACTS.md`] |
| Search metadata is by-reference with `claim_support: none`; deep evidence remains local/snapshot-bound. | Explicit six-dimension local coverage and deficit-only existing search. | Preserves evidence semantics and the no-downloader boundary. [VERIFIED: `PLATFORM-FACTS.md`] |
| Scholar errors may leak OpenAlex query secrets. | Central redaction before errors can reach durable artifacts. | Closes a known information-disclosure gap required by SAFE-02. [VERIFIED: `.planning/codebase/CONCERNS.md`] |

**Deprecated/outdated for this phase:** registry-only “operated” claims; monolithic whole-paper generation; metadata-only citation support; model reviewer scores as release truth; one-pass TeX success inference; hardcoded model IDs; hardcoded user-specific MiKTeX paths; automatic full-text acquisition. [VERIFIED: `01-AI-SPEC.md`, phase decisions]

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| — | None. All factual claims are grounded in the bounded repository inputs or orchestrator-supplied local command evidence; proposed filenames/symbols are prescriptive planning recommendations, not claims that files already exist. | All | No user confirmation is required before planning. |

## Open Questions

None requiring a user decision. The agent-discretion choices are resolved here as: native framework only; authoritative JSON Schema; `latexmk` first, bounded direct `pdflatex`/bibliography fallback, venue-selected Xe/Lua only when required; focused tool modules; separate review recipe; adaptive optional section specialists but non-skippable evidence/integration/independent truth capabilities. [VERIFIED: `01-CONTEXT.md` discretion]

## Sources

### Primary (HIGH confidence)

- `.planning/phases/01-operated-ai-manuscript-authoring/01-CONTEXT.md` — locked decisions, discretion, scope, and delivery/build truth.
- `.planning/phases/01-operated-ai-manuscript-authoring/01-AI-SPEC.md` — native framework decision, target layout, DAG, schemas, LaTeX contract, evaluation set, and guardrails.
- `.planning/REQUIREMENTS.md` — all 28 Phase 1 requirements.
- `operate/modes/read_paper_deep.py` — exact sparse-DAG, input-contract, bundle, reducer, repair, readable-render, and report analog symbols.
- `operate/modes/__init__.py` and `PLATFORM-FACTS.md` — current operated/spec-only truth and mirror boundary.
- `.planning/codebase/ARCHITECTURE.md`, `STRUCTURE.md`, `TESTING.md`, `CONVENTIONS.md`, `CONCERNS.md` — current component boundaries, conventions, test commands, known risks, and missing LaTeX/manuscript product.
- `../.agents/skills/research-orchestrator/SKILL.md` and project `AGENTS.md` — operation, human-gate, vault, secret, GPU, and Markdown-first constraints.
- Orchestrator-supplied local command evidence — MiKTeX/Perl/latexmk/tool availability, real successful build, PDF size/hash, reference closure, and `chktex` result.

### Secondary (MEDIUM confidence)

- Official venue and external research-system URLs already curated in `01-AI-SPEC.md`. They were not re-fetched in this bounded retry, so the implementation must refresh and hash the selected venue's official current rules at run time rather than hardcode their values.

### Tertiary (LOW confidence)

- None.

## Metadata

**Confidence breakdown:**

- Standard stack: HIGH — existing environment and native contracts are documented; no new dependency is recommended.
- Architecture: HIGH — directly maps locked decisions onto a proven operated recipe/scheduler/run-store pattern.
- LaTeX environment: HIGH for this Windows host — real command/PDF/hash evidence supplied; portability branches remain mandatory.
- Pitfalls/security: HIGH — derived from documented codebase gaps, locked guardrails, and exact existing boundaries.
- Venue-specific current rules: MEDIUM until the selected run refreshes and hashes official sources.

**Research date:** 2026-07-21  
**Valid until:** 2026-08-20 for repository architecture; venue requirements must be refreshed per run at freeze time.
