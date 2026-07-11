"""M1 acceptance: the two V1 modes run end-to-end on fixtures, with the hard gates ACTUALLY enforced,
the result recorded in a tamper-proof ledger, and a forward-skip path resumable after a crash.

This wires the real deterministic cores (lit-scout / evidence-verifier / experiment-planner /
protocol-compiler / variable-control-auditor / train-test-alignment-auditor) into the proven M0 spine
engine. A gate BLOCK is enforced by the stage producer refusing to advance (raising), which leaves the
run halted at that stage — exactly the "dynamic agents cannot cross a hard gate" constitution rule.

Tested, NOT operated on real research (director discipline).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from research_agent_teams.orchestrator.engine import _resolve_path, resume_task, run_task
from research_agent_teams.orchestrator.router import resolve_task
from research_agent_teams.tools.alignment_checker import build_report as alignment_report
from research_agent_teams.tools.evidence_checker import build_verdict as evidence_verdict
from research_agent_teams.tools.evidence_scout import build_evidence_table
from research_agent_teams.tools.experiment_planner import build_matrix
from research_agent_teams.tools.ledger import read_events, verify_chain
from research_agent_teams.tools.protocol_compiler import compile_protocol
from research_agent_teams.tools.runstore import (
    checkpoint_stage,
    classify_status,
    create_run,
    start_stage,
)
from research_agent_teams.tools.validate_artifact import validate_artifact
from research_agent_teams.tools.variable_control_checker import build_report as variable_control_report

TS = "2026-06-08T00:00:00Z"
PROFILE = "cv-medical-segmentation"


class GateBlock(RuntimeError):
    """Raised by a stage producer when a hard gate refuses — halts the run at that stage."""


# --------------------------------------------------------------------------- fixtures

GOOD_EVIDENCE = {
    "query": "text-prompted 3D medical segmentation",
    "sources": [
        {"id": "s1", "kind": "paper", "ref": "[[ma-2023-medsam]]#sha", "claim_support": "strong"},
        {"id": "s2", "kind": "paper", "ref": "arXiv:2408.00001", "claim_support": "moderate"},
        {"id": "s3", "kind": "repo", "ref": "https://github.com/x/y", "claim_support": "moderate"},
    ],
    "saturation": True,
}
THIN_EVIDENCE = {"query": "niche claim", "sources": [
    {"id": "s1", "kind": "blog", "ref": "https://blog/x", "claim_support": "weak"}], "saturation": False}

# An aligned train/test pair (parity holds) and a mismatched one (eval spacing differs).
_TRAIN = {"preprocessing": {"spacing": [1, 1, 1]}, "augmentation": {"enabled": True}, "pretrained": "none",
          "precision": "fp32", "inference": {"threshold": 0.5}, "label_space": ["bg", "vessel"]}
_TEST_OK = {"preprocessing": {"spacing": [1, 1, 1]}, "augmentation": {"enabled": False}, "pretrained": "none",
            "precision": "fp32", "inference": {"threshold": 0.5}, "label_space": ["bg", "vessel"]}
_TEST_BAD = {**_TEST_OK, "preprocessing": {"spacing": [2, 2, 2]}}  # spacing mismatch -> alignment BLOCK

_CLEAN_DESIGN = {
    "rq": "Does a LoRA adapter beat full fine-tune at equal data/budget?",
    "variables": {"studied": ["adapter"], "controlled": ["lr", "epochs"], "frozen": ["backbone", "split"]},
    "conditions": [
        {"id": "c0", "factors": {"adapter": "none", "lr": 1e-4, "epochs": 50, "backbone": "sam-vit-b", "split": "fold0"}, "baseline": True},
        {"id": "c1", "factors": {"adapter": "lora", "lr": 1e-4, "epochs": 50, "backbone": "sam-vit-b", "split": "fold0"}},
    ],
    "ranked_batch": [{"rank": 1, "condition_id": "c1", "hypothesis": "LoRA >= full-ft at equal budget"}],
    "leakage": "All inputs derive from training images only; test masks never read.",
}
# A confounded variant: c1 changes adapter AND lr -> variable-control BLOCK.
_CONFOUNDED_DESIGN = json.loads(json.dumps(_CLEAN_DESIGN))
_CONFOUNDED_DESIGN["conditions"][1]["factors"]["lr"] = 3e-4


def _design_fx(design=_CLEAN_DESIGN, test=_TEST_OK):
    return {"design": design, "train": _TRAIN, "test": test, "profile_body": {}}


# --------------------------------------------------------------------------- producers

def _env(atype, by, payload, status="approved"):
    return {"artifact_id": atype, "artifact_type": atype, "schema_version": "1.0.0",
            "created_by": by, "created_at": TS, "status": status, "payload": payload}


def _write_validated(path: Path, art: dict) -> Path:
    errs = validate_artifact(art)
    assert errs == [], f"producer wrote an invalid artifact: {errs}"
    path.write_text(json.dumps(art), encoding="utf-8")
    return path


def _stage_dir(run_dir, stage) -> Path:
    d = Path(run_dir) / "evidence" / stage
    d.mkdir(parents=True, exist_ok=True)
    return d


def _report_producer(fx):
    def produce(stage, tf, run_dir, ts):
        d = _stage_dir(run_dir, stage)
        note = {"summary": fx.get("summary", "task complete"), "references": fx.get("refs", []),
                "produced_artifacts": [], "open_questions": []}
        return _write_validated(d / "report-note.artifact.json", _env("report_note", "research-orchestrator", note))
    return produce


def make_evidence_agent(fx):
    report = _report_producer(fx)

    def agent_fn(stage, tf, run_dir, ts):
        if stage == "DISCOVER":
            d = _stage_dir(run_dir, stage)
            table = build_evidence_table(fx["query"], fx["sources"], fx["saturation"])
            verdict = evidence_verdict(table, profile=fx.get("profile_body"))
            blocked = verdict["verdict"] == "BLOCK"
            _write_validated(d / "evidence-verdict.artifact.json",
                             _env("evidence_verdict", "evidence-verifier", verdict, "blocked" if blocked else "approved"))
            if blocked:
                raise GateBlock(f"evidence gate BLOCK: {verdict['reasons']}")
            return _write_validated(d / "evidence-table.artifact.json",
                                    _env("evidence_table", "lit-scout", table))
        if stage == "REPORT":
            return report(stage, tf, run_dir, ts)
        raise AssertionError(f"evidence_review should not reach stage {stage}")
    return agent_fn


def make_design_agent(fx):
    report = _report_producer(fx)

    def agent_fn(stage, tf, run_dir, ts):
        if stage == "DESIGN":
            d = _stage_dir(run_dir, stage)
            design = fx["design"]
            matrix = build_matrix(design["rq"], design["variables"], design["conditions"],
                                  design["ranked_batch"], design["leakage"])
            # gate 1 — variable control (isolates the studied variable)
            vc = variable_control_report(matrix, profile=fx.get("profile_body"))
            _write_validated(d / "variable-control-report.artifact.json",
                             _env("variable_control_report", "variable-control-auditor", vc,
                                  "blocked" if vc["verdict"] == "BLOCK" else "approved"))
            if vc["verdict"] == "BLOCK":
                raise GateBlock(f"variable-control gate BLOCK: {vc['violations']}")
            # the design compiles to runnable per-condition configs
            proto = compile_protocol(matrix, from_matrix_ref="experiment_matrix", shared={"optimizer": "adamw"})
            _write_validated(d / "protocol-spec.artifact.json", _env("protocol_spec", "protocol-compiler", proto))
            # gate 2 — train/test/inference alignment (the 对齐人)
            al = alignment_report(fx["train"], fx["test"], profile=fx.get("profile_body"))
            _write_validated(d / "alignment-report.artifact.json",
                             _env("alignment_report", "train-test-alignment-auditor", al,
                                  "blocked" if al["verdict"] == "BLOCK" else "approved"))
            if al["verdict"] == "BLOCK":
                raise GateBlock(f"alignment gate BLOCK: {al['violations']}")
            return _write_validated(d / "experiment-matrix.artifact.json",
                                    _env("experiment_matrix", "experiment-planner", matrix))
        if stage == "REPORT":
            return report(stage, tf, run_dir, ts)
        raise AssertionError(f"design_experiment_minimal should not reach stage {stage}")
    return agent_fn


def _approve(stage, tf):
    return "approved"


# --------------------------------------------------------------------------- engine path unit tests

def test_resolve_path_defaults_to_full_tail():
    tf = resolve_task("x", "design_experiment", "r", TS)
    tf["payload"].pop("stage_path", None)                         # simulate a legacy frame with no explicit path
    assert _resolve_path(tf) == ["DESIGN", "EXECUTE", "ANALYZE", "VERIFY", "REPORT"]


def test_resolve_path_uses_design_experiment_explicit_path():
    tf = resolve_task("x", "design_experiment", "r", TS)
    assert _resolve_path(tf) == ["DESIGN", "REPORT"]


def test_resolve_path_uses_declared_forward_skip():
    tf = resolve_task("x", "evidence_review", "r", TS)
    assert _resolve_path(tf) == ["DISCOVER", "REPORT"]            # experiment stages forward-skipped


def test_resolve_path_rejects_malformed_paths():
    tf = resolve_task("x", "evidence_review", "r", TS)
    tf["payload"]["stage_path"] = ["REPORT", "DISCOVER"]          # not forward-only
    with pytest.raises(ValueError):
        _resolve_path(tf)
    tf["payload"]["stage_path"] = ["DISCOVER", "DESIGN"]          # does not end at REPORT
    with pytest.raises(ValueError):
        _resolve_path(tf)


# --------------------------------------------------------------------------- mode 1: evidence_review

def test_evidence_review_good_runs_end_to_end_and_forward_skips(tmp_path):
    runs = tmp_path / "runs"
    m = run_task(runs, "ev1", "review the evidence for claim X", "evidence_review", TS,
                 make_evidence_agent(GOOD_EVIDENCE), _approve, domain_profile_ref=PROFILE)
    assert m["status"] == "done"
    # forward-skip proven: only DISCOVER + REPORT ran; experiment stages never executed
    assert [c["stage"] for c in m["completed_work"]] == ["DISCOVER", "REPORT"]
    run_dir = runs / "ev1"
    assert not (run_dir / "evidence" / "DESIGN").exists()
    assert not (run_dir / "evidence" / "EXECUTE").exists()
    # the evidence gate produced both the table and a PASS verdict
    assert (run_dir / "evidence" / "DISCOVER" / "evidence-table.artifact.json").exists()
    assert (run_dir / "evidence" / "DISCOVER" / "evidence-verdict.artifact.json").exists()
    # tamper-proof history intact
    assert verify_chain(read_events(run_dir / "ledger.jsonl")) == []
    assert classify_status(run_dir) == "done"


def test_evidence_review_thin_evidence_is_blocked_by_the_gate(tmp_path):
    runs = tmp_path / "runs"
    with pytest.raises(GateBlock):
        run_task(runs, "ev2", "review weak evidence", "evidence_review", TS,
                 make_evidence_agent(THIN_EVIDENCE), _approve, domain_profile_ref=PROFILE)
    run_dir = runs / "ev2"
    # the run halted at DISCOVER (the gate cannot be crossed); REPORT never reached
    assert classify_status(run_dir) == "crashed_mid_stage"
    assert not (run_dir / "evidence" / "REPORT").exists()
    # the BLOCK verdict was recorded with its reasons
    v = json.loads((run_dir / "evidence" / "DISCOVER" / "evidence-verdict.artifact.json").read_text(encoding="utf-8"))
    assert v["payload"]["verdict"] == "BLOCK" and v["payload"]["reasons"]


# --------------------------------------------------------------------------- mode 2: design_experiment_minimal

def test_design_minimal_good_runs_through_both_hard_gates(tmp_path):
    runs = tmp_path / "runs"
    m = run_task(runs, "dz1", "design the LoRA ablation", "design_experiment_minimal", TS,
                 make_design_agent(_design_fx()), _approve, domain_profile_ref=PROFILE)
    assert m["status"] == "done"
    assert [c["stage"] for c in m["completed_work"]] == ["DESIGN", "REPORT"]
    dd = runs / "dz1" / "evidence" / "DESIGN"
    for name in ("experiment-matrix", "variable-control-report", "alignment-report", "protocol-spec"):
        assert (dd / f"{name}.artifact.json").exists()
    assert verify_chain(read_events(runs / "dz1" / "ledger.jsonl")) == []


def test_design_minimal_alignment_mismatch_is_blocked(tmp_path):
    runs = tmp_path / "runs"
    with pytest.raises(GateBlock):
        run_task(runs, "dz2", "design with mismatched eval", "design_experiment_minimal", TS,
                 make_design_agent(_design_fx(test=_TEST_BAD)), _approve, domain_profile_ref=PROFILE)
    run_dir = runs / "dz2"
    assert classify_status(run_dir) == "crashed_mid_stage"
    al = json.loads((run_dir / "evidence" / "DESIGN" / "alignment-report.artifact.json").read_text(encoding="utf-8"))
    assert al["payload"]["verdict"] == "BLOCK"
    assert not (run_dir / "evidence" / "REPORT").exists()


def test_design_minimal_confounded_variable_is_blocked(tmp_path):
    runs = tmp_path / "runs"
    with pytest.raises(GateBlock):
        run_task(runs, "dz3", "design with a confound", "design_experiment_minimal", TS,
                 make_design_agent(_design_fx(design=_CONFOUNDED_DESIGN)), _approve, domain_profile_ref=PROFILE)
    run_dir = runs / "dz3"
    vc = json.loads((run_dir / "evidence" / "DESIGN" / "variable-control-report.artifact.json").read_text(encoding="utf-8"))
    assert vc["payload"]["verdict"] == "BLOCK"
    # blocked before alignment even ran (variable-control is the first DESIGN gate)
    assert not (run_dir / "evidence" / "DESIGN" / "alignment-report.artifact.json").exists()


# --------------------------------------------------------------------------- resume under a forward-skip

def test_forward_skip_path_resumes_after_crash(tmp_path):
    runs = tmp_path / "runs"
    rid = "ev3"
    tf = resolve_task("review evidence", "evidence_review", rid, TS, domain_profile_ref=PROFILE)
    create_run(runs, rid, "evidence_review", "DISCOVER", TS, PROFILE, tf["payload"]["agent_subset"])
    run_dir = runs / rid
    (run_dir / "task_frame.artifact.json").write_text(json.dumps(tf), encoding="utf-8")

    agent_fn = make_evidence_agent(GOOD_EVIDENCE)
    # finish DISCOVER, then die mid-REPORT (the next path stage, NOT the global next stage IDEATE)
    checkpoint_stage(run_dir, "DISCOVER", [agent_fn("DISCOVER", tf, run_dir, TS)], "idem-DISCOVER", TS)
    start_stage(run_dir, "REPORT", TS)
    assert classify_status(run_dir) == "crashed_mid_stage"

    m = resume_task(runs, rid, TS, agent_fn, _approve)
    assert m["status"] == "done"
    assert [c["stage"] for c in m["completed_work"]] == ["DISCOVER", "REPORT"]  # IDEATE was never run
    assert verify_chain(read_events(run_dir / "ledger.jsonl")) == []


# --------------------------------------------------------------------------- model policy threading

def _obs_models(run_dir) -> list:
    lines = (run_dir / "obs.jsonl").read_text(encoding="utf-8").splitlines()
    return [json.loads(line)["model"] for line in lines if line.strip()]


def test_default_policy_is_recorded_and_keeps_each_agents_tier(tmp_path):
    runs = tmp_path / "runs"
    # evidence_review's lead agent is lit-scout (sonnet) -> default keeps it sonnet on every line
    run_task(runs, "mp1", "review the evidence for claim X", "evidence_review", TS,
             make_evidence_agent(GOOD_EVIDENCE), _approve, domain_profile_ref=PROFILE)
    tf = json.loads((runs / "mp1" / "task_frame.artifact.json").read_text(encoding="utf-8"))
    assert tf["payload"]["model_policy"] == "default"
    assert _obs_models(runs / "mp1") == ["sonnet", "sonnet"]


def test_default_policy_keeps_an_opus_lead_on_opus(tmp_path):
    runs = tmp_path / "runs"
    # design_experiment_minimal's lead agent is experiment-planner (opus) -> opus even in default mode
    run_task(runs, "mp2", "design the LoRA ablation", "design_experiment_minimal", TS,
             make_design_agent(_design_fx()), _approve, domain_profile_ref=PROFILE)
    assert _obs_models(runs / "mp2") == ["opus", "opus"]


def test_max_quality_policy_forces_the_lead_to_opus(tmp_path):
    runs = tmp_path / "runs"
    # same sonnet-lead run, but max_quality lifts it to opus and records that choice
    run_task(runs, "mp3", "review the evidence for claim X", "evidence_review", TS,
             make_evidence_agent(GOOD_EVIDENCE), _approve, domain_profile_ref=PROFILE,
             model_policy="max_quality")
    tf = json.loads((runs / "mp3" / "task_frame.artifact.json").read_text(encoding="utf-8"))
    assert tf["payload"]["model_policy"] == "max_quality"
    assert _obs_models(runs / "mp3") == ["opus", "opus"]


def test_router_rejects_an_unknown_model_policy():
    with pytest.raises(ValueError, match="unknown model_policy"):
        resolve_task("x", "evidence_review", "r", TS, model_policy="ultra")


def test_legacy_task_frame_without_model_policy_defaults(tmp_path):
    # A task_frame written before model_policy existed has no such key; the engine must default it
    # to 'default' on resume rather than crash (backward compatibility for in-flight legacy runs).
    runs = tmp_path / "runs"
    rid = "mp4"
    tf = resolve_task("review the evidence", "evidence_review", rid, TS, domain_profile_ref=PROFILE)
    tf["payload"].pop("model_policy")                       # simulate a pre-feature frame
    create_run(runs, rid, "evidence_review", "DISCOVER", TS, PROFILE, tf["payload"]["agent_subset"])
    run_dir = runs / rid
    (run_dir / "task_frame.artifact.json").write_text(json.dumps(tf), encoding="utf-8")

    m = resume_task(runs, rid, TS, make_evidence_agent(GOOD_EVIDENCE), _approve)
    assert m["status"] == "done"
    assert _obs_models(run_dir) == ["sonnet", "sonnet"]    # defaulted -> lit-scout (sonnet)
