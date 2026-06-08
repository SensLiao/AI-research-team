# Research Agent Teams (the machine)

The **agent team itself**: its configuration, its control plane, and everything it produces while
running. This is one of **two cleanly separated systems**:

| System | Directory | Role |
|---|---|---|
| **Research Agent Teams** (this) | `research_agent_teams/` | THE MACHINE — agent roster + config + control plane + run outputs |
| **PhD-Research-OS** | `AI agent database/PhD-Research-OS/` | THE RESEARCH DATABASE — validated knowledge (the vault) |

> They must NOT be mixed. They connect at exactly **one seam**: the machine *reads* the database
> by reference (recall) and *promotes* vetted artifacts INTO it through a human gate. Nothing else
> crosses. Full design: `_design/research-agent-teams-complete-blueprint-v1.md`.

## What this is (and is NOT)

Built **control-plane-first**: the system core is a state-machine + artifact schemas + permission
scopes + hash-ledger + hard gates + observability. **Agents are controlled workers, not the system
itself.** We build + test the machine before operating it on real research.

## Domain generality (hard rule)

Serves **computer-science / AI research in general** — NOT one domain. Medical-imaging prompt-based
segmentation is just **one profile** (`profiles/cv-medical-segmentation.profile.yaml`). All
domain-specific invariants live in pluggable **domain profiles** (`profiles/*.yaml`), never hardcoded
into the control plane or agents.

## Layout

```
research_agent_teams/
├── schemas/      JSON-Schema artifact contracts (domain-agnostic)
├── profiles/     pluggable domain profiles (cv-medical-segmentation, nlp-text-classification, ai-generic, ...)
├── tools/        deterministic validators/hashers (the enforcement primitives)
├── tests/        REAL pytest for every tool — no "passes" without terminal evidence
├── agents/       (later) agent .md specs — the team roster
├── orchestrator/ (later) FSM graph spec: PARSE→RECALL→WORK→VERIFY→RECORD→REVIEW→REPORT + mode registry
└── runs/         (later) run-store: the team's runtime files (ephemeral, gitignored, outside the vault)
```

## Build status (toward the complete form)

- [x] Control plane · brick 1: artifact envelope + task_frame + domain_profile schemas, validator, canonical hasher + hash-chain, 3 example profiles, 21 real tests
- [x] Control plane · brick 2: ledger (hash-chain) + run-store + checkpoint/resume + crash/tamper detection, 16 real tests (37 total green)
- [x] Control plane · brick 3: FSM graph + mode registry + routing resolver + guardrails (15 tests)
- [x] Control plane · brick 4: budget/stop controller + ADR schema + observability log (12 tests)
- [x] Control plane · brick 5: permission-scope-guard + artifact-contract-enforcer (Python core + node-run .js hooks, 15 tests)
- [x] Control plane · brick 6: spine engine + end-to-end DRY-RUN (crash/resume/scope, 3 tests)
- [x] Control plane · brick H: foundation hardening (crash@every boundary, fuzz, parallel-no-collision, single-writer, 33 tests)
- [x] **MILESTONE M0 reached** — control plane complete + proven + hardened (**115 tests green**)
- [ ] operation-wiring: orchestrator SKILL.md + state-tracker.md + gate slash-skills + settings.json
- [ ] core agents (V1 = 16) → then V2 → then specialized (M1 → M2 → M3)

Run tests: `python -m pytest research_agent_teams/tests -v` (115 green at M0).

Run tests: `python -m pytest research_agent_teams/tests -v` (from the case-for-research dir).
