"""Deterministic core of the literature-ingest agent.

Given a dict of paper facts gathered by the LLM agent, assembles a paper_note payload that
is schema-valid against paper_note.schema.json. The agent gathers facts from the paper; this
function — not the LLM — decides the shape of the note, so the payload is mechanical, not a vibe.

Required facts: title, source_ref, summary, claims (list).
Optional facts (with defaults): year (None), venue (None), methods ([]), datasets ([]), metrics ([]).

Optional READ-ONLY vault dedup (L7): pass `vault_root` to cross-check this paper against the existing
`02-wiki/papers/**/*.md` pages. On a title-normalized or source-ref match the payload gains
`vault_slug` + `possible_duplicate=True` so the director can dedup before promoting. The vault is only
READ — this never writes it. Without `vault_root` the output is byte-identical to the pre-L7 behaviour
(the two new keys are simply absent).

Fail-fast at the boundary: raises ValueError on missing or empty required fields before any
downstream schema validation can run.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import List, Optional

# Frontmatter `title: "..."` (quotes optional). Only the first match (the page's own title) is used.
_FM_TITLE = re.compile(r"(?im)^\s*title\s*:\s*[\"']?(.+?)[\"']?\s*$")
# Significant alphanumeric identifier runs >= 4 chars (e.g. arxiv "1706.03762" -> "1706","03762";
# a doi tail; "2404.03010"). Used to match a source_ref against an existing page's body/frontmatter.
_IDENT = re.compile(r"[a-z0-9]{4,}")
_PUNCT = re.compile(r"[^a-z0-9\s]+")
_WS = re.compile(r"\s+")


def _normalize_title(title: str) -> str:
    """Lowercase, drop punctuation, collapse whitespace — so 'LoRA: Low-Rank...' and
    'lora low rank...' compare equal. Pure / deterministic."""
    t = _PUNCT.sub(" ", (title or "").lower())
    return _WS.sub(" ", t).strip()


def _source_ref_idents(source_ref: str) -> set:
    """The significant identifier tokens of a source ref (e.g. 'arxiv:1706.03762' -> {'arxiv','1706','03762'}).
    A page matches the ref when it contains EVERY numeric-bearing identifier (so '1706.03762' must fully
    appear, not just the year). Empty set => no usable identifier => no source-ref match attempted."""
    return {m.group(0) for m in _IDENT.finditer((source_ref or "").lower())}


def ingest_paper(facts: dict, vault_root: Optional[str] = None) -> dict:
    """Assemble and return a paper_note payload from raw paper facts.

    Args:
        facts: Flat dict of paper facts collected by the LLM agent.
        vault_root: Optional path to the PhD-Research-OS vault. When given, the existing
            02-wiki/papers/**/*.md pages are READ (never written) to flag a possible duplicate.

    Returns:
        A dict that is schema-valid against paper_note.schema.json. With a vault match it also carries
        `vault_slug` + `possible_duplicate=True`; otherwise those keys are absent (byte-identical to the
        pre-dedup payload).

    Raises:
        ValueError: If any required field is missing or empty, or if claims is absent.
    """
    _validate_required(facts)

    title: str = facts["title"]
    source_ref: str = facts["source_ref"]
    summary: str = facts["summary"]
    claims: List[str] = facts["claims"]

    year: Optional[int] = facts.get("year", None)
    venue: Optional[str] = facts.get("venue", None)
    methods: List[str] = facts.get("methods", [])
    datasets: List[str] = facts.get("datasets", [])
    metrics: List[str] = facts.get("metrics", [])

    payload = {
        "title": title,
        "source_ref": source_ref,
        "year": year,
        "venue": venue,
        "summary": summary,
        "claims": claims,
        "methods": methods,
        "datasets": datasets,
        "metrics": metrics,
    }

    if vault_root is not None:
        match = _find_vault_duplicate(title, source_ref, vault_root)
        if match is not None:
            payload["vault_slug"] = match
            payload["possible_duplicate"] = True

    return payload


def _find_vault_duplicate(title: str, source_ref: str, vault_root: str) -> Optional[str]:
    """Scan 02-wiki/papers/**/*.md (READ-ONLY) for a page whose title (normalized) equals this paper's,
    or whose body/frontmatter contains every significant identifier of `source_ref`. Returns the matching
    page's slug (filename stem), or None. Deterministic: candidates are sorted, first match wins."""
    papers_dir = Path(vault_root) / "02-wiki" / "papers"
    if not papers_dir.is_dir():
        return None

    want_title = _normalize_title(title)
    want_idents = _source_ref_idents(source_ref)

    for page in sorted(papers_dir.rglob("*.md")):
        try:
            text = page.read_text(encoding="utf-8")          # READ ONLY — never written
        except OSError:
            continue
        # Title match (primary): the page's own frontmatter title, normalized.
        m = _FM_TITLE.search(text)
        if m and _normalize_title(m.group(1)) == want_title and want_title:
            return page.stem
        # Source-ref match: every significant identifier of the ref is present in the page text — AND the
        # ref must carry at least one LONG digit-bearing token (>=5 chars, e.g. an arxiv id / doi tail), so
        # a ref whose only id is a short number (a stray '1000' from a doi prefix) never matches loosely.
        if want_idents and _has_strong_identifier(want_idents):
            page_idents = {mm.group(0) for mm in _IDENT.finditer(text.lower())}
            if want_idents <= page_idents:
                return page.stem
    return None


def _has_strong_identifier(idents: set) -> bool:
    """True if the ref carries a discriminating identifier — a token >=5 chars containing a digit
    (arxiv id / doi tail / long accession). Guards source-ref matching from firing on weak short numbers."""
    return any(len(t) >= 5 and any(c.isdigit() for c in t) for t in idents)


def _validate_required(facts: dict) -> None:
    """Raise ValueError for any missing or empty required field."""
    for field in ("title", "source_ref", "summary"):
        if field not in facts:
            raise ValueError(f"ingest_paper: required field '{field}' is missing from facts")
        value = facts[field]
        if not isinstance(value, str) or not value.strip():
            raise ValueError(
                f"ingest_paper: required field '{field}' must be a non-empty string, got {value!r}"
            )

    if "claims" not in facts:
        raise ValueError("ingest_paper: required field 'claims' is missing from facts")
