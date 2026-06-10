"""idea_grounding — ScholarEval grounded scoring: score-only, resolved refs, neutral-no-retrieval (wave 1)."""
from __future__ import annotations

import pytest

from research_agent_teams.operate.artifacts import envelope
from research_agent_teams.tools.idea_grounding import (
    DEFAULT_THRESHOLDS,
    score_idea_grounding,
    thresholds_from_profile,
)
from research_agent_teams.tools.novelty_aggregate import aggregate_novelty
from research_agent_teams.tools.validate_artifact import validate_artifact

TS = "2026-06-10T12:00:00Z"
EV = ["inbox/search-results.json"]

RECORDS = [
    {"title": "Skeleton recall loss for thin tubular structures", "doi": "10.1000/skel.1",
     "arxiv_id": "2403.12345"},
    {"title": "A survey of interactive segmentation", "doi": "10.1000/surv.2", "arxiv_id": None},
]

IDEAS = [
    {"idea_id": "IDEA-1",
     "summary": "Skeleton recall loss adapted to interactive 3D canal segmentation",
     "evidence_ref": ["GAP-1", "10.1000/skel.1", "[[kirchhoff-2024-skeleton-recall]]"]},
    {"idea_id": "IDEA-2",
     "summary": "Quantum annealing for cafeteria menu planning",
     "evidence_ref": ["GAP-99", "10.9999/does.not.exist"]},
    {"idea_id": "IDEA-3", "summary": "Entirely novel curriculum for federated tooth models",
     "evidence_ref": ["GAP-1"]},
]


def test_scores_every_idea_and_grounds_refs():
    rep = score_idea_grounding(IDEAS, RECORDS, known_internal_ids={"GAP-1"}, evidence_ref=EV)
    assert [i["idea_id"] for i in rep["ideas"]] == ["IDEA-1", "IDEA-2", "IDEA-3"]   # none dropped
    one, two, three = rep["ideas"]
    assert one["soundness"] == 1.0                       # internal id + matched DOI + slug all resolve
    assert set(one["grounded_refs"]) == set(IDEAS[0]["evidence_ref"])
    assert two["soundness"] == 0.0                       # unknown GAP-99 + unmatched DOI
    assert "soundness" in two.get("below_threshold", [])
    assert three["soundness"] == 1.0 and three["n_neighbors"] == 0
    # IDEA-1 sits near a retrieved neighbor -> lower contribution than the far-out IDEA-2
    assert one["contribution"] < two["contribution"]
    assert one["n_neighbors"] >= 1


def test_no_retrieval_means_neutral_contribution_not_free_novelty():
    rep = score_idea_grounding(IDEAS[:1], [], known_internal_ids={"GAP-1"}, evidence_ref=EV)
    entry = rep["ideas"][0]
    assert entry["contribution"] == 0.5
    assert "no retrieved neighbors" in entry["notes"]


def test_offline_external_refs_are_unresolvable_not_unsupported():
    # Adversarial (reviewer MEDIUM): with zero retrieval, an external DOI ref cannot be checked.
    # That must NOT crater soundness to 0 (cannot-check != unsupported) — the same honest-unknown
    # symmetry contribution already had. The internal GAP-1 still grounds soundness.
    idea_mixed = {"idea_id": "X", "summary": "mixed refs",
                  "evidence_ref": ["GAP-1", "10.1000/only.online"]}
    rep = score_idea_grounding([idea_mixed], [], known_internal_ids={"GAP-1"}, evidence_ref=EV)
    e = rep["ideas"][0]
    assert e["soundness"] == 1.0                       # 1 resolved internal / 1 checkable; external excluded
    assert "unresolvable without retrieval" in e["notes"]
    # all-external + offline -> neutral 0.5, never 0.0
    idea_ext = {"idea_id": "Y", "summary": "external only", "evidence_ref": ["10.1000/a", "10.1000/b"]}
    rep2 = score_idea_grounding([idea_ext], [], evidence_ref=EV)
    assert rep2["ideas"][0]["soundness"] == 0.5


def test_freetext_ref_starting_with_c_is_not_a_fabricated_internal_id():
    # Adversarial (reviewer LOW): "cnn" / "constraint" must route to title matching, not be judged
    # a fabricated internal id (which would score 0). With a matching record they resolve.
    recs = [{"title": "CNN architectures for segmentation", "doi": None, "arxiv_id": None}]
    idea = {"idea_id": "Z", "summary": "uses a cnn", "evidence_ref": ["cnn architectures for segmentation"]}
    rep = score_idea_grounding([idea], recs, evidence_ref=EV)
    assert rep["ideas"][0]["soundness"] == 1.0         # matched a retrieved title, not flagged fabricated


def test_profile_thresholds_annotate_never_cut():
    strict = {"idea_grounding": {"soundness_min": 1.0, "contribution_min": 0.9}}
    rep = score_idea_grounding(IDEAS, RECORDS, known_internal_ids={"GAP-1"},
                               profile=strict, evidence_ref=EV)
    assert len(rep["ideas"]) == 3                        # annotation only — every idea still present
    assert all("below_threshold" in i for i in rep["ideas"][:2])
    assert rep["thresholds"] == {"soundness_min": 1.0, "contribution_min": 0.9}
    assert thresholds_from_profile(None) == DEFAULT_THRESHOLDS


def test_payload_passes_schema():
    rep = score_idea_grounding(IDEAS, RECORDS, known_internal_ids={"GAP-1"}, evidence_ref=EV)
    art = envelope("idea_grounding_report", "idea-grounding", rep, TS)
    assert validate_artifact(art) == []


def test_fail_loud():
    with pytest.raises(ValueError):
        score_idea_grounding([], RECORDS, evidence_ref=EV)
    with pytest.raises(ValueError):
        score_idea_grounding([{"idea_id": " ", "evidence_ref": []}], RECORDS, evidence_ref=EV)
    with pytest.raises(ValueError):
        score_idea_grounding(IDEAS, RECORDS, evidence_ref=[])
    with pytest.raises(ValueError):
        score_idea_grounding([IDEAS[0], dict(IDEAS[1], idea_id="IDEA-1")], RECORDS, evidence_ref=EV)


def test_novelty_aggregate_grounding_injection_is_additive():
    gaps = [{"gap_id": "GAP-1", "gap_type": "coverage_gap", "reason_code": "WHITESPACE",
             "evidence_ref": ["[[a-page]]"]},
            {"gap_id": "GAP-2", "gap_type": "evidence_gap", "reason_code": "UNDER_EVIDENCED",
             "evidence_ref": ["[[b-page]]"]}]
    base = aggregate_novelty(gaps)
    boosted = aggregate_novelty(gaps, signals={"GAP-1": ["no_semantic_neighbor_found"]})
    b1, b2 = boosted["scores"]
    o1, o2 = base["scores"]
    assert "no_semantic_neighbor_found" in b1["derived_from"]
    assert b1["novelty"] > o1["novelty"]                 # one more distinct signal
    assert b2 == o2                                      # untouched gap is byte-identical
    assert aggregate_novelty(gaps, signals=None) == base  # default keeps pre-wave behaviour
