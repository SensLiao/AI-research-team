"""Real tests for the FSM graph spec, roster, and mode registry validators."""
from __future__ import annotations

import copy

from research_agent_teams.orchestrator.graph_spec import (
    load_graph,
    load_mode_registry,
    load_roster,
    validate_graph,
    validate_mode_registry,
)


def test_shipped_graph_is_valid():
    assert validate_graph() == []


def test_shipped_mode_registry_is_valid():
    assert validate_mode_registry() == []


def test_roster_contains_known_agents():
    roster = load_roster()
    assert "train-test-alignment-auditor" in roster
    assert "research-orchestrator" in roster
    assert len(roster) > 40


def test_dangling_next_detected():
    g = copy.deepcopy(load_graph())
    g["stages"]["DESIGN"]["next"] = "NOWHERE"
    assert any("DESIGN.next invalid" in e for e in validate_graph(g))


def test_unknown_allowed_agent_detected():
    g = copy.deepcopy(load_graph())
    g["stages"]["DISCOVER"]["allowed_agents"].append("ghost-agent")
    assert any("ghost-agent" in e for e in validate_graph(g))


def test_gate_not_in_allowed_detected():
    g = copy.deepcopy(load_graph())
    g["stages"]["DESIGN"]["blocking_gates"].append("evidence-verifier")  # not in DESIGN allowed
    assert any("not in its allowed_agents" in e for e in validate_graph(g))


def test_broken_chain_to_report_detected():
    g = copy.deepcopy(load_graph())
    g["stages"]["DESIGN"]["next"] = None  # severs the chain before REPORT
    assert any("does not reach REPORT" in e for e in validate_graph(g))


def test_unknown_exit_artifact_detected():
    g = copy.deepcopy(load_graph())
    g["stages"]["DISCOVER"]["exit_artifacts"] = ["made_up_artifact"]
    assert any("unknown type" in e for e in validate_graph(g))


def test_mode_registry_unknown_agent_detected():
    reg = copy.deepcopy(load_mode_registry())
    reg["modes"]["evidence_review"]["agent_subset"].append("ghost")
    assert any("ghost" in e for e in validate_mode_registry(reg))


def test_mode_registry_stage_path_must_start_forward_and_end_at_report():
    reg = copy.deepcopy(load_mode_registry())
    reg["modes"]["evidence_review"]["stage_path"] = ["IDEATE", "DISCOVER"]
    errs = validate_mode_registry(reg)
    assert any("stage_path must start" in e for e in errs)
    assert any("stage_path must end at REPORT" in e for e in errs)
    assert any("stage_path must be forward-only" in e for e in errs)
