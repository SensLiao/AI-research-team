"""JBI step-3 citation chasing: backward and forward over a seed pool (Semantic Scholar).

Closes failure-catalog items (``_design/2026-08-20-team-upgrade/00-inputs-failure-catalog.md``):
  A4 — JBI step 3 absent: no backward/forward citation chasing existed in any executed
       mode. This is the run-proven ``chase_v2`` engine (S2 graph endpoints, ~2 requests
       per seed instead of an OpenAlex request storm) promoted into the machine, with all
       run/domain vocabulary stripped — seeds are campaign input.
  A5 — no checkpointing: per-seed checkpoint + ``.done`` ledger; an interrupted chase
       resumes instead of restarting. An unchased seed is a hole in the search, so a seed
       that resolves through nothing is reported as UNRESOLVED, never quietly dropped.

Throttling: S2 429s are throttles (retryable) — patient bounded backoff lives in the
``scholar_clients`` resilient default transport, never a circuit breaker. A budget-class
429 (``ScholarBudgetError``) is NOT retried: the checkpoint is saved and the error
propagates so the operator sees the channel and its reset hint (re-run to resume).

Never writes the vault; output goes to the caller's run-local path only.
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from research_agent_teams.tools.scholar_clients import (
    ScholarBudgetError,
    ScholarLookupError,
    Transport,
    is_budget_status_error,
    normalize_arxiv_id,
    normalize_doi,
    resilient_transport,
    sanitize_scholar_error,
    get_citations_s2,
    get_references_s2,
    search_s2,
)

CHASE_ENGINE_VERSION = "citation-chase/v1"

_DIRECTIONS = ("backward", "forward")


@dataclass
class ChaseResult:
    """Per-seed accounting: chased vs unresolved is countable, never silent."""

    out_path: str
    seeds_total: int
    seeds_chased: int
    seeds_unresolved: List[str]     # seed ids that resolve through nothing — holes, named
    n_records: int
    n_backward: int
    n_forward: int
    errors: List[dict] = field(default_factory=list)
    resumed: bool = False
    complete: bool = False
    engine_version: str = CHASE_ENGINE_VERSION


def _reject_vault_path(path) -> None:
    """Two-repo seam guard (hard boundary §1): chase output never lands in the vault."""
    resolved = str(Path(path).resolve()).replace("\\", "/").lower()
    if "phd-research-os" in resolved:
        raise ValueError(f"refusing to write inside the knowledge vault (promote-gate-only): {path}")


def _polite_transport(transport: Optional[Transport], mailto: str) -> Transport:
    """Contact rides in the User-Agent HEADER only — never in the URL."""
    inner = transport or resilient_transport

    def wrapped(url: str, headers: Dict[str, str]) -> bytes:
        h = dict(headers or {})
        ua = h.get("User-Agent", "research-agent-teams/1.0 (research use; +local)")
        if mailto and "mailto:" not in ua:
            ua = f"{ua} mailto:{mailto}"
        h["User-Agent"] = ua
        return inner(url, h)

    return wrapped


def _norm_title(t) -> str:
    return re.sub(r"[^a-z0-9]", "", str(t or "").lower())[:80]


def _dedup_key(rec: dict) -> str:
    if rec.get("doi"):
        return f"doi:{str(rec['doi']).lower()}"
    if rec.get("arxiv_id"):
        return f"arxiv:{rec['arxiv_id']}"
    if rec.get("id"):
        return f"s2:{rec['id']}"
    return f"title:{_norm_title(rec.get('title'))}"


def _resolve_seed_id(seed: dict, transport: Transport) -> Optional[str]:
    """Seed -> an S2 paper identifier: DOI, else arXiv id, else a title search.
    Returns None when the seed resolves through nothing (an UNRESOLVED hole, counted)."""
    doi = normalize_doi(str(seed.get("doi") or "")) or str(seed.get("doi") or "").strip()
    if doi:
        return f"DOI:{doi}"
    arxiv = normalize_arxiv_id(str(seed.get("arxiv_id") or seed.get("arxiv") or ""))
    if arxiv:
        return f"arXiv:{arxiv}"
    title = str(seed.get("title") or "").strip()
    if not title:
        return None
    query = re.sub(r"[^A-Za-z0-9 ]", " ", title)[:180].strip()
    if not query:
        return None
    hits = search_s2(query, limit=1, transport=transport)
    if not hits:
        return None
    # accept only a lexically-plausible match — a wrong seed poisons both directions
    a = _norm_title(hits[0].get("title"))
    b = _norm_title(title)
    if a and b and (a[:60] == b[:60] or a in b or b in a):
        return hits[0].get("id") or None
    return None


def _page_direction(seed_id: str, direction: str, transport: Transport, *, pages: int,
                    page_size: int, pause_s: float,
                    sleep: Callable[[float], None]) -> List[dict]:
    fetch = get_references_s2 if direction == "backward" else get_citations_s2
    out: List[dict] = []
    for page_index in range(pages):
        rows = fetch(seed_id, limit=page_size, transport=transport,
                     offset=page_index * page_size)
        out.extend(rows)
        if len(rows) < page_size:
            break
        if pause_s:
            sleep(pause_s)
    return out


def chase(seeds: List[dict], out_path: Path, *, mailto: str,
          directions: Sequence[str] = _DIRECTIONS,
          transport: Optional[Transport] = None, pages: int = 5, page_size: int = 100,
          pause_s: float = 1.5, sleep: Callable[[float], None] = time.sleep) -> ChaseResult:
    """Chase every seed backward (its references) and/or forward (works citing it).

    Seeds carry ``{id, title, doi?, arxiv_id?}``; ``id`` is the ledger key. Per-seed
    checkpoint + resume: records land in ``out_path`` and the ledger in
    ``<out_path stem>.done.json`` after every seed. A seed whose requests FAIL (network /
    throttle exhaustion) is recorded as an error and retried on the next run — only seeds
    that were actually chased or affirmatively resolved-to-nothing enter the ledger.
    """
    dirs = tuple(directions)
    unknown = [d for d in dirs if d not in _DIRECTIONS]
    if not dirs or unknown:
        raise ValueError(f"unknown directions {unknown or list(dirs)} (known: {list(_DIRECTIONS)})")
    if not str(mailto or "").strip():
        raise ValueError("chase requires a contact mailto (polite-pool identification)")
    seeds = list(seeds or [])
    for i, s in enumerate(seeds):
        if not isinstance(s, dict) or not str(s.get("id") or "").strip():
            raise ValueError(f"seed #{i} has no 'id' — seeds carry {{id, title, doi?, arxiv_id?}}")

    out_path = Path(out_path)
    _reject_vault_path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    done_path = out_path.with_name(out_path.stem + ".done.json")

    records: List[dict] = json.loads(out_path.read_text(encoding="utf-8")) if out_path.exists() else []
    ledger: Dict[str, dict] = (json.loads(done_path.read_text(encoding="utf-8"))
                               if done_path.exists() else {})
    resumed = bool(ledger)
    seen = {_dedup_key(r) for r in records}
    errors: List[dict] = []
    polite = _polite_transport(transport, str(mailto).strip())

    def save() -> None:
        out_path.write_text(json.dumps(records, ensure_ascii=False, indent=1), encoding="utf-8")
        done_path.write_text(json.dumps(ledger, ensure_ascii=False, indent=1), encoding="utf-8")

    for seed in seeds:
        sid = str(seed["id"]).strip()
        if sid in ledger:
            continue
        try:
            paper_id = _resolve_seed_id(seed, polite)
            if paper_id is None:
                ledger[sid] = {"status": "unresolved"}
                save()
                continue
            counts = {"backward": 0, "forward": 0}
            for direction in dirs:
                rows = _page_direction(paper_id, direction, polite, pages=pages,
                                       page_size=page_size, pause_s=pause_s, sleep=sleep)
                for r in rows:
                    key = _dedup_key(r)
                    if key and key not in seen:
                        seen.add(key)
                        records.append(dict(r, channel=f"citation-chase:{direction}",
                                            seed_id=sid))
                        counts[direction] += 1
                if pause_s:
                    sleep(pause_s)
        except ScholarBudgetError:
            save()   # budget-class 429: checkpoint, then stop — NEVER retried (A2)
            raise
        except ScholarLookupError as e:
            # transient failure: named, seed NOT marked done — retried on the next run
            errors.append({"seed_id": sid, "error": sanitize_scholar_error(e)})
            save()
            continue
        ledger[sid] = {"status": "chased", "paper_id": paper_id,
                       "backward": counts["backward"], "forward": counts["forward"]}
        save()

    unresolved = sorted(k for k, v in ledger.items() if v.get("status") == "unresolved")
    return ChaseResult(
        out_path=str(out_path),
        seeds_total=len(seeds),
        seeds_chased=sum(1 for v in ledger.values() if v.get("status") == "chased"),
        seeds_unresolved=unresolved,
        n_records=len(records),
        n_backward=sum(1 for r in records if str(r.get("channel", "")).endswith("backward")),
        n_forward=sum(1 for r in records if str(r.get("channel", "")).endswith("forward")),
        errors=errors,
        resumed=resumed,
        complete=all(str(s["id"]).strip() in ledger for s in seeds),
    )
