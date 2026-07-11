"""Solution tree — AIDE journal.py port (EXECUTE-stage variant bookkeeping, absorption wave 1).

Experiment variants organized as a scored tree: node = variant artifact + parent + metric + buggy
flag + the action that produced it (draft = new root attempt, debug = fix a buggy node,
improve = refine the current best). The draft/debug/improve POLICY reads the tree to propose the
next bounded attempt — absorbed from WecoAI AIDE's agent policy, stripped of its executor: node
EXECUTION stays behind the director-supervised EXECUTE gate; until live GPU runs, ``metric`` comes
from design-time auditor scores.

Design invariants (mirrors tournament_bracket.py hardening):
  - Pure functions, no I/O / network / LLM / clock; same input -> same output.
  - Immutability: every mutator returns a NEW tree dict; the input is never modified.
  - Fail loud on duplicate node_id / unknown parent / wrong action-parent combination.
  - best_node_id is DERIVED (highest non-null metric among non-buggy nodes; stable tiebreak by
    node_id ASC) — never caller-settable, so a tree can never self-award a winner.
"""
from __future__ import annotations

from typing import List, Optional, Tuple

ACTIONS = ("draft", "debug", "improve")
DEFAULT_MAX_DEBUG_DEPTH = 3


def new_tree(evidence_ref: List[str]) -> dict:
    """An empty solution tree bound to its provenance (evidence_ref minItems:1 — anti-slop)."""
    if not evidence_ref or not all(isinstance(r, str) and r.strip() for r in evidence_ref):
        raise ValueError("new_tree requires a non-empty evidence_ref list (anti-slop binding)")
    return {"nodes": [], "best_node_id": None, "evidence_ref": list(evidence_ref)}


def _derive_best(nodes: List[dict]) -> Optional[str]:
    """Best = highest-metric non-buggy node (stable tiebreak by node_id). CONVENTION: ``metric`` is
    ALWAYS higher-is-better — a lower-is-better objective (loss, HD95, latency) must be stored
    negated by the caller, exactly as tournament_bracket's score_key expects. (Documented rather
    than parameterized: the tree is dict-passed across calls and carries no direction field, and no
    operate mode executes nodes yet — see the absorption-wave-1 build record.)"""
    scored = [n for n in nodes if not n["buggy"] and n["metric"] is not None]
    if not scored:
        return None
    best = sorted(scored, key=lambda n: (-float(n["metric"]), n["node_id"]))[0]
    return best["node_id"]


def add_node(tree: dict, node_id: str, parent_id: Optional[str], action: str,
             artifact_ref: str, metric: Optional[float] = None, buggy: bool = False,
             notes: str = "") -> dict:
    """Return a NEW tree with the node appended (input tree untouched). Fail-loud validation."""
    if not isinstance(node_id, str) or not node_id.strip():
        raise ValueError("add_node: node_id must be a non-empty string")
    if action not in ACTIONS:
        raise ValueError(f"add_node: action must be one of {ACTIONS}, got {action!r}")
    if not isinstance(artifact_ref, str) or not artifact_ref.strip():
        raise ValueError("add_node: artifact_ref must be a non-empty string")
    ids = {n["node_id"] for n in tree["nodes"]}
    if node_id in ids:
        raise ValueError(f"add_node: duplicate node_id {node_id!r} (no node may vanish)")
    if action == "draft":
        if parent_id is not None:
            raise ValueError("add_node: a draft is a new root attempt — parent_id must be None")
    else:
        if parent_id is None or parent_id not in ids:
            raise ValueError(f"add_node: {action} requires an existing parent_id (got {parent_id!r})")
    node = {"node_id": node_id, "parent_id": parent_id, "action": action,
            "artifact_ref": artifact_ref,
            "metric": float(metric) if metric is not None else None,
            "buggy": bool(buggy)}
    if notes:
        node["notes"] = notes
    nodes = [dict(n) for n in tree["nodes"]] + [node]
    return {"nodes": nodes, "best_node_id": _derive_best(nodes),
            "evidence_ref": list(tree["evidence_ref"])}


def score_node(tree: dict, node_id: str, metric: Optional[float], buggy: bool) -> dict:
    """Return a NEW tree with one node's outcome recorded (metric + buggy); best re-derived."""
    if node_id not in {n["node_id"] for n in tree["nodes"]}:
        raise ValueError(f"score_node: unknown node_id {node_id!r}")
    nodes = []
    for n in tree["nodes"]:
        n = dict(n)
        if n["node_id"] == node_id:
            n["metric"] = float(metric) if metric is not None else None
            n["buggy"] = bool(buggy)
        nodes.append(n)
    return {"nodes": nodes, "best_node_id": _derive_best(nodes),
            "evidence_ref": list(tree["evidence_ref"])}


def _node(tree: dict, node_id: str) -> dict:
    return next(n for n in tree["nodes"] if n["node_id"] == node_id)


def debug_depth(tree: dict, node_id: str) -> int:
    """Length of the consecutive-debug chain ending at node_id (the AIDE debug-depth bound)."""
    depth, cur = 0, _node(tree, node_id)
    while cur["action"] == "debug":
        depth += 1
        if cur["parent_id"] is None:
            break
        cur = _node(tree, cur["parent_id"])
    return depth


def _last_open_buggy(tree: dict) -> Optional[dict]:
    """The most recent buggy node nobody has acted on yet (no child), in insertion order."""
    children = {n["parent_id"] for n in tree["nodes"] if n["parent_id"] is not None}
    for n in reversed(tree["nodes"]):
        if n["buggy"] and n["node_id"] not in children:
            return n
    return None


def next_action(tree: dict, max_debug_depth: int = DEFAULT_MAX_DEBUG_DEPTH) -> Tuple[str, Optional[str]]:
    """The AIDE draft/debug/improve policy: what bounded attempt comes next?

    Returns (action, target_node_id):
      - no nodes yet                       -> ("draft", None)
      - an unresolved buggy node exists and its debug chain is under the depth bound
                                            -> ("debug", that node)
      - a scored best exists               -> ("improve", best)
      - otherwise (everything buggy/unscored and debug exhausted)
                                            -> ("draft", None)  (start fresh, never loop forever)
    """
    if not tree["nodes"]:
        return ("draft", None)
    buggy = _last_open_buggy(tree)
    if buggy is not None and debug_depth(tree, buggy["node_id"]) < max_debug_depth:
        return ("debug", buggy["node_id"])
    if tree["best_node_id"] is not None:
        return ("improve", tree["best_node_id"])
    return ("draft", None)
