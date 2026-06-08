"""Deterministic core of the idea-tournament-ranker (IDEATE producer).

Runs a round-robin pairwise tournament over a list of research ideas:
every distinct pair plays exactly once (C(N,2) matchups), the winner is
the idea with the higher value at ``score_key``, and the ranking is by
win-count DESC with a stable tiebreak by ``idea_id`` ascending.

Design invariants:
- Pure function: no I/O, no network, no LLM, no time-based nondeterminism.
- Same input -> same output (reproducible ordering via sorted iteration).
- NEVER crashes on a missing score_key — defaults to 0.0 (documented below).
- winner ALWAYS equals pair_a or pair_b — the caller can rely on this guarantee.
- Tiebreak is STABLE: when two ideas have the same score, the one whose
  idea_id is lexicographically SMALLER wins (deterministic, reproducible).
- rank assigned 1..N contiguously, ordered by win-count DESC then idea_id ASC.

score_key default behaviour:
  If an idea dict does not contain the requested score_key, its score is
  treated as 0.0.  This is intentional: a missing signal is the weakest
  possible signal, not an error.  Callers should document what score_key
  they pass (e.g. "score" from the feasibility rubric).
"""
from __future__ import annotations

from itertools import combinations
from typing import List, Optional


# --------------------------------------------------------------------------- #
#  Internal helpers                                                            #
# --------------------------------------------------------------------------- #

def _get_score(idea: dict, score_key: str) -> float:
    """Return the numeric score for *score_key*, defaulting to 0.0 if absent.

    A missing key is treated as 0.0 (weakest possible signal, not an error).
    """
    raw = idea.get(score_key)
    if raw is None:
        return 0.0
    try:
        return float(raw)
    except (TypeError, ValueError):
        return 0.0


def _play_match(idea_a: dict, idea_b: dict, score_key: str) -> str:
    """Determine the winner between two ideas.

    Parameters
    ----------
    idea_a, idea_b:
        Idea dicts, each must have at least an ``idea_id`` key.
    score_key:
        The key whose value is compared. Missing -> 0.0.

    Returns
    -------
    str
        The ``idea_id`` of the winner.  Tiebreak: the lexicographically
        *smaller* ``idea_id`` wins (stable, reproducible).
    """
    score_a = _get_score(idea_a, score_key)
    score_b = _get_score(idea_b, score_key)
    id_a: str = idea_a["idea_id"]
    id_b: str = idea_b["idea_id"]

    if score_a > score_b:
        return id_a
    if score_b > score_a:
        return id_b
    # Tiebreak: lexicographically smaller idea_id wins.
    return id_a if id_a <= id_b else id_b


# --------------------------------------------------------------------------- #
#  Public API                                                                  #
# --------------------------------------------------------------------------- #

def build_bracket(
    ideas: List[dict],
    score_key: str = "score",
    evidence_ref: Optional[List[str]] = None,
) -> dict:
    """Build a complete round-robin pairwise tournament over *ideas*.

    Every distinct pair plays exactly once (C(N,2) matchups).  The winner
    of each matchup is the idea with the higher ``score_key`` value; ties
    are broken by lexicographically smaller ``idea_id`` (stable).

    Parameters
    ----------
    ideas:
        List of idea dicts.  Each must have at least an ``idea_id`` key.
        ``score_key`` is read from each dict; defaults to 0.0 if absent.
    score_key:
        The field name whose numeric value drives the outcome of each
        matchup.  Defaults to ``"score"``.  A missing key → 0.0 (see
        module docstring).
    evidence_ref:
        Optional list of non-empty reference strings to bind as the
        tournament's ``evidence_ref``.  If omitted or empty, the caller
        must bind a non-empty list before the payload passes schema
        validation (the schema requires ``minItems:1``).

    Returns
    -------
    dict
        A payload conforming to ``idea_tournament.schema.json``::

            {
                "matchups": [{"pair_a": ..., "pair_b": ..., "winner": ...}, ...],
                "ranking":  [{"idea_id": ..., "rank": ..., "wins": ...}, ...],
                "evidence_ref": [...],
            }

        Guarantees:
        - ``len(matchups) == C(N,2) == N*(N-1)//2``
        - ``winner`` is always one of ``pair_a`` or ``pair_b``
        - ``ranking`` is sorted by wins DESC, then idea_id ASC
        - ``rank`` is assigned 1..N contiguously

    Raises
    ------
    ValueError
        If *ideas* is empty (no tournament to run).
    """
    if not ideas:
        raise ValueError("build_bracket requires at least one idea")

    # Fail loud on a missing or non-string idea_id (an idea with no identity cannot
    # be ranked — better to raise than to KeyError mid-bracket on an opaque dict).
    ids = [i.get("idea_id") for i in ideas]
    if any(not isinstance(x, str) or not x.strip() for x in ids):
        raise ValueError(
            "build_bracket: every idea must carry a non-empty string idea_id "
            f"(got {ids})"
        )
    # Fail loud on duplicate idea_id: keying win_counts by idea_id would otherwise
    # SILENTLY collapse two ideas into one (an idea vanishes + a degenerate self-match),
    # the same class of bug build_classification was hardened against in M3-a.
    if len(set(ids)) != len(ids):
        dupes = sorted({x for x in ids if ids.count(x) > 1})
        raise ValueError(
            f"build_bracket: duplicate idea_id (ideas must be unique, none may vanish): {dupes}"
        )

    # Sort ideas deterministically before iterating so pair generation is
    # reproducible regardless of the order the caller passes them.
    sorted_ideas = sorted(ideas, key=lambda i: i["idea_id"])

    # --- run matchups -------------------------------------------------------
    win_counts: dict[str, int] = {i["idea_id"]: 0 for i in sorted_ideas}
    matchups: List[dict] = []

    for idea_a, idea_b in combinations(sorted_ideas, 2):
        w = _play_match(idea_a, idea_b, score_key)
        matchups.append({
            "pair_a": idea_a["idea_id"],
            "pair_b": idea_b["idea_id"],
            "winner": w,
        })
        win_counts[w] += 1

    # --- build ranking ------------------------------------------------------
    # Sort: primary = wins DESC (negated for ascending sort), secondary = idea_id ASC.
    ranked_ids = sorted(win_counts.keys(), key=lambda k: (-win_counts[k], k))
    ranking: List[dict] = [
        {"idea_id": iid, "rank": pos, "wins": win_counts[iid]}
        for pos, iid in enumerate(ranked_ids, start=1)
    ]

    return {
        "matchups": matchups,
        "ranking": ranking,
        "evidence_ref": evidence_ref if evidence_ref else [],
    }
