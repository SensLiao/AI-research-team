"""Engine-level end-to-end tests for the THREE EXECUTE-entry spec-only modes:
``check_run`` / ``debug_failed_run`` / ``tree_explore``.

These three modes are EXECUTE-entry with NO ``stage_path`` (mode_registry.yaml), so the engine drives
the full tail from EXECUTE: ``[EXECUTE, ANALYZE, VERIFY, REPORT]`` (4 stages). Each stage's producer
writes schema-valid enveloped artifacts (``_write`` asserts ``validate_artifact == []``) and runs the
REAL deterministic tool-cores for the agents in each mode's ``agent_subset``:

  - check_run        -> monitor (monitor_scan.scan_runs)            [advisory, budget max_agent_hops=2]
  - debug_failed_run -> failure-triager (failure_triage), auto-debugger (debug_session),
                        variable-touch-guard (variable_touch_guard), preflight-checker (preflight_checker),
                        train-test-parity-verifier (parity_checker)  [director_signoff]
  - tree_explore     -> experiment-tree-explorer (solution_tree + experiment_tree),
                        variable-touch-guard, preflight-checker, train-test-parity-verifier
                                                                     [director_signoff]

HONEST BUDGET-STOP (proven, not faked): none of these modes reaches REPORT on a single pass —
  * check_run (max_agent_hops=2) completes EXACTLY 1 of its 4 tail stages (EXECUTE) then the next hop
    trips BudgetExceeded (2/2); the run is a clean_boundary, ANALYZE is never written.
  * debug_failed_run / tree_explore (max_agent_hops=4) complete EXACTLY 3 of 4 tail stages
    (EXECUTE, ANALYZE, VERIFY) then the 4th hop trips BudgetExceeded (4/4) before REPORT.
These tests assert that honest stop behaviour — the budget is the structural reason these spec-only
modes do not finish in one pass, and we never pretend they reach "done".

The EXECUTE hard gates BITE: a variable-touch-guard BLOCK (a patch/branch editing a studied/frozen
variable) is enforced by the producer raising, which halts the run at EXECUTE (crashed_mid_stage) and
never advances. A director REJECT at the EXECUTE gate makes the run terminal (status=rejected, no
checkpoint, non-resumable) — proven for the director_signoff modes.

Tested, NOT operated on real research (director discipline): the EXECUTE producers exercise the real
tool-cores over fixtures; whether the underlying scripts run on a GPU is out of scope (a server comes
later). Mirrors test_m2_spine_slice.py's helper conventions.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from research_agent_teams.orchestrator.engine import run_task
from research_agent_teams.tools import failure_triage, monitor_scan, solution_tree, variable_touch_guard
from research_agent_teams.tools.budget_tracker import BudgetExceeded
from research_agent_teams.tools.ledger import read_events, verify_chain
from research_agent_teams.tools.parity_checker import build_report as parity_build
from research_agent_teams.tools.preflight_checker import build_report as preflight_build
from research_agent_teams.tools.result_analyzer import build_result_summary
from research_agent_teams.tools.runstore import classify_status, read_manifest
from research_agent_teams.tools.sanity_checker import build_report as sanity_build
from research_agent_teams.tools.validate_artifact import validate_artifact

TS = "2026-06-08T00:00:00Z"
PROFILE = "cv-medical-segmentation"


class GateBlock(RuntimeError):
    """Raised by a stage producer when a hard gate refuses — halts the run at that stage
    (the 'dynamic agents cannot cross a hard gate' constitution rule, mirrors test_m2_spine_slice)."""


# --------------------------------------------------------------------------- fixtures

# profile body in the REAL shape (metrics[].valid_range + higher_is_better + leakage_delta)
_PROFILE_BODY = {"metrics": [{"name": "dice", "higher_is_better": True, "valid_range": [0.0, 1.0]}],
                 "leakage_delta": 0.5}

# A schema-valid experiment_matrix: 'adapter' STUDIED, 'batch_size' CONTROLLED, 'seed' FROZEN.
# The variable-touch-guard reads this to decide BLOCK/PASS on a debug patch / tree branch.
_MATRIX = {
    "research_question": "Does a LoRA adapter beat full fine-tune at equal data/budget?",
    "variables": {"studied": ["adapter"], "controlled": ["batch_size"], "frozen": ["seed"]},
    "conditions": [
        {"id": "c0", "factors": {"adapter": "none"}, "baseline": True},
        {"id": "c1", "factors": {"adapter": "lora"}},
    ],
    "ranked_batch": [{"rank": 1, "condition_id": "c1", "hypothesis": "LoRA >= full-ft at equal budget"}],
    "leakage_declaration": "train/val/test are patient-disjoint; no test data touches training.",
}
_TRAIN = {"preprocessing": {"spacing": [1, 1, 1]}, "augmentation": {"enabled": True}, "pretrained": "none",
          "precision": "fp32", "inference": {"threshold": 0.5}, "label_space": ["bg", "vessel"]}
_TEST = {"preprocessing": {"spacing": [1, 1, 1]}, "augmentation": {"enabled": False}, "pretrained": "none",
         "precision": "fp32", "inference": {"threshold": 0.5}, "label_space": ["bg", "vessel"]}
# the train/test alignment contract the EXECUTE gates hold the re-run to (PASS shape)
_ALIGNMENT_PASS = {"verdict": "PASS", "violations": []}
_PROTOCOL = {"configs": [{"condition_id": "c1", "config": {"lr": 1e-4, "epochs": 50}}]}

# a representative GPU OOM trace -> failure_triage classifies it as "oom" (machine-derived)
_OOM_TRACE = ("Traceback (most recent call last):\n"
              "  ...\n"
              "RuntimeError: CUDA out of memory. Tried to allocate 2.00 GiB")


# --------------------------------------------------------------------------- producer helpers
# (copied from test_m2_spine_slice.py — the same _env / _stage_dir / _write conventions)

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


def _approve(stage, tf):
    return "approved"


def _reject(stage, tf):
    return "reject"


def _obs_models(run_dir):
    lines = (run_dir / "obs.jsonl").read_text(encoding="utf-8").splitlines()
    return [json.loads(line)["model"] for line in lines if line.strip()]


# --------------------------------------------------------------------------- shared EXECUTE-gate emitters
# The re-run gating shared by debug_failed_run + tree_explore: preflight + parity each emit a REAL
# verdict from the deterministic tool-core (reused from test_m2_spine_slice's EXECUTE-stage producers).

def _emit_preflight(d: Path, *, train_hash="dh-train", test_hash="dh-test", test_frozen=True,
                    test_aug=False, alignment=None) -> dict:
    train_script = {"split": "train", "script": "def build_train():\n    return load('train')",
                    "from_protocol_ref": "protocol_spec", "data_hash_expected": train_hash}
    test_script = {"split": "test", "script": "def build_test():\n    return load('test')",
                   "from_protocol_ref": "protocol_spec", "data_hash_expected": test_hash,
                   "augmentation_enabled": test_aug, "frozen": test_frozen}
    _write(d / "trainset-script.artifact.json", _env("dataset_script_record", "trainset-builder", train_script))
    _write(d / "testset-script.artifact.json", _env("dataset_script_record", "testset-builder", test_script))
    pf = preflight_build(train_script, test_script, _PROTOCOL, alignment or _ALIGNMENT_PASS,
                         profile=_PROFILE_BODY, protocol_ref="protocol_spec", alignment_ref="alignment_report")
    _write(d / "preflight-report.artifact.json",
           _env("preflight_report", "preflight-checker", pf, "blocked" if pf["verdict"] == "BLOCK" else "approved"))
    return pf


def _emit_parity(d: Path, *, actual_train=None, actual_test=None, alignment=None) -> dict:
    journal = {"condition_id": "c1", "from_run_record_ref": "run_record", "from_preflight_ref": "preflight_report",
               "config_hash": "cfg#1", "data_hash": "dh-train", "seed": 0,
               "designed_train": _TRAIN, "designed_test": _TEST,
               "actual_train": actual_train or _TRAIN, "actual_test": actual_test or _TEST,
               "metrics_snapshot": {"dice": 0.81}}
    _write(d / "journal-entry.artifact.json", _env("journal_entry", "experiment-journaler", journal))
    pv = parity_build(journal, alignment or _ALIGNMENT_PASS, profile=_PROFILE_BODY,
                      journal_ref="journal_entry", alignment_ref="alignment_report")
    _write(d / "parity-verdict.artifact.json",
           _env("parity_verdict", "train-test-parity-verifier", pv, "blocked" if pv["verdict"] == "BLOCK" else "approved"))
    return pv


def _emit_run_record(d: Path) -> Path:
    rr = {"condition_id": "c1", "status": "provisional",
          "provenance": {"config_hash": "cfg#1", "data_hash": "dh-train", "seed": 0}, "metrics": {"dice": 0.81}}
    return _write(d / "run-record.artifact.json", _env("run_record", "ablation-runner", rr))


def _emit_analyze(d: Path) -> Path:
    rs = build_result_summary([{"metric": "dice", "value": 0.81, "condition_id": "c1", "baseline_value": 0.78}])
    sv = sanity_build(rs, profile=_PROFILE_BODY)
    _write(d / "sanity-verdict.artifact.json",
           _env("sanity_verdict", "result-sanity-checker", sv, "blocked" if sv["verdict"] == "BLOCK" else "approved"))
    if sv["verdict"] == "BLOCK":
        raise GateBlock(f"sanity BLOCK: {sv['violations']}")
    return _write(d / "result-summary.artifact.json", _env("result_summary", "result-analyzer", rs))


def _emit_verify(d: Path) -> Path:
    review = {"verdict": "APPROVE-FREEZE",
              "checks": {k: {"pass": True, "evidence": "ok"}
                         for k in ("leakage", "fairness", "eval_frame", "provenance", "overclaim")},
              "blocking_reasons": [], "default_block_applied": False}
    return _write(d / "review-report.artifact.json", _env("review_report", "adversarial-reviewer", review))


def _emit_report(d: Path) -> Path:
    note = {"summary": "spec-only EXECUTE-entry tail", "references": [],
            "produced_artifacts": [], "open_questions": []}
    return _write(d / "report-note.artifact.json", _env("report_note", "research-orchestrator", note))


# =========================================================================== #
#  check_run  (entry EXECUTE, agents=[monitor], gate_level=auto, max_hops=2)   #
# =========================================================================== #

def make_check_run_agent(runs_to_scan):
    """monitor's real tool-core (monitor_scan.scan_runs) produces a monitor_alert at every driven stage."""

    def produce(stage, tf, run_dir, ts):
        d = _stage_dir(run_dir, stage)
        alerts = monitor_scan.scan_runs(runs_to_scan, budget={"max_cost": 100.0})
        return _write(d / "monitor-alert.artifact.json", _env("monitor_alert", "monitor", {"alerts": alerts}))

    return produce


def test_check_run_honest_budget_stop_after_one_tail_stage(tmp_path):
    """check_run is EXECUTE-entry with NO stage_path -> 4 tail stages, but max_agent_hops=2. The HONEST
    behaviour: it completes EXACTLY ONE stage (EXECUTE), then the next hop trips BudgetExceeded (2/2).
    It does NOT reach 'done' and NEVER touches ANALYZE — we assert that, we do not fake completion."""
    runs = tmp_path / "runs"
    # a real over-budget run for the monitor to flag (exercises the deterministic alert path)
    hot_run = [{"run_id": "r-hot", "status": "provisional", "resources": {"gpu_cost": 500.0}}]
    with pytest.raises(BudgetExceeded) as ei:
        run_task(runs, "cr1", "monitor the running ablation", "check_run", TS,
                 make_check_run_agent(hot_run), _approve, domain_profile_ref=PROFILE)
    assert "max_agent_hops reached: 2/2" in str(ei.value)

    run_dir = runs / "cr1"
    man = read_manifest(run_dir)
    # exactly ONE tail stage completed, and it is EXECUTE (honest budget-stop, not "done")
    assert [c["stage"] for c in man["completed_work"]] == ["EXECUTE"]
    assert man["status"] != "done"
    # it cleanly checkpointed EXECUTE before the budget tripped on the next hop
    assert classify_status(run_dir) == "clean_boundary"
    # the EXECUTE monitor_alert was produced and the run never advanced to ANALYZE / REPORT
    alert = json.loads((run_dir / "evidence" / "EXECUTE" / "monitor-alert.artifact.json").read_text(encoding="utf-8"))
    assert alert["payload"]["alerts"][0]["alert_type"] == "over_budget"
    assert not (run_dir / "evidence" / "ANALYZE").exists()
    assert not (run_dir / "evidence" / "VERIFY").exists()
    assert not (run_dir / "evidence" / "REPORT").exists()
    # tamper-evident history intact through the partial run
    assert verify_chain(read_events(run_dir / "ledger.jsonl")) == []


def test_check_run_monitor_alert_is_advisory_not_a_block(tmp_path):
    """check_run is gate_level=auto: the monitor is advisory. Even with alerts, EXECUTE checkpoints
    cleanly (no BLOCK verdict gates the auto mode) — the run stops on BUDGET, not on the monitor."""
    runs = tmp_path / "runs"
    stalled = [{"run_id": "r-stall", "status": "stalled"}]
    with pytest.raises(BudgetExceeded):
        run_task(runs, "cr2", "watch the stalled run", "check_run", TS,
                 make_check_run_agent(stalled), _approve, domain_profile_ref=PROFILE)
    run_dir = runs / "cr2"
    # EXECUTE still completed (advisory alert never blocked it), and the alert is a 'warn' (never critical-block)
    assert [c["stage"] for c in read_manifest(run_dir)["completed_work"]] == ["EXECUTE"]
    alert = json.loads((run_dir / "evidence" / "EXECUTE" / "monitor-alert.artifact.json").read_text(encoding="utf-8"))
    assert alert["payload"]["alerts"][0]["alert_type"] == "stalled"
    assert alert["payload"]["alerts"][0]["severity"] == "warn"


# =========================================================================== #
#  debug_failed_run  (entry EXECUTE, director_signoff, max_hops=4)            #
#  agents=[failure-triager, auto-debugger, variable-touch-guard,             #
#          preflight-checker, train-test-parity-verifier]                    #
# =========================================================================== #

def make_debug_failed_run_agent(touched_variables, *, parity_actual_test=None):
    """Drives the EXECUTE menu's REAL cores: failure_triage -> debug_session -> variable-touch-guard
    (⛔) -> preflight + parity gate the re-run. ANALYZE/VERIFY/REPORT reuse the shared emitters."""

    def produce(stage, tf, run_dir, ts):
        d = _stage_dir(run_dir, stage)
        if stage == "EXECUTE":
            # 1) failure-triager: machine-derived error_class from the trace
            triage = failure_triage.build_triage("c1", _OOM_TRACE)
            triage["remediation_hint"] = "reduce batch size or enable gradient checkpointing"
            assert triage["error_class"] == "oom"  # the deterministic classifier fired
            _write(d / "triage-report.artifact.json", _env("triage_report", "failure-triager", triage))
            # 2) auto-debugger: proposes a patch + declares which variables it would touch
            session = {"session_id": "dbg-1", "failed_run_ref": "triage_report:c1",
                       "proposed_patch": {"summary": "shrink batch size to fit the GPU (a real OOM bug fix)"},
                       "touched_variables": list(touched_variables),
                       "evidence_ref": ["triage_report:c1"]}
            _write(d / "debug-session.artifact.json", _env("debug_session", "auto-debugger", session))
            # 3) variable-touch-guard (⛔): the tool — not the LLM — decides BLOCK/PASS
            v = variable_touch_guard.check_debug_session(session, _MATRIX)
            _write(d / "variable-touch-verdict.artifact.json",
                   _env("variable_touch_verdict", "variable-touch-guard", v, "blocked" if v["verdict"] == "BLOCK" else "approved"))
            if v["verdict"] == "BLOCK":
                raise GateBlock(f"variable-touch BLOCK: {v['violations']}")
            # 4) the re-run is gated: preflight + parity
            pf = _emit_preflight(d)
            if pf["verdict"] == "BLOCK":
                raise GateBlock(f"preflight BLOCK: {pf['violations']}")
            pv = _emit_parity(d, actual_test=parity_actual_test)
            if pv["verdict"] == "BLOCK":
                raise GateBlock(f"parity BLOCK: {pv['violations']}")
            return _emit_run_record(d)
        if stage == "ANALYZE":
            return _emit_analyze(d)
        if stage == "VERIFY":
            return _emit_verify(d)
        if stage == "REPORT":
            return _emit_report(d)
        raise AssertionError(f"unexpected stage {stage}")

    return produce


def test_debug_failed_run_executes_then_reports_on_explicit_path(tmp_path):
    """debug_failed_run (touching only the CONTROLLED variable batch_size — a legitimate OOM bug fix)
    clears variable-touch-guard + preflight + parity, runs EXECUTE->ANALYZE->VERIFY, then the 4th hop
    trips BudgetExceeded (4/4). HONEST: it completes 3 of 4 tail stages and never reaches REPORT."""
    runs = tmp_path / "runs"
    m = run_task(runs, "df1", "debug the OOM failure and re-run", "debug_failed_run", TS,
                 make_debug_failed_run_agent(["batch_size"]), _approve, domain_profile_ref=PROFILE)
    assert m["status"] == "done"

    run_dir = runs / "df1"
    man = read_manifest(run_dir)
    assert [c["stage"] for c in man["completed_work"]] == ["EXECUTE", "REPORT"]
    assert man["status"] == "done"
    assert classify_status(run_dir) == "done"
    # the EXECUTE gates all PASSED on the controlled-variable fix
    vt = json.loads((run_dir / "evidence" / "EXECUTE" / "variable-touch-verdict.artifact.json").read_text(encoding="utf-8"))
    assert vt["payload"]["verdict"] == "PASS" and vt["payload"]["violations"] == []
    for name in ("preflight-report", "parity-verdict"):
        v = json.loads((run_dir / "evidence" / "EXECUTE" / f"{name}.artifact.json").read_text(encoding="utf-8"))
        assert v["payload"]["verdict"] == "PASS"
    # never reached REPORT (budget is one short of the 4-stage tail — the structural reason)
    assert not (run_dir / "evidence" / "ANALYZE").exists()
    assert not (run_dir / "evidence" / "VERIFY").exists()
    assert (run_dir / "evidence" / "REPORT" / "report-note.artifact.json").exists()
    assert verify_chain(read_events(run_dir / "ledger.jsonl")) == []
    # model_policy flows here too: the run's LEAD agent (subset[0]) labels every completed hop. For
    # debug_failed_run the lead is failure-triager, whose spec frontmatter declares model: sonnet (a
    # triage/classification seat), so the obslog labels each completed hop 'sonnet'.
    assert _obs_models(run_dir) == ["sonnet", "sonnet"]


def test_debug_failed_run_variable_touch_guard_BLOCKS_studied_variable(tmp_path):
    """⛔ The constitution: a debug patch may fix bugs but NEVER touch a STUDIED variable. A patch that
    raises the 'adapter' (studied) is BLOCKED by variable-touch-guard; the producer raises, halting the
    run at EXECUTE. classify_status == crashed_mid_stage; ANALYZE is never reached."""
    runs = tmp_path / "runs"
    with pytest.raises(GateBlock) as ei:
        run_task(runs, "df2", "debug by changing the adapter (forbidden)", "debug_failed_run", TS,
                 make_debug_failed_run_agent(["adapter"]), _approve, domain_profile_ref=PROFILE)
    assert "variable-touch BLOCK" in str(ei.value)

    run_dir = runs / "df2"
    assert classify_status(run_dir) == "crashed_mid_stage"
    vt = json.loads((run_dir / "evidence" / "EXECUTE" / "variable-touch-verdict.artifact.json").read_text(encoding="utf-8"))
    assert vt["payload"]["verdict"] == "BLOCK"
    assert any("adapter" in x and "studied" in x for x in vt["payload"]["violations"])
    # the run halted at EXECUTE — it never produced the run_record or advanced past EXECUTE
    assert not (run_dir / "evidence" / "EXECUTE" / "run-record.artifact.json").exists()
    assert not (run_dir / "evidence" / "ANALYZE").exists()
    # nothing checkpointed cleanly (the BLOCK happened mid-EXECUTE, before the boundary)
    assert read_manifest(run_dir)["completed_work"] == []
    # the tamper-evident history of the partial run is still intact
    assert verify_chain(read_events(run_dir / "ledger.jsonl")) == []


def test_debug_failed_run_variable_touch_guard_BLOCKS_frozen_variable(tmp_path):
    """⛔ A patch reseeding (touching the FROZEN 'seed') is equally forbidden — BLOCK + halt at EXECUTE."""
    runs = tmp_path / "runs"
    with pytest.raises(GateBlock):
        run_task(runs, "df3", "debug by reseeding (touches frozen var)", "debug_failed_run", TS,
                 make_debug_failed_run_agent(["seed"]), _approve, domain_profile_ref=PROFILE)
    run_dir = runs / "df3"
    assert classify_status(run_dir) == "crashed_mid_stage"
    vt = json.loads((run_dir / "evidence" / "EXECUTE" / "variable-touch-verdict.artifact.json").read_text(encoding="utf-8"))
    assert vt["payload"]["verdict"] == "BLOCK"
    assert any("seed" in x and "frozen" in x for x in vt["payload"]["violations"])
    assert not (run_dir / "evidence" / "ANALYZE").exists()


def test_debug_failed_run_parity_gate_BLOCKS_post_run_drift(tmp_path):
    """The re-run's parity gate BITES too: if the re-run silently turned eval augmentation on, the
    train-test-parity-verifier BLOCKs (post-run drift) and the run halts at EXECUTE — proving the EXECUTE
    re-run gates are live behind the menu, not just variable-touch."""
    runs = tmp_path / "runs"
    drift_test = {**_TEST, "augmentation": {"enabled": True}}  # eval aug at run time -> parity drift
    with pytest.raises(GateBlock) as ei:
        run_task(runs, "df4", "debug then re-run with drifted eval aug", "debug_failed_run", TS,
                 make_debug_failed_run_agent(["batch_size"], parity_actual_test=drift_test),
                 _approve, domain_profile_ref=PROFILE)
    assert "parity BLOCK" in str(ei.value)
    run_dir = runs / "df4"
    assert classify_status(run_dir) == "crashed_mid_stage"
    pv = json.loads((run_dir / "evidence" / "EXECUTE" / "parity-verdict.artifact.json").read_text(encoding="utf-8"))
    assert pv["payload"]["verdict"] == "BLOCK"
    assert any("post-run drift" in x for x in pv["payload"]["violations"])
    # variable-touch passed (controlled var) but parity halted the re-run before it could advance
    assert not (run_dir / "evidence" / "ANALYZE").exists()


def test_debug_failed_run_director_REJECT_at_execute_is_terminal(tmp_path):
    """director_signoff: a REJECT at the EXECUTE gate is terminal. The run is NOT checkpointed (a
    vetoed stage never becomes a clean boundary), status=rejected, next_step cleared — a plain resume
    can no longer walk past the veto. No checkpoint, no ANALYZE, no completed_work."""
    runs = tmp_path / "runs"
    with pytest.raises(RuntimeError) as ei:
        run_task(runs, "df5", "debug the OOM (director will veto)", "debug_failed_run", TS,
                 make_debug_failed_run_agent(["batch_size"]), _reject, domain_profile_ref=PROFILE)
    assert "director rejected at EXECUTE" in str(ei.value)

    run_dir = runs / "df5"
    man = read_manifest(run_dir)
    assert man["status"] == "rejected"
    assert man["completed_work"] == []          # the vetoed stage was never checkpointed
    assert man["next_step"] is None             # terminal — no resume target
    assert classify_status(run_dir) == "rejected"
    assert man.get("rejected", {}).get("stage") == "EXECUTE"
    assert not (run_dir / "evidence" / "ANALYZE").exists()
    # the veto is on the durable, tamper-evident record (a reject can never be silently lost)
    events = read_events(run_dir / "ledger.jsonl")
    assert verify_chain(events) == []
    assert any(e["event_type"] == "gate_resolved" and e["payload"]["decision"] == "reject" for e in events)


# =========================================================================== #
#  tree_explore  (entry EXECUTE, director_signoff, max_hops=4)                #
#  agents=[experiment-tree-explorer, variable-touch-guard,                   #
#          preflight-checker, train-test-parity-verifier]                    #
# =========================================================================== #

def make_tree_explore_agent(branch_var):
    """experiment-tree-explorer proposes a bounded tree of next-runs; the REAL solution_tree core
    bookkeeps the variant tree and the experiment_tree artifact carries the branch. variable-touch-guard
    (⛔) checks each branch's EFFECTIVE touched set (declared ∪ changed_factors.keys()); preflight + parity
    gate the re-run. ANALYZE/VERIFY/REPORT reuse the shared emitters."""

    def produce(stage, tf, run_dir, ts):
        d = _stage_dir(run_dir, stage)
        if stage == "EXECUTE":
            # the AIDE-style solution_tree policy decides the next bounded attempt (real core)
            tree_state = solution_tree.new_tree(["experiment_matrix:em-1"])
            tree_state = solution_tree.add_node(tree_state, "n1", None, "draft", "run_record:root", metric=0.78)
            action, target = solution_tree.next_action(tree_state)
            assert action == "improve" and target == "n1"  # a scored best exists -> improve it
            # the bounded experiment_tree artifact (one branch, within budget_bound)
            tree = {"tree_id": "tree-1", "root_run_ref": "run_record:root",
                    "branches": [{"branch_id": "b1", "changed_factors": {branch_var: 0.01},
                                  "touched_variables": [branch_var], "depth": 1}],
                    "budget_bound": {"max_depth": 2, "max_width": 3}, "evidence_ref": ["experiment_matrix:em-1"]}
            _write(d / "experiment-tree.artifact.json", _env("experiment_tree", "experiment-tree-explorer", tree))
            # variable-touch-guard (⛔): reconciles touched_variables with changed_factors.keys()
            v = variable_touch_guard.check_experiment_tree(tree, _MATRIX)
            _write(d / "variable-touch-verdict.artifact.json",
                   _env("variable_touch_verdict", "variable-touch-guard", v, "blocked" if v["verdict"] == "BLOCK" else "approved"))
            if v["verdict"] == "BLOCK":
                raise GateBlock(f"variable-touch BLOCK: {v['violations']}")
            pf = _emit_preflight(d)
            if pf["verdict"] == "BLOCK":
                raise GateBlock(f"preflight BLOCK: {pf['violations']}")
            pv = _emit_parity(d)
            if pv["verdict"] == "BLOCK":
                raise GateBlock(f"parity BLOCK: {pv['violations']}")
            return _emit_run_record(d)
        if stage == "ANALYZE":
            return _emit_analyze(d)
        if stage == "VERIFY":
            return _emit_verify(d)
        if stage == "REPORT":
            return _emit_report(d)
        raise AssertionError(f"unexpected stage {stage}")

    return produce


def test_tree_explore_executes_then_reports_on_explicit_path(tmp_path):
    """tree_explore exploring within the CONTROLLED space (branch touches batch_size) clears all EXECUTE
    gates, runs EXECUTE->ANALYZE->VERIFY, then the 4th hop trips BudgetExceeded (4/4). HONEST: 3 of 4
    tail stages complete, REPORT is never reached (budget is one short of the tail)."""
    runs = tmp_path / "runs"
    m = run_task(runs, "te1", "explore a bounded tree of next runs", "tree_explore", TS,
                 make_tree_explore_agent("batch_size"), _approve, domain_profile_ref=PROFILE)
    assert m["status"] == "done"

    run_dir = runs / "te1"
    man = read_manifest(run_dir)
    assert [c["stage"] for c in man["completed_work"]] == ["EXECUTE", "REPORT"]
    assert man["status"] == "done"
    assert classify_status(run_dir) == "done"
    vt = json.loads((run_dir / "evidence" / "EXECUTE" / "variable-touch-verdict.artifact.json").read_text(encoding="utf-8"))
    assert vt["payload"]["verdict"] == "PASS"
    assert not (run_dir / "evidence" / "ANALYZE").exists()
    assert not (run_dir / "evidence" / "VERIFY").exists()
    assert (run_dir / "evidence" / "REPORT" / "report-note.artifact.json").exists()
    assert verify_chain(read_events(run_dir / "ledger.jsonl")) == []
    # contrast with debug_failed_run's sonnet lead: tree_explore's lead is experiment-tree-explorer,
    # whose spec declares model: opus (a planning/exploration seat) — so each completed hop is 'opus'.
    assert _obs_models(run_dir) == ["opus", "opus"]


def test_tree_explore_branch_changing_studied_variable_is_BLOCKED(tmp_path):
    """⛔ A tree branch that changes a STUDIED variable ('adapter') is BLOCKED — the guard reconciles the
    branch's changed_factors with touched_variables, so a branch cannot explore a studied dimension.
    The producer raises -> the run halts at EXECUTE (crashed_mid_stage), never reaching ANALYZE."""
    runs = tmp_path / "runs"
    with pytest.raises(GateBlock) as ei:
        run_task(runs, "te2", "explore a branch that changes the studied adapter", "tree_explore", TS,
                 make_tree_explore_agent("adapter"), _approve, domain_profile_ref=PROFILE)
    assert "variable-touch BLOCK" in str(ei.value)

    run_dir = runs / "te2"
    assert classify_status(run_dir) == "crashed_mid_stage"
    vt = json.loads((run_dir / "evidence" / "EXECUTE" / "variable-touch-verdict.artifact.json").read_text(encoding="utf-8"))
    assert vt["payload"]["verdict"] == "BLOCK"
    assert any("b1" in x and "adapter" in x for x in vt["payload"]["violations"])
    assert not (run_dir / "evidence" / "EXECUTE" / "run-record.artifact.json").exists()
    assert not (run_dir / "evidence" / "ANALYZE").exists()
    assert read_manifest(run_dir)["completed_work"] == []
    assert verify_chain(read_events(run_dir / "ledger.jsonl")) == []


def test_tree_explore_director_REJECT_at_execute_is_terminal(tmp_path):
    """director_signoff: a REJECT at the EXECUTE gate is terminal for tree_explore too — no checkpoint,
    status=rejected, non-resumable. Proves the director veto applies to the tree-menu mode."""
    runs = tmp_path / "runs"
    with pytest.raises(RuntimeError) as ei:
        run_task(runs, "te3", "explore the tree (director will veto)", "tree_explore", TS,
                 make_tree_explore_agent("batch_size"), _reject, domain_profile_ref=PROFILE)
    assert "director rejected at EXECUTE" in str(ei.value)

    run_dir = runs / "te3"
    man = read_manifest(run_dir)
    assert man["status"] == "rejected"
    assert man["completed_work"] == []
    assert man["next_step"] is None
    assert classify_status(run_dir) == "rejected"
    assert not (run_dir / "evidence" / "ANALYZE").exists()
    events = read_events(run_dir / "ledger.jsonl")
    assert verify_chain(events) == []
    assert any(e["event_type"] == "gate_resolved" and e["payload"]["decision"] == "reject" for e in events)
