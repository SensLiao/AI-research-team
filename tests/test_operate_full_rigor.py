"""Operate acceptance — drive `full_rigor_minimal` through the STEP-WISE spine (operate.spine +
modes.full_rigor_minimal) the way the research-orchestrator skill does, with stub worker bundles in
place of live sub-agents. Proves the operated twin of tests/test_m2_spine_slice.py:

  - the full DESIGN->EXECUTE->ANALYZE->VERIFY->REPORT tail runs end-to-end on fixtures, every
    artifact contract-valid, with the journal-present (executed) path;
  - the honest journal=null path: parity is SKIPPED and a non-'planned' run_record BLOCKs;
  - each hard gate (variable-control / preflight / sanity / goal-alignment / prereg-deviation) and
    the north-star drift gate demonstrably BLOCKs on an injected violation, halting the run;
  - per-seed data produces real significance stats; its absence is an honest caveat.

The ONLY difference from a live run is fixture bundles instead of real GPU work — the deterministic
governance is the real cores. Run ONLY this file + test_operate_venue_readiness.py.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from research_agent_teams.operate import spine
from research_agent_teams.operate.artifacts import GateBlock
from research_agent_teams.operate.modes import full_rigor_minimal as fr
from research_agent_teams.tools.ledger import read_events, verify_chain
from research_agent_teams.tools.runstore import classify_status
from research_agent_teams.tools.validate_artifact import validate_artifact

TS = "2026-06-13T00:00:00Z"
PROFILE = "cv-medical-segmentation"
REQUEST = "compare a LoRA adapter against full fine-tune for 3D segmentation at equal budget"
NORTH_STAR = {"statement": REQUEST, "in_scope": ["LoRA adapter", "segmentation"],
              "out_of_scope": ["diffusion"]}

# Every metric the cv-medical-segmentation profile declares — the metric-impl gate requires ALL of
# them present (and identical) in every condition, so the fixtures implement the full set.
PROFILE_METRICS = ["Dice", "IoU", "HD95", "clDice", "centerline_continuity",
                   "topology_break_count", "small_structure_recall", "false_disconnection_rate"]


def _all_metric_impls():
    """metric_impls covering every profile metric, identical across both conditions (gate-clean)."""
    impls = {m: {"impl_ref": f"monai.{m.lower()}", "spacing": None, "postprocess": None}
             for m in PROFILE_METRICS}
    return [{"condition_id": "c0", "metric_impls": impls},
            {"condition_id": "c1", "metric_impls": dict(impls)}]


# --------------------------------------------------------------------------- fixtures

def _design_bundle(**over):
    rq = over.get("rq", "Does a LoRA adapter match full fine-tune at equal data budget on fold0?")
    conditions = over.get("conditions", [
        {"id": "c0", "factors": {"adapter": "none", "lr": 1e-4, "epochs": 50,
                                 "backbone": "sam-vit-b", "split": "fold0"}, "baseline": True},
        {"id": "c1", "factors": {"adapter": "lora", "lr": 1e-4, "epochs": 50,
                                 "backbone": "sam-vit-b", "split": "fold0"}},
    ])
    return {
        "design": {
            "rq": rq,
            "variables": {"studied": ["adapter"], "controlled": ["lr", "epochs"],
                          "frozen": ["backbone", "split"]},
            "conditions": conditions,
            "ranked_batch": [{"rank": 1, "condition_id": "c1",
                              "hypothesis": "LoRA adapter matches full fine-tune at equal budget"}],
            "leakage": "All inputs derive from training images only; test masks never read.",
        },
        "train": {"preprocessing": {"spacing": [1, 1, 1]}, "augmentation": {"enabled": True},
                  "pretrained": "none", "precision": "fp32", "inference": {"threshold": 0.5},
                  "label_space": ["bg", "vessel"]},
        "test": {"preprocessing": {"spacing": [1, 1, 1]}, "augmentation": {"enabled": False},
                 "pretrained": "none", "precision": "fp32", "inference": {"threshold": 0.5},
                 "label_space": ["bg", "vessel"]},
        "shared_config": {"optimizer": "adamw"},
        "metric_impls": over.get("metric_impls", _all_metric_impls()),
        "prereg": over.get("prereg", {
            "primary_metric": "Dice", "secondary_metrics": [], "n_seeds_planned": 3,
            "stopping_rule": "fixed 3 seeds per condition",
            "analysis_plan": "paired permutation vs baseline on Dice, Holm-corrected, alpha=0.05"}),
    }


def _execute_bundle(executed=False, **over):
    train_script = {"split": "train", "script": "def build_train():\n    return load('train')",
                    "from_protocol_ref": "protocol_spec",
                    "data_hash_expected": over.get("train_data_hash", "dh-train")}
    test_script = {"split": "test", "script": "def build_test():\n    return load('test')",
                   "from_protocol_ref": "protocol_spec",
                   "data_hash_expected": over.get("test_data_hash", "dh-test"),
                   "augmentation_enabled": False, "frozen": True}
    if "test_data_hash" in over and over["test_data_hash"] is None:
        test_script["data_hash_expected"] = None
    if executed:
        journal = {"condition_id": "c1", "config_hash": "cfg#1", "data_hash": "dh-train", "seed": 0,
                   "designed_train": _design_bundle()["train"], "designed_test": _design_bundle()["test"],
                   "actual_train": _design_bundle()["train"], "actual_test": _design_bundle()["test"],
                   "metrics_snapshot": {"Dice": 0.81}}
        run_records = [{"condition_id": "c1", "status": "provisional",
                        "provenance": {"config_hash": "cfg#1", "data_hash": "dh-train", "seed": 0},
                        "metrics": {"Dice": 0.81}}]
    else:
        journal = None
        run_records = over.get("run_records", [
            {"condition_id": "c1", "status": "planned",
             "provenance": {"config_hash": "cfg#1", "data_hash": "dh-train", "seed": 0}}])
    return {"train_script": train_script, "test_script": test_script,
            "journal": journal, "run_records": run_records}


def _analyze_bundle(**over):
    findings = over.get("findings", [{"metric": "Dice", "value": 0.81, "condition_id": "c1",
                                      "baseline_value": 0.78, "baseline_condition_id": "c0"}])
    per_seed = over.get("per_seed", None)
    return {"findings": findings, "per_seed": per_seed, "caveats": over.get("caveats", [])}


def _verify_bundle(all_pass=True):
    ev = "opened eval code; verified" if all_pass else ""
    return {"checks": {k: {"pass": all_pass, "evidence": ev}
                       for k in ("leakage", "fairness", "eval_frame", "provenance", "overclaim")}}


# --------------------------------------------------------------------------- drivers

def _bundle(run_dir, stage, payload):
    inbox = Path(run_dir) / "inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    (inbox / f"{stage}.bundle.json").write_text(json.dumps(payload), encoding="utf-8")


def _validate_written(paths):
    for p in paths:
        art = json.loads(Path(p).read_text(encoding="utf-8"))
        assert validate_artifact(art) == [], f"artifact failed contract: {p}"


def _begin(runs, run_id, north_star=NORTH_STAR, profile=PROFILE):
    return spine.begin(str(runs), run_id, REQUEST, "full_rigor_minimal", TS,
                       domain_profile_ref=profile, north_star=north_star)


def _drive(run_dir, stage, payload=None):
    if payload is not None:
        _bundle(run_dir, stage, payload)
    spine.open_stage(run_dir, stage, TS)
    paths, rep = fr.run_dets(run_dir, stage, TS)
    res = spine.commit_stage(run_dir, stage, paths, TS)
    return res, rep, paths


# --------------------------------------------------------------------------- 1. happy path (executed)

def test_full_rigor_runs_end_to_end_executed(tmp_path):
    runs = tmp_path / "runs"
    plan = _begin(runs, "fr1")
    rd = plan["run_dir"]
    assert plan["stages"] == ["DESIGN", "EXECUTE", "ANALYZE", "VERIFY", "REPORT"]

    _, d_rep, d_paths = _drive(rd, "DESIGN", _design_bundle())
    assert d_rep == {"vc_gate": "PASS", "metric_gate": "PASS", "alignment_gate": "PASS",
                     "prereg_frozen": True, "n_conditions": 2}
    _validate_written(d_paths)

    _, e_rep, e_paths = _drive(rd, "EXECUTE", _execute_bundle(executed=True))
    assert e_rep == {"preflight_gate": "PASS", "parity_gate": "PASS",
                     "scripts_emitted": True, "executed": True}
    _validate_written(e_paths)

    per_seed = {"c1": {"Dice": [0.80, 0.81, 0.82]}, "c0": {"Dice": [0.77, 0.78, 0.79]}}
    _, a_rep, a_paths = _drive(rd, "ANALYZE", _analyze_bundle(per_seed=per_seed))
    assert a_rep["sanity_gate"] == "PASS" and a_rep["goal_alignment_gate"] == "PASS"
    assert a_rep["prereg_deviation_gate"] == "PASS" and a_rep["stats_computed"] is True
    _validate_written(a_paths)

    _, v_rep, v_paths = _drive(rd, "VERIFY", _verify_bundle())
    assert v_rep["review_gate"] == "APPROVE-FREEZE"
    _validate_written(v_paths)

    r_res, _, r_paths = _drive(rd, "REPORT")
    assert r_res["done"] is True
    _validate_written(r_paths)

    st = spine.status(rd)
    assert st["run_status"] == "done"
    assert st["completed"] == ["DESIGN", "EXECUTE", "ANALYZE", "VERIFY", "REPORT"]
    # tamper-evident history intact end to end
    assert verify_chain(read_events(Path(rd) / "ledger.jsonl")) == []
    # the run is director_signoff-gated and never freezes a number
    assert r_res["gate"] == "director_signoff"
    rs = json.loads((Path(rd) / "evidence" / "ANALYZE" / "result-summary.artifact.json").read_text())
    assert rs["payload"]["status"] == "provisional" and rs["payload"]["can_cite_thesis"] is False


# --------------------------------------------------------------------------- 2. honest scripts-only path

def test_execute_scripts_only_path_skips_parity_and_requires_planned(tmp_path):
    runs = tmp_path / "runs"
    rd = _begin(runs, "fr2")["run_dir"]
    _drive(rd, "DESIGN", _design_bundle())

    # journal=null + planned run_records -> parity SKIPPED, executed False (the honest path)
    _, e_rep, _ = _drive(rd, "EXECUTE", _execute_bundle(executed=False))
    assert e_rep == {"preflight_gate": "PASS", "parity_gate": "SKIPPED(no real run)",
                     "scripts_emitted": True, "executed": False}
    assert not (Path(rd) / "evidence" / "EXECUTE" / "journal-entry.artifact.json").exists()
    assert not (Path(rd) / "evidence" / "EXECUTE" / "parity-verdict.artifact.json").exists()

    # a provisional run_record WITH metrics but NO journal is a self-claim of a run that never ran
    runs2 = tmp_path / "runs2"
    rd2 = _begin(runs2, "fr2b")["run_dir"]
    _drive(rd2, "DESIGN", _design_bundle())
    lying = _execute_bundle(executed=False, run_records=[
        {"condition_id": "c1", "status": "provisional",
         "provenance": {"config_hash": "cfg#1", "data_hash": "dh-train", "seed": 0},
         "metrics": {"Dice": 0.81}}])
    _bundle(rd2, "EXECUTE", lying)
    spine.open_stage(rd2, "EXECUTE", TS)
    with pytest.raises(GateBlock) as ei:
        fr.run_dets(rd2, "EXECUTE", TS)
    assert "no real run" in str(ei.value)
    assert not (Path(rd2) / "evidence" / "ANALYZE").exists()


# --------------------------------------------------------------------------- 3. variable-control BLOCK

def test_variable_control_gate_blocks_confounded_design(tmp_path):
    runs = tmp_path / "runs"
    rd = _begin(runs, "fr3")["run_dir"]
    # c1 changes a NON-studied factor (lr) on top of the studied 'adapter' -> confounded contrast
    confounded = [
        {"id": "c0", "factors": {"adapter": "none", "lr": 1e-4, "epochs": 50,
                                 "backbone": "sam-vit-b", "split": "fold0"}, "baseline": True},
        {"id": "c1", "factors": {"adapter": "lora", "lr": 5e-4, "epochs": 50,
                                 "backbone": "sam-vit-b", "split": "fold0"}},
    ]
    _bundle(rd, "DESIGN", _design_bundle(conditions=confounded))
    spine.open_stage(rd, "DESIGN", TS)
    with pytest.raises(GateBlock) as ei:
        fr.run_dets(rd, "DESIGN", TS)
    assert "confounded" in str(ei.value)
    vc = json.loads((Path(rd) / "evidence" / "DESIGN" /
                     "variable-control-report.artifact.json").read_text())
    assert vc["payload"]["verdict"] == "BLOCK"
    assert not (Path(rd) / "evidence" / "EXECUTE").exists()  # never advanced past DESIGN


# --------------------------------------------------------------------------- 4. preflight BLOCK

def test_preflight_gate_blocks_missing_test_data_hash(tmp_path):
    runs = tmp_path / "runs"
    rd = _begin(runs, "fr4")["run_dir"]
    _drive(rd, "DESIGN", _design_bundle())
    _bundle(rd, "EXECUTE", _execute_bundle(executed=False, test_data_hash=None))
    spine.open_stage(rd, "EXECUTE", TS)
    with pytest.raises(GateBlock):
        fr.run_dets(rd, "EXECUTE", TS)
    pf = json.loads((Path(rd) / "evidence" / "EXECUTE" /
                     "preflight-report.artifact.json").read_text())
    assert pf["payload"]["verdict"] == "BLOCK" and pf["payload"]["violations"]
    assert not (Path(rd) / "evidence" / "ANALYZE").exists()


# --------------------------------------------------------------------------- 5. sanity BLOCK

def test_sanity_gate_blocks_out_of_range_dice(tmp_path):
    runs = tmp_path / "runs"
    rd = _begin(runs, "fr5")["run_dir"]
    _drive(rd, "DESIGN", _design_bundle())
    _drive(rd, "EXECUTE", _execute_bundle(executed=True))
    bad = _analyze_bundle(findings=[{"metric": "Dice", "value": 1.5, "condition_id": "c1"}])
    _bundle(rd, "ANALYZE", bad)
    spine.open_stage(rd, "ANALYZE", TS)
    with pytest.raises(GateBlock):
        fr.run_dets(rd, "ANALYZE", TS)
    sv = json.loads((Path(rd) / "evidence" / "ANALYZE" /
                     "sanity-verdict.artifact.json").read_text())
    assert sv["payload"]["verdict"] == "BLOCK" and sv["payload"]["out_of_range"] == ["Dice"]
    assert not (Path(rd) / "evidence" / "VERIFY").exists()


# --------------------------------------------------------------------------- 6. goal-alignment BLOCK

def test_goal_alignment_gate_blocks_unsupported_generalization_claim(tmp_path):
    runs = tmp_path / "runs"
    # rq claims generalization; the design + findings carry NO external/ood-tagged condition.
    # north_star tuned to share anchors with this rq so the DRIFT gate passes and the
    # GOAL-ALIGNMENT gate is the one that bites (the audit-W2 production hard gate).
    ns = {"statement": "show the LoRA adapter generalizes across segmentation sites",
          "in_scope": ["LoRA adapter", "segmentation"], "out_of_scope": ["diffusion"]}
    rd = spine.begin(str(runs), "fr6",
                     "show the LoRA adapter generalizes across segmentation sites",
                     "full_rigor_minimal", TS, domain_profile_ref=PROFILE, north_star=ns)["run_dir"]
    gen_rq = "Does the LoRA adapter generalize to a new segmentation site at equal budget?"
    _drive(rd, "DESIGN", _design_bundle(rq=gen_rq))
    _drive(rd, "EXECUTE", _execute_bundle(executed=True))
    _bundle(rd, "ANALYZE", _analyze_bundle())  # findings on c1 only, no ood tag
    spine.open_stage(rd, "ANALYZE", TS)
    with pytest.raises(GateBlock) as ei:
        fr.run_dets(rd, "ANALYZE", TS)
    assert "goal-alignment" in str(ei.value)
    ga = json.loads((Path(rd) / "evidence" / "ANALYZE" /
                     "goal-alignment-verdict.artifact.json").read_text())
    assert ga["payload"]["pass"] is False and ga["payload"]["panel_role"] == "goal_alignment"
    # the sanity gate (which runs first) PASSED — proves goal-alignment is the blocking gate here
    sv = json.loads((Path(rd) / "evidence" / "ANALYZE" /
                     "sanity-verdict.artifact.json").read_text())
    assert sv["payload"]["verdict"] == "PASS"


# --------------------------------------------------------------------------- 7. prereg-deviation BLOCK

def test_prereg_deviation_gate_blocks_outcome_switching(tmp_path):
    runs = tmp_path / "runs"
    rd = _begin(runs, "fr7")["run_dir"]
    _drive(rd, "DESIGN", _design_bundle())  # preregisters primary_metric Dice only
    _drive(rd, "EXECUTE", _execute_bundle(executed=True))
    # findings report an UNREGISTERED metric (IoU) — classic outcome switching. Keep Dice present
    # so the failure is specifically the undeclared metric, not the missing primary.
    switched = _analyze_bundle(findings=[
        {"metric": "Dice", "value": 0.81, "condition_id": "c1"},
        {"metric": "IoU", "value": 0.74, "condition_id": "c1"}])
    _bundle(rd, "ANALYZE", switched)
    spine.open_stage(rd, "ANALYZE", TS)
    with pytest.raises(GateBlock) as ei:
        fr.run_dets(rd, "ANALYZE", TS)
    assert "prereg-deviation" in str(ei.value)
    dv = json.loads((Path(rd) / "evidence" / "ANALYZE" /
                     "prereg-deviation-verdict.artifact.json").read_text())
    assert dv["payload"]["pass"] is False and dv["payload"]["panel_role"] == "compliance"
    assert any("IoU" in v for v in dv["payload"]["violations"])


# --------------------------------------------------------------------------- 8. per-seed stats vs caveat

def test_per_seed_produces_stats_else_caveat(tmp_path):
    runs = tmp_path / "runs"
    rd = _begin(runs, "fr8")["run_dir"]
    _drive(rd, "DESIGN", _design_bundle())
    _drive(rd, "EXECUTE", _execute_bundle(executed=True))
    per_seed = {"c1": {"Dice": [0.80, 0.81, 0.82, 0.83]}, "c0": {"Dice": [0.70, 0.71, 0.72, 0.73]}}
    _, a_rep, _ = _drive(rd, "ANALYZE", _analyze_bundle(per_seed=per_seed))
    assert a_rep["stats_computed"] is True
    rs = json.loads((Path(rd) / "evidence" / "ANALYZE" /
                     "result-summary.artifact.json").read_text())["payload"]
    f0 = rs["findings"][0]
    assert "p_value" in f0 and "significant_after_correction" in f0 and "n_seeds" in f0
    assert rs["stats"]["n_findings_tested"] == 1

    # no per_seed -> no stats, an honest caveat is recorded
    runs2 = tmp_path / "runs2"
    rd2 = _begin(runs2, "fr8b")["run_dir"]
    _drive(rd2, "DESIGN", _design_bundle())
    _drive(rd2, "EXECUTE", _execute_bundle(executed=True))
    _, a_rep2, _ = _drive(rd2, "ANALYZE", _analyze_bundle(per_seed=None))
    assert a_rep2["stats_computed"] is False
    rs2 = json.loads((Path(rd2) / "evidence" / "ANALYZE" /
                      "result-summary.artifact.json").read_text())["payload"]
    assert any("no significance computed" in c for c in rs2["caveats"])
    assert "p_value" not in rs2["findings"][0]


# --------------------------------------------------------------------------- 9. drift BLOCK

def test_drift_gate_blocks_out_of_scope_topic_in_design(tmp_path):
    runs = tmp_path / "runs"
    # north_star explicitly excludes "diffusion"; the DESIGN rq introduces it -> provable drift.
    rd = _begin(runs, "fr9")["run_dir"]
    drift_rq = "Does a diffusion adapter beat the LoRA adapter at equal budget on segmentation?"
    _bundle(rd, "DESIGN", _design_bundle(rq=drift_rq))
    spine.open_stage(rd, "DESIGN", TS)
    with pytest.raises(GateBlock) as ei:
        fr.run_dets(rd, "DESIGN", TS)
    assert "drift" in str(ei.value).lower()
    dv = json.loads((Path(rd) / "evidence" / "DESIGN" /
                     "drift-verdict.artifact.json").read_text())
    assert dv["payload"]["pass"] is False
    assert any("diffusion" in v for v in dv["payload"]["violations"])
    assert not (Path(rd) / "evidence" / "EXECUTE").exists()


# --------------------------------------------------------------------------- 10. llm_step dispatch shape

def test_full_rigor_llm_step_shape(tmp_path):
    runs = tmp_path / "runs"
    rd = _begin(runs, "fr10")["run_dir"]
    # every WORK stage dispatches one worker carrying the north-star block + complete bundle shape +
    # honesty + repair clauses; REPORT is deterministic (None).
    labels = {"DESIGN": "design-worker", "EXECUTE": "execute-worker",
              "ANALYZE": "analyze-worker", "VERIFY": "adversarial-reviewer"}
    for st, label in labels.items():
        s = fr.llm_step(rd, st, REQUEST, model_policy="default")
        assert s["label"] == label
        assert s["output"].endswith(f"inbox/{st}.bundle.json")
        for marker in ("NORTH STAR", "HONESTY", "REPAIR ATTEMPT"):
            assert marker in s["prompt"], f"{st} prompt missing {marker}"
    assert fr.llm_step(rd, "REPORT", REQUEST) is None
    # default routing: DESIGN/VERIFY = opus (judgment), EXECUTE/ANALYZE = sonnet (scoped execution)
    assert fr.llm_step(rd, "DESIGN", REQUEST, model_policy="default")["model"] == "opus"
    assert fr.llm_step(rd, "VERIFY", REQUEST, model_policy="default")["model"] == "opus"
    assert fr.llm_step(rd, "EXECUTE", REQUEST, model_policy="default")["model"] == "sonnet"
    # max_quality -> all opus
    assert fr.llm_step(rd, "EXECUTE", REQUEST, model_policy="max_quality")["model"] == "opus"
