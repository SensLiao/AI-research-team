<div align="right"><a href="README.zh-CN.md">简体中文</a></div>

<p align="center"><img src="docs/hero.png" alt="Research Agent Teams — auditable multi-agent research orchestration" width="100%"></p>

Research Agent Teams is an auditable multi-agent research orchestration system. It coordinates AI agents through a real research workflow — from discovery to a written report — without losing traceability or human control. Evidence stays auditable end to end: citation attribution recomputes every claim→source span from a local, immutable snapshot, and each run is recorded in a hash-chained, append-only ledger. The fastest way in is the test suite.

**What a run produces — a director-review packet:**

- evidence briefs
- idea bets
- experiment plans
- a manuscript draft
- a reviewer report

## ✨ Highlights

- **Traceable by construction** — citation attribution recomputes every claim→source span from a local, immutable snapshot, so a claim can always be traced back to its source.
- **Tamper-evident record** — a hash-chained, append-only ledger with a single-writer lock records each run.
- **Humans hold the pen** — 5 human decision gates, arranged so the model structurally cannot bet on its own ideas.
- **Double-validated artifacts** — every artifact is validated twice against JSON-Schema contracts before it moves downstream.
- **Search saturation, tracked** — an evidence-search-saturation trace records when a search has been exhausted.
- **Controlled promotion** — a gated promotion seam moves results into a separate research vault only through an explicit gate.

## 🏗 Architecture

<p align="center"><img src="docs/architecture.png" alt="Research Agent Teams architecture — seven-stage pipeline over control, execution and evidence planes" width="100%"></p>

<p align="center"><sub>Seven pipeline stages resting on three planes: control, execution and repair, evidence and audit.</sub></p>

Runs flow through a seven-stage pipeline — **DISCOVER → IDEATE → DESIGN → EXECUTE → ANALYZE → VERIFY → REPORT** — driven by a control plane that holds the orchestrator's stage graph, a registry of 26 modes and a roster of 166 specialised agents. Execution runs on an operated spine (begin → workers → commit → report) with bounded repair, and 5 human decision gates sit between stages so a person signs off before work proceeds — placed so the model structurally cannot bet on its own ideas. Everything the run emits passes through the evidence layer: 170 JSON-Schema contracts double-validate each artifact, citation attribution ties every claim back to a source span, and the hash-chained, append-only ledger records the run. A full pass ends in the director-review packet; moving results into the separate research vault happens only through a single gated promotion seam.

## 🧰 Tech stack

| Layer | Choice |
| --- | --- |
| Language | Python, standard-library-first |
| Key libraries | PyYAML, jsonschema, cryptography, PyMuPDF, paramiko |
| Contracts | JSON Schema Draft 2020-12 |
| Hooks | Two Node hooks |

The system it adds up to:

| Measure | Count |
| --- | --- |
| Specialised agents | 166 |
| Pipeline stages | 7 (DISCOVER → IDEATE → DESIGN → EXECUTE → ANALYZE → VERIFY → REPORT) |
| Modes | 26 (23 operated) |
| Tools | 146 |
| JSON-Schema contracts | 170 (all 170 parse) |
| Human decision gates | 5 |
| Test files | 245 |

## 🚀 Getting started

Prerequisites: Python with pytest. The checkout directory must be named `research_agent_teams` — modules import from `research_agent_teams.*`.

```bash
python -m pytest tests/ -q
```

A bundled end-to-end example project is not included in this repository, so the fastest way in is the test suite together with the architecture docs.

## 🧪 Testing

The repository ships **245 test files**. Run them with:

```bash
python -m pytest tests/ -q
```

All 170 JSON-Schema contracts parse, and every artifact is double-validated against them.

## 📌 Limitations

A personal research-infrastructure project, designed and built end to end by **Ruixuan Liao**. It is functional and exercised by its test suite, with two practical caveats worth knowing before you clone it: the checkout directory must be named `research_agent_teams`, and no bundled end-to-end example project ships here.

## 📄 License

No LICENSE file ships in this repository, so the terms of use are not yet defined.

<p align="center"><sub>Built by <a href="https://github.com/SensLiao">Ruixuan "Sens" Liao</a> · USYD Advanced Computing (Honours)</sub></p>
