from __future__ import annotations

import copy

import pytest

from research_agent_teams.tools.mechanism_council import (
    MechanismCouncilError,
    compile_bundle,
    load_contract,
    plan_council,
    render_anonymous_candidate,
)
from research_agent_teams.tools.validate_artifact import validate_payload


INPUT_SHA = "sha256:" + "a" * 64


def _contribution(role: str) -> dict:
    return {
        "contract_version": "mechanism-council-contribution/v1",
        "role": role,
        "input_sha256": INPUT_SHA,
        "status": "COMPLETE",
        "perspective_summary": f"Independent {role} analysis.",
        "observations": [
            {
                "observation_id": f"OBS-{role}",
                "kind": "requirement",
                "statement": "The proposed chain needs a discriminating comparison.",
                "evidence_status": "UNVERIFIED",
                "source_refs": [],
            }
        ],
        "proposed_mechanisms": [],
        "experiments": [],
        "blockers": [],
    }


def _all_contributions() -> list[dict]:
    return [
        _contribution(role)
        for role in (
            "mathematical_formalizer",
            "domain_reality_auditor",
            "cognitive_intent_modeler",
            "curriculum_design_specialist",
            "research_engineering_planner",
            "causal_mechanism_critic",
        )
    ]


def _chain() -> dict:
    return {
        "hypothesis": {
            "statement": "Intent is identifiable only relative to the current segmentation state.",
            "alternative": "Scribble geometry alone is sufficient.",
            "observable_prediction": "A state-aware model separates ambiguous intent classes better than no-M0.",
        },
        "mechanism": {
            "inputs": ["scribble", "M0", "PET", "CT"],
            "representation": "Scribble query and image-state tokens.",
            "transformation": "Cross-attention followed by structured slot prediction.",
            "output": "Operation, target, and scope intent slots.",
            "distinguishing_signal": "Different predictions for equal geometry under different M0 states.",
            "failure_modes": ["Shortcut learning from geometry or prevalence."],
        },
        "falsifiable_experiment": {
            "intervention": "Provide M0 to the state-aware intent model.",
            "comparator": "Matched no-M0 model.",
            "held_constant": ["split", "scribble", "backbone", "optimizer", "training budget"],
            "analysis_unit": "patient",
            "primary_outcome": "Macro intent accuracy on frozen held-out patients.",
            "leakage_checks": ["patient-disjoint split", "no test tuning", "same scribble manifest"],
            "falsifier": "No pre-registered gain on ambiguous state-relative intent classes.",
            "stop_condition": "Stop if manifest identity or patient-disjointness fails.",
        },
    }


def test_contract_has_seven_real_agent_specs_and_compiler_last():
    contract = load_contract()
    roles = [row["role"] for row in contract["roles"]]
    assert len(roles) == 7
    assert roles[-1] == "hypothesis_compiler"
    assert set(contract["roles"][-1]["depends_on"]) == set(roles[:-1])


def test_auto_council_needs_two_independent_signal_groups():
    routine = plan_council("Summarize this paper's introduction.")
    assert routine["enabled"] is False
    assert routine["selected_roles"] == []

    state_only = plan_council("The scribble intent depends on M0 and the current state.")
    assert state_only["enabled"] is False

    mechanism = plan_council(
        "The scribble intent depends on M0; use a falsifiable cross-disciplinary mechanism and ablation."
    )
    assert mechanism["enabled"] is True
    assert len(mechanism["selected_roles"]) == 7
    assert mechanism["waves"][-1] == ["hypothesis_compiler"]


def test_manual_compiler_override_adds_declared_dependency_closure():
    plan = plan_council("Compile this mechanism.", manual_roles=["hypothesis_compiler"])
    assert plan["selection_source"] == "manual_override"
    assert len(plan["selected_roles"]) == 7
    assert set(plan["auto_added_dependencies"]) == set(plan["selected_roles"]) - {"hypothesis_compiler"}


def test_compiler_requires_every_independent_role_and_frozen_input():
    rows = _all_contributions()
    with pytest.raises(MechanismCouncilError, match="cover exactly"):
        compile_bundle(
            work_order={"request_id": "SM0-01", "north_star": "State-relative intent.", "input_sha256": INPUT_SHA},
            contributions=rows[:-1],
            compiled_chain=_chain(),
            conflicts=[],
            compiler_agent_id="agent/compiler",
        )

    changed = copy.deepcopy(rows)
    changed[1]["input_sha256"] = "sha256:" + "b" * 64
    with pytest.raises(MechanismCouncilError, match="frozen work order"):
        compile_bundle(
            work_order={"request_id": "SM0-01", "north_star": "State-relative intent.", "input_sha256": INPUT_SHA},
            contributions=changed,
            compiled_chain=_chain(),
            conflicts=[],
            compiler_agent_id="agent/compiler",
        )


def test_compiled_bundle_is_design_only_and_schema_valid():
    bundle = compile_bundle(
        work_order={"request_id": "SM0-01", "north_star": "State-relative intent.", "input_sha256": INPUT_SHA},
        contributions=_all_contributions(),
        compiled_chain=_chain(),
        conflicts=[
            {
                "conflict_id": "C-1",
                "roles": ["cognitive_intent_modeler", "causal_mechanism_critic"],
                "summary": "Whether synthetic prompts identify human intent remains unresolved.",
                "resolution_status": "OPEN",
                "resolution": "Requires a future human study; not needed for the synthetic-task claim.",
            }
        ],
        compiler_agent_id="agent/compiler",
    )
    assert bundle["truth_boundary"] == {
        "execution_status": "DESIGN_ONLY",
        "result_claims_allowed": False,
        "novelty_claim_allowed": False,
        "compiler_agent_id": "agent/compiler",
    }
    assert len(bundle["contribution_receipts"]) == 6
    assert validate_payload("mechanism_council_bundle", bundle) == []


def test_anonymous_render_preserves_science_and_removes_producer_identity():
    bundle = compile_bundle(
        work_order={"request_id": "SM0-01", "north_star": "State-relative intent.", "input_sha256": INPUT_SHA},
        contributions=_all_contributions(),
        compiled_chain=_chain(),
        conflicts=[],
        compiler_agent_id="secret/compiler-agent",
    )
    rendered = render_anonymous_candidate(bundle)
    assert "## Hypothesis" in rendered
    assert "## Implementable mechanism" in rendered
    assert "## Falsifiable experiment" in rendered
    assert "DESIGN_ONLY" in rendered
    assert "secret/compiler-agent" not in rendered
    assert "contribution_receipts" not in rendered


def test_verified_observation_cannot_omit_source_locator():
    row = _contribution("domain_reality_auditor")
    row["observations"][0]["evidence_status"] = "VERIFIED"
    assert validate_payload("mechanism_council_contribution", row)
