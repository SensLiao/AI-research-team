"""Bibliography audit + authority-backed repair for BibTeX files (failure-catalog D4).

Closes catalog item D4 (2026-08-20 team upgrade): a real run shipped 88/171 defective
bibliography entries — preprints with published versions, missing DOIs, leaked
work-notes, name-suffix render bugs — and two generator-class bugs nearly survived:
a fuzzy title match accepted a two-years-later reprint of a landmark entry because
containment alone was treated as identity, and XML-escaped authority metadata
("&amp;") reached the .bib unescaped, where the bare "&" is a LaTeX alignment tab
that kills the build.

Ported from the proven run-local pair ``ref_audit.py`` + ``fix_bib.py``
(runs/ref-free-seg-qa/deep_research-20260819T055022Z/tools/), generalized:

  * strict title matching — a bibliographic-search candidate is accepted only on
    exact normalized title equality, or containment PLUS year agreement within
    +/- 1; anything else is UNRESOLVED, never guessed (an entry with no recorded
    year never accepts a containment-only match);
  * the DOI override table is caller-injectable — for entries whose canonical
    record the bibliographic search cannot surface, a hand-verified DOI is the
    authority, not a search hit;
  * the LEAKED_WORKNOTE pattern list is caller-injectable — work-note idioms are
    campaign text, not machine truth (a generic default ships for convenience);
  * ``clean()`` is the ONE authority-metadata -> BibTeX field escaper:
    ``html.unescape`` FIRST, then LaTeX-escape (backslash, &, %, #, _, ~, ^) —
    in that order, or "&amp;" would become "\\&amp;" and the entity would be
    preserved rather than removed;
  * auto-fix applies ONLY authority-supported classes (preprint->published,
    add-doi, drop-worknote, author-suffix). VENUE_MISMATCH and UNRESOLVED are
    listed for human decision and NEVER rewritten — a venue disagreement can mean
    the entry is wrong OR that the authority matched a different work.

All HTTP goes through an injectable ``transport`` callable (the same shape as
``tools/scholar_clients.Transport``: ``transport(url, headers) -> bytes``), so
tests run fully offline. The default transport is urllib with a polite UA and
bounded exponential backoff on 429/5xx — never a permanent circuit breaker
(TU-3). A transport failure is recorded on the report as a lookup error, never
as UNRESOLVED: absence is claimed only when the authority actually answered.

Domain-general by construction: no field vocabulary, no venue names, no topic
words live in this module. Stdlib only. This module never writes the vault.
"""
from __future__ import annotations

import html
import json
import re
import shutil
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Set, Tuple

Transport = Callable[[str, Dict[str, str]], bytes]

# ------------------------------------------------------------------ defect classes
DEFECT_PREPRINT_SUPERSEDED = "PREPRINT_SUPERSEDED"
DEFECT_MISSING_DOI = "MISSING_DOI"
DEFECT_LEAKED_WORKNOTE = "LEAKED_WORKNOTE"
DEFECT_SUFFIX_RENDER_HAZARD = "SUFFIX_RENDER_HAZARD"
DEFECT_VENUE_MISMATCH = "VENUE_MISMATCH"
DEFECT_UNRESOLVED = "UNRESOLVED"

#: Defect classes an authority record supports rewriting. Everything else is
#: reported for human decision and never auto-rewritten.
AUTO_FIXABLE_CLASSES = frozenset(
    {
        DEFECT_PREPRINT_SUPERSEDED,
        DEFECT_MISSING_DOI,
        DEFECT_LEAKED_WORKNOTE,
        DEFECT_SUFFIX_RENDER_HAZARD,
    }
)
NEVER_AUTO_FIXED_CLASSES = frozenset({DEFECT_VENUE_MISMATCH, DEFECT_UNRESOLVED})

#: Generic extraction work-note idioms (workflow English, not domain vocabulary).
#: Callers whose campaigns use different idioms inject their own list.
DEFAULT_WORKNOTE_PATTERNS: Tuple[str, ...] = (
    r"not stated in the retrieved artefact",
    r"no venue named",
    r"not reported in the pdf",
    r"unknown venue",
    r"retrieved artefact",
)

# "Given M. Surname III" parses as surname="III" in BibTeX and renders "G. M. S. III".
_SUFFIX_PAT = re.compile(r"\b(?:[IVX]{2,}|Jr\.?|Sr\.?)\s*$")
_PROCEEDINGS_TYPES = frozenset({"proceedings-article", "book-chapter"})
_CROSSREF_API = "https://api.crossref.org/works"
_MAX_ATTEMPTS = 4
_BACKOFF_CAP_S = 12.0
_TIMEOUT_S = 30


class BibAuditLookupError(RuntimeError):
    """An authority lookup could not be completed — NOT 'no record exists'.

    ``status`` carries the HTTP status when one was received (e.g. 404), else None.
    Transports must raise this (or return body bytes); a 404 is mapped by the
    caller to "this id does not resolve", never to a network failure.
    """

    def __init__(self, detail: str, *, status: "int | None" = None):
        super().__init__(detail)
        self.status = status


# ------------------------------------------------------------------ reports
@dataclass
class AuditReport:
    """What ``audit`` found. Always carries the resolved authority metadata and the
    exact worknote/override inputs, so ``apply_fixes`` replays the same policy."""

    bib_path: str
    n_entries: int
    n_entries_with_defects: int
    defects_by_class: Dict[str, int] = field(default_factory=dict)
    findings: List[Dict[str, Any]] = field(default_factory=list)
    resolved: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    lookup_errors: List[Dict[str, str]] = field(default_factory=list)
    worknote_patterns: List[str] = field(default_factory=list)
    doi_overrides: Dict[str, str] = field(default_factory=dict)

    def to_payload(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class FixReport:
    """What ``apply_fixes`` changed — and, just as deliberately, what it refused to."""

    bib_path: str
    output_path: str
    backup_path: Optional[str]
    in_place: bool
    n_entries: int
    n_changed: int
    changes_by_class: Dict[str, int] = field(default_factory=dict)
    entries: List[Dict[str, Any]] = field(default_factory=list)
    #: keys carrying VENUE_MISMATCH / UNRESOLVED — left for human decision, never rewritten.
    deferred: List[str] = field(default_factory=list)

    def to_payload(self) -> Dict[str, Any]:
        return asdict(self)


# ------------------------------------------------------------------ transport
def default_transport(url: str, headers: Dict[str, str]) -> bytes:
    """urllib transport with bounded backoff on 429/5xx (<= 4 attempts, capped sleep).

    Honors a numeric ``Retry-After`` header when present. Never a permanent
    breaker: after the attempts are exhausted the error is raised and the caller
    records a lookup error — the channel is named, not silently zeroed (TU-3).
    """
    last_detail = "no attempt made"
    for attempt in range(_MAX_ATTEMPTS):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=_TIMEOUT_S) as resp:  # nosec - public metadata APIs
                return resp.read()
        except urllib.error.HTTPError as exc:
            if exc.code in (429, 500, 502, 503, 504) and attempt < _MAX_ATTEMPTS - 1:
                retry_after = None
                try:
                    retry_after = float(exc.headers.get("Retry-After", ""))
                except (TypeError, ValueError):
                    retry_after = None
                sleep_s = retry_after if retry_after is not None else 1.5 * (2 ** attempt)
                time.sleep(min(_BACKOFF_CAP_S, max(0.0, sleep_s)))
                last_detail = f"HTTP {exc.code} for {url}"
                continue
            raise BibAuditLookupError(f"HTTP {exc.code} for {url}", status=exc.code) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            if attempt < _MAX_ATTEMPTS - 1:
                time.sleep(min(_BACKOFF_CAP_S, 1.5 * (2 ** attempt)))
                last_detail = f"network failure for {url}: {exc}"
                continue
            raise BibAuditLookupError(f"network failure for {url}: {exc}") from exc
    raise BibAuditLookupError(last_detail)


def _fetch_json(url: str, headers: Dict[str, str], send: Transport) -> Optional[Dict[str, Any]]:
    """GET url -> parsed JSON dict; a 404 means 'does not resolve' -> None.

    Any other transport failure re-raises BibAuditLookupError; an unparseable body
    is a lookup error too (an authority that answered garbage did not answer)."""
    try:
        body = send(url, headers)
    except BibAuditLookupError as exc:
        if exc.status == 404:
            return None
        raise
    try:
        parsed = json.loads(body.decode("utf-8", "replace"))
    except (json.JSONDecodeError, ValueError) as exc:
        raise BibAuditLookupError(f"unparseable authority response from {url}: {exc}") from exc
    return parsed if isinstance(parsed, dict) else None


# ------------------------------------------------------------------ bib parsing
def parse_bib(text: str) -> List[Dict[str, Any]]:
    """Minimal brace-balanced BibTeX reader (entries with ``field = {value}`` bodies).

    Strict about brace balance; deliberately not a full BibTeX grammar
    (@string/@preamble and quote-delimited values are out of scope)."""
    entries: List[Dict[str, Any]] = []
    i = 0
    while True:
        at = text.find("@", i)
        if at < 0:
            break
        m = re.match(r"@(\w+)\s*\{\s*([^,]+),", text[at:])
        if not m:
            i = at + 1
            continue
        brace_offset = text[at:].find("{")
        if brace_offset < 0:
            break
        depth, j = 0, at + brace_offset
        start = j
        while j < len(text):
            if text[j] == "{":
                depth += 1
            elif text[j] == "}":
                depth -= 1
                if depth == 0:
                    break
            j += 1
        body = text[start + 1 : j]
        fields: Dict[str, str] = {}
        for fm in re.finditer(r"(\w+)\s*=\s*\{", body):
            k = fm.group(1).lower()
            d, p = 1, fm.end()
            while p < len(body) and d:
                if body[p] == "{":
                    d += 1
                elif body[p] == "}":
                    d -= 1
                p += 1
            fields[k] = body[fm.end() : p - 1].strip()
        entries.append(
            {
                "type": m.group(1).lower(),
                "key": m.group(2).strip(),
                "fields": fields,
                "raw_span": (at, j + 1),
            }
        )
        i = j + 1
    return entries


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


# ------------------------------------------------------------------ field escaping
def clean(v: Any) -> str:
    """Authority metadata -> safe BibTeX field text. THE one escaper for this job.

    Authorities return XML-escaped strings, so a venue containing "&" arrives as
    "&amp;". Written straight into a .bib that is two bugs at once: the entity
    survives into the rendered bibliography, and the bare "&" is a LaTeX
    alignment tab that kills the build. Unescape first, then LaTeX-escape — in
    that order, or "&amp;" would become "\\&amp;" and the entity would be
    preserved rather than removed (catalog D4).
    """
    s = html.unescape(str(v))
    for a, b in (
        ("\\", r"\textbackslash{}"),
        ("&", r"\&"),
        ("%", r"\%"),
        ("#", r"\#"),
        ("_", r"\_"),
        ("~", r"\textasciitilde{}"),
        ("^", r"\textasciicircum{}"),
    ):
        s = s.replace(a, b)
    return s


def fix_author(a: str) -> str:
    """``Given M. Surname III`` -> ``Surname, III, Given M.`` (BibTeX von/last/jr/first).

    Without the comma form BibTeX parses surname="III" and renders "G. M. S. III".
    Already-comma'd or braced names, and names too short to split, are untouched."""
    a = a.strip()
    if not a or "," in a or not _SUFFIX_PAT.search(a):
        return a
    parts = a.split()
    if len(parts) < 3:
        return a
    return f"{parts[-2]}, {parts[-1]}, {' '.join(parts[:-2])}"


# ------------------------------------------------------------------ authorities
def _crossref_by_doi(doi: str, send: Transport, headers: Dict[str, str]) -> Optional[Dict[str, Any]]:
    parsed = _fetch_json(f"{_CROSSREF_API}/{urllib.parse.quote(doi)}", headers, send)
    if not parsed:
        return None
    msg = parsed.get("message")
    return msg if isinstance(msg, dict) else None


def _candidate_year(item: Dict[str, Any]) -> Optional[int]:
    try:
        year = (item.get("issued", {}).get("date-parts") or [[None]])[0][0]
    except (IndexError, TypeError, AttributeError):
        return None
    return year if isinstance(year, int) else None


def _crossref_by_title(
    title: str, year: Optional[int], send: Transport, headers: Dict[str, str], mailto: str
) -> Optional[Dict[str, Any]]:
    """Resolve by title, but only accept a match the metadata actually supports.

    Containment alone is not identity: a reprint, a translation, an extended
    version and a same-titled unrelated work all pass it (that is exactly how a
    two-years-later reprint was once matched to the original — catalog D4).
    Acceptance requires exact normalized title equality, or containment PLUS
    year agreement within +/- 1; a candidate that fails both is left unresolved
    rather than guessed at. No recorded year -> containment is never enough.
    """
    query = urllib.parse.urlencode(
        {"query.bibliographic": title[:200], "rows": 8, "mailto": mailto}
    )
    parsed = _fetch_json(f"{_CROSSREF_API}?{query}", headers, send)
    if not parsed:
        return None
    try:
        items = parsed["message"]["items"]
    except (KeyError, TypeError):
        return None
    if not isinstance(items, list):
        return None
    tn = _norm(title)
    exact: List[Dict[str, Any]] = []
    loose: List[Dict[str, Any]] = []
    for it in items:
        if not isinstance(it, dict):
            continue
        cand = _norm((it.get("title") or [""])[0])
        if not cand:
            continue
        if cand == tn:
            exact.append(it)
        elif cand in tn or tn in cand:
            loose.append(it)
    if exact:
        if year:
            exact.sort(key=lambda it: abs((_candidate_year(it) or 9999) - year))
        return exact[0]
    if year:
        near = [it for it in loose if _candidate_year(it) and abs(_candidate_year(it) - year) <= 1]
        if near:
            near.sort(key=lambda it: abs(_candidate_year(it) - year))
            return near[0]
    return None


def _cr_meta(msg: Dict[str, Any]) -> Dict[str, Any]:
    ct = msg.get("container-title") or [""]
    return {
        "doi": msg.get("DOI"),
        "title": (msg.get("title") or [""])[0],
        "venue": ct[0] if ct else None,
        "year": (msg.get("issued", {}).get("date-parts") or [[None]])[0][0],
        "volume": msg.get("volume"),
        "issue": msg.get("issue"),
        "pages": msg.get("page") or msg.get("article-number"),
        "type": msg.get("type"),
        "authors": [
            " ".join(x for x in [a.get("given"), a.get("family")] if x)
            for a in (msg.get("author") or [])
        ],
        "is_preprint": msg.get("type") == "posted-content",
    }


# ------------------------------------------------------------------ audit
def audit(
    bib_path: Path,
    *,
    mailto: str,
    overrides: "Dict[str, str] | None" = None,
    worknote_patterns: "Sequence[str] | None" = None,
    transport: "Transport | None" = None,
    pace_s: "float | None" = None,
) -> AuditReport:
    """Audit a .bib against the authority record; report defects, never rewrite.

    ``overrides`` maps entry key -> hand-verified DOI (the authority for entries
    the bibliographic search cannot surface). ``worknote_patterns`` are regexes
    (case-insensitive) marking internal extraction prose. ``transport`` injects
    the HTTP layer for offline tests; ``pace_s`` is the inter-entry politeness
    sleep (defaults to 0.15 s on the live default transport, 0 with an injected
    one). Lookup failures land in ``report.lookup_errors`` — named, never
    silently degraded into UNRESOLVED.
    """
    bib_path = Path(bib_path)
    text = bib_path.read_text(encoding="utf-8")
    entries = parse_bib(text)
    doi_overrides = dict(overrides or {})
    patterns = list(worknote_patterns if worknote_patterns is not None else DEFAULT_WORKNOTE_PATTERNS)
    worknote_res = [re.compile(p, re.I) for p in patterns]
    send: Transport = transport if transport is not None else default_transport
    pace = (0.15 if transport is None else 0.0) if pace_s is None else float(pace_s)
    headers = {
        "User-Agent": f"research-agent-teams-bib-audit/1.0 (mailto:{mailto})",
        "Accept": "application/json",
    }

    findings: List[Dict[str, Any]] = []
    resolved: Dict[str, Dict[str, Any]] = {}
    lookup_errors: List[Dict[str, str]] = []

    for e in entries:
        f, key = e["fields"], e["key"]
        title = re.sub(r"[{}]", "", f.get("title", ""))
        doi = (f.get("doi") or "").strip()
        defects: List[Dict[str, Any]] = []

        # -- static defects (no network needed)
        for fld in ("howpublished", "journal", "note", "venue"):
            value = f.get(fld)
            if value and any(p.search(value) for p in worknote_res):
                defects.append({"class": DEFECT_LEAKED_WORKNOTE, "field": fld, "value": value})
        for author in re.split(r"\s+and\s+", f.get("author", "")):
            author = author.strip()
            if author and _SUFFIX_PAT.search(author) and "," not in author and not author.endswith("}"):
                defects.append(
                    {
                        "class": DEFECT_SUFFIX_RENDER_HAZARD,
                        "author": author,
                        "fix": fix_author(author),
                    }
                )

        # -- authority resolution (strict; UNRESOLVED only when authorities answered)
        try:
            year: Optional[int] = int(re.sub(r"[^0-9]", "", f.get("year", ""))[:4])
        except ValueError:
            year = None
        msg: Optional[Dict[str, Any]] = None
        errors: List[str] = []
        lookup_doi = doi_overrides.get(key) or doi
        if lookup_doi:
            try:
                msg = _crossref_by_doi(lookup_doi, send, headers)
            except BibAuditLookupError as exc:
                errors.append(str(exc))
        if msg is None and title:
            try:
                msg = _crossref_by_title(title, year, send, headers, mailto)
            except BibAuditLookupError as exc:
                errors.append(str(exc))

        if msg is None:
            if errors:
                lookup_errors.append({"key": key, "detail": "; ".join(errors)[:300]})
            else:
                defects.append(
                    {
                        "class": DEFECT_UNRESOLVED,
                        "note": "no authority record matched under the strict rule; verify by hand",
                    }
                )
        else:
            meta = _cr_meta(msg)
            resolved[key] = meta
            if not doi and meta["doi"]:
                defects.append(
                    {"class": DEFECT_MISSING_DOI, "resolved_doi": meta["doi"], "venue": meta["venue"]}
                )
            is_preprint_entry = (
                e["type"] == "misc"
                or "arxiv" in (f.get("archiveprefix", "")).lower()
                or "arxiv" in (f.get("eprinttype", "")).lower()
                or "arxiv" in (f.get("url", "")).lower()
            )
            if is_preprint_entry and not meta["is_preprint"] and meta["venue"]:
                defects.append(
                    {
                        "class": DEFECT_PREPRINT_SUPERSEDED,
                        "published_as": {
                            k: meta[k] for k in ("venue", "year", "volume", "issue", "pages", "doi")
                        },
                    }
                )
            recorded_venue = _norm(f.get("journal") or f.get("booktitle") or "")
            if (
                recorded_venue
                and meta["venue"]
                and _norm(meta["venue"]) != recorded_venue
                and recorded_venue not in _norm(meta["venue"])
                and _norm(meta["venue"]) not in recorded_venue
            ):
                defects.append(
                    {
                        "class": DEFECT_VENUE_MISMATCH,
                        "recorded": f.get("journal") or f.get("booktitle"),
                        "authority": meta["venue"],
                    }
                )

        if defects:
            findings.append({"key": key, "type": e["type"], "title": title, "defects": defects})
        if pace:
            time.sleep(pace)

    by_class: Dict[str, int] = {}
    for finding in findings:
        for d in finding["defects"]:
            by_class[d["class"]] = by_class.get(d["class"], 0) + 1

    return AuditReport(
        bib_path=str(bib_path),
        n_entries=len(entries),
        n_entries_with_defects=len(findings),
        defects_by_class=dict(sorted(by_class.items(), key=lambda kv: -kv[1])),
        findings=findings,
        resolved=resolved,
        lookup_errors=lookup_errors,
        worknote_patterns=patterns,
        doi_overrides=doi_overrides,
    )


# ------------------------------------------------------------------ fix
def _render_entry(
    entry: Dict[str, Any],
    meta: "Dict[str, Any] | None",
    defects: Set[str],
    worknote_res: List["re.Pattern[str]"],
) -> Tuple[str, List[str]]:
    """Re-serialize one entry, applying ONLY authority-supported defect classes."""
    typ, key, f = entry["type"], entry["key"], dict(entry["fields"])
    changed: List[str] = []

    # -- authors: suffix rendering
    if "author" in f and DEFECT_SUFFIX_RENDER_HAZARD in defects:
        fixed = " and ".join(fix_author(a) for a in re.split(r"\s+and\s+", f["author"]))
        if fixed != f["author"]:
            f["author"] = fixed
            changed.append("author-suffix")

    # -- drop internal work-notes (only from note-ish fields; a worknote sitting in
    #    a load-bearing field like journal is reported, never auto-deleted)
    if DEFECT_LEAKED_WORKNOTE in defects:
        for fld in ("howpublished", "note"):
            if fld in f and any(p.search(f[fld]) for p in worknote_res):
                del f[fld]
                changed.append(f"drop-{fld}")

    # -- promote preprint to the peer-reviewed record (arXiv id kept as an audit note)
    if meta and DEFECT_PREPRINT_SUPERSEDED in defects:
        arxiv = f.get("eprint") or ""
        for fld in ("archiveprefix", "eprint", "eprinttype", "primaryclass", "howpublished", "url"):
            f.pop(fld, None)
        typ = "inproceedings" if meta.get("type") in _PROCEEDINGS_TYPES else "article"
        if typ == "inproceedings":
            f["booktitle"] = clean(meta["venue"])
        else:
            f["journal"] = clean(meta["venue"])
        for src, dst in (("year", "year"), ("volume", "volume"), ("issue", "number"), ("pages", "pages")):
            if meta.get(src):
                f[dst] = clean(meta[src])
        f["doi"] = meta["doi"]
        if arxiv:
            f["note"] = f"Preprint arXiv:{arxiv}; entry promoted to the published record by bib_audit"
        changed.append("preprint->published")
    elif meta and DEFECT_MISSING_DOI in defects and meta.get("doi"):
        f["doi"] = meta["doi"]
        changed.append("add-doi")

    order = [
        "title", "author", "booktitle", "journal", "year", "volume", "number",
        "pages", "doi", "note", "howpublished", "eprint", "archiveprefix", "url",
    ]
    keys = [k for k in order if k in f] + [k for k in f if k not in order]
    width = max((len(k) for k in keys), default=8)
    body = ",\n".join(f"  {k.ljust(width)} = {{{f[k]}}}" for k in keys)
    return f"@{typ}{{{key},\n{body}\n}}", changed


def apply_fixes(bib_path: Path, report: AuditReport, *, in_place: bool = False) -> FixReport:
    """Emit a corrected .bib from an AuditReport; a citation is never silently invented.

    Applies only what the resolved authority record supports (preprint->published,
    add-doi, drop-worknote, author-suffix). Entries carrying VENUE_MISMATCH or
    UNRESOLVED are left byte-identical in content and listed in ``deferred`` for
    human decision. The whole file is re-serialized in normalized form (leading
    preamble preserved; comments between entries are not).

    ``in_place=False`` writes ``<stem>.v2<suffix>`` beside the input;
    ``in_place=True`` overwrites after copying a ``<name>.backup`` beside it.
    """
    bib_path = Path(bib_path)
    text = bib_path.read_text(encoding="utf-8")
    entries = parse_bib(text)
    by_key: Dict[str, Set[str]] = {
        finding["key"]: {d["class"] for d in finding["defects"]} for finding in report.findings
    }
    worknote_res = [re.compile(p, re.I) for p in report.worknote_patterns]

    out: List[str] = []
    log: List[Dict[str, Any]] = []
    if entries:
        preamble = text[: entries[0]["raw_span"][0]].rstrip()
        if preamble:
            out.append(preamble)
    for e in entries:
        defects = by_key.get(e["key"], set())
        rendered, changed = _render_entry(e, report.resolved.get(e["key"]), defects, worknote_res)
        out.append(rendered)
        if changed:
            log.append({"key": e["key"], "changes": changed, "defects": sorted(defects)})

    new_text = "\n\n".join(out) + "\n"
    backup_path: Optional[Path] = None
    if in_place:
        backup_path = bib_path.with_name(bib_path.name + ".backup")
        shutil.copy2(bib_path, backup_path)
        dest = bib_path
    else:
        dest = bib_path.with_name(bib_path.stem + ".v2" + bib_path.suffix)
    dest.write_text(new_text, encoding="utf-8")

    changes_by_class: Dict[str, int] = {}
    for row in log:
        for c in row["changes"]:
            changes_by_class[c] = changes_by_class.get(c, 0) + 1
    deferred = sorted(k for k, classes in by_key.items() if classes & NEVER_AUTO_FIXED_CLASSES)

    return FixReport(
        bib_path=str(bib_path),
        output_path=str(dest),
        backup_path=str(backup_path) if backup_path else None,
        in_place=in_place,
        n_entries=len(entries),
        n_changed=len(log),
        changes_by_class=changes_by_class,
        entries=log,
        deferred=deferred,
    )
