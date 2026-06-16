---
type: registry
registry-of: projects
updated: 2026-05-01
---

# Project Registry

Authoritative list of projects this vault tracks. Filled at bootstrap from `bootstrap-intake.yml`.

For a single-project vault: 1 row.
For a multi-project (e.g., PhD with sub-projects): 1 row per sub-project.
For a meta-vault (cross-project methodology only): no project rows; all `project:` references point at sibling project vaults.

---

## Active projects

| project-slug | title | phase | supervisor | domain | status | started | hot.md | brief |
|---|---|---|---|---|---|---|---|---|
| (empty — fill at bootstrap) | | | | | | | | |

---

## Schema

| field | description |
|---|---|
| `project-slug` | lowercase-kebab; used in `project:` frontmatter field of every knowledge note |
| `title` | human-readable |
| `phase` | `undergraduate-thesis | masters-thesis | phd-chapter | phd-program | postdoc | independent` |
| `supervisor` | name(s); empty if independent |
| `domain` | 1-3 keywords from `_registry/domains.md` (or your custom list) |
| `status` | `active | parked | completed | abandoned` |
| `started` | YYYY-MM-DD |
| `hot.md` | path to project hot file (if multi-vault, points at sibling vault's `00-system/hot.md`) |
| `brief` | wikilink to `[[<project-slug>-brief]]` source page |

---

## Multi-project ground rules

1. Each `02-wiki/` page MUST set `project: <slug>` from this registry
2. `meta-vault` pages set `project: meta` (reserved value)
3. Cross-project references use full `[[<project-slug>:<page-slug>]]` if and only if the target lives in a sibling vault (Obsidian doesn't natively support this — the convention is documentary)
4. A page can serve multiple projects — `project:` accepts a list

---

## Project lifecycle

```
bootstrap → active → (completed | parked | abandoned)
```

When a project moves to `completed`:
1. Run `/ghost` to find dangling references
2. Mark all `experiment` and `decision` pages as `status: completed`
3. Archive `01-raw/` to a project-archive location
4. Keep `02-wiki/` browsable forever — never delete

When a project moves to `abandoned`:
1. Same as completed, but also mark all `claim` pages as `status: deprecated`
2. Write a final `02-wiki/syntheses/<project-slug>-postmortem.md` if useful for future projects

---

## Reserved project slugs

- `meta` — for cross-project methodology pages (only valid in a meta-vault)
- `template` — for pages that exist in `04-templates/` and have no real project (excluded from LINT project-completeness check)
