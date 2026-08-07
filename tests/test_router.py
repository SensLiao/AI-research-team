"""Real tests for the deterministic router + routing guardrails."""
from __future__ import annotations

import json

import pytest

from research_agent_teams.orchestrator.graph_spec import load_mode_registry
from research_agent_teams.orchestrator.router import resolve_task, validate_routing
from research_agent_teams.tools.research_capability_router import (
    DEFAULT_OVERLAY_CATALOG,
    route_research_capabilities,
)
from research_agent_teams.tools.validate_artifact import validate_artifact

TS = "2026-06-08T00:00:00Z"

# Policy-derived, not literal — see test_research_capability_router.py for why `<= 5` was a trap.
_POLICY = json.loads(DEFAULT_OVERLAY_CATALOG.read_text(encoding="utf-8"))["policy"]
_POLICY_MIN = int(_POLICY["selection_min"])
_POLICY_MAX = int(_POLICY["selection_max"])


def _tf(entry, subset, gate_level="record_only"):
    return {"payload": {"entry_stage": entry, "agent_subset": subset, "gate_level": gate_level}}


def test_resolve_design_experiment_is_valid_task_frame():
    tf = resolve_task("design the next LoRA ablation", "design_experiment", "run-1", TS,
                      domain_profile_ref="cv-medical-segmentation")
    assert validate_artifact(tf) == []
    assert tf["payload"]["entry_stage"] == "DESIGN"
    assert "train-test-alignment-auditor" in tf["payload"]["agent_subset"]
    overlay_plan = tf["payload"]["capability_overlay_plan"]
    # design_experiment became one-button in wave 2 (2026-08-04).
    assert overlay_plan["mode_status"] == "operated"
    assert overlay_plan["external_skill_execution"] is False
    assert overlay_plan["network_access"] is False
    assert _POLICY_MIN <= len(overlay_plan["overlays"]) <= _POLICY_MAX
    assert validate_routing(tf) == []


def test_unknown_mode_raises():
    with pytest.raises(ValueError, match="unknown mode"):
        resolve_task("x", "no_such_mode", "run-1", TS)


def test_every_shipped_mode_resolves_and_routes_clean():
    for mode in load_mode_registry()["modes"]:
        tf = resolve_task("req", mode, f"run-{mode}", TS)
        assert validate_artifact(tf) == [], f"{mode} task_frame invalid"
        assert validate_routing(tf) == [], f"{mode} routing rejected"


def test_overlay_plan_is_advisory_and_does_not_rewrite_the_mode_contract():
    registry = load_mode_registry()
    spec = registry["modes"]["design_experiment"]
    tf = resolve_task("为患者级 PET/CT 设计有功效依据的实验", "design_experiment", "run-overlay", TS,
                      registry=registry)
    payload = tf["payload"]
    assert payload["mode"] == "design_experiment"
    assert payload["entry_stage"] == spec["entry_stage"]
    assert payload["agent_subset"] == spec["agent_subset"]
    assert payload["gate_level"] == spec["gate_level"]
    assert payload["budget"] == spec["budget"]
    assert any(item["overlay_id"] == "power_unit_of_analysis_contract"
               for item in payload["capability_overlay_plan"]["overlays"])


def test_task_frame_schema_rejects_an_overlay_execution_escalation():
    tf = resolve_task("review evidence", "evidence_review", "run-overlay-unsafe", TS)
    tf["payload"]["capability_overlay_plan"]["external_skill_execution"] = True
    errors = validate_artifact(tf)
    assert any("external_skill_execution" in error for error in errors)


def test_precomputed_auto_route_is_frozen_with_automatic_source():
    request = "深读这篇论文并核验其证据"
    route = route_research_capabilities(request)
    mode = route["routing"]["mode"]
    tf = resolve_task(request, mode, "run-auto-overlay", TS, capability_route=route)
    plan = tf["payload"]["capability_overlay_plan"]
    assert plan["mode_source"] == "automatic_suggestion"
    assert tf["payload"]["mode"] == mode
    assert validate_artifact(tf) == []


def test_mechanism_council_selection_is_frozen_but_does_not_mutate_mode():
    request = "研究 M0 状态相对意图，并用数学和认知机制设计可证伪实验"
    route = route_research_capabilities(request, explicit_mode="full_rigor_minimal")
    tf = resolve_task(
        request,
        "full_rigor_minimal",
        "run-council",
        TS,
        capability_route=route,
    )
    plan = tf["payload"]["mechanism_council_plan"]
    assert plan["enabled"] is True
    assert len(plan["selected_roles"]) == 7
    assert plan["waves"][-1] == ["hypothesis_compiler"]
    assert tf["payload"]["mode"] == "full_rigor_minimal"
    assert validate_artifact(tf) == []


def test_mechanism_council_cannot_escalate_into_result_authority():
    request = "研究 M0 状态相对意图与可证伪机制"
    route = route_research_capabilities(request, explicit_mode="full_rigor_minimal")
    route["mechanism_council_plan"]["truth_boundary"]["may_create_results"] = True
    with pytest.raises(ValueError, match="attempted to create results"):
        resolve_task(
            request,
            "full_rigor_minimal",
            "run-council-unsafe",
            TS,
            capability_route=route,
        )


def test_router_pins_caveated_upstream_delivery_acceptance():
    """A registry opt-in must survive task-frame freezing for later handoff validation."""
    tf = resolve_task("refine an evidence-bounded idea", "deep_ideation", "run-caveated", TS)
    assert tf["payload"]["product_contract"]["accepts_delivery_statuses"] == [
        "USABLE", "USABLE_WITH_CAVEATS",
    ]


def test_router_pins_idea_bet_at_the_ideate_boundary_only():
    """A direction run may ground evidence automatically; its human bet is after its menu exists."""
    tf = resolve_task("refine an evidence-bounded idea", "deep_ideation", "run-idea-gate", TS)
    assert tf["payload"]["director_gate_stages"] == ["IDEATE"]


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
