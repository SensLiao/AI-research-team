# Paper-Reading Upgrade — Gap Analysis & Design (0+3+1 Protocol)

> **Superseded / implemented status (2026-07-01):** this is the original proposal and design rationale. The build it proposes is now implemented; `ingest_paper` and `read_paper_deep` are operated modes, `fulltext-pre` can copy local PDFs into run scratch and extract page contexts via PyMuPDF fallback, and the smoke run `read-skeleton-recall-20260701` completed on a real PDF. Use `paper-reading-upgrade-LEDGER.md` and `../../PLATFORM-FACTS.md` for current facts.

> **Original status (2026-06-26):** PROPOSAL — awaiting director's scope decision. Nothing built yet.
> **Date:** 2026-06-26 · **Author:** lead (opus, max_quality) over 3 read-only mapping agents.
> **Spans both systems:** System D (DB = `AI agent database/PhD-Research-OS/`) + System M (machine = `research_agent_teams/`).
> **Trigger:** director's upgraded *0+3+1 research-reading protocol* (Stage-0 positioning · 3 passes · Stage-4 concept-centric synthesis + paper-type lenses + reporting standards).
> **Note:** the project-root `_design/` referenced by project CLAUDE.md §8 is no longer on disk; this doc is placed inside the versioned machine repo (`research_agent_teams/_design/`) so it survives.

---

## 0. Executive finding (the reframe)

Both systems were mapped independently and **corroborate one story**:

> **~60% of the 0+3+1 protocol's substance already exists as parts.** The work is NOT "invent a reading system from scratch." It is **(a) add a missing FRONT-END** (Stage-0 positioning + paper-type + Pass-1 5-C contract), **(b) WIRE existing machinery to single-paper reading** (the claim→evidence ledger; the page-anchored full-text reader), **(c) RE-POINT the existing 7-dimension appraisal rubric OUTWARD** (it currently judges the machine's own manuscript, not a paper being read), **(d) add a small BACK-END** (typed paper↔paper relations + a trend card), and **(e) ENFORCE** the already-rich DB template as a graduated default instead of an ignored suggestion.

Three load-bearing facts, personally verified (not second-hand):

1. **DB already has a full 3-pass paper template** — `04-templates/paper.md`: `TL;DR → Pass 1 Big picture → Pass 2 Method → Results table → Pass 3 Critique & relevance → Links → Reading log`. It is **scaffolding, not a contract** (LINT checks frontmatter/links, never body depth) → ~80% of ~60 paper pages are thin 4-section skims.
2. **Machine's single-paper output (`paper_note`) is thin** — required `[title, source_ref, summary, claims]` with `claims` as **flat strings**, `additionalProperties:false`. That is the entire "read a paper" output today.
3. **Machine's 7-D appraisal rubric is reusable but inward** — `agents/references/venue-rubrics/rubric-7d.md` (D1 Soundness · D2 Significance · D3 Originality · D4 Eval-Rigor/Fairness · D5 Reproducibility · D6 Clarity · D7 Clinical-Validity, with 1-4 anchors, `paper_type`-awareness, and non-scoring Limitations/Ethics checks). It aims at **venue-accepting the machine's own result**, not at appraising an external paper. ~80% of an outward per-paper appraisal checklist already written, pointed the wrong way.

---

## 1. Current-state map (consolidated, with file paths)

### 1.1 System D — how a read paper is stored
- **Page type** `type: paper`, folder `02-wiki/papers/<thread>/`; defined `05-registry/type-registry.md` + `00-system/CLAUDE.md`.
- **Frontmatter** (required): universal 18-field block + paper-specific `authors, year, venue, reading-status, relevance`; always `evidence-class: PAPER-CITE`. Optional: `doi, url, key-claims, serves-claim`.
  - **Stage-0-ish dials already present:** `reading-status ∈ {to-read|skimmed|read|deep-read|cited|deprecated}` (depth) + `relevance ∈ {direct|adjacent|background}` (A/B/C relation).
  - **`reading-status` is the de-facto thesis-citability gate** — `06-scripts/render_claim_chain.py` enforces "略读的论文不让引" (`00-system/how-to-operate.md`). So an un-deepened skim is structurally non-citable. The unenforced depth is a **real downstream limiter**, not cosmetic.
- **Body template** = the rich 3-pass structure above, but **enforcement = almost none** (`06-scripts/lint_vault.py` 9 checks: orphans/links/stubs/stale-confidence/registry/missing-source/dup-slugs/derived-field — never body sections).
- **Three coexisting shapes:** skim (~80%: `TL;DR/Key contributions/Relevance/Source`), deep-read (~8: full template, e.g. `koleilat-2025-biomedcoop.md` with per-term loss `L=L_CE+λ₁L_SCCM+λ₂L_KDSP`; `cheng-2024-h-sam.md` with code-anchored cites), bespoke (~10: role-driven headings, some Chinese).
- **The `claim` graph is empty:** the `claim` page type is fully specified (`evidence-for/against/audit`) but **zero `claim` pages exist**; `serves-claim`/`rq`/`contrib` are empty on skims. The paper card is a **dead-end node**, not wired into a claim/evidence graph.
- **Schema drift:** 2 papers carry `reading-status` outside the enum (`web-verified-2026-06-08`, `shallow-read`).

### 1.2 System M — how the machine reads papers
- **Reading = corpus/claim-evidence pipeline, not per-paper deep reading.** Modes: `ingest_paper` (SPEC-ONLY, not in the one-button operate REGISTRY `operate/modes/__init__.py`) emits thin `paper_note`; `evidence_review`/`evidence_deep`/`deep_research` (WIRED) read a *body of literature* and emit graded `evidence_table` + `claim_evidence_map` + `contradiction_report` + `landscape_map`.
- **Single-pass per paper.** "Deep" modes add **breadth** (more agents / perspectives / cross-domain analogy), never re-read one paper in deepening passes. Wired modes also **consolidate the reading subteam into ONE worker prompt**.
- **The claim→evidence ledger is gate-grade but decoupled from single-paper reading.** `claim_list → claim_evidence_map` (`loci[]{location, kind, reported_result, supports_claim}`, `overall_support`) is real and enforced — but fed by `lit-scout`/DISCOVER over a query's source set, **not** by single-paper `paper_note` ingestion. Directness = implicit; risk = scattered across `calibrated_claims`/`source_quality_report`/`fulltext_qa.retraction_flags`.
- **Full-text reading is BUILT but UNWIRED.** `tools/fulltext_qa.py` (PaperQA2 page-anchored QA + Crossref retraction check, schema `fulltext_qa_report`) exists; **no operate recipe produces `inbox/fulltext-qa.json`**. Every one-button reading run operates on **titles/abstracts + vault pages**, not paper full text. `deep_research` even tracks a self-reported `fulltext_reads` counter with no wired reader.
- **Critical appraisal is rich but inward.** `review_report` (5 checks), `venue_review` (7-D rubric + reject-triggers + Limitations/Ethics), `baseline_audit_report`, `threats_report`, `power_audit_report`, `preregistration` — ALL score the machine's own result/manuscript. The one outward appraisal, `weakness_report`, is framed as gap-hunting, not full per-paper appraisal.
- **Stage-4 synthesis = strong opportunity machinery, weak literature-network.** `landscape_map` (method×source coverage + gaps), gap/white-space/collision family, novelty-collision gate (`novelty_collision_report` + known-prior-art ledger) are strong. But **typed paper↔paper edges (inherits/refutes/unifies/replaces/opens) are ABSENT**, concept matrix is method×source only, **trend card is ABSENT** (only a prose `sub-domain-historian`).
- **Profiles tune experiments, not reading.** `domain_profile` (`schemas/domain_profile.schema.json`, `profiles/*.profile.yaml`) carries `split_policy/leakage_checks/metrics/hard_invariants/idea_grounding` — **no reading-lens / paper-type / reporting-standard hook**. So Pass-3/Stage-4 rigor is not domain-tunable the way experiments are.
- **Registry mechanism:** `tools/validate_artifact.py` `PAYLOAD_SCHEMAS` dict (~95 types), double-validated (envelope + payload, Draft 2020-12). **Adding a capability = add a schema file + register one line.** Low-friction extension point.

---

## 2. Coverage vs the 0+3+1 protocol (both systems)

| Protocol element | System D (DB page) | System M (machine) | Net |
|---|---|---|---|
| **Stage 0** positioning (why · paper-type · A/B/C · depth · 1-line objective) | PARTIAL (`reading-status`+`relevance` dials; no purpose/type/objective) | ABSENT (`paper_note` has none) | **biggest front-end gap** |
| **Pass 1** 5 C's → paper contract | PARTIAL (template Pass-1; no 5-C scaffold, no applicability) | ABSENT (free-paragraph summary) | **front-end gap** |
| **Pass 2** claim→evidence→location→directness→risk | ABSENT (flat `key-claims` prose) | **PRESENT** (ledger) but **not wired to single-paper**; directness/risk under-typed | **WIRING gap (machinery exists)** |
| **Pass 2** method teardown · formula→ablate-it · figure reading | PARTIAL method, ABSENT formula/figure | ABSENT per-paper | **new small schemas** |
| **Pass 3** appraisal (assumptions/baseline-fairness/ablation/stats/selective-reporting/repro) + formal checklist | PARTIAL (limitations only) | **PRESENT but INWARD** (7-D rubric reusable) | **RE-POINT outward** |
| **Stage 4** typed relations · concept matrix · trend card · opportunity | ABSENT on page (displaced to `syntheses/`) | PARTIAL (strong opportunity; ABSENT relations/trend) | **new back-end (relations+trend)** |
| Paper-type lenses + reporting standards (PRISMA/CONSORT/STROBE/TRIPOD+AI) | ABSENT | ABSENT (rubric is `paper_type`-aware seed) | **new, profile-tunable** |
| One-page research card | PARTIAL (deep-read body ≈ card; ~80% never reach it) | PARTIAL (`paper_note` is the card, thin) | **unify + graduate + enforce** |

---

## 3. The design — ONE canonical Research Card, graduated, seam-aligned

**Core idea:** define **one canonical "Research Card" shape spanning 0+3+1**, *produced by the machine* and *stored by the DB as a `paper` page* — so the seam stays coherent (today `paper_note` is thin while the DB template is rich; they diverge). The card is **graduated by reading depth**, reusing the existing `reading-status` ladder as the depth dial:

- **Tier S (skim)** = Stage 0 positioning + Pass 1 contract (5 C's + one-sentence contract). Cheap, allowed, but now **typed and honestly labeled**. Non-citable in thesis (gate unchanged).
- **Tier D (deep-read)** = full 0+3+1: Stage 0 + Pass 1 + Pass 2 (claim-evidence table + method teardown + figure reading) + Pass 3 (appraisal checklist) + Stage 4 (typed relations + trend/implications). Citable.
- **Tier R (reproduce-level)** = Tier D + method teardown to per-term loss + reproducibility checklist + (optional) code-anchored cites. The "I could re-implement this" bar.

Graduation is the **honesty mechanism**: we never pretend an 80%-skim is deep; we type it Tier S and make the rich card the enforced default only for D/R.

---

## 4. Detailed changes by stage (DB ‖ machine; REUSE vs NEW flagged)

### Stage 0 — positioning  *(front-end · NEW, small)*
- **DB** frontmatter += `paper-type` (method/theory/empirical/dataset-benchmark/tool/review/position), `read-purpose` (idea/method/baseline/related-work/reproduce/review), `reading-objective` (one line). Reuse `reading-status` (depth) + `relevance` (A/B/C). Touch: `05-registry/type-registry.md`, `04-templates/paper.md`, `00-system/CLAUDE.md` INGEST contract.
- **Machine** `paper_note.schema.json` += `paper_type`, `read_purpose`, `relation_to_thesis`, `reading_objective`, `tier`. Reuse the `paper_type` enum already in the venue rubric (single source). Touch: `schemas/paper_note.schema.json`, `agents/literature-ingest.md`, `tools/paper_ingest.py`.

### Pass 1 — 5-C contract  *(front-end · NEW, small)*
- **DB** template: add a "Reading contract" block — 5 C's (Category/Context/Correctness/Contributions/Clarity) + one-sentence contract (problem→method→vs-prior→evidence→applicability).
- **Machine** `paper_note` += `paper_contract{category, context, correctness_prior, contributions[], clarity, contract_sentence}`.

### Pass 2 — method+evidence teardown  *(WIRE existing + 2 NEW small schemas — highest leverage)*
- **Machine (wiring, REUSE):** wire `claim_list → claim_evidence_map` to **single-paper** ingestion so a read paper produces per-claim loci (not flat strings). Add `directness ∈ {direct|indirect|proxy|assumed}` + `risk` to the claim row. **Wire `fulltext_qa.py`** into the deep/reproduce path (page-anchored evidence + retraction check) — the single highest-leverage fix. Touch: `operate/modes/{evidence_deep,deep_research}.py` + a new single-paper read recipe, `schemas/claim_evidence_map.schema.json`, `operate/modes/_shared.py`.
- **Machine (NEW):** `method_teardown.schema.json` (problem-def / core-assumptions / representation / loss-per-term / train-infer flow / data / cost) + `figure_reading.schema.json` (axes / controls / error-bars / take-home / distrust). Register both in `tools/validate_artifact.py`.
- **DB** template: replace flat `key-claims` prose with a **claim→evidence→location→directness→risk TABLE**; add method-breakdown scaffold (per-term loss); add figure-reading block.

### Pass 3 — outward critical appraisal  *(RE-POINT existing + paper-type checklist)*
- **Machine (REUSE→re-point):** new `paper_appraisal.schema.json` = the venue-7D rubric **aimed at a read paper** (assumptions · limitations ack-vs-unack · baseline-fairness · ablation-sufficiency · statistical-robustness · selective-reporting · reproducibility-gaps · generalization + reviewer-mode questions). New `paper-appraiser` agent reusing `venue-reviewer-persona` discipline. Add a paper-type-selected formal checklist artifact (NeurIPS-checklist / CASP / Cochrane RoB2 / STROBE / TRIPOD+AI).
- **DB** template: extend Pass-3 from "limitations ack/unack" to the full scaffolded appraisal checklist.

### Stage 4 — concept-centric synthesis  *(NEW back-end + reuse synthesis types)*
- **Machine (NEW):** `paper_relations.schema.json` = typed paper→paper edges (`inherits|refutes|unifies|replaces|opens|extends|uses`); `trend_card.schema.json` (problem-/method-/representation-/assumption-/eval-/resource-shift + failure-modes + mechanism-vs-result + reproducibility-trend + opportunity). Reuse `landscape_map` for the coverage matrix; optionally add concept/attribute axes.
- **DB:** emit typed relations from the paper card (beyond untyped `related:`); add a Stage-4 block (typed relations + implications-for-thesis + opportunity). Reuse existing `synthesis`/`comparison`/`concept` types as the cross-paper home, linked from the card.

### Enforcement + graduation + migration  *(DB · the part that makes it real)*
- **DB LINT:** add body-section presence checks **keyed to `reading-status` tier** (S = Stage0+Pass1 required; D = full 0+3+1; R = +method-teardown+reproducibility). Fix the 2 enum-drift values. Make the rich template the enforced default for D/R. Touch: `06-scripts/lint_vault.py`, `05-registry/status-registry.md`.
- **Migration (honest, cheap-default):** do **NOT** force-rewrite the ~80% skims. Type them Tier S, label honestly, offer **on-demand re-deepening** (deepen a paper when it needs to become citable). Normalize the ~8 deep-read + ~10 bespoke pages to the canonical card opportunistically.

### Profile hooks for reading rigor  *(machine · makes it domain-general, per §5 hard rule)*
- Extend `domain_profile.schema.json` with a `reading` block: paper-type lens defaults + reporting-standard selection per domain (med-imaging → TRIPOD+AI / clinical lenses; NLP → NeurIPS-checklist; …). So reading rigor becomes domain-tunable like experiment rigor already is.

### One-button wiring  *(machine)*
- Wire `ingest_paper` into the operate REGISTRY (`operate/modes/__init__.py`) so "ingest/read this paper" is genuinely one-button and emits the canonical card at the chosen tier. (Today it is spec-only.)

---

## 5. Test / risk / boundary impact (honest)
- Machine has **2655 green tests**. `paper_note.schema.json` is `additionalProperties:false` → adding fields requires schema + test updates. All new schemas are additive (new files + one registry line each) — low blast radius, but each needs unit tests (the repo's norm). DB LINT change adds checks → run against the existing ~60 pages and expect the 2 drift values + many "skim missing Pass-1 contract" findings (graduate, don't fail-all).
- **Boundaries respected:** two-repo separation kept (DB changes in the DB repo, machine changes in the machine repo); the canonical-card shape is *defined in both* and *kept in sync by this doc as SSOT* — it does not make the machine write the DB (still only `/promote-to-vault` writes the vault). Crown-jewels rules (`evidence-contract`, `can-cite-thesis` derivation, status-registry) read-only. Domain-general (rigor in profiles, not hardcoded).
- **GPU boundary unchanged:** this is all reading/representation; no experiment execution. Still tested-not-operated for real GPU runs.
- **`_design/` discrepancy** surfaced: project-root `_design/` absent on disk; this doc lives in the versioned machine repo instead.

---

## 6. Scope options (director decides)
- **Option A — Full single-pass (recommended; matches director's single-pass preference):** all of §4, both systems, one comprehensive build with live ToDo + a build-LEDGER. Largest, most coherent; biggest token/test cost.
- **Option B — Core-first:** canonical card + Stage-0/Pass-1 front-end + wire claim-evidence ledger + wire full-text reader + re-point appraisal outward + DB enforcement/graduation. **Defer** trend-card/concept-matrix/profile-hooks/`ingest_paper`-operate-wiring to a Wave 2. Captures the highest-leverage ~70% first.
- **Option C — Design-only:** stop at this doc; implement later.

**Recommended sequencing inside A/B** (dependency order): canonical-card schema (foundation) → Stage-0/Pass-1 front-end → wire claim-evidence ledger + full-text reader (Pass-2) → re-point appraisal (Pass-3) → DB enforcement/graduation → trend/relations (Stage-4) → profile hooks → operate wiring.

### Open decisions for the director
1. **Scope:** A / B / C.
2. **Migration stance:** leave-and-label existing skims as Tier S + normalize the few deep pages (recommended) — or also bulk re-deepen the high-relevance subset now (expensive, many runs).
3. **Persist location confirm:** machine repo `research_agent_teams/_design/` (chosen here) — or elsewhere.

---

## 7. Honesty boundary
Everything above is **DESIGN / PROPOSAL**. Nothing is built. No DB page changed, no machine schema/agent/mode changed, no test run. "~60% already exists" means the *parts* exist (claim-evidence ledger, venue-7D rubric, landscape/gap/collision machinery, the rich DB template, the reading-status/relevance dials) — they are not yet composed into a single graduated per-paper reading flow. The remaining ~40% (Stage-0 front-end, outward appraisal card, typed paper-relations, trend card, reading-profile hooks, the wiring + enforcement) is genuinely new or unwired.
