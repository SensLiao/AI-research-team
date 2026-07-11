# Paper-Reading Upgrade — BUILD LEDGER (SSOT, cross-session)

> **Read this FIRST in any new session working on this build.** It holds the locked design + the phase checklist + the current pointer. Companion: `00-gap-analysis-and-upgrade-design-2026-06-26.md` (the why).
> **Scope:** A (full single-pass, both systems). **Quality:** max_quality (top logical tier; Codex runtime `gpt-5.5` + `reasoning_effort=xhigh`). **Started:** 2026-06-26.
> **Director decisions on record:** Scope = A. Existing ~60 papers = leave-and-label + author Codex work-orders for re-deepen (P6); director runs Codex.

---

## CURRENT POINTER
- **Phase:** ALL PHASES P0–P6 DONE ✅. Build complete, GREEN, UNCOMMITTED.
- **Next concrete step (director's call):** (1) review + commit the repos if desired; (2) hand the P6 work-orders to Codex to backfill legacy papers on-demand; (3) optionally promote a vetted reading through `/promote-to-vault` after human review. The first real `read_paper_deep` PDF smoke run is now done (`read-skeleton-recall-20260701`).
- **Done:** P0–P5 ✅ (machine **2768** green, DB lint **exit 0**) · P6 ✅ (`P6-codex-reread-work-orders.md` authored). Build GREEN + **UNCOMMITTED** (git commits are the director's call).

---

## LOCKED DESIGN DECISIONS (the spec downstream phases follow)

- **D1 — The DB markdown `paper` page IS the human "research card".** No new `research_card` composite schema. The machine emits structured artifacts; promote/ingest renders them into the page's sections. (Avoids over-engineering; matches existing architecture where the DB page is the human artifact.)
- **D2 — Depth dial = existing `reading-status` ladder. No new `tier` enum.** LINT graduation (P2) keys required body sections on `reading-status` (mapping below). Respects the crown-jewel granularity-controller in `status-registry.md`; "reproduce-level" = a `deep-read` whose reproducibility checklist + per-term loss are filled (a rigor flag, not a new status).
- **D3 — `paper_note` is the Tier-S SPINE.** Extend it with Stage-0 positioning + Pass-1 contract, all **additive-OPTIONAL** (keeps existing artifacts + tests valid under `additionalProperties:false`). `claims` STAY flat strings; the structured claim→evidence ledger is the SEPARATE existing `claim_evidence_map` (wired to single-paper in P4, extended with directness/risk in P1).
- **D4 — New per-paper artifacts** (each enveloped, `source_ref`-anchored, rendered into the page): `method_teardown`, `figure_reading`, `paper_appraisal`, `paper_relations`, `trend_card`.
- **D5 — `paper_appraisal` = the venue-7D rubric RE-POINTED OUTWARD** at a READ paper. **Advisory only — never a governed gate, never auto-cuts/decides** (distinct from `venue_review`, which judges the machine's own manuscript). Carries a paper-type-selected formal checklist (NeurIPS / CASP / Cochrane RoB2 / STROBE / TRIPOD+AI / PRISMA / CONSORT).
- **D6 — `domain_profile` += optional `reading` block** (paper-type default + reporting standards + appraisal checklist) so reading rigor is domain-tunable like experiment rigor. Reading agents consult it.
- **D7 — Wiring (P4):** new single-paper deep-read operate recipe; `claim_list→claim_evidence_map` wired to single-paper ingestion; `tools/fulltext_qa.py` wired into the deep/reproduce path (page-anchored full text + retraction check, now with a PyMuPDF local-PDF fallback via `operate fulltext-pre`); `ingest_paper` wired into the operate REGISTRY (`operate/modes/__init__.py`).
- **D8 — Enforcement is honest graduation.** Existing skims stay `skimmed` (Tier S), labeled honestly; NOT force-rewritten. New frontmatter fields are registry-OPTIONAL but LINT-REQUIRED at `reading-status ≥ read` (graduation, not fail-all). Re-deepen happens via P6 Codex work-orders, director-driven.

### `reading-status` → required body sections (the P2 LINT graduation)
| reading-status | required sections (cumulative) |
|---|---|
| `to-read` | (stub; none) |
| `skimmed` (Tier S) | Stage-0 positioning · Pass-1 (TL;DR + paper contract + key contributions) |
| `read` | + Pass-2 (claim→evidence table + method breakdown + results table) |
| `deep-read` (Tier D) | + Pass-2 figure reading + Pass-3 appraisal checklist + Stage-4 (typed relations + implications + opportunity) |
| `cited` | same as `deep-read` (already gated by `render_claim_chain.py`) |
| reproduce-level (flag on deep-read) | + reproducibility checklist + per-term loss filled |

---

## FIELD-LEVEL SCHEMA SPECS (P0 + P1 implement exactly; all `additionalProperties:false`)

**`paper_note` (P0, extend — all new props OPTIONAL):** keep required `[title, source_ref, summary, claims]`. Add:
`paper_type` enum[method,theory,empirical,dataset-benchmark,tool,review,position] · `read_purpose` enum[idea,method,baseline,related-work,reproduce,review] · `relation_to_thesis` enum[A-core,B-related,C-background] · `reading_objective` str · `reading_status` enum[to-read,skimmed,read,deep-read,cited,deprecated] · `paper_contract` obj{category,context,correctness_prior,contributions[],clarity,contract_sentence} (all optional).

**`claim_evidence_map` (P1, extend):** per-locus add `directness` enum[direct,indirect,proxy,assumed] (optional). Per-mapping add `claim_risk` obj{level enum[high,medium,low], note str} (optional). Keep required unchanged.

**`method_teardown` (P1, NEW):** required `[source_ref]`. `problem_definition` str · `core_assumptions[]` str · `representation` str · `loss_terms[]`{term,role,ablate_effect} · `training_flow` str · `inference_flow` str · `train_infer_consistency` str|null · `data` str · `cost` str|null · `baseline_difference` str|null.

**`figure_reading` (P1, NEW):** required `[source_ref, figures]`. `figures[]`{figure_ref, axes, controls|null, error_bars|null, take_home, distrust|null}.

**`paper_appraisal` (P1, NEW):** required `[source_ref, dimensions]`. `paper_type` enum(as above) · `dimensions[]`{dim enum[soundness,significance,originality,eval_rigor,reproducibility,clarity,domain_validity], score int 1-4, evidence_ref, note} · `assumptions[]` · `limitations_acknowledged[]` · `limitations_unacknowledged[]` · `baseline_fairness` str · `ablation_sufficiency` str · `statistical_robustness` str · `selective_reporting` str · `reproducibility_gaps[]` · `generalization` str · `reviewer_questions[]` · `checklist` obj{standard enum[neurips,casp,cochrane_rob2,strobe,tripod_ai,prisma,consort,none], items[]{item,status enum[met,partial,unmet,na],note}} · `overall` str. **Advisory; no verdict/decision field.**

**`paper_relations` (P1, NEW):** required `[source_ref, edges]`. `edges[]`{target_ref, relation enum[inherits,refutes,unifies,replaces,opens,extends,uses], note}.

**`trend_card` (P1, NEW):** required `[scope]`. `shifts[]`{dimension enum[problem,method,representation,assumption,evaluation,resource], from, to} · `failure_modes[]` · `mechanism_vs_result` str · `reproducibility_trend` str|null · `opportunities[]` · `source_refs[]`.

**`domain_profile` (P1, extend — read the file first for its additionalProperties posture):** add optional `reading` obj{paper_type_default str|null, reporting_standards[] enum[tripod_ai,strobe,consort,prisma,neurips,casp,cochrane_rob2], appraisal_checklist str|null, notes str|null}.

**Registry:** each NEW schema gets one line in `tools/validate_artifact.py` `PAYLOAD_SCHEMAS`. **Lead serializes ALL registry edits** (parallel P1 agents create schema FILES + tests only; they do NOT edit the shared registry — avoids write race).

---

## PHASE CHECKLIST

- [x] **P0 Foundation** (lead, opus) — LEDGER · DB `04-templates/paper.md` rewrite · `paper_note` spine extension · `type-registry.md` paper frontmatter. VERIFIED (41 targeted tests green; schema validates + enforces enum/additionalProperties).
- [x] **P1 Machine schemas** (parallel opus ×4 + lead registry) — 5 new + 2 extended schemas + unit tests + registry lines. VERIFIED: full suite 2750 passed (0 regress); 5 new types validate via registry; paper_appraisal advisory-only (6 forbidden decision names rejected by additionalProperties:false).
- [x] **P2 DB enforcement** — lint_vault.py +2 WARN checks (READING_DEPTH graduation + READING_STATUS_ENUM) · INGEST contract (`00-system/CLAUDE.md`) · status-registry graduation subsection · 2 drift pages fixed→skimmed (no write-guard block). Lint exit 0, 0 errors, 59 READING_DEPTH WARN (legacy flags, intended), enum-drift 0. RE-VERIFY at P5.
- [x] **P3 Machine agents + assembler** — literature-ingest extended (v1.2.0, positioning+contract) · paper_ingest.py conditional-add (byte-identical when absent) · 5 new producers (paper-appraiser / method-teardown-extractor / figure-reader / paper-relations-mapper / trend-card-builder) + rostered under discover. Full suite 2753 green (produces-guard + roster consistency pass).
- [x] **P4 Wiring** — new `read_paper_deep` recipe (8-artifact card; drift + citation-integrity + existence hard gates fire; appraisal advisory; profile reading-hook; optional fulltext_qa pre-step) + `ingest_paper` (Tier-S) made operated; both wired into REGISTRY + mode_registry as `record_only` (amends D7); the claim-evidence ledger is produced single-paper in-recipe. Wiring-test mirror + routing guardrails pass. (Lead caught an incomplete-wiring gap on verification — recipes existed but weren't registered — and completed it.)
- [x] **P5 Green** — full machine suite **2768 passed** (0 fail, up from 2655 baseline). DB lint **EXIT 0**: 0 errors / 936 warn / 1894 info (59 READING_DEPTH legacy flags intended). Both re-verified by lead (not self-marked).
- [x] **P6 Codex work-orders** — `P6-codex-reread-work-orders.md` authored: reusable per-paper Codex 施工单 template + graduation acceptance criteria + prioritization + a worked example. Director-paced, on-demand. Legacy skims stay `skimmed` until pulled.

---

## HONESTY / BOUNDARY
- The reading build is no longer merely theoretical: as of 2026-07-01, `read_paper_deep` has one real local-PDF smoke run. GPU/EXECUTE boundary is unchanged: no real GPU experiment has been operated.
- Two-repo boundary kept: DB changes in the DB repo, machine changes in the machine repo; the card shape is mirrored in both, kept in sync by THIS ledger. The machine still never writes the vault except via `/promote-to-vault`.
- Crown-jewels read-only for content semantics (`evidence-contract`, `can-cite-thesis` derivation, `reading-status` citability gate) — we ADD graduation enforcement, we do not lower any existing floor.
- `paper_appraisal` is ADVISORY (a reading aid), never a governed verdict — it never auto-cuts a paper or self-decides anything.

## RUN LOG (append-only)
- 2026-06-26 — P0 opened; LEDGER created; design locked (D1-D8). Director approved Scope A + Codex-backfill. Mapping (3 opus agents) + design doc done in prior session.
- 2026-06-26 — P0 DONE: `paper_note` spine extended (additive-optional); DB template rewritten to 0+3+1; type-registry paper row + log. Verified 41 targeted tests green. P1‖P2 launched. NOTE: graduation enforcement = WARN during the migration window (hardens to ERROR at `reading-status ≥ read` after existing pages are migrated, so it never fail-alls the ~60 legacy pages).
- 2026-06-26 — P1 DONE: method_teardown, figure_reading, paper_appraisal (advisory, no verdict field), paper_relations, trend_card created + registered; claim_evidence_map (+directness/claim_risk) + domain_profile (+reading block) extended additive-optional; 7 real profiles revalidate. Full machine suite **2750 passed, 0 regress**. P2 (DB) still running.
- 2026-06-26 — P2 DONE: DB lint_vault.py +READING_DEPTH (graduation, WARN) +READING_STATUS_ENUM checks; INGEST contract + status-registry graduation subsection; 2 drift pages fixed→skimmed (no write-guard). Lint exit 0 / 0 errors / 59 graduation-WARN (legacy, intended) / enum-drift 0 (agent-reported, re-verify@P5). P3 launched (extend literature-ingest+assembler ‖ 5 new producer agents).
- 2026-06-26 — P3 DONE: literature-ingest v1.2.0 (positioning+contract gathering) + paper_ingest.py conditional-add (byte-identical when new facts absent, asserted) + 5 new producer agents created & rostered under discover (operate sub-workers, not in graph). Full machine suite 2753 passed, 0 regress. P4 (wiring) IN PROGRESS — serial, lead.
- 2026-06-26 — P4 + P5 DONE: read_paper_deep + ingest_paper recipes wired (REGISTRY + mode_registry operated, record_only); wiring-test mirror + routing guardrails pass. Lead verification CAUGHT an incomplete-wiring gap (recipe files existed but weren't registered — full suite passed trivially because the unwired modes didn't break the mirror), and completed the registration. Full machine suite **2768 passed**; DB lint **exit 0 / 0 errors** (re-verified, not trusting self-mark). Build GREEN + UNCOMMITTED (commits are the director's call). HONESTY NOTE (ingest_paper budget): ingest_paper's one-button path is its OPERATE recipe (run_dets DISCOVER+REPORT tested green); its legacy ENGINE-FSM path budget-bites at max_agent_hops:1 (documented in test_mode_discover_speconly_e2e.py). NOT bumped — bumping would dead-tail the engine REPORT stage (no REPORT agent in the subset), worse than a clean bite. read_paper_deep (the core 0+3+1 card) is fully drivable at budget 8. CONCURRENCY NOTE: lead + p4-wiring both edited the shared files; final state verified DUPLICATE-FREE (each mode once in __init__ REGISTRY + mode_registry). P6 (Codex work-orders) IN PROGRESS.
- 2026-06-26 — P6 DONE + BUILD COMPLETE: Codex re-read work-order package authored. ALL 7 phases done; machine **2768 green**, DB lint **exit 0**; both repos UNCOMMITTED (director's call). The 0+3+1 reading upgrade is live in both systems: DB paper page = the human card (graduated, LINT-enforced); machine emits the card via `read_paper_deep` (full 8-artifact card, drivable) + `ingest_paper` (Tier-S). Nothing operated on real research yet; GPU boundary unchanged.
- 2026-06-26 — P4 ARCHITECTURE DECISION (lead, amends D7): `read_paper_deep` + `ingest_paper` are `gate_level: record_only`, NOT director_signoff. Reading = DRAFT knowledge; the human gate is `/promote-to-vault`, so a director PAUSE at the DISCOVER boundary is redundant. The genuinely-applicable HARD gates (citation-integrity + live existence + north-star drift) STILL fire as deterministic cores (gate_level-independent). The evidence-verifier SATURATION gate is N/A for a single source, so it is honestly OMITTED — never listed-then-skipped (that would be a fake gate). The 5 new producers stay operate sub-workers (not in graph allowed_agents / not in agent_subset), per the P3 roster design; the recipe dispatches them. (Surfaced by p4-wiring hitting validate_routing guardrails 1+2 — correct catch.)
- 2026-07-01 — STATUS CONSISTENCY + REAL PDF RUN: Codex runtime mapping added to worker specs/logs (`runtime_model=gpt-5.5`, `reasoning_effort=xhigh`, `service_tier=priority`; `opus/sonnet` retained only as logical tiers). Added `operate fulltext-pre` and PyMuPDF local-PDF fallback, hardened mode `stage_path`/late hard-gate validation, removed deep-ideation pseudo-agent labels, normalized agent tool declarations away from `Bash`, and fixed secondary `produces` fields. Real smoke run `read-skeleton-recall-20260701` (project `iac-cbct-seg`) copied a local Skeleton Recall Loss PDF into run scratch, extracted 70 page contexts, emitted the full 8 reading artifacts, passed DISCOVER citation/existence/drift gates, and committed REPORT. Targeted regression set: 86 passed; full machine suite: **2782 passed**.
