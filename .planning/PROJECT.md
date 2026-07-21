# Research Agent Teams — AI Manuscript Authoring

## What This Is

An extension to the existing Research Agent Teams machine that turns locally held, auditable AI-research evidence and frozen result references into a coherent multi-agent-authored LaTeX manuscript. It gives the director separate operated authoring and manuscript-review paths, honest PDF build status, deterministic manuscript audits, and human-first review artifacts while keeping all draft work in the machine's scratch run store.

## Core Value

Turn locally held, auditable AI-research evidence into a coherent multi-agent-authored LaTeX manuscript, honest PDF build status, and strict submission evidence without polluting the database.

## Success Measure

A local-first end-to-end fixture runs through evidence coverage, frozen tokens/context, section authoring and integration, LaTeX source generation, PDF compiler detection/build status, manuscript audits, and director-review output; relevant unit, integration, operated-mode, AI-eval, security, and completion checks pass with evidence; no database write or OpenAlex download path exists.

## Requirements

### Validated

- ✓ The existing machine provides resumable operated-mode recipes, sparse dependency-safe worker waves, schema validation, tamper-evident run state, deterministic gates, and Markdown-first director review outputs.
- ✓ The PhD-Research-OS seam already supports bounded read-by-reference recall and an explicit top-level `/promote-to-vault` write gate.
- ✓ Existing scholarly search can query metadata providers and degrade honestly when network providers fail.

### Active

- [ ] Provide distinct, truthfully registered operated paths for manuscript authoring and manuscript review/rebuttal.
- [ ] Assess local literature coverage first and activate only the existing search engine for explicit evidence deficits, with no OpenAlex or bulk PDF acquisition path.
- [ ] Freeze paper type, venue family, manuscript context, evidence references, and cascading Paper Design Tokens before section drafting.
- [ ] Author through a sparse role DAG with scoped context and one integration owner for cross-section coherence.
- [ ] Deliver a native LaTeX project, provenance-bound figures/tables, and either a real compiled PDF or an honest `TOOLCHAIN_MISSING` status.
- [ ] Produce readable director-review outputs and deterministic scientific, citation, consistency, venue, LaTeX, and submission audits.
- [ ] Preserve usable-first daily delivery while keeping truth, permission, execution, and submission-readiness gates strict.
- [ ] Prove the complete capability with local-first fixtures and proportionate unit, integration, eval, security, and completion verification.

### Out of Scope

- Bulk paper downloading or corpus construction — local recall and targeted use of the existing search engine are sufficient for this capability.
- Autonomous venue submission — submission remains a director decision outside manuscript generation.
- Autonomous vault promotion — only a later explicit top-level `/promote-to-vault` command may write the database.
- GPU experiment execution — manuscripts may cite only already frozen, auditable result artifacts.
- A universal prose template — paper and venue conventions are resolved through advisory token overlays rather than one rigid style.
- A second control plane based on FlowCopilot — it remains reference material for isolation, checkpoints, diffs, resumability, and figure workflows.

## Context

The current Python CLI is a local, configuration-driven research control plane rather than a web service. Operated products live in `operate/modes/`, use the shared scheduler and deterministic contract layer, and expose a Markdown entry point under each run's `director-review/` tree. At project initialization, `manuscript_review_pack` is routable/spec-only and `manuscript_authoring` is not yet an operated product; neither may be advertised as one-button operated until its concrete recipe exists.

The target runtime is the repository's current Python CLI on Windows and Linux. A LaTeX engine is optional and detected at runtime. The sibling PhD-Research-OS repository is the validated knowledge database; manuscript drafts, search results, source trees, PDFs, and review artifacts remain machine-side scratch unless the director separately invokes the promotion gate.

## Constraints

- **Delivery shape**: One coherent vertical Phase 1 covers authoring, review, LaTeX output, audits, and verification; internal plans may use architecture, implementation, review, and verification waves.
- **Local-first evidence**: Recall and read the read-only vault first; online search is activated only by an explicit coverage deficit and uses the existing search engine.
- **No acquisition expansion**: Do not add or invoke an OpenAlex PDF downloader, bulk-download path, content API, or automatic PDF acquisition flow.
- **Database boundary**: Authoring is read-only with respect to PhD-Research-OS; only the explicit top-level `/promote-to-vault` command may cross the write seam.
- **Usability policy**: Preserve the director's 90/10 priority. Readable work may be `USABLE_WITH_CAVEATS`; only truth, permission, irrecoverable-input, or false-execution defects hard-block daily delivery, while submission readiness remains strict.
- **Execution truth**: No GPU execution occurs in this scope, and no execution claim is accepted without frozen, auditable result evidence.
- **Authoring contract**: Freeze the manuscript snapshot and resolved token cascade before parallel authors receive their dependency slices; one integrator owns cross-section coherence.
- **Toolchain honesty**: Detect an external LaTeX engine at runtime. Missing tooling yields `TOOLCHAIN_MISSING` plus complete source, never a fabricated PDF.
- **Cross-platform**: Path handling, CLI behavior, fixtures, and tool detection must work on Windows and Linux.
- **Domain generality**: AI-research defaults live in profile/token overlays, not in the generic orchestration control plane.
- **Security**: Search failures remain distinct from evidence absence, and secrets never appear in URLs, errors, logs, generated LaTeX, or review packets.
- **Architecture reuse**: Extend authoritative operated recipes, schemas, scheduler, run store, director-review renderer, and deterministic gates; FlowCopilot does not become a second control plane.
- **Worktree safety**: Preserve all existing user changes and avoid unrelated source or planning rewrites.

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Deliver the accepted system as one vertical Phase 1 | Authoring is useful only when evidence, integration, LaTeX, audits, and review output work end to end | — Pending |
| Keep authoring and manuscript review/rebuttal as separate operated recipes | Generation and independent review have different roles, evidence, and truth boundaries | — Pending |
| Use local-first coverage with deficit-triggered existing search | Maximizes reuse of auditable local evidence and avoids unnecessary acquisition | — Pending |
| Freeze paper/venue context and cascading tokens before parallel writing | Prevents claim, terminology, notation, citation, number, figure, and style drift | — Pending |
| Use a sparse multi-agent DAG with a single integrator | Preserves independent specialist work while giving one owner cross-section coherence | — Pending |
| Separate daily usability from strict submission readiness | Readable work can be delivered early without weakening scientific-truth or submission gates | — Pending |
| Treat LaTeX compilation as optional external capability | Source delivery remains reliable on machines without a compiler and PDF status stays honest | — Pending |
| Keep the database read-only throughout authoring | Protects the machine/database seam and prevents drafts from polluting permanent knowledge | — Pending |

## Evolution

After Phase 1, move verified active requirements to Validated, record any changed constraints or decisions, and update this description only if the shipped operated surface differs from the accepted scope.

---
*Last updated: 2026-07-21 after approved project initialization from the locked manuscript-authoring SPEC*
