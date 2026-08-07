"""Operate recipe tests for the `design_experiment` mode (DESIGN -> REPORT).

The mode's whole reason to exist is that ten separately schema-valid design slices can still describe
ten different experiments, so most of what is asserted here is `cross_artifact_violations`: the
happy path proves a coherent design passes every gate and renders every registry-declared section,
and the blocked-gate cases each break exactly one cross-artifact invariant and assert the BLOCK names
it. Two structural properties get their own tests because they are what make the audits meaningful:
all three auditors must depend on the SAME frozen six-bundle design set, and no artifact may claim a
measurement in a run that executed nothing.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from research_agent_teams.operate.artifacts import GateBlock
from research_agent_teams.operate.modes import _panel_recipe, _shared, design_experiment as dx
from research_agent_teams.tools.validate_artifact import validate_artifact

TS = "2026-08-04T12:00:00Z"
NORTH_STAR = {"statement": "residual correction for petct lesion segmentation",
              "in_scope": ["residual correction", "petct segmentation"],
              "out_of_scope": ["topology continuity"]}


def _mk_run(tmp_path, budget=None):
    run_dir = tmp_path / "run-1"
    (run_dir / "inbox").mkdir(parents=True)
    tf = {"payload": {"task_id": "run-1", "mode": "design_experiment",
                      "request_text": "design the residual-correction experiment",
                      "north_star": NORTH_STAR,
                      "budget": budget or {"max_agent_hops": 11, "max_debug_retries_per_run": 3}}}
    (run_dir / "task_frame.artifact.json").write_text(json.dumps(tf), encoding="utf-8")
    return run_dir


# --------------------------------------------------------------------------- coherent design fixture

def _bundles() -> dict:
    """One internally consistent experiment design, split across the eleven seat bundles."""
    rq = "does residual correction improve petct lesion segmentation over the supervised baseline"
    return {
        "rq-architect": {"rq_hypothesis_chain": {
            "research_question": rq,
            "hypotheses": [
                {"hypothesis_id": "H1",
                 "statement": "residual correction raises overlap on failure regions",
                 "falsifiable_prediction": "conf2 beats conf1 on the primary metric; if it does not, "
                                          "residual correction adds nothing",
                 "evidence_needed": ["paired comparison on the frozen test split"],
                 "depends_on": [], "notes": None},
                {"hypothesis_id": "H2",
                 "statement": "the gain survives a stronger decoder in the baseline",
                 "falsifiable_prediction": "conf3 keeps the conf2 margin; a vanishing margin "
                                           "falsifies it",
                 "evidence_needed": ["ablation over the decoder factor"],
                 "depends_on": ["H1"], "notes": None}],
            "rq_notes": "petct segmentation only; topology work is out of scope"}},
        "decision-surfacer": {"design_decisions": {
            "open_decisions": [
                {"question": "should the correction module be trained jointly or post-hoc?",
                 "options": ["joint training", "post-hoc refinement"],
                 "evidence": ["joint training couples the losses; post-hoc keeps the baseline frozen"],
                 "locks": [dx.MATRIX_REF]},
                {"question": "which stratification key governs the split?",
                 "options": ["lesion volume", "scanner vendor"],
                 "evidence": ["vendor imbalance is documented in the cohort notes"],
                 "locks": [dx.SPLIT_REF]}],
            "acceptance_criteria": {
                "primary_metric": "dice", "secondary_metrics": ["hd95"], "n_seeds_planned": 3,
                "stopping_rule": "three seeds per condition, then stop",
                "analysis_plan": "paired permutation test versus conf1 on dice, alpha=0.05"}}},
        "experiment-planner": {"experiment_design": {
            "research_question": rq,
            "variables": {"studied": ["correction"], "controlled": ["decoder"],
                          "frozen": ["seed_policy"]},
            "conditions": [
                {"id": "conf1", "factors": {"correction": "none", "decoder": "unet"},
                 "baseline": True},
                {"id": "conf2", "factors": {"correction": "residual", "decoder": "unet"}},
                {"id": "conf3", "factors": {"correction": "residual", "decoder": "unet"}}],
            "ranked_batch": [
                {"rank": 1, "condition_id": "conf2", "hypothesis": "residual correction beats none",
                 "cost_gpu_hours": None, "expected_signal": "dice gain on failure regions"},
                {"rank": 2, "condition_id": "conf3", "hypothesis": "the gain survives the ablation",
                 "cost_gpu_hours": None, "expected_signal": "margin retained"}],
            "leakage_declaration": "patient ids are disjoint across splits; correction inputs never "
                                   "touch test labels",
            "hypothesis_coverage": {"H1": ["conf2"], "H2": ["conf3"]}}},
        "dataset-split-planner": {"split_manifest": {
            "split_unit": "patient",
            "splits": [{"name": "train", "fraction": 0.7, "n_units": None,
                        "stratification_keys": ["vendor"], "frozen": False},
                       {"name": "test", "fraction": 0.3, "n_units": None,
                        "stratification_keys": ["vendor"], "frozen": True}],
            "leakage_declaration": "patient_id_disjoint, checked before training",
            "from_domain_profile": None, "notes": None}},
        "data-protocol-designer": {"data_protocol": {
            "from_split_manifest_ref": dx.SPLIT_REF,
            "steps": [
                {"step_id": "S1", "kind": "resampling", "description": "resample to 2mm isotropic",
                 "train_only": False, "params": {}, "applies_to_splits": ["train", "test"]},
                {"step_id": "S2", "kind": "normalization", "description": "suv normalization",
                 "train_only": False, "params": {}, "applies_to_splits": ["train", "test"]},
                {"step_id": "S3", "kind": "augmentation", "description": "random flips",
                 "train_only": True, "params": {}, "applies_to_splits": ["train"]}],
            "notes": None}},
        "config-unifier": {"unified_config": {
            "from_protocol_ref": dx.PROTOCOL_REF,
            "shared_config": {"optimizer": "adamw", "lr": 0.0003, "epochs": 200},
            "conditions": [
                {"condition_id": "conf1", "divergences": []},
                {"condition_id": "conf2", "divergences": [
                    {"key": "correction", "value": "residual",
                     "justification": "correction is the studied variable"}]},
                {"condition_id": "conf3", "divergences": [
                    {"key": "correction", "value": "residual",
                     "justification": "correction is the studied variable"}]}],
            "notes": None}},
        "method-integration-planner": {"integration_plan": {
            "research_question": rq, "from_matrix_ref": dx.MATRIX_REF,
            "conditions": [
                {"condition_id": "conf1", "module": None, "entry_point": "scripts/train_baseline.py",
                 "patch_description": None, "dependencies": [], "notes": None},
                {"condition_id": "conf2", "module": "petct.correction.residual",
                 "entry_point": "scripts/train_correction.py",
                 "patch_description": "add the residual head to the decoder output",
                 "dependencies": ["monai"], "notes": None},
                {"condition_id": "conf3", "module": "petct.correction.residual",
                 "entry_point": "scripts/train_correction.py",
                 "patch_description": "same head, ablation entry point",
                 "dependencies": ["monai"], "notes": None}],
            "shared_infra_notes": "one data loader and one metric module across all conditions"}},
        "baseline-fairness-planner": {"baseline_fairness_plan": {
            "baseline_ref": "conf1", "treatment_refs": ["conf2", "conf3"],
            "fairness_checks": [
                {"check_name": "data_hash", "baseline_value": None,
                 "treatment_values": {"conf2": None, "conf3": None}, "mismatch_detected": False},
                {"check_name": "compute_budget", "baseline_value": "200 epochs",
                 "treatment_values": {"conf2": "200 epochs", "conf3": "200 epochs"},
                 "mismatch_detected": False},
                {"check_name": "metric_set", "baseline_value": "dice+hd95",
                 "treatment_values": {"conf2": "dice+hd95", "conf3": "dice+hd95"},
                 "mismatch_detected": False}],
            "fairness_violations": [], "override_justification": None, "notes": None}},
        "variable-control-auditor": {"variable_control_facts": {
            "audited_matrix_ref": dx.MATRIX_REF, "independent_of_planner": True,
            "conditions_reviewed": [{"condition_id": "conf2", "changed_vs_baseline": ["correction"]},
                                    {"condition_id": "conf3", "changed_vs_baseline": ["correction"]}],
            "leakage_flagged": False,
            "leakage_note": "correction inputs were traced; none derives from test labels"}},
        "train-test-alignment-auditor": {"alignment_facts": {
            "independent_of_designers": True, "train_split": "train", "test_split": "test",
            "train": {"preprocessing": ["S1", "S2"], "precision": "amp",
                      "label_space": ["background", "lesion"], "pretrained": "none",
                      "augmentation": {"enabled": True}},
            "test": {"preprocessing": ["S1", "S2"], "precision": "amp",
                     "label_space": ["background", "lesion"], "augmentation": {"enabled": False},
                     "inference": {"sliding_window": "96x96x96", "threshold": 0.5}}}},
        "metric-implementation-auditor": {"metric_impl_facts": {
            "independent_of_planner": True, "evaluated_splits": ["test"],
            "conditions": [
                {"condition_id": cid, "metric_impls": {
                    "dice": {"impl_ref": "monai.metrics.DiceMetric", "spacing": "2mm",
                             "postprocess": "argmax"},
                    "hd95": {"impl_ref": "monai.metrics.HausdorffDistanceMetric", "spacing": "2mm",
                             "postprocess": "argmax"}}}
                for cid in ("conf1", "conf2", "conf3")]}},
    }


def _write(run_dir, bundles, skip=()):
    for label, payload in bundles.items():
        if label in skip:
            continue
        (Path(run_dir) / "inbox" / f"DESIGN.{label}.bundle.json").write_text(
            json.dumps(payload, ensure_ascii=False), encoding="utf-8")


@pytest.fixture(autouse=True)
def _offline_vault(monkeypatch):
    """Keep the referential-integrity gate hermetic: no real vault, no network."""
    monkeypatch.setattr(_shared, "VAULT_ROOT_OVERRIDE", False)
    monkeypatch.setattr(_shared, "EXISTENCE_TRANSPORT", None)


def _run_all(run_dir):
    reports = {}
    for stage in dx.STAGES:
        paths, report = dx.run_dets(run_dir, stage, TS)
        for path in paths:
            errors = validate_artifact(json.loads(Path(path).read_text(encoding="utf-8")))
            assert not errors, f"{stage} produced an invalid artifact at {path}: {errors}"
        reports[stage] = report
    return reports


# --------------------------------------------------------------------------- 1. happy path

def test_happy_path_passes_every_gate_and_renders_every_required_section(tmp_path):
    run_dir = _mk_run(tmp_path)
    _write(run_dir, _bundles())
    reports = _run_all(run_dir)
    design = reports["DESIGN"]

    assert design["consistency_gate"] == "PASS"
    assert design["variable_control_gate"] == "PASS"
    assert design["alignment_gate"] == "PASS"
    assert design["metric_impl_gate"] == "PASS"
    assert design["drift_gate"] == "PASS"
    assert design["referential_integrity"] == "PASS"
    # No bibliography in a design panel: the citation gates say so instead of pretending to have run.
    assert design["existence_gate"] == "NOT_APPLICABLE"
    assert design["n_conditions"] == 3
    assert design["n_hypotheses"] == 2
    assert design["n_open_director_decisions"] == 2
    assert design["prereg_frozen"] is True

    spec = _panel_recipe.target_markdown("design_experiment")
    md_path = Path(run_dir) / design["director_markdown"]
    assert design["director_markdown"] == spec["path"]
    text = md_path.read_text(encoding="utf-8")
    for section in spec["required_sections"]:
        assert f"## {section}" in text, f"required section missing from the brief: {section}"
        body = text.split(f"## {section}", 1)[1].split("\n## ", 1)[0].strip()
        assert body, f"required section rendered empty: {section}"

    # Every design artifact really landed, including the mode's own consistency verdict.
    written = {p.name for p in (Path(run_dir) / "evidence" / "DESIGN").glob("*.artifact.json")}
    assert {"rq-hypothesis-chain.artifact.json", "experiment-matrix.artifact.json",
            "split-manifest.artifact.json", "data-protocol.artifact.json",
            "unified-config.artifact.json", "integration-plan.artifact.json",
            "baseline-fairness-plan.artifact.json", "design-consistency-verdict.artifact.json",
            "variable-control-report.artifact.json", "alignment-report.artifact.json",
            "metric-impl-report.artifact.json", "preregistration.artifact.json",
            "adr-adr-0001.artifact.json", "adr-adr-0002.artifact.json"} <= written


def test_report_stage_references_the_director_brief(tmp_path):
    run_dir = _mk_run(tmp_path)
    _write(run_dir, _bundles())
    _run_all(run_dir)
    note = json.loads((Path(run_dir) / "evidence" / "REPORT" / "report-note.artifact.json")
                      .read_text(encoding="utf-8"))["payload"]
    assert _panel_recipe.target_markdown("design_experiment")["path"] in note["references"]
    assert "PLANNED" in note["summary"] or "no experiment was executed" in note["summary"]


# --------------------------------------------------------------------------- 2. missing seat bundle

@pytest.mark.parametrize("missing", ["rq-architect", "config-unifier",
                                     "metric-implementation-auditor"])
def test_missing_seat_bundle_blocks_and_names_the_file(tmp_path, missing):
    run_dir = _mk_run(tmp_path)
    _write(run_dir, _bundles(), skip=(missing,))
    with pytest.raises(GateBlock) as exc:
        dx.run_dets(run_dir, "DESIGN", TS)
    assert f"DESIGN.{missing}.bundle.json" in str(exc.value)


# --------------------------------------------------------------------------- 3. the mode's own gates

def _blocks(run_dir, bundles) -> str:
    _write(run_dir, bundles)
    with pytest.raises(GateBlock) as exc:
        dx.run_dets(run_dir, "DESIGN", TS)
    return str(exc.value)


def test_untested_hypothesis_blocks(tmp_path):
    """A hypothesis no condition tests is the design failing to answer its own question."""
    b = _bundles()
    del b["experiment-planner"]["experiment_design"]["hypothesis_coverage"]["H2"]
    message = _blocks(_mk_run(tmp_path), b)
    assert "cross-artifact consistency BLOCK" in message
    assert "H2" in message and "hypothesis_coverage" in message


def test_condition_set_disagreement_blocks(tmp_path):
    """A config that covers a condition the grid never declared is not the same experiment."""
    b = _bundles()
    b["config-unifier"]["unified_config"]["conditions"][2]["condition_id"] = "conf9"
    message = _blocks(_mk_run(tmp_path), b)
    assert "unified_config covers conditions" in message
    assert "conf9" in message


def test_divergence_on_an_undeclared_variable_blocks(tmp_path):
    """A config key nobody declared as a variable is invisible to the variable-control audit."""
    b = _bundles()
    b["config-unifier"]["unified_config"]["conditions"][1]["divergences"].append(
        {"key": "loss_weighting", "value": 0.7, "justification": "tuned for the correction head"})
    message = _blocks(_mk_run(tmp_path), b)
    assert "loss_weighting" in message
    assert "neither studied, controlled nor frozen" in message


def test_divergence_on_a_frozen_variable_blocks(tmp_path):
    b = _bundles()
    b["config-unifier"]["unified_config"]["conditions"][1]["divergences"].append(
        {"key": "seed_policy", "value": "per-condition", "justification": "convenience"})
    message = _blocks(_mk_run(tmp_path), b)
    assert "frozen variable 'seed_policy'" in message


def test_phantom_split_name_blocks(tmp_path):
    """A protocol step that processes a split the manifest never declared."""
    b = _bundles()
    b["data-protocol-designer"]["data_protocol"]["steps"][0]["applies_to_splits"] = ["train", "val"]
    message = _blocks(_mk_run(tmp_path), b)
    assert "applies_to_splits" in message and "'val'" in message


def test_orphan_split_blocks(tmp_path):
    """A declared split that no step processes, no metric measures and no pipeline uses."""
    b = _bundles()
    b["dataset-split-planner"]["split_manifest"]["splits"].append(
        {"name": "holdout", "fraction": 0.0001, "n_units": None, "stratification_keys": [],
         "frozen": True})
    message = _blocks(_mk_run(tmp_path), b)
    assert "holdout" in message
    assert "no protocol step processes" in message


def test_unfrozen_evaluation_split_blocks(tmp_path):
    b = _bundles()
    b["dataset-split-planner"]["split_manifest"]["splits"][1]["frozen"] = False
    message = _blocks(_mk_run(tmp_path), b)
    assert "is not frozen in the split manifest" in message


def test_training_and_evaluating_on_the_same_split_blocks(tmp_path):
    b = _bundles()
    b["train-test-alignment-auditor"]["alignment_facts"]["test_split"] = "train"
    message = _blocks(_mk_run(tmp_path), b)
    assert "trains and evaluates on the same split" in message


def test_baseline_disagreement_between_grid_and_integration_plan_blocks(tmp_path):
    b = _bundles()
    conditions = b["method-integration-planner"]["integration_plan"]["conditions"]
    conditions[0]["module"] = "petct.baseline.explicit"
    conditions[1]["module"] = None
    message = _blocks(_mk_run(tmp_path), b)
    assert "no-new-code baseline" in message


def test_broken_artifact_handoff_blocks(tmp_path):
    """A downstream seat that cannot name the upstream artifact it designed against."""
    b = _bundles()
    b["config-unifier"]["unified_config"]["from_protocol_ref"] = "evidence/DESIGN/whatever.json"
    message = _blocks(_mk_run(tmp_path), b)
    assert "unified_config.from_protocol_ref" in message
    assert dx.PROTOCOL_REF in message


def test_research_question_paraphrase_blocks(tmp_path):
    b = _bundles()
    b["method-integration-planner"]["integration_plan"]["research_question"] = \
        "can we make petct segmentation better somehow"
    message = _blocks(_mk_run(tmp_path), b)
    assert "the research question differs across seats" in message


def test_auditor_reading_a_different_design_blocks(tmp_path):
    """The independence check with teeth: the auditor's own enumeration must match the frozen grid."""
    b = _bundles()
    b["variable-control-auditor"]["variable_control_facts"]["conditions_reviewed"][0][
        "changed_vs_baseline"] = ["correction", "decoder"]
    message = _blocks(_mk_run(tmp_path), b)
    assert "graded a different experiment" in message
    assert "conf2" in message


def test_auditor_that_does_not_attest_independence_blocks(tmp_path):
    b = _bundles()
    b["metric-implementation-auditor"]["metric_impl_facts"]["independent_of_planner"] = False
    message = _blocks(_mk_run(tmp_path), b)
    assert "independent_of_planner=true" in message


def test_unaudited_contrast_blocks(tmp_path):
    b = _bundles()
    b["variable-control-auditor"]["variable_control_facts"]["conditions_reviewed"].pop()
    message = _blocks(_mk_run(tmp_path), b)
    assert "every contrast must be audited" in message


def test_preregistered_metric_no_condition_implements_blocks(tmp_path):
    b = _bundles()
    b["decision-surfacer"]["design_decisions"]["acceptance_criteria"]["primary_metric"] = "nsd"
    message = _blocks(_mk_run(tmp_path), b)
    assert "'nsd'" in message
    assert "not every condition implements" in message


def test_unjustified_fairness_violation_blocks(tmp_path):
    b = _bundles()
    b["baseline-fairness-planner"]["baseline_fairness_plan"]["fairness_violations"] = [
        "conf3 trains for 400 epochs against the baseline's 200"]
    message = _blocks(_mk_run(tmp_path), b)
    assert "override_justification" in message


def test_confounded_condition_blocks_the_variable_control_audit(tmp_path):
    """Past the consistency gate, the deterministic variable-control core still owns its verdict."""
    b = _bundles()
    b["experiment-planner"]["experiment_design"]["conditions"][1]["factors"]["decoder"] = "segresnet"
    b["variable-control-auditor"]["variable_control_facts"]["conditions_reviewed"][0][
        "changed_vs_baseline"] = ["correction", "decoder"]
    message = _blocks(_mk_run(tmp_path), b)
    assert "independent DESIGN audit BLOCK" in message
    assert "confounded" in message


def test_leakage_flag_from_the_auditor_blocks(tmp_path):
    b = _bundles()
    b["variable-control-auditor"]["variable_control_facts"]["leakage_flagged"] = True
    message = _blocks(_mk_run(tmp_path), b)
    assert "leakage flagged" in message


def test_train_eval_preprocessing_mismatch_blocks(tmp_path):
    b = _bundles()
    b["train-test-alignment-auditor"]["alignment_facts"]["test"]["preprocessing"] = ["S1"]
    message = _blocks(_mk_run(tmp_path), b)
    assert "independent DESIGN audit BLOCK" in message
    assert "preprocessing mismatch" in message


def test_inconsistent_metric_implementation_blocks(tmp_path):
    b = _bundles()
    b["metric-implementation-auditor"]["metric_impl_facts"]["conditions"][1]["metric_impls"][
        "dice"]["impl_ref"] = "custom.dice"
    message = _blocks(_mk_run(tmp_path), b)
    assert "independent DESIGN audit BLOCK" in message
    assert "inconsistent" in message


def test_all_three_audit_verdicts_are_persisted_even_when_one_blocks(tmp_path):
    """The director is owed every independent verdict, not just the first failure."""
    run_dir = _mk_run(tmp_path)
    b = _bundles()
    b["train-test-alignment-auditor"]["alignment_facts"]["test"]["precision"] = "fp32"
    _blocks(run_dir, b)
    design_dir = Path(run_dir) / "evidence" / "DESIGN"
    for name in ("variable-control-report", "alignment-report", "metric-impl-report"):
        assert (design_dir / f"{name}.artifact.json").is_file(), f"{name} was not persisted"
    alignment = json.loads((design_dir / "alignment-report.artifact.json")
                           .read_text(encoding="utf-8"))
    assert alignment["status"] == "blocked"
    assert alignment["payload"]["verdict"] == "BLOCK"


def test_a_pre_decided_open_decision_blocks(tmp_path):
    """Only the director chooses; the surfacer may only surface."""
    b = _bundles()
    b["decision-surfacer"]["design_decisions"]["open_decisions"][0]["chosen_option"] = \
        "joint training"
    message = _blocks(_mk_run(tmp_path), b)
    assert "arrived pre-decided" in message


def test_a_result_shaped_key_in_a_design_bundle_blocks(tmp_path):
    """Designing is not running: this mode never carries a measurement."""
    b = _bundles()
    b["experiment-planner"]["experiment_design"]["results"] = [{"condition_id": "conf2",
                                                               "dice": 0.81}]
    message = _blocks(_mk_run(tmp_path), b)
    assert "not-started" in message or "plan" in message
    assert "/experiment_design/results" in message


def test_out_of_scope_topic_blocks_the_shared_drift_gate(tmp_path):
    b = _bundles()
    b["rq-architect"]["rq_hypothesis_chain"]["rq_notes"] = \
        "we also pivot to topology continuity here"
    message = _blocks(_mk_run(tmp_path), b)
    assert "drift gate BLOCK" in message


# --------------------------------------------------------------------------- 4. unknown stage

def test_unknown_stage_raises_value_error(tmp_path):
    run_dir = _mk_run(tmp_path)
    with pytest.raises(ValueError, match="has no stage"):
        dx.run_dets(run_dir, "EXECUTE", TS)


# --------------------------------------------------------------------------- 5. dispatch contract

def test_every_dispatched_label_is_a_declared_seat(tmp_path):
    run_dir = _mk_run(tmp_path)
    panel = dx.llm_step(run_dir, "DESIGN", "design the residual-correction experiment")
    declared = set(_panel_recipe.declared_seats("design_experiment"))
    labels = [worker["label"] for worker in panel["workers"]]
    assert labels, "the DESIGN panel dispatched nobody"
    assert set(labels) <= declared, f"undeclared seat(s): {sorted(set(labels) - declared)}"
    assert len(labels) == len(set(labels)) == 11
    # `synthesis-writer` is in no wave-2 panel: the director Markdown is rendered deterministically.
    assert "synthesis-writer" not in labels
    assert dx.llm_step(run_dir, "REPORT", "x") is None


def test_every_prompt_carries_the_north_star_the_honesty_rules_and_no_upper_bound(tmp_path):
    run_dir = _mk_run(tmp_path)
    panel = dx.llm_step(run_dir, "DESIGN", "design the residual-correction experiment")
    for worker in panel["workers"]:
        prompt, label = worker["prompt"], worker["label"]
        assert "NORTH STAR" in prompt, f"{label} lost its north-star block"
        assert NORTH_STAR["statement"] in prompt, f"{label} lost the run's direction"
        assert "HONESTY (hard)" in prompt, f"{label} lost the honesty requirement"
        assert "REPAIR ATTEMPT" in prompt, f"{label} cannot be repaired by the bounded loop"
        assert "DESIGN, NOT A RUN" in prompt, f"{label} may not know this is a plan"
        assert f"DESIGN.{label}.bundle.json" in prompt, f"{label} was not told where to write"
        # The 2026-08-03 measurement: cap wording throttles output. Floors only.
        for capped in ("at most", "最多", "no more than", "top 3", "top 5"):
            assert capped not in prompt.lower(), f"{label} carries cap wording {capped!r}"
        assert "FLOOR" in prompt, f"{label} states no floor"


def test_the_three_audits_grade_one_frozen_design_and_never_each_other(tmp_path):
    """The property that makes segment 3 an audit rather than a relay."""
    run_dir = _mk_run(tmp_path)
    panel = dx.llm_step(run_dir, "DESIGN", "design the residual-correction experiment")
    workers = {worker["label"]: worker for worker in panel["workers"]}
    protocol = {"experiment-planner", "dataset-split-planner", "data-protocol-designer",
                "config-unifier", "method-integration-planner", "baseline-fairness-planner"}
    auditors = {"variable-control-auditor", "train-test-alignment-auditor",
                "metric-implementation-auditor"}
    for auditor in auditors:
        deps = set(workers[auditor].get("depends_on") or [])
        assert deps == protocol, (
            f"{auditor} depends on {sorted(deps)}; it must grade exactly the frozen six-bundle "
            f"design set {sorted(protocol)}")
        assert not deps & auditors, f"{auditor} depends on a sibling auditor"
    # Identical dependency sets put all three in one wave — the same frozen design, in parallel.
    assert sorted(panel["parallel_groups"][-1]) == sorted(auditors)
    for auditor in auditors:
        for sibling in auditors - {auditor}:
            assert f"DESIGN.{sibling}.bundle.json" not in workers[auditor]["prompt"], (
                f"{auditor} is told to read {sibling}'s bundle — that is not an independent audit")


def test_no_seat_both_produces_and_audits_its_own_artifact(tmp_path):
    run_dir = _mk_run(tmp_path)
    panel = dx.llm_step(run_dir, "DESIGN", "design the residual-correction experiment")
    for worker in panel["workers"]:
        if worker["label"].endswith("-auditor"):
            assert "You produced NO part" in worker["prompt"] \
                or "designed NO pipeline" in worker["prompt"] \
                or "designed\nneither" in worker["prompt"] \
                or "designed \nneither" in worker["prompt"] \
                or "neither the grid nor the configs" in worker["prompt"], \
                f"{worker['label']} does not state that it audits work it did not produce"


def test_model_policy_routes_every_seat_explicitly(tmp_path):
    run_dir = _mk_run(tmp_path)
    max_quality = dx.llm_step(run_dir, "DESIGN", "x", model_policy="max_quality")
    default = dx.llm_step(run_dir, "DESIGN", "x", model_policy="default")
    assert {worker["model"] for worker in max_quality["workers"]} == {"opus"}
    models = {worker["label"]: worker["model"] for worker in default["workers"]}
    assert all(models.values()), "a seat was dispatched without an explicit model"
    assert models["variable-control-auditor"] == "opus", "an audit seat must not drop below opus"
    assert models["config-unifier"] == "sonnet"


# --------------------------------------------------------------------------- pure-function checks

def test_cross_artifact_violations_is_clean_on_the_coherent_fixture():
    b = _bundles()
    design = b["experiment-planner"]["experiment_design"]
    matrix = {k: v for k, v in design.items() if k != "hypothesis_coverage"}
    assert dx.cross_artifact_violations(
        b["rq-architect"]["rq_hypothesis_chain"], matrix, design["hypothesis_coverage"],
        b["dataset-split-planner"]["split_manifest"], b["data-protocol-designer"]["data_protocol"],
        b["config-unifier"]["unified_config"],
        b["method-integration-planner"]["integration_plan"],
        b["baseline-fairness-planner"]["baseline_fairness_plan"],
        b["variable-control-auditor"]["variable_control_facts"],
        b["train-test-alignment-auditor"]["alignment_facts"],
        b["metric-implementation-auditor"]["metric_impl_facts"],
        b["decision-surfacer"]["design_decisions"]["acceptance_criteria"]) == []


def test_split_fractions_over_one_are_caught():
    b = _bundles()
    original = copy.deepcopy(b["dataset-split-planner"]["split_manifest"])
    original["splits"][0]["fraction"] = 0.9
    design = b["experiment-planner"]["experiment_design"]
    matrix = {k: v for k, v in design.items() if k != "hypothesis_coverage"}
    violations = dx.cross_artifact_violations(
        b["rq-architect"]["rq_hypothesis_chain"], matrix, design["hypothesis_coverage"], original,
        b["data-protocol-designer"]["data_protocol"], b["config-unifier"]["unified_config"],
        b["method-integration-planner"]["integration_plan"],
        b["baseline-fairness-planner"]["baseline_fairness_plan"],
        b["variable-control-auditor"]["variable_control_facts"],
        b["train-test-alignment-auditor"]["alignment_facts"],
        b["metric-implementation-auditor"]["metric_impl_facts"],
        b["decision-surfacer"]["design_decisions"]["acceptance_criteria"])
    assert any("more than the whole dataset is allocated" in row for row in violations)
