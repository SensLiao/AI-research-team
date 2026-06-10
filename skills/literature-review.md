# literature-review — systematic review protocol (machine skill, absorption wave 1)

> Adapted from K-Dense `scientific-agent-skills/literature-review` v1.0 (MIT) on 2026-06-10.
> Stripped: parallel-cli plumbing, PubMed/bioRxiv bio-vertical emphasis, gget/bioservices,
> LaTeX/PDF generation, mandatory figures. Absorbed: the 7-phase systematic protocol, PRISMA-style
> screening accounting, and high-impact prioritization — rewired to the machine's evidence
> discipline (evidence_table + claim chains + deterministic gates).

## When a worker uses this

`evidence_review` / `evidence_deep` / `deep_research` DISCOVER workers building a verified
evidence picture; lit-scout assembling a graded source set.

## The 7-phase protocol (adapted)

1. **Plan & scope** — restate the request as a precise question; pick 2-4 main concepts +
   synonyms; set explicit inclusion/exclusion bounds (years, domains, study types). Record the
   bounds in the bundle — an unstated scope is an audit finding.
2. **Systematic search** — the sanctioned connector (`tools/paper_search.py` /
   `inbox/search-results.json`) across arXiv + OpenAlex + Crossref + S2, PLUS the vault by
   reference (`[[slug]]` clusters are prior verified reading). Two passes: concept-focused, then
   a counter-evidence pass (search for the claim's negation — missing counter-evidence is the
   classic review failure).
3. **Screen & select** — title screen → relevance screen against the stated criteria; KEEP the
   accounting PRISMA-style: `found N → deduped M → screened K → graded into the table J`.
   The dedup is the facade's job; the screening judgment is yours; the counts go in your
   hand-back line.
4. **Extract & grade** — per kept source: a by-reference row (`id/kind/ref/title/year`) +
   honest `claim_support` (strong = directly and centrally supports THE query; prestige ≠
   support). Full-text page anchors come from the `fulltext_qa_report` channel when present.
5. **Synthesize** — claims (`claim_list`) anchored by loci (`claim_evidence_map`) with explicit
   per-locus `supports_claim`; contradictions surfaced, never resolved by you
   (contradiction-miner / reviewer panel territory).
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

The bundle shapes the recipes expect (`evidence_table` + `claim_list` + `claim_evidence_map`);
deterministic gates (evidence-verifier, citation-integrity-auditor) judge them. If a REPAIR
ATTEMPT block arrives, fix exactly the gate feedback and re-emit the complete bundle.
