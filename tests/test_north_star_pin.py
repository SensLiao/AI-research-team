"""North-star contract plumbing (audit H2/A1): router default, ledger pin, immutable request."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from research_agent_teams.operate import spine
from research_agent_teams.operate.cli import cmd_worker
from research_agent_teams.orchestrator.router import resolve_task
from research_agent_teams.tools.ledger import read_events, verify_chain
from research_agent_teams.tools.runstore import classify_status
from research_agent_teams.tools.validate_artifact import validate_artifact

TS = "2026-06-13T00:00:00Z"


def test_router_defaults_north_star_to_the_request():
    tf = resolve_task("improve canal segmentation prompts", "evidence_review", "r1", TS)
    ns = tf["payload"]["north_star"]
    assert ns == {"statement": "improve canal segmentation prompts", "in_scope": [], "out_of_scope": []}
    assert validate_artifact(tf) == []


def test_router_accepts_a_sharper_north_star():
    tf = resolve_task("req", "evidence_review", "r1", TS,
                      north_star={"statement": "the ONE direction", "in_scope": ["a"],
                                  "out_of_scope": ["b", " "]})
    ns = tf["payload"]["north_star"]
    assert ns["statement"] == "the ONE direction" and ns["out_of_scope"] == ["b"]
    assert validate_artifact(tf) == []


def test_begin_pins_the_task_frame_into_the_hash_chain(tmp_path):
    runs = tmp_path / "runs"
    runs.mkdir()
    plan = spine.begin(str(runs), "ns1", "scan canal prompts", "evidence_review", TS)
    run_dir = Path(plan["run_dir"])
    events = read_events(run_dir / "ledger.jsonl")
    assert verify_chain(events) == []
    pinned = [e for e in events if e["event_type"] == "task_frame_pinned"]
    assert len(pinned) == 1
    assert pinned[0]["payload"]["north_star_statement"] == "scan canal prompts"
    assert pinned[0]["payload"]["task_frame_sha256"].startswith("sha256:")
    assert classify_status(run_dir) == "ready"          # the pin never wedges resume classification
    assert plan["north_star"]["statement"] == "scan canal prompts"


def test_editing_the_task_frame_after_begin_is_detectable(tmp_path):
    runs = tmp_path / "runs"
    runs.mkdir()
    plan = spine.begin(str(runs), "ns2", "scan canal prompts", "evidence_review", TS)
    run_dir = Path(plan["run_dir"])
    tf_path = run_dir / "task_frame.artifact.json"
    tf = json.loads(tf_path.read_text(encoding="utf-8"))
    tf["payload"]["north_star"]["statement"] = "quietly different direction"
    tf_path.write_text(json.dumps(tf), encoding="utf-8")
    events = read_events(run_dir / "ledger.jsonl")
    pinned = [e for e in events if e["event_type"] == "task_frame_pinned"][0]
    from research_agent_teams.tools.runstore import hash_file
    assert hash_file(tf_path) != pinned["payload"]["task_frame_sha256"]   # tamper is provable


def test_worker_request_cannot_be_re_aimed_from_the_cli(tmp_path, capsys, monkeypatch):
    runs = tmp_path / "runs"
    runs.mkdir()
    spine.begin(str(runs), "ns3", "the pinned ask", "evidence_review", TS)

    class A:
        runs_dir, run_id, stage = str(runs), "ns3", "DISCOVER"
        request, vault, ts = "a DIFFERENT ask", None, TS
    with pytest.raises(SystemExit) as e:
        cmd_worker(A())
    assert e.value.code == 2
    out = json.loads(capsys.readouterr().out)
    assert "request mismatch" in out["error"]
