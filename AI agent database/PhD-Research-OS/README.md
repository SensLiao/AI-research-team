# PhD Research OS — Template

> An **agent-executable research vault** template designed to scale from a single thesis to a multi-year PhD program with multiple sub-projects.
>
> Distilled from a working Honors-thesis vault (Karpathy LLM-Wiki style → expanded). Removes domain-specific content; keeps the architecture, schema, routing, evidence contract, citation gate, and operational rituals.

**Version:** 0.1 (skeleton, 2026-05-01)
**License:** internal use
**Designed for:** Obsidian as human UI, plain markdown + YAML frontmatter as the substrate, Python scripts as the integrity layer.

---

## What this is

A **scaffolding** for a research operating system, not a knowledge base. The distinction matters:

- A **knowledge base** stores notes and links them.
- A **research OS** stores typed, versioned, audit-gated artifacts and **executes operations on them** — citation gating, lint, reproducibility tracking, claim→evidence→result→decision chain rendering.

The structure assumes an LLM agent (Claude, Codex, or similar) is a **first-class operator** of the vault, not just an author. Every file lives in a registered type, with a frontmatter schema agents can read, write, and validate.

---

## Quick start (3 paths)

### Path A — Instantiate for a specific research topic
You have a topic. You want a working vault.

```
1. Read BOOTSTRAP.md end-to-end.
2. Answer the 12 intake questions in BOOTSTRAP.md §2.
3. Run the bootstrap script (or paste the intake answers to an LLM agent).
4. The agent fills in 00-system/{hot,index}.md, 05-registry/{project,contribution}-registry.md.
5. Start ingesting raw/ files; the agent uses INGEST workflow to fan into wiki/.
```

### Path B — Adopt as your PhD vault skeleton
You're starting a PhD or a major research project. You want the full system.

```
1. cp -r PhD-Research-OS-Template <your-research-folder>/<project-name>
2. Customize 00-system/CLAUDE.md §0 (project-name banner)
3. Customize 05-registry/project-registry.md (your projects)
4. Customize 05-registry/contribution-registry.md (C1, C2, ... thesis claims)
5. Walk Week 1 → Week 4 sections in BOOTSTRAP.md §6
```

### Path C — Use as reference / steal selectively
You have an existing vault. You want to upgrade specific layers.

```
- Schema discipline?         → 00-system/schema-contract.md + 05-registry/type-registry.md
- Anti-hallucination?        → 00-system/evidence-contract.md
- Result citation gate?      → 04-templates/result.md + 03-views/00-thesis-citable-results.base
- Claim → evidence chain?    → 04-templates/claim.md + 06-scripts/render_claim_chain.py
- Programmatic lint?         → 06-scripts/lint_vault.py + .pre-commit-config.yaml
- Decision records?          → 04-templates/decision.md
- Reproducibility manifest?  → 04-templates/run.md + 04-templates/compute-budget.md
```

---

## Architecture (3 layers, immutable boundaries)

```
┌─────────────────────────────────────────────────────────────┐
│  raw/      — facts (PDFs, transcripts, dataset docs)        │
│              IMMUTABLE. Agent never modifies.               │
├─────────────────────────────────────────────────────────────┤
│  wiki/     — interpretations (typed notes with frontmatter) │
│              AGENT-OWNED. Agent reads & writes freely.      │
├─────────────────────────────────────────────────────────────┤
│  schema/   — rules (CLAUDE.md, registries, templates)       │
│              HUMAN-DEFINED. Agent follows; updates only via │
│              the explicit registry-extension ritual.        │
└─────────────────────────────────────────────────────────────┘
```

The boundary is the contract. Without it, agents drift up the stack and rewrite their own rules.

---

## Folder map

| Path | Role |
|------|------|
| `00-system/` | Schema, routing, contracts. Read by agent every session. |
| `01-raw/` | Immutable inputs (PDFs, transcripts, dataset docs). Agent never writes. |
| `02-wiki/` | Typed knowledge notes (papers, experiments, results, claims, decisions, ...). Agent's primary workspace. |
| `03-views/` | Obsidian Bases (`.base`) — queryable database views over frontmatter. |
| `04-templates/` | One template per registered type. Agents copy these when creating new pages. |
| `05-registry/` | Open-enum registries: types, statuses, evidence classes, projects, contributions. |
| `06-scripts/` | Python scripts: lint, citation-gate check, claim-chain renderer, close-day ritual. |
| `07-logs/` | Append-only operation logs. Never delete entries. |
| `08-artifact-manifests/` | Pointers to large artifacts (datasets, containers, env locks, RO-Crate packages). |

---

## Type system (17 knowledge types + 8 meta-doc types)

Knowledge types — full universal frontmatter:
`paper · source · experiment · run · result · claim · decision · method · model · dataset · synthesis · process-memory · negative-result · compute-budget · protocol · idea · meeting · concept · entity · comparison · risk`

Meta-doc types — minimal frontmatter:
`schema · registry · readme · index · log · hot · routing · manifest · plan · view`

See `05-registry/type-registry.md` for the authoritative list and per-type fields.

---

## Operational rituals

| Skill | When | What |
|---|---|---|
| `/ingest <raw-path>` | A new PDF / transcript / dataset doc lands in `raw/` | Read → classify → fill frontmatter → fan out related stubs → update index/log/hot |
| `/recall <topic>` | Answering a question | hot → index → wikilinks; answer with `[[slug]]` citations |
| `/trace <claim>` | Verifying a claim's origin | wiki → raw; show full evidence chain |
| `/close` | End of session | Refresh `00-system/hot.md` from recent log entries |
| `/ghost` | Weekly | Lint: orphans, broken links, stubs, missing source, stale low-confidence |

Scripts in `06-scripts/` make the lint and citation-gate checks programmatic (not agent-judged).

---

## What makes this different from a wiki

| | Plain wiki | This OS |
|---|---|---|
| Storage | Notes + links | Typed notes + frontmatter + registry |
| Citation | Manual ref | Derived `can-cite-thesis` gate |
| Truth | "What's written" | "What passed audit" |
| Context | All notes equal | L0 always-read / L1 project / L2 task tiered |
| Decisions | Implicit in commits | Explicit ADR-style `decision` type |
| Reproducibility | None | git commit + container digest + data hash + env lock |
| Failure modes | Fade away | `negative-result` + `process-memory` permanent record |
| Writing | Manual | Claim-chain → render thesis section |

---

## Required tooling

| Tool | Why | Required? |
|---|---|---|
| Obsidian | Human UI for browsing wikilinks + Bases | Recommended |
| Python 3.10+ | Run lint and renderer scripts | Required |
| `pyyaml`, `python-frontmatter` | Parse vault frontmatter | Required for scripts |
| Git | Version the vault | Required |
| Git LFS / DVC | Large artifacts (datasets, model weights) | Required for reproducibility layer |
| `pre-commit` | Run lint on every commit | Recommended |
| `conda-lock` / `uv` | Lock environments for reproducibility | Recommended |
| LLM agent (Claude Code, Codex CLI) | Operate the vault | Required for full effect |

---

## Documents to read in order

1. **`README.md`** ← you are here
2. **`BOOTSTRAP.md`** — how to instantiate this template for a new topic
3. **`00-system/CLAUDE.md`** — vault schema (vault operations contract)
4. **`00-system/AGENTS.md`** — entry contract for any agent
5. **`00-system/agent-startup-router.md`** — task-type → required reading + actions
6. **`00-system/evidence-contract.md`** — anti-hallucination 9-clause spec
7. **`00-system/schema-contract.md`** — frontmatter discipline
8. **`05-registry/type-registry.md`** — authoritative type list

---

## Versioning policy

- The schema (`05-registry/`, `00-system/CLAUDE.md`, `00-system/AGENTS.md`) is treated as the contract surface.
- Schema changes require a `SCHEMA:` log entry in `07-logs/log.md` and a reasoned migration plan.
- Templates evolve more freely but should stay backwards-compatible with existing pages where possible.

---

## Acknowledgments

This template descends from Andrej Karpathy's [LLM Wiki gist](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f) — the original "personal knowledge base built up by an LLM" idea. It extends that into a research OS with citation gating, ADR-style decisions, claim chains, reproducibility manifests, and 5-class evidence labels.

Borrowed concepts:
- [FAIR data principles](https://www.go-fair.org/fair-principles/) — Findable, Accessible, Interoperable, Reusable
- [RO-Crate](https://www.researchobject.org/) — packaging research objects with provenance
- [ADR pattern](https://adr.github.io/) — architectural decision records
- [DVC](https://dvc.org/) — data + experiment versioning
- [conda-lock](https://github.com/conda/conda-lock) — reproducible env locks
- [pre-commit](https://pre-commit.com/) — git-hook lint enforcement

The 5-class evidence labeling (CODE-LIVE / VAULT-CITE / EXP-RESULT / EXTERNAL-PAPER / ASSUMPTION), 6-state result lifecycle, and L0/L1/L2 routing are original contributions of the source vault, expanded here to 8 evidence classes and 17 types.
