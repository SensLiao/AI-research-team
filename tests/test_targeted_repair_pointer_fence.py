import json
from pathlib import Path

import pytest

from research_agent_teams.operate.output_versions import (
    finalize_output,
    physical_output,
    prepare_plan,
    resolve_effective_output,
    sha256,
)


TS = "2026-08-13T00:00:00Z"


def _frame(run_dir: Path, mode: str) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "task_frame.artifact.json").write_text(
        json.dumps({"payload": {"mode": mode}}), encoding="utf-8"
    )


def _node(run_dir: Path, logical: Path, label: str = "landscape-mapper") -> dict:
    rel = logical.relative_to(run_dir).as_posix()
    return {
        "id": f"0:{label}:{rel}",
        "label": label,
        "output_path": logical,
        "output_rel": rel,
    }


def _defect(run_dir: Path, logical: Path, **updates) -> dict:
    row = {
        "defect_id": "DOSSIER-MAJOR-1",
        "location": "research_brief.bottom_line",
        "summary": "repair only the bottom line",
        "target_agents": ["landscape-mapper"],
        "refresh_agents": [],
        "target_artifact_ref": logical.relative_to(run_dir).as_posix(),
        "target_artifact_sha256": sha256(logical),
        "allowed_json_pointers": ["/research_brief/bottom_line"],
    }
    row.update(updates)
    return row


def test_deep_research_finalize_rejects_out_of_scope_change_without_advancing_cycle(tmp_path):
    run_dir = tmp_path / "run"
    _frame(run_dir, "deep_research")
    logical = run_dir / "inbox" / "landscape-mapper.bundle.json"
    logical.parent.mkdir(parents=True)
    logical.write_text(json.dumps({
        "research_brief": {"bottom_line": "old", "scope": "frozen"},
        "landscape_map": {"summary": "also frozen"},
    }), encoding="utf-8")
    node = _node(run_dir, logical)
    state = {
        "contract_version": "incremental-repair/v2",
        "attempts": [{"stage": "DISCOVER", "defects": [_defect(run_dir, logical)]}],
    }
    state_path = run_dir / "inbox" / "repair-state.json"
    state_path.write_text(json.dumps(state), encoding="utf-8")
    state_before = state_path.read_bytes()
    attempt = {"verdict": "NEEDS_SUPPLEMENT", "defects": [_defect(run_dir, logical)]}
    plan = prepare_plan(run_dir, "DISCOVER", 1, [node], {node["label"]}, attempt)
    assert plan["outputs"][0]["repair_scope"]["scope_policy"] == "json-pointer-fenced"
    assert plan["outputs"][0]["repair_scope"]["target_artifact_sha256"] == sha256(logical)

    corrected_path = physical_output(run_dir, plan, node["id"])
    assert corrected_path is not None
    corrected_path.parent.mkdir(parents=True, exist_ok=True)
    corrected_path.write_text(json.dumps({
        "research_brief": {"bottom_line": "fixed", "scope": "scope drift"},
        "landscape_map": {"summary": "also frozen"},
    }), encoding="utf-8")
    with pytest.raises(ValueError, match="outside allowed scope.*research_brief/scope"):
        finalize_output(run_dir, "DISCOVER", 1, node["id"], TS)

    rejected_plan = json.loads(
        (run_dir / "inbox/supplements/DISCOVER/repair-001/repair-plan.json")
        .read_text(encoding="utf-8")
    )
    assert rejected_plan["outputs"][0]["output_sha256"] is None
    assert rejected_plan["outputs"][0]["completed_at"] is None
    assert state_path.read_bytes() == state_before
    assert resolve_effective_output(run_dir, "DISCOVER", logical) == logical

    corrected_path.write_text(json.dumps({
        "research_brief": {"bottom_line": "fixed", "scope": "frozen"},
        "landscape_map": {"summary": "also frozen"},
    }), encoding="utf-8")
    finalize_output(run_dir, "DISCOVER", 1, node["id"], TS)
    accepted_plan = json.loads(
        (run_dir / "inbox/supplements/DISCOVER/repair-001/repair-plan.json")
        .read_text(encoding="utf-8")
    )
    assert accepted_plan["outputs"][0]["changed_paths"] == [
        "/research_brief/bottom_line"
    ]
    assert resolve_effective_output(run_dir, "DISCOVER", logical) == corrected_path

    corrected_path.write_text(json.dumps({
        "research_brief": {"bottom_line": "fixed", "scope": "post-finalize drift"},
        "landscape_map": {"summary": "also frozen"},
    }), encoding="utf-8")
    with pytest.raises(ValueError, match="finalized repair output hash drift"):
        resolve_effective_output(run_dir, "DISCOVER", logical)


def test_deep_research_targeted_author_repair_requires_explicit_pointers(tmp_path):
    run_dir = tmp_path / "run"
    _frame(run_dir, "deep_research")
    logical = run_dir / "inbox" / "landscape-mapper.bundle.json"
    logical.parent.mkdir(parents=True)
    logical.write_text(json.dumps({"research_brief": {"bottom_line": "old"}}), encoding="utf-8")
    node = _node(run_dir, logical)
    defect = _defect(run_dir, logical)
    defect.pop("allowed_json_pointers")

    with pytest.raises(ValueError, match="requires explicit.*allowed_json_pointers"):
        prepare_plan(
            run_dir, "DISCOVER", 1, [node], {node["label"]},
            {"verdict": "NEEDS_SUPPLEMENT", "defects": [defect]},
        )


def test_plan_rejects_declared_target_hash_that_is_not_current_artifact(tmp_path):
    run_dir = tmp_path / "run"
    _frame(run_dir, "deep_research")
    logical = run_dir / "inbox" / "landscape-mapper.bundle.json"
    logical.parent.mkdir(parents=True)
    logical.write_text(json.dumps({"research_brief": {"bottom_line": "old"}}), encoding="utf-8")
    node = _node(run_dir, logical)
    defect = _defect(run_dir, logical, target_artifact_sha256="sha256:" + "0" * 64)

    with pytest.raises(ValueError, match="repair target hash mismatch"):
        prepare_plan(
            run_dir, "DISCOVER", 1, [node], {node["label"]},
            {"verdict": "NEEDS_SUPPLEMENT", "defects": [defect]},
        )


def test_legacy_mode_without_pointer_scope_remains_explicitly_unrestricted(tmp_path):
    run_dir = tmp_path / "run"
    _frame(run_dir, "design_experiment")
    logical = run_dir / "inbox" / "legacy.bundle.json"
    logical.parent.mkdir(parents=True)
    logical.write_text(json.dumps({"a": 1, "b": 1}), encoding="utf-8")
    node = _node(run_dir, logical, "design-synthesizer")
    defect = {
        "defect_id": "LEGACY-1", "target_agents": ["design-synthesizer"],
        "location": "a", "summary": "historical unscoped defect",
    }
    plan = prepare_plan(
        run_dir, "DESIGN", 1, [node], {node["label"]},
        {"verdict": "NEEDS_SUPPLEMENT", "defects": [defect]},
    )
    assert plan["outputs"][0]["repair_scope"]["scope_policy"] == "legacy-unrestricted"
    corrected = physical_output(run_dir, plan, node["id"])
    assert corrected is not None
    corrected.parent.mkdir(parents=True, exist_ok=True)
    corrected.write_text(json.dumps({"a": 2, "b": 2}), encoding="utf-8")
    finalize_output(run_dir, "DESIGN", 1, node["id"], TS)
    assert resolve_effective_output(run_dir, "DESIGN", logical) == corrected
