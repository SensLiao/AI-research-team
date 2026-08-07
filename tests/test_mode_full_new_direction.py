"""Tests for the `full_new_direction` operate recipe (DISCOVER -> REPORT) — wave 2.

Covers: the happy path (both grounding gates PASS, all five agent_subset artifacts validate, the
director Markdown carries every required_section, and REPORT closes cleanly); a missing gather_
landscape seat bundle (GateBlock naming the missing file); this mode's own hard gate firing on thin
evidence (evidence-verifier BLOCK); an unknown stage (ValueError); and that llm_step never dispatches
a seat outside the registry's agent_subset while proving the "frozen shared source set" wiring --
model-dataset-scout depends on lit-scout, so both scouts share ONE gather_landscape pass.

`tests/conftest.py`'s autouse `hermetic_gates` fixture already forces the citation-existence
transport offline (lookup_error -> warning) and the vault unreachable (slug refs -> warning, never a
violation), so every `[[slug]]` ref below is safe without a real vault fixture.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from research_agent_teams.operate.artifacts import GateBlock
from research_agent_teams.operate.modes import _panel_recipe, full_new_direction
from research_agent_teams.tools.validate_artifact import validate_artifact

TS = "2026-08-04T00:00:00Z"
MODE = full_new_direction.MODE


def _mk_run(tmp_path, budget=None):
    run_dir = tmp_path / "run-1"
    (run_dir / "inbox").mkdir(parents=True)
    tf = {"payload": {"task_id": "run-1", "mode": MODE,
                      "request_text": "find directions for residual correction on PET/CT",
                      "north_star": {"statement": "residual correction on PET/CT",
                                    "in_scope": ["residual correction", "PET/CT"],
                                    "out_of_scope": ["unrelated modalities"]},
                      "budget": budget or {"max_agent_hops": 6, "max_debug_retries_per_run": 3}}}
    (run_dir / "task_frame.artifact.json").write_text(json.dumps(tf), encoding="utf-8")
    return run_dir


def _write_bundle(run_dir, stage: str, label: str, payload: dict) -> Path:
    p = Path(_panel_recipe.bundle_path(run_dir, stage, label))
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(payload), encoding="utf-8")
    return p


# --------------------------------------------------------------------------- fixture bundles

_SOURCES = [
    {"id": "s1", "kind": "paper", "ref": "[[hu-2021-lora]]", "title": "LoRA", "year": 2021,
     "claim_support": "strong"},
    {"id": "s2", "kind": "paper", "ref": "[[toothfairy-2025]]", "title": "ToothFairy", "year": 2025,
     "claim_support": "moderate"},
    {"id": "s3", "kind": "paper", "ref": "[[hdilemma-2024]]", "title": "HD Dilemma", "year": 2024,
     "claim_support": "strong"},
    {"id": "s4", "kind": "paper", "ref": "[[residual-fm-2026]]", "title": "Residual FM", "year": 2026,
     "claim_support": "weak"},
    # a non-slug (external) ref so the existence gate has something to check, not NOT_APPLICABLE.
    {"id": "s5", "kind": "paper", "ref": "arXiv:2106.09685", "title": "LoRA arXiv", "year": 2021,
     "claim_support": "moderate"},
]

_LIT_SCOUT_BUNDLE = {
    "evidence_table": {
        "query": "residual correction for PET/CT attenuation artifacts",
        "sources": _SOURCES,
        "saturation_reached": True,
    },
    "claim_list": {
        "source_scope": "residual correction gap scan",
        "claims": [
            {"claim_id": "c1", "text": "Adapter tuning is underexplored for promptable 3D residual "
                                       "correction.", "source_ref": "[[hu-2021-lora]]"},
        ],
    },
    "claim_evidence_map": {
        "mappings": [
            {"claim_id": "c1", "overall_support": "supported",
             "loci": [{"locus_id": "l1", "source_ref": "[[hu-2021-lora]]", "location": "Sec 5",
                      "kind": "text", "reported_result": "named as open future work",
                      "supports_claim": True}]},
        ],
    },
    "signals": [
        {"gap_id": "GAP-1", "statement": "Adapter tuning underexplored for promptable residual "
                                         "correction", "source_ref": "[[hu-2021-lora]]",
         "evidence_ref": ["[[hu-2021-lora]]"]},                                    # stated_open_problem
        {"gap_id": "GAP-2", "locus": "baseline evaluation", "opportunity": "equal-budget comparison",
         "evidence_ref": ["[[hdilemma-2024]]"]},                                  # methodological_gap
    ],
}

_MODEL_DATASET_BUNDLE = {
    "task": "residual correction for PET/CT attenuation artifacts",
    "candidates": [
        {"kind": "model", "name": "SegResNet", "ref": "[[sam-vit-b]]", "modality": "3D CT/PET",
         "license": "Apache-2.0", "fit_notes": "Strong volumetric baseline."},
        {"kind": "dataset", "name": "ToothFairy3", "ref": "[[toothfairy-2025]]", "modality": "CBCT",
         "license": "non-commercial research", "fit_notes": "Overlaps lit-scout's frozen evidence."},
    ],
}


def _write_happy_bundles(run_dir):
    _write_bundle(run_dir, "DISCOVER", "lit-scout", _LIT_SCOUT_BUNDLE)
    _write_bundle(run_dir, "DISCOVER", "model-dataset-scout", _MODEL_DATASET_BUNDLE)


# =========================================================================== 1. happy path

def test_happy_path_discover_then_report_produces_valid_artifacts_and_markdown(tmp_path):
    run_dir = _mk_run(tmp_path)
    _write_happy_bundles(run_dir)

    paths, report = full_new_direction.run_dets(run_dir, "DISCOVER", TS)

    assert report["evidence_gate"] == "PASS"
    assert report["citation_gate"] == "PASS"
    assert report["gaps_classified"] == 2
    assert report["n_model_candidates"] == 1
    assert report["n_dataset_candidates"] == 1
    assert report["drift_gate"] == "PASS"
    # C2 (2026-08-07): offline transport means zero refs VERIFIED, so the gate now honestly
    # reports UNVERIFIED instead of PASS — it still proves the gate ran (not NOT_APPLICABLE).
    assert report["existence_gate"] == "UNVERIFIED"
    assert report["existence_warnings"] >= 1           # offline transport -> lookup_error warning
    assert report["referential_integrity"] == "PASS"
    assert report["prior_gap_overlaps"] == []          # no project workspace in this flat tmp_path

    # Every produced artifact validates against its schema.
    assert len(paths) >= 8   # evidence-verdict, evidence-table, citation-verdict, gap-classification,
                              # model-dataset-candidates, landscape-map, drift-verdict, existence-verdict
    seen_types = set()
    for p in paths:
        art = json.loads(Path(p).read_text(encoding="utf-8"))
        errors = validate_artifact(art)
        assert errors == [], f"{p} failed schema validation: {errors}"
        seen_types.add(art["artifact_type"])
    assert seen_types == {
        "evidence_verdict", "evidence_table", "citation_integrity_verdict", "gap_classification",
        "model_dataset_candidates", "landscape_map", "analysis_check_verdict",
        "citation_existence_verdict",
    }

    # created_by attribution matches the registry's agent_subset (or a documented synthetic identity).
    by_type = {json.loads(Path(p).read_text(encoding="utf-8"))["artifact_type"]:
               json.loads(Path(p).read_text(encoding="utf-8"))["created_by"] for p in paths}
    assert by_type["evidence_verdict"] == "evidence-verifier"
    assert by_type["evidence_table"] == "lit-scout"
    assert by_type["citation_integrity_verdict"] == "citation-integrity-auditor"
    assert by_type["gap_classification"] == "gap-classifier"
    assert by_type["model_dataset_candidates"] == "model-dataset-scout"

    # The director Markdown carries every registry-required section, non-empty.
    md_spec = _panel_recipe.target_markdown(MODE)
    md_path = Path(run_dir) / md_spec["path"]
    assert md_path.is_file()
    text = md_path.read_text(encoding="utf-8")
    for section in md_spec["required_sections"]:
        assert f"## {section}" in text, f"missing section {section!r}"

    # Product boundary (director lock): this mode stops before any bet; the director presses /idea-bet.
    handoff = text.split("## Recommended handoff", 1)[1]
    assert "/idea-bet" in handoff
    assert "director" in handoff.lower()
    assert "never" in handoff.lower() or "does not" in handoff.lower()

    # REPORT stage closes deterministically and references the same Markdown.
    rpaths, _rreport = full_new_direction.run_dets(run_dir, "REPORT", TS)
    assert len(rpaths) == 1
    rart = json.loads(Path(rpaths[0]).read_text(encoding="utf-8"))
    assert validate_artifact(rart) == []
    assert rart["artifact_type"] == "report_note"
    assert rart["payload"]["references"] == [md_spec["path"]]
    assert rart["payload"]["open_questions"] == []


def test_run_dets_with_repair_ok_path_matches_run_dets(tmp_path):
    run_dir = _mk_run(tmp_path)
    _write_happy_bundles(run_dir)
    outcome = full_new_direction.run_dets_with_repair(run_dir, "DISCOVER", TS)
    assert outcome[0] == "ok"
    paths, report = outcome[1]
    assert report["evidence_gate"] == "PASS"
    assert len(paths) >= 8


# =========================================================================== 2. missing seat bundle

def test_missing_seat_bundle_blocks_and_names_the_missing_file(tmp_path):
    run_dir = _mk_run(tmp_path)
    _write_bundle(run_dir, "DISCOVER", "lit-scout", _LIT_SCOUT_BUNDLE)
    # model-dataset-scout bundle deliberately never written.
    with pytest.raises(GateBlock, match=r"DISCOVER\.model-dataset-scout\.bundle\.json"):
        full_new_direction.run_dets(run_dir, "DISCOVER", TS)


def test_missing_both_seat_bundles_names_both_files(tmp_path):
    run_dir = _mk_run(tmp_path)
    with pytest.raises(GateBlock) as excinfo:
        full_new_direction.run_dets(run_dir, "DISCOVER", TS)
    msg = str(excinfo.value)
    assert "DISCOVER.lit-scout.bundle.json" in msg
    assert "DISCOVER.model-dataset-scout.bundle.json" in msg


# =========================================================================== 3. this mode's own hard gate

def test_evidence_gate_blocks_thin_evidence(tmp_path):
    run_dir = _mk_run(tmp_path)
    thin = copy.deepcopy(_LIT_SCOUT_BUNDLE)
    thin["evidence_table"]["sources"] = _SOURCES[:1]        # only 1 source: below min_sources=3
    thin["evidence_table"]["saturation_reached"] = False
    _write_bundle(run_dir, "DISCOVER", "lit-scout", thin)
    _write_bundle(run_dir, "DISCOVER", "model-dataset-scout", _MODEL_DATASET_BUNDLE)

    with pytest.raises(GateBlock, match="evidence gate BLOCK"):
        full_new_direction.run_dets(run_dir, "DISCOVER", TS)

    # halted BEFORE lit-scout's own evidence-table artifact (and everything after it) was written.
    discover_dir = Path(run_dir) / "evidence" / "DISCOVER"
    written = sorted(p.name for p in discover_dir.glob("*.json")) if discover_dir.is_dir() else []
    assert "evidence-verdict.artifact.json" in written
    assert "evidence-table.artifact.json" not in written
    assert "gap-classification.artifact.json" not in written
    verdict = json.loads((discover_dir / "evidence-verdict.artifact.json").read_text(encoding="utf-8"))
    assert verdict["payload"]["verdict"] == "BLOCK"
    assert verdict["status"] == "blocked"


def test_citation_gate_blocks_a_contradicted_claim(tmp_path):
    run_dir = _mk_run(tmp_path)
    contradicted = copy.deepcopy(_LIT_SCOUT_BUNDLE)
    contradicted["claim_evidence_map"] = {
        "mappings": [{"claim_id": "c1", "overall_support": "contradicted",
                     "loci": [{"locus_id": "l1", "source_ref": "[[hu-2021-lora]]", "location": "Sec 5",
                               "kind": "text", "reported_result": "claims it is already solved",
                               # A1 (2026-08-07): explicit contradicts relation required to BLOCK-and-name.
                               "support_relation": "contradicts",
                               "supports_claim": False}]}],
    }
    _write_bundle(run_dir, "DISCOVER", "lit-scout", contradicted)
    _write_bundle(run_dir, "DISCOVER", "model-dataset-scout", _MODEL_DATASET_BUNDLE)

    with pytest.raises(GateBlock, match="citation gate BLOCK"):
        full_new_direction.run_dets(run_dir, "DISCOVER", TS)

    discover_dir = Path(run_dir) / "evidence" / "DISCOVER"
    written = sorted(p.name for p in discover_dir.glob("*.json"))
    assert "evidence-table.artifact.json" in written        # evidence gate passed first
    assert "citation-verdict.artifact.json" in written
    assert "gap-classification.artifact.json" not in written  # halted before classify_directions
    cv = json.loads((discover_dir / "citation-verdict.artifact.json").read_text(encoding="utf-8"))
    assert cv["payload"]["verdict"] == "BLOCK"
    assert cv["payload"]["contradicted_claims"] == ["c1"]


# =========================================================================== 4. unknown stage

def test_unknown_stage_raises_value_error(tmp_path):
    run_dir = _mk_run(tmp_path)
    with pytest.raises(ValueError, match=f"{MODE} has no stage"):
        full_new_direction.run_dets(run_dir, "BOGUS_STAGE", TS)


# =========================================================================== 5. declared seats + freeze wiring

def test_llm_step_only_dispatches_declared_seats_and_freezes_the_source_set(tmp_path):
    run_dir = _mk_run(tmp_path)
    panel = full_new_direction.llm_step(run_dir, "DISCOVER", "find a direction")
    allowed = set(_panel_recipe.declared_seats(MODE))

    labels = {w["label"] for w in panel["workers"]}
    assert labels == {"lit-scout", "model-dataset-scout"}
    assert labels <= allowed

    # "Frozen shared source set": model-dataset-scout depends on lit-scout — it reads the SAME
    # frozen bundle rather than gathering a second, independent literature pass. This is the
    # structural proof of the freeze, not just a prose claim in the prompt.
    mds_worker = next(w for w in panel["workers"] if w["label"] == "model-dataset-scout")
    lit_worker = next(w for w in panel["workers"] if w["label"] == "lit-scout")
    assert mds_worker.get("depends_on") == ["lit-scout"]
    assert not lit_worker.get("depends_on")
    assert panel["parallel_groups"] == [["lit-scout"], ["model-dataset-scout"]]

    # REPORT is deterministic-only — dispatches nobody.
    assert full_new_direction.llm_step(run_dir, "REPORT", "find a direction") is None


def test_declared_seats_matches_registry_agent_subset():
    assert set(_panel_recipe.declared_seats(MODE)) == {
        "lit-scout", "model-dataset-scout", "evidence-verifier", "citation-integrity-auditor",
        "gap-classifier",
    }


# =========================================================================== bonus: pre_search wiring

def test_pre_search_degrades_honestly_offline(tmp_path):
    run_dir = _mk_run(tmp_path)

    def _offline_transport(url, headers):
        raise RuntimeError("offline (deterministic test transport)")

    path = full_new_direction.pre_search(str(run_dir), "find a direction", TS,
                                         transport=_offline_transport)
    assert Path(path).is_file()
    bundle = json.loads(Path(path).read_text(encoding="utf-8"))
    assert bundle.get("records") == []
    assert bundle.get("source_errors")
