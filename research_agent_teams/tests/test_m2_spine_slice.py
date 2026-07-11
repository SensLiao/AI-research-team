"""M2-a acceptance — the spine slice: the FULL tail DESIGN→EXECUTE→ANALYZE→VERIFY→REPORT runs
end-to-end on fixtures with execution + analysis depth, and the THREE new hard gates
(preflight-checker, train-test-parity-verifier, result-sanity-checker) are live and demonstrably
BLOCK on injected violations. This proves the M2 architecture (the full-rigor pipeline) on the
smallest possible build, before the 47-agent breadth.

Wires the real deterministic cores (experiment-planner / variable-control / protocol-compiler /
train-test-alignment from M1, + the new preflight / parity / sanity checkers) into the proven engine.
A gate BLOCK is enforced by the stage producer refusing to advance (raising), leaving the run halted
at that stage — the "dynamic agents cannot cross a hard gate" constitution rule.

Tested, NOT operated on real research (director discipline); execution agents emit real scripts as
artifacts — whether they really run on a GPU is out of scope here (a server comes later).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from research_agent_teams.orchestrator.engine import run_task
from research_agent_teams.tools.alignment_checker import build_report as alignment_build
from research_agent_teams.tools.experiment_planner import build_matrix
from research_agent_teams.tools.ledger import read_events, verify_chain
from research_agent_teams.tools.parity_checker import build_report as parity_build
from research_agent_teams.tools.preflight_checker import build_report as preflight_build
from research_agent_teams.tools.protocol_compiler import compile_protocol
from research_agent_teams.tools.result_analyzer import build_result_summary
from research_agent_teams.tools.runstore import classify_status
from research_agent_teams.tools.sanity_checker import build_report as sanity_build
from research_agent_teams.tools.validate_artifact import validate_artifact
from research_agent_teams.tools.variable_control_checker import build_report as vc_build

TS = "2026-06-08T00:00:00Z"
PROFILE = "cv-medical-segmentation"


class GateBlock(RuntimeError):
    """Raised by a stage producer when a hard gate refuses — halts the run at that stage."""


# --------------------------------------------------------------------------- fixtures

_DESIGN = {
    "rq": "Does a LoRA adapter beat full fine-tune at equal data/budget?",
    "variables": {"studied": ["adapter"], "controlled": ["lr", "epochs"], "frozen": ["backbone", "split"]},
    "conditions": [
        {"id": "c0", "factors": {"adapter": "none", "lr": 1e-4, "epochs": 50, "backbone": "sam-vit-b", "split": "fold0"}, "baseline": True},
        {"id": "c1", "factors": {"adapter": "lora", "lr": 1e-4, "epochs": 50, "backbone": "sam-vit-b", "split": "fold0"}},
    ],
    "ranked_batch": [{"rank": 1, "condition_id": "c1", "hypothesis": "LoRA >= full-ft at equal budget"}],
    "leakage": "All inputs derive from training images only; test masks never read.",
}
_TRAIN = {"preprocessing": {"spacing": [1, 1, 1]}, "augmentation": {"enabled": True}, "pretrained": "none",
          "precision": "fp32", "inference": {"threshold": 0.5}, "label_space": ["bg", "vessel"]}
_TEST_OK = {"preprocessing": {"spacing": [1, 1, 1]}, "augmentation": {"enabled": False}, "pretrained": "none",
            "precision": "fp32", "inference": {"threshold": 0.5}, "label_space": ["bg", "vessel"]}
_TEST_DRIFT = {**_TEST_OK, "augmentation": {"enabled": True}}  # eval aug at run time → parity drift
# profile in the REAL shape (metrics[].valid_range + higher_is_better + leakage_delta)
_PROFILE_BODY = {"metrics": [{"name": "dice", "higher_is_better": True, "valid_range": [0.0, 1.0]}],
                 "leakage_delta": 0.5}


def _fx(**over):
    base = {
        "design": _DESIGN, "train": _TRAIN, "test": _TEST_OK,
        "actual_train": _TRAIN, "actual_test": _TEST_OK,
        "train_data_hash": "dh-train", "test_data_hash": "dh-test",
        "findings": [{"metric": "dice", "value": 0.81, "condition_id": "c1", "baseline_value": 0.78}],
        "profile_body": _PROFILE_BODY,
    }
    base.update(over)
    return base


# --------------------------------------------------------------------------- producer helpers

def _env(atype, by, payload, status="approved"):
    return {"artifact_id": atype, "artifact_type": atype, "schema_version": "1.0.0",
            "created_by": by, "created_at": TS, "status": status, "payload": payload}


def _stage_dir(run_dir, stage) -> Path:
    d = Path(run_dir) / "evidence" / stage
    d.mkdir(parents=True, exist_ok=True)
    return d


def _write(path: Path, art: dict) -> Path:
    errs = validate_artifact(art)
    assert errs == [], f"producer wrote an invalid artifact: {errs}"
    path.write_text(json.dumps(art), encoding="utf-8")
    return path


def make_full_rigor_agent(fx):
    """A single producer driving all 5 stages of full_rigor_minimal, running the real gates."""
    state: dict = {}

    def produce(stage, tf, run_dir, ts):
        d = _stage_dir(run_dir, stage)
        prof = fx["profile_body"]

        if stage == "DESIGN":
            design = fx["design"]
            matrix = build_matrix(design["rq"], design["variables"], design["conditions"],
                                  design["ranked_batch"], design["leakage"])
            vc = vc_build(matrix, profile=prof)
            _write(d / "variable-control-report.artifact.json",
                   _env("variable_control_report", "variable-control-auditor", vc,
                        "blocked" if vc["verdict"] == "BLOCK" else "approved"))
            if vc["verdict"] == "BLOCK":
                raise GateBlock(f"variable-control BLOCK: {vc['violations']}")
            proto = compile_protocol(matrix, from_matrix_ref="experiment_matrix", shared={"optimizer": "adamw"})
            _write(d / "protocol-spec.artifact.json", _env("protocol_spec", "protocol-compiler", proto))
            al = alignment_build(fx["train"], fx["test"], profile=prof)
            _write(d / "alignment-report.artifact.json",
                   _env("alignment_report", "train-test-alignment-auditor", al,
                        "blocked" if al["verdict"] == "BLOCK" else "approved"))
            if al["verdict"] == "BLOCK":
                raise GateBlock(f"alignment BLOCK: {al['violations']}")
            state["protocol"], state["alignment"] = proto, al
            return _write(d / "experiment-matrix.artifact.json",
                          _env("experiment_matrix", "experiment-planner", matrix))

        if stage == "EXECUTE":
            train_script = {"split": "train", "script": "def build_train():\n    return load('train')",
                            "from_protocol_ref": "protocol_spec", "data_hash_expected": fx["train_data_hash"]}
            test_script = {"split": "test", "script": "def build_test():\n    return load('test')",
                           "from_protocol_ref": "protocol_spec", "data_hash_expected": fx["test_data_hash"],
                           "augmentation_enabled": False, "frozen": True}
            _write(d / "trainset-script.artifact.json", _env("dataset_script_record", "trainset-builder", train_script))
            _write(d / "testset-script.artifact.json", _env("dataset_script_record", "testset-builder", test_script))
            pf = preflight_build(train_script, test_script, state["protocol"], state["alignment"],
                                 profile=prof, protocol_ref="protocol_spec", alignment_ref="alignment_report")
            _write(d / "preflight-report.artifact.json",
                   _env("preflight_report", "preflight-checker", pf, "blocked" if pf["verdict"] == "BLOCK" else "approved"))
            if pf["verdict"] == "BLOCK":
                raise GateBlock(f"preflight BLOCK: {pf['violations']}")
            run_record = {"condition_id": "c1", "status": "provisional",
                          "provenance": {"config_hash": "cfg#1", "data_hash": "dh-train", "seed": 0},
                          "metrics": {"dice": 0.81}}
            _write(d / "run-record.artifact.json", _env("run_record", "ablation-runner", run_record))
            journal = {"condition_id": "c1", "from_run_record_ref": "run_record", "from_preflight_ref": "preflight_report",
                       "config_hash": "cfg#1", "data_hash": "dh-train", "seed": 0,
                       "designed_train": fx["train"], "designed_test": fx["test"],
                       "actual_train": fx["actual_train"], "actual_test": fx["actual_test"],
                       "metrics_snapshot": {"dice": 0.81}}
            _write(d / "journal-entry.artifact.json", _env("journal_entry", "experiment-journaler", journal))
            pv = parity_build(journal, state["alignment"], profile=prof,
                              journal_ref="journal_entry", alignment_ref="alignment_report")
            _write(d / "parity-verdict.artifact.json",
                   _env("parity_verdict", "train-test-parity-verifier", pv, "blocked" if pv["verdict"] == "BLOCK" else "approved"))
            if pv["verdict"] == "BLOCK":
                raise GateBlock(f"parity BLOCK: {pv['violations']}")
            return _write(d / "run-record-exit.artifact.json", _env("run_record", "ablation-runner", run_record))

        if stage == "ANALYZE":
            rs = build_result_summary(fx["findings"])
            sv = sanity_build(rs, profile=prof)
            _write(d / "sanity-verdict.artifact.json",
                   _env("sanity_verdict", "result-sanity-checker", sv, "blocked" if sv["verdict"] == "BLOCK" else "approved"))
            if sv["verdict"] == "BLOCK":
                raise GateBlock(f"sanity BLOCK: {sv['violations']}")
            return _write(d / "result-summary.artifact.json", _env("result_summary", "result-analyzer", rs))

        if stage == "VERIFY":
            review = {"verdict": "APPROVE-FREEZE",
                      "checks": {k: {"pass": True, "evidence": "ok"}
                                 for k in ("leakage", "fairness", "eval_frame", "provenance", "overclaim")},
                      "blocking_reasons": [], "default_block_applied": False}
            return _write(d / "review-report.artifact.json", _env("review_report", "adversarial-reviewer", review))

        if stage == "REPORT":
            note = {"summary": "full-rigor spine slice complete", "references": [],
                    "produced_artifacts": [], "open_questions": []}
            return _write(d / "report-note.artifact.json", _env("report_note", "research-orchestrator", note))

        raise AssertionError(f"unexpected stage {stage}")

    return produce


def _approve(stage, tf):
    return "approved"


def _obs_models(run_dir):
    lines = (run_dir / "obs.jsonl").read_text(encoding="utf-8").splitlines()
    return [json.loads(line)["model"] for line in lines if line.strip()]


# --------------------------------------------------------------------------- happy path

def test_full_rigor_slice_runs_end_to_end_through_all_gates(tmp_path):
    runs = tmp_path / "runs"
    m = run_task(runs, "fr1", "design+run+analyze+review the LoRA ablation", "full_rigor_minimal", TS,
                 make_full_rigor_agent(_fx()), _approve, domain_profile_ref=PROFILE)
    assert m["status"] == "done"
    assert [c["stage"] for c in m["completed_work"]] == ["DESIGN", "EXECUTE", "ANALYZE", "VERIFY", "REPORT"]
    run_dir = runs / "fr1"
    # the new gate artifacts were produced and PASSED
    for name in ("preflight-report", "parity-verdict"):
        v = json.loads((run_dir / "evidence" / "EXECUTE" / f"{name}.artifact.json").read_text(encoding="utf-8"))
        assert v["payload"]["verdict"] == "PASS"
    sv = json.loads((run_dir / "evidence" / "ANALYZE" / "sanity-verdict.artifact.json").read_text(encoding="utf-8"))
    assert sv["payload"]["verdict"] == "PASS"
    # tamper-proof history intact + the run is observable
    assert verify_chain(read_events(run_dir / "ledger.jsonl")) == []
    assert classify_status(run_dir) == "done"
    # model_policy flows here too: lead agent experiment-planner (opus) labels every stage in default mode
    assert _obs_models(run_dir) == ["opus", "opus", "opus", "opus", "opus"]


# --------------------------------------------------------------------------- the 3 new gates each BLOCK

def test_preflight_gate_blocks_missing_data_hash(tmp_path):
    runs = tmp_path / "runs"
    with pytest.raises(GateBlock):
        run_task(runs, "fr2", "run without a pinned test data hash", "full_rigor_minimal", TS,
                 make_full_rigor_agent(_fx(test_data_hash=None)), _approve, domain_profile_ref=PROFILE)
    run_dir = runs / "fr2"
    assert classify_status(run_dir) == "crashed_mid_stage"
    pf = json.loads((run_dir / "evidence" / "EXECUTE" / "preflight-report.artifact.json").read_text(encoding="utf-8"))
    assert pf["payload"]["verdict"] == "BLOCK" and pf["payload"]["violations"]
    assert not (run_dir / "evidence" / "ANALYZE").exists()  # never advanced past EXECUTE
    assert not (run_dir / "evidence" / "REPORT").exists()


def test_parity_gate_blocks_post_run_drift(tmp_path):
    runs = tmp_path / "runs"
    with pytest.raises(GateBlock):
        run_task(runs, "fr3", "run where eval augmentation drifted on", "full_rigor_minimal", TS,
                 make_full_rigor_agent(_fx(actual_test=_TEST_DRIFT)), _approve, domain_profile_ref=PROFILE)
    run_dir = runs / "fr3"
    assert classify_status(run_dir) == "crashed_mid_stage"
    pv = json.loads((run_dir / "evidence" / "EXECUTE" / "parity-verdict.artifact.json").read_text(encoding="utf-8"))
    assert pv["payload"]["verdict"] == "BLOCK"
    assert any("post-run drift" in x for x in pv["payload"]["violations"])
    assert not (run_dir / "evidence" / "ANALYZE").exists()  # never advanced past EXECUTE
    assert not (run_dir / "evidence" / "REPORT").exists()


def test_parity_gate_blocks_self_consistent_design_drift(tmp_path):
    runs = tmp_path / "runs"
    # designed fp32 but the run silently switched BOTH train+test to fp16: internally aligned, yet no
    # longer the designed run — the designed-vs-actual check must catch this self-consistent drift.
    actual_train = {**_TRAIN, "precision": "fp16"}
    actual_test = {**_TEST_OK, "precision": "fp16"}
    with pytest.raises(GateBlock):
        run_task(runs, "fr5", "run that silently switched precision", "full_rigor_minimal", TS,
                 make_full_rigor_agent(_fx(actual_train=actual_train, actual_test=actual_test)),
                 _approve, domain_profile_ref=PROFILE)
    run_dir = runs / "fr5"
    assert classify_status(run_dir) == "crashed_mid_stage"
    pv = json.loads((run_dir / "evidence" / "EXECUTE" / "parity-verdict.artifact.json").read_text(encoding="utf-8"))
    assert pv["payload"]["verdict"] == "BLOCK"
    assert any("drifted from design" in x for x in pv["payload"]["violations"])


def test_sanity_gate_blocks_out_of_range_result(tmp_path):
    runs = tmp_path / "runs"
    bad_findings = [{"metric": "dice", "value": 1.5, "condition_id": "c1"}]  # dice > 1.0 is impossible
    with pytest.raises(GateBlock):
        run_task(runs, "fr4", "analyze an impossible result", "full_rigor_minimal", TS,
                 make_full_rigor_agent(_fx(findings=bad_findings)), _approve, domain_profile_ref=PROFILE)
    run_dir = runs / "fr4"
    assert classify_status(run_dir) == "crashed_mid_stage"
    sv = json.loads((run_dir / "evidence" / "ANALYZE" / "sanity-verdict.artifact.json").read_text(encoding="utf-8"))
    assert sv["payload"]["verdict"] == "BLOCK" and sv["payload"]["out_of_range"] == ["dice"]
    assert not (run_dir / "evidence" / "VERIFY").exists()  # never advanced past ANALYZE
