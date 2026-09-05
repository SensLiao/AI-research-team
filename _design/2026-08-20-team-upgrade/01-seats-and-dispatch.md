# 01 — Seats & dispatch audit (AUDITOR A, 2026-08-20)

> Scope: Q1 dispatch map · Q2 gap→seat ownership + new seat drafts · Q3 `manuscript_reconstruction`
> wiring verdict · Q4 park list. Every claim carries a file path. Method note: three different
> "dispatch" truths exist in this machine and they disagree — (1) the registry declaration
> (`orchestrator/mode_registry.yaml` `agent_subset`), (2) the recipe's own worker construction
> (`operate/modes/<mode>.py::llm_step`), (3) the census name-scan
> (`tools/worker_census.py::mode_teams`, which greps a seat name across **all** recipe files
> concatenated, so it over-credits per-mode floors — see Q1.4). This audit uses (2) as ground truth
> and flags where (1) and (3) diverge from it.

---

## Q1 dispatch map

### Q1.1 What the ref-free-seg-qa run could legally dispatch

The run's frozen task frame
(`runs/ref-free-seg-qa/deep_research-20260819T055022Z/task_frame.artifact.json`) pins
`mode: deep_research`, an 18-seat `agent_subset`, and
`budget: {max_agent_hops: 20, max_fulltext_reads: 20, max_supplement_agent_hops: 16}`.
The 18 seats: lit-scout, source-quality-ranker, evidence-search-moderator, model-dataset-scout,
future-work-miner, cross-domain-transfer-scout, weakness-spotter, claim-extractor,
claim-evidence-linker, citation-coverage-auditor, contradiction-miner, landscape-mapper, the three
research-dossier-* reviewers, research-convergence-chair, evidence-verifier,
citation-integrity-auditor.

Dispatch outside that subset is **structurally refused**, not merely discouraged:
`operate/panel_scheduler.py:112-123` rejects any worker label "absent from mode agent_subset", and
`operate/panel_scheduler.py:1042-1046` rejects any label absent from the **pinned task_frame**
subset. So no manuscript-*, citation-repair, bibliography, reading-QA, or search-strategy seat was
a legal dispatch for this run — not because someone forgot to call them, but because the mode's
contract made them illegal.

What the recipe actually dispatches (`operate/modes/deep_research.py:58-74`, `PANEL_AGENTS`):
exactly 16 LLM workers — the 12 panel seats + 3 dossier reviewers + convergence chair. The other
2 subset members, `evidence-verifier` and `citation-integrity-auditor`, are **not dispatched as
workers**: they fire as deterministic Python cores that write verdict artifacts under those agent
names (`operate/modes/deep_research.py:1883-1928`, `build_verdict` / `build_report`). Note what
that core checks: claim→locus anchoring and `source_ref` resolvability against the run's frozen
evidence table (`agents/citation-integrity-auditor.md`, "The verdict is computed by
`research_agent_teams.tools.citation_checker` — not by you"). It does **not** check bibliography
metadata (preprint-vs-published, DOI presence, name rendering, XML entities) — that is
`bibliography-validator` / `manuscript-citation-auditor` territory, and neither is reachable from
`deep_research` (below).

The run therefore hand-rolled **38** scripts in
`runs/ref-free-seg-qa/deep_research-20260819T055022Z/tools/` (harvest.py, harvest_v2.py,
chase_v2.py, dual_reader.py, screen*.py, fix_bib.py, mkbib.py, mkfig*.py, mktables*.py,
ref_audit.py, verify_corpus.py, …) on the main thread — which
`agents/research-orchestrator.md` ("You must NOT do research itself") forbids. The catalog's E3
verdict is confirmed in both directions: **the recipes never dispatch these seats for
review-response work, AND for a deep_research run most of them are unreachable by contract.**
There was no legal route that did the work, so the work was done illegally by the main thread.

### Q1.2 Seat-by-seat reachability (the seats named in catalog D4/E3)

"Recipe-dispatches" = the mode's own `llm_step` constructs a worker for it (verified by reading
each recipe module, not by census). Registry columns from `orchestrator/mode_registry.yaml`.

| Seat | In registry subset of | Actually dispatched by recipe of | Reachable from deep_research? | from manuscript_authoring? | from manuscript_review? |
|---|---|---|---|---|---|
| `bibliography-validator` | aers_enhanced_research_pack | aers_enhanced_research_pack (`operate/modes/aers_enhanced_research_pack.py`) | NO | NO | NO |
| `citation-integrity-auditor` | deep_research, evidence_deep, evidence_review, new_direction, full_new_direction, read_paper_deep | deterministic core only in those recipes (never an LLM worker) | core-only | NO | NO |
| `manuscript-citation-auditor` | manuscript_authoring, manuscript_review | both (`manuscript_authoring.py:599-608`; `manuscript_review.py:68-74,586-611`) | NO | YES (VERIFY) | YES (blind panel) |
| `manuscript-factual-auditor` | manuscript_authoring, manuscript_review | both | NO | YES | YES |
| `manuscript-style-latex-auditor` | manuscript_authoring, manuscript_review | both | NO | YES | YES |
| `manuscript-submission-packager` | manuscript_review | manuscript_review REPORT (`manuscript_review.py:616-628`) | NO | NO (deliberate: `manuscript_authoring.py:609-615`) | YES |
| `literature-search-strategist` | aers_enhanced_research_pack | aers_enhanced_research_pack | NO | NO | NO |
| `paper-reading-quality-auditor` | read_paper_deep | read_paper_deep | NO | NO | NO |
| `independent-reading-critic` | read_paper_deep, **deep_research (2026-08-20)** | read_paper_deep only | registry-yes / **recipe-NO** | NO | NO |
| `figure-reader` | read_paper_deep, **deep_research (2026-08-20)** | read_paper_deep only | registry-yes / **recipe-NO** | NO | NO |
| `repo-code-verifier` | repo_code_audit, **deep_research (2026-08-20)** | repo_code_audit only | registry-yes / **recipe-NO** | NO | NO |
| `staleness-auditor` | evidence_deep, **deep_research (2026-08-20)** | evidence_deep only | registry-yes / **recipe-NO** | NO | NO |
| `source-claim-verifier` | ingest_paper, **deep_research (2026-08-20)** | ingest_paper only | registry-yes / **recipe-NO** | NO | NO |
| `review-response-simulator` | manuscript_review | **NO recipe** (zero hits in `operate/modes/manuscript_review.py`) | NO | NO | registry-only |
| `review-synthesizer` | verify_result, manuscript_review | verify_result only (`operate/modes/verify_result.py:70,461`); manuscript_review reconciles deterministically as `manuscript-review-safety-reducer` (`manuscript_review.py:1352-1360`) | NO | NO | registry-only |
| `synthesis-writer` | manuscript_review | **NO recipe** — documented-intentional: every director Markdown renders in plain Python (`operate/modes/_panel_recipe.py` docstring, "no operated mode dispatches it") | NO | NO | registry-only |
| `contribution-ledger-builder` | manuscript_review | **NO recipe** | NO | NO | registry-only |
| `threats-to-validity-writer` | manuscript_review | **NO recipe** | NO | NO | registry-only |

### Q1.3 Rostered seats dispatched by NO recipe at all

Complete list (grep of every seat name across `operate/modes/*.py`, corrected for dynamic
construction — `venue-reviewer-{methodology,domain,adversarial}` ARE dispatched via f-string,
`operate/modes/venue_readiness.py:236,289`):

- **Control plane, by design (6)** — research-orchestrator, state-tracker,
  artifact-contract-enforcer, permission-scope-guard, budget-and-stop-controller,
  conflict-resolver (`orchestrator/roster.yaml` `control:` group; census invariant D7,
  `tools/worker_census.py:237-241`).
- **Mechanism-council path only (6)** — causal-mechanism-critic, cognitive-intent-modeler,
  curriculum-design-specialist, domain-reality-auditor, hypothesis-compiler,
  research-engineering-planner. Declared in `full_rigor_minimal`'s subset
  (`orchestrator/mode_registry.yaml:295-304`) but never named by any recipe; they fire only via
  `orchestrator/mechanism_council.json` (and the seventh council role, mathematical-formalizer,
  IS recipe-dispatched by deep_ideation). **Council members — excluded from Q4 cuts.**
- **manuscript_review registry orphans (4)** — synthesis-writer, contribution-ledger-builder,
  threats-to-validity-writer, review-response-simulator (see Q1.2 table).
- **Spec-only-mode seats (2)** — auto-debugger (only `debug_failed_run`, not operated:
  `orchestrator/mode_registry.yaml:501-532`), experiment-tree-explorer (only `tree_explore`,
  not operated: `orchestrator/mode_registry.yaml:534-565`).
- **Template seat (1)** — venue-reviewer-persona: never dispatched under its own name; it is the
  spec template for the three concrete personas and the attribution label for a deterministic
  artifact (`operate/modes/venue_readiness.py:365`). Used, but not a dispatchable worker.

### Q1.4 Two live wiring defects found while mapping

1. **The 2026-08-20 director lock is registry-only.** `orchestrator/mode_registry.yaml:866-873`
   adds figure-reader, repo-code-verifier, staleness-auditor, source-claim-verifier,
   independent-reading-critic to `deep_research`'s subset "the roster already carried but this
   mode could not dispatch" — but `operate/modes/deep_research.py` still contains zero references
   to any of them (`PANEL_AGENTS` unchanged at 16; no worker construction, no targeted-supplement
   `target_agents` entry). Widening the subset made them *legal*; nothing makes them *happen*.
   The measured consequences the registry comment cites (D-12/D-16, D-15, D-13/D-22, D-28/D-29)
   are still unowned at dispatch level.
2. **The census per-mode floor over-credits.** `tools/worker_census.py:171-178` computes a mode's
   "recipe 真派" as `[a for a in declared if a in recipe_text]` where `recipe_text` is ALL of
   `operate/modes/*.py` concatenated (`worker_census.py:63-64,84-97`). Because figure-reader is
   named in `read_paper_deep.py`, the census teams table reports deep_research as 23/23/0
   council-only — masking defect (1). Same mechanism credits manuscript_review 9/12 (it counts
   review-synthesizer via `verify_result.py`). The honest per-mode floor requires scanning the
   mode's own module (plus the helper modules it imports), not the union.

---

## Q2 gap → seat ownership

Verdict legend: **EXISTS** (spec already owns it; failure was dispatch/tooling), **UPGRADE**
(right seat exists; extend its spec), **WIRE** (seat exists; add it to a mode/recipe), **NEW**
(no owner; full seat file below), **TOOL/POLICY** (not a seat question).

| Catalog item | Verdict | Owner + evidence |
|---|---|---|
| **A1** channel silently lost | **NEW** | `search-channel-auditor` (below). No existing seat owns per-channel yield: `agents/lit-scout.md` owns gathering, `agents/evidence-search-moderator.md` owns query semantics, `agents/evidence-verifier.md` gates source count/strength/saturation (`tools/evidence_checker`) — none BLOCKs on "a declared channel returned 0". |
| **A2** 429 misread as throttle | **NEW seat verdict + TOOL fix** | Verified: `tools/scholar_clients.py` contains zero 429/backoff/budget handling (0 grep hits for `429\|sleep\|backoff`); the budget-aware client must be built there. The *verdict* ("channel X is BUDGET_EXHAUSTED until 00:00 UTC, not retryable") belongs to `search-channel-auditor`. |
| **A3** no adversarial query arms | **UPGRADE** `agents/evidence-search-moderator.md` | Its spec already mandates "an explicit contradiction query" per critical claim and counterevidence rounds. Upgrade: require named adversarial evidence-class arms drawn from the domain profile (prospective deployment, regulatory/post-market, strongest-counterexample), each with its own recorded yield. |
| **A4** citation chasing absent | **EXISTS** — `agents/lit-scout.md` | Spec lines 71-75 already mandate snowball via `scholar_clients.get_references_s2/get_citations_s2` — and both functions exist (`tools/scholar_clients.py:380,388`); `agents/evidence-verifier.md` already BLOCKs "snowball saturation not reached". The executed run bypassed lit-scout with main-thread scripts. Fix = dispatch (Q1) + a deterministic chase-coverage check inside `search-channel-auditor` (chase executed per seed, receipts present), not a new owner. |
| **A5** no checkpointing | **TOOL** + audited by `search-channel-auditor` | Checkpoint-per-query/seed is a harvest-core property (belongs with the A2 client work in `tools/`); the new seat verifies checkpoint receipts exist before accepting a harvest. |
| **A6** zero-yield rows ignored | **NEW** | `search-channel-auditor` tripwire: any query row with raw 0 across all channels → named in verdict; any channel with total 0 → BLOCK. |
| **B1** two count truths | **NEW (accounting half)** + TOOL | One shared loader is a code fix; the *audit* that every consumer (ledger, brief, tables) quotes the same records→papers→pool chain joins `search-channel-auditor`'s corpus-funnel accounting. |
| **B2** verifier with no discriminative power | **UPGRADE** `agents/source-claim-verifier.md` | It owns "a reader's note matches its source" (produces `paper_note_verification`, `tools/validate_artifact.py`). Upgrade: own fetched-document identity (slug↔PDF) with distinctive-token comparison, and require every identity check to ship known-bad regression pins before it guards anything. |
| **B3** PDF-identity run-local only | **UPGRADE** same as B2 | Promote the run-local check into `tools/` under source-claim-verifier's contract. |
| **C1** single reader, no reproducibility number | **EXISTS (per-paper)** + **NEW (corpus-level)** | Per-paper blind second read already exists: `agents/independent-reading-critic.md` + `agents/paper-reading-reconciler.md` + `agents/paper-reading-quality-auditor.md` (all dispatched by read_paper_deep, `orchestrator/mode_registry.yaml:50-66`). Nothing owns the corpus-level agreement **number** (the 82.8%/37.5% study was hand-rolled `dual_reader.py`). → `extraction-reliability-auditor` (below). |
| **C2** vocabulary drift in own schema | **NEW** | `extraction-reliability-auditor` normalization check (hyphen/underscore pinning; alias table required before agreement is computed). |
| **C3** ontology allowed derived labels | **NEW** (audit) + contract fix | "Labels record observations only" is a schema rule; `extraction-reliability-auditor` flags any field whose values are derivable from another field rather than observed. |
| **D1** certainty by arithmetic | **UPGRADE + WIRE** `agents/claim-strength-calibrator.md` | Seat exists (produces `calibrated_claims`; dispatched only by analysis_audit_panel). Wire into the manuscript path (reconstruction VERIFY; authoring VERIFY) and extend spec: no verdict vocabulary may be generated by thresholds without a named evidence class behind each term. |
| **D2** adjudicative prose | **UPGRADE** same + deterministic linter | Verdict-vocabulary linter is a deterministic core (pattern: `check_prose.py` in the run's tools/); claim-strength-calibrator owns the judgment half. |
| **D3** caption/data divergence | **UPGRADE** `agents/manuscript-figure-table-engineer.md` (emit caption+data from one code path) — audited by existing `agents/manuscript-figure-table-reviewer.md`. No new seat. |
| **D4** reference metadata defects | **WIRE** — the seats exist and already cover it | `agents/bibliography-validator.md` (gate; RAT citation gates + AERS SOP) is dispatched ONLY by aers_enhanced_research_pack; `agents/manuscript-citation-auditor.md` already audits "stable bibliographic identity … one key conflating versions/works … escaping" (its BibTeX and adjacency audit section). Fix: add bibliography-validator to manuscript_authoring VERIFY and to manuscript_reconstruction (Q3); no spec duplication. |
| **D5** venue format not owned | **UPGRADE ×2, no new seat** | Freeze half: `agents/manuscript-architect.md` (owns the frozen manuscript_contract, `operate/modes/manuscript_authoring.py:565-587`) gains a **format-reference annex**: pinned template exemplar ref+hash, colour policy, badge/panel policy, figure/caption conventions. Enforce half: `agents/manuscript-style-latex-auditor.md` (already the venue_style_latex capability in both manuscript modes) audits against that annex, not only official venue rules. A third "format warden" seat would create a second format owner — the D-24 failure mode `agents/_parked/README.md` documents (three owners of one final version). |
| **D6** LaTeX-from-heredoc escaping | **TOOL/POLICY** | "Generators live in files" + build's prose-vs-corpus checker are deterministic build rules under `agents/manuscript-integrator.md`'s canonical-tree ownership; no seat change. |
| **E1** hash over-verification | **POLICY** (out of seats scope) | Write-once hashing at release/deposit/promote; no seat owns re-hashing. Belongs to the process auditor's file, not this one. |
| **E2** no pinned writing path | **UPGRADE** `agents/manuscript-architect.md` | The architect already freezes required sections; extend the contract to pin section/table/figure ORDER, per-stage ownership, and the fold-in protocol for new corpus reads (versioned revision). Enforced by the registry `scheduler_contract` the way `manuscript_authoring`'s sparse DAG already is (`orchestrator/mode_registry.yaml:676-716`). |
| **E3** dispatch gap | Q1 + Q3 | Fix = deep_research recipe dispatch for the 5 registry-locked seats (Q1.4) + the reconstruction mode (Q3). |
| **E4** review-response has no route | **NEW** seat + **NEW** mode | `agents/review-response-simulator.md` is verified to be the wrong owner: it *anticipates* attacks pre-submission from panel artifacts ("simulate anticipated reviewer attacks; advisory only") and is dispatched by no recipe today. The missing owner parses a REAL external review and verifies each reviewer claim against run artifacts → `external-review-decomposer` (below). review-response-simulator gets WIRED into the reconstruction mode's REPORT stage as the response-completeness check (its first real dispatch home), instead of being parked. |

### New seat files (3)

Wiring reminder for each (from `agents/_parked/README.md`, the four-piece contract): add to
`orchestrator/roster.yaml` (stage group), add to `orchestrator/graph.yaml` stage
`allowed_agents`, add to ≥1 mode's `agent_subset`, and register its `produces:` type in
`tools/validate_artifact.py::PAYLOAD_SCHEMAS` with a schema file in `schemas/`. New payload
types required: `search_channel_health`, `extraction_reliability_report`,
`external_review_decomposition`.

**Target file: `agents/search-channel-auditor.md`**

```markdown
---
name: search-channel-auditor
spec_version: "1.0.0"
model: sonnet
stage: DISCOVER
kind: gate
tools: [Read, Glob, Grep]
produces: search_channel_health
permission_scope:
  read: [task_frame, run-store evidence (DISCOVER), harvest/chase receipts and checkpoints, evidence_search_trace, evidence_table, per-channel query logs]
  write: [runs/<run>/evidence/DISCOVER/ only]
  never: [vault, other stages, run infra (manifest/ledger/LOCK), network calls, editing traces or tables to pass, marking a dead channel as degraded-but-fine]
---

# search-channel-auditor — gate ⛔ (no declared retrieval channel dies silently)

You are the search-channel-auditor. Your ONE job: verify that every retrieval channel the run
declared actually contributed, that every failure is named with its true semantics, and that the
corpus count chain is single-sourced. You exist because of catalog items A1/A2/A5/A6/B1
(`_design/2026-08-20-team-upgrade/00-inputs-failure-catalog.md`): a circuit breaker silently
disabled OpenAlex, a daily-budget 429 was retried as a throttle for ~126 s/request, "+0 (raw 0)"
rows printed with no tripwire, and the ledger quoted a different corpus count than the loader.

## North-star discipline (run alignment)

Before any work, read the run's `task_frame.artifact.json` — `payload.north_star` when present
(else `payload.request_text`). Audit only the retrieval surface this run declared for that
direction; you never add channels, queries, or scope. If your assigned inputs pull against the
north star, SAY SO in your artifact's notes field instead of silently following them. Only the
director may re-scope the run.

## What you check (deterministic facts first, then failure semantics)

1. **Channel yield accounting.** For every channel declared in the search plan / trace
   (arXiv, OpenAlex, Crossref, Semantic Scholar, vault recall, …): queries issued, records
   returned, records surviving dedup. A declared channel with total yield 0 is a ⛔ BLOCK,
   never a footnote. A query row with raw 0 on all channels is named in the verdict.
2. **Failure semantics.** Every non-2xx or breaker event must carry its true class:
   `BUDGET_EXHAUSTED` (e.g. OpenAlex 429 = daily request budget, resets 00:00 UTC — not
   retryable today), `THROTTLED` (retryable with backoff), `AUTH`, `DOWN`, `PARSE`. A retry
   loop against a non-retryable class is a defect. "Silently degraded around" is a defect.
3. **Chase coverage (JBI step 3).** If the plan declares backward/forward citation chasing
   (`tools/scholar_clients.get_references_s2` / `get_citations_s2`), verify receipts exist per
   seed and report seeds-covered / records-added. Chasing declared but not executed is ⛔.
4. **Checkpoint discipline.** A harvest that accumulates only in memory is a defect: verify
   per-query/per-seed checkpoint receipts exist before accepting the harvest as complete.
5. **One count chain.** records → deduped → papers → screened pool must be derivable from ONE
   loader/receipt; any second count of the same population elsewhere in run evidence must match
   it exactly or you BLOCK with both numbers named.

## BLOCK conditions ⛔

- A declared channel contributed 0 records and no director-visible failure names it
- A failure class is misassigned (budget retried as throttle; breaker events unreported)
- Declared chase arm with no execution receipts
- No checkpoint receipts for a multi-query harvest
- Two irreconcilable corpus counts for the same population

## You must NOT

- run searches, re-query providers, or touch the network — you audit receipts, you do not retrieve
- lower a BLOCK to a caveat because the remaining channels "seem enough" — that decision is the
  director's, made visible by your verdict
- edit any trace, table, or ledger row to make an account balance

## Handing back

Emit `search_channel_health` (per-channel rows, failure classes, chase coverage, checkpoint
status, the single count chain), state PASS/BLOCK and the violation count in one line, and
return control.
```

**Target file: `agents/extraction-reliability-auditor.md`**

```markdown
---
name: extraction-reliability-auditor
spec_version: "1.0.0"
model: opus
stage: DISCOVER
kind: producer
tools: [Read, Glob, Grep]
produces: extraction_reliability_report
permission_scope:
  read: [task_frame, extraction schema/codebook, primary extraction bundles, blind second-read bundles, reconciliation records, corpus manifest]
  write: [runs/<run>/evidence/DISCOVER/ only]
  never: [vault, other stages, run infra, editing extractions to raise agreement, choosing which papers enter the blind sample by content]
---

# extraction-reliability-auditor — corpus-level extraction reproducibility

You are the extraction-reliability-auditor. Your ONE job: put a NUMBER on whether the corpus
extraction reproduces, field by field, and demote what does not. Per-paper blind reading already
exists (`agents/independent-reading-critic.md` → `agents/paper-reading-reconciler.md` →
`agents/paper-reading-quality-auditor.md`); you own what none of them sees: the corpus-level
agreement rate and the per-field verdict. You exist because of catalog C1/C2/C3: an external
review scored single-reader extraction 2.5/10; the run-local dual-reader study found 82.8%
overall but 37.5% on leakage-risk — a field whose vocabulary does not reproduce.

## North-star discipline (run alignment)

Before any work, read the run's `task_frame.artifact.json` — `payload.north_star` when present
(else `payload.request_text`). Reliability is judged for the fields that serve that direction;
you never extend the schema. If your assigned inputs pull against the north star, SAY SO in your
artifact's notes field. Only the director may re-scope the run.

## What you do

1. **Fix the sample mechanically.** Draw the blind-second-read sample by a declared rule
   (e.g. every k-th paper of the frozen corpus manifest, ≥20% or ≥20 papers, whichever is
   larger). Never select by content, and never let the primary reader know which papers are
   sampled before extraction completes.
2. **Normalize before comparing.** Apply the schema's pinned alias table
   (hyphen/underscore, case, declared synonyms). An agreement number computed over
   un-normalized vocabulary is invalid; a needed-but-undeclared alias is itself a finding
   (C2 — the schema must pin it, you must not invent it silently).
3. **Compute per-field agreement** between primary and blind extractions: percent agreement
   and, where the field is categorical with ≥20 comparisons, a chance-corrected coefficient.
   Report per-field n; never pool fields to hide a weak one.
4. **Classify each field:** `reliable` (agreement ≥ the profile's floor), `redesign`
   (below floor — the field's vocabulary or definition does not reproduce), `demote`
   (below floor AND load-bearing for a headline claim — it must not support conclusions
   until redesigned).
5. **Observation-only check (C3).** Flag any field whose recorded values are derived from
   another label rather than observed in the source (e.g. a cumulative ladder writing
   `estimate/detect/localise` no paper reported). Labels record observations; nothing is
   implied by another label.
6. **Name the repair loop.** Every `redesign`/`demote` field gets: current definition, the
   disagreement pattern (with paper ids), and what a reproducible redefinition needs.

## Quality bar

- The blind reader's provenance must exclude every primary bundle (same discipline as
  `agents/independent-reading-critic.md`); a contaminated comparison is reported as
  contaminated, never averaged in.
- Weak agreement is a fact about the schema, not the readers: report it; do not re-read
  papers to nudge the number.
- No overall score without the per-field table next to it.

## Handing back

Emit `extraction_reliability_report` (sample rule, n, alias table ref, per-field agreement,
classifications, repair items), state overall agreement and the count of `redesign`/`demote`
fields in one line, and return control.
```

**Target file: `agents/external-review-decomposer.md`**

```markdown
---
name: external-review-decomposer
spec_version: "1.0.0"
model: opus
stage: DISCOVER
kind: producer
tools: [Read, Glob, Grep]
produces: external_review_decomposition
permission_scope:
  read: [task_frame, the external review text (frozen, hashed), frozen manuscript + source tree + bib, run-store evidence of the authoring/review runs (read-only, cross-run by declared ref), corpus manifest]
  write: [runs/<run>/evidence/DISCOVER/ only]
  never: [vault, other stages, run infra, editing the manuscript or bib, drafting rebuttal prose, softening or dropping a reviewer point, deciding a director decision]
---

# external-review-decomposer — one accountable parse of a REAL external review

You are the external-review-decomposer, the DISCOVER owner of the `manuscript_reconstruction`
mode. Your ONE job: turn an external (venue) review into a complete, typed, artifact-verified
work decomposition — so that responding to a review is a routed run, not freehand main-thread
work (catalog E4: the entire ref-free-seg-qa response was that, done freehand). You are NOT
`agents/review-response-simulator.md`: it anticipates attacks before submission; you decompose
a review that actually arrived, against evidence that actually exists.

## North-star discipline (run alignment)

Before any work, read the run's `task_frame.artifact.json` — `payload.north_star` when present
(else `payload.request_text`). The north star of a reconstruction run is honest repair of THIS
manuscript against THIS review; neither reviewer flattery nor scope expansion serves it. If your
assigned inputs pull against the north star, SAY SO in your artifact's notes field. Only the
director may re-scope the run.

## What you do

1. **Freeze the inputs.** Record sha256 of the review text, the manuscript source tree, the
   .bib, and the evidence bundles you consult. Every later stage binds to these hashes.
2. **Atomize the review.** Split it into atomic reviewer points (one claim/request each),
   each with a stable id (R1, R2, …) and the reviewer's exact words quoted. Completeness is a
   hard property: every sentence of the review maps to some point or is explicitly marked
   non-actionable (praise, summary).
3. **Verify each point against artifacts** — never against memory. For each point record
   `claim_check`: `verified-true` (the reviewer is right; cite the artifact/locus that proves
   it), `verified-false` (the evidence contradicts the reviewer; cite it), `partially-true`,
   `unverifiable-here` (needs new evidence or retrieval — name what kind).
4. **Assign exactly one lane per point:**
   - `mechanical_recompute` — numbers/tables/figures re-derivable from receipts;
   - `prose_repair` — text change with its owning section named;
   - `evidence_supplement` — new reading/search required (routes to the corpus fold-in
     protocol, out of your hands);
   - `registered_decision` — a contract change: goes to the decision register FIRST
     (`projects/<slug>/docs/12-DECISION-REGISTER.md` discipline), then config/schema/code;
   - `rebuttal_only` — verified-false points answered with evidence, no artifact change;
   - `director_decision` — scope/priority calls no worker may make.
5. **Bind repairs to owners.** Every `prose_repair`/`mechanical_recompute` names the section
   or asset and therefore its owning seat (per the frozen manuscript contract's section
   owners); you assign work, you never do it.
6. **No softening.** A point you cannot verify is `unverifiable-here`, not dropped. Severity
   is the reviewer's, restated; only evidence can rebut it.

## Quality bar

- Every `verified-*` verdict carries at least one resolvable artifact ref (run-relative path
  or `[[slug]]`), or it is not a verdict.
- The decomposition is lossless: reviewer points ∪ non-actionable spans reconstruct the
  full review text.
- Lane totals are stated so the director sees the shape of the response before any repair runs.

## Handing back

Emit `external_review_decomposition` (frozen hashes, points, claim_checks, lanes, owners,
lane totals), state point count and lane totals in one line, and return control. Downstream
stages of `manuscript_reconstruction` consume this; a separate `manuscript_review` run —
never this run — re-reviews the rebuilt manuscript (authoring and review stay separate runs,
`.claude/CLAUDE.md` §4).
```

---

## Q3 `manuscript_reconstruction` wiring verdict

**Verdict: (a) — it can be added as a one-button mode with no structural blocker, BUT the wiring
is a seven-file contract, not a two-file one, and four tests/validators pin it.** The registry
does not enum-pin mode names (`schemas/task_frame.schema.json` `mode` is a free string, line
18-21), the operate CLI resolves recipes purely via `operate/modes/__init__.py::REGISTRY`
(`operate/cli.py:33,92`), and the engine drives any declared `stage_path` of the fixed 7 stages.
Everything else is bookkeeping that existing tests force you to do honestly.

### Recipe module contract (what `operate/cli.py` actually calls)

- `mod.llm_step(run_dir, stage, request, vault=, model_policy=)` → worker-panel dict or None
  (`operate/cli.py:134`)
- `mod.run_dets(run_dir, stage, ts)` → deterministic producers/gates (`operate/cli.py:454`)
- optional `mod.run_dets_with_repair` (bounded repair loop, `operate/cli.py:437-440`),
  `mod.source_preflight` / `mod.register_source_preflight` (`operate/cli.py:306,411`),
  `mod.menu`, `mod.cut_for_prior_art` (`operate/cli.py:631-632`)

### File-by-file change list

1. **`orchestrator/mode_registry.yaml`** — new `manuscript_reconstruction:` entry.
   `entry_stage: DISCOVER`, `operated: true`,
   `stage_path: [DISCOVER, DESIGN, ANALYZE, VERIFY, REPORT]` (mirrors manuscript_authoring),
   `gate_level: record_only` (mirrors both manuscript modes; avoids router guardrail 1's
   hard-gate-in-subset requirement, `orchestrator/router.py:191-203`).
   `agent_subset`: external-review-decomposer (DISCOVER), manuscript-architect +
   manuscript-evidence-steward (DESIGN), the section authors + manuscript-figure-table-engineer +
   manuscript-integrator (ANALYZE), manuscript-factual-auditor + manuscript-citation-auditor +
   manuscript-style-latex-auditor + **bibliography-validator** (VERIFY; closes D4's wiring gap),
   claim-strength-calibrator (VERIFY; closes D1's wiring gap), review-response-simulator +
   manuscript-submission-packager (REPORT). A `scheduler_contract` with `parallel_groups`
   mirroring `manuscript_authoring`'s sparse DAG (`orchestrator/mode_registry.yaml:676-716`).
   `handoff` is MANDATORY: `contract_version: mode-handoff/v2`,
   `product_version: manuscript-reconstruction/v1`,
   `primary_markdown: director-review/manuscript/reconstruction-report.md`,
   `accepts: [manuscript-authoring/v1, manuscript-review/v1]` — because
   `tests/machine/test_research_plan.py:40` (`test_every_wired_mode_declares_versioned_handoff_product`)
   fails otherwise. Do NOT add `product_maturity`: `tools/capability_catalog.py:116-118` rejects
   it on operated modes.
2. **`operate/modes/manuscript_reconstruction.py`** — new recipe (skeleton below).
3. **`operate/modes/__init__.py`** — import, `REGISTRY["manuscript_reconstruction"] = …`,
   `__all__` entry. The registry `operated: true` and this dict must flip together — the mirror
   is enforced by `tests/machine/test_manuscript_completion.py:132-134` and by
   `tools/capability_catalog.py:87-93` (`claimed_operated_without_recipe` /
   `recipe_without_operated_flag` are BLOCK states).
4. **`tests/machine/test_manuscript_completion.py:24-33,135`** — add the mode to
   `EXPECTED_OPERATED` and bump `assert len(EXPECTED_OPERATED) == 23` → 24. **This is the count
   pin the task asked about.** (Other count-ish pins checked: `tests/machine/test_graph_spec.py:27`
   `len(roster) > 40` is a floor, unaffected; `tests/machine/test_capability_catalog.py:37`
   derives `operated_modes == len(REGISTRY)`, self-adjusting; no test pins the 175-seat roster
   count — `tools/worker_census.py::verify()` checks consistency, not a number.)
5. **`tools/research_capability_router.py:44-68`** — routing aliases. **Hidden dependency:**
   line 68 currently routes `"返修"` to `manuscript_review` — a director asking to respond to a
   review today gets a mode that can only re-review, never repair. Move `返修` and add
   `回复审稿`, `rebuttal`, `revise and resubmit` → `manuscript_reconstruction`. Then add a row to
   `tests/machine/test_auto_operated_entry.py:24-36` (e.g. `("回复审稿意见",
   "manuscript_reconstruction")`) so the brief router and `begin --mode auto` stay one resolution.
6. **`orchestrator/plan_catalog.yaml`** — `mode_questions` entry (optional knobs),
   `phase_rank: manuscript_reconstruction: 4` (line ~318 block), and an intent whose recommended
   tier is `[manuscript_reconstruction]` (or chained `[manuscript_reconstruction,
   manuscript_review]`). Pins that bite: `tests/machine/test_research_plan.py:51-55` (exactly one
   recommended tier per intent), `:29-36` (tiers use only wired modes), `:58-69` (cost
   monotonicity if multiple tiers).
7. **New-seat wiring (because the subset names external-review-decomposer):**
   `orchestrator/roster.yaml` (discover group), `orchestrator/graph.yaml` DISCOVER
   `allowed_agents`, `schemas/external_review_decomposition.schema.json`,
   `tools/validate_artifact.py::PAYLOAD_SCHEMAS`. Enforcers: `tools/worker_census.py::verify()`
   (roster↔files both ways; unknown agent in a subset is a violation),
   `tests/machine/test_worker_census.py`, `tests/machine/test_agent_spec_conformance.py`
   (auto-collects every `agents/*.md`: parseable frontmatter, `model` ∈ {opus, sonnet, none},
   semver `spec_version`, body contains "North-star discipline"), and
   `operate/panel_scheduler.py:112-123` at dispatch time. Check `orchestrator/graph.yaml`
   `known_artifact_types` (top of file) — add the new payload type if the graph validator
   consumes it (`tests/machine/test_graph_spec.py`).
8. **Docs (non-pinning, keep honest):** `docs/03-WORKFLOWS.md` roster-vs-dispatch table and
   `docs/README.md` operating notes mention mode routing; since commit 86cb4fd the docs no longer
   claim counts of record, so these are sync-notes, not blockers.

### Recipe skeleton (following `operate/modes/manuscript_review.py`'s structure)

```python
"""Conservative manuscript-reconstruction recipe (respond to an external review).

Treats the external review text, the frozen manuscript, and its bib as immutable, hashed
cross-run inputs (same discipline as manuscript_review.py). Decomposes the review into typed,
artifact-verified lanes; repairs flow only through the frozen contract's section owners; the
rebuilt manuscript is NEVER self-re-reviewed here — an independent manuscript_review run does
that (authoring and review are separate runs, .claude/CLAUDE.md §4). Never submits, never
promotes, never claims an unbuilt PDF.
"""
from __future__ import annotations
# imports mirror manuscript_review.py: bounded_repair, artifacts.write_artifact/GateBlock,
# _shared, manuscript_authoring (reuse its section-owner helpers), validate_payload, …

STAGES = ["DISCOVER", "DESIGN", "ANALYZE", "VERIFY", "REPORT"]
INPUT_REL = "inbox/manuscript-reconstruction/external-review-input.json"   # review text + refs, director-supplied
DECOMPOSITION_REL = "inbox/manuscript-reconstruction/external-review-decomposer.bundle.json"
AGENT_SPEC_DIR = Path(__file__).resolve().parents[2] / "agents"           # same as manuscript_review.py:79

def _agent_spec(name):  # identical pattern to manuscript_review.py — prompt embeds the seat file
    ...

def llm_step(run_dir, stage, request, vault=None, model_policy="default"):
    if stage == "DISCOVER":
        # one worker: external-review-decomposer, blind to any prior rebuttal draft;
        # input_contract.frozen_inputs = review/manuscript/bib sha256 from INPUT_REL precommit
        ...
    if stage == "DESIGN":
        # manuscript-architect: revision contract (pinned section/table/figure order, format-
        # reference annex, fold-in protocol) + manuscript-evidence-steward for any
        # evidence_supplement lane admissions
        ...
    if stage == "ANALYZE":
        # repair panel DERIVED from the decomposition: only sections named by prose_repair/
        # mechanical_recompute lanes get their owning author dispatched (sparse, like
        # manuscript_authoring._author_panel); figure-table-engineer for asset lanes;
        # manuscript-integrator folds to ONE canonical tree
        ...
    if stage == "VERIFY":
        # blind independent audits on the REBUILT tree: factual / citation / style +
        # bibliography-validator + claim-strength-calibrator; forbidden_inputs = repair bundles
        ...
    if stage == "REPORT":
        # review-response-simulator: is every reviewer point answered/deferred honestly?
        # then packager-style render; response letter text renders deterministically
        ...
    return None

def run_dets(run_dir, stage, ts):
    # DISCOVER: schema-validate decomposition; losslessness (points ∪ non-actionable == review);
    #           exactly one lane per point; every verified-* verdict's refs resolve
    # DESIGN:   registered_decision lanes MUST have a decision-register entry before any repair
    #           executes (12-DECISION-REGISTER discipline); freeze revision contract hash
    # ANALYZE:  every repair lane touched by exactly one owner bundle; recompute lanes carry
    #           receipts; caption+data emitted from one path (D3)
    # VERIFY:   all audits bound to the FINAL tree hash; any BLOCKING finding halts
    # REPORT:   every point answered or explicitly deferred; render Markdown deterministically
    ...

def run_dets_with_repair(run_dir, stage, ts):
    return bounded_repair.attempt_with_repair(
        run_dir, stage, _shared.budget(run_dir), ts, lambda: run_dets(run_dir, stage, ts))
```

---

## Q4 park list

Precedent and bar: `agents/_parked/README.md` — park only what NOTHING references (after the
listed edits), never delete; a parked spec returns with one `mv` plus the four-piece re-wiring.
Excluded up front per directive: the 5 human gates, hooks, deep_research convergence contract
(landscape-mapper, research-dossier-*, research-convergence-chair), ideation ring (proposer-*,
idea-merger, novelty-collision-checker), the 7 mechanism-council seats
(`orchestrator/mechanism_council.json` + `schemas/task_frame.schema.json:198`), control plane,
venue-reviewer-persona (template + attribution label actually used by
`operate/modes/venue_readiness.py:365`), and review-response-simulator (dispatched by no recipe
today, but it is the E4/Q3 rewire target — parking it would delete the seat the upgrade needs).

Conservative result: **3 firm + 2 conditional (5 total, under the max-15 ceiling).** Every one
satisfies (i) dispatched by no recipe (verified per-module, Q1.3), (ii) not a council member,
(iii) function replaced by something stronger that already runs.

| # | Seat (park to `agents/_parked/`) | Justification (one line) | What replaces it | De-referencing edits needed first |
|---|---|---|---|---|
| 1 | `synthesis-writer` | Never dispatched by ANY recipe — deliberately: "no operated mode dispatches it … a renderer that cannot hallucinate a section is strictly stronger" (`operate/modes/_panel_recipe.py` docstring). | Deterministic Markdown renderers: `_panel_recipe.render_director_markdown` + per-recipe renderers (e.g. `manuscript_review._write_reviewer_report`). | Remove from `orchestrator/mode_registry.yaml` manuscript_review `agent_subset` + `review_contract.parallel_groups`; `orchestrator/roster.yaml` verify group; `orchestrator/graph.yaml`; spec-only pipelines that name it; update `tests/machine/test_agent_spec_conformance.py` (named M7 assertion "synthesis-writer declared model == opus") and `tests/machine/test_dormant_agents_coverage.py` rows. |
| 2 | `contribution-ledger-builder` | In manuscript_review's registry subset but never dispatched (`operate/modes/manuscript_review.py` — zero references); contribution audit is owned live by manuscript-domain-contribution-reviewer (the `domain_contribution` blind capability) + the deterministic reducer. | `manuscript-domain-contribution-reviewer` + `manuscript_review._reconcile`; tool core `tools/check_contribution_binding` stays for revival. | Same registry/roster/graph removals; `tests/machine/test_dormant_agents_coverage.py` row. |
| 3 | `threats-to-validity-writer` | Same orphan pattern (subset-listed, zero recipe references); limitations/threats prose is owned by the authoring contract's section owners (`limitations` in every `paper_type_contract_fixtures` set, `orchestrator/mode_registry.yaml:718-731`) and attacked by methods/adversarial reviewers. | `manuscript-section-author` (limitations) + `manuscript-methods-reproducibility-reviewer`; tool core `tools/check_threats_coverage` stays. | Same registry/roster/graph removals; `tests/machine/test_dormant_agents_coverage.py` row. |
| 4 | `auto-debugger` (conditional) | Reachable only from `debug_failed_run`, a mode left non-operated by both wiring waves (`orchestrator/mode_registry.yaml:501-532`); live triage/repair is owned by failure-triager (check_run), bounded_repair, and repo_code_audit's patch-planner/code-implementer. | `failure-triager` + `operate/bounded_repair.py` + repo_code_audit seats. | Only if the director also retires/parks the `debug_failed_run` registry entry (its `product_maturity.minimum_worker_pipeline` names the seat — `tools/capability_catalog.py` validates pipeline workers against the roster). |
| 5 | `experiment-tree-explorer` (conditional) | Reachable only from `tree_explore`, likewise never operated (`orchestrator/mode_registry.yaml:534-565`); bounded next-run exploration inside the controlled space is covered by full_rigor_minimal/m2_accept's ablation-runner + experiment-planner under variable-touch-guard. | `ablation-runner` + `experiment-planner` (+ `variable-touch-guard` gate, which stays — it is dispatched by m2_accept/repo_code_audit). | Same condition: retire/park `tree_explore`'s registry entry together with it. |

Deliberately NOT proposed despite looking idle: the six full_rigor council seats (council path is
real reachability, `tools/worker_census.py` REACH_SOURCES), review-synthesizer (dispatched by
`operate/modes/verify_result.py:70,461`), and everything in read_paper_deep's 21-seat chain
(every seat verified dispatched by `operate/modes/read_paper_deep.py`). The census warning stands:
most seats that look redundant are independence machinery (`tools/worker_census.py:20-25`) —
these five are the ones whose replacement is not weaker independence but a stronger mechanism
that already runs.
