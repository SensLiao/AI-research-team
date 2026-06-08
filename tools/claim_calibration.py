"""Deterministic core of the claim-strength-calibrator (ANALYZE producer).

Calibrates the strength of numeric claims by comparing the claimed delta against
the measured variance (std or half-CI). A claim of "+0.3% significant" is meaningless
if the std is ±0.5% — it should be rewritten as "marginal within variance".

Calibration rules (deterministic):
  - delta is None or variance is None → strength unchanged (advisory only)
  - abs(delta) >= 2 * variance         → "strong"   (clear signal)
  - abs(delta) >= variance             → "moderate" (signal > noise)
  - abs(delta) >= 0.5 * variance       → "marginal" (borderline)
  - abs(delta) <  0.5 * variance       → "inconclusive" (noise-dominated)

The LLM provides the original claim and numeric context; this checker recomputes
the strength label deterministically. Nothing hardcoded per domain.
"""
from __future__ import annotations

from typing import List, Optional


# --------------------------------------------------------------------------- #
#  Calibration logic                                                           #
# --------------------------------------------------------------------------- #

_STRONG_THRESHOLD = 2.0      # delta >= 2 * variance
_MODERATE_THRESHOLD = 1.0    # delta >= 1 * variance
_MARGINAL_THRESHOLD = 0.5    # delta >= 0.5 * variance
# below 0.5 * variance → inconclusive


def _calibrate_strength(delta: Optional[float], variance: Optional[float]) -> str:
    """Return the calibrated strength label based on delta vs. variance.

    M2 FIX: If either delta or variance is None/missing, returns 'inconclusive' (the
    weakest/most neutral label), NOT 'moderate'. An uncalibratable claim cannot
    be assigned even moderate strength — the data simply isn't there to support it.
    """
    if delta is None or variance is None:
        return "inconclusive"  # cannot calibrate without numeric context — weakest label

    abs_delta = abs(delta)
    var = abs(variance)

    if var == 0.0:
        # zero variance: any nonzero delta is strong; zero delta inconclusive
        return "strong" if abs_delta > 0 else "inconclusive"

    ratio = abs_delta / var

    if ratio >= _STRONG_THRESHOLD:
        return "strong"
    elif ratio >= _MODERATE_THRESHOLD:
        return "moderate"
    elif ratio >= _MARGINAL_THRESHOLD:
        return "marginal"
    else:
        return "inconclusive"


def _build_caveat(
    original_strength: Optional[str],
    calibrated_strength: str,
    delta: Optional[float],
    variance: Optional[float],
) -> str:
    """Build a human-readable caveat explaining why the strength was (or wasn't) changed."""
    if delta is None or variance is None:
        return (
            "Numeric delta or variance not provided; strength could not be calibrated. "
            "Claim downgraded to 'inconclusive' (uncalibratable)."
        )

    if original_strength and original_strength != calibrated_strength:
        return (
            f"Claim strength downgraded from '{original_strength}' to '{calibrated_strength}': "
            f"delta={delta:.4g} vs variance={variance:.4g} "
            f"(ratio={abs(delta) / abs(variance):.2f} < threshold for '{original_strength}')."
        )
    return (
        f"Calibrated strength '{calibrated_strength}': "
        f"delta={delta:.4g}, variance={variance:.4g}."
    )


# --------------------------------------------------------------------------- #
#  Public API                                                                  #
# --------------------------------------------------------------------------- #

def calibrate_claim(
    original_claim: str,
    delta: Optional[float] = None,
    variance: Optional[float] = None,
    original_strength: Optional[str] = None,
    metric: Optional[str] = None,
) -> dict:
    """Return a calibrated_claim dict (one entry of calibrated_claims.calibrated[]).

    calibrated_claim text is updated to reflect the calibrated strength.
    downgraded is True iff the strength was reduced.
    """
    calibrated_strength = _calibrate_strength(delta, variance)
    downgraded = bool(
        original_strength and original_strength != calibrated_strength
        and _strength_rank(calibrated_strength) < _strength_rank(original_strength)
    )

    # Rewrite claim text to reflect calibrated strength
    if downgraded:
        calibrated_text = (
            f"[calibrated: {calibrated_strength}] {original_claim}"
        )
    else:
        calibrated_text = original_claim

    caveat = _build_caveat(original_strength, calibrated_strength, delta, variance)

    return {
        "original_claim": original_claim,
        "metric": metric,
        "delta": delta,
        "variance": variance,
        "strength": calibrated_strength,
        "calibrated_claim": calibrated_text,
        "caveat": caveat,
        "downgraded": downgraded,
    }


def _strength_rank(s: str) -> int:
    """Numeric rank for strength comparison (higher = stronger claim)."""
    order = {"inconclusive": 0, "marginal": 1, "moderate": 2, "strong": 3}
    return order.get(s, 1)


def build_report(
    raw_claims: List[dict],
    source_ref: Optional[str] = None,
) -> dict:
    """Build a calibrated_claims payload from a list of raw claim dicts.

    Each raw claim dict:
      {
        "original_claim": str,
        "metric": str | None,
        "delta": float | None,
        "variance": float | None,
        "original_strength": str | None,   # pre-calibration strength asserted by LLM
      }

    Returns a calibrated_claims payload.
    """
    calibrated = []
    for raw in raw_claims or []:
        entry = calibrate_claim(
            original_claim=str(raw.get("original_claim", "")),
            delta=raw.get("delta"),
            variance=raw.get("variance"),
            original_strength=raw.get("original_strength"),
            metric=raw.get("metric"),
        )
        calibrated.append(entry)

    return {
        "source_ref": source_ref,
        "calibrated": calibrated,
    }
