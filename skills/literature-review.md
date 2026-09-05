# literature-review — evidence-synthesis protocol

> Adapted from K-Dense `scientific-agent-skills/literature-review` v1.0 (MIT) on 2026-06-10.
> Stripped: parallel-cli plumbing, PubMed/bioRxiv bio-vertical emphasis, gget/bioservices,
> LaTeX/PDF generation, mandatory figures. Absorbed: the 7-phase systematic protocol, PRISMA-style
> screening accounting, and high-impact prioritization — rewired to the machine's evidence
> discipline (evidence_table + claim chains + deterministic gates).

## When a worker uses this

`evidence_review` / `evidence_deep` / `deep_research` DISCOVER workers building a verified
evidence picture; lit-scout assembling a graded source set.

## First freeze the review identity

`METHODOLOGICAL_CRITICAL_REVIEW`, narrative review, scoping review, and systematic review are different products. Do not let a large corpus silently promote a critical review into a PRISMA claim. Use SANRA as a pragmatic quality lens for narrative/critical reviews; use PRISMA/PRISMA-S only when the manuscript actually claims the corresponding review conduct. PRESS-style search peer review is recommended for load-bearing absence claims.

## The 7-phase protocol (adapted)

1. **Plan & scope** — restate the request as a precise question; pick 2-4 main concepts +
   synonyms; set explicit inclusion/exclusion bounds (years, domains, study types). Record the
   bounds in the bundle — an unstated scope is an audit finding.
2. **Declared search** — the sanctioned connector (`tools/paper_search.py` /
   `inbox/search-results.json`) across arXiv + OpenAlex + Crossref + S2, PLUS the vault by
   reference (`[[slug]]` clusters are prior verified reading). Two passes: concept-focused, then
   a counter-evidence pass (search for the claim's negation — missing counter-evidence is the
   classic review failure). Add logged-in/manual channels such as IEEE Xplore only through the receipt discipline in `skills/research-lookup.md`; `NOT_EXECUTED` is not a search.
   For a broad or many-named question, the four-stage funnel (`tools/search_funnel.py`, see
   `skills/research-lookup.md`) fuses the channels' own rankings, reranks by best abstract passage,
   and proposes related queries for the next pass; its scores are triage only, never grading.
3. **Screen & select** — title screen → relevance screen against the stated criteria; KEEP the
   accounting PRISMA-style: `found N → deduped M → screened K → graded into the table J`.
   The dedup is the facade's job; the screening judgment is yours; the counts go in your
   hand-back line.
4. **Extract & grade** — per kept report version: a compact `SOURCES.tsv` row plus long-form `EVIDENCE.tsv` loci. Record `version_read`, access scope, supplement/figure/code scope, acquisition receipt, and value origin. Readers transcribe exact text; suspected source errors are separate annotations. `RE_DERIVED`/`REVIEWER_COUNT` values require formula and input loci and may never be attributed as source-reported.
   honest `claim_support` (strong = directly and centrally supports THE query; prestige ≠
   support). Full-text page anchors come from the `fulltext_qa_report` channel when present.
5. **Synthesize** — claims (`claim_list`) anchored by loci (`claim_evidence_map`) with explicit
   per-locus `supports_claim`; contradictions surfaced, never resolved by you
   (contradiction-miner / reviewer panel territory).
   Persist every three full-text reads; write the batch synthesis separately. Section authors receive only queryable rows relevant to their section, not the full corpus or copied nested bundles.
6. **Verify citations** — every external ref you cite is checkable by
   `tools/citation_existence.py`; every vault ref is a REAL `[[slug]]`. A reference you cannot
   point at does not enter the table.
7. **Saturate honestly** — `saturation_reached: true` only after a snowball round
   (`get_references_s2` / `get_citations_s2` on the strong hits) surfaces nothing new. Thin
   coverage is reported thin; the evidence-verifier gate BLOCKs on unsaturated tables and that
   is correct behaviour, not an obstacle.

## High-impact prioritization (absorbed; triage-only)

Prefer reading order by the citation/venue tables in `skills/research-lookup.md`. Same boundary:
triage heuristics, never review grounds, never a reason to inflate `claim_support`.

## Output

Keep the FSM's compact evidence boundary (`evidence_table` + `claim_list` + `claim_evidence_map`) but do not use it as the authoring surface. Manuscript workers retrieve from `REVIEW-METHOD.md`, `MANUSCRIPT-ONTOLOGY.md`, `SOURCES.tsv`, `EVIDENCE.tsv`, and `refs.bib`. Do not create a task-specific script or another JSON representation merely to pass content between agents.
