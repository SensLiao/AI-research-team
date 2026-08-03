"""Regression coverage for immutable, stage-aware director decision boundaries."""
from research_agent_teams.orchestrator.gate_policy import director_gate_required


def test_configured_director_gate_applies_only_at_declared_stage():
    payload = {
        "gate_level": "director_signoff",
        "director_gate_stages": ["IDEATE"],
    }
    assert director_gate_required(payload, "DISCOVER") is False
    assert director_gate_required(payload, "IDEATE") is True
    assert director_gate_required(payload, "REPORT") is False


def test_legacy_director_signoff_frame_remains_fail_closed_at_every_stage():
    payload = {"gate_level": "director_signoff"}
    assert director_gate_required(payload, "DISCOVER") is True
    assert director_gate_required(payload, "IDEATE") is True


def test_non_signoff_mode_never_requests_a_director_gate():
    assert director_gate_required({"gate_level": "record_only"}, "IDEATE") is False
