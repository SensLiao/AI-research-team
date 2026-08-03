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
    "manuscript_venue_profile_slice": "manuscript_venue_profile_slice.schema.json",
    "manuscript_evidence_slice": "manuscript_evidence_slice.schema.json",
    "manuscript_section_bundle": "manuscript_section_bundle.schema.json",
    "manuscript_integration": "manuscript_integration.schema.json",
    "manuscript_build_receipt": "manuscript_build_receipt.schema.json",
    "manuscript_asset_manifest": "manuscript_asset_manifest.schema.json",
    "manuscript_quality_report": "manuscript_quality_report.schema.json",
    "manuscript_review_verdict": "manuscript_review_verdict.schema.json",
    "submission_checklist": "submission_checklist.schema.json",
}


def _sha(character: str) -> str:
    return character * 64


def _hashed_reference(ref: str, character: str = "a") -> dict:
    return {"ref": ref, "sha256": _sha(character)}


def _evidence_slice() -> dict:
    evidence_ref = "runs/run-001/evidence/local-paper-001.json"
    return {
        "contract_version": "1.0",
        "evidence_slice_id": "evidence-slice-run-001",
        "worker_role": "manuscript-evidence-steward",
        "authorization_receipt": {
            "ref": "runs/run-001/receipts/evidence-steward.json",
            "sha256": _sha("a"),
            "worker_role": "manuscript-evidence-steward",
        },
        "manuscript_snapshot_sha256": _sha("b"),
        "claim_evidence_map_ref": "runs/run-001/evidence/claim-evidence-map.json",
        "claim_evidence_map_sha256": _sha("c"),
        "evidence_refs": [
            {
                "ref": evidence_ref,
                "sha256": _sha("d"),
                "source_kind": "LOCAL_FULL_TEXT",
                "claim_support": "EXACT_SPAN",
            }
        ],
        "result_refs": [
            {
                "ref": "runs/run-001/results/frozen-result.json",
                "sha256": _sha("e"),
                "status": "FROZEN",
                "receipt_ref": "runs/run-001/receipts/executor.json",
                "receipt_sha256": _sha("f"),
            }
        ],
        "bibliography": {
            "style": "natbib",
            "entries": [
                {
                    "citation_key": "LocalPaper2026",
                    "source_ref": evidence_ref,
                    "source_sha256": _sha("d"),
                    "identity_status": "VERIFIED",
                }
            ],
        },
        "evidence_slice_sha256": _sha("0"),
    }


def _venue_profile_slice() -> dict:
    venue_rule_ref = "runs/run-001/venue/icml-2026-author-instructions.json"
    return {
        "contract_version": "1.0",
        "venue_profile_slice_id": "venue-profile-slice-run-001",
        "worker_role": "manuscript-venue-corpus-scout",
        "authorization_receipt": {
            "ref": "runs/run-001/receipts/venue-scout.json",
            "sha256": _sha("1"),
            "worker_role": "manuscript-venue-corpus-scout",
        },
        "manuscript_snapshot_sha256": _sha("2"),
        "local_literature_coverage_ref": "runs/run-001/evidence/local-literature-coverage.json",
        "local_literature_coverage_sha256": _sha("3"),
        "venue_profile": {
            "venue_id": "icml",
            "venue_family": "top-ai-conference",
            "year": 2026,
            "track": "main",
            "retrieved_at": "2026-07-22T00:00:00Z",
            "official_rule_refs": [_hashed_reference(venue_rule_ref, "4")],
            "template_ref": "runs/run-001/templates/icml-2026",
            "template_sha256": _sha("5"),
            "requires_pdf": True,
            "hard_field_policy": {
                "requires_pdf": {
                    "classification": "OFFICIAL_HARD",
                    "weakenable": False,
                    "source_ref": venue_rule_ref,
                    "source_sha256": _sha("4"),
                }
            },
        },
        "venue_profile_slice_sha256": _sha("6"),
    }


def _submission_checklist() -> dict:
    def check(summary: str, character: str) -> dict:
        return {
            "state": "CLEAR",
            "summary": summary,
            "evidence_refs": [_hashed_reference("runs/review-001/evidence/checks.json", character)],
            "finding_ids": [],
        }

    capability = {
        "state": "PASS",
        "source_ref": "runs/review-001/evidence/reconciliation.json",
        "source_sha256": _sha("7"),
    }
    return {
        "schema_version": "1.0.0",
        "checklist_id": "submission-checklist-review-001",
        "review_run_id": "review-001",
        "producer_role": "manuscript-submission-packager",
        "manuscript_snapshot_sha256": _sha("8"),
        "reconciliation": {
            "ref": "runs/review-001/evidence/reconciliation.json",
            "sha256": _sha("7"),
            "source_finding_index_ref": "runs/review-001/evidence/finding-index.json",
            "source_finding_index_sha256": _sha("9"),
        },
        "quality_report": _hashed_reference("runs/authoring-001/evidence/quality-report.json", "a"),
        "daily_state": "USABLE",
        "submission_ready": True,
        "build_truth": {
            "receipt_ref": "runs/authoring-001/evidence/build-receipt.json",
            "receipt_sha256": _sha("b"),
            "build_state": "COMPILED",
            "requires_pdf": True,
            "source_tree_ref": "runs/authoring-001/manuscript/source",
            "source_tree_sha256": _sha("c"),
            "pdf": {
                "available": True,
                "ref": "runs/authoring-001/build/main.pdf",
                "sha256": _sha("d"),
            },
        },
        "capability_coverage": {
            "domain_contribution": capability,
            "methods_reproducibility": capability,
            "figure_table": capability,
            "factual": capability,
            "citation": capability,
            "venue_style_latex": capability,
        },
        "checks": {
            "official_rules": check("Official rules are reconciled.", "e"),
            "anonymity_privacy": check("Anonymity review is clear.", "f"),
            "scientific_citation_number_closure": check("Scientific closure is clear.", "0"),
            "assets": check("Assets are present.", "1"),
            "cross_references": check("Cross references are resolved.", "2"),
            "source_build_pdf_truth": check("Compiled PDF is hash-bound.", "3"),
        },
        "findings": [],
        "submission_blockers": [],
        "evidence_links": {
            "overview": _hashed_reference("runs/authoring-001/director-review/manuscript/00-OVERVIEW.md", "4"),
            "coverage": _hashed_reference("runs/authoring-001/director-review/manuscript/01-COVERAGE.md", "5"),
            "authoring_plan": _hashed_reference("runs/authoring-001/director-review/manuscript/02-AUTHORING-PLAN.md", "6"),
            "manuscript": _hashed_reference("runs/authoring-001/manuscript/source/main.tex", "7"),
            "source_tree": _hashed_reference("runs/authoring-001/manuscript/source", "c"),
            "quality_report": _hashed_reference("runs/authoring-001/evidence/quality-report.json", "a"),
            "review": _hashed_reference("runs/review-001/evidence/review-verdict.json", "8"),
            "build_receipt": _hashed_reference("runs/authoring-001/evidence/build-receipt.json", "b"),
            "reconciliation": _hashed_reference("runs/review-001/evidence/reconciliation.json", "7"),
            "evidence_index": _hashed_reference("runs/review-001/evidence/link-index.json", "9"),
            "pdf": _hashed_reference("runs/authoring-001/build/main.pdf", "d"),
        },
        "outstanding_director_decisions": [
            {
                "decision_id": "director-submit-review-001",
                "question": "Does the director authorize a submission attempt?",
                "authority": "DIRECTOR_HUMAN",
                "status": "REQUIRED",
                "evidence_refs": [_hashed_reference("runs/review-001/evidence/reconciliation.json", "7")],
            }
        ],
        "submission_authorization": False,
        "submission_checklist_sha256": _sha("e"),
    }


VALID_PAYLOADS = {
    "manuscript_contract": valid_manuscript_contract,
    "local_literature_coverage": valid_local_literature_coverage,
    "manuscript_venue_profile_slice": _venue_profile_slice,
    "manuscript_evidence_slice": _evidence_slice,
    "manuscript_section_bundle": valid_section_bundle,
    "manuscript_integration": valid_integration,
    "manuscript_build_receipt": _compiled_build,
    "manuscript_asset_manifest": _asset_manifest,
    "manuscript_quality_report": _compiled_quality,
    "manuscript_review_verdict": _review_verdict,
    "submission_checklist": _submission_checklist,
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
    } | {
        "local_literature_coverage.schema.json",
        "submission_checklist.schema.json",
    }

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
        ("manuscript_venue_profile_slice", "venue_profile"),
        ("manuscript_evidence_slice", "claim_evidence_map_sha256"),
        ("manuscript_section_bundle", "authorization_receipt"),
        ("manuscript_integration", "canonical_file_inventory"),
        ("manuscript_build_receipt", "build_state"),
        ("manuscript_asset_manifest", "assets"),
        ("manuscript_quality_report", "daily_state"),
        ("manuscript_review_verdict", "reviewer_identity"),
        ("submission_checklist", "reconciliation"),
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
            "manuscript_venue_profile_slice",
            lambda payload: payload["venue_profile"].update(template_sha256="not-a-hash"),
            "venue_profile/template_sha256",
        ),
        (
            "manuscript_evidence_slice",
            lambda payload: payload.update(claim_evidence_map_sha256="short"),
            "claim_evidence_map_sha256",
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
        (
            "submission_checklist",
            lambda payload: payload["build_truth"].update(receipt_sha256="not-a-hash"),
            "build_truth/receipt_sha256",
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


def test_submission_checklist_cannot_claim_readiness_with_a_blocked_check():
    payload = _submission_checklist()
    payload["checks"]["official_rules"]["state"] = "BLOCK"

    errors = _errors("submission_checklist", payload)
    assert errors
    assert any("submission_ready" in error or "submission_blockers" in error for error in errors)


@pytest.mark.parametrize(
    "coverage_field",
    (
        "domain_contribution",
        "methods_reproducibility",
        "figure_table",
        "factual",
        "citation",
        "venue_style_latex",
    ),
)
def test_submission_checklist_blocked_capability_requires_not_ready_and_a_blocker(
    coverage_field,
):
    payload = _submission_checklist()
    payload["capability_coverage"][coverage_field] = {
        **payload["capability_coverage"][coverage_field],
        "state": "BLOCK",
    }
    assert all(
        capability["state"] == "PASS"
        for field, capability in payload["capability_coverage"].items()
        if field != coverage_field
    )

    errors = _errors("submission_checklist", payload)
    assert any("submission_ready" in error for error in errors)
    assert any("submission_blockers" in error for error in errors)

    payload["submission_ready"] = False
    errors = _errors("submission_checklist", payload)
    assert any("submission_blockers" in error for error in errors)

    payload["submission_blockers"] = [
        {
            "blocker_id": f"capability-{coverage_field}-blocker",
            "finding_id": f"capability-{coverage_field}-finding",
            "source_ref": "runs/review-001/evidence/reconciliation.json",
            "source_sha256": _sha("7"),
            "rationale": f"{coverage_field} capability coverage is blocked.",
        }
    ]
    assert _errors("submission_checklist", payload) == []


def test_inputs_are_not_mutated_by_public_registry_validation():
    for artifact_type, factory in VALID_PAYLOADS.items():
        payload = factory()
        before = copy.deepcopy(payload)

        assert _errors(artifact_type, payload) == []
        assert payload == before
