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
import re
from difflib import SequenceMatcher
from pathlib import Path
from typing import Dict, List, Optional

from research_agent_teams.tools.scholar_clients import (
    ScholarLookupError,
    Transport,
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

_WORD_RE = re.compile(r"[a-z0-9]+")


def _norm_title(title: str) -> str:
    return " ".join(_WORD_RE.findall((title or "").lower()))


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
    for src in sources:
        try:
            recs = _SEARCHERS[src](query, limit=limit_per_source, transport=transport)
        except ScholarLookupError as e:
            errors[src] = str(e)
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
        row = {"id": f"s{i}", "kind": "paper", "ref": ref, "claim_support": "none",
               "notes": f"live-retrieval via {'+'.join(rec.get('found_in') or [rec.get('source', '?')])}"}
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
    payload = {"query": query, "retrieved_at": ts,
               "records": result.get("records", []), "source_errors": result.get("source_errors", {}),
               "evidence_rows": to_evidence_sources(result.get("records", []))}
    p.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    return str(p)


# --------------------------------------------------------------------------- CLI (manual / agent channel)

def main(argv: Optional[List[str]] = None) -> int:
    """`python -m research_agent_teams.tools.paper_search "<query>" [--sources a,b] [--limit N] [--json out]`"""
    import argparse

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
