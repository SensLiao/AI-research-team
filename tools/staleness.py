"""Deterministic staleness assessor for staleness-auditor.

Decides whether a source is CURRENT, AGING, STALE, or SUPERSEDED based on:
  - age_years: years since publication relative to audit_year
  - successor_ref: explicit named successor (non-null => SUPERSEDED)

The SUPERSEDED decision is deterministic and binary: if a successor_ref is
provided the status is SUPERSEDED regardless of age.  Thresholds for the
other statuses are:
  < 2 years  => CURRENT
  2-3 years  => AGING
  > 3 years  => STALE  (unless SUPERSEDED)
  None year  => UNKNOWN

A 3-year-old repo with a named successor therefore gets SUPERSEDED, not STALE.
This is a pure function: no I/O, no LLM, no network.
"""
from __future__ import annotations

from typing import Optional

_CURRENT_THRESHOLD = 2    # < 2 years => CURRENT
_AGING_THRESHOLD = 3      # 2 <= age < 3 => AGING; >= 3 => STALE


def classify_staleness(
    year: Optional[int],
    successor_ref: Optional[str] = None,
    audit_year: int = 2026,
) -> str:
    """Return the status string for a source.

    Args:
        year: publication/release year of the source (None => UNKNOWN).
        successor_ref: ref of a known successor that replaces this source.
            Non-null (and non-empty) triggers SUPERSEDED.
        audit_year: reference year for age calculation.

    Returns:
        One of "CURRENT", "AGING", "STALE", "SUPERSEDED", "UNKNOWN".
    """
    # Explicit named successor => always SUPERSEDED
    if successor_ref and str(successor_ref).strip():
        return "SUPERSEDED"

    if year is None:
        return "UNKNOWN"

    age = audit_year - int(year)

    if age < 0:
        # future-dated source (rare; treat as CURRENT)
        return "CURRENT"
    if age < _CURRENT_THRESHOLD:
        return "CURRENT"
    if age < _AGING_THRESHOLD:
        return "AGING"
    return "STALE"


def age_years(year: Optional[int], audit_year: int = 2026) -> Optional[float]:
    """Return age in years, or None if year is unknown."""
    if year is None:
        return None
    return float(audit_year - int(year))


def build_report(
    source_ref: str,
    year: Optional[int],
    successor_ref: Optional[str] = None,
    audit_year: int = 2026,
    staleness_rationale: str = "",
) -> dict:
    """Build a staleness_report payload matching staleness_report.schema.json.

    Verdict (status) is derived from the inputs — never set by hand.
    """
    status = classify_staleness(year, successor_ref, audit_year)
    computed_age = age_years(year, audit_year)

    rationale = staleness_rationale
    if not rationale:
        if status == "SUPERSEDED":
            rationale = f"Superseded by {successor_ref!r}."
        elif status == "UNKNOWN":
            rationale = "Publication year unknown; cannot determine staleness."
        else:
            rationale = (
                f"Published in {year}; age {computed_age:.1f} years relative to audit year {audit_year}. "
                f"Status: {status}."
            )

    report: dict = {
        "source_ref": source_ref,
        "status": status,
        "age_years": computed_age,
        "staleness_rationale": rationale,
        "audit_year": audit_year,
    }
    # Only include successor_ref when SUPERSEDED (required by schema allOf)
    if status == "SUPERSEDED":
        report["successor_ref"] = successor_ref
    else:
        report["successor_ref"] = None
    return report
