"""idea_dedup — 0.8-similarity clustering with provenance, lexical + injected-embedding paths (wave 1)."""
from __future__ import annotations

import pytest

from research_agent_teams.tools.idea_dedup import (
    dedupe_ideas,
    lexical_similarity,
    similarity,
)


def idea(iid, summary):
    return {"idea_id": iid, "summary": summary}


def test_near_duplicates_merge_with_provenance():
    ideas = [
        idea("IDEA-1", "LoRA-adapt SAM3 with click-side text prompts for 3D canal segmentation"),
        idea("IDEA-2", "Adapt SAM3 with LoRA using click side text prompts for 3D canal segmentation"),
        idea("IDEA-3", "A skeleton-recall loss term for thin tubular continuity"),
    ]
    out = dedupe_ideas(ideas)
    kept_ids = [k["idea_id"] for k in out["kept"]]
    assert kept_ids == ["IDEA-1", "IDEA-3"]                      # lowest id represents the cluster
    assert out["merged"] == [{"kept_id": "IDEA-1", "merged_ids": ["IDEA-2"],
                              "max_similarity": out["merged"][0]["max_similarity"]}]
    assert out["merged"][0]["max_similarity"] >= 0.8
    # no idea vanishes: every id is in kept or exactly one merged_ids
    all_ids = set(kept_ids) | {m for e in out["merged"] for m in e["merged_ids"]}
    assert all_ids == {"IDEA-1", "IDEA-2", "IDEA-3"}


def test_distinct_ideas_all_kept():
    ideas = [idea("A", "Curriculum pacing for federated distillation"),
             idea("B", "Topology-aware augmentation for vessel trees"),
             idea("C", "Replay-free continual learning via gradient sketches")]
    out = dedupe_ideas(ideas)
    assert [k["idea_id"] for k in out["kept"]] == ["A", "B", "C"] and out["merged"] == []


def test_empty_summaries_never_vacuously_merge():
    assert lexical_similarity("", "") == 0.0
    out = dedupe_ideas([idea("A", ""), idea("B", "")])
    assert len(out["kept"]) == 2 and out["merged"] == []


def test_fail_loud_on_bad_input():
    with pytest.raises(ValueError):
        dedupe_ideas([idea("A", "x"), idea("A", "y")])           # duplicate id
    with pytest.raises(ValueError):
        dedupe_ideas([{"idea_id": "  ", "summary": "x"}])        # blank id
    with pytest.raises(ValueError):
        dedupe_ideas([idea("A", "x")], threshold=0.0)            # bad threshold


def test_injected_embedder_replaces_lexical():
    # a fake embedder that maps both phrasings to the same vector (cosine 1.0)
    table = {"phrase one": (1.0, 0.0), "totally different wording": (1.0, 0.0),
             "orthogonal idea": (0.0, 1.0)}

    def embed(text):
        return table[text]

    assert similarity("phrase one", "totally different wording", embed_fn=embed) == 1.0
    out = dedupe_ideas([idea("A", "phrase one"), idea("B", "totally different wording"),
                        idea("C", "orthogonal idea")], embed_fn=embed)
    assert [k["idea_id"] for k in out["kept"]] == ["A", "C"]
    assert out["merged"][0]["merged_ids"] == ["B"]
    # lexical fallback would NOT have merged these two phrasings
    assert lexical_similarity("phrase one", "totally different wording") < 0.8


def test_input_ideas_not_mutated():
    ideas = [idea("A", "alpha"), idea("B", "alpha")]
    dedupe_ideas(ideas)
    assert ideas[0] == {"idea_id": "A", "summary": "alpha"}
