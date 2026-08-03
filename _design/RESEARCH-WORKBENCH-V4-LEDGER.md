# Research Workbench v4 — build ledger

> Durable progress ledger for the v4 reshape ("前台一页，后台千军，能力做厚，治理做薄").
> **A fresh session reads §1 first**, then §6 for the current pointer. This file is the anti-amnesia
> device: session-local ToDo lists die on `/clear`, this does not.
> Opened 2026-08-03. Source design: the director's external architecture memo (pasted in-session,
> archived below in §2). Machine repo: `research_agent_teams/` @ `snapshot/latest-research-team-20260711`.

---

## 1. Read this before doing anything

The external memo describes a 7-phase build. **Four of those seven were already built** on
2026-07-31 → 2026-08-01 (the T4 upgrade + usability-hardening rounds). The external model authored
the memo from uploaded documents only — it could not see the working tree — so it presented
already-shipped subsystems as greenfield work. §3 is the verified delta. **Do not re-derive it; do
not re-plan from the memo alone.**

The director was shown §3 and **reaffirmed the full 7-phase scope anyway**, plus a reversal of the
upstream-mounting decision. Both reaffirmations are recorded in §2. Rebuild work is therefore
authorized, but every rebuilt-over-existing item must be **labelled as such** in the session report.

---

## 2. Director's locked decisions

| # | Decision | Locked | Note |
|---|---|---|---|
| D1 | Scope = **all 7 phases** | 2026-08-03 | Reaffirmed *after* being shown that P3/P4/P5/P6 already exist. Rebuild is authorized; must be labelled. |
| D2 | Workbench surface = **Markdown + CLI only** | 2026-08-03 | No `workbench/ui/`, no web UI. This is why the UI design pipeline never fires. |
| D3 | Single entry = **evolve the existing `research-orchestrator` in place** | 2026-08-03 | Do **not** move the entry into `research_agent_teams/.claude/`. The auto-loading entry is the **project-root** `.claude/` + `.agents/`; relocating it breaks auto-load. The external memo's target tree is wrong on this point. |
| D4 | Git baseline = **commit the pre-existing working tree first**, then build | 2026-08-03 | 145 modified + ~80 untracked files predate this engagement. |
| D5 | Upstream repos = **really mount them** (reverses the concept-only stance) | 2026-08-03 | Reaffirmed after one objection. Before mounting, the reversed safety decisions must be listed to the director item by item. See §5. |
| D6 | No subagent fan-out / no Workflow unless asked | session rule | Work is done serially by the main thread. GSD-format artifacts are still written so the repo stays GSD-manageable. |
| D7 | **Every role in `agents/` is a SUB-agent.** There is exactly ONE main thread. | 2026-08-03 | Director's standing rule. The sole main-thread role is the `research-orchestrator` skill; the other 162 files are `worker` / `hook` / `producer` / `single-writer`. No new capability may create a second main-thread role, and a worker never dispatches a worker. **Verified, not assumed:** `grep -l "main-thread\|kind: skill" agents/*.md` returns exactly `agents/research-orchestrator.md`, whose `never:` list already contains "allow sub-agents to spawn sub-agents". D7 promotes an implicit property to a pinned one (see the subagent invariant in `tests/test_outcome_recipes.py`). Note D7 constrains **the machine at run time**; D6 constrains **this build session** — they do not conflict. |

Standing rules that also bind this work: two-repo boundary (machine vs vault); only
`/promote-to-vault` writes the vault; secrets live only in the gitignored `.env`; a dry-run is never
reported as an observed result.

---

## 3. Verified delta — the 7 phases against the real tree

Verified 2026-08-03 by direct inspection of the working tree (not from documents).

| Memo phase | Real status | Evidence in-tree |
|---|---|---|
| **P1 Workbench projection** | ❌ **genuinely absent** — the one real gap | No persistent projection store anywhere. The only `sqlite` use is a per-run citation-existence cache (`tools/citation_existence.py`). No `PROJECT-HOME.md` generator, no unified Machine+Vault full-text search. `tools/workspace.py::dashboard/project_index` compute in memory, on demand, and never touch the vault. |
| **P2 Single entry** | ✅ **largely done** | The 2026-08-01 round fixed exactly this: entry docs advertised 7/8/7/10 modes while the registry had 12, hiding 5 real capabilities. Entry SKILL rewritten as a plain-language routing table; 3 intents added so 4 previously unreachable modes route; guard tests added. `reporting/` (4 modules) = the memo's Execution Brief + plain-words progress report, exposed as `operate brief` / `operate report`. |
| **P3 Nine upstream sources** | ✅ **done — deliberately in the opposite direction** | All nine cloned, source-reviewed, HEAD-pinned, 45 file SHA-256 receipts; **359** upstream `SKILL.md` inventoried; 25 integration decisions (20 implemented / 4 planned / 1 rejected). But **not mounted, not imported, not executed** — capabilities are clean-room summaries in `orchestrator/research_capability_overlays.json`. Authoritative: `orchestrator/external_research_skill_sources.json` + `_design/review/external-research-skills-source-audit-2026-07-31.md`. **D5 reverses this.** |
| **P4 Dynamic Director** | ✅ **done** | `natural-language → deterministic capability/mode selection → operated mode only → optional council → existing stage/gate/budget contracts`. `--mode` overrides; `--mode auto` cannot silently run a spec-only mode; overlays are advisory (cannot add agents, open network, or write the vault). `tools/research_capability_router.py`. |
| **P5 Hypothesis→Experiment compiler** | ✅ **done, one role richer than the memo asks** | 7-role mechanism council: `mathematical_formalizer` · `domain_reality_auditor` · `cognitive_intent_modeler` · `curriculum_design_specialist` · `causal_mechanism_critic` + `research_engineering_planner` + `hypothesis_compiler` (conflict-preserving hypothesis→mechanism→experiment closure). `orchestrator/mechanism_council.json`, `tools/mechanism_council.py`. |
| **P6 Example project + double-blind** | ✅ **done and actually executed once** | `projects/t4-scribble-m0-mechanism-eval/`: 6 contributor work orders + compiler + 1 independent challenger + 3 blind judges + an X/Y mapping committed before review and revealed after + a preserved first `FAIL` + repair + final independent `PASS`. Dispatch evidence: `tools/native_dispatch_trace.py`. |
| **P7 Governance slimming** | ❌ absent | And per the memo itself it must come last, driven by real usage telemetry. |

### 3.1 Three honesty records the P6 round left behind (do not lose these)

They are the evidence that the machine does not launder failure into success:

- a causal worker lost its stream twice → recorded `ABANDONED_NO_OUTPUT`, replaced by a different owner;
- a repair worker found the target file's bytes no longer matched its dispatched packet → stopped
  before output, recorded `SOURCE_HASH_MISMATCH_AFTER_DISPATCH`, never silently overwrote;
- all three blind judges preferred the **independent challenger** over the council's own candidate —
  an unflattering result, kept.

---

## 4. Baseline facts (measured, not quoted)

| Fact | Measured value | How |
|---|---|---|
| agents | **163** files in `agents/` (**157** research workers per the 08-01 round) | `ls agents/*.md` |
| tools | **137** | `ls tools/*.py` |
| schemas | **167** | `find schemas -type f` |
| modes in registry | **26** | parsed `orchestrator/mode_registry.yaml` |
| one-button (operated) modes | **12** | `operate/modes/*.py` minus private/`__init__` |
| gates | **5** | `ls gates/*.md` |
| profiles | **7** | `ls profiles/*.yaml` |
| slash commands | **19** | `ls .claude/commands/*.md` (project root) |
| registered projects | **3** — `iac-cbct-seg`, `petct-residual-correction`, `t4-scribble-m0-mechanism-eval` | `ls projects/` (gitignored) |
| upstream skills inventoried | **359** across 9 repos | `external_research_skill_sources.json` |

### 4.1 Test suite — the documented number was wrong

`CLAUDE.md` and `_design/review/t4-research-agent-team-upgrade-2026-08-01.md` both claim
`3914 passed, 4 skipped, exit 0`. **Measured on this working tree 2026-08-03: `3 failed, 3910
passed, 5 skipped` in 351 s.** All three failures were regressions from the 2026-08-03 doc/rename
session, not pre-existing:

| Failure | Root cause | Fix applied |
|---|---|---|
| `test_manuscript_completion.py::test_every_director_entry_is_synchronized_to_the_two_operated_manuscript_products` | `AGENTS.md` was converted to a pointer stub, so it no longer literally names `manuscript_authoring`; the 08-01 entry-doc truth guard requires every entry doc to name both operated manuscript products. | Guard made **stronger**, not looser: `.claude/CLAUDE.md` (the real operating manual, previously **unguarded** — a hole) added to `DIRECTOR_ENTRY_FILES`, and the per-file check now accepts a pointer stub **only** when it names a workspace-relative path that is itself guarded *and* whose target discloses both products. Negative-controlled: a stub pointing at an unguarded file, or with no pointer, still fails. |
| `test_resource_resolver.py::test_petct_dual_gpu_candidates_are_discoverable_but_only_a6000_is_execution_ready` | Project slug renamed `petct-textual-intent` → `petct-residual-correction` (recorded in `projects/petct-residual-correction/records/2026-08-01-project-normalization.md`); the test still hardcoded the old slug. | Slug updated. **Assertion strength unchanged** (only the A6000 is execution-ready; `submit_job` still denied). |
| `test_resources.py::test_real_bdav_3090_director_resolution_still_requires_live_execution_admission` | Same stale slug — the file was half-migrated (line 208 already used the new slug, line 213 did not). | Slug updated; assertions unchanged. |

`tests/test_server_monitor.py` also mentions the old slug (lines 284/288) but passes — it is a
CLI pass-through string, not a filesystem lookup. Left alone deliberately (minimal diff).

### 4.2 The project root had no working git repo — found AND fixed 2026-08-04

Measured, not assumed: the root holds a `.git` **empty directory** (created 2026-07-11, no `HEAD`, no
objects, no config), so `git rev-parse --show-toplevel` there returns *fatal: not a git repository*.
Two real repos exist below it — `research_agent_teams/` (machine) and `AI agent database/PhD-Research-OS/`
(vault). Everything at root level is therefore **unversioned: no history, no diff, no rollback**:

- `.claude/CLAUDE.md` — the operating manual, edited twice today;
- `.claude/skills/research-orchestrator/SKILL.md` — the entry skill;
- `.claude/commands/*.md` — 19 slash commands;
- `docs/` — the 5-file doc centre; `AGENTS.md`.

Three options were put to the director (① a root repo with the two subrepos gitignored, ② separate
small repos for `.claude/` and `docs/`, ③ leave it unversioned). **Answer: ①.** Shipped as root commit
`e4d77db` — 51 files (`.claude/` manual + settings + 2 skills + 19 commands, `.agents/` 18 mirrors,
`.Codex/` 3, `docs/` 5, `AGENTS.md`, `.gitignore`), secret-scanned first. The two real repos are in
`.gitignore`, and `git ls-files | grep -c` for either of them returns **0** — the §5.1 boundary is
preserved by ignoring them, not broken by nesting. Note option ③ was weaker than it sounded: the
existing GitHub config mirror covers `~/.claude/`, never this project's `.claude/`.

---

## 5. Before mounting the upstream repos (D5) — the decisions being reversed

**RESTATED AND ANSWERED 2026-08-04.** The five items were read out to the director item by item; the
decision was **"只挂原文，不跑任何东西"** — vendor the upstream TEXT read-only. That reverses items
**1 and 5**; items **2 and 3 stay in force**; item 4 is recorded, not a veto. Executed by
`tools/vendor_upstream_skills.py` into `vendor/upstream-research-skills/`; the same four-line record
is machine-readable in `orchestrator/external_research_skill_sources.json::text_vendoring` and in the
vendor `MANIFEST.json::policy`, with a test asserting the two agree word for word.

| # | Item | Outcome 2026-08-04 |
|---|---|---|
| 1 | 359 third-party `SKILL.md` files move into the repo tree | **REVERSED** — 358 bundles / 2604 markdown files / 25.9 MB vendored (the 359th belongs to the excluded source) |
| 2 | Mounting implies running third-party installers / hooks / MCP / auto-update | **KEPT** — the copy allowlist admits markdown + license notices only, so there is nothing runnable in the tree; a test asserts it |
| 3 | `drawio-scientific-illustrator` rejected on safety grounds | **KEPT** — excluded entirely; still `selectable: false`; overlay-catalog validation still fails if referenced |
| 4 | License findings (CC BY-NC; one `NOASSERTION`) | **RECORDED, not a veto** — per-source license text vendored where upstream ships one; `agent_research_skills` ships none at all, disclosed rather than papered over |
| 5 | The verified clean-room "no non-empty exact copy" property | **REVERSED — it has ended, by design** |

Original wording of the five, preserved:

1. **359 third-party `SKILL.md` files move into the repo tree.** They currently live in an
   out-of-repo review root; only clean-room summaries + hashes are in-repo.
2. **Mounting implies running third-party installers / hooks / MCP servers / auto-update.** The
   2026-07-31 audit lists each of those as an explicit rejection.
3. **`icebird1998/drawio-scientific-illustrator` was rejected on safety grounds**, not preference:
   its live CDP browser-control route duplicates a safer offline path. `selectable:false`, and
   catalog validation currently *fails* if an overlay references it.
4. **License findings** (recorded, not treated as a veto — the director's standing stance is that
   licenses are moot for personal/local Route A use): `academic-research-skills` is CC BY-NC 4.0;
   `agent-research-skills` asserts no license.
5. A SHA-256 sweep over 5,640 upstream and 2,038 local files found **no non-empty exact copy** —
   the current tree is verifiably clean-room. Mounting ends that property.

Keep regardless of D5: repo + commit + license + retrieval date recorded per source; no secret
ingestion; no credential propagation; the vault stays write-gated.

---

## 6. Phase checklist + current pointer

Status: `TODO` / `WIP` / `DONE` / `REBUILD` (re-doing something that already exists, per D1) / `BLOCKED`.

| # | Item | Status | Note |
|---|---|---|---|
| 0.1 | Delta audit vs the memo | **DONE** | §3 |
| 0.2 | Measure the real baseline | **DONE** | §4 |
| 0.3 | Fix the 3 regressions | **DONE** | §4.1; targeted 27 passed; guard negative-controlled |
| 0.4 | Full suite green | **DONE** | measured `3913 passed, 5 skipped, exit 0` in 353 s. (The doc's `3914 passed / 4 skipped` is the same 3918 total — one test skips on this host. Benign.) |
| 0.5 | Baseline commit (D4) | **DONE** | `2297503` — 250 files, +39967/−1241. Secret-scanned: the 4 hits are all test fixtures, incl. a redaction canary (`TEST-SENTINEL-DO-NOT-LEAK`, asserted absent from output) and an env-var *name* reference. `.gitignore` gained `.workbench/`, `.harness/`, `workspace/*.jsonl`. |
| P1.1 | `workbench/` package: dual-state model + rebuildable store | **DONE** | `c2b876c` |
| P1.2 | Unified Machine + Vault full-text search | **DONE** | `c2b876c` |
| P1.3 | Generated `PROJECT-HOME.md` + global research home | **DONE** | `c2b876c` |
| P1.4 | `status` / `search` / `next` / `open` verbs + JSON views | **DONE** | `c2b876c` — put in `workbench/cli.py`, deliberately not in `operate/cli.py` (already 1172 lines, over the 800-line rule; and a navigation verb must never be able to start a run) |
| P1.5 | Dual work-state × evidence-state task model | **DONE** | `c2b876c` |

### P1 as shipped (commit `c2b876c`, suite `3986 passed, 5 skipped, exit 0`)

Files: `workbench/{model,store,indexer,projectors,cli}.py` + 4 test modules (71 tests).
`python -m research_agent_teams.workbench <verb>`; `reindex` is the only verb that writes,
and only inside `.workbench/` plus one generated `PROJECT-HOME.md` per existing workspace.

Real numbers from the first live index: **3 projects · 1211 artifacts · 15 tasks · 26 modes**;
artifacts split machine 705 / vault 471 / run 32; FTS5 available on this host.

Honesty properties, each test-pinned:

- **An evidence state above SIMULATED cannot be self-claimed.** OBSERVED needs an executor
  receipt bound to raw result bytes; FROZEN additionally needs a human freeze. An over-claim
  is downgraded *and* the downgrade is recorded in the row.
- **The vault's own two fields are read, never recomputed.** `status` = lifecycle,
  `result-status` = evidence, `can-cite-thesis` stays the vault's derived field
  (`05-registry/status-registry.md` says outright the two axes "measure different things").
  Cross-checked against independent greps: 48 frozen / 62 provisional / 42 deprecated of 471.
- **Tasks are graded by the ledger's own stated rule** — receipt path + checkable number or
  hash — not by the word in their `status` field.
- **A project's own vocabulary survives.** `TaskRow.source_status` / `ArtifactRow.lifecycle`
  keep the source word, and the curated mapping table outranks the pending-regex so
  `UNBLOCKED_PENDING_RERUN` reads as ready rather than blocked.
- **Vault kinds are enumerated from disk**, never hardcoded.

Three defects found and fixed while building it (two in pre-existing code, one mine):

1. `reporting/scan.py` counted the vault from a hardcoded kind list — it named a `risks`
   folder that does not exist and omitted `comparisons` / `meetings` / `models` / `papers`,
   so **47 pages (~10% of the vault) never reached a briefing**. 424 → 471, sum reconciles.
2. `pending_director_decisions` lives in its own array in the task ledger, so reading only
   `tasks` reported "nothing is waiting on you" while **two decisions sat unmade**.
3. Search handed raw input to FTS5, so `state-relative intent` failed with `no such column:
   relative`. Terms are now quoted; a CJK query is routed to substring search because FTS5's
   default tokenizer cannot segment CJK; the answer reports which engine ran.
| P2.1 | Six Outcome Recipes as the user-facing layer | **DONE** | `6d1b470` |

### P2.1 as shipped (commits `6d1b470` + `e6f9509`, suite `4022 passed, 5 skipped, exit 0` in 179 s)

> Verification note, kept deliberately: the first full-suite run reported **4020**, because it was
> launched *before* the last card-wording fix and its test. The arithmetic did not reconcile
> (3986 + 34 + 2 = 4022), which is how the gap surfaced — and the missing test was in fact **failing**:
> it asserted a sentence ("不是一定全派") that was never written into `_SEAT_NOTE`. Re-run after the
> fix: 4022. A suite number is only worth quoting for the tree it actually ran on.

Files: `orchestrator/outcome_recipes.yaml` (data SSOT — edit it and the menu changes with zero code
change) · `tools/outcome_recipes.py` (load / validate / derive / compile) · `reporting/outcomes.py`
(the two plain-Chinese cards) · 2 `workbench` verbs (`outcomes`, `outcome`) · 1 cross-reference in
`operate brief` · `tests/test_outcome_recipes.py` (35 tests).

**What it adds that `plan_catalog.yaml` did not.** The plan catalog is reactive: it routes a request
the director already knows how to phrase. A director who does not know `deep_ideation` exists cannot
ask for it. The six recipes are the inverse — a menu of OUTCOMES that can be SHOWN, named by what
ends up in the director's hands. It sits ABOVE the 2026-08-01 routing table and replaces nothing.

Honesty properties, each test-pinned **with a negative control** (a deliberately-broken copy of the
catalog must fail, so no check passes vacuously):

- **Coverage.** All 12 operated modes are reachable from some outcome; all 8 plan-catalog intents have
  an outcome. Both sets are derived from the registries, not written down. This is the same defect
  class the 08-01 round fixed at the routing layer, re-pinned at the menu layer.
- **Derived, never declared.** Seats / hop budget / human gates / deliverable file are read from
  `mode_registry.yaml` + `plan_catalog.yaml` at render time, and `validate_all` REJECTS a recipe that
  restates any of them — **including in prose**: `_SEAT_COUNT_IN_PROSE` caught "一份 20 席深读报告",
  which I had written into the data myself.
- **A roster is not a dispatch promise.** `docs/03-WORKFLOWS.md` §1 already stated the discipline
  (`agent_subset` = roster, `max_agent_hops` = ceiling, real dispatch in between, neither is
  concurrency). The first draft of the card said "一共 23 席 sub-agent", which reads as a promise; it
  now says "23 席可上场" plus the two-numbers note, and a test asserts the promise wording is absent.
- **No seat is the main thread** (D7): every mode's `agent_subset` is non-empty and never contains
  `research-orchestrator`; the card states outright that the main thread only routes / gates / reports.
- **Forced ceilings.** A route containing `full_rigor_minimal` must state the no-GPU-receipt limit; a
  paper route must state that only `/promote-to-vault` admits it to the vault.
- **The north star is never defaulted to the generic want.** "我想要一个能下注的研究方向" bounds
  nothing, so pinning it would make every downstream drift check vacuous; the compiled command carries
  an explicit placeholder until `--request` is given.
- Only WIRED modes may appear; chains stay non-decreasing in `phase_rank`; every claimed gate has a
  spec file in `gates/`.

Three defects found and fixed while building it:

1. **Every route rendered as "大工程，全队上".** `estimate_cost`'s bands (heavy above 16 hops) were
   calibrated for single tiers, and all six outcomes exceed them, so the size column carried zero
   information. Fixed in the card with the derived numbers plus a marker relative to the other five.
   The shared thresholds were deliberately **not** touched — they still serve the tier menu.
2. **The menu took 11.6 s to render.** `research_plan` re-parsed 58 KB + 14 KB of YAML on *every*
   call (~84 ms each), a few hundred times per render. Added an `(mtime, size)`-keyed parse cache that
   deep-copies on return (0.76 ms), so the caller contract is unchanged — existing callers already
   `copy.deepcopy` before mutating — and an on-disk edit still takes effect with no restart. Both
   halves are test-pinned (`tests/test_research_plan.py`). **11.6 s → 0.17 s**, and it speeds up the
   whole control plane (briefing / router / `operate begin`), not just the menu.
3. **P1's workbench was in NO entry document.** It shipped on 2026-08-03 and the director could only
   use it because the commands were said in chat; a fresh session would never have found it. Now in
   `docs/03-WORKFLOWS.md` §0.5, `docs/README.md`, `PLATFORM-FACTS.md` §0, the `.claude/CLAUDE.md`
   access map, and the orchestrator SKILL §1.
| P3.x | Really mount the nine sources (D5) | **DONE** | text-only, per the director's 2026-08-04 answer to the §5 restatement — see below |

### P3 as shipped

`tools/vendor_upstream_skills.py` (`fetch` online / `verify` offline) + `vendor/upstream-research-skills/`
(README + MANIFEST + 8 source trees) + `tests/test_vendor_upstream_skills.py` (11 tests) + the
`text_vendoring` block in the source lock.

- **The 2026-07-31 review root was gone.** `C:/Users/廖神/Desktop/Honor degree/.tmp/research-agent-skills-review/2026-07-31`
  no longer exists, so "mounting" could not be a copy — it had to be a **re-fetch at the pinned
  commits**. Recorded in the lock as `review_root_status`. Only one stray snapshot survived elsewhere
  on disk, partial; it was not used.
- **43 of 43 audit receipts re-verified** against what upstream serves today, 0 sources blocked. The
  rule is deliberate: a source whose bytes drifted under a pinned commit is BLOCKED and not copied,
  because that is exactly the case where quietly vendoring would be worst.
- **"Cannot run" is structural.** The allowlist admits markdown + license notices only, scoped to skill
  bundles, so the tree holds no `.py` / `.js` / `.sh` / plugin manifest / hook / MCP config. A test
  walks the real tree and asserts it.
- **815 files / 14.5 MB deliberately skipped** — upstream `docs/`, `CHANGELOG`, `.github/` templates,
  and in one repo several hundred files of the upstream's own eval run logs. Counted per source in the
  manifest (`sources[].skipped`), never silently dropped.
- **The lock's own `copy_policy` said the opposite.** Every source carried a self-imposed
  `concept_only_no_code_or_(long_)text` policy from 07-31, and `agent_research_skills` literally said
  `no_code_or_text`. Rather than quietly contradicting the audit record, the lock now carries a
  `text_vendoring` block stating what the director overrode, what still holds (`copy_policy` governs
  CODE — none is copied or run), and which ledger items moved. A test pins lock and manifest to the
  same words.
- **Not capability, not indexed.** Verified rather than assumed: the workbench indexer's only
  machine-source sweep is `projects/<slug>/`, so third-party text cannot inflate artifact counts or
  appear in the director's search. A test asserts the vendor root is outside every swept root.
- Weakest-standing inclusion, flagged not hidden: `agent_research_skills` is `NOASSERTION` (no license
  grant at all) with `commercial_use_policy: not_permitted_without_separate_license`. 31 bundles / 66
  files. Kept under the director's standing Route-A-personal-use position; droppable in one line
  (`EXCLUDED_SOURCE_IDS`) if that position ever changes.
| P4.x | Director additions over the existing router | **DONE (one half REFUTED by measurement)** | `tools/worker_census.py` + `workbench team` + 17 tests — see below |

### P4 as shipped — and the half that was refuted

P4 was specified from a memo claim and a memo assumption. Measuring first turned one into a verified
fact and killed the other, so P4 shipped as **seat accounting**, not as a pruning policy.

**The claim: VERIFIED.** "157 workers, 120 used by operated modes, 37 spec-only" — never checked
before this ledger flagged it as an open premise. Measured: 163 rostered = 6 control + 157 workers;
120 declared by an operated mode, 37 only by spec-only modes, 0 in no subset at all. `roster.yaml`
and `agents/*.md` agree in both directions. Now asserted in code, so the number cannot rot.

**The assumption: REFUTED.** "Dynamic dispatch of dormant workers" presumes dormant workers exist.
**Zero of the 163 are unreachable** — every one is named by a recipe, the mechanism-council config, a
tool, or the engine. There is nothing to wake up, so that half was not built; a test now fails if an
orphan seat ever appears (which is the useful version of the same concern).

**What was actually wrong, and is now measurable:**

- **The roster is a ceiling, not a plan.** 168 declared seat-slots across the 12 operated modes, of
  which **153 are dispatched by the mode's own recipe and 15 fire only on the mechanism-council
  path** — `full_rigor_minimal` 7, `manuscript_review` 5, `venue_readiness` 3. The outcome cards now
  say "35 席可上场（其中 7 席只在 council 路径上场）" instead of a bare ceiling, and a test asserts
  the card's numbers come from the census rather than being typed in.
- **Only 1 of 12 modes can actually be run cheaper.** `deep_research` is the only operated mode with
  a budget knob in `plan_catalog.yaml`. So a "smallest-sufficient-team policy" would have been
  claiming a control that does not exist for the other eleven; `team_plan()` reports what is scalable
  and says plainly that the rest are fixed.
- **`research-orchestrator` is the only name a recipe dispatches without a subset declaring it** —
  correct (it is the main thread, D7) and now pinned, so a genuinely undeclared worker dispatch would
  fail the suite. `agent_subset` is what bounds a mode's permission scope; escaping it silently was
  possible before and is not now.

**Deliberately NOT built: automatic seat pruning.** The seats that look redundant are the independence
machinery — mutually blind hunters, independent auditors, the collision checker that must not be the
idea's own author. Dropping those to save budget removes the reason an output can be trusted.
Narrowing belongs in a recipe's own depth knob, where the author decides what is safe to skip. The
honest follow-up is therefore *adding depth knobs to recipes that can support one*, not a policy layer
that prunes from outside.
| P5.x | Compiler additions over the existing council | REBUILD | the memo's soft output template |
| P6.x | Re-run the example project end-to-end | REBUILD | dry-run only; never dress a dry-run as a GPU result |
| P7.x | Governance slimming | TODO | last, and telemetry-driven |

**Current pointer:** P1, P2.1, P3 and P4 are shipped. Next is **P5** — the memo's soft output template
over the existing 7-role mechanism council (`orchestrator/mechanism_council.json`,
`tools/mechanism_council.py`), a **REBUILD-over-existing** per D1: label which part is new. Then **P6**
(re-run the example project end-to-end, dry-run only — never dress a dry-run as a GPU result), then
**P7** (governance slimming) last and telemetry-driven.

P4 closed the ledger's last open premise: the 120/37 split is **verified**, and the dormant-worker
assumption behind half of P4 is **refuted** (0 unreachable seats). Both are now test-pinned, so P5
inherits measured ground rather than memo claims.

**Unverified premise still open:** the memo's "157 workers, 120 used by operated modes, 37
spec-only". The 157 figure is corroborated by the 08-01 round; the **120 / 37 split is not
verified** and no policy should rest on it until a real cross-reference of
`mode_registry.yaml` × `agents/` is run.

---

## 7. Session log

| Date | What happened |
|---|---|
| 2026-08-03 | Ledger opened. Delta audit (§3) + baseline measurement (§4) done. Documented `3914 green` claim disproved: 3 regressions found and fixed, entry-doc guard hardened and negative-controlled. Director reaffirmed D1 (all 7 phases) and D5 (really mount) after one objection each. |
| 2026-08-03 | **P1 shipped** (`c2b876c`): the rebuildable projection — dual-state model, `.workbench/` FTS5 store, read-only indexer, generated home pages, 7 verbs. Found 3 defects: the vault count was blind to 47 pages (~10%), `pending_director_decisions` never reached a report, and search broke on a hyphenated phrase. |
| 2026-08-04 | **P4 shipped as seat accounting** (`tools/worker_census.py` + `workbench team`, 17 tests). The memo's 120/37 split is now VERIFIED in code; its dormant-worker premise is REFUTED (0 of 163 unreachable). Real findings: the roster is a ceiling — 168 declared vs 153 recipe-dispatched, 15 council-only across 3 modes (now disclosed on the outcome cards); only 1 of 12 modes has a real depth knob, so a pruning policy would have claimed a control that does not exist; and `research-orchestrator` is now pinned as the only recipe-dispatched name without a subset, closing a silent way past `agent_subset` permission scope. Automatic seat pruning deliberately NOT built — the "redundant" seats are the independence machinery. |
| 2026-08-04 | **P3 shipped, text-only**, after the §5 five-item restatement was read out and answered. Review root found deleted → re-fetched at the pinned commits; 43/43 receipts re-verified; 8 sources / 358 bundles / 2604 files / 25.9 MB vendored read-only; 815 files / 14.5 MB skipped and counted; drawio excluded. The lock's contradicting `copy_policy` is now reconciled by an explicit `text_vendoring` record instead of a silent override. **Root repo created** (`e4d77db`, director option ①) — the operating manual and doc centre have history for the first time. |
| 2026-08-04 | **P2.1 shipped** (`6d1b470`): the six outcome recipes + 2 workbench verbs + the brief cross-reference, 35 tests each negative-controlled. Director added **D7** (every role in `agents/` is a sub-agent — verified already true in-tree, now pinned). Found 3 more defects: the size column read "大工程" six times, the menu took 11.6 s (yaml re-parsed hundreds of times → cached, whole suite 456 s → 183 s), and **P1's workbench was in no entry document at all** — now in `docs/03` §0.5, `docs/README`, `PLATFORM-FACTS` §0, the CLAUDE.md access map and the SKILL. Also found, not fixed: §4.2, the project root's `.git` is empty so the operating manual and doc centre are unversioned. |
