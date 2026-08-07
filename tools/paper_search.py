"""Multi-source scholarly search facade (the sanctioned live DISCOVER channel, absorption wave 1).

One entry point over the deterministic clients in ``scholar_clients`` that:
  - fans a query across the free-first sources (arXiv / OpenAlex / Crossref / Semantic Scholar),
  - merges + dedupes records by DOI -> arXiv id -> normalized title (provenance kept),
  - converts records into evidence_table source rows (by-reference: DOI / arXiv id / URL only,
    never inlined content) ready for ``evidence_scout.build_evidence_table``,
  - derives the ``no_semantic_neighbor_found`` novelty signal (paper-search-mcp absorption:
    a gap/idea whose query surfaces NO semantically-near title is a positive novelty signal),
  - writes an operate-layer search bundle into a run's ``inbox/`` (the deterministic pre-step
    recipes drop before dispatching the lit-scout worker).

Govern-by-construction: this module produces EVIDENCE rows only — it never grades
``claim_support`` above the conservative default and never decides PASS/BLOCK (the
evidence-verifier hard gate owns that). A source failure degrades that source to zero rows and
is reported in ``source_errors`` — partial availability must never fabricate results.
"""
from __future__ import annotations

import json
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from difflib import SequenceMatcher
from pathlib import Path
from typing import Dict, List, Optional, Sequence

from research_agent_teams.tools.scholar_clients import (
    ScholarLookupError,
    Transport,
    sanitize_scholar_error,
    search_arxiv,
    search_crossref,
    search_openalex,
    search_s2,
)

DEFAULT_SOURCES = ("arxiv", "openalex", "crossref", "s2")


def _reject_vault_path(path) -> None:
    """Two-repo seam guard: this tool must NEVER write into the knowledge vault. Reject any output
    path that resolves inside a PhD-Research-OS vault — the machine writes the vault ONLY through
    /promote-to-vault. Applies to the operate bundle AND the CLI --json (an agent/manual channel)."""
    resolved = str(Path(path).resolve()).replace("\\", "/").lower()
    if "phd-research-os" in resolved:
        raise ValueError(f"refusing to write inside the knowledge vault (promote-gate-only): {path}")

_SEARCHERS = {
    "arxiv": search_arxiv,
    "openalex": search_openalex,
    "crossref": search_crossref,
    "s2": search_s2,
}


def _sanitize_source_errors(source_errors) -> Dict[str, str]:
    """Return a fresh, persistence-safe provider-error mapping."""
    return {
        str(source): sanitize_scholar_error(detail)
        for source, detail in dict(source_errors or {}).items()
    }

_WORD_RE = re.compile(r"[a-z0-9]+")
_CJK_RE = re.compile(r"[\u3400-\u9fff]")
_GENERIC_SEARCH_TERMS = {
    "about", "architecture", "based", "baseline", "budget", "build", "building",
    "current", "design", "evidence", "experiment", "fairness", "framework", "initial",
    "known", "matched", "method", "model", "paper", "research", "result", "results",
    "same", "source", "study", "system", "task", "using",
}
_GENERIC_CJK_BIGRAMS = {
    "当前", "方法", "模型", "研究", "实验", "结果", "系统", "任务", "设计",
    "问题", "构建", "验证", "融合", "相关", "论文", "证据", "来源", "已有",
}


def _norm_title(title: str) -> str:
    return " ".join(_WORD_RE.findall((title or "").lower()))


def script_of(text: str) -> str:
    """Classify text's script: 'latin', 'cjk', or 'mixed' (Unicode ranges, no dependencies).

    C1 (2026-08-07): the sanctioned scholarly-search facade fans queries at English-biased
    metadata APIs; a raw non-Latin request sent to them directly is retrieval poison (wrong
    or empty results reported as if they were real coverage). This is the shared script
    classifier both pre_search's Latin-only direct-query guard and search_many's
    cross_script_rejections counter key off of. Empty or script-free text (pure digits/
    punctuation) classifies as 'latin' — a conservative default that never trips the guard
    on ambiguous input.
    """
    has_latin = bool(re.search(r"[a-zA-Z]", text or ""))
    has_cjk = bool(_CJK_RE.search(text or ""))
    if has_latin and has_cjk:
        return "mixed"
    if has_cjk:
        return "cjk"
    return "latin"


def _salient_terms(text: str) -> set[str]:
    """Multilingual lexical anchors for a conservative query/title relevance gate.

    Latin terms are tokenised normally. CJK text has no whitespace guarantee, so adjacent
    character bigrams are used after removing generic research/management phrases. The gate is
    intentionally lexical: it removes obvious off-topic API noise; scientific relevance is still
    judged by the lit-scout over the primary source.
    """
    value = text or ""
    latin = {
        token for token in _WORD_RE.findall(value.lower())
        if len(token) >= 3 and token not in _GENERIC_SEARCH_TERMS
    }
    cjk = _CJK_RE.findall(value)
    bigrams = {
        "".join(cjk[i:i + 2]) for i in range(max(0, len(cjk) - 1))
        if "".join(cjk[i:i + 2]) not in _GENERIC_CJK_BIGRAMS
    }
    return latin | bigrams


def query_title_relevance(query: str, title: str) -> float:
    """Return a deterministic lexical relevance score in ``[0, 1]``.

    This is a retrieval hygiene check, not a semantic or evidence-strength judgment. A zero score
    means the title shares no non-generic multilingual anchor with the query and is unsafe to place
    in a scientific evidence bundle without a worker explicitly retrieving it through another
    channel.
    """
    query_terms = _salient_terms(query)
    title_terms = _salient_terms(title)
    if not query_terms or not title_terms:
        return 0.0
    shared = query_terms & title_terms
    if not shared:
        return 0.0
    return round(min(1.0, len(shared) / max(1, min(4, len(query_terms)))), 4)


def _is_component_record(record: dict) -> bool:
    """Reject figures, tables, media supplements, and other non-paper DOI components.

    Crossref occasionally returns a component DOI whose title inherits enough words from the
    parent paper to pass a lexical gate. Those objects are useful only after the parent paper has
    been admitted; they must not occupy an evidence-table source slot on their own.
    """
    title = str(record.get("title") or "").strip().lower()
    doi = str(record.get("doi") or "").strip().lower()
    if title.startswith(("figure ", "table ", "supplementary figure ",
                         "supplementary table ", "supplementary material ")):
        return True
    if re.search(r"(?:^|[_\s-])supp(?:lement(?:ary)?)?\d*(?:\.|$|[_\s-])", title):
        return True
    if re.search(r"/(?:mm|suppl?|fig|table)\d+$", doi):
        return True
    return False


def _dedup_key(rec: dict) -> str:
    if rec.get("doi"):
        return f"doi:{rec['doi']}"
    if rec.get("arxiv_id"):
        return f"arxiv:{rec['arxiv_id']}"
    return f"title:{_norm_title(rec.get('title', ''))}"


def search(query: str, sources=DEFAULT_SOURCES, limit_per_source: int = 10,
           transport: Optional[Transport] = None) -> dict:
    """Fan ``query`` across ``sources``; return {records, source_errors}.

    records: deduped normalized records, each annotated with ``found_in`` (list of source
    names that returned it) — deterministic order: by (-cited_by_count, title).
    source_errors: {source: error string} for sources that failed (never fabricated rows).
    """
    if not (query or "").strip():
        raise ValueError("search requires a non-empty query")
    unknown = [s for s in sources if s not in _SEARCHERS]
    if unknown:
        raise ValueError(f"unknown sources {unknown} (known: {sorted(_SEARCHERS)})")

    merged: Dict[str, dict] = {}
    errors: Dict[str, str] = {}

    def run_source(src: str):
        try:
            return src, _SEARCHERS[src](query, limit=limit_per_source, transport=transport), None
        except ScholarLookupError as e:
            return src, [], sanitize_scholar_error(e)

    # Providers are independent public metadata channels. Query them concurrently so one 20-second
    # outage does not multiply across arXiv/OpenAlex/Crossref/S2. Results are merged below in the
    # caller-declared source order, keeping the output deterministic despite concurrent I/O.
    with ThreadPoolExecutor(max_workers=min(4, len(sources))) as pool:
        outcomes = {src: (recs, error) for src, recs, error in pool.map(run_source, sources)}

    for src in sources:
        recs, error = outcomes[src]
        if error is not None:
            errors[src] = sanitize_scholar_error(error)
            continue
        for r in recs:
            key = _dedup_key(r)
            if key in merged:
                if src not in merged[key]["found_in"]:
                    merged[key]["found_in"].append(src)
                # prefer richer metadata: fill missing doi/arxiv/year from later sources
                for f in ("doi", "arxiv_id", "year", "cited_by_count"):
                    if merged[key].get(f) is None and r.get(f) is not None:
                        merged[key][f] = r[f]
            else:
                merged[key] = dict(r, found_in=[src])

    records = sorted(merged.values(),
                     key=lambda r: (-(r.get("cited_by_count") or 0), _norm_title(r.get("title", ""))))
    return {"query": query, "records": records, "source_errors": errors}


def search_many(queries: Sequence[str], sources=DEFAULT_SOURCES, limit_per_source: int = 10,
                transport: Optional[Transport] = None, min_relevance: float = 0.5) -> dict:
    """Run a decomposed query plan and keep only title-relevant metadata candidates.

    Each provider is still queried independently by :func:`search`. Results are merged across
    subqueries, while ``matched_queries`` and the maximum lexical ``relevance_score`` preserve why
    a record entered the bundle. Provider failures remain visible with a query-qualified key.
    Local full text and agent Web Search are separate retrieval channels; their sources join later
    through the lit-scout and the common citation/existence gates.
    """
    clean_queries: List[str] = []
    for raw in queries or []:
        query = str(raw or "").strip()
        if query and query not in clean_queries:
            clean_queries.append(query)
    if not clean_queries:
        raise ValueError("search_many requires at least one non-empty query")
    if not 0.0 <= min_relevance <= 1.0:
        raise ValueError("min_relevance must be in [0, 1]")

    merged: Dict[str, dict] = {}
    errors: Dict[str, str] = {}
    n_candidates = 0
    n_rejected = 0
    n_merged_duplicates = 0
    n_cross_script_rejected = 0
    for query_index, query in enumerate(clean_queries, start=1):
        result = search(query, sources=sources, limit_per_source=limit_per_source,
                        transport=transport)
        query_script = script_of(query)
        for source, detail in result.get("source_errors", {}).items():
            errors[f"q{query_index}:{source}"] = sanitize_scholar_error(detail)
        for record in result.get("records", []):
            n_candidates += 1
            title = str(record.get("title") or "").strip()
            # Metadata APIs can return component DOIs for figures/tables/media supplements. Those
            # are not standalone scholarly works and must never become evidence-table candidates.
            if _is_component_record(record):
                n_rejected += 1
                continue
            score = query_title_relevance(query, title)
            if score < min_relevance:
                n_rejected += 1
                # C1 (2026-08-07): a rejection where the query and this title are in different
                # scripts is named separately — it may be a genuine mismatch, or it may be a
                # translation/retrieval gap worth flagging rather than reading as "no related work".
                if title and script_of(title) != query_script:
                    n_cross_script_rejected += 1
                continue
            key = _dedup_key(record)
            if key not in merged:
                merged[key] = dict(record, matched_queries=[query], relevance_score=score)
                continue
            n_merged_duplicates += 1
            existing = merged[key]
            for source in record.get("found_in") or []:
                if source not in existing["found_in"]:
                    existing["found_in"].append(source)
            if query not in existing["matched_queries"]:
                existing["matched_queries"].append(query)
            existing["relevance_score"] = max(existing["relevance_score"], score)
            for field in ("doi", "arxiv_id", "year", "cited_by_count"):
                if existing.get(field) is None and record.get(field) is not None:
                    existing[field] = record[field]

    records = sorted(
        merged.values(),
        key=lambda record: (
            -float(record.get("relevance_score") or 0.0),
            -(record.get("cited_by_count") or 0),
            _norm_title(record.get("title", "")),
        ),
    )
    return {
        "query": " || ".join(clean_queries),
        "queries": clean_queries,
        "records": records,
        "source_errors": errors,
        "relevance_filter": {
            "kind": "multilingual_query_title_lexical/v1",
            "min_score": min_relevance,
            "n_candidates": n_candidates,
            "n_accepted": len(records),
            "n_rejected": n_rejected,
            "n_merged_duplicates": n_merged_duplicates,
            "cross_script_rejections": n_cross_script_rejected,
        },
        "retrieval_channels": {
            "metadata_apis": list(sources),
            "local_fulltext": "fulltext-pre",
            "agent_web_search": "worker fallback over primary sources only",
        },
    }


# --------------------------------------------------------------------------- evidence rows

def _best_ref(rec: dict) -> str:
    if rec.get("doi"):
        return f"doi:{rec['doi']}"
    if rec.get("arxiv_id"):
        return f"arXiv:{rec['arxiv_id']}"
    return rec.get("url") or rec.get("id") or ""


def to_evidence_sources(records: List[dict], start_index: int = 1) -> List[dict]:
    """Records -> evidence_table source rows (schema: id/kind/ref/title/year/claim_support/notes).

    claim_support is ALWAYS the conservative default "none": grading support for a specific
    claim is the lit-scout worker's judgment over the actual content, never this facade's.
    Provenance (which APIs returned the record) goes into ``notes`` — the row schema is closed
    (additionalProperties:false), so no extra keys.
    """
    rows: List[dict] = []
    for i, rec in enumerate(records, start=start_index):
        ref = _best_ref(rec)
        if not ref:
            continue
        notes = f"live-retrieval via {'+'.join(rec.get('found_in') or [rec.get('source', '?')])}"
        if rec.get("matched_queries"):
            notes += "; matched query plan: " + " | ".join(rec["matched_queries"])
        row = {"id": f"s{i}", "kind": "paper", "ref": ref, "claim_support": "none",
               "notes": notes}
        if rec.get("title"):
            row["title"] = rec["title"]
        if rec.get("year") is not None:
            row["year"] = rec["year"]
        rows.append(row)
    return rows


# --------------------------------------------------------------------------- novelty signal

def neighbor_overlap(query: str, title: str) -> float:
    """Deterministic semantic-neighbor proxy: max(token-Jaccard, SequenceMatcher ratio) in [0,1]."""
    qt, tt = set(_WORD_RE.findall(query.lower())), set(_WORD_RE.findall((title or "").lower()))
    jacc = len(qt & tt) / len(qt | tt) if (qt or tt) else 0.0
    seq = SequenceMatcher(None, _norm_title(query), _norm_title(title)).ratio()
    return max(jacc, seq)


def no_semantic_neighbor_found(query: str, records: List[dict], threshold: float = 0.45) -> dict:
    """The novelty grounding signal: True when no retrieved title is near the query.

    SCORE-ONLY input for ``novelty_aggregate`` (an extra ``derived_from`` signal) — it never
    cuts or filters anything. ``basis`` records the best-overlap title so the signal is auditable.
    """
    best, best_title = 0.0, ""
    for r in records:
        ov = neighbor_overlap(query, r.get("title", ""))
        if ov > best:
            best, best_title = ov, r.get("title", "")
    return {"no_semantic_neighbor_found": best < threshold,
            "n_results": len(records), "best_overlap": round(best, 4),
            "best_title": best_title, "threshold": threshold}


# --------------------------------------------------------------------------- operate pre-step bundle

def write_search_bundle(run_dir, query: str, result: dict, ts: str) -> str:
    """Write the live-retrieval result into ``<run>/inbox/search-results.json`` (the deterministic
    pre-step the operate recipes run BEFORE dispatching the lit-scout worker). Returns the path."""
    p = Path(run_dir) / "inbox" / "search-results.json"
    _reject_vault_path(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = {"query": result.get("query") or query,
               "queries": result.get("queries") or [result.get("query") or query],
               "task_request": result.get("task_request") or query,
               "retrieved_at": ts,
               "records": result.get("records", []),
               "source_errors": _sanitize_source_errors(result.get("source_errors", {})),
               "evidence_rows": to_evidence_sources(result.get("records", [])),
               "relevance_filter": result.get("relevance_filter") or {},
               "retrieval_channels": result.get("retrieval_channels") or {
                   "metadata_apis": list(DEFAULT_SOURCES),
                   "local_fulltext": "fulltext-pre",
                   "agent_web_search": "worker fallback over primary sources only",
               }}
    # C1 passthrough (2026-08-07): this writer otherwise projects a fixed key set, which would
    # silently drop _shared.pre_search's Latin-only direct-query guard block. Callers that don't
    # set it are unaffected — the key is only added when present.
    if "query_language_block" in result:
        payload["query_language_block"] = result["query_language_block"]
    p.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    return str(p)


# --------------------------------------------------------------------------- CLI (manual / agent channel)

def main(argv: Optional[List[str]] = None) -> int:
    """`python -m research_agent_teams.tools.paper_search "<query>" [--sources a,b] [--limit N] [--json out]`"""
    import argparse

    os.environ["PYTHONUTF8"] = "1"
    os.environ["PYTHONIOENCODING"] = "utf-8"
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8", errors="strict")

    ap = argparse.ArgumentParser(description="Sanctioned scholarly search channel (free-first, no Sci-Hub)")
    ap.add_argument("query")
    ap.add_argument("--sources", default=",".join(DEFAULT_SOURCES))
    ap.add_argument("--limit", type=int, default=8)
    ap.add_argument("--json", dest="json_out", default=None, help="write full result JSON here")
    args = ap.parse_args(argv)
    res = search(args.query, sources=tuple(s.strip() for s in args.sources.split(",") if s.strip()),
                 limit_per_source=args.limit)
    if args.json_out:
        _reject_vault_path(args.json_out)               # seam guard: never let --json write the vault
        Path(args.json_out).write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    for r in res["records"][:20]:
        print(f"[{'+'.join(r['found_in'])}] {r.get('year') or '----'}  {r['title'][:90]}  ({_best_ref(r)})")
    for src, err in res["source_errors"].items():
        print(f"!! {src}: {err}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
