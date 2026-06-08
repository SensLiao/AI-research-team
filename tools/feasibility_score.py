"""Deterministic core of the feasibility-reranker (IDEATE producer).

Scores and ranks research ideas by feasibility using a rubric over declared
compute/data/time signals vs an optional budget from task_frame.payload.budget.

Design invariants:
- Pure function: no I/O, no network, no LLM, no time-based nondeterminism.
- Same input -> same output (reproducible ordering).
- Never crashes on absent budget or absent signals — neutral fallback documented below.
- Nothing domain-hardcoded: all thresholds are relative to declared signals or budget.
- Stable tiebreak: ideas with equal score are ordered by idea_id ascending (lexicographic),
  so the ranking is fully deterministic even with equal scores.

Feasibility rubric (three additive sub-scores, each in [0.0, 1.0]):
  1. Compute feasibility (weight 1/3):
     - Signal source: idea["feasibility"]["compute"] if present, else 1.0 (neutral).
     - Mapping: "low" or numbers <= 1 -> 1.0; "medium" or (1, 3] -> 0.6;
       "high" or > 3 -> 0.2; unrecognised string -> 0.5 (neutral).
     - Budget modulation: if budget.max_gpu_runs_before_review is present and
       numeric, ideas declaring compute > that threshold are penalised by 0.2
       (floor 0.0). Absent budget -> no modulation.
  2. Data feasibility (weight 1/3):
     - Signal source: idea["feasibility"]["data"] if present, else 1.0 (neutral).
     - Mapping: "available" or "public" -> 1.0; "restricted" or "limited" -> 0.5;
       "unavailable" or "none" -> 0.1; numeric in [0,1] -> the value directly;
       unrecognised string -> 0.5 (neutral).
  3. Time feasibility (weight 1/3):
     - Signal source: idea["feasibility"]["time"] if present, else 1.0 (neutral).
     - Mapping: "short" or numbers <= 1 -> 1.0; "medium" or (1, 6] -> 0.6;
       "long" or > 6 -> 0.2; unrecognised string -> 0.5 (neutral).

Final score = mean(compute_score, data_score, time_score) rounded to 4 decimal places.
Absent feasibility object on the idea -> all three sub-scores neutral -> final score 0.6667.
"""
from __future__ import annotations

from typing import List, Optional


# --------------------------------------------------------------------------- #
#  Internal signal-mapping helpers                                             #
# --------------------------------------------------------------------------- #

def _compute_signal(value: Optional[object]) -> float:
    """Map compute signal to [0, 1]. Neutral fallback: 1.0."""
    if value is None:
        return 1.0
    if isinstance(value, bool):
        return 1.0
    if isinstance(value, (int, float)):
        v = float(value)
        if v <= 1.0:
            return 1.0
        if v <= 3.0:
            return 0.6
        return 0.2
    s = str(value).strip().lower()
    if s in ("low",):
        return 1.0
    if s in ("medium", "moderate"):
        return 0.6
    if s in ("high", "very high", "extreme"):
        return 0.2
    return 0.5  # unrecognised -> neutral


def _data_signal(value: Optional[object]) -> float:
    """Map data-availability signal to [0, 1]. Neutral fallback: 1.0."""
    if value is None:
        return 1.0
    if isinstance(value, bool):
        return 1.0
    if isinstance(value, (int, float)):
        v = float(value)
        return max(0.0, min(1.0, v))
    s = str(value).strip().lower()
    if s in ("available", "public", "open", "yes"):
        return 1.0
    if s in ("restricted", "limited", "partial"):
        return 0.5
    if s in ("unavailable", "none", "no", "missing"):
        return 0.1
    return 0.5  # unrecognised -> neutral


def _time_signal(value: Optional[object]) -> float:
    """Map time-to-result signal to [0, 1]. Neutral fallback: 1.0."""
    if value is None:
        return 1.0
    if isinstance(value, bool):
        return 1.0
    if isinstance(value, (int, float)):
        v = float(value)
        if v <= 1.0:
            return 1.0
        if v <= 6.0:
            return 0.6
        return 0.2
    s = str(value).strip().lower()
    if s in ("short", "fast", "quick"):
        return 1.0
    if s in ("medium", "moderate"):
        return 0.6
    if s in ("long", "slow", "extended"):
        return 0.2
    return 0.5  # unrecognised -> neutral


def _budget_compute_ceiling(budget: Optional[dict]) -> Optional[float]:
    """Extract the GPU-run ceiling from the task_frame budget, if declared."""
    if budget is None:
        return None
    try:
        val = budget.get("max_gpu_runs_before_review")
        if val is not None:
            return float(val)
    except (TypeError, ValueError):
        pass
    return None


# --------------------------------------------------------------------------- #
#  Public API                                                                  #
# --------------------------------------------------------------------------- #

def score_feasibility(
    idea: dict,
    budget: Optional[dict] = None,
    profile: Optional[dict] = None,
) -> dict:
    """Compute a feasibility object for one idea.

    Parameters
    ----------
    idea:
        One idea dict (may or may not have a ``feasibility`` sub-object with
        compute/data/time signals; missing signals default to neutral 1.0).
    budget:
        Optional budget dict from ``task_frame.payload.budget``.  When absent,
        no budget modulation is applied.
    profile:
        Optional domain profile.  Currently unused in the rubric but accepted
        for forward-compatibility — never crashes if provided.

    Returns
    -------
    dict
        A ``feasibility`` object conforming to the idea_backlog schema:
        ``{"score": float, "compute": ..., "data": ..., "time": ...}``.
    """
    feas = idea.get("feasibility") or {}
    raw_compute = feas.get("compute", None)
    raw_data = feas.get("data", None)
    raw_time = feas.get("time", None)

    c_score = _compute_signal(raw_compute)
    d_score = _data_signal(raw_data)
    t_score = _time_signal(raw_time)

    # Budget modulation: penalise compute-heavy ideas when a GPU ceiling exists.
    ceiling = _budget_compute_ceiling(budget)
    if ceiling is not None and isinstance(raw_compute, (int, float)):
        if float(raw_compute) > ceiling:
            c_score = max(0.0, c_score - 0.2)

    final_score = round((c_score + d_score + t_score) / 3.0, 4)

    return {
        "score": final_score,
        "compute": raw_compute,
        "data": raw_data,
        "time": raw_time,
    }


def rank_ideas(
    ideas: List[dict],
    budget: Optional[dict] = None,
    profile: Optional[dict] = None,
) -> List[dict]:
    """Score and rank ideas by feasibility DESC with a stable tiebreak.

    Parameters
    ----------
    ideas:
        List of idea dicts (each may have partial or missing ``feasibility``
        sub-objects — handled gracefully by score_feasibility).
    budget:
        Optional budget from task_frame.
    profile:
        Optional domain profile (forwarded to score_feasibility).

    Returns
    -------
    list[dict]
        A new list of idea dicts (deep-copied structure) with ``feasibility``
        replaced by the scored dict and ``rank`` assigned 1..N contiguously.
        Sorted: highest score first; equal scores broken by ``idea_id``
        ascending (lexicographic) — stable and reproducible.
    """
    scored: List[tuple[float, str, dict]] = []
    for idea in ideas:
        feas_obj = score_feasibility(idea, budget=budget, profile=profile)
        idea_copy = dict(idea)
        idea_copy["feasibility"] = feas_obj
        scored.append((-feas_obj["score"], idea_copy.get("idea_id", ""), idea_copy))

    # Sort: primary key = score DESC (negated); secondary key = idea_id ASC (stable tiebreak)
    scored.sort(key=lambda t: (t[0], t[1]))

    ranked: List[dict] = []
    for rank_num, (_, _, idea_copy) in enumerate(scored, start=1):
        idea_copy["rank"] = rank_num
        ranked.append(idea_copy)

    return ranked


def build_idea_backlog(
    ideas: List[dict],
    budget: Optional[dict] = None,
    profile: Optional[dict] = None,
) -> dict:
    """Assemble a complete idea_backlog payload deterministically.

    Parameters
    ----------
    ideas:
        Raw idea dicts from the hypothesis-generator / feasibility-reranker.
    budget:
        Optional budget for compute modulation.
    profile:
        Optional domain profile.

    Returns
    -------
    dict
        A payload conforming to idea_backlog.schema.json.
    """
    ranked = rank_ideas(ideas, budget=budget, profile=profile)
    return {"ranked_ideas": ranked}
