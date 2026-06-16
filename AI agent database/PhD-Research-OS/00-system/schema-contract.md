---
title: "Schema Contract (frontmatter discipline)"
type: routing
status: active
confidence: high
created: 2026-05-01
updated: 2026-05-01
canonical: true
---

# Schema Contract

> **Why this exists.** Without a frontmatter contract, agents drift. Some pages get one type, some get another, fields rename themselves, and three months later your `.base` queries return garbage. This page is the discipline.
>
> **What this is.** The frontmatter rules. Type registry, status registry, evidence registry — they live in `05-registry/`. This page tells the agent **how to apply** them.

---

## §1 — Universal frontmatter (every knowledge note)

```yaml
---
title: <human-readable title>
type: <one of registered knowledge-note types>
status: <draft | active | completed | deprecated | parked>
confidence: <high | medium | low | unverified>
created: YYYY-MM-DD
updated: YYYY-MM-DD
project: <project-slug>
rq: [RQ1, RQ2, ...]
contrib: [C1, C2, ...]
domain: [...]
tags: [...]
related: ['[[slug-a]]', '[[slug-b]]']
source: 01-raw/<path>                # optional
aliases: [...]                        # optional
evidence-class: <see 00-system/evidence-contract.md Part 1>
owner: <agent-id | human-name>
reviewed: YYYY-MM-DD                  # optional, last human-review date
review-cycle: <30 | 60 | 90 | none>   # optional
---
```

**Required fields:** `title`, `type`, `status`, `confidence`, `created`, `updated`, `project`.
**Recommended:** `rq`, `contrib`, `domain`, `tags`, `related`.
**Optional:** `source`, `aliases`, `evidence-class`, `owner`, `reviewed`, `review-cycle`.

---

## §2 — Type-specific fields layer on top

Each knowledge-note type adds **type-specific fields** above and beyond the universal block. The authoritative spec is in `05-registry/type-registry.md`. Templates in `04-templates/<type>.md` show the canonical scaffolding.

Examples:

| Type | Type-specific fields |
|---|---|
| `paper` | `authors`, `year`, `venue`, `doi`, `url`, `reading-status`, `relevance`, `key-claims` |
| `experiment` | `run-id`, `model`, `dataset`, `seed`, `split`, `started`, `finished`, `result-pages` |
| `run` | `experiment` (link to experiment slug), `git-commit`, `container-digest`, `data-version`, `env-lock`, `seed`, `metrics-file`, `hardware`, `wallclock-hours` |
| `result` | `model`, `dataset`, `metric`, `value`, `prompt`, `table`, `split`, `result-status`, `can-cite-thesis`, `eval-frame`, `metric-source`, `leakage-audit`, `fairness-audit`, `evidence-artifact` |
| `claim` | `claim-status`, `evidence-for`, `evidence-against`, `audit`, `serves-rq`, `supports-contrib`, `chapter` |
| `decision` | `date`, `decision-status`, `decision-owner`, `options-considered`, `chosen`, `consequences`, `revisitable-when` |

---

## §3 — Meta-doc frontmatter (minimal)

Meta-doc types (`schema`, `registry`, `readme`, `index`, `log`, `hot`, `routing`, `manifest`, `plan`, `view`) carry only:

```yaml
---
type: <meta-type>
updated: YYYY-MM-DD
---
```

Plus optional extras for some meta-types:
- `schema` files: `schema-version`
- `registry` files: `registry-of`
- `routing` files: `canonical: true`

LINT skips meta-docs for: universal-frontmatter completeness, orphan-link checks, source-backing checks.

---

## §4 — Field semantics (avoid common pitfalls)

### `status:` (vault-page lifecycle)
Values: `draft | active | completed | deprecated | parked`
- `draft`: just created, body incomplete or unverified
- `active`: curated, in-use, linked into the workflow
- `completed`: terminal — finished work for `experiment`, `meeting`, `decision` types
- `deprecated`: superseded by another page; kept for history
- `parked`: paused / blocked / deferred

### `confidence:` (epistemic)
- `high`: directly verified or sourced
- `medium`: derived but reasoned
- `low`: inferred or single-source — should appear in stale-low-confidence LINT check
- `unverified`: placeholder; needs review

### `evidence-class:` (frontmatter-level evidence label)
One of `CODE-LIVE | VAULT-CITE | EXP-RESULT | PAPER-CITE | DATA-CITE | MEETING-CITE | DECISION-CITE | ASSUMPTION`. Optional but recommended for any page whose body relies primarily on a single evidence class.

### `review-cycle:` (anti-rot)
For `confidence: high` pages, set a review cycle in days. LINT flags pages where `today - reviewed > review-cycle`.

### `rq:` and `contrib:` (research traceability)
Always lists, even if single-element. Empty list `[]` is valid for utility pages (e.g., `concept`, `entity`).

### `related:` (semantic links)
Always wikilinks `[[slug]]`. LINT flags broken targets.

---

## §5 — Slug discipline

| Type | Slug rule | Example |
|---|---|---|
| Most | `lowercase-kebab`, no dates | `example-lora-ablation` |
| `paper` | `<firstauthor>-<year>-<shortname>` | `radford-2021-clip` |
| `meeting` | `meeting-YYYY-MM-DD-<topic>` | `meeting-2026-04-29-supervisor` |
| `decision` | `dec-NNNN-<topic>` | `dec-0007-fixed-split` |
| `process-memory` | `pm-NNNN-<topic>` | `pm-0017-dual-lora-load` |
| `run` | `run-<experiment>-NNN` | `run-exp-t50-003` |
| `compute-budget` | `cb-YYYY-MM[-period]` | `cb-2026-05` |

**Once set, never rename.** If the human-readable name needs to change, add to `aliases:`.

---

## §6 — Common LINT errors and fixes

| Error | Cause | Fix |
|---|---|---|
| `MISSING_TYPE` | `type:` field empty | Add `type: <something-from-registry>` |
| `UNKNOWN_TYPE` | `type:` value not in registry | Either fix the typo, or run the type-extension ritual |
| `MISSING_UNIVERSAL` | Knowledge-note page missing required field | Fill it; LINT names which field |
| `BROKEN_LINK` | `[[slug]]` resolves to no file | Fix the slug, or create the missing page |
| `ORPHAN_PAGE` | Knowledge-note page has no inbound `[[link]]` | Add the page to a parent index or synthesis |
| `STUB_PAGE` | Body < 100 chars or only `TODO` | Either flesh out or mark `status: draft` |
| `STALE_LOW_CONF` | `confidence: low` and `updated > 30d` ago | Re-verify or mark `status: parked` |
| `MISSING_SOURCE` | Type `paper` / `source` page with empty `source:` | Point to the raw file or set explicitly empty for non-raw-derived |
| `DERIVED_INCONSISTENT` | `can-cite-thesis: true` but `result-status != frozen` | Fix the underlying audits, NOT the derived flag |
| `UNREGISTERED_STATUS` | `status:` not in registry | Either fix typo or extend registry |

---

## §7 — When to extend the schema vs work around it

**Extend (run the ritual)** when:
- A new type has accumulated ≥3 candidate pages naturally
- A new status value covers a state that existing values mash together
- A new evidence class describes a fundamentally new evidence channel

**Work around (use tags or a wrapper field)** when:
- You only need one or two pages with this characteristic
- The "type" is really just a sub-category of an existing type
- The "status" is really a domain-specific overlay (use a type-specific status field, e.g., `reading-status`, `claim-status`, `idea-status`)

The schema should be **small enough to memorize** but **large enough to be useful**. 15-25 knowledge-note types, 5-7 statuses, 8 evidence classes is a healthy steady state.

---

## §8 — Migration policy

When a schema field is renamed or restructured:
1. Write a `SCHEMA:` log entry in `07-logs/log.md`
2. Update `05-registry/` first
3. Update `04-templates/` to match
4. Run a sweep across affected pages — usually with `06-scripts/lint_vault.py --fix-rename old=<old> new=<new>` or a manual sed
5. Verify with LINT

Schema changes are NOT casual. Treat them like database migrations.

---

## §9 — Facet & classification policy (standing law)

> Added 2026-06-07 from the taxonomy-design review. These 10 rules govern how knowledge
> is *organized and classified*. They bind every agent. Lift them verbatim before any
> change to classification structure.

1. **Single source of truth = the YAML frontmatter.** Never introduce a second
   authoritative store (no SQLite / graph-DB / RDF as primary truth). Any external ID
   (signac job, dvc hash, trace id) is a *secondary reference* in frontmatter, never
   authoritative state.
2. **Classify by frontmatter facets, not folder path.** A physical directory may mirror
   at most ONE coarse axis (`type`). Never encode `project` / `rq` / `topic` / `domain`
   / `year` into the path — a multi-value facet collapsed into one physical location is
   the mathematical limit of trees. Cross-cutting classification lives only in
   frontmatter lists.
3. **Add a new axis / type / facet only when ≥3 pages naturally accumulate AND no
   existing axis covers them.** Reject speculative "might need it later" fields — they
   rot into empty / inconsistent facets.
4. **Keep the required core tiny** (`title type status created updated project`); make
   everything else optional. Low capture friction — a solo non-engineer abandons a vault
   that fights them.
5. **Derived views are always regenerable and disposable.** `.base` queries and
   auto-generated MOCs are one-way projections of frontmatter; if deleting a view would
   lose information, the facet design is wrong. Never let a derived view become truth.
6. **Link, don't copy.** A paper / finding serving N projects or RQs = ONE canonical note
   wikilinked from N places, never N copies. Multi-membership is expressed by list fields
   — `project` / `rq` / `contrib` / `domain` / `tags` are all many-to-many lists.
7. **Don't split the vault for organization.** One git vault. Multiple vaults only for
   hard isolation (embargo / confidential), never for classification — splitting severs
   cross-project backlinks.
8. **Controlled vocabularies are enforced against rot.** `domain` and `tags` are
   controlled (see `05-registry/`); `lint_vault.py` flags out-of-vocabulary values
   (advisory). Run a periodic normalize pass; the agent does the mechanical part, the
   human-facing vocabulary stays small.
9. **Never touch the crown jewels for organization work.** The typed-artifact schema,
   evidence-contract, citation gate (`can-cite-thesis` derivation), 3-layer immutable
   boundary, and slug-never-rename are out of scope for any classification change.
10. **No big-bang reorg; grow the faceted schema incrementally.** A PhD pivots; add one
    value / one key at a time. Migrate only the layer that has a real query need now;
    don't pre-build empty type folders. Monthly light normalize > periodic great refactor.
