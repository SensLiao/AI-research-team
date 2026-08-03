from __future__ import annotations

import runpy
from pathlib import Path


SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "projects"
    / "t4-scribble-m0-mechanism-eval"
    / "scripts"
    / "preflight"
    / "scribble_m0_contract_dry_run.py"
)


def _module() -> dict:
    return runpy.run_path(str(SCRIPT), run_name="t4_contract_dry_run")


def test_contract_dry_run_is_real_but_non_scientific_and_fail_closed():
    result = _module()["run_dry_run"]()
    assert result["evidence_class"] == "NOT_SCIENTIFIC_EVIDENCE"
    assert result["execution_kind"] == "CPU_SYNTHETIC_CONTRACT_ONLY"
    assert result["preflight_state"] == "PREFLIGHT_BLOCKED"
    assert result["scientific_claims_allowed"] is False
    assert result["gpu_execution_authorized"] is False
    assert len(result["unresolved_blockers"]) >= 5


def test_frozen_six_joint_ontology_and_output_shapes_are_exercised():
    module = _module()
    assert len(module["LEGAL_JOINTS"]) == 6
    for illegal in module["ILLEGAL_JOINTS"]:
        try:
            module["validate_joint"](illegal)
        except ValueError:
            pass
        else:
            raise AssertionError(f"illegal joint was admitted: {illegal}")
    assert module["forward_shape_stub"](3) == {
        "joint_logits": [3, 6],
        "operation_logits": [3, 2],
        "target_logits": [3, 2],
        "scope_logits": [3, 2],
    }


def test_fixture_metric_pipeline_uses_patient_not_episode_as_unit():
    result = _module()["run_dry_run"]()
    fixture = result["fixture_metric_pipeline"]
    assert fixture["status"] == "NOT_SCIENTIFIC_EVIDENCE"
    assert fixture["episode_mean"] != fixture["patient_level_mean"]
