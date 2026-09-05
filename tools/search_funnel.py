"""Four-stage retrieval funnel + recursive related-query search (AgentSearch absorption, 2026-09-05).

Pattern absorbed from SciPhi AgentSearch (https://github.com/SciPhi-AI/agent-search, Apache-2.0,
pinned commit b47b9327f9a47d09995a09a3079b718d5ddb73c5, last upstream change 2024-01-16). It is
re-implemented natively against the documented pipeline (README / docs/source/api/main.rst /
agent_search/app/server.py / examples/recursive_agent_search.py); no upstream code is copied, and the
machine keeps its stdlib-only, injectable-transport, offline-testable discipline.

What AgentSearch does over ONE vector index (Qdrant over its 1.26 TB 2023 web snapshot) this module
does over the machine's sanctioned scholarly channels:

  stage 1  broad recall          fan the query across arXiv / OpenAlex / Crossref / Semantic Scholar
                                 (``paper_search.search``; deduped by DOI -> arXiv id -> title)
  stage 2  cross-channel fusion  Reciprocal Rank Fusion of each channel's OWN ranking
                                 (``recall.fuse_rrf``, k=60) after the multilingual title-relevance
                                 gate; a record two channels agree on outranks a one-channel hit
                                 (AgentSearch: broad similarity search -> unique-URL selection)
  stage 3  best-passage rerank   per record, the passage of its abstract (one batched OpenAlex
                                 request per 50 DOIs, or caller-supplied text) that best matches
                                 the query; relevance = mean(rrf, passage)
                                 (AgentSearch: hierarchical per-URL best-chunk reranking)
  stage 4  authority blend       score = (1 - alpha) * relevance + alpha * authority, where
                                 authority = log-scaled citations + recency
                                 (AgentSearch: ``pagerank_importance`` = 0.1 domain-rank blend)

plus ``recursive_search``: depth x breadth expansion over machine-proposed related queries
(AgentSearch ``examples/recursive_agent_search.py``), stopping early when two trailing rounds add
no new record. That stop is an EXPANSION stop, never an evidence-saturation verdict: the trace
rounds it emits carry no claims/findings, and ``evidence_search_trace.evaluate_search_trace`` still
derives completion on its own.

NOT absorbed, and why (verified 2026-09-05): the hosted SciPhi API (``api.sciphi.ai`` times out,
``www.sciphi.ai`` fails the TLS handshake, ``search.sciphi.ai`` is a dead Vercel deployment, so no
key can be obtained); the Sensei-7B RAG model behind ``/search_rag``; the AgentSearch-V1 dataset
(a 2023 snapshot needing Postgres + Qdrant + 768-d Jina embeddings). The PyPI package (0.1.0,
2024-01-14) pins pydantic<2 / openai 0.27.8 / Python<3.12 and is not installed.

Machine rules kept: metadata by reference; ``text`` is a triage snippet (<= 400 chars) that never
enters an evidence row (``paper_search.to_evidence_sources`` is unchanged); every score is search
triage, never a ``claim_support`` grade; provider failures are named in ``source_errors`` /
``channels_lost``, never silently degraded around; nothing here writes the vault.
"""
from __future__ import annotations

import json
import math
import os
import re
import sys
import urllib.parse
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from research_agent_teams.tools import paper_search
from research_agent_teams.tools.paper_search import (
    DEFAULT_SOURCES,
    _GENERIC_SEARCH_TERMS,
    _best_ref,
    _dedup_key,
    _is_component_record,
    _reject_vault_path,
    _salient_terms,
    query_title_relevance,
)
from research_agent_teams.tools.rank_sources import _recency_score
from research_agent_teams.tools.recall import _STOPWORDS, RRF_K, fuse_rrf
from research_agent_teams.tools.scholar_clients import (
    OPENALEX_API,
    ScholarLookupError,
    Transport,
    _fetch_parse,
    _reject_openalex_query_key,
    normalize_doi,
    sanitize_scholar_error,
)
from research_agent_teams.tools.search_campaign import _oa_abstract

FUNNEL_VERSION = "search-funnel/v1"
RECURSION_VERSION = "search-funnel-recursion/v1"

#: AgentSearch blends authority at ``pagerank_importance = 0.1``; the same default keeps relevance
#: dominant and authority a tie-breaker, never a prestige filter.
DEFAULT_ALPHA = 0.1
#: citations at which the log-scaled citation term saturates to 1.0
_CITATION_SATURATION = 1000
#: authority = 0.7 * citations + 0.3 * recency (recency from rank_sources' 20-year linear decay)
_AUTHORITY_CITATION_WEIGHT = 0.7
_AUTHORITY_RECENCY_WEIGHT = 0.3
#: relevance after stage 3 = mean of the normalised RRF score and the best-passage score
_PASSAGE_WEIGHT = 0.5
#: two trailing rounds that add nothing end a recursive expansion (mirrors
#: evidence_search_trace.TRAILING_LOW_GAIN_ROUNDS, but over raw new-record counts)
TRAILING_EMPTY_ROUNDS = 2
_SNIPPET_CHARS = 400
_OPENALEX_FILTER_BATCH = 50

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?;。！？；])\s+|\n+")
_WORD_RE = re.compile(r"[a-z0-9]+")
_CJK_RE = re.compile(r"[㐀-鿿]")

TextProvider = Callable[[dict], Optional[str]]


# --------------------------------------------------------------------------- stage 2: fusion

def channel_ranks(channel_rankings: Dict[str, Sequence[str]],
                  keep: Optional[set] = None) -> Dict[str, Dict[str, int]]:
    """Per-channel ``{dedup_key: rank}`` (1-based, in each provider's own order) for ``fuse_rrf``.

    ``keep`` restricts the ranking to keys that survived the relevance gate, so a filtered-out
    record cannot push a kept one down a channel's list.
    """
    out: Dict[str, Dict[str, int]] = {}
    for source, keys in (channel_rankings or {}).items():
        ranks: Dict[str, int] = {}
        for key in keys or []:
            if keep is not None and key not in keep:
                continue
            if key not in ranks:
                ranks[key] = len(ranks) + 1
        if ranks:
            out[str(source)] = ranks
    return out


# --------------------------------------------------------------------------- stage 3: best passage

def _passages(text: str) -> List[str]:
    parts = [p.strip() for p in _SENTENCE_SPLIT.split(text or "") if p and p.strip()]
    return parts or ([text.strip()] if (text or "").strip() else [])


def best_passage(query: str, text: Optional[str]) -> dict:
    """The passage of ``text`` that best matches ``query``: ``{text, score, index}``.

    Score is the share of the query's salient anchors (Latin tokens or CJK bigrams, generic
    research words removed) present in the passage, capped so a 6-anchor query needs 6 matches for
    1.0. Deterministic and lexical: the AgentSearch stage is cosine similarity over chunk
    embeddings; without an embedding model this is the honest stdlib equivalent. Ties keep the
    earlier passage. Empty text -> ``{"text": "", "score": 0.0, "index": -1}``.
    """
    query_terms = _salient_terms(query)
    if not query_terms or not (text or "").strip():
        return {"text": "", "score": 0.0, "index": -1}
    denominator = max(1, min(6, len(query_terms)))
    best_score, best_index, best_text = 0.0, -1, ""
    for index, passage in enumerate(_passages(text or "")):
        shared = query_terms & _salient_terms(passage)
        score = round(min(1.0, len(shared) / denominator), 4)
        if score > best_score:
            best_score, best_index, best_text = score, index, passage
    if best_index < 0:
        first = _passages(text or "")[0]
        return {"text": first[:_SNIPPET_CHARS], "score": 0.0, "index": 0}
    return {"text": best_text[:_SNIPPET_CHARS], "score": best_score, "index": best_index}


def fetch_abstracts_openalex(records: List[dict], transport: Optional[Transport] = None,
                             batch_size: int = _OPENALEX_FILTER_BATCH) -> Tuple[Dict[str, str], List[str]]:
    """Abstracts for the records' DOIs via ONE batched OpenAlex filter request per ``batch_size``
    DOIs (``filter=doi:a|b|...`` + ``select=abstract_inverted_index``).

    Returns ``({normalized_doi: abstract_text}, [sanitized error, ...])``. A failed batch is named
    and skipped — the funnel then ranks those records on fused relevance alone. Same OpenAlex
    query-key stance as every other client: a configured query-string key blocks the call.
    """
    _reject_openalex_query_key()
    dois: List[str] = []
    for record in records or []:
        ndoi = normalize_doi(str(record.get("doi") or ""))
        if ndoi and ndoi not in dois:
            dois.append(ndoi)
    found: Dict[str, str] = {}
    errors: List[str] = []
    for start in range(0, len(dois), max(1, int(batch_size))):
        chunk = dois[start:start + max(1, int(batch_size))]
        params = {"filter": "doi:" + "|".join(chunk),
                  "select": "id,doi,abstract_inverted_index",
                  "per-page": len(chunk)}
        url = f"{OPENALEX_API}?{urllib.parse.urlencode(params, encoding='utf-8', errors='strict')}"
        try:
            data = _fetch_parse(url, lambda body: json.loads(body.decode("utf-8")), transport)
        except ScholarLookupError as e:
            errors.append(sanitize_scholar_error(e))
            continue
        for work in (data.get("results") or []) if isinstance(data, dict) else []:
            ndoi = normalize_doi(str(work.get("doi") or ""))
            text = _oa_abstract(work.get("abstract_inverted_index"))
            if ndoi and text:
                found[ndoi] = text
    return found, errors


# --------------------------------------------------------------------------- stage 4: authority

def authority_score(record: dict, audit_year: int = 2026) -> float:
    """[0, 1] authority proxy: 0.7 * log-scaled citations (saturating at 1000) + 0.3 * recency.

    The machine's stand-in for AgentSearch's Open PageRank domain score: a scholarly record has no
    domain rank, but it has a citation count and a year. Triage only — ``claim_support`` grading
    and the venue personas' anti-prestige rules are untouched.
    """
    cited = record.get("cited_by_count")
    try:
        cited_f = max(0.0, float(cited)) if cited is not None else 0.0
    except (TypeError, ValueError):
        cited_f = 0.0
    citation_term = min(1.0, math.log1p(cited_f) / math.log1p(_CITATION_SATURATION))
    year = record.get("year")
    recency = _recency_score(int(year) if isinstance(year, int) else None, audit_year)
    return round(_AUTHORITY_CITATION_WEIGHT * citation_term + _AUTHORITY_RECENCY_WEIGHT * recency, 6)


# --------------------------------------------------------------------------- related queries

def _query_anchor_order(query: str) -> List[str]:
    """The query's salient anchors in order of first appearance (Latin tokens, then CJK bigrams);
    function words ("with", "for") are never anchors even though the title gate tolerates them."""
    salient = _salient_terms(query)
    ordered: List[str] = []
    for token in _WORD_RE.findall((query or "").lower()):
        if token in salient and token not in _STOPWORDS and token not in ordered:
            ordered.append(token)
    cjk = _CJK_RE.findall(query or "")
    for i in range(max(0, len(cjk) - 1)):
        bigram = "".join(cjk[i:i + 2])
        if bigram in salient and bigram not in ordered:
            ordered.append(bigram)
    return ordered


def _lead_tokens(title: str) -> List[str]:
    return [t for t in _WORD_RE.findall((title or "").lower())
            if len(t) >= 3 and t not in _GENERIC_SEARCH_TERMS and t not in _STOPWORDS
            and not t.isdigit()]


def _candidate_leads(title: str, query_terms: set) -> List[str]:
    """New leads a title offers: adjacent salient pairs first ("whole body", "promptable models"),
    then single terms; anything already fully inside the query is not a lead."""
    tokens = _lead_tokens(title)
    leads: List[str] = []
    for left, right in zip(tokens, tokens[1:]):
        if left in query_terms and right in query_terms:
            continue
        phrase = f"{left} {right}"
        if phrase not in leads:
            leads.append(phrase)
    for token in tokens:
        if token not in query_terms and token not in leads:
            leads.append(token)
    cjk = _CJK_RE.findall(title or "")
    for i in range(max(0, len(cjk) - 1)):
        bigram = "".join(cjk[i:i + 2])
        if bigram in _salient_terms(title) and bigram not in query_terms and bigram not in leads:
            leads.append(bigram)
    return leads


def propose_related_queries(query: str, records: List[dict], k: int = 5,
                            max_anchors: int = 4) -> List[dict]:
    """Machine-proposed follow-up queries (AgentSearch's ``related_queries``, without an LLM).

    Each proposal = the query's first ``max_anchors`` anchors + ONE new lead that co-occurs in the
    retrieved titles but not in the query. A lead is an adjacent salient word pair when the
    titles offer one ("whole body", "promptable models"), else a single term; leads are ordered by
    how many retrieved titles carry them (pairs before singles at equal support, then
    alphabetical). ``support`` is that title count, so a worker can see why a proposal exists.
    Proposals are leads for the next round; nothing here judges relevance.
    """
    anchors = _query_anchor_order(query)[:max(1, int(max_anchors))]
    if not anchors or int(k) <= 0:
        return []
    query_terms = _salient_terms(query)
    document_frequency: Dict[str, int] = {}
    for record in records or []:
        for lead in _candidate_leads(str(record.get("title") or ""), query_terms):
            document_frequency[lead] = document_frequency.get(lead, 0) + 1
    ranked = sorted(document_frequency.items(),
                    key=lambda item: (-item[1], -len(item[0].split()), item[0]))
    proposals: List[dict] = []
    covered = set(query_terms)          # a lead whose words are all already covered adds nothing
    for term, support in ranked:
        if len(proposals) >= int(k):
            break
        words = set(term.split()) if " " in term else {term}
        if words <= covered:
            continue                    # "body" after "whole body", "body pet" after both
        covered |= words
        all_cjk = bool(_CJK_RE.search(term)) and all(_CJK_RE.search(anchor) for anchor in anchors)
        joined = "".join(anchors + [term]) if all_cjk else " ".join(anchors + [term])
        proposals.append({"query": joined, "new_term": term, "support": support,
                          "basis": "title-term co-occurrence in the retrieved records"})
    return proposals


# --------------------------------------------------------------------------- the funnel

def funnel(query: str, *, sources=DEFAULT_SOURCES, limit_broad: int = 20, limit_fused: int = 40,
           limit_passage: int = 20, limit_final: int = 10, alpha: float = DEFAULT_ALPHA,
           rrf_k: int = RRF_K, min_relevance: float = 0.5, transport: Optional[Transport] = None,
           text_provider: Optional[TextProvider] = None, fetch_abstracts: bool = True,
           audit_year: int = 2026, related_k: int = 5) -> dict:
    """Run the four stages for one query; return ranked records + per-stage accounting.

    ``limit_broad`` is per source (AgentSearch: 1000 -> 100 -> 25 -> 10; the free metadata APIs
    are paced, so the defaults are 20 per source -> 40 -> 20 -> 10). ``text_provider`` supplies a
    record's passage text (e.g. a local full-text snapshot); when it returns nothing and
    ``fetch_abstracts`` is on, abstracts come from one batched OpenAlex request.
    """
    if not (query or "").strip():
        raise ValueError("funnel requires a non-empty query")
    if not 0.0 <= float(alpha) <= 1.0:
        raise ValueError("alpha must be in [0, 1]")
    if not 0.0 <= float(min_relevance) <= 1.0:
        raise ValueError("min_relevance must be in [0, 1]")
    for name, value in (("limit_broad", limit_broad), ("limit_fused", limit_fused),
                        ("limit_passage", limit_passage), ("limit_final", limit_final)):
        if int(value) < 1:
            raise ValueError(f"{name} must be >= 1")

    # ---- stage 1: broad recall (the sanctioned facade; provider failures stay named)
    broad = paper_search.search(query, sources=sources, limit_per_source=int(limit_broad),
                                transport=transport)
    rankings: Dict[str, List[str]] = dict(broad.get("channel_rankings") or {})
    source_errors: Dict[str, str] = dict(broad.get("source_errors") or {})
    source_yield = {src: len(rankings.get(src) or []) for src in sources}
    by_key: Dict[str, dict] = {_dedup_key(r): r for r in broad.get("records") or []}

    # ---- stage 2: relevance gate + cross-channel RRF
    gated: Dict[str, dict] = {}
    n_component = n_offtopic = 0
    for key, record in by_key.items():
        if _is_component_record(record):
            n_component += 1
            continue
        relevance = query_title_relevance(query, str(record.get("title") or ""))
        if relevance < float(min_relevance):
            n_offtopic += 1
            continue
        gated[key] = dict(record, title_relevance=relevance)
    gated_ranks = channel_ranks(rankings, keep=set(gated))
    fused = fuse_rrf(gated_ranks, k=int(rrf_k))
    max_rrf = fused[0][1] if fused else 0.0
    stage2: List[dict] = []
    for key, rrf_score in fused[:int(limit_fused)]:
        record = gated[key]
        record["rrf_score"] = round(rrf_score, 6)
        record["rrf_normalized"] = round(rrf_score / max_rrf, 6) if max_rrf else 0.0
        record["channel_ranks"] = {src: ranks[key] for src, ranks in gated_ranks.items()
                                   if key in ranks}
        stage2.append(record)

    # ---- stage 3: best passage per record
    texts: Dict[str, str] = {}
    for record in stage2:
        provided = text_provider(record) if text_provider else None
        if provided:
            texts[_dedup_key(record)] = str(provided)
    abstract_errors: List[str] = []
    missing = [r for r in stage2 if _dedup_key(r) not in texts and r.get("doi")]
    if fetch_abstracts and missing:
        try:
            abstracts, abstract_errors = fetch_abstracts_openalex(missing, transport=transport)
        except ScholarLookupError as e:                      # e.g. the query-key block
            abstracts, abstract_errors = {}, [sanitize_scholar_error(e)]
        for record in missing:
            ndoi = normalize_doi(str(record.get("doi") or ""))
            if ndoi in abstracts:
                texts[_dedup_key(record)] = abstracts[ndoi]
    if abstract_errors:
        source_errors["openalex_abstracts"] = "; ".join(abstract_errors)
    n_with_text = 0
    for record in stage2:
        text = texts.get(_dedup_key(record))
        if text:
            n_with_text += 1
            passage = best_passage(query, text)
            record["text"] = passage["text"]
            record["passage_score"] = passage["score"]
            record["relevance"] = round((1 - _PASSAGE_WEIGHT) * record["rrf_normalized"]
                                        + _PASSAGE_WEIGHT * passage["score"], 6)
        else:
            record["text"] = ""
            record["passage_score"] = None
            record["relevance"] = record["rrf_normalized"]
    stage3 = sorted(stage2, key=lambda r: (-r["relevance"], _dedup_key(r)))[:int(limit_passage)]

    # ---- stage 4: authority blend
    for record in stage3:
        record["authority"] = authority_score(record, audit_year)
        record["score"] = round((1 - float(alpha)) * record["relevance"]
                                + float(alpha) * record["authority"], 6)
        record["dataset"] = (record.get("found_in") or [record.get("source") or "?"])[0]
    final = sorted(stage3, key=lambda r: (-r["score"], _dedup_key(r)))[:int(limit_final)]

    return {
        "funnel_version": FUNNEL_VERSION,
        "query": query,
        "sources": list(sources),
        "alpha": float(alpha),
        "rrf_k": int(rrf_k),
        "records": final,
        "related_queries": propose_related_queries(query, final, k=int(related_k)),
        "stage_counts": {
            "broad_raw": sum(source_yield.values()),
            "broad_unique": len(by_key),
            "rejected_component": n_component,
            "rejected_offtopic": n_offtopic,
            "fused": len(stage2),
            "with_passage_text": n_with_text,
            "passage_ranked": len(stage3),
            "final": len(final),
        },
        "source_errors": source_errors,
        "source_yield": source_yield,
        "channels_lost": [src for src in sources if source_yield[src] == 0],
        "text_policy": "triage snippet <= 400 chars; never an evidence-row field",
    }


# --------------------------------------------------------------------------- recursion

def _norm_query(query: str) -> str:
    return " ".join(_WORD_RE.findall((query or "").lower())) + "".join(_CJK_RE.findall(query or ""))


def recursive_search(query: str, *, depth: int = 2, breadth: int = 2, **funnel_kwargs) -> dict:
    """Depth x breadth expansion: each round runs the funnel on its queries and proposes the next.

    Round 0 is the seed query. Each searched query contributes up to ``breadth`` not-yet-searched
    related queries to the next round. Stops at ``depth`` rounds, when no new related query is
    left, or when ``TRAILING_EMPTY_ROUNDS`` consecutive rounds added no new record. The stop is
    recorded as ``expansion_stop_reason`` — it is NOT a saturation verdict and never sets the
    evidence trace's ``stop_reason``.

    Drift guard: a follow-up query is judged by its own funnel, but a record it returns enters the
    merged list only if its title still passes the SEED query's relevance gate
    (``min_relevance``, default 0.5); the rest are counted per round as ``n_drift_rejected``. The
    merged list is ordered by relevance to the seed first, then by the record's best funnel score,
    because per-query scores are not comparable across queries.
    """
    if int(depth) < 1 or int(breadth) < 1:
        raise ValueError("depth and breadth must be >= 1")
    seed_gate = float(funnel_kwargs.get("min_relevance", 0.5))
    searched = {_norm_query(query)}
    frontier: List[str] = [query]
    query_tree: List[dict] = [{"query": query, "parent": None, "round": 0}]
    records: Dict[str, dict] = {}
    rounds: List[dict] = []
    source_errors: Dict[str, str] = {}
    last_proposals: List[dict] = []
    stop_reason = "depth_reached"
    for round_index in range(int(depth)):
        next_frontier: List[str] = []
        hits: List[str] = []
        last_proposals = []
        n_new = n_drift = 0
        for q in frontier:
            result = funnel(q, **funnel_kwargs)
            last_proposals.extend(result.get("related_queries") or [])
            for src, detail in (result.get("source_errors") or {}).items():
                source_errors[f"r{round_index}:{src}:{q}"] = detail
            for record in result.get("records") or []:
                key = _dedup_key(record)
                seed_relevance = query_title_relevance(query, str(record.get("title") or ""))
                if round_index > 0 and seed_relevance < seed_gate:
                    n_drift += 1                # found by the follow-up, off the seed question
                    continue
                hits.append(_best_ref(record) or key)
                if key in records:
                    existing = records[key]
                    if q not in existing["matched_queries"]:
                        existing["matched_queries"].append(q)
                    existing["score"] = max(existing["score"], record["score"])
                    continue
                records[key] = dict(record, matched_queries=[q], first_round=round_index,
                                    seed_title_relevance=seed_relevance)
                n_new += 1
            for proposal in result.get("related_queries") or []:
                candidate = str(proposal.get("query") or "").strip()
                if not candidate or _norm_query(candidate) in searched:
                    continue
                if sum(1 for row in query_tree if row["parent"] == q) >= int(breadth):
                    break
                searched.add(_norm_query(candidate))
                next_frontier.append(candidate)
                query_tree.append({"query": candidate, "parent": q, "round": round_index + 1})
        rounds.append({"round_index": round_index, "queries": list(frontier),
                       "n_source_hits": len(hits), "n_new_records": n_new,
                       "n_drift_rejected": n_drift,
                       "source_hits": list(dict.fromkeys(hits)),
                       "proposed_next": list(next_frontier)})
        trailing = [r["n_new_records"] for r in rounds[-TRAILING_EMPTY_ROUNDS:]]
        if len(trailing) == TRAILING_EMPTY_ROUNDS and not any(trailing):
            stop_reason = "trailing_rounds_added_nothing"
            break
        if not next_frontier:
            stop_reason = "no_new_related_queries"
            break
        frontier = next_frontier
    ordered = sorted(records.values(),
                     key=lambda r: (-r["seed_title_relevance"], -r["score"], _dedup_key(r)))
    # A query proposed for the round after the stop was registered (so it is never re-proposed)
    # but never run: the tree says which is which, and the count is of queries actually searched.
    executed = {_norm_query(q) for round_row in rounds for q in round_row["queries"]}
    for row in query_tree:
        row["searched"] = _norm_query(row["query"]) in executed
    # leads the LAST round proposed but this expansion never ran — the worker's next-step menu
    unsearched = [p for p in last_proposals if _norm_query(str(p.get("query") or "")) not in executed]
    return {
        "recursion_version": RECURSION_VERSION,
        "seed_query": query,
        "depth": int(depth),
        "breadth": int(breadth),
        "rounds": rounds,
        "query_tree": query_tree,
        "records": ordered,
        "related_queries": combine_related_queries([{"related_queries": unsearched}]),
        "n_queries_searched": sum(len(round_row["queries"]) for round_row in rounds),
        "n_records": len(ordered),
        "expansion_stop_reason": stop_reason,
        "not_a_saturation_verdict": True,
        "source_errors": source_errors,
    }


def trace_rounds(recursion: dict) -> List[dict]:
    """``evidence-search-trace/v1`` round rows (skeleton) from a recursive search.

    Only the retrieval facts are filled — ``questions`` and ``source_hits``. Claims addressed,
    contradiction queries, representativeness dimensions and findings stay EMPTY: those are the
    evidence-search-moderator's judgments, and ``evaluate_search_trace`` will (correctly) call a
    trace made only of these rows INCOMPLETE.
    """
    rows: List[dict] = []
    for index, round_row in enumerate(recursion.get("rounds") or []):
        rows.append({
            "round_index": index,
            "questions": [str(q) for q in round_row.get("queries") or []],
            "source_hits": [{"source_ref": str(ref)} for ref in round_row.get("source_hits") or []],
            "claim_ids_addressed": [],
            "contradiction_claim_ids_queried": [],
            "representativeness_dimensions_queried": [],
            "findings": [],
        })
    return rows


# --------------------------------------------------------------------------- operated pre-search merge

#: funnel-only fields: they stay in inbox/search-funnel.json and never enter the metadata bundle
_FUNNEL_ONLY_FIELDS = frozenset({
    "text", "passage_score", "rrf_score", "rrf_normalized", "channel_ranks", "relevance",
    "authority", "dataset", "score", "title_relevance", "seed_title_relevance", "first_round",
})


def combine_related_queries(results: Sequence[dict], k: int = 5) -> List[dict]:
    """Top-``k`` related-query proposals across several funnel results (same query string merges,
    keeping the highest ``support``; ordered by support, then query text)."""
    merged: Dict[str, dict] = {}
    for result in results or []:
        for proposal in (result or {}).get("related_queries") or []:
            text = str(proposal.get("query") or "").strip()
            if not text:
                continue
            if text not in merged or int(proposal.get("support") or 0) > int(merged[text].get("support") or 0):
                merged[text] = dict(proposal, query=text)
    ranked = sorted(merged.values(), key=lambda p: (-int(p.get("support") or 0), p["query"]))
    return ranked[:max(0, int(k))]


def combine_funnel_results(results: Sequence[dict]) -> List[dict]:
    """One ranked record list from several per-query funnel / recursion results.

    Query order first (the caller's plan order), score order inside a query; a record seen under
    several queries keeps its first position, its best ``score`` and the union of
    ``matched_queries``.
    """
    combined: Dict[str, dict] = {}
    for result in results or []:
        query = str(result.get("query") or result.get("seed_query") or "")
        for record in result.get("records") or []:
            key = _dedup_key(record)
            queries = list(record.get("matched_queries") or ([query] if query else []))
            if key in combined:
                existing = combined[key]
                existing["score"] = max(float(existing.get("score") or 0.0),
                                        float(record.get("score") or 0.0))
                for q in queries:
                    if q not in existing["matched_queries"]:
                        existing["matched_queries"].append(q)
                continue
            combined[key] = dict(record, matched_queries=queries)
    return list(combined.values())


def merge_funnel_into_search_result(result: dict, combined: Sequence[dict], *, summary: dict) -> dict:
    """Fold a combined funnel ranking into a ``search_many`` result IN PLACE, metadata only.

    - a record the facade already holds gets ``funnel_rank`` / ``funnel_score``;
    - a record only the funnel found is appended WITHOUT the funnel-only fields (no ``text``):
      the bundle stays metadata-by-reference, the snippet lives in ``inbox/search-funnel.json``;
    - ``records`` is re-ordered: funnel-ranked records first in funnel order, then the rest in
      their existing order — the reading order the lit-scout sees;
    - the ``funnel`` summary is attached; the facade's own ``source_errors`` and
      ``relevance_filter`` are not touched.
    """
    existing: Dict[str, dict] = {_dedup_key(r): r for r in result.get("records") or []}
    n_added = n_annotated = 0
    for rank, record in enumerate(combined or [], start=1):
        key = _dedup_key(record)
        if key in existing:
            existing[key]["funnel_rank"] = rank
            existing[key]["funnel_score"] = record.get("score")
            n_annotated += 1
            continue
        clean = {k: v for k, v in record.items() if k not in _FUNNEL_ONLY_FIELDS}
        clean["funnel_rank"] = rank
        clean["funnel_score"] = record.get("score")
        clean["found_via"] = "search-funnel"
        clean.setdefault("relevance_score",
                         record.get("seed_title_relevance", record.get("title_relevance", 0.0)))
        existing[key] = clean
        n_added += 1
    ranked = sorted((r for r in existing.values() if r.get("funnel_rank")),
                    key=lambda r: r["funnel_rank"])
    rest = [r for r in result.get("records") or [] if not r.get("funnel_rank")]
    result["records"] = ranked + rest
    result["funnel"] = dict(summary, n_funnel_records=len(combined or []),
                            n_added_records=n_added, n_annotated_records=n_annotated)
    return result


# --------------------------------------------------------------------------- run-local bundle

def _sanitized_errors(errors) -> Dict[str, str]:
    return {str(k): sanitize_scholar_error(v) for k, v in (errors or {}).items()}


def write_funnel_bundle(run_dir, result: dict, ts: str) -> str:
    """Write a funnel / recursion result (or the operated per-query collection) to
    ``<run>/inbox/search-funnel.json`` (never the vault).

    A separate file from ``inbox/search-results.json``: the passage snippets and per-stage
    accounting live here; the metadata bundle only carries ranks and scores.
    """
    path = Path(run_dir) / "inbox" / "search-funnel.json"
    _reject_vault_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(result, retrieved_at=ts)
    payload["source_errors"] = _sanitized_errors(result.get("source_errors"))
    if isinstance(payload.get("results"), list):
        payload["results"] = [dict(r, source_errors=_sanitized_errors(r.get("source_errors")))
                              if isinstance(r, dict) else r for r in payload["results"]]
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    return str(path)


# --------------------------------------------------------------------------- CLI (manual / agent channel)

def main(argv: Optional[List[str]] = None, transport: Optional[Transport] = None) -> int:
    """`python -m research_agent_teams.tools.search_funnel "<query>" [--sources a,b] [--limit-broad N]
    [--final N] [--alpha F] [--depth N] [--breadth N] [--no-abstracts] [--json out]`"""
    import argparse

    os.environ["PYTHONUTF8"] = "1"
    os.environ["PYTHONIOENCODING"] = "utf-8"
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8", errors="strict")

    ap = argparse.ArgumentParser(
        description="Four-stage scholarly retrieval funnel (AgentSearch pattern over arXiv/OpenAlex/"
                    "Crossref/S2; free-first, no Sci-Hub, triage only)")
    ap.add_argument("query")
    ap.add_argument("--sources", default=",".join(DEFAULT_SOURCES))
    ap.add_argument("--limit-broad", type=int, default=20, help="records per source at stage 1")
    ap.add_argument("--final", type=int, default=10, help="records kept after stage 4")
    ap.add_argument("--alpha", type=float, default=DEFAULT_ALPHA, help="authority weight in [0,1]")
    ap.add_argument("--depth", type=int, default=1, help=">1 runs the recursive expansion")
    ap.add_argument("--breadth", type=int, default=2, help="related queries followed per query")
    ap.add_argument("--no-abstracts", action="store_true", help="skip the batched OpenAlex abstract fetch")
    ap.add_argument("--json", dest="json_out", default=None, help="write the full result JSON here")
    args = ap.parse_args(argv)

    sources = tuple(s.strip() for s in args.sources.split(",") if s.strip())
    kwargs = dict(sources=sources, limit_broad=args.limit_broad, limit_final=args.final,
                  alpha=args.alpha, fetch_abstracts=not args.no_abstracts, transport=transport)
    if args.depth > 1:
        result = recursive_search(args.query, depth=args.depth, breadth=args.breadth, **kwargs)
        records = result["records"]
        print(f"recursive search: {result['n_queries_searched']} queries / {len(result['rounds'])} rounds "
              f"/ stop={result['expansion_stop_reason']} (expansion stop, not saturation)")
    else:
        result = funnel(args.query, **kwargs)
        records = result["records"]
        counts = result["stage_counts"]
        print(f"funnel: raw {counts['broad_raw']} -> unique {counts['broad_unique']} -> fused {counts['fused']}"
              f" -> passage-ranked {counts['passage_ranked']} -> final {counts['final']}")
    if args.json_out:
        _reject_vault_path(args.json_out)
        Path(args.json_out).write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    for r in records[:20]:
        snippet = (r.get("text") or "").replace("\n", " ")[:110]
        print(f"[{'+'.join(r.get('found_in') or [])}] {r.get('year') or '----'}  score={r.get('score'):.3f}  "
              f"{str(r.get('title') or '')[:80]}  ({_best_ref(r)})")
        if snippet:
            print(f"      » {snippet}")
    for proposal in (result.get("related_queries") or [])[:5]:
        print(f"related: {proposal['query']}  (support={proposal['support']})")
    for src, err in (result.get("source_errors") or {}).items():
        print(f"!! {src}: {err}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
