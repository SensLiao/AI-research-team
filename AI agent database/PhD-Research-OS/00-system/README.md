---
type: readme
updated: 2026-05-01
---

# 00-system/ — schema and routing

> Always-read kernel. Every agent must read these files at session start.

## Files

| File | Type | Purpose |
|---|---|---|
| `CLAUDE.md` | `schema` | Vault operations contract — INGEST / QUERY / LINT / CLOSE / RENDER |
| `AGENTS.md` | `routing` | Agent-agnostic entry contract — citation gate, evidence labels, vault-write protocol |
| `agent-startup-router.md` | `routing` | Task-type → required reading + actions + forbidden actions (9 rows) |
| `evidence-contract.md` | `routing` | Anti-hallucination 9-clause spec |
| `schema-contract.md` | `routing` | Frontmatter discipline |
| `index.md` | `index` | Master catalog by type |
| `hot.md` | `hot` | Session state cache (~500 words) |

## Reading order (every session)

1. `hot.md` — current state
2. `index.md` — what exists in the vault
3. `agent-startup-router.md` — pick the matching task row
4. `evidence-contract.md` — citation discipline
5. (conditional) `schema-contract.md` — when about to create or edit a page

## Hard rule

These files are **canonical**. Editing them requires:
- A `CONTRACT-EDIT:` line in `07-logs/log.md`
- The agent's first user-visible message of the session must include `Editing canonical page [[<slug>]] — change summary: <one sentence>`

This protects against silent contract drift.
