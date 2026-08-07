"""Tests for the `ideate_ring` operate recipe (wave-2 backlog, wired 2026-08-07).

Covers the operate-layer contract `operate/cli.py` calls (`llm_step` / `run_dets` /
`run_dets_with_repair`), the five-seat panel's dependency waves, the fixed
`inbox/COLLISION.bundle.json` output-path override for novelty-collision-checker, and the mode's
own hard gates (duplicate hypothesis_id, empty tournament/evolution, feasibility coverage,
evolved-parent-id validity). This mode has NO `pre_search` (`entry_stage` is IDEATE, not
DISCOVER — the grounded input is the director's own opportunity-set text).

Director's 2026-08-07 hash/receipt-removal pass: `_check_bundle_immutability` (a sha256
fingerprint BLOCK across repair rounds) was stripped from `ideate_ring.py` — schema/markdown/
grounding/referential-integrity gates all stay. `test_rewriting_an_upstream_bundle_...` below
proves the removal rather than merely omitting a now-stale test.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from research_agent_teams.operate.artifacts import GateBlock
from research_agent_teams.operate.modes import _panel_recipe, ideate_ring
from research_agent_teams.tools.validate_artifact import validate_artifact

TS = "2026-08-07T00:00:00Z"


def _mk_run(tmp_path, request_text=None, budget=None):
    run_dir = tmp_path / "run-1"
    (run_dir / "inbox").mkdir(parents=True)
    tf = {"payload": {
        "task_id": "run-1", "mode": "ideate_ring",
        "request_text": request_text or (
            "Opportunity set: (1) promptable segmentation lacks an equal-budget baseline; "
            "(2) it is unclear whether a LoRA adapter matches full fine-tune at equal budget."),
        "north_star": {"statement": "a ranked, evidence-linked idea menu for promptable segmentation",
                       "in_scope": ["segmentation"], "out_of_scope": []},
        "budget": budget or {"max_agent_hops": 6, "max_debug_retries_per_run": 3}}}
    (run_dir / "task_frame.artifact.json").write_text(json.dumps(tf), encoding="utf-8")
    return run_dir


def _write_bundle(run_dir, filename: str, payload: dict) -> None:
    (run_dir / "inbox" / filename).write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _good_hypotheses() -> dict:
    return {"hypothesis_set": {"hypotheses": [
        {"hypothesis_id": "IH1",
         "statement": "An equal-budget baseline closes most of the reported SOTA gap.",
         "falsifiable_prediction": "Dice(equal-budget baseline) is within 1% of Dice(SOTA) at "
                                   "matched GPU-hours on fold0.",
         "evidence_needed": ["equal-budget ablation"],
         "evidence_ref": ["opportunity set fragment 1"]},
        {"hypothesis_id": "IH2",
         "statement": "A LoRA adapter matches full fine-tune for promptable segmentation.",
         "falsifiable_prediction": "Dice(LoRA) is within 1% of Dice(full-ft) at matched "
                                   "GPU-hours on fold0.",
         "evidence_needed": ["LoRA vs full-ft ablation"],
         "evidence_ref": ["opportunity set fragment 2"]},
    ]}}


def _good_tournament_ideas() -> dict:
    return {"tournament_ideas": [
        {"idea_id": "IDEA-1", "from_hypothesis_ref": "IH1",
         "summary": "Equal-budget baseline ablation for promptable segmentation.",
         "score": 0.8, "score_rationale": "highest leverage", "evidence_ref": ["IH1"]},
        {"idea_id": "IDEA-2", "from_hypothesis_ref": "IH2",
         "summary": "LoRA-vs-full-ft equal-budget ablation.",
         "score": 0.6, "score_rationale": "lower leverage than IDEA-1", "evidence_ref": ["IH2"]},
    ]}


def _good_evolved() -> dict:
    return {"evolved_ideas": {"ideas": [
        {"idea_id": "EV-1",
         "summary": "Equal-budget baseline ablation, strengthened with a variance report.",
         "parent_ids": ["IDEA-1"], "mutation_type": "strengthen", "evidence_ref": ["IDEA-1"]},
    ]}}


def _good_feasibility() -> dict:
    return {"feasibility_ratings": [
        {"idea_id": "IDEA-1",
         "feasibility": {"compute": "medium", "data": "available", "time": "medium"}},
        {"idea_id": "IDEA-2",
         "feasibility": {"compute": "low", "data": "available", "time": "short"}},
        {"idea_id": "EV-1",
         "feasibility": {"compute": "medium", "data": "available", "time": "medium"}},
    ]}


def _collision_finding(idea_id: str, method: str, query: str) -> dict:
    return {"idea_id": idea_id, "method_combination": method,
            "application": "promptable segmentation", "domain": "medical imaging",
            "queries": [query], "verdict": "unverified", "colliding_papers": [],
            "confidence": "medium", "retrieval_status": "unavailable",
            "retrieval_note": "offline — vault only"}


def _good_collision() -> dict:
    return {"findings": [
        _collision_finding("IDEA-1", "equal-budget baseline", "equal budget baseline segmentation"),
        _collision_finding("IDEA-2", "LoRA vs full fine-tune", "LoRA full fine-tune segmentation"),
        _collision_finding("EV-1", "equal-budget baseline, strengthened",
                           "equal budget baseline segmentation variance"),
    ], "evidence_ref": ["inbox/COLLISION.bundle.json"]}


def _write_good_panel(run_dir) -> None:
    _write_bundle(run_dir, "IDEATE.hypothesis-generator.bundle.json", _good_hypotheses())
    _write_bundle(run_dir, "IDEATE.idea-tournament-ranker.bundle.json", _good_tournament_ideas())
    _write_bundle(run_dir, "IDEATE.idea-evolver.bundle.json", _good_evolved())
    _write_bundle(run_dir, "IDEATE.feasibility-reranker.bundle.json", _good_feasibility())
    _write_bundle(run_dir, "COLLISION.bundle.json", _good_collision())


# =========================================================================== module contract

def test_stages_and_vault_match_the_registry_and_shared_default():
    assert ideate_ring.STAGES == ["IDEATE", "REPORT"]
    assert ideate_ring.DEFAULT_VAULT == _panel_recipe.DEFAULT_VAULT


def test_unknown_stage_raises_value_error(tmp_path):
    run_dir = _mk_run(tmp_path)
    with pytest.raises(ValueError, match="ideate_ring"):
        ideate_ring.run_dets(run_dir, "DISCOVER", TS)
    with pytest.raises(ValueError, match="ideate_ring"):
        ideate_ring.run_dets(run_dir, "SOMETHING_ELSE", TS)


def test_module_has_no_pre_search_entry_stage_is_ideate_not_discover():
    """entry_stage is IDEATE (registry-declared) — there is no DISCOVER grounding step in this
    mode, so unlike gap_scan/aers_enhanced_research_pack it exposes no `pre_search` function."""
    assert not hasattr(ideate_ring, "pre_search")


# =========================================================================== llm_step / dispatch

def test_llm_step_dispatches_only_declared_seats(tmp_path):
    run_dir = _mk_run(tmp_path)
    panel = ideate_ring.llm_step(run_dir, "IDEATE", "run the ring", ideate_ring.DEFAULT_VAULT,
                                 "max_quality")
    labels = {worker["label"] for worker in panel["workers"]}
    assert labels == set(_panel_recipe.declared_seats("ideate_ring"))
    assert labels == {"hypothesis-generator", "idea-tournament-ranker", "idea-evolver",
                      "feasibility-reranker", "novelty-collision-checker"}


def test_llm_step_report_stage_is_deterministic(tmp_path):
    run_dir = _mk_run(tmp_path)
    assert ideate_ring.llm_step(run_dir, "REPORT", "run the ring") is None


def test_llm_step_builds_four_dependency_waves(tmp_path):
    """hypothesis-generator -> idea-tournament-ranker -> idea-evolver -> {feasibility-reranker,
    novelty-collision-checker} run in parallel — the last wave is the only one with >1 seat."""
    run_dir = _mk_run(tmp_path)
    panel = ideate_ring.llm_step(run_dir, "IDEATE", "run the ring")
    assert panel["parallel_groups"] == [
        ["hypothesis-generator"],
        ["idea-tournament-ranker"],
        ["idea-evolver"],
        ["feasibility-reranker", "novelty-collision-checker"],
    ]


def test_llm_step_writes_collision_checker_to_the_fixed_path_not_the_standard_bundle_path(tmp_path):
    """novelty-collision-checker's output overrides the standard per-seat bundle_path so
    `_shared.run_collision_gate` can reuse the shared collision machinery verbatim."""
    run_dir = _mk_run(tmp_path)
    panel = ideate_ring.llm_step(run_dir, "IDEATE", "run the ring")
    by_label = {worker["label"]: worker for worker in panel["workers"]}
    collision_out = by_label["novelty-collision-checker"]["output"]
    assert collision_out == f"{run_dir}/{ideate_ring.COLLISION_BUNDLE_REL}"
    assert collision_out != _panel_recipe.bundle_path(run_dir, "IDEATE", "novelty-collision-checker")
    # every other seat keeps the standard per-seat naming
    for label in ("hypothesis-generator", "idea-tournament-ranker", "idea-evolver",
                 "feasibility-reranker"):
        assert by_label[label]["output"] == _panel_recipe.bundle_path(run_dir, "IDEATE", label)


def test_island_model_instruction_replaces_the_old_top_two_and_round_cap(tmp_path):
    """2026-08-07 director pass (R2-audit §A0-2): the evolver's old hard caps ('Pick the 2-3
    STRONGEST candidates', 'At most TWO evolve rounds') are gone; the island-model text — a
    floor, never a cap — is what actually gets dispatched."""
    run_dir = _mk_run(tmp_path)
    panel = ideate_ring.llm_step(run_dir, "IDEATE", "run the ring")
    by_label = {worker["label"]: worker for worker in panel["workers"]}
    evolver_prompt = by_label["idea-evolver"]["prompt"]
    assert "ISLAND generation" in evolver_prompt
    assert "The number of evolved ideas is a floor, never a cap" in evolver_prompt
    assert "Pick the 2-3 STRONGEST candidates" not in evolver_prompt
    assert "At most TWO evolve" not in evolver_prompt


# =========================================================================== happy path

def test_happy_path_produces_valid_artifacts_and_markdown(tmp_path):
    run_dir = _mk_run(tmp_path)
    _write_good_panel(run_dir)

    paths, report = ideate_ring.run_dets(run_dir, "IDEATE", TS)
    assert paths, "IDEATE must produce at least one artifact"
    for p in paths:
        art = json.loads(Path(p).read_text(encoding="utf-8"))
        errors = validate_artifact(art)
        assert errors == [], (p, errors)

    assert report["hypotheses"] == 2
    assert report["tournament_ideas"] == 2
    assert report["evolved"] == 1
    assert report["tournament_matchups"] == 1               # C(2,2 kept)=1 matchup
    assert report["ranked_ideas"] == 3                       # 2 originals + 1 evolved
    assert report["collision_survivors"] == 3                # offline -> nothing cut
    assert report["collision_cut"] == 0
    assert report["collision_retrieval_grounded"] is False   # retrieval_status=unavailable
    assert report["referential_integrity"] == "PASS"

    md_path = run_dir / report["director_idea_bet_menu"] if False else None  # REPORT renders it
    report_paths, report_note = ideate_ring.run_dets(run_dir, "REPORT", TS)
    assert report_paths
    for p in report_paths:
        art = json.loads(Path(p).read_text(encoding="utf-8"))
        assert validate_artifact(art) == []

    rel = report_note["director_idea_bet_menu"]
    md_path = run_dir / rel
    assert md_path.is_file()
    text = md_path.read_text(encoding="utf-8")
    for section in ("Input opportunity set", "Falsifiable hypotheses", "Tournament results",
                    "Evolved ideas and lineage", "Prior-art collisions", "Director bet menu"):
        assert f"## {section}" in text, section
    assert "IH1" in text and "IH2" in text
    assert "IDEA-1" in text and "EV-1" in text
    # honesty floor: the model never self-bets
    assert "/idea-bet" in text


def test_run_dets_with_repair_happy_path_returns_ok(tmp_path):
    run_dir = _mk_run(tmp_path)
    _write_good_panel(run_dir)
    outcome, payload = ideate_ring.run_dets_with_repair(run_dir, "IDEATE", TS)
    assert outcome == "ok"
    paths, _report = payload
    assert paths


# =========================================================================== bundle prechecks

def test_missing_seat_bundle_blocks(tmp_path):
    run_dir = _mk_run(tmp_path)
    _write_bundle(run_dir, "IDEATE.hypothesis-generator.bundle.json", _good_hypotheses())
    _write_bundle(run_dir, "IDEATE.idea-tournament-ranker.bundle.json", _good_tournament_ideas())
    _write_bundle(run_dir, "IDEATE.idea-evolver.bundle.json", _good_evolved())
    # feasibility-reranker bundle never written
    with pytest.raises(GateBlock, match="feasibility-reranker"):
        ideate_ring.run_dets(run_dir, "IDEATE", TS)


def test_empty_hypothesis_set_blocks(tmp_path):
    run_dir = _mk_run(tmp_path)
    _write_bundle(run_dir, "IDEATE.hypothesis-generator.bundle.json",
                 {"hypothesis_set": {"hypotheses": []}})
    _write_bundle(run_dir, "IDEATE.idea-tournament-ranker.bundle.json", _good_tournament_ideas())
    _write_bundle(run_dir, "IDEATE.idea-evolver.bundle.json", _good_evolved())
    _write_bundle(run_dir, "IDEATE.feasibility-reranker.bundle.json", _good_feasibility())
    _write_bundle(run_dir, "COLLISION.bundle.json", _good_collision())
    with pytest.raises(GateBlock, match="hypothesis_set has no hypotheses"):
        ideate_ring.run_dets(run_dir, "IDEATE", TS)


def test_duplicate_hypothesis_id_blocks(tmp_path):
    run_dir = _mk_run(tmp_path)
    hyps = _good_hypotheses()
    hyps["hypothesis_set"]["hypotheses"][1]["hypothesis_id"] = "IH1"   # duplicate of item 0
    _write_bundle(run_dir, "IDEATE.hypothesis-generator.bundle.json", hyps)
    _write_bundle(run_dir, "IDEATE.idea-tournament-ranker.bundle.json", _good_tournament_ideas())
    _write_bundle(run_dir, "IDEATE.idea-evolver.bundle.json", _good_evolved())
    _write_bundle(run_dir, "IDEATE.feasibility-reranker.bundle.json", _good_feasibility())
    _write_bundle(run_dir, "COLLISION.bundle.json", _good_collision())
    with pytest.raises(GateBlock, match="duplicate hypothesis_id"):
        ideate_ring.run_dets(run_dir, "IDEATE", TS)


def test_empty_tournament_ideas_blocks(tmp_path):
    run_dir = _mk_run(tmp_path)
    _write_bundle(run_dir, "IDEATE.hypothesis-generator.bundle.json", _good_hypotheses())
    _write_bundle(run_dir, "IDEATE.idea-tournament-ranker.bundle.json", {"tournament_ideas": []})
    _write_bundle(run_dir, "IDEATE.idea-evolver.bundle.json", _good_evolved())
    _write_bundle(run_dir, "IDEATE.feasibility-reranker.bundle.json", _good_feasibility())
    _write_bundle(run_dir, "COLLISION.bundle.json", _good_collision())
    with pytest.raises(GateBlock, match="no candidate ideas"):
        ideate_ring.run_dets(run_dir, "IDEATE", TS)


def test_empty_evolved_ideas_blocks(tmp_path):
    run_dir = _mk_run(tmp_path)
    _write_bundle(run_dir, "IDEATE.hypothesis-generator.bundle.json", _good_hypotheses())
    _write_bundle(run_dir, "IDEATE.idea-tournament-ranker.bundle.json", _good_tournament_ideas())
    _write_bundle(run_dir, "IDEATE.idea-evolver.bundle.json", {"evolved_ideas": {"ideas": []}})
    _write_bundle(run_dir, "IDEATE.feasibility-reranker.bundle.json", _good_feasibility())
    _write_bundle(run_dir, "COLLISION.bundle.json", _good_collision())
    with pytest.raises(GateBlock, match="no evolved ideas"):
        ideate_ring.run_dets(run_dir, "IDEATE", TS)


def test_evolved_idea_with_unknown_parent_id_blocks(tmp_path):
    """A parent_id naming an id no upstream stage ever minted is caught by the generic
    referential-integrity gate (checked first, in `common_gates`)."""
    run_dir = _mk_run(tmp_path)
    _write_bundle(run_dir, "IDEATE.hypothesis-generator.bundle.json", _good_hypotheses())
    _write_bundle(run_dir, "IDEATE.idea-tournament-ranker.bundle.json", _good_tournament_ideas())
    evolved = _good_evolved()
    evolved["evolved_ideas"]["ideas"][0]["parent_ids"] = ["IDEA-999"]
    _write_bundle(run_dir, "IDEATE.idea-evolver.bundle.json", evolved)
    _write_bundle(run_dir, "IDEATE.feasibility-reranker.bundle.json", _good_feasibility())
    _write_bundle(run_dir, "COLLISION.bundle.json", _good_collision())
    with pytest.raises(GateBlock, match="referential integrity"):
        ideate_ring.run_dets(run_dir, "IDEATE", TS)


def test_evolved_idea_pointing_at_another_evolved_idea_blocks_surviving_parent_check(tmp_path):
    """A parent_id that IS a real ring id (so it clears referential integrity — evolved_ids are
    part of known_ids) but is not one of the SURVIVING ORIGINAL ideas (only tournament ideas are
    eligible parents) must still BLOCK on the mode's own post-dedup parent check."""
    run_dir = _mk_run(tmp_path)
    _write_bundle(run_dir, "IDEATE.hypothesis-generator.bundle.json", _good_hypotheses())
    _write_bundle(run_dir, "IDEATE.idea-tournament-ranker.bundle.json", _good_tournament_ideas())
    evolved = _good_evolved()
    evolved["evolved_ideas"]["ideas"].append(
        {"idea_id": "EV-2", "summary": "A second-generation strengthening of EV-1.",
         "parent_ids": ["EV-1"], "mutation_type": "strengthen", "evidence_ref": ["EV-1"]})
    _write_bundle(run_dir, "IDEATE.idea-evolver.bundle.json", evolved)
    feas = _good_feasibility()
    feas["feasibility_ratings"].append(
        {"idea_id": "EV-2", "feasibility": {"compute": "medium", "data": "available", "time": "medium"}})
    _write_bundle(run_dir, "IDEATE.feasibility-reranker.bundle.json", feas)
    collision = _good_collision()
    collision["findings"].append(_collision_finding("EV-2", "second-generation strengthening",
                                                     "equal budget baseline segmentation variance v2"))
    _write_bundle(run_dir, "COLLISION.bundle.json", collision)
    with pytest.raises(GateBlock, match="parent_ids"):
        ideate_ring.run_dets(run_dir, "IDEATE", TS)


def test_missing_feasibility_coverage_blocks(tmp_path):
    """productization gap: feasibility-reranker must rate EVERY original and evolved idea."""
    run_dir = _mk_run(tmp_path)
    _write_bundle(run_dir, "IDEATE.hypothesis-generator.bundle.json", _good_hypotheses())
    _write_bundle(run_dir, "IDEATE.idea-tournament-ranker.bundle.json", _good_tournament_ideas())
    _write_bundle(run_dir, "IDEATE.idea-evolver.bundle.json", _good_evolved())
    feas = _good_feasibility()
    feas["feasibility_ratings"] = feas["feasibility_ratings"][:2]   # drop EV-1's rating
    _write_bundle(run_dir, "IDEATE.feasibility-reranker.bundle.json", feas)
    _write_bundle(run_dir, "COLLISION.bundle.json", _good_collision())
    with pytest.raises(GateBlock, match="did not rate idea"):
        ideate_ring.run_dets(run_dir, "IDEATE", TS)


def test_fabricated_ring_internal_ref_blocks_referential_integrity(tmp_path):
    """A RING-INTERNAL reference (idea -> hypothesis, evolved -> idea) that names an id nobody
    upstream minted must BLOCK — but hypothesis-generator's OWN evidence_ref (which points OUTSIDE
    the ring, at the director's freeform text) is validated only by the hypothesis_set schema."""
    run_dir = _mk_run(tmp_path)
    _write_bundle(run_dir, "IDEATE.hypothesis-generator.bundle.json", _good_hypotheses())
    ideas = _good_tournament_ideas()
    ideas["tournament_ideas"][0]["evidence_ref"] = ["IH1", "IDEA-999"]
    _write_bundle(run_dir, "IDEATE.idea-tournament-ranker.bundle.json", ideas)
    _write_bundle(run_dir, "IDEATE.idea-evolver.bundle.json", _good_evolved())
    _write_bundle(run_dir, "IDEATE.feasibility-reranker.bundle.json", _good_feasibility())
    _write_bundle(run_dir, "COLLISION.bundle.json", _good_collision())
    with pytest.raises(GateBlock, match="referential integrity"):
        ideate_ring.run_dets(run_dir, "IDEATE", TS)


# =========================================================================== novelty collision

def test_offline_collision_leaves_every_idea_unverified_and_cuts_nothing(tmp_path):
    """No retrieval grounding (retrieval_status=unavailable) -> never a false cut."""
    run_dir = _mk_run(tmp_path)
    _write_good_panel(run_dir)
    _paths, report = ideate_ring.run_dets(run_dir, "IDEATE", TS)
    assert report["collision_retrieval_grounded"] is False
    assert report["collision_cut"] == 0
    assert report["collision_survivors"] == report["ranked_ideas"]


def test_missing_collision_bundle_is_honest_not_a_crash(tmp_path):
    """`_shared.run_collision_gate` never requires the collision bundle to exist; a missing one
    degrades to 'not retrieval-grounded', never a fatal error (mandatory-check honesty)."""
    run_dir = _mk_run(tmp_path)
    _write_bundle(run_dir, "IDEATE.hypothesis-generator.bundle.json", _good_hypotheses())
    _write_bundle(run_dir, "IDEATE.idea-tournament-ranker.bundle.json", _good_tournament_ideas())
    _write_bundle(run_dir, "IDEATE.idea-evolver.bundle.json", _good_evolved())
    _write_bundle(run_dir, "IDEATE.feasibility-reranker.bundle.json", _good_feasibility())
    # inbox/COLLISION.bundle.json never written
    _paths, report = ideate_ring.run_dets(run_dir, "IDEATE", TS)
    assert report["collision_retrieval_grounded"] is False
    assert report["collision_cut"] == 0


# =========================================================================== hash/receipt removal

def test_rewriting_an_upstream_bundle_between_repair_rounds_no_longer_blocks(tmp_path):
    """2026-08-07: `_check_bundle_immutability` (a sha256 fingerprint BLOCK across invocations)
    was removed as part of the director's hash/receipt-completeness-check teardown. Re-running
    IDEATE after an upstream seat's bundle changed must succeed, not raise
    'immutability gate BLOCK' — proving the gate is gone, not merely untested."""
    run_dir = _mk_run(tmp_path)
    _write_good_panel(run_dir)
    first_paths, _first_report = ideate_ring.run_dets(run_dir, "IDEATE", TS)
    assert first_paths

    # Rewrite feasibility-reranker's frozen bundle with different (still valid) bytes — exactly
    # what the old fingerprint gate treated as a BLOCK-worthy tamper.
    feas = _good_feasibility()
    feas["feasibility_ratings"][0]["feasibility"]["compute"] = "high"
    _write_bundle(run_dir, "IDEATE.feasibility-reranker.bundle.json", feas)

    second_paths, second_report = ideate_ring.run_dets(run_dir, "IDEATE", TS)
    assert second_paths
    assert second_report["ranked_ideas"] == 3
    assert not (run_dir / ideate_ring._FINGERPRINT_REL if hasattr(ideate_ring, "_FINGERPRINT_REL")
               else run_dir / "inbox" / "ideate-ring-fingerprints.json").exists()


def test_no_hashlib_import_or_fingerprint_helpers_remain():
    """Structural proof the hash-based gate was torn down, not just skipped in this suite."""
    assert not hasattr(ideate_ring, "hashlib")
    assert not hasattr(ideate_ring, "_check_bundle_immutability")
    assert not hasattr(ideate_ring, "_fingerprint_path")
    assert not hasattr(ideate_ring, "_FINGERPRINT_REL")
    assert not hasattr(ideate_ring, "_IMMUTABLE_SEATS")
