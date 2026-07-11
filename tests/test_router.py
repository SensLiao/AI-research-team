"""Real tests for the deterministic router + routing guardrails."""
from __future__ import annotations

import pytest

from research_agent_teams.orchestrator.graph_spec import load_mode_registry
from research_agent_teams.orchestrator.router import resolve_task, validate_routing
from research_agent_teams.tools.validate_artifact import validate_artifact

TS = "2026-06-08T00:00:00Z"


def _tf(entry, subset, gate_level="record_only"):
    return {"payload": {"entry_stage": entry, "agent_subset": subset, "gate_level": gate_level}}


def test_resolve_design_experiment_is_valid_task_frame():
    tf = resolve_task("design the next LoRA ablation", "design_experiment", "run-1", TS,
                      domain_profile_ref="cv-medical-segmentation")
    assert validate_artifact(tf) == []
    assert tf["payload"]["entry_stage"] == "DESIGN"
    assert "train-test-alignment-auditor" in tf["payload"]["agent_subset"]
    assert validate_routing(tf) == []


def test_unknown_mode_raises():
    with pytest.raises(ValueError, match="unknown mode"):
        resolve_task("x", "no_such_mode", "run-1", TS)


def test_every_shipped_mode_resolves_and_routes_clean():
    for mode in load_mode_registry()["modes"]:
        tf = resolve_task("req", mode, f"run-{mode}", TS)
        assert validate_artifact(tf) == [], f"{mode} task_frame invalid"
        assert validate_routing(tf) == [], f"{mode} routing rejected"


def test_routing_rejects_missing_hard_gate():
    tf = resolve_task("design", "design_experiment", "run-1", TS)
    tf["payload"]["agent_subset"].remove("train-test-alignment-auditor")
    errors = validate_routing(tf)
    assert any("train-test-alignment-auditor" in e and "hard gate" in e for e in errors)


def test_routing_rejects_missing_hard_gate_in_later_driven_stage():
    tf = resolve_task("full rigor", "full_rigor_minimal", "run-1", TS)
    tf["payload"]["agent_subset"].remove("variable-touch-guard")
    errors = validate_routing(tf)
    assert any("EXECUTE" in e and "variable-touch-guard" in e and "hard gate" in e for e in errors)


def test_routing_rejects_agent_not_allowed_downstream():
    # lit-scout lives in DISCOVER; entering at VERIFY it is not allowed at/after VERIFY.
    tf = _tf("VERIFY", ["lit-scout"], gate_level="record_only")
    errors = validate_routing(tf)
    assert any("lit-scout" in e and "not allowed" in e for e in errors)


def test_auto_mode_does_not_require_gate():
    # check_run enters EXECUTE (which has hard gates) but is gate_level=auto -> no gate requirement.
    tf = resolve_task("check the run", "check_run", "run-1", TS)
    assert tf["payload"]["gate_level"] == "auto"
    assert validate_routing(tf) == []
