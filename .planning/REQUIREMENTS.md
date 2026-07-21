# Requirements: Research Agent Teams — AI Manuscript Authoring

**Defined:** 2026-07-21  
**Core Value:** Turn locally held, auditable AI-research evidence into a coherent multi-agent-authored LaTeX manuscript, honest PDF build status, and strict submission evidence without polluting the database.

## v1 Requirements

### Operated Product

- [ ] **OPER-01**: The director can start and resume a one-button `manuscript_authoring` run through the existing validated, checkpointed, tamper-evident operated lifecycle.
- [x] **OPER-02**: The director can run manuscript review/rebuttal through a distinct operated recipe that consumes a manuscript without conflating review evidence with generation evidence.
- [ ] **OPER-03**: Capability facts and the mode registry expose authoring or review as operated only when the corresponding concrete recipe exists and is runnable.

### Pre-Draft Contract

- [x] **PREP-01**: Before drafting, the run selects and freezes a paper type and realistic target-venue family, prioritizing current top AI or CCF A-class-equivalent venues while treating official venue rules as authoritative.
- [x] **PREP-02**: Before parallel authoring, the run freezes a manuscript snapshot containing the paper brief, outline, claim ledger, evidence/result references, terminology/notation, venue profile, bibliography state, figure/table plan, and resolved Paper Design Tokens.
- [ ] **PREP-03**: Paper Design Tokens resolve deterministically with precedence `base -> paper type -> venue -> project -> run override`.
- [ ] **PREP-04**: The resolved token contract distinguishes the small hard-rule set—official template/anonymity, traceability, terminology/notation, figure provenance, compile/cross-reference integrity, and no fabrication—from advisory structure, voice, caption, rhetoric, and formatting guidance.

### Evidence Coverage

- [x] **EVID-01**: Each authoring run recalls and reads relevant papers and notes from the read-only PhD-Research-OS database first, then emits an explicit local-literature coverage assessment.
- [x] **EVID-02**: Only a documented comparison, implementation, method, dataset, metric, or industry-prior-art deficit activates the existing paper-search engine, and network/search failure remains distinguishable from genuine evidence absence.
- [x] **EVID-03**: The authoring and review paths contain no OpenAlex PDF downloader, bulk-download/content API, corpus-construction, or automatic PDF acquisition path; OpenAlex may remain metadata-only inside the existing search engine.

### Multi-Agent Authoring

- [x] **ORCH-01**: Authoring runs use a sparse dependency DAG with explicit venue/corpus reconnaissance, paper architecture, evidence stewardship, section author, figure/table, integration, independent factual/citation/style/LaTeX audit, and submission-packaging roles.
- [x] **ORCH-02**: Each section author receives the frozen shared context plus only its declared dependency slice, and one integrator owns terminology, notation, claim, citation, number, figure, and cross-section coherence.

### LaTeX and Assets

- [x] **LATX-01**: The run produces a native LaTeX project containing `main.tex`, `refs.bib`, section files, figure/table manifests, build metadata, and a deterministic quality report.
- [x] **LATX-02**: The run detects an available LaTeX engine and builds a real PDF when possible; otherwise it reports `TOOLCHAIN_MISSING`, delivers the complete source project, and never claims that a PDF was compiled.
- [x] **ASST-01**: Every included figure and table has provenance, caption/label ownership, source/result references, and either a local source asset or reproducible generation/rendering command, without silently overwriting director-owned assets.

### Audit and Delivery

- [x] **AUDT-01**: Deterministic audits cover abstract/body/conclusion claim closure, claim-evidence entailment references, result numbers against frozen sources, BibTeX/in-text citation closure, terminology/notation, labels/cross-references, required sections, anonymity, official venue constraints, LaTeX compilation, and PDF existence whenever compilation is claimed.
- [ ] **DELV-01**: The run delivers human-first outputs under `director-review/` plus machine evidence bundles, including a manuscript overview, local-literature coverage report, authoring plan, LaTeX source tree, compiled PDF when available, quality report, reviewer report, and submission checklist.
- [x] **DELV-02**: The run reports `USABLE`, `USABLE_WITH_CAVEATS`, `NEEDS_SUPPLEMENT`, or `BLOCK`; readable work survives advisory defects, only truth/permission/irrecoverable-input/false-execution defects hard-block daily delivery, and submission readiness remains strict.

### Safety and Platform Boundaries

- [x] **SAFE-01**: Authoring and review keep PhD-Research-OS read-only and never copy a draft, search result, manuscript, or PDF into it without a later explicit top-level `/promote-to-vault` command.
- [x] **SAFE-02**: Secrets never appear in request URLs, error artifacts, logs, generated LaTeX, build metadata, or director-review outputs.
- [x] **SAFE-03**: The capability does not run GPU experiments and accepts execution claims only from frozen, auditable result artifacts rather than scripts, model-authored metrics, or unsupported prose.
- [x] **PLAT-01**: The local CLI, path handling, fixtures, and optional LaTeX tool detection operate on the repository's supported Python runtime on Windows and Linux.
- [ ] **PLAT-02**: The control plane remains domain-general, with AI-research defaults supplied through profile or Paper Design Token overlays rather than hardcoded domain rules.

### Verification Evidence

- [x] **VERI-01**: A local-first end-to-end fixture reaches frozen context, dependency-safe authoring bundles, integration, LaTeX generation, quality gates, director-review Markdown, and honest PDF build status.
- [x] **VERI-02**: Automated tests prove sufficient local evidence suppresses online search, explicit deficits activate only the existing search engine, search failures remain explicit, and no OpenAlex download code path exists.
- [x] **VERI-03**: Automated tests prove token cascade precedence and hard-rule versus advisory-rule separation.
- [x] **VERI-04**: Negative-path tests reject or surface unsupported citations/numbers, false execution claims, database writes, unsafe paths, missing required roles, inconsistent terminology/labels, secret leakage, and false PDF claims at the correct gate.
- [x] **VERI-05**: Relevant unit, integration, operated-mode, AI-eval, security, and completion verification commands pass and leave inspectable evidence artifacts.

## v2 Requirements

None committed. Scope discovered during Phase 1 must be explicitly accepted before it is added here or to the roadmap.

## Out of Scope

| Feature | Reason |
|---------|--------|
| Bulk paper downloading or corpus construction | Conflicts with local-first, deficit-triggered retrieval and expands the acquisition surface |
| OpenAlex PDF/content download integration | OpenAlex remains metadata-only inside the existing search engine |
| Autonomous submission to a venue | Publication is a director decision |
| Autonomous vault promotion | The database write seam requires a separate explicit top-level `/promote-to-vault` command |
| GPU experiment execution | This phase authors from already frozen, auditable results |
| Universal manuscript prose template | Paper/venue/project/run token overlays preserve useful variation |
| FlowCopilot as a second control plane | Existing Research Agent Teams orchestration remains authoritative |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| OPER-01 | Phase 1 | Pending |
| OPER-02 | Phase 1 | Complete |
| OPER-03 | Phase 1 | Pending |
| PREP-01 | Phase 1 | Complete |
| PREP-02 | Phase 1 | Complete |
| PREP-03 | Phase 1 | Pending |
| PREP-04 | Phase 1 | Pending |
| EVID-01 | Phase 1 | Complete |
| EVID-02 | Phase 1 | Complete |
| EVID-03 | Phase 1 | Complete |
| ORCH-01 | Phase 1 | Complete |
| ORCH-02 | Phase 1 | Complete |
| LATX-01 | Phase 1 | Complete |
| LATX-02 | Phase 1 | Complete |
| ASST-01 | Phase 1 | Complete |
| AUDT-01 | Phase 1 | Complete |
| DELV-01 | Phase 1 | Pending |
| DELV-02 | Phase 1 | Complete |
| SAFE-01 | Phase 1 | Complete |
| SAFE-02 | Phase 1 | Complete |
| SAFE-03 | Phase 1 | Complete |
| PLAT-01 | Phase 1 | Complete |
| PLAT-02 | Phase 1 | Pending |
| VERI-01 | Phase 1 | Complete |
| VERI-02 | Phase 1 | Complete |
| VERI-03 | Phase 1 | Complete |
| VERI-04 | Phase 1 | Complete |
| VERI-05 | Phase 1 | Complete |

**Coverage:**

- v1 requirements: 28 total
- Mapped to phases: 28
- Unmapped: 0 ✓
- Duplicate phase assignments: 0 ✓

---
*Requirements defined: 2026-07-21 from the locked manuscript-authoring SPEC*  
*Last updated: 2026-07-21 after initial roadmap mapping*
