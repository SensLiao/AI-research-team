"""Novelty-collision gate — IDEATE end-to-end (novelty-collision-upgrade 2026-06-18).

Drives ``new_direction.run_dets(run_dir, "IDEATE", ts)`` (the real deterministic IDEATE producer)
with the worker bundles injected into ``inbox/`` and ``_shared.EXISTENCE_TRANSPORT`` faked offline:

  - the COLLISION case: an evidenced collision (a 'verified' paper that did the same method×problem
    AND ran it) CUTS the colliding idea before the /idea-bet menu; survivors reach the backlog; the
    verdict artifact is schema-valid; ``cut_for_prior_art`` surfaces the DEAD entry; and (with a
    project workspace) the cut is appended to the cross-run known-prior-art ledger.
  - the OFFLINE case: no COLLISION bundle -> nothing cut, retrieval_grounded False, and the REPORT
    open_questions loudly warns novelty was NOT verified (mandatory-check honesty, design §4).

The existence checker never touches the network (the faked transport is the single injection point);
the vault is forced unreachable (VAULT_ROOT_OVERRIDE=False) so slug checks degrade to warnings.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from research_agent_teams.operate import spine
from research_agent_teams.operate.modes import _shared, new_direction
from research_agent_teams.tools.project_memory import load_prior_art
from research_agent_teams.tools.validate_artifact import validate_artifact

TS = "2026-06-18T00:00:00Z"

# A fake CrossRef transport: every DOI/title lookup resolves -> citation_existence marks it 'verified'
# (so a colliding paper PASSES the existence fact-check). Offline: no real network is ever touched.
_CROSSREF_OK = json.dumps({"message": {
    "DOI": "10.5555/collide", "title": ["The Colliding Paper"],
    "issued": {"date-parts": [[2024]]}, "container-title": ["Proc."]}}).encode()


def _verify_all(url, headers):
    return _CROSSREF_OK


# --------------------------------------------------------------------------- fixtures (worker bundles)

# Two ideas; the north star vocabulary is shared by both so the drift gate passes (the collision gate,
# not drift, is the thing under test). IDEA-1 will collide; IDEA-2 is clear.
_IDEATE_BUNDLE = {
    "hypotheses": [
        {"hypothesis_id": "IH1", "statement": "A Tversky+boundary loss improves canal segmentation prompts.",
         "falsifiable_prediction": "Dice rises >=2% on fold0 at equal budget.",
         "evidence_needed": ["equal-budget ablation"], "evidence_ref": ["GAP-1"]},
        {"hypothesis_id": "IH2", "statement": "Gated TTA rescues the canal segmentation tail.",
         "falsifiable_prediction": "Worst-decile Dice rises >=5% on the canal segmentation hard cases.",
         "evidence_needed": ["tail study"], "evidence_ref": ["GAP-1"]},
    ],
    "ideas": [
        {"idea_id": "IDEA-1", "summary": "Tversky plus boundary loss on a frozen FM for canal segmentation",
         "evidence_ref": ["IH1", "GAP-1"], "from_hypothesis_ref": "IH1",
         "feasibility": {"compute": "low", "data": "available", "time": "short"}},
        {"idea_id": "IDEA-2", "summary": "Gated test-time adaptation tail-rescue for canal segmentation prompts",
         "evidence_ref": ["IH2", "GAP-1"], "from_hypothesis_ref": "IH2",
         "feasibility": {"compute": "medium", "data": "available", "time": "medium"}},
    ],
    "tournament": [
        {"round": 1, "pair_a": "IDEA-1", "pair_b": "IDEA-2", "winner": "IDEA-2",
         "rationale": "IDEA-2's gated TTA targets the canal segmentation tail more directly than IDEA-1's loss tweak."}
    ],
    "evolved": [],
}

# The independent checker's bundle: IDEA-1 collides with a real (verified) paper that did the same
# method on the same problem AND ran it; IDEA-2 is clear.
_COLLISION_BUNDLE = {
    "findings": [
        {"idea_id": "IDEA-1", "method_combination": "Tversky + boundary loss on a frozen FM",
         "application": "canal segmentation", "domain": "dental CBCT",
         "queries": ["Tversky boundary frozen foundation model canal segmentation"],
         "verdict": "collision",
         "colliding_papers": [
             {"ref": "doi:10.5555/collide", "title": "The Colliding Paper",
              "does_same_method_on_same_problem": True, "experimentally_validated": True,
              "justification": "same loss combo on the same canal task, with experiments",
              "quote": "we train Tversky+boundary on the frozen encoder for canal segmentation"}],
         "confidence": "high", "retrieval_note": "covered arXiv + crossref"},
        {"idea_id": "IDEA-2", "method_combination": "gated TTA", "application": "canal segmentation",
         "domain": "dental CBCT", "queries": ["gated test-time adaptation canal segmentation"],
         "verdict": "clear", "colliding_papers": [], "confidence": "medium",
         "retrieval_note": "no collision found within coverage"},
    ],
    "evidence_ref": ["inbox/COLLISION.bundle.json"],
}

# A DISCOVER gap-classification artifact so IDEATE referential integrity resolves GAP-1.
_GAP_CLASSIFICATION = {
    "gaps": [{"gap_id": "GAP-1", "gap_type": "methodological_gap", "reason_code": "WEAK_LOCUS",
              "statement": "Tversky+boundary loss is underexplored for canal segmentation prompts",
              "evidence_ref": ["GAP-1"], "derived_from": ["weakness_opportunity"]}]
}

_NORTH_STAR = {"statement": "Tversky boundary loss and gated TTA for canal segmentation prompts on a frozen FM",
               "in_scope": ["canal segmentation", "prompts"], "out_of_scope": ["pricing"]}


# --------------------------------------------------------------------------- run scaffolding

def _begin_run(tmp_path, *, project=None):
    """Begin a new_direction run (optionally in a project workspace for the ledger path)."""
    runs = tmp_path / "runs"
    runs.mkdir(exist_ok=True)
    if project:
        # the per-project durable workspace projects/<slug>/notes/ must exist for workspace_for_run.
        (tmp_path / "projects" / project / "notes").mkdir(parents=True, exist_ok=True)
    plan = spine.begin(str(runs), "cg1", "find a canal segmentation direction", "new_direction", TS,
                       north_star=_NORTH_STAR, project=project)
    return Path(plan["run_dir"])


def _seed_discover(run_dir):
    """Write the DISCOVER gap-classification the IDEATE referential-integrity gate reads."""
    d = run_dir / "evidence" / "DISCOVER"
    d.mkdir(parents=True, exist_ok=True)
    art = {"artifact_id": "gap_classification", "artifact_type": "gap_classification",
           "schema_version": "1.0.0", "created_by": "gap-classifier", "created_at": TS,
           "status": "approved", "payload": _GAP_CLASSIFICATION}
    (d / "gap-classification.artifact.json").write_text(json.dumps(art), encoding="utf-8")


def _inject(run_dir, name, bundle):
    inbox = run_dir / "inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    (inbox / name).write_text(json.dumps(bundle), encoding="utf-8")
    if name == "IDEATE.bundle.json" and "memo_contract_version" not in bundle:
        new_direction.write_legacy_replay_receipt(
            str(run_dir), source_run_id="fixture-cg1",
            reason="exercise frozen pre-panel collision compatibility")


@pytest.fixture(autouse=True)
def _offline(monkeypatch):
    """Force the whole gate offline + deterministic: a fake existence transport (verifies every ref)
    and an unreachable vault (slug checks degrade to warnings, never a false block)."""
    monkeypatch.setattr(_shared, "EXISTENCE_TRANSPORT", _verify_all)
    monkeypatch.setattr(_shared, "VAULT_ROOT_OVERRIDE", False)


def _payload(run_dir, stage, name):
    return json.loads((run_dir / "evidence" / stage / name).read_text(encoding="utf-8"))["payload"]


# --------------------------------------------------------------------------- 1. collision case (cut)

def test_colliding_idea_is_cut_from_the_menu_and_survivors_remain(tmp_path):
    run_dir = _begin_run(tmp_path)
    _seed_discover(run_dir)
    _inject(run_dir, "IDEATE.bundle.json", _IDEATE_BUNDLE)
    _inject(run_dir, "COLLISION.bundle.json", _COLLISION_BUNDLE)

    paths, report = new_direction.run_dets(run_dir, "IDEATE", TS)

    # the colliding idea is GONE from the ranked /idea-bet menu; the clear one survives.
    backlog = _payload(run_dir, "IDEATE", "idea-backlog.artifact.json")
    ranked_ids = [i["idea_id"] for i in backlog["ranked_ideas"]]
    assert "IDEA-1" not in ranked_ids
    assert "IDEA-2" in ranked_ids
    # the report counters reflect exactly one evidenced cut.
    assert report["collision_cut"] == 1
    assert report["collision_retrieval_grounded"] is True


def test_collision_verdict_artifact_is_written_and_schema_valid(tmp_path):
    run_dir = _begin_run(tmp_path)
    _seed_discover(run_dir)
    _inject(run_dir, "IDEATE.bundle.json", _IDEATE_BUNDLE)
    _inject(run_dir, "COLLISION.bundle.json", _COLLISION_BUNDLE)

    new_direction.run_dets(run_dir, "IDEATE", TS)

    p = run_dir / "evidence" / "IDEATE" / "novelty-collision-verdict.artifact.json"
    assert p.exists()
    art = json.loads(p.read_text(encoding="utf-8"))
    assert validate_artifact(art) == []                  # schema_version envelope + payload contract
    payload = art["payload"]
    assert payload["cut_ids"] == ["IDEA-1"]
    assert payload["survivors"] == ["IDEA-2"]
    assert payload["retrieval_grounded"] is True
    dead = next(e for e in payload["ideas"] if e["idea_id"] == "IDEA-1")
    assert dead["verdict"] == "DEAD" and dead["cut"] is True
    assert dead["colliding_papers"][0]["existence"] == "verified"


def test_cut_for_prior_art_surfaces_the_dead_entry(tmp_path):
    run_dir = _begin_run(tmp_path)
    _seed_discover(run_dir)
    _inject(run_dir, "IDEATE.bundle.json", _IDEATE_BUNDLE)
    _inject(run_dir, "COLLISION.bundle.json", _COLLISION_BUNDLE)

    new_direction.run_dets(run_dir, "IDEATE", TS)

    cut = new_direction.cut_for_prior_art(run_dir)
    assert [c["idea_id"] for c in cut] == ["IDEA-1"]
    assert cut[0]["verdict"] == "DEAD"
    assert cut[0]["source"] == "worker"
    assert cut[0]["colliding_papers"]            # the evidence travels with the cut (not hidden)


def test_dead_cut_is_appended_to_the_cross_run_prior_art_ledger(tmp_path):
    run_dir = _begin_run(tmp_path, project="proj-canal")
    _seed_discover(run_dir)
    _inject(run_dir, "IDEATE.bundle.json", _IDEATE_BUNDLE)
    _inject(run_dir, "COLLISION.bundle.json", _COLLISION_BUNDLE)

    new_direction.run_dets(run_dir, "IDEATE", TS)

    ws = tmp_path / "projects" / "proj-canal"
    rows = load_prior_art(ws)
    assert len(rows) == 1                                 # the one DEAD idea is recorded for future runs
    row = rows[0]
    assert row["idea_id"] == "IDEA-1"
    assert row["verdict"] == "DEAD"
    assert "doi:10.5555/collide" in row["colliding_refs"]
    assert row["experimentally_validated"] is True


# --------------------------------------------------------------------------- 2. offline case (nothing cut)

def test_offline_no_collision_bundle_cuts_nothing_and_flags_unverified(tmp_path):
    run_dir = _begin_run(tmp_path)
    _seed_discover(run_dir)
    _inject(run_dir, "IDEATE.bundle.json", _IDEATE_BUNDLE)
    # deliberately NO COLLISION.bundle.json -> the gate cannot confirm a collision.

    paths, report = new_direction.run_dets(run_dir, "IDEATE", TS)

    # nothing cut: BOTH ideas survive to the menu.
    backlog = _payload(run_dir, "IDEATE", "idea-backlog.artifact.json")
    ranked_ids = {i["idea_id"] for i in backlog["ranked_ideas"]}
    assert ranked_ids == {"IDEA-1", "IDEA-2"}
    assert report["collision_cut"] == 0
    assert report["collision_retrieval_grounded"] is False

    # the verdict marks every idea UNVERIFIED and retrieval_grounded False.
    payload = _payload(run_dir, "IDEATE", "novelty-collision-verdict.artifact.json")
    assert payload["retrieval_grounded"] is False
    assert payload["cut_ids"] == []
    assert all(e["verdict"] == "UNVERIFIED" for e in payload["ideas"])


def test_offline_report_open_questions_warns_novelty_not_verified(tmp_path):
    run_dir = _begin_run(tmp_path)
    _seed_discover(run_dir)
    _inject(run_dir, "IDEATE.bundle.json", _IDEATE_BUNDLE)
    new_direction.run_dets(run_dir, "IDEATE", TS)        # IDEATE writes the collision verdict

    # the REPORT stage reads the verdict and must loudly tell the director novelty was NOT verified.
    new_direction.run_dets(run_dir, "REPORT", TS)
    note = _payload(run_dir, "REPORT", "report-note.artifact.json")
    assert any("novelty was NOT verified" in q for q in note["open_questions"])


def test_offline_cut_for_prior_art_is_empty(tmp_path):
    run_dir = _begin_run(tmp_path)
    _seed_discover(run_dir)
    _inject(run_dir, "IDEATE.bundle.json", _IDEATE_BUNDLE)
    new_direction.run_dets(run_dir, "IDEATE", TS)
    assert new_direction.cut_for_prior_art(run_dir) == []   # nothing was cut offline
