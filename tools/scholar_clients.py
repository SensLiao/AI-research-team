"""Deterministic scholarly-API clients (DISCOVER live-retrieval layer, absorption wave 1).

Free-first connectors for arXiv / OpenAlex / Crossref / Semantic Scholar Graph, normalized to ONE
record shape so downstream tools (paper_search facade, citation_existence checker) are
source-agnostic. Pattern absorbed from paper-search-mcp (multi-source, free-first) and the ARS
deterministic client suite; re-implemented natively against the public API docs so the machine
keeps its zero-hard-dependency rule (stdlib only: urllib + xml.etree + json).

Design invariants:
  - NO Sci-Hub or any paywall-bypass source — resolvable public metadata APIs only.
  - All HTTP goes through an injectable ``transport`` callable -> tests run fully offline with
    canned bytes; the default transport is urllib with a timeout and a polite UA.
  - 404 on a lookup means "this id does not resolve" -> the lookup returns None.
    Network/HTTP failures raise ScholarLookupError -> callers must treat that as "could not
    check", NEVER as "does not exist" (the citation_existence checker depends on this split).
  - Pure parsing helpers (_parse_*) are separated from I/O for direct unit-testing.
  - No keys required. Optional env: RAT_S2_API_KEY (Semantic Scholar quota),
    RAT_CONTACT_MAIL (polite-pool identification for OpenAlex/Crossref).
  - This module never writes files and never touches the vault.

Normalized record:
  {"source": "arxiv|openalex|crossref|s2", "id": str, "title": str, "year": int|None,
   "venue": str, "authors": [str, ...], "doi": str|None, "arxiv_id": str|None,
   "url": str, "cited_by_count": int|None}
"""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from typing import Callable, Dict, List, Optional

Transport = Callable[[str, Dict[str, str]], bytes]

_TIMEOUT_S = 20
_UA_BASE = "research-agent-teams/1.0 (research use; +local)"
_ATOM_NS = {"atom": "http://www.w3.org/2005/Atom"}

ARXIV_API = "https://export.arxiv.org/api/query"
OPENALEX_API = "https://api.openalex.org/works"
CROSSREF_API = "https://api.crossref.org/works"
S2_API = "https://api.semanticscholar.org/graph/v1"
_S2_FIELDS = "title,year,venue,authors,externalIds,citationCount,url"

_ARXIV_ID_RE = re.compile(r"(?:arxiv[:/\s]*)?(\d{4}\.\d{4,5})(?:v\d+)?$", re.IGNORECASE)
_DOI_RE = re.compile(r"^(?:https?://(?:dx\.)?doi\.org/)?(10\.\d{4,9}/\S+)$", re.IGNORECASE)


class ScholarLookupError(RuntimeError):
    """A lookup could not be completed (network / HTTP / parse failure) — NOT 'does not exist'."""


class _HTTPStatusError(ScholarLookupError):
    def __init__(self, status: int, url: str):
        super().__init__(f"HTTP {status} for {url}")
        self.status = status


def _ua() -> str:
    mail = os.environ.get("RAT_CONTACT_MAIL", "").strip()
    return f"{_UA_BASE} mailto:{mail}" if mail else _UA_BASE


def default_transport(url: str, headers: Dict[str, str]) -> bytes:
    """urllib transport: GET url -> body bytes. HTTP error -> _HTTPStatusError; network -> ScholarLookupError."""
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT_S) as resp:  # nosec - fixed public API hosts
            return resp.read()
    except urllib.error.HTTPError as e:  # has a status code
        raise _HTTPStatusError(e.code, url) from e
    except urllib.error.URLError as e:
        raise ScholarLookupError(f"network failure for {url}: {e.reason}") from e


def _get(url: str, transport: Optional[Transport], extra_headers: Optional[Dict[str, str]] = None) -> bytes:
    headers = {"User-Agent": _ua(), "Accept": "*/*"}
    if extra_headers:
        headers.update(extra_headers)
    return (transport or default_transport)(url, headers)


def _fetch_parse(url: str, parser, transport: Optional[Transport],
                 extra_headers: Optional[Dict[str, str]] = None):
    """GET + parse, with PARSE failures normalized to ScholarLookupError. A provider returning
    malformed XML/JSON is a 'could not check this source' condition (like a network error) —
    callers (paper_search.search, citation_existence) degrade that source to source_errors /
    lookup_error; it must NEVER crash the whole search or be read as confirmed 'not found'."""
    body = _get(url, transport, extra_headers)
    try:
        return parser(body)
    except ScholarLookupError:
        raise
    except Exception as e:  # ET.ParseError, json.JSONDecodeError, malformed-shape KeyError, ...
        raise ScholarLookupError(f"malformed response body from {url}: {type(e).__name__}: {e}") from e


def _record(source: str, rid: str, title: str, year: Optional[int], venue: str,
            authors: List[str], doi: Optional[str], arxiv_id: Optional[str],
            url: str, cited_by_count: Optional[int]) -> dict:
    return {"source": source, "id": rid, "title": (title or "").strip(),
            "year": year, "venue": (venue or "").strip(), "authors": authors[:8],
            "doi": normalize_doi(doi) if doi else None, "arxiv_id": arxiv_id,
            "url": url, "cited_by_count": cited_by_count}


# --------------------------------------------------------------------------- id normalization

def normalize_doi(doi: str) -> Optional[str]:
    """Lowercased bare DOI ('10.x/...') or None if the string is not a DOI."""
    m = _DOI_RE.match((doi or "").strip())
    return m.group(1).lower() if m else None


def normalize_arxiv_id(s: str) -> Optional[str]:
    """Bare new-style arXiv id ('2403.12345', version stripped) or None."""
    m = _ARXIV_ID_RE.search((s or "").strip())
    return m.group(1) if m else None


# --------------------------------------------------------------------------- pure parsers

def _parse_arxiv_atom(body: bytes) -> List[dict]:
    root = ET.fromstring(body)
    out: List[dict] = []
    for e in root.findall("atom:entry", _ATOM_NS):
        title = (e.findtext("atom:title", default="", namespaces=_ATOM_NS) or "").strip()
        raw_id = e.findtext("atom:id", default="", namespaces=_ATOM_NS) or ""
        aid = normalize_arxiv_id(raw_id.rsplit("/", 1)[-1])
        if not aid or title.lower() == "error":
            continue
        published = e.findtext("atom:published", default="", namespaces=_ATOM_NS) or ""
        year = int(published[:4]) if published[:4].isdigit() else None
        authors = [a.findtext("atom:name", default="", namespaces=_ATOM_NS) or ""
                   for a in e.findall("atom:author", _ATOM_NS)]
        out.append(_record("arxiv", aid, title, year, "arXiv", [a for a in authors if a],
                           f"10.48550/arxiv.{aid}", aid, f"https://arxiv.org/abs/{aid}", None))
    return out


def _parse_openalex_work(w: dict) -> dict:
    doi = w.get("doi") or (w.get("ids") or {}).get("doi")
    loc = (w.get("primary_location") or {}) or {}
    venue = ((loc.get("source") or {}) or {}).get("display_name") or ""
    authors = [((a.get("author") or {}).get("display_name") or "")
               for a in (w.get("authorships") or [])]
    ndoi = normalize_doi(doi or "")
    arxiv = None
    if ndoi and ndoi.startswith("10.48550/arxiv."):
        arxiv = normalize_arxiv_id(ndoi.rsplit(".", 1)[-1]) or ndoi.split("arxiv.")[-1]
    rid = (w.get("id") or "").rsplit("/", 1)[-1]
    return _record("openalex", rid, w.get("display_name") or "", w.get("publication_year"),
                   venue, [a for a in authors if a], ndoi, arxiv,
                   w.get("id") or "", w.get("cited_by_count"))


def _parse_openalex(body: bytes) -> List[dict]:
    data = json.loads(body.decode("utf-8"))
    return [_parse_openalex_work(w) for w in (data.get("results") or [])]


def _parse_crossref_item(it: dict) -> dict:
    title = (it.get("title") or [""])[0]
    issued = ((it.get("issued") or {}).get("date-parts") or [[None]])[0]
    year = issued[0] if issued and isinstance(issued[0], int) else None
    venue = (it.get("container-title") or [""])[0]
    authors = [" ".join(x for x in [a.get("given"), a.get("family")] if x)
               for a in (it.get("author") or [])]
    doi = it.get("DOI")
    return _record("crossref", doi or "", title, year, venue, [a for a in authors if a],
                   doi, None, it.get("URL") or (f"https://doi.org/{doi}" if doi else ""),
                   it.get("is-referenced-by-count"))


def _parse_crossref_list(body: bytes) -> List[dict]:
    data = json.loads(body.decode("utf-8"))
    return [_parse_crossref_item(it) for it in ((data.get("message") or {}).get("items") or [])]


def _parse_s2_paper(p: dict) -> dict:
    ext = p.get("externalIds") or {}
    return _record("s2", p.get("paperId") or "", p.get("title") or "", p.get("year"),
                   p.get("venue") or "", [a.get("name") or "" for a in (p.get("authors") or []) if a],
                   ext.get("DOI"), normalize_arxiv_id(str(ext.get("ArXiv") or "")),
                   p.get("url") or "", p.get("citationCount"))


def _parse_s2_search(body: bytes) -> List[dict]:
    data = json.loads(body.decode("utf-8"))
    return [_parse_s2_paper(p) for p in (data.get("data") or [])]


# --------------------------------------------------------------------------- search (query -> records)

def search_arxiv(query: str, limit: int = 10, transport: Optional[Transport] = None) -> List[dict]:
    q = urllib.parse.quote(f"all:{query}")
    url = f"{ARXIV_API}?search_query={q}&start=0&max_results={int(limit)}"
    return _fetch_parse(url, _parse_arxiv_atom, transport)[:limit]


def search_openalex(query: str, limit: int = 10, transport: Optional[Transport] = None) -> List[dict]:
    params = {"search": query, "per-page": int(limit)}
    mail = os.environ.get("RAT_CONTACT_MAIL", "").strip()
    if mail:
        params["mailto"] = mail
    url = f"{OPENALEX_API}?{urllib.parse.urlencode(params)}"
    return _fetch_parse(url, _parse_openalex, transport)[:limit]


def search_crossref(query: str, limit: int = 10, transport: Optional[Transport] = None) -> List[dict]:
    url = f"{CROSSREF_API}?{urllib.parse.urlencode({'query': query, 'rows': int(limit)})}"
    return _fetch_parse(url, _parse_crossref_list, transport)[:limit]


def _s2_headers() -> Dict[str, str]:
    key = os.environ.get("RAT_S2_API_KEY", "").strip()
    return {"x-api-key": key} if key else {}


def search_s2(query: str, limit: int = 10, transport: Optional[Transport] = None) -> List[dict]:
    params = {"query": query, "limit": int(limit), "fields": _S2_FIELDS}
    url = f"{S2_API}/paper/search?{urllib.parse.urlencode(params)}"
    return _fetch_parse(url, _parse_s2_search, transport, _s2_headers())[:limit]


# --------------------------------------------------------------------------- lookups (id -> record | None)

def lookup_doi_crossref(doi: str, transport: Optional[Transport] = None) -> Optional[dict]:
    ndoi = normalize_doi(doi)
    if not ndoi:
        return None
    url = f"{CROSSREF_API}/{urllib.parse.quote(ndoi, safe='')}"
    try:
        body = _get(url, transport)
    except _HTTPStatusError as e:
        if e.status == 404:
            return None
        raise
    try:
        msg = (json.loads(body.decode("utf-8")).get("message")) or {}
    except Exception as e:  # malformed body -> 'could not check', never a confirmed absence
        raise ScholarLookupError(f"malformed Crossref body for {url}: {type(e).__name__}: {e}") from e
    return _parse_crossref_item(msg) if msg else None


def lookup_doi_openalex(doi: str, transport: Optional[Transport] = None) -> Optional[dict]:
    """Resolve a DOI via OpenAlex (covers DataCite-registered DOIs — Zenodo / figshare datasets &
    software — that a Crossref-only lookup 404s on). 404 -> None (OpenAlex answered: unknown);
    other HTTP / malformed -> ScholarLookupError (could not check)."""
    ndoi = normalize_doi(doi)
    if not ndoi:
        return None
    url = f"{OPENALEX_API}/doi:{urllib.parse.quote(ndoi, safe='')}"
    mail = os.environ.get("RAT_CONTACT_MAIL", "").strip()
    if mail:
        url += f"?mailto={urllib.parse.quote(mail)}"
    try:
        body = _get(url, transport)
    except _HTTPStatusError as e:
        if e.status == 404:
            return None
        raise
    try:
        w = json.loads(body.decode("utf-8"))
    except Exception as e:
        raise ScholarLookupError(f"malformed OpenAlex body for {url}: {type(e).__name__}: {e}") from e
    return _parse_openalex_work(w) if isinstance(w, dict) and w.get("id") else None


def lookup_arxiv(arxiv_id: str, transport: Optional[Transport] = None) -> Optional[dict]:
    aid = normalize_arxiv_id(arxiv_id)
    if not aid:
        return None
    url = f"{ARXIV_API}?id_list={urllib.parse.quote(aid)}&max_results=1"
    recs = _fetch_parse(url, _parse_arxiv_atom, transport)
    return recs[0] if recs else None


def lookup_title_s2(title: str, limit: int = 3, transport: Optional[Transport] = None) -> List[dict]:
    """Top title-search candidates from Semantic Scholar (caller judges the match)."""
    return search_s2(title, limit=limit, transport=transport)


def lookup_title_openalex(title: str, limit: int = 3, transport: Optional[Transport] = None) -> List[dict]:
    """Top title-search candidates from OpenAlex (caller judges the match)."""
    return search_openalex(title, limit=limit, transport=transport)


# --------------------------------------------------------------------------- citation graph (snowball)

def _parse_s2_edge(body: bytes, key: str) -> List[dict]:
    data = json.loads(body.decode("utf-8"))
    out = []
    for row in (data.get("data") or []):
        p = row.get(key) or {}
        if p.get("title"):
            out.append(_parse_s2_paper(p))
    return out


def get_references_s2(paper_id: str, limit: int = 25, transport: Optional[Transport] = None) -> List[dict]:
    """Outgoing references of a paper (the 'follow citations' half of the Asta PaperFinder recipe)."""
    params = {"limit": int(limit), "fields": _S2_FIELDS}
    pid = urllib.parse.quote(paper_id, safe="")          # safe="" : a '/' in the id can't rewrite the API path
    url = f"{S2_API}/paper/{pid}/references?{urllib.parse.urlencode(params)}"
    return _fetch_parse(url, lambda b: _parse_s2_edge(b, "citedPaper"), transport, _s2_headers())[:limit]


def get_citations_s2(paper_id: str, limit: int = 25, transport: Optional[Transport] = None) -> List[dict]:
    """Incoming citations of a paper (forward snowball)."""
    params = {"limit": int(limit), "fields": _S2_FIELDS}
    pid = urllib.parse.quote(paper_id, safe="")          # safe="" : a '/' in the id can't rewrite the API path
    url = f"{S2_API}/paper/{pid}/citations?{urllib.parse.urlencode(params)}"
    return _fetch_parse(url, lambda b: _parse_s2_edge(b, "citingPaper"), transport, _s2_headers())[:limit]


# --------------------------------------------------------------------------- retraction notices

def crossref_updates(doi: str, transport: Optional[Transport] = None) -> List[dict]:
    """Crossref update notices that target ``doi`` (the documented ``filter=updates:<DOI>`` query —
    a retraction/correction/concern NOTICE 'updates' the original work). Returns one
    {"type": update-type, "label": update label, "notice_doi": notice DOI} per notice; empty list
    means no notice is registered for the work. Raises ScholarLookupError on network failure."""
    ndoi = normalize_doi(doi)
    if not ndoi:
        return []
    url = f"{CROSSREF_API}?{urllib.parse.urlencode({'filter': f'updates:{ndoi}', 'rows': 10})}"
    try:
        data = json.loads(_get(url, transport).decode("utf-8"))
    except ScholarLookupError:
        raise
    except Exception as e:  # malformed -> 'could not check' (retraction_check maps to status unknown)
        raise ScholarLookupError(f"malformed Crossref updates body for {url}: {type(e).__name__}: {e}") from e
    out: List[dict] = []
    for it in ((data.get("message") or {}).get("items") or []):
        for upd in (it.get("update-to") or []):
            if normalize_doi(str(upd.get("DOI") or "")) == ndoi:
                out.append({"type": (upd.get("type") or "").lower(),
                            "label": upd.get("label") or "",
                            "notice_doi": it.get("DOI") or ""})
    return out
