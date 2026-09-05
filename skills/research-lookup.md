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
`RAT_OPENALEX_API_KEY`, `RAT_S2_API_KEY`, `RAT_CONTACT_MAIL`. In operated runs the recipe pre-step drops the same
result shape at `runs/<run>/inbox/search-results.json` — read that first.)

### Logged-in/manual scholarly channels

The free facade is not proof that IEEE Xplore, Scopus, Web of Science, or another declared database was searched. When the director authorizes a logged-in browser search, the primary host may operate that browser and save a **manual acquisition receipt** into the run. For IEEE Xplore record:

- `acquisition_channel=IEEE_XPLORE_MANUAL`;
- exact query, filters, sort, result count, and execution date;
- IEEE document ID, DOI, and result/detail URL;
- exported citation or local PDF path and version actually read;
- local snapshot SHA-256 after download/import.

Never save cookies, tokens, headers, or account details. If browser control fails, emit the exact query worksheet for the director and mark the channel `NOT_EXECUTED`; a suggested query is not a completed search. Search-page metadata remains noncitable until the full source/version/locus is admitted.

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

## Four-stage funnel + recursive expansion (AgentSearch absorption, 2026-09-05)

When one flat facade search is not enough — a broad question, a method with several names, or a
first pass whose top hits are all one-channel — run the funnel instead of re-querying by hand:

```bash
python -m research_agent_teams.tools.search_funnel "<query>" --final 10 --json <out>
python -m research_agent_teams.tools.search_funnel "<query>" --depth 2 --breadth 2 --json <out>
```

Pattern absorbed from SciPhi AgentSearch (Apache-2.0, pinned commit `b47b932`, last upstream change
2024-01-16). Its hosted API was unreachable on 2026-09-05 and its local engine needs a 1.26 TB 2023
snapshot, so only the recipe is absorbed — clean-room, no package installed. Four stages over the
same four sources:

1. **Broad recall** per source (default 20 each) through `paper_search.search`, which now also
   returns each provider's own order as `channel_rankings`.
2. **Cross-channel fusion**: Reciprocal Rank Fusion of those rankings after the title-relevance
   gate — a record two channels agree on outranks a one-channel hit, whatever its citation count.
3. **Best-passage rerank**: one batched OpenAlex request fetches abstracts for the fused DOIs (or
   supply local full text through `text_provider`); the passage that best matches the query becomes
   `text` (≤ 400 chars) and `passage_score`, averaged with the fused rank into `relevance`.
4. **Authority blend**: `score = 0.9 × relevance + 0.1 × authority`, authority = log-scaled
   citations + recency (`--alpha` moves the weight; 0 = relevance only, 1 = authority only).

`--depth N` runs the recursive expansion: every round proposes `related_queries` from the retrieved
titles (each with a `support` count of how many titles carry the new term), follows `--breadth` of
them, and stops when two rounds in a row add no new record. That is an **expansion stop**
(`expansion_stop_reason`), never saturation: `search_funnel.trace_rounds()` hands the
evidence-search-moderator `evidence-search-trace/v1` round skeletons (questions + source_hits only),
and `evaluate_search_trace` still derives completion from claims, contradictions and
representativeness.

**Operated runs run it by default** (director decision 2026-09-05): `operate pre-search` runs the
funnel over the same query plan right after the facade search — depth 1 in every DISCOVER-entry
mode, depth 2 / breadth 2 in `deep_research` (one round of related queries). What the worker sees:

- `inbox/search-results.json` keeps its shape; its records now carry `funnel_rank` /
  `funnel_score`, records only the funnel found are appended as metadata rows
  (`found_via: search-funnel`, no snippet), the list is ordered by funnel rank, and
  `related_queries` + a `funnel` summary (stage counts, expansion stops, channels lost) are attached.
  The facade's own `source_errors` and `relevance_filter` are never touched.
- `inbox/search-funnel.json` holds the full result: per-query stage counts, rounds, the `text`
  passage per record. Read it for the snippet, never cite it.
- A funnel failure is recorded as `funnel.status: failed` and the run continues on the facade
  bundle. Flags: `--funnel-depth N`, `--funnel-breadth N`, `--no-funnel`.

Boundaries (machine rules, override the source): every score and the `text` snippet are search
triage — they never grade `claim_support`, never enter an evidence row (`to_evidence_sources`
ignores them), and never replace reading the source. Channel loss stays loud: `channels_lost`,
`source_yield`, `source_errors` (including `openalex_abstracts` when the abstract fetch fails and
ranking falls back to fusion only).

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

Results enter evidence by reference. For long-corpus manuscript work, persist one compact row per report version in `SOURCES.tsv`; keep raw provider exports in `inbox/` only when they are needed to reproduce the search. `claim_support` starts at `none` and is upgraded only after the actual source/version was read. Do not copy the same provider metadata through multiple JSON layers.
