"""Regression tests for the director-veto fix (governance red line ①).

Before the fix: engine._drive checkpointed the stage BEFORE the gate, and a `reject` only raised — no
ledger event, the stage already in completed_work — so resume_task skipped it and a plain 'continue'
walked the vetoed run to completion. The veto was both UN-RECORDED and BYPASSABLE.

After the fix: a reject is a tamper-evident gate_resolved event, the stage is NOT checkpointed, the run is
terminal (status=rejected), and prepare_resume refuses it.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from research_agent_teams.operate import spine
from research_agent_teams.orchestrator.engine import resume_task, run_task
from research_agent_teams.tools.ledger import last_of_type, read_events, verify_chain
from research_agent_teams.tools.runstore import (
    classify_status,
    create_run,
    prepare_resume,
    read_manifest,
    record_gate,
    start_stage,
)

TS = "2026-06-10T00:00:00Z"


# ----------------------------- runstore.record_gate -----------------------------

def test_record_gate_reject_is_terminal_and_on_the_ledger(tmp_path):
    create_run(tmp_path, "r", "m", "DISCOVER", TS)
    run_dir = tmp_path / "r"
    start_stage(run_dir, "DISCOVER", TS)
    m = record_gate(run_dir, "DISCOVER", "reject", TS, reason="not novel enough")
    assert m["status"] == "rejected"
    assert m["rejected"]["stage"] == "DISCOVER" and m["next_step"] is None

    events = read_events(run_dir / "ledger.jsonl")
    assert verify_chain(events) == []                                  # tamper-evident, intact
    gr = last_of_type(events, "gate_resolved")
    assert gr is not None and gr["payload"]["decision"] == "reject"    # the veto IS on the permanent record
    assert classify_status(run_dir) == "rejected"
    with pytest.raises(RuntimeError, match="rejected|REJECTED"):
        prepare_resume(run_dir, TS)                                    # vetoed run cannot be resumed


def test_record_gate_approve_keeps_running_and_is_recorded(tmp_path):
    create_run(tmp_path, "r", "m", "DISCOVER", TS)
    run_dir = tmp_path / "r"
    start_stage(run_dir, "DISCOVER", TS)
    m = record_gate(run_dir, "DISCOVER", "approved", TS)
    assert m["status"] == "running"
    assert last_of_type(read_events(run_dir / "ledger.jsonl"), "gate_resolved")["payload"]["decision"] == "approved"


# ----------------------------- engine reject path -----------------------------

def _note_agent(stage, task_frame, run_dir, ts):
    d = Path(run_dir) / "evidence" / stage
    d.mkdir(parents=True, exist_ok=True)
    art = {"artifact_id": f"n-{stage}", "artifact_type": "note", "schema_version": "1.0.0",
           "created_by": "stub", "created_at": ts, "status": "draft",
           "payload": {"title": f"{stage} note", "body": "x"}}
    p = d / "note.artifact.json"
    p.write_text(json.dumps(art), encoding="utf-8")
    return p


def _reject(stage, task_frame):
    return "reject"


def test_engine_reject_does_not_checkpoint_and_is_unresumable(tmp_path):
    """The core bypass fix: a vetoed stage is never checkpointed, the run is terminal, and a plain resume
    REFUSES it — so 'continue' can no longer walk a rejected run to completion."""
    runs = tmp_path / "runs"
    with pytest.raises(RuntimeError, match="director rejected"):
        run_task(runs, "r", "find a direction", "new_direction", TS, _note_agent, _reject,
                 budget_override={"max_agent_hops": 10})

    run_dir = runs / "r"
    m = read_manifest(run_dir)
    assert m["status"] == "rejected"
    # DISCOVER is automatic; the configured human boundary is IDEATE. The
    # rejected IDEATE menu itself is never checkpointed by the synchronous
    # engine adapter.
    assert [row["stage"] for row in m["completed_work"]] == ["DISCOVER"]
    assert m["rejected"]["stage"] == "IDEATE"

    events = read_events(run_dir / "ledger.jsonl")
    assert verify_chain(events) == []
    assert last_of_type(events, "gate_resolved")["payload"]["decision"] == "reject"

    with pytest.raises(RuntimeError, match="rejected|REJECTED"):       # the bypass is closed
        resume_task(runs, "r", TS, _note_agent, lambda s, t: "approved")


# ----------------------------- operate twin -----------------------------

def test_operate_reject_stage_is_terminal(tmp_path):
    runs = tmp_path / "runs"
    plan = spine.begin(str(runs), "op", "find a direction", "new_direction", TS)
    rd = plan["run_dir"]
    spine.open_stage(rd, "DISCOVER", TS)
    m = spine.reject_stage(rd, "DISCOVER", TS, reason="pivot")
    assert m["status"] == "rejected"
    assert spine.status(rd)["run_status"] == "rejected"
    events = read_events(Path(rd) / "ledger.jsonl")
    assert verify_chain(events) == []
    assert last_of_type(events, "gate_resolved")["payload"]["decision"] == "reject"
