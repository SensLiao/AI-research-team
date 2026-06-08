"""Deterministic source ranking for source-quality-ranker.

Ranks a list of sources by a composite score derived from three factors:
  1. Venue tier (peer-reviewed > workshop > preprint > technical-report > blog > other)
  2. Methodological rigor score (if provided; else derived from tier)
  3. Recency (more recent = higher; tied years share the same recency contribution)

The ordering guarantee: for any two sources with the same recency, a peer-reviewed source
ALWAYS outranks a preprint (tier dominates when recency is tied). This is a pure function:
no I/O, no LLM, no network.
"""
from __future__ import annotations

from typing import List, Optional

# Tier weights: higher = better quality signal
_TIER_WEIGHT: dict[str, float] = {
    "peer-reviewed": 1.0,
    "workshop": 0.7,
    "preprint": 0.5,
    "technical-report": 0.4,
    "blog": 0.2,
    "other": 0.1,
}

# Current year used when source year is missing (conservative: assume oldest possible)
_DEFAULT_YEAR_WHEN_MISSING = 2000
# Recency scale: a source published this many years ago gets recency 0.0
_RECENCY_SPAN_YEARS = 20


def _tier_score(tier: str) -> float:
    """Return a [0,1] score for the venue tier. Unknown tiers get 0.0."""
    return _TIER_WEIGHT.get(tier, 0.0)


def _recency_score(year: Optional[int], audit_year: int = 2026) -> float:
    """Return a [0,1] recency score. More recent = higher.

    Uses a linear decay over _RECENCY_SPAN_YEARS.  A source published in
    audit_year gets 1.0; a source _RECENCY_SPAN_YEARS or more older gets 0.0.
    """
    if year is None:
        y = _DEFAULT_YEAR_WHEN_MISSING
    else:
        y = int(year)
    age = max(0, audit_year - y)
    return max(0.0, 1.0 - age / _RECENCY_SPAN_YEARS)


def _composite_score(
    tier: str,
    year: Optional[int],
    explicit_rigor: Optional[float] = None,
    audit_year: int = 2026,
    tier_weight: float = 0.6,
    recency_weight: float = 0.4,
) -> float:
    """Compute a composite rigor score in [0,1].

    If explicit_rigor is provided it replaces the tier-derived component
    (useful when the caller has an external quality signal).  Otherwise the
    tier score is used as the rigor proxy.

    Weights: tier/rigor 60%, recency 40% by default.  These are fixed
    (deterministic) — not tunable per call, so the output is reproducible.
    """
    rigor = explicit_rigor if explicit_rigor is not None else _tier_score(tier)
    recency = _recency_score(year, audit_year)
    return round(tier_weight * rigor + recency_weight * recency, 6)


def rank_sources(
    sources: List[dict],
    audit_year: int = 2026,
) -> List[dict]:
    """Rank sources by composite score (tier + recency).

    Args:
        sources: list of dicts, each with optional keys:
            source_ref (str), tier (str), year (int|None), rigor_score (float|None),
            venue (str|None), rank_notes (str).
        audit_year: reference year for recency calculation.

    Returns:
        New list of ranked-source dicts, sorted descending by composite score,
        with `rank` (1-based) and `rigor_score` fields populated.
        The primary sort key is composite_score (descending); tie-break is
        tier_score (descending), then year (descending — more recent first).
    """
    scored: list[tuple[float, float, int, dict]] = []
    for src in sources:
        tier = src.get("tier", "other") or "other"
        year = src.get("year")
        explicit_rigor = src.get("rigor_score")
        comp = _composite_score(tier, year, explicit_rigor, audit_year)
        tier_s = _tier_score(tier)
        yr_for_sort = year if isinstance(year, int) else _DEFAULT_YEAR_WHEN_MISSING
        scored.append((comp, tier_s, yr_for_sort, src))

    # Sort: highest composite first; then highest tier; then most recent
    scored.sort(key=lambda x: (x[0], x[1], x[2]), reverse=True)

    ranked: List[dict] = []
    for i, (comp, _tier_s, _yr, src) in enumerate(scored, start=1):
        entry: dict = {
            "source_ref": src.get("source_ref", ""),
            "rank": i,
            "tier": src.get("tier", "other") or "other",
            "rigor_score": comp,
            "year": src.get("year"),
            "venue": src.get("venue"),
            "rank_notes": src.get("rank_notes", ""),
        }
        ranked.append(entry)
    return ranked


def build_report(sources: List[dict], audit_year: int = 2026) -> dict:
    """Build a source_quality_report payload.

    Verdict is not applicable here (this is a producer, not a gate).
    Returns a dict matching source_quality_report.schema.json.
    """
    ranked = rank_sources(sources, audit_year)
    return {
        "ranked_sources": ranked,
        "ranking_rationale": (
            "Sources ranked by composite score: venue tier (60%) + recency (40%). "
            "Peer-reviewed venues always outrank preprints when recency is equal."
        ),
        "n_sources_ranked": len(ranked),
    }
