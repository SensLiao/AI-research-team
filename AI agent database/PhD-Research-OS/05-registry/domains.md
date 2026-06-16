---
type: registry
registry-of: domains
updated: 2026-06-07
---

# Domain Registry

Controlled enum for the `domain:` frontmatter field. Used for cross-cutting filtering.

`domain:` is a **list** — a page may carry multiple domains (a paper can be
`[medical-imaging, segmentation, foundation-models]` at once). Domains are a coarse,
cross-cutting filter, **NOT a folder**. Finer labels go to `tags:`; paper / model /
dataset / metric NAMES go in the body + wikilinks, never here.

## What goes here

Top-level subject areas this vault touches. Keep it small — 5-15 entries is healthy.
Resist adding a domain for every keyword.

## Controlled domains

> Fill at bootstrap: replace the example rows below with the domains that fit your project.
> Keep it small — 5-15 entries is healthy; resist adding a domain for every keyword.

| domain | meaning | absorbs (examples) |
|---|---|---|
| `medical-imaging` | Medical imaging (example) | medical-image, segmentation |
| `nlp` | Natural language processing (example) | text, language-model |
| `example-domain` | Your research domain (replace this row) | keyword-a, keyword-b |

Method / paradigm keywords that are wrongly used as domains
(`reinforcement-learning`, `auto-prompting`, `text-prompting`, `self-supervised`,
`detection`, `recognition`, `video-segmentation`, `survey`, ...) are **not**
domains — demote to a registered tag (see tags.md) or move into the body.

## Per-page usage

```yaml
domain: [medical-imaging, segmentation, foundation-models]
```

Multi-domain pages list multiple values. Every knowledge page should carry ≥1 domain
from this list; values outside this list are flagged by `lint_vault.py` (advisory, not
a hard block).

## Extension policy

Add a domain only when ≥3 pages naturally fit and no existing domain covers them.
Retire (mark `(deprecated)`) when no page has cited it in 6 months. Method / model /
dataset names are NOT domains — they go in the body or as a registered tag.
