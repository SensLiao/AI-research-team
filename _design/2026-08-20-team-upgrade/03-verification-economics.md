# Audit 03 — Verification economics (Auditor C, 2026-08-20)

Directive being implemented (E1, verbatim intent): "hash 不要总去验证，没必要的" — stop routine
hash verification; hash/verify only where it actually protects something. Constraint: the
tamper-evident ledger and the honesty invariants are crown jewels and are NOT weakened here.

Operative principle this audit encodes (TU-2 in `_design/2026-08-20-team-upgrade/DECISIONS.md`):

> **Hash once at a boundary moment, record a receipt (hash + timestamp + what it covered),
> trust the receipt until the artifact set changes; never re-hash unchanged artifacts on a
> schedule or per report.**

Method note: everything below was read from source, and the two big offline verifications were
timed on this machine (read-only): `vendor_upstream_skills verify` = **0.41 s** over 2,604
manifest files; `example_replay` **cannot run in this checkout** (its recorded project
`projects/t4-scribble-m0-mechanism-eval/` is absent, so its 10 tests and the 5 T4-evidence
tests all SKIP — `PLATFORM-FACTS.md` line 27 still describes it as present: live-truth drift).
The 2026-08-07 de-governance already converted most *re*-verification into write-once or
informational behaviour; what remained routine in practice was **run-side habit** (deposit
root hash and colour sweeps re-run per report), not machine-loop cost.

Paths are machine-root-relative (`research_agent_teams/`) unless they start with `tests/`
(workspace root) or `runs/` (run store).

---

## Q1 inventory table

Bucket = where it actually runs **today** (as practiced). "Re-verifies unchanged?" asks whether
an invocation re-derives trust over artifacts that have not changed since they were last hashed.

### A. Per-stage/per-run — the engine's normal loop (worker → run-dets → commit)

| # | verification | file path | protects | cost | re-verifies unchanged? |
|---|---|---|---|---|---|
| A1 | Ledger append-time chain hashing (`chain_hash` on every event: run_started, task_frame_pinned, stage_started, step_done, boundary, gate_pending/resolved, resume, run_completed/failed/reopened, promote) | `tools/ledger.py` `append_event` → `tools/hash_artifact.py` `chain_hash` | the tamper-evident run history — crown jewel | <1s (one small canonical-JSON per event) | **No** — write-once; since 2026-08-07 appending never calls `verify_chain` first |
| A2 | Stage-artifact file hashing at commit (one `hash_file` per committed artifact, recorded in `step_done` + manifest) | `tools/runstore.py` `checkpoint_stage` (called from `orchestrator/engine.py` `_drive` and `operate/spine.py:167`) | binds each evidence file to the chain at its birth | <1s | **No** — write-once at the commit boundary |
| A3 | Task-frame pin (hash the direction contract once at run start) | `tools/runstore.py` `pin_task_frame` (from `orchestrator/engine.py:145`, `operate/spine.py:78`) | north-star cannot be silently rewritten (audit H2.3) | <1s | **No** — once per run |
| A4 | Upstream-handoff pin (hash the grounding manifest once at arrival) | `tools/runstore.py` `pin_upstream_grounding` | cross-mode handoff transport manifest | <1s | **No** — once per handoff |
| A5 | Artifact contract validation per stage (schema only — **not** a hash check; `output_hash` in the envelope is producer-stamped and never re-derived here) | `orchestrator/engine.py` `_validate_artifact_file` → `tools/validate_artifact.py`; envelope: `schemas/artifact_envelope.schema.json` (output_hash nullable) | artifact shape/contract | <1s | No |
| A6 | Scope-guard decide per write (not a hash check) | `tools/scope_guard.py` via `orchestrator/engine.py:104`; hooks `hooks/permission-scope-guard.js`, `hooks/artifact-contract-enforcer.js` (no hashing inside either) | write fences | <1s | No |

### B. Per-run at consumption boundaries (an artifact set changes hands)

| # | verification | file path | protects | cost | re-verifies unchanged? |
|---|---|---|---|---|---|
| B1 | Upstream-run completion check: `verify_chain` over the upstream ledger + REPORT boundary anchored in its manifest | `tools/research_plan.py:731` (`_upstream_completion_errors`) | a handoff can only consume a really-completed, untampered upstream run | <1s (tens of events) | Yes — but at the trust boundary where the consumer first touches it |
| B2 | Handoff-manifest consumption check: `verify_chain` + grounding file re-hashed against its ledger pin | `tools/research_plan.py:1078-1086` (`augment_worker_with_upstream`) | the transport manifest wasn't edited between pin and dispatch | <1s (one file) | Yes — single file vs recorded receipt, at consumption |
| B3 | DISCOVER-checkpoint bridge check: `verify_chain` before reusing a prior run's checkpoint | `operate/modes/deep_research.py:2230` | checkpoint reuse cannot launder a tampered prior run | <1s | Yes — at reuse boundary |
| B4 | Review-target authenticity: `verify_chain` + run_started(mode=manuscript_authoring) before an independent review run consumes a draft | `operate/modes/manuscript_review.py:277` | reviewer grades a real authoring run, not a planted tree | <1s | Yes — at consumption |
| B5 | Finalized-output resolve: recompute one file's sha256 against its recorded `output_sha256` receipt every time a repair lineage is resolved | `operate/output_versions.py:422-447` | a finalized correction cannot be mutated after finalization | <1s (one file) | Yes — single file vs receipt, at each consumption |
| B6 | LaTeX source-tree gate: re-hash the manuscript src set against the integration inventory (`SOURCE_CHANGED`) + toolchain identity hashes | `tools/latex_build.py:198-235, 393, 426` | integration→compile handoff: the build compiles exactly what the integrator wrote | <1s–seconds (small tree) | Yes — change **detection between two adjacent steps is its job** |
| B7 | Asset copy uses hash-checked bytes (copy-time, single use) | manuscript integrator (pinned by `tests/machine/test_manuscript_integration.py:852`) | figure/asset swap between check and copy | <1s | No — same bytes it just checked |

### C. Boundary/promote-time (write-once by design)

| # | verification | file path | protects | cost | re-verifies unchanged? |
|---|---|---|---|---|---|
| C1 | Promote-candidate hashing + admission-ledger append (`promote` / `document_admission` events); since 2026-08-07 the gate **no longer** re-verifies referenced audit files' sha256 | `tools/promote_gate.py:307,358,154,180`; `tools/promote.py:183`; `tools/document_promotion.py:769,818` | the seam: what entered the vault is exactly what the director saw | <1s | No — write-once at the gate |
| C2 | Director-reopen inbox digest (hash every worker bundle at reopen) | `operate/cli.py:537` (`cmd_reopen`) | reopen carries a snapshot of what stood at reopen time | <1s–seconds | No — once per reopen |
| C3 | Project-state snapshot payload hash | `tools/project_state_capture.py:529` | hash/time-bound state input for dossier review | <1s | No — once per snapshot |

### D. On-demand (director/cockpit-invoked)

| # | verification | file path | protects | cost | re-verifies unchanged? |
|---|---|---|---|---|---|
| D1 | Numeric benchmark recompute (metric recompute + run-journal gate = the real evidence gates; `hash_check` via manifest validator is **informational** since 2026-08-07, but the CLI still **requires** `--hash-manifest`) | `tools/numeric_benchmark_adapter.py` (cockpit `.claude/commands/numeric-benchmark.md`); `tools/hash_manifest_validator.py`; schema `schemas/numeric_benchmark_report.schema.json` (hash_check required) | claimed metrics recomputable from rows | seconds | No (recompute over current inputs) — but the mandatory manifest input forces a hash artifact to exist for every recompute |
| D2 | Live server hash-manifest as execution evidence (producer + validator) | `tools/hash_manifest_validator.py`; producer pinned by `tests/machine/test_server_hash_manifest.py` | GPU execution evidence import boundary | seconds (remote) | No — evidence is minted once at the execution boundary |
| D3 | Vendor tree verify — existence + no-stray-file walk; since 2026-08-07 **no content re-hash** (`sha256` kept as record fields only) | `tools/vendor_upstream_skills.py` `verify`; invoked by doc pointers (machine `CLAUDE.md` §10 "re-check with … verify", `tools/upstream_catalog.py:101`) and tests | text-only / cannot-execute property of the vendor tree | **0.41 s measured** (2,604 files) | Partially — walks the whole unchanged tree every call (stat-only) |
| D4 | Example replay (re-derive the recorded T4 collaboration; digest-binding stage deleted 2026-08-07, 5 stages remain) | `tools/example_replay.py` | recorded honesty example still derivable by current code | seconds when present; **currently cannot run** (project absent from checkout) | Yes when run — re-derives an unchanged recorded example |
| D5 | Integrity flagger over claims (unsupported numbers / missing-evidence refusal — advisory, no hashing) | `tools/integrity_scan.py`; runs inside `operate/modes/analysis_audit_panel.py`, `operate/modes/_deep_ideate.py` | numeric claims carry evidence refs | <1s | No |
| D6 | `verify_chain` as read-only diagnostic — **doc drift**: `tools/ledger.py` docstring says "workbench governance calls it", but `workbench/cli.py:260` → `tools/governance_census.py` never does | `tools/ledger.py` `verify_chain` | chain-health diagnosis | <1s | Yes when someone runs it |

### E. Per-build — machine test suite (runs when machine code changes)

| # | verification | file path | protects | cost | re-verifies unchanged? |
|---|---|---|---|---|---|
| E1 | Vendored provenance receipts re-hashed against real bytes (~45 files) + real-tree `verify()` walk | `tests/machine/test_absorbed_methods_and_fanout.py:115`; `tests/machine/test_vendor_upstream_skills.py:28` | catalog cards cite real vendored bytes | **1.34 s measured** (both files, 29 tests) | Yes — same unchanged tree every pytest run |
| E2 | Crown-jewel primitive pins (canonical JSON, chain tamper/reorder detection, lock sidecar, event types) | `tests/machine/test_hash_artifact.py`, `tests/machine/test_ledger.py`, `tests/machine/test_ledger_hardening.py` | the ledger core itself | <1s | N/A (synthetic fixtures) |
| E3 | `verify_chain(...) == []` as a post-condition on freshly created runs (~15 e2e/mode tests) | e.g. `tests/machine/test_engine.py:51`, `test_operate_spine.py:173`, `test_m1_end_to_end.py:215`, `test_mode_*_e2e.py`, `test_director_veto.py:43`, `test_promote_gate.py:81`, `test_document_promotion.py:140` | every code path still writes an intact chain | <1s each | No — the runs are created inside the test |

### F. Run-side (ref-free-seg-qa) — the E1 incident surface

| # | verification | file path | protects | cost | re-verifies unchanged? |
|---|---|---|---|---|---|
| F1 | Prose-vs-corpus check, pre-compile (citekeys resolve→corpus, orphaned floats, undefined count macros, eaten-backslash macros, label integrity, Outlook firewall, banned filler) — **not a hash check** | `runs/ref-free-seg-qa/deep_research-20260819T055022Z/tools/check_prose.py`, gated in `runs/ref-free-seg-qa/Ref_Free_Seg_QA_Review_v1.0/build.sh` pass 0 (exit 1; `SKIP_CHECK=1` escape) | the manuscript states what the corpus holds; caught the real D6-class bugs | seconds | No — checks *current* prose vs *current* corpus; the set changes every build by definition |
| F2 | Study-level number check, pre-compile (every number in a cited sentence vs the cited records; deliberately a REPORT, not a gate) | `.../tools/check_numbers.py` (build.sh pass 0, `--brief`) | hand-transcribed study numbers (caught sensitivity↔specificity swap) | seconds | No — same reason as F1 |
| F3 | Rendered-page check, post-compile (abstract 250-word cap, footer collisions, body target, placeholder declarations) | `.../tools/check_rendered.py` (build.sh tail) | constraints only the PDF can settle | seconds | No — checks the PDF just built |
| F4 | **Deposit manifest + root hash** — 204 files / 4.0 MB, per-file sha256 + one root hash, printed into the article via `src/tab/deposit_numbers.tex` | `.../tools/mkdeposit.py` → `.../DEPOSIT-MANIFEST.json` | deposit identity + completeness for readers (review §6.4) | ~1s wall-clock; the real cost is **receipt churn** — re-running mid-edit changes the printed root hash and burns an agent round per report | **Yes — this is the E1 habit**: re-run per report over a mostly-unchanged set |
| F5 | Colour/monochrome + pixel sweeps — **no script exists**; were ad-hoc per-report PDF pixel checks (E1; D5 retrofit) | (ad hoc; nothing under `runs/ref-free-seg-qa/Ref_Free_Seg_QA_Review_v1.0/qa/` — the dir is empty) | venue monochrome rule | seconds–minutes of agent attention each time | **Yes — per report, unchanged figures** |
| F6 | Corpus identity verify (PDF↔slug distinctive-word containment; quarantine optional) | `.../tools/verify_corpus.py` | a downloaded PDF is the paper its slug claims (B2 incident) | seconds (~121 PDFs) | Only if re-run over already-verified PDFs |
| F7 | Verifier regression pins — 6 real mismatches + real matches, both directions | `.../tools/test_verify.py` | the verifier itself has discriminative power (B2 lesson) | <1s | No — runs when the verifier changes |
| F8 | Citation metadata audits (preprint→published, DOI presence, year agreement, XML entities) | `.../tools/ref_audit.py`, `.../tools/fix_bib.py` | D4 bibliography defects | seconds | Only if re-run on an unchanged .bib |

---

## Q2 policy table

One test for every row: **does this invocation protect a boundary where the artifact set changes
hands or changes state?** If yes it earns its cost; if it re-derives trust over an unchanged set,
it becomes a receipt.

### KEEP — per-commit in the engine (crown jewel; explicitly retained by E1)

| verification | file path | justification |
|---|---|---|
| Ledger append-time chain hashing | `tools/ledger.py` `append_event` | write-once, <1s, the tamper-evidence itself; removing it would weaken a crown jewel — out of scope by directive |
| Checkpoint artifact hashing + task-frame / handoff pins | `tools/runstore.py` `checkpoint_stage`, `pin_task_frame`, `pin_upstream_grounding` | hashes are minted exactly once, at the artifact's birth boundary; they ARE the receipts everything else trusts |
| Promote-time candidate hashing + admission ledger | `tools/promote_gate.py`, `tools/document_promotion.py` | the seam's write-once receipt; already de-governed of its re-verification half |
| Reopen inbox digest, project-state snapshot hash | `operate/cli.py:537`, `tools/project_state_capture.py:529` | once per rare boundary event |

### KEEP — per-build (cheap, catch real bugs, and never re-verify an unchanged set)

| verification | file path | justification |
|---|---|---|
| Prose-vs-corpus + number check + rendered check | `runs/.../tools/check_prose.py`, `check_numbers.py`, `check_rendered.py` via `build.sh` | **not hash checks** — they compare current prose to current corpus, and a build exists because something changed; caught three real defect classes this week (D6 heredoc corruption, orphaned floats, the sensitivity↔specificity transcription); seconds each. These are the pattern to keep and to port machine-side (TU-1 format authority) |
| LaTeX source-tree `SOURCE_CHANGED` gate | `tools/latex_build.py:198-235` | change detection between two adjacent pipeline steps is precisely a boundary check; <1s |

### KEEP — per-consumption, single-artifact, receipt-checked (this IS the receipt pattern)

| verification | file path | justification |
|---|---|---|
| Handoff checks (`verify_chain` + grounding-vs-pin) | `tools/research_plan.py:731,1078-1086` | a run's outputs change hands; one small file + tens of events, <1s |
| Bridge / review-target checks | `operate/modes/deep_research.py:2230`, `operate/modes/manuscript_review.py:277` | same boundary logic |
| Finalized-output resolve vs `output_sha256` receipt | `operate/output_versions.py:422-447` | verifies against a recorded receipt, never re-derives trust; one file, <1s |

### MOVE → per-release only (the E1 heart)

| verification | file path | move + receipt |
|---|---|---|
| **Deposit root hash** | `runs/.../tools/mkdeposit.py` | run exactly at a release/deposit moment (version freeze, submission package, promote) or when the deposit set changes through a versioned fold-in (TU-7). `DEPOSIT-MANIFEST.json` **already is the receipt** (root, per-file sha256, counts, timestamp implicit in the version dir) — cite it; never re-run per report. A report that needs the root hash quotes `depositRootFull` from `src/tab/deposit_numbers.tex` |
| **Vendor verify** | `tools/vendor_upstream_skills.py` `verify` | run after `fetch`, in a release audit, or on suspicion the tree changed. `vendor/upstream-research-skills/MANIFEST.json` is the receipt. **Doc fix required**: machine `CLAUDE.md` §10 "re-check with … verify" invites routine re-checking — reword to "verify after fetch or when the tree is suspected changed"; same for the hint in `tools/upstream_catalog.py:101` |
| **Example replay** | `tools/example_replay.py` | run before a release/promote that cites the example, or after editing `tools/mechanism_council.py` / `tools/native_dispatch_trace.py`. Honesty note: in this checkout it is structurally unrunnable (project absent) — the receipt states *UNVERIFIABLE-in-checkout*, and `PLATFORM-FACTS.md:27` must stop describing it as replayable-here |
| **Colour/pixel checks** | fold into `runs/.../tools/check_rendered.py` (or a 20-line `check_mono.py` beside it) | make the ad-hoc sweep a deterministic function (sample rendered figure pages; assert max saturation ≈ 0), run at **release builds only** (e.g. `RELEASE=1 ./build.sh`), receipt = one line in the build report. Figures change rarely; prose builds must not pay for them |

### CUT outright

| cut | file path | justification |
|---|---|---|
| Mandatory `--hash-manifest` on the numeric-benchmark CLI | `tools/numeric_benchmark_adapter.py` `main` (required=True), `build_report(hash_manifest=…)` required kwarg | de-governance already made `hash_check` informational; keeping the *input* mandatory forces a manifest ritual for every local recompute. Make it optional; when absent, emit `hash_check: {verdict: "NOT_PROVIDED", …}`. **Contract change — register in `<proj>/docs/12-DECISION-REGISTER.md` first**, then sync `schemas/numeric_benchmark_report.schema.json` (currently requires `hash_check` + `input_refs.hash_manifest_ref`) and the tests (Q4) |
| Routine `verify_chain` sweeps | — | nothing left to cut: append-time verification, `classify_status` "tampered", replay digest stage, vendor content re-hash, promote-gate audit re-hash were all removed 2026-08-07. Record as **already cut**; do not re-add |
| Stale docstring claim | `tools/ledger.py` module docstring ("workbench governance calls it") | `workbench/cli.py:260` → `tools/governance_census.py` never calls `verify_chain`; fix the sentence, not the code |

### Receipt convention (minimal, no new machinery)

The receipts already exist: ledger events (A1–A4), `DEPOSIT-MANIFEST.json`, vendor
`MANIFEST.json`, `output_sha256` rows, promote admission records. The only additions:
(1) a release build appends one line per release-only check to the build report
(check name + root/verdict + timestamp + coverage count); (2) any report that would
have re-run a verification instead **quotes the receipt and its date**. A receipt is
invalidated by exactly one thing: a change to the artifact set it covers — never by time.

---

## Q3 missing checks (from the failure catalog) + minimal deterministic sketches

| # | missing check | catalog | where it lives | minimal deterministic sketch |
|---|---|---|---|---|
| 1 | **Channel-yield watchdog** — a *declared* search channel contributing 0 records fails loudly | A1, A6 | machine: extend `tools/evidence_search_trace.py` (today it scores saturation/coverage and has **no per-channel concept**) + enforce as a deterministic det at the DISCOVER commit in `operate/modes/deep_research.py`; run-side: `runs/.../tools/harvest_v2.py:201` prints `+0 (raw 0)` with no tripwire, and `harvest.py:131` (`_BREAK_AFTER = 3`) silently zeroes a channel forever | trace contract gains per-round `channels: [{name, records_returned, breaker_open}]`. Det: `declared = set(plan.channels); dead = [c for c in declared if total_raw[c] == 0]; if dead and not waiver[c]: BLOCK("CHANNEL_ZERO_YIELD: " + c)`. A tripped breaker must surface as `breaker_open: true` in the trace — hard boundary §6 already forbids silent degradation; this makes it computable. Waiver = an explicit, named degradation note in the artifact, never a default |
| 2 | **Verifier-validation rule** — no guard is trusted until it fails on known-bad input | B2 | test-harness convention + registry: `tests/machine/test_verifier_validation.py` (new meta-test) + a small `orchestrator/guard_registry.yaml`; seat instruction for any check author. The run's own `runs/.../tools/test_verify.py` (6 real mismatches pinned in both directions) is the exemplar | registry rows: `{guard: tools/<name>.py, known_bad: tests/machine/fixtures/known_bad/<name>.json, expect: BLOCK|FAIL|nonempty}`. Meta-test: for each row, import the guard, feed the fixture, assert the non-PASS outcome; assert every module matching `tools/*{checker,guard,validator,linter}*.py` has a registry row. A guard with no known-bad fixture is itself a test failure |
| 3 | **Adjudicative-language linter** for manuscripts | D2 | run/build: new block inside `runs/.../tools/check_prose.py` (build.sh pass 0 gates it); machine: the same word list as a det in the manuscript path (`tools/manuscript_audit.py` or the TU-1 path doc's tripwire list) so authoring/review runs get it too | `ADJUDICATIVE = re.compile(r"\b(settled|displaced|direction is knowable|apparatus largely exists|definitively|established beyond|is now certain|closes? the question)\b", re.I)`; scan `sec/*.tex` (and generated `tab/*.tex` — the D3 lesson says a generated cell printed in prose IS prose); every hit is a problem row → exit 1 with the same `SKIP_CHECK=1` escape. Word list lives in ONE file the machine det and the build check both read |
| 4 | **Caption-data co-generation rule** — generated artifacts emit caption and data from the same code path | D3 | run/build: new block in `runs/.../tools/check_prose.py`; convention already half-exists (`mkdeposit.py` writes an `%% AUTO-GENERATED by tools/…` header into `src/tab/deposit_numbers.tex`); machine: TU-1 path doc states the rule for every generator seat | rule: every `tab/*.tex`/data-bearing `fig/*.tex` must carry the `%% AUTO-GENERATED by <generator>` header, and any `\caption{}` for a label defined in a generated file must appear **in that same file**. Check: `for f in tab/*.tex + fig/*.tex: if defines_label(f) and not AUTO_HEADER.match(first_line(f)): problem; if caption_for(label) found in a different file: problem("caption and data diverge: fix the generator")` |
| 5 | **Independent-labels schema rule** — extraction schemas mark derived fields; readers may never write them | C3 (TU-4) | machine: schema convention in `schemas/` consumed by `tools/validate_artifact.py`; run-side: a validator over `runs/.../corpus/deepread/*.json` before any synthesis (`runs/.../tools/synthesize.py` load path is the single choke point, per TU-8) | extraction schema gains per-field `"provenance": "observed" \| "derived"`. Validator: `derived = fields_marked_derived(schema); for rec in deepread/*.json: leak = set(rec) & derived; if leak: BLOCK(f"{rec}: reader wrote derived field(s) {leak}")`. Derived values may exist only in a separate generator-owned file carrying the AUTO-GENERATED header (check 4), computed by one code path from observed fields — the F1–F4 ladder incident (26/73 credited *estimate* nobody observed) is the regression case |

---

## Q4 affected tests

Grep basis: `verify_chain|hash_artifact|hash_manifest_validator|example_replay|vendor_upstream_skills|output_hash|chain_hash|stdout_sha256|hash_check|integrity_scan` over `tests/machine/`.

**Break / must change if the Q2 cuts land** (register the contract change first):

| file | why |
|---|---|
| `tests/machine/test_numeric_benchmark_adapter.py` | pins `hash_check` always present with a computed verdict (`:84-101`) and a required-manifest call shape; making `--hash-manifest` optional requires adding the `NOT_PROVIDED` branch here |
| `schemas/numeric_benchmark_report.schema.json` (not a test, but the pin the test enforces) | `required: [... hash_check ...]` and `input_refs.required: [... hash_manifest_ref ...]` must admit the absent-manifest shape |

**Conflict with the letter of the no-re-hash rule but recommended KEEP with an exemption comment**
(pytest runs only when machine code changes — "the artifact set changed" is true of the code
under test; measured cost 1.34 s for all of them together):

| file | what it re-verifies per pytest run |
|---|---|
| `tests/machine/test_absorbed_methods_and_fanout.py` (`:115`) | re-hashes ~45 vendored receipt files against `orchestrator/external_research_skill_sources.json` declarations |
| `tests/machine/test_vendor_upstream_skills.py` (`:28`) | walks the real 2,604-file vendor tree via `verify()` (existence + stray only) |

**Already inert in this checkout — must not be quoted as exercised** (recorded example absent;
all skip; `PLATFORM-FACTS.md:27` still claims it is on disk):

| file | status |
|---|---|
| `tests/machine/test_example_replay.py` | 10/10 SKIP |
| `tests/machine/test_t4_native_multi_agent_evidence.py` | 5/5 SKIP |

**Guard list — pin the KEEP rows; the policy must NOT touch them** (they will fail loudly if
anyone "optimises" the crown jewels): `tests/machine/test_hash_artifact.py`,
`tests/machine/test_ledger.py`, `tests/machine/test_ledger_hardening.py`,
`tests/machine/test_hash_manifest_validator.py`, `tests/machine/test_server_hash_manifest.py`,
`tests/machine/test_output_versions.py` (`:124` finalized-hash drift),
`tests/machine/test_manuscript_integration.py` (`:852` hash-checked asset copy),
`tests/machine/test_integrity_scan.py`, `tests/machine/test_preflight_checker.py`, and the
~15 files asserting `verify_chain(...) == []` on runs they create themselves:
`test_engine.py`, `test_operate_spine.py`, `test_operate_full_rigor.py`,
`test_operate_venue_readiness.py`, `test_m1_end_to_end.py`, `test_m2_breadth_accept.py`,
`test_m2_spine_slice.py`, `test_m3a_new_direction.py`, `test_mode_discover_speconly_e2e.py`,
`test_mode_execute_speconly_e2e.py`, `test_mode_ideate_design_verify_e2e.py`,
`test_north_star_pin.py`, `test_director_veto.py`, `test_promote_gate.py`,
`test_document_promotion.py`, `test_seam_profile_generality.py` (all under `tests/machine/`).

---

*Auditor C. Read-only everywhere except this file. Timings measured on this machine 2026-08-20;
nothing was fetched, no run was started, no run artifact was modified.*
