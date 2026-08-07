"""Tests for the `gap_scan` operate recipe (wave-2 absorption, built on `_panel_recipe`).

Covers the operate-layer contract `operate/cli.py` calls (`llm_step` / `run_dets` /
`run_dets_with_repair` / `pre_search`), plus the two mode-specific hard gates the registry's
`productization_gaps` explicitly ask for:

  - evidence coverage: gap-classifier may never silently drop a hunter's anchor while merging.
  - deterministic dedup: gap-classifier may never leave two near-identical candidates unmerged.

and the structural mutual-blindness of the two hunters (their dispatch prompts never name the
other's bundle path, and they share a dependency-free parallel wave).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from research_agent_teams.operate.artifacts import GateBlock
from research_agent_teams.operate.modes import _panel_recipe, gap_scan
from research_agent_teams.tools.validate_artifact import validate_artifact

TS = "2026-08-04T00:00:00Z"


def _mk_run(tmp_path, budget=None):
    run_dir = tmp_path / "run-1"
    (run_dir / "inbox").mkdir(parents=True)
    tf = {"payload": {
        "task_id": "run-1", "mode": "gap_scan",
        "request_text": "scan for candidate gaps in promptable segmentation",
        "north_star": {"statement": "candidate research gaps for promptable segmentation",
                       "in_scope": ["segmentation"], "out_of_scope": []},
        "budget": budget or {"max_agent_hops": 6, "max_debug_retries_per_run": 3}}}
    (run_dir / "task_frame.artifact.json").write_text(json.dumps(tf), encoding="utf-8")
    return run_dir


def _write_bundle(run_dir, agent: str, payload: dict) -> None:
    (run_dir / "inbox" / f"DISCOVER.{agent}.bundle.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _good_fw() -> dict:
    return {"future_work_items": {"items": [
        {"item_id": "FW-1",
         "statement": "Authors flag future research on promptable segmentation as unresolved.",
         "source_ref": "[[hu-2021-lora]]"},
    ]}}


def _good_wk() -> dict:
    return {"weakness_report": {"weaknesses": [
        {"gap_id": "WK-1", "locus": "baseline evaluation protocol for segmentation",
         "opportunity": "an equal-budget baseline would close the reported SOTA gap",
         "evidence_ref": ["[[hdilemma-2024]]"]},
    ]}}


def _good_signals() -> dict:
    return {"gap_signals": {"signals": [
        {"gap_id": "GAP-1",
         "statement": "Authors flag future research on promptable segmentation as unresolved.",
         "source_ref": "[[hu-2021-lora]]", "evidence_ref": ["[[hu-2021-lora]]"],
         "derived_from": ["future_work"]},
        {"gap_id": "GAP-2", "locus": "baseline evaluation protocol for segmentation",
         "opportunity": "an equal-budget baseline would close the reported SOTA gap",
         "evidence_ref": ["[[hdilemma-2024]]"], "derived_from": ["weakness_opportunity"]},
    ]}}


def _write_good_panel(run_dir) -> None:
    _write_bundle(run_dir, "future-work-miner", _good_fw())
    _write_bundle(run_dir, "weakness-spotter", _good_wk())
    _write_bundle(run_dir, "gap-classifier", _good_signals())


# =========================================================================== module contract

def test_stages_and_vault_match_the_registry_and_shared_default():
    assert gap_scan.STAGES == ["DISCOVER", "REPORT"]
    assert gap_scan.DEFAULT_VAULT == _panel_recipe.DEFAULT_VAULT


def test_unknown_stage_raises_value_error(tmp_path):
    run_dir = _mk_run(tmp_path)
    with pytest.raises(ValueError, match="gap_scan"):
        gap_scan.run_dets(run_dir, "IDEATE", TS)
    with pytest.raises(ValueError, match="gap_scan"):
        gap_scan.run_dets(run_dir, "SOMETHING_ELSE", TS)


# =========================================================================== llm_step / dispatch

def test_llm_step_dispatches_only_declared_seats(tmp_path):
    run_dir = _mk_run(tmp_path)
    panel = gap_scan.llm_step(run_dir, "DISCOVER", "scan request", gap_scan.DEFAULT_VAULT, "max_quality")
    labels = {worker["label"] for worker in panel["workers"]}
    assert labels == set(_panel_recipe.declared_seats("gap_scan"))
    assert labels == {"future-work-miner", "weakness-spotter", "gap-classifier"}


def test_llm_step_report_stage_is_deterministic(tmp_path):
    run_dir = _mk_run(tmp_path)
    assert gap_scan.llm_step(run_dir, "REPORT", "scan request") is None


def test_hunters_are_mutually_blind_in_their_dispatch_prompts(tmp_path):
    """future-work-miner and weakness-spotter must never be told to read each other's bundle —
    the panel's diversity has to be structural (parallel wave, no depends_on), not merely a
    prompt-discipline promise."""
    run_dir = _mk_run(tmp_path)
    panel = gap_scan.llm_step(run_dir, "DISCOVER", "scan request", gap_scan.DEFAULT_VAULT, "max_quality")
    by_label = {worker["label"]: worker for worker in panel["workers"]}

    fw_prompt = by_label["future-work-miner"]["prompt"]
    wk_prompt = by_label["weakness-spotter"]["prompt"]
    assert "weakness-spotter.bundle.json" not in fw_prompt
    assert "future-work-miner.bundle.json" not in wk_prompt

    assert by_label["future-work-miner"].get("depends_on") in (None, [])
    assert by_label["weakness-spotter"].get("depends_on") in (None, [])
    assert by_label["gap-classifier"]["depends_on"] == ["future-work-miner", "weakness-spotter"]

    assert panel["parallel_groups"][0] == ["future-work-miner", "weakness-spotter"]
    assert panel["parallel_groups"][1] == ["gap-classifier"]

    # the classifier IS told where to read both frozen bundles
    classifier_prompt = by_label["gap-classifier"]["prompt"]
    assert "future-work-miner.bundle.json" in classifier_prompt
    assert "weakness-spotter.bundle.json" in classifier_prompt


# =========================================================================== happy path

def test_happy_path_produces_valid_artifacts_and_markdown(tmp_path):
    run_dir = _mk_run(tmp_path)
    _write_good_panel(run_dir)

    paths, report = gap_scan.run_dets(run_dir, "DISCOVER", TS)
    assert paths, "DISCOVER must produce at least one artifact"
    for p in paths:
        art = json.loads(Path(p).read_text(encoding="utf-8"))
        errors = validate_artifact(art)
        assert errors == [], (p, errors)

    assert report["future_work_items"] == 1
    assert report["weaknesses"] == 1
    assert report["signals_classified"] == 2
    assert report["gaps_classified"] == 2
    assert set(report["gap_types"]) == {"stated_open_problem", "methodological_gap"}
    assert report["referential_integrity"] == "PASS"
    assert report["existence_gate"] == "NOT_APPLICABLE"

    md_path = run_dir / report["director_gap_scan"]
    assert md_path.is_file()
    text = md_path.read_text(encoding="utf-8")
    for section in ("Search scope", "Candidate gaps", "Evidence and source anchors",
                    "Gap classification", "Unknowns and next searches"):
        assert f"## {section}" in text, section
    assert "GAP-1" in text and "GAP-2" in text
    assert "[[hu-2021-lora]]" in text and "[[hdilemma-2024]]" in text
    # honesty floor: no novelty/bet language leaks into this lightweight scan
    assert "novelty" not in text.lower() or "no novelty" in text.lower()
    assert "bet recommendation" not in text.lower() or "no" in text.lower()

    report_paths, _ = gap_scan.run_dets(run_dir, "REPORT", TS)
    assert report_paths
    for p in report_paths:
        art = json.loads(Path(p).read_text(encoding="utf-8"))
        assert validate_artifact(art) == []


def test_run_dets_with_repair_happy_path_returns_ok(tmp_path):
    run_dir = _mk_run(tmp_path)
    _write_good_panel(run_dir)
    outcome, payload = gap_scan.run_dets_with_repair(run_dir, "DISCOVER", TS)
    assert outcome == "ok"
    paths, _report = payload
    assert paths


def test_happy_path_with_zero_candidates_is_honest_not_padded(tmp_path):
    """Both hunters legitimately find nothing — schemas allow empty arrays; the Markdown must say
    so honestly rather than fabricating a candidate."""
    run_dir = _mk_run(tmp_path)
    _write_bundle(run_dir, "future-work-miner", {"future_work_items": {"items": []}})
    _write_bundle(run_dir, "weakness-spotter", {"weakness_report": {"weaknesses": []}})
    _write_bundle(run_dir, "gap-classifier", {"gap_signals": {"signals": []}})

    paths, report = gap_scan.run_dets(run_dir, "DISCOVER", TS)
    for p in paths:
        assert validate_artifact(json.loads(Path(p).read_text(encoding="utf-8"))) == []
    assert report["gaps_classified"] == 0

    md_path = run_dir / report["director_gap_scan"]
    text = md_path.read_text(encoding="utf-8")
    assert "None" in text.split("## Candidate gaps", 1)[1].split("## ", 1)[0]


# =========================================================================== bundle prechecks

def test_missing_seat_bundle_blocks(tmp_path):
    run_dir = _mk_run(tmp_path)
    _write_bundle(run_dir, "future-work-miner", _good_fw())
    _write_bundle(run_dir, "weakness-spotter", _good_wk())
    # gap-classifier bundle never written
    with pytest.raises(GateBlock, match="gap-classifier"):
        gap_scan.run_dets(run_dir, "DISCOVER", TS)


def test_future_work_item_missing_source_ref_blocks(tmp_path):
    run_dir = _mk_run(tmp_path)
    fw = _good_fw()
    del fw["future_work_items"]["items"][0]["source_ref"]
    _write_bundle(run_dir, "future-work-miner", fw)
    _write_bundle(run_dir, "weakness-spotter", _good_wk())
    _write_bundle(run_dir, "gap-classifier", _good_signals())
    with pytest.raises(GateBlock, match="future-work-miner item"):
        gap_scan.run_dets(run_dir, "DISCOVER", TS)


def test_weakness_missing_opportunity_blocks(tmp_path):
    run_dir = _mk_run(tmp_path)
    wk = _good_wk()
    del wk["weakness_report"]["weaknesses"][0]["opportunity"]
    _write_bundle(run_dir, "future-work-miner", _good_fw())
    _write_bundle(run_dir, "weakness-spotter", wk)
    _write_bundle(run_dir, "gap-classifier", _good_signals())
    with pytest.raises(GateBlock, match="weakness-spotter weakness"):
        gap_scan.run_dets(run_dir, "DISCOVER", TS)


# =========================================================================== mode-specific hard gates

def test_signal_missing_gap_id_blocks(tmp_path):
    run_dir = _mk_run(tmp_path)
    _write_bundle(run_dir, "future-work-miner", _good_fw())
    _write_bundle(run_dir, "weakness-spotter", _good_wk())
    signals = _good_signals()
    signals["gap_signals"]["signals"][0]["gap_id"] = "   "
    _write_bundle(run_dir, "gap-classifier", signals)
    with pytest.raises(GateBlock, match="gap_id"):
        gap_scan.run_dets(run_dir, "DISCOVER", TS)


def test_signal_missing_evidence_ref_blocks(tmp_path):
    run_dir = _mk_run(tmp_path)
    _write_bundle(run_dir, "future-work-miner", _good_fw())
    _write_bundle(run_dir, "weakness-spotter", _good_wk())
    signals = _good_signals()
    signals["gap_signals"]["signals"][0]["evidence_ref"] = []
    _write_bundle(run_dir, "gap-classifier", signals)
    with pytest.raises(GateBlock, match="evidence_ref anchor"):
        gap_scan.run_dets(run_dir, "DISCOVER", TS)


def test_signal_bad_derived_from_blocks(tmp_path):
    """gap_scan only ever runs two hunters; a signal claiming provenance from a hunter that does
    not exist in this mode (e.g. white-space-mapper, only present in gap_breadth) is a bug."""
    run_dir = _mk_run(tmp_path)
    _write_bundle(run_dir, "future-work-miner", _good_fw())
    _write_bundle(run_dir, "weakness-spotter", _good_wk())
    signals = _good_signals()
    signals["gap_signals"]["signals"][0]["derived_from"] = ["white_space_present"]
    _write_bundle(run_dir, "gap-classifier", signals)
    with pytest.raises(GateBlock, match="derived_from"):
        gap_scan.run_dets(run_dir, "DISCOVER", TS)


def test_dropped_hunter_anchor_blocks_evidence_coverage(tmp_path):
    """productization_gap #1: gap-classifier must preserve every independent hunter finding.
    Dropping the weakness-spotter's anchor entirely during merge must BLOCK, never pass quietly."""
    run_dir = _mk_run(tmp_path)
    _write_bundle(run_dir, "future-work-miner", _good_fw())
    _write_bundle(run_dir, "weakness-spotter", _good_wk())
    signals = _good_signals()
    signals["gap_signals"]["signals"] = [signals["gap_signals"]["signals"][0]]  # drop GAP-2 entirely
    _write_bundle(run_dir, "gap-classifier", signals)
    with pytest.raises(GateBlock, match="evidence-coverage"):
        gap_scan.run_dets(run_dir, "DISCOVER", TS)


def test_near_duplicate_signals_block_dedup_gate(tmp_path):
    """productization_gap #2: deterministic deduplication. An unmerged near-duplicate signal
    (same statement, different gap_id) must BLOCK rather than silently double-count a gap."""
    run_dir = _mk_run(tmp_path)
    _write_bundle(run_dir, "future-work-miner", _good_fw())
    _write_bundle(run_dir, "weakness-spotter", _good_wk())
    signals = _good_signals()
    duplicate = dict(signals["gap_signals"]["signals"][0])
    duplicate["gap_id"] = "GAP-3"
    signals["gap_signals"]["signals"].append(duplicate)
    _write_bundle(run_dir, "gap-classifier", signals)
    with pytest.raises(GateBlock, match="dedup"):
        gap_scan.run_dets(run_dir, "DISCOVER", TS)


def test_fabricated_internal_ref_blocks_referential_integrity(tmp_path):
    """The classifier may not cite an evidence_ref that is neither a hunter-produced anchor nor a
    real vault page — an internal-id-shaped fabrication (mirrors a GAP-* id) must BLOCK."""
    run_dir = _mk_run(tmp_path)
    _write_bundle(run_dir, "future-work-miner", _good_fw())
    _write_bundle(run_dir, "weakness-spotter", _good_wk())
    signals = _good_signals()
    signals["gap_signals"]["signals"][0]["evidence_ref"].append("GAP-999")
    _write_bundle(run_dir, "gap-classifier", signals)
    with pytest.raises(GateBlock, match="referential integrity"):
        gap_scan.run_dets(run_dir, "DISCOVER", TS)


# =========================================================================== pre_search

def test_pre_search_degrades_honestly_on_dead_transport(tmp_path):
    run_dir = _mk_run(tmp_path)

    def down(url, headers):
        from research_agent_teams.tools.scholar_clients import ScholarLookupError
        raise ScholarLookupError("offline")

    p = gap_scan.pre_search(run_dir, "scan topic", TS, transport=down)
    data = json.loads(Path(p).read_text(encoding="utf-8"))
    assert data["records"] == []
    assert len(data["source_errors"]) == 4
