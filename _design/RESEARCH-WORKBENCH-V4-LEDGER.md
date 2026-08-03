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

---

## 5. Before mounting the upstream repos (D5) — the decisions being reversed

Must be restated to the director at mount time, then executed per D5:

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
| P2.1 | Six Outcome Recipes as the user-facing layer | TODO | on top of the existing plain-language routing table |
| P3.x | Really mount the nine sources (D5) | TODO | restate §5 first |
| P4.x | Director additions over the existing router | REBUILD | smallest-sufficient-team policy; dynamic dispatch of dormant workers |
| P5.x | Compiler additions over the existing council | REBUILD | the memo's soft output template |
| P6.x | Re-run the example project end-to-end | REBUILD | dry-run only; never dress a dry-run as a GPU result |
| P7.x | Governance slimming | TODO | last, and telemetry-driven |

**Current pointer:** P1 is shipped. Next is **P2.1** — the six Outcome Recipes as the
user-facing layer, built on top of the plain-language routing table the 2026-08-01 round
already added (do not replace that table; the recipes sit above it). After that P3 needs the
§5 restatement to the director before any mount happens.

**Unverified premise still open:** the memo's "157 workers, 120 used by operated modes, 37
spec-only". The 157 figure is corroborated by the 08-01 round; the **120 / 37 split is not
verified** and no policy should rest on it until a real cross-reference of
`mode_registry.yaml` × `agents/` is run.

---

## 7. Session log

| Date | What happened |
|---|---|
| 2026-08-03 | Ledger opened. Delta audit (§3) + baseline measurement (§4) done. Documented `3914 green` claim disproved: 3 regressions found and fixed, entry-doc guard hardened and negative-controlled. Director reaffirmed D1 (all 7 phases) and D5 (really mount) after one objection each. |
