# Project: AI Research Agent Teams + PhD-Research-OS (Route A)

> Auto-loaded when Codex opens this folder. This is the **operating manual** for the director's
> bespoke AI research system. When the director asks for research work here, follow this file.
> Current fact source: `research_agent_teams/PLATFORM-FACTS.md`; historical design/status records: `research_agent_teams/_design/`.
> Communication: default Chinese.

---

## 1. What is in this folder — TWO systems, ONE seam

| System | Directory | Role |
|---|---|---|
| **THE MACHINE** | `research_agent_teams/` | the agent team + control plane + tools + the run-store (scratch). Does the work. |
| **THE DATABASE** | `AI agent database/PhD-Research-OS/` | validated knowledge only (the crown jewels): papers / claims / experiments / decisions. Permanent. |

They must NOT be mixed. They connect at exactly **one seam**: the machine **reads** the DB by reference
(`recall`) and **promotes** vetted artifacts INTO it through a **human gate** (`/promote-to-vault`).
Nothing else crosses. The DB never gets polluted with drafts — scratch lives in `research_agent_teams/runs/`
(ephemeral, gitignored), outside the DB.

**Mental model for the director:** the DB = a clean permanent library; the machine = a messy workshop.
Only two things enter the library: ① papers the director ingests, ② results the director approves at a gate.

**Markdown-first review boundary (2026-07-10):** for every completed operated machine run, the director-facing
entry must be a Markdown packet at `research_agent_teams/runs/<project>/<run_id>/director-review/00-REVIEW-PACKET.md`.
`*.artifact.json` and `*.bundle.json` remain machine evidence/archive, not the primary human output. Old runs can
be rendered with `python -m research_agent_teams.operate packet --run-id <run_id>`. The packet is still scratch
unless `/promote-to-vault` admits it into the database.

---

## 2. How to operate — route the director's request to a mode

The entry is the **`research-orchestrator`** skill (`.agents/skills/research-orchestrator/SKILL.md`). It
PARSEs a request into a `task_frame`, drives it through the fixed 7-stage spine
(PARSE→RECALL→WORK→VERIFY→RECORD→REVIEW→REPORT) by dispatching real worker sub-agents per stage,
validating every artifact with the machine's tools, recording in a tamper-evident ledger, and pausing at
the director's human gates. Modes live in `research_agent_teams/orchestrator/mode_registry.yaml`.

| Director says… | Mode / action | Needs a server? |
|---|---|---|
| "把这篇论文收进库 / ingest this paper" | DB **INGEST** (raw → typed `02-wiki/` page) — or machine `ingest_paper` mode | **No** |
| "查一下库里有没有 X / recall X" | machine `recall` (by reference) or the DB's own `/recall` | **No** |
| "帮我找个研究方向 / find a direction" | `new_direction` (gap-hunting → ideate → ranked idea backlog + `director-review/ideas/idea-bet-menu.md` → **`/idea-bet`**) | **No** |
| "扫一遍空白点 / gap scan" | `gap_breadth` (5 hunters → classify → novelty score-only) | **No** |
| "把这些点子排个序 / ideate" | `ideate_ring` (hypothesis → tournament → evolve → backlog) | **No** |
| "评一下证据 / 文献深读" | `evidence_review` / `evidence_deep` | **No** |
| "设计这个实验 / design the experiment" | `design_experiment` / `full_rigor_minimal` (emits runnable **scripts** as artifacts) | **No** (design only) |
| "这个结果够投顶会吗 / venue readiness" | `venue_readiness` (mock blind review → **`/venue-pick`** / **`/venue-decide`**) | **No** |
| "真跑这个实验 / run it on GPU" | EXECUTE (real training/inference) | **YES — needs §6 server** |
| "这个结果可以进库了 / promote" | **`/promote-to-vault`** (re-derives frozen/citable, never trusts a self-claim) | **No** |
| "建/看/删一个研究项目 / new、list、delete project" | `operate project-init / project-list / project-delete --confirm <slug>` | **No** |

To add a paper, the director can just drop the file into `AI agent database/PhD-Research-OS/01-raw/`
and say "ingest", or hand it over directly — structuring it into a typed knowledge page is the machine's
job, not the director's.

**Project dimension (multi-paper / multi-experiment):** every machine run belongs to ONE registered
research project — `operate begin` requires `--project <slug>` (registered in the vault's
`05-registry/project-registry.md`; the director adds rows, the machine never writes the registry).
Machine-side layout per project: `runs/<project>/<run_id>/` (scratch runs) + `projects/<project>/`
(durable workspace: pulled results / scripts / figures / notes) + remote `<workdir>/<project>/<run_id>`
on the GPU server. `operate project-delete --project <slug> --confirm <slug>` wipes a project's whole
machine-side footprint in one command — the vault (promoted knowledge + registry) is NEVER touched.

---

## 3. What works NOW vs what waits for the server (be honest — never blur these)

- ✅ **One-button operable, no GPU** (the TEN wired modes — `operate/modes/__init__.py::REGISTRY`, mirror-tested):
  `new_direction` (gap→tournament-judged ideate→**evidenced prior-art collision gate**→Markdown-first /idea-bet menu
  at `director-review/ideas/idea-bet-menu.md`;
  the collision gate cuts an idea before the menu when an existence-verified paper already did this
  method×problem AND ran it, and records it to a known-prior-art ledger so it is never re-output —
  a novelty SCORE still never cuts; offline ⇒ ideas marked UNVERIFIED, never a false cut), `deep_ideation`
  (strict per-survivor experiment sketches + the same Markdown-first idea-bet menu),
  `gap_breadth` (5 blind hunters → prosecutor → mechanism synthesis → quality audit),
  `evidence_review` / `evidence_deep` / `deep_research` (methodology-derived source quality,
  semantic search trace, exact-span attribution, and independent citation audit),
  `venue_readiness` (profile/precommit → 3 blind reviews → meta-review → human gates),
  `full_rigor_minimal` (16 seats across DESIGN/EXECUTE/ANALYZE/VERIFY; receipt-bound real results or
  an honest scripts-only state), `ingest_paper`, and `read_paper_deep`.
  Every wired run is north-star drift-gated per stage, grounding-gated (citation existence /
  referential integrity), recorded in a tamper-evident run. Plus: ingest papers, recall, promote.
- 🧩 **Spec-only modes (NOT one-button)**: `design_experiment(±minimal)`, `power_analysis_review`,
  `verify_result`, `ideate_ring`, `gap_scan`, `debug_failed_run`, `tree_explore`, `m2_accept`,
  `full_new_direction`, `check_run`, `repo_code_audit`, `analysis_audit_panel`,
  `manuscript_review_pack`, `aers_enhanced_research_pack` — registry-defined and engine-tested/routable, but no operate recipe yet;
  never present them as push-button (audit H8 honesty rule).
- ⏳ **Waits for the director's server (§6)**: actually **running** an experiment on a GPU. The EXECUTE agents
  emit the scripts; running them needs the wired server + credentials. Status today: **tested, NOT operated**
  on real research — no in-machine GPU executor. ([[research-os-execution-boundary]])

Never present a script-emitting "design" run as if the experiment ran (full_rigor_minimal's EXECUTE
without a journal keeps run_records `planned` and metrics empty — structurally). Never present a
scratch result as DB-grade knowledge.

Reading boundary update (2026-07-01): `read_paper_deep` has now been operated
once on a real local PDF (`read-skeleton-recall-20260701`, project
`iac-cbct-seg`) through the local-PDF `fulltext-pre` path. That proves
PDF-grounded paper reading only. It does NOT mean GPU experiments have run, and
it does NOT promote scratch reading artifacts into the vault.

Paper-reading upgrade (2026-07-10): `read_paper_deep` is now a true staged
20-worker A-core paper dissect panel, not a single merged worker. It requires
separate worker bundles for pre-read planning, paper note, structure map,
project alignment, claims, claim-evidence, independent exact citation audit, method teardown, figure/table
reading, result-table audit, math/algorithm audit, appraisal, relations, trend,
domain-transfer critique, reproducibility materials audit, independent
second-reader critique, reconciliation, quality audit, and the Markdown writer. The
deterministic layer blocks missing roles, inconsistent `source_ref`, claim-map
gaps, unread or omitted load-bearing figures/tables under a PASS audit, thin or
weak PASS self-claims, unresolved second-reader scientific repairs, and non-PASS
truth checks. Markdown coverage gaps and `markdown_ready=false` are delivery advisories, not reasons
to hide the current readable result. The human output is
`director-review/papers/<paper>.md`; JSON remains evidence only.

Paper-reading efficiency upgrade (2026-07-11): the 20-role A-core contract is no longer twenty
serial sign-offs. Explicit `parallel_groups` expose the sparse dependency graph in 12 waves: blind
reader+planner; ingest; structure+project alignment; claims; linker+method+relations; independent
citation+figure+math; results+reproducibility; appraisal; trend+transfer; reconciliation; quality;
Markdown. The planner may explicitly skip only scientifically inapplicable visual, result, math,
lineage/trend, or reproducibility specialists; deterministic schema-valid not-applicable bundles keep
downstream interfaces intact. Missing/uncertain policy means run the specialist. A shared paper
representation reuses stable note/structure/claim facts while specialists reopen source snapshots only
for their own verification. Blind reading, independent citation audit, reconciliation, and truth gates
are never optional.

Incremental-repair upgrade (2026-07-11): a failed paper-reading check no longer invalidates the
whole 20-worker panel. The machine records structured defects and uses immutable, hash-linked
supplements under `inbox/supplements/`; only the failed role and explicitly affected data consumers
refresh. Formatting-only normalization consumes zero research workers and preserves richer fields in
a sidecar report. Daily delivery states are `USABLE`, `USABLE_WITH_CAVEATS`,
`NEEDS_SUPPLEMENT`, and `BLOCK`; scientific truth checks (citation entailment, numbers, leakage, oracle quarantine, baseline
fairness, execution truth, and transfer boundaries) remain fail-closed.

Usability-first boundary (2026-07-11): readable Markdown is delivered before presentation-quality
gates. Character count, heading names, keyword coverage, schema formatting, and non-critical figure
coverage are advisories or targeted supplements. Only fabricated/missing core sources, unsupported
core claims, false execution claims, leakage/invalid comparisons, permission violations, or
irrecoverably corrupt inputs may hard-BLOCK daily delivery. `/promote-to-vault` retains strict complete
schema, provenance, claim-evidence closure, and promotion-readiness requirements.

Evidence-depth upgrade (2026-07-10): `evidence_deep` is now a true staged
10-worker evidence panel, not a single merged worker. It requires separate worker
bundles for source gathering, methodology-derived source-quality ranking, claim extraction,
semantic search moderation, claim-evidence linking, independent exact citation audit,
contradiction/invalidation mining, dataset cards, staleness audit, and landscape mapping.
The deterministic layer blocks unverifiable source methodology, incomplete search traces,
missing roles, source-quality refs outside the evidence table, unmapped claims, unknown
contradiction claim refs, and invented invalidation slugs. The human output is
`director-review/evidence/evidence-deep-brief.md`.

Deep-research upgrade (2026-07-10): `deep_research` is now a true staged
12-worker perspective panel, not a single supervisor simulating researchers.
It requires a shared source set, methodology-derived source-quality ranking, four independent
perspective notes, claim extraction, semantic search moderation, claim-evidence linking,
independent exact citation audit, contradiction mining, and synthesis by `landscape-mapper`.
The deterministic layer blocks incomplete search traces,
missing perspective bundles, fewer than three perspectives, duplicate
perspective ids, missing perspective findings, unmapped claims, unknown
contradiction claim refs, and Markdown briefs that omit a perspective. The human
output is `director-review/research/research-brief.md`.

Execution-truth upgrade (2026-07-10): `full_rigor_minimal` uses 16 LLM seats
(DESIGN 5, EXECUTE 3, ANALYZE 4, VERIFY 4). A reasoning worker cannot make a run
provisional by inventing a coherent journal and metric table: real numbers must be rebuilt from
raw result files bound to a non-LLM executor's Ed25519 receipt. Until the external executor is
deployed and signs a real job, the honest state is scripts-only and no GPU claim is admissible.

Historical product boundary (2026-07-10): the current scoreboard sees 57 manifests and 45 completed
operated runs, but all 45 predate the current mode-specific primary Markdown contract. They remain
historical evidence (`LEGACY_UNVERIFIED` where replayed), not current PASS products; rerendering a
packet does not substitute for rerunning missing scientific workers.

---

## 4. Human gates (the director's sign-off points — the model NEVER self-decides)

All are `disable-model-invocation` — only the director runs them (specs in `research_agent_teams/gates/`):
- **`/idea-bet`** — which research direction to bet on (a reject = "none of these, pivot").
- **`/promote-to-vault`** — admit a vetted, human-frozen result into the DB. The gate re-derives
  frozen/can-cite-thesis from the real audits; a `provisional` result is structurally non-promotable.
- **`/venue-pick`** — choose the target venue. **`/venue-decide`** — publish / iterate / pivot.

The machine produces honest, derived verdicts; the decision to bet, publish, or write into the crown
jewels is always the director's.

---

## 5. Boundaries / hard rules (do not cross)

1. **Two-repo boundary**: the machine (`research_agent_teams/`, git repo #1) and the DB
   (`PhD-Research-OS/`, git repo #2) are separate repos. Don't commit one into the other.
2. **Only the `/promote-to-vault` gate writes the DB.** Workers stage into `runs/<run>/inbox/`; the DB's
   own write-guard hooks + the machine's `permission-scope-guard` enforce this.
3. **Crown jewels are read-only for the machine**: the `can-cite-thesis` derivation, evidence-contract,
   status-registry, 3-layer boundary, slug-never-rename — read them, never modify them.
4. **No secret in the repo** (see §6). **Tested, not operated** until the server is wired.
5. **Domain-general**: all domain rigor lives in `research_agent_teams/profiles/*.yaml` — never hardcode a
   domain into the control plane (medical-imaging is just one profile; NLP is another).

---

## 6. Server credentials / env (where the director's lab-server access goes)

Running experiments needs the lab server (SSH host, user, key/password, GPU workdir, scheduler). **Hard
rule: credentials NEVER go in the repo, never in git, never hardcoded, never echoed to chat/logs.**

Flow when the director provides access:
1. Director drops the credentials in the **out-of-repo handoff file**
   `<OUT_OF_REPO_HANDOFF>/server-access-handoff.md` and says "go".
2. I transcribe them into **`research_agent_teams/.env`** — which is **gitignored** (never committed).
3. The operate layer reads them from environment variables only. The placeholder/spec of what's needed
   is `research_agent_teams/.env.example` (committed, no real values).
4. The handoff file can then be deleted; the working secret lives only in the gitignored `.env`.

Until then, all GPU-execution flows stay gated; everything in §3 "works now" runs without them.

---

## 7. Model routing (director lock)

Two policy modes only: **default** = task-appropriate logical capability;
**max_quality** = every reasoning worker requests the strongest capability
profile. `opus` / `sonnet` remain historical workload aliases, not literal model
names. Operated workers declare model-agnostic requirements:

```text
reasoning_strength: strong | frontier
long_context: true | false
tool_use: true | false
provider: any
```

The old director phrase "全 OPUS" is accepted as an alias for
`--model-policy max_quality`. Optional concrete runtime fields are supplied only
through deployment bindings (`RAT_RUNTIME_MODEL`,
`RAT_RUNTIME_REASONING_EFFORT`, `RAT_RUNTIME_SERVICE_TIER`); the research
architecture never hardcodes a provider model. ([[research-os-model-routing-policy]])

---

## 8. Pointers

- Operating entry: `.agents/skills/research-orchestrator/SKILL.md`
- Machine: `research_agent_teams/` (engine `orchestrator/engine.py`, tools `tools/`, agents `agents/`,
  modes `orchestrator/mode_registry.yaml`, profiles `profiles/`, run-store `runs/`)
- Seam: `tools/promote.py` + `gates/promote-to-vault.md` (write) · `tools/recall.py` + `skills/recall.md` (read)
- Design / status / reviews: `_design/` (blueprint + build-plan + M3/M3.5 contracts + `review/`)
- The DB's own operating schema: `AI agent database/PhD-Research-OS/00-system/AGENTS.md`
- Run the machine's self-tests: `python -m pytest research_agent_teams/tests/ -q` (see `research_agent_teams/PLATFORM-FACTS.md` for the current verified count)
- **Workspace control plane** (the director's cockpit, 2026-06-16): slash palette `.Codex/commands/*.md`
  (`/start-research`, `/project-new|list|archive|delete|restore`, `/run-mode|stage|skill|bridge`,
  `/resources`, `/resource-bind`) + operate verbs (`dashboard` / `index` / `set-active` /
  `project-archive|restore|soft-delete|purge` / `resources` / `resource-bind`). Resource pool
  `research_agent_teams/resources/` holds secrets by REFERENCE only (env-var NAMES, never values);
  leases + lifecycle + mid-flight execution in
  `tools/{lease_manager,resource_resolver,workspace,lifecycle,execution_registry}.py`; registries in
  `research_agent_teams/workspace/registries/`. Build ledger: `_design/workspace-control-plane-LEDGER.md`.
- **What works NOW vs waits for the server** (honest 3-bucket boundary + the control plane in plain
  terms): `research_agent_teams/PLATFORM-FACTS.md`.
- Read-only GPU server status: `.Codex/skills/server-query/SKILL.md` (live SSH gated by
  `RAT_SERVER_QUERY_AUTHORIZED`, default OFF; deeper server footguns in `server_monitor/PLATFORM-NOTES.md`).
- Capability audit + roadmap (waves A-D shipped 2026-06-13): `_design/review/ai-capability-audit-2026-06-12.md`
