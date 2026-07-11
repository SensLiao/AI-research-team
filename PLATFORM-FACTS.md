# Platform Facts - Research Agent Teams

This file is the fact source for what the machine can do today. It separates
one-button operated modes, routable/spec-only modes, and work that still waits
for the director's GPU server.

## 1. Three Honest Buckets

### Bucket A - One-Button Operated, No GPU Required

The operated surface is exactly the modes present in `operate/modes/__init__.py::REGISTRY`
and mirrored by `orchestrator/mode_registry.yaml` with `operated: true`.

There are currently 10 operated modes:

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
| `ingest_paper` | `DISCOVER -> REPORT` | Two workers: quick extractor plus independent source/claim verifier. No local reopenable snapshot means `NEEDS_DEEP_READ`; promotion remains human-only. |
| `read_paper_deep` | `DISCOVER -> REPORT` | Twenty workers: blind second reader first, primary paper dissection, exact citation audit, visual/table/math/reproducibility audits, reconciliation, quality audit, and Markdown writer. Human product: `director-review/papers/<paper>.md`. The 2026-07-01 Skeleton Recall Loss run proves historical PDF-grounded reading, not operation of this upgraded panel. |

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

### Bucket B - Routable / Spec-Only, Not One-Button Operated

These modes are defined in the registry and route cleanly, but they do not yet
have an `operate/modes/*.py` recipe. Do not present them as push-button operated.

`check_run`, `gap_scan`, `design_experiment`, `design_experiment_minimal`,
`power_analysis_review`, `verify_result`, `full_new_direction`, `m2_accept`,
`ideate_ring`, `debug_failed_run`, `tree_explore`, `repo_code_audit`,
`analysis_audit_panel`, `manuscript_review_pack`, `aers_enhanced_research_pack`.

The coverage-closure modes exist so every non-control agent is reachable through
the router:

| Mode | Covers |
|---|---|
| `power_analysis_review` | Statistical power/design adequacy audit. |
| `repo_code_audit` | Repo inspection, patch planning, implementation, tests, sandbox/repro support. |
| `analysis_audit_panel` | Result diagnostics, fairness/variance/compliance/visualization/claim-strength audits. |
| `manuscript_review_pack` | Synthesis, contribution ledger, threats to validity, response simulation, review pack. |
| `aers_enhanced_research_pack` | AERS-informed SOP, literature-search, data-wrangling, reproducibility, benchmark, venue, bibliography, and manuscript polish pack; routable only, not one-button operated. |

### Bucket C - Waits For The GPU Server

Real GPU training/inference still waits for the director's server credentials
and resource binding. `full_rigor_minimal` can emit scripts and planned/provisional
records, but without a real execution journal the records stay structurally honest:
run records remain `planned` and metrics stay empty.

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

The machine has 140 rostered agents:

```text
140 total
  6 control / infrastructure agents
  134 non-control research worker agents
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
- `/promote-to-vault`: promote only a vetted, frozen result into the database.

## 5. Boundary With The Vault

`research_agent_teams/` is the machine: messy scratch, runs, tools, control plane.
`AI agent database/PhD-Research-OS/` is the database: validated knowledge only.

The seam is narrow:

- Read by reference through recall.
- Write only through `/promote-to-vault`.
- Never place secrets in the repo, git, chat, or logs.

## 6. Quick Commands

| Goal | Command surface | Operate layer |
|---|---|---|
| Start or inspect workspace | `/start-research` | `dashboard` / `index` |
| Run a full operated mode | `/run-mode` | `begin -> pre-search/fulltext-pre -> repeat worker waves until stage complete -> run-dets -> commit -> human gate/report` |
| Run one stage/skill/bridge | `/run-stage`, `/run-skill`, `/run-bridge` | matching operate verb with dependency checks |
| Project lifecycle | `/project-*` | `project-init`, `project-archive`, `project-restore`, `project-soft-delete`, guarded `project-purge` |
| Resource pool | `/resources`, `/resource-bind` | references only; no secret values |
| Read-only server status | `server-query` | live SSH only when authorized |

## 7. Verification

Run the self-tests from `research_agent_teams/`:

```powershell
python -m pytest tests -q
```

Current local verification after the 2026-07-11 quality-first performance upgrade:
`3062 passed in 157.91s`.

Additional deterministic evaluations on the same checkout:

```text
rat_eval_harness --no-manual: 4/4 scenarios pass, 13/13 required machine checks pass
JSON schemas parsed: 143/143
AERS upstream validator: 0 errors
quality scoreboard: BLOCKED, 57 manifests, 45 completed operated runs, 45/45 missing current primary Markdown
```

The scoreboard block is intentional historical debt, not a failure of the current code. Old JSON and
generic report notes are not auto-promoted into current scientific products; decision-relevant runs must
be scientifically rerun under the new worker and truth contracts.

Additional real-paper smoke run (2026-07-01): `read-skeleton-recall-20260701`
under project `iac-cbct-seg`, with 70 local PDF contexts extracted by
`fulltext-pre`, 11 DISCOVER artifacts generated, citation/existence/drift gates
passing, and REPORT committed.
