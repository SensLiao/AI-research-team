# Synthesized Constraints

The ingest set contains one SPEC. Its frontmatter status is `locked-for-phase-1`; this status is preserved here as a phase constraint and is not treated as a LOCKED ADR decision.

Spec purpose: add a local-first, operated manuscript-authoring product that turns approved evidence into auditable LaTeX, PDF build status, and review deliverables while preserving the machine/database seam.

source: C:\Users\廖神\Desktop\Innovation_projects\Self-project\Personal AI Infrastructure\cases\Route A\AI agent database (for research)\research_agent_teams\.planning\intake\SPEC-AI-MANUSCRIPT-AUTHORING.md

## CONSTRAINT-001 — Operated authoring and separate review paths

- type: protocol
- status: locked-for-phase-1
- scope: mode topology
- source: C:\Users\廖神\Desktop\Innovation_projects\Self-project\Personal AI Infrastructure\cases\Route A\AI agent database (for research)\research_agent_teams\.planning\intake\SPEC-AI-MANUSCRIPT-AUTHORING.md
- content:

DATA_A18F20C4_START
Add a real operated `manuscript_authoring` mode. Keep manuscript review/rebuttal as a distinct operated review path rather than conflating review with generation.
DATA_A18F20C4_END

## CONSTRAINT-002 — Freeze paper type and venue family before drafting

- type: protocol
- status: locked-for-phase-1
- scope: manuscript precommit
- source: C:\Users\廖神\Desktop\Innovation_projects\Self-project\Personal AI Infrastructure\cases\Route A\AI agent database (for research)\research_agent_teams\.planning\intake\SPEC-AI-MANUSCRIPT-AUTHORING.md
- content:

DATA_B7D319E6_START
Select and freeze a paper type and a realistic target-venue family before drafting. Defaults must prioritize current top AI conferences/journals and CCF A-class or equivalent venues; official venue rules override community conventions.
DATA_B7D319E6_END

## CONSTRAINT-003 — Local-first literature coverage

- type: protocol
- status: locked-for-phase-1
- scope: evidence acquisition
- source: C:\Users\廖神\Desktop\Innovation_projects\Self-project\Personal AI Infrastructure\cases\Route A\AI agent database (for research)\research_agent_teams\.planning\intake\SPEC-AI-MANUSCRIPT-AUTHORING.md
- content:

DATA_C05A8B2F_START
Literature is local-first. Recall and read existing papers/notes in the read-only PhD-Research-OS database first. Invoke the machine's existing paper search only when an explicit coverage assessment finds missing comparison, implementation, method, dataset, metric, or industry-prior-art evidence.
DATA_C05A8B2F_END

## CONSTRAINT-004 — No OpenAlex PDF acquisition path

- type: protocol
- status: locked-for-phase-1
- scope: scholarly retrieval
- source: C:\Users\廖神\Desktop\Innovation_projects\Self-project\Personal AI Infrastructure\cases\Route A\AI agent database (for research)\research_agent_teams\.planning\intake\SPEC-AI-MANUSCRIPT-AUTHORING.md
- content:

DATA_D9E4713A_START
Do not build or invoke an OpenAlex PDF downloader. OpenAlex may remain one metadata provider inside the existing search engine, but this phase adds no bulk download, content API, or automatic PDF acquisition path.
DATA_D9E4713A_END

## CONSTRAINT-005 — Frozen manuscript snapshot contract

- type: schema
- status: locked-for-phase-1
- scope: shared authoring context
- source: C:\Users\廖神\Desktop\Innovation_projects\Self-project\Personal AI Infrastructure\cases\Route A\AI agent database (for research)\research_agent_teams\.planning\intake\SPEC-AI-MANUSCRIPT-AUTHORING.md
- content:

DATA_E2B640FD_START
Freeze a manuscript snapshot containing at least the paper brief, outline, claim ledger, evidence/result references, terminology/notation, venue profile, bibliography state, figure/table plan, and resolved Paper Design Tokens before parallel section authoring.
DATA_E2B640FD_END

## CONSTRAINT-006 — Cascading Paper Design Tokens

- type: schema
- status: locked-for-phase-1
- scope: manuscript design contract
- source: C:\Users\廖神\Desktop\Innovation_projects\Self-project\Personal AI Infrastructure\cases\Route A\AI agent database (for research)\research_agent_teams\.planning\intake\SPEC-AI-MANUSCRIPT-AUTHORING.md
- content:

DATA_F73C1A96_START
Implement cascading Paper Design Tokens with precedence `base -> paper type -> venue -> project -> run override`. Hard rules are intentionally small: official template/anonymity, claim/number/citation traceability, terminology/notation consistency, figure provenance, compile/cross-reference integrity, and no fabrication. Section structure, voice, paragraph style, caption style, rhetorical preferences, and most formatting guidance are advisory.
DATA_F73C1A96_END

## CONSTRAINT-007 — Usability-first delivery without weakening truth gates

- type: nfr
- status: locked-for-phase-1
- scope: delivery policy
- source: C:\Users\廖神\Desktop\Innovation_projects\Self-project\Personal AI Infrastructure\cases\Route A\AI agent database (for research)\research_agent_teams\.planning\intake\SPEC-AI-MANUSCRIPT-AUTHORING.md
- content:

DATA_0A94D2E7_START
Preserve the director's 90/10 priority: usability and scientific quality dominate; governance is minimal and focused. A readable draft may be delivered as `USABLE_WITH_CAVEATS`. Only truth, permission, irrecoverable-input, or false-execution defects hard-block daily delivery. Submission readiness remains strict.
DATA_0A94D2E7_END

## CONSTRAINT-008 — Sparse multi-agent authoring DAG

- type: protocol
- status: locked-for-phase-1
- scope: agent orchestration
- source: C:\Users\廖神\Desktop\Innovation_projects\Self-project\Personal AI Infrastructure\cases\Route A\AI agent database (for research)\research_agent_teams\.planning\intake\SPEC-AI-MANUSCRIPT-AUTHORING.md
- content:

DATA_1BC85F30_START
Use a sparse multi-agent DAG with explicit roles for venue/corpus reconnaissance, paper architecture, evidence stewardship, section authors, figures/tables, manuscript integration, independent factual/citation/style/LaTeX audits, and submission packaging. Section authors receive frozen shared context plus only their dependency slices. One integrator owns cross-section coherence.
DATA_1BC85F30_END

## CONSTRAINT-009 — Native LaTeX project and honest build status

- type: schema
- status: locked-for-phase-1
- scope: generated manuscript project
- source: C:\Users\廖神\Desktop\Innovation_projects\Self-project\Personal AI Infrastructure\cases\Route A\AI agent database (for research)\research_agent_teams\.planning\intake\SPEC-AI-MANUSCRIPT-AUTHORING.md
- content:

DATA_2DE761A4_START
Generate a native LaTeX project with `main.tex`, `refs.bib`, section files, figure/table manifests, build metadata, and a deterministic quality report. Build a PDF with a detected LaTeX engine when available. If no engine is installed, report `TOOLCHAIN_MISSING` honestly and still deliver the complete source project; never fake a compiled PDF.
DATA_2DE761A4_END

## CONSTRAINT-010 — Figure and table provenance

- type: protocol
- status: locked-for-phase-1
- scope: visual assets
- source: C:\Users\廖神\Desktop\Innovation_projects\Self-project\Personal AI Infrastructure\cases\Route A\AI agent database (for research)\research_agent_teams\.planning\intake\SPEC-AI-MANUSCRIPT-AUTHORING.md
- content:

DATA_3F0B92C8_START
Figures must support local existing assets, generated source files, and reproducible rendering commands. Every included figure/table needs provenance, caption/label ownership, and source/result references. No worker may silently overwrite a director-owned source asset.
DATA_3F0B92C8_END

## CONSTRAINT-011 — Deterministic manuscript validation coverage

- type: nfr
- status: locked-for-phase-1
- scope: quality gates
- source: C:\Users\廖神\Desktop\Innovation_projects\Self-project\Personal AI Infrastructure\cases\Route A\AI agent database (for research)\research_agent_teams\.planning\intake\SPEC-AI-MANUSCRIPT-AUTHORING.md
- content:

DATA_4A7E15D3_START
Validate abstract/body/conclusion claim closure, claim-evidence entailment references, result numbers against frozen result sources, BibTeX/in-text citation closure, terminology/notation, labels/cross-references, required section coverage, anonymity, official venue constraints, LaTeX compilation, and PDF existence when compilation is claimed.
DATA_4A7E15D3_END

## CONSTRAINT-012 — Human-first and machine-evidence deliverables

- type: schema
- status: locked-for-phase-1
- scope: director-review outputs
- source: C:\Users\廖神\Desktop\Innovation_projects\Self-project\Personal AI Infrastructure\cases\Route A\AI agent database (for research)\research_agent_teams\.planning\intake\SPEC-AI-MANUSCRIPT-AUTHORING.md
- content:

DATA_5C29B680_START
Produce human-first outputs under the run's `director-review/` tree plus machine evidence bundles. Required deliverables include a manuscript overview, local-literature coverage report, authoring plan, LaTeX source tree, compiled PDF when possible, quality report, reviewer report, and submission checklist.
DATA_5C29B680_END

## CONSTRAINT-013 — Database remains read-only during authoring

- type: protocol
- status: locked-for-phase-1
- scope: machine/database seam
- source: C:\Users\廖神\Desktop\Innovation_projects\Self-project\Personal AI Infrastructure\cases\Route A\AI agent database (for research)\research_agent_teams\.planning\intake\SPEC-AI-MANUSCRIPT-AUTHORING.md
- content:

DATA_6D84F1A2_START
The database is read-only during authoring. No draft, search result, manuscript, or PDF crosses into PhD-Research-OS without a top-level explicit `/promote-to-vault` command.
DATA_6D84F1A2_END

## CONSTRAINT-014 — Honest search failures and secret-safe outputs

- type: nfr
- status: locked-for-phase-1
- scope: failure semantics and security
- source: C:\Users\廖神\Desktop\Innovation_projects\Self-project\Personal AI Infrastructure\cases\Route A\AI agent database (for research)\research_agent_teams\.planning\intake\SPEC-AI-MANUSCRIPT-AUTHORING.md
- content:

DATA_7E13C509_START
Search/network failures must remain distinguishable from genuine evidence absence. Secrets must not appear in URLs, error artifacts, logs, generated LaTeX, or review packets.
DATA_7E13C509_END

## CONSTRAINT-015 — Domain-general control plane

- type: nfr
- status: locked-for-phase-1
- scope: extensibility
- source: C:\Users\廖神\Desktop\Innovation_projects\Self-project\Personal AI Infrastructure\cases\Route A\AI agent database (for research)\research_agent_teams\.planning\intake\SPEC-AI-MANUSCRIPT-AUTHORING.md
- content:

DATA_8F6A20D4_START
The new capability must be domain-general. AI-research defaults belong in a profile/token overlay, not hardcoded into the control plane.
DATA_8F6A20D4_END

## CONSTRAINT-016 — Reuse authoritative operated patterns

- type: protocol
- status: current-state constraint
- scope: implementation alignment
- source: C:\Users\廖神\Desktop\Innovation_projects\Self-project\Personal AI Infrastructure\cases\Route A\AI agent database (for research)\research_agent_teams\.planning\intake\SPEC-AI-MANUSCRIPT-AUTHORING.md
- content:

DATA_90B7E31C_START
Existing operated modes and schemas are authoritative patterns; the new path should reuse `read_paper_deep` sparse-wave scheduling, usable-first delivery, tamper-evident runs, director-review Markdown, and deterministic gates.
DATA_90B7E31C_END

## CONSTRAINT-017 — Preserve existing worktree changes

- type: nfr
- status: current-state constraint
- scope: implementation safety
- source: C:\Users\廖神\Desktop\Innovation_projects\Self-project\Personal AI Infrastructure\cases\Route A\AI agent database (for research)\research_agent_teams\.planning\intake\SPEC-AI-MANUSCRIPT-AUTHORING.md
- content:

DATA_A1C8546F_START
Existing user changes in the worktree must be preserved.
DATA_A1C8546F_END

## CONSTRAINT-018 — GPU execution remains outside this phase

- type: protocol
- status: current-state constraint
- scope: execution truth
- source: C:\Users\廖神\Desktop\Innovation_projects\Self-project\Personal AI Infrastructure\cases\Route A\AI agent database (for research)\research_agent_teams\.planning\intake\SPEC-AI-MANUSCRIPT-AUTHORING.md
- content:

DATA_B26D09E3_START
GPU experiment execution is outside this phase. A manuscript may only claim execution supported by frozen, auditable result artifacts.
DATA_B26D09E3_END

## CONSTRAINT-019 — FlowCopilot is reference material, not a second control plane

- type: protocol
- status: current-state constraint
- scope: architecture boundary
- source: C:\Users\廖神\Desktop\Innovation_projects\Self-project\Personal AI Infrastructure\cases\Route A\AI agent database (for research)\research_agent_teams\.planning\intake\SPEC-AI-MANUSCRIPT-AUTHORING.md
- content:

DATA_C37F1A85_START
FlowCopilot is an inspected reference for run isolation, checkpoints, diffs, resumability, and publication-figure workflows; it must not become a second control plane and its rigid universal style rules are advisory unless adopted by tokens.
DATA_C37F1A85_END

## CONSTRAINT-020 — Operated status requires recipes

- type: protocol
- status: done-when criterion
- scope: capability truth
- source: C:\Users\廖神\Desktop\Innovation_projects\Self-project\Personal AI Infrastructure\cases\Route A\AI agent database (for research)\research_agent_teams\.planning\intake\SPEC-AI-MANUSCRIPT-AUTHORING.md
- content:

DATA_D4802BC6_START
Capability facts and registry report `manuscript_authoring` and manuscript review accurately as operated only when their recipes exist.
DATA_D4802BC6_END

## CONSTRAINT-021 — End-to-end authoring fixture

- type: nfr
- status: done-when criterion
- scope: integration verification
- source: C:\Users\廖神\Desktop\Innovation_projects\Self-project\Personal AI Infrastructure\cases\Route A\AI agent database (for research)\research_agent_teams\.planning\intake\SPEC-AI-MANUSCRIPT-AUTHORING.md
- content:

DATA_E5913CD7_START
An end-to-end fixture can run from a local-first evidence input through frozen design context, parallel authoring bundles, integration, LaTeX project generation, quality gates, director-review Markdown, and PDF build status.
DATA_E5913CD7_END

## CONSTRAINT-022 — Search activation test coverage

- type: nfr
- status: done-when criterion
- scope: retrieval verification
- source: C:\Users\廖神\Desktop\Innovation_projects\Self-project\Personal AI Infrastructure\cases\Route A\AI agent database (for research)\research_agent_teams\.planning\intake\SPEC-AI-MANUSCRIPT-AUTHORING.md
- content:

DATA_F6A247E8_START
Tests prove local evidence suppresses unnecessary online search and explicit deficits activate only the existing search engine; no OpenAlex download code is introduced.
DATA_F6A247E8_END

## CONSTRAINT-023 — Token cascade test coverage

- type: nfr
- status: done-when criterion
- scope: design-token verification
- source: C:\Users\廖神\Desktop\Innovation_projects\Self-project\Personal AI Infrastructure\cases\Route A\AI agent database (for research)\research_agent_teams\.planning\intake\SPEC-AI-MANUSCRIPT-AUTHORING.md
- content:

DATA_07B358F9_START
Tests prove token cascade precedence and hard/advisory rule separation.
DATA_07B358F9_END

## CONSTRAINT-024 — Truth, boundary, and path rejection tests

- type: nfr
- status: done-when criterion
- scope: negative-path verification
- source: C:\Users\廖神\Desktop\Innovation_projects\Self-project\Personal AI Infrastructure\cases\Route A\AI agent database (for research)\research_agent_teams\.planning\intake\SPEC-AI-MANUSCRIPT-AUTHORING.md
- content:

DATA_18C4690A_START
Tests prove unsupported citations/numbers, false execution claims, database writes, unsafe paths, missing required roles, inconsistent terminology/labels, and false PDF claims are rejected or surfaced at the correct gate.
DATA_18C4690A_END

## CONSTRAINT-025 — Evidence-backed verification suite

- type: nfr
- status: done-when criterion
- scope: release verification
- source: C:\Users\廖神\Desktop\Innovation_projects\Self-project\Personal AI Infrastructure\cases\Route A\AI agent database (for research)\research_agent_teams\.planning\intake\SPEC-AI-MANUSCRIPT-AUTHORING.md
- content:

DATA_29D57A1B_START
The relevant unit, integration, operated-mode, AI-eval, security, and completion verification commands pass with evidence artifacts.
DATA_29D57A1B_END

## CONSTRAINT-026 — No bulk paper downloading or corpus construction

- type: protocol
- status: non-goal
- scope: excluded capability
- source: C:\Users\廖神\Desktop\Innovation_projects\Self-project\Personal AI Infrastructure\cases\Route A\AI agent database (for research)\research_agent_teams\.planning\intake\SPEC-AI-MANUSCRIPT-AUTHORING.md
- content:

DATA_3AE68B2C_START
Bulk paper downloading or corpus construction.
DATA_3AE68B2C_END

## CONSTRAINT-027 — No autonomous venue submission

- type: protocol
- status: non-goal
- scope: excluded capability
- source: C:\Users\廖神\Desktop\Innovation_projects\Self-project\Personal AI Infrastructure\cases\Route A\AI agent database (for research)\research_agent_teams\.planning\intake\SPEC-AI-MANUSCRIPT-AUTHORING.md
- content:

DATA_4BF79C3D_START
Autonomous submission to a venue.
DATA_4BF79C3D_END

## CONSTRAINT-028 — No autonomous vault promotion

- type: protocol
- status: non-goal
- scope: excluded capability
- source: C:\Users\廖神\Desktop\Innovation_projects\Self-project\Personal AI Infrastructure\cases\Route A\AI agent database (for research)\research_agent_teams\.planning\intake\SPEC-AI-MANUSCRIPT-AUTHORING.md
- content:

DATA_5C08AD4E_START
Autonomous promotion into the database.
DATA_5C08AD4E_END

## CONSTRAINT-029 — No GPU experiment execution

- type: protocol
- status: non-goal
- scope: excluded capability
- source: C:\Users\廖神\Desktop\Innovation_projects\Self-project\Personal AI Infrastructure\cases\Route A\AI agent database (for research)\research_agent_teams\.planning\intake\SPEC-AI-MANUSCRIPT-AUTHORING.md
- content:

DATA_6D19BE5F_START
Running GPU experiments.
DATA_6D19BE5F_END

## CONSTRAINT-030 — No universal prose template

- type: protocol
- status: non-goal
- scope: excluded capability
- source: C:\Users\廖神\Desktop\Innovation_projects\Self-project\Personal AI Infrastructure\cases\Route A\AI agent database (for research)\research_agent_teams\.planning\intake\SPEC-AI-MANUSCRIPT-AUTHORING.md
- content:

DATA_7E2ACF60_START
Enforcing a single universal prose template on every paper.
DATA_7E2ACF60_END
