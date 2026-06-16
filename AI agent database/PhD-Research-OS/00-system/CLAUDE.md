---
type: schema
updated: 2026-05-01
schema-version: 1.0
---

# Vault Operation Schema

> **Scope.** This file governs **vault operations only** — ingesting raw sources, answering queries, linting integrity. It does NOT govern the underlying research workflow (experiment design, paper writing, supervisor coordination); those live in project-specific source pages and decision records.
>
> **Project banner placeholder.** When this template is instantiated for a specific topic, replace `{{PROJECT_TITLE}}` and `{{PROJECT_SLUG}}` below.

```
Project: {{PROJECT_TITLE}}
Slug:    {{PROJECT_SLUG}}
Phase:   {{PROJECT_PHASE}}
```

---

## §1 — Architecture: 3 layers, immutable boundaries

| Layer | Path | Owner | Rule |
|-------|------|-------|------|
| **raw** | `01-raw/` | Human | Immutable. Agent never modifies. |
| **wiki** | `02-wiki/` | Agent | Agent reads & writes freely, subject to schema. |
| **schema** | `00-system/` + `05-registry/` + `04-templates/` | Human-defined | Agent follows; updates only via registry-extension ritual (§3.5 below). |

The boundary is the **contract**. Without it, agents drift up the stack and rewrite their own rules.

---

## §2 — Operations: 5 verbs

### 2.1 INGEST (`raw → wiki`)

**Trigger.** A new file lands in `01-raw/`, or the user says "ingest X".

**Steps:**
1. Read the raw file fully. Never modify it.
2. Classify the `type:` per `05-registry/type-registry.md`.
3. Pick a slug (§5).
4. Copy `04-templates/<type>.md` as the starting page.
5. Fill the universal frontmatter + type-specific fields.
6. Extract 3-7 key claims into the body.
7. Fan out related stubs: for each named noun/method/dataset/model, create or update its typed page.
8. **Update three meta files (mandatory):**
   - `00-system/index.md` — add entry under matching section
   - `07-logs/log.md` — append `INGEST [[<slug>]]` line
   - `00-system/hot.md` — touch if session-relevant (keep ≤500 words)
9. Flag contradictions: if this source disagrees with an existing page, set both to `confidence: low` and file `02-wiki/comparisons/<a-vs-b>.md`.
10. If batch mode: run LINT at end.

### 2.2 QUERY (`question → answer with citations`)

**Trigger.** Any project question.

**Steps:**
1. Read `00-system/hot.md` first.
2. Scan `00-system/index.md`.
3. Grep wiki by `type:` or `tags:`.
4. Walk `related:` + `[[wikilinks]]`.
5. For structured queries, open the matching `.base` view in `03-views/`.
6. Answer with inline `[[slug]]` citations. If vault is silent, say so explicitly and offer to INGEST.
7. If the answer produces a cross-cutting insight, file `02-wiki/syntheses/<slug>.md`.

### 2.3 LINT (`integrity check`)

**Trigger.** `/ghost`, weekly, or after a batch INGEST.

**Steps:** see `06-scripts/lint_vault.py` and `00-system/agent-startup-router.md` Row 6. 9 checks: orphans, broken links, stubs, stale low-confidence, hot.md drift, registry consistency, missing source, duplicate slugs, derived-field inconsistency.

### 2.4 CLOSE (`refresh hot.md`)

**Trigger.** End of session, or after a major decision / result.

**Steps:** see `06-scripts/close_day.py`. Reads recent log entries, rewrites hot.md as a **state snapshot** (not a narrative).

### 2.5 RENDER (`claim → thesis paragraph`)

**Trigger.** Writing a thesis section / paper / proposal.

**Steps:** see `06-scripts/render_claim_chain.py`. Reads a synthesis page's `claim-chain:`, walks each claim → result → audit, refuses to render if `can-cite-thesis: false` for any cited row.

---

## §3 — Type system

The authoritative list lives in `05-registry/type-registry.md`. This section is a summary; if it disagrees with the registry, the registry wins.

### 3.1 Knowledge-note types (21) — full universal frontmatter

`paper · source · experiment · run · result · claim · decision · method · model · dataset · synthesis · process-memory · negative-result · compute-budget · protocol · idea · meeting · concept · entity · comparison · risk`

Folder placement is convention. Frontmatter `type:` is authoritative.

**`negative-result` cluster** (`02-wiki/negative-results/`): documents tried-and-failed experiments as first-class knowledge. Pages enter via `/promote-to-vault` after a run fails, or via director hand-entry. The `ideate_ring` / `new_direction` modes consult this cluster before generating ideas — a direction already falsified here is deprioritized automatically to prevent re-spending compute on known dead ends. Template: `04-templates/negative-result.md`. Required body sections: *What was tried* (with run/experiment refs) / *Why it failed* / *Conditions & caveats* (precise failure scope — avoid over-generalizing) / *Do-not-retry-unless* (explicit decision gate).

### 3.2 Meta-doc types (10) — minimal frontmatter only

`schema · registry · readme · index · log · hot · routing · manifest · plan · view`

Exempt from universal-frontmatter rules; LINT skips them for orphan / source-backing checks.

### 3.3 Universal frontmatter (every knowledge note)

```yaml
---
title: <human title>
type: <one of the registered types>
status: <see 05-registry/status-registry.md>
confidence: high | medium | low | unverified
created: YYYY-MM-DD
updated: YYYY-MM-DD
project: <project-slug>
rq: []                                              # [RQ1, RQ2, ...]
contrib: []                                         # [C1, C2, ...]
domain: []
tags: []
related: []                                         # [[slug-a]]
source: 01-raw/<path>                               # optional
aliases: []
evidence-class: <see 00-system/evidence-contract.md>
owner: <agent-id | human-name>
reviewed: YYYY-MM-DD                                # last human-review date, optional
review-cycle: 30 | 60 | 90 | none                   # optional
---
```

Type-specific fields are **appended** to this universal block. See `04-templates/<type>.md`.

### 3.4 Meta-doc frontmatter (minimal)

```yaml
---
type: <meta-type>
updated: YYYY-MM-DD
---
```

Allowed extras for some meta-types (`schema-version` for schema files; `registry-of` for registries; `canonical: true` for canonical routing pages).

### 3.5 Type extension ritual

Adding a knowledge-note type requires all 4 steps in one commit:

1. **Register** — add a row to `05-registry/type-registry.md`
2. **Template** — create `04-templates/<new-type>.md`
3. **Folder** (optional) — `mkdir 02-wiki/<new-type>s/`
4. **View** (optional) — create `03-views/<new-type>-view.base`

Adding a meta-type:
1. Add a row to `05-registry/type-registry.md` meta-doc table
2. Use `type: <new-meta>` in that file

---

## §4 — Slug & link conventions

### Slugs
- Lowercase-kebab only: `example-lora-ablation`, `claim-prompt-bridges-gap`
- No spaces, no CamelCase, no special chars except `-`
- Once set, **never rename** — use `aliases:` for new names
- **Date-in-slug exceptions:**
  - `meeting`: `meeting-YYYY-MM-DD-<topic>`
  - `paper`: `<firstauthor>-<year>-<shortname>` (year is part of citation)
  - `decision`: `dec-NNNN-<topic>` (sequential id, never date)
  - `run`: `run-<experiment-slug>-NNN`
  - all other types: no dates

### Links
- Always `[[slug]]`, never relative paths
- `[[slug|Display Text]]` if display ≠ slug
- Mixed languages OK; key technical terms appear in both languages on first use

---

## §5 — Hard rules (never break)

| Rule | Detail |
|------|--------|
| **Never modify raw/** | raw/ is read-only; treat all files as immutable |
| **Always update index.md + log.md** | Every INGEST / SCHEMA / BACKFILL must update both |
| **confidence: low when uncertain** | If inferred or single-source, use `low` |
| **Mark deprecated, don't delete** | `status: deprecated` with a pointer; never `rm` |
| **hot.md ≤ 500 words** | State snapshot, not narrative |
| **Slugs are stable** | Once set, never rename — use `aliases:` |
| **Links use `[[slug]]`** | Never relative paths |
| **Frontmatter matches registry** | `type:` and `status:` must exist in registry |
| **Type-folder consistency** | Best-effort; frontmatter wins on conflict |
| **`can-cite-thesis` is derived** | Manual override forbidden — fix the audits, not the flag |

---

## §6 — Session workflow

- **Start:** Read `00-system/hot.md`. Then read the rows from `agent-startup-router.md` matching the task type.
- **During:** `/recall <topic>` for targeted lookup; `/trace <claim>` for evidence chain.
- **End:** `/close` refreshes `hot.md`.
- **Weekly:** `/ghost` runs LINT.

---

## §7 — Integration

- **Project context:** `02-wiki/sources/project-brief.md` (created at bootstrap).
- **External agents:** read `00-system/AGENTS.md` first.
- **Bases:** `03-views/*.base` are Obsidian queryable database views.
- **Scripts:** `06-scripts/*.py` for lint, render, close.

---

## §8 — Versioning policy

The schema (this file + `05-registry/` + `00-system/agent-startup-router.md` + `00-system/evidence-contract.md` + `00-system/schema-contract.md`) is the contract surface. Changes require:
1. A `SCHEMA:` log entry in `07-logs/log.md`
2. A migration plan if existing pages are affected
3. Updates to `04-templates/` to match
