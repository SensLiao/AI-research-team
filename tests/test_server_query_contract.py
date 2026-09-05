from __future__ import annotations

import pytest

import json
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2] / "research_agent_teams"
WORKSPACE_ROOT = REPO_ROOT.parent
CONTRACT_PATH = REPO_ROOT / "server_monitor" / "query_contract.json"
PLATFORM_NOTES_PATH = REPO_ROOT / "server_monitor" / "PLATFORM-NOTES.md"
SKILL_PATH = WORKSPACE_ROOT / ".agents" / "skills" / "server-query" / "SKILL.md"


def _contract() -> dict:
    return json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))


def test_resource_registry_records_both_hardware_baselines_without_inventing_tasks():
    contract = _contract()
    resources = {item["alias"]: item for item in contract["resource_registry"]}
    assert set(resources) == {"primary_gpu", "secondary_gpu"}

    primary = resources["primary_gpu"]
    assert primary["resource_id"] == "server.honor.gpu"
    assert primary["registered_hardware"]["gpus"] == [{
        "model": "NVIDIA RTX A6000",
        "count": 2,
        "memory_gib_each": 48,
    }]

    secondary = resources["secondary_gpu"]
    assert secondary["resource_id"] == "server.usyd.bdav_z390_3090"
    assert secondary["registered_hardware"]["gpus"] == [
        {"model": "NVIDIA GeForce RTX 3090", "count": 1},
        {"model": "NVIDIA GeForce GTX 1080 Ti", "count": 1},
    ]
    assert secondary["status"]["statement"] == (
        "director reported resolved; live re-verification pending"
    )
    assert all(resource["current_task"] == "UNKNOWN" for resource in resources.values())


def test_every_query_requires_the_eight_what_and_how_sections():
    contract = _contract()
    checks = {item["id"]: item for item in contract["required_checks"]}
    assert set(checks) == {
        "identity",
        "gpu",
        "tmux_process",
        "project_run_campaign",
        "receipts_gates",
        "storage",
        "env_marker",
        "failure_duplicate_risk",
    }
    for check in checks.values():
        assert check["required"] is True
        assert check["what"]
        assert check["how"]
        assert check["required_output_fields"]
        assert "status" in check["required_output_fields"]


def test_current_task_is_fail_closed_and_never_inherited_from_history():
    policy = _contract()["freshness_policy"]
    assert policy["current_task_allowed_sources"] == [
        "live_snapshot",
        "validated_job_or_scheduler_receipt",
    ]
    assert policy["historical_snapshot_may_populate_current_task"] is False
    assert policy["inherit_previous_state"] is False
    assert policy["unknown_on_missing_failed_or_stale_probe"] is True
    assert policy["live_snapshot_required_for_idle_busy_or_execution_ready_claim"] is True


def test_read_only_query_never_grants_submit_job():
    operations = _contract()["operations"]
    query = operations["query_status"]
    submit = operations["submit_job"]
    assert query["classification"] == "read_only"
    assert query["may_self_authorize"] is False
    assert query["grants_submit_job"] is False
    assert "submit_job" in query["forbidden_actions"]
    assert submit["classification"] == "state_mutating"
    assert submit["implemented_by_server_query"] is False
    assert submit["query_status_is_authorization"] is False


def test_human_docs_reference_the_contract_and_keep_utf8_clean():
    if not SKILL_PATH.is_file():
        pytest.skip("workspace entry skill is not part of this checkout")
    notes = PLATFORM_NOTES_PATH.read_text(encoding="utf-8")
    skill = SKILL_PATH.read_text(encoding="utf-8")
    combined = notes + "\n" + skill

    assert "server_monitor/query_contract.json" in combined
    expected_secondary_status = "director reported resolved; live re-verification pending"
    assert expected_secondary_status in notes
    assert expected_secondary_status in skill
    assert "UNKNOWN" in notes and "inherit" in combined.lower()
    assert "query_status" in combined and "submit_job" in combined
    assert "carried another user's live task" not in combined
    assert "READ_ONLY_VERIFIED / EXECUTION_BLOCKED" not in combined

    mojibake_markers = ("鈥", "鏌", "鏈", "鐘", "鐪", "璁", "杩", "搂", "鈮", "掳", "淪", "\ufffd")
    assert not any(marker in combined for marker in mojibake_markers)
