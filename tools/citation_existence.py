"""Three-state citation-existence checker (DISCOVER deterministic gate helper, absorption wave 1).

Absorbs the ARS (academic-research-skills) three-state citation-verification idiom: every external
reference a worker cites is looked up against the live scholarly APIs and lands in exactly one of:

  verified     — the reference resolves (DOI resolves / arXiv id resolves / a title match is found)
  not_found    — every relevant source answered and none resolves the reference (confirmed missing)
  lookup_error — a source could not be reached; absence CANNOT be confirmed (offline-safe state)

plus ``skipped`` for refs this checker does not own (vault ``[[slug]]`` refs are resolved by the
existing citation-integrity-auditor structural gate; bare URLs are carried as-is).

Verdict discipline (conservative, offline-safe; C2, 2026-08-07 — three states; director-
tightened 2026-08-07 — a confirmed fabrication BLOCKs unconditionally, checked first):
  BLOCK       at least one reference is ``not_found`` — a confirmed-nonexistent citation is
              the fabrication signal this gate exists to catch, and grounding is never
              relaxed for it: it BLOCKs even in the same batch as an unrelated lookup_error,
              even when nothing else in the batch was ever verified.
  UNVERIFIED  (when not BLOCK) no refs were given, or nothing was genuinely verified and at
              least one lookup errored — no external existence check actually happened, so
              the run must not read as a clean PASS.
  PASS        otherwise; every ``lookup_error`` becomes a WARNING — a dead network must never
              false-BLOCK a run, and must never silently count as verified either.

The state for each ref is cached (sqlite, machine-side path supplied by the caller — typically
under ``runs/``; never the vault) keyed by the normalized ref, so re-checks are free and a run's
verdict is reproducible offline from its own cache. ``ts`` is always caller-supplied (the engine's
clock discipline) — this module never reads the wall clock.
"""
from __future__ import annotations

import hashlib
import re
import sqlite3
from difflib import SequenceMatcher
from pathlib import Path
from typing import Dict, List, Optional, Sequence

from research_agent_teams.tools.scholar_clients import (
    ScholarLookupError,
    Transport,
    lookup_arxiv,
    lookup_doi_crossref,
    lookup_doi_openalex,
    lookup_title_openalex,
    lookup_title_s2,
    normalize_arxiv_id,
    normalize_doi,
)

STATE_VERIFIED = "verified"
STATE_NOT_FOUND = "not_found"
STATE_LOOKUP_ERROR = "lookup_error"
STATE_SKIPPED = "skipped"

_SLUG_REF_RE = re.compile(r"^\[\[[a-z0-9]+(?:-[a-z0-9]+)*\]\]")
_URL_RE = re.compile(r"^https?://", re.IGNORECASE)
_LOCAL_SHA_REF_RE = re.compile(
    r"^(?P<path>.+)\+sha(?:256)?:(?P<digest>[0-9a-fA-F]{64})$",
    re.IGNORECASE,
)
_LOCAL_SHA_MARKER_RE = re.compile(r"\+sha(?:256)?:", re.IGNORECASE)
_TITLE_MATCH_RATIO = 0.92
_WORD_RE = re.compile(r"[a-z0-9]+")


def _norm(s: str) -> str:
    return " ".join(_WORD_RE.findall((s or "").lower()))


def classify_ref(ref: str) -> Dict[str, str]:
    """Parse a raw ref string into {"kind": doi|arxiv|slug|url|title, "value": normalized}."""
    r = (ref or "").strip()
    if _SLUG_REF_RE.match(r):
        return {"kind": "slug", "value": r}
    arxiv_doi = re.fullmatch(
        r"(?:doi:)?10\.48550/arxiv\.(\d{4}\.\d{4,5}(?:v\d+)?)", r,
        re.IGNORECASE,
    )
    if arxiv_doi:
        aid = normalize_arxiv_id(arxiv_doi.group(1))
        if aid:
            return {"kind": "arxiv", "value": aid}
    doi = normalize_doi(r.split("doi:")[-1] if r.lower().startswith("doi:") else r)
    if doi:
        return {"kind": "doi", "value": doi}
    aid = normalize_arxiv_id(r)
    if aid and (r.lower().startswith("arxiv") or re.fullmatch(r"\d{4}\.\d{4,5}(v\d+)?", r)):
        return {"kind": "arxiv", "value": aid}
    if _URL_RE.match(r):
        return {"kind": "url", "value": r}
    return {"kind": "title", "value": r}


def _within(path: Path, root: Path) -> bool:
    """Return whether *path* resolves inside *root* (symlinks included in the check)."""
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _check_local_reference(ref: str, local_roots: Sequence[Path]) -> Optional[Dict[str, str]]:
    """Verify a hash-bound local reference without ever sending it to scholarly APIs.

    The on-disk citation schema predates local references and restricts ``kind`` to five values;
    ``title`` is retained here for schema compatibility while ``detail`` explicitly records the
    local-file verification.  A local-looking reference is fail-closed: malformed syntax, an
    escaped path, a missing/non-file target, or a digest mismatch is ``not_found`` and therefore
    blocks the ordinary existence verdict.
    """
    raw = (ref or "").strip()
    if _URL_RE.match(raw):
        return None
    match = _LOCAL_SHA_REF_RE.fullmatch(raw)
    if match is None:
        if _LOCAL_SHA_MARKER_RE.search(raw):
            return {
                "ref": ref,
                "kind": "title",
                "state": STATE_NOT_FOUND,
                "detail": (
                    "malformed local hash-bound reference; expected "
                    "'<path>+sha:<64 hexadecimal characters>'"
                ),
            }
        return None

    roots = [Path(root).resolve() for root in local_roots]
    if not roots:
        return {
            "ref": ref,
            "kind": "title",
            "state": STATE_NOT_FOUND,
            "detail": "local hash-bound reference has no authorized run/workspace root",
        }

    raw_path = Path(match.group("path"))
    if raw_path.is_absolute():
        candidate = raw_path.resolve()
        candidates = [(candidate, root) for root in roots]
    else:
        first_part = raw_path.parts[0].casefold() if raw_path.parts else ""
        if first_part == "inbox":
            candidate_roots = roots[:1]       # explicitly run-relative
        elif first_part == "research_agent_teams":
            candidate_roots = roots[-1:]      # explicitly workspace-relative
        else:
            candidate_roots = roots
        candidates = [((root / raw_path).resolve(), root) for root in candidate_roots]

    authorized = [candidate for candidate, owning_root in candidates
                  if _within(candidate, owning_root)]
    if not authorized:
        return {
            "ref": ref,
            "kind": "title",
            "state": STATE_NOT_FOUND,
            "detail": "local path escapes the authorized run/workspace roots",
        }

    existing = [candidate for candidate in authorized if candidate.is_file()]
    if not existing:
        display = ", ".join(str(candidate) for candidate in authorized[:2])
        return {
            "ref": ref,
            "kind": "title",
            "state": STATE_NOT_FOUND,
            "detail": f"local evidence file does not exist (checked: {display})",
        }

    expected = match.group("digest").lower()
    mismatches = []
    for candidate in existing:
        actual = hashlib.sha256(candidate.read_bytes()).hexdigest()
        if actual == expected:
            return {
                "ref": ref,
                "kind": "title",
                "state": STATE_VERIFIED,
                "detail": f"local hash-bound file verified: {candidate}",
            }
        mismatches.append((candidate, actual))

    candidate, actual = mismatches[0]
    return {
        "ref": ref,
        "kind": "title",
        "state": STATE_NOT_FOUND,
        "detail": (
            f"local evidence hash mismatch: {candidate} "
            f"(expected {expected}, observed {actual})"
        ),
    }


# --------------------------------------------------------------------------- cache (sqlite, machine-side)

class ExistenceCache:
    """Tiny keyed cache: normalized ref -> (state, detail, checked_at). In-memory when path is None."""

    def __init__(self, path: Optional[str] = None):
        # Two-repo seam (fence-by-construction, matching fulltext_qa._fence_cache_dir): the
        # verification cache must never live inside the knowledge vault.
        if path and "phd-research-os" in str(Path(path).resolve()).replace("\\", "/").lower():
            raise ValueError(f"citation cache must never live in the vault (promote-gate-only): {path}")
        self._conn = sqlite3.connect(path if path else ":memory:")
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS lookups (ref TEXT PRIMARY KEY, state TEXT NOT NULL,"
            " detail TEXT NOT NULL, checked_at TEXT NOT NULL)")
        self._conn.commit()

    def get(self, ref: str) -> Optional[Dict[str, str]]:
        row = self._conn.execute(
            "SELECT state, detail, checked_at FROM lookups WHERE ref = ?", (ref,)).fetchone()
        return {"state": row[0], "detail": row[1], "checked_at": row[2]} if row else None

    def put(self, ref: str, state: str, detail: str, ts: str) -> None:
        # lookup_error is never cached as durable truth — a later run with network must re-check.
        if state == STATE_LOOKUP_ERROR:
            return
        self._conn.execute(
            "INSERT OR REPLACE INTO lookups (ref, state, detail, checked_at) VALUES (?, ?, ?, ?)",
            (ref, state, detail, ts))
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()


# --------------------------------------------------------------------------- single-ref check

def _check_title(title: str, transport: Optional[Transport]) -> Dict[str, str]:
    """Title existence: S2 first, OpenAlex fallback; verified iff a near-exact title match returns.

    Three-state discipline (offline-safe): a verified match short-circuits immediately. Absent a
    match, ``not_found`` may be returned ONLY when EVERY source actually answered — if ANY source
    errored (so absence could not be confirmed there), the result is ``lookup_error``. A single
    source being down must never produce a confirmed ``not_found`` (which would BLOCK the gate)."""
    errors = []
    for fn, name in ((lookup_title_s2, "s2"), (lookup_title_openalex, "openalex")):
        try:
            for cand in fn(title, limit=3, transport=transport):
                ratio = SequenceMatcher(None, _norm(title), _norm(cand.get("title", ""))).ratio()
                if ratio >= _TITLE_MATCH_RATIO:
                    return {"state": STATE_VERIFIED,
                            "detail": f"title match {ratio:.2f} via {name}: {cand.get('title', '')[:80]}"}
        except ScholarLookupError as e:
            errors.append(f"{name}: {e}")
    if errors:                                # ANY source failed -> absence is NOT confirmable
        return {"state": STATE_LOOKUP_ERROR,
                "detail": "title not matched and a source could not be reached "
                          f"(absence unconfirmable): {'; '.join(errors)[:280]}"}
    return {"state": STATE_NOT_FOUND,
            "detail": "no near-exact title match in any source (all sources answered)"}


def check_reference(ref: str, ts: str, transport: Optional[Transport] = None,
                    cache: Optional[ExistenceCache] = None,
                    local_roots: Optional[Sequence[Path]] = None) -> Dict[str, str]:
    """Check ONE reference; returns {"ref", "kind", "state", "detail"} (state per module docstring)."""
    local = _check_local_reference(ref, local_roots or ())
    if local is not None:
        # Never cache local checks: the file can be deleted or modified while retaining the same
        # path+digest ref, and every deterministic gate run must observe that fresh state.
        return local

    c = classify_ref(ref)
    if c["kind"] in ("slug", "url"):
        return {"ref": ref, "kind": c["kind"], "state": STATE_SKIPPED,
                "detail": "vault slug refs are owned by the citation-integrity-auditor gate"
                if c["kind"] == "slug" else "bare URL carried as-is (no metadata authority to check)"}

    cache_key = f"{c['kind']}:{c['value']}"
    if cache is not None:
        hit = cache.get(cache_key)
        if hit is not None:
            return {"ref": ref, "kind": c["kind"], "state": hit["state"],
                    "detail": f"(cached {hit['checked_at']}) {hit['detail']}"}

    try:
        if c["kind"] == "doi":
            rec = lookup_doi_crossref(c["value"], transport=transport)
            if rec:
                res = {"state": STATE_VERIFIED, "detail": f"DOI resolves via Crossref: {rec.get('title', '')[:80]}"}
            else:
                # Crossref 404 does NOT prove a non-Crossref DOI absent — DataCite-registered DOIs
                # (Zenodo / figshare datasets & software, common in AI citations) live in OpenAlex.
                # Confirm not_found only when OpenAlex ALSO answers absent; an OpenAlex outage ->
                # lookup_error (absence unconfirmable), never a false BLOCK.
                rec2 = lookup_doi_openalex(c["value"], transport=transport)
                res = ({"state": STATE_VERIFIED, "detail": f"DOI resolves via OpenAlex: {rec2.get('title', '')[:80]}"}
                       if rec2 else {"state": STATE_NOT_FOUND,
                                     "detail": "Crossref + OpenAlex both answered: DOI does not resolve"})
        elif c["kind"] == "arxiv":
            rec = lookup_arxiv(c["value"], transport=transport)
            res = ({"state": STATE_VERIFIED, "detail": f"arXiv id resolves: {rec.get('title', '')[:80]}"}
                   if rec else {"state": STATE_NOT_FOUND, "detail": "arXiv answered: id does not resolve"})
        else:  # title
            res = _check_title(c["value"], transport)
    except ScholarLookupError as e:
        res = {"state": STATE_LOOKUP_ERROR, "detail": str(e)[:300]}

    if cache is not None:
        cache.put(cache_key, res["state"], res["detail"], ts)
    return {"ref": ref, "kind": c["kind"], "state": res["state"], "detail": res["detail"]}


# --------------------------------------------------------------------------- verdict (allOf idiom)

def build_existence_verdict(refs: List[str], ts: str, transport: Optional[Transport] = None,
                            cache: Optional[ExistenceCache] = None,
                            local_roots: Optional[Sequence[Path]] = None) -> dict:
    """Check every ref; return the ``citation_existence_verdict`` payload.

    Three-state verdict (C2, 2026-08-07; director-tightened 2026-08-07) — checked in this
    order:
      BLOCK       iff any ref is confirmed ``not_found`` — checked FIRST and unconditionally.
                  A confirmed fabrication BLOCKs even in the same batch as an unrelated
                  lookup_error, even when n_verified==0 elsewhere in the batch: grounding is
                  never relaxed for a confirmed-missing citation.
      UNVERIFIED  iff (not BLOCK and) no refs were given, OR nothing was verified AND at
                  least one lookup errored (nothing genuinely checked out clean; reporting
                  that as PASS would claim a verification that never happened).
      PASS        otherwise.
    ``lookup_error`` alone (with at least one genuine ``verified`` ref, and no confirmed
    ``not_found``) still never blocks — a dead network on one source must not sink an
    otherwise-clean citation list. Deterministic: same refs + same transport answers -> same
    payload.
    """
    checked = [check_reference(r, ts, transport=transport, cache=cache,
                               local_roots=local_roots)
               for r in refs]
    n = {s: sum(1 for c in checked if c["state"] == s)
         for s in (STATE_VERIFIED, STATE_NOT_FOUND, STATE_LOOKUP_ERROR, STATE_SKIPPED)}
    violations = [f"{c['ref']}: verification failed — {c['detail']}"
                  for c in checked if c["state"] == STATE_NOT_FOUND]
    warnings = [f"{c['ref']}: could not check — {c['detail']}"
                for c in checked if c["state"] == STATE_LOOKUP_ERROR]
    if violations:
        verdict = "BLOCK"
    elif not checked or (n[STATE_VERIFIED] == 0 and n[STATE_LOOKUP_ERROR] > 0):
        verdict = "UNVERIFIED"
    else:
        verdict = "PASS"
    return {
        "checked": checked,
        "n_verified": n[STATE_VERIFIED],
        "n_not_found": n[STATE_NOT_FOUND],
        "n_lookup_error": n[STATE_LOOKUP_ERROR],
        "n_skipped": n[STATE_SKIPPED],
        "verdict": verdict,
        "violations": violations,
        "warnings": warnings,
    }
