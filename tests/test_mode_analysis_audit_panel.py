"""Operate recipe for `analysis_audit_panel`: independence, disagreement, and claim-evidence.

The registry's gap for this mode is *"run diagnostic seats independently before synthesis"* plus
*"deterministic cross-panel coverage, disagreement, and claim-evidence checks"*. These tests hold
that contract rather than merely exercising the code path:

  * a judgment seat is never TOLD to read another judgment seat's bundle (the independence assertion);
  * two seats reaching opposite conclusions produce a rendered disagreement with BOTH positions and
    no winner;
  * a calibrated claim that cannot be traced to a real piece of evidence BLOCKs;
  * a synthesis that drops a diagnostic seat BLOCKs;
  * a finding about a figure nobody drew BLOCKs.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from research_agent_teams.operate.artifacts import GateBlock
from research_agent_teams.operate.modes import _panel_recipe, _shared
from research_agent_teams.operate.modes import analysis_audit_panel as mode
from research_agent_teams.tools.validate_artifact import validate_artifact

TS = "2026-08-04T12:00:00Z"
REQUEST = "audit whether the petct residual-correction analysis supports its claims"
AUDITED_RESULTS = "inbox/analysis-under-audit/results.json"
AUDITED_SEEDS = "inbox/analysis-under-audit/per-seed.json"


@pytest.fixture(autouse=True)
def _offline_vault(monkeypatch):
    """Force the offline vault state so slug checks are deterministic in CI and on the director's box."""
    monkeypatch.setattr(_shared, "VAULT_ROOT_OVERRIDE", False)


# --------------------------------------------------------------------------- fixture


def _mk_run(tmp_path, budget=None):
    run_dir = tmp_path / "run-1"
    (run_dir / "inbox").mkdir(parents=True)
    audited = run_dir / "inbox" / "analysis-under-audit"
    audited.mkdir()
    (audited / "results.json").write_text(
        json.dumps({"accuracy": {"ours_petct": 0.91, "baseline_petct": 0.88}}), encoding="utf-8")
    (audited / "per-seed.json").write_text(
        json.dumps({"accuracy": [0.910, 0.912, 0.908]}), encoding="utf-8")
    task_frame = {"payload": {
        "task_id": "run-1", "mode": "analysis_audit_panel", "request_text": REQUEST,
        "north_star": {"statement": "petct residual correction analysis audit",
                       "in_scope": ["petct"], "out_of_scope": ["topology continuity"]},
        "domain_profile_ref": "ai-generic",
        "agent_subset": list(mode.DIAGNOSTIC_SEATS) + list(mode._RESOLVERS),
        "budget": budget or {"max_agent_hops": 40, "max_debug_retries_per_run": 3}}}
    (run_dir / "task_frame.artifact.json").write_text(json.dumps(task_frame), encoding="utf-8")
    return run_dir


def _matrix():
    factors = {"data_source": "petct-internal-v3", "epochs": 100,
               "metric_impl_ref": "sklearn.accuracy_score", "primary_metric": "accuracy",
               "postprocess": "argmax"}
    return {"research_question": "Does petct residual correction outperforms the baseline on accuracy?",
            "conditions": [{"id": "baseline_petct", "factors": dict(factors, baseline=True)},
                           {"id": "ours_petct", "factors": dict(factors)}]}


def _figures(y_min=0.0):
    return {"run_ref": AUDITED_RESULTS, "figures": [
        {"figure_id": "fig1_accuracy_by_condition", "figure_type": "bar",
         "title": "petct accuracy by condition", "data_source": AUDITED_RESULTS,
         "x_axis": {"label": "condition"},
         "y_axis": {"label": "accuracy", "min": y_min, "error_bars": "std"},
         "conditions": ["baseline_petct", "ours_petct"], "metrics": ["accuracy"],
         "caption": "petct accuracy, 3 seeds", "notes": ""},
        {"figure_id": "fig2_per_seed_spread", "figure_type": "boxplot",
         "title": "petct per-seed spread", "data_source": AUDITED_SEEDS,
         "x_axis": {"label": "seed"}, "y_axis": {"label": "accuracy", "min": 0.0},
         "conditions": ["ours_petct"], "metrics": ["accuracy"],
         "caption": "petct per-seed accuracy", "notes": ""}]}


def _bundles():
    """A complete, internally consistent clean panel: every seat delivered, nothing contradicts."""
    seeds = [{"condition_id": "ours_petct", "seed": s, "metrics": {"accuracy": v},
              "source_ref": AUDITED_SEEDS}
             for s, v in ((1, 0.910), (2, 0.912), (3, 0.908))]
    return {
        "result-sanity-checker": {"result_summary": {
            "findings": [{"metric": "accuracy", "value": 0.91, "condition_id": "ours_petct",
                          "baseline_value": 0.88, "source_ref": AUDITED_RESULTS},
                         {"metric": "f1", "value": 0.87, "condition_id": "ours_petct",
                          "baseline_value": 0.85, "source_ref": AUDITED_RESULTS}],
            "caveats": ["petct cohort is single-centre"], "sources_read": [AUDITED_RESULTS]}},
        "baseline-comparison-auditor": {"baseline_audit_inputs": {
            "baseline_condition_id": "baseline_petct", "method_condition_id": "ours_petct",
            "experiment_matrix": _matrix(), "notes": "petct configs read from the staged plan",
            "sources_read": [AUDITED_RESULTS]}},
        "variance-analyzer": {"variance_inputs": {
            "condition_id": "ours_petct", "run_records": seeds,
            "declared_stability_label": "stable",
            "notes": "three petct seeds logged", "sources_read": [AUDITED_SEEDS]}},
        "fairness-auditor": {"fairness_inputs": {
            "result_summary": {"findings": [
                {"metric": "accuracy", "value": 0.93, "condition_id": "ours_petct",
                 "stratum": "lesion", "stratum_key": "label"},
                {"metric": "accuracy", "value": 0.89, "condition_id": "ours_petct",
                 "stratum": "background", "stratum_key": "label"}]},
            "run_records": [dict(row, stratum="lesion", stratum_key="label") for row in seeds],
            "notes": "petct per-label results are published", "sources_read": [AUDITED_RESULTS]}},
        "compliance-auditor": {"compliance_inputs": {
            "experiment_matrix": {"conditions": [{"id": "baseline_petct"}, {"id": "ours_petct"}]},
            "run_records": [{"condition_id": "baseline_petct", "source_ref": AUDITED_SEEDS},
                            {"condition_id": "ours_petct", "source_ref": AUDITED_SEEDS}],
            "notes": "both petct conditions have logs", "sources_read": [AUDITED_SEEDS]}},
        "goal-alignment-checker": {"alignment_inputs": {
            "experiment_matrix": _matrix(),
            "result_summary": {"findings": [{"metric": "accuracy", "value": 0.91,
                                             "condition_id": "ours_petct"}]},
            "notes": "petct headline claim is a baseline comparison", "sources_read": [AUDITED_RESULTS]}},
        "failure-case-miner": {"failure_inventory": {
            "condition_id": "ours_petct", "failures": [
                {"type": "false_negative", "description": "petct lesion missed on low-uptake case",
                 "case_ref": "case-042", "metric_context": "accuracy=0.31",
                 "hypothesized_cause": "low tracer uptake"},
                {"type": "boundary_error", "description": "petct boundary bleeds into liver",
                 "case_ref": "case-117", "metric_context": "accuracy=0.55",
                 "hypothesized_cause": None}],
            "summary": "petct failures concentrate on low-uptake lesions",
            "sources_read": [AUDITED_RESULTS]}},
        "figure-generator": {"figure_spec_bundle": _figures()},
        "claim-strength-calibrator": {"claim_calibration_inputs": {
            "source_ref": AUDITED_RESULTS, "claims": [
                {"original_claim": "petct residual correction improves accuracy by 3 points",
                 "metric": "accuracy", "delta": 0.03, "variance": 0.0016,
                 "original_strength": "strong", "evidence_ref": [AUDITED_RESULTS]},
                {"original_claim": "the petct gain holds on every seed", "metric": "accuracy",
                 "delta": 0.02, "variance": 0.0016, "original_strength": "moderate",
                 "evidence_ref": [AUDITED_SEEDS]}],
            "notes": "both petct claims are numeric"}},
        "visualization-auditor": {"viz_audit_inputs": {
            "declared_clean": True, "per_figure": [
                {"figure_id": "fig1_accuracy_by_condition", "concern": "ok", "severity": "info",
                 "detail": "petct bar chart starts at zero and draws error bars",
                 "evidence_ref": ["figure_spec/fig1_accuracy_by_condition/y_axis.min=0.0"]},
                {"figure_id": "fig2_per_seed_spread", "concern": "ok", "severity": "info",
                 "detail": "petct boxplot shows the spread by design", "evidence_ref": [AUDITED_SEEDS]}],
            "notes": "both petct figures assessed"}},
        "figure-vlm-critic": {"figure_critique_inputs": {"per_figure": [
            {"figure_id": "fig1_accuracy_by_condition", "finding_type": "ok", "severity": "info",
             "detail": "petct caption matches the plotted comparison",
             "evidence_ref": ["figure_spec/fig1_accuracy_by_condition"]},
            {"figure_id": "fig2_per_seed_spread", "finding_type": "ok", "severity": "info",
             "detail": "petct spread is visible", "evidence_ref": ["figure_spec/fig2_per_seed_spread"]}],
            "notes": "no rendered image was available; specs and captions only"}},
        "quality-controller": {"coverage_review": {
            "seats_reviewed": [{"seat": seat, "reviewed": True, "verdict_read": "PASS",
                                "note": f"{seat} delivered its petct diagnostic"}
                               for seat in mode.DIAGNOSTIC_SEATS],
            "disagreements": [], "unreviewed_gaps": [],
            "notes": "the petct analysis supports its two numeric claims"}},
        "integrity-refusal-recommender": {"integrity_scan_input": {
            "claims": [{"claim_id": "IC-1",
                        "text": "petct residual correction improves accuracy by 3 points",
                        "evidence_ref": [AUDITED_RESULTS], "asserts_result": True}],
            "extra_flags": [], "notes": "nothing withheld"}},
    }


def _write_bundles(run_dir, bundles):
    for label, payload in bundles.items():
        (run_dir / "inbox" / f"ANALYZE.{label}.bundle.json").write_text(
            json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _markdown(run_dir) -> str:
    return (run_dir / _panel_recipe.target_markdown(mode.MODE)["path"]).read_text(encoding="utf-8")


# --------------------------------------------------------------------------- 1. happy path


def test_clean_panel_passes_and_renders_every_required_section(tmp_path):
    run_dir = _mk_run(tmp_path)
    _write_bundles(run_dir, _bundles())

    paths, report = mode.run_dets(run_dir, "ANALYZE", TS)

    for path in paths:
        artifact = json.loads(Path(path).read_text(encoding="utf-8"))
        assert validate_artifact(artifact) == [], f"{path} failed its contract"

    written = {json.loads(Path(p).read_text(encoding="utf-8"))["artifact_type"] for p in paths}
    assert {"sanity_verdict", "baseline_audit_report", "variance_report", "analysis_check_verdict",
            "failure_inventory", "figure_spec_bundle", "viz_audit_report", "figure_critique",
            "calibrated_claims", "stage_scorecard", "integrity_recommendation"} <= written

    assert report["sanity_gate"] == "PASS"
    assert report["baseline_clean"] is True
    assert report["variance_sufficient"] is True
    assert report["claim_evidence_gate"] == "PASS"
    assert report["cross_panel_coverage"] == "PASS"
    assert report["independent_diagnostic_seats"] == 11
    assert report["stage_pass"] is True
    assert report["n_disagreements_derived"] == 0
    assert report["integrity_recommendation"] == "PROCEED"
    assert report["existence_gate"] == "NOT_APPLICABLE"  # no bibliography — reported, not faked

    text = _markdown(run_dir)
    for section in _panel_recipe.target_markdown(mode.MODE)["required_sections"]:
        assert f"## {section}" in text
        body = text.split(f"## {section}", 1)[1].split("\n## ", 1)[0].strip()
        assert body, f"required section {section!r} rendered empty"
    assert "无 —— 已检查 11 个独立诊断席位的产出，没有阻断项。" in text
    assert "Panel independence and coverage" in text

    report_paths, _ = mode.run_dets(run_dir, "REPORT", TS)
    note = json.loads(Path(report_paths[0]).read_text(encoding="utf-8"))
    assert validate_artifact(note) == []
    assert _panel_recipe.target_markdown(mode.MODE)["path"] in note["payload"]["references"]
    assert "executed nothing itself" in note["payload"]["summary"]


# --------------------------------------------------------------------------- 2. missing seat


def test_missing_seat_bundle_blocks_and_names_the_file(tmp_path):
    run_dir = _mk_run(tmp_path)
    bundles = _bundles()
    del bundles["variance-analyzer"]
    _write_bundles(run_dir, bundles)

    with pytest.raises(GateBlock) as excinfo:
        mode.run_dets(run_dir, "ANALYZE", TS)
    assert "ANALYZE.variance-analyzer.bundle.json" in str(excinfo.value)


# --------------------------------------------------------------------------- 3. the mode's own gates


def test_untraceable_calibrated_claim_blocks(tmp_path):
    run_dir = _mk_run(tmp_path)
    bundles = _bundles()
    bundles["claim-strength-calibrator"]["claim_calibration_inputs"]["claims"][0]["evidence_ref"] = [
        "Table 2", "as reported in our results"]
    _write_bundles(run_dir, bundles)

    with pytest.raises(GateBlock) as excinfo:
        mode.run_dets(run_dir, "ANALYZE", TS)
    message = str(excinfo.value)
    assert "claim-evidence BLOCK" in message
    assert "Table 2" in message


def test_claim_may_not_launder_another_seats_output_as_evidence(tmp_path):
    run_dir = _mk_run(tmp_path)
    bundles = _bundles()
    bundles["claim-strength-calibrator"]["claim_calibration_inputs"]["claims"][0]["evidence_ref"] = [
        "inbox/ANALYZE.variance-analyzer.bundle.json"]
    _write_bundles(run_dir, bundles)

    with pytest.raises(GateBlock) as excinfo:
        mode.run_dets(run_dir, "ANALYZE", TS)
    assert "claim-evidence BLOCK" in str(excinfo.value)


def test_dropped_diagnostic_seat_blocks_the_synthesis(tmp_path):
    run_dir = _mk_run(tmp_path)
    bundles = _bundles()
    review = bundles["quality-controller"]["coverage_review"]
    review["seats_reviewed"] = [row for row in review["seats_reviewed"]
                               if row["seat"] != "failure-case-miner"]
    _write_bundles(run_dir, bundles)

    with pytest.raises(GateBlock) as excinfo:
        mode.run_dets(run_dir, "ANALYZE", TS)
    message = str(excinfo.value)
    assert "cross-panel coverage BLOCK" in message
    assert "failure-case-miner" in message


def test_finding_about_a_figure_nobody_drew_blocks(tmp_path):
    run_dir = _mk_run(tmp_path)
    bundles = _bundles()
    bundles["figure-vlm-critic"]["figure_critique_inputs"]["per_figure"].append(
        {"figure_id": "fig9_ghost", "finding_type": "misleading_axis", "severity": "critical",
         "detail": "invented", "evidence_ref": ["figure_spec/fig9_ghost"]})
    _write_bundles(run_dir, bundles)

    with pytest.raises(GateBlock) as excinfo:
        mode.run_dets(run_dir, "ANALYZE", TS)
    assert "fig9_ghost" in str(excinfo.value)


def test_hand_raised_derived_integrity_kind_blocks(tmp_path):
    run_dir = _mk_run(tmp_path)
    bundles = _bundles()
    bundles["integrity-refusal-recommender"]["integrity_scan_input"]["extra_flags"] = [
        {"kind": "unsupported_number", "locus": "IC-1", "severity": "high", "detail": "hand-raised"}]
    _write_bundles(run_dir, bundles)

    with pytest.raises(GateBlock) as excinfo:
        mode.run_dets(run_dir, "ANALYZE", TS)
    assert "unsupported_number" in str(excinfo.value)


# --------------------------------------------------------------------------- 4. unknown stage


def test_unknown_stage_raises_value_error(tmp_path):
    run_dir = _mk_run(tmp_path)
    with pytest.raises(ValueError, match="has no stage 'IDEATE'"):
        mode.run_dets(run_dir, "IDEATE", TS)


# --------------------------------------------------------------------------- 5. dispatch contract


def test_every_dispatched_label_is_declared_in_the_registry(tmp_path):
    run_dir = _mk_run(tmp_path)
    spec = mode.llm_step(run_dir, "ANALYZE", REQUEST)
    declared = set(_panel_recipe.declared_seats(mode.MODE))

    labels = [worker["label"] for worker in spec["workers"]]
    assert set(labels) <= declared
    assert len(labels) == len(set(labels)) == len(declared)
    assert spec["parallel_groups"] == [
        list(mode._CORE + mode._VALIDITY + (mode._FIGURE_PRODUCER, mode._CLAIM)),
        list(mode._FIGURE_AUDITORS), list(mode._RESOLVERS)]
    assert mode.llm_step(run_dir, "REPORT", REQUEST) is None
    # Model routing under the DEFAULT policy: every seat that GRADES someone else's numbers is on
    # opus; `figure-generator` is the one production seat and runs on sonnet — its output is graded
    # by visualization-auditor and figure-vlm-critic, which are both on opus.
    assert {w["label"]: w["model"] for w in spec["workers"]
            if w["model"] != "opus"} == {mode._FIGURE_PRODUCER: "sonnet"}
    for worker in spec["workers"]:
        assert "NORTH STAR" in worker["prompt"]
        assert "FLOOR" in worker["prompt"]
        assert "at most" not in worker["prompt"].lower()


# --------------------------------------------------------------------------- 6. independence


def test_no_judgment_seat_is_told_to_read_another_judgment_seats_bundle(tmp_path):
    run_dir = _mk_run(tmp_path)
    spec = mode.llm_step(run_dir, "ANALYZE", REQUEST)
    prompts = {worker["label"]: worker["prompt"] for worker in spec["workers"]}
    contracts = {worker["label"]: worker["input_contract"] for worker in spec["workers"]}

    for seat in mode.INDEPENDENT_JUDGMENT_SEATS:
        for other in mode.INDEPENDENT_JUDGMENT_SEATS:
            if other == seat:
                continue
            bundle = f"ANALYZE.{other}.bundle.json"
            assert bundle not in prompts[seat], f"{seat} was told to read {other}'s bundle"
            assert mode._bundle_rel(other) in contracts[seat]["forbidden_inputs"]
        assert contracts[seat]["blind"] is True
        assert not any(dep in mode.INDEPENDENT_JUDGMENT_SEATS
                       for dep in (spec["workers"][0].get("depends_on") or []))

    # The one deliberate shared read: the figure specs are the OBJECT under audit.
    for auditor in mode._FIGURE_AUDITORS:
        assert mode._bundle_rel(mode._FIGURE_PRODUCER) in prompts[auditor]
        assert mode._bundle_rel(mode._FIGURE_PRODUCER) in contracts[auditor]["allowed_inputs"]

    # Only the two resolvers may see the whole panel.
    for resolver in mode._RESOLVERS:
        assert contracts[resolver]["forbidden_inputs"] == []
        for seat in mode.DIAGNOSTIC_SEATS:
            assert mode._bundle_rel(seat) in contracts[resolver]["allowed_inputs"]


# --------------------------------------------------------------------------- 7. disagreement


def _contradictory_bundles():
    """One seed sold as 'stable', a truncated axis declared clean, and two critics who disagree."""
    bundles = copy.deepcopy(_bundles())
    bundles["result-sanity-checker"]["result_summary"]["findings"][0].update(
        {"value": 0.95, "baseline_value": 0.40})            # leakage smell vs a clean baseline audit
    variance = bundles["variance-analyzer"]["variance_inputs"]
    variance["run_records"] = variance["run_records"][:1]    # 1 seed, still called "stable"
    bundles["figure-generator"]["figure_spec_bundle"] = _figures(y_min=0.94)
    bundles["figure-vlm-critic"]["figure_critique_inputs"]["per_figure"][0].update(
        {"finding_type": "truncated_axis", "severity": "warn",
         "detail": "petct y-axis starts at 0.94, so a 3-point gain looks like a landslide"})
    return bundles


def test_opposing_seats_produce_a_rendered_unresolved_disagreement(tmp_path):
    run_dir = _mk_run(tmp_path)
    _write_bundles(run_dir, _contradictory_bundles())

    paths, report = mode.run_dets(run_dir, "ANALYZE", TS)
    for path in paths:
        assert validate_artifact(json.loads(Path(path).read_text(encoding="utf-8"))) == []

    assert report["n_disagreements_derived"] >= 4
    assert report["sanity_gate"] == "BLOCK"      # reported, never a halt: the audit must be delivered
    assert report["variance_sufficient"] is False
    assert report["viz_clean"] is False
    assert report["stage_pass"] is False
    assert report["n_blocking_issues"] > 0

    text = _markdown(run_dir)
    assert "Cross-panel disagreements (machine-derived, unresolved)" in text
    assert text.count("UNRESOLVED — shown to the director") >= 4
    # BOTH positions reach the director; the machine never resolves the contradiction for them.
    assert "leakage smell" in text and "no asymmetry found" in text
    assert "the analysis calls the result 'stable'" in text
    assert "declared the figures clean" in text and "axis truncation flagged" in text
    assert "figure-vlm-critic" in text and "raised no concern" in text
    assert "已检查 11 个独立诊断席位的产出，没有阻断项" not in text


def test_declared_stability_that_the_seed_count_denies_is_reported(tmp_path):
    run_dir = _mk_run(tmp_path)
    bundles = copy.deepcopy(_bundles())
    variance = bundles["variance-analyzer"]["variance_inputs"]
    variance["run_records"] = [dict(variance["run_records"][0], seed=7)] * 3  # one seed, thrice
    _write_bundles(run_dir, bundles)

    _paths, report = mode.run_dets(run_dir, "ANALYZE", TS)
    assert report["n_seeds"] == 1
    assert report["variance_sufficient"] is False
    text = _markdown(run_dir)
    assert "1 distinct seed(s) -> 'insufficient_data'" in text


# --------------------------------------------------------------------------- 8. honest emptiness


def test_empty_failure_inventory_is_reported_as_a_coverage_gap_not_a_clean_bill(tmp_path):
    run_dir = _mk_run(tmp_path)
    bundles = copy.deepcopy(_bundles())
    bundles["failure-case-miner"]["failure_inventory"].update(
        {"failures": [], "summary": "the petct analysis publishes no per-case output"})
    _write_bundles(run_dir, bundles)

    paths, report = mode.run_dets(run_dir, "ANALYZE", TS)
    assert report["n_failure_cases"] == 0
    assert report["stage_pass"] is False
    assert not any(path.endswith("failure-inventory.artifact.json") for path in paths)
    text = _markdown(run_dir)
    assert "这本身是一个覆盖缺口，不是干净的证明" in text
