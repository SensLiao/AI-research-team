"""Experiment feedback builder — RD-Agent failure-attribution pattern (ANALYZE stage, wave 1).

Attributes an experiment outcome to the layer that produced it — the science (hypothesis), the
code (implementation), or the setup (environment) — so the next bounded attempt is routed at the
RIGHT layer instead of blindly re-running. Absorbed from Microsoft RD-Agent's
experiment-feedback loop; re-shaped into the machine's idiom: a pure deterministic builder the
result-analyzer calls with ITS read of the artifacts (the LLM gathers, this code structures and
fail-validates; routing hints are advisory EVIDENCE — the director gate is never bypassed).
"""
from __future__ import annotations

from typing import List, Optional

OUTCOMES = ("improved", "regressed", "inconclusive", "failed")
ATTRIBUTIONS = ("hypothesis", "implementation", "environment", "unknown")
NEXT_ACTIONS = ("revise_hypothesis", "fix_implementation", "fix_environment", "escalate", "stop")

_ATTRIBUTION_TO_ACTION = {
    "hypothesis": "revise_hypothesis",
    "implementation": "fix_implementation",
    "environment": "fix_environment",
    "unknown": "escalate",
}


def suggest_next_action(outcome: str, attribution: str) -> str:
    """The RD-Agent routing rule: improved -> stop (this loop converged; next step is the
    director's call), otherwise route by attribution; unknown always escalates to a human."""
    if outcome not in OUTCOMES:
        raise ValueError(f"outcome must be one of {OUTCOMES}, got {outcome!r}")
    if attribution not in ATTRIBUTIONS:
        raise ValueError(f"attribution must be one of {ATTRIBUTIONS}, got {attribution!r}")
    if outcome == "improved":
        return "stop"
    return _ATTRIBUTION_TO_ACTION[attribution]


def build_experiment_feedback(run_ref: str, outcome: str, attribution: str, summary: str,
                              evidence_ref: List[str], hypothesis_ref: Optional[str] = None,
                              next_action_hint: Optional[str] = None,
                              metrics_delta: Optional[List[dict]] = None) -> dict:
    """Assemble + fail-validate an ``experiment_feedback`` payload (schema-ready).

    next_action_hint defaults to ``suggest_next_action(outcome, attribution)`` — pass it
    explicitly only to override the routing rule (the override is still enum-checked).
    """
    if not isinstance(run_ref, str) or not run_ref.strip():
        raise ValueError("run_ref must be a non-empty string")
    if not isinstance(summary, str) or not summary.strip():
        raise ValueError("summary must be a non-empty string")
    if not evidence_ref or not all(isinstance(r, str) and r.strip() for r in evidence_ref):
        raise ValueError("evidence_ref must be a non-empty list of refs (anti-slop binding)")
    hint = next_action_hint if next_action_hint is not None else suggest_next_action(outcome, attribution)
    if hint not in NEXT_ACTIONS:
        raise ValueError(f"next_action_hint must be one of {NEXT_ACTIONS}, got {hint!r}")
    if outcome not in OUTCOMES:
        raise ValueError(f"outcome must be one of {OUTCOMES}, got {outcome!r}")
    if attribution not in ATTRIBUTIONS:
        raise ValueError(f"attribution must be one of {ATTRIBUTIONS}, got {attribution!r}")

    payload = {"run_ref": run_ref, "outcome": outcome, "attribution": attribution,
               "summary": summary, "next_action_hint": hint,
               "evidence_ref": list(evidence_ref)}
    if hypothesis_ref:
        payload["hypothesis_ref"] = hypothesis_ref
    if metrics_delta:
        cleaned = []
        for m in metrics_delta:
            if not isinstance(m, dict) or not str(m.get("name", "")).strip():
                raise ValueError(f"metrics_delta entries need a non-empty name: {m!r}")
            cleaned.append({"name": str(m["name"]),
                            "before": float(m["before"]) if m.get("before") is not None else None,
                            "after": float(m["after"]) if m.get("after") is not None else None})
        payload["metrics_delta"] = cleaned
    return payload
