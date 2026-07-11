"""Tests for the result-analyzer deterministic core."""
from __future__ import annotations

from research_agent_teams.operate.artifacts import envelope
from research_agent_teams.tools.result_analyzer import (
    build_result_summary,
    build_result_summary_with_stats,
)
from research_agent_teams.tools.validate_artifact import validate_against, validate_artifact


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


# ---------------------------------------------------------------------------
# H6: build_result_summary_with_stats wrapper (significance enrichment)
# ---------------------------------------------------------------------------

TS = "2026-06-12T12:00:00Z"


def test_build_with_stats_is_additive_base_fields_unchanged():
    """The wrapper preserves every field plain build_result_summary produces; only ADDS stats."""
    findings = [{
        "metric": "dice", "value": 0.85, "condition_id": "cond-A",
        "baseline_value": 0.70, "baseline_condition_id": "baseline",
    }]
    per_seed = {
        "cond-A": {"dice": [0.84, 0.86, 0.85, 0.87]},
        "baseline": {"dice": [0.70, 0.71, 0.69, 0.70]},
    }
    base = build_result_summary(findings, caveats=["c"])
    enriched = build_result_summary_with_stats(findings, per_seed, seed=2024, caveats=["c"])

    # Hard ceilings untouched.
    assert enriched["status"] == "provisional"
    assert enriched["can_cite_thesis"] is False
    assert enriched["caveats"] == ["c"]
    # Base finding fields are preserved exactly.
    bf, ef = base["findings"][0], enriched["findings"][0]
    for k in ("metric", "value", "condition_id", "baseline_value", "delta",
              "baseline_condition_id"):
        assert ef[k] == bf[k]
    # And the new stats fields are present on top.
    assert "p_value" in ef and "stats" in enriched


def test_build_with_stats_validates_as_artifact():
    findings = [{
        "metric": "dice", "value": 0.85, "condition_id": "cond-A",
        "baseline_value": 0.70, "baseline_condition_id": "baseline",
    }]
    per_seed = {
        "cond-A": {"dice": [0.84, 0.86, 0.85, 0.87]},
        "baseline": {"dice": [0.70, 0.71, 0.69, 0.70]},
    }
    payload = build_result_summary_with_stats(findings, per_seed, seed=1)
    assert validate_against("result_summary.schema.json", payload) == []
    art = envelope("result_summary", "result-analyzer", payload, TS)
    assert validate_artifact(art) == []


def test_build_with_stats_no_per_seed_data_notes_insufficient():
    """No per-seed data → wrapper still valid, with an explicit 'no significance' note."""
    payload = build_result_summary_with_stats(
        [FINDING_WITH_BASELINE], per_seed={}, seed=0
    )
    assert payload["stats"]["n_findings_tested"] == 0
    assert payload["stats"]["note"] == "insufficient per-seed data — no significance computed"
    assert "p_value" not in payload["findings"][0]
    assert validate_against("result_summary.schema.json", payload) == []


def test_baseline_condition_id_passes_through_build_result_summary():
    """The plain builder carries baseline_condition_id through when supplied (and stays valid)."""
    payload = build_result_summary([{
        "metric": "dice", "value": 0.8, "condition_id": "c1",
        "baseline_value": 0.7, "baseline_condition_id": "base",
    }])
    assert payload["findings"][0]["baseline_condition_id"] == "base"
    assert validate_against("result_summary.schema.json", payload) == []
