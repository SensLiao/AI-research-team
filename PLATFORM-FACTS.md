# Platform Facts - Research Agent Teams

**Scientific figures, scoped update 2026-09-05:** `tools/scientific_figure.py` and `tools/journal_render.py` are implemented offline adapters. The authoring path consumes a compact scientific figure plan and v2 realized assets; it can reuse unchanged, hash-checked figures. Journal questions/default recommendations, the three reused agent roles, actual rule provenance and custom-TeX limits are documented in `docs/SCIENTIFIC-FIGURES.md`. The buckwheat run `runs/tartary-buckwheat-germplasm-review/figure-upgrade-20260905/` contains three actual reviewed figures, an exercised automatic/reuse path, and **196 passing scoped tests**. This row is a feature-specific verification, not a recount or a full-suite green claim for the historical inventory below.

This file is the fact source for what the machine can do today. It separates
one-button operated modes, routable/spec-only modes, and work that still waits
for the director's GPU server.

## 0. Machine Inventory (re-derived from code on 2026-09-06)

Every number below is computed from the registries and the file tree, never quoted from memory.

| Part | Count | Source of truth |
|---|---:|---|
| Rostered agents | **172** (7 control + 165 workers) | `orchestrator/roster.yaml` == `agents/*.md` |
| Modes | **27** (24 operated / 3 spec-only) | `orchestrator/mode_registry.yaml`; operated mirrored by `operate/modes/__init__.py::REGISTRY` |
| Stage graph | **7** stages | `orchestrator/graph.yaml`: DISCOVER IDEATE DESIGN EXECUTE ANALYZE VERIFY REPORT |
| Deterministic tools | **163** modules | `tools/*.py` (re-derived 2026-09-05; `search_funnel.py` added) |
| Artifact schemas | **181** JSON | `schemas/*.json`; parse/contract validity is test-derived |
| Human gates | **5** | `gates/` — idea-bet, promote-to-vault, venue-pick, venue-decide, aers-reference-approve |
| Enforcement hooks | **2** | `hooks/` — artifact-contract-enforcer, permission-scope-guard |
| Domain profiles | **7** | `profiles/*.yaml` (medical-segmentation is one profile, never a hardcoded domain) |
| `operate` subcommands | **33** | `operate/cli.py` — counted from the built argparse, not by hand |
| `workbench` verbs | **14** | `workbench/cli.py` — read-only navigation; only `reindex` writes, and only inside `.workbench/` + one generated `PROJECT-HOME.md` per workspace. Three added 2026-08-04, all index-free: **`gates`** 现在该按哪个命令 + 每个导演决定点的触发条件（`/gates` 也可以）· **`map`** 研究链条断在哪一环（哪个点子还没有实验）· **`capabilities`** 8 个来源 358 份上游 skill 原文（只读原文，**不是能力**） |
| Outcome recipes | **12** | `orchestrator/outcome_recipes.yaml` — the "你想得到什么" menu above the mode table; a test pins that EVERY operated mode stays reachable from it |
| Vendored upstream text | **8** sources / **358** skill bundles | `vendor/upstream-research-skills/MANIFEST.json` — third-party markdown, READ-ONLY reference. Not capability, not indexed, structurally unrunnable (markdown + license notices only). `drawio-scientific-illustrator` excluded on safety grounds |
| Seat accounting | **260** seat-slots declared / **254** recipe-dispatched / **6** council-only | `tools/worker_census.py teams --json` — `agent_subset` is the roster CEILING, not a dispatch promise; 0 orphan seats, and only `deep_research` has a real depth knob (1/24 modes can be scaled) |
| Governance usage (measured) | **6/24** modes · **20/172** seats seen in **23** retained runs | `tools/governance_census.py --json` — only the currently retained `runs/` tree is measurable; REACHABLE and EXERCISED are different axes |
| Recorded example | **86** files tracked (of 87 on disk), replayable | `projects/t4-scribble-m0-mechanism-eval/` — the only copy of the three honesty records; now tracked (was gitignored while 8 tests required it). The untracked 87th is the generated `PROJECT-HOME.md`. `tools/example_replay.py` re-derives it: 22 checks, 0 executions |
| Slash commands / skills | **20 Claude commands / 2 Claude skills / 19 Codex skills** | `.claude/commands/`, `.claude/skills/`, `.agents/skills/` |
| Test files | **259** | `tests/machine/test_*.py` — re-derived 2026-09-05, never typed from memory (pinned by `tests/machine/test_governance_census.py`; the row has drifted before) |

Worker roster by stage group (census 2026-09-06): discover 44 · gap_hunting 10 · ideate 13 · design 24 ·
execute 20 · analyze 24 · verify 25 · report 5 · control 7.

### Selected operated-mode contract rows

`agent_subset` = the roster names a mode may use. `hops` = `budget.max_agent_hops`, the real ceiling on
dispatched LLM workers. Neither is a concurrency number.

| Mode | stage_path | subset | hops | gate_level | product_version |
|---|---|---:|---:|---|---|
| `ingest_paper` | DISCOVER→REPORT | 2 | 4 | record_only | `ingest-paper/v1` |
| `read_paper_deep` | DISCOVER→REPORT | 21 | 20 | record_only | `paper-reading/v3` |
| `evidence_review` | DISCOVER→REPORT | 8 | 6 | director_signoff | `evidence-brief/v2` |
| `evidence_deep` | DISCOVER→REPORT | 12 | 10 | director_signoff | `evidence-deep/v2` |
| `deep_research` | DISCOVER→REPORT | 18 | 20 | record_only | `research-brief/v2` |
| `gap_breadth` | DISCOVER→REPORT | 10 | 10 | record_only | `gap-dossier/v1` |
| `new_direction` | DISCOVER→IDEATE→REPORT | 15 | 10 | director_signoff @ IDEATE | `idea-investment-memo/v2` |
| `deep_ideation` | DISCOVER→IDEATE→REPORT | 25 | unbounded initial panel; bounded repair | director_signoff @ IDEATE | `idea-investment-memo/v2` |
| `full_rigor_minimal` | DESIGN→EXECUTE→ANALYZE→VERIFY→REPORT | 35 | 24 | director_signoff | `full-rigor/v2` |
| `venue_readiness` | VERIFY→REPORT | 11 | 6 | director_signoff | `venue-readiness/v2` |
| `manuscript_authoring` | DISCOVER→DESIGN→ANALYZE→VERIFY→REPORT | 13 | 12 | record_only | `manuscript-authoring/v1` |
| `manuscript_review` | VERIFY→REPORT | 12 | 12 | record_only | `manuscript-review/v1` |

## 1. Three Honest Buckets

### Bucket A - One-Button Operated, No GPU Required

The operated surface is exactly the modes present in `operate/modes/__init__.py::REGISTRY`
and mirrored by `orchestrator/mode_registry.yaml` with `operated: true`.

There are currently 23 operated modes. Wave 2 (2026-08-04) added nine — `gap_scan`,
`full_new_direction`, `design_experiment`, `power_analysis_review`, `m2_accept`,
`analysis_audit_panel`, `verify_result`, `check_run`, `repo_code_audit` — all built on
`operate/modes/_panel_recipe.py`, which compiles each mode's registry-declared worker
pipeline and director-Markdown contract onto the same spine wave 1 uses. Nothing that was
manual became automatic: the five human gates, GPU submission and code-patch application
are unchanged, and the wave-2 recipes stop AT those boundaries.

Wave-1 modes:

| Mode | Shape | Honest use |
|---|---|---|
| `new_direction` | `DISCOVER -> IDEATE -> REPORT` | Registry-bounded grounding/proposal/ranking/collision/planning path. Current runs require an `idea-investment-memo/v2`; missing prior-art coverage is `UNVERIFIED`, never silently clear. Human product: `director-review/ideas/idea-bet-menu.md`. |
| `deep_ideation` | `DISCOVER -> IDEATE -> REPORT` | Multi-view formalization, mechanism, analogy, saturation, merger, collision, and experiment path. The initial panel is not hop-capped; repair remains bounded and targeted. It ends at the same human `/idea-bet` boundary. |
| `gap_breadth` | `DISCOVER -> REPORT` | Five blind hunters, then gap prosecutor, mechanism synthesizer, and quality auditor. A gap can be `CLOSED` only from hash-bound exact full-text scope/result spans. |
| `evidence_review` | `DISCOVER -> REPORT` | Six workers: source set, methodology-derived source quality and claims, semantic search moderator, exact-span linker, and independent citation auditor. |
| `evidence_deep` | `DISCOVER -> REPORT` | Ten workers in a seven-wave sparse DAG add contradiction, dataset, staleness, and landscape analysis to strict source methodology, search trace, and citation attribution. Human product: `director-review/evidence/evidence-deep-brief.md`. |
| `deep_research` | `DISCOVER -> REPORT` | Sixteen explicitly dispatched research/review seats in ten waves; the declared subset also includes the shared `evidence-verifier` and `citation-integrity-auditor` gate roles. The path freezes sources, gathers four perspectives, runs the evidence/citation chain, uses one dossier author, three mutually blind reviewers, and an H-Max chair. CRITICAL/MAJOR targets only the author; all reviewers/chair refresh blind on the revised hash. Human product: `director-review/research/research-brief.md`. |
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
and recorded in the append-only run-store (hash-chained fields are still written; chain
verification is no longer re-checked before every append — 2026-08-07 de-governance).
The database is not written except through `/promote-to-vault`.

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
into all 40 candidate challenge hashes. Seal accepts only author outputs whose receipts bind to that
policy's challenge (schema, path, and challenge-binding checked; ed25519 attestation and file-content
hash comparison are no longer cryptographically re-verified — 2026-08-07 de-governance) and whose
provider-observed model/tier/effort are consistent across the full 40 calls, not merely within each
X/Y pair. The harness then deterministically reconciles three mutually blind judge
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
targeted re-reviews. (2026-08-07 de-governance: work orders/completions still carry hash fields, but content
hash comparison is no longer re-verified for this personal single-operator tool — schema conformance, path
safety, referential integrity, and temporal ordering are what fail-closes now; see native_dispatch_trace.py.) The initial panel replicated four substantive defects 3/3; the first re-review preserved
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

The live catalog currently has exactly three spec-only modes: `debug_failed_run`,
`design_experiment_minimal`, and `tree_explore`. They route cleanly but have no
registered `operate/modes/*.py` recipe, so they must not be presented as push-button
operated. All other current modes, including the former coverage-closure modes
`power_analysis_review`, `repo_code_audit`, `analysis_audit_panel`, and
`aers_enhanced_research_pack`, are now in the operated registry.

Do not maintain another hand-written mode inventory here. Recompute the current
23 operated / 3 spec-only split with `python -m research_agent_teams.operate brief
--request "capability inventory" --json`; `operate.modes.REGISTRY` and
`orchestrator/mode_registry.yaml` are the machine truth.

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

The machine has 175 rostered agents (6 control/infrastructure + 169 scientific workers):

```text
175 total
  6 control / infrastructure agents
  169 non-control research worker agents
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
- `/aers-reference-approve`: approve or reject a staged AERS candidate as reference-only run-inbox
  input. It never grants external skill execution, project approval, job submission, or vault write.

Live server mutation is a separate execution authorization, not one of the five research lifecycle/reference
gates. For upload/submit, the primary assistant must first present the exact remote path,
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

`tools/search_funnel.py` (added 2026-09-05; SciPhi AgentSearch retrieval pattern, Apache-2.0 source,
clean-room re-implementation, no package installed because the hosted service was unreachable) layers
four stages over the same providers: per-source broad recall, Reciprocal Rank Fusion of each provider's
own ranking (`paper_search.search` now returns `channel_rankings`), best-passage reranking from one
batched OpenAlex abstract request (or local full text), and an authority blend (0.9 relevance +
0.1 log-citations/recency). `--depth/--breadth` add a recursive related-query expansion whose stop is an
expansion stop, never a saturation verdict; the evidence-search-moderator still owns
`evidence-search-trace/v1`. Scores and the ≤ 400-char `text` snippet are triage only and never enter
evidence rows. Director decision 2026-09-05: `operate pre-search` runs the funnel by default in every
DISCOVER-entry mode (depth 1) and with one round of related queries in `deep_research` (depth 2,
breadth 2); `search-results.json` gains `funnel_rank` / `funnel_score`, funnel-only records as
metadata rows, `related_queries` and a `funnel` summary, while `search-funnel.json` holds the
snippets and per-stage counts. `--funnel-depth`, `--funnel-breadth`, `--no-funnel` override it; a
funnel failure is recorded as `funnel.status: failed` and never blocks the facade bundle.

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
python -m pytest tests/ -q
```

The suite was consolidated into the workspace `tests/` home on 2026-08-13 (director's order):
`tests/machine/` is the machine's core harness, `tests/projects/petct-residual-correction/` the project
suite, `tests/database/` the vault gate tests. `tests/__init__.py` + per-home `conftest.py` files wire
the paths; run from the workspace root. Any other cwd is a wrong cwd, not a red suite.

### Historical verification snapshot (2026-07-22 through 2026-08-03; not current truth)

The following block is retained only as historical release evidence. It must not be used for current
mode counts, seat counts, test counts, run-store state, or readiness; recompute those from §0 and the
live commands. Phase 01 release verification on 2026-07-22 used:
the current full-suite JUnit plus matching before/after source SHA-256 snapshots.

The evidence bundle additionally contains a real Windows `COMPILED` PDF receipt,
the pinned immutable Docker `linux/amd64` targeted suite, AI evaluation, security,
and director-route/completion gates. These prove the concrete operated recipes and
their boundaries; they do not claim a real research-paper run, GPU execution,
autonomous submission, or externally verified independent review.

Historical deterministic re-verification on 2026-08-03 (that checkout, all read-only):

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
