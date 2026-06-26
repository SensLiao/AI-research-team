"""Tests for idea_quality_eval — blind pairwise quality harness (deep-ideation REPORT stage).

Mirrors the style of test_idea_grounding.py: pytest, direct tool import,
schema-validate via validate_payload, explicit adversarial edge cases.
"""
from __future__ import annotations

import pytest

from research_agent_teams.tools.idea_quality_eval import build_quality_eval
from research_agent_teams.tools.validate_artifact import validate_payload

# ---------------------------------------------------------------------------
# Shared fixtures / test data
# ---------------------------------------------------------------------------

IDEA_A = {"idea_id": "IDEA-1", "evidence_ref": ["[[slug-a]]", "2403.12345"]}
IDEA_B = {"idea_id": "IDEA-2", "evidence_ref": ["not-a-real-ref", "also-fake"]}
IDEA_C = {
    "idea_id": "IDEA-3",
    "evidence_ref": ["[[slug-c]]"],
    "falsifiable_prediction": "no gain over baseline",
}


def _make_mechanism_graph(n_nodes: int, chain_len: int) -> dict:
    """Build a simple linear chain graph with n_nodes total (chain_len deep)."""
    nodes = [
        {"node_id": f"N{i}", "label": f"node {i}", "kind": "mechanism",
         "evidence_ref": ["[[ref]]"]}
        for i in range(n_nodes)
    ]
    edges = []
    for i in range(min(chain_len - 1, n_nodes - 1)):
        edges.append({
            "edge_id": f"E{i}",
            "from_node": f"N{i}",
            "to_node": f"N{i + 1}",
            "relation": "causes",
            "evidence_ref": ["[[ref]]"],
        })
    return {
        "graph_id": "MG-001",
        "problem_ref": "PA-001",
        "nodes": nodes,
        "edges": edges,
    }


def _make_mechanism_mappings(domains: list[str], shared_per: int) -> list[dict]:
    """Build a list of PASS mechanism_mapping payloads, one per domain."""
    mappings = []
    for idx, domain in enumerate(domains):
        shared = [
            {"mechanism": f"mech-{i}", "source_evidence_ref": ["[[ref]]"]}
            for i in range(shared_per)
        ]
        mappings.append({
            "mapping_id": f"AM-{idx:03d}",
            "source_domain": domain,
            "target_problem_id": "PA-001",
            "shared_mechanisms": shared,
            "blocking_assumptions": [],
            "required_adaptations": [],
            "overlap_score": 0.5,
            "verdict": "PASS",
        })
    return mappings


def _make_experiment_sketch(idea_id: str, falsifier: str = "no improvement over baseline") -> dict:
    """Build a minimal experiment_sketch payload for the given idea_id."""
    return {
        "sketch_id": f"ES-{idea_id}",
        "idea_ref": idea_id,
        "experiment": "train with the new method on the held-out set",
        "controls": ["frozen-encoder baseline"],
        "metrics": ["Dice score"],
        "observable_signals": ["Dice on test set"],
        "falsifier": falsifier,
    }


def _make_collision_verdict(entries: list[dict]) -> dict:
    """Build a minimal novelty_collision_report payload."""
    return {"ideas": entries}


def _make_contradiction(n_claims: int, n_conflicts: int) -> dict:
    """Build a minimal contradiction_report payload."""
    conflicts = [{"claim_a": f"c{i}", "claim_b": f"d{i}", "kind": "direct_negation"}
                 for i in range(n_conflicts)]
    return {"conflicts": conflicts, "n_claims_checked": n_claims}


# ---------------------------------------------------------------------------
# 1. Happy-path — full call validates against schema
# ---------------------------------------------------------------------------

def test_happy_path_schema_valid():
    """A full call with all optional inputs should produce a schema-valid payload."""
    mg = _make_mechanism_graph(n_nodes=6, chain_len=5)
    mappings = _make_mechanism_mappings(["NLP", "Graph-NN", "RL"], shared_per=3)
    sketches = [_make_experiment_sketch("IDEA-1"), _make_experiment_sketch("IDEA-3")]
    collision = _make_collision_verdict([
        {"idea_id": "IDEA-1", "verdict": "CLEAR", "cut": False,
         "colliding_papers": [], "reason": "no prior art found", "source": "existence_check"},
        {"idea_id": "IDEA-2", "verdict": "ADJACENT", "cut": False,
         "colliding_papers": [], "reason": "tangential", "source": "existence_check"},
        {"idea_id": "IDEA-3", "verdict": "UNVERIFIED", "cut": False,
         "colliding_papers": [], "reason": "offline", "source": "existence_check"},
    ])
    contradiction = _make_contradiction(n_claims=10, n_conflicts=2)
    grounding = {"IDEA-1": 0.9, "IDEA-2": 0.1}

    out = build_quality_eval(
        "QE-001",
        [IDEA_A, IDEA_B, IDEA_C],
        mechanism_graph=mg,
        mechanism_mappings=mappings,
        contradiction=contradiction,
        experiment_sketches=sketches,
        collision_verdict=collision,
        grounding_by_id=grounding,
    )
    errors = validate_payload("idea_quality_eval", out)
    assert errors == [], f"Schema errors: {errors}"
    assert out["eval_id"] == "QE-001"
    assert len(out["per_idea"]) == 3
    # pairwise: 3 ideas × 6 dims = 18 entries
    assert len(out["pairwise"]) == 18


# ---------------------------------------------------------------------------
# 2. Depth: deeper graph -> higher depth score
# ---------------------------------------------------------------------------

def test_depth_deeper_graph_scores_higher():
    shallow = _make_mechanism_graph(n_nodes=2, chain_len=2)
    deep = _make_mechanism_graph(n_nodes=8, chain_len=8)

    idea = [{"idea_id": "X-1"}]
    out_shallow = build_quality_eval("QE-d1", idea, mechanism_graph=shallow)
    out_deep = build_quality_eval("QE-d2", idea, mechanism_graph=deep)

    d_shallow = out_shallow["per_idea"][0]["scores"]["depth"]
    d_deep = out_deep["per_idea"][0]["scores"]["depth"]
    assert d_deep > d_shallow, (
        f"deep graph (chain=8) should score higher than shallow (chain=2): {d_deep} vs {d_shallow}"
    )


def test_depth_none_is_zero():
    out = build_quality_eval("QE-dn", [{"idea_id": "X-1"}], mechanism_graph=None)
    assert out["per_idea"][0]["scores"]["depth"] == 0.0


# ---------------------------------------------------------------------------
# 3. Novelty mapping: CLEAR -> high, COLLISION+cut -> 0.0, missing -> 0.3
# ---------------------------------------------------------------------------

def test_novelty_clear():
    collision = _make_collision_verdict([
        {"idea_id": "IDEA-1", "verdict": "CLEAR", "cut": False,
         "colliding_papers": [], "reason": "no prior art", "source": "existence_check"},
    ])
    out = build_quality_eval("QE-n1", [{"idea_id": "IDEA-1"}], collision_verdict=collision)
    assert out["per_idea"][0]["scores"]["novelty"] == 1.0


def test_novelty_collision_with_cut_is_zero():
    collision = _make_collision_verdict([
        {"idea_id": "IDEA-1", "verdict": "COLLISION", "cut": True,
         "colliding_papers": ["paper-x"], "reason": "duplicate", "source": "existence_check"},
    ])
    out = build_quality_eval("QE-n2", [{"idea_id": "IDEA-1"}], collision_verdict=collision)
    assert out["per_idea"][0]["scores"]["novelty"] == 0.0


def test_novelty_collision_no_cut():
    """COLLISION verdict with cut=False should still map to 0.0 (the verdict, not the cut, drives 0)."""
    collision = _make_collision_verdict([
        {"idea_id": "IDEA-1", "verdict": "COLLISION", "cut": False,
         "colliding_papers": ["paper-x"], "reason": "overlap", "source": "existence_check"},
    ])
    out = build_quality_eval("QE-n3", [{"idea_id": "IDEA-1"}], collision_verdict=collision)
    assert out["per_idea"][0]["scores"]["novelty"] == 0.0


def test_novelty_missing_entry_defaults_to_03():
    """No collision entry for an idea -> same as UNVERIFIED -> 0.3."""
    collision = _make_collision_verdict([
        # entry for a different idea
        {"idea_id": "OTHER", "verdict": "CLEAR", "cut": False,
         "colliding_papers": [], "reason": "ok", "source": "existence_check"},
    ])
    out = build_quality_eval("QE-n4", [{"idea_id": "IDEA-X"}], collision_verdict=collision)
    assert out["per_idea"][0]["scores"]["novelty"] == 0.3


def test_novelty_adjacent():
    collision = _make_collision_verdict([
        {"idea_id": "IDEA-1", "verdict": "ADJACENT", "cut": False,
         "colliding_papers": [], "reason": "nearby", "source": "existence_check"},
    ])
    out = build_quality_eval("QE-n5", [{"idea_id": "IDEA-1"}], collision_verdict=collision)
    assert out["per_idea"][0]["scores"]["novelty"] == 0.6


def test_novelty_case_insensitive():
    collision = _make_collision_verdict([
        {"idea_id": "IDEA-1", "verdict": "White_Space", "cut": False,
         "colliding_papers": [], "reason": "gap", "source": "existence_check"},
    ])
    out = build_quality_eval("QE-n6", [{"idea_id": "IDEA-1"}], collision_verdict=collision)
    assert out["per_idea"][0]["scores"]["novelty"] == 1.0


# ---------------------------------------------------------------------------
# 4. Falsifiability: sketch falsifier -> 1.0; only prediction -> 0.5; neither -> 0.0
# ---------------------------------------------------------------------------

def test_falsifiability_with_sketch():
    sketches = [_make_experiment_sketch("IDEA-1", "no Dice improvement over baseline")]
    out = build_quality_eval("QE-f1", [{"idea_id": "IDEA-1"}], experiment_sketches=sketches)
    assert out["per_idea"][0]["scores"]["falsifiability"] == 1.0


def test_falsifiability_prediction_only():
    idea = {"idea_id": "IDEA-1", "falsifiable_prediction": "p < 0.05 significance"}
    out = build_quality_eval("QE-f2", [idea])
    assert out["per_idea"][0]["scores"]["falsifiability"] == 0.5


def test_falsifiability_neither():
    out = build_quality_eval("QE-f3", [{"idea_id": "IDEA-1"}])
    assert out["per_idea"][0]["scores"]["falsifiability"] == 0.0


def test_falsifiability_blank_sketch_falsifier_falls_back_to_prediction():
    """A sketch with a blank falsifier should not count; fall back to prediction."""
    sketches = [{"sketch_id": "ES-X", "idea_ref": "IDEA-1",
                 "experiment": "run it", "controls": ["baseline"],
                 "metrics": ["Dice"], "observable_signals": ["Dice"],
                 "falsifier": "   "}]
    idea = {"idea_id": "IDEA-1", "falsifiable_prediction": "no improvement"}
    out = build_quality_eval("QE-f4", [idea], experiment_sketches=sketches)
    assert out["per_idea"][0]["scores"]["falsifiability"] == 0.5


# ---------------------------------------------------------------------------
# 5. Pairwise: winner is higher-scoring id; equal scores -> "tie"
# ---------------------------------------------------------------------------

def test_pairwise_winner_is_higher_scoring_id():
    """IDEA-1 has a sketch (falsifiability=1.0), IDEA-2 has only a prediction (0.5)."""
    sketches = [_make_experiment_sketch("IDEA-1")]
    ideas = [
        {"idea_id": "IDEA-1", "falsifiable_prediction": "fp"},
        {"idea_id": "IDEA-2", "falsifiable_prediction": "fp"},
    ]
    out = build_quality_eval("QE-pw1", ideas, experiment_sketches=sketches)
    fw = [p for p in out["pairwise"] if p["dimension"] == "falsifiability"]
    assert len(fw) == 1
    assert fw[0]["pair_a"] == "IDEA-1"
    assert fw[0]["pair_b"] == "IDEA-2"
    assert fw[0]["winner"] == "IDEA-1"


def test_pairwise_equal_scores_tie():
    """Two ideas with identical scores on all dims -> all pairwise winners are 'tie'."""
    ideas = [{"idea_id": "IDEA-1"}, {"idea_id": "IDEA-2"}]
    out = build_quality_eval("QE-pw2", ideas)
    for pw in out["pairwise"]:
        assert pw["winner"] == "tie", f"Expected tie, got {pw['winner']} on {pw['dimension']}"


def test_pairwise_pairs_ordered_lexicographically():
    """pair_a must be lexicographically smaller than pair_b."""
    ideas = [{"idea_id": "IDEA-3"}, {"idea_id": "IDEA-1"}, {"idea_id": "IDEA-2"}]
    out = build_quality_eval("QE-pw3", ideas)
    for pw in out["pairwise"]:
        assert pw["pair_a"] < pw["pair_b"], (
            f"pair_a={pw['pair_a']} should be < pair_b={pw['pair_b']}"
        )


# ---------------------------------------------------------------------------
# 6. Degradation: all optional inputs None -> no crash, correct neutral scores
# ---------------------------------------------------------------------------

def test_degradation_all_optional_none():
    ideas = [{"idea_id": "IDEA-1"}, {"idea_id": "IDEA-2"}]
    out = build_quality_eval("QE-deg", ideas)

    errors = validate_payload("idea_quality_eval", out)
    assert errors == [], f"Schema errors with all-None inputs: {errors}"

    for entry in out["per_idea"]:
        scores = entry["scores"]
        assert scores["depth"] == 0.0,     "depth should be 0.0 with no mechanism_graph"
        assert scores["breadth"] == 0.0,   "breadth should be 0.0 with no mechanism_mappings"
        assert scores["refutation"] == 0.0, "refutation should be 0.0 with no contradiction"
        # grounding: IDEA-1/IDEA-2 have no evidence_ref -> 0.0
        assert scores["grounding"] == 0.0, "grounding should be 0.0 with no evidence_ref"
        # falsifiability: no sketch, no prediction -> 0.0
        assert scores["falsifiability"] == 0.0
        # novelty: no collision_verdict, no entry -> 0.3
        assert scores["novelty"] == 0.3
        # evidence_ref must still be non-empty (schema requires minItems:1)
        assert len(entry["evidence_ref"]) >= 1


# ---------------------------------------------------------------------------
# 7. ValueError on blank eval_id and on empty ideas
# ---------------------------------------------------------------------------

def test_value_error_blank_eval_id():
    with pytest.raises(ValueError, match="eval_id"):
        build_quality_eval("   ", [{"idea_id": "IDEA-1"}])


def test_value_error_empty_eval_id():
    with pytest.raises(ValueError, match="eval_id"):
        build_quality_eval("", [{"idea_id": "IDEA-1"}])


def test_value_error_empty_ideas():
    with pytest.raises(ValueError, match="ideas"):
        build_quality_eval("QE-err", [])


# ---------------------------------------------------------------------------
# 8. Additional coverage: grounding_by_id override takes precedence
# ---------------------------------------------------------------------------

def test_grounding_by_id_overrides_evidence_ref():
    idea = {"idea_id": "IDEA-1", "evidence_ref": []}  # would be 0.0 locally
    out = build_quality_eval("QE-g1", [idea], grounding_by_id={"IDEA-1": 0.85})
    assert out["per_idea"][0]["scores"]["grounding"] == 0.85


def test_grounding_heuristic_real_refs():
    """evidence_ref with [[slug]] and digit refs should increase grounding."""
    idea_good = {"idea_id": "IDEA-1", "evidence_ref": ["[[slug-a]]", "2403.12345", "[[slug-b]]"]}
    idea_poor = {"idea_id": "IDEA-2", "evidence_ref": ["no-digit-no-bracket"]}
    out = build_quality_eval("QE-g2", [idea_good, idea_poor])
    g_good = out["per_idea"][0]["scores"]["grounding"]
    g_poor = out["per_idea"][1]["scores"]["grounding"]
    assert g_good > g_poor


# ---------------------------------------------------------------------------
# 9. Breadth: REJECT mappings do not count; only PASS/REPAIR do
# ---------------------------------------------------------------------------

def test_breadth_reject_mappings_excluded():
    mappings_reject = [
        {"mapping_id": "AM-000", "source_domain": "NLP",
         "target_problem_id": "PA-001",
         "shared_mechanisms": [{"mechanism": "m1", "source_evidence_ref": ["[[r]]"]}],
         "blocking_assumptions": [{"assumption": "x", "why_blocking": "y"}],
         "required_adaptations": [],
         "overlap_score": 0.1, "verdict": "REJECT"},
    ]
    out_reject = build_quality_eval("QE-br1", [{"idea_id": "I-1"}],
                                    mechanism_mappings=mappings_reject)
    out_none = build_quality_eval("QE-br2", [{"idea_id": "I-1"}],
                                  mechanism_mappings=None)
    assert out_reject["per_idea"][0]["scores"]["breadth"] == 0.0
    assert out_none["per_idea"][0]["scores"]["breadth"] == 0.0


def test_breadth_increases_with_more_domains():
    one_domain = _make_mechanism_mappings(["NLP"], shared_per=2)
    three_domains = _make_mechanism_mappings(["NLP", "Graph-NN", "RL"], shared_per=2)
    out1 = build_quality_eval("QE-br3", [{"idea_id": "I-1"}], mechanism_mappings=one_domain)
    out3 = build_quality_eval("QE-br4", [{"idea_id": "I-1"}], mechanism_mappings=three_domains)
    b1 = out1["per_idea"][0]["scores"]["breadth"]
    b3 = out3["per_idea"][0]["scores"]["breadth"]
    assert b3 > b1


# ---------------------------------------------------------------------------
# 10. Refutation score
# ---------------------------------------------------------------------------

def test_refutation_zero_claims_is_zero():
    contr = _make_contradiction(n_claims=0, n_conflicts=5)
    out = build_quality_eval("QE-r1", [{"idea_id": "I-1"}], contradiction=contr)
    assert out["per_idea"][0]["scores"]["refutation"] == 0.0


def test_refutation_saturates_at_three_or_more_conflicts():
    contr = _make_contradiction(n_claims=10, n_conflicts=3)
    out = build_quality_eval("QE-r2", [{"idea_id": "I-1"}], contradiction=contr)
    assert out["per_idea"][0]["scores"]["refutation"] == 1.0


def test_refutation_partial():
    contr = _make_contradiction(n_claims=10, n_conflicts=1)
    out = build_quality_eval("QE-r3", [{"idea_id": "I-1"}], contradiction=contr)
    score = out["per_idea"][0]["scores"]["refutation"]
    assert 0.0 < score < 1.0
