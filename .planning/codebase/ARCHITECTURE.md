---
last_mapped_commit: 165d62a6deaa4cd57eee18352d5a48aab626c49d
last_mapped_date: 2026-07-21
focus: arch
---
<!-- refreshed: 2026-07-21 -->
# Architecture

**Analysis Date:** 2026-07-21

## System Overview

```text
┌───────────────────────────────────────────────────────────────────────────────┐
│ Director-facing adapters                                                     │
│ `../.agents/skills/research-orchestrator/SKILL.md` · `operate/cli.py`         │
└──────────────────────────────────┬────────────────────────────────────────────┘
                                   │ begin / resume / dets / commit / approve
                                   ▼
┌───────────────────────────────────────────────────────────────────────────────┐
│ Operated, resumable control adapter                                           │
│ `operate/spine.py` · `operate/panel_scheduler.py` · `operate/modes/`          │
└──────────────────────┬───────────────────────────┬────────────────────────────┘
                       │                           │
                       ▼                           ▼
┌──────────────────────────────────────┐  ┌─────────────────────────────────────┐
│ Canonical orchestration core         │  │ Deterministic contract layer        │
│ `orchestrator/`                      │  │ `tools/` · `schemas/` · `hooks/`    │
│ route → stage → gate → checkpoint    │  │ validate · score · guard · ledger   │
└───────────────────┬──────────────────┘  └──────────────────┬──────────────────┘
                    └──────────────────────┬──────────────────┘
                                           ▼
┌───────────────────────────────────────────────────────────────────────────────┐
│ Machine-owned state                                                          │
│ `runs/<project>/<run_id>/` · `projects/<project>/` · `workspace/`            │
└─────────────────────────┬──────────────────────────────┬──────────────────────┘
                          │ recall / explicit promotion  │ gated execution
                          ▼                              ▼
┌────────────────────────────────────────┐  ┌───────────────────────────────────┐
│ Separate knowledge-vault repository    │  │ External compute boundary         │
│ `../AI agent database/PhD-Research-OS/`│  │ `execute/` · `server_monitor/`    │
└────────────────────────────────────────┘  └───────────────────────────────────┘
```

The repository is THE MACHINE: it coordinates research work, validates artifacts, and keeps scratch state. The sibling `../AI agent database/PhD-Research-OS/` is THE DATABASE: a separate Git repository containing admitted knowledge. Preserve the seam: use `tools/recall.py` for reference-based reads and the explicit director-command promotion path for writes.

## Component Responsibilities

| Component | Responsibility | File |
|-----------|----------------|------|
| Director adapter | Converts a director request into the operated workflow and exposes the command surface | `../.agents/skills/research-orchestrator/SKILL.md`, `operate/cli.py` |
| Operated spine | Persists stage lifecycle, checkpoints, and human-gate transitions | `operate/spine.py` |
| Panel scheduler | Releases only dependency-safe worker waves and records authorization receipts | `operate/panel_scheduler.py` |
| Mode recipes | Productize the wired research modes and their deterministic reducers | `operate/modes/` |
| Router | Resolves a request into a frozen, schema-valid task frame | `orchestrator/router.py` |
| Engine | Provides the synchronous, testable PARSE→REPORT state-machine core | `orchestrator/engine.py` |
| Graph and policy | Defines stage topology, mode metadata, model policy, agent connectivity, and gate rules | `orchestrator/graph.yaml`, `orchestrator/mode_registry.yaml`, `orchestrator/roster.yaml`, `orchestrator/gate_policy.py` |
| Run store | Owns manifests, checkpoints, task-frame pinning, ledger events, and resume classification | `tools/runstore.py` |
| Artifact contracts | Validates the common envelope and registered payload schemas | `tools/validate_artifact.py`, `schemas/` |
| Permission boundary | Restricts workers to the active run/stage and blocks direct vault access | `tools/scope_guard.py`, `tools/path_boundaries.py`, `hooks/permission-scope-guard.js` |
| Recall port | Searches the vault by reference and returns bounded provenance pointers | `tools/recall.py` |
| Promotion gate | Re-validates explicit director-authorized promotion requests | `tools/promote_gate.py` |
| Promotion writers | Admit frozen results or reviewed Markdown through separate lanes | `tools/promote.py`, `tools/document_promotion.py` |
| Compute adapter | Plans and, when explicitly enabled, submits/statuses/pulls remote jobs | `execute/runner.py`, `execute/job.py` |
| Read-only server monitor | Reports server status without becoming an experiment executor | `server_monitor/monitor.py` |
| Domain profiles | Hold domain-specific rigor outside the control plane | `profiles/*.profile.yaml` |

## Pattern Overview

**Overall:** Configuration-driven, stage-oriented orchestration with ports/adapters, deterministic evidence gates, and an append-only run store.

**Key Characteristics:**
- Treat `orchestrator/` as the canonical state-machine and policy core; keep product-facing resumability in `operate/`.
- Treat workers as stage-scoped producers. Workers write candidate bundles under the active run, while deterministic code validates and commits them.
- Persist durable workflow facts in `manifest.yaml`, `ledger.jsonl`, evidence artifacts, and checkpoint hashes rather than in chat history.
- Separate probabilistic research work from deterministic validation in `tools/` and `schemas/`.
- Keep the knowledge vault and remote compute behind narrow, explicit ports rather than importing their state into the machine.
- Configure domain behavior through `profiles/` and mode behavior through registries/recipes; do not hardcode one scientific domain into orchestration code.

## Layers

**Director and Command Interface:**
- Purpose: Parse human intent, select an operation, and expose explicit human decisions.
- Location: `../.agents/skills/`, `operate/cli.py`, `gates/`
- Contains: Orchestrator skill instructions, CLI verbs, and director-gate contracts.
- Depends on: `operate/spine.py`, `operate/panel_scheduler.py`, workspace tools, and promotion tools.
- Used by: The primary assistant and the director; workers must not invoke director-only gates.

**Operated Workflow Adapter:**
- Purpose: Turn the canonical lifecycle into resumable, real sub-agent work with deterministic reducers.
- Location: `operate/`
- Contains: Stage spine, recipes, artifact adapters, bounded repair, packet rendering, and wave scheduling.
- Depends on: `orchestrator/`, `tools/`, `schemas/`, and `execute/` for plan emission.
- Used by: `operate/cli.py` and the external agent harness.

**Canonical Orchestration Core:**
- Purpose: Resolve routing, enforce graph transitions, select policies, and model gates independently of a specific worker runtime.
- Location: `orchestrator/`
- Contains: Router, engine, graph parser, connectivity rules, mode/roster/plan registries, and policy modules.
- Depends on: Run-store and validation utilities in `tools/`.
- Used by: `operate/`, tests in `tests/`, and capability inspection tools.

**Research Worker Specifications:**
- Purpose: Define single-stage scientific roles and reusable scientific-method guidance.
- Location: `agents/`, `skills/`
- Contains: Worker role Markdown, role references, literature/recall/evaluation guidance.
- Depends on: Read scopes and artifact contracts selected by the scheduler.
- Used by: The external agent harness after `operate/panel_scheduler.py` authorizes a wave.

**Deterministic Enforcement:**
- Purpose: Convert worker outputs into reproducible evidence and reject contract, scope, provenance, or truth violations.
- Location: `tools/`, `schemas/`, `hooks/`
- Contains: JSON Schema validation, scorers, audit logic, permission guards, ledger/hash utilities, recall, promotion, workspace, and resource controls.
- Depends on: Versioned schemas/configuration and run-local inputs.
- Used by: Both orchestration paths, CLI reducers, Git/tool hooks, and tests.

**Machine State:**
- Purpose: Store scratch runs, project workspaces, leases, registries, and audit history without polluting the vault.
- Location: `runs/`, `projects/`, `workspace/`, `resources/`
- Contains: Per-run manifests/evidence/review packets; project scripts/results/figures/notes; workspace registries and redacted resource references.
- Depends on: Atomic file writes and the append-only ledger implementation in `tools/runstore.py`.
- Used by: All operated commands and resumable stages.

**External Boundaries:**
- Purpose: Read/admit validated knowledge and optionally operate remote compute.
- Location: `tools/recall.py`, `tools/promote_gate.py`, `tools/promote.py`, `tools/document_promotion.py`, `execute/`, `server_monitor/`
- Contains: Narrow adapters only; external state remains outside this repository.
- Depends on: Director authorization, project binding, hashes, audit evidence, and deployment configuration.
- Used by: Recall, promotion, experiment planning, and explicitly enabled live operations.

## Data Flow

### Primary Operated Research Path

1. Start a registered project run through `cmd_begin`; the CLI validates project membership and opens the operated spine (`operate/cli.py:175`, `operate/spine.py:54`).
2. Resolve the request into a frozen task frame containing the north star, stage path, model policy, agent subset, budgets, product contract, and human gates (`orchestrator/router.py:18`).
3. Create the run, pin the task-frame hash, and append the opening ledger events (`tools/runstore.py:99`, `tools/runstore.py:127`).
4. Build the selected mode's panel and release only the next dependency-safe worker wave (`operate/modes/`, `operate/panel_scheduler.py:691`).
5. Workers write stage-scoped bundles to `runs/<project>/<run_id>/inbox/`; deterministic reducers validate, score, and write schema-wrapped evidence (`operate/cli.py:376`, `tools/validate_artifact.py`).
6. Commit re-validates scope and every artifact, appends observations and checkpoint hashes, and persists any pending human gate (`operate/cli.py:433`, `operate/spine.py:134`).
7. A director approval or rejection is hash-chained and releases exactly the pinned successor or terminal state (`operate/cli.py:475`, `operate/spine.py:176`).
8. REPORT renders the human entry point at `runs/<project>/<run_id>/director-review/00-REVIEW-PACKET.md`; machine JSON remains evidence/archive (`operate/cli.py:496`).

### Canonical Engine Path

1. Resolve and validate the requested mode and stage path (`orchestrator/router.py:95`, `orchestrator/engine.py:47`).
2. Drive each stage synchronously through a supplied opaque worker function (`orchestrator/engine.py:75`).
3. Apply gates and checkpoints through the canonical run-store contract (`orchestrator/engine.py:127`, `orchestrator/engine.py:147`).

Use `orchestrator/engine.py` for deterministic core behavior and tests. Use `operate/spine.py` when real sub-agent dispatch must pause between stages: the operated path checkpoints reviewable output, persists `gate_pending`, and waits for a later explicit decision.

### Vault Recall Flow

1. Call `tools/recall.py:294` with a query and optional project scope.
2. Read the vault index and eligible `02-wiki/` pages without mutating the sibling repository.
3. Rank slug, text, wikilink, and temporal signals and return bounded slug/hash/section/support pointers.
4. Record the recalled references in the run so downstream claims remain traceable.

### Vault Promotion Flow

1. Stage a candidate under the active run's `inbox/`; never write a worker artifact directly into the vault.
2. Require a top-level explicit `/promote-to-vault` director command and invoke `tools/promote_gate.py:164`.
3. For a result, use `tools/promote.py:230` to re-derive frozen and thesis-citation eligibility from real audits.
4. For reviewed Markdown, use `tools/document_promotion.py:688` to preflight all candidates, verify source hashes/project binding/target contracts, and copy the full document atomically.
5. Record promotion provenance. A document admission does not create a result or a thesis-citable metric.

### External Experiment Flow

1. Generate a remote job plan without claiming execution (`execute/runner.py:105`).
2. Submit only when the deployment has explicitly enabled live execution and the director has supplied the required out-of-repository configuration (`execute/runner.py:189`).
3. Query job state and pull raw outputs through the same adapter (`execute/runner.py:220`, `execute/runner.py:239`).
4. Accept numeric research results only when raw result files are bound to valid non-LLM executor evidence; scripts-only runs remain planned.

**State Management:**
- Keep run state under `runs/<project>/<run_id>/`: `manifest.yaml` is the current snapshot and `ledger.jsonl` is the tamper-evident event history.
- Use `tools/runstore.py` atomic temp/write/fsync/replace operations for manifests and its locked, hash-chained append path for the ledger.
- Keep project-level scripts, figures, notes, pulled results, lifecycle state, and resource bindings under `projects/<project>/`.
- Keep shared command/stage/skill/bridge registries and workspace lease/audit state under `workspace/`.
- Treat `runs/` and `projects/` as machine-owned scratch/workspace, not knowledge-vault storage.

## Key Abstractions

**Task Frame:**
- Purpose: Freeze the north star, routing, budgets, policies, permitted agents, product contract, and gates before work begins.
- Examples: `orchestrator/router.py`, `schemas/task_frame.schema.json`, `tools/runstore.py`
- Pattern: Immutable, hash-pinned command object.

**Stage Graph:**
- Purpose: Define legal PARSE→RECALL→WORK→VERIFY→RECORD→REVIEW→REPORT transitions.
- Examples: `orchestrator/graph.yaml`, `orchestrator/graph_spec.py`, `orchestrator/engine.py`
- Pattern: Configuration-backed finite-state machine.

**Mode Recipe:**
- Purpose: Bind an operated product to its panel roles, dependencies, deterministic reducers, and output contract.
- Examples: `operate/modes/__init__.py`, `operate/modes/read_paper_deep.py`, `orchestrator/mode_registry.yaml`
- Pattern: Registry plus strategy modules. A registry entry alone is not an operated recipe.

**Artifact Envelope:**
- Purpose: Carry typed payloads with provenance, stage, run, and validation metadata.
- Examples: `operate/artifacts.py`, `tools/validate_artifact.py`, `schemas/artifact_envelope.schema.json`
- Pattern: Versioned schema contract.

**Panel Authorization Receipt:**
- Purpose: Prove that a worker wave was dependency-safe, in scope, and within budget before dispatch.
- Examples: `operate/panel_scheduler.py`, `schemas/panel_synthesis.schema.json`
- Pattern: Persisted capability grant with predecessor hashes.

**Director Gate:**
- Purpose: Separate machine-derived evidence from human decisions about research bets, venues, publication, and vault admission.
- Examples: `gates/idea-bet.md`, `gates/venue-pick.md`, `gates/venue-decide.md`, `gates/promote-to-vault.md`
- Pattern: Explicit, hash-linked human checkpoint.

**Project Workspace:**
- Purpose: Group multi-run machine artifacts under one registered research project without writing into the vault.
- Examples: `tools/projects.py`, `tools/workspace.py`, `projects/<project>/`, `runs/<project>/`
- Pattern: Project-scoped scratch aggregate bound to a read-only vault registry entry.

## Entry Points

**Operated CLI:**
- Location: `operate/cli.py`, `operate/__main__.py`
- Triggers: `python -m research_agent_teams.operate ...`
- Responsibilities: Begin/resume runs, execute deterministic reducers, commit stages, resolve gates, render packets, and manage workspace/project commands.

**Canonical Engine API:**
- Location: `orchestrator/engine.py`
- Triggers: Tests and programmatic orchestration through `run_task` or `resume_task`.
- Responsibilities: Drive the canonical stage graph with an injected worker function.

**Remote Execution CLI:**
- Location: `execute/cli.py`, `execute/__main__.py`
- Triggers: Plan, submit, status, and pull commands.
- Responsibilities: Keep remote job handling separate from reasoning-worker output and default to an offline plan.

**Server Query CLI:**
- Location: `server_monitor/__main__.py`, `server_monitor/monitor.py`
- Triggers: Read-only server status requests.
- Responsibilities: Plan a query or perform an explicitly enabled live read without executing research jobs.

**Hook Guards:**
- Location: `hooks/permission-scope-guard.js`, `hooks/artifact-contract-enforcer.js`
- Triggers: Project-installed tool and artifact hooks.
- Responsibilities: Fail closed on out-of-scope writes and malformed artifact submissions.

## Architectural Constraints

- **Threading:** The CLI and finite-state machine are synchronous. The external harness may execute independent workers within a scheduler-approved wave concurrently; internal scholarly search may use bounded thread pools in `tools/paper_search.py`.
- **Global state:** Authoritative mutable state is file-backed and project/run scoped. `tools/recall.py` maintains only a process-local index cache; do not make module globals the source of workflow truth.
- **Circular imports:** No non-trivial cycle appears in the inspected Python import graph. Preserve the dominant `operate → orchestrator/tools/execute` and `orchestrator → tools` direction; keep existing feature-specific back-edges lazy and narrow.
- **Single-writer boundary:** Only `tools/promote.py` and `tools/document_promotion.py`, reached through `tools/promote_gate.py`, may write the vault.
- **Human decisions:** Workers, scheduled modes, and completed runs cannot self-approve idea bets, venue decisions, publication, or vault promotion.
- **Domain generality:** Put domain rigor in `profiles/*.profile.yaml`; keep `orchestrator/`, `operate/`, and generic tools domain-neutral.
- **Repository boundary:** Do not commit the sibling vault into this repository or this machine into the vault repository.
- **Execution truth:** Remote scripts, a coherent journal, or model-produced metrics do not prove that an experiment ran. Require raw outputs and valid executor evidence.
- **Operational truth:** Only modes present in `operate/modes/__init__.py::REGISTRY` are one-button operated modes; other `orchestrator/mode_registry.yaml` entries are routable specifications.

## Anti-Patterns

### Direct Vault Writes

**What happens:** A worker, helper, or manual script writes into `../AI agent database/PhD-Research-OS/`.
**Why it's wrong:** It bypasses director authorization, provenance re-derivation, and the two-lane admission contract.
**Do this instead:** Stage under `runs/<project>/<run_id>/inbox/` and enter through `tools/promote_gate.py` plus the appropriate writer.

### Registry-Only Mode Presented as Operated

**What happens:** A mode listed only in `orchestrator/mode_registry.yaml` is exposed as a one-button product.
**Why it's wrong:** The mode lacks an `operate/modes/` recipe, worker-wave contract, deterministic reducer, or complete human output path.
**Do this instead:** Add and register an operated recipe in `operate/modes/`, its schemas/checkers, and tests before exposing it through `operate/cli.py`.

### Dispatch Outside the Scheduler

**What happens:** A caller starts workers before predecessor hashes, read scope, roster connectivity, and budgets are authorized.
**Why it's wrong:** Evidence can be contaminated by future-stage information or produced outside the frozen task frame.
**Do this instead:** Obtain the next authorization receipt from `operate/panel_scheduler.py` and dispatch only that wave.

### Chat as Workflow State

**What happens:** Resume decisions rely on conversational memory instead of the run store.
**Why it's wrong:** The stage, gate, hashes, budget, and artifacts can diverge from the durable record.
**Do this instead:** Classify and resume through `tools/runstore.py:413` and `tools/runstore.py:445`.

### Domain Logic in the Control Plane

**What happens:** Medical imaging, NLP, or another domain's thresholds are hardcoded into `orchestrator/` or generic `tools/` modules.
**Why it's wrong:** It breaks the repository's domain-general contract and makes policies impossible to swap cleanly.
**Do this instead:** Add or extend a `profiles/*.profile.yaml` contract and consume it through existing profile-aware tools.

### Scripts-Only Output Reported as Execution

**What happens:** Generated scripts or model-authored metrics are described as a completed GPU experiment.
**Why it's wrong:** There is no external executor receipt or raw result provenance.
**Do this instead:** Keep the result state planned until `execute/` returns verifiable raw outputs and the audit layer accepts them.

## Error Handling

**Strategy:** Fail closed at scope, schema, evidence, budget, and human-decision boundaries while persisting enough structured state for safe resume or targeted repair.

**Patterns:**
- Raise typed boundary errors such as `PermissionError`, `GateBlock`, `TargetedGateBlock`, and `BudgetExceeded` from deterministic layers.
- Emit structured JSON and stable non-zero CLI exit codes from `operate/cli.py`; input/config failures, gate blocks, and budget/live-operation refusals remain distinguishable.
- Persist hard gate failures as failed run state. Preserve accepted upstream outputs when `operate/bounded_repair.py` can request a hash-linked targeted supplement.
- Reject malformed artifacts at production time through `hooks/artifact-contract-enforcer.js` and again at commit time through `tools/validate_artifact.py`.
- Append gate decisions and checkpoint hashes to `ledger.jsonl`; never rewrite prior ledger history.

## Cross-Cutting Concerns

**Logging:** Use the per-run hash-chained `ledger.jsonl` for authoritative events, `obs.jsonl` for stage observations, and workspace audit logs for redacted resource/lifecycle actions. Human-facing output belongs under `director-review/`.

**Validation:** Validate the artifact envelope and registered payload schema, verify provenance/source hashes, re-check scope at commit, and keep truth-sensitive gates deterministic. Treat Markdown presentation gaps separately from scientific truth failures where the mode contract permits targeted repair.

**Authentication:** Local research work requires no general application identity layer. Sensitive actions use capability boundaries: explicit director commands, project registration, default-deny resource bindings, time-bounded leases, ignored environment configuration, and deployment flags for live server access.

---

*Architecture analysis: 2026-07-21*
