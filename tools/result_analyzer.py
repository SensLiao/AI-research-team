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

from .stats_test import enrich_result_summary


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
    # Optional: carry through the baseline CONDITION id (not the scalar baseline_value).
    # enrich_result_summary needs it to locate the per-seed baseline vector for a paired test.
    baseline_cond = raw.get("baseline_condition_id")
    if baseline_cond is not None:
        finding["baseline_condition_id"] = baseline_cond
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


def build_result_summary_with_stats(
    findings: list[dict],
    per_seed: dict,
    *,
    seed: int,
    alpha: float = 0.05,
    caveats: Optional[list[str]] = None,
) -> dict:
    """Assemble a result_summary AND decorate it with significance statistics in one call.

    Thin composition over the unchanged primitives: first ``build_result_summary`` assembles the
    canonical payload (same hard ceilings — status 'provisional', can_cite_thesis False), then
    ``stats_test.enrich_result_summary`` attaches per-finding paired-permutation p-values, bootstrap
    CIs, Holm-corrected significance flags, and a top-level ``stats`` block — but ONLY for findings
    that carry pairable per-seed data (a ``baseline_condition_id`` plus equal-length per-seed vectors
    for both conditions in ``per_seed``). Findings without per-seed data are left exactly as
    ``build_result_summary`` produced them; no statistic is fabricated from a raw delta.

    This is the H6-fix entry point: the result-analyzer agent calls it when it has per-seed metric
    values; otherwise it calls plain ``build_result_summary`` and states "no significance computed".
    ``build_result_summary``'s own signature and behaviour are unchanged — this is purely additive.

    Parameters
    ----------
    findings:
        Same shape as ``build_result_summary`` accepts, optionally including
        ``baseline_condition_id`` per finding to identify the paired baseline condition.
    per_seed:
        ``{condition_id: {metric_name: [float, ...]}}`` — one value per seed, paired by list index.
    seed:
        Caller-supplied seed threaded into the permutation / bootstrap RNGs (determinism).
    alpha:
        Two-sided significance level for the tests, CIs, and Holm correction.
    caveats:
        Optional caveat strings, passed straight through to ``build_result_summary``.

    Returns
    -------
    dict
        An enriched result_summary payload (validates against result_summary.schema.json). The
        ``findings``/``caveats`` produced by ``build_result_summary`` are never mutated in place;
        ``enrich_result_summary`` returns a fresh copy.
    """
    base = build_result_summary(findings, caveats=caveats)
    return enrich_result_summary(base, per_seed, seed=seed, alpha=alpha)
