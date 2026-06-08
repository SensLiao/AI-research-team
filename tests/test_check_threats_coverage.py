"""Tests for check_threats_coverage — validity dimension completeness check.

All four dimensions (internal, external, construct, statistical) must be present.
Missing any → violation. Test: only internal covered → 3 missing dimensions reported.
"""
from __future__ import annotations

from research_agent_teams.tools.check_threats_coverage import (
    REQUIRED_DIMENSIONS,
    build_report,
    check_threats_coverage,
)


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------

def _threat(dim: str, text: str = "threat text", mitigation: str = "none identified") -> dict:
    return {
        "validity_dimension": dim,
        "threat_text": text,
        "mitigation": mitigation,
        "severity": "medium",
    }


def _report(threats: list) -> dict:
    return {"threats": threats}


# ---------------------------------------------------------------------------
# Happy path: all four dimensions covered
# ---------------------------------------------------------------------------

def test_all_four_dimensions_passes() -> None:
    """All four required dimensions present → no violations."""
    report = _report([
        _threat("internal", "selection bias in patient cohort"),
        _threat("external", "single-site dataset, may not generalize"),
        _threat("construct", "Dice metric may not capture topology errors"),
        _threat("statistical", "only 3 seeds, overlapping CIs possible"),
    ])
    result = build_report(report)
    assert result["verdict"] == "PASS"
    assert result["violations"] == []
    assert result["missing_dimensions"] == []


def test_multiple_threats_per_dimension_passes() -> None:
    """More than one threat per dimension is fine as long as all four covered."""
    report = _report([
        _threat("internal"),
        _threat("internal", "instrumentation change mid-study"),
        _threat("external"),
        _threat("construct"),
        _threat("statistical"),
    ])
    assert build_report(report)["verdict"] == "PASS"


def test_four_dimensions_different_severities_pass() -> None:
    """Coverage check doesn't care about severity — just dimension presence."""
    report = _report([
        _threat("internal"),
        _threat("external"),
        _threat("construct"),
        _threat("statistical"),
    ])
    violations = check_threats_coverage(report)
    assert violations == []


# ---------------------------------------------------------------------------
# The contract's golden test: only internal covered → 3 missing
# ---------------------------------------------------------------------------

def test_only_internal_covered_three_missing() -> None:
    """Only internal validity covered → exactly 3 missing dimensions reported.

    This is the specific test the contract requires.
    """
    report = _report([_threat("internal")])
    violations = check_threats_coverage(report)

    # Must report exactly 3 violations (external, construct, statistical missing)
    assert len(violations) == 3, (
        f"expected 3 violations for 3 missing dims but got {len(violations)}: {violations}"
    )
    assert any("external" in v for v in violations)
    assert any("construct" in v for v in violations)
    assert any("statistical" in v for v in violations)
    assert not any("internal" in v for v in violations)

    result = build_report(report)
    assert result["verdict"] == "BLOCK"
    assert len(result["missing_dimensions"]) == 3


# ---------------------------------------------------------------------------
# Other missing combinations
# ---------------------------------------------------------------------------

def test_all_missing_four_violations() -> None:
    """No threats at all → all four dimensions missing."""
    report = _report([])
    violations = check_threats_coverage(report)
    assert len(violations) == 4
    assert build_report(report)["verdict"] == "BLOCK"


def test_three_of_four_covered_one_missing() -> None:
    """Three dimensions covered → exactly one violation for the missing one."""
    report = _report([
        _threat("internal"),
        _threat("external"),
        _threat("construct"),
        # statistical MISSING
    ])
    violations = check_threats_coverage(report)
    assert len(violations) == 1
    assert "statistical" in violations[0]
    # The violation must NOT mention covered dimensions
    assert "internal" not in violations[0]


def test_two_missing_two_violations() -> None:
    """Two dimensions covered → two violations."""
    report = _report([
        _threat("internal"),
        _threat("external"),
    ])
    violations = check_threats_coverage(report)
    assert len(violations) == 2
    missing = {d for v in violations for d in ["internal", "external", "construct", "statistical"] if d in v}
    assert "construct" in missing
    assert "statistical" in missing


def test_unknown_dimension_does_not_count_as_coverage() -> None:
    """A threat with an unknown/invalid dimension does not count toward required coverage."""
    report = _report([
        _threat("internal"),
        _threat("external"),
        _threat("construct"),
        {"validity_dimension": "philosophical", "threat_text": "unknown", "mitigation": "none"},
    ])
    violations = check_threats_coverage(report)
    # statistical is still missing
    assert len(violations) == 1
    assert "statistical" in violations[0]


# ---------------------------------------------------------------------------
# build_report missing_dimensions field
# ---------------------------------------------------------------------------

def test_build_report_missing_dimensions_field_accurate() -> None:
    """build_report.missing_dimensions lists precisely the missing dims."""
    report = _report([_threat("internal")])
    result = build_report(report)
    missing = set(result["missing_dimensions"])
    assert missing == {"external", "construct", "statistical"}


def test_build_report_missing_dimensions_empty_when_all_covered() -> None:
    """All four covered → missing_dimensions is empty."""
    report = _report([
        _threat("internal"), _threat("external"),
        _threat("construct"), _threat("statistical"),
    ])
    result = build_report(report)
    assert result["missing_dimensions"] == []


# ---------------------------------------------------------------------------
# All required dimensions are the canonical four
# ---------------------------------------------------------------------------

def test_required_dimensions_constant() -> None:
    """The REQUIRED_DIMENSIONS constant must be exactly the four canonical dims."""
    assert REQUIRED_DIMENSIONS == frozenset(["internal", "external", "construct", "statistical"])
