---
type: registry
registry-of: tags
updated: 2026-06-07
---

# Tag Registry

Controlled enum for the `tags:` frontmatter field — cross-cutting labels that don't
deserve their own type, status, or domain.

## Tag philosophy

- Tags are **additive / many-to-many** — a page can carry many tags at once
- Tags are **lowercase-kebab** — `must-read`, `text-prompt`, not `MustRead`
- Tags describe a **cross-cutting facet**, NOT paper / model / dataset NAMES
  (those live in title + aliases + body wikilinks, never as a tag)
- Paper-slug tags, venue / year tags, and one-off method internals do NOT belong here

## Discipline / workflow tags (keep)

- `must-read` · `canonical` · `draft` · `deprecated` · `parked` · `historical-reference`
- `ablation-only` · `rq1-finding` — result-row overlays on top of `result-status:`
- `bootstrap` · `migration` · `audit` — workflow provenance

## Controlled content tags

> Fill at bootstrap: replace the example tags below with cross-cutting content tags
> that span ≥2 threads or ≥3 pages in your project. Keep the list small and stable.
> Keep in sync with lint_vault.py THREAD_LABELS set.

`example-tag-1` · `example-tag-2` · `evaluation` · `domain-adaptation`

## Thread labels (controlled subset — DO NOT delete / rename; exactly 1 per paper)

The literature threads. They mirror the `02-wiki/papers/<thread>/` folders, but the
**authoritative classification is this tag, not the folder**. Each paper carries
exactly one thread label (a paper that genuinely spans threads keeps its home-thread
label and gets the other thread's content tags).

Replace the examples below with your own thread labels — keep in sync with the
`THREAD_LABELS` set in `06-scripts/lint_vault.py`.

`thread-example-1` · `thread-example-2` · `thread-example-3`

## Per-page usage

```yaml
# 1 thread label + cross-cutting content tags + optional discipline tags
tags: [thread-example-1, example-tag-1, evaluation]
```

## Extension policy

- **register** a content tag when it spans ≥2 threads or ≥3 pages and is stable
- **don't register** one-off labels (1-2 pages) — use inline or drop
- **never** register paper / model / dataset names, venues, or years (those have fields)
- thread labels are fixed — changing them is a schema migration, not a tag edit
- `lint_vault.py` flags tags outside this registry (advisory, not a hard block)
