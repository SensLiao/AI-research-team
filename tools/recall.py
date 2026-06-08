"""Recall core — the M⇐D seam, read side (machine reads System D BY REFERENCE).

The machine never inlines System-D content into its run-store (blueprint §5). `/recall` resolves a
topic to [[slug]] + content-sha + section citations and emits a `recall_note`. The note carries
POINTERS, never the DB page body — so the run-store stays free of copied knowledge, and every cited
fact is traceable back to a live, hashed DB page (evidence-contract: never invent a slug).

Pure where it can be (build_recall_note); I/O isolated in recall(). No network, no LLM.
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import List, Optional

_SLUG_IN_INDEX = re.compile(r"\[\[([a-z0-9]+(?:-[a-z0-9]+)*)")
_HEADING = re.compile(r"^#{1,3}\s+(.*\S)", re.MULTILINE)


def _sha256_text(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def _index_slugs(vault_root: Path) -> List[str]:
    idx = vault_root / "00-system" / "index.md"
    if not idx.exists():
        return []
    return sorted(set(_SLUG_IN_INDEX.findall(idx.read_text(encoding="utf-8"))))


def _resolve_page(vault_root: Path, slug: str) -> Optional[Path]:
    hits = list((vault_root / "02-wiki").glob(f"**/{slug}.md"))
    return hits[0] if hits else None


def _tokens(query: str) -> List[str]:
    return [t for t in re.split(r"[^a-z0-9]+", (query or "").lower()) if len(t) >= 3]


# ---------- pure ----------

def build_recall_note(query: str, citations: List[dict], *,
                      closest: Optional[dict] = None) -> dict:
    """Assemble a recall_note. citations is a list of {slug, sha256, section?, supports?} — pointers
    only, never DB body. vault_silent is derived from whether any citation was found."""
    silent = len(citations) == 0
    confidence = "high" if len(citations) >= 2 else ("medium" if citations else "low")
    note = {
        "query": query,
        "citations": citations,
        "confidence": confidence,
        "vault_silent": silent,
    }
    if silent and closest is not None:
        note["closest"] = closest
    return note


# ---------- I/O ----------

def recall(query: str, *, vault_root) -> dict:
    """Resolve `query` against System D BY REFERENCE and return a recall_note. Matches index slugs
    by shared token; for each match records slug + content-sha + first heading. The DB page body is
    hashed and pointed at, NEVER copied into the returned note."""
    vault_root = Path(vault_root)
    toks = _tokens(query)
    citations: List[dict] = []
    closest: Optional[dict] = None

    for slug in _index_slugs(vault_root):
        slug_toks = set(slug.split("-"))
        shared = [t for t in toks if t in slug_toks]   # whole-token match only (no substring false-positives)
        if not shared:
            if closest is None:
                closest = {"slug": slug, "differs": "no shared topic token with the query"}
            continue
        page = _resolve_page(vault_root, slug)
        if page is None:
            continue
        text = page.read_text(encoding="utf-8")
        heading = _HEADING.search(text)
        citations.append({
            "slug": slug,
            "sha256": _sha256_text(text),                 # hash of the page (by reference)
            "section": heading.group(1) if heading else "",
            "supports": f"matches query token(s): {', '.join(shared)}",
        })

    return build_recall_note(query, citations, closest=closest if not citations else None)
