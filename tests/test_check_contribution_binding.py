"""Tests for check_contribution_binding — contribution ledger binding check.

Every contribution must have:
  - non-empty evidence_refs (at least one artifact reference)
  - non-empty condition_id (must trace to an experimental condition)

A contribution with either missing → unbound → violation.
"""
from __future__ import annotations

from research_agent_teams.tools.check_contribution_binding import (
    build_report,
    check_contribution_binding,
)


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------

def _ledger(contributions: list) -> dict:
    return {"contributions": contributions}


def _contrib(
    claim_text: str = "Method X outperforms baseline on Dice",
    evidence_refs: list = None,
    condition_id: str = "treatment-lora",
    contribution_type: str = "method",
) -> dict:
    result = {
        "claim_text": claim_text,
        "condition_id": condition_id,
        "contribution_type": contribution_type,
    }
    if evidence_refs is not None:
        result["evidence_refs"] = evidence_refs
    else:
        result["evidence_refs"] = ["runs/run-001/evidence/ANALYZE/result-summary.artifact.json"]
    return result


# ---------------------------------------------------------------------------
# Happy paths
# ---------------------------------------------------------------------------

def test_fully_bound_ledger_passes() -> None:
    """All contributions have evidence_refs and condition_id → no violations."""
    ledger = _ledger([
        _contrib("Our method achieves +3% Dice", ["runs/r1/result.json"], "treatment-lora"),
        _contrib("Dataset X reduces leakage risk", ["runs/r1/dataset-card.json"], "baseline-data"),
    ])
    result = build_report(ledger)
    assert result["verdict"] == "PASS"
    assert result["violations"] == []


def test_single_contribution_fully_bound_passes() -> None:
    ledger = _ledger([_contrib()])
    assert build_report(ledger)["verdict"] == "PASS"


def test_empty_contributions_passes() -> None:
    """An empty contributions list has no unbound entries."""
    ledger = _ledger([])
    violations = check_contribution_binding(ledger)
    assert violations == []


# ---------------------------------------------------------------------------
# Empty evidence_refs
# ---------------------------------------------------------------------------

def test_empty_evidence_refs_list_blocked() -> None:
    """evidence_refs=[] → unbound violation."""
    ledger = _ledger([_contrib(evidence_refs=[])])
    violations = check_contribution_binding(ledger)
    assert len(violations) >= 1
    assert any("evidence_refs" in v.lower() or "evidence" in v.lower() for v in violations)
    assert build_report(ledger)["verdict"] == "BLOCK"


def test_missing_evidence_refs_key_blocked() -> None:
    """contribution missing evidence_refs key entirely → violation."""
    contrib = {"claim_text": "claim", "condition_id": "cond-1", "contribution_type": "method"}
    ledger = _ledger([contrib])
    violations = check_contribution_binding(ledger)
    assert len(violations) >= 1


def test_blank_evidence_ref_string_blocked() -> None:
    """evidence_refs contains blank string → violation."""
    ledger = _ledger([_contrib(evidence_refs=["   "])])
    violations = check_contribution_binding(ledger)
    assert len(violations) >= 1
    assert any("blank" in v.lower() or "non-empty" in v.lower() for v in violations)


def test_multiple_refs_one_blank_blocked() -> None:
    """evidence_refs has a valid ref plus a blank → violation for the blank."""
    ledger = _ledger([_contrib(evidence_refs=["runs/r1/result.json", ""])])
    violations = check_contribution_binding(ledger)
    assert len(violations) >= 1


# ---------------------------------------------------------------------------
# Empty condition_id
# ---------------------------------------------------------------------------

def test_empty_condition_id_blocked() -> None:
    """condition_id="" → unbound violation."""
    ledger = _ledger([_contrib(condition_id="")])
    violations = check_contribution_binding(ledger)
    assert any("condition_id" in v.lower() for v in violations)
    assert build_report(ledger)["verdict"] == "BLOCK"


def test_whitespace_condition_id_blocked() -> None:
    """condition_id="  " → unbound violation."""
    ledger = _ledger([_contrib(condition_id="  ")])
    violations = check_contribution_binding(ledger)
    assert len(violations) >= 1


def test_missing_condition_id_key_blocked() -> None:
    """contribution missing condition_id key → violation."""
    contrib = {
        "claim_text": "claim",
        "evidence_refs": ["runs/r1/result.json"],
        "contribution_type": "method",
    }
    ledger = _ledger([contrib])
    violations = check_contribution_binding(ledger)
    assert any("condition_id" in v for v in violations)


# ---------------------------------------------------------------------------
# Multiple contributions with mixed binding
# ---------------------------------------------------------------------------

def test_mixed_binding_all_violations_reported() -> None:
    """Two unbound contributions → two separate violations."""
    ledger = _ledger([
        _contrib("claim 1", evidence_refs=[], condition_id="cond-1"),  # no evidence
        _contrib("claim 2", evidence_refs=["runs/r.json"], condition_id=""),  # no condition
    ])
    violations = check_contribution_binding(ledger)
    assert len(violations) >= 2
    assert build_report(ledger)["verdict"] == "BLOCK"


def test_one_unbound_one_bound_reports_only_unbound() -> None:
    """One bound + one unbound → violation only for the unbound one."""
    ledger = _ledger([
        _contrib("good", ["runs/r.json"], "cond-A"),     # bound
        _contrib("bad", [], "cond-B"),                   # unbound (no evidence)
    ])
    violations = check_contribution_binding(ledger)
    assert len(violations) >= 1
    # The good contribution should not appear in violations
    assert not any("good" in v for v in violations)
