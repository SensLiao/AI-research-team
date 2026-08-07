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

### 2.1 Gate-contract changes — registered 2026-08-06 before any code was touched

Three runs (`gap_breadth`, `deep_research`, `design_experiment`) each delivered a full panel and each
proved unshippable at its own deterministic gate. The director was shown the options and chose. These
are **machine gate-contract changes**; the project's scientific contracts are untouched, so nothing
enters `projects/*/docs/12-DECISION-REGISTER.md`.

| # | Decision | Chosen | Status |
|---|---|---|---|
| **D8** | **A terminally-failed run may be reopened — by the director only, once, with an audited reason.** A plain `GateBlock` calls `runstore.fail_run` and nothing can reopen the run, even after the offending worker output has been repaired. `gap_breadth-20260804T142806Z` proved the cost: it died on one prose field at 05:41, the field was repaired at 06:00, and a 2.2 MB / 114-gap dossier stayed unshippable. Reopen records who, why, and the pre/post hash of every changed bundle; it never clears the failure from the ledger, it appends. Never model-invocable. | 坎1 = **B + C** — the existing gap_breadth content is read as draft (option B, no re-run of 8 seats); the machine gets the reopen path (option C) so the next one is not lost. | **implemented** 2026-08-06 |
| **D9** | **The citation gate must separate "the evidence refutes this" from "I could not check this."** `citation_checker.check_contradicted` BLOCKed on every `supports_claim=false`, so a locus the linker marked *insufficient* (source unreachable, 403, paywalled) was reported to the director as a **contradiction**. Split them: `support_relation=insufficient` is recorded as UNVERIFIED and does not block **provided the claim still holds at least one supporting locus**; every other falsity, and any missing or unrecognised relation, blocks exactly as before. | 坎2 = **A** | **implemented** 2026-08-06 |
| **D10** | **`design_experiment` needs a legal channel for two shapes it already advertises but cannot pass.** (a) `alignment_checker` demands train/eval parity for `preprocessing`/`precision`/`label_space`, but a zero-training design has no training pipeline and there is no `zero_training` escape anywhere in the gate code. (b) `compare_metric_impls` demands one identical metric implementation across all conditions, but an experiment whose **treatment is the metric implementation** varies it on purpose. Both raise plain `GateBlock`, i.e. both are terminal. | 坎3 = **A now** (read the current run as draft, use its 22 open decisions), **C queued** (build the channel). **B refused** by the director: do not re-issue the 11-seat run until D9 lands, or it hits the same wall. | **queued — spec below, no code yet** |

**D10 spec, so the queued item is a contract and not a note.** A design declares its shape once, in
`experiment_design.variables.frozen`, and the gate reads that declaration rather than guessing:
`zero_training: true` makes the train-side parity keys **not applicable** (the gate must then require
`train.pretrained` to name the external checkpoints AND require an explicit statement of what corpus
they were fitted on, so the weaker check is replaced, never dropped); a variable listed in
`variables.studied` is a **declared treatment**, so `compare_metric_impls` must require consistency
only across conditions that share the same value of that variable, and must still BLOCK when an
undeclared implementation difference appears. Both remain fail-closed: an undeclared shape gates as
today.

**What D9 actually bought, measured on the real bundle rather than argued.** Re-running the fixed
checker over `deep_research-20260804T142821Z` still returns **BLOCK** — that bundle predates the
prompt fix, so 21 of its 22 relation labels are outside the enum and fail closed exactly as intended.
Projecting the plainly-unverifiable labels (`uncertain` ×13, `adjacent_context_only` ×1) onto
`insufficient` moves the blocked-claim count **11 → 7**: four claims were blocked only because an
unreachable source was reported as counter-evidence, and **seven are real refutations that still
block.** The gate was right about 7 and wrong about 4, and it now says which is which.

**A cross-cutting finding that D9 does not fix and D10 should absorb.** The
`contradiction_report` schema can only express *claim vs claim*. The 2026-08-05 run produced **17
source-vs-claim contradictions** — several sharper than anything in `conflicts[]`, including a set of
per-tracer numbers attributed to a paper containing zero occurrences of the tracer's name — and they
had to be parked in a free-text `summary` that **no downstream gate parses**. The gate cannot see the
findings most likely to sink a paper.

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
| P5.x | Compiler additions over the existing council | **DONE** | `tools/council_template.py` + 4 CLI verbs + 17 tests — see below |
| P6.x | Re-run the example project end-to-end | **DONE, as a REPLAY** | `tools/example_replay.py` + 15 tests; the example is now tracked at last — see below |
| P7.x | Governance slimming | **DONE, as measurement only** | `tools/governance_census.py` + `workbench governance` + 16 tests — see below |

### P5 as shipped — three real gaps, and the one thing that was already right

The memo asked for a "soft output template" over the compiler. The 7-role council already existed
(`orchestrator/mechanism_council.json`, `tools/mechanism_council.py`), so per D1 this is
**REBUILD-over-existing and labelled as such**: nothing in the council contract was rewritten. What
was genuinely missing, measured before building:

1. **No authoring template.** A contributor had prose in its agent spec plus a JSON Schema, and
   nothing that showed the required shape. NEW: `role_template()` / `render_role_template()` derive
   the sheet from the schema + contract at call time.
2. **No director-facing rendering.** The only renderer, `render_anonymous_candidate`, strips producer
   identity and receipts *because it feeds a blind review* — which makes it exactly the wrong
   artifact for the person who has to decide. NEW: `render_council_report()` is its deliberate
   opposite (attribution, OPEN conflicts first, the ceiling read off the bundle).
3. **The output side had no CLI at all.** `mechanism_council` exposed only `plan`; `compile` and
   `render` were Python-API-only, which is why the T4 run had to hand-write JSON. NEW: `template`,
   `check`, `compile`, `render --audience director|blind`.

Honesty properties, test-pinned with negative controls:

- **The template cannot drift from the schema.** A monkeypatched schema with an extra required field
  must appear in the template, or the test fails — so a hand-typed template is caught.
- **The label table's coverage is asserted**, so a new schema field cannot render as a bare English
  key at the director. (Non-vacuous: ≥40 derived paths, and a fabricated path must be absent.)
- **A blank template is not a submission.** Every human decision is a `<TODO：…>` placeholder and
  `check_contribution` fails on any survivor. Better still: filling it naively with each enum's FIRST
  option yields `evidence_status: VERIFIED`, which the schema binds to a source locator — so the lazy
  path still cannot skip the evidence requirement.
- **The compiler seat gets the BUNDLE shape**, not the contribution shape; `blank_contribution()`
  refuses that role outright.
- **The two renderings stay opposite**: one test asserts the director card names roles and the
  compiler id, the blind card names neither, and both carry `DESIGN_ONLY`.

Found and fixed on the way: **`--out` had never worked.** `Path.write_text(newline=…)` is Python
3.10+, this host runs 3.9, and no test ever passed `--out` — so `plan --out` raised `TypeError` for
every caller since it was written. Now uses the repo's existing LF-safe `open()` pattern, with a
regression test.

Found and NOT fixed, deliberately: the contribution schema puts no `minItems` on
`proposed_mechanisms` or `experiments`, so a `COMPLETE` contribution can legally contain neither a
mechanism nor a falsifier. Tightening it would retro-invalidate already-recorded contributions (and
break the P6 replay), so `check_contribution` **discloses it as a warning** instead of silently
changing a live contract. All six recorded T4 contributions fill both fields, so the hole is latent,
not manifested.

### P6 as shipped — a REPLAY, and the reason it is not a re-run

A live re-run means ~14 sub-agent dispatches (blocked by D6/session rule) and would still be
`DESIGN_ONLY` — no GPU. So P6 shipped as the strongest honest version: `tools/example_replay.py`
re-derives the recorded example from its own receipts and stamps the result
`REPLAY_OF_RECORDED_RUN`, never `EXECUTED`. **22 checks, all green**, over 6 stages: recorded
path→digest bindings · dispatch and failure records · council recompile · blind review · repair and
independent re-review · truth boundary.

Why it is worth more than the tests that already existed: `tests/test_t4_*` pin *this* example's
specific ids and verdicts, so they answer "did anyone edit it?". The replay answers "is it still
internally consistent, and does the current code still produce it?" — it discovers the chain from
disk, recomputes 36 digests from bytes, recompiles the bundle from the 6 recorded contributions and
requires the result to be **byte-identical**, and recomputes the three-judge aggregation.

**The finding that mattered most: the example was not in version control.** `projects/` is
gitignored, so all 87 files — including the ONLY copy of the three §3.1 honesty records — lived on
exactly one disk, while **8 tests in `tests/test_t4_*.py` hard-required them**. On a fresh clone
those tests error. Fixed by narrowing the ignore to `projects/*` and re-including this one project
(secret-scanned first: the only "token"/"secret" hits are scientific prose — "arm token",
"missingness token" — and there are no hosts, IPs or credentials). **86 of the 87 are tracked**; the
87th is `PROJECT-HOME.md`, which `workbench reindex` regenerates, so tracking it would churn on every
reindex. Verified that the other two projects stay ignored and nothing leaked in.

Two replay-design decisions worth keeping:

- **A recorded mismatch gets the INVERSE assertion.** One honesty record is a worker that aborted
  because its target file no longer matched its packet, so a stale digest is preserved on purpose. A
  naive replay reported that *finding* as a defect (the first run did exactly this). Now those pairs
  are derived from the failure record itself and must **still fail to match** — "fixing" the example
  breaks the replay, which is the point.
- **Independence is derived, not trusted.** One round's packet declares a 14-name forbidden list and
  the other declares none, so the reviewer-is-not-the-repair-author check reads the author out of the
  repair completion the packet names. Otherwise that round's check would have passed vacuously
  against an empty list. Also: reviews are ordered by their own `reviewed_at`, because a filename
  sort put `-r2` first and reported the rounds backwards (`PASS → FAIL`).

Negative-controlled: 8 tamper tests. Edit a referenced artifact, edit a contribution, heal the
recorded mismatch, invent a completion for the abandoned order, break a dependency digest, reveal the
mapping early, flip a judge vote, or drop the design-only boundary → the replay goes FAIL, each for
its own reason.

### P7 as shipped — measurement, and a refusal to slim anything

The memo said governance slimming must be telemetry-driven and come last. The telemetry turned out to
be real and thicker than expected: **32 recorded runs** (31 `done`, 1 `awaiting_director`). So P7 is
`tools/governance_census.py` + `workbench governance`: it measures, buckets, and reports. It removes
nothing, and `does_not_authorize` is part of its output. Same discipline as P4's refusal to auto-prune
seats — the surfaces that look redundant are usually the independence machinery — and a test asserts
the module contains no mutating call at all.

Measured, over the real history:

| Axis | Built | Ever exercised | Never |
|---|---:|---:|---:|
| One-button modes | 12 | 8 | 4 (`ingest_paper`, `manuscript_authoring`, `manuscript_review`, `new_direction`) |
| Seats | 163 | **50** | 113 |
| Named human gates | 5 | 0 recorded firings | 5 |
| checker / guard tools | 22 | **unmeasurable** | unmeasurable |

**Reachable ≠ exercised, and this does not contradict P4.** P4 proved all 163 seats are wired to
something (0 orphans). P7 measures whether they have ever actually run. Different axes; stating both
is the honest picture.

Four findings, each earned by a number:

1. **`obs.jsonl` looks like a dispatch log and is not one.** It records ONE per-stage *lead* label
   (`agent_name: lead or "operate"`), so reading it as "which seats ran" gives **7** where the answer
   is **50**. The real record is `inbox/<STAGE>.<seat>.bundle.json`, one per worker. I made this exact
   mistake mid-session before checking who writes the file.
2. **`run_completed` is under-written**: 31 runs are `done` per manifest, 2 wrote the ledger event.
   Counting completions from the ledger undercounts 15×; the manifest `status` is the reliable field.
3. **The vault-write path has never been exercised.** 0 promotion targets and 0 `promote` events in
   32 runs. `/promote-to-vault` is not redundant — it is *untested in practice*.
4. **Nothing records an individual check firing.** The 22 guard tools are therefore `unmeasurable`,
   never "unused"; the honest first step toward slimming is to record a firing, not to cut on
   instinct.

With no run history at all, everything reports `telemetry: ABSENT` and **nothing** is bucketed as
unused — you cannot call a surface unused with no usage data (test-pinned).

Also corrected here: a hand-count earlier in this session said **54** seats had been dispatched. It
was wrong — it counted four non-seat bundle kinds (`profile`, `review.<lens>`) as seats. The census
splits inbox bundles three ways (seat / stage-level / other) and reports **50**.

Found while syncing docs: **`PLATFORM-FACTS.md` §0 had no numeric guard** and had already rotted — it
claimed **225** test files while 222 existed. Only its wording was pinned. Five counts that rot every
round (tools, test files, workbench verbs, gates, operated modes) are now re-derived from disk and
asserted row-by-row, with an off-by-one control so the guard cannot pass vacuously.

**Current pointer: all seven memo phases are shipped.** P1 · P2.1 · P3 · P4 · P5 · P6 · P7 are DONE,
and the ledger carries **no open premise** — every number in it is now derived by code and asserted by
a test, so it cannot rot silently.

Two of the seven landed as something narrower than the memo asked, both because measuring first
refuted the ask rather than because the work was skipped. Both are labelled at the point of use, never
presented as the full thing:

| Memo asked for | Shipped | Why the difference |
|---|---|---|
| P4 dynamic dispatch of **dormant** workers | seat accounting | 0 of 163 seats are dormant — nothing to wake |
| P6 **re-run** the example end-to-end | replay from its own receipts | a live re-run needs ~14 dispatches and would still be `DESIGN_ONLY`; the replay re-derives instead, and says so in its own status field |
| P7 governance **slimming** | governance measurement | slimming needs a director decision; and per-check firing is recorded nowhere, so cutting now would be cutting on instinct |

**What the director may reasonably ask for next** (not started, not planned without a decision):

1. **Record a check firing.** P7's biggest blind spot: 22 guard tools with zero observability. One
   line per check turns the `unmeasurable` bucket into a real one, and only then is slimming
   evidence-based.
2. **Exercise the never-run modes and the promote path.** ~~`ingest_paper`~~ (run for real 2026-08-04,
   see §8), `manuscript_authoring`, `manuscript_review`, `new_direction` — 3 still never run, and
   `new_direction` is outcome-menu row 1 with zero runs. `/promote-to-vault` has still never fired in
   33 runs; the only route into the vault remains untested in practice, and there is now a concrete
   candidate sitting in front of it.
3. **Depth knobs where a recipe can support one** (P4's honest follow-up): 11 of 12 modes have no way
   to run cheaper, so today "smaller team" is not a control the director actually has.

---

## 7. Session log

| Date | What happened |
|---|---|
| 2026-08-03 | Ledger opened. Delta audit (§3) + baseline measurement (§4) done. Documented `3914 green` claim disproved: 3 regressions found and fixed, entry-doc guard hardened and negative-controlled. Director reaffirmed D1 (all 7 phases) and D5 (really mount) after one objection each. |
| 2026-08-03 | **P1 shipped** (`c2b876c`): the rebuildable projection — dual-state model, `.workbench/` FTS5 store, read-only indexer, generated home pages, 7 verbs. Found 3 defects: the vault count was blind to 47 pages (~10%), `pending_director_decisions` never reached a report, and search broke on a hyphenated phrase. |
| 2026-08-04 | **P4 shipped as seat accounting** (`tools/worker_census.py` + `workbench team`, 17 tests). The memo's 120/37 split is now VERIFIED in code; its dormant-worker premise is REFUTED (0 of 163 unreachable). Real findings: the roster is a ceiling — 168 declared vs 153 recipe-dispatched, 15 council-only across 3 modes (now disclosed on the outcome cards); only 1 of 12 modes has a real depth knob, so a pruning policy would have claimed a control that does not exist; and `research-orchestrator` is now pinned as the only recipe-dispatched name without a subset, closing a silent way past `agent_subset` permission scope. Automatic seat pruning deliberately NOT built — the "redundant" seats are the independence machinery. |
| 2026-08-04 | **P3 shipped, text-only**, after the §5 five-item restatement was read out and answered. Review root found deleted → re-fetched at the pinned commits; 43/43 receipts re-verified; 8 sources / 358 bundles / 2604 files / 25.9 MB vendored read-only; 815 files / 14.5 MB skipped and counted; drawio excluded. The lock's contradicting `copy_policy` is now reconciled by an explicit `text_vendoring` record instead of a silent override. **Root repo created** (`e4d77db`, director option ①) — the operating manual and doc centre have history for the first time. |
| 2026-08-04 | **P5 + P6 + P7 shipped — the 7-phase scope is closed.** P5: the council's authoring template (derived from schema + contract, so it cannot drift), a director-facing rendering that is the deliberate opposite of the blind one, and the 4 CLI verbs its output side never had. P6: a REPLAY of the recorded example — 22 checks, 0 executions — plus the finding that **the example was never in version control** while 8 tests required it (87 files now tracked, secret-scanned). P7: governance measured over 32 real runs — 8/12 modes, **50/163 seats**, 0 recorded gate firings, 22 guard tools `unmeasurable` — and a refusal to slim anything, since that is the director's call. Four defects found: `--out` in the council CLI had **never worked** (`write_text(newline=)` is 3.10+, host is 3.9, no test ever passed it); `obs.jsonl` reads like a dispatch log but undercounts 50→7; `run_completed` is written for 2 of 31 finished runs; and `PLATFORM-FACTS.md` §0 had no numeric guard and already claimed 225 test files when 222 existed. My own earlier hand-count of "54 seats" was wrong (it counted 4 non-seat bundle kinds) — the census says **50**. |
| 2026-08-04 | **P2.1 shipped** (`6d1b470`): the six outcome recipes + 2 workbench verbs + the brief cross-reference, 35 tests each negative-controlled. Director added **D7** (every role in `agents/` is a sub-agent — verified already true in-tree, now pinned). Found 3 more defects: the size column read "大工程" six times, the menu took 11.6 s (yaml re-parsed hundreds of times → cached, whole suite 456 s → 183 s), and **P1's workbench was in no entry document at all** — now in `docs/03` §0.5, `docs/README`, `PLATFORM-FACTS` §0, the CLAUDE.md access map and the SKILL. Also found, not fixed: §4.2, the project root's `.git` is empty so the operating manual and doc centre are unversioned. |
| 2026-08-04 | **First live end-to-end run after scope closure** — `ingest_paper` driven for real (§8). Moved the machine's own telemetry 32→33 runs, 8→9 of 12 modes, 50→52 of 163 seats, proving `workbench governance` measures rather than reports constants. Three defects found by running rather than reading (§8.2). A `/promote-to-vault` candidate now exists for the first time in 33 runs. |

---

## 8. Live-run verification 2026-08-04 (post-scope-closure)

**Why this run and not a heavier one:** `ingest_paper` was one of the 4 modes with **zero** recorded
runs, so driving it tests dispatch for real; re-running an already-exercised mode would only replay a
known-good path. 2 seats / 2 stages / 4-hop ceiling — the cheapest never-run mode.

Run: `runs/petct-residual-correction/ingest_paper-20260803T230717Z`, status `done`, 8 hash-chained
ledger events. Source: `01-raw/papers/petct-residual-correction-2026-07-04/2025_AutoPET_IV_Interactive_Lesion_Segmentation_arXiv_2508.21680.pdf`.

### 8.1 What the run proves (each checked, not assumed)

- **Workers really read their source.** I computed the PDF's sha256 **before** dispatch and withheld it;
  both seats independently returned `f542ef8bed6d3e2f891ee69183671d3d753df24d3e3d503c2c7e0a5b772a9f57`.
- **Wave gating is real.** `begin` released wave 1 only; wave 2's prompt was withheld until wave 1's
  bundle existed. `run-dets` is a *preview* (`dispatch_authorized:false`, `scheduler_receipt:null`);
  `operate worker` is the *authorizing* verb (writes the receipt). Not a contradiction — verified in
  `panel_scheduler.py:1004,1017`. I flagged it as a suspected bug first and was wrong.
- **Honesty is enforced by code, not by asking.** The independent verifier judged
  `NEEDS_DEEP_READ`; the deterministic producer then cut claims **15 submitted → 14 retained**.
- **The cut claim was a genuine catch**: the paper's abstract says EDT beats Gaussian "across all
  metrics", but its own Table 1 shows Gaussian σ=0.25 (FPvol 8.39 last) beating 4 EDT rows including
  the Dice-best (8.50). Also verified: no ensemble row and no test-set metric anywhere in the paper,
  and a `6,14` comma typo in Table 1 that deterministic parsing must normalise to 6.14.

### 8.2 Three defects found by running (all still OPEN)

1. **`ingest_paper` has no document input.** The mode's entire job is reading one local file, yet
   `begin` has no `--doc` and `fulltext-pre` returns `mode 'ingest_paper' has no fulltext_pre step`.
   The path can only reach the worker out-of-band, via the orchestrator's dispatch text.
2. **The receipt's declared read boundary understates reality.** `source-claim-verifier`'s prompt
   orders it to read the extractor bundle, but that bundle is a *barrier-only* dep, so
   `panel_scheduler.py:697` records `readable:false` with `allowed_inputs:[]`. With
   `os_read_sandbox_enforced:false` nothing detects the mismatch. Provenance accuracy, not correctness.
3. **Capability-overlay routing is coarse.** Both seats got the `dicom_data_audit` lens injected for a
   *read-a-PDF* task — matched on the project's domain (PET/CT), not on the task. Noise, not error.

### 8.2b The vault-write path, walked for the first time in 33 runs (2026-08-04)

Director invoked `/promote-to-vault` explicitly. Admitted through the **document lane** (not the
frozen-result lane): `02-wiki/papers/rokuss-2025-interactive-lesion-segmentation-petct.md`, with
`00-system/index.md` + `07-logs/log.md` appended per vault write discipline. The page carries
`owner: promote-to-vault-document-gate`, an admission-id + source sha, and **no** `result-status` /
`can-cite-thesis` — exactly what the two-lane split promises.

Three things the first firing exposed, none of which any amount of reading would have found:

1. **The gate REFUSED the first attempt** — `paper metadata.relevance is invalid`. The gate's enum is
   `{direct, adjacent, background}`, but the vault's own 21 existing paper pages use **five** values
   (direct 9 / core 6 / supporting 4 / adjacent 2): **10 existing pages carry a value the gate would
   reject**, and the vault's `schema-contract.md` only names the field, never its enum. I hit it by
   copying `supporting` off a real page. Not fixed here — the vault's contracts are read-only to the
   machine and reconciling them is the director's call.
2. **Tamper detection fired for real.** Editing the staged source after the candidate was built made the
   second attempt fail with `source_ref.sha256 mismatch (stale or forged source)`. The candidate builder
   also refuses to overwrite an existing batch, which is what surfaced it.
3. **The document lane wrote the vault but no ledger event**, so `workbench governance` still read
   "promote 事件为 0" while a page had just been written. Fixed (§8.2d).

### 8.2c Director lock 2026-08-04 — the status bar

*"这东西我都不知道什么时候用它，什么时候摁它."* Shipped `reporting/status_bar.py` + `workbench gates`
+ `/gates` + auto-append to `operate brief` / `operate report` + a new rule 4 in the orchestrator SKILL's
铁律 so every director-facing report carries it. Five lines: project progress · **which command to press
now** · which gates are not due and what unlocks them.

Derived, never typed: gate→unlocking-mode comes from `outcome_recipes` scanned across **every depth
variant** (default-only would have missed that `deep_ideation` also unlocks `/idea-bet`); gate names from
`plain_words.known_gates()`; pending state from the runs' own manifests. Index-free on purpose — it is
the verb a lost director runs first, so it must not require a `reindex`. 13 tests, each with a negative
control, incl. *no button is invented when nothing is waiting* and *the bar stays ≤6 lines*.

### 8.2d Three more CLI surfaces (2026-08-04)

| Verb | Answers | Honesty property |
|---|---|---|
| `workbench gates` / `/gates` | 现在该按哪个命令，每个关卡什么条件才触发 | 没有待办就明说"现在没有要你按的"，绝不编下一步 |
| `workbench map` | 研究链条断在哪一环 | 只认 `[[wikilink]]`；「断了」= 没找到链接 ≠ 没做过。**Measured: 19 ideas in `petct-residual-correction`, 15 with no experiment; 4 experiments, 0 with a result; 0 of the vault's 110 results bind to this project.** |
| `workbench capabilities` | 8 源 358 份上游 skill 原文可搜可定位 | 每个渲染面都带「只读原文，不是能力」；模块被测试断言无 subprocess / urllib / exec / write 路径。Derived bundle counts match every source's upstream-declared count (98/98, 45/45, 158/158 …) |

Plus the governance fix: the document lane now appends a **`document_admission`** ledger event —
deliberately a different `event_type` from `promote`, because collapsing them would let a reviewed
Markdown copy be counted as a citable result — and `governance_census` counts vault writes from the
gate's own record files, which works retroactively for the admission that predates the event.
The gates axis now reports `promote-to-vault` as exercised, and the pre-existing test that pinned
"this axis must stay empty" was **strengthened, not loosened**: a text mention still must not count
(negative control), only the gate's own deterministic record file does.

Suite after this round: **4127 passed, 5 skipped, exit 0** (192 s). `PLATFORM-FACTS.md` §0 counts
re-derived: tools 143→145, test files 226→228, workbench verbs 11→14.

### 8.2e `new_direction` RUN FOR REAL — the last zero-run mode, and what running it exposed (2026-08-04)

Run `new_direction-20260804T052848Z`, project `petct-residual-correction`. Counted off the scheduler
receipts (`inbox/panel-scheduler/{DISCOVER,IDEATE}.json`), not from memory: **8 LLM dispatches / 7 distinct
roles over 7 waves** — DISCOVER 3 waves (scout · [formalizer + contradiction-miner] · formalizer again for
the mechanism graph) + IDEATE 4 waves (hypothesis → tournament → collision → experiment-planner). Both
stage gates PASS, run **paused at the IDEATE director gate** exactly as designed. Product: 7 ranked
directions in `director-review/ideas/`, `cut_ids: []`.

**The registry's "13 seats" is distorted in BOTH directions** — worth stating plainly, because the number
appears in the director-facing card:
- **6 of the 13 named roles never ran an LLM at all** (`future-work-miner`, `gap-classifier`,
  `novelty-scorer`, `evidence-verifier`, `citation-integrity-auditor`, `feasibility-reranker`).
  Deterministic producers do that work and sign the artifact under the role's name
  (`new_direction.py:662,669,698,701,708,853`). Reading "13" as "13 agents get dispatched" overstates by
  ~46%.
- **2 roles that are NOT in the 13 produced artifacts**: `idea-evolver` (evolved-ideas, idea-lineage) and
  `goal-alignment-checker` (drift-verdict).
- One role ran **twice** (`mathematical-formalizer`, for FORMALIZE then MECHANISM).
`reporting/outcomes.py:26-31` already refuses to call the roster a promise ("席可上场", never "会派"), which
is the right instinct; the roster is nonetheless not a count of anything real.

**What the run proves.** The spine, the wave scheduler, the drift gate, the tournament, the independent
collision gate and the director pause all work on a real request end to end. Two behaviours were better
than advertised: `mathematical-formalizer` **refused to open two files not in its `scheduler_contract`**
(nothing would have stopped it — self-restraint, see defect 4 below), and every seat that hit a
schema/template conflict emitted the *schema's* name and reported the deviation instead of silently
producing an artifact its own validator would reject.

Suite after this round: **4132 passed, 5 skipped, exit 0** (212 s) — 4127 plus the 5 regression tests
the two fixes below required.

**Six defects, all found only by running. Three now FIXED, three OPEN.**

1. **FIXED — the after-report's director-gate branch was dead code.** `reporting/progress.py` compared
   `status == "awaiting"`; `operate/spine.py:270` writes **`awaiting_director`**. So on the live path the
   one sentence the director most needs ("this is yours to sign, press `/idea-bet`") never rendered, §1
   said "还没写出结论" for a run that had a full product, and the raw enum `awaiting_director` leaked into
   §2. The test that should have caught it (`test_progress_flags_a_run_waiting_on_the_director`) passed
   **against a status the engine never writes** — a green test guarding a fictional path. Fixed with the
   real enum, a derived gate name (reuses `status_bar.gate_prerequisites()`, so the two can never
   disagree), and a paused-run headline. 4 new tests, incl. a no-bare-enum guard.
2. **FIXED — the status bar pointed at the wrong run.** With two runs paused on one gate it took
   `hits[0]` from a **path-sorted** glob, so immediately after finishing a run the director was sent to an
   older one and the run they had just watched was invisible. Now newest-first by `updated_at`, and a
   queue of >1 is disclosed rather than dropped. 1 new test with path order and time order deliberately
   opposed.
3. **OPEN — a Chinese request silently poisons the retrieval corpus.** `pre-search` with the director's
   own Chinese sentence as the query: **16 candidates → 2 accepted**, and both accepted rows were
   *Chinese figure captions from a Russian radiology journal*, while 14 real English candidates were
   rejected by `multilingual_query_title_lexical/v1`. The same run with 6 decomposed English scholarly
   queries: **182 candidates → 122 accepted**. The `--query` flag exists and fixes it, but the DEFAULT
   path (director types Chinese, which §0 of the global config *tells* them to do) degrades 61× with no
   warning. A thin-corpus warning is not enough here: the bundle was not merely thin, it was off-topic.
4. **OPEN — declared read scope is RECORDED, not ENFORCED.** `os_read_sandbox_enforced: false` on every
   packet. This run is the proof: one seat honoured its contract voluntarily and nothing in the machine
   would have noticed otherwise. Provenance accuracy, and it is now measured rather than assumed.
5. **OPEN — honest code, dishonest surface: the grounding gates are softer than the report reads.**
   All CONFIRMED by reading the code and re-running the checkers, not from a summary:
   - `new_direction.py:678` calls `run_existence_gate(..., [])` with a **hardcoded empty list**, and
     `build_existence_verdict([], ts)` → `verdict: PASS`. The choice is deliberate and documented in the
     comment right above it ("strict existence replay remains part of vault promotion rather than
     ordinary idea delivery") — so this is **not a coding bug**. The defect is on the SURFACE: the run
     report prints `existence_gate: PASS` and the menu prints "prior-art collision retrieval was grounded
     for this run", and a director reads both as "the citations were checked".
   - This run performed **zero external lookups**: `inbox/citation-cache.sqlite` `lookups` table = **0
     rows**. IDEATE has no existence verdict at all. So the 23 arXiv/Crossref refs the collision seat used
     to *haircut three ideas' novelty* rest entirely on that seat's self-report.
   - `evidence_gate` runs its legacy branch when a bundle carries no `evidence_contract_version` (this
     run's did not), and then reads `n_strong` and `saturation` straight off the worker's own
     self-declared `claim_support` / `saturation_reached`. Three fabricated sources self-marked "strong"
     PASS.
   - `citation_gate` derives `resolvable_refs` from the **same** worker bundle it is checking
     (`_shared.py:418-420`), so it proves internal consistency, not existence. Fabricated-but-consistent
     PASSes; an empty `claim_list` PASSes.
   - The north-star drift gate is a **soft** gate: this run's `anchor_coverage` was 0.375 against a 0.4
     threshold and still `pass: true` — low coverage only warns; only an out-of-scope hit or *zero*
     coverage blocks. (The code says so honestly; the report's "PASS" does not.)
   The one gate that is genuinely **earned**: vault-slug existence. All 6 slugs were checked against real
   files in `02-wiki/papers/`, and `operate/artifacts.py:62-64` validates every artifact before writing.
   Fix direction (not yet done): an empty check set on a stage that cited external work must not render as
   `PASS`; and the menu must not say "grounded" on the strength of a worker's own claim.
6. **FIXED — a worker packet asked for a key its own schema bans.** `operate/modes/_deep_ideate.py`
   told the contradiction seat to emit `detail`; `schemas/contradiction_report.schema.json` sets
   `additionalProperties:false` and names the field `description`; `produce_contradiction` passes
   conflict dicts through **verbatim** (`_deep_ideate.py:473`), and `research_brief_markdown.py:113,392`
   reads `description`. So an obedient worker produced an artifact the machine's own validator rejects,
   and the brief's blocker line rendered blank. Template corrected + 2 guard tests that pin the CLASS
   (packet keys ⊆ schema keys; renderer keys ⊆ schema keys), verified to fail against the pre-fix text.
   **Two sibling reports were checked and are NOT defects** — worth recording, because both were
   reported as defects by the seats that hit them and only reading the projection code settled it:
   the tournament's `rationale` is synthesized into the schema's `rationale_ref` by
   `new_direction.py:801`, and the 9 experiment-sketch keys are validated by the memo contract and then
   filtered by `produce_experiment_sketches`. A worker hitting a two-layer contract cannot tell the
   difference from the inside, which is why all three read as bugs to the seats.

### 8.2f Adversarial cross-review of that run (3 independent lenses, 2026-08-04)

Three reviewers, none of which produced the material, on rigour / governance / executability. They did
not soften the run — they **materially demoted its headline**, which is the point.

- **The #1 direction's central number is imported from someone else's paper.** Its whole framing rests
  on "the anisotropic `[3, 2.04, 2.04]` mm grid". `2.04` appears **nowhere** in this project's own data
  records — only in `director-approved/paper-admission-20260804/rokuss-2025-…md` (ingested the same day)
  and a reference audit of that same external paper. The project's own measured spacings are three, with the
  anisotropy sign REVERSING between them (`director-review/deploy-20260802/00-WAVE1-EXECUTION-REPORT.md:166`:
  `4.073×4.073×2.0` ×418 · `2.734×2.734×3.27` ×386 · `4.073×4.073×5.0` ×208), and decision
  `D-2026-08-02-01` deliberately measures in **pixels, not mm, because spacing varies per scan**. The
  idea's "state the envelope in millimetres, not voxels" is thus the exact inverse of the project's own
  ruling, and its per-axis mechanism claim and `d* ≤ 3 mm` threshold are not commensurable across the
  cohort. CONFIRMED independently by the main thread, not accepted from the reviewer.
- **The mechanism and the evidence are different objects.** The card's mechanism is "discontinuities
  exactly at component surfaces"; the 38 % knife-edge it cites is the `far_slice.any()` rule at the
  **15 mm ring** (`docs/03-INTENT-ONTOLOGY.md:189`). The ring travels with the scribble, so a
  displacement *inside* the bound component can flip extent — which trips the card's own
  "within-component control > 10 %" failure threshold and would kill the audit on a correct result.
- **A quoted ceiling is arithmetically wrong.** "structurally-free ceiling 263/739 = 35.6 %" is one
  policy's score, not a ceiling: a free-polarity best-constant policy reaches 139+164 = **303/739 = 41.0 %**.
- **"Runnable today" is false on this machine: 0 of 7.** Every sketch claims CPU-only over frozen
  artifacts, but the corpus, the 1012 residual masks and the binding code are all on `server.honor.gpu`;
  `projects/…/scripts/` and `results/` are **empty directories**. What is local is *receipts about* the
  data. Also: `binding_sha256 607dc957…` is a **data**-binding receipt, not a hash of the binding *code*
  the sketches say they will re-run; the component census says `cases_with_any_component` = **486**, not
  the 506 all seven sketches quote, and is sourced from run **R2**, not R3. Honest effort estimate from
  the project's own timings (2827 s for one full binding pass, `N-TASK-LEDGER.md:75`): ES-2 S2 ≈ 15 CPU-h,
  ≈ 90–110 CPU-h with the S3 arms — and the "70.01 MB, laptop scale" figure is the episode-document
  footprint only, excluding the masks the re-derivation actually needs.
- **The one place the machine was STRONGER than it claimed**: the 91-case locked exam really is
  structurally untouched — partitioned into `cohort.excluded` with `test_access_receipt_sha256: None`
  before any read, and R3 ran `--partitions train val`. A naive re-implementation would not stumble into it.

**Governance verdict: PARTLY REAL** — and the two halves are worth separating, because they fail
differently.

- **What is genuinely enforced** (each re-run, not read off a summary): the artifact schema layer
  (`artifacts.py:62-64`, validate-before-write); vault-slug existence; the collision gate's *cut* path,
  which is real code — a synthetic finding drives `build_collision_verdict` to `cut_ids:['IDEA-1']`, and
  downgrading only its existence field to `lookup_error` flips it to UNVERIFIED instead of a cut, exactly
  as specified; and the rule that **a novelty SCORE can never cut**, which holds structurally — the
  function's signature takes no score parameter and `novelty_score` is a side artifact never passed in.
  The tamper-evident chain also works: `ledger.jsonl` hash-chains each event, `step_done` records the
  byte-sha256 of all 25 typed artifacts, `manifest.yaml:last_boundary_hash` anchors the tail, and editing
  one artifact in a copy makes its recorded hash mismatch at the next gate reconciliation.
- **What is weaker than the report reads**: see defect 5 above, plus two structural limits.
  **(i) The cut was structurally unreachable THIS run** — not because the gate is fake, but because with
  0 external lookups every `_ref_exists` returns False, all 7 findings were `adjacent` with 0
  `colliding_papers`, and `full_text_reviewed` was false everywhere. "0 cut" this run therefore carries no
  information about novelty. **(ii) The tamper-evidence perimeter excludes its own inputs**: the 8
  `inbox/*.bundle.json` (the gates' ONLY inputs) and the 8 `director-review/*.md` (the 221 KB menu the
  director actually reads to place a bet) are hashed nowhere, and the whole chain lives inside the
  gitignored run directory with no external anchor — so anyone able to write that directory can rewrite
  artifacts, ledger and manifest into a self-consistent whole.
- **Read scope is RECORDED, never ENFORCED** (defect 4, now pinned to a line):
  `panel_scheduler.py:718` hardcodes `os_read_sandbox_enforced: False` and says so; the project's
  `PreToolUse` hooks match only `Write|Edit|NotebookEdit|Bash`, and no hook mentions `Read`/`Grep`/`Glob`.
  Nothing could have stopped the seat that abstained, and its abstention is not even recorded — so
  "I deliberately did not open those two files" is **UNVERIFIABLE** from the receipts, in either direction.
  Treat it as good manners observed, not a control proven.

**Capability gap this exposes (new, not previously on any list):** the machine has **no local-data
availability check**. It will happily emit, gate and rank a "zero-GPU, runnable today" experiment plan
whose inputs are not on the machine. The honest label for all 7 sketches is *design-complete,
data-absent*, and the machine cannot currently derive that label itself.

**One methodological note for future rounds.** Of the three template-vs-schema "defects" the seats
reported from the inside, **one was real and two were two-layer contracts working as designed** — and
only reading the projection code settled which. A worker cannot tell those apart from inside its own
packet, so a seat's self-reported "the machine's template is wrong" must always be verified against the
projection layer before it enters this ledger.

### 8.2f-1 Strength assessment of the ideation itself — honest ceiling, and three more defects

**Honest ceiling: a competent PhD student's proposal shortlist.** Not a brainstorm (the machine attacked
its own strongest idea — `RANKING.bundle.json#tournament[7]` demotes IDEA-1 because its primary endpoint is
"close to entailed by its own construction", and EV-2 repairs it with an endpoint that can fail; that is
supervisor-grade criticism). But not a peer contribution either: all 7 directions are zero-GPU measurement
/ validity audits with **no new method, loss or architecture**, the machine's own breadth score is
**0.000 for all 7**, and the whole evidence base is **6 sources / 3 strong**.

Three further defects, each CONFIRMED against the run's own files:

7. **OPEN — two producers in one stage contradict each other on evidence saturation.**
   `evidence/DISCOVER/evidence-saturation-report.artifact.json` → `rounds: 1`, `coverage_dimensions: []`,
   `saturation_score: 0.0`, `verdict: INSUFFICIENT_DATA`. Same stage,
   `evidence-verdict.artifact.json` → `saturation_reached: true`. The gate reports the optimistic one.
   Saturation was therefore **never measured** in this run — and the earlier `deep_ideation` run shows the
   identical pattern, so the "measured evidence saturation" that `deep_ideation` advertises over
   `new_direction` is not being measured in either.
8. **OPEN — the depth metric is saturated and cannot distinguish a deep graph from a shell.**
   `tools/idea_quality_eval.py:122-148` caps its depth credit at 8 nodes / 8 edges, so this run's
   31-node / 38-edge mechanism graph scores `depth = 1.0` — exactly the same as the 8/8 graph of the
   2026-07-14 run. A metric that maxes out an order of magnitude below the real output measures nothing.
9. **OPEN — two deep artifacts are written and then never read.** The problem abstraction (PA-001: 6
   primitives / 8 failure modes / 10 constraints / 9 metrics) is cited **0 times** by `IDEATE.bundle.json`,
   and the mechanism graph's node ids are cited **0 times** by any downstream bundle, sketch or the menu.
   By contrast the contradiction report is genuinely load-bearing (CF-x cited 7× in IDEATE, 4× in
   hypothesis-set, 3× in EXPERIMENT, 4× in the menu — and it is what produced EV-2), and the experiment
   sketches are cited 106× in the menu. So the deep chain is real where it is read and decorative where it
   is not; the fix is to make the graph's intervention points cite-able rather than to delete them.

**Breadth, measured**: 6/6 gaps received an idea, but clustering the 7 by what they intervene on gives 5-6
clusters **all inside one layer** (endpoint instrumentation · label-definition stability · task
well-posedness · annotation reliability · confound test · reportable population). Ranking discrimination is
real (Elo spread 1061.73 → 940.32, fully transitive, no cycles, per-pair rationales specific) but two of
six scoring dimensions are near-degenerate (`importance` and `mechanism_coherence` only ever take {4,5}).

**What the un-run REPORT stage actually costs**: less than it appears — the blind pairwise numbers are
already computed inline (`tools/idea_bet_markdown.py:308`) and printed in the menu appendix. The real loss
is that **nothing aggregates the two soft warnings**: `anchor_coverage` 0.375 (below the 0.4 advisory) and
saturation `INSUFFICIENT_DATA` appear **zero times** in the 221 KB menu the director reads. The director
sees a clean "grounded" menu and cannot see that north-star anchor coverage was under 40% and saturation
was never measured.

### 8.2f-2 The vault write-guard is REAL but was UNARMED for every seat in this run (2026-08-04)

Tested directly against the hook, not inferred:

```
# fenced (RAT_RUN_ID set)   -> exit 2
[permission-scope-guard] BLOCK: cannot write the vault directly (promote via the human gate)
# unfenced (RAT_RUN_ID unset) -> exit 0, no output
```

`hooks/permission-scope-guard.js:109` returns `exit(0)` — a deliberate NO-OP — when `RAT_RUN_ID` is unset,
and the mechanism is documented that way in `.claude/settings.json`'s own `_comment`. **`RAT_RUN_ID` was
unset for the whole session**, so all 8 worker seats dispatched today ran with the vault block inactive;
nothing mechanical would have stopped a worker from writing `02-wiki/`. Nor is arming it part of the
procedure: no file under `.claude/skills/` or `docs/` mentions `RAT_RUN_ID` — the operating entry tells the
dispatcher to spawn "with the printed model + prompt" and nothing more.

Compounding it, the **vault's own** two write-guard hooks (`AI agent database/PhD-Research-OS/.claude/
{settings.json,hooks/schema-write-block.js,hooks/write-time-lint.js}`) sit in a subdirectory; Claude Code
loads settings from the project root, the user scope and managed scope — not from arbitrary nested folders
— and the project root's `settings.json` wires only the two machine-side hooks. So of the two protections
`CLAUDE.md` §5.2 names ("the DB's own write-guard hooks **+** the machine's permission-scope-guard"), the
first never fires and the second was unarmed.

Honest scope of the finding: nothing was written to the vault outside the gate this run (the one admission
went through `promote_gate.py`), and the guard's logic is correct — this is an **arming** defect, not a
logic defect. Two candidate fixes, both a director decision because they change a control's behaviour:
(a) make the vault block unconditional for `Write`/`Edit`/`NotebookEdit` (the `discoverVaultRoot()` helper
already works without env, so the check can move above the `runId` early return; Bash stays untouched so
the promote gate's own Python writes still work), or (b) keep it run-fenced and add the arming step to the
dispatch procedure — noting that a subagent inherits the session environment, so per-worker arming is not
actually available through the Agent tool and (a) is the only fix that closes it.

### 8.2g Director lock 2026-08-04 — an agent budget is per-mode, never a shared pool

Director's words: *"agents 预算上限也是不需要有共享的，而是独立按 modes 算的."*  Measured against the code,
this was **half already true and half violated**:

| Ceiling | Was it per-mode? | Evidence |
|---|---|---|
| `max_agent_hops` (initial dispatch) | ✅ already per-mode | Declared by all 26 modes and **mandatory** — `graph_spec.py:122-123` errors if a mode omits it. Values genuinely differ (2 … 24). `spine.py:135` computes usage from **this run's own** `completed_work`, and no budget code reads `--upstream-run`, so chaining modes never pooled a budget. |
| `max_supplement_agent_hops` (repair waves) | ❌ **was a shared constant** | `panel_scheduler.py` did `budget.setdefault("max_supplement_agent_hops", 12)`. Only `read_paper_deep` declared its own, so **25 of 26 modes silently inherited one number** — a 2-seat mode carried a 13-seat mode's repair headroom. |

Fixed by `_supplement_limit(budget, nodes)`: the mode's own declared value wins; otherwise the ceiling is
**derived from that mode's own panel** (one re-dispatch per seat it may schedule), never from a table and
never from a constant. 5 tests pin the rule, including a shape guard asserting the shared `setdefault`
does not come back, and a registry test asserting every mode still declares its own initial ceiling and
that the ceilings are not all equal (which would be a shared pool in disguise).

Worth recording alongside it, because it is the reason the lock looked violated in the run: **a "hop" is a
STAGE, not an agent.** `new_direction` shows `max_agent_hops: 10` against a 13-name `agent_subset`, which
reads like a contradiction; it is not — the mode has 3 stages, so it can spend at most 3 initial hops. The
name is misleading and `reporting/outcomes.py:26-31` already warns that the roster is a permission list,
not a dispatch promise. Renaming the field is not done (it is in the registry contract and in
`spec_hash`-adjacent surfaces); the honest fix taken here was to document the unit at both ends.

### 8.2h Hard capability census 2026-08-04 — every number re-derived, ~30 verbs actually invoked

Rule for this census: a capability counted as WORKING only if it was **invoked**. Nothing quoted from a
markdown file.

| Axis | Measured | Note |
|---|---|---|
| Modes | registry **26** · one-button **12** · spec-only **14**; the `operated:` flag mirrors `operate/modes/REGISTRY` with **0 mismatches** | A spec-only mode **fails closed**: `begin --mode ideate_ring` → exit 2, JSON error, **zero run dir created**. No silent half-run. |
| `workbench` verbs | **14**; 12 green, `open` needs args, `destroy` deliberately not run | **0 crashes** |
| `operate` read-only verbs | **13** green | **0 crashes** |
| Slash commands | 20 files → **24 distinct operate verbs, all present**; **0 dangling references** | 6 carry `disable-model-invocation` |
| Agents — three different numbers | **163** on disk · **157** reachable via some `agent_subset` (+6 control-plane = 163; **0 dangling, 0 unreachable**; of the 157, 120 belong to one-button modes and 37 only to spec-only modes) · **52 (32%) ever dispatched** across 34 runs | The three must never be conflated |
| Gates | 5 files, **1 ever exercised** | Frontmatter is INCONSISTENT: only `idea-bet`/`venue-pick`/`venue-decide` use `disable-model-invocation: true`; `promote-to-vault` uses `invocation-policy: explicit-top-level-user-skill`; `aers-reference-approve` has **no frontmatter at all**. All 5 do carry the flag in their `.claude/commands/` wrapper, which is the harness-enforced surface — so the control holds, but the gate specs do not state it uniformly. |
| Tools / tests / schemas | **145** tools (144 excl `__init__`) · **228** test files · **167** schemas · **4139 collected, 4139 passed, 5 skipped, exit 0** | `.claude/CLAUDE.md` was **stale** (137 / 217 / 3914) — corrected 2026-08-04 |
| Vendored upstream | `verify` → `ok: true, violations: []`; 8 sources / 358 bundles / 2604 files = 2591 `.md` + 6 LICENSE `.txt` + 1 own MANIFEST `.json` + 8 LICENSE, **0 scripts / 0 hooks / 0 MCP / 0 exec bits** | The "text only, structurally unrunnable" claim is **TRUE** |
| Profiles | **7** `.yaml`, loaded dynamically, consumed by 4 of the 12 wired modes | **One violation of hard rule 5**: `operate/modes/read_paper_deep.py` hardcodes ~8 medical-imaging strings (autoPET, TRIPOD+AI/STARD-AI) inside `operate/` instead of a profile. Conditional and defaults to `"not-applicable"`, so it is a layering violation rather than a live bug. |

**The single biggest wired-but-not-usable gap: the EXECUTE → result → citable chain has never produced one
real number.** Across all 34 runs the repo holds **10 run-records, 0 hash-manifests, 0 journals**, and every
run-record payload is `status: "planned", metrics: {}`. No frozen result exists anywhere. So
`/numeric-benchmark`, `/promote-to-vault`'s frozen-result path, `/venue-pick` and `/venue-decide` are wired,
tested and **structurally un-runnable** — not a bug, just no GPU run has ever happened. The vault has been
written exactly **once**, through document ingest; the frozen-result channel is still **0**. 4139 green
tests certify the plumbing; **none of them can certify a research finding.**

Minor: `tools.mechanism_council template <unknown-role>` refuses correctly but leaks a **raw Python
traceback**, where `operate begin` returns clean JSON for the same class of error. Cosmetic, but it is the
one place a director-facing tool prints a stack trace.

### 8.2i Director lock 2026-08-04 — worker output is FLOOR-bounded, and workers may read the upstream originals

Two director instructions, both answered with a measurement first.

**(1) "输出太少了 … 量大的输出，不要控制住."** The throttle was neither the model nor the schema — it was the
packet wording, and one run proves it. Inside `new_direction-20260804T052848Z`, same model, same 122-record
corpus:

| Packet instruction shape | Seat's output | What the reviewers said |
|---|---|---|
| **floor** — mechanism graph, ">=3 nodes and >=2 edges" | **31 nodes / 38 edges** | "substantive" (all three) |
| **cap** — evidence table, "sources 4-6" | **exactly 6 sources / 3 strong** | "too thin to support a novelty claim" |

Structurally nothing was stopping volume: only **14 of 167** schemas carry any `maxItems`, and **none** on
these arrays. So every closed range was converted to a floor with an explicit "no upper bound", and the
one anti-volume sentence ("fewer, sharper, defensible gaps beat a long shallow list") was replaced by a
**per-item** bar:

| Template | was | now |
|---|---|---|
| `new_direction` DISCOVER | sources 4-6 · claims 2-3 · signals 4-6 | **≥12 · ≥6 · ≥8** |
| `new_direction` IDEATE | "Emit 3-5 hypotheses and 3-5 ideas" | **≥8 · ≥8** |
| `evidence_review` | sources 4-8 · claims 2-4 | **≥12 · ≥6** |
| `deep_research` / `evidence_deep` | sources 5-10 | **≥20** |
| `gap_breadth` (per hunter) | 2-4 signals | **≥6** |
| cross-domain analogy | "Emit 1-3 mappings" | **≥4** |

**The grounding bar was NOT relaxed** — that is the safety floor, not a style point: every source must
still exist, every `[[slug]]` is still hard-checked against the vault, every gap must still be individually
defensible and genuinely open. Volume opened; honesty did not. 23 tests pin it, including a cap-detector
verified to fire on the real pre-lock strings (a guard that cannot fail is not a guard) and a
"never tell a worker to keep the list short" phrase ban.

**(2) "现在的 research team 的能力是不是已经可以使用外部那些仓库 skills 的能力了？你实测过了吗."**
Measured, and the honest answer was **no**: 358 vendored bundles → **11 overlay summary cards** (~842 chars
each) → what a worker actually received was **two lines** of our paraphrase, flagged
`advisory_only: true, external_skill_execution: false, allowed_use: internal_checklist`. And **no packet
anywhere named the vendored originals** — grep over `operate/` and `agents/` returned nothing — so a worker
could not consult what an upstream skill actually says even though 2591 markdown files sit on disk,
read-only. (Today's routing was also coarse: both DISCOVER seats got a DICOM-audit lens for a read-papers
task — already recorded as defect 3 in §8.2.)

Fixed by `_UPSTREAM_ORIGINALS_POINTER`, now rendered in every packet that carries an overlay plan: it names
the path, names `workbench capabilities <keyword>` as the way in, and carries the boundary with it — READ
it, never execute / install / treat as a tool / let it re-scope the assigned output. Verified against the
real run directory: the pointer renders and `external_skill_execution` stays `false`. **This closes the
"reference the external repos" gap without moving the execution boundary one inch** — the 358 bundles are
still text, and the machine's capabilities are still `mode_registry.yaml` + `agents/`.

Suite after both: **4162 passed, 5 skipped, exit 0**.

**Not done, and it is a director decision** (measured cost, so it can be decided rather than debated):
making the 163 roles into *natively dispatchable* fixed roles needs (i) moving them under `.claude/agents/`,
(ii) adding a `description:` to all 163 — **0 have one today** and it is required, (iii) fixing 3 files that
declare `model: none`, an illegal value. No blockers: names are unique, lowercase-hyphen, and collide with
none of the ~90 user-scope agents. The real price is 163 descriptions living permanently in the Agent-tool
listing of every session in this project.

### 8.3 Current pointer after this run

The 7 phases stay closed. Newly true: the machine has been **operated**, not just tested, since scope
closure — and as of §8.2e **every one of the 12 wired modes' outcome-menu row 1 has now actually run**.
Done since the last pointer: ① `/promote-to-vault` walked (§8.2b); ② `new_direction` run for real
(§8.2e) and adversarially cross-reviewed (§8.2f).

Open, in the director's court:
1. **The vault's `relevance` vocabulary vs the promote gate.** The vault uses 5 values, the gate accepts
   3; 10 existing paper pages would be rejected today. Unifying them is a vault-contract change, and the
   vault contract is read-only to the machine.
2. **Whether to fix the 3 open defects in §8.2e** — the Chinese-query retrieval poisoning (3) is the one
   with real scientific consequences; the empty-check existence gate (5) is the one that most misleads
   a reader; (6) is already fixed.
3. **The missing local-data availability check** (§8.2f): the machine ranks "runnable today" plans whose
   inputs are not on the machine. Either add the check, or a director-gated read-only pull of the
   R3 corpus + binding code so the label becomes true instead of just honest.
4. The memo's Project-Home tabs *Research Map / Experiments / Results&Figures / Writing* were never built
   (7 of 9 sections exist).
5. P3 remains text-only by D5-as-answered — 2606 vendored files, 0 runnable — the largest single
   divergence from the memo.
