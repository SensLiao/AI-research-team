from __future__ import annotations

import copy
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from research_agent_teams.tools import native_dispatch_trace as native


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _write(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")


def _write_at(path: Path, value: str, when: datetime) -> None:
    _write(path, value)
    timestamp_ns = int(when.timestamp() * 1_000_000_000)
    os.utime(path, ns=(timestamp_ns, timestamp_ns))


def _base_files(root: Path) -> None:
    _write(root / "sealed/input.md", "frozen input\n")
    _write(root / "scheduler/design-auth.json", '{"authorized":true}\n')
    _write(root / "scheduler/synthesis-auth.json", '{"authorized":true}\n')
    _write(root / "scheduler/analyze-na-auth.json", '{"authorized":true}\n')


def _trace(
    root: Path,
    *,
    second_agent_id: str = "agent-synth",
    second_task_name: str = "/root/native-synth",
    dependency_sha: str | None = None,
) -> tuple[list[dict], list[dict], dict[str, str], set[str]]:
    _base_files(root)
    base = datetime.now(timezone.utc) + timedelta(minutes=5)
    planner = native.create_work_order(
        root,
        run_id="native-run-1",
        work_order_id="wo-planner",
        stage="DESIGN",
        role="experiment-planner",
        applicability=native.APPLICABLE,
        agent_id="agent-plan",
        canonical_agent_task_name="/root/native-planner",
        input_packet_path="sealed/input.md",
        authorization_path="scheduler/design-auth.json",
        nonce="a" * 64,
        dependencies=[],
        expected_output_path="outputs/planner.md",
        authorized_at=_iso(base),
        recorded_at=_iso(base + timedelta(seconds=1)),
    )
    _write_at(
        root / "outputs/planner.md",
        "planner output\n",
        base + timedelta(seconds=3),
    )
    planner_completion = native.create_completion(
        root,
        work_order=planner,
        nonce_echo="a" * 64,
        started_at=_iso(base + timedelta(seconds=2)),
        completed_at=_iso(base + timedelta(seconds=4)),
        recorded_at=_iso(base + timedelta(seconds=5)),
    )

    synthesizer = native.create_work_order(
        root,
        run_id="native-run-1",
        work_order_id="wo-synth",
        stage="DESIGN",
        role="design-synthesizer",
        applicability=native.APPLICABLE,
        agent_id=second_agent_id,
        canonical_agent_task_name=second_task_name,
        input_packet_path="sealed/input.md",
        authorization_path="scheduler/synthesis-auth.json",
        nonce="b" * 64,
        dependencies=[{
            "work_order_id": "wo-planner",
            "role": "experiment-planner",
            "output_sha256": dependency_sha or planner_completion["output"]["sha256"],
        }],
        expected_output_path="outputs/synthesis.md",
        authorized_at=_iso(base + timedelta(seconds=6)),
        recorded_at=_iso(base + timedelta(seconds=7)),
    )
    _write_at(
        root / "outputs/synthesis.md",
        "synthesis output\n",
        base + timedelta(seconds=9),
    )
    synthesis_completion = native.create_completion(
        root,
        work_order=synthesizer,
        nonce_echo="b" * 64,
        started_at=_iso(base + timedelta(seconds=8)),
        completed_at=_iso(base + timedelta(seconds=10)),
        recorded_at=_iso(base + timedelta(seconds=11)),
    )

    analyzer_na = native.create_work_order(
        root,
        run_id="native-run-1",
        work_order_id="wo-analyze-na",
        stage="ANALYZE",
        role="result-analyzer",
        applicability=native.RESULT_ROLE_NO_EXECUTOR,
        agent_id=None,
        canonical_agent_task_name=None,
        input_packet_path="sealed/input.md",
        authorization_path="scheduler/analyze-na-auth.json",
        nonce="c" * 64,
        dependencies=[],
        expected_output_path=None,
        authorized_at=_iso(base + timedelta(seconds=12)),
        recorded_at=_iso(base + timedelta(seconds=13)),
    )
    analyzer_completion = native.create_completion(
        root,
        work_order=analyzer_na,
        nonce_echo="c" * 64,
        started_at=_iso(base + timedelta(seconds=14)),
        completed_at=_iso(base + timedelta(seconds=14)),
        recorded_at=_iso(base + timedelta(seconds=15)),
    )

    expected = {
        "experiment-planner": native.APPLICABLE,
        "design-synthesizer": native.APPLICABLE,
        "result-analyzer": native.RESULT_ROLE_NO_EXECUTOR,
    }
    return (
        [planner, synthesizer, analyzer_na],
        [planner_completion, synthesis_completion, analyzer_completion],
        expected,
        {"result-analyzer"},
    )


def _blind_packet(root: Path) -> tuple[dict, Path, str]:
    _write(root / "candidates/x.md", "candidate X\n")
    _write(root / "candidates/y.md", "candidate Y\n")
    packet = native.build_blind_packet(
        evaluation_id="native-eval-1",
        project_id="petct-residual-correction",
        case_id="SM0-01",
        request="Produce a scripts-only continuation decision.",
        source_packet_sha256="d" * 64,
        candidate_paths={
            "X": root / "candidates/x.md",
            "Y": root / "candidates/y.md",
        },
    )
    packet_path = root / "sealed/blind-packet.json"
    sealed = native.seal_blind_packet(packet_path, packet)
    return packet, packet_path, sealed["sha256"]


def _judge(
    packet: dict,
    packet_sha256: str,
    *,
    judge_id: str,
    judge_role: str,
    agent_id: str,
    task_name: str,
    finding_key: str,
    substantive: bool = True,
) -> dict:
    finding = {
        "finding_id": f"{judge_id}-f1",
        "replication_key": finding_key,
        "candidate": "Y",
        "kind": "SUBSTANTIVE_DESIGN" if substantive else "STYLE",
        "substantive": substantive,
        "severity": "HIGH" if substantive else "LOW",
        "summary": "The downstream gate is not bound to the canonical receipt.",
        "locator": "Y:section-next-step",
        "repair": "Bind the step to the canonical receipt SHA before dispatch.",
    }
    return {
        "schema_version": native.JUDGE_CONTRACT,
        "rubric_version": "native-content-quality-rubric/v1",
        "analysis_mode": "SINGLE_PROJECT_DESCRIPTIVE_ONLY",
        "inferential_statistics_claimed": False,
        "evaluation_id": packet["evaluation_id"],
        "project_id": packet["project_id"],
        "case_id": packet["case_id"],
        "judge_id": judge_id,
        "judge_role": judge_role,
        "agent_id": agent_id,
        "canonical_agent_task_name": task_name,
        "packet_sha256": packet_sha256,
        "blindness_attestation": {
            "condition_mapping_not_seen": True,
            "runtime_data_not_seen": True,
            "sibling_review_data_not_seen": True,
        },
        "runtime_usage": {"status": "UNOBSERVED"},
        "candidates": {
            "X": {
                "scores": {f"Q{i}": 3 for i in range(1, 9)},
                "fatal_defects": [],
                "rationale": "Grounded but less explicit.",
            },
            "Y": {
                "scores": {f"Q{i}": 4 for i in range(1, 9)},
                "fatal_defects": [],
                "rationale": "More explicit and safer.",
            },
        },
        "winner": "Y",
        "winner_rationale": "Y has the higher descriptive total.",
        "findings": [finding],
        "overall_notes": "Single-project descriptive judgment only.",
    }


def _three_judges(packet: dict, packet_sha256: str) -> list[dict]:
    return [
        _judge(
            packet,
            packet_sha256,
            judge_id="judge-domain",
            judge_role="domain_mechanism",
            agent_id="agent-judge-domain",
            task_name="/root/judge-domain",
            finding_key="receipt-gate-binding",
        ),
        _judge(
            packet,
            packet_sha256,
            judge_id="judge-methods",
            judge_role="methods_statistics",
            agent_id="agent-judge-methods",
            task_name="/root/judge-methods",
            finding_key="receipt-gate-binding",
        ),
        _judge(
            packet,
            packet_sha256,
            judge_id="judge-evidence",
            judge_role="evidence_integrity",
            agent_id="agent-judge-evidence",
            task_name="/root/judge-evidence",
            finding_key="different-finding",
        ),
    ]


def _precommit(*, judge_id: str, judge_role: str, agent_id: str, task_name: str) -> dict:
    return {
        "schema_version": native.PRECOMMIT_CONTRACT,
        "evaluation_id": "native-eval-1",
        "judge_id": judge_id,
        "judge_role": judge_role,
        "agent_id": agent_id,
        "canonical_agent_task_name": task_name,
        "precommit_brief_sha256": "a" * 64,
        "blindness_attestation": {
            "candidates_not_seen": True,
            "condition_mapping_not_seen": True,
            "runtime_data_not_seen": True,
            "sibling_review_data_not_seen": True,
        },
        "priority_failure_modes": [
            {"replication_key": "primary_endpoint_not_frozen", "rationale": "Endpoint drift invalidates the comparison."},
            {"replication_key": "no_m0_neutralization_not_frozen", "rationale": "Residual M0 access defeats the ablation."},
            {"replication_key": "data_leakage_or_oracle_access", "rationale": "Oracle access invalidates held-out claims."},
        ],
        "rejection_conditions": [
            "Any fatal defect remains.",
            "Any core dimension is below three.",
            "The patient-level estimand is absent.",
        ],
        "score_policy": {
            "core_dimensions": ["Q1", "Q3", "Q4", "Q6"],
            "minimum_core_score_each": 3,
            "fatal_defects_allowed": 0,
            "winner_rule": "Winner follows the larger Q1-Q8 total; equal totals are a tie.",
        },
        "declared_at": "2026-08-01T00:00:00Z",
        "runtime_usage": {"status": "UNOBSERVED"},
    }


def _three_precommits() -> list[dict]:
    return [
        _precommit(
            judge_id="judge-domain",
            judge_role="domain_mechanism",
            agent_id="agent-domain",
            task_name="/root/judge-domain",
        ),
        _precommit(
            judge_id="judge-methods",
            judge_role="methods_statistics",
            agent_id="agent-methods",
            task_name="/root/judge-methods",
        ),
        _precommit(
            judge_id="judge-evidence",
            judge_role="evidence_integrity",
            agent_id="agent-evidence",
            task_name="/root/judge-evidence",
        ),
    ]


def test_schemas_are_valid_strict_utf8_and_usage_cannot_be_faked():
    for path in (
        native.WORK_ORDER_SCHEMA,
        native.COMPLETION_SCHEMA,
        native.JUDGE_SCHEMA,
        native.PRECOMMIT_SCHEMA,
    ):
        text = path.read_text(encoding="utf-8")
        Draft202012Validator.check_schema(json.loads(text))
        assert "\ufffd" not in text

    work_schema = json.loads(native.WORK_ORDER_SCHEMA.read_text(encoding="utf-8"))
    assert work_schema["$defs"]["runtimeUsage"]["properties"]["status"]["const"] == "UNOBSERVED"
    assert work_schema["$defs"]["runtimeUsage"]["additionalProperties"] is False


def test_three_reviewers_precommit_before_candidate_exposure():
    report = native.validate_review_precommit_panel(
        _three_precommits(),
        precommit_brief_sha256="a" * 64,
        evaluation_id="native-eval-1",
    )
    assert report == {
        "status": "PASS",
        "evaluation_id": "native-eval-1",
        "judge_roles": ["domain_mechanism", "evidence_integrity", "methods_statistics"],
        "judge_ids": ["judge-domain", "judge-evidence", "judge-methods"],
        "runtime_usage": {"status": "UNOBSERVED"},
    }


def test_precommit_accepts_valid_dotnet_seven_digit_iso_timestamp():
    row = _three_precommits()[0]
    row["declared_at"] = "2026-08-01T22:05:49.8514048+10:00"
    validated = native.validate_review_precommit(
        row,
        precommit_brief_sha256="a" * 64,
    )
    assert validated["declared_at"] == "2026-08-01T22:05:49.8514048+10:00"


def test_precommit_panel_blocks_candidate_exposure_or_duplicate_identity():
    rows = _three_precommits()
    rows[0]["blindness_attestation"]["candidates_not_seen"] = False
    with pytest.raises(native.NativeDispatchTraceError, match="schema validation"):
        native.validate_review_precommit_panel(
            rows,
            precommit_brief_sha256="a" * 64,
            evaluation_id="native-eval-1",
        )

    rows = _three_precommits()
    rows[1]["agent_id"] = rows[0]["agent_id"]
    with pytest.raises(native.NativeDispatchTraceError, match="unique agent_id"):
        native.validate_review_precommit_panel(
            rows,
            precommit_brief_sha256="a" * 64,
            evaluation_id="native-eval-1",
        )


def test_mapping_reveal_opens_prejudge_commitment_and_binds_three_sheets(tmp_path):
    secret = {
        "mapping": {"X": "challenger", "Y": "council"},
        "salt": "f" * 64,
    }
    commitment = {
        "schema_version": native.MAPPING_COMMITMENT_CONTRACT,
        "evaluation_id": "native-eval-1",
        "project_id": "project",
        "case_id": "case",
        "algorithm": "sha256(canonical_json({mapping,salt}))",
        "mapping_labels": ["X", "Y"],
        "commitment_sha256": native.sha256_value(secret),
        "source_packet_sha256": "a" * 64,
        "candidate_source_sha256_sorted": ["b" * 64, "c" * 64],
        "created_before_judge_dispatch": True,
        "created_at": "2026-08-01T00:00:00Z",
    }
    commitment_path = tmp_path / "commitment.json"
    _write(commitment_path, json.dumps(commitment, sort_keys=True) + "\n")
    reveal = {
        "schema_version": native.MAPPING_REVEAL_CONTRACT,
        "evaluation_id": "native-eval-1",
        "project_id": "project",
        "case_id": "case",
        "mapping": secret["mapping"],
        "salt": secret["salt"],
        "commitment_sha256": commitment["commitment_sha256"],
        "commitment_file_sha256": native.sha256_file(commitment_path),
        "judge_sheet_sha256_sorted": ["d" * 64, "e" * 64, "f" * 64],
        "revealed_after_review_at": "2026-08-01T01:00:00Z",
    }
    assert native.validate_mapping_reveal(
        reveal,
        commitment=commitment_path,
    )["mapping"] == {"X": "challenger", "Y": "council"}

    tampered = copy.deepcopy(reveal)
    tampered["mapping"] = {"X": "council", "Y": "challenger"}
    with pytest.raises(native.NativeDispatchTraceError, match="does not open"):
        native.validate_mapping_reveal(tampered, commitment=commitment_path)


def test_targeted_re_review_requires_four_closed_repairs_no_regression_and_fresh_agent():
    review = {
        "schema_version": native.TARGETED_RE_REVIEW_CONTRACT,
        "evaluation_id": "T4-SM0-BLIND-01",
        "reviewer_id": "repair-reviewer",
        "agent_id": "/root/fresh-reviewer",
        "canonical_agent_task_name": "/root/fresh-reviewer",
        "repair_packet_sha256": "a" * 64,
        "source_candidate_sha256": "b" * 64,
        "repaired_candidate_sha256": "c" * 64,
        "reconciliation_sha256": "d" * 64,
        "reviewed_repairs": [
            {"replication_key": key, "status": "CLOSED", "evidence_locator": f"section:{key}", "assessment": "The previously open contract is now explicit and frozen."}
            for key in (
                "primary_endpoint_not_frozen",
                "no_m0_neutralization_not_frozen",
                "ambiguity_strata_not_frozen",
                "curriculum_schedule_not_frozen",
            )
        ],
        "regression_checks": {
            "six_joint_ontology_unchanged": True,
            "simple_first_primary_unchanged": True,
            "cross_attention_still_deferred": True,
            "oof_not_regenerated": True,
            "existing_experiments_unchanged": True,
            "truth_boundary_preserved": True,
        },
        "fatal_defects": [],
        "overall_verdict": "PASS",
        "overall_rationale": "All four replicated defects are closed without scope drift.",
        "reviewed_at": "2026-08-01T02:00:00Z",
        "runtime_usage": {"status": "UNOBSERVED"},
    }
    assert native.validate_targeted_re_review(
        review,
        repair_packet_sha256="a" * 64,
        source_candidate_sha256="b" * 64,
        repaired_candidate_sha256="c" * 64,
        reconciliation_sha256="d" * 64,
        forbidden_agent_ids={"/root/repair-author"},
    )["overall_verdict"] == "PASS"

    partial = copy.deepcopy(review)
    partial["reviewed_repairs"][0]["status"] = "PARTIAL"
    with pytest.raises(native.NativeDispatchTraceError, match="verdict conflicts"):
        native.validate_targeted_re_review(
            partial,
            repair_packet_sha256="a" * 64,
            source_candidate_sha256="b" * 64,
            repaired_candidate_sha256="c" * 64,
            reconciliation_sha256="d" * 64,
        )

    with pytest.raises(native.NativeDispatchTraceError, match="fresh agent"):
        native.validate_targeted_re_review(
            review,
            repair_packet_sha256="a" * 64,
            source_candidate_sha256="b" * 64,
            repaired_candidate_sha256="c" * 64,
            reconciliation_sha256="d" * 64,
            forbidden_agent_ids={"/root/fresh-reviewer"},
        )

def test_valid_trace_proves_role_coverage_unique_ownership_dag_hashes_and_typed_na(tmp_path):
    orders, completions, expected, result_roles = _trace(tmp_path)
    report = native.validate_dispatch_trace(
        tmp_path,
        work_orders=orders,
        completions=completions,
        expected_roles=expected,
        result_roles=result_roles,
        executor_receipt_present=False,
    )
    assert report["status"] == "PASS"
    assert report["applicable_role_count"] == 2
    assert report["typed_n_a_role_count"] == 1
    assert report["runtime_usage"] == {"status": "UNOBSERVED"}
    assert len(report["agent_ids"]) == 2


def test_later_phase_can_bind_prior_completion_and_reuse_same_reviewer_identity(tmp_path):
    orders, completions, _expected, _result_roles = _trace(
        tmp_path,
        second_agent_id="agent-plan",
        second_task_name="/root/native-planner",
    )
    report = native.validate_dispatch_trace(
        tmp_path,
        work_orders=[orders[1]],
        completions=[completions[1]],
        expected_roles={"design-synthesizer": native.APPLICABLE},
        executor_receipt_present=False,
        external_work_orders=[orders[0]],
        external_completions=[completions[0]],
    )
    assert report["status"] == "PASS"
    assert report["external_dependency_role_count"] == 1
    assert report["agent_ids"] == ["agent-plan"]


def test_preexisting_fixture_cannot_become_a_new_work_order_output(tmp_path):
    _base_files(tmp_path)
    _write(tmp_path / "outputs/planner.md", "fixture\n")
    now = datetime.now(timezone.utc)
    with pytest.raises(native.NativeDispatchTraceError, match="preexisting output"):
        native.create_work_order(
            tmp_path,
            run_id="run",
            work_order_id="wo",
            stage="DESIGN",
            role="planner",
            applicability=native.APPLICABLE,
            agent_id="agent",
            canonical_agent_task_name="/root/planner",
            input_packet_path="sealed/input.md",
            authorization_path="scheduler/design-auth.json",
            nonce="a" * 64,
            dependencies=[],
            expected_output_path="outputs/planner.md",
            authorized_at=_iso(now),
            recorded_at=_iso(now + timedelta(seconds=1)),
        )


def test_missing_role_duplicate_agent_and_wrong_dependency_hash_block(tmp_path):
    orders, completions, expected, result_roles = _trace(tmp_path / "missing")
    with pytest.raises(native.NativeDispatchTraceError, match="role coverage"):
        native.validate_dispatch_trace(
            tmp_path / "missing",
            work_orders=orders[:-1],
            completions=completions[:-1],
            expected_roles=expected,
            result_roles=result_roles,
            executor_receipt_present=False,
        )

    orders, completions, expected, result_roles = _trace(
        tmp_path / "duplicate",
        second_agent_id="agent-plan",
    )
    with pytest.raises(native.NativeDispatchTraceError, match="unique agent ownership"):
        native.validate_dispatch_trace(
            tmp_path / "duplicate",
            work_orders=orders,
            completions=completions,
            expected_roles=expected,
            result_roles=result_roles,
            executor_receipt_present=False,
        )

    orders, completions, expected, result_roles = _trace(
        tmp_path / "dependency",
        dependency_sha="0" * 64,
    )
    with pytest.raises(native.NativeDispatchTraceError, match="dependency output SHA"):
        native.validate_dispatch_trace(
            tmp_path / "dependency",
            work_orders=orders,
            completions=completions,
            expected_roles=expected,
            result_roles=result_roles,
            executor_receipt_present=False,
        )

    orders, completions, expected, result_roles = _trace(tmp_path / "cross-run")
    orders[1]["run_id"] = "other-run"
    completions[1] = native.create_completion(
        tmp_path / "cross-run",
        work_order=orders[1],
        nonce_echo=orders[1]["nonce"],
        started_at=completions[1]["started_at"],
        completed_at=completions[1]["completed_at"],
        recorded_at=completions[1]["recorded_at"],
    )
    with pytest.raises(native.NativeDispatchTraceError, match="mix run_id"):
        native.validate_dispatch_trace(
            tmp_path / "cross-run",
            work_orders=orders,
            completions=completions,
            expected_roles=expected,
            result_roles=result_roles,
            executor_receipt_present=False,
        )


def test_output_tamper_nonce_and_completion_before_authorization_block(tmp_path):
    orders, completions, expected, result_roles = _trace(tmp_path)
    _write(tmp_path / "outputs/planner.md", "tampered after completion\n")
    with pytest.raises(native.NativeDispatchTraceError, match="output SHA-256"):
        native.validate_dispatch_trace(
            tmp_path,
            work_orders=orders,
            completions=completions,
            expected_roles=expected,
            result_roles=result_roles,
            executor_receipt_present=False,
        )

    clean_root = tmp_path / "nonce"
    orders, _completions, _expected, _result_roles = _trace(clean_root)
    base = datetime.now(timezone.utc) + timedelta(minutes=10)
    with pytest.raises(native.NativeDispatchTraceError, match="nonce echo"):
        native.create_completion(
            clean_root,
            work_order=orders[0],
            nonce_echo="z" * 64,
            started_at=_iso(base),
            completed_at=_iso(base + timedelta(seconds=1)),
            recorded_at=_iso(base + timedelta(seconds=2)),
        )

    with pytest.raises(native.NativeDispatchTraceError, match="started before authorization"):
        native.create_completion(
            clean_root,
            work_order=orders[0],
            nonce_echo=orders[0]["nonce"],
            started_at="2000-01-01T00:00:00Z",
            completed_at="2000-01-01T00:00:01Z",
            recorded_at="2000-01-01T00:00:02Z",
        )


def test_no_executor_result_roles_must_be_typed_na(tmp_path):
    orders, completions, expected, result_roles = _trace(tmp_path)
    bad_expected = dict(expected)
    bad_expected["result-analyzer"] = native.APPLICABLE
    with pytest.raises(native.NativeDispatchTraceError, match="must be typed N/A"):
        native.validate_dispatch_trace(
            tmp_path,
            work_orders=orders,
            completions=completions,
            expected_roles=bad_expected,
            result_roles=result_roles,
            executor_receipt_present=False,
        )
    with pytest.raises(native.NativeDispatchTraceError, match="cannot be N/A"):
        native.validate_dispatch_trace(
            tmp_path,
            work_orders=orders,
            completions=completions,
            expected_roles=expected,
            result_roles=result_roles,
            executor_receipt_present=True,
        )


@pytest.mark.parametrize("forbidden_key", ["mapping", "runtime_usage", "sibling_reviews"])
def test_blind_packet_rejects_mapping_runtime_and_sibling_review_data(
    tmp_path, forbidden_key
):
    packet, _packet_path, _packet_sha = _blind_packet(tmp_path)
    contaminated = copy.deepcopy(packet)
    contaminated[forbidden_key] = {"secret": True}
    with pytest.raises(native.NativeDispatchTraceError, match="field contract"):
        native.validate_blind_packet(contaminated)


def test_three_unique_judges_share_packet_and_replicate_substantive_finding(tmp_path):
    packet, packet_path, packet_sha = _blind_packet(tmp_path)
    judges = _three_judges(packet, packet_sha)
    report = native.reconcile_native_judges(
        blind_packet_path=packet_path,
        judge_sheets=judges,
    )
    assert report["evaluation_state"] == "DESCRIPTIVE_REVIEW_PASS"
    assert report["inferential_statistics_claimed"] is False
    assert report["majority_winner"] == "Y"
    assert report["paired_delta_y_minus_x"]["values"] == [8, 8, 8]
    replicated = report["replicated_substantive_findings"]
    assert len(replicated) == 1
    assert replicated[0]["replication_count"] == 2
    assert replicated[0]["meets_two_of_three_rule"] is True
    assert len({judge["agent_id"] for judge in report["judges"]}) == 3
    assert {judge["sheet_hash_kind"] for judge in report["judges"]} == {"CANONICAL_VALUE"}


def test_judges_block_on_duplicate_agent_different_packet_or_missing_locator(tmp_path):
    packet, packet_path, packet_sha = _blind_packet(tmp_path)
    judges = _three_judges(packet, packet_sha)
    judges[1]["agent_id"] = judges[0]["agent_id"]
    with pytest.raises(native.NativeDispatchTraceError, match="unique agent ownership"):
        native.reconcile_native_judges(
            blind_packet_path=packet_path,
            judge_sheets=judges,
        )

    judges = _three_judges(packet, packet_sha)
    judges[1]["packet_sha256"] = "e" * 64
    with pytest.raises(native.NativeDispatchTraceError, match="different blind packet"):
        native.reconcile_native_judges(
            blind_packet_path=packet_path,
            judge_sheets=judges,
        )

    judges = _three_judges(packet, packet_sha)
    del judges[0]["findings"][0]["locator"]
    with pytest.raises(native.NativeDispatchTraceError, match="schema validation"):
        native.reconcile_native_judges(
            blind_packet_path=packet_path,
            judge_sheets=judges,
        )


def test_no_two_of_three_substantive_finding_blocks_descriptive_acceptance(tmp_path):
    packet, packet_path, packet_sha = _blind_packet(tmp_path)
    judges = _three_judges(packet, packet_sha)
    for index, judge in enumerate(judges):
        judge["findings"][0]["replication_key"] = f"unique-{index}"
    report = native.reconcile_native_judges(
        blind_packet_path=packet_path,
        judge_sheets=judges,
    )
    assert report["evaluation_state"] == "DESCRIPTIVE_REVIEW_BLOCKED"
    assert report["replicated_substantive_findings"] == []
    assert report["failure_cases"] == [{
        "code": "NO_REPLICATED_SUBSTANTIVE_FINDING",
        "required_distinct_judges": 2,
        "observed": 0,
    }]
