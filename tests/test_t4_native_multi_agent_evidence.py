"""Integration evidence for the T4 research-agent upgrade example.

These tests bind the checked-in source decisions, real native-agent trace, blind
review, fail-closed repair history, and final targeted re-review.  They do not
run a model, contact a server, or turn the design-only example into evidence of
scientific effectiveness.
"""
from __future__ import annotations

import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from research_agent_teams.tools import native_dispatch_trace as native
from research_agent_teams.tools.mechanism_council import load_contract
from research_agent_teams.tools.research_capability_router import (
    load_external_source_lock,
)
from research_agent_teams.tools.validate_artifact import validate_payload


ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT / "projects" / "t4-scribble-m0-mechanism-eval"
NATIVE = PROJECT / "native-eval"
WORK_ORDERS = NATIVE / "work-orders"
COMPLETIONS = NATIVE / "completions"


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _orders(*ids: str) -> list[Path]:
    return [WORK_ORDERS / f"{identifier}.json" for identifier in ids]


def _completions(*ids: str) -> list[Path]:
    return [COMPLETIONS / f"{identifier}.json" for identifier in ids]


def _role_states(ids: tuple[str, ...]) -> dict[str, str]:
    return {
        _json(WORK_ORDERS / f"{identifier}.json")["role"]: native.APPLICABLE
        for identifier in ids
    }


def _utc(value: str) -> datetime:
    rendered = value[:-1] + "+00:00" if value.endswith("Z") else value
    rendered = re.sub(r"(\.\d{6})\d+(?=[+-]\d{2}:\d{2}$)", r"\1", rendered)
    parsed = datetime.fromisoformat(rendered)
    assert parsed.tzinfo is not None and parsed.utcoffset() is not None
    return parsed.astimezone(timezone.utc)


def test_source_phase1_selection_and_server_query_contract():
    source_lock = load_external_source_lock()
    assert source_lock["source_count"] == len(source_lock["sources"]) == 9
    assert source_lock["skill_count_total"] == 359
    assert sum(row["skill_count"] for row in source_lock["sources"]) == 359
    assert sum(len(row["source_artifacts"]) for row in source_lock["sources"]) == 45

    registry = _json(ROOT / "orchestrator" / "research_skill_integration_registry.json")
    capabilities = registry["capabilities"]
    assert registry["selection_scope"]["selected_capability_count"] == len(capabilities) == 25
    assert Counter(row["implementation_status"] for row in capabilities) == {
        "implemented": 20,
        "planned": 4,
        "rejected": 1,
    }
    assert {row["category"] for row in capabilities} == set(registry["category_order"])

    locked_artifacts = {
        (source["source_id"], artifact["path"], artifact["sha256"])
        for source in source_lock["sources"]
        for artifact in source["source_artifacts"]
    }
    assert all(
        (row["source_id"], row["path"], row["sha256"]) in locked_artifacts
        for row in capabilities
    )

    query = _json(ROOT / "server_monitor" / "query_contract.json")
    resources = {row["alias"]: row for row in query["resource_registry"]}
    assert set(resources) == {"primary_gpu", "secondary_gpu"}
    assert resources["primary_gpu"]["registered_hardware"]["gpus"] == [
        {"model": "NVIDIA RTX A6000", "count": 2, "memory_gib_each": 48}
    ]
    assert [gpu["model"] for gpu in resources["secondary_gpu"]["registered_hardware"]["gpus"]] == [
        "NVIDIA GeForce RTX 3090",
        "NVIDIA GeForce GTX 1080 Ti",
    ]
    assert all(row["current_task"] == "UNKNOWN" for row in resources.values())
    assert resources["secondary_gpu"]["status"]["statement"] == (
        "director reported resolved; live re-verification pending"
    )
    assert {row["id"] for row in query["required_checks"]} == {
        "identity",
        "gpu",
        "tmux_process",
        "project_run_campaign",
        "receipts_gates",
        "storage",
        "env_marker",
        "failure_duplicate_risk",
    }
    assert query["operations"]["query_status"]["grants_submit_job"] is False


def test_real_council_and_challenger_trace():
    council_ids = (
        "WO-MATH",
        "WO-DOMAIN",
        "WO-COGNITIVE",
        "WO-CURRICULUM",
        "WO-ENGINEERING",
        "WO-CAUSAL-R2",
        "WO-COMPILER",
    )
    trace = native.validate_dispatch_trace(
        PROJECT,
        work_orders=_orders(*council_ids),
        completions=_completions(*council_ids),
        expected_roles=_role_states(council_ids),
        executor_receipt_present=False,
    )
    assert trace["status"] == "PASS"
    assert trace["expected_role_count"] == trace["applicable_role_count"] == 7
    assert len(trace["agent_ids"]) == len(set(trace["agent_ids"])) == 7

    contract = load_contract()
    contract_roles = [row["role"] for row in contract["roles"]]
    contributor_roles = set(contract_roles) - {"hypothesis_compiler"}
    assert len(contributor_roles) == 6
    assert len(contract_roles) == 7  # five required perspectives + engineering + compiler

    bundle = _json(NATIVE / "candidates" / "council-bundle.json")
    assert validate_payload("mechanism_council_bundle", bundle) == []
    assert {row["role"] for row in bundle["contribution_receipts"]} == contributor_roles
    assert bundle["truth_boundary"]["execution_status"] == "DESIGN_ONLY"
    assert bundle["truth_boundary"]["result_claims_allowed"] is False
    assert bundle["truth_boundary"]["novelty_claim_allowed"] is False

    compiler = _json(WORK_ORDERS / "WO-COMPILER.json")
    contributor_ids = set(council_ids) - {"WO-COMPILER"}
    assert {row["work_order_id"] for row in compiler["dependencies"]} == contributor_ids
    for dependency in compiler["dependencies"]:
        completion = _json(COMPLETIONS / f"{dependency['work_order_id']}.json")
        assert dependency["output_sha256"] == completion["output"]["sha256"]

    challenger_ids = ("WO-CHALLENGER",)
    challenger_trace = native.validate_dispatch_trace(
        PROJECT,
        work_orders=_orders(*challenger_ids),
        completions=_completions(*challenger_ids),
        expected_roles=_role_states(challenger_ids),
        executor_receipt_present=False,
    )
    challenger = _json(WORK_ORDERS / "WO-CHALLENGER.json")
    assert challenger_trace["status"] == "PASS"
    assert challenger["dependencies"] == []
    assert challenger["agent_id"] not in trace["agent_ids"]
    assert challenger["input_packet_sha256"] == native.sha256_file(
        PROJECT / "inputs" / "frozen-brief.md"
    )

    causal_failure = _json(NATIVE / "failures" / "WO-CAUSAL.json")
    assert causal_failure["state"] == "ABANDONED_NO_OUTPUT"
    assert causal_failure["replacement_work_order_id"] == "WO-CAUSAL-R2"
    assert not (COMPLETIONS / "WO-CAUSAL.json").exists()


def test_preregistered_blind_three_judge_chain():
    precommit_ids = (
        "WO-JUDGE-DOMAIN-PRECOMMIT",
        "WO-JUDGE-METHODS-PRECOMMIT",
        "WO-JUDGE-EVIDENCE-PRECOMMIT",
    )
    precommit_files = [
        NATIVE / "reviews" / "commitments" / "domain_mechanism.json",
        NATIVE / "reviews" / "commitments" / "methods_statistics.json",
        NATIVE / "reviews" / "commitments" / "evidence_integrity.json",
    ]
    precommit_brief_sha = native.sha256_file(
        NATIVE / "sealed" / "review-precommit-brief.json"
    )
    panel = native.validate_review_precommit_panel(
        precommit_files,
        precommit_brief_sha256=precommit_brief_sha,
        evaluation_id="T4-SM0-BLIND-01",
    )
    assert panel["status"] == "PASS"
    assert len(panel["judge_ids"]) == 3
    assert native.validate_dispatch_trace(
        PROJECT,
        work_orders=_orders(*precommit_ids),
        completions=_completions(*precommit_ids),
        expected_roles=_role_states(precommit_ids),
        executor_receipt_present=False,
    )["status"] == "PASS"

    blind_packet = NATIVE / "sealed" / "blind-packet.json"
    _packet, packet_sha = native.validate_blind_packet_file(blind_packet)
    commitment_path = NATIVE / "sealed" / "mapping-commitment.json"
    commitment = native.validate_mapping_commitment(commitment_path)
    assert commitment["created_before_judge_dispatch"] is True

    review_ids = (
        "WO-JUDGE-DOMAIN-REVIEW",
        "WO-JUDGE-METHODS-REVIEW",
        "WO-JUDGE-EVIDENCE-REVIEW",
    )
    review_trace = native.validate_dispatch_trace(
        PROJECT,
        work_orders=_orders(*review_ids),
        completions=_completions(*review_ids),
        expected_roles=_role_states(review_ids),
        executor_receipt_present=False,
        external_work_orders=_orders(*precommit_ids),
        external_completions=_completions(*precommit_ids),
    )
    assert review_trace["status"] == "PASS"
    assert len(review_trace["agent_ids"]) == 3
    assert _utc(commitment["created_at"]) <= min(
        _utc(_json(path)["authorized_at"]) for path in _orders(*review_ids)
    )

    sheets = [
        NATIVE / "reviews" / "sheets" / "domain_mechanism.json",
        NATIVE / "reviews" / "sheets" / "methods_statistics.json",
        NATIVE / "reviews" / "sheets" / "evidence_integrity.json",
    ]
    report = native.reconcile_native_judges(
        blind_packet_path=blind_packet,
        judge_sheets=sheets,
    )
    stored = _json(NATIVE / "reviews" / "reconciliation.json")
    assert report["evaluation_state"] == stored["evaluation_state"] == "DESCRIPTIVE_REVIEW_PASS"
    assert report["inferential_statistics_claimed"] is stored[
        "inferential_statistics_claimed"
    ] is False
    assert report["winner_votes"] == stored["winner_votes"] == {"X": 3, "Y": 0, "TIE": 0}
    replicated = stored["replicated_substantive_findings"]
    assert {row["replication_key"] for row in replicated} == {
        "primary_endpoint_not_frozen",
        "no_m0_neutralization_not_frozen",
        "ambiguity_strata_not_frozen",
        "curriculum_schedule_not_frozen",
    }
    assert all(row["replication_count"] == 3 for row in replicated)
    assert all(row["meets_two_of_three_rule"] is True for row in replicated)

    reveal = native.validate_mapping_reveal(
        NATIVE / "sealed" / "mapping-reveal.json",
        commitment=commitment_path,
    )
    assert reveal["mapping"] == {"X": "challenger", "Y": "council"}
    assert len(reveal["judge_sheet_sha256_sorted"]) == 3
    assert all(_json(sheet)["packet_sha256"] == packet_sha for sheet in sheets)
    assert _utc(reveal["revealed_after_review_at"]) >= max(
        _utc(_json(path)["completed_at"]) for path in _completions(*review_ids)
    )


def test_fail_closed_repair_then_first_targeted_re_review_fail():
    failure = _json(NATIVE / "failures" / "WO-TARGETED-REPAIR.json")
    assert failure["state"] == "ABORTED_BEFORE_OUTPUT"
    assert failure["reason_code"] == "SOURCE_HASH_MISMATCH_AFTER_DISPATCH"
    assert failure["output_absent_at_abort"] is True
    assert failure["observed"]["sha256"] == native.sha256_file(
        NATIVE / "reviews" / "reconciliation.json"
    )
    assert not (NATIVE / "candidates" / "council-repaired.md").exists()
    assert not (COMPLETIONS / "WO-TARGETED-REPAIR.json").exists()

    repair_packet = _json(NATIVE / "sealed" / "repair-packet-r2.json")
    assert repair_packet["recovery_of"] == "WO-TARGETED-REPAIR"
    assert repair_packet["review_evidence"]["sha256"] == native.sha256_file(
        NATIVE / "reviews" / "reconciliation.json"
    )

    predecessor_ids = ("WO-TARGETED-REPAIR-R2",)
    review_ids = ("WO-TARGETED-RE-REVIEW",)
    trace = native.validate_dispatch_trace(
        PROJECT,
        work_orders=_orders(*review_ids),
        completions=_completions(*review_ids),
        expected_roles=_role_states(review_ids),
        executor_receipt_present=False,
        external_work_orders=_orders(*predecessor_ids),
        external_completions=_completions(*predecessor_ids),
    )
    assert trace["status"] == "PASS"

    review = native.validate_targeted_re_review(
        NATIVE / "reviews" / "targeted-re-review.json",
        repair_packet_sha256=native.sha256_file(NATIVE / "sealed" / "repair-packet-r2.json"),
        source_candidate_sha256=native.sha256_file(NATIVE / "candidates" / "council.md"),
        repaired_candidate_sha256=native.sha256_file(
            NATIVE / "candidates" / "council-repaired-r2.md"
        ),
        reconciliation_sha256=native.sha256_file(NATIVE / "reviews" / "reconciliation.json"),
        forbidden_agent_ids={"/root/t4_repair_author_r2"},
    )
    assert Counter(row["status"] for row in review["reviewed_repairs"]) == {
        "CLOSED": 2,
        "PARTIAL": 2,
    }
    assert all(review["regression_checks"].values())
    assert review["fatal_defects"] == []
    assert review["overall_verdict"] == "FAIL"


def test_r3_second_independent_re_review_and_truth_boundary():
    repair_packet = _json(NATIVE / "sealed" / "repair-packet-r3.json")
    assert {row["replication_key"] for row in repair_packet["required_repairs"]} == {
        "ambiguity_strata_not_frozen",
        "curriculum_schedule_not_frozen",
    }
    assert set(repair_packet["first_targeted_re_review"]["partial_repairs"]) == {
        "ambiguity_strata_not_frozen",
        "curriculum_schedule_not_frozen",
    }

    r3_ids = ("WO-TARGETED-REPAIR-R3",)
    r3_predecessors = ("WO-TARGETED-REPAIR-R2", "WO-TARGETED-RE-REVIEW")
    assert native.validate_dispatch_trace(
        PROJECT,
        work_orders=_orders(*r3_ids),
        completions=_completions(*r3_ids),
        expected_roles=_role_states(r3_ids),
        executor_receipt_present=False,
        external_work_orders=_orders(*r3_predecessors),
        external_completions=_completions(*r3_predecessors),
    )["status"] == "PASS"

    final_ids = ("WO-TARGETED-RE-REVIEW-R2",)
    final_predecessors = (
        "WO-TARGETED-REPAIR-R2",
        "WO-TARGETED-RE-REVIEW",
        "WO-TARGETED-REPAIR-R3",
    )
    final_trace = native.validate_dispatch_trace(
        PROJECT,
        work_orders=_orders(*final_ids),
        completions=_completions(*final_ids),
        expected_roles=_role_states(final_ids),
        executor_receipt_present=False,
        external_work_orders=_orders(*final_predecessors),
        external_completions=_completions(*final_predecessors),
    )
    assert final_trace["status"] == "PASS"

    packet = _json(NATIVE / "sealed" / "targeted-re-review-packet-r2.json")
    forbidden = set(packet["forbidden_agent_ids"])
    review = native.validate_targeted_re_review(
        NATIVE / "reviews" / "targeted-re-review-r2.json",
        repair_packet_sha256=packet["repair_packet"]["sha256"],
        source_candidate_sha256=packet["source_candidate"]["sha256"],
        repaired_candidate_sha256=packet["repaired_candidate"]["sha256"],
        reconciliation_sha256=packet["reconciliation"]["sha256"],
        forbidden_agent_ids=forbidden,
    )
    assert review["agent_id"] not in forbidden
    assert all(row["status"] == "CLOSED" for row in review["reviewed_repairs"])
    assert all(review["regression_checks"].values())
    assert review["fatal_defects"] == []
    assert review["overall_verdict"] == "PASS"
    assert "preliminary content check" in review["overall_rationale"]
    assert "not a new blind round" in review["overall_rationale"]

    source_manifest = _json(PROJECT / "inputs" / "source-manifest.json")
    assert source_manifest["truth_boundary"] == {
        "local_files_only": True,
        "server_query_performed": False,
        "gpu_experiment_performed": False,
        "scientific_result_allowed": False,
    }
    authorization = _json(NATIVE / "authorization.json")
    forbidden_text = "\n".join(authorization["forbidden"]).casefold()
    assert "connect to a server" in forbidden_text
    assert "run a gpu experiment" in forbidden_text
    assert "change the frozen pet/ct canonical" in forbidden_text
    assert "claim scientific effectiveness" in forbidden_text

    dry_run = _json(NATIVE / "preflight" / "contract-dry-run.json")
    assert dry_run["evidence_class"] == "NOT_SCIENTIFIC_EVIDENCE"
    assert dry_run["preflight_state"] == "PREFLIGHT_BLOCKED"
    assert dry_run["scientific_claims_allowed"] is False

    final_candidate = (NATIVE / "candidates" / "council-repaired-r3.md").read_text(
        encoding="utf-8"
    )
    assert "DESIGN_ONLY / NON_CITABLE / NO RESULTS" in final_candidate
    assert "`full` versus exhaustive `no_M0`" in final_candidate
    assert "Cross-attention remains future work only" in final_candidate
