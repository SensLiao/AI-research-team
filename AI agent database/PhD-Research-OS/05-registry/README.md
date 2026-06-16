---
type: readme
updated: 2026-05-01
---

# 05-registry/ — open-enum registries

> The contract surface. Every `type:`, `status:`, evidence class, project, contribution, domain, and tag must appear in one of these registries.

## Registries

| File | Registry of | Authoritative for |
|---|---|---|
| `type-registry.md` | knowledge-note types + meta-doc types | every page's `type:` field |
| `status-registry.md` | universal `status:` + type-specific overlays | every page's `status:` and per-type `<x>-status` fields |
| `evidence-registry.md` | 8 evidence classes | inline citation labels and `evidence-class:` field |
| `project-registry.md` | active projects | every page's `project:` field |
| `contribution-registry.md` | thesis-level contributions C1..Cn | claim → contribution link |
| `domains.md` | top-level subject areas | `domain:` field |
| `tags.md` | flat label vocabulary | `tags:` field |

## Why open-enum

The original [Karpathy LLM Wiki](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f) used a closed type system. This template uses **open registries** so adding a new type or status doesn't require a schema migration — only an entry in the registry plus (for types) a template + folder.

## Extension rituals

See each registry file for its extension ritual.

## LINT enforcement

`06-scripts/lint_vault.py` reads these registries and validates every page against them. Schema discipline is therefore programmatic, not documentary.
