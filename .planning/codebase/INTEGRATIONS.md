---
last_mapped_commit: 165d62a6deaa4cd57eee18352d5a48aab626c49d
mapping_scope: full_repo
---

# External Integrations

**Analysis Date:** 2026-07-21

## APIs & External Services

**Scholarly metadata:**
- arXiv Export API - Free Atom metadata search and identifier lookup in `tools/scholar_clients.py`.
  - SDK/Client: Python `urllib.request` plus `xml.etree.ElementTree` in `tools/scholar_clients.py`.
  - Auth: None; a polite user agent can include the `RAT_CONTACT_MAIL` identity referenced in `tools/scholar_clients.py`.
  - Failure behavior: Network and malformed-response failures become `ScholarLookupError`, while a genuine not-found remains distinct in `tools/scholar_clients.py`.
- OpenAlex Works API - Metadata search plus DOI/title resolution, including DataCite-style records, in `tools/scholar_clients.py`.
  - SDK/Client: Python `urllib.request` and JSON parsing in `tools/scholar_clients.py`.
  - Auth: Optional `RAT_OPENALEX_API_KEY`; optional polite-pool identity `RAT_CONTACT_MAIL`, both named in `tools/scholar_clients.py` and `resources/resource_registry.yaml`.
- Crossref Works API - Metadata search, DOI resolution, and retraction/correction/concern lookup in `tools/scholar_clients.py` and `tools/fulltext_qa.py`.
  - SDK/Client: Python `urllib.request` and JSON parsing in `tools/scholar_clients.py`.
  - Auth: No API token; optional contact identity `RAT_CONTACT_MAIL` is declared in `resources/resource_registry.yaml`.
- Semantic Scholar Academic Graph API - Paper/title search plus incoming/outgoing citation graph expansion in `tools/scholar_clients.py`.
  - SDK/Client: Python `urllib.request` against Graph v1 in `tools/scholar_clients.py`.
  - Auth: Optional `RAT_S2_API_KEY` sent as `x-api-key`, as implemented in `tools/scholar_clients.py` and declared in `resources/resource_registry.yaml`.
- Multi-source search facade - Queries arXiv, OpenAlex, Crossref, and Semantic Scholar concurrently, then deduplicates by DOI, arXiv id, or title in `tools/paper_search.py`.
  - SDK/Client: `ThreadPoolExecutor` over the deterministic clients in `tools/scholar_clients.py`.
  - Contract: Partial provider failures are retained in `source_errors`; output is metadata/evidence rows only and cannot write inside the vault, enforced by `tools/paper_search.py`.

**Local AI and document processing:**
- Ollama - Optional loopback-only OpenReviewer seat posts to `/api/generate` in `tools/openreviewer_seat.py`.
  - SDK/Client: Python `urllib.request`; no Ollama Python package is required by `tools/openreviewer_seat.py`.
  - Auth: None in project code; endpoint and model names come from `RAT_OLLAMA_URL` and `RAT_OPENREVIEWER_MODEL` in `tools/openreviewer_seat.py`.
  - Safety: Non-loopback hosts and URL userinfo are rejected before manuscript content is sent by `tools/openreviewer_seat.py`.
- PaperQA2 - Optional local Python integration for full-text question answering in `tools/fulltext_qa.py`.
  - SDK/Client: Lazy `paperqa` import; it is not installed in the inspected environment, and local PDFs fall back to PyMuPDF through `tools/fulltext_qa.py`.
  - Auth: No provider credential is read directly by this repository's wrapper in `tools/fulltext_qa.py`.
- PyMuPDF - Local PDF extraction and image rendering in `tools/fulltext_qa.py`, `tools/citation_attribution.py`, and `tools/paper_visual_assets.py`.
  - SDK/Client: `fitz` / PyMuPDF; files are local and paths inside the knowledge vault are fenced by `tools/fulltext_qa.py`.

**Harness connectors (declarations, not direct provider clients):**
- Exa, built-in WebSearch, and Context7 are declared as harness capabilities in `resources/resource_registry.yaml` and `resources/backends/mcp_connector_refs.yaml`.
  - SDK/Client: The external host harness owns connector invocation; no Exa or Context7 client import exists in `execute/`, `operate/`, `orchestrator/`, or `tools/`.
  - Auth: No project-held secret is declared for these entries in `resources/backends/mcp_connector_refs.yaml`.
- Notion, Gmail, Google Drive, and Vercel are declared as personal/read-oriented harness connectors in `resources/resource_registry.yaml` and `resources/backends/mcp_connector_refs.yaml`.
  - SDK/Client: Registry-only capability references in `resources/backends/mcp_connector_refs.yaml`; runtime installation/login is outside this repository and must not be inferred from the YAML declaration.
  - Auth: Harness-managed; project policy requires explicit project binding/human approval in `resources/resource_policy.yaml`.
  - Scope: Default policy allows `notion_read`, `mail_read`, `drive_read`, and `deploy_read`; write/draft capabilities are not policy-default in `resources/resource_policy.yaml`.

**GPU compute server:**
- Honor-degree GPU server - Optional SSH/SFTP target for experiment submission, status, result pull, and read-only monitoring in `execute/runner.py` and `server_monitor/monitor.py`.
  - SDK/Client: Paramiko is imported lazily only after a live authorization gate in `execute/runner.py` and `server_monitor/monitor.py`.
  - Auth: Password or SSH-key material is read at connect time from named `RAT_SERVER_*` environment variables by `execute/config.py`; secret values are never stored on `ServerConfig`.
  - Host verification: System/director-pinned known-hosts entries plus `paramiko.RejectPolicy` are mandatory in `execute/runner.py`; an optional direct IP still verifies the canonical SSH hostname.
  - Scheduler: Remote jobs are launched in `tmux`, not Slurm/PBS, through `execute/job.py`; read-only status also inspects `nvidia-smi`, process state, and logs in `server_monitor/train_progress.py`.
  - Current availability: The integration is configured and tested, but real research GPU execution is explicitly not operated according to `PLATFORM-FACTS.md`.

## Data Storage

**Databases:**
- No network database or ORM is present; authoritative machine state is file-backed by `tools/runstore.py`, `tools/ledger.py`, `tools/workspace.py`, and `tools/project_memory.py`.
- SQLite is used only for the local citation-existence cache in `tools/citation_existence.py`.
  - Connection: An injected path or `:memory:` in `tools/citation_existence.py`; the code rejects cache paths inside the vault.
  - Client: Python standard-library `sqlite3` in `tools/citation_existence.py`.
- The separate PhD-Research-OS repository is a Markdown knowledge database, not a SQL service; machine reads are by reference through `tools/recall.py`, and writes are gated through `tools/promote_gate.py` or `tools/document_promotion.py`.

**File Storage:**
- Ephemeral run state lives under `runs/<project>/<run_id>/` as `manifest.yaml`, `ledger.jsonl`, `obs.jsonl`, evidence, inbox artifacts, and director-review Markdown, as implemented by `tools/runstore.py`, `tools/ledger.py`, `tools/obslog.py`, and `operate/spine.py`.
- Per-project machine workspaces live under `projects/<project>/` for pulled results, scripts, figures, and notes, as implemented by `tools/projects.py` and documented in `README.md`.
- Shared resource/audit state uses YAML and JSONL under `resources/` and `workspace/`, managed by `tools/resources.py`, `tools/resource_resolver.py`, and `tools/lease_manager.py`.
- Remote result transfer uses Paramiko SFTP into fenced local run/project directories in `execute/runner.py`; pulls may not escape the result root or land in the vault.
- Validated permanent knowledge is copied into `02-wiki/` only by the director-command paths in `tools/promote.py` and `tools/document_promotion.py`.

**Caching:**
- Citation existence can use the local SQLite cache in `tools/citation_existence.py`; lookup errors remain unknown rather than being cached as absence.
- PaperQA/PDF work may use a caller-supplied scratch cache in `tools/fulltext_qa.py`; cache and source-document paths inside the vault are rejected.
- No Redis, Memcached, CDN, or shared cache service is detected anywhere under `execute/`, `operate/`, `orchestrator/`, `server_monitor/`, or `tools/`.

## Authentication & Identity

**Auth Provider:**
- No end-user accounts, browser sessions, OAuth server, JWT issuance, or identity provider is implemented; all exposed surfaces are local CLIs in `operate/cli.py`, `execute/cli.py`, and `server_monitor/__main__.py`.
- SSH authentication is environment-backed and only consumed at connection time by `execute/config.py` and `execute/runner.py`.
- Scholarly API identity consists of optional provider key/contact variables consumed by `tools/scholar_clients.py`; it is not user authentication.
- External executor identity is cryptographic rather than account-based: `tools/execution_receipt_import.py` verifies Ed25519 signatures against environment-supplied public keys named `RAT_EXECUTOR_TRUST_PUBLIC_KEY_<KEY_ID>`.

**Authorization:**
- Live GPU mutations require a fresh `explicit_director_command` or the legacy exact-run capability `RAT_EXECUTE_AUTHORIZED=<run-id>` in `execute/runner.py`; the ordinary CLI cannot manufacture the explicit flag.
- Read-only server queries require their own gated capability in `server_monitor/monitor.py` and a resource lease resolved through `tools/resource_resolver.py` when project binding is used.
- Resource use is default-deny and least-privilege through `resources/resource_policy.yaml`, `tools/resources.py`, `tools/resource_resolver.py`, and `tools/lease_manager.py`.
- Vault promotion requires an explicit top-level director command (or a narrowly scoped legacy environment capability) plus deterministic evidence re-derivation in `tools/promote_gate.py` and SHA/path checks in `tools/document_promotion.py`.

## Monitoring & Observability

**Error Tracking:**
- No Sentry, Datadog, OpenTelemetry collector, or other external error-tracking service is detected; failures are raised or recorded locally by `orchestrator/engine.py`, `operate/spine.py`, and the individual tools under `tools/`.

**Logs:**
- Per-run observations append to `obs.jsonl` through `tools/obslog.py` and `orchestrator/engine.py`.
- State changes and human gates append hash-linked events to `ledger.jsonl` through `tools/ledger.py` and `operate/spine.py`.
- Resource access and leases append redacted records to `workspace/audit_log.jsonl` and `workspace/lease_registry.jsonl` through `tools/lease_manager.py`; the writer rejects secret-shaped fields.
- Read-only GPU monitoring collects remote `tmux`, process, GPU, filesystem, and training-log summaries through `server_monitor/monitor.py` and `server_monitor/train_progress.py`.

## CI/CD & Deployment

**Hosting:**
- Not detected. `README.md`, `operate/__main__.py`, and `hooks/` define local Python/Node command-line tooling; no Dockerfile, web host configuration, serverless manifest, or process-manager definition exists.
- `connector.vercel` in `resources/resource_registry.yaml` is a harness `deploy_read` capability declaration, not evidence that this repository is deployed to Vercel.

**CI Pipeline:**
- None detected. There is no `.github/workflows/`, GitLab CI, Azure Pipelines, CircleCI, or equivalent configuration in the repository.
- Verification is local via `python -m pytest research_agent_teams/tests/ -q` from the parent directory as documented in `README.md` and `PLATFORM-FACTS.md`.
- The two scripts under `hooks/` are host-harness guards; they are not a CI pipeline and only run when the surrounding tool host registers them.

## Environment Configuration

**Required env vars:**
- Core no-network modes generally need no service credential; path overrides such as `RAT_RUNS_DIR`, `RAT_PROJECTS_ROOT`, `RAT_VAULT_ROOT`, `RAT_WORKSPACE_ROOT`, and `RAT_RESOURCES_ROOT` are optional configuration points used across `tools/`.
- Scholarly quotas/identity: `RAT_S2_API_KEY`, `RAT_OPENALEX_API_KEY`, and `RAT_CONTACT_MAIL` in `tools/scholar_clients.py`.
- Local reviewer: `RAT_OLLAMA_URL` and `RAT_OPENREVIEWER_MODEL` in `tools/openreviewer_seat.py`.
- Live SSH: `RAT_SERVER_HOST`, `RAT_SERVER_PORT`, `RAT_SERVER_USER`, one of `RAT_SERVER_PASSWORD` / `RAT_SERVER_SSH_KEY`, `RAT_SERVER_KNOWN_HOSTS`, and `RAT_REMOTE_WORKDIR` in `execute/config.py`.
- Remote job options: `RAT_SERVER_CONNECT_HOST`, `RAT_REMOTE_PYTHON`, `RAT_REMOTE_CONDA_ENV`, `RAT_REMOTE_CONDA_SH`, `RAT_SCHEDULER`, and `RAT_RESULTS_PULL_DIR` in `execute/config.py`.
- Authorization capabilities: `RAT_EXECUTE_AUTHORIZED`, the server-query authorization read by `server_monitor/monitor.py`, and promotion authorizations read by `tools/promote_gate.py` / `tools/document_promotion.py`; use these only at their documented human gates.
- Model routing: `RAT_RUNTIME_MODEL`, `RAT_RUNTIME_REASONING_EFFORT`, and `RAT_RUNTIME_SERVICE_TIER` in `orchestrator/model_policy.py`.
- Receipt trust: `RAT_EXECUTOR_TRUST_PUBLIC_KEY_<KEY_ID>` in `tools/execution_receipt_import.py`.

**Secrets location:**
- `.env` is present and gitignored by `.gitignore`; its contents were not read during mapping.
- `.env.example` is tracked as a placeholder specification, but its contents were not read during mapping.
- `resources/resource_registry.yaml` and `resources/backends/*.yaml` contain environment-variable names and capability metadata only; loaders in `tools/resources.py` reject non-reference secret material.
- Executor private signing keys must remain outside the repository and reasoning-worker runtime; only public trust material is consumed by `tools/execution_receipt_import.py`.

## Webhooks & Callbacks

**Incoming:**
- None. No HTTP listener, route framework, webhook endpoint, or callback server is implemented under `execute/`, `operate/`, `orchestrator/`, `server_monitor/`, or `tools/`.
- Runtime entry is through local CLI/module commands in `operate/__main__.py`, `execute/__main__.py`, and `server_monitor/__main__.py`.

**Outgoing:**
- HTTPS GET requests go only to the fixed scholarly providers in `tools/scholar_clients.py` during live metadata retrieval.
- HTTP POST requests go only to a validated loopback Ollama endpoint in `tools/openreviewer_seat.py`.
- SSH commands and SFTP transfers go to the director-configured GPU server through `execute/runner.py` and `server_monitor/monitor.py` after authorization.
- Injectable `transport`, `post_transport`, and executor arguments in `tools/scholar_clients.py`, `tools/openreviewer_seat.py`, `tools/fulltext_qa.py`, and `server_monitor/monitor.py` are test seams, not network webhooks.

---

*Integration audit: 2026-07-21*
*Connector registry entries describe governed capabilities; they do not prove the external connector is installed or authenticated in the current host.*
