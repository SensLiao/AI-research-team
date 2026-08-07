"""Operate-recipe tests for `verify_result` — the VERIFY independence panel (wave 2).

The mode's whole value is reviewer SEPARATION, so these tests drive the guarantees directly rather
than only the happy path: a contaminated reviewer, a dropped reviewer BLOCK, a fabricated reference,
a missing "still cannot claim" line, a suppressed disagreement, and an adversarial gate that the
synthesis tries to walk around must each stop the run — while a panel that legitimately BLOCKs the
result must be DELIVERED, not swallowed.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from research_agent_teams.operate.artifacts import GateBlock
from research_agent_teams.operate.modes import _panel_recipe, verify_result as vr
from research_agent_teams.tools.validate_artifact import validate_artifact

TS = "2026-08-04T10:00:00Z"
MD_REL = "director-review/verification/result-verification.md"
CRITIC_FLAG = "the headline delta is reported without the variance that would make it readable"


def _mk_run(tmp_path, budget=None):
    run_dir = tmp_path / "run-1"
    (run_dir / "inbox").mkdir(parents=True)
    tf = {"payload": {"task_id": "run-1", "mode": "verify_result",
                      "request_text": "verify the held-out Dice result before anything leans on it",
                      "north_star": {"statement": "verify the held-out Dice result",
                                     "in_scope": ["held-out Dice", "residual correction"],
                                     "out_of_scope": ["topology continuity"]},
                      "budget": budget or {"max_agent_hops": 8, "max_debug_retries_per_run": 3}}}
    (run_dir / "task_frame.artifact.json").write_text(json.dumps(tf), encoding="utf-8")
    return run_dir


# --------------------------------------------------------------------------- fixtures
def _bundles() -> dict:
    """One coherent eight-seat panel: a rebutted reviewer BLOCK plus a live, unresolved split."""
    return {
        vr.CONFIGURATOR: {"review_scope": {
            "result_under_review": "Dice +2.1 points over the nnU-Net baseline on the held-out "
                                   "split (Table 2 of run r-77)",
            "result_refs": ["evidence/ANALYZE/result-summary.artifact.json"],
            "review_config": {
                "run_ref": "run-1",
                "lenses": [
                    {"lens": "methodology",
                     "anchor": "statistical design, variable control and split integrity",
                     "reviewer_agent": "methodology-reviewer",
                     "notes": "domain invariants are deliberately outside this territory"},
                    {"lens": "domain",
                     "anchor": "domain hard invariants and metric validity on the required frame",
                     "reviewer_agent": "domain-reviewer",
                     "notes": "seed counts are deliberately outside this territory"},
                    {"lens": "adversarial",
                     "anchor": "leakage, baseline fairness, eval frame, provenance and overclaim",
                     "reviewer_agent": "adversarial-reviewer",
                     "notes": "reads the evaluation code itself"},
                ],
                "synthesis_mandate": "Cover every configured lens plus the baseline-completeness "
                                     "and historical seats; report disagreement, never settle it.",
                "inputs_to_review": ["evidence/ANALYZE/result-summary.artifact.json",
                                     "evidence/EXECUTE/run-record.artifact.json",
                                     "evidence/DESIGN/protocol-spec.artifact.json"],
            }}},
        vr.METHODOLOGY: {"methodology_review": {"lens": "methodology", "findings": [
            {"finding_id": "meth-01", "anchor": "Table 2, held-out Dice column",
             "evidence": "the experiment matrix records n_seeds=1 while the wording implies a "
                         "repeated measurement",
             "severity": "BLOCK", "rebuttal_required": True},
            {"finding_id": "meth-02", "anchor": "Section 4.1 ablation budget",
             "evidence": "the residual branch trains 40 epochs longer than the arm it is compared "
                         "against",
             "severity": "WARN"}],
            "reviewer_notes": "the training launcher was not readable, so the epoch asymmetry comes "
                              "from the run record alone"}},
        vr.DOMAIN: {"domain_review": {"lens": "domain", "findings": [
            {"finding_id": "dom-01", "anchor": "metric definition in the protocol spec",
             "evidence": "Dice is computed on resampled 1mm spacing while the profile requires the "
                         "original acquisition spacing",
             "severity": "WARN"}],
            "reviewer_notes": "the active profile covers spacing but is silent on prompt count"}},
        vr.ADVERSARIAL: {"adversarial_checks": {
            "leakage": {"pass": True,
                        "evidence": "re-derived the loader; no held-out id ever enters training"},
            "fairness": {"pass": True,
                         "evidence": "one split file and one metric implementation serve both arms"},
            "eval_frame": {"pass": True,
                           "evidence": "read the eval entrypoint: per-case Dice, then averaged"},
            "provenance": {"pass": True,
                           "evidence": "commit 9f2c1ab and the pinned data hash both resolve"},
            "overclaim": {"pass": True,
                          "evidence": "the abstract wording stays inside the reported delta"}}},
        vr.CRITIC: {"critic_memo": {
            "cross_findings": [
                {"description": "the significance language leans on a repeated measurement while "
                                "the frame the domain requires was never recomputed",
                 "involved_lenses": ["methodology", "domain"],
                 "resolution_path": "recompute on the required frame across three seeds"}],
            "block_flags": [
                {"flag_text": CRITIC_FLAG,
                 "source": "Table 2 read directly; the critic's own assessment",
                 "defensible_path": "report the per-seed spread beside the mean"}],
            "gaps": ["nobody reports how the interactive prompt count was calibrated"],
            "critic_notes": "read Table 2 and the protocol spec; training code was unavailable"}},
        vr.BASELINE: {"baseline_review": {"lens": "baseline-completeness", "findings": [
            {"finding_id": "base-01", "anchor": "the comparison table in Table 2",
             "evidence": "arXiv:2401.01234 reports this task and dataset a year earlier and is "
                         "absent from the table; see also [[nnunet-baseline]]",
             "severity": "WARN"}],
            "reviewer_notes": "14 candidates checked across arXiv and OpenAlex; one survived as a "
                              "real omission"}},
        vr.HISTORIAN: {"historical_review": {"lens": "historical-context", "findings": [
            {"finding_id": "hist-01", "anchor": "the first-to-correct-residuals positioning claim",
             "evidence": "[[residual-refinement-2019]] proposed the same correction stage for "
                         "another modality, so the claim needs its scope stated",
             "severity": "NOTE"}],
            "reviewer_notes": "four hops: cascade refinement, end-to-end models, interactive "
                              "recovery, then this work"}},
        vr.SYNTHESIZER: {"synthesis_draft": {
            "overall_summary": "The panel accepts the direction but not the current wording: the "
                               "seed count and the metric frame both need work first.",
            "addressed_blocks": [
                {"block_source": "meth-01",
                 "rebuttal": "the run record shows three completed seeds; the single-seed figure in "
                             "the matrix is stale and the spread is 0.014 Dice"},
                {"block_source": CRITIC_FLAG,
                 "rebuttal": "the per-seed spread of 0.014 Dice sits in the run journal and is "
                             "carried into the calibrated claim below"}],
            "unaddressed_blocks": [],
            "open_critic_flags": [],
            "disagreements": [
                {"topic": "whether the reported delta may be described as significant",
                 "critic_cross_finding_ref": "cross-1",
                 "positions": [
                     {"lens": "methodology",
                      "position": "the training budget differs by 40 epochs, so significance is "
                                  "confounded",
                      "finding_refs": ["meth-02"]},
                     {"lens": "domain",
                      "position": "the frame mismatch outweighs the budget: the metric is not "
                                  "computed where the domain requires",
                      "finding_refs": ["dom-01"]}],
                 "resolution": "unresolved",
                 "resolution_note": "both readings survive the evidence in front of the panel"}],
            "claims": [
                {"original_claim": "residual correction improves held-out Dice by 2.1 points",
                 "metric": "Dice", "delta": 0.021, "variance": 0.014,
                 "original_strength": "strong",
                 "supported_by": ["meth-01", "eval_frame"], "contradicted_by": ["dom-01"],
                 "cannot_claim": "nothing about the original acquisition spacing, and nothing "
                                 "about cases outside this split's institution"},
                {"original_claim": "the correction also helps the boundary metric",
                 "metric": "HD95", "delta": 0.005, "variance": 0.02,
                 "original_strength": "moderate",
                 "supported_by": ["dom-01"], "contradicted_by": [],
                 "cannot_claim": "no boundary-metric improvement may be claimed at this spread"}],
            "required_next_actions": [
                {"action": "compare against the 2024 method the baseline seat found",
                 "owner_stage": "DESIGN", "finding_refs": ["base-01"]},
                {"action": "recompute Dice on the acquisition spacing the profile requires",
                 "owner_stage": "ANALYZE", "finding_refs": ["dom-01", "hist-01"]}]}},
    }


def _seed(run_dir, bundles: dict) -> None:
    for seat, payload in bundles.items():
        Path(_panel_recipe.bundle_path(str(run_dir), "VERIFY", seat)).write_text(
            json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _run(tmp_path, mutate=None, drop=None):
    run_dir = _mk_run(tmp_path)
    bundles = _bundles()
    if mutate:
        mutate(bundles)
    if drop:
        bundles.pop(drop)
    _seed(run_dir, bundles)
    return run_dir


# --------------------------------------------------------------------------- 1. happy path
def test_full_panel_delivers_a_validated_brief(tmp_path):
    run_dir = _run(tmp_path)

    paths, report = vr.run_dets(str(run_dir), "VERIFY", TS)
    for path in paths:
        artifact = json.loads(Path(path).read_text(encoding="utf-8"))
        assert validate_artifact(artifact) == [], f"{path} failed its contract"

    written = {json.loads(Path(p).read_text(encoding="utf-8"))["artifact_type"] for p in paths}
    assert {"review_config", "panel_review", "review_report", "critic_memo", "panel_synthesis",
            "calibrated_claims"} <= written

    assert report["panel_verdict"] == "APPROVE"          # every BLOCK + flag really was rebutted
    assert report["adversarial_gate"] == "APPROVE-FREEZE"
    assert report["reviewer_independence"] == "PASS"
    assert report["seats_reviewed"] == 6
    assert report["seat_verdicts"]["methodology-reviewer"] == "BLOCK"   # derived, not declared
    assert report["seat_verdicts"]["domain-reviewer"] == "PASS"
    assert report["n_reviewer_blocks"] == 1 and report["n_critic_block_flags"] == 1
    assert report["n_disagreements"] == 1 and report["n_coverage_violations"] == 0
    assert report["n_claims"] == 2 and report["n_claims_downgraded"] == 2   # calibrator overruled
    assert report["scholar_refs_checked"] == 3          # 1 arXiv id + 2 vault slugs, from prose
    assert report["drift_gate"] == "PASS"

    text = (run_dir / MD_REL).read_text(encoding="utf-8")
    for section in _panel_recipe.target_markdown("verify_result")["required_sections"]:
        assert f"## {section}" in text, f"missing director section {section!r}"
    assert "STILL CANNOT CLAIM" in text                 # the calibration column, never dropped
    assert "no winner picked" in text                   # both readings survive to the director
    assert "acquisition spacing" in text
    assert report["director_verification_brief"] == MD_REL

    report_paths, _ = vr.run_dets(str(run_dir), "REPORT", TS)
    note = json.loads(Path(report_paths[0]).read_text(encoding="utf-8"))
    assert validate_artifact(note) == []
    assert note["payload"]["references"] == [MD_REL]
    assert "APPROVE" in note["payload"]["summary"]


def test_panel_that_blocks_the_result_is_delivered_not_swallowed(tmp_path):
    """A reviewer BLOCK left standing is the panel's ANSWER — it must reach the director."""
    def leave_it_standing(bundles):
        draft = bundles[vr.SYNTHESIZER]["synthesis_draft"]
        draft["addressed_blocks"] = [row for row in draft["addressed_blocks"]
                                     if row["block_source"] != "meth-01"]
        draft["unaddressed_blocks"] = ["meth-01"]

    run_dir = _run(tmp_path, mutate=leave_it_standing)
    paths, report = vr.run_dets(str(run_dir), "VERIFY", TS)

    assert report["panel_verdict"] == "BLOCK"
    assert report["n_coverage_violations"] >= 1
    synthesis = next(json.loads(Path(p).read_text(encoding="utf-8")) for p in paths
                     if json.loads(Path(p).read_text(encoding="utf-8"))["artifact_type"]
                     == "panel_synthesis")
    assert synthesis["status"] == "blocked"
    assert synthesis["payload"]["unaddressed_blocks"] == ["meth-01"]
    assert validate_artifact(synthesis) == []
    assert (run_dir / MD_REL).is_file()          # the director still gets the full brief


# --------------------------------------------------------------------------- 2. incomplete panel
@pytest.mark.parametrize("seat", [vr.DOMAIN, vr.ADVERSARIAL, vr.CRITIC, vr.HISTORIAN])
def test_missing_seat_bundle_blocks_and_names_the_file(tmp_path, seat):
    run_dir = _run(tmp_path, drop=seat)
    with pytest.raises(GateBlock) as excinfo:
        vr.run_dets(str(run_dir), "VERIFY", TS)
    assert f"VERIFY.{seat}.bundle.json" in str(excinfo.value)


# --------------------------------------------------------------------------- 3. the mode's own gates
def test_reviewer_citing_a_sibling_bundle_is_terminal(tmp_path):
    """Reading another seat's output file is the contamination signal — and it never retries."""
    def contaminate(bundles):
        bundles[vr.DOMAIN]["domain_review"]["reviewer_notes"] = (
            "cross-checked against inbox/VERIFY.methodology-reviewer.bundle.json before writing")

    run_dir = _run(tmp_path, mutate=contaminate)
    with pytest.raises(GateBlock) as excinfo:
        vr.run_dets(str(run_dir), "VERIFY", TS)
    message = str(excinfo.value)
    assert "reviewer-independence BLOCK" in message
    assert "domain-reviewer" in message and "methodology-reviewer" in message
    # terminal, not a repairable supplement: a contaminated reviewer cannot un-see a verdict
    assert vr.run_dets_with_repair.__doc__
    with pytest.raises(GateBlock):
        vr.run_dets_with_repair(str(run_dir), "VERIFY", TS)


def test_reviewer_citing_a_sibling_finding_id_blocks(tmp_path):
    def contaminate(bundles):
        bundles[vr.BASELINE]["baseline_review"]["findings"][0]["evidence"] += \
            " — this also explains meth-02 above"

    run_dir = _run(tmp_path, mutate=contaminate)
    with pytest.raises(GateBlock, match="reviewer-independence BLOCK"):
        vr.run_dets(str(run_dir), "VERIFY", TS)


def test_two_seats_sharing_verbatim_prose_blocks(tmp_path):
    def copy_paste(bundles):
        stolen = bundles[vr.METHODOLOGY]["methodology_review"]["findings"][1]["evidence"]
        bundles[vr.DOMAIN]["domain_review"]["findings"][0]["evidence"] = stolen

    run_dir = _run(tmp_path, mutate=copy_paste)
    with pytest.raises(GateBlock, match="verbatim"):
        vr.run_dets(str(run_dir), "VERIFY", TS)


def test_dropped_reviewer_block_blocks(tmp_path):
    """Leaving a BLOCK standing is allowed; pretending it was never filed is not."""
    def drop_it(bundles):
        draft = bundles[vr.SYNTHESIZER]["synthesis_draft"]
        draft["addressed_blocks"] = [row for row in draft["addressed_blocks"]
                                     if row["block_source"] != "meth-01"]

    run_dir = _run(tmp_path, mutate=drop_it)
    with pytest.raises(GateBlock) as excinfo:
        vr.run_dets(str(run_dir), "VERIFY", TS)
    assert "appears nowhere in the synthesis" in str(excinfo.value)
    assert "meth-01" in str(excinfo.value)


def test_synthesis_citing_a_finding_nobody_filed_blocks(tmp_path):
    def fabricate(bundles):
        bundles[vr.SYNTHESIZER]["synthesis_draft"]["claims"][0]["supported_by"] = ["meth-99"]

    run_dir = _run(tmp_path, mutate=fabricate)
    with pytest.raises(GateBlock) as excinfo:
        vr.run_dets(str(run_dir), "VERIFY", TS)
    assert "fabricated reference" in str(excinfo.value) and "meth-99" in str(excinfo.value)


def test_claim_without_its_limit_blocks(tmp_path):
    """`cannot_claim` is the field that stops a verified result from quietly growing."""
    def strip_limit(bundles):
        bundles[vr.SYNTHESIZER]["synthesis_draft"]["claims"][1]["cannot_claim"] = "   "

    run_dir = _run(tmp_path, mutate=strip_limit)
    with pytest.raises(GateBlock) as excinfo:
        vr.run_dets(str(run_dir), "VERIFY", TS)
    assert "cannot_claim" in str(excinfo.value)


def test_suppressed_disagreement_blocks(tmp_path):
    def hide_the_split(bundles):
        bundles[vr.SYNTHESIZER]["synthesis_draft"]["disagreements"] = []

    run_dir = _run(tmp_path, mutate=hide_the_split)
    with pytest.raises(GateBlock) as excinfo:
        vr.run_dets(str(run_dir), "VERIFY", TS)
    assert "cross-1" in str(excinfo.value)


def test_disagreement_with_one_position_is_picking_a_winner(tmp_path):
    def pick_a_winner(bundles):
        row = bundles[vr.SYNTHESIZER]["synthesis_draft"]["disagreements"][0]
        row["positions"] = row["positions"][:1]
        row["resolution"] = "resolved_by_evidence"
        row["resolution_note"] = "ok"

    run_dir = _run(tmp_path, mutate=pick_a_winner)
    with pytest.raises(GateBlock) as excinfo:
        vr.run_dets(str(run_dir), "VERIFY", TS)
    message = str(excinfo.value)
    assert "picking a winner" in message
    assert "an unwritten resolution is a preference" in message


def test_adversarial_block_cannot_be_walked_around(tmp_path):
    """An unrebutted refutation-gate failure forces BLOCK even with every reviewer happy."""
    def break_the_eval(bundles):
        bundles[vr.ADVERSARIAL]["adversarial_checks"]["eval_frame"] = {
            "pass": False, "evidence": "the metric is averaged over slices, not cases"}

    run_dir = _run(tmp_path, mutate=break_the_eval)
    paths, report = vr.run_dets(str(run_dir), "VERIFY", TS)
    assert report["adversarial_gate"] == "BLOCK"
    assert report["panel_verdict"] == "BLOCK"
    assert any("adversarial refutation gate BLOCK" in violation
               for violation in json.loads(
                   next(Path(p).read_text(encoding="utf-8") for p in paths
                        if p.endswith("panel-synthesis.artifact.json")))["payload"]["violations"])


def test_claimed_pass_without_evidence_defaults_to_block(tmp_path):
    def strip_evidence(bundles):
        bundles[vr.ADVERSARIAL]["adversarial_checks"]["leakage"] = {"pass": True, "evidence": ""}

    run_dir = _run(tmp_path, mutate=strip_evidence)
    _paths, report = vr.run_dets(str(run_dir), "VERIFY", TS)
    assert report["adversarial_gate"] == "BLOCK"        # default-to-BLOCK under uncertainty
    assert report["panel_verdict"] == "BLOCK"


def test_unanchored_seat_blocks_the_scope(tmp_path):
    def forget_a_lens(bundles):
        config = bundles[vr.CONFIGURATOR]["review_scope"]["review_config"]
        config["lenses"] = [row for row in config["lenses"] if row["lens"] != "adversarial"]

    run_dir = _run(tmp_path, mutate=forget_a_lens)
    with pytest.raises(GateBlock) as excinfo:
        vr.run_dets(str(run_dir), "VERIFY", TS)
    assert "review-scope BLOCK" in str(excinfo.value)
    assert "adversarial-reviewer" in str(excinfo.value)


def test_config_handing_the_panel_a_reviewer_output_blocks(tmp_path):
    def leak_it(bundles):
        bundles[vr.CONFIGURATOR]["review_scope"]["review_config"]["inputs_to_review"].append(
            "evidence/VERIFY/review-report.artifact.json")

    run_dir = _run(tmp_path, mutate=leak_it)
    with pytest.raises(GateBlock, match="destroys the independence"):
        vr.run_dets(str(run_dir), "VERIFY", TS)


def test_seat_answering_the_wrong_lens_blocks(tmp_path):
    def swap_lens(bundles):
        bundles[vr.BASELINE]["baseline_review"]["lens"] = "domain"

    run_dir = _run(tmp_path, mutate=swap_lens)
    with pytest.raises(GateBlock, match="lens-coverage BLOCK"):
        vr.run_dets(str(run_dir), "VERIFY", TS)


def test_declared_overall_verdict_is_refused(tmp_path):
    def self_declare(bundles):
        bundles[vr.METHODOLOGY]["methodology_review"]["overall_verdict"] = "PASS"

    run_dir = _run(tmp_path, mutate=self_declare)
    with pytest.raises(GateBlock, match="computed, never asserted"):
        vr.run_dets(str(run_dir), "VERIFY", TS)


def test_weak_scope_blocks_the_reviewer_wave_before_it_costs_a_hop(tmp_path):
    """llm_step refuses to open the reviewer wave on a scope that cannot support independence."""
    run_dir = _mk_run(tmp_path)
    bundles = _bundles()
    bundles[vr.CONFIGURATOR]["review_scope"]["result_under_review"] = ""
    _seed(run_dir, {vr.CONFIGURATOR: bundles[vr.CONFIGURATOR]})
    with pytest.raises(ValueError, match="result_under_review is empty"):
        vr.llm_step(str(run_dir), "VERIFY", "verify the held-out Dice result")


# --------------------------------------------------------------------------- 4. unknown stage
def test_unknown_stage_raises_value_error(tmp_path):
    run_dir = _mk_run(tmp_path)
    with pytest.raises(ValueError, match="has no stage"):
        vr.run_dets(str(run_dir), "IDEATE", TS)
    assert vr.STAGES == ["VERIFY", "REPORT"]


# --------------------------------------------------------------------------- 5. dispatch contract
def test_every_dispatched_label_is_a_declared_seat(tmp_path):
    run_dir = _mk_run(tmp_path)
    panel = vr.llm_step(str(run_dir), "VERIFY", "verify the held-out Dice result")
    declared = set(_panel_recipe.declared_seats("verify_result"))
    labels = [worker["label"] for worker in panel["workers"]]

    assert labels and set(labels) <= declared
    assert len(labels) == len(set(labels))              # one accountable writer per bundle
    assert len(labels) == 8                             # the registry's minimum_distinct_workers
    assert panel["parallel_groups"] == [
        [vr.CONFIGURATOR],
        [vr.METHODOLOGY, vr.DOMAIN, vr.ADVERSARIAL, vr.CRITIC, vr.BASELINE, vr.HISTORIAN],
        [vr.SYNTHESIZER]]
    assert vr.llm_step(str(run_dir), "REPORT", "x") is None

    for worker in panel["workers"]:
        assert worker["model"] == "opus"                # max_quality default
        assert "NORTH STAR" in worker["prompt"]
        assert worker["output"].endswith(f"VERIFY.{worker['label']}.bundle.json")
        for banned in ("at most", "no more than", "top 3", "top 5"):
            assert banned not in worker["prompt"].lower(), f"{worker['label']} carries a ceiling"

    reviewers = {w["label"]: w["prompt"] for w in panel["workers"]
                 if w["label"] in vr._REVIEWING_SEATS}
    assert len(reviewers) == 6
    for label, prompt in reviewers.items():
        assert "You may NOT open, quote, or reason about any" in prompt
        for other in vr._REVIEWING_SEATS:
            if other != label:
                assert f"VERIFY.{other}.bundle.json" not in prompt, \
                    f"{label} is handed {other}'s bundle path"
