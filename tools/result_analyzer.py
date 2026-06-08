"""Deterministic core of the result-analyzer (ANALYZE stage).

Given a list of findings (each with metric, value, condition_id, and optionally
baseline_value), build a result_summary payload. Hard ceilings enforced here:
  - status is ALWAYS "provisional"   (never accept as a param; schema const enforces it)
  - can_cite_thesis is ALWAYS False  (never accept as a param; schema const enforces it)

The LLM agent gathers findings from the run-store and calls this function; the
function — not the LLM — assembles the payload and enforces the ceilings.
"""
from __future__ import annotations

from typing import Optional


def _build_finding(raw: dict) -> dict:
    """Build a single finding dict with only schema-allowed fields.

    Required from caller: metric (str), value (number), condition_id (str).
    Optional from caller: baseline_value (number or None).

    If baseline_value is present and not None, include it and compute delta.
    Otherwise omit both baseline_value and delta entirely.
    """
    finding: dict = {
        "metric": raw["metric"],
        "value": raw["value"],
        "condition_id": raw["condition_id"],
    }
    baseline = raw.get("baseline_value")
    if baseline is not None:
        finding["baseline_value"] = baseline
        finding["delta"] = round(raw["value"] - baseline, 6)
    return finding


def build_result_summary(
    findings: list[dict],
    caveats: Optional[list[str]] = None,
) -> dict:
    """Assemble a result_summary payload.

    Parameters
    ----------
    findings:
        List of finding dicts. Each must have 'metric' (str), 'value' (number),
        'condition_id' (str). May optionally include 'baseline_value' (number);
        if present and not None, delta is computed and included.
    caveats:
        Optional list of caveat strings. Defaults to empty list.

    Returns
    -------
    dict
        A result_summary payload that validates against result_summary.schema.json.
        'status' is hardcoded "provisional"; 'can_cite_thesis' is hardcoded False.
        These are not exposed as parameters — the schema enforces them as consts.
    """
    return {
        "status": "provisional",
        "findings": [_build_finding(f) for f in findings],
        "caveats": caveats if caveats is not None else [],
        "can_cite_thesis": False,
    }
