"""M0 acceptance: the spine engine drives a task end-to-end, resumes after a crash, and aborts on
a scope violation — exercising router + run-store + contract + scope + budget + observability together."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from research_agent_teams.orchestrator.engine import resume_task, run_task
from research_agent_teams.orchestrator.router import resolve_task
from research_agent_teams.tools.ledger import read_events, verify_chain
from research_agent_teams.tools.obslog import read_logs
from research_agent_teams.tools.runstore import (
    checkpoint_stage,
    classify_status,
    create_run,
    start_stage,
)

TS = "2026-06-08T00:00:00Z"


def _note_agent(stage, task_frame, run_dir, ts):
    d = Path(run_dir) / "evidence" / stage
    d.mkdir(parents=True, exist_ok=True)
    art = {
        "artifact_id": f"note-{stage}", "artifact_type": "note", "schema_version": "1.0.0",
        "created_by": "stub", "created_at": ts, "status": "draft",
        "payload": {"title": f"{stage} note", "body": "stub output"},
    }
    p = d / "note.artifact.json"
    p.write_text(json.dumps(art), encoding="utf-8")
    return p


def _approve(stage, task_frame):
    return "approved"


def test_dry_run_walks_full_spine_to_done(tmp_path):
    runs = tmp_path / "runs"
    m = run_task(runs, "r1", "design the ablation", "design_experiment", TS,
                 _note_agent, _approve, domain_profile_ref="cv-medical-segmentation",
                 budget_override={"max_agent_hops": 10})
    assert m["status"] == "done"
    assert m["next_step"] is None
    assert [c["stage"] for c in m["completed_work"]] == ["DESIGN", "REPORT"]

    run_dir = runs / "r1"
    assert verify_chain(read_events(run_dir / "ledger.jsonl")) == []   # tamper-proof history intact
    assert classify_status(run_dir) == "done"
    assert len(read_logs(run_dir / "obs.jsonl")) == 2                  # every driven stage observed


def test_resume_after_crash_completes(tmp_path):
    runs = tmp_path / "runs"
    rid = "r2"
    tf = resolve_task("verify it", "verify_result", rid, TS)
    create_run(runs, rid, "verify_result", "VERIFY", TS, None, tf["payload"]["agent_subset"])
    run_dir = runs / rid
    (run_dir / "task_frame.artifact.json").write_text(json.dumps(tf), encoding="utf-8")

    checkpoint_stage(run_dir, "VERIFY", [_note_agent("VERIFY", tf, run_dir, TS)], "idem-VERIFY", TS)
    start_stage(run_dir, "REPORT", TS)            # die mid-REPORT
    assert classify_status(run_dir) == "crashed_mid_stage"

    m = resume_task(runs, rid, TS, _note_agent, _approve)
    assert m["status"] == "done"
    assert classify_status(run_dir) == "done"
    assert verify_chain(read_events(run_dir / "ledger.jsonl")) == []


def test_scope_violation_aborts_the_run(tmp_path):
    runs = tmp_path / "runs"

    def rogue_agent(stage, task_frame, run_dir, ts):
        d = Path(run_dir) / "evidence" / "EXECUTE"   # writes to the WRONG stage
        d.mkdir(parents=True, exist_ok=True)
        p = d / "x.artifact.json"
        p.write_text(json.dumps({
            "artifact_id": "n", "artifact_type": "note", "schema_version": "1.0.0",
            "created_by": "rogue", "created_at": ts, "status": "draft", "payload": {"title": "t"},
        }), encoding="utf-8")
        return p

    with pytest.raises(PermissionError):
        run_task(runs, "r3", "verify it", "verify_result", TS, rogue_agent, _approve,
                 budget_override={"max_agent_hops": 10})
