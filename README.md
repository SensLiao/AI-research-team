<div align="right"><a href="README.zh-CN.md">简体中文</a></div>

<p align="center"><img src="docs/hero.png" alt="Research Agent Teams banner" width="100%"></p>

<p align="center"><b>Orchestrated research runs where every claim is traced to a source and a human signs off at each gate.</b></p>

<p align="center">
<img src="https://img.shields.io/badge/Python-stdlib--first-7c6cf0?style=flat-square" alt="Python stdlib-first">
<img src="https://img.shields.io/badge/Agents-166-7c6cf0?style=flat-square" alt="166 agents">
<img src="https://img.shields.io/badge/Pipeline-7%20stages-7c6cf0?style=flat-square" alt="7-stage pipeline">
<img src="https://img.shields.io/badge/JSON%20Schema-Draft%202020--12-7c6cf0?style=flat-square" alt="JSON Schema Draft 2020-12">
<img src="https://img.shields.io/badge/Human%20gates-5-7c6cf0?style=flat-square" alt="5 human gates">
<img src="https://img.shields.io/badge/License-planned-64748b?style=flat-square" alt="License planned">
</p>

Research Agent Teams is an auditable multi-agent research orchestration system. It coordinates AI agents through a real research workflow — from discovery to a written report — without losing traceability or human control. Every run produces a **director-review packet**: evidence briefs, idea bets, experiment plans, a manuscript draft, and a reviewer report.

Evidence is auditable end-to-end: citation attribution recomputes every claim→source span from a local, immutable snapshot, and each run is recorded in a hash-chained, append-only ledger. The fastest way in is the test suite (see [Getting started](#-getting-started)).

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

## 📊 By the numbers

| Measure | Count |
| --- | --- |
| Specialised agents | 166 |
| Pipeline stages | 7 (DISCOVER → IDEATE → DESIGN → EXECUTE → ANALYZE → VERIFY → REPORT) |
| Modes | 26 (23 operated) |
| Tools | 146 |
| JSON-Schema contracts | 170 (all 170 parse) |
| Human decision gates | 5 |
| Test files | 245 |

## 🏗 Architecture

<p align="center"><img src="docs/architecture.png" alt="Research Agent Teams architecture" width="100%"></p>

Runs flow through a seven-stage pipeline — **DISCOVER → IDEATE → DESIGN → EXECUTE → ANALYZE → VERIFY → REPORT** — with 5 human decision gates placed between stages where a person signs off before work proceeds. Agents operate in typed modes and call a shared tool set; every artifact they emit is validated twice against JSON-Schema contracts, appended to a hash-chained ledger, and — when promoted — moved through a single gated seam into a separate research vault.

## 🧰 Tech stack

- **Language:** Python, standard-library-first
- **Key libraries:** PyYAML, jsonschema, cryptography, PyMuPDF, paramiko
- **Contracts:** JSON Schema Draft 2020-12
- **Hooks:** two Node hooks

## 🚀 Getting started

The checkout directory must be named `research_agent_teams` — modules import from `research_agent_teams.*`.

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

## 📌 Project status

A personal research-infrastructure project, designed and built end-to-end by **Ruixuan Liao**. It is functional and exercised by its test suite; note the two practical caveats above — the checkout directory must be named `research_agent_teams`, and no bundled end-to-end example project ships in this repository. A rename of the repository to `research-agent-teams` is planned.

## 📄 License

A license is planned but not yet added — no LICENSE file ships in this repository today.

<p align="center"><sub>Built by <a href="https://github.com/SensLiao">Ruixuan "Sens" Liao</a> · USYD Advanced Computing (Honours)</sub></p>
