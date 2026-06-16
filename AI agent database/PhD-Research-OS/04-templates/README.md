---
type: readme
updated: 2026-05-01
---

# 04-templates/ — one template per knowledge-note type

> Starter scaffolding. Agents copy the matching template when creating a new wiki page.

## Templates

| File | Type | Purpose |
|---|---|---|
| `paper.md` | `paper` | External research paper |
| `source.md` | `source` | Internal runbook / plan / rules |
| `experiment.md` | `experiment` | Experiment design |
| `run.md` | `run` | Single execution of an experiment |
| `result.md` | `result` | Atomic benchmark row (citation-gated) |
| `claim.md` | `claim` | Thesis-level proposition |
| `decision.md` | `decision` | ADR-style locked decision |
| `method.md` | `method` | Technique card |
| `model.md` | `model` | Model architecture card |
| `dataset.md` | `dataset` | Dataset card |
| `synthesis.md` | `synthesis` | Cross-cutting writeup / chapter draft |
| `process-memory.md` | `process-memory` | Postmortem → permanent rule |
| `negative-result.md` | `negative-result` | Documented failure |
| `compute-budget.md` | `compute-budget` | GPU-hours per period |
| `protocol.md` | `protocol` | Locked experimental / evaluation protocol |
| `risk.md` | `risk` | Identified research risk |
| `idea.md` | `idea` | Hypothesis / future work |
| `meeting.md` | `meeting` | Supervisor / team meeting |
| `concept.md` | `concept` | Domain concept / mechanism |
| `entity.md` | `entity` | Person / tool / lab / venue |
| `comparison.md` | `comparison` | Head-to-head analysis |

## How to use

1. Identify the type — see `05-registry/type-registry.md`
2. Copy the matching template into the matching folder (`02-wiki/<type>s/`) with the slug as filename
3. Fill the frontmatter (universal + type-specific fields)
4. Replace `<placeholder>` text with actual content
5. Update `00-system/index.md` and append to `07-logs/log.md`

## Authoritative source

The registry (`05-registry/type-registry.md`) is the contract. Templates are scaffolding. If a template and the registry disagree, the registry wins.

## Adding a new template

When you register a new type:
1. Copy the closest existing template
2. Adjust the frontmatter to match the new type's required + optional fields
3. Update the body section headers to fit the new type's purpose
4. Add a row to this README
