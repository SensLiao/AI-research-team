"""Blind pairwise quality harness for candidate research ideas (deep-ideation REPORT stage).

Scores every candidate idea on DECOMPOSED, auditable quality dimensions derived
deterministically from the run's typed artifacts, and records blind per-dimension
pairwise comparisons. ADVISORY / measurement only.

Design invariants (same as idea_grounding.py and feasibility_score.py):
- Pure function: no I/O, no network, no LLM, no time-based nondeterminism.
- Same input -> same output (fully reproducible).
- Never crashes on absent optional inputs — all None -> documented neutral scores.
- Nothing domain-hardcoded.
- NEVER emits a single collapsed total that could be read as a bet.
- NEVER cuts an idea, NEVER gates a stage (advisory measurement only).
- stability and cost are deliberately OMITTED (require multi-run / budget telemetry).

Six required score dimensions (each in [0.0, 1.0], rounded to 3 decimal places):

depth (RUN-LEVEL, same score for every idea):
    Source: mechanism_graph — treats the graph as a DAG and finds the longest
    directed chain by DFS (stops a path if revisiting a node already on the current
    path to avoid infinite loops). Computes longest_chain_len (number of nodes in
    the longest chain, minimum 1 if no edges), n_nodes, n_edges.
    score = mean([
        min(1, (longest_chain_len - 1) / 4),
        min(1, n_edges / 8),
        min(1, n_nodes / 8),
    ])
    If mechanism_graph is None -> 0.0.

breadth (RUN-LEVEL, same score for every idea):
    Source: mechanism_mappings — counts distinct source_domain strings among
    items whose verdict is in {"PASS", "REPAIR"} (case-sensitive enum check), and
    the total count of shared_mechanisms items across those same entries.
    score = mean([
        min(1, distinct_domains / 3),
        min(1, total_shared / 6),
    ])
    If mechanism_mappings is None or empty, or none pass the verdict filter -> 0.0.

grounding (PER-IDEA):
    If grounding_by_id carries a float for this idea_id -> use it directly.
    Else, parse idea["evidence_ref"] (list of strings): let "real" refs be those
    containing "[[" or at least one ASCII digit. Distinct real refs are deduplicated.
    score = mean([
        len(distinct_real) / max(1, len(refs)),
        min(1, len(distinct_real) / 3),
    ])
    If evidence_ref is absent or empty -> 0.0.
    The grounding_by_id override path (float from idea_grounding_report) takes
    precedence over the local evidence_ref heuristic.

refutation (RUN-LEVEL, same score for every idea):
    Source: contradiction — if n_claims_checked > 0:
        score = min(1, len(conflicts) / 3)
    else:
        score = 0.0
    If contradiction is None -> 0.0.

falsifiability (PER-IDEA):
    1.0 if some experiment_sketch has idea_ref == idea_id AND a non-blank "falsifier".
    0.5 if the idea dict carries a non-blank "falsifiable_prediction".
    0.0 otherwise.

novelty (PER-IDEA):
    Source: collision_verdict.ideas — find the entry whose idea_id matches.
    If entry has cut == True -> 0.0 (regardless of verdict string).
    Else map verdict (case-insensitive) to:
        CLEAR       -> 1.0
        WHITE_SPACE -> 1.0
        ADJACENT    -> 0.6
        UNVERIFIED  -> 0.3
        COLLISION   -> 0.0
    If no matching entry -> 0.3 (same as UNVERIFIED: status unknown).
"""
from __future__ import annotations

from collections import defaultdict
from typing import Dict, List, Optional


# --------------------------------------------------------------------------- #
#  Internal helpers                                                            #
# --------------------------------------------------------------------------- #

_NOVELTY_MAP: Dict[str, float] = {
    "clear": 1.0,
    "white_space": 1.0,
    "adjacent": 0.6,
    "unverified": 0.3,
    "collision": 0.0,
}

_REQUIRED_DIMS = ["depth", "breadth", "grounding", "refutation", "falsifiability", "novelty"]


def _longest_chain(adjacency: Dict[str, List[str]], nodes: List[str]) -> int:
    """DFS longest path in a DAG with cycle avoidance (per-path visited set).

    Returns the number of nodes in the longest path (minimum 1 when no edges lead
    anywhere useful). Treats the graph as a DAG: if a cycle is encountered on the
    current DFS path, that branch is stopped (not globally marked visited).
    """
    if not nodes:
        return 1

    def _dfs(node: str, on_path: set) -> int:
        best = 1
        for nbr in adjacency.get(node, []):
            if nbr not in on_path:
                depth = 1 + _dfs(nbr, on_path | {nbr})
                if depth > best:
                    best = depth
        return best

    best_global = 1
    for n in nodes:
        length = _dfs(n, {n})
        if length > best_global:
            best_global = length
    return best_global


def _score_depth(mechanism_graph: Optional[dict]) -> float:
    """Compute the depth score from a mechanism_graph payload."""
    if mechanism_graph is None:
        return 0.0
    nodes = mechanism_graph.get("nodes") or []
    edges = mechanism_graph.get("edges") or []
    n_nodes = len(nodes)
    n_edges = len(edges)

    # Build adjacency from edges (from_node -> [to_node])
    adjacency: Dict[str, List[str]] = defaultdict(list)
    for edge in edges:
        fn = edge.get("from_node", "")
        tn = edge.get("to_node", "")
        if fn and tn:
            adjacency[fn].append(tn)

    node_ids = [n.get("node_id", "") for n in nodes if n.get("node_id", "")]
    longest = _longest_chain(dict(adjacency), node_ids)

    raw = [
        min(1.0, (longest - 1) / 4.0),
        min(1.0, n_edges / 8.0),
        min(1.0, n_nodes / 8.0),
    ]
    return round(sum(raw) / len(raw), 3)


def _score_breadth(mechanism_mappings: Optional[List[dict]]) -> float:
    """Compute the breadth score from mechanism_mapping payloads."""
    if not mechanism_mappings:
        return 0.0
    passing = [m for m in mechanism_mappings
               if m.get("verdict") in ("PASS", "REPAIR")]
    if not passing:
        return 0.0
    distinct_domains = len({m.get("source_domain", "") for m in passing
                            if m.get("source_domain", "")})
    total_shared = sum(len(m.get("shared_mechanisms") or []) for m in passing)
    raw = [
        min(1.0, distinct_domains / 3.0),
        min(1.0, total_shared / 6.0),
    ]
    return round(sum(raw) / len(raw), 3)


def _score_refutation(contradiction: Optional[dict]) -> float:
    """Compute the refutation score from a contradiction_report payload."""
    if contradiction is None:
        return 0.0
    n_checked = contradiction.get("n_claims_checked", 0)
    if not isinstance(n_checked, (int, float)) or n_checked <= 0:
        return 0.0
    conflicts = contradiction.get("conflicts") or []
    return round(min(1.0, len(conflicts) / 3.0), 3)


def _score_grounding(
    idea: dict,
    grounding_by_id: Optional[Dict[str, float]],
) -> float:
    """Compute the grounding score for one idea."""
    idea_id = idea.get("idea_id", "")
    if grounding_by_id and idea_id in grounding_by_id:
        val = grounding_by_id[idea_id]
        if isinstance(val, (int, float)):
            return round(float(val), 3)
    refs = idea.get("evidence_ref") or []
    if not refs:
        return 0.0
    # "real" refs: contain "[[" or at least one ASCII digit
    def _is_real(r: str) -> bool:
        return "[[" in r or any(c.isdigit() for c in r)

    distinct_real = list({r for r in refs if _is_real(r)})
    raw = [
        len(distinct_real) / max(1, len(refs)),
        min(1.0, len(distinct_real) / 3.0),
    ]
    return round(sum(raw) / len(raw), 3)


def _score_falsifiability(
    idea: dict,
    sketch_by_idea: Dict[str, str],  # idea_id -> falsifier string
) -> float:
    """Compute falsifiability for one idea."""
    idea_id = idea.get("idea_id", "")
    falsifier = sketch_by_idea.get(idea_id, "")
    if falsifier and falsifier.strip():
        return 1.0
    fp = idea.get("falsifiable_prediction", "")
    if fp and str(fp).strip():
        return 0.5
    return 0.0


def _score_novelty(
    idea: dict,
    collision_verdict: Optional[dict],
) -> float:
    """Compute novelty for one idea from the collision_verdict payload."""
    idea_id = idea.get("idea_id", "")
    if collision_verdict is None:
        return 0.3
    ideas_list = collision_verdict.get("ideas") or []
    for entry in ideas_list:
        if entry.get("idea_id") == idea_id:
            if entry.get("cut") is True:
                return 0.0
            verdict_str = str(entry.get("verdict", "")).lower()
            return _NOVELTY_MAP.get(verdict_str, 0.3)
    return 0.3


def _evidence_refs_for(
    idea: dict,
    mechanism_graph: Optional[dict],
    mechanism_mappings: Optional[List[dict]],
    contradiction: Optional[dict],
    experiment_sketches: Optional[List[dict]],
    collision_verdict: Optional[dict],
    grounding_by_id: Optional[Dict[str, float]],
) -> List[str]:
    """Build the non-empty evidence_ref list for one scorecard entry."""
    sources: List[str] = []
    if mechanism_graph is not None:
        sources.append("mechanism_graph")
    if mechanism_mappings is not None:
        sources.append("mechanism_mappings")
    if contradiction is not None:
        sources.append("contradiction_report")
    if experiment_sketches is not None:
        sources.append("experiment_sketches")
    if collision_verdict is not None:
        sources.append("collision_verdict")
    if grounding_by_id and idea.get("idea_id", "") in grounding_by_id:
        sources.append("grounding_by_id")
    # Add any idea-local evidence_ref entries
    idea_refs = idea.get("evidence_ref") or []
    for r in idea_refs:
        if isinstance(r, str) and r.strip() and r not in sources:
            sources.append(r)
    if not sources:
        sources = ["(no artifact inputs — all scores are neutral defaults)"]
    return sources


# --------------------------------------------------------------------------- #
#  Public API                                                                  #
# --------------------------------------------------------------------------- #

def build_quality_eval(
    eval_id: str,
    ideas: list[dict],
    *,
    mechanism_graph: dict | None = None,
    mechanism_mappings: list[dict] | None = None,
    contradiction: dict | None = None,
    experiment_sketches: list[dict] | None = None,
    collision_verdict: dict | None = None,
    grounding_by_id: dict | None = None,
) -> dict:
    """Build an idea_quality_eval payload valid against idea_quality_eval.schema.json.

    Parameters
    ----------
    eval_id:
        Non-blank unique identifier for this eval run (e.g. "QE-001").
    ideas:
        List of idea dicts; each must have at minimum {"idea_id": str}.
        May also carry "evidence_ref" (list[str]) and "falsifiable_prediction" (str).
    mechanism_graph:
        Optional mechanism_graph payload (schema: mechanism_graph.schema.json).
        Used for RUN-LEVEL depth score (same for every idea).
    mechanism_mappings:
        Optional list of mechanism_mapping payloads.
        Used for RUN-LEVEL breadth score.
    contradiction:
        Optional contradiction_report payload {conflicts: list, n_claims_checked: int}.
        Used for RUN-LEVEL refutation score.
    experiment_sketches:
        Optional list of experiment_sketch payloads {idea_ref, falsifier, ...}.
        Used for PER-IDEA falsifiability score.
    collision_verdict:
        Optional novelty_collision_report payload {ideas: [{idea_id, verdict, cut}]}.
        Used for PER-IDEA novelty score.
    grounding_by_id:
        Optional mapping {idea_id: float in [0,1]} from an idea_grounding_report.
        When present and the id matches, used directly as the grounding score;
        overrides the local evidence_ref heuristic for that idea.

    Returns
    -------
    dict
        Payload valid against idea_quality_eval.schema.json with keys:
        eval_id, per_idea[], pairwise[].

    Raises
    ------
    ValueError
        If eval_id is blank or ideas is empty.
    """
    if not (isinstance(eval_id, str) and eval_id.strip()):
        raise ValueError("eval_id must be a non-blank string")
    if not ideas:
        raise ValueError("ideas must be a non-empty list")

    # Pre-compute run-level scores (same for every idea)
    run_depth = _score_depth(mechanism_graph)
    run_breadth = _score_breadth(mechanism_mappings)
    run_refutation = _score_refutation(contradiction)

    # Build sketch lookup: idea_id -> falsifier string (first non-blank match wins)
    sketch_by_idea: Dict[str, str] = {}
    for sketch in (experiment_sketches or []):
        ref = sketch.get("idea_ref", "")
        falsifier = sketch.get("falsifier", "")
        if ref and ref not in sketch_by_idea and falsifier and str(falsifier).strip():
            sketch_by_idea[ref] = str(falsifier)

    per_idea: List[dict] = []
    for idea in ideas:
        idea_id = idea.get("idea_id", "")
        grounding = _score_grounding(idea, grounding_by_id)
        falsifiability = _score_falsifiability(idea, sketch_by_idea)
        novelty = _score_novelty(idea, collision_verdict)

        scores = {
            "depth": run_depth,
            "breadth": run_breadth,
            "grounding": grounding,
            "refutation": run_refutation,
            "falsifiability": falsifiability,
            "novelty": novelty,
        }
        evidence_ref = _evidence_refs_for(
            idea, mechanism_graph, mechanism_mappings, contradiction,
            experiment_sketches, collision_verdict, grounding_by_id,
        )
        per_idea.append({
            "idea_id": idea_id,
            "scores": scores,
            "evidence_ref": evidence_ref,
        })

    # Build pairwise comparisons for every unordered pair, per dimension
    pairwise: List[dict] = []
    sorted_ideas = sorted(per_idea, key=lambda x: x["idea_id"])
    for i in range(len(sorted_ideas)):
        for j in range(i + 1, len(sorted_ideas)):
            a = sorted_ideas[i]
            b = sorted_ideas[j]
            pair_a = a["idea_id"]
            pair_b = b["idea_id"]
            for dim in _REQUIRED_DIMS:
                score_a = a["scores"][dim]
                score_b = b["scores"][dim]
                if score_a - score_b > 1e-9:
                    winner = pair_a
                elif score_b - score_a > 1e-9:
                    winner = pair_b
                else:
                    winner = "tie"
                pairwise.append({
                    "pair_a": pair_a,
                    "pair_b": pair_b,
                    "dimension": dim,
                    "winner": winner,
                })

    return {
        "eval_id": eval_id,
        "per_idea": per_idea,
        "pairwise": pairwise,
    }
