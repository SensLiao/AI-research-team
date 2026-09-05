"""Checkpointed, breaker-free multi-channel search-campaign driver (JBI step-2 engine).

Closes failure-catalog items (``_design/2026-08-20-team-upgrade/00-inputs-failure-catalog.md``):
  A1 — channel silently lost: NO circuit breakers, by contract — a failing request costs
       time (and is named), never a whole channel; and a ``channels_lost`` list is ALWAYS
       present in the result (empty = healthy), so a dead channel is loud, not buried.
  A2 — 429 misread: a budget-class 429 (the provider names a request budget in the body)
       is classified via ``scholar_clients`` and raised as ``BudgetExhaustedError`` —
       checkpoint saved first, never retried, never spun on; the campaign resumes cleanly
       after the provider's reset window.
  A5 — no checkpointing: the record store and a per-(channel, query) done-ledger are
       rewritten after EVERY query; an interrupted campaign resumes instead of restarting.
  A6 — zero-yield rows ignored: raw-zero queries are collected in ``zero_yield_queries``
       and per-channel raw yield in ``channel_yield`` — the channel-yield watchdog's feed.

Generalized from the run's ``harvest_v2.py`` (cursor-paged OpenAlex, breaker-free) with the
audit's correction that the promoted engine must checkpoint per query (the run's search
streams still wrote once at the end). Query lists are campaign input — no domain vocabulary
lives here. Channels delegate to ``scholar_clients`` where a client exists; OpenAlex is
cursor-paged locally (depth beyond one page is the point of the campaign engine).

Never writes the vault; output goes to the caller's run-local directory only.
"""
from __future__ import annotations

import json
import re
import time
import urllib.parse
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from research_agent_teams.tools.scholar_clients import (
    OPENALEX_API,
    ScholarBudgetError,
    ScholarLookupError,
    Transport,
    _reject_openalex_query_key,  # single source of truth for the query-key security stance
    budget_reset_hint,
    channel_for_url,
    is_budget_status_error,
    normalize_doi,
    resilient_transport,
    sanitize_scholar_error,
    search_arxiv,
    search_crossref,
    search_s2,
)

CAMPAIGN_ENGINE_VERSION = "search-campaign/v1"

KNOWN_CHANNELS = ("openalex", "arxiv", "crossref", "s2")

RECORDS_FILE = "campaign-records.json"
STATE_FILE = "campaign-state.json"
ERRORS_FILE = "campaign-errors.json"
REPORT_FILE = "campaign-report.json"

_OA_SELECT = ("id,doi,ids,title,publication_year,type,cited_by_count,open_access,"
              "primary_location,authorships,abstract_inverted_index")


class BudgetExhaustedError(RuntimeError):
    """A channel's request budget is exhausted for its whole window (A2).

    The campaign has already saved its checkpoint when this raises: stop cleanly, report
    the channel and the reset hint, re-run the same campaign after the window to resume."""

    def __init__(self, channel: str, reset_hint: str):
        self.channel = channel
        self.reset_hint = reset_hint
        super().__init__(
            f"search budget exhausted on channel '{channel}': {reset_hint} — "
            f"campaign checkpoint saved; re-run to resume")


@dataclass
class CampaignResult:
    """Per-channel yield accounting for the channel-yield watchdog.

    ``channels_lost`` is ALWAYS present — empty means every declared channel contributed
    at least one raw record. A listed channel's coverage claims are UNVERIFIED."""

    out_dir: str
    records_path: str
    channels: Tuple[str, ...]
    n_queries: int
    n_pairs_total: int          # (channel, query) work items
    n_pairs_done: int
    n_records: int              # unique records in the store
    channel_yield: Dict[str, dict]
    zero_yield_queries: List[str]
    channels_lost: List[str] = field(default_factory=list)
    errors: List[dict] = field(default_factory=list)
    resumed: bool = False
    complete: bool = False
    engine_version: str = CAMPAIGN_ENGINE_VERSION


# --------------------------------------------------------------------------- plumbing

def _reject_vault_path(path) -> None:
    """Two-repo seam guard (hard boundary §1): campaign output never lands in the vault."""
    resolved = str(Path(path).resolve()).replace("\\", "/").lower()
    if "phd-research-os" in resolved:
        raise ValueError(f"refusing to write inside the knowledge vault (promote-gate-only): {path}")


def _polite_transport(transport: Optional[Transport], mailto: str) -> Transport:
    """Ensure a contact address rides in the User-Agent HEADER (polite pool) — never in the
    URL (machine policy: contact/keys stay out of request query strings)."""
    inner = transport or resilient_transport

    def wrapped(url: str, headers: Dict[str, str]) -> bytes:
        h = dict(headers or {})
        ua = h.get("User-Agent", "research-agent-teams/1.0 (research use; +local)")
        if mailto and "mailto:" not in ua:
            ua = f"{ua} mailto:{mailto}"
        h["User-Agent"] = ua
        return inner(url, h)

    return wrapped


def _write_json(path: Path, payload) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")


def _read_json(path: Path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def _norm_title(t) -> str:
    return re.sub(r"[^a-z0-9]", "", str(t or "").lower())[:80]


def _dedup_key(rec: dict) -> str:
    doi = normalize_doi(str(rec.get("doi") or "")) or (rec.get("doi") or "")
    if doi:
        return f"doi:{str(doi).lower()}"
    if rec.get("arxiv_id"):
        return f"arxiv:{rec['arxiv_id']}"
    if rec.get("id"):
        return f"{rec.get('channel') or rec.get('source') or 'id'}:{rec['id']}"
    return f"title:{_norm_title(rec.get('title'))}"


# --------------------------------------------------------------------------- channels

def _oa_abstract(inv) -> Optional[str]:
    if not inv:
        return None
    pos = {}
    for word, idxs in inv.items():
        for i in idxs:
            pos[i] = word
    if not pos:
        return None
    return " ".join(pos[i] for i in sorted(pos))[:4000]


def _oa_record(w: dict, query: str) -> dict:
    """Rich OpenAlex record for corpus work: unlike the evidence-facade shape, it keeps the
    OA location (oa_url / pdf_url / pmid) that the downstream full-text ladder needs."""
    loc = (w.get("primary_location") or {}) or {}
    src = (loc.get("source") or {}) or {}
    oa = (w.get("open_access") or {}) or {}
    ids = w.get("ids") or {}
    pmid = str(ids.get("pmid") or "").rsplit("/", 1)[-1] or None
    return {
        "channel": "openalex",
        "id": (w.get("id") or "").rsplit("/", 1)[-1],
        "title": (w.get("title") or w.get("display_name") or "").strip(),
        "year": w.get("publication_year"),
        "venue": src.get("display_name"),
        "type": w.get("type"),
        "doi": normalize_doi(str(w.get("doi") or "")) or None,
        "pmid": pmid,
        "cited_by_count": w.get("cited_by_count"),
        "is_oa": oa.get("is_oa"),
        "oa_url": oa.get("oa_url"),
        "pdf_url": loc.get("pdf_url") or None,
        "authors": [
            (a.get("raw_author_name") or ((a.get("author") or {}).get("display_name")) or "")
            for a in (w.get("authorships") or [])
        ][:25],
        "abstract": _oa_abstract(w.get("abstract_inverted_index")),
        "query": query,
    }


def _search_openalex_paged(query: str, transport: Transport, *, pages: int, per_page: int,
                           pause_s: float, sleep: Callable[[float], None]) -> List[dict]:
    """Relevance-ranked, cursor-paged OpenAlex search (the harvest_v2 recovery pattern).
    No breaker: a failed page ends THIS query's paging; the channel stays alive."""
    _reject_openalex_query_key()
    out: List[dict] = []
    cursor = "*"
    for page_index in range(pages):
        params = {"search": query, "per-page": int(per_page), "cursor": cursor,
                  "select": _OA_SELECT}
        url = f"{OPENALEX_API}?{urllib.parse.urlencode(params, encoding='utf-8', errors='strict')}"
        body = transport(url, {"Accept": "application/json"})
        try:
            data = json.loads(body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as e:
            raise ScholarLookupError(
                f"malformed OpenAlex body for {url}: {type(e).__name__}: {e}") from e
        results = data.get("results") or []
        if not results:
            break
        out.extend(_oa_record(w, query) for w in results)
        cursor = (data.get("meta") or {}).get("next_cursor")
        if not cursor:
            break
        if pause_s and page_index + 1 < pages:
            sleep(pause_s)
    return out


def _run_channel_query(channel: str, query: str, transport: Transport, *, pages: int,
                       per_page: int, pause_s: float,
                       sleep: Callable[[float], None]) -> List[dict]:
    if channel == "openalex":
        return _search_openalex_paged(query, transport, pages=pages, per_page=per_page,
                                      pause_s=pause_s, sleep=sleep)
    searchers = {"arxiv": search_arxiv, "crossref": search_crossref, "s2": search_s2}
    recs = searchers[channel](query, limit=int(pages) * int(per_page), transport=transport)
    return [dict(r, channel=channel, query=query) for r in recs]


# --------------------------------------------------------------------------- the campaign

def run_campaign(queries: List[str], channels: List[str], out_dir: Path, *,
                 pages: int = 3, mailto: str, per_page: int = 25,
                 transport: Optional[Transport] = None, pause_s: float = 0.35,
                 sleep: Callable[[float], None] = time.sleep) -> CampaignResult:
    """Run every (channel, query) pair with per-query checkpointing; resume on re-run.

    - NO circuit breakers: a failed query is recorded and RETRIED on the next run (it is
      never marked done), and the channel keeps serving the remaining queries.
    - budget-class 429 -> save checkpoint, raise ``BudgetExhaustedError`` (channel + reset
      hint); a plain throttle is the transport layer's business (bounded retry, no breaker).
    - result carries per-channel yield, zero-yield queries, and an ALWAYS-present
      ``channels_lost`` list — the channel-yield watchdog's input.
    """
    clean_queries: List[str] = []
    for raw in queries or []:
        q = str(raw or "").strip()
        if q and q not in clean_queries:
            clean_queries.append(q)
    if not clean_queries:
        raise ValueError("run_campaign requires at least one non-empty query")
    channels = [str(c).strip() for c in (channels or []) if str(c).strip()]
    unknown = [c for c in channels if c not in KNOWN_CHANNELS]
    if not channels or unknown:
        raise ValueError(f"unknown channels {unknown or channels} (known: {list(KNOWN_CHANNELS)})")
    if not str(mailto or "").strip():
        raise ValueError("run_campaign requires a contact mailto (polite-pool identification)")

    out_dir = Path(out_dir)
    _reject_vault_path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    records_path = out_dir / RECORDS_FILE
    state_path = out_dir / STATE_FILE
    errors_path = out_dir / ERRORS_FILE

    records: List[dict] = _read_json(records_path, [])
    state: Dict[str, dict] = _read_json(state_path, {})
    errors: List[dict] = _read_json(errors_path, [])
    resumed = bool(state)
    seen = {_dedup_key(r) for r in records}
    polite = _polite_transport(transport, str(mailto).strip())

    pairs = [(ch, q) for ch in channels for q in clean_queries]

    def save() -> None:
        _write_json(records_path, records)
        _write_json(state_path, state)
        _write_json(errors_path, errors)

    def budget_stop(channel: str, exc: Exception) -> BudgetExhaustedError:
        hint = getattr(exc, "reset_hint", None) or budget_reset_hint(channel)
        save()
        return BudgetExhaustedError(channel, hint)

    for channel, query in pairs:
        key = f"{channel}::{query}"
        if key in state:
            continue
        try:
            got = _run_channel_query(channel, query, polite, pages=pages, per_page=per_page,
                                     pause_s=pause_s, sleep=sleep)
        except ScholarBudgetError as e:
            raise budget_stop(e.channel or channel, e) from e
        except ScholarLookupError as e:
            if is_budget_status_error(e):
                raise budget_stop(channel, e) from e
            # named, retryable on the next run (NOT marked done), channel stays alive
            errors.append({"channel": channel, "query": query,
                           "error": sanitize_scholar_error(e)})
            save()
            continue
        new = 0
        for r in got:
            k = _dedup_key(r)
            if k and k not in seen:
                seen.add(k)
                records.append(r)
                new += 1
        state[key] = {"channel": channel, "query": query, "raw": len(got), "new": new}
        save()
        if pause_s:
            sleep(pause_s)

    # ---- yield accounting (from the durable ledger, so it survives resume)
    channel_yield: Dict[str, dict] = {}
    for ch in channels:
        rows = [v for v in state.values() if v.get("channel") == ch]
        errored = [e for e in errors if e.get("channel") == ch]
        channel_yield[ch] = {
            "queries_done": len(rows),
            "queries_errored": len(errored),
            "records_raw": sum(int(v.get("raw") or 0) for v in rows),
            "records_new": sum(int(v.get("new") or 0) for v in rows),
        }
    zero_yield_queries = sorted(k for k, v in state.items() if int(v.get("raw") or 0) == 0)
    channels_lost = [ch for ch in channels if channel_yield[ch]["records_raw"] == 0]

    result = CampaignResult(
        out_dir=str(out_dir),
        records_path=str(records_path),
        channels=tuple(channels),
        n_queries=len(clean_queries),
        n_pairs_total=len(pairs),
        n_pairs_done=sum(1 for ch, q in pairs if f"{ch}::{q}" in state),
        n_records=len(records),
        channel_yield=channel_yield,
        zero_yield_queries=zero_yield_queries,
        channels_lost=channels_lost,
        errors=errors,
        resumed=resumed,
        complete=all(f"{ch}::{q}" in state for ch, q in pairs),
    )
    _write_json(out_dir / REPORT_FILE, {
        "engine_version": result.engine_version,
        "channels": list(result.channels),
        "n_queries": result.n_queries,
        "n_pairs_total": result.n_pairs_total,
        "n_pairs_done": result.n_pairs_done,
        "n_records": result.n_records,
        "channel_yield": result.channel_yield,
        "zero_yield_queries": result.zero_yield_queries,
        "channels_lost": result.channels_lost,
        "n_errors": len(result.errors),
        "complete": result.complete,
    })
    return result
