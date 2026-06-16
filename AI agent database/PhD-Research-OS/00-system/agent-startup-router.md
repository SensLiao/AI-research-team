---
title: "Agent Startup Router (task-type → required reading + actions)"
type: routing
status: active
confidence: high
created: 2026-05-01
updated: 2026-05-01
canonical: true
aliases:
  - startup-router
  - task-router
  - session-entry
---

# Agent Startup Router

> **Read me first.** Every new session — and every new task within a session — starts here.
>
> The router does ONE job: given the task type the user asks for, name the exact canonical pages the agent must read, the actions it must perform, and the actions it is forbidden from taking. This is the entry point that prevents the "patch-chase until green" pattern.

---

## Stage 1: Classify the task

Pick exactly one row. If the user request spans two task types, classify as the **higher-risk** one.

| # | Task type | Trigger phrases / signals |
|---|---|---|
| 1 | **Code change** (model wrapper / training / preprocess / eval script) | "edit X", "fix bug in", "patch", "refactor", "改 wrapper" |
| 2 | **New experiment / run launch** | "run T<N>", "launch sweep", "run on full test set", "新开实验" |
| 3 | **Debug result anomaly** | "metric is wrong", "model fails on X", "崩了", "为什么这么低" |
| 4 | **Method / prompt / protocol design** | "design ablation", "Route A/C/D", "evaluation protocol" |
| 5 | **Paper / thesis / report writing** | "write chapter", "Table X", "rebuttal", "supervisor slides" |
| 6 | **Vault read / recall / sync** | "vault 里有没有", "what do I know about", "summarize" |
| 7 | **Server / infra / automation** | "上传脚本", "起 tmux", "ssh", "拉 log", "container build" |
| 8 | **Decision (ADR) — new** | "decide X", "should I use Y", "lock the choice" |
| 9 | **Meeting prep / debrief** | "supervisor meeting", "1:1 prep", "draft agenda" |

If you cannot classify within 30 seconds → ask the user to disambiguate. **Do not guess.**

---

## Stage 1b: Dispatch → which agent executes (added 2026-06-07)

The 9 rows route to *reading pages*; this table names the `.claude/agents/` role that owns execution — connecting the router to the team.

| Row | Task type | Owning agent |
|---|---|---|
| 1 | Code change | `ablation-runner` for approved-experiment scripts; **main thread** for from-scratch wrapper/preprocess (no dedicated code agent yet — roadmap Step 6) |
| 2 | New experiment / run launch | `ablation-runner` (requires an approved experiment card) |
| 3 | Debug result anomaly | `result-analyzer` (+ `adversarial-reviewer` if a result's validity is in doubt) |
| 4 | Method / prompt / protocol design | `experiment-planner` (propose-only, no Bash) |
| 5 | Paper / thesis / report writing | main thread + `render_claim_chain.py`; pull citable rows via `adversarial-reviewer` verdicts |
| 6 | Vault read / recall / sync | `literature-ingest` (new external lit) or direct recall |
| 7 | Server / infra / automation | `ablation-runner` (owns tmux/sbatch/upload) |
| 8 | Decision (ADR) | `experiment-planner` drafts; director signs off |
| 9 | Meeting prep / debrief | main thread (no dedicated agent) |

## Stage 1c: Granularity overlay (the zoom dial — added 2026-06-07)

Independent of task type, set the **granularity** per the controller (`05-registry/status-registry.md` → reading-status drive rules):

| Zoom | When | Agent behavior |
|---|---|---|
| **coarse** (trend / breadth) | scanning a field; papers at `to-read`/`skimmed`; no direction committed | `literature-ingest` **breadth mode** (haiku/sonnet, five-C's, Pass 1 only); read L0 tier only (fast); `adversarial-reviewer` does NOT engage |
| **fine** (implementation / depth) | direction committed; deep-read worklist; papers heading to `deep-read`/`cited` | `literature-ingest` **depth mode** (opus, Pass 2/3); read L0+L1+L2 tiers; **freeze + citation gate fully enforced** — coarse output can never pass it |

The dial moves with rigor: **deeper zoom = stricter gate** (global CLAUDE.md §3.7). The director picks the zoom (or it's implied by the worklist they're working from in `03-views/11-granularity-worklists.base`).

---

## Stage 2: For the chosen row, follow the contract

### Row 1 — Code change

| | |
|---|---|
| **Required reading** | 1. `evidence-contract.md` · 2. `02-wiki/sources/upstream-fidelity-rule.md` (if exists) · 3. `02-wiki/sources/process-memory-index.md` — grep for the model + subsystem · 4. `02-wiki/sources/bug-class-index.md` — locate "what you are doing" row, read linked PMs · 5. Recent `02-wiki/process-memory/pm-*.md` entries for the model |
| **Required actions** | 1. **Cite upstream first.** Before writing any wrapper line, open and quote the matching source-of-truth file paths + line numbers. · 2. **Reuse over reimplement.** Import sibling helpers; copy-and-modify is a code-fidelity violation. · 3. **Backup before overwrite** (`<file>.pre_pmNN.bak`). · 4. **Smoke test** before declaring done. |
| **Forbidden** | ❌ Edit anything outside the project's intended-write surface · ❌ Invent a function / module / attribute name without grepping the live code · ❌ Patch via in-place string-replace on remote files · ❌ Loosen an assert to "make a test pass" |
| **Output to user** | Diff summary: files touched, key logic changes, which PM rules justify each delta, smoke command to verify. |

### Row 2 — New experiment / run launch

| | |
|---|---|
| **Required reading** | 1. `02-wiki/sources/pre-launch-checklist.md` (if exists) · 2. `02-wiki/sources/experiment-protocol.md` · 3. The matching `02-wiki/experiments/<slug>.md` design page · 4. `02-wiki/sources/server-usage-guide.md` (if applicable) · 5. Recent `02-wiki/process-memory/pm-*.md` for the model |
| **Required actions** | 1. **Open / create the matching `02-wiki/experiments/<slug>.md`** BEFORE editing any code. Draft the experiment card. · 2. **Smoke ladder:** 1 case → small set → full sweep. Do not skip rungs. · 3. **Create the `02-wiki/runs/run-<slug>-NNN.md` page** before launching. · 4. **Tag every run with `git-commit` + `env-lock` + `data-version` + `seed`.** · 5. Launch in tmux / nohup / sbatch — never foreground long-running. · 6. **Pre-allocate a `result-status: provisional`** placeholder on result page. |
| **Forbidden** | ❌ Skip the experiment card "to save time" — without it the run is unauditable · ❌ Launch full sweep without smoke first · ❌ Promote in-training metrics to a thesis-table number — use raw-frame eval per project protocol · ❌ Reuse a `seed` already used for that experiment without flagging it |
| **Output to user** | Pre-launch checklist with every box ticked + evidence; tmux/sbatch command; link to experiment + run cards; expected ETA. |

### Row 3 — Debug result anomaly

| | |
|---|---|
| **Required reading** | 1. `evidence-contract.md` (debugging is where hallucination is most expensive) · 2. `02-wiki/sources/bug-class-index.md` — find the anomaly class · 3. Linked PMs · 4. Sibling `02-wiki/syntheses/<slug>.md` postmortems |
| **Required actions** | **1a. Restate the symptom precisely** — file path + metric + observed + expected + sample size. · **1b. Query bug-class-index** — find every row whose symptom-string matches. List them all. · **1c. Disambiguator gate.** If 1b returns ≥ 2 rows OR ≥ 2 first-hypothesis branches, **STOP. Ask the user for the minimum disambiguator BEFORE reading any full PM section.** · **2. Inspect, do not guess.** Once disambiguated, open the actual log / metrics file / data on disk before forming a hypothesis. · **3. Map symptom to PM rule.** · **4. If novel:** dispatch read-only audit before patching. · **5. Smoke the fix** on 1 case before committing. · **6. Write a new PM entry** if the bug is genuinely novel. |
| **Forbidden** | ❌ Patch the symptom without identifying the root cause · ❌ Loosen a fairness check / assert / threshold to "make the test pass" · ❌ Re-run a failing command in a sleep loop instead of diagnosing · ❌ Conclude "the model is just bad" before checking PMs |
| **Output to user** | Hypothesis + evidence chain (file:line → observation → PM cited); minimal repro command; proposed fix + smoke plan. |

### Row 4 — Method / prompt / protocol design

| | |
|---|---|
| **Required reading** | 1. `02-wiki/sources/research-questions.md` — confirm RQ alignment · 2. Existing `02-wiki/methods/*.md` — what's already proposed · 3. Existing `02-wiki/protocols/*.md` — what's already locked · 4. `02-wiki/decisions/dec-*.md` — what's already decided · 5. The relevant `02-wiki/comparisons/*.md` if any |
| **Required actions** | 1. **Declare the variables** — what is θ_trainable, what is θ_frozen, what is the supervision signal. · 2. **Leakage audit:** prove every input derives from public/training-allowed features only — never test labels. · 3. **Match against contribution-registry** — confirm this design serves a registered C<N>. · 4. **Write a `decision` page** before locking the design — even a "we tried A and rejected it" needs ADR-style record. |
| **Forbidden** | ❌ Use case-specific oracle inputs · ❌ Use test-set artifacts to derive a method · ❌ Conflate "trained on dev" with "tested on dev" results · ❌ Ship a method without leakage proof |
| **Output to user** | Method declaration + variable boundary + leakage proof + decision-page link + matched contribution. |

### Row 5 — Paper / thesis / report writing

| | |
|---|---|
| **Required reading** | 1. `02-wiki/sources/research-questions.md` · 2. `02-wiki/sources/claim-map.md` · 3. The chapter's `02-wiki/syntheses/chapter-<N>-*.md` page · 4. 🔴 `00-system/AGENTS.md` §2 (citation gate) — check `can-cite-thesis: true` before any number enters thesis text |
| **Required actions** | 1. **Cite via slug** — `[[<slug>]]` for every quoted number, every method, every paper. · 2. **Tag every claim with its source row.** · 3. **Use the careful-language rules** from `02-wiki/sources/writing-style-guide.md`. · 4. **Distinguish RQ finding vs implementation detail** for any "X model produces Y" claim. · 5. Run `06-scripts/render_claim_chain.py` if a synthesis page declares `claim-chain:` — it will refuse to render uncitable rows. |
| **Forbidden** | ❌ Quote pre-PM result numbers from invalid status · ❌ Quote in-training metrics as canonical · ❌ Cite a paper not in `02-wiki/papers/` · ❌ Use vague qualifiers ("usually", "often", "tends to") in a Results section without an explicit `[[result-slug]]` |
| **Output to user** | Text / table / figure with inline `[[slug]]` citations to every number. |

### Row 6 — Vault read / recall / sync

| | |
|---|---|
| **Required reading** | 1. `00-system/hot.md` first · 2. `00-system/index.md` for the topic slug · 3. Walk `[[slug]]` links inside matching pages |
| **Required actions** | 1. **Quote the page slug + section heading** you are reading from. · 2. If the vault is silent, say so explicitly and offer to INGEST. · 3. If the answer requires synthesis across multiple pages, file `02-wiki/syntheses/<slug>.md` after answering. |
| **Forbidden** | ❌ Reconstruct a fact from training-data memory when the vault has it · ❌ Invent a slug — only cite slugs that exist in `index.md` |
| **Output to user** | Answer with inline `[[slug]]` citations; explicit "vault is silent on X" if applicable. |

### Row 7 — Server / infra / automation

| | |
|---|---|
| **Required reading** | 1. `02-wiki/sources/server-usage-guide.md` (if exists) — platform footguns · 2. Recent server-related PMs · 3. `02-wiki/protocols/*.md` for any locked deployment protocol |
| **Required actions** | 1. **Normalize line endings** before remote upload (CRLF → LF for `.sh`). · 2. **Set cache + tmp dirs** to project-allowed paths before pip / conda. · 3. **Wrap conda activate** safely under `set -euo pipefail`. · 4. **Whole-file replace via SFTP** — never in-place patch. · 5. **Tmux all long-running commands.** · 6. **Verify exit codes + stdout/stderr** — never trust "command finished" without reading output. |
| **Forbidden** | ❌ Edit files outside the project's intended-write surface · ❌ `pip install` without setting cache dir · ❌ Trust an exit code without reading stderr · ❌ Skip backup step on overwrite |
| **Output to user** | Driver script summary + key safeguards + tmux session name + sentinel path. |

### Row 8 — Decision (ADR) — new

| | |
|---|---|
| **Required reading** | 1. Existing `02-wiki/decisions/dec-*.md` for any prior overlapping decision · 2. The relevant `02-wiki/sources/research-questions.md` and `contribution-registry.md` rows |
| **Required actions** | 1. Open `04-templates/decision.md`, copy to `02-wiki/decisions/dec-<NNNN>-<slug>.md`. · 2. Fill: context · options-considered · chosen · rationale · consequences · risks · revisit-when. · 3. Set `status: proposed` until user confirms; then `accepted`. · 4. Update `00-system/index.md` and `07-logs/log.md`. |
| **Forbidden** | ❌ Make a high-stakes decision without ADR record · ❌ Set `status: accepted` without explicit user sign-off |
| **Output to user** | Decision page link + the trade-off summary + the explicit ask: "confirm and I will mark accepted, or push back". |

### Row 9 — Meeting prep / debrief

| | |
|---|---|
| **Required reading** | 1. Last 3 `02-wiki/meetings/meeting-*.md` for the same supervisor / team · 2. `02-wiki/sources/supervisor-feedback-index.md` (if exists) · 3. `00-system/hot.md` "Open questions" section |
| **Required actions** | **Pre-meeting:** · 1. Draft agenda from open questions in hot.md. · 2. Pull recent `result-status: provisional` rows that need supervisor input. · 3. Pull pending `decision` pages with `status: proposed`. **Post-meeting:** · 4. Write `02-wiki/meetings/meeting-YYYY-MM-DD-<topic>.md` with `decisions:` and `action-items:`. · 5. For each decision made, file a corresponding `02-wiki/decisions/dec-*.md`. · 6. For each action item, link to the experiment / paper / claim it serves. |
| **Forbidden** | ❌ Lose a decision in a meeting note without ADR record · ❌ Carry "TODO" items in meeting notes that don't link to a typed page |
| **Output to user** | Agenda doc (pre-meeting) or meeting summary + ADR links + action-item list (post-meeting). |

---

## Stage 3: Hand-off contract

After classifying + reading + acting, the agent's **first user-visible message** must declare:

```
Task type: <row 1-9>
Required pages read: [<slug>, <slug>, ...]
Identified rules / PMs in scope: [<rule>, ...]
Planned actions: <bulleted list>
Forbidden actions I will NOT take: <bulleted list>
Acceptance criteria (how I will know I'm done): <bulleted list>
```

This single block protects against:
- silent context-loss across long sessions
- the agent skipping a relevant rule because it "felt obvious"
- the user not noticing the agent took an off-router shortcut

---

## When to skip the router

- Trivial single-line edit to a doc file (typo) — proceed without router; still respect `evidence-contract.md`.
- Read-only inspection (open file, list dir) — proceed without router.
- User explicitly says "skip the router, just X" — honor the override but log it in the response.

Anything that touches code, an experiment, an eval, a result, a thesis claim, or a decision — **always go through the router**.

---

## Maintenance

Update when:
- A new task type emerges in repeated user requests
- A new canonical rule page is added that should be in the required-reading column
- A new "forbidden action" bug class is discovered
