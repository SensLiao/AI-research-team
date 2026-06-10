# research-lookup — sanctioned live scholarly lookup (machine skill, absorption wave 1)

> Adapted from K-Dense `scientific-agent-skills/research-lookup` v1.0 (MIT) on 2026-06-10.
> Their backend plumbing (parallel-cli / Parallel Chat API / Perplexity via OpenRouter) is
> REPLACED by this machine's sanctioned deterministic connector; their mandatory-figures rule is
> dropped (anti-slop). What is absorbed: the routing discipline and the paper-quality
> prioritization tables.

## What this skill is

How a machine worker looks up CURRENT research information — papers, claims to verify, citation
candidates — through the ONE sanctioned channel:

```bash
python -m research_agent_teams.tools.paper_search "<query>" --sources arxiv,openalex,crossref,s2 --limit 8 --json <out>
```

(arXiv + OpenAlex + Crossref + Semantic Scholar, free-first, NO Sci-Hub; optional env:
`RAT_S2_API_KEY`, `RAT_CONTACT_MAIL`. In operated runs the recipe pre-step drops the same
result shape at `runs/<run>/inbox/search-results.json` — read that first.)

## Routing discipline (absorbed pattern)

- **Default**: one facade search across all four sources; dedup/merge is the tool's job.
- **Citation-graph follow-up**: for a strong hit, snowball through
  `scholar_clients.get_references_s2` / `get_citations_s2` (the Asta decompose→search→
  follow-citations recipe) rather than re-querying with paraphrases.
- **Existence verification**: a specific claimed reference (DOI / arXiv id / title) is checked
  with `tools/citation_existence.py` (three-state verified / not_found / lookup_error) — never
  by eyeballing search results.
- **Retraction check**: DOIs that will carry evidence weight go through
  `tools/fulltext_qa.retraction_check` before being graded "strong".

## Paper quality prioritization (absorbed tables)

Citation-based ranking when triaging results:

| Paper age | Citations | Classification |
|-----------|-----------|----------------|
| 0-3 years | 20+ | Noteworthy |
| 0-3 years | 100+ | Highly influential |
| 3-7 years | 100+ | Significant |
| 3-7 years | 500+ | Landmark |
| 7+ years | 500+ | Seminal |
| 7+ years | 1000+ | Foundational |

Venue tiers (AI/CS-relevant subset): Tier 1 = Nature/Science/PNAS + NeurIPS/ICML/ICLR/ACL/CVPR;
Tier 2 = IF>10 journals + strong subfield conferences (EMNLP/ECCV/MICCAI); Tier 3 = respected
specialized venues.

**Boundary (machine rule, overrides the source skill):** these tiers are SEARCH-TRIAGE
heuristics only — which results to read first. They are NEVER review/reject grounds: the venue
personas' anti-bias suppressors forbid prestige-based judgment, and `claim_support` grading must
reflect what a source demonstrates for the query, not its tier.

## Output discipline

Results enter evidence as BY-REFERENCE rows (`to_evidence_sources`: DOI / arXiv id / URL — never
inlined content), `claim_support` arrives "none" and is upgraded only by a worker that actually
judged the content. Search provenance (which APIs returned the record) lives in the row's
`notes`. Save full result JSON into the run's `inbox/`, never into the vault.
