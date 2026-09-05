"""Open-access-only full-text fetch ladder with on-arrival identity verification.

Closes failure-catalog items (``_design/2026-08-20-team-upgrade/00-inputs-failure-catalog.md``):
  F  — scope rule made executable: read everything retrievable; what cannot be found or
       fetched is OUT OF SCOPE — named, counted, reason-coded (``unfetchable`` is a
       first-class status), never claimed read, never obtained by bypassing a paywall.
       Landing pages are NEVER scraped: only direct PDF URLs are downloaded.
  B2/B3 — identity verification ON ARRIVAL: every downloaded PDF's first-page text is
       checked against the expected title with ``document_identity``'s hardened
       distinctive-word comparator (self-tested against known-bad pairs); mismatches are
       QUARANTINED, never kept — a corpus that is wrong is worse than one that is small.
  A5 — per-record checkpointing: the manifest is rewritten after every record; an
       interrupted fetch resumes instead of restarting.
  A1 — no circuit breakers: a failing resolver rung costs that candidate, never a channel.

Resolution ladder per record (stop at the first VERIFIED PDF):
  1. ``pdf_url`` already on the record        (e.g. an OpenAlex primary location)
  2. ``oa_url`` already on the record
  3. arXiv id                                 -> https://arxiv.org/pdf/<id>
  4. Unpaywall by DOI (best_oa_location)      — the email query parameter is Unpaywall's
     documented authentication mechanism (its API accepts no header alternative)
  5. Europe PMC full-text PDF by DOI or PMID

Generalized from the run's ``fetch_t1_v2.py``; the queue is campaign input — no domain
vocabulary lives here. Never writes the vault; PDFs and the manifest go to caller paths.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
import urllib.parse
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, Iterator, List, Optional, Tuple

from research_agent_teams.tools import document_identity
from research_agent_teams.tools.scholar_clients import (
    ScholarBudgetError,
    ScholarLookupError,
    Transport,
    resilient_transport,
    sanitize_scholar_error,
)

FETCH_ENGINE_VERSION = "fulltext-fetch/v1"

UNPAYWALL_API = "https://api.unpaywall.org/v2/"
EUROPEPMC_API = "https://www.ebi.ac.uk/europepmc/webservices/rest"

# terminal manifest statuses — a resumed run skips these
_TERMINAL = ("verified", "quarantined", "unfetchable")


@dataclass
class FetchResult:
    """Reason-coded fetch accounting: verified / quarantined / unfetchable all countable."""

    manifest_path: str
    pdf_dir: str
    n_queue: int
    n_skipped_done: int
    n_verified: int
    n_quarantined: int
    n_unfetchable: int
    by_source: Dict[str, int]
    unfetchable: List[dict] = field(default_factory=list)   # [{key, title, reason}]
    engine_version: str = FETCH_ENGINE_VERSION


def _reject_vault_path(path) -> None:
    """Two-repo seam guard (hard boundary §1): fetched artifacts never land in the vault."""
    resolved = str(Path(path).resolve()).replace("\\", "/").lower()
    if "phd-research-os" in resolved:
        raise ValueError(f"refusing to write inside the knowledge vault (promote-gate-only): {path}")


def _polite_transport(transport: Optional[Transport], mailto: str) -> Transport:
    """Contact rides in the User-Agent HEADER — the one exception is Unpaywall's documented
    ``email`` query parameter, added explicitly in ``_candidates``."""
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


def record_key(rec: dict, index: int) -> str:
    doi = str(rec.get("doi") or "").strip().lower()
    if doi:
        return f"doi:{doi}"
    nt = _norm_title(rec.get("title"))
    if nt:
        return f"title:{nt}"
    if rec.get("id"):
        return f"id:{rec['id']}"
    return f"index:{index}"


def slugify(rec: dict, key: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", str(rec.get("title") or "").lower()).strip("-")[:64]
    h = hashlib.sha1(key.encode("utf-8")).hexdigest()[:8]
    year = rec.get("year") or "nd"
    return f"{year}-{base or 'untitled'}-{h}"


def _default_page_text(pdf_path: Path) -> str:
    """First-page text via document_identity (PyMuPDF); raises when extraction is impossible."""
    text, _n = document_identity.pdf_text(pdf_path, max_pages=1)
    return document_identity.clean_text(text)


def _candidates(rec: dict, mailto: str, transport: Transport) -> Iterator[Tuple[str, str]]:
    """Yield (source, url) in ladder order. A ``*:page`` URL is a LANDING PAGE — yielded so
    the manifest can name it, but the ladder never downloads or scrapes it."""
    if rec.get("pdf_url"):
        yield "record:pdf_url", str(rec["pdf_url"])
    if rec.get("oa_url") and rec.get("oa_url") != rec.get("pdf_url"):
        yield "record:oa_url", str(rec["oa_url"])
    if rec.get("arxiv_id"):
        aid = str(rec["arxiv_id"]).replace("arXiv:", "").strip()
        if aid:
            yield "arxiv", f"https://arxiv.org/pdf/{aid}"

    doi = str(rec.get("doi") or "").strip()
    if doi:
        # Unpaywall: the ``email`` query parameter is the API's documented auth mechanism.
        url = (UNPAYWALL_API + urllib.parse.quote(doi, safe="")
               + "?" + urllib.parse.urlencode({"email": mailto}))
        try:
            data = json.loads(transport(url, {"Accept": "application/json"}).decode("utf-8"))
            loc = (data.get("best_oa_location") or {}) if isinstance(data, dict) else {}
            if loc.get("url_for_pdf"):
                yield "unpaywall", str(loc["url_for_pdf"])
            elif loc.get("url"):
                yield "unpaywall:page", str(loc["url"])
        except ScholarBudgetError:
            raise
        except (ScholarLookupError, ValueError, UnicodeDecodeError):
            pass  # this rung failed; the next rung still runs (no breaker)

    pmcid = None
    for query in ([f'DOI:"{doi}"'] if doi else []) + (
            [f"EXT_ID:{rec['pmid']} SRC:MED"] if rec.get("pmid") else []):
        url = (f"{EUROPEPMC_API}/search?"
               + urllib.parse.urlencode({"query": query, "format": "json", "pageSize": 1}))
        try:
            data = json.loads(transport(url, {"Accept": "application/json"}).decode("utf-8"))
            hit = ((data.get("resultList") or {}).get("result") or [{}])[0]
            if hit.get("pmcid"):
                pmcid = hit["pmcid"]
                break
        except ScholarBudgetError:
            raise
        except (ScholarLookupError, ValueError, UnicodeDecodeError):
            continue
    if pmcid:
        yield "europepmc", f"{EUROPEPMC_API}/{pmcid}/fullTextPDF"


def fetch(records: List[dict], pdf_dir: Path, manifest_path: Path, *, mailto: str,
          verify_title: bool = True, transport: Optional[Transport] = None,
          page_text_fn: Optional[Callable[[Path], str]] = None,
          stop_vocab=None, quarantine_dir: Optional[Path] = None,
          threshold: float = document_identity.DEFAULT_THRESHOLD,
          pause_s: float = 0.4, sleep: Callable[[float], None] = time.sleep) -> FetchResult:
    """Fetch open-access full texts for ``records`` down the ladder; verify on arrival.

    Records may carry ``{title, year, doi?, pmid?, arxiv_id?, pdf_url?, oa_url?, id?}``.
    The manifest at ``manifest_path`` is the per-record checkpoint (rewritten after every
    record); records already in a terminal state are skipped on resume. ``stop_vocab`` is
    the profile-supplied domain stop vocabulary for the identity comparator.
    """
    if not str(mailto or "").strip():
        raise ValueError("fetch requires a contact mailto (Unpaywall auth + polite pool)")
    pdf_dir = Path(pdf_dir)
    manifest_path = Path(manifest_path)
    quarantine_dir = Path(quarantine_dir) if quarantine_dir else pdf_dir / "quarantine"
    for p in (pdf_dir, manifest_path.parent, quarantine_dir):
        _reject_vault_path(p)
    pdf_dir.mkdir(parents=True, exist_ok=True)
    quarantine_dir.mkdir(parents=True, exist_ok=True)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)

    manifest: Dict[str, dict] = (json.loads(manifest_path.read_text(encoding="utf-8"))
                                 if manifest_path.exists() else {})
    polite = _polite_transport(transport, str(mailto).strip())
    extract = page_text_fn or _default_page_text
    n_skipped = 0

    def save() -> None:
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=1),
                                 encoding="utf-8")

    for index, rec in enumerate(records or []):
        key = record_key(rec, index)
        if manifest.get(key, {}).get("status") in _TERMINAL:
            n_skipped += 1
            continue
        slug = slugify(rec, key)
        title = str(rec.get("title") or "").strip()
        attempts: List[dict] = []
        verified_source = None
        identity_score = None
        identity_method = None
        quarantined_any = False

        try:
            for source, url in _candidates(rec, str(mailto).strip(), polite):
                if source.endswith(":page"):
                    # a landing page is not a PDF; scraping it is out of contract
                    attempts.append({"source": source, "outcome": "landing_page_skipped"})
                    continue
                try:
                    raw = polite(url, {"Accept": "application/pdf"})
                except ScholarBudgetError:
                    raise
                except ScholarLookupError as e:
                    attempts.append({"source": source,
                                     "outcome": f"fetch_error: {sanitize_scholar_error(e)}"})
                    continue
                if not raw or not raw[:5].startswith(b"%PDF"):
                    attempts.append({"source": source, "outcome": "not_pdf"})
                    continue
                pdf_path = pdf_dir / f"{slug}.pdf"
                pdf_path.write_bytes(raw)

                if not verify_title or not title:
                    verified_source = source
                    identity_method = "unverified (verify_title off or no expected title)"
                    attempts.append({"source": source, "outcome": "kept_unverified"})
                    break
                try:
                    page_text = extract(pdf_path)
                except Exception as e:  # extraction impossible -> cannot verify -> quarantine
                    pdf_path.rename(quarantine_dir / f"{slug}.{source.replace(':', '_')}.pdf")
                    quarantined_any = True
                    attempts.append({"source": source,
                                     "outcome": f"quarantined: extract_failed ({type(e).__name__})"})
                    continue
                verdict = document_identity.title_match(page_text, title,
                                                        stop_vocab=stop_vocab,
                                                        threshold=threshold)
                identity_score = verdict.score
                identity_method = verdict.method
                if verdict.passed:
                    verified_source = source
                    attempts.append({"source": source, "outcome": "verified",
                                     "identity_score": verdict.score})
                    break
                pdf_path.rename(quarantine_dir / f"{slug}.{source.replace(':', '_')}.pdf")
                quarantined_any = True
                attempts.append({"source": source, "outcome": "quarantined: identity_mismatch",
                                 "identity_score": verdict.score})
        except ScholarBudgetError:
            save()   # budget-class 429: checkpoint, then stop — resumable (A2)
            raise

        if verified_source:
            status, reason = "verified", None
        elif quarantined_any:
            status, reason = "quarantined", "identity_mismatch_or_unextractable"
        elif attempts:
            status, reason = "unfetchable", "candidates_exhausted"
        else:
            status, reason = "unfetchable", "no_oa_candidate"
        manifest[key] = {
            "slug": slug, "title": title or None, "year": rec.get("year"),
            "doi": rec.get("doi"), "status": status, "reason": reason,
            "source": verified_source, "identity_score": identity_score,
            "identity_method": identity_method, "attempts": attempts,
        }
        save()
        if pause_s:
            sleep(pause_s)

    statuses = Counter(v.get("status") for v in manifest.values())
    return FetchResult(
        manifest_path=str(manifest_path),
        pdf_dir=str(pdf_dir),
        n_queue=len(records or []),
        n_skipped_done=n_skipped,
        n_verified=statuses.get("verified", 0),
        n_quarantined=statuses.get("quarantined", 0),
        n_unfetchable=statuses.get("unfetchable", 0),
        by_source=dict(Counter(v.get("source") for v in manifest.values() if v.get("source"))),
        unfetchable=[{"key": k, "title": v.get("title"), "reason": v.get("reason")}
                     for k, v in sorted(manifest.items())
                     if v.get("status") == "unfetchable"],
    )
