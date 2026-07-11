"""Deterministic core of the lit-scout (DISCOVER stage, producer).

Given a query string and a list of source dicts (caller-supplied, never fabricated),
assemble the evidence_table payload that exits the DISCOVER stage.  The LLM agent
gathers sources from scholarly search + snowball; this module structures them into
the validated payload — it decides nothing about the sources themselves.

Payload contract:  evidence_table.schema.json (additionalProperties: false)
  {
    "query":             str,
    "sources":           list[source_dict],   # passed through unchanged
    "saturation_reached": bool,
    "n_sources":         int,
  }

Each source_dict must already carry the fields required by the schema
(id, kind, ref); optional fields (title, year, claim_support, notes) are
forwarded if present.  Fabrication of sources is the caller's responsibility
to avoid — this layer never invents entries.
"""
from __future__ import annotations

from typing import List


def build_evidence_table(
    query: str,
    sources: List[dict],
    saturation_reached: bool = False,
) -> dict:
    """Return an evidence_table payload ready for schema validation.

    Parameters
    ----------
    query:
        The research question or search string that drove the gathering.
    sources:
        Caller-supplied list of source dicts.  Each dict is passed through
        unchanged; the caller must ensure required fields (id, kind, ref).
        This function never fabricates or modifies source entries.
    saturation_reached:
        True when snowball search stopped surfacing new relevant sources.

    Returns
    -------
    dict matching evidence_table.schema.json.
    """
    return {
        "query": str(query),
        "sources": list(sources),
        "saturation_reached": bool(saturation_reached),
        "n_sources": len(sources),
    }


def count_strong(sources: List[dict]) -> int:
    """Return the number of sources whose claim_support is 'strong'."""
    return sum(1 for s in sources if s.get("claim_support") == "strong")
