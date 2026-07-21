"""Central-registry parity tests for every manuscript artifact contract."""
from __future__ import annotations

import copy

import pytest

from research_agent_teams.tools.validate_artifact import (
    PAYLOAD_SCHEMAS,
    SCHEMA_DIR,
    validate_payload,
)
from tests.test_manuscript_delivery_schemas import (
    _asset_manifest,
    _compiled_build,
    _compiled_quality,
    _review_verdict,
    _toolchain_missing_build,
)
from tests.test_manuscript_predraft_schemas import (
    _deficit_with_outcome,
    valid_integration,
    valid_local_literature_coverage,
    valid_manuscript_contract,
    valid_section_bundle,
)


MANUSCRIPT_SCHEMAS = {
    "manuscript_contract": "manuscript_contract.schema.json",
    "local_literature_coverage": "local_literature_coverage.schema.json",
    "manuscript_section_bundle": "manuscript_section_bundle.schema.json",
    "manuscript_integration": "manuscript_integration.schema.json",
    "manuscript_build_receipt": "manuscript_build_receipt.schema.json",
    "manuscript_asset_manifest": "manuscript_asset_manifest.schema.json",
    "manuscript_quality_report": "manuscript_quality_report.schema.json",
    "manuscript_review_verdict": "manuscript_review_verdict.schema.json",
}

VALID_PAYLOADS = {
    "manuscript_contract": valid_manuscript_contract,
    "local_literature_coverage": valid_local_literature_coverage,
    "manuscript_section_bundle": valid_section_bundle,
    "manuscript_integration": valid_integration,
    "manuscript_build_receipt": _compiled_build,
    "manuscript_asset_manifest": _asset_manifest,
    "manuscript_quality_report": _compiled_quality,
    "manuscript_review_verdict": _review_verdict,
}


def _errors(artifact_type: str, payload: dict) -> list[str]:
    return validate_payload(artifact_type, payload)


def test_registry_and_schema_files_have_exact_one_to_one_manuscript_parity():
    registered = {
        artifact_type: PAYLOAD_SCHEMAS.get(artifact_type)
        for artifact_type in MANUSCRIPT_SCHEMAS
    }
    schema_family = {
        path.name for path in SCHEMA_DIR.glob("manuscript_*.schema.json")
    } | {"local_literature_coverage.schema.json"}

    assert registered == MANUSCRIPT_SCHEMAS
    assert set(registered.values()) == schema_family
    assert len(set(registered.values())) == len(registered)


@pytest.mark.parametrize("artifact_type", tuple(MANUSCRIPT_SCHEMAS))
def test_every_registered_manuscript_payload_validates_through_public_boundary(artifact_type):
    payload = VALID_PAYLOADS[artifact_type]()

    assert _errors(artifact_type, payload) == []


@pytest.mark.parametrize(
    ("artifact_type", "required_field"),
    [
        ("manuscript_contract", "manuscript_snapshot_sha256"),
        ("local_literature_coverage", "axes"),
        ("manuscript_section_bundle", "authorization_receipt"),
        ("manuscript_integration", "canonical_file_inventory"),
        ("manuscript_build_receipt", "build_state"),
        ("manuscript_asset_manifest", "assets"),
        ("manuscript_quality_report", "daily_state"),
        ("manuscript_review_verdict", "reviewer_identity"),
    ],
)
def test_every_registered_manuscript_payload_rejects_a_missing_required_field(
    artifact_type, required_field
):
    payload = VALID_PAYLOADS[artifact_type]()
    del payload[required_field]

    errors = _errors(artifact_type, payload)
    assert errors
    assert any(required_field in error for error in errors)


@pytest.mark.parametrize("artifact_type", tuple(MANUSCRIPT_SCHEMAS))
def test_every_registered_manuscript_payload_remains_closed(artifact_type):
    payload = VALID_PAYLOADS[artifact_type]()
    payload["unregistered_truth_override"] = True

    errors = _errors(artifact_type, payload)
    assert errors
    assert any("unregistered_truth_override" in error for error in errors)


@pytest.mark.parametrize(
    ("artifact_type", "mutate", "expected_path"),
    [
        (
            "manuscript_contract",
            lambda payload: payload["source_hashes"][0].update(sha256="not-a-hash"),
            "source_hashes/0/sha256",
        ),
        (
            "manuscript_section_bundle",
            lambda payload: payload.update(content_hash="short"),
            "content_hash",
        ),
        (
            "manuscript_integration",
            lambda payload: payload.update(source_tree_sha256="bad"),
            "source_tree_sha256",
        ),
        (
            "manuscript_build_receipt",
            lambda payload: payload.update(build_state="BUILT"),
            "build_state",
        ),
        (
            "manuscript_asset_manifest",
            lambda payload: payload["assets"][0]["output"].update(run_owned=False),
            "assets/0/output/run_owned",
        ),
        (
            "manuscript_quality_report",
            lambda payload: payload.update(daily_state="BLOCK"),
            "daily_state",
        ),
        (
            "manuscript_review_verdict",
            lambda payload: payload.update(disposition="BLOCK"),
            "disposition",
        ),
    ],
)
def test_truth_sensitive_manuscript_payloads_reject_inconsistent_facts(
    artifact_type, mutate, expected_path
):
    payload = VALID_PAYLOADS[artifact_type]()
    mutate(payload)

    errors = _errors(artifact_type, payload)
    assert errors
    assert any(expected_path in error for error in errors)


def test_exhaustive_zero_result_claim_requires_a_complete_successful_empty_trace():
    payload = _deficit_with_outcome("NO_EVIDENCE_AFTER_VALID_SEARCH")
    terminal = payload["axes"]["related_comparison"]["query_authorization"]["attempts"][
        "attempt-001"
    ]["terminal"]
    terminal["result_count"] = 1

    errors = _errors("local_literature_coverage", payload)
    assert errors
    assert any("result_count" in error or "<root>" in error for error in errors)


def test_official_requires_pdf_policy_cannot_be_weakened_in_registered_contract():
    payload = valid_manuscript_contract()
    payload["venue_profile"]["hard_field_policy"]["requires_pdf"]["weakenable"] = True

    errors = _errors("manuscript_contract", payload)
    assert errors
    assert any("requires_pdf/weakenable" in error for error in errors)


def test_toolchain_missing_registered_receipt_cannot_expose_pdf_facts():
    payload = _toolchain_missing_build()
    payload["pdf"] = _compiled_build()["pdf"]

    errors = _errors("manuscript_build_receipt", payload)
    assert errors
    assert any("pdf" in error or "<root>" in error for error in errors)


def test_inputs_are_not_mutated_by_public_registry_validation():
    for artifact_type, factory in VALID_PAYLOADS.items():
        payload = factory()
        before = copy.deepcopy(payload)

        assert _errors(artifact_type, payload) == []
        assert payload == before
