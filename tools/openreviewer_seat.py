"""Decorrelated local reviewer seat (absorption wave 1; OpenReviewer / Llama-OpenReviewer-8B).

Every seat on the machine's mock-review panel runs the same frontier-model family — correlated
errors are invisible to the panel itself. OpenReviewer is an 8B local model fine-tuned on 79K
real expert reviews whose RATING DISTRIBUTION matches human reviewers (frontier chat models skew
lenient). This module POSTs the manuscript to a LOCAL Ollama endpoint serving that model and
returns one decorrelated, human-calibrated vote + a leniency anchor for the area-chair.

Honesty + optionality rules:
  - The seat is OPTIONAL infrastructure: no Ollama running / no model pulled -> the seat
    returns {"available": false, reason} and the panel proceeds without it. Never required.
  - The endpoint is LOCAL ONLY (default http://127.0.0.1:11434, override RAT_OLLAMA_URL) —
    the manuscript never leaves the machine.
  - Injectable post_transport -> offline tests with canned responses.
  - Output is a SEAT RESULT dict for the venue-readiness recipe to fold into the panel
    (mapping into a venue_review artifact is the recipe/area-chair's job — deliberately NOT done
    here, to avoid this tool guessing venue-specific fields). The area-chair logs the seat's
    mean-rating offset vs the opus panel as the leniency-bias anchor.
"""
from __future__ import annotations

import ipaddress
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from typing import Callable, Dict, Optional

PostTransport = Callable[[str, Dict[str, str], bytes], bytes]

_DEFAULT_URL = "http://127.0.0.1:11434"
_DEFAULT_MODEL = "openreviewer"
_TIMEOUT_S = 600  # an 8B model reviewing a full paper on CPU is legitimately slow
_LOCAL_HOSTNAMES = {"localhost", "ip6-localhost"}


def _assert_local_endpoint(base_url: str) -> None:
    """Enforce the LOCAL-ONLY contract: the manuscript is POSTed to this endpoint, so it must be a
    loopback address — never a remote host that would exfiltrate the paper. Rejects userinfo
    (user:pass@host) and any non-loopback host. Raises ValueError on a non-local endpoint."""
    parsed = urllib.parse.urlparse(base_url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"openreviewer endpoint must be http(s), got {parsed.scheme!r}: {base_url}")
    if parsed.username or parsed.password:
        raise ValueError(f"openreviewer endpoint must not carry userinfo (credentials in URL): {base_url}")
    host = (parsed.hostname or "").lower()
    if host in _LOCAL_HOSTNAMES:
        return
    try:
        if ipaddress.ip_address(host).is_loopback:
            return
    except ValueError:
        pass
    raise ValueError(
        f"openreviewer endpoint must be loopback (localhost / 127.0.0.1 / ::1) — the manuscript never "
        f"leaves the machine; refusing remote host {host!r} in {base_url}")

_RATING_RE = re.compile(
    r"(?im)^\s*\**\s*(rating|overall|soundness|presentation|contribution|confidence)"
    r"\s*\**\s*[:：]\s*\**\s*(\d+(?:\.\d+)?)")


class SeatUnavailable(RuntimeError):
    pass


def default_post_transport(url: str, headers: Dict[str, str], body: bytes) -> bytes:
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT_S) as resp:  # nosec - localhost only
            return resp.read()
    except urllib.error.URLError as e:
        raise SeatUnavailable(f"local Ollama endpoint unreachable at {url}: "
                              f"{getattr(e, 'reason', e)}") from e


def parse_ratings(text: str) -> Dict[str, float]:
    """Best-effort deterministic extraction of 'Rating: N'-style lines (lowercased keys).
    The first occurrence of each key wins (review templates state them once up front)."""
    out: Dict[str, float] = {}
    for m in _RATING_RE.finditer(text or ""):
        key = m.group(1).lower()
        if key not in out:
            out[key] = float(m.group(2))
    return out


def review_with_local_seat(paper_markdown: str, venue_template: str,
                           url: Optional[str] = None, model: Optional[str] = None,
                           post_transport: Optional[PostTransport] = None) -> dict:
    """One decorrelated review vote from the local OpenReviewer seat.

    Returns {"available": true, "seat", "model", "review_text", "ratings"} or
    {"available": false, "reason"} — the caller folds an available seat into the panel and
    silently proceeds without an unavailable one (it is an anchor, never a dependency).
    """
    if not (paper_markdown or "").strip():
        raise ValueError("review_with_local_seat requires the paper markdown")
    if not (venue_template or "").strip():
        raise ValueError("review_with_local_seat requires the venue review template")
    base = (url or os.environ.get("RAT_OLLAMA_URL", "").strip() or _DEFAULT_URL).rstrip("/")
    _assert_local_endpoint(base)                         # LOCAL-ONLY contract (manuscript never leaves the box)
    mdl = model or os.environ.get("RAT_OPENREVIEWER_MODEL", "").strip() or _DEFAULT_MODEL
    body = json.dumps({"model": mdl, "stream": False,
                       "prompt": f"{venue_template}\n\n---\n\nPAPER:\n\n{paper_markdown}"}).encode("utf-8")
    transport = post_transport or default_post_transport
    try:
        raw = transport(f"{base}/api/generate", {"Content-Type": "application/json"}, body)
        data = json.loads(raw.decode("utf-8"))
        text = str(data.get("response") or "")
        if not text.strip():
            return {"available": False, "reason": f"seat answered with an empty response (model {mdl})"}
        return {"available": True, "seat": "llama-openreviewer-8b", "model": mdl,
                "review_text": text, "ratings": parse_ratings(text)}
    except SeatUnavailable as e:
        return {"available": False, "reason": str(e)}
    except (ValueError, KeyError) as e:  # malformed endpoint answer
        return {"available": False, "reason": f"seat endpoint returned malformed data: {e}"}


def leniency_offset(seat_ratings: Dict[str, float], panel_mean_rating: Optional[float]) -> Optional[float]:
    """panel_mean - seat_rating for the 'rating'/'overall' key — positive means the in-house
    panel is MORE lenient than the human-calibrated seat. None when either side is missing."""
    seat = seat_ratings.get("rating", seat_ratings.get("overall"))
    if seat is None or panel_mean_rating is None:
        return None
    return round(float(panel_mean_rating) - float(seat), 4)
