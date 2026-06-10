"""solution_tree — AIDE journal port: invariants, derived best, draft/debug/improve policy (wave 1)."""
from __future__ import annotations

import pytest

from research_agent_teams.operate.artifacts import envelope
from research_agent_teams.tools.solution_tree import (
    add_node,
    debug_depth,
    new_tree,
    next_action,
    score_node,
)
from research_agent_teams.tools.validate_artifact import validate_artifact

TS = "2026-06-10T12:00:00Z"
EV = ["experiment-matrix.artifact.json"]


def test_new_tree_requires_evidence_ref():
    with pytest.raises(ValueError):
        new_tree([])
    with pytest.raises(ValueError):
        new_tree(["  "])
    t = new_tree(EV)
    assert t["nodes"] == [] and t["best_node_id"] is None


def test_add_node_validation_and_immutability():
    t0 = new_tree(EV)
    t1 = add_node(t0, "n1", None, "draft", "variant-1.json")
    assert t0["nodes"] == []                                  # input untouched (immutability)
    with pytest.raises(ValueError):
        add_node(t1, "n1", None, "draft", "x.json")           # duplicate id
    with pytest.raises(ValueError):
        add_node(t1, "n2", "n1", "draft", "x.json")           # draft must be a root
    with pytest.raises(ValueError):
        add_node(t1, "n2", None, "debug", "x.json")           # debug needs a parent
    with pytest.raises(ValueError):
        add_node(t1, "n2", "ghost", "improve", "x.json")      # unknown parent
    with pytest.raises(ValueError):
        add_node(t1, "n2", "n1", "mutate", "x.json")          # unknown action


def test_best_is_derived_never_self_awarded():
    t = new_tree(EV)
    t = add_node(t, "a", None, "draft", "a.json", metric=0.7)
    t = add_node(t, "b", None, "draft", "b.json", metric=0.9, buggy=True)   # buggy never wins
    t = add_node(t, "c", "a", "improve", "c.json", metric=0.8)
    assert t["best_node_id"] == "c"
    t = score_node(t, "c", metric=None, buggy=True)            # c turns out broken
    assert t["best_node_id"] == "a"
    t2 = add_node(t, "d", "a", "improve", "d.json", metric=0.7)
    assert t2["best_node_id"] == "a"                           # tie -> lexicographically smaller id


def test_policy_draft_debug_improve_cycle():
    t = new_tree(EV)
    assert next_action(t) == ("draft", None)
    t = add_node(t, "n1", None, "draft", "v1.json", buggy=True)
    assert next_action(t) == ("debug", "n1")
    t = add_node(t, "n2", "n1", "debug", "v2.json", buggy=True)
    t = add_node(t, "n3", "n2", "debug", "v3.json", buggy=True)
    t = add_node(t, "n4", "n3", "debug", "v4.json", buggy=True)
    assert debug_depth(t, "n4") == 3       # consecutive-debug chain n2 -> n3 -> n4
    assert next_action(t, max_debug_depth=3) == ("draft", None)   # debug chain exhausted -> fresh draft
    t = add_node(t, "n5", None, "draft", "v5.json", metric=0.6)
    assert next_action(t, max_debug_depth=3) == ("improve", "n5")


def test_payload_passes_schema():
    t = new_tree(EV)
    t = add_node(t, "n1", None, "draft", "v1.json", metric=0.5, notes="first try")
    art = envelope("solution_tree", "experiment-journaler", t, TS)
    assert validate_artifact(art) == []
    bad = dict(t, nodes=[dict(t["nodes"][0], action="explode")])
    assert validate_artifact(envelope("solution_tree", "experiment-journaler", bad, TS)) != []
