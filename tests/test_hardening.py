"""0.H foundation hardening — adversarial / property / fuzz before any agent is built on this base.

Covers: crash recovery at EVERY stage boundary, router never crashes uncaught on garbage,
parallel fan-out to distinct stage dirs cannot collide, and run-infra is single-writer for all agents.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from research_agent_teams.orchestrator.engine import resume_task
from research_agent_teams.orchestrator.router import resolve_task, validate_routing
from research_agent_teams.tools.ledger import read_events, verify_chain
from research_agent_teams.tools.runstore import (
    STAGES,
    checkpoint_stage,
    classify_status,
    create_run,
    start_stage,
)
from research_agent_teams.tools.scope_guard import decide

TS = "2026-06-08T00:00:00Z"


def _note_agent(stage, task_frame, run_dir, ts):
    d = Path(run_dir) / "evidence" / stage
    d.mkdir(parents=True, exist_ok=True)
    p = d / "note.artifact.json"
    p.write_text(json.dumps({
        "artifact_id": f"note-{stage}", "artifact_type": "note", "schema_version": "1.0.0",
        "created_by": "stub", "created_at": ts, "status": "draft", "payload": {"title": f"{stage}"},
    }), encoding="utf-8")
    return p


def _approve(stage, tf):
    return "approved"


@pytest.mark.parametrize("crash_stage", STAGES)
def test_crash_recovery_at_every_boundary(tmp_path, crash_stage):
    runs = tmp_path / "runs"
    rid = f"r-{crash_stage}"
    tf = resolve_task("x", "full_new_direction", rid, TS)
    tf["payload"]["budget"] = {"max_agent_hops": 20}
    create_run(runs, rid, "full_new_direction", "DISCOVER", TS, None, tf["payload"]["agent_subset"])
    run_dir = runs / rid
    (run_dir / "task_frame.artifact.json").write_text(json.dumps(tf), encoding="utf-8")

    for s in STAGES[:STAGES.index(crash_stage)]:           # complete everything before the crash
        checkpoint_stage(run_dir, s, [_note_agent(s, tf, run_dir, TS)], f"idem-{s}", TS)
    start_stage(run_dir, crash_stage, TS)                  # die mid-stage
    assert classify_status(run_dir) == "crashed_mid_stage"

    m = resume_task(runs, rid, TS, _note_agent, _approve)  # recover
    assert m["status"] == "done"
    assert verify_chain(read_events(run_dir / "ledger.jsonl")) == []


@pytest.mark.parametrize("bad", [
    {"mode": "nonexistent_mode"},
    {"mode": ""},
    {"mode": 123},
])
def test_router_rejects_garbage_cleanly(bad):
    # The router must raise a clean ValueError, never an uncaught crash.
    with pytest.raises((ValueError, TypeError)):
        resolve_task("req", bad["mode"], "run-x", TS)


def test_validate_routing_handles_malformed_payload():
    # Missing/garbage routing fields produce errors, not exceptions.
    errs = validate_routing({"payload": {"entry_stage": "NOPE", "agent_subset": [], "gate_level": "auto"}})
    assert errs and any("entry_stage" in e for e in errs)


def test_parallel_distinct_stage_writes_cannot_collide(tmp_path):
    run_root, run_id = str(tmp_path / "runs"), "rp"
    # Two fenced agents in two different stages: each may write only its own stage dir.
    s_discover = {"run_root": run_root, "run_id": run_id, "stage": "DISCOVER"}
    s_design = {"run_root": run_root, "run_id": run_id, "stage": "DESIGN"}
    p_disc = f"{run_root}/{run_id}/evidence/DISCOVER/a.md"
    p_des = f"{run_root}/{run_id}/evidence/DESIGN/a.md"
    assert decide("Write", p_disc, s_discover)[0] is True
    assert decide("Write", p_des, s_design)[0] is True
    # Cross-writes are blocked -> two parallel agents can never target the same file.
    assert decide("Write", p_des, s_discover)[0] is False
    assert decide("Write", p_disc, s_design)[0] is False
    assert p_disc != p_des


@pytest.mark.parametrize("stage", STAGES)
@pytest.mark.parametrize("infra", ["manifest.yaml", "ledger.jsonl", "LOCK"])
def test_run_infra_is_single_writer_for_all_agents(tmp_path, stage, infra):
    scope = {"run_root": str(tmp_path / "runs"), "run_id": "r", "stage": stage}
    target = f"{scope['run_root']}/r/{infra}"
    ok, reason = decide("Write", target, scope)
    assert not ok and "single-writer infra" in reason
