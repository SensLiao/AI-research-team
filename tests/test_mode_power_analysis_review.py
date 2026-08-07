"""Operate wave-2 mode: power_analysis_review (DESIGN -> REPORT).

Covers the registry's own self-approval gap: a staged data-protocol -> power-and-sensitivity ->
independent-methodology-review panel, with every sensitivity scenario and the `sufficient` verdict
deterministically recomputed rather than taken on the worker's word.
"""
from __future__ import annotations

import json

import pytest

from research_agent_teams.operate.artifacts import GateBlock
from research_agent_teams.operate.modes import _panel_recipe as pr
from research_agent_teams.operate.modes import power_analysis_review as mod
from research_agent_teams.tools.stats_test import approx_paired_power
from research_agent_teams.tools.validate_artifact import validate_artifact

TS = "2026-08-04T12:00:00Z"
MODE = "power_analysis_review"


def _mk_run(tmp_path):
    run_dir = tmp_path / "run-1"
    (run_dir / "inbox").mkdir(parents=True)
    tf = {"payload": {"task_id": "run-1", "mode": "test",
                      "request_text": "Paired pre/post comparison, n=8 seeds, primary endpoint Dice "
                                      "similarity at 30 days, 1:1 treatment vs control.",
                      "north_star": {"statement": "Assess power for the paired Dice-improvement "
                                                   "design.",
                                     "in_scope": ["power", "sample size", "sensitivity"],
                                     "out_of_scope": []},
                      "budget": {"max_agent_hops": 3, "max_debug_retries_per_run": 3}}}
    (run_dir / "task_frame.artifact.json").write_text(json.dumps(tf), encoding="utf-8")
    return run_dir


def _write_bundle(run_dir, label, payload):
    path = run_dir / "inbox" / f"DESIGN.{label}.bundle.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _scenario(label, mean_diff, sd_diff, n, alpha=0.05, rationale="test rationale"):
    return {"label": label, "mean_diff": mean_diff, "sd_diff": sd_diff, "n": n, "alpha": alpha,
            "reported_power": approx_paired_power(mean_diff, sd_diff, n, alpha),
            "rationale": rationale}


def _default_scenarios():
    return [
        _scenario("conservative", 0.03, 0.08, 8, rationale="Cohen's small-effect convention"),
        _scenario("moderate", 0.05, 0.08, 8, rationale="pilot-observed midpoint estimate"),
        _scenario("optimistic", 0.09, 0.08, 8, rationale="pilot-observed best-arm estimate"),
    ]


def _data_protocol_bundle():
    return {"data_protocol": {
        "from_split_manifest_ref": None,
        "steps": [
            {"step_id": "s1", "kind": "resampling",
             "description": "impute missing follow-up via last-observation-carried-forward",
             "train_only": False, "params": {}, "applies_to_splits": []},
            {"step_id": "s2", "kind": "normalization",
             "description": "z-score the primary endpoint within arm",
             "train_only": False, "params": {}, "applies_to_splits": []},
        ],
        "notes": "Sample size: n=8 paired seeds. Primary endpoint: Dice similarity coefficient at "
                 "30 days. Grouping: treatment vs control, 1:1 paired by patient. Missingness: 10% "
                 "assumed dropout, handled via LOCF.",
    }}


def _power_audit_bundle(scenarios=None, *, n_seeds=8, min_seeds=5, sufficient=True):
    return {"power_audit_report": {
        "sufficient": sufficient, "n_seeds_declared": n_seeds, "min_seeds_required": min_seeds,
        "power_concerns": ["baseline auditor note: variance estimate stable across scenarios"],
        "adr_override_ref": None,
        "notes": "computed via standard paired z-approximation power formula",
        "sensitivity_scenarios": _default_scenarios() if scenarios is None else scenarios,
    }}


def _panel_review_bundle(*, lens="methodology", reviewer_notes=None, findings=None):
    if reviewer_notes is None:
        reviewer_notes = (
            "Option A: collect 2 more seeds to raise the conservative-scenario power above 0.8. "
            "Option B: accept the current power and narrow the claim to the optimistic-bracket-"
            "only scope, explicitly caveated.")
    if findings is None:
        findings = [{"anchor": "conservative scenario power",
                    "evidence": "power under the small-effect bracket is well below the "
                               "conventional 0.8 target",
                    "severity": "WARN", "rebuttal_required": False, "finding_id": "meth-1"}]
    return {"panel_review": {"lens": lens, "findings": findings, "reviewer_notes": reviewer_notes}}


def _write_all_bundles(run_dir, *, dp=None, pa=None, mr=None):
    _write_bundle(run_dir, "data-protocol-designer",
                 dp if dp is not None else _data_protocol_bundle())
    _write_bundle(run_dir, "statistics-power-auditor",
                 pa if pa is not None else _power_audit_bundle())
    _write_bundle(run_dir, "methodology-reviewer",
                 mr if mr is not None else _panel_review_bundle())


# --------------------------------------------------------------------------- llm_step / dispatch


def test_llm_step_design_dispatches_declared_seats(tmp_path):
    run_dir = _mk_run(tmp_path)
    panel = mod.llm_step(str(run_dir), "DESIGN", "review this design", model_policy="default")
    labels = [w["label"] for w in panel["workers"]]
    assert set(labels) == set(pr.declared_seats(MODE))
    by_label = {w["label"]: w for w in panel["workers"]}
    assert by_label["statistics-power-auditor"]["depends_on"] == ["data-protocol-designer"]
    assert set(by_label["methodology-reviewer"]["depends_on"]) == {
        "data-protocol-designer", "statistics-power-auditor"}
    # every label llm_step dispatches must be a declared seat (brief requirement #5)
    assert set(labels) <= set(pr.declared_seats(MODE))


def test_llm_step_report_is_none(tmp_path):
    run_dir = _mk_run(tmp_path)
    assert mod.llm_step(str(run_dir), "REPORT", "review this design") is None


# --------------------------------------------------------------------------- happy path


def test_happy_path_design_and_report(tmp_path):
    run_dir = _mk_run(tmp_path)
    _write_all_bundles(run_dir)

    paths, report = mod.run_dets(str(run_dir), "DESIGN", TS)

    # every produced artifact validates against its schema
    for p in paths:
        artifact = json.loads((run_dir.parent / p).read_text(encoding="utf-8")) \
            if not str(p).startswith(str(run_dir)) else json.loads(open(p, encoding="utf-8").read())
        errs = validate_artifact(artifact)
        assert errs == [], f"{p} failed validation: {errs}"

    assert report["n_scenarios"] == 3
    assert report["sufficient"] is True
    assert report["n_seeds_declared"] == 8
    assert 0.0 <= report["worst_case_power"] <= report["best_case_power"] <= 1.0
    assert report["reviewer_findings"] == 1
    assert report["reviewer_block_findings"] == 0

    md_rel = report["director_markdown"]
    assert md_rel == pr.target_markdown(MODE)["path"]
    md_text = (run_dir / md_rel).read_text(encoding="utf-8")
    for section in pr.target_markdown(MODE)["required_sections"]:
        assert f"## {section}" in md_text, f"missing section {section!r}"
    # decision-options discipline: the recommended-changes section is not a bare boolean
    assert "Option A" in md_text or "Independent reviewer's options" in md_text

    # REPORT stage is deterministic and independent of DESIGN's in-memory state
    report_paths, _report_frag = mod.run_dets(str(run_dir), "REPORT", TS)
    assert len(report_paths) == 1
    note = json.loads((run_dir.parent / report_paths[0]).read_text(encoding="utf-8")) \
        if not str(report_paths[0]).startswith(str(run_dir)) else \
        json.loads(open(report_paths[0], encoding="utf-8").read())
    assert validate_artifact(note) == []
    assert md_rel in note["payload"]["references"]


# --------------------------------------------------------------------------- missing bundle


def test_missing_seat_bundle_blocks(tmp_path):
    run_dir = _mk_run(tmp_path)
    # only write two of the three required seat bundles
    _write_bundle(run_dir, "data-protocol-designer", _data_protocol_bundle())
    _write_bundle(run_dir, "statistics-power-auditor", _power_audit_bundle())

    with pytest.raises(GateBlock) as exc:
        mod.run_dets(str(run_dir), "DESIGN", TS)
    assert "DESIGN.methodology-reviewer.bundle.json" in str(exc.value)


# --------------------------------------------------------------------------- this mode's own hard gates


def test_single_scenario_point_estimate_blocks(tmp_path):
    run_dir = _mk_run(tmp_path)
    one_scenario = [_scenario("point-estimate", 0.05, 0.08, 8)]
    _write_all_bundles(run_dir, pa=_power_audit_bundle(scenarios=one_scenario))

    with pytest.raises(GateBlock) as exc:
        mod.run_dets(str(run_dir), "DESIGN", TS)
    assert "floor" in str(exc.value)


def test_scenario_missing_explicit_assumption_blocks(tmp_path):
    run_dir = _mk_run(tmp_path)
    scenarios = _default_scenarios()
    del scenarios[0]["sd_diff"]
    _write_all_bundles(run_dir, pa=_power_audit_bundle(scenarios=scenarios))

    with pytest.raises(GateBlock) as exc:
        mod.run_dets(str(run_dir), "DESIGN", TS)
    assert "sd_diff" in str(exc.value)


def test_power_recompute_mismatch_blocks(tmp_path):
    run_dir = _mk_run(tmp_path)
    scenarios = _default_scenarios()
    scenarios[0]["reported_power"] = 0.999  # fabricated, far from the recomputed value
    _write_all_bundles(run_dir, pa=_power_audit_bundle(scenarios=scenarios))

    with pytest.raises(GateBlock) as exc:
        mod.run_dets(str(run_dir), "DESIGN", TS)
    assert "recomputation" in str(exc.value)


def test_sufficient_mismatch_blocks(tmp_path):
    run_dir = _mk_run(tmp_path)
    # n_seeds_declared (2) < min_seeds_required (5) but sufficient is falsely claimed True
    _write_all_bundles(run_dir, pa=_power_audit_bundle(n_seeds=2, min_seeds=5, sufficient=True))

    with pytest.raises(GateBlock) as exc:
        mod.run_dets(str(run_dir), "DESIGN", TS)
    assert "sufficient" in str(exc.value)


def test_wrong_lens_blocks(tmp_path):
    run_dir = _mk_run(tmp_path)
    _write_all_bundles(run_dir, mr=_panel_review_bundle(lens="domain"))

    with pytest.raises(GateBlock) as exc:
        mod.run_dets(str(run_dir), "DESIGN", TS)
    assert "lens" in str(exc.value)


def test_blank_reviewer_notes_blocks(tmp_path):
    run_dir = _mk_run(tmp_path)
    _write_all_bundles(run_dir, mr=_panel_review_bundle(reviewer_notes=""))

    with pytest.raises(GateBlock) as exc:
        mod.run_dets(str(run_dir), "DESIGN", TS)
    assert "reviewer_notes" in str(exc.value)


# --------------------------------------------------------------------------- stage contract


def test_unknown_stage_raises_value_error(tmp_path):
    run_dir = _mk_run(tmp_path)
    with pytest.raises(ValueError):
        mod.run_dets(str(run_dir), "NOPE", TS)
