"""Deterministic evidence-saturation meter for the evidence-saturation-judge.

Answers the question the machine never used to ask: *have we searched enough?*
Given a per-round search history (how many NEW unique sources each round surfaced),
it computes whether a literature/evidence search has SATURATED (diminishing new
results) or still NEEDS MORE queries — mechanically, with documented thresholds.

This is the measurable replacement for lit-scout's single self-asserted
``saturation_reached`` boolean: instead of one vibe-flag, the search history is read
as a saturation curve and a verdict is *derived*.

----------------------------------------------------------------------------------
The math (pure, reproducible — no network / clock / random):

Each round i records ``new_unique_sources`` (the dedup'd count of sources first seen
in round i) and ``cumulative_unique_sources`` (running total through round i).

  marginal new-result rate of round i:
      rate_i = new_unique_i / cumulative_i          (cumulative_i includes new_unique_i)
      rate_i = 0.0 when cumulative_i == 0            (a round that found nothing)
  -> "what fraction of everything known so far did THIS round add."
     The first non-empty round has rate 1.0 (everything is new); as a search saturates
     the marginal rate decays toward 0.

  new_result_rate_last_round = rate of the final round (0.0 when no rounds).

  duplicate_rate (cumulative overlap across the whole history):
      total_surfaced  = sum(new_unique_i) + redundant_resurfacing
  Only ``new_unique`` is recorded per round (not raw hits), so the deterministic,
  data-available reading of overlap is the SHRINK of the marginal rate: how much of
  the search effort (rounds beyond the first discovery) stopped producing new uniques.
      duplicate_rate = 1 - (mean marginal new-result rate across all rounds)
  0.0 = every round added at its full marginal rate (no diminishing return yet);
  toward 1.0 = later rounds re-tread known ground (the saturation signature).

  saturation_score = 1 - new_result_rate_last_round   (1.0 = fully saturated).

Verdict (documented thresholds, all named constants below):
  - INSUFFICIENT_DATA  when fewer than MIN_ROUNDS_TO_JUDGE rounds exist
                       (too little history to decide — NEVER a silent cut).
  - SATURATED          when the new-result rate of the last
                       SATURATION_WINDOW_ROUNDS rounds each stayed at/below
                       SATURATION_RATE_THRESHOLD (diminishing new results held).
  - NOT_SATURATED      otherwise (still finding fresh material — widen / keep going).

A SCORE/RATE never on its own terminates a search: when history is too thin the meter
returns INSUFFICIENT_DATA, not a false SATURATED.
"""
from __future__ import annotations

from typing import Dict, List, Optional

# --- Verdict thresholds (named, deterministic — the documented saturation rule) ---

# Minimum number of rounds before a SATURATED / NOT_SATURATED call can be made.
# Below this we emit INSUFFICIENT_DATA (never a silent termination).
MIN_ROUNDS_TO_JUDGE: int = 2

# How many trailing rounds must ALL be at/below the rate threshold to call SATURATED.
SATURATION_WINDOW_ROUNDS: int = 2

# Marginal new-result rate at/below which a round counts as "no meaningful new yield".
# 0.10 => a round that grew the known set by <=10% is treated as saturated.
SATURATION_RATE_THRESHOLD: float = 0.10

# Rounding precision for reported floats (matches the project's deterministic tools).
_PRECISION: int = 6


def _marginal_rate(new_unique: int, cumulative: int) -> float:
    """Marginal new-result rate of a single round.

    rate = new_unique / cumulative  (cumulative already includes new_unique).
    Returns 0.0 when cumulative is 0 (a round that surfaced nothing).
    Clamped to [0, 1].
    """
    if cumulative <= 0:
        return 0.0
    rate = new_unique / cumulative
    if rate < 0.0:
        return 0.0
    if rate > 1.0:
        return 1.0
    return rate


def _round_rates(rounds: List[dict]) -> List[float]:
    """Per-round marginal new-result rates, in input order."""
    return [
        _marginal_rate(
            int(r.get("new_unique_sources", 0)),
            int(r.get("cumulative_unique_sources", 0)),
        )
        for r in rounds
    ]


def new_result_rate_last_round(rounds: List[dict]) -> float:
    """Marginal new-result rate of the final round (0.0 when there are no rounds)."""
    if not rounds:
        return 0.0
    return round(_round_rates(rounds)[-1], _PRECISION)


def duplicate_rate(rounds: List[dict]) -> float:
    """Cumulative duplicate/overlap rate across the whole history, in [0, 1].

    Defined as ``1 - mean(marginal new-result rate)`` over all rounds: when every
    round adds at its full marginal rate the search has no diminishing return yet
    (duplicate_rate -> 0); as later rounds re-tread known ground the mean marginal
    rate shrinks and duplicate_rate -> 1. Returns 0.0 for an empty history.
    """
    if not rounds:
        return 0.0
    rates = _round_rates(rounds)
    mean_rate = sum(rates) / len(rates)
    dup = 1.0 - mean_rate
    if dup < 0.0:
        dup = 0.0
    if dup > 1.0:
        dup = 1.0
    return round(dup, _PRECISION)


def saturation_score(rounds: List[dict]) -> float:
    """Saturation index in [0, 1]: 1.0 = fully saturated, 0.0 = wide open.

    saturation_score = 1 - new_result_rate_last_round.
    """
    score = 1.0 - new_result_rate_last_round(rounds)
    if score < 0.0:
        score = 0.0
    if score > 1.0:
        score = 1.0
    return round(score, _PRECISION)


def decide_verdict(rounds: List[dict]) -> str:
    """Derive the saturation verdict from the documented thresholds.

    Returns one of "SATURATED", "NOT_SATURATED", "INSUFFICIENT_DATA".

    - INSUFFICIENT_DATA when fewer than MIN_ROUNDS_TO_JUDGE rounds exist.
    - SATURATED when each of the last SATURATION_WINDOW_ROUNDS rounds has a marginal
      new-result rate at/below SATURATION_RATE_THRESHOLD.
    - NOT_SATURATED otherwise.
    """
    if len(rounds) < MIN_ROUNDS_TO_JUDGE:
        return "INSUFFICIENT_DATA"

    rates = _round_rates(rounds)
    window = rates[-SATURATION_WINDOW_ROUNDS:]
    if all(rate <= SATURATION_RATE_THRESHOLD for rate in window):
        return "SATURATED"
    return "NOT_SATURATED"


def _default_rationale(verdict: str, last_rate: float, n_rounds: int) -> str:
    """Human-readable one-liner for the verdict (the judge may override)."""
    if verdict == "INSUFFICIENT_DATA":
        return (
            f"Only {n_rounds} round(s) of search history; need >= {MIN_ROUNDS_TO_JUDGE} "
            f"to judge saturation. No cut made."
        )
    if verdict == "SATURATED":
        return (
            f"Last {SATURATION_WINDOW_ROUNDS} round(s) each added <= "
            f"{SATURATION_RATE_THRESHOLD:.0%} new uniques (final-round rate "
            f"{last_rate:.1%}); search has saturated."
        )
    return (
        f"Final-round new-result rate {last_rate:.1%} exceeds the "
        f"{SATURATION_RATE_THRESHOLD:.0%} threshold; still finding fresh material — "
        f"widen / keep searching."
    )


def measure_saturation(
    rounds: List[dict],
    report_id: str = "SAT-001",
    coverage_dimensions: Optional[List[str]] = None,
) -> Dict[str, object]:
    """Assemble an evidence_saturation_report payload from a per-round search history.

    Pure function — deterministic on the same input. No network, clock, or randomness.

    Args:
        rounds: chronological per-round history. Each dict should carry
            ``round_index``, ``queries_run``, ``new_unique_sources``,
            ``cumulative_unique_sources``. The metrics use ``new_unique_sources`` and
            ``cumulative_unique_sources``; missing numeric fields default to 0.
        report_id: identifier for the report (non-blank; defaults to "SAT-001").
        coverage_dimensions: which search angles were covered (defaults to []).

    Returns:
        A dict conforming to evidence_saturation_report.schema.json (required fields,
        plus a default ``rationale``). ``rounds`` is normalised to the schema's four
        required integer fields so the payload validates directly.
    """
    dims: List[str] = list(coverage_dimensions) if coverage_dimensions else []

    normalised_rounds: List[Dict[str, int]] = [
        {
            "round_index": int(r.get("round_index", i)),
            "queries_run": int(r.get("queries_run", 0)),
            "new_unique_sources": int(r.get("new_unique_sources", 0)),
            "cumulative_unique_sources": int(r.get("cumulative_unique_sources", 0)),
        }
        for i, r in enumerate(rounds)
    ]

    last_rate = new_result_rate_last_round(normalised_rounds)
    verdict = decide_verdict(normalised_rounds)

    return {
        "report_id": report_id,
        "rounds": normalised_rounds,
        "new_result_rate_last_round": last_rate,
        "duplicate_rate": duplicate_rate(normalised_rounds),
        "coverage_dimensions": dims,
        "saturation_score": saturation_score(normalised_rounds),
        "verdict": verdict,
        "rationale": _default_rationale(verdict, last_rate, len(normalised_rounds)),
    }
