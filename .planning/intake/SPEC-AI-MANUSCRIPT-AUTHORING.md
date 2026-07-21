---
type: SPEC
status: locked-for-phase-1
date: 2026-07-21
source: director-request-and-approved-design
---

# AI Manuscript Authoring System

## Problem

The machine has strong paper-reading, evidence, and venue-review capabilities, but it does not yet provide a one-button, operated path that turns approved research evidence into a coherent AI-research manuscript, a compilable LaTeX project, a PDF, and a review package. The missing authoring control plane also makes parallel section writing vulnerable to terminology, claim, citation, number, figure, and style drift.

## Goal

Add a usable-first AI manuscript authoring product to `research_agent_teams/`. It must preserve the machine/database seam, use existing local literature before network search, support sparse parallel agent work with a single integrator, and produce both readable work-in-progress and strict submission-readiness evidence.

## Locked requirements

1. Add a real operated `manuscript_authoring` mode. Keep manuscript review/rebuttal as a distinct operated review path rather than conflating review with generation.
2. Select and freeze a paper type and a realistic target-venue family before drafting. Defaults must prioritize current top AI conferences/journals and CCF A-class or equivalent venues; official venue rules override community conventions.
3. Literature is local-first. Recall and read existing papers/notes in the read-only PhD-Research-OS database first. Invoke the machine's existing paper search only when an explicit coverage assessment finds missing comparison, implementation, method, dataset, metric, or industry-prior-art evidence.
4. Do not build or invoke an OpenAlex PDF downloader. OpenAlex may remain one metadata provider inside the existing search engine, but this phase adds no bulk download, content API, or automatic PDF acquisition path.
5. Freeze a manuscript snapshot containing at least the paper brief, outline, claim ledger, evidence/result references, terminology/notation, venue profile, bibliography state, figure/table plan, and resolved Paper Design Tokens before parallel section authoring.
6. Implement cascading Paper Design Tokens with precedence `base -> paper type -> venue -> project -> run override`. Hard rules are intentionally small: official template/anonymity, claim/number/citation traceability, terminology/notation consistency, figure provenance, compile/cross-reference integrity, and no fabrication. Section structure, voice, paragraph style, caption style, rhetorical preferences, and most formatting guidance are advisory.
7. Preserve the director's 90/10 priority: usability and scientific quality dominate; governance is minimal and focused. A readable draft may be delivered as `USABLE_WITH_CAVEATS`. Only truth, permission, irrecoverable-input, or false-execution defects hard-block daily delivery. Submission readiness remains strict.
8. Use a sparse multi-agent DAG with explicit roles for venue/corpus reconnaissance, paper architecture, evidence stewardship, section authors, figures/tables, manuscript integration, independent factual/citation/style/LaTeX audits, and submission packaging. Section authors receive frozen shared context plus only their dependency slices. One integrator owns cross-section coherence.
9. Generate a native LaTeX project with `main.tex`, `refs.bib`, section files, figure/table manifests, build metadata, and a deterministic quality report. Build a PDF with a detected LaTeX engine when available. If no engine is installed, report `TOOLCHAIN_MISSING` honestly and still deliver the complete source project; never fake a compiled PDF.
10. Figures must support local existing assets, generated source files, and reproducible rendering commands. Every included figure/table needs provenance, caption/label ownership, and source/result references. No worker may silently overwrite a director-owned source asset.
11. Validate abstract/body/conclusion claim closure, claim-evidence entailment references, result numbers against frozen result sources, BibTeX/in-text citation closure, terminology/notation, labels/cross-references, required section coverage, anonymity, official venue constraints, LaTeX compilation, and PDF existence when compilation is claimed.
12. Produce human-first outputs under the run's `director-review/` tree plus machine evidence bundles. Required deliverables include a manuscript overview, local-literature coverage report, authoring plan, LaTeX source tree, compiled PDF when possible, quality report, reviewer report, and submission checklist.
13. The database is read-only during authoring. No draft, search result, manuscript, or PDF crosses into PhD-Research-OS without a top-level explicit `/promote-to-vault` command.
14. Search/network failures must remain distinguishable from genuine evidence absence. Secrets must not appear in URLs, error artifacts, logs, generated LaTeX, or review packets.
15. The new capability must be domain-general. AI-research defaults belong in a profile/token overlay, not hardcoded into the control plane.

## Current-state constraints

- Existing operated modes and schemas are authoritative patterns; the new path should reuse `read_paper_deep` sparse-wave scheduling, usable-first delivery, tamper-evident runs, director-review Markdown, and deterministic gates.
- Existing user changes in the worktree must be preserved.
- GPU experiment execution is outside this phase. A manuscript may only claim execution supported by frozen, auditable result artifacts.
- FlowCopilot is an inspected reference for run isolation, checkpoints, diffs, resumability, and publication-figure workflows; it must not become a second control plane and its rigid universal style rules are advisory unless adopted by tokens.

## Done when

1. Capability facts and registry report `manuscript_authoring` and manuscript review accurately as operated only when their recipes exist.
2. An end-to-end fixture can run from a local-first evidence input through frozen design context, parallel authoring bundles, integration, LaTeX project generation, quality gates, director-review Markdown, and PDF build status.
3. Tests prove local evidence suppresses unnecessary online search and explicit deficits activate only the existing search engine; no OpenAlex download code is introduced.
4. Tests prove token cascade precedence and hard/advisory rule separation.
5. Tests prove unsupported citations/numbers, false execution claims, database writes, unsafe paths, missing required roles, inconsistent terminology/labels, and false PDF claims are rejected or surfaced at the correct gate.
6. The relevant unit, integration, operated-mode, AI-eval, security, and completion verification commands pass with evidence artifacts.

## Non-goals

- Bulk paper downloading or corpus construction.
- Autonomous submission to a venue.
- Autonomous promotion into the database.
- Running GPU experiments.
- Enforcing a single universal prose template on every paper.
