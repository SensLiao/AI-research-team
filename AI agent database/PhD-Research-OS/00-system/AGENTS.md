---
type: routing
canonical: true
updated: 2026-05-01
---

# AGENTS.md — Vault Entry Contract (agent-agnostic)

> **Read this first if you are any AI agent (Claude / Codex / Cursor / future) about to read or write this vault.**
>
> This file is the **agent-agnostic** entry contract. It is a **pointer**, not a schema duplicate. The authoritative schema lives in `00-system/CLAUDE.md`. Tool-specific extensions live alongside the agent (e.g. project-root `.claude/CLAUDE.md` for Claude Code, `.codex-tasks/*.md` for Codex CLI).
>
> If anything below disagrees with `00-system/CLAUDE.md`, `CLAUDE.md` wins.

---

## §0 — Vault is the single source of truth

- All project knowledge for `{{PROJECT_TITLE}}` lives at `02-wiki/`.
- `01-raw/` is **immutable**. The agent never modifies files there.
- Any frozen legacy material from a prior workflow goes in a separate `legacy/` directory; the agent treats it as read-only and only consults it when the vault is genuinely silent on a topic.
- All new writes go to `02-wiki/` only. See `00-system/CLAUDE.md` §2.1.

---

## §1 — Required reading order (every session)

### L0 — ALWAYS READ (every session, ~3 pages)

1. `00-system/hot.md` — current session state cache (~500 words)
2. `00-system/index.md` — master catalog by type
3. `00-system/agent-startup-router.md` — task-type → required reading + actions + forbidden actions

### L1 — PROJECT CONDITIONAL (pull when starting any task on this project)

- `02-wiki/sources/project-brief.md`
- `02-wiki/sources/research-questions.md`
- `02-wiki/sources/claim-map.md` (if exists)
- Most recent `02-wiki/decisions/dec-*.md` (top 3 by date)
- `00-system/evidence-contract.md`

### L2 — TASK CONDITIONAL (pull only if the task type signals the need)

- `02-wiki/sources/paper-reading-index.md` (paper / lit work)
- `02-wiki/sources/experiment-protocol.md` (experiment work)
- `02-wiki/sources/bug-class-index.md` (debug work)
- `02-wiki/sources/model-footgun-index.md` (code change work)
- `02-wiki/sources/writing-style-guide.md` (paper / thesis writing)
- `02-wiki/sources/supervisor-feedback-index.md` (post-meeting)

The split is **intentional and load-bearing** — do not eat all 12+ pages every session.

---

## §2 — Result citation gate

Before quoting **any** number from `02-wiki/results/`:

```
can-cite-thesis  ==  (result-status == "frozen")
                AND  (leakage-audit  == "pass")
                AND  (fairness-audit == "pass")
                AND  (reproducibility-audit == "pass")   # if reproducibility_level == "full"
```

- `can-cite-thesis` is a **derived** field — manual override is forbidden. Fix the underlying audits, not the derived flag.
- If `can-cite-thesis: false`, do **not** quote the value as a thesis fact. Use safe phrasing per `02-wiki/sources/results-validity-policy.md` (or fall back to: `(provisional)`, `(invalidated by <PM>)`, `(subject to <audit>)`).
- Forbidden state transitions: `frozen → provisional`, `invalid → frozen`. Re-running a fix produces a NEW row, not a status flip on the old row.

---

## §3 — Anti-hallucination: every claim carries an evidence label

When you make any claim about code, results, papers, or the project, label it with one of:

| Label | Meaning |
|---|---|
| `CODE-LIVE` | Just inspected the relevant code/file in this session |
| `VAULT-CITE` | Cited from a vault page with `[[slug]]` reference |
| `EXP-RESULT` | Pulled from a `02-wiki/results/<slug>.md` page (gated through §2) |
| `PAPER-CITE` | Cited from a `02-wiki/papers/<slug>.md` page or external DOI |
| `DATA-CITE` | Cited from a dataset / annotation / split file in `02-wiki/datasets/` |
| `MEETING-CITE` | Cited from a `02-wiki/meetings/<slug>.md` page |
| `DECISION-CITE` | Cited from a `02-wiki/decisions/<slug>.md` page |
| `ASSUMPTION` | Inferred / cannot verify right now |

- **Default for any unlabeled claim is `ASSUMPTION`** — the user can demand "show me the evidence for X" at any point.
- Code claims require `CODE-LIVE` (no model-memory-based code assertions).
- Result-number claims require `EXP-RESULT` AND must pass §2 citation gate.

Full 9-clause spec: `00-system/evidence-contract.md`.

---

## §4 — Vault-write protocol

| What | Where |
|---|---|
| New external paper | `02-wiki/papers/<firstauthor>-<year>-<shortname>.md` using `04-templates/paper.md` |
| New benchmark/experiment metric | `02-wiki/results/<slug>.md` using `04-templates/result.md` |
| New experiment design | `02-wiki/experiments/<exp-slug>.md` using `04-templates/experiment.md` |
| Specific run of an experiment | `02-wiki/runs/run-<exp>-NNN.md` using `04-templates/run.md` |
| Thesis claim | `02-wiki/claims/claim-<slug>.md` using `04-templates/claim.md` |
| Decision (ADR) | `02-wiki/decisions/dec-NNNN-<topic>.md` using `04-templates/decision.md` |
| Cross-cutting writeup / chapter draft | `02-wiki/syntheses/<slug>.md` |
| Meeting notes | `02-wiki/meetings/meeting-YYYY-MM-DD-<topic>.md` |
| New method / model / dataset card | `02-wiki/{methods,models,datasets}/<slug>.md` |
| Hypothesis / future work | `02-wiki/ideas/<slug>.md` |
| Process-memory entry (PM) | `02-wiki/process-memory/pm-NNNN-<slug>.md` |
| Failure record | `02-wiki/negative-results/<slug>.md` |
| Compute budget snapshot | `02-wiki/compute-budgets/<period>.md` |

Every vault write must:
1. Use a valid `type:` from `05-registry/type-registry.md`
2. Fill universal frontmatter per `00-system/CLAUDE.md` §3.3
3. Update `00-system/index.md` and `07-logs/log.md`
4. Touch `00-system/hot.md` if session-relevant
5. Use `[[slug]]` wikilinks only — never relative paths

---

## §5 — Canonical pages: edit with checkpoint

If you edit a page with `canonical: true` in frontmatter (most `00-system/*` pages and `05-registry/*`):
- Your first user-visible message of the session must include `Editing canonical page [[<slug>]] — change summary: <one sentence>`
- Append to `07-logs/log.md` with the `CONTRACT-EDIT:` tag, capturing: page, change-summary, before-state, after-state, rationale

This is the structural protection against silent contract drift.

---

## §6 — Tool-specific overlays (read AFTER this file)

| Tool | Overlay file | What it adds |
|---|---|---|
| Claude Code | `.claude/CLAUDE.md` (project-root) | Project-specific hard rules, server constraints, write rules |
| Codex CLI | `.codex-tasks/<task>.md` per-task spec | Task-scoped instructions; Codex must also read this AGENTS.md before vault writes |
| Cursor / other | This file is enough | Then drill into `agent-startup-router.md` |

---

## §7 — Hard "do not"

- ❌ Modify `01-raw/` files
- ❌ Quote a result number where `can-cite-thesis: false` as if it were a thesis fact
- ❌ Manual override of `can-cite-thesis` (it is derived)
- ❌ Allow forbidden status transitions (`frozen → provisional`, `invalid → frozen`)
- ❌ Add a new vault `type:` without updating `05-registry/type-registry.md` first
- ❌ Skip `07-logs/log.md` after any INGEST / EDIT / SCHEMA / BACKFILL operation
- ❌ Bypass the agent-startup-router for non-trivial tasks

---

_Last updated: 2026-05-01. If this file goes stale relative to `00-system/CLAUDE.md`, treat `CLAUDE.md` as authoritative and flag the drift in `07-logs/log.md`._
