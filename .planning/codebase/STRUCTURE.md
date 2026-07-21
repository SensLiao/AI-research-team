---
last_mapped_commit: 165d62a6deaa4cd57eee18352d5a48aab626c49d
last_mapped_date: 2026-07-21
focus: arch
---
# Codebase Structure

**Analysis Date:** 2026-07-21

## Directory Layout

```text
research_agent_teams/
├── operate/                 # Productized, resumable CLI and operated mode recipes
│   └── modes/               # One-button mode implementations registered by the operate layer
├── orchestrator/            # Canonical stage graph, router, policies, roster, and engine
├── tools/                   # Deterministic validators, gates, stores, scoring, and adapters
├── schemas/                 # Versioned JSON Schema contracts for artifacts and evidence
├── agents/                  # Research/control worker role specifications and role references
├── skills/                  # Worker-facing scientific-method guidance used inside research runs
├── profiles/                # Swappable domain-rigor profiles
├── gates/                   # Human decision-gate contracts
├── hooks/                   # Scope and artifact enforcement hooks
├── execute/                 # Remote experiment plan/submit/status/pull adapter
├── server_monitor/          # Separately gated, read-only server status interface
├── resources/               # Secret-free resource policies, registries, and reference bindings
├── workspace/               # Workspace registries plus generated lease/audit state
│   └── registries/          # Command, stage, skill, and bridge control-plane registries
├── runs/                    # Gitignored per-project/per-run scratch and evidence store
├── projects/                # Gitignored machine-side project workspaces
├── tests/                   # Unit, contract, integration, boundary, and CLI tests
├── docs/                    # Operator-facing standards and explanatory documentation
├── _design/                 # Historical design, build, audit, and review records
├── README.md                # Repository overview and operating entry points
├── PLATFORM-FACTS.md        # Current verified capability and operational-truth source
├── AI-RESEARCH-TEAM-ARCHITECTURE-CN.md  # Broader Chinese architecture/design reference
└── __init__.py              # Python package marker
```

The project-level command adapters live one directory above this Git repository, including `../.agents/skills/research-orchestrator/SKILL.md` and the source-command skills. The validated knowledge vault is the separate sibling repository `../AI agent database/PhD-Research-OS/`; neither external tree belongs inside `research_agent_teams/`.

## Directory Purposes

**`operate/`:**
- Purpose: Expose resumable, director-facing operations and bridge real sub-agent waves to deterministic reducers.
- Contains: CLI verbs, stage spine, panel scheduler, artifact helpers, bounded repair, output versioning, and mode recipes.
- Key files: `operate/cli.py`, `operate/spine.py`, `operate/panel_scheduler.py`, `operate/artifacts.py`, `operate/bounded_repair.py`, `operate/output_versions.py`, `operate/modes/__init__.py`

**`operate/modes/`:**
- Purpose: Implement the wired product modes that can run through the operated CLI.
- Contains: Recipes for `new_direction`, `deep_ideation`, `evidence_review`, `evidence_deep`, `deep_research`, `gap_breadth`, `venue_readiness`, `full_rigor_minimal`, `ingest_paper`, and `read_paper_deep`.
- Key files: `operate/modes/__init__.py`, `operate/modes/read_paper_deep.py`, `operate/modes/evidence_deep.py`, `operate/modes/full_rigor_minimal.py`

**`orchestrator/`:**
- Purpose: Define the canonical, testable workflow independently of the external worker runtime.
- Contains: Routing, graph parsing, engine transitions, model/gate policies, agent connectivity, and YAML registries.
- Key files: `orchestrator/engine.py`, `orchestrator/router.py`, `orchestrator/graph_spec.py`, `orchestrator/graph.yaml`, `orchestrator/mode_registry.yaml`, `orchestrator/roster.yaml`, `orchestrator/plan_catalog.yaml`

**`tools/`:**
- Purpose: Own deterministic behavior and all narrow integration ports.
- Contains: Run-store persistence, schema validation, source/audit checkers, scorers, scope guards, recall, promotion, project/workspace lifecycle, resources, and search adapters.
- Key files: `tools/runstore.py`, `tools/validate_artifact.py`, `tools/scope_guard.py`, `tools/path_boundaries.py`, `tools/recall.py`, `tools/promote_gate.py`, `tools/promote.py`, `tools/document_promotion.py`, `tools/projects.py`

**`schemas/`:**
- Purpose: Provide machine-checkable contracts for task frames, envelopes, panels, evidence, audit outputs, and product artifacts.
- Contains: `*.schema.json` files referenced by validators and operated recipes.
- Key files: `schemas/task_frame.schema.json`, `schemas/artifact_envelope.schema.json`, `schemas/panel_synthesis.schema.json`

**`agents/`:**
- Purpose: Define the responsibilities, inputs, outputs, and restrictions of control and research worker roles.
- Contains: Root role specifications plus shared role references under `agents/references/`.
- Key files: `agents/research-orchestrator.md`, `agents/artifact-contract-enforcer.md`, `agents/references/`

**`skills/`:**
- Purpose: Supply worker-facing scientific practices, not Codex/GSD command routing.
- Contains: Guidance for hypothesis generation, literature review, recall, research lookup, source evaluation, and critical thinking.
- Key files: `skills/hypothesis-generation.md`, `skills/literature-review.md`, `skills/recall.md`, `skills/scholar-evaluation.md`, `skills/scientific-critical-thinking.md`

**`profiles/`:**
- Purpose: Keep domain-specific rigor configurable while the control plane remains domain-general.
- Contains: `*.profile.yaml` contracts for supported research domains.
- Key files: `profiles/cv-medical-segmentation.profile.yaml`, `profiles/cs-nlp-llm.profile.yaml`, `profiles/nlp-text-classification.profile.yaml`

**`gates/`:**
- Purpose: Document decisions that only the director or another explicitly authorized human can make.
- Contains: Idea, venue, publication, promotion, and reference-approval gate definitions.
- Key files: `gates/idea-bet.md`, `gates/promote-to-vault.md`, `gates/venue-pick.md`, `gates/venue-decide.md`, `gates/aers-reference-approve.md`

**`hooks/`:**
- Purpose: Enforce permission scope and artifact shape at tool boundaries.
- Contains: JavaScript hook implementations installed by the project harness.
- Key files: `hooks/permission-scope-guard.js`, `hooks/artifact-contract-enforcer.js`

**`execute/`:**
- Purpose: Keep non-LLM remote experiment execution behind an explicit adapter.
- Contains: CLI, deployment configuration loader, job model, and plan/submit/status/pull runner.
- Key files: `execute/cli.py`, `execute/config.py`, `execute/job.py`, `execute/runner.py`, `execute/__main__.py`

**`server_monitor/`:**
- Purpose: Provide a read-only status path that is distinct from experiment execution.
- Contains: Query planning, live status adapter, training-progress parsing, and manifest hashing.
- Key files: `server_monitor/monitor.py`, `server_monitor/train_progress.py`, `server_monitor/hash_manifest.py`, `server_monitor/PLATFORM-NOTES.md`

**`resources/`:**
- Purpose: Register execution resources by reference without storing secret values.
- Contains: Resource policy, registry, and backend reference YAML.
- Key files: `resources/resource-policy.yaml`, `resources/resource-registry.yaml`, `resources/backends.local.refs.yaml`

**`workspace/`:**
- Purpose: Hold the director cockpit's control-plane registries and generated workspace state.
- Contains: Committed YAML registries plus runtime lease and audit JSONL files.
- Key files: `workspace/registries/command-registry.yaml`, `workspace/registries/stage-registry.yaml`, `workspace/registries/skill-registry.yaml`, `workspace/registries/bridge-registry.yaml`

**`runs/`:**
- Purpose: Store ephemeral, reproducible run state outside the knowledge vault.
- Contains: `runs/<project>/<run_id>/manifest.yaml`, `ledger.jsonl`, `task_frame.artifact.json`, `obs.jsonl`, `inbox/`, `evidence/<STAGE>/`, and `director-review/`.
- Key files: Generated per run; accessed through `tools/runstore.py` and `operate/spine.py`.

**`projects/`:**
- Purpose: Store the machine-side workspace for a registered multi-run research project.
- Contains: `projects/<project>/results/`, `scripts/`, `figures/`, `notes/`, and lifecycle/resource state.
- Key files: Generated through `tools/projects.py`, `tools/workspace.py`, and `tools/lifecycle.py`.

**`tests/`:**
- Purpose: Verify orchestration transitions, mode contracts, schemas, CLI behavior, permissions, vault seams, and execution honesty.
- Contains: Python `test_*.py` modules and repository fixtures.
- Key files: `tests/test_engine.py`, `tests/test_operate_cli.py`, `tests/test_scope_guard.py`, `tests/test_promote_gate.py`

**`docs/`:**
- Purpose: Explain operational and scientific standards to maintainers and operators.
- Contains: Human-readable Markdown standards.
- Key files: Use `docs/` for explanatory material that does not participate in runtime policy.

**`_design/`:**
- Purpose: Preserve historical design, build, audit, and review records.
- Contains: Architecture blueprints, build plans, ledgers, and review documents.
- Key files: `_design/` records provide history; use `PLATFORM-FACTS.md` and executable contracts for current operational truth.

## Key File Locations

**Entry Points:**
- `operate/__main__.py`: Module entry for the operated research machine.
- `operate/cli.py`: Director-facing command parser and command handlers.
- `orchestrator/engine.py`: Programmatic entry for the canonical workflow engine.
- `execute/__main__.py`: Remote execution command entry.
- `server_monitor/__main__.py`: Read-only server query entry.
- `../.agents/skills/research-orchestrator/SKILL.md`: Project-level primary-assistant adapter that drives the operated commands.

**Configuration:**
- `orchestrator/graph.yaml`: Fixed stage topology.
- `orchestrator/mode_registry.yaml`: Operated and spec-only mode definitions.
- `orchestrator/roster.yaml`: Control/research role inventory and stage assignments.
- `orchestrator/plan_catalog.yaml`: Supported panel plans.
- `profiles/*.profile.yaml`: Domain-specific rigor.
- `resources/*.yaml`: Secret-free resource policy and references.
- `workspace/registries/*.yaml`: Command, stage, skill, and bridge control-plane registries.
- `.env.example`: Committed configuration shape only; keep actual values in the ignored `.env` and never read them into mapping documents.

**Core Logic:**
- `operate/spine.py`: Operated stage state machine and gate persistence.
- `operate/panel_scheduler.py`: Sparse dependency scheduling and worker authorization.
- `orchestrator/router.py`: Task-frame resolution and routing validation.
- `orchestrator/engine.py`: Canonical run/resume driver.
- `tools/runstore.py`: Atomic manifest updates and append-only ledger.
- `tools/validate_artifact.py`: Artifact envelope and payload validation.
- `tools/scope_guard.py`: Worker read/write boundary enforcement.
- `tools/recall.py`: Read-only knowledge-vault seam.
- `tools/promote_gate.py`: Director-authorized vault-write seam.

**Testing:**
- `tests/test_*.py`: Co-located repository-level test suite organized by behavior or module.
- `tests/test_engine.py`: Canonical state-machine coverage.
- `tests/test_panel_scheduler.py`: Operated panel scheduling coverage.
- `tests/test_scope_guard.py`: Permission and path-boundary coverage.
- `tests/test_promote_gate.py`: Promotion authorization and admission coverage.

## Naming Conventions

**Files:**
- Use `snake_case.py` for Python modules: `panel_scheduler.py`, `document_promotion.py`.
- Use `test_<behavior>.py` for tests: `test_scope_guard.py`, `test_operate_cli.py`.
- Use `<contract>.schema.json` for schema contracts: `task_frame.schema.json`.
- Use lowercase kebab-case for human gate and worker guidance Markdown: `promote-to-vault.md`, `scientific-critical-thinking.md`.
- Use `<domain>.profile.yaml` for domain rigor: `medical-imaging.profile.yaml`.
- Keep top-level operator/status documents uppercase where they are durable landmarks: `README.md`, `PLATFORM-FACTS.md`.

**Directories:**
- Use lowercase functional package names: `operate/`, `orchestrator/`, `execute/`.
- Use `runs/<project>/<run_id>/` for run isolation; never flatten runs across projects.
- Use `projects/<project>/<artifact-class>/` for project outputs such as `scripts/` and `figures/`.
- Use stage names as uppercase evidence subdirectories when created by the run store: `evidence/VERIFY/`.

## Where to Add New Code

**New Operated Mode:**
- Primary code: Add a recipe under `operate/modes/<mode_name>.py` and register it in `operate/modes/__init__.py`.
- Configuration: Add or update the definition in `orchestrator/mode_registry.yaml`, roster/connectivity entries in `orchestrator/roster.yaml`, and a plan in `orchestrator/plan_catalog.yaml` when required.
- Contracts: Add payload schemas under `schemas/` and deterministic validators/reducers under `tools/`.
- Tests: Add mode, scheduler, schema, CLI, and product-output coverage under `tests/test_<mode_name>*.py`.
- Documentation: Update `PLATFORM-FACTS.md` only after the mode's actual operated status is supported by evidence.

**New Agent Role:**
- Implementation: Add the role contract at `agents/<role-name>.md`.
- Shared guidance: Put reusable role material under `agents/references/` or scientific-method guidance under `skills/`.
- Registration: Add the role and allowed stage/connectivity to `orchestrator/roster.yaml` and relevant panel plan.
- Tests: Extend roster, connectivity, and scheduler tests under `tests/`.

**New Artifact Type:**
- Schema: Add `schemas/<artifact-name>.schema.json` and register it with the existing validation registry.
- Producer/consumer code: Add deterministic helpers in the closest `tools/<domain>.py` module and adapters in `operate/artifacts.py` or the owning mode.
- Tests: Cover a valid fixture, each truth-sensitive rejection, and commit-time re-validation under `tests/`.

**New Deterministic Gate or Checker:**
- Primary code: Add a focused module in `tools/` rather than embedding the check in a worker prompt.
- Contract: Add any output schema under `schemas/`.
- Workflow binding: Call it from the owning `operate/modes/<mode_name>.py` reducer or `orchestrator/gate_policy.py`.
- Tests: Add direct unit tests plus one operated-path test under `tests/`.

**New Domain Profile:**
- Implementation: Add `profiles/<domain>.profile.yaml` following the existing profile shape.
- Core logic: Reuse profile-aware generic code; do not add domain-specific branches to `orchestrator/engine.py` or `operate/spine.py`.
- Tests: Add profile validation and one consuming-tool test under `tests/`.

**New CLI or Workspace Command:**
- Command handler: Add the verb in `operate/cli.py` or the narrower `execute/cli.py`/`server_monitor/monitor.py` entry.
- Durable registration: Update the applicable `workspace/registries/*.yaml` file and external command adapter under `../.agents/skills/` when the command is director-facing.
- Implementation: Put reusable lifecycle, project, resource, or lease behavior in `tools/`.
- Tests: Add parser, success, denial, and resume/state tests under `tests/`.

**New Human Decision:**
- Contract: Add a Markdown gate under `gates/`.
- Policy: Bind it in `orchestrator/gate_policy.py` and the relevant mode/task frame.
- State: Persist the pending decision and its resolution through `tools/runstore.py`; never encode approval as an ordinary worker result.

**Vault Integration:**
- Read path: Extend `tools/recall.py` only when the vault's read contract changes.
- Write path: Extend `tools/promote_gate.py` and exactly one existing admission lane; do not create a general-purpose vault writer.
- Tests: Exercise cross-repository boundaries and verify the vault remains unchanged on every failed preflight.

**Utilities:**
- Shared deterministic helpers: `tools/`
- Orchestration-only policy: `orchestrator/`
- Operated product adaptation: `operate/`
- Remote execution behavior: `execute/`
- Avoid generic catch-all utility modules; place code beside the owning boundary.

## Special Directories

**`runs/`:**
- Purpose: Ephemeral run scratch, evidence, ledgers, and director review packets.
- Generated: Yes
- Committed: No; ignored by `.gitignore`.

**`projects/`:**
- Purpose: Machine-side, project-scoped scripts, pulled results, figures, notes, and lifecycle state.
- Generated: Yes
- Committed: No; ignored by `.gitignore` and deletable without touching the vault.

**`workspace/registries/`:**
- Purpose: Declarative control-plane registries for commands, stages, skills, and bridges.
- Generated: No
- Committed: Yes

**`workspace/*.jsonl`:**
- Purpose: Runtime lease and audit records such as `workspace/lease_registry.jsonl` and `workspace/audit_log.jsonl`.
- Generated: Yes
- Committed: No; treat them as local runtime state and inspect the changed-file list before shipping.

**`schemas/`:**
- Purpose: Deterministic, versioned contracts consumed at producer and commit boundaries.
- Generated: No
- Committed: Yes

**`_design/`:**
- Purpose: Historical architecture, build, audit, and review evidence.
- Generated: Mixed
- Committed: Yes for selected durable records; do not use it as the current runtime registry.

**`../AI agent database/PhD-Research-OS/`:**
- Purpose: Separate validated knowledge-vault repository.
- Generated: No
- Committed: Yes, but in its own Git repository. Access by `tools/recall.py` and explicit promotion only.

**`../.agents/skills/`:**
- Purpose: Project-level Codex adapters and director source-command gates outside the machine repository.
- Generated: No
- Committed: Managed by the parent project, not by this repository.

**`.env`:**
- Purpose: Local, ignored deployment configuration when present.
- Generated: Locally provisioned
- Committed: No. Never read, quote, or copy its contents into code, logs, tests, or planning documents.

---

*Structure analysis: 2026-07-21*
