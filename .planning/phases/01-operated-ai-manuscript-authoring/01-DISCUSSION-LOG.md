# Phase 1: Operated AI Manuscript Authoring - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md; this log preserves the alternatives considered.

**Date:** 2026-07-21
**Phase:** 1-operated-ai-manuscript-authoring
**Areas discussed:** product boundary, literature acquisition, style governance, parallel authorship, LaTeX/PDF truth, delivery gates

---

## Product boundary

| Option | Description | Selected |
|--------|-------------|----------|
| Review-only pack | Productize only the existing manuscript review registry spec | |
| One combined writer/reviewer | Generation and review share one evidence stream | |
| Distinct operated authoring and review | Separate recipes and evidence lineage with shared deterministic utilities | Yes |

**User's choice:** Distinct operated authoring and manuscript review/rebuttal paths.
**Notes:** The current system is strong at evidence and review but lacks end-to-end manuscript generation; both capabilities must be honestly productized.

---

## Literature acquisition

| Option | Description | Selected |
|--------|-------------|----------|
| Redownload a corpus | Build a new OpenAlex/PDF acquisition path before writing | |
| Always search online | Query providers for every manuscript regardless of local holdings | |
| Local-first, deficit-triggered search | Read existing database evidence first and invoke the existing search engine only for named gaps | Yes |

**User's choice:** Use existing local papers first; search online only when comparison, implementation, technical, or industry evidence is insufficient.
**Notes:** No OpenAlex download capability is added. Provider failure must not masquerade as evidence absence.

---

## Style governance

| Option | Description | Selected |
|--------|-------------|----------|
| Rigid universal template | Hard-code section and paragraph rules for every paper | |
| No shared contract | Let each author choose its own style and terminology | |
| Cascading Paper Design Tokens | Freeze a small hard core and keep most prose/format guidance advisory | Yes |

**User's choice:** CSS-like cascading tokens with usability/quality weighted about 90% and governance 10% or less.
**Notes:** Official format, truth traceability, terminology/notation, provenance, cross-references, and no fabrication are hard; most writing style remains flexible.

---

## Parallel authorship

| Option | Description | Selected |
|--------|-------------|----------|
| One monolithic writer | One agent writes every section serially | |
| Independent section files only | Many agents write without a canonical integration owner | |
| Sparse DAG plus one integrator | Scoped parallel specialists feed one owner of global coherence, followed by independent audits | Yes |

**User's choice:** Clear parallel roles, dependency-safe waves, one integrator, and independent validation.
**Notes:** Capability roles are required; exact worker and wave counts may adapt so governance does not make the system unusable.

---

## LaTeX and PDF truth

| Option | Description | Selected |
|--------|-------------|----------|
| Markdown only | Stop before a native submission source tree | |
| Claim PDF without build proof | Treat generated TeX as equivalent to compilation | |
| Native source plus honest build receipt | Compile with a detected engine or report `TOOLCHAIN_MISSING` with complete source | Yes |

**User's choice:** LaTeX-to-PDF is a first-class output; compilation claims require actual build evidence.
**Notes:** Local figure sources remain immutable and every rendered asset is provenance-bound in run scratch.

---

## Delivery gates

| Option | Description | Selected |
|--------|-------------|----------|
| Block on every defect | Hide readable work for presentation or advisory style issues | |
| Never block | Deliver even with fabricated citations, numbers, or execution claims | |
| Usable-first plus strict truth/submission gates | Deliver caveated drafts while hard-blocking truth/safety failures and keeping submission readiness strict | Yes |

**User's choice:** First make it useful and high quality; use minimal, focused governance without weakening scientific truth.
**Notes:** Daily and submission verdicts are separate so toolchain/style gaps do not erase readable work.

---

## the agent's Discretion

- Exact compiler priority, timeout defaults, source module split, schema filenames, advisory token values, optional specialist skips, and section-role granularity within the locked boundaries.

## Deferred Ideas

- Automatic full-text acquisition, live GPU execution, autonomous submission, and autonomous vault promotion.
