"""Tests for the frozen-holdout Stage-B research-capability paired A/B evaluation.

R3 §B①: this module calls into provider_call_receipt_import, so it inherits the same signature/
file-hash teardown (see test_provider_call_receipt_import.py). Deleted: test_seal_blocks_without_a_
real_host_trust_binding (the "no trusted key" gate is vestigial once nothing verifies attestation),
and the "sha" case (receipt-declared vs. recomputed author-artifact SHA-256) from the parametrized
fail-closed test. Kept: schema validation, path fencing, missing-file existence, and every
coherence/binding check that is not a file-content hash comparison — global runtime-policy parity
across all 40 receipts, challenge/artifact-path binding, blind-packet identity binding
(packet_sha256 on a judge sheet), and paired-statistics/scoring logic.
"""
from __future__ import annotations

import hashlib
import base64
import copy
import json
import socket
import subprocess
import urllib.request
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from jsonschema import Draft202012Validator

from research_agent_teams.tools import research_capability_ab_eval as ab
from research_agent_teams.tools import provider_call_receipt_import as provider_receipts
from research_agent_teams.tools.research_capability_router import load_overlay_catalog


TEST_PRIVATE_KEY = Ed25519PrivateKey.from_private_bytes(bytes(range(1, 33)))
TEST_PUBLIC_KEY = TEST_PRIVATE_KEY.public_key().public_bytes(
    encoding=serialization.Encoding.Raw,
    format=serialization.PublicFormat.Raw,
)

TEST_AUTHOR_RUNTIME_POLICY = {
    "schema_version": ab.AUTHOR_RUNTIME_POLICY_CONTRACT,
    "runtime_policy_id": "stage-b-test-policy-v1",
    "model_policy": "max_quality",
    "model": "synthetic-requested-model",
    "service_tier": "test-requested-tier",
    "reasoning_effort": "test-requested-effort",
    "agent_type": "stage-b-author",
    "context_budget_tokens": 4096,
    "max_output_tokens": 1024,
}


def _provider_key_resolver(key_id: str) -> bytes | None:
    return TEST_PUBLIC_KEY if key_id == "stage-b-test-host" else None


def _sign_provider_receipt(receipt: dict) -> dict:
    signed = copy.deepcopy(receipt)
    signed["attestation"]["signature"] = "ed25519:" + base64.b64encode(
        TEST_PRIVATE_KEY.sign(provider_receipts.receipt_attestation_message(signed))
    ).decode("ascii")
    return signed


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _prepare(tmp_path: Path) -> tuple[dict, Path]:
    out_dir = tmp_path / "prepared"
    plan = ab.prepare_stage_b(
        out_dir=out_dir,
        author_runtime_policy=TEST_AUTHOR_RUNTIME_POLICY,
    )
    return plan, out_dir / "dispatch-plan.json"


def _write_author_artifacts(plan: dict, root: Path) -> None:
    for pair in plan["pairs"]:
        for label, candidate in pair["candidates"].items():
            author_path = root / candidate["author_output_rel"]
            receipt_path = root / candidate["runtime_receipt_rel"]
            author_path.parent.mkdir(parents=True, exist_ok=True)
            receipt_path.parent.mkdir(parents=True, exist_ok=True)
            author_path.write_text(
                f"Synthetic test-only response for {pair['request_id']} candidate {label}.\n",
                encoding="utf-8",
            )
            challenge = candidate["provider_receipt_challenge"]
            requested_policy = candidate["author_runtime_policy"]
            receipt = {
                "receipt_version": ab.RUNTIME_CONTRACT,
                "producer_kind": provider_receipts.PROVIDER_PRODUCER_KIND,
                "run_id": challenge["run_id"],
                "task_id": challenge["task_id"],
                "stage": challenge["stage"],
                "worker_id": challenge["worker_id"],
                "invocation_id": challenge["invocation_id"],
                "nonce": challenge["nonce"],
                "dispatch_spec_sha256": challenge["dispatch_spec_sha256"],
                "provider_request_id": f"test-provider-{pair['request_id']}-{label}",
                "requested": {
                    "runtime_policy_id": requested_policy["runtime_policy_id"],
                    "model": requested_policy["model"],
                    "service_tier": requested_policy["service_tier"],
                    "reasoning_effort": requested_policy["reasoning_effort"],
                    "agent_type": requested_policy["agent_type"],
                    "context_budget_tokens": requested_policy["context_budget_tokens"],
                    "max_output_tokens": requested_policy["max_output_tokens"],
                },
                "observed": {
                    "resolved_model": {
                        "value": "synthetic-resolved-model",
                        "source": "provider_response",
                    },
                    "service_tier": {"value": "test-tier", "source": "provider_response"},
                    "reasoning_effort": {
                        "value": "test-effort",
                        "source": "provider_response",
                    },
                    "input_tokens": {
                        "value": 100 + (1 if label == "X" else 2),
                        "source": "provider_response",
                    },
                    "output_tokens": {"value": 50, "source": "provider_response"},
                    "total_tokens": {
                        "value": 150 + (1 if label == "X" else 2),
                        "source": "provider_response",
                    },
                    "elapsed_ms": {
                        "value": 1000 + (1 if label == "X" else 2),
                        "source": "host_monotonic",
                    },
                },
                "started_at": "2026-07-31T00:00:00Z",
                "finished_at": "2026-07-31T00:00:02Z",
                "artifact": {
                    "path": candidate["author_output_rel"],
                    "sha256": provider_receipts.sha256_file(author_path),
                    "size_bytes": author_path.stat().st_size,
                },
                "attestation": {
                    "scheme": "ed25519",
                    "key_id": "stage-b-test-host",
                    "signature": "ed25519:" + base64.b64encode(b"0" * 64).decode("ascii"),
                },
            }
            receipt = _sign_provider_receipt(receipt)
            receipt_path.write_text(
                json.dumps(receipt, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
                encoding="utf-8",
            )


def _seal(tmp_path: Path) -> tuple[dict, Path]:
    plan, plan_path = _prepare(tmp_path)
    artifact_root = tmp_path / "artifacts"
    _write_author_artifacts(plan, artifact_root)
    sealed_dir = tmp_path / "sealed"
    condition = ab.seal_stage_b(
        plan_path,
        artifact_root=artifact_root,
        out_dir=sealed_dir,
        provider_key_resolver=_provider_key_resolver,
    )
    return condition, sealed_dir / "condition-manifest.json"


def _judge_sheets(
    condition: dict,
    root: Path,
    *,
    enhanced_scores: dict[str, int] | None = None,
    fatal_request: str | None = None,
) -> list[Path]:
    enhanced_scores = enhanced_scores or {key: 3 for key in ab.SCORE_KEYS}
    baseline_scores = {key: 2 for key in ab.SCORE_KEYS}
    paths = []
    for index, role in enumerate(ab.JUDGE_ROLES, start=1):
        cases = []
        for pair in condition["pairs"]:
            treatment_to_label = {
                treatment: label for label, treatment in pair["mapping"].items()
            }
            baseline_label = treatment_to_label["baseline"]
            enhanced_label = treatment_to_label["enhanced"]
            candidates = {}
            for label in ab.BLIND_LABELS:
                scores = enhanced_scores if label == enhanced_label else baseline_scores
                fatal_defects = []
                if fatal_request == pair["request_id"] and label == enhanced_label and index == 1:
                    fatal_defects.append(
                        {
                            "code": "UNSUPPORTED_CORE_CLAIM",
                            "severity": "FATAL",
                            "summary": "Synthetic fatal defect used only by this unit test.",
                            "evidence_locator": "candidate paragraph 1",
                        }
                    )
                candidates[label] = {
                    "scores": dict(scores),
                    "fatal_defects": fatal_defects,
                    "rationale": "Synthetic schema-valid unit-test rationale.",
                }
            x_total = sum(candidates["X"]["scores"].values())
            y_total = sum(candidates["Y"]["scores"].values())
            winner = "X" if x_total > y_total else "Y" if y_total > x_total else "TIE"
            cases.append(
                {
                    "request_id": pair["request_id"],
                    "candidates": candidates,
                    "winner": winner,
                    "winner_rationale": "Winner follows the frozen Q1-Q8 total.",
                }
            )
        sheet = {
            "schema_version": ab.JUDGE_CONTRACT,
            "rubric_version": "research-capability-overlay-stage-b-rubric/v1",
            "judge_id": f"synthetic-judge-{index}",
            "judge_role": role,
            "packet_sha256": condition["blind_packet"]["sha256"],
            "blindness_attestation": {
                "condition_mapping_not_seen": True,
                "other_judge_sheets_not_seen": True,
                "author_runtime_receipts_not_seen": True,
            },
            "cases": cases,
            "overall_notes": "Synthetic unit-test sheet; not Stage-B evidence.",
        }
        path = root / f"judge-{index}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(sheet, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
        paths.append(path)
    return paths


def test_frozen_holdout_manifest_is_exactly_twenty_and_diverse():
    manifest = json.loads(ab.DEFAULT_REQUEST_MANIFEST.read_text(encoding="utf-8"))
    requests = ab.validate_request_manifest(manifest)
    assert len(requests) == 20
    assert len({item["domain"] for item in requests.values()}) >= 5
    assert len({item["task_type"] for item in requests.values()}) >= 4
    assert all(item["source_packet"]["status"] == "SYNTHETIC_FROZEN_FIXTURE" for item in requests.values())
    invalid = dict(manifest)
    invalid["stage_a_prompt_sha256"] = []
    with pytest.raises(ab.OverlayABEvalError, match="five unique Stage-A"):
        ab.validate_request_manifest(invalid)


def test_s2_overlay_requires_complete_evidence_matrix_and_unverified_fallback():
    catalog = load_overlay_catalog()
    overlay = next(
        item
        for item in catalog["overlays"]
        if item["overlay_id"] == "cross_domain_mechanism_translation"
    )
    contract_text = " ".join([overlay["summary"], *overlay["non_goals"]])
    for field in (
        "source_ref",
        "borrowed_principle",
        "target_mapping",
        "preserved_and_broken_assumptions",
        "evidence_status",
        "prior_art_collision_status",
        "falsifier",
        "UNVERIFIED",
    ):
        assert field in contract_text


def test_prepare_is_evaluation_only_and_does_not_call_external_operations(
    tmp_path, monkeypatch
):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("external operation attempted")

    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(urllib.request, "urlopen", forbidden)
    plan, plan_path = _prepare(tmp_path)
    assert plan["evaluation_state"] == "PREPARED_NOT_RUN"
    assert len(plan["pairs"]) == 20
    assert plan["author_runtime_policy"] == TEST_AUTHOR_RUNTIME_POLICY
    assert len(plan["author_runtime_policy_sha256"]) == 64
    assert plan["safety"] == {
        "network": "DENY",
        "model_execution": False,
        "third_party_execution": False,
        "production_entry_modified": False,
    }
    assert _sha256(plan_path) == (plan_path.parent / "dispatch-plan.sha256").read_text().strip()
    for pair in plan["pairs"]:
        assert set(pair["mapping"].values()) == {"baseline", "enhanced"}
        enhanced = next(
            item for item in pair["candidates"].values() if item["treatment"] == "enhanced"
        )
        assert enhanced["overlay_ids"]
        for candidate in pair["candidates"].values():
            assert candidate["author_runtime_policy"] == TEST_AUTHOR_RUNTIME_POLICY
            challenge = candidate["provider_receipt_challenge"]
            assert challenge["run_id"] == plan["evaluation_id"]
            assert challenge["artifact_path"] == candidate["author_output_rel"]
            assert challenge["dispatch_spec_sha256"].startswith("sha256:")


def test_prepare_requires_explicit_global_runtime_policy_and_binds_it_to_challenges(tmp_path):
    with pytest.raises(ab.OverlayABEvalError, match="author runtime policy.*schema"):
        ab.prepare_stage_b(out_dir=tmp_path / "missing-policy")

    first = ab.prepare_stage_b(
        out_dir=tmp_path / "first",
        author_runtime_policy=TEST_AUTHOR_RUNTIME_POLICY,
    )
    changed_policy = dict(TEST_AUTHOR_RUNTIME_POLICY)
    changed_policy["max_output_tokens"] = 2048
    changed_policy["runtime_policy_id"] = "stage-b-test-policy-v2"
    second = ab.prepare_stage_b(
        out_dir=tmp_path / "second",
        author_runtime_policy=changed_policy,
    )
    first_candidate = first["pairs"][0]["candidates"]["X"]
    second_candidate = second["pairs"][0]["candidates"]["X"]
    assert first["evaluation_id"] != second["evaluation_id"]
    assert (
        first_candidate["provider_receipt_challenge"]["dispatch_spec_sha256"]
        != second_candidate["provider_receipt_challenge"]["dispatch_spec_sha256"]
    )


def test_prepare_refuses_to_overwrite_immutable_plan(tmp_path):
    _prepare(tmp_path)
    with pytest.raises(ab.OverlayABEvalError, match="overwrite immutable"):
        ab.prepare_stage_b(
            out_dir=tmp_path / "prepared",
            author_runtime_policy=TEST_AUTHOR_RUNTIME_POLICY,
        )


def test_seal_validates_schema_hash_bindings_and_runtime_parity(tmp_path):
    condition, condition_path = _seal(tmp_path)
    schema = json.loads(ab.CONDITION_SCHEMA.read_text(encoding="utf-8"))
    Draft202012Validator(schema).validate(condition)
    assert condition["evaluation_state"] == "SEALED_AWAITING_JUDGES"
    assert len(condition["pairs"]) == 20
    assert all(pair["runtime_parity"] == "PASS" for pair in condition["pairs"])
    assert condition["author_runtime_policy"] == TEST_AUTHOR_RUNTIME_POLICY
    assert condition["global_runtime_parity"] == "PASS"
    assert condition["global_observed_runtime"] == {
        "resolved_model": "synthetic-resolved-model",
        "service_tier": "test-tier",
        "reasoning_effort": "test-effort",
    }
    packet = condition_path.parent / condition["blind_packet"]["path"]
    assert _sha256(packet) == condition["blind_packet"]["sha256"]


@pytest.mark.parametrize(
    ("mutation", "match"),
    [
        ("missing", "missing author artifact"),
        ("policy", "frozen global author runtime policy"),
        ("usage", "signed provider-attested.*schema BLOCK"),
        ("path", "artifact path does not match"),
    ],
)
def test_seal_fails_closed_on_missing_or_noncomparable_receipts(tmp_path, mutation, match):
    plan, plan_path = _prepare(tmp_path)
    artifact_root = tmp_path / "artifacts"
    _write_author_artifacts(plan, artifact_root)
    pair = plan["pairs"][0]
    candidate = pair["candidates"]["X"]
    receipt_path = artifact_root / candidate["runtime_receipt_rel"]
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    if mutation == "missing":
        receipt_path.unlink()
    elif mutation == "policy":
        receipt["requested"]["runtime_policy_id"] = "different-policy"
        receipt_path.write_text(json.dumps(_sign_provider_receipt(receipt)), encoding="utf-8")
    elif mutation == "usage":
        receipt["observed"]["input_tokens"]["source"] = "estimated"
        receipt_path.write_text(json.dumps(_sign_provider_receipt(receipt)), encoding="utf-8")
    else:
        receipt["artifact"]["path"] = "authors/wrong.md"
        receipt_path.write_text(json.dumps(_sign_provider_receipt(receipt)), encoding="utf-8")
    with pytest.raises(ab.OverlayABEvalError, match=match):
        ab.seal_stage_b(
            plan_path,
            artifact_root=artifact_root,
            out_dir=tmp_path / "sealed",
            provider_key_resolver=_provider_key_resolver,
        )


def test_seal_rejects_cross_pair_runtime_drift_even_when_each_xy_pair_matches(tmp_path):
    plan, plan_path = _prepare(tmp_path)
    artifact_root = tmp_path / "artifacts"
    _write_author_artifacts(plan, artifact_root)
    # Drift both candidates in a later pair.  The historical pair-only check
    # would pass because X and Y still agree with one another.
    pair = plan["pairs"][1]
    for label in ab.BLIND_LABELS:
        candidate = pair["candidates"][label]
        receipt_path = artifact_root / candidate["runtime_receipt_rel"]
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        receipt["observed"]["resolved_model"]["value"] = "synthetic-drifted-model"
        receipt_path.write_text(
            json.dumps(_sign_provider_receipt(receipt)),
            encoding="utf-8",
        )
    with pytest.raises(ab.OverlayABEvalError, match="across all 40 receipts"):
        ab.seal_stage_b(
            plan_path,
            artifact_root=artifact_root,
            out_dir=tmp_path / "sealed",
            provider_key_resolver=_provider_key_resolver,
        )


def test_seal_rejects_legacy_plan_without_global_policy_or_challenges(tmp_path):
    plan, plan_path = _prepare(tmp_path)
    plan["schema_version"] = "research-capability-overlay-stage-b-dispatch/v1"
    plan.pop("author_runtime_policy")
    plan.pop("author_runtime_policy_sha256")
    for pair in plan["pairs"]:
        for candidate in pair["candidates"].values():
            candidate.pop("author_runtime_policy")
            candidate.pop("provider_receipt_challenge")
    plan_path.write_text(json.dumps(plan), encoding="utf-8")
    plan_path.with_name("dispatch-plan.sha256").write_text(
        _sha256(plan_path) + "\n", encoding="ascii"
    )
    with pytest.raises(ab.OverlayABEvalError, match="legacy.*fresh prepare"):
        ab.seal_stage_b(
            plan_path,
            artifact_root=tmp_path / "artifacts",
            out_dir=tmp_path / "sealed",
            provider_key_resolver=_provider_key_resolver,
        )


def test_seal_rejects_dispatch_path_escape(tmp_path):
    plan, plan_path = _prepare(tmp_path)
    plan["pairs"][0]["candidates"]["X"]["author_output_rel"] = "../escape.md"
    plan_path.write_text(json.dumps(plan), encoding="utf-8")
    plan_path.with_name("dispatch-plan.sha256").write_text(_sha256(plan_path) + "\n", encoding="ascii")
    with pytest.raises(ab.OverlayABEvalError, match="escapes the artifact root"):
        ab.seal_stage_b(plan_path, artifact_root=tmp_path / "artifacts", out_dir=tmp_path / "sealed")


def test_reconcile_applies_preregistered_paired_gate(tmp_path):
    condition, condition_path = _seal(tmp_path)
    judges = _judge_sheets(condition, tmp_path / "judges")
    report = ab.reconcile_stage_b(condition_path, judge_paths=judges)
    assert report["evaluation_state"] == "PAIRED_EVALUATION_PASS"
    assert report["pair_count"] == 20
    assert report["judge_count"] == 3
    assert report["primary"]["mean_paired_difference_points"] == 8.0
    assert report["primary"]["paired_bootstrap_interval"] == [8.0, 8.0]
    assert report["primary"]["exact_two_sided_sign_flip_p"] < 0.001
    assert report["failure_cases"] == []


def test_reconcile_rejects_winner_that_conflicts_with_scores(tmp_path):
    condition, condition_path = _seal(tmp_path)
    judges = _judge_sheets(condition, tmp_path / "judges")
    sheet = json.loads(judges[0].read_text(encoding="utf-8"))
    sheet["cases"][0]["winner"] = "TIE"
    judges[0].write_text(json.dumps(sheet), encoding="utf-8")
    with pytest.raises(ab.OverlayABEvalError, match="winner conflicts"):
        ab.reconcile_stage_b(condition_path, judge_paths=judges)


def test_reconcile_fails_on_core_regression_and_discloses_all_cases(tmp_path):
    condition, condition_path = _seal(tmp_path)
    scores = {key: 3 for key in ab.SCORE_KEYS}
    scores["Q1"] = 1
    judges = _judge_sheets(condition, tmp_path / "judges", enhanced_scores=scores)
    report = ab.reconcile_stage_b(condition_path, judge_paths=judges)
    assert report["evaluation_state"] == "PAIRED_EVALUATION_FAIL"
    regressions = [item for item in report["failure_cases"] if item["code"] == "CORE_DIMENSION_REGRESSION"]
    assert regressions == [{"code": "CORE_DIMENSION_REGRESSION", "dimension": "Q1", "observed": -1.0}]
    assert len(report["case_results"]) == 20


def test_reconcile_fails_on_fatal_defect_without_hiding_other_cases(tmp_path):
    condition, condition_path = _seal(tmp_path)
    judges = _judge_sheets(condition, tmp_path / "judges", fatal_request="HB-07")
    report = ab.reconcile_stage_b(condition_path, judge_paths=judges)
    assert report["evaluation_state"] == "PAIRED_EVALUATION_FAIL"
    assert any(item["code"] == "FATAL_DEFECT" for item in report["failure_cases"])
    assert len(report["case_results"]) == 20
    assert {item["request_id"] for item in report["fatal_defects"]} == {"HB-07"}


def test_reconcile_requires_three_unique_blind_roles_and_packet_hash(tmp_path):
    condition, condition_path = _seal(tmp_path)
    judges = _judge_sheets(condition, tmp_path / "judges")
    with pytest.raises(ab.OverlayABEvalError, match="exactly three"):
        ab.reconcile_stage_b(condition_path, judge_paths=judges[:2])
    sheet = json.loads(judges[2].read_text(encoding="utf-8"))
    sheet["packet_sha256"] = "0" * 64
    judges[2].write_text(json.dumps(sheet), encoding="utf-8")
    with pytest.raises(ab.OverlayABEvalError, match="different blind packet"):
        ab.reconcile_stage_b(condition_path, judge_paths=judges)
