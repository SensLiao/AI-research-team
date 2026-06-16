---
type: registry
registry-of: types
updated: 2026-05-01
---

# Type Registry

**Authoritative list of recognized `type:` values + per-type fields.** Every wiki page's `type:` must match a row below. New types added via the extension ritual at the end.

This registry is the source of truth. Templates in `04-templates/` are scaffolding; fields are reconciled against this registry during LINT.

---

## Knowledge-note types (21) — full universal frontmatter + type-specific fields

Universal frontmatter (every knowledge note):
```
title / type / status / confidence / created / updated / project /
rq / contrib / domain / tags / related / source / aliases /
evidence-class / owner / reviewed / review-cycle
```

### Per-type extra fields

| type | Folder | Purpose | Required type-specific fields | Optional fields |
|------|--------|---------|------------------------------|-----------------|
| `paper` | `papers/` | External research paper | `authors` (list), `year` (int), `venue` (str), `reading-status` (to-read\|skimmed\|read\|deep-read\|cited\|deprecated), `relevance` (direct\|adjacent\|background) | `doi`, `url`, `key-claims`, `serves-claim` (list of `[[claim-slug]]`) |
| `source` | `sources/` | Internal runbook / plan / rules | `source-type` (runbook\|plan\|rules\|readme\|transcript), `maintained-by` (human\|llm\|both) | `canonical` (bool) |
| `experiment` | `experiments/` | Experiment design (one per research question slice) | `experiment-id` (str), `model` (`[[model-slug]]`), `dataset` (`[[dataset-slug]]`), `protocol` (`[[protocol-slug]]`), `serves-rq` (list), `serves-contrib` (list) | `expected-outputs` (list), `stop-conditions` (list), `runs` (list of `[[run-slug]]`), `result-pages` (list of `[[result-slug]]`) |
| `run` | `runs/` | A single execution of an experiment | `experiment` (`[[experiment-slug]]`), `run-id` (str), `seed` (int), `git-commit` (str, 40-char SHA), `data-version` (str — DVC hash or dataset release), `env-lock` (`[[env-lock-slug]]` or path), `started` (datetime ISO 8601), `finished` (datetime ISO 8601), `wallclock-hours` (float), `hardware` (str), `status` (running\|completed\|failed\|aborted) | `container-digest` (str), `metrics-file` (path), `log-file` (path), `notes` (str), `superseded-by` (`[[run-slug]]`) |
| `method` | `methods/` | Technique | `category` (prompt\|adaptation\|loss\|arch\|pre-processing\|post-processing\|evaluation) | `first-seen` (`[[paper-slug]]`), `applied-in` (list of `[[experiment-slug]]`), `mathematical-form` (str) |
| `model` | `models/` | Model architecture | `family` (str — sam\|unet\|transformer\|hybrid\|other), `native-dim` (1D\|2D\|2.5D\|3D\|nD) | `params` (str), `prompt-modes` (list), `training-data` (str), `license`, `official-repo`, `paper` (`[[paper-slug]]`) |
| `dataset` | `datasets/` | Dataset card | `size` (str), `modality` (str) | `classes` (list), `split-policy` (str), `preprocessing` (str), `source-url`, `license`, `local-path`, `version`, `data-hash` |
| `result` | `results/` | Atomic benchmark row (1 model × 1 metric × 1 setting) | **Data:** `model`, `dataset`, `metric`, `value` (number), `prompt` (str), `table` (str), `split` (val\|test). **Validity:** `result-status` (provisional\|frozen\|invalid\|superseded\|missing-audit\|diagnostic-only), `can-cite-thesis` (bool — derived), `eval-frame` (str), `metric-source` (str), `leakage-audit` (pass\|fail\|missing), `fairness-audit` (pass\|fail\|missing), `evidence-artifact` (str — path or wikilink) | `std`, `ci95`, `n-cases`, `unit`, `mean-or-aggregate`, `experiment` (`[[experiment-slug]]`), `run` (`[[run-slug]]`), `superseded-by` (`[[result-slug]]`), `invalidated-by` (`[[pm-slug]]`) |
| `claim` | `claims/` | Thesis-level proposition | `claim-status` (draft\|supported\|contested\|validated\|thesis-ready\|deprecated), `serves-rq` (list), `supports-contrib` (list of `Cn`), `evidence-for` (list of `[[result-slug]]` / `[[paper-slug]]`), `evidence-against` (list — same), `audit` (object with `leakage`, `fairness`, `reproducibility` keys) | `chapter` (str), `paragraph-draft` (str), `risks` (list of `[[risk-slug]]`), `valid-at` (YYYY-MM-DD — when the claim started holding), `invalid-at` (YYYY-MM-DD — when it stopped; **setting this REQUIRES `invalidated-by`**; invalidate-don't-delete), `invalidated-by` (`[[slug]]` of the refuting/superseding page), `superseded-by` (`[[claim-slug]]`), `extends` (list of `[[claim-slug]]` — typed edge), `uses` (list of `[[method-slug]]`/`[[dataset-slug]]` — typed edge) |
| `decision` | `decisions/` | Architectural / scope / method decision (ADR) | `decision-status` (proposed\|accepted\|rejected\|superseded\|revisit-needed), `date` (YYYY-MM-DD), `decision-owner` (str), `context` (str), `options-considered` (list), `chosen` (str), `rationale` (str), `consequences` (list) | `risks` (list), `revisitable-when` (list of conditions), `superseded-by` (`[[decision-slug]]`) |
| `synthesis` | `syntheses/` | Cross-cutting writeup / chapter draft | `covers` (list of `[[slug]]`) | `for-chapter` (str), `claim-chain` (list of `[[claim-slug]]`), `required-evidence-status` (str — typically `thesis-citable`) |
| `process-memory` | `process-memory/` | Postmortem of a recurring bug class (PM) | `pm-id` (PM-NNNN), `bug-class` (str), `discovered-in` (`[[run-slug]]` or `[[experiment-slug]]`), `pm-status` (draft\|active\|confirmed\|retired) | `affected-rows` (list of `[[result-slug]]`), `superseded-by` (`[[pm-slug]]`) |
| `negative-result` | `negative-results/` | Tried-and-failed experiment record | `tried-method` (`[[method-slug]]`), `failure-mode` (str), `would-have-served-rq` (list), `cost-gpu-hours` (float) | `re-tryable-when` (list of conditions), `related-pm` (`[[pm-slug]]`) |
| `compute-budget` | `compute-budgets/` | GPU-hours / cost tracker | `period` (str — e.g., `2026-05`), `gpu-hours-used` (float), `gpu-hours-budgeted` (float), `failed-run-hours` (float), `successful-run-hours` (float) | `estimated-cost` (str), `hardware` (str), `bottleneck` (str), `risk` (str) |
| `protocol` | `protocols/` | Locked experimental / evaluation / ablation protocol | `protocol-type` (experimental\|evaluation\|ablation\|deployment), `protocol-version` (str), `applies-to` (list of `[[experiment-slug]]` or `[[dataset-slug]]`), `superseded-by` (`[[protocol-slug]]`) | `rationale-doc` (`[[decision-slug]]`) |
| `idea` | `ideas/` | Hypothesis / future work | `idea-status` (preset\|in-consideration\|greenlit\|shipped\|parked), `rationale` (str) | `evidence-for` (list), `evidence-against` (list), `blockers` (list), `decided-by` (`[[decision-slug]]`) |
| `meeting` | `meetings/` | Supervisor / team meeting | `date` (YYYY-MM-DD), `with` (list of str) | `format` (str), `duration-min` (int), `decisions` (list of `[[decision-slug]]`), `action-items` (list) |
| `concept` | `concepts/` | Idea / mechanism / principle | — (only universal) | `also-known-as` (list), `definition-source` (`[[paper-slug]]`) |
| `entity` | `entities/` | Named thing (person / tool / lab / venue / benchmark-suite) | `entity-type` (person\|tool\|lab\|venue\|benchmark-suite\|conference\|funding-body) | `affiliation`, `homepage` |
| `comparison` | `comparisons/` | Head-to-head analysis | `compares` (list of `[[slug]]`, ≥2) | `dimensions` (list), `valid-at` (YYYY-MM-DD), `invalid-at` (YYYY-MM-DD — **setting this REQUIRES `invalidated-by`**; invalidate-don't-delete), `invalidated-by` (`[[slug]]`), `superseded-by` (`[[comparison-slug]]`) |
| `risk` | `risks/` | Identified research / methodology risk | `risk-status` (open\|mitigated\|accepted\|invalidated), `severity` (high\|medium\|low), `affects-claim` (list of `[[claim-slug]]`) | `mitigation` (str), `surfaced-by` (`[[meeting-slug]]` or `[[decision-slug]]`) |

---

## Bases per type

| type | Views (in `03-views/`) |
|------|-------|
| `result` | `00-thesis-citable-results.base`, `01-missing-audit.base`, `02-provisional.base`, `03-invalidated.base` |
| `paper` | `04-reading-status.base` |
| `claim` | `05-claim-without-evidence.base`, `06-claim-by-chapter.base` |
| `decision` | `07-open-decisions.base` |
| `compute-budget` | `08-compute-budget.base` |
| `risk` | `09-open-risks.base` |
| `experiment` / `run` | `10-experiment-pipeline.base` |
| `meeting` | `11-supervisor-feedback-unresolved.base` |

---

## Meta-doc types — exempt from universal frontmatter

These are system / admin files. They carry minimal frontmatter (`type` + `updated`) and are excluded from the universal-frontmatter rule, LINT orphan checks, Bases.

| type | File(s) | Purpose |
|------|---------|---------|
| `schema` | `00-system/CLAUDE.md` | Vault schema definition |
| `registry` | `05-registry/*.md` | Type / status / evidence / project / contribution enums |
| `readme` | `README.md`, all `*/README.md` | Human-facing orientation docs |
| `index` | `00-system/index.md` | Master catalog |
| `log` | `07-logs/*.md` | Append-only operation logs |
| `hot` | `00-system/hot.md` | Session context cache |
| `routing` | `00-system/agent-startup-router.md`, `00-system/evidence-contract.md`, `00-system/schema-contract.md`, `00-system/AGENTS.md` | ALWAYS-READ entry contracts |
| `manifest` | `08-artifact-manifests/*.md` | Pointers to large artifacts |
| `plan` | bootstrap-intake.yml, ingest-plan.md | Execution plans |
| `view` | `03-views/*.base` | Obsidian Bases queryable views |

Adding a new meta-type is purely documentational — update the table above and use the new `type:` value.

---

## Global type rules

1. `type:` is a **string**, not a locked enum — but it **must** appear in one of the two tables above
2. Folder placement is **convention**, not a hard constraint. Frontmatter `type:` is authoritative.
3. Universal frontmatter applies to **knowledge-note types only**. Meta-types are exempt.
4. Type-specific fields layer on top of universal frontmatter.
5. A knowledge-note type with `confidence: low` and `updated:` older than 30 days triggers LINT.

---

## Extension ritual (adding a new knowledge-note type)

Do all 4 steps in the same commit:

1. **Register** — add a row to "Knowledge-note types" with purpose, folder, required fields, optional fields
2. **Template** — create `04-templates/<new-type>.md` with frontmatter scaffold + body sections
3. **Folder** (optional) — `mkdir 02-wiki/<new-type>s/`
4. **View** (optional) — create `03-views/<new-type>-view.base`

Use `type: <new-type>` in frontmatter freely after that — LINT will recognize.

---

## Extension ritual (adding a meta-type)

1. Add a row to the meta-doc table above
2. Use `type: <new-meta>` in that file

No template needed. LINT auto-exempts.

---

## Type retirement

Types are never deleted. If obsolete:
- Mark its row with `(deprecated — see replacement: <link>)`
- Existing pages stay valid but flag for migration

---

## Field-extension log (ritual records)

- **2026-06-10 — bi-temporal validity on `claim` / `comparison`** (absorption wave 1; Graphiti
  invalidate-don't-delete pattern). New OPTIONAL fields: `valid-at`, `invalid-at`,
  `invalidated-by`, `superseded-by` (+ typed edges `extends` / `uses` on `claim`).
  Hard rule (enforced by `06-scripts/lint_vault.py` BITEMPORAL check): a page that sets
  `invalid-at` MUST set `invalidated-by` — an invalidated claim always references its
  invalidator and is NEVER deleted. The machine proposes invalidations via its
  `invalidation_record` artifact; they land here only through `/promote-to-vault`.
  Templates updated: `04-templates/claim.md`, `04-templates/comparison.md`.

---

## Parked type ideas (not yet registered)

Promote to registered when ≥3 pages naturally fit:

- `figure` — paper / thesis figure drafts (currently lives under `synthesis`)
- `code-snippet` — reusable code reference (currently lives under `method` or `source`)
- `tool-config` — env / container / server configs (currently lives under `source`)
- `writing-feedback` — supervisor comments on drafts (currently lives under `meeting`)
- `corpus` — large text corpus distinct from `dataset` (e.g., for NLP work)
- `benchmark-suite` — multi-task evaluation pipeline (currently lives under `entity` with `entity-type: benchmark-suite`)
