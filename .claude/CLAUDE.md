# Project: AI Research Agent Teams + PhD-Research-OS (Route A)

> Auto-loaded when Claude Code opens this folder. This is the **operating manual** for the director's
> bespoke AI research system. When the director asks for research work here, follow this file.
> Design of record: `_design/research-agent-teams-complete-blueprint-v1.md`. Build/status:
> `_design/research-agent-teams-build-plan-v1.md`. Communication: default 中文 (see global §0/§0.5).

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

---

## 2. How to operate — route the director's request to a mode

The entry is the **`research-orchestrator`** skill (`.claude/skills/research-orchestrator/SKILL.md`). It
PARSEs a request into a `task_frame`, drives it through the fixed 7-stage spine
(PARSE→RECALL→WORK→VERIFY→RECORD→REVIEW→REPORT) by dispatching real worker sub-agents per stage,
validating every artifact with the machine's tools, recording in a tamper-evident ledger, and pausing at
the director's human gates. Modes live in `research_agent_teams/orchestrator/mode_registry.yaml`.

| Director says… | Mode / action | Needs a server? |
|---|---|---|
| "把这篇论文收进库 / ingest this paper" | DB **INGEST** (raw → typed `02-wiki/` page) — or machine `ingest_paper` mode | **No** |
| "查一下库里有没有 X / recall X" | machine `recall` (by reference) or the DB's own `/recall` | **No** |
| "帮我找个研究方向 / find a direction" | `new_direction` (gap-hunting → ideate → ranked idea backlog → **`/idea-bet`**) | **No** |
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

- ✅ **One-button operable, no GPU** (the SEVEN wired modes — `operate/modes/REGISTRY`, mirror-tested):
  `new_direction` (gap→tournament-judged ideate→/idea-bet menu), `gap_breadth` (5 parallel hunters),
  `evidence_review` / `evidence_deep` / `deep_research`, `venue_readiness` (mock blind review →
  /venue-pick · /venue-decide), `full_rigor_minimal` (experiment DESIGN→…→VERIFY with preregistration,
  significance stats, and the honest scripts-only EXECUTE path until the server runs for real).
  Every wired run is north-star drift-gated per stage, grounding-gated (citation existence /
  referential integrity), recorded in a tamper-evident run. Plus: ingest papers, recall, promote.
- 🧩 **Spec-only modes (NOT one-button)**: `design_experiment(±minimal)`, `verify_result`,
  `ideate_ring`, `gap_scan`, `debug_failed_run`, `tree_explore`, `m2_accept`, `full_new_direction`,
  `check_run`, `ingest_paper` — registry-defined and engine-tested, but no operate recipe yet;
  never present them as push-button (audit H8 honesty rule).
- ⏳ **Waits for the director's server (§6)**: actually **running** an experiment on a GPU. The EXECUTE agents
  emit the scripts; running them needs the wired server + credentials. Status today: **tested, NOT operated**
  on real research — no in-machine GPU executor. ([[research-os-execution-boundary]])

Never present a script-emitting "design" run as if the experiment ran (full_rigor_minimal's EXECUTE
without a journal keeps run_records `planned` and metrics empty — structurally). Never present a
scratch result as DB-grade knowledge.

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
   `<a scratch path OUTSIDE this repo, e.g. ~/secrets/server-access-handoff.md>` and says "go".
2. I transcribe them into **`research_agent_teams/.env`** — which is **gitignored** (never committed).
3. The operate layer reads them from environment variables only. The placeholder/spec of what's needed
   is `research_agent_teams/.env.example` (committed, no real values).
4. The handoff file can then be deleted; the working secret lives only in the gitignored `.env`.

Until then, all GPU-execution flows stay gated; everything in §3 "works now" runs without them.

---

## 7. Model routing (director lock)

Two modes only: **default** = task-appropriate (opus for judgment / hard gates / sign-off / planning;
sonnet for scoped execution) ; **max_quality** = every reasoning agent on opus (only when the director says
"全 OPUS" / max). haiku tier is unused. ([[research-os-model-routing-policy]])

---

## 8. Pointers

- Operating entry: `.claude/skills/research-orchestrator/SKILL.md`
- Machine: `research_agent_teams/` (engine `orchestrator/engine.py`, tools `tools/`, agents `agents/`,
  modes `orchestrator/mode_registry.yaml`, profiles `profiles/`, run-store `runs/`)
- Seam: `tools/promote.py` + `gates/promote-to-vault.md` (write) · `tools/recall.py` + `skills/recall.md` (read)
- Design / status / reviews: `_design/` (blueprint + build-plan + M3/M3.5 contracts + `review/`)
- The DB's own operating schema: `AI agent database/PhD-Research-OS/00-system/CLAUDE.md`
- Run the machine's self-tests: `python -m pytest research_agent_teams/tests/ -q` (2131 green — incl. the Workspace Control Plane, 2026-06-16)
- **Workspace control plane** (the director's cockpit, 2026-06-16): slash palette `.claude/commands/*.md`
  (`/start-research`, `/project-new|list|archive|delete|restore`, `/run-mode|stage|skill|bridge`,
  `/resources`, `/resource-bind`) + operate verbs (`dashboard` / `index` / `set-active` /
  `project-archive|restore|soft-delete|purge` / `resources` / `resource-bind`). Resource pool
  `research_agent_teams/resources/` holds secrets by REFERENCE only (env-var NAMES, never values);
  leases + lifecycle + mid-flight execution in
  `tools/{lease_manager,resource_resolver,workspace,lifecycle,execution_registry}.py`; registries in
  `research_agent_teams/workspace/registries/`. Build ledger: `_design/workspace-control-plane-LEDGER.md`.
- **What works NOW vs waits for the server** (honest 3-bucket boundary + the control plane in plain
  terms): `research_agent_teams/PLATFORM-FACTS.md`.
- Read-only GPU server status: `.claude/skills/server-query/SKILL.md` (live SSH gated by
  `RAT_SERVER_QUERY_AUTHORIZED`, default OFF; deeper server footguns in `server_monitor/PLATFORM-NOTES.md`).
- Capability audit + roadmap (waves A-D shipped 2026-06-13): `_design/review/ai-capability-audit-2026-06-12.md`
