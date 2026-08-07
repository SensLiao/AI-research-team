"""Operate-layer acceptance — drive `new_direction` through the STEP-WISE spine (operate.spine +
modes.new_direction) the way the research-orchestrator skill does, with stub worker bundles in place of
live sub-agents. Proves the operated twin carries the SAME guarantees the engine-driven test
(test_m3a_new_direction) proves for run_task():
  - the two DISCOVER hard gates are LIVE (thin evidence -> BLOCK, run halts, never ideates);
  - the gap chain + ranked menu are produced and contract-valid;
  - the tamper-evident ledger hash-chain stays intact;
  - the IDEATE boundary is a director_signoff gate; the machine never self-bets.

The ONLY difference from a live run is that the LLM workers' bundles are fixtures here instead of real
vault mining — exactly the tested-vs-operated line. The deterministic governance is the real cores.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from research_agent_teams.operate import cli, spine
from research_agent_teams.operate.artifacts import GateBlock
from research_agent_teams.operate.modes import new_direction
from research_agent_teams.tools import runstore
from research_agent_teams.tools.ledger import append_event, read_events, verify_chain
from research_agent_teams.tools.runstore import classify_status, read_manifest
from research_agent_teams.tools.validate_artifact import validate_against

TS = "2026-06-09T00:00:00Z"

_EVIDENCE_CLEAN = {
    "query": "gap scan for a new promptable-3D-segmentation direction",
    "sources": [
        {"id": "s1", "kind": "paper", "ref": "[[hu-2021-lora]]", "claim_support": "strong"},
        {"id": "s2", "kind": "paper", "ref": "[[toothfairy-2025]]", "claim_support": "moderate"},
        {"id": "s3", "kind": "paper", "ref": "[[hdilemma-2024]]", "claim_support": "moderate"},
    ],
    "saturation_reached": True,
}
_CLAIM_LIST = {"source_scope": "new-direction gap scan",
               "claims": [{"claim_id": "c1", "text": "Adapter tuning is underexplored for promptable 3D seg.",
                           "source_ref": "[[hu-2021-lora]]"}]}
_CLAIM_MAP = {"mappings": [{"claim_id": "c1", "overall_support": "supported",
              "loci": [{"locus_id": "l1", "source_ref": "[[hu-2021-lora]]", "location": "Sec 5",
                        "kind": "text", "reported_result": "named as open future work",
                        "supports_claim": True}]}]}
_SIGNALS = [
    {"gap_id": "GAP-1", "statement": "Adapter tuning underexplored for promptable 3D segmentation",
     "source_ref": "[[hu-2021-lora]]", "evidence_ref": ["[[hu-2021-lora]]"], "derived_from": ["white_space_present"]},
    {"gap_id": "GAP-2", "statement": "No public fair-budget benchmark for SAM medical adaptation",
     "source_ref": "[[toothfairy-2025]]", "evidence_ref": ["[[toothfairy-2025]]"]},
    {"gap_id": "GAP-3", "locus": "baseline evaluation", "opportunity": "equal-budget comparison",
     "evidence_ref": ["[[hdilemma-2024]]"], "derived_from": ["contrarian_angle", "empirically_untested"]},
]
_HYPOTHESES = [
    {"hypothesis_id": "IH1", "statement": "A LoRA adapter matches full fine-tune for 3D prompts at equal budget.",
     "falsifiable_prediction": "Mean Dice(LoRA) >= Dice(full-ft) within 1% at equal GPU-hours on fold0.",
     "evidence_needed": ["equal-budget ablation"], "evidence_ref": ["GAP-1", "[[hu-2021-lora]]"]},
]
_IDEAS = [
    {"idea_id": "IDEA-1", "summary": "LoRA-vs-full-ft equal-budget ablation for promptable 3D seg.",
     "evidence_ref": ["IH1", "GAP-1"], "from_hypothesis_ref": "IH1",
     "feasibility": {"compute": "medium", "data": "available", "time": "medium"}},
    {"idea_id": "IDEA-2", "summary": "Build the fair-budget SAM-medical benchmark and re-rank the leaderboard.",
     "evidence_ref": ["IH1", "GAP-2"], "from_hypothesis_ref": "IH1",
     "feasibility": {"compute": "low", "data": "available", "time": "short"}},
]
# Audit B3: the IDEATE bundle now carries the worker's pairwise tournament judgments (every
# unordered pair of its ideas) + optional evolved ideas — the dets validate + Elo-rate them.
_TOURNAMENT = [{"round": 1, "pair_a": "IDEA-1", "pair_b": "IDEA-2", "winner": "IDEA-2",
                "rationale": "the benchmark idea is cheaper and unblocks the ablation idea"}]
_EVOLVED: list = []


def _stage_bundle(run_dir, stage, payload):
    inbox = Path(run_dir) / "inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    (inbox / f"{stage}.bundle.json").write_text(json.dumps(payload), encoding="utf-8")


def _discover_bundle(evidence="clean"):
    table = _EVIDENCE_CLEAN if evidence == "clean" else {**_EVIDENCE_CLEAN, "sources": _EVIDENCE_CLEAN["sources"][:1]}
    return {"read_summary": "stub", "evidence_table": table, "claim_list": _CLAIM_LIST,
            "claim_evidence_map": _CLAIM_MAP, "signals": _SIGNALS}


def _drive_discover(run_dir):
    spine.open_stage(run_dir, "DISCOVER", TS)
    paths, rep = new_direction.run_dets(run_dir, "DISCOVER", TS)
    return spine.commit_stage(run_dir, "DISCOVER", paths, TS), rep


def _drive_ideate(run_dir):
    _stage_bundle(run_dir, "IDEATE", {"hypotheses": _HYPOTHESES, "ideas": _IDEAS,
                                      "tournament": _TOURNAMENT, "evolved": _EVOLVED})
    new_direction.write_legacy_replay_receipt(
        run_dir, source_run_id="fixture-op1", reason="exercise frozen pre-panel compatibility")
    spine.open_stage(run_dir, "IDEATE", TS)
    paths, rep = new_direction.run_dets(run_dir, "IDEATE", TS)
    return spine.commit_stage(run_dir, "IDEATE", paths, TS), rep


def _drive_report(run_dir):
    spine.open_stage(run_dir, "REPORT", TS)
    paths, _ = new_direction.run_dets(run_dir, "REPORT", TS)
    return spine.commit_stage(run_dir, "REPORT", paths, TS)


def _run_cli(argv) -> int:
    try:
        cli.main(argv)
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 1
    return 0


def _prepare_final_report_gate(tmp_path, run_id: str):
    """Create the REPORT-gate shape without executing unrelated workers."""
    plan = spine.begin(str(tmp_path / "runs"), run_id, "review source-bound evidence", "evidence_review", TS)
    run_dir = Path(plan["run_dir"])
    assert plan["stages"] == ["DISCOVER", "REPORT"]
    from research_agent_teams.tools.runstore import checkpoint_stage, mark_gate_pending

    checkpoint_stage(run_dir, "DISCOVER", [], "k-discover", TS, stage_path=plan["stages"])
    checkpoint_stage(run_dir, "REPORT", [], "k-report", TS, stage_path=plan["stages"])
    mark_gate_pending(run_dir, "REPORT", TS, None, reason="configured_director_gate")
    return run_dir


# --------------------------------------------------------------------------- 1. end-to-end happy path

def test_operate_new_direction_runs_end_to_end(tmp_path):
    runs = tmp_path / "runs"
    plan = spine.begin(str(runs), "op1", "find a promptable segmentation direction worth betting on",
                       "new_direction", TS)
    rd = plan["run_dir"]
    assert plan["stages"] == ["DISCOVER", "IDEATE", "REPORT"]

    _stage_bundle(rd, "DISCOVER", _discover_bundle("clean"))
    d_res, d_rep = _drive_discover(rd)
    assert d_rep["evidence_gate"] == "PASS" and d_rep["citation_gate"] == "PASS"
    assert d_res["gate"] == "auto"  # evidence is verified before the menu, but no human bet yet
    assert d_res["next_stage"] == "IDEATE"

    i_res, i_rep = _drive_ideate(rd)
    assert i_rep["ideas_ranked"] == 2
    assert i_res["gate"] == "director_signoff"          # the /idea-bet boundary
    assert i_res["next_stage"] == "REPORT"

    spine.resolve_director_gate(rd, "IDEATE", "approved", TS, reason="test director bet")
    r_res = _drive_report(rd)
    assert r_res["done"] is True
    st = spine.status(rd)
    assert st["run_status"] == "done"
    assert st["completed"] == ["DISCOVER", "IDEATE", "REPORT"]


def test_final_report_approval_records_terminal_completion(tmp_path):
    run_dir = _prepare_final_report_gate(tmp_path, "op-final-gate")

    resolved = spine.resolve_director_gate(run_dir, "REPORT", "approved", TS, reason="director accepted brief")
    manifest = read_manifest(run_dir)
    events = read_events(run_dir / "ledger.jsonl")

    assert resolved["status"] == "done"
    assert resolved["terminal"] is True and resolved["reconciled"] is False and resolved["idempotent"] is False
    assert manifest["status"] == "done" and manifest["next_step"] is None
    assert events[-2]["event_type"] == "gate_resolved"
    assert events[-1]["event_type"] == "run_completed"
    assert events[-1]["payload"]["stage"] == "REPORT"
    assert events[-1]["payload"]["approved_gate_event_hash"] == events[-2]["hash"]
    assert events[-1]["payload"]["reconciled"] is False
    assert validate_against("ledger_event.schema.json", events[-1]) == []
    assert verify_chain(events) == [] and classify_status(run_dir) == "done"


def test_cli_reconciles_exact_legacy_approved_final_gate_append_only(tmp_path, capsys):
    run_dir = _prepare_final_report_gate(tmp_path, "op-final-gate-legacy")
    # Simulate only the historical bug: approval is in the ledger, but the old
    # record_gate implementation left the final manifest in running state.
    append_event(
        run_dir / "ledger.jsonl",
        "gate_resolved",
        {"stage": "REPORT", "decision": "approved", "reason": "director accepted brief"},
        TS,
    )
    manifest = read_manifest(run_dir)
    manifest["status"] = "running"
    manifest["pending_gates"] = []
    manifest["next_step"] = None
    manifest["updated_at"] = TS
    runstore._write_manifest(run_dir, manifest)
    before = read_events(run_dir / "ledger.jsonl")

    code = _run_cli([
        "approve", "--runs-dir", str(tmp_path / "runs"), "--run-id", "op-final-gate-legacy",
        "--stage", "REPORT", "--reason", "reconcile already-recorded final approval",
    ])
    out = json.loads(capsys.readouterr().out)
    after = read_events(run_dir / "ledger.jsonl")
    repaired = read_manifest(run_dir)

    assert code == 0 and out["approved"] is True
    assert (out["status"] == "done" and out["terminal"] is True and out["reconciled"] is True
            and out["idempotent"] is False)
    assert after[:-1] == before                     # no history rewrite or duplicate approval
    assert after[-1]["event_type"] == "run_completed"
    assert after[-1]["payload"]["reconciled"] is True
    assert after[-1]["payload"]["approved_gate_event_hash"] == before[-1]["hash"]
    assert repaired["status"] == "done" and repaired["next_step"] is None
    assert verify_chain(after) == []

    repeat_code = _run_cli([
        "approve", "--runs-dir", str(tmp_path / "runs"), "--run-id", "op-final-gate-legacy",
        "--stage", "REPORT", "--reason", "repeat terminal approval is a no-op",
    ])
    repeat = json.loads(capsys.readouterr().out)
    assert repeat_code == 0 and repeat["status"] == "done" and repeat["idempotent"] is True
    assert read_events(run_dir / "ledger.jsonl") == after


# --------------------------------------------------------------------------- 2. DISCOVER gates are LIVE

def test_operate_thin_evidence_blocks_and_never_ideates(tmp_path):
    runs = tmp_path / "runs"
    plan = spine.begin(str(runs), "op2", "ideate on thin promptable segmentation evidence",
                       "new_direction", TS)
    rd = plan["run_dir"]
    _stage_bundle(rd, "DISCOVER", _discover_bundle("thin"))
    spine.open_stage(rd, "DISCOVER", TS)
    with pytest.raises(GateBlock):
        new_direction.run_dets(rd, "DISCOVER", TS)
    # the gate artifact was written as 'blocked'; the stage was NOT committed; IDEATE never created
    ev = json.loads((Path(rd) / "evidence" / "DISCOVER" / "evidence-verdict.artifact.json").read_text())
    assert ev["payload"]["verdict"] == "BLOCK"
    assert not (Path(rd) / "evidence" / "IDEATE").exists()
    assert classify_status(rd) != "done"


# --------------------------------------------------------------------------- 3. menu ranked + no self-bet

def test_operate_menu_ranked_by_feasibility_and_no_self_bet(tmp_path):
    runs = tmp_path / "runs"
    plan = spine.begin(str(runs), "op3", "rank promptable segmentation directions", "new_direction", TS)
    rd = plan["run_dir"]
    _stage_bundle(rd, "DISCOVER", _discover_bundle("clean"))
    _drive_discover(rd)
    _drive_ideate(rd)
    rows = new_direction.menu(rd)
    assert [r["rank"] for r in rows] == [1, 2]
    assert rows[0]["idea_id"] == "IDEA-2"               # most feasible (low/available/short) ranks #1
    assert [r["score"] for r in rows] == sorted([r["score"] for r in rows], reverse=True)
    backlog = json.loads((Path(rd) / "evidence" / "IDEATE" / "idea-backlog.artifact.json").read_text())["payload"]
    assert not (set(backlog) & {"selected", "chosen", "bet", "winner"})
    for idea in backlog["ranked_ideas"]:
        assert not (set(idea) & {"selected", "chosen", "bet", "winner"})


def test_ideate_gate_is_persisted_and_blocks_report_until_director_resolves_it(tmp_path):
    """The idea menu is a durable human boundary, not merely a CLI reminder."""
    runs = tmp_path / "runs"
    plan = spine.begin(str(runs), "op-gate-persist", "rank promptable segmentation directions",
                       "new_direction", TS)
    rd = plan["run_dir"]
    _stage_bundle(rd, "DISCOVER", _discover_bundle("clean"))
    _drive_discover(rd)
    ideate_result, _ = _drive_ideate(rd)

    assert ideate_result["gate"] == "director_signoff"
    manifest = read_manifest(rd)
    assert manifest["status"] == "awaiting_director"
    assert manifest["pending_gates"] == ["IDEATE"]
    assert manifest["next_step"]["stage"] == "REPORT"
    assert classify_status(rd) == "awaiting"
    with pytest.raises(ValueError, match="director"):
        spine.open_stage(rd, "REPORT", TS)


def test_director_approval_releases_the_exact_mode_path_after_idea_bet(tmp_path):
    runs = tmp_path / "runs"
    plan = spine.begin(str(runs), "op-gate-approve", "rank promptable segmentation directions",
                       "new_direction", TS)
    rd = plan["run_dir"]
    _stage_bundle(rd, "DISCOVER", _discover_bundle("clean"))
    _drive_discover(rd)
    _drive_ideate(rd)

    resolved = spine.resolve_director_gate(rd, "IDEATE", "approved", TS)

    assert resolved["status"] == "running"
    manifest = read_manifest(rd)
    assert manifest["pending_gates"] == []
    assert manifest["next_step"]["stage"] == "REPORT"
    assert spine.open_stage(rd, "REPORT", TS) is True


def test_reconcile_legacy_idea_boundary_append_only_and_holds_report(tmp_path):
    runs = tmp_path / "runs"
    plan = spine.begin(str(runs), "op-gate-migrate", "rank promptable segmentation directions",
                       "new_direction", TS)
    rd = plan["run_dir"]
    # Reproduce the historical fault: global-STAGES checkpointing wrote DESIGN
    # after an otherwise valid IDEATE completion.
    from research_agent_teams.tools.runstore import checkpoint_stage, read_manifest

    checkpoint_stage(rd, "DISCOVER", [], "legacy-discover", TS)
    checkpoint_stage(rd, "IDEATE", [], "legacy-ideate", TS)
    before = read_events(Path(rd) / "ledger.jsonl")

    repaired = spine.reconcile_director_gate(rd, "IDEATE", TS)

    after = read_events(Path(rd) / "ledger.jsonl")
    manifest = read_manifest(rd)
    assert after[:-1] == before
    assert after[-1]["event_type"] == "gate_pending"
    assert after[-1]["payload"]["next_stage"] == "REPORT"
    assert after[-1]["payload"]["reason"] == "retroactive_path_and_gate_reconciliation"
    assert after[-1]["payload"]["previous_boundary_next"] == "DESIGN"
    assert repaired["next_stage"] == "REPORT"
    assert manifest["status"] == "awaiting_director"
    assert manifest["pending_gates"] == ["IDEATE"]
    assert manifest["next_step"]["stage"] == "REPORT"


def test_reconcile_director_gate_tolerates_a_rewritten_task_frame(tmp_path):
    """De-governance (director order 2026-08-07): the task-frame byte/hash comparison was removed
    from reconcile — a cosmetic rewrite of the file no longer refuses the gate. The file must still
    EXIST (that check stayed), which the happy path below exercises."""
    runs = tmp_path / "runs"
    plan = spine.begin(str(runs), "op-gate-tamper", "rank promptable segmentation directions",
                       "new_direction", TS)
    rd = Path(plan["run_dir"])
    from research_agent_teams.tools.runstore import checkpoint_stage

    checkpoint_stage(rd, "DISCOVER", [], "legacy-discover", TS)
    checkpoint_stage(rd, "IDEATE", [], "legacy-ideate", TS)
    task_frame = rd / "task_frame.artifact.json"
    task_frame.write_text(task_frame.read_text(encoding="utf-8") + "\n", encoding="utf-8")

    out = spine.reconcile_director_gate(rd, "IDEATE", TS)
    assert out is not None


def test_operate_ideate_writes_director_idea_bet_markdown(tmp_path):
    runs = tmp_path / "runs"
    plan = spine.begin(str(runs), "op3b", "rank promptable segmentation directions", "new_direction", TS)
    rd = plan["run_dir"]
    _stage_bundle(rd, "DISCOVER", _discover_bundle("clean"))
    _drive_discover(rd)
    _drive_ideate(rd)

    menu = Path(rd) / "director-review" / "ideas" / "idea-bet-menu.md"
    assert menu.is_file()
    text = menu.read_text(encoding="utf-8")
    assert "## Decision Snapshot" in text
    assert "## Candidate Ideas" in text
    assert "## Cut Before Betting" in text
    assert "IDEA-1" in text and "IDEA-2" in text
    assert "Minimal experiment sketch: not present" in text
    assert "PIVOT" in text


# --------------------------------------------------------------------------- 4. tamper-evident ledger intact

def test_operate_ledger_hash_chain_intact(tmp_path):
    runs = tmp_path / "runs"
    plan = spine.begin(str(runs), "op4", "menu the promptable segmentation directions for a human bet",
                       "new_direction", TS)
    rd = plan["run_dir"]
    _stage_bundle(rd, "DISCOVER", _discover_bundle("clean"))
    _drive_discover(rd)
    _drive_ideate(rd)
    spine.resolve_director_gate(rd, "IDEATE", "approved", TS, reason="test director bet")
    _drive_report(rd)
    assert verify_chain(read_events(Path(rd) / "ledger.jsonl")) == []
    # the machine produced only the menu — no bet/adr written by the run
    produced = [p.name for p in (Path(rd) / "evidence").rglob("*.json")]
    assert not any("idea-bet" in n or ".adr." in n for n in produced)


def test_open_stage_is_idempotent_for_multiple_panel_waves(tmp_path):
    runs = tmp_path / "runs"
    plan = spine.begin(str(runs), "op-open", "schedule a panel", "new_direction", TS)
    rd = plan["run_dir"]
    assert spine.open_stage(rd, "DISCOVER", TS) is True
    assert spine.open_stage(rd, "DISCOVER", TS) is False
    starts = [
        event for event in read_events(Path(rd) / "ledger.jsonl")
        if event["event_type"] == "stage_started"
    ]
    assert len(starts) == 1


def test_open_stage_refuses_future_wave_before_current_stage_commits(tmp_path):
    runs = tmp_path / "runs"
    plan = spine.begin(str(runs), "op-future", "schedule a panel", "new_direction", TS)
    with pytest.raises(ValueError, match="next legal stage"):
        spine.open_stage(plan["run_dir"], "IDEATE", TS)
