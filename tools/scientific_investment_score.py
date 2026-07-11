"""Deterministic scientific-investment ranking for strict idea-bet runs.

The independent ranker supplies bounded dimension judgments. This module combines
those judgments with separate tournament, grounding, feasibility, and experiment
readiness signals. It never chooses a bet; it only orders the director's menu.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Iterable, Mapping


POLICY_VERSION = "scientific-investment/v1"

DIMENSION_WEIGHTS = {
    "importance": 0.20,
    "mechanism_coherence": 0.15,
    "novelty_exposure": 0.15,
    "falsifiability": 0.20,
    "information_gain": 0.20,
    "downstream_leverage": 0.10,
}

SIGNAL_WEIGHTS = {
    "scientific_merit": 0.65,
    "tournament_signal": 0.15,
    "feasibility": 0.10,
    "evidence_grounding": 0.05,
    "falsification_readiness": 0.05,
}

_SKETCH_FIELDS = (
    "experiment",
    "baselines",
    "controls",
    "metrics",
    "success_thresholds",
    "failure_thresholds",
    "kill_criteria",
    "execution_order",
    "stages",
)


def _bounded(value: object, low: float = 0.0, high: float = 1.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return low
    return min(high, max(low, number))


def validate_assessments(assessments: Iterable[dict], idea_ids: Iterable[str]) -> list[str]:
    """Validate the strict independent-ranker dimensions for every candidate."""
    by_id = {
        str(row.get("idea_id")): row
        for row in assessments
        if isinstance(row, dict) and row.get("idea_id")
    }
    errors: list[str] = []
    for idea_id in sorted(set(str(x) for x in idea_ids)):
        row = by_id.get(idea_id)
        if row is None:
            errors.append(f"{idea_id}: independent investment assessment missing")
            continue
        scores = row.get("dimension_scores")
        if not isinstance(scores, dict):
            errors.append(f"{idea_id}: dimension_scores must be an object")
            continue
        for dimension in DIMENSION_WEIGHTS:
            value = scores.get(dimension)
            if not isinstance(value, (int, float)) or isinstance(value, bool) or not 1 <= value <= 5:
                errors.append(f"{idea_id}: dimension_scores.{dimension} must be numeric in [1, 5]")
        if not str(row.get("strongest_rejection_case") or "").strip():
            errors.append(f"{idea_id}: strongest_rejection_case is required")
    return errors


def _scientific_merit(assessment: Mapping[str, object]) -> float:
    scores = assessment.get("dimension_scores")
    if not isinstance(scores, Mapping):
        return 0.0
    value = sum(
        DIMENSION_WEIGHTS[name] * ((_bounded(scores.get(name), 1.0, 5.0) - 1.0) / 4.0)
        for name in DIMENSION_WEIGHTS
    )
    return round(value, 4)


def _tournament_signals(tournament: Mapping[str, object]) -> dict[str, float]:
    ratings = [row for row in (tournament.get("ratings") or []) if isinstance(row, dict)]
    values = [float(row["elo"]) for row in ratings if isinstance(row.get("elo"), (int, float))]
    if not values:
        return {}
    low, high = min(values), max(values)
    if high == low:
        return {str(row.get("idea_id")): 0.5 for row in ratings if row.get("idea_id")}
    return {
        str(row.get("idea_id")): round((float(row["elo"]) - low) / (high - low), 4)
        for row in ratings
        if row.get("idea_id") and isinstance(row.get("elo"), (int, float))
    }


def _grounding_signals(grounding: Mapping[str, object]) -> dict[str, float]:
    return {
        str(row.get("idea_id")): _bounded(row.get("soundness"))
        for row in (grounding.get("ideas") or [])
        if isinstance(row, dict) and row.get("idea_id")
    }


def _readiness(sketch: Mapping[str, object]) -> float:
    if not sketch:
        return 0.0
    present = 0
    for field in _SKETCH_FIELDS:
        value = sketch.get(field)
        if isinstance(value, str):
            present += bool(value.strip())
        else:
            present += bool(value)
    return round(present / len(_SKETCH_FIELDS), 4)


def rank_scientific_investments(
    ideas: Iterable[dict],
    *,
    assessments: Iterable[dict],
    tournament: Mapping[str, object] | None = None,
    grounding: Mapping[str, object] | None = None,
    sketches: Iterable[dict] = (),
    novelty_retrieval_grounded: bool = False,
) -> list[dict]:
    """Attach an auditable composite and rank by scientific investment value.

    Missing Elo for a newly evolved idea is neutral rather than punitive. Novelty
    verification changes confidence, not the scientific score: an unverified idea
    remains visible but cannot masquerade as a high-confidence recommendation.
    """
    rows = [deepcopy(row) for row in ideas]
    assessment_by_id = {
        str(row.get("idea_id")): row for row in assessments if isinstance(row, dict)
    }
    sketch_by_id = {
        str(row.get("idea_ref")): row
        for row in sketches
        if isinstance(row, dict) and row.get("idea_ref")
    }
    tournament_by_id = _tournament_signals(tournament or {})
    grounding_by_id = _grounding_signals(grounding or {})

    scored: list[tuple[float, str, dict]] = []
    for row in rows:
        idea_id = str(row.get("idea_id") or "")
        scientific = _scientific_merit(assessment_by_id.get(idea_id, {}))
        signals = {
            "scientific_merit": scientific,
            "tournament_signal": tournament_by_id.get(idea_id, 0.5),
            "feasibility": _bounded((row.get("feasibility") or {}).get("score")),
            "evidence_grounding": grounding_by_id.get(idea_id, 0.0),
            "falsification_readiness": _readiness(sketch_by_id.get(idea_id, {})),
        }
        score = round(sum(SIGNAL_WEIGHTS[key] * value for key, value in signals.items()), 4)
        assessment = assessment_by_id.get(idea_id, {})
        row["scientific_investment"] = {
            "score": score,
            **{key: round(value, 4) for key, value in signals.items()},
            "confidence": "high" if novelty_retrieval_grounded else "provisional",
            "policy_version": POLICY_VERSION,
            "assessment_ref": f"inbox/RANKING.bundle.json#investment_assessments/{idea_id}",
            "strongest_rejection_case": str(assessment.get("strongest_rejection_case") or ""),
        }
        scored.append((-score, idea_id, row))

    scored.sort(key=lambda item: (item[0], item[1]))
    ranked: list[dict] = []
    for rank, (_, _, row) in enumerate(scored, start=1):
        row["rank"] = rank
        ranked.append(row)
    return ranked
