---
last_mapped_commit: 165d62a6deaa4cd57eee18352d5a48aab626c49d
mapping_scope: full_repo
---

# Technology Stack

**Analysis Date:** 2026-07-21

## Languages

**Primary:**
- Python 3.9+ - All control-plane, operated-mode, scientific-checker, GPU-execution, monitoring, and test code lives in `operate/`, `orchestrator/`, `tools/`, `execute/`, `server_monitor/`, and `tests/`. The current checkout imports under Python 3.9.13; the repository does not declare or pin a supported Python version.
- YAML 1.2-style documents - Agent topology, mode routing, profiles, resource policy, and command registries are data-driven in `orchestrator/*.yaml`, `profiles/*.profile.yaml`, `resources/**/*.yaml`, and `workspace/registries/*.yaml`.
- JSON / JSON Schema Draft 2020-12 - Artifact contracts and executor receipts are defined under `schemas/*.schema.json` and enforced by `tools/validate_artifact.py` and `tools/execution_receipt_import.py`.

**Secondary:**
- JavaScript (Node.js) - Two dependency-free tool guards run as Node scripts in `hooks/permission-scope-guard.js` and `hooks/artifact-contract-enforcer.js`.
- Markdown - Agent role specifications, human gates, research standards, and director-facing products are defined under `agents/`, `gates/`, `skills/`, and `docs/`; these files are part of the executable operating contract even though they are not compiled.
- POSIX shell - Remote GPU job scripts are generated as LF-only shell text by `execute/job.py` and launched through `tmux` by `execute/runner.py`.

## Runtime

**Environment:**
- CPython - The inspected environment is Python 3.9.13; code relies on Python 3.9-era built-in generics and string helpers throughout `operate/`, `tools/`, and `execute/`, but no `requires-python` metadata exists.
- Node.js - The inspected environment is v22.17.0; Node is needed only for the two hook entry points in `hooks/`, and no Node engine constraint is declared.
- Local CLI/package runtime - There is no HTTP application server or long-running web framework; the main entry points are `operate/__main__.py`, `execute/__main__.py`, and `server_monitor/__main__.py`.
- Linux GPU host runtime - Live experiment execution assumes remote Bash, Python/Conda, `tmux`, and optionally NVIDIA tooling as encoded in `execute/job.py`, `server_monitor/monitor.py`, and `server_monitor/train_progress.py`.

**Package Manager:**
- pip 22.2.2 - Present in the inspected environment, but the repository has no `requirements*.txt`, `pyproject.toml`, `setup.py`, `Pipfile`, or Python lockfile.
- npm/pnpm/yarn - Not used; there is no `package.json` or JavaScript lockfile, and `hooks/*.js` use Node built-ins only.
- Lockfile: missing for both Python and Node alongside the repository-root `README.md` and `.gitignore`; dependency versions below are observed local versions, not repository guarantees.

## Frameworks

**Core:**
- Custom Python orchestration engine - The seven-stage state machine and transition enforcement are implemented directly in `orchestrator/engine.py`, `operate/spine.py`, `tools/runstore.py`, and `orchestrator/graph.yaml`.
- Custom operated-mode layer - Ten wired research recipes are registered in `operate/modes/__init__.py` and mirrored by `orchestrator/mode_registry.yaml`; no workflow-framework dependency is used.
- `argparse` CLIs - Command surfaces are standard-library CLIs in `operate/cli.py`, `execute/cli.py`, `server_monitor/__main__.py`, and tool-specific modules such as `tools/paper_search.py`.
- JSON Schema Draft 2020-12 - `jsonschema.Draft202012Validator` is the artifact contract engine in `tools/validate_artifact.py` and the signed execution-import validator in `tools/execution_receipt_import.py`.

**Testing:**
- pytest 8.4.2 - The test suite is under `tests/`; configuration is fixture-based in `tests/conftest.py` because no `pytest.ini`, `tox.ini`, or `pyproject.toml` exists.
- Offline injectable transports/fakes - Network and SSH boundaries expose injectable transports or executors in `tools/scholar_clients.py`, `tools/paper_search.py`, `tools/fulltext_qa.py`, `tools/openreviewer_seat.py`, and `server_monitor/monitor.py`.

**Build/Dev:**
- No compilation or bundling step - Python modules execute from source and Node directly executes `hooks/*.js`; no Dockerfile, build configuration, or packaging metadata is present.
- Module invocation - Run control-plane commands from the directory containing the `research_agent_teams/` package, as shown by `README.md`, using `python -m research_agent_teams.operate`, `python -m research_agent_teams.execute`, or `python -m research_agent_teams.server_monitor`.
- Schema/config validation - Treat `schemas/*.schema.json`, `orchestrator/*.yaml`, and `profiles/*.profile.yaml` as build-time contracts even though they are loaded at runtime by `tools/validate_artifact.py`, `orchestrator/graph_spec.py`, and `orchestrator/model_policy.py`.

## Key Dependencies

**Critical:**
- PyYAML 6.0.2 (observed, unpinned) - Parses orchestration graphs, manifests, profiles, resource policies, and registries in `orchestrator/graph_spec.py`, `operate/panel_scheduler.py`, `operate/modes/_shared.py`, and `tools/resources.py`.
- jsonschema 4.25.1 (observed, unpinned) - Enforces the artifact envelope/payload registry and executor-receipt contracts in `tools/validate_artifact.py` and `tools/execution_receipt_import.py`.
- cryptography 47.0.0 (observed, unpinned) - Verifies external executor Ed25519 attestations before real metrics are accepted in `tools/execution_receipt_import.py`.
- PyMuPDF 1.26.5 / `fitz` (observed, unpinned) - Provides local PDF text extraction and page rendering in `tools/fulltext_qa.py`, `tools/citation_attribution.py`, and `tools/paper_visual_assets.py`.
- pytest 8.4.2 (observed, unpinned) - Runs the repository-wide deterministic suite in `tests/`.

**Infrastructure:**
- Paramiko 2.8.1 (observed, unpinned) - Lazily opens pinned-host-key SSH/SFTP sessions only for authorized live paths in `execute/runner.py` and `server_monitor/monitor.py`.
- PaperQA / `paperqa` (optional, not installed in the inspected environment) - When available, supplies full-text QA through a lazy import in `tools/fulltext_qa.py`; local PDFs fall back to PyMuPDF and otherwise return an honest unavailable result.
- Python standard library networking - `urllib`, `xml.etree.ElementTree`, `json`, and `concurrent.futures` implement the multi-provider scholarly layer without `requests` in `tools/scholar_clients.py` and `tools/paper_search.py`.
- Python standard library persistence - `pathlib`, JSON/YAML/JSONL, hashing, file locks, and `sqlite3` implement local state in `tools/runstore.py`, `tools/ledger.py`, `tools/obslog.py`, and `tools/citation_existence.py`.
- Node built-ins - `fs`, `path`, and related standard modules support hook enforcement in `hooks/permission-scope-guard.js` and `hooks/artifact-contract-enforcer.js`; no npm dependencies are required.

## Configuration

**Environment:**
- A gitignored `.env` exists at `.env`; a tracked `.env.example` also exists, but neither file's contents were read during mapping. The minimal loader in `execute/config.py` reads `KEY=VALUE` pairs without adding a dotenv package.
- Scholarly access uses optional variable names referenced by `tools/scholar_clients.py`: `RAT_S2_API_KEY`, `RAT_OPENALEX_API_KEY`, and `RAT_CONTACT_MAIL`.
- Local review uses `RAT_OLLAMA_URL` and `RAT_OPENREVIEWER_MODEL` in `tools/openreviewer_seat.py`; the endpoint is constrained to loopback.
- GPU access uses `RAT_SERVER_*`, `RAT_REMOTE_*`, `RAT_RESULTS_PULL_DIR`, `RAT_SCHEDULER`, and exact authorization capabilities in `execute/config.py`, `execute/runner.py`, and `server_monitor/monitor.py`.
- Runtime model binding is provider-neutral by default; optional concrete deployment fields come from `RAT_RUNTIME_MODEL`, `RAT_RUNTIME_REASONING_EFFORT`, and `RAT_RUNTIME_SERVICE_TIER` in `orchestrator/model_policy.py`.
- Root relocation uses named variables such as `RAT_RUNS_DIR`, `RAT_PROJECTS_ROOT`, `RAT_VAULT_ROOT`, `RAT_WORKSPACE_ROOT`, and `RAT_RESOURCES_ROOT` in `tools/runstore.py`, `tools/projects.py`, `tools/scope_guard.py`, and `tools/resources.py`.
- Executor trust uses dynamically named public-key variables of the form `RAT_EXECUTOR_TRUST_PUBLIC_KEY_<KEY_ID>` in `tools/execution_receipt_import.py`; private signing keys are intentionally outside the reasoning runtime and repository.

**Build:**
- Orchestration configuration: `orchestrator/graph.yaml`, `orchestrator/mode_registry.yaml`, `orchestrator/plan_catalog.yaml`, and `orchestrator/roster.yaml`.
- Domain configuration: `profiles/*.profile.yaml`, validated against `schemas/domain_profile.schema.json` through `tools/validate_artifact.py`.
- Resource configuration: `resources/resource_registry.yaml`, `resources/resource_policy.yaml`, and `resources/backends/*.yaml`; these store capability metadata and environment-variable names, not secret values.
- Command configuration: `workspace/registries/command_registry.yaml`, `workspace/registries/stage_registry.yaml`, `workspace/registries/skill_registry.yaml`, and `workspace/registries/bridge_registry.yaml`.
- Artifact configuration: `schemas/*.schema.json` is the source of truth consumed by `tools/validate_artifact.py`; schema additions must also be registered in `PAYLOAD_SCHEMAS` there.

## Platform Requirements

**Development:**
- Use Python 3.9+ with the unpinned dependencies above; install them explicitly because the repository has no environment manifest. Import behavior is exercised from the parent directory by `tests/conftest.py` and the commands documented in `README.md`.
- Windows and POSIX file locking are both handled through conditional `msvcrt` / `fcntl` imports in the local-state layer under `tools/`; path-boundary code in `tools/scope_guard.py` and `tools/path_boundaries.py` must remain cross-platform.
- Node.js is required only when the host harness activates `hooks/permission-scope-guard.js` and `hooks/artifact-contract-enforcer.js`.
- Network-free operation remains available for most deterministic checks; live literature retrieval in `tools/scholar_clients.py`, local Ollama in `tools/openreviewer_seat.py`, and SSH in `execute/runner.py` are optional/gated boundaries.

**Production:**
- This repository is a local research control plane, not a deployed web service; `README.md` and `PLATFORM-FACTS.md` define local/module operation and no hosting, container, process-manager, or CI definition is present.
- Real experiment execution targets a separately configured Linux GPU server over SSH/SFTP and `tmux` through `execute/runner.py`; `PLATFORM-FACTS.md` states that this live GPU path is built/tested but not yet operated on real research.
- Durable validated knowledge lives in the separate PhD-Research-OS Markdown vault; `tools/recall.py`, `tools/promote_gate.py`, and `tools/document_promotion.py` are the only supported integration seam.

---

*Stack analysis: 2026-07-21*
*Observed package versions are local-environment evidence because the repository has no dependency lockfile.*
