"""Tests for staleness.py — deterministic staleness classification.

Key invariants:
  - A named successor => SUPERSEDED (regardless of age).
  - A 3-year-old source with no successor => STALE.
  - A source < 2 years old => CURRENT.
  - Unknown year => UNKNOWN.
"""
from __future__ import annotations

from research_agent_teams.tools.staleness import (
    age_years,
    build_report,
    classify_staleness,
)


# ---------------------------------------------------------------------------
# classify_staleness unit tests
# ---------------------------------------------------------------------------

def test_named_successor_is_superseded():
    """Any non-null successor_ref => SUPERSEDED, regardless of age."""
    status = classify_staleness(year=2020, successor_ref="github.com/new-repo", audit_year=2026)
    assert status == "SUPERSEDED"


def test_named_successor_even_if_recent():
    """Even a source published this year is SUPERSEDED if a successor is named."""
    status = classify_staleness(year=2026, successor_ref="arxiv:2026.9999", audit_year=2026)
    assert status == "SUPERSEDED"


def test_three_year_old_no_successor_is_stale():
    """A 3-year-old repo with no successor => STALE."""
    status = classify_staleness(year=2023, successor_ref=None, audit_year=2026)
    assert status == "STALE"


def test_exactly_three_year_old_is_stale():
    """The age threshold is strict: 2026-2023=3 years => STALE."""
    assert classify_staleness(year=2023, audit_year=2026) == "STALE"


def test_two_year_old_is_aging():
    """2 years old is AGING (at the boundary between CURRENT and STALE)."""
    assert classify_staleness(year=2024, audit_year=2026) == "AGING"


def test_one_year_old_is_current():
    """1 year old is CURRENT."""
    assert classify_staleness(year=2025, audit_year=2026) == "CURRENT"


def test_same_year_is_current():
    """Published this year is CURRENT."""
    assert classify_staleness(year=2026, audit_year=2026) == "CURRENT"


def test_unknown_year_is_unknown():
    """No year information => UNKNOWN."""
    assert classify_staleness(year=None) == "UNKNOWN"


def test_empty_string_successor_is_not_superseded():
    """An empty/whitespace-only successor_ref does NOT trigger SUPERSEDED."""
    status = classify_staleness(year=2020, successor_ref="", audit_year=2026)
    assert status == "STALE"


def test_whitespace_successor_not_superseded():
    status = classify_staleness(year=2020, successor_ref="   ", audit_year=2026)
    assert status == "STALE"


def test_very_old_source_is_stale():
    """A source from 10 years ago is STALE."""
    assert classify_staleness(year=2016, audit_year=2026) == "STALE"


# ---------------------------------------------------------------------------
# age_years helper
# ---------------------------------------------------------------------------

def test_age_years_computes_correctly():
    assert age_years(2024, audit_year=2026) == 2.0


def test_age_years_none_returns_none():
    assert age_years(None) is None


def test_age_years_current_is_zero():
    assert age_years(2026, audit_year=2026) == 0.0


# ---------------------------------------------------------------------------
# build_report integration tests
# ---------------------------------------------------------------------------

def test_build_report_superseded_has_successor_ref():
    """SUPERSEDED report must include the successor_ref field."""
    report = build_report(
        source_ref="github.com/old-tool",
        year=2022,
        successor_ref="github.com/new-tool",
        audit_year=2026,
    )
    assert report["status"] == "SUPERSEDED"
    assert report["successor_ref"] == "github.com/new-tool"
    assert report["source_ref"] == "github.com/old-tool"


def test_build_report_stale_has_null_successor():
    """STALE report has successor_ref=None."""
    report = build_report(
        source_ref="some-old-paper",
        year=2020,
        successor_ref=None,
        audit_year=2026,
    )
    assert report["status"] == "STALE"
    assert report["successor_ref"] is None


def test_build_report_current():
    report = build_report("recent-paper", year=2025, audit_year=2026)
    assert report["status"] == "CURRENT"
    assert report["age_years"] == 1.0


def test_build_report_unknown_year():
    report = build_report("mystery-paper", year=None, audit_year=2026)
    assert report["status"] == "UNKNOWN"
    assert report["age_years"] is None


def test_build_report_aging():
    report = build_report("two-year-old", year=2024, audit_year=2026)
    assert report["status"] == "AGING"
    assert report["age_years"] == 2.0


def test_build_report_contains_all_required_fields():
    """build_report returns all fields required by staleness_report.schema.json."""
    report = build_report("ref-1", year=2023, audit_year=2026)
    required = {"source_ref", "status", "age_years", "successor_ref", "staleness_rationale", "audit_year"}
    assert required.issubset(set(report.keys()))


def test_build_report_rationale_is_nonempty():
    """staleness_rationale must be a non-empty string."""
    report = build_report("ref-x", year=2021, audit_year=2026)
    assert isinstance(report["staleness_rationale"], str)
    assert len(report["staleness_rationale"]) > 0


# ---------------------------------------------------------------------------
# The "3-year-old repo with a named successor => SUPERSEDED" contract case
# ---------------------------------------------------------------------------

def test_three_year_old_repo_with_successor_is_superseded_not_stale():
    """The M2 contract golden test: a 3-yr-old repo with a named successor => SUPERSEDED.

    Without the successor, it would be STALE.  The successor_ref takes priority.
    """
    # Without successor: STALE
    no_successor = classify_staleness(year=2023, successor_ref=None, audit_year=2026)
    assert no_successor == "STALE"

    # With successor: SUPERSEDED (not STALE)
    with_successor = classify_staleness(
        year=2023,
        successor_ref="github.com/replacement-repo",
        audit_year=2026,
    )
    assert with_successor == "SUPERSEDED"

    # build_report confirms the same
    report = build_report(
        source_ref="github.com/old-segmentation-tool",
        year=2023,
        successor_ref="github.com/replacement-repo",
        audit_year=2026,
    )
    assert report["status"] == "SUPERSEDED"
    assert report["successor_ref"] == "github.com/replacement-repo"
