"""Real tests for the artifact contract enforcer + the domain-profile mechanism.

Includes a test that loads ALL example profiles and validates them — this is the
proof that the system is domain-general (cv-medical + nlp + generic all conform to
the SAME schema; medical is just one instance, not hardcoded).
"""
from __future__ import annotations

import copy

import pytest
import yaml

from research_agent_teams.tools.validate_artifact import (
    PAYLOAD_SCHEMAS,
    PROFILE_DIR,
    SCHEMA_DIR,
    is_valid,
    validate_against,
    validate_artifact,
    validate_payload,
    validate_profile_dict,
)


MANUSCRIPT_PAYLOAD_SCHEMAS = {
    "manuscript_contract": "manuscript_contract.schema.json",
    "local_literature_coverage": "local_literature_coverage.schema.json",
    "manuscript_section_bundle": "manuscript_section_bundle.schema.json",
    "manuscript_integration": "manuscript_integration.schema.json",
    "manuscript_build_receipt": "manuscript_build_receipt.schema.json",
    "manuscript_asset_manifest": "manuscript_asset_manifest.schema.json",
    "manuscript_quality_report": "manuscript_quality_report.schema.json",
    "manuscript_review_verdict": "manuscript_review_verdict.schema.json",
}


def valid_task_frame_artifact() -> dict:
    return {
        "artifact_id": "task_frame-2026-06-08T14-22-04Z-d8f3",
        "artifact_type": "task_frame",
        "schema_version": "1.0.0",
        "created_by": "orchestrator",
        "created_at": "2026-06-08T14:22:04Z",
        "status": "draft",
        "input_artifact_hashes": [],
        "output_hash": None,
        "domain_profile_ref": "cv-medical-segmentation",
        "payload": {
            "task_id": "t-d8f3",
            "mode": "design_experiment",
            "request_text": "design the next LoRA ablation",
            "entry_stage": "DESIGN",
            "agent_subset": ["experiment-planner", "train-test-alignment-auditor"],
            "gate_level": "director_signoff",
            "domain_profile_ref": "cv-medical-segmentation",
            "budget": {"max_agent_hops": 4, "max_gpu_runs_before_review": 6},
        },
    }


# ---------- envelope + payload happy path ----------

def test_valid_task_frame_passes():
    assert validate_artifact(valid_task_frame_artifact()) == []
    assert is_valid(valid_task_frame_artifact()) is True


# ---------- payload-level rejections ----------

def test_missing_required_mode_fails():
    art = valid_task_frame_artifact()
    del art["payload"]["mode"]
    errors = validate_artifact(art)
    assert any("mode" in e for e in errors)
    assert not is_valid(art)


def test_bad_gate_level_enum_fails():
    art = valid_task_frame_artifact()
    art["payload"]["gate_level"] = "MAYBE"
    errors = validate_artifact(art)
    assert any("gate_level" in e for e in errors)


def test_additional_payload_property_rejected():
    art = valid_task_frame_artifact()
    art["payload"]["sneaky_extra"] = True
    errors = validate_artifact(art)
    assert any("sneaky_extra" in e for e in errors)


def test_empty_agent_subset_fails():
    art = valid_task_frame_artifact()
    art["payload"]["agent_subset"] = []
    errors = validate_artifact(art)
    assert any("agent_subset" in e for e in errors)


def test_budget_requires_max_agent_hops():
    art = valid_task_frame_artifact()
    art["payload"]["budget"] = {}
    errors = validate_artifact(art)
    assert any("max_agent_hops" in e for e in errors)


# ---------- envelope-level rejections ----------

def test_envelope_missing_status_fails():
    art = valid_task_frame_artifact()
    del art["status"]
    errors = validate_artifact(art)
    assert any("status" in e and e.startswith("envelope") for e in errors)


def test_bad_schema_version_pattern_fails():
    art = valid_task_frame_artifact()
    art["schema_version"] = "v1"
    errors = validate_artifact(art)
    assert any("schema_version" in e for e in errors)


def test_unknown_artifact_type_payload_error():
    art = valid_task_frame_artifact()
    art["artifact_type"] = "not_a_real_type"
    errors = validate_artifact(art)
    assert any("unknown artifact_type" in e for e in errors)


# ---------- domain-profile mechanism (proves domain generality) ----------

def _load_profile(name: str) -> dict:
    with open(PROFILE_DIR / name, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def test_all_example_profiles_validate():
    profiles = sorted(p.name for p in PROFILE_DIR.glob("*.yaml"))
    assert len(profiles) >= 3, f"expected >=3 example profiles, found {profiles}"
    for name in profiles:
        body = _load_profile(name)
        assert validate_profile_dict(body) == [], f"{name} failed: {validate_profile_dict(body)}"


def test_profiles_span_multiple_domains():
    ids = {_load_profile(p.name)["profile_id"] for p in PROFILE_DIR.glob("*.yaml")}
    # The system is NOT medical-only: at least one non-CV-medical profile must exist.
    assert "cv-medical-segmentation" in ids
    assert any(pid != "cv-medical-segmentation" for pid in ids)


def test_medical_profile_forbids_slice_level_split():
    body = _load_profile("cv-medical-segmentation.profile.yaml")
    forbidden = body["split_policy"]["forbidden_split_units"]
    assert "slice" in forbidden and "patch" in forbidden


def test_nlp_profile_is_document_level_not_patient():
    body = _load_profile("nlp-text-classification.profile.yaml")
    assert body["split_policy"]["default_split_unit"] == "document"


def test_profile_missing_required_field_fails():
    body = _load_profile("ai-generic.profile.yaml")
    broken = copy.deepcopy(body)
    del broken["hard_invariants"]
    assert validate_profile_dict(broken) != []


def test_ai_generic_profile_is_thickened_and_valid():
    """L3 thicken: the generic baseline now carries real metrics / leakage checks / alignment invariants
    (not the old 1/1/2 stub), and still conforms to the SAME schema — proving the baseline has teeth
    without any domain term leaking in."""
    body = _load_profile("ai-generic.profile.yaml")
    assert validate_profile_dict(body) == []

    metric_names = {m["name"] for m in body["metrics"]}
    assert {"accuracy", "f1", "auroc"} <= metric_names
    for m in body["metrics"]:                                  # every generic metric is range-bounded [0,1]
        assert m["valid_range"] == [0.0, 1.0]

    leakage = set(body["leakage_checks"])
    assert {"train_test_id_disjoint", "data_contamination", "split_unit_integrity"} <= leakage

    invariants = " ".join(body["alignment_invariants"]).lower()
    for marker in ("tokenizer", "eval_protocol_parity", "seed_disjointness",
                   "llm_judge_bias_note", "human_eval_iaa"):
        assert marker in invariants, f"missing alignment invariant marker: {marker}"

    # domain-general: no medical / vision / NLP-specific term leaked into the generic baseline
    blob = yaml.safe_dump(body).lower()
    for banned in ("dice", "patient", "spacing", "lesion", "tumor", "voxel", "slice", "ct ", "mri"):
        assert banned not in blob, f"domain-specific term '{banned.strip()}' leaked into ai-generic"


# ---------- gate verdict integrity (verdict is derived, never hand-set) ----------

GATE_VERDICT_SCHEMAS = [
    "preflight_report.schema.json",
    "parity_verdict.schema.json",
    "sanity_verdict.schema.json",
    "alignment_report.schema.json",
    "variable_control_report.schema.json",
]


@pytest.mark.parametrize("schema", GATE_VERDICT_SCHEMAS)
def test_gate_verdict_pass_with_violations_is_rejected(schema):
    # the structural guarantee: a hand-set PASS alongside real violations cannot clear schema validation
    assert validate_against(schema, {"verdict": "PASS", "violations": ["something broke"]}) != []


@pytest.mark.parametrize("schema", GATE_VERDICT_SCHEMAS)
def test_gate_verdict_legitimate_shapes_validate(schema):
    assert validate_against(schema, {"verdict": "BLOCK", "violations": ["x"]}) == []
    assert validate_against(schema, {"verdict": "PASS", "violations": []}) == []


def test_all_manuscript_payload_schemas_have_one_authoritative_registry_entry():
    registered = {
        artifact_type: PAYLOAD_SCHEMAS.get(artifact_type)
        for artifact_type in MANUSCRIPT_PAYLOAD_SCHEMAS
    }

    assert registered == MANUSCRIPT_PAYLOAD_SCHEMAS
    assert len(set(registered.values())) == len(registered)
    assert all((SCHEMA_DIR / schema_name).is_file() for schema_name in registered.values())


def test_unknown_manuscript_payload_type_remains_rejected_centrally():
    errors = validate_payload("manuscript_unregistered_result", {})

    assert errors == [
        "payload: unknown artifact_type 'manuscript_unregistered_result' (no registered schema)"
    ]
