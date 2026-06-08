"""Tests for rank_sources.py — deterministic source ordering.

Key invariant: a peer-reviewed source ALWAYS ranks above a preprint when recency is equal.
"""
from __future__ import annotations

from research_agent_teams.tools.rank_sources import (
    _composite_score,
    _recency_score,
    _tier_score,
    build_report,
    rank_sources,
)


# ---------------------------------------------------------------------------
# Unit tests for sub-functions
# ---------------------------------------------------------------------------

def test_peer_reviewed_tier_score_is_max():
    assert _tier_score("peer-reviewed") == 1.0


def test_preprint_tier_score_less_than_peer_reviewed():
    assert _tier_score("preprint") < _tier_score("peer-reviewed")


def test_blog_tier_score_is_low():
    assert _tier_score("blog") < _tier_score("preprint")


def test_unknown_tier_gets_zero():
    assert _tier_score("unknown-venue-type") == 0.0


def test_recency_current_year_gets_max():
    score = _recency_score(2026, audit_year=2026)
    assert score == 1.0


def test_recency_very_old_gets_zero():
    # 2006 is 20 years before 2026 => recency_span = 0.0
    score = _recency_score(2006, audit_year=2026)
    assert score == 0.0


def test_recency_no_year_uses_conservative_default():
    # No year defaults to _DEFAULT_YEAR_WHEN_MISSING = 2000
    score_none = _recency_score(None, audit_year=2026)
    assert score_none == 0.0


def test_composite_score_bounded():
    for tier in ["peer-reviewed", "preprint", "blog", "other"]:
        for year in [2020, 2024, 2026, None]:
            s = _composite_score(tier, year, audit_year=2026)
            assert 0.0 <= s <= 1.0, f"Score out of [0,1]: tier={tier}, year={year}, score={s}"


# ---------------------------------------------------------------------------
# Core invariant: peer-reviewed ranks above preprint at equal recency
# ---------------------------------------------------------------------------

def test_peer_reviewed_ranks_above_preprint_same_year():
    """Primary guarantee: for same year, peer-reviewed > preprint in composite score."""
    peer_score = _composite_score("peer-reviewed", 2024, audit_year=2026)
    pre_score = _composite_score("preprint", 2024, audit_year=2026)
    assert peer_score > pre_score, (
        f"peer-reviewed ({peer_score}) must outrank preprint ({pre_score}) at equal recency"
    )


def test_rank_sources_peer_above_preprint():
    """rank_sources() places peer-reviewed above preprint when years are equal."""
    sources = [
        {"source_ref": "arxiv:2024.0001", "tier": "preprint", "year": 2024},
        {"source_ref": "cvpr:2024.0002", "tier": "peer-reviewed", "year": 2024},
    ]
    ranked = rank_sources(sources, audit_year=2026)
    assert ranked[0]["source_ref"] == "cvpr:2024.0002"
    assert ranked[1]["source_ref"] == "arxiv:2024.0001"


def test_rank_sources_recent_preprint_vs_old_peer_reviewed():
    """Tier (60%) + recency (40%) composite: peer-reviewed 2010 vs preprint 2025.

    Both score 0.68 by composite: peer-reviewed has higher tier (1.0*0.6=0.60)
    but lower recency (age=16yr, 0.2*0.4=0.08), total=0.68.
    Preprint has lower tier (0.5*0.6=0.30) but higher recency (age=1yr, 0.95*0.4=0.38),
    total=0.68.  Tie-break: tier score favours peer-reviewed.
    Contract guarantee: peer-reviewed is not penalised unfairly on ties.
    """
    sources = [
        {"source_ref": "journal:2010.x", "tier": "peer-reviewed", "year": 2010},
        {"source_ref": "arxiv:2025.y", "tier": "preprint", "year": 2025},
    ]
    ranked = rank_sources(sources, audit_year=2026)
    # Both have composite 0.68; peer-reviewed wins the tie by tier score
    assert len(ranked) == 2
    refs = [r["source_ref"] for r in ranked]
    assert "journal:2010.x" in refs and "arxiv:2025.y" in refs
    # Peer-reviewed wins tie (or scores higher): confirm rank 1 is peer-reviewed
    assert ranked[0]["source_ref"] == "journal:2010.x"
    # An extremely recent peer-reviewed paper comfortably beats a 2025 preprint:
    sources2 = [
        {"source_ref": "journal:2025.z", "tier": "peer-reviewed", "year": 2025},
        {"source_ref": "arxiv:2025.y", "tier": "preprint", "year": 2025},
    ]
    ranked2 = rank_sources(sources2, audit_year=2026)
    assert ranked2[0]["source_ref"] == "journal:2025.z"


def test_rank_sources_assigns_sequential_ranks():
    """rank field is 1-based and sequential."""
    sources = [
        {"source_ref": "r1", "tier": "preprint", "year": 2023},
        {"source_ref": "r2", "tier": "peer-reviewed", "year": 2023},
        {"source_ref": "r3", "tier": "blog", "year": 2022},
    ]
    ranked = rank_sources(sources, audit_year=2026)
    ranks = [r["rank"] for r in ranked]
    assert ranks == [1, 2, 3]


def test_rank_sources_all_fields_present():
    """Each ranked entry must contain source_ref, rank, tier, rigor_score, year, venue."""
    sources = [
        {"source_ref": "s1", "tier": "peer-reviewed", "year": 2024, "venue": "NeurIPS 2024"}
    ]
    ranked = rank_sources(sources, audit_year=2026)
    assert len(ranked) == 1
    r = ranked[0]
    assert r["source_ref"] == "s1"
    assert r["rank"] == 1
    assert r["tier"] == "peer-reviewed"
    assert 0.0 <= r["rigor_score"] <= 1.0
    assert r["year"] == 2024
    assert r["venue"] == "NeurIPS 2024"


def test_rank_sources_empty_list():
    """Empty input returns empty output."""
    ranked = rank_sources([], audit_year=2026)
    assert ranked == []


def test_rank_sources_missing_tier_defaults_to_other():
    """Sources without a tier key are treated as 'other' (lowest tier)."""
    sources = [
        {"source_ref": "no-tier"},
        {"source_ref": "peer", "tier": "peer-reviewed", "year": 2024},
    ]
    ranked = rank_sources(sources, audit_year=2026)
    # peer-reviewed should be first
    assert ranked[0]["source_ref"] == "peer"
    assert ranked[1]["tier"] == "other"


# ---------------------------------------------------------------------------
# build_report integration
# ---------------------------------------------------------------------------

def test_build_report_structure():
    """build_report returns valid source_quality_report shape."""
    sources = [
        {"source_ref": "r1", "tier": "peer-reviewed", "year": 2023},
        {"source_ref": "r2", "tier": "preprint", "year": 2024},
    ]
    report = build_report(sources, audit_year=2026)
    assert "ranked_sources" in report
    assert "ranking_rationale" in report
    assert report["n_sources_ranked"] == 2
    assert len(report["ranked_sources"]) == 2
    # Peer-reviewed (2023) vs preprint (2024): 2024 preprint may beat 2023 peer-reviewed
    # The key guarantee is both are present and ranked
    ranks = {r["source_ref"]: r["rank"] for r in report["ranked_sources"]}
    assert "r1" in ranks and "r2" in ranks


def test_build_report_peer_reviewed_same_year_ranked_first():
    """build_report: peer-reviewed at same year is rank 1."""
    sources = [
        {"source_ref": "pre", "tier": "preprint", "year": 2025},
        {"source_ref": "peer", "tier": "peer-reviewed", "year": 2025},
    ]
    report = build_report(sources, audit_year=2026)
    assert report["ranked_sources"][0]["source_ref"] == "peer"
    assert report["ranked_sources"][0]["rank"] == 1
