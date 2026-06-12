"""Lightweight preregistration (audit C3 — locks the analysis contract before results exist).

At DESIGN time the run freezes WHAT will be measured and HOW it will be analyzed:
primary metric, condition set, planned seeds, stopping rule, analysis plan. The artifact is
checkpointed into the hash-chained ledger like every stage artifact, so it cannot be quietly
rewritten after the numbers arrive. At ANALYZE time ``build_deviation_verdict`` mechanically
compares the result_summary against the preregistration:

  - VIOLATION (hard — caller blocks): the preregistered primary metric is absent from the
    findings; a finding reports a condition that was never preregistered; a finding reports a
    metric that was neither preregistered (primary/secondary) — the classic outcome-switching /
    p-hacking move ("look at the results, then pick the metric"). Exploratory numbers belong in
    ``caveats`` prose, not in findings.
  - WARNING (advisory, surfaced, never a block): fewer seeds than planned (honest partial
    progress is reportable — but the shortfall must be visible).

Pure functions; no I/O, no clock. Payload conforms to preregistration.schema.json; the deviation
verdict conforms to analysis_check_verdict.schema.json (panel_role "compliance").
"""
from __future__ import annotations

from typing import List, Optional, Tuple


def build_prereg(matrix: dict, *, primary_metric: str, n_seeds_planned: int,
                 stopping_rule: str, analysis_plan: str,
                 secondary_metrics: Optional[List[str]] = None) -> dict:
    """Freeze the analysis contract from the experiment_matrix. Fail-loud on an unfrozen plan."""
    if not (primary_metric or "").strip():
        raise ValueError("preregistration requires a non-empty primary_metric")
    if not isinstance(n_seeds_planned, int) or n_seeds_planned < 1:
        raise ValueError(f"preregistration requires n_seeds_planned >= 1 (got {n_seeds_planned!r})")
    if not (stopping_rule or "").strip():
        raise ValueError("preregistration requires a non-empty stopping_rule")
    if not (analysis_plan or "").strip():
        raise ValueError("preregistration requires a non-empty analysis_plan")
    conditions = matrix.get("conditions") or []
    if not conditions:
        raise ValueError("preregistration requires an experiment_matrix with conditions")
    condition_ids = sorted(str(c.get("id")) for c in conditions if c.get("id"))
    baseline = next((str(c.get("id")) for c in conditions if c.get("baseline")), None)
    hypotheses = [str(r.get("hypothesis")) for r in (matrix.get("ranked_batch") or [])
                  if r.get("hypothesis")]
    payload = {
        "research_question": str(matrix.get("research_question") or ""),
        "primary_metric": primary_metric.strip(),
        "secondary_metrics": [m.strip() for m in (secondary_metrics or []) if (m or "").strip()],
        "condition_ids": condition_ids,
        "n_seeds_planned": n_seeds_planned,
        "stopping_rule": stopping_rule.strip(),
        "analysis_plan": analysis_plan.strip(),
    }
    if baseline is not None:
        payload["baseline_condition_id"] = baseline
    if hypotheses:
        payload["hypotheses"] = hypotheses
    return payload


def check_deviation(prereg: dict, result_summary: dict) -> Tuple[List[str], List[str]]:
    """Return (violations, warnings) for a result_summary vs its preregistration."""
    violations: List[str] = []
    warnings: List[str] = []

    primary = str(prereg.get("primary_metric") or "").lower()
    registered_metrics = {primary} | {str(m).lower() for m in (prereg.get("secondary_metrics") or [])}
    registered_conditions = {str(c) for c in (prereg.get("condition_ids") or [])}
    findings = result_summary.get("findings") or []

    reported_metrics = {str(f.get("metric") or "").lower() for f in findings}
    if primary and primary not in reported_metrics:
        violations.append(
            f"preregistered primary metric {prereg.get('primary_metric')!r} is absent from the "
            "findings — the analysis must report the primary outcome it committed to")

    for f in findings:
        metric = str(f.get("metric") or "").lower()
        cid = str(f.get("condition_id") or "")
        if metric and metric not in registered_metrics:
            violations.append(
                f"finding reports metric {f.get('metric')!r} which was NOT preregistered — "
                "outcome switching; preregister it or move exploratory numbers to caveats prose")
        if cid and registered_conditions and cid not in registered_conditions:
            violations.append(
                f"finding reports condition {cid!r} which was NOT in the preregistered condition "
                f"set {sorted(registered_conditions)} — undeclared condition")

    planned = prereg.get("n_seeds_planned")
    if isinstance(planned, int) and planned >= 1:
        for f in findings:
            n = f.get("n_seeds")
            if isinstance(n, int) and n < planned:
                warnings.append(
                    f"finding {f.get('metric')!r}@{f.get('condition_id')!r} used {n} seeds, fewer "
                    f"than the preregistered {planned} — honest partial progress; shortfall visible")
    return violations, warnings


def build_deviation_verdict(prereg: dict, result_summary: dict) -> dict:
    """The prereg-deviation check as an analysis_check_verdict (panel_role 'compliance')."""
    violations, warnings = check_deviation(prereg, result_summary)
    notes = ["preregistration deviation check"]
    notes += warnings
    return {
        "panel_role": "compliance",
        "pass": not violations,
        "violations": violations,
        "checked_items": sorted({str(f.get("metric")) for f in (result_summary.get("findings") or [])
                                 if f.get("metric")}),
        "notes": "; ".join(notes),
    }
