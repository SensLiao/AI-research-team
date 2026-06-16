---
name: recall
description: "Targeted vault lookup with citations"
when_to_use: "Any project question. Pulls hot.md → index.md → wikilinks; answers with [[slug]] citations."
usage: "/recall <topic>"
---

# /recall

Targeted retrieval from the vault.

## Procedure

1. Read `00-system/hot.md` first.
2. Scan `00-system/index.md` for the topic slug.
3. Grep wiki by `type:` or `tags:` if needed.
4. Walk `related:` + `[[wikilinks]]` from the matching pages.
5. For structured queries (e.g., "all frozen results for model X"), open the matching `.base` view in `03-views/`.
6. Answer with inline `[[slug]]` citations.
7. If the vault is silent, say so explicitly and offer to INGEST.
8. If the answer requires synthesis across multiple pages, file `02-wiki/syntheses/<slug>.md` after answering.

## Output

```
**Topic:** <topic>

**Answer:** <answer>

**Citations:**
- [[slug-a]] §<heading> — <how it supports the answer>
- [[slug-b]] §<heading>

**Confidence:** <high | medium | low> — <reasoning>
```

If silent:
```
**Vault is silent on:** <topic>

**Closest:** [[<closest-slug>]] — <how it differs>

**Suggested next step:** ingest <raw-source> or run an experiment to fill this gap.
```

## Rules

- Quote the page slug + section heading you are reading from.
- Never invent a slug — only cite slugs that exist in `index.md`.
- Never reconstruct a fact from training-data memory when the vault has it.
