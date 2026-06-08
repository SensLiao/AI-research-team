"""Deterministic core of the literature-ingest agent.

Given a dict of paper facts gathered by the LLM agent, assembles a paper_note payload that
is schema-valid against paper_note.schema.json. The agent gathers facts from the paper; this
function — not the LLM — decides the shape of the note, so the payload is mechanical, not a vibe.

Required facts: title, source_ref, summary, claims (list).
Optional facts (with defaults): year (None), venue (None), methods ([]), datasets ([]), metrics ([]).

Fail-fast at the boundary: raises ValueError on missing or empty required fields before any
downstream schema validation can run.
"""
from __future__ import annotations

from typing import List, Optional


def ingest_paper(facts: dict) -> dict:
    """Assemble and return a paper_note payload from raw paper facts.

    Args:
        facts: Flat dict of paper facts collected by the LLM agent.

    Returns:
        A dict that is schema-valid against paper_note.schema.json.

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

    return {
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
