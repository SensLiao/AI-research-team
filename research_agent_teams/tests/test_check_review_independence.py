"""Tests for check_review_independence — VERIFY panel independence gate.

Every test: clean input → no violations; crafted-bad input → violations.
"""
from __future__ import annotations

from research_agent_teams.tools.check_review_independence import (
    build_report,
    check_review_independence,
)


def _config(lenses: list) -> dict:
    return {
        "run_ref": "run-001",
        "lenses": lenses,
        "synthesis_mandate": "Synthesize findings.",
    }


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------

def test_clean_config_passes() -> None:
    """Two unique lenses with non-empty anchors → no violations."""
    config = _config([
        {"lens": "methodology", "anchor": "statistical design and variable control", "reviewer_agent": "methodology-reviewer"},
        {"lens": "domain", "anchor": "metric validity per cv-medical-segmentation profile", "reviewer_agent": "domain-reviewer"},
    ])
    result = build_report(config)
    assert result["valid"] is True
    assert result["violations"] == []


def test_single_lens_is_invalid() -> None:
    """A config with a single lens is INVALID — independence requires ≥2 distinct lenses.

    Updated from the original 'passes' assertion (which encoded the pre-L1-fix behavior).
    A single-lens panel has no independent second perspective; the gate must reject it.
    """
    config = _config([
        {"lens": "methodology", "anchor": "statistical design", "reviewer_agent": "methodology-reviewer"},
    ])
    result = build_report(config)
    assert result["valid"] is False
    assert len(result["violations"]) >= 1


def test_empty_lenses_is_invalid() -> None:
    """An empty lenses list is INVALID — independence requires ≥2 distinct lenses.

    Updated from the original 'passes' assertion (which encoded the pre-L1-fix behavior).
    Zero lenses means no review has been configured; the gate must reject it.
    """
    config = _config([])
    violations = check_review_independence(config)
    assert len(violations) >= 1
    result = build_report(config)
    assert result["valid"] is False


# ---------------------------------------------------------------------------
# Duplicate lens detection
# ---------------------------------------------------------------------------

def test_duplicate_lens_methodology_blocked() -> None:
    """Two 'methodology' lenses → violation for duplicate."""
    config = _config([
        {"lens": "methodology", "anchor": "variable control", "reviewer_agent": "methodology-reviewer"},
        {"lens": "methodology", "anchor": "statistical power", "reviewer_agent": "second-methodology-reviewer"},
    ])
    violations = check_review_independence(config)
    assert len(violations) >= 1
    assert any("duplicate" in v.lower() and "methodology" in v for v in violations)


def test_duplicate_lens_domain_blocked() -> None:
    """Two 'domain' lenses → violation for duplicate."""
    config = _config([
        {"lens": "domain", "anchor": "metric validity", "reviewer_agent": "domain-reviewer-1"},
        {"lens": "domain", "anchor": "invariant checks", "reviewer_agent": "domain-reviewer-2"},
    ])
    violations = check_review_independence(config)
    assert any("duplicate" in v.lower() and "domain" in v for v in violations)


def test_duplicate_lens_build_report_invalid() -> None:
    """build_report marks valid=False and reports violations when duplicate lens."""
    config = _config([
        {"lens": "methodology", "anchor": "eval framing", "reviewer_agent": "r1"},
        {"lens": "methodology", "anchor": "variable control", "reviewer_agent": "r2"},
        {"lens": "domain", "anchor": "domain check", "reviewer_agent": "r3"},
    ])
    result = build_report(config)
    assert result["valid"] is False
    assert len(result["violations"]) >= 1


# ---------------------------------------------------------------------------
# Empty anchor detection
# ---------------------------------------------------------------------------

def test_empty_anchor_blocked() -> None:
    """A lens entry with an empty anchor string → violation."""
    config = _config([
        {"lens": "methodology", "anchor": "", "reviewer_agent": "methodology-reviewer"},
        {"lens": "domain", "anchor": "metric validity", "reviewer_agent": "domain-reviewer"},
    ])
    violations = check_review_independence(config)
    assert any("empty" in v.lower() and "methodology" in v for v in violations)


def test_whitespace_only_anchor_blocked() -> None:
    """A lens entry with a whitespace-only anchor → violation."""
    config = _config([
        {"lens": "methodology", "anchor": "   ", "reviewer_agent": "methodology-reviewer"},
    ])
    violations = check_review_independence(config)
    assert len(violations) >= 1
    assert any("empty" in v.lower() or "anchor" in v.lower() for v in violations)


def test_missing_anchor_key_blocked() -> None:
    """A lens entry with no anchor key at all → violation."""
    config = _config([
        {"lens": "methodology", "reviewer_agent": "methodology-reviewer"},
        {"lens": "domain", "anchor": "metric validity", "reviewer_agent": "domain-reviewer"},
    ])
    violations = check_review_independence(config)
    assert any("anchor" in v.lower() for v in violations)


# ---------------------------------------------------------------------------
# Compound failures
# ---------------------------------------------------------------------------

def test_duplicate_lens_and_empty_anchor_both_flagged() -> None:
    """Two methodology lenses, one with empty anchor → both violations reported."""
    config = _config([
        {"lens": "methodology", "anchor": "", "reviewer_agent": "r1"},
        {"lens": "methodology", "anchor": "statistical power", "reviewer_agent": "r2"},
        {"lens": "domain", "anchor": "domain invariants", "reviewer_agent": "r3"},
    ])
    violations = check_review_independence(config)
    # Should have at least: one duplicate + one empty anchor
    assert len(violations) >= 2
    result = build_report(config)
    assert result["valid"] is False


# ---------------------------------------------------------------------------
# L1 regression: fewer than 2 distinct lenses
# ---------------------------------------------------------------------------

def test_l1_single_lens_panel_is_violation() -> None:
    """L1 regression: only 1 distinct lens → MUST be a violation.

    Previously a single-lens panel passed the independence check because the checker
    only looked for duplicates and empty anchors.  With 1 lens there is no duplicate
    (the second lens is simply absent) so the gate was silent.
    """
    config = _config([
        {"lens": "methodology", "anchor": "statistical design", "reviewer_agent": "r1"},
    ])
    violations = check_review_independence(config)
    assert len(violations) >= 1, (
        "L1 regression FAILED: single-lens panel passed independence check; "
        "independence requires ≥2 distinct lenses"
    )
    assert any("independence" in v.lower() or "2" in v or "lenses" in v.lower() for v in violations)
    result = build_report(config)
    assert result["valid"] is False


def test_l1_zero_lens_panel_is_violation() -> None:
    """L1 regression: empty lenses list → MUST be a violation (0 < 2 distinct lenses)."""
    config = _config([])
    violations = check_review_independence(config)
    assert len(violations) >= 1, (
        "L1 regression FAILED: zero-lens panel passed independence check"
    )
    result = build_report(config)
    assert result["valid"] is False


def test_l1_two_lenses_passes_independence_count() -> None:
    """L1 regression (happy): 2 distinct lenses with non-empty, distinct anchors → valid."""
    config = _config([
        {"lens": "methodology", "anchor": "statistical design and variable control", "reviewer_agent": "r1"},
        {"lens": "domain", "anchor": "metric validity per cv-medical profile", "reviewer_agent": "r2"},
    ])
    result = build_report(config)
    assert result["valid"] is True
    assert result["violations"] == []


# ---------------------------------------------------------------------------
# L1 regression: byte-identical anchor text
# ---------------------------------------------------------------------------

def test_l1_identical_anchor_text_is_violation() -> None:
    """L1 regression: two lenses with byte-identical anchor text → MUST be a violation.

    Identical anchors mean both reviewers are scoped to the exact same passage;
    independence is lost even if the lens names differ.
    """
    config = _config([
        {"lens": "methodology", "anchor": "section 3.2 experimental setup", "reviewer_agent": "r1"},
        {"lens": "domain", "anchor": "section 3.2 experimental setup", "reviewer_agent": "r2"},
    ])
    violations = check_review_independence(config)
    assert len(violations) >= 1, (
        "L1 regression FAILED: byte-identical anchor text passed independence check"
    )
    assert any("identical" in v.lower() or "same anchor" in v.lower() or "byte-identical" in v.lower() for v in violations)
    result = build_report(config)
    assert result["valid"] is False


def test_l1_distinct_anchor_text_passes() -> None:
    """L1 regression (happy): two lenses with distinct anchors → no anchor-identity violation."""
    config = _config([
        {"lens": "methodology", "anchor": "statistical design and variable control", "reviewer_agent": "r1"},
        {"lens": "domain", "anchor": "metric validity per cv-medical profile", "reviewer_agent": "r2"},
    ])
    violations = check_review_independence(config)
    assert violations == []
