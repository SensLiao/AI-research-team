"""Tests for the `aers_enhanced_research_pack` operate recipe (wave-2 backlog, wired 2026-08-07).

Six-stage recipe (DISCOVER -> DESIGN -> EXECUTE -> ANALYZE -> VERIFY -> REPORT) built on
`_panel_recipe`. Each non-VERIFY stage is exercised independently (none of DISCOVER/DESIGN/
EXECUTE/ANALYZE reads another stage's artifacts, only its own bundles); VERIFY is exercised via
a full sequential walkthrough because it renders the director Markdown from every prior stage's
already-committed `evidence/<STAGE>/*.artifact.json` files (`_read_stage_payloads`), never from
worker prose a later stage cannot see.

Hash/receipt self-check (director's 2026-08-07 teardown pass): this module was grepped for
in-file hash/receipt integrity gates. None exist — `refuse_metrics_without_receipt` and
`numeric_benchmark_adapter.build_report(...)` are execution-truth / recompute-from-empty-input
honesty checks (planned-vs-ran), not cryptographic tamper detection, and both live in shared
modules this recipe only calls. `numeric_benchmark_report["verdict"]` is queried from the live
function below rather than hardcoded, since that module's own BLOCK/PASS vocabulary is being
worked on separately in this wave.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from research_agent_teams.operate.artifacts import GateBlock
from research_agent_teams.operate.modes import _panel_recipe, aers_enhanced_research_pack as aers
from research_agent_teams.tools import numeric_benchmark_adapter
from research_agent_teams.tools.validate_artifact import validate_artifact

TS = "2026-08-07T00:00:00Z"


def _mk_run(tmp_path, request_text=None, budget=None):
    run_dir = tmp_path / "run-1"
    (run_dir / "inbox").mkdir(parents=True)
    tf = {"payload": {
        "task_id": "run-1", "mode": "aers_enhanced_research_pack",
        "request_text": request_text or "assemble a reference pack for the residual-correction line",
        "north_star": {"statement": "a reference-only AERS-enhanced research pack",
                       "in_scope": ["residual correction"], "out_of_scope": []},
        "budget": budget or {"max_agent_hops": 12, "max_debug_retries_per_run": 3}}}
    (run_dir / "task_frame.artifact.json").write_text(json.dumps(tf), encoding="utf-8")
    return run_dir


def _write_bundle(run_dir, stage: str, agent: str, payload: dict) -> None:
    (run_dir / "inbox" / f"{stage}.{agent}.bundle.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8")


# ------------------------------------------------------------------------------- good bundles

def _good_applicability_note() -> dict:
    return {"aers_applicability_note": {
        "title": "AERS reference applicability for the residual-correction line",
        "body": "sop_pack 'reproducibility-audit' is relevant: this line needs a documented "
                "reproduction path before submission. No other cataloged pack applies.",
        "refs": [],
    }}


def _good_search_trace() -> dict:
    return {"evidence_search_trace": {
        "search_contract_version": "evidence-search-trace/v1",
        "research_question": "What data-wrangling and reproducibility practice does the "
                             "literature already establish for this line?",
        "critical_claims": [
            {"claim_id": "C1", "question": "Is an equal-budget baseline reported?",
             "importance": "critical"},
        ],
        "representativeness_dimensions": ["method"],
        "rounds": [
            {"round_index": 0, "questions": ["equal-budget baseline promptable segmentation"],
             "source_hits": [{"source_ref": "[[hu-2021-lora]]"}],
             "claim_ids_addressed": ["C1"], "contradiction_claim_ids_queried": [],
             "representativeness_dimensions_queried": [],
             "findings": [{"finding_id": "F1", "source_refs": ["[[hu-2021-lora]]"],
                          "claim_ids": ["C1"], "finding_kind": "supportive"}]},
        ],
        "stop_reason": "semantic_complete",
        "budget_exhausted": False,
    }}


def _good_data_protocol() -> dict:
    return {"data_protocol": {
        "from_split_manifest_ref": None,
        "steps": [
            {"step_id": "s1", "kind": "preprocessing", "description": "resample to 1mm isotropic",
             "train_only": False, "params": {}, "applies_to_splits": ["train", "val", "test"]},
            {"step_id": "s2", "kind": "augmentation", "description": "random flip + intensity jitter",
             "train_only": True, "params": {}, "applies_to_splits": ["train"]},
        ],
        "notes": "reconstructed for the residual-correction reference pack from the project's "
                "existing split-manifest notes",
    }}


def _good_repro_audit() -> dict:
    return {"reproducibility_materials_audit": {
        "source_ref": "[[hu-2021-lora]]",
        "code_availability": "official repo linked in the paper",
        "data_availability": "public benchmark, no access restriction",
        "config_availability": "hyperparameters documented in the appendix",
        "environment": "PyTorch 2.x, documented conda env",
        "license_or_access_constraints": [],
        "reproduction_steps": ["clone repo", "download benchmark", "run train.py with the "
                               "documented config"],
        "missing_materials": [],
        "reproducibility_risk": "low",
    }}


def _good_benchmark_note(own_measured_metrics=None) -> dict:
    return {"benchmark_evidence_note": {
        "title": "Benchmark evidence landscape for the residual-correction line",
        "body": "The literature reports Dice/HD95 on [[hu-2021-lora]]'s benchmark; no "
                "equal-budget baseline has been published.",
        "refs": ["[[hu-2021-lora]]"],
        "own_measured_metrics": own_measured_metrics if own_measured_metrics is not None else [],
    }}


def _good_submission_checklist() -> dict:
    return {"submission_checklist_note": {
        "title": "Submission checklist (reference only)",
        "body": "Page limit: unconfirmed. Anonymization: unconfirmed. Required sections: "
                "unconfirmed — no venue-specific SOP note found in the vault.",
        "refs": [],
    }}


def _good_bibliography_note() -> dict:
    return {"bibliography_verification_note": {
        "title": "Independent bibliography verification",
        "body": "1 ref re-checked, 1 confirmed, 0 flagged.",
        "refs": ["[[hu-2021-lora]]"],
    }}


def _good_manuscript_polish() -> dict:
    return {"manuscript_polish_note": {
        "title": "Manuscript polish recommendations for the residual-correction reference pack",
        "body": "1. Tighten the abstract's claim to match the reported Dice delta (routine).",
        "refs": [],
    }}


def _write_discover(run_dir) -> None:
    _write_bundle(run_dir, "DISCOVER", "aers-sop-curator", _good_applicability_note())
    _write_bundle(run_dir, "DISCOVER", "literature-search-strategist", _good_search_trace())


def _write_design(run_dir, protocol=None) -> None:
    _write_bundle(run_dir, "DESIGN", "data-wrangling-auditor", protocol or _good_data_protocol())


def _write_execute(run_dir, own_measured_metrics=None) -> None:
    _write_bundle(run_dir, "EXECUTE", "reproducibility-packager", _good_repro_audit())
    _write_bundle(run_dir, "EXECUTE", "benchmark-evidence-auditor",
                 _good_benchmark_note(own_measured_metrics))


def _write_analyze(run_dir) -> None:
    _write_bundle(run_dir, "ANALYZE", "submission-guideline-scout", _good_submission_checklist())
    _write_bundle(run_dir, "ANALYZE", "bibliography-validator", _good_bibliography_note())


def _write_verify(run_dir) -> None:
    _write_bundle(run_dir, "VERIFY", "manuscript-polish-editor", _good_manuscript_polish())


def _expected_bench_verdict() -> str:
    """Query the live adapter rather than hardcode 'BLOCK' — its own BLOCK/PASS vocabulary is
    being reworked elsewhere in this wave (informational-vs-gate), and this decouples the two."""
    report = numeric_benchmark_adapter.build_report(
        run_records=[], result_rows=[], hash_manifest={}, journal={}, required_paths=[])
    return report["verdict"]


# =========================================================================== module contract

def test_stages_and_vault_match_the_registry_and_shared_default():
    assert aers.STAGES == ["DISCOVER", "DESIGN", "EXECUTE", "ANALYZE", "VERIFY", "REPORT"]
    assert aers.DEFAULT_VAULT == _panel_recipe.DEFAULT_VAULT


def test_unknown_stage_raises_value_error(tmp_path):
    run_dir = _mk_run(tmp_path)
    with pytest.raises(ValueError, match="aers_enhanced_research_pack"):
        aers.run_dets(run_dir, "IDEATE", TS)


def test_module_has_no_in_file_hash_or_receipt_integrity_gate():
    """Self-check per the director's 2026-08-07 teardown pass: nothing to strip here — the
    module imports no hashlib and defines no fingerprint/tamper helper of its own."""
    assert not hasattr(aers, "hashlib")
    source = Path(aers.__file__).read_text(encoding="utf-8")
    assert "hashlib" not in source
    assert "sha256" not in source


# =========================================================================== llm_step / dispatch

@pytest.mark.parametrize("stage,expected_labels", [
    ("DISCOVER", {"aers-sop-curator", "literature-search-strategist"}),
    ("DESIGN", {"data-wrangling-auditor"}),
    ("EXECUTE", {"reproducibility-packager", "benchmark-evidence-auditor"}),
    ("ANALYZE", {"submission-guideline-scout", "bibliography-validator"}),
    ("VERIFY", {"manuscript-polish-editor"}),
])
def test_llm_step_dispatches_only_the_declared_seats_for_each_stage(tmp_path, stage, expected_labels):
    run_dir = _mk_run(tmp_path)
    panel = aers.llm_step(run_dir, stage, "assemble the pack", aers.DEFAULT_VAULT, "max_quality")
    labels = {worker["label"] for worker in panel["workers"]}
    assert labels == expected_labels
    assert labels <= set(_panel_recipe.declared_seats("aers_enhanced_research_pack"))


def test_llm_step_report_stage_is_deterministic(tmp_path):
    run_dir = _mk_run(tmp_path)
    assert aers.llm_step(run_dir, "REPORT", "assemble the pack") is None


def test_discover_llm_step_drops_a_deterministic_aers_snapshot_for_the_curator(tmp_path):
    """The curator's judgment must be grounded in the SAME snapshot the deterministic planner
    later recomputes — never re-derived or invented by the worker."""
    run_dir = _mk_run(tmp_path)
    aers.llm_step(run_dir, "DISCOVER", "assemble the pack")
    snapshot = run_dir / "inbox" / "aers-integration-plan-snapshot.json"
    assert snapshot.is_file()
    plan = json.loads(snapshot.read_text(encoding="utf-8"))
    assert "summary" in plan and "by_sop_pack" in plan


# =========================================================================== per-stage happy path

def test_discover_happy_path(tmp_path):
    run_dir = _mk_run(tmp_path)
    _write_discover(run_dir)
    paths, report = aers.run_dets(run_dir, "DISCOVER", TS)
    assert paths
    for p in paths:
        assert validate_artifact(json.loads(Path(p).read_text(encoding="utf-8"))) == []
    assert report["search_rounds"] == 1
    assert report["search_stop_reason"] == "semantic_complete"
    assert report["referential_integrity"] == "PASS"
    assert report["existence_gate"] == "NOT_APPLICABLE"


def test_design_happy_path(tmp_path):
    run_dir = _mk_run(tmp_path)
    _write_design(run_dir)
    paths, report = aers.run_dets(run_dir, "DESIGN", TS)
    assert paths
    for p in paths:
        assert validate_artifact(json.loads(Path(p).read_text(encoding="utf-8"))) == []
    assert report["n_data_protocol_steps"] == 2
    assert report["n_augmentation_steps"] == 1


def test_design_anti_leakage_gate_blocks_an_augmentation_step_outside_train_only(tmp_path):
    run_dir = _mk_run(tmp_path)
    leaky = _good_data_protocol()
    leaky["data_protocol"]["steps"][1]["train_only"] = False
    _write_design(run_dir, protocol=leaky)
    with pytest.raises(GateBlock, match="anti-leakage"):
        aers.run_dets(run_dir, "DESIGN", TS)


def test_execute_happy_path_is_packaging_only_never_a_run_claim(tmp_path):
    run_dir = _mk_run(tmp_path)
    _write_execute(run_dir)
    paths, report = aers.run_dets(run_dir, "EXECUTE", TS)
    assert paths
    for p in paths:
        assert validate_artifact(json.loads(Path(p).read_text(encoding="utf-8"))) == []
    assert report["executed"] is False
    assert report["reproducibility_risk"] == "low"
    assert report["numeric_benchmark_verdict"] == _expected_bench_verdict()


def test_execute_refuses_own_measured_metrics_without_an_execution_receipt(tmp_path):
    """Mode-specific hard gate: this pack ran nothing, so a worker-reported 'own' metric with no
    attested execution receipt is a fabrication, refused before anything is written."""
    run_dir = _mk_run(tmp_path)
    _write_execute(run_dir, own_measured_metrics=[{"metric": "dice", "value": 0.91}])
    with pytest.raises(GateBlock, match="own-measured benchmark metrics"):
        aers.run_dets(run_dir, "EXECUTE", TS)


def test_analyze_happy_path(tmp_path):
    run_dir = _mk_run(tmp_path)
    _write_analyze(run_dir)
    paths, report = aers.run_dets(run_dir, "ANALYZE", TS)
    assert paths
    for p in paths:
        assert validate_artifact(json.loads(Path(p).read_text(encoding="utf-8"))) == []
    assert report["bibliography_refs_reverified"] == 1


# =========================================================================== bundle prechecks

def test_missing_seat_bundle_blocks(tmp_path):
    run_dir = _mk_run(tmp_path)
    _write_bundle(run_dir, "DISCOVER", "aers-sop-curator", _good_applicability_note())
    # literature-search-strategist bundle never written
    with pytest.raises(GateBlock, match="literature-search-strategist"):
        aers.run_dets(run_dir, "DISCOVER", TS)


# =========================================================================== full sequential walkthrough

def test_full_sequential_walkthrough_renders_every_required_verify_section(tmp_path):
    """VERIFY reads every prior stage's already-committed artifacts (`_read_stage_payloads`), so
    it must be exercised as a real DISCOVER->DESIGN->EXECUTE->ANALYZE->VERIFY chain, not in
    isolation, to prove the director brief is assembled from committed evidence, not prose."""
    run_dir = _mk_run(tmp_path)

    _write_discover(run_dir)
    d_paths, _ = aers.run_dets(run_dir, "DISCOVER", TS)
    assert d_paths

    _write_design(run_dir)
    design_paths, _ = aers.run_dets(run_dir, "DESIGN", TS)
    assert design_paths

    _write_execute(run_dir)
    exec_paths, exec_report = aers.run_dets(run_dir, "EXECUTE", TS)
    assert exec_paths

    _write_analyze(run_dir)
    analyze_paths, _ = aers.run_dets(run_dir, "ANALYZE", TS)
    assert analyze_paths

    _write_verify(run_dir)
    verify_paths, verify_report = aers.run_dets(run_dir, "VERIFY", TS)
    assert verify_paths
    for p in verify_paths:
        assert validate_artifact(json.loads(Path(p).read_text(encoding="utf-8"))) == []

    md_path = run_dir / verify_report["director_research_pack"]
    assert md_path.is_file()
    text = md_path.read_text(encoding="utf-8")
    for section in ("AERS references and applicability", "Literature search strategy",
                    "Data-wrangling protocol", "Reproducibility package", "Benchmark evidence",
                    "Submission checklist", "Bibliography audit", "Manuscript revisions"):
        assert f"## {section}" in text, section

    # the EXECUTE honesty boundary must reach the rendered brief verbatim, not be softened
    assert "Did NOT run" in text or "did NOT run" in text.lower()
    assert exec_report["executed"] is False

    report_paths, _report_dict = aers.run_dets(run_dir, "REPORT", TS)
    assert report_paths
    report_note = None
    for p in report_paths:
        art = json.loads(Path(p).read_text(encoding="utf-8"))
        assert validate_artifact(art) == []
        if art.get("artifact_type") == "report_note":
            report_note = art["payload"]
    assert report_note is not None
    assert verify_report["director_research_pack"] in report_note["references"]


def test_run_dets_with_repair_happy_path_returns_ok_for_every_stage(tmp_path):
    run_dir = _mk_run(tmp_path)
    _write_discover(run_dir)
    outcome, payload = aers.run_dets_with_repair(run_dir, "DISCOVER", TS)
    assert outcome == "ok"
    assert payload[0]


# =========================================================================== pre_search

def test_pre_search_degrades_honestly_on_dead_transport(tmp_path):
    run_dir = _mk_run(tmp_path)

    def down(url, headers):
        from research_agent_teams.tools.scholar_clients import ScholarLookupError
        raise ScholarLookupError("offline")

    p = aers.pre_search(run_dir, "assemble the pack", TS, transport=down)
    data = json.loads(Path(p).read_text(encoding="utf-8"))
    assert data["records"] == []
    assert len(data["source_errors"]) == 4
