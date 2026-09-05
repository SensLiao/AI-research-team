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
  - Optional env: RAT_OPENALEX_API_KEY (OpenAlex API budget), RAT_S2_API_KEY
    (Semantic Scholar quota), RAT_CONTACT_MAIL (polite-pool identification for
    OpenAlex/Crossref).
  - This module never writes files and never touches the vault.

Normalized record:
  {"source": "arxiv|openalex|crossref|s2", "id": str, "title": str, "year": int|None,
   "venue": str, "authors": [str, ...], "doi": str|None, "arxiv_id": str|None,
   "url": str, "cited_by_count": int|None}
"""
from __future__ import annotations

import json
import http.client
import os
import random
import re
import socket
import time
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
_SCHOLAR_URL_RE = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)
_SENSITIVE_ASSIGNMENT_RE = re.compile(
    r"(?i)\b(api[_-]?key|access[_-]?token|token|credential|secret|mailto|contact|email)="
    r"([^\s&;,]+)"
)
_SENSITIVE_ENV_NAMES = (
    "RAT_OPENALEX_API_KEY",
    "RAT_S2_API_KEY",
    "RAT_CONTACT_MAIL",
)


def sanitize_scholar_url(url: object) -> str:
    """Return a request identity that cannot retain query values or fragments."""
    value = str(url or "")
    try:
        parsed = urllib.parse.urlsplit(value)
        if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
            return "[invalid scholarly request]"
        host = parsed.hostname.lower()
        if parsed.port is not None:
            host = f"{host}:{parsed.port}"
        return urllib.parse.urlunsplit(
            (parsed.scheme.lower(), host, parsed.path or "/", "", "")
        )
    except (TypeError, ValueError):
        return "[invalid scholarly request]"


def sanitize_scholar_error(detail: object) -> str:
    """Strip URL queries and configured credential/contact values from durable diagnostics."""
    text = str(detail or "scholarly provider failure")
    text = _SCHOLAR_URL_RE.sub(lambda match: sanitize_scholar_url(match.group(0)), text)
    text = _SENSITIVE_ASSIGNMENT_RE.sub(
        lambda match: f"{match.group(1)}=[REDACTED]", text
    )
    for name in _SENSITIVE_ENV_NAMES:
        value = os.environ.get(name, "").strip()
        if not value:
            continue
        encoded_values = {
            value,
            urllib.parse.quote(value, safe=""),
            urllib.parse.quote_plus(value),
        }
        for candidate in encoded_values:
            if candidate:
                text = text.replace(candidate, "[REDACTED]")
    return text


class ScholarLookupError(RuntimeError):
    """A lookup could not be completed (network / HTTP / parse failure) — NOT 'does not exist'."""

    def __init__(self, detail: object):
        super().__init__(sanitize_scholar_error(detail))


class _HTTPStatusError(ScholarLookupError):
    def __init__(self, status: int, url: str, *, body_snippet: str = "",
                 retry_after_s: Optional[float] = None):
        super().__init__(f"HTTP {status} for {url}")
        self.status = status
        self.body_snippet = body_snippet          # first bytes of the error body (429 classification)
        self.retry_after_s = retry_after_s        # parsed Retry-After header, when the provider sent one


# --------------------------------------------------------------------------- budget-429 classification
# Failure-catalog A2: an OpenAlex 429 is a DAILY REQUEST BUDGET (resets 00:00 UTC), not a
# throttle — exponential backoff can never succeed against it. A budget-class 429 must be
# NAMED and NEVER retried; a throttle-class 429 is retried with backoff (A1: no breakers).

_CHANNEL_BY_HOST = {
    "api.openalex.org": "openalex",
    "export.arxiv.org": "arxiv",
    "api.crossref.org": "crossref",
    "api.semanticscholar.org": "s2",
}
_BUDGET_RESET_HINTS = {
    "openalex": ("OpenAlex enforces a daily request budget that resets 00:00 UTC — "
                 "backoff cannot succeed today; stop, do not spin"),
}
GENERIC_BUDGET_RESET_HINT = ("provider request budget exhausted — retrying now cannot "
                             "succeed; wait for the provider's reset window")


def channel_for_url(url: str) -> str:
    """Map a request URL to its scholarly channel name (falls back to the bare host)."""
    try:
        host = (urllib.parse.urlsplit(str(url or "")).hostname or "").lower()
    except (TypeError, ValueError):
        host = ""
    return _CHANNEL_BY_HOST.get(host, host or "unknown")


def budget_reset_hint(channel: str) -> str:
    return _BUDGET_RESET_HINTS.get(channel, GENERIC_BUDGET_RESET_HINT)


class ScholarBudgetError(ScholarLookupError):
    """A budget-class 429: the provider's request budget is exhausted for its whole window.

    NEVER retried and never breaker'd — the caller must checkpoint, name the channel as
    lost-for-the-window, and stop cleanly (resumable after the reset)."""

    def __init__(self, channel: str, reset_hint: Optional[str] = None, *,
                 status: int = 429, detail: object = None):
        self.channel = channel
        self.status = status
        self.reset_hint = reset_hint or budget_reset_hint(channel)
        super().__init__(detail or f"budget-class HTTP {status} from {channel}: {self.reset_hint}")


def is_budget_status_error(exc: object) -> bool:
    """True when ``exc`` is a 429 whose body names a budget (vs a plain throttle)."""
    if isinstance(exc, ScholarBudgetError):
        return True
    return (isinstance(exc, _HTTPStatusError) and exc.status == 429
            and "budget" in (exc.body_snippet or "").lower())


def _parse_retry_after(value: object) -> Optional[float]:
    try:
        seconds = float(str(value).strip())
        return seconds if seconds >= 0 else None
    except (TypeError, ValueError):
        return None


def _ua() -> str:
    mail = os.environ.get("RAT_CONTACT_MAIL", "").strip()
    return f"{_UA_BASE} mailto:{mail}" if mail else _UA_BASE


def default_transport(url: str, headers: Dict[str, str]) -> bytes:
    """urllib transport: GET url -> body bytes. HTTP error -> _HTTPStatusError; network -> ScholarLookupError.

    Exactly ONE attempt (retry/backoff lives in ``retrying_transport``; the module default
    is ``resilient_transport``). On an HTTP error the first bytes of the error body and any
    Retry-After header are preserved on the exception so a 429 can be classified as
    budget-class (A2) vs throttle-class."""
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT_S) as resp:  # nosec - fixed public API hosts
            return resp.read()
    except urllib.error.HTTPError as e:  # has a status code
        snippet = ""
        try:
            snippet = (e.read(2048) or b"").decode("utf-8", "replace")
        except (OSError, ValueError, AttributeError):
            snippet = ""
        retry_after = _parse_retry_after(e.headers.get("Retry-After")) if e.headers else None
        raise _HTTPStatusError(e.code, url, body_snippet=snippet,
                               retry_after_s=retry_after) from e
    except urllib.error.URLError as e:
        raise ScholarLookupError(f"network failure for {url}: {e.reason}") from e
    except (TimeoutError, socket.timeout, ConnectionError, OSError,
            http.client.HTTPException) as e:
        # ``urlopen`` may succeed and only fail while ``resp.read()`` consumes the TLS socket.
        # urllib does not wrap those read-time failures in URLError, so normalize them here too;
        # callers must record LOOKUP_ERROR rather than crash or misclassify the citation as absent.
        raise ScholarLookupError(
            f"network failure for {url}: {type(e).__name__}: {e}"
        ) from e


# --------------------------------------------------------------------------- retry / pacing (A1/A2 fixes)
# Bounded retry with jitter on transient statuses; NEVER a circuit breaker (a transient
# failure costs time, never a whole channel). Budget-class 429s are raised immediately as
# ScholarBudgetError and are NEVER retried. Injected test transports bypass all of this —
# the injectable-transport contract keeps every test offline and instant.

_RETRYABLE_STATUSES = frozenset({429, 500, 502, 503, 504})
_RETRY_MAX_TRIES = 4
_RETRY_BASE_SLEEP_S = 1.0
_RETRY_MAX_SLEEP_S = 30.0
# arXiv's API terms ask for >= 3 s between requests; violated by multi-query plans before.
# Semantic Scholar documents 1 request/second with an API key (a shared pool without one); the
# recursive funnel issues consecutive S2 searches, which returned 429 before this pacing existed.
_MIN_INTERVAL_S = {"export.arxiv.org": 3.0, "api.semanticscholar.org": 1.0}
_last_request_monotonic: Dict[str, float] = {}


def _pace(url: str, sleep: Callable[[float], None] = time.sleep) -> None:
    """Per-host minimum-interval pacing (applies only to the real-network default path)."""
    try:
        host = (urllib.parse.urlsplit(url).hostname or "").lower()
    except (TypeError, ValueError):
        return
    min_interval = _MIN_INTERVAL_S.get(host)
    if not min_interval:
        return
    now = time.monotonic()
    last = _last_request_monotonic.get(host)
    if last is not None and now - last < min_interval:
        sleep(min_interval - (now - last))
    _last_request_monotonic[host] = time.monotonic()


def retrying_transport(inner: Transport, *, max_tries: int = _RETRY_MAX_TRIES,
                       base_sleep_s: float = _RETRY_BASE_SLEEP_S,
                       max_sleep_s: float = _RETRY_MAX_SLEEP_S,
                       sleep: Callable[[float], None] = time.sleep,
                       jitter: Callable[[], float] = random.random,
                       pace: Optional[Callable[[str], None]] = None) -> Transport:
    """Wrap ``inner`` with bounded retry/backoff (+jitter) on 429/500/502/503/504.

    - budget-class 429 (body names a budget) -> ScholarBudgetError immediately, NEVER retried;
    - throttle-class 429 / 5xx -> sleep min(max_sleep, Retry-After or base*2^attempt + jitter);
    - network errors and every other status raise unchanged (no retry — the 404-vs-error
      and read-failure disciplines of ``default_transport`` are preserved);
    - never a circuit breaker: each request starts with the channel alive.
    """
    def transport(url: str, headers: Dict[str, str]) -> bytes:
        for attempt in range(max_tries):
            if pace is not None:
                pace(url)
            try:
                return inner(url, headers)
            except _HTTPStatusError as e:
                if is_budget_status_error(e):
                    raise ScholarBudgetError(channel_for_url(url), status=e.status) from e
                if e.status in _RETRYABLE_STATUSES and attempt + 1 < max_tries:
                    delay = (e.retry_after_s if e.retry_after_s is not None
                             else base_sleep_s * (2 ** attempt) + jitter())
                    sleep(min(max_sleep_s, max(0.0, delay)))
                    continue
                raise
        raise ScholarLookupError(f"retries exhausted for {url}")  # pragma: no cover - loop always raises

    return transport


_DEFAULT_RETRYING: Transport = retrying_transport(default_transport, pace=_pace)


def resilient_transport(url: str, headers: Dict[str, str]) -> bytes:
    """The module-default transport: per-host pacing + bounded retry around ``default_transport``."""
    return _DEFAULT_RETRYING(url, headers)


def _get(url: str, transport: Optional[Transport], extra_headers: Optional[Dict[str, str]] = None) -> bytes:
    headers = {"User-Agent": _ua(), "Accept": "*/*"}
    if extra_headers:
        headers.update(extra_headers)
    return (transport or resilient_transport)(url, headers)


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
    q = urllib.parse.quote(f"all:{query}", encoding="utf-8", errors="strict")
    url = f"{ARXIV_API}?search_query={q}&start=0&max_results={int(limit)}"
    return _fetch_parse(url, _parse_arxiv_atom, transport)[:limit]


def _reject_openalex_query_key() -> None:
    if os.environ.get("RAT_OPENALEX_API_KEY", "").strip():
        raise ScholarLookupError(
            "OpenAlex provider failure: configured RAT_OPENALEX_API_KEY uses query-only "
            "authentication; request blocked before transport"
        )


def _openalex_params(params: Dict[str, object]) -> Dict[str, object]:
    """Return metadata params only; OpenAlex query-key auth is unsafe for this client."""
    _reject_openalex_query_key()
    return dict(params)


def search_openalex(query: str, limit: int = 10, transport: Optional[Transport] = None) -> List[dict]:
    _reject_openalex_query_key()
    params = {"search": query, "per-page": int(limit)}
    url = f"{OPENALEX_API}?{urllib.parse.urlencode(params, encoding='utf-8', errors='strict')}"
    return _fetch_parse(url, _parse_openalex, transport)[:limit]


def search_crossref(query: str, limit: int = 10, transport: Optional[Transport] = None) -> List[dict]:
    url = (f"{CROSSREF_API}?" + urllib.parse.urlencode(
        {"query": query, "rows": int(limit)}, encoding="utf-8", errors="strict"))
    return _fetch_parse(url, _parse_crossref_list, transport)[:limit]


def _s2_headers() -> Dict[str, str]:
    key = os.environ.get("RAT_S2_API_KEY", "").strip()
    return {"x-api-key": key} if key else {}


def search_s2(query: str, limit: int = 10, transport: Optional[Transport] = None) -> List[dict]:
    params = {"query": query, "limit": int(limit), "fields": _S2_FIELDS}
    url = (f"{S2_API}/paper/search?" +
           urllib.parse.urlencode(params, encoding="utf-8", errors="strict"))
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
    _reject_openalex_query_key()
    url = f"{OPENALEX_API}/doi:{urllib.parse.quote(ndoi, safe='')}"
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


def get_references_s2(paper_id: str, limit: int = 25, transport: Optional[Transport] = None,
                      offset: int = 0) -> List[dict]:
    """Outgoing references of a paper (the 'follow citations' half of the Asta PaperFinder recipe).

    ``offset`` pages through long reference lists (audit Q2 defect 5: a real chase pages;
    a single capped page silently truncates the JBI step-3 search)."""
    params = {"limit": int(limit), "fields": _S2_FIELDS}
    if int(offset) > 0:
        params["offset"] = int(offset)
    pid = urllib.parse.quote(paper_id, safe="")          # safe="" : a '/' in the id can't rewrite the API path
    url = f"{S2_API}/paper/{pid}/references?{urllib.parse.urlencode(params)}"
    return _fetch_parse(url, lambda b: _parse_s2_edge(b, "citedPaper"), transport, _s2_headers())[:limit]


def get_citations_s2(paper_id: str, limit: int = 25, transport: Optional[Transport] = None,
                     offset: int = 0) -> List[dict]:
    """Incoming citations of a paper (forward snowball). ``offset`` pages the citation list."""
    params = {"limit": int(limit), "fields": _S2_FIELDS}
    if int(offset) > 0:
        params["offset"] = int(offset)
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
