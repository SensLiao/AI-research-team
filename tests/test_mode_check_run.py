"""Tests for the `check_run` operate recipe (EXECUTE -> REPORT) — wave-2 wiring (2026-08-04).

check_run is a read-only run-health snapshot: monitor observes the run-store and the deterministic
`monitor_scan.build_alerts` core (already engine-tested, see test_monitor_scan.py) derives alerts;
an INDEPENDENT failure-triager then judges what those alerts mean. Covers the registry's own
productization_gaps: an ordered observe -> independent_triage -> render pipeline, a deterministic
Markdown compiler, and packet tests across healthy / stalled / failed / over-budget runs.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from research_agent_teams.operate.artifacts import GateBlock
from research_agent_teams.operate.modes import _panel_recipe as pr
from research_agent_teams.operate.modes import check_run
from research_agent_teams.tools.validate_artifact import validate_artifact

TS = "2026-08-04T00:00:00Z"


def _mk_run(tmp_path, budget=None) -> Path:
    run_dir = tmp_path / "run-1"
    (run_dir / "inbox").mkdir(parents=True)
    tf = {"payload": {"task_id": "run-1", "mode": "check_run",
                     "request_text": "monitor the running ablation",
                     "north_star": {"statement": "q", "in_scope": ["q"], "out_of_scope": []},
                     "budget": budget or {"max_agent_hops": 2, "max_debug_retries_per_run": 3}}}
    (run_dir / "task_frame.artifact.json").write_text(json.dumps(tf), encoding="utf-8")
    return run_dir


def _write_bundle(run_dir, label, payload) -> None:
    p = run_dir / "inbox" / f"EXECUTE.{label}.bundle.json"
    p.write_text(json.dumps(payload), encoding="utf-8")


def _observed(run_dir, *rows) -> None:
    _write_bundle(run_dir, "monitor", {"observed_runs": list(rows)})


def _triaged(run_dir, *rows) -> None:
    _write_bundle(run_dir, "failure-triager", {"triage_assessments": list(rows)})


def _load(path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _brief_text(run_dir) -> str:
    rel = pr.target_markdown("check_run")["path"]
    return (run_dir / rel).read_text(encoding="utf-8")


# --------------------------------------------------------------------------- llm_step / wiring

def test_llm_step_execute_dispatches_both_seats_in_dependency_order(tmp_path):
    run_dir = _mk_run(tmp_path)
    panel = check_run.llm_step(str(run_dir), "EXECUTE", "monitor the running ablation")
    labels = [w["label"] for w in panel["workers"]]
    assert labels == ["monitor", "failure-triager"]
    assert panel["parallel_groups"] == [["monitor"], ["failure-triager"]]
    triage_worker = next(w for w in panel["workers"] if w["label"] == "failure-triager")
    assert triage_worker["depends_on"] == ["monitor"]


def test_llm_step_report_is_deterministic(tmp_path):
    run_dir = _mk_run(tmp_path)
    assert check_run.llm_step(str(run_dir), "REPORT", "monitor the running ablation") is None


def test_llm_step_seat_labels_declared_in_registry(tmp_path):
    run_dir = _mk_run(tmp_path)
    panel = check_run.llm_step(str(run_dir), "EXECUTE", "monitor the running ablation")
    declared = set(pr.declared_seats("check_run"))
    assert {w["label"] for w in panel["workers"]} <= declared
    assert declared == {"monitor", "failure-triager"}


# --------------------------------------------------------------------------- happy path — 4 scenarios

def test_healthy_run_produces_empty_alerts_and_usable_markdown(tmp_path):
    run_dir = _mk_run(tmp_path)
    _observed(run_dir, {"run_id": "r-healthy", "status": "provisional", "cost": 10.0, "run_dir": None})
    _triaged(run_dir)  # nothing to triage — a legitimate result
    paths, report = check_run.run_dets(str(run_dir), "EXECUTE", TS)
    for p in paths:
        assert validate_artifact(_load(p)) == []
    alert = _load(run_dir / "evidence" / "EXECUTE" / "monitor-alert.artifact.json")
    assert alert["payload"]["alerts"] == []
    md = _brief_text(run_dir)
    for section in ("Current run status", "Evidence-backed alerts", "Intervention options",
                   "Unresolved decisions"):
        assert f"## {section}" in md
    assert "healthy" in md.lower()
    assert report["n_alerts"] == 0
    assert report["n_runs_observed"] == 1


def test_stalled_run_flows_through_to_alert_and_intervention_menu(tmp_path):
    run_dir = _mk_run(tmp_path)
    _observed(run_dir, {"run_id": "r-stall", "status": "stalled", "run_dir": None})
    _triaged(run_dir, {"condition_id": "r-stall",
                       "raw_evidence_excerpt": "status=stalled, no progress in 6h",
                       "likely_cause": "data loader hung", "urgency": "warn",
                       "intervention_options": ["restart the run", "inspect the data loader logs"],
                       "open_question": None})
    paths, report = check_run.run_dets(str(run_dir), "EXECUTE", TS)
    for p in paths:
        assert validate_artifact(_load(p)) == []
    alert = _load(run_dir / "evidence" / "EXECUTE" / "monitor-alert.artifact.json")
    assert alert["payload"]["alerts"][0]["alert_type"] == "stalled"
    triage = _load(run_dir / "evidence" / "EXECUTE" / "triage-report-r-stall.artifact.json")
    assert triage["payload"]["condition_id"] == "r-stall"
    assert triage["payload"]["error_class"] == "unknown"  # no crash signature -> safe fallback
    md = _brief_text(run_dir)
    assert "restart the run" in md
    assert "director's call" in md
    assert "none of them has been carried out" in md.lower()


def test_failed_run_classifies_oom_error_class_from_evidence(tmp_path):
    run_dir = _mk_run(tmp_path)
    _observed(run_dir, {"run_id": "r-fail", "status": "failed", "run_dir": None})
    _triaged(run_dir, {"condition_id": "r-fail",
                       "raw_evidence_excerpt": "RuntimeError: CUDA out of memory. Tried to allocate 2.00 GiB",
                       "likely_cause": "batch size too large for available GPU memory",
                       "urgency": "critical",
                       "intervention_options": ["reduce batch size", "enable gradient checkpointing"],
                       "open_question": None})
    paths, report = check_run.run_dets(str(run_dir), "EXECUTE", TS)
    for p in paths:
        assert validate_artifact(_load(p)) == []
    alert = _load(run_dir / "evidence" / "EXECUTE" / "monitor-alert.artifact.json")
    assert alert["payload"]["alerts"][0]["alert_type"] == "failed"
    assert alert["payload"]["alerts"][0]["severity"] == "critical"
    triage = _load(run_dir / "evidence" / "EXECUTE" / "triage-report-r-fail.artifact.json")
    assert triage["payload"]["error_class"] == "oom"  # classify_trace derived it, never hand-set
    assert triage["payload"]["condition_id"] == "r-fail"


def test_over_budget_run_flags_declared_cost(tmp_path):
    run_dir = _mk_run(tmp_path, budget={"max_agent_hops": 2, "max_cost": 100.0})
    _observed(run_dir, {"run_id": "r-hot", "status": "provisional", "cost": 500.0, "run_dir": None})
    _triaged(run_dir, {"condition_id": "r-hot",
                       "raw_evidence_excerpt": "declared cost 500.0 exceeds budget limit 100.0",
                       "likely_cause": "condition sweeping too many seeds", "urgency": "warn",
                       "intervention_options": ["cap seeds per condition",
                                                "confirm the spend with the director"],
                       "open_question": None})
    paths, report = check_run.run_dets(str(run_dir), "EXECUTE", TS)
    for p in paths:
        assert validate_artifact(_load(p)) == []
    alert = _load(run_dir / "evidence" / "EXECUTE" / "monitor-alert.artifact.json")
    assert alert["payload"]["alerts"][0]["alert_type"] == "over_budget"
    assert report["n_alerts"] == 1


# --------------------------------------------------------------------------- honesty / coverage

def test_uncovered_alert_surfaces_as_unresolved_never_silently_dropped(tmp_path):
    run_dir = _mk_run(tmp_path)
    _observed(run_dir,
             {"run_id": "r-stall-a", "status": "stalled", "run_dir": None},
             {"run_id": "r-stall-b", "status": "stalled", "run_dir": None})
    _triaged(run_dir, {"condition_id": "r-stall-a", "raw_evidence_excerpt": "stalled 6h",
                       "likely_cause": "unknown", "urgency": "warn",
                       "intervention_options": ["restart"], "open_question": None})
    # r-stall-b never triaged — must surface honestly, never silently disappear
    paths, report = check_run.run_dets(str(run_dir), "EXECUTE", TS)
    md = _brief_text(run_dir)
    assert "r-stall-b" in md
    assert "no independent triage assessment was produced" in md


# --------------------------------------------------------------------------- gates

def test_missing_seat_bundle_gate_blocks_with_filename(tmp_path):
    run_dir = _mk_run(tmp_path)
    _observed(run_dir, {"run_id": "r1", "status": "provisional"})
    # failure-triager bundle never written
    with pytest.raises(GateBlock) as exc:
        check_run.run_dets(str(run_dir), "EXECUTE", TS)
    assert "EXECUTE.failure-triager.bundle.json" in str(exc.value)


def test_ungrounded_triage_target_is_blocked(tmp_path):
    run_dir = _mk_run(tmp_path)
    _observed(run_dir, {"run_id": "r-real", "status": "stalled"})
    _triaged(run_dir, {"condition_id": "r-imaginary", "raw_evidence_excerpt": "made up",
                       "likely_cause": "n/a", "urgency": "warn", "intervention_options": ["x"]})
    with pytest.raises(GateBlock) as exc:
        check_run.run_dets(str(run_dir), "EXECUTE", TS)
    assert "r-imaginary" in str(exc.value)


def test_duplicate_triage_assessment_is_blocked(tmp_path):
    run_dir = _mk_run(tmp_path)
    _observed(run_dir, {"run_id": "r-dup", "status": "stalled"})
    _triaged(run_dir,
             {"condition_id": "r-dup", "raw_evidence_excerpt": "a", "likely_cause": "x",
              "urgency": "warn", "intervention_options": ["y"]},
             {"condition_id": "r-dup", "raw_evidence_excerpt": "b", "likely_cause": "z",
              "urgency": "info", "intervention_options": ["w"]})
    with pytest.raises(GateBlock) as exc:
        check_run.run_dets(str(run_dir), "EXECUTE", TS)
    assert "r-dup" in str(exc.value)


def test_unknown_stage_raises_value_error(tmp_path):
    run_dir = _mk_run(tmp_path)
    with pytest.raises(ValueError):
        check_run.run_dets(str(run_dir), "NOPE", TS)


# --------------------------------------------------------------------------- REPORT + full pipeline

def test_report_stage_references_the_markdown(tmp_path):
    run_dir = _mk_run(tmp_path)
    paths, _report = check_run.run_dets(str(run_dir), "REPORT", TS)
    note = _load(paths[0])
    assert validate_artifact(note) == []
    assert "run-health-brief.md" in note["payload"]["references"][0]


def test_full_pipeline_execute_then_report(tmp_path):
    run_dir = _mk_run(tmp_path)
    _observed(run_dir, {"run_id": "r-ok", "status": "done", "cost": 5.0, "run_dir": None})
    _triaged(run_dir)
    exec_paths, exec_report = check_run.run_dets(str(run_dir), "EXECUTE", TS)
    assert exec_report["n_runs_observed"] == 1
    report_paths, _ = check_run.run_dets(str(run_dir), "REPORT", TS)
    for p in exec_paths + report_paths:
        assert validate_artifact(_load(p)) == []


def test_run_dets_with_repair_happy_path_returns_ok(tmp_path):
    run_dir = _mk_run(tmp_path)
    _observed(run_dir, {"run_id": "r-ok", "status": "provisional"})
    _triaged(run_dir)
    outcome = check_run.run_dets_with_repair(str(run_dir), "EXECUTE", TS)
    assert outcome[0] == "ok"
