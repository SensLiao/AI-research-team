# Phase 1: Operated AI Manuscript Authoring - Context

**Gathered:** 2026-07-21
**Status:** Ready for planning

<domain>
## Phase Boundary

Deliver one complete machine-side product that turns existing, auditable AI-research evidence into a coherent multi-agent-authored LaTeX manuscript, an honest PDF build outcome, independent manuscript-review evidence, and human-first submission artifacts. The phase includes distinct operated authoring and review/rebuttal recipes, local-first literature assessment, frozen manuscript design, Paper Design Tokens, sparse worker waves, integration, figures/tables, deterministic audits, and end-to-end verification. It excludes paper downloading, GPU execution, autonomous submission, and database promotion.

</domain>

<decisions>
## Implementation Decisions

### Product and evidence boundaries

- **D-01:** `manuscript_authoring` and manuscript review/rebuttal are separate operated products. They may share deterministic utilities and schemas, but generation evidence and independent review evidence remain distinct.
- **D-02:** A mode becomes `operated` only after a concrete `operate/modes/` recipe, registry mirror, worker contract, deterministic reducer, director-facing renderer, and operated tests exist. Registry-only entries remain spec-only.
- **D-03:** Authoring reads the sibling PhD-Research-OS only through bounded recall/reference paths. It never writes the database and never invokes promotion; drafts and build artifacts remain run scratch.
- **D-04:** The phase adds no OpenAlex PDF/content downloader, bulk acquisition, or automatic PDF fetch. OpenAlex remains an optional metadata provider inside the existing search engine.

### Venue and local-first literature

- **D-05:** Paper type and a realistic top-tier venue family are frozen before drafting. Official current venue requirements are authoritative; community rankings and CCF A-class or equivalent labels guide candidate selection but are not hardcoded as permanent truth.
- **D-06:** Local evidence coverage is explicit, not assumed. The assessment covers at least related comparison, technical method, implementation detail, dataset, metric/evaluation, and relevant industry prior art, with traceable local source references.
- **D-07:** Only a named coverage deficit creates a targeted query plan for the existing `paper_search` path. A network/provider failure is recorded separately from a genuine no-result state and cannot be interpreted as evidence absence.
- **D-08:** Search results are references for follow-up evidence work, not manuscript-ready support by default. No retrieved metadata row may silently become an entailed citation or a locally owned full-text source.

### Paper Design Tokens and frozen context

- **D-09:** Resolve and hash Paper Design Tokens in the order `base -> paper type -> venue -> project -> run override`. The resolved snapshot, provenance of every override, and source hashes are frozen before author waves begin.
- **D-10:** The small hard-rule set covers official template/anonymity, claim-number-citation traceability, terminology/notation consistency, figure/table provenance, compile/cross-reference integrity, and no fabrication. A lower layer or run override cannot weaken these rules.
- **D-11:** Section shape, paragraph rhythm, voice, rhetorical pattern, caption preference, visual taste, and most formatting guidance are advisory. Advisory conflicts produce a recommendation or caveat, not a daily-delivery block.
- **D-12:** The frozen manuscript snapshot contains the paper brief, paper type, venue profile, outline, claim ledger, evidence/result references, terminology and notation glossary, bibliography state, figure/table plan, resolved tokens, and dependency slices.

### Parallel authoring and integration

- **D-13:** Required capabilities include venue/corpus reconnaissance, paper architecture, evidence stewardship, section authorship, figure/table engineering, manuscript integration, independent factual/citation/style/LaTeX audit, and submission packaging. These are capability roles, not a requirement for one fixed worker per label.
- **D-14:** Use a sparse dependency DAG and scheduler authorization receipts. Each worker receives the frozen common snapshot plus only declared predecessor slices; independent auditors do not see conclusions they are meant to judge blindly.
- **D-15:** One integrator owns the canonical manuscript state and reconciles cross-section terminology, notation, claims, citations, numbers, labels, figures, and narrative flow. Section agents never write directly into the integrated manuscript tree.
- **D-16:** Exact worker count, wave count, and section partition may adapt to paper type and complexity, provided the required capabilities, independence boundaries, and deterministic contracts remain satisfied.

### LaTeX, figures, and build truth

- **D-17:** Produce a native, run-owned LaTeX source tree with `main.tex`, `refs.bib`, section files, figure/table manifests, build metadata, and a deterministic quality report.
- **D-18:** Detect an external LaTeX engine at runtime and invoke it through an argument-safe subprocess contract. A successful build must bind the PDF hash, command receipt, log, and source snapshot; missing tooling yields `TOOLCHAIN_MISSING` and never a fabricated PDF claim.
- **D-19:** Local director-owned figure sources are immutable inputs. The run copies or renders into run-owned paths, records source hashes and reproducible commands, and never silently overwrites the original asset.
- **D-20:** Every included figure/table owns a stable label, caption, source/result references, and provenance entry. Cross-reference and asset-existence checks run before a submission-ready verdict.

### Delivery and quality policy

- **D-21:** Daily delivery states are `USABLE`, `USABLE_WITH_CAVEATS`, `NEEDS_SUPPLEMENT`, and `BLOCK`. Readable manuscript output remains visible when only advisory style, completeness, or toolchain issues exist.
- **D-22:** Missing/fabricated core sources, unsupported core claims or numbers, false execution/PDF claims, permission/path violations, secret leakage, or irrecoverably corrupt inputs hard-block daily delivery. Submission readiness separately requires every official, scientific, citation, anonymity, cross-reference, and compilation requirement that applies.
- **D-23:** Human-first Markdown under `director-review/` is the entry point. JSON bundles, source hashes, logs, LaTeX trees, and PDFs are evidence/archive products referenced by the Markdown packet.
- **D-24:** The end-to-end fixture must exercise a sufficient-local-evidence branch and a documented-deficit branch, plus compiler-present or deterministic fake-compiler behavior and a real `TOOLCHAIN_MISSING` branch.

### the agent's Discretion

- Choose the exact LaTeX engine priority order, subprocess timeout defaults, source-tree module names, schema filenames, and renderer module boundaries using existing repository conventions and cross-platform tests.
- Choose section-role granularity and optional specialist skips from paper type and evidence state; required capability coverage and independent truth audits may not be skipped.
- Choose advisory prose defaults and AI-research token overlay values from current official/top-paper evidence gathered in the AI integration phase; do not hardcode transient venue dates or rules into generic control-plane code.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Locked scope and current facts

- `.planning/intake/SPEC-AI-MANUSCRIPT-AUTHORING.md` - Director-approved requirements, boundaries, and Done When criteria.
- `.planning/PROJECT.md` - Core value, success measure, non-goals, and locked project constraints.
- `.planning/REQUIREMENTS.md` - The 28 v1 requirements and Phase 1 traceability map.
- `PLATFORM-FACTS.md` - Current operated/spec-only capability truth and machine/database boundary.
- `README.md` - Existing CLI operation and supported product surface.

### Reusable operated patterns

- `operate/modes/read_paper_deep.py` - Sparse dependency waves, frozen shared representation, usable-first delivery, targeted supplements, and one final writer.
- `operate/modes/venue_readiness.py` - Blind parallel reviewers, derived verdicts, venue profiles, and human gates.
- `operate/panel_scheduler.py` - Dependency-safe wave authorization, read scopes, budgets, and predecessor receipts.
- `operate/spine.py` - Resumable operated lifecycle and persisted gate/checkpoint behavior.
- `operate/modes/__init__.py` - Authoritative one-button operated-mode registry.
- `orchestrator/mode_registry.yaml` - Declarative mode contracts and current spec-only manuscript review entry.

### Evidence, safety, and output boundaries

- `tools/recall.py` - Bounded read-only vault recall by reference.
- `tools/paper_search.py` - Existing metadata search, query planning, and by-reference evidence behavior.
- `tools/scholar_clients.py` - Provider clients and the request-error redaction boundary that this phase must harden.
- `tools/runstore.py` - Atomic manifests, checkpoints, hashes, and tamper-evident run state.
- `tools/validate_artifact.py` - Artifact envelope and registered payload-schema validation.
- `tools/director_packet.py` - Human-first director-review packet assembly.
- `tools/path_boundaries.py` and `tools/scope_guard.py` - Cross-platform path and permission boundaries.

### Architecture and risk maps

- `.planning/codebase/STACK.md` - Supported Python/Node runtime facts and optional dependency behavior.
- `.planning/codebase/ARCHITECTURE.md` - Operated recipe, deterministic layer, run store, and vault seam architecture.
- `.planning/codebase/CONCERNS.md` - Manuscript/LaTeX gaps, secret-redaction risk, dirty-worktree risk, and fragile mirrored registries.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets

- `operate/modes/read_paper_deep.py`: strongest template for a sparse scientific panel, optional specialists, immutable supplements, and usable-first Markdown.
- `operate/modes/venue_readiness.py` plus `tools/venue_review_protocol.py`: strongest template for frozen review input, blind receipts, independent reviewers, deterministic scoring, and venue decisions.
- `operate/panel_scheduler.py`: existing worker-DAG enforcement; the new mode should extend it rather than dispatch workers directly.
- `tools/recall.py` and `tools/paper_search.py`: the local-first/read-by-reference and targeted-online lookup ports.
- `tools/validate_artifact.py`, `schemas/`, and `tools/director_packet.py`: schema registration, deterministic validation, and human output assembly.

### Established Patterns

- Operated status comes from an executable recipe registered in `operate/modes/__init__.py`, not from YAML alone.
- Probabilistic worker output is staged into run-local bundles; deterministic reducers validate and commit it.
- The run manifest and hash-chained ledger, not chat memory, are the resume source of truth.
- Scientific truth failures remain fail-closed while presentation and non-critical completeness gaps may be repaired or delivered with caveats.
- Domain-specific rigor belongs in profiles/overlays; generic orchestration remains domain-neutral.

### Integration Points

- Add authoring/review recipes under `operate/modes/`, mirror them in `orchestrator/mode_registry.yaml`, and expose them through the existing CLI/capability catalog path.
- Add focused token, manuscript-contract, literature-coverage, LaTeX-project/build, and manuscript-audit utilities under `tools/` with registered schemas under `schemas/`.
- Add AI-research defaults under profile/token configuration, agent role specs under `agents/`, director output under the existing run `director-review/` tree, and tests under `tests/`.
- Redact scholarly request URLs before exception text can enter `paper_search` results, ledgers, build metadata, or director packets.

</code_context>

<specifics>
## Specific Ideas

- Treat Paper Design Tokens like CSS design tokens: cascade, resolve, freeze, hash, and hand the same resolved contract to every author and auditor.
- Reuse FlowCopilot concepts for run isolation, checkpoints, diffs, resumability, and reproducible publication figures, while keeping Research Agent Teams as the only control plane.
- Optimize roughly 90% for usable scientific output and 10% or less for governance. Governance exists to prevent truth, safety, and submission failures, not to prescribe every paragraph.
- Start from the database's existing papers and notes; go online only when the coverage report can name what is missing.

</specifics>

<deferred>
## Deferred Ideas

- Lawful automatic open-access acquisition or large corpus construction is not part of this phase.
- Live GPU experiment execution remains gated by the existing external executor/server path.
- Autonomous venue submission and automatic vault promotion remain director-only decisions outside authoring.

</deferred>

---

*Phase: 1-operated-ai-manuscript-authoring*
*Context gathered: 2026-07-21*
