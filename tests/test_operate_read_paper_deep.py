"""Operate read_paper_deep + ingest_paper recipes — paper-reading upgrade P4 wiring tests.

Proves: the single-paper deep-read writes all EIGHT typed artifacts; the north-star drift + citation +
existence HARD gates fire and APPROVE a clean read; the evidence-verifier SATURATION gate is correctly
SKIPPED (one source has nothing to saturate); a missing bundle key / empty (fabricated) source_ref / an
unresolvable locus ref each BLOCK; paper_appraisal is ADVISORY (written, never a gate, never blocks).
Plus ingest_paper's Tier-S happy path + a malformed-note BLOCK, and the OPTIONAL fulltext_pre degrading
honestly (available:false) when the paper-qa dependency is absent, never crashing the run.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from research_agent_teams.operate.artifacts import GateBlock
from research_agent_teams.operate.modes import ingest_paper, read_paper_deep
from research_agent_teams.tools import fulltext_qa
from research_agent_teams.tools.validate_artifact import validate_artifact

TS = "2026-06-26T12:00:00Z"
SOURCE = "doi:10.1109/TMI.2024.7654321"
NORTH_STAR = {"statement": "inferior alveolar canal segmentation in CBCT",
              "in_scope": ["canal", "segmentation", "CBCT", "foundation model"],
              "out_of_scope": []}

# eight deep-read artifact filenames (the card the recipe writes)
EIGHT_FILES = ["paper-note", "claim-list", "claim-evidence-map", "method-teardown",
               "figure-reading", "paper-appraisal", "paper-relations", "trend-card"]

# the citation-existence gate is forced OFFLINE + the vault unreachable by conftest's autouse
# `hermetic_gates` fixture, so every existence lookup degrades to a WARNING (the offline-safe PASS).


def _mk_run(tmp_path, name="run-1", mode="read_paper_deep", north_star=NORTH_STAR, budget=None):
    run_dir = tmp_path / name
    (run_dir / "inbox").mkdir(parents=True)
    tf = {"payload": {"task_id": name, "mode": mode, "north_star": north_star,
                      "budget": budget or {"max_agent_hops": 8, "max_debug_retries_per_run": 3}}}
    (run_dir / "task_frame.artifact.json").write_text(json.dumps(tf), encoding="utf-8")
    return run_dir


def _write_bundle(run_dir, payload):
    (run_dir / "inbox" / "DISCOVER.bundle.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _validate_written(paths):
    for p in paths:
        art = json.loads(Path(p).read_text(encoding="utf-8"))
        assert validate_artifact(art) == [], f"artifact failed contract: {p}"


def _load(paths, needle):
    return json.loads(Path(next(p for p in paths if needle in p)).read_text(encoding="utf-8"))


def _good_bundle(source_ref=SOURCE):
    """A clean single-paper deep read: all eight artifacts valid, every locus anchored to the paper."""
    return {
        "paper_note": {
            "title": "A foundation model for inferior alveolar canal segmentation in CBCT",
            "source_ref": source_ref,
            "summary": "Adapts a segmentation foundation model to thin tubular canal structures in CBCT "
                       "volumes, improving topological continuity over supervised baselines.",
            "claims": ["the adapted foundation model beats nnU-Net on canal segmentation Dice",
                       "topological continuity improves with the boundary loss"],
            "methods": ["low-rank adapter", "boundary loss"], "datasets": ["CBCT"], "metrics": ["Dice"],
            "paper_type": "method", "read_purpose": "method", "relation_to_thesis": "A-core",
            "reading_objective": "establish whether foundation-model adaptation helps canal segmentation",
            "reading_status": "deep-read",
            "paper_contract": {"category": "method", "context": "CBCT canal segmentation",
                               "correctness_prior": "plausible", "contributions": ["adapter", "loss"],
                               "clarity": "clear",
                               "contract_sentence": "thin canal segmentation -> FM adapter + boundary loss "
                                                    "-> vs supervised -> Dice/HD95 -> CBCT only"}},
        "claim_list": {"source_scope": "this paper", "claims": [
            {"claim_id": "c1", "text": "the adapted foundation model beats nnU-Net on canal Dice",
             "source_ref": source_ref},
            {"claim_id": "c2", "text": "topological continuity improves with the boundary loss",
             "source_ref": source_ref}]},
        "claim_evidence_map": {"mappings": [
            {"claim_id": "c1", "overall_support": "supported",
             "loci": [{"locus_id": "l1", "source_ref": source_ref, "location": "Table 2",
                       "kind": "table", "reported_result": "0.91 vs 0.85 Dice", "supports_claim": True,
                       "directness": "direct"}],
             "claim_risk": {"level": "low", "note": "direct Dice comparison"}},
            {"claim_id": "c2", "overall_support": "supported",
             "loci": [{"locus_id": "l2", "source_ref": source_ref, "location": "Figure 4",
                       "kind": "figure", "reported_result": "fewer canal breaks with boundary loss",
                       "supports_claim": True}]}]},
        "method_teardown": {"source_ref": source_ref,
                            "problem_definition": "input CBCT volume -> binary canal segmentation mask",
                            "core_assumptions": ["the canal is a single connected tube"],
                            "representation": "adds a low-rank adapter + boundary-aware loss to a frozen "
                                              "foundation-model encoder for canal segmentation",
                            "loss_terms": [
                                {"term": "Dice", "role": "region overlap", "ablate_effect": "recall drops"},
                                {"term": "boundary", "role": "continuity", "ablate_effect": "more breaks"}],
                            "training_flow": "freeze encoder, train adapter + decoder with Dice+boundary",
                            "inference_flow": "single forward pass + connected-component cleanup",
                            "train_infer_consistency": "matched",
                            "data": "480 CBCT volumes, patient-level split",
                            "cost": "4.2M trainable params",
                            "baseline_difference": "the boundary loss on a frozen FM"},
        "figure_reading": {"source_ref": source_ref, "figures": [
            {"figure_ref": "Figure 4", "axes": "method vs continuity-error count",
             "controls": "nnU-Net, supervised FM", "error_bars": None,
             "take_home": "the boundary loss reduces canal breaks",
             "distrust": "no variance shown across folds"}]},
        "paper_appraisal": {"source_ref": source_ref, "paper_type": "method",
                            "dimensions": [
                                {"dim": "soundness", "score": 3, "evidence_ref": "Section 4", "note": "solid"},
                                {"dim": "eval_rigor", "score": 2, "evidence_ref": None,
                                 "note": "single split, no variance"},
                                {"dim": "reproducibility", "score": 2, "note": "no code released"}],
                            "assumptions": ["canal connectivity"],
                            "limitations_acknowledged": ["single center"],
                            "limitations_unacknowledged": ["no cross-scanner test"],
                            "baseline_fairness": "nnU-Net tuned, fair",
                            "ablation_sufficiency": "loss terms ablated",
                            "statistical_robustness": "no variance reported",
                            "selective_reporting": "none evident",
                            "reproducibility_gaps": ["no code"], "generalization": "single-center only",
                            "reviewer_questions": ["how does it transfer across scanners?"],
                            "checklist": {"standard": "tripod_ai",
                                          "items": [{"item": "reports calibration", "status": "unmet",
                                                     "note": "absent"}]},
                            "overall": "a solid single-center method paper; eval rigor is the weakness"},
        "paper_relations": {"source_ref": source_ref, "edges": [
            {"target_ref": "[[nnunet]]", "relation": "extends", "note": "uses nnU-Net as the baseline"},
            {"target_ref": "doi:10.1000/sam", "relation": "uses", "note": "adapts the SAM family"}]},
        "trend_card": {"scope": "foundation-model adaptation for thin-structure CBCT segmentation",
                       "shifts": [{"dimension": "method", "from": "fully supervised nnU-Net",
                                   "to": "adapter-tuned foundation models"}],
                       "failure_modes": ["broken tubular continuity"],
                       "mechanism_vs_result": "mostly reports THAT, rarely explains WHY",
                       "reproducibility_trend": "stagnant", "opportunities": ["topology-aware losses"],
                       "source_refs": [source_ref]},
    }


# ---------------- read_paper_deep — happy path ----------------

def test_read_paper_deep_writes_all_eight_artifacts_and_gates_approve(tmp_path):
    run_dir = _mk_run(tmp_path)
    _write_bundle(run_dir, _good_bundle())
    paths, report = read_paper_deep.run_dets(run_dir, "DISCOVER", TS)

    # all eight typed artifacts written
    for needle in EIGHT_FILES:
        assert any(needle in p for p in paths), f"missing artifact {needle}"
    # the live hard gates fired and approved (saturation gate deliberately absent — single source)
    assert report["citation_gate"] == "PASS" and report["existence_gate"] == "PASS"
    assert not any("evidence-verdict" in p for p in paths), "saturation gate must be SKIPPED for 1 source"
    drift = _load(paths, "drift-verdict")
    assert drift["status"] == "approved" and drift["payload"]["pass"] is True
    # counts reflect the read
    assert report["n_claims"] == 2 and report["n_figures"] == 1 and report["n_relations"] == 2
    assert report["n_loss_terms"] == 2 and report["n_appraisal_dims"] == 3 and report["n_trend_shifts"] == 1
    _validate_written(paths)

    rpaths, _ = read_paper_deep.run_dets(run_dir, "REPORT", TS)
    _validate_written(rpaths)


def test_read_paper_deep_paper_note_written_as_draft(tmp_path):
    run_dir = _mk_run(tmp_path)
    _write_bundle(run_dir, _good_bundle())
    paths, _ = read_paper_deep.run_dets(run_dir, "DISCOVER", TS)
    note = _load(paths, "paper-note")
    assert note["status"] == "draft" and note["artifact_type"] == "paper_note"  # ingestion never freezes


# ---------------- read_paper_deep — appraisal stays ADVISORY ----------------

def test_read_paper_deep_appraisal_is_advisory_never_blocks(tmp_path):
    run_dir = _mk_run(tmp_path)
    b = _good_bundle()
    # harshest possible appraisal — every dimension a 1; the run must STILL succeed (appraisal never gates)
    b["paper_appraisal"]["dimensions"] = [{"dim": d, "score": 1, "note": "poor"} for d in
                                          ("soundness", "significance", "eval_rigor", "reproducibility")]
    b["paper_appraisal"]["overall"] = "weak paper on every axis"
    _write_bundle(run_dir, b)
    paths, report = read_paper_deep.run_dets(run_dir, "DISCOVER", TS)   # no GateBlock
    assert report["citation_gate"] == "PASS"
    appraisal = _load(paths, "paper-appraisal")["payload"]
    # structurally impossible to carry a verdict/decision (additionalProperties:false) — assert it
    for forbidden in ("verdict", "decision", "accept", "reject", "meets_bar", "status", "cut"):
        assert forbidden not in appraisal


# ---------------- read_paper_deep — hard-gate BLOCKs ----------------

def test_read_paper_deep_missing_bundle_key_blocks(tmp_path):
    run_dir = _mk_run(tmp_path)
    b = _good_bundle()
    del b["trend_card"]                                   # worker dropped one of the eight
    _write_bundle(run_dir, b)
    with pytest.raises(GateBlock) as ei:
        read_paper_deep.run_dets(run_dir, "DISCOVER", TS)
    assert "trend_card" in str(ei.value) and "missing required key" in str(ei.value)


def test_read_paper_deep_empty_source_ref_blocks_on_schema(tmp_path):
    run_dir = _mk_run(tmp_path)
    _write_bundle(run_dir, _good_bundle(source_ref=""))   # fabricated/empty anchor -> schema BLOCK
    with pytest.raises(GateBlock) as ei:
        read_paper_deep.run_dets(run_dir, "DISCOVER", TS)
    assert "schema BLOCK" in str(ei.value) and "source_ref" in str(ei.value)


def test_read_paper_deep_unresolvable_locus_blocks_citation(tmp_path):
    run_dir = _mk_run(tmp_path)
    b = _good_bundle()
    # a locus citing a paper OTHER than the one being read — citation-integrity must BLOCK (the gate
    # is real, not vacuous): resolvable_refs is the single paper, this ref is not in it.
    b["claim_evidence_map"]["mappings"][0]["loci"][0]["source_ref"] = "doi:10.9999/not-this-paper"
    _write_bundle(run_dir, b)
    with pytest.raises(GateBlock) as ei:
        read_paper_deep.run_dets(run_dir, "DISCOVER", TS)
    assert "citation gate BLOCK" in str(ei.value)


def test_read_paper_deep_unknown_stage_raises_valueerror(tmp_path):
    run_dir = _mk_run(tmp_path)
    with pytest.raises(ValueError):
        read_paper_deep.run_dets(run_dir, "NO_SUCH_STAGE", TS)


def test_read_paper_deep_llm_step_shape_carries_north_star(tmp_path):
    run_dir = str(_mk_run(tmp_path))
    spec = read_paper_deep.llm_step(run_dir, "DISCOVER", "read this canal paper", model_policy="default")
    assert spec["label"] == "read-paper-deep-worker"
    assert spec["output"].endswith("inbox/DISCOVER.bundle.json")
    assert "NORTH STAR" in spec["prompt"] and "read this canal paper" in spec["prompt"]
    assert "REPAIR ATTEMPT" in spec["prompt"]
    assert spec["model"] == "sonnet"                                   # default policy -> sonnet
    assert read_paper_deep.llm_step(run_dir, "DISCOVER", "q")["model"] == "opus"  # max_quality default
    assert read_paper_deep.llm_step(run_dir, "REPORT", "q") is None


# ---------------- read_paper_deep — optional fulltext pre-step ----------------

def test_fulltext_pre_no_docs_writes_nothing(tmp_path):
    run_dir = _mk_run(tmp_path)
    assert read_paper_deep.fulltext_pre(str(run_dir), "what is the method?", [], TS) is None
    assert not (run_dir / "inbox" / "fulltext-qa.json").exists()


def test_fulltext_pre_degrades_honestly_when_paperqa_absent(tmp_path, monkeypatch):
    run_dir = _mk_run(tmp_path)
    monkeypatch.setattr(fulltext_qa, "paperqa_available", lambda: False)   # force the absent path
    doc = str(tmp_path / "scratch" / "paper.pdf")                          # non-vault scratch doc
    p = read_paper_deep.fulltext_pre(str(run_dir), "what is the method?", [doc], TS)
    assert p is not None
    report = json.loads(Path(p).read_text(encoding="utf-8"))
    assert report["available"] is False and "paper-qa" in report["reason"]   # honest, never fabricated
    assert (run_dir / "inbox" / "fulltext-qa.json").exists()


# ---------------- ingest_paper — Tier-S happy path + BLOCK ----------------

def test_ingest_paper_happy_path_writes_draft_note(tmp_path):
    run_dir = _mk_run(tmp_path, mode="ingest_paper")
    pn = _good_bundle()["paper_note"]
    pn["reading_status"] = "skimmed"                                      # Tier-S quick note
    _write_bundle(run_dir, {"paper_note": pn})
    paths, report = ingest_paper.run_dets(run_dir, "DISCOVER", TS)
    assert report["n_claims"] == 2 and report["reading_status"] == "skimmed"
    note = _load(paths, "paper-note")
    assert note["status"] == "draft" and note["artifact_type"] == "paper_note"
    _validate_written(paths)
    rpaths, _ = ingest_paper.run_dets(run_dir, "REPORT", TS)
    _validate_written(rpaths)


def test_ingest_paper_malformed_note_blocks(tmp_path):
    run_dir = _mk_run(tmp_path, mode="ingest_paper")
    pn = _good_bundle()["paper_note"]
    pn["reading_status"] = "not-a-real-status"                            # invalid enum -> schema BLOCK
    _write_bundle(run_dir, {"paper_note": pn})
    with pytest.raises(GateBlock) as ei:
        ingest_paper.run_dets(run_dir, "DISCOVER", TS)
    assert "schema BLOCK" in str(ei.value)


def test_ingest_paper_missing_key_blocks(tmp_path):
    run_dir = _mk_run(tmp_path, mode="ingest_paper")
    _write_bundle(run_dir, {"not_a_note": {}})
    with pytest.raises(GateBlock) as ei:
        ingest_paper.run_dets(run_dir, "DISCOVER", TS)
    assert "paper_note" in str(ei.value) and "missing required key" in str(ei.value)
