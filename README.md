# AI Research Agent Teams + PhD-Research-OS

A bespoke, **domain-general** AI research system you drive from [Claude Code](https://claude.com/claude-code). It is two cooperating systems joined at exactly **one seam**:

| System | Directory | Role |
|---|---|---|
| **THE MACHINE** | `research_agent_teams/` | the agent team + 7-stage control plane + tools + ephemeral run-store. *Does the work.* |
| **THE DATABASE** | `AI agent database/PhD-Research-OS/` | validated knowledge only — papers / claims / experiments / decisions. *Permanent.* |

The machine **reads** the database by reference (`recall`) and **promotes** vetted results INTO it through a **human gate** (`/promote-to-vault`). Nothing else crosses — drafts and scratch never pollute the knowledge base.

> **Mental model:** the database is a clean permanent library; the machine is a messy workshop. Only two things ever enter the library — papers you ingest, and results you approve at a gate.

---

## What's in this repo (and what's deliberately NOT)

This is a **framework / template** to fork and run on *your own* research. It ships the **structure**, not the author's data.

**Included**
- `research_agent_teams/` — the full machine: engine, worker agents, tools, modes, profiles, and schemas.
- `AI agent database/PhD-Research-OS/` — the **knowledge-base skeleton**: system docs (`00-system/`), page templates (`04-templates/`), blank registries (`05-registry/`), scripts (`06-scripts/`), and the empty `01-raw/` · `02-wiki/` · `03-views/` folder taxonomy with `.gitkeep` placeholders.
- `.claude/` — the Claude Code entry point: the `research-orchestrator` skill, slash commands (human gates + workspace palette), and project settings.

**NOT included (on purpose)**
- ❌ The author's actual research pages (the `02-wiki/` knowledge — private data).
- ❌ Any secrets / server credentials. `.env` is gitignored; only `.env.example` placeholders ship.
- ❌ The ephemeral run-store (`runs/`) and per-project workspaces (`projects/`).
- ❌ Internal design-of-record docs (`_design/`).
- ❌ The unit test suite (`research_agent_teams/tests/`) — not part of this template export.

---

## Quickstart

1. Install [Claude Code](https://claude.com/claude-code) and open this folder.
2. The project-level `.claude/CLAUDE.md` auto-loads — it is the operating manual.
3. **Entry point:** the `research-orchestrator` skill. It parses a request into a `task_frame` and drives it through the fixed 7-stage spine — **PARSE → RECALL → WORK → VERIFY → RECORD → REPORT** — pausing at your human gates.
4. Stand up your own knowledge base via `AI agent database/PhD-Research-OS/BOOTSTRAP.md`.

### What runs with no GPU (today)
Gap-hunting, ideation (Elo-tournament-judged), evidence / deep research, venue-readiness (mock blind review), and experiment **design** (emits runnable scripts as artifacts) — every run anti-drift-gated and grounding-gated, recorded in a tamper-evident run-store. Plus: ingest papers, recall, promote-to-vault.

### What waits for a server
Actually **running** an experiment on a GPU. The execute agents emit the scripts; running them needs a lab server + credentials you supply via a gitignored `.env` (see `research_agent_teams/.env.example`). Honest status: **tested, not operated** on real research — read `research_agent_teams/PLATFORM-FACTS.md` for the exact boundary.

---

## Human gates — you decide; the model never self-decides
- `/idea-bet` — which research direction to bet on (a reject = "none of these, pivot").
- `/promote-to-vault` — admit a vetted result into the knowledge base; it re-derives the verdict from the real audits and never trusts a self-claim.
- `/venue-pick` · `/venue-decide` — choose the target venue / publish-or-iterate-or-pivot.

---

## Boundaries (hard rules)
1. The machine and the database are **separate concerns** — scratch never enters the knowledge base except through the promote gate.
2. **No secret in the repo, ever.** Credentials live only in a gitignored `.env`.
3. **Domain-general.** All domain rigor lives in `research_agent_teams/profiles/*.yaml` — medical-imaging is just one profile, NLP is another. Never hardcode a domain into the control plane.

---

## License
[MIT](LICENSE).
