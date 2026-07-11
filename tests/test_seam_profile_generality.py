"""DoD #5 — domain generality: the SAME full-rigor pipeline runs end-to-end under a SECOND domain
profile (nlp-text-classification), not just cv-medical. This is the missing half of build-plan §7 #5
("the same pipeline runs under >=2 profiles on fixtures") — the 3 profiles were already proven to
*conform* (test_validate_artifact); here the NLP profile actually *drives a run*.

The profile body is LOADED FROM THE REAL nlp profile yaml (not hand-typed) so the proof tracks the
profile: macro_f1 / accuracy metrics, leakage_delta, document split. Reuses the proven engine + the
real deterministic gates (variable-control / alignment / preflight / parity / sanity), mirroring the
cv-medical full_rigor_minimal acceptance with NLP-flavored fixtures throughout (no dice / no spacing).

Tested, NOT operated (no GPU); execution emits scripts-as-artifacts, same boundary as the cv e2e.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

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
from research_agent_teams.tools.variable_control_checker import build_report as vc_build
# reuse the proven harness helpers (envelope / stage-dir / write / approve / GateBlock)
from research_agent_teams.tests.test_m2_spine_slice import (
    GateBlock,
    TS,
    _approve,
    _env,
    _stage_dir,
    _write,
)

NLP_PROFILE = "nlp-text-classification"
_PROFILE_PATH = (Path(__file__).resolve().parent.parent / "profiles"
                 / "nlp-text-classification.profile.yaml")


def _nlp_profile_body() -> dict:
    """Load the REAL nlp profile and shape it for the gate checkers (metrics + leakage_delta)."""
    p = yaml.safe_load(_PROFILE_PATH.read_text(encoding="utf-8"))
    return {"metrics": p["metrics"], "leakage_delta": p["leakage_delta"]}


# --------------------------------------------------------------------------- NLP fixtures

_NLP_DESIGN = {
    "rq": "Does prompt-tuning beat full fine-tune at equal data/budget for text classification?",
    "variables": {"studied": ["adapter"], "controlled": ["lr", "epochs"], "frozen": ["base_model", "split"]},
    "conditions": [
        {"id": "c0", "factors": {"adapter": "none", "lr": 2e-5, "epochs": 3, "base_model": "bert-base", "split": "fold0"}, "baseline": True},
        {"id": "c1", "factors": {"adapter": "prompt-tuning", "lr": 2e-5, "epochs": 3, "base_model": "bert-base", "split": "fold0"}},
    ],
    "ranked_batch": [{"rank": 1, "condition_id": "c1", "hypothesis": "prompt-tuning >= full-ft at equal budget"}],
    "leakage": "Splits are document-disjoint; near-duplicate documents removed; test frozen before training.",
}
# same KEYS the alignment checker reads, NLP values; train/test align except train-only augmentation
_NLP_TRAIN = {"preprocessing": {"tokenizer": "bert-base-uncased", "max_length": 256},
              "augmentation": {"enabled": True}, "pretrained": "bert-base-uncased",
              "precision": "fp32", "inference": {"threshold": 0.5}, "label_space": ["neg", "neu", "pos"]}
_NLP_TEST = {**_NLP_TRAIN, "augmentation": {"enabled": False}}


def _nlp_fx(**over):
    base = {
        "design": _NLP_DESIGN, "train": _NLP_TRAIN, "test": _NLP_TEST,
        "actual_train": _NLP_TRAIN, "actual_test": _NLP_TEST,
        "train_data_hash": "dh-train-nlp", "test_data_hash": "dh-test-nlp",
        "findings": [{"metric": "macro_f1", "value": 0.82, "condition_id": "c1", "baseline_value": 0.79}],
        "profile_body": _nlp_profile_body(),
    }
    base.update(over)
    return base


def _make_nlp_rigor_agent(fx):
    """Mirror of make_full_rigor_agent, NLP-flavored throughout (macro_f1, no dice/spacing). Drives
    all 5 stages of full_rigor_minimal through the real gates under the nlp profile."""
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
                          "provenance": {"config_hash": "cfg#1", "data_hash": "dh-train-nlp", "seed": 0},
                          "metrics": {"macro_f1": 0.82}}
            _write(d / "run-record.artifact.json", _env("run_record", "ablation-runner", run_record))
            journal = {"condition_id": "c1", "from_run_record_ref": "run_record", "from_preflight_ref": "preflight_report",
                       "config_hash": "cfg#1", "data_hash": "dh-train-nlp", "seed": 0,
                       "designed_train": fx["train"], "designed_test": fx["test"],
                       "actual_train": fx["actual_train"], "actual_test": fx["actual_test"],
                       "metrics_snapshot": {"macro_f1": 0.82}}
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
            note = {"summary": "NLP full-rigor run complete", "references": [],
                    "produced_artifacts": [], "open_questions": []}
            return _write(d / "report-note.artifact.json", _env("report_note", "research-orchestrator", note))

        raise AssertionError(f"unexpected stage {stage}")

    return produce


# --------------------------------------------------------------------------- DoD #5 proof

def test_full_pipeline_runs_under_nlp_profile(tmp_path):
    """The SAME full_rigor_minimal pipeline runs DESIGN→...→REPORT under the nlp profile on NLP
    fixtures — proving the machine is domain-general, not medical-only (DoD #5)."""
    runs = tmp_path / "runs"
    m = run_task(runs, "nlp1", "design+run+analyze+review the prompt-tuning ablation", "full_rigor_minimal",
                 TS, _make_nlp_rigor_agent(_nlp_fx()), _approve, domain_profile_ref=NLP_PROFILE)
    assert m["status"] == "done"
    assert [c["stage"] for c in m["completed_work"]] == ["DESIGN", "EXECUTE", "ANALYZE", "VERIFY", "REPORT"]
    run_dir = runs / "nlp1"
    assert m["domain_profile_ref"] == NLP_PROFILE                     # the nlp profile actually drove it
    for name in ("preflight-report", "parity-verdict"):
        v = json.loads((run_dir / "evidence" / "EXECUTE" / f"{name}.artifact.json").read_text(encoding="utf-8"))
        assert v["payload"]["verdict"] == "PASS"
    sv = json.loads((run_dir / "evidence" / "ANALYZE" / "sanity-verdict.artifact.json").read_text(encoding="utf-8"))
    assert sv["payload"]["verdict"] == "PASS"                          # macro_f1 0.82 in [0,1], no leakage smell
    assert verify_chain(read_events(run_dir / "ledger.jsonl")) == []
    assert classify_status(run_dir) == "done"


def test_sanity_gate_is_live_under_nlp_profile(tmp_path):
    """A hard gate still BLOCKs under the 2nd profile: macro_f1 = 1.4 is out of the nlp profile's
    [0,1] range ⇒ sanity BLOCK ⇒ run halts at ANALYZE (gates are not cv-only)."""
    runs = tmp_path / "runs"
    bad = [{"metric": "macro_f1", "value": 1.4, "condition_id": "c1"}]
    with pytest.raises(GateBlock):
        run_task(runs, "nlp2", "analyze an impossible macro_f1", "full_rigor_minimal", TS,
                 _make_nlp_rigor_agent(_nlp_fx(findings=bad)), _approve, domain_profile_ref=NLP_PROFILE)
    run_dir = runs / "nlp2"
    assert classify_status(run_dir) == "crashed_mid_stage"
    sv = json.loads((run_dir / "evidence" / "ANALYZE" / "sanity-verdict.artifact.json").read_text(encoding="utf-8"))
    assert sv["payload"]["verdict"] == "BLOCK" and sv["payload"]["out_of_range"] == ["macro_f1"]
    assert not (run_dir / "evidence" / "VERIFY").exists()
