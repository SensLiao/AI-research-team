"""Tests for the result-analyzer deterministic core."""
from __future__ import annotations

from research_agent_teams.tools.result_analyzer import build_result_summary
from research_agent_teams.tools.validate_artifact import validate_against


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

FINDING_WITH_BASELINE = {
    "metric": "dice",
    "value": 0.82,
    "condition_id": "cond-A",
    "baseline_value": 0.75,
}

FINDING_NO_BASELINE = {
    "metric": "iou",
    "value": 0.71,
    "condition_id": "cond-B",
}


# ---------------------------------------------------------------------------
# Test functions
# ---------------------------------------------------------------------------

def test_finding_with_baseline_delta_and_schema_valid():
    """Finding with baseline_value → delta computed correctly AND payload schema-valid."""
    payload = build_result_summary([FINDING_WITH_BASELINE])

    assert validate_against("result_summary.schema.json", payload) == [], \
        "Payload must validate against result_summary.schema.json"

    finding = payload["findings"][0]
    assert finding["baseline_value"] == 0.75
    assert abs(finding["delta"] - round(0.82 - 0.75, 6)) < 1e-9, \
        "delta must equal round(value - baseline_value, 6)"


def test_status_always_provisional_and_can_cite_thesis_always_false():
    """status is always 'provisional' and can_cite_thesis is always False regardless of input."""
    payload = build_result_summary([FINDING_NO_BASELINE], caveats=["preliminary run"])

    assert payload["status"] == "provisional", "status must be hardcoded 'provisional'"
    assert payload["can_cite_thesis"] is False, "can_cite_thesis must be hardcoded False"

    # Verify the schema const constraints are also satisfied
    assert validate_against("result_summary.schema.json", payload) == []


def test_empty_findings_schema_valid():
    """Empty findings list → payload is schema-valid."""
    payload = build_result_summary([])

    assert payload["findings"] == []
    assert validate_against("result_summary.schema.json", payload) == [], \
        "Empty findings must produce a schema-valid payload"


def test_finding_without_baseline_no_delta_schema_valid():
    """Finding without baseline_value → no delta field, schema-valid."""
    payload = build_result_summary([FINDING_NO_BASELINE])

    assert validate_against("result_summary.schema.json", payload) == [], \
        "Finding without baseline must produce a schema-valid payload"

    finding = payload["findings"][0]
    assert "baseline_value" not in finding, \
        "baseline_value must be absent when not supplied"
    assert "delta" not in finding, \
        "delta must be absent when baseline_value is not supplied"


def test_multiple_findings_mixed_baseline():
    """Mix of findings with and without baseline → all schema-valid, deltas only where baseline exists."""
    findings = [FINDING_WITH_BASELINE, FINDING_NO_BASELINE]
    payload = build_result_summary(findings, caveats=["mixed run"])

    assert validate_against("result_summary.schema.json", payload) == []
    assert "delta" in payload["findings"][0]
    assert "delta" not in payload["findings"][1]
    assert payload["caveats"] == ["mixed run"]


def test_caveats_default_to_empty_list():
    """Omitting caveats → caveats defaults to []."""
    payload = build_result_summary([FINDING_NO_BASELINE])
    assert payload["caveats"] == []
