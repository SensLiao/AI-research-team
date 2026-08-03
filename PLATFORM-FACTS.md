# Platform Facts - Research Agent Teams

This file is the fact source for what the machine can do today. It separates
one-button operated modes, routable/spec-only modes, and work that still waits
for the director's GPU server.

## 0. Machine Inventory (re-derived from code on 2026-08-03)

Every number below is computed from the registries and the file tree, never quoted from memory.

| Part | Count | Source of truth |
|---|---:|---|
| Rostered agents | **163** (6 control + 157 workers) | `orchestrator/roster.yaml` == `agents/*.md` |
| Modes | **26** (12 operated / 14 spec-only) | `orchestrator/mode_registry.yaml`; operated mirrored by `operate/modes/__init__.py::REGISTRY` |
| Stage graph | **7** stages | `orchestrator/graph.yaml`: DISCOVER IDEATE DESIGN EXECUTE ANALYZE VERIFY REPORT |
| Deterministic tools | **140** modules | `tools/*.py` (137 + `outcome_recipes` + `vendor_upstream_skills` + `worker_census`, 2026-08-04) |
| Artifact schemas | **167** JSON (167/167 parse) | `schemas/*.json` |
| Human gates | **5** | `gates/` — idea-bet, promote-to-vault, venue-pick, venue-decide, aers-reference-approve |
| Enforcement hooks | **2** | `hooks/` — artifact-contract-enforcer, permission-scope-guard |
| Domain profiles | **7** | `profiles/*.yaml` (medical-segmentation is one profile, never a hardcoded domain) |
| `operate` subcommands | **32** | `operate/cli.py` — counted from the built argparse, not by hand; the previous **31** here was stale |
| `workbench` verbs | **10** | `workbench/cli.py` — read-only navigation; only `reindex` writes, and only inside `.workbench/` + one generated `PROJECT-HOME.md` per workspace |
| Outcome recipes | **6** | `orchestrator/outcome_recipes.yaml` — the "你想得到什么" menu above the mode table; a test pins that all 12 operated modes stay reachable from it |
| Vendored upstream text | **8** sources / **358** skill bundles | `vendor/upstream-research-skills/MANIFEST.json` — third-party markdown, READ-ONLY reference. Not capability, not indexed, structurally unrunnable (markdown + license notices only). `drawio-scientific-illustrator` excluded on safety grounds |
| Seat accounting | **168** seat-slots declared / **153** recipe-dispatched / **15** council-only | `tools/worker_census.py` — `agent_subset` is the roster CEILING, not a dispatch promise; 0 orphan seats, and only `deep_research` has a real depth knob (1/12 modes can be scaled) |
| Slash commands / skills | **19 / 2** | `.claude/commands/`, `.claude/skills/` |
| Test files | **225** | `tests/` (217 + 4 workbench + outcome-recipes + vendor + worker-census, 2026-08-04) |

Worker roster by stage group: discover 38 · gap_hunting 10 · ideate 7 · design 24 · execute 20 ·
analyze 24 · verify 29 · report 5.

### Operated-mode contract table (authoritative)

`agent_subset` = the roster names a mode may use. `hops` = `budget.max_agent_hops`, the real ceiling on
dispatched LLM workers. Neither is a concurrency number.

| Mode | stage_path | subset | hops | gate_level | product_version |
|---|---|---:|---:|---|---|
| `ingest_paper` | DISCOVER→REPORT | 2 | 4 | record_only | `ingest-paper/v1` |
| `read_paper_deep` | DISCOVER→REPORT | 20 | 20 | record_only | `paper-reading/v3` |
| `evidence_review` | DISCOVER→REPORT | 8 | 6 | director_signoff | `evidence-brief/v2` |
| `evidence_deep` | DISCOVER→REPORT | 12 | 10 | director_signoff | `evidence-deep/v2` |
| `deep_research` | DISCOVER→REPORT | 14 | 12 | record_only | `research-brief/v2` |
| `gap_breadth` | DISCOVER→REPORT | 10 | 10 | record_only | `gap-dossier/v1` |
| `new_direction` | DISCOVER→IDEATE→REPORT | 13 | 10 | director_signoff @ IDEATE | `idea-investment-memo/v2` |
| `deep_ideation` | DISCOVER→IDEATE→REPORT | 18 | 9 | director_signoff @ IDEATE | `idea-investment-memo/v2` |
| `full_rigor_minimal` | DESIGN→EXECUTE→ANALYZE→VERIFY→REPORT | 35 | 24 | director_signoff | `full-rigor/v2` |
| `venue_readiness` | VERIFY→REPORT | 11 | 6 | director_signoff | `venue-readiness/v2` |
| `manuscript_authoring` | DISCOVER→DESIGN→ANALYZE→VERIFY→REPORT | 13 | 12 | record_only | `manuscript-authoring/v1` |
| `manuscript_review` | VERIFY→REPORT | 12 | 12 | record_only | `manuscript-review/v1` |

## 1. Three Honest Buckets

### Bucket A - One-Button Operated, No GPU Required

The operated surface is exactly the modes present in `operate/modes/__init__.py::REGISTRY`
and mirrored by `orchestrator/mode_registry.yaml` with `operated: true`.

There are currently 12 operated modes:

| Mode | Shape | Honest use |
|---|---|---|
| `new_direction` | `DISCOVER -> IDEATE -> REPORT` | Eight-seat grounding/proposal/ranking/collision/planning path. Current runs require an `idea-investment-memo/v2`; missing prior-art coverage is `UNVERIFIED`, never silently clear. Human product: `director-review/ideas/idea-bet-menu.md`. |
| `deep_ideation` | `DISCOVER -> IDEATE -> REPORT` | Nine-seat extension with formalization and cross-domain mechanism/analogy work, followed by the same independent investment pipeline and `/idea-bet` product. |
| `gap_breadth` | `DISCOVER -> REPORT` | Five blind hunters, then gap prosecutor, mechanism synthesizer, and quality auditor. A gap can be `CLOSED` only from hash-bound exact full-text scope/result spans. |
| `evidence_review` | `DISCOVER -> REPORT` | Six workers: source set, methodology-derived source quality and claims, semantic search moderator, exact-span linker, and independent citation auditor. |
| `evidence_deep` | `DISCOVER -> REPORT` | Ten workers in a seven-wave sparse DAG add contradiction, dataset, staleness, and landscape analysis to strict source methodology, search trace, and citation attribution. Human product: `director-review/evidence/evidence-deep-brief.md`. |
| `deep_research` | `DISCOVER -> REPORT` | Twelve workers in eight waves: frozen source set, source-quality audit, four independent perspectives, semantic search moderation, claims/spans, parallel independent citation/contradiction audits, and synthesis. Human product: `director-review/research/research-brief.md`. |
| `venue_readiness` | `VERIFY -> REPORT` | Six seats: venue profile, rubric/precommit freeze, three blind reviewers, and post-hoc meta-review. Verdict is advisory; venue gates remain human. |
| `full_rigor_minimal` | `DESIGN -> EXECUTE -> ANALYZE -> VERIFY -> REPORT` | Sixteen seats across DESIGN 5, EXECUTE 3, ANALYZE 4, VERIFY 4 when real results exist. Real metrics require a non-LLM Ed25519 executor receipt and receipt-bound raw results. Scripts-only runs use eight scientific seats, then deterministically skip result-only ANALYZE/VERIFY panels. |
| `ingest_paper` | `DISCOVER -> REPORT` | Two workers: quick extractor plus independent source/claim verifier. No local reopenable snapshot means `NEEDS_DEEP_READ`; promotion requires a later explicit top-level user `/promote-to-vault` command. |
| `read_paper_deep` | `DISCOVER -> REPORT` | Twenty workers: blind second reader first, primary paper dissection, exact citation audit, visual/table/math/reproducibility audits, reconciliation, quality audit, and Markdown writer. Human product: `director-review/papers/<paper>.md`. The 2026-07-01 Skeleton Recall Loss run proves historical PDF-grounded reading, not operation of this upgraded panel. |
| `manuscript_authoring` | `DISCOVER -> DESIGN -> ANALYZE -> VERIFY -> REPORT` | Local-coverage-first AI manuscript authoring: freeze a paper contract and design tokens, dispatch a sparse adaptive author/audit DAG, integrate one canonical LaTeX tree, and render a Markdown-first director packet. Generic scholarly search is forbidden until a schema-valid local coverage artifact names a deficit and freezes a targeted metadata-only `paper_search.search_many` plan. A build receipt may truthfully be `TOOLCHAIN_MISSING`; no submission or vault write occurs. |
| `manuscript_review` | `VERIFY -> REPORT` | Separate, frozen-input capability review: six blind-scope seats, deterministic reconciliation, and review/rebuttal advice in a distinct director packet. Without a signed external scheduler receipt verifier, the useful output remains explicitly advisory (`submission_ready: false`) rather than claiming external independence; the review run cannot mutate authoring, submit, or promote. |

Since 2026-07-11, paper-reading repair is incremental: immutable hash-linked supplements preserve the
original bundle and refresh only named data consumers. Formatting-only normalization uses zero worker
hops. Daily delivery states are `USABLE`, `USABLE_WITH_CAVEATS`, `NEEDS_SUPPLEMENT`, and `BLOCK`.
Readable Markdown is emitted before presentation checks; length, headings, keywords, and non-critical
coverage are advisories. Initial panel hops and supplement hops have independent budgets. Only
scientific-integrity, execution-truth, permission, or irrecoverable-input failures remain fail-closed;
strict completeness is enforced again at `/promote-to-vault`.

The paper panel now executes in 12 explicit dependency waves instead of 20 accidental serial waves.
Planner-declared, scientifically inapplicable specialists are replaced by deterministic not-applicable
bundles, never by invented analysis; uncertain cases still run. Stable note/structure/claim facts are
materialized once in `inbox/shared-paper-representation.json` for downstream reuse. The blind second
reader, independent citation auditor, reconciliation, and scientific truth checks remain mandatory.

Every operated run remains north-star drift-gated, scope-fenced, schema-validated,
and recorded in the tamper-evident run-store. The database is not written except
through `/promote-to-vault`.

As of 2026-07-10, completed operated runs are also Markdown-first at the director boundary:
REPORT must expose `director-review/00-REVIEW-PACKET.md` as the primary human entry. Idea-bet
runs also expose `director-review/ideas/idea-bet-menu.md` at the IDEATE human gate, before
any model or machine can record a bet. JSON artifacts remain the validated evidence/archive layer.
Existing runs can be rendered with `python -m research_agent_teams.operate packet --run-id <run_id>`.

### Single-entry research capability overlays (2026-07-31)

`research-orchestrator` is still the only research entry. A deterministic UTF-8 selector at
`tools/research_capability_router.py` can now map a Chinese or English request to one existing mode and
2–5 internally curated quality overlays. `operate begin --mode auto ...` uses that route; an explicit mode
remains the manual override.

The selected `capability_overlay_plan` is frozen into the task frame and therefore covered by the
existing task-frame hash pin. `panel_scheduler` injects only stage-relevant internal guidance into an
already-authorized worker prompt. Overlays cannot add workers, alter stage/gate/budget contracts, write
the vault, enable network access, or execute an external repository. The true one-button boundary remains
`operate/modes/__init__.py::REGISTRY`; an auto-selected spec-only mode is still refused by the operate
layer rather than silently relabelled or replaced.

The external repository review is selective: hypothesis/prediction, unit-of-analysis/power,
results-to-claim, blind handoff, submission freshness, DICOM audit, figure QA, offline diagram, methods,
and review rubrics were abstracted with fixed source commits. Whole-repo installers, hooks, MCP, auto
update, live CDP, external image APIs, second knowledge-base writes, and unknown-license code copying are
not in the runtime path. Focused router/schema/scheduler/wiring/Stage-B-harness regressions passed
`134` tests on 2026-07-31; this proves routing and contract behavior, not that every external tool has
been operated.

The evaluation-only Stage-B harness is implemented at
`tools/research_capability_ab_eval.py`, with a frozen 20-request holdout manifest and strict condition /
judge/runtime-policy schemas under `_design/review/` and `schemas/`. Fresh prepare requires one explicit
global author runtime policy and binds its complete model-policy/model/service/reasoning/agent/budget fields
into all 40 candidate challenge hashes. Seal accepts only hash-bound author outputs whose signed receipts
match that policy and whose provider-observed model/tier/effort are consistent across the full 40 calls,
not merely within each X/Y pair. The harness then deterministically reconciles three mutually blind judge
sheets using the pre-registered paired gate.
No real Stage-B author or judge run has been performed. The current author runtime exposes optional
deployment bindings but no independently verifiable per-call input/output token and elapsed-time receipt,
so the fail-closed seal cannot yet establish A/B runtime parity. The accurate state is
`HARNESS_IMPLEMENTED / HOLDOUT_FROZEN / GLOBAL_AUTHOR_RUNTIME_POLICY_CONTRACT_IMPLEMENTED /
RUNTIME_USAGE_EXPORT_BLOCKED /
AUTHORS_AND_JUDGES_NOT_RUN`, never a quality-improvement claim. Do not fabricate or estimate usage.

### T4 external-skill and native multi-agent validation (2026-08-01)

The external research-skill source lock now covers 9 pinned repositories, 359 visible `SKILL.md` files,
and 45 selected source-file SHA-256 receipts. The Phase-1 integration registry contains 25 bounded
decisions: 20 implemented local contracts, 4 planned adapters, and 1 rejected live-control route. No
upstream installer, hook, MCP server, autonomous loop, or external repository implementation was executed.

The optional mechanism council is a seven-role functional superset: five required scientific perspectives,
one supplemental engineering contributor, and one compiler. It must not be described as an exact six-role
council. A design-only Scribble–M0 example produced hash-bound work orders/completions for all seven council
roles, an independent challenger, three precommitted blind judges, fail-closed repair recovery, and two
targeted re-reviews. The initial panel replicated four substantive defects 3/3; the first re-review preserved
a `FAIL` with two partial repairs; the minimal R3 repair then received an independent targeted `PASS` with
4/4 repairs closed, 6/6 canonical/truth regressions true, and no fatal defects. Platform thread limits meant
the final independent auditor had performed a non-authoring preliminary check before formal authorization;
the review discloses this and is not represented as a new blind round.

This validates local dispatch and design-review contracts on one case only. The example remains
`DESIGN_ONLY / NON_CITABLE / NO RESULTS`; its CPU dry-run is `NOT_SCIENTIFIC_EVIDENCE` and
`PREFLIGHT_BLOCKED`. It did not query either GPU server, submit a job, alter the PET/CT canonical, or promote
anything to the vault. The registered resources remain 2 × 48-GiB RTX A6000 and RTX 3090 + GTX 1080 Ti;
their current tasks are `UNKNOWN` until a fresh live query. The secondary-server issue is director-reported
resolved but not live re-verified. `server_monitor/query_contract.json` freezes eight read-only check classes,
and `query_status` never grants `submit_job`.

Evidence and reading order are in
`_design/review/t4-research-agent-team-upgrade-2026-08-01.md` and
`projects/t4-scribble-m0-mechanism-eval/README.md`.
The final repository-wide verification for this checkout was
`3914 passed, 4 skipped in 462.02s` with exit code 0; this proves the local contracts and regressions,
not a scientific result or real GPU operation.

### Bucket B - Routable / Spec-Only, Not One-Button Operated

These modes are defined in the registry and route cleanly, but they do not yet
have an `operate/modes/*.py` recipe. Do not present them as push-button operated.

`check_run`, `gap_scan`, `design_experiment`, `design_experiment_minimal`,
`power_analysis_review`, `verify_result`, `full_new_direction`, `m2_accept`,
`ideate_ring`, `debug_failed_run`, `tree_explore`, `repo_code_audit`,
`analysis_audit_panel`, `aers_enhanced_research_pack`.

The coverage-closure modes exist so every non-control agent is reachable through
the router:

| Mode | Covers |
|---|---|
| `power_analysis_review` | Statistical power/design adequacy audit. |
| `repo_code_audit` | Repo inspection, patch planning, implementation, tests, sandbox/repro support. |
| `analysis_audit_panel` | Result diagnostics, fairness/variance/compliance/visualization/claim-strength audits. |
| `aers_enhanced_research_pack` | AERS-informed SOP, literature-search, data-wrangling, reproducibility, benchmark, venue, bibliography, and manuscript polish pack; routable only, not one-button operated. |

### Bucket C - Waits For The GPU Server

Real GPU training/inference still waits for the director's server credentials
and resource binding. `full_rigor_minimal` can emit scripts and planned/provisional
records, but without a real execution journal the records stay structurally honest:
run records remain `planned` and metrics stay empty.

GPU experiment execution is **not operated** on real research today; a script,
design, or fixture receipt is never presented as a completed GPU job.

The reading line is no longer "never operated": as of 2026-07-01, one real
local-PDF `read_paper_deep` run completed against the Skeleton Recall Loss paper.
That proves PDF-grounded reading, not GPU experiment execution and not vault-grade
promotion.

As of 2026-07-10, `read_paper_deep` has also been upgraded from a merged
single-worker read to a true staged 20-worker A-core paper dissect panel. The
director-facing output is a Markdown paper card under `director-review/papers/`;
JSON artifacts remain the machine evidence layer.

## 2. Model-Agnostic Runtime Contract

The historical names `opus` and `sonnet` remain compatibility workload tiers,
not literal provider/model selections. Scientific roles declare capabilities:

```text
reasoning_strength: strong | frontier
long_context: true | false
tool_use: true | false
provider: any
```

Deployment may optionally bind `RAT_RUNTIME_MODEL`,
`RAT_RUNTIME_REASONING_EFFORT`, and `RAT_RUNTIME_SERVICE_TIER`. Without those
bindings, worker specs contain no concrete runtime model request.
`--model-policy max_quality` requests the strongest logical capability profile;
deterministic workers remain `model: none`.

## 3. Connectivity Contract

Server transport has a two-name boundary when local DNS is overridden:

```text
RAT_SERVER_CONNECT_HOST = literal IP used only for the TCP socket
RAT_SERVER_HOST         = canonical SSH identity used for pinned host-key verification
```

The direct endpoint is omitted from normal config summaries. Paramiko still receives the canonical
hostname and `RejectPolicy`; an unknown/mismatched canonical key remains a hard refusal.

The machine has 163 rostered agents (6 control/infrastructure + 157 scientific workers):

```text
163 total
  6 control / infrastructure agents
  157 non-control research worker agents
```

The current contract is:

```text
every non-control agent
  -> listed in graph.yaml allowed_agents
  -> listed in at least one mode_registry.yaml agent_subset
  -> validated by orchestrator/agent_connectivity.py
  -> pinned by tests/test_agent_connectivity.py
```

Control agents are intentionally not ordinary mode workers:
`research-orchestrator`, `state-tracker`, `artifact-contract-enforcer`,
`permission-scope-guard`, `budget-and-stop-controller`, `conflict-resolver`.

## 4. Human Gates

The model never self-decides these:

- `/idea-bet`: choose or reject a research direction.
- `/venue-pick`: choose a target venue.
- `/venue-decide`: submit, iterate, change method, pivot, or re-review.
- `/promote-to-vault`: only a top-level user's explicit source-command invocation lets the primary assistant promote either (a) a vetted, frozen experiment result through the audit-derived result lane, or (b) a director-reviewed final Markdown copy through the SHA-bound document-admission lane. Workers, modes, schedules, and subagents cannot invoke it. The latter never creates a result, `can-cite-thesis`, or an experimental claim.
- Live server mutation (upload/submit): the primary assistant must first present the exact remote path,
  file/command scope and non-goals, then ask the director in chat. A fresh confirmation is passed through
  the execution library as `explicit-director-command` and recorded in the live receipt. The director is
  not asked to set PowerShell variables. The ordinary CLI keeps the exact per-run
  `RAT_EXECUTE_AUTHORIZED` capability only for legacy unattended use and exposes no confirmation-bypass
  flag; workers, modes and schedules always default-deny.

## 5. Boundary With The Vault

`research_agent_teams/` is the machine: messy scratch, runs, tools, control plane.
`AI agent database/PhD-Research-OS/` is the database: validated knowledge only.

The seam is narrow:

- Read by reference through recall.
- Write only through `/promote-to-vault`.
- Final human-readable Markdown is copied into typed vault pages through the director-reviewed document-admission lane before scratch cleanup; the vault never depends on a future-surviving `runs/` path for readable research knowledge.
- Never place secrets in the repo, git, chat, or logs.

## 5.1 Multichannel Scholarly Retrieval And Encoding

`pre-search` accepts a repeatable `--query` plan. Each technical subquery fans out concurrently to
arXiv, OpenAlex, Crossref, and Semantic Scholar, then passes a deterministic multilingual title
relevance filter before metadata candidates reach a worker. Local hash-bound PDFs/full-text contexts
remain the stronger reading channel. A `lit-scout` may use agent Web Search when a named method is
missing or API recall is empty/off-topic, but only original papers, official publisher/project pages,
or authors' official repositories may enter the common existence/citation gates. Search snippets and
aggregators are leads, never evidence.

The CLI and direct paper-search entry point force UTF-8 for process I/O and child commands; scholarly
client URL encoding and JSON writes use explicit strict UTF-8. On Windows, manual inspection must use
`Get-Content -Encoding UTF8`: PowerShell's display decoder is not evidence that stored UTF-8 bytes are
corrupt. Metadata candidates still carry `claim_support: none` until a full-text worker and independent
auditors establish support.

Network failures raised while reading an HTTP response body are normalized into the same auditable
scholarly-lookup error contract as connection failures, so one slow provider cannot crash an otherwise
valid multi-provider search. Source-quality workers judge `applicability` against the full task-frame
research question: a paper that directly supports only one component of a bundled question remains
partial/indirect. The strong-source gate is never cleared by relabeling a convenient subclaim; split the
work into a new atomic evidence review instead.

## 6. Quick Commands

| Goal | Command surface | Operate layer |
|---|---|---|
| **Plan card BEFORE any work** | — | `brief --request "…" --project <slug>` (read-only: scans the knowledge base, projects, recent runs and compute; proposes routes; names the human gates; starts nothing) |
| **Progress report AFTER a run** | — | `report --run-id <id>` (read-only: what came out, how far it got, what is openable, what cannot be claimed, whose decision is next) |
| Start or inspect workspace | `/start-research` | `dashboard` / `index` |
| Run a full operated mode | `/run-mode` | `begin -> pre-search/fulltext-pre -> repeat worker waves until stage complete -> run-dets -> commit -> human gate/report` |
| Run one stage/skill/bridge | `/run-stage`, `/run-skill`, `/run-bridge` | matching operate verb with dependency checks |
| Project lifecycle | `/project-*` | `project-init`, `project-archive`, `project-restore`, `project-soft-delete`, guarded `project-purge` |
| Resource pool | `/resources`, `/resource-bind` | references only; no secret values |
| Read-only server status | `server-query` | live SSH only when authorized |

## 7. Verification

Run the self-tests **with `research_agent_teams/` as the working directory** — this is not optional:

```powershell
cd research_agent_teams
python -m pytest tests/ -q
```

Running `python -m pytest research_agent_teams/tests/ -q` from the parent directory fails with three
collection errors (`test_manuscript_schema_contracts.py`, `test_operate_manuscript_authoring.py`,
`test_operate_manuscript_review.py` use `from tests....` absolute imports, which need `tests` importable
at top level). That is a wrong cwd, not a red suite.

Current Phase 01 release verification on 2026-07-22:
the current full-suite JUnit plus matching before/after source SHA-256 snapshots.

The evidence bundle additionally contains a real Windows `COMPILED` PDF receipt,
the pinned immutable Docker `linux/amd64` targeted suite, AI evaluation, security,
and director-route/completion gates. These prove the concrete operated recipes and
their boundaries; they do not claim a real research-paper run, GPU execution,
autonomous submission, or externally verified independent review.

Deterministic re-verification on 2026-08-03 (this checkout, all read-only):

```text
pytest (cwd = research_agent_teams/): 3914 passed, 4 skipped, exit 0, 440s
JSON schemas parsed:                  167/167
rat_eval_harness --no-manual:         4/4 scenarios pass, 13/13 required machine checks, 0 manual open
operate scoreboard --no-manual:       overall_status = machine_clean
  capability:        26 modes, 12 operated, 14 spec-only, 7 execute-stage, 4 server-gated,
                     operate_registry_drift = 0
  business outputs:  31 completed operated runs -> 7 PASS / 12 advisory / 12 FAIL
                     12/12 FAIL are legacy (pre-product-contract); 0 failures under the current contract
  run store:         45 runs (31 done, 7 running, 1 awaiting_director, 6 failed), 0 invalid manifests
  vault_write: false        external_skill_execution: false
```

The 12 legacy FAILs are intentional historical debt, not a failure of the current code: they are listed by
name in `legacy_failure_run_ids` rather than hidden, and the only way to clear them is a scientific rerun —
the director's call. Old JSON and generic report notes are never auto-promoted into current scientific
products. `machine_clean` means the machine's own contracts are green; it is **not** a scientific claim.

Additional real-paper smoke run (2026-07-01): `read-skeleton-recall-20260701`
under project `iac-cbct-seg`, with 70 local PDF contexts extracted by
`fulltext-pre`, 11 DISCOVER artifacts generated, citation/existence/drift gates
passing, and REPORT committed.
