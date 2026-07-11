"""Experiment feedback builder — RD-Agent failure-attribution pattern (ANALYZE stage, wave 1).

Attributes an experiment outcome to the layer that produced it — hypothesis, implementation,
environment, data, evaluation, protocol, statistics, or an unresolved/inconclusive boundary — so
the next bounded attempt is routed at the RIGHT layer instead of blindly re-running. Absorbed from
Microsoft RD-Agent's
experiment-feedback loop; re-shaped into the machine's idiom: a pure deterministic builder the
result-analyzer calls with ITS read of the artifacts (the LLM gathers, this code structures and
fail-validates; routing hints are advisory EVIDENCE — the director gate is never bypassed).
"""
from __future__ import annotations

import re
from typing import List, Optional

OUTCOMES = ("improved", "regressed", "inconclusive", "failed")
ATTRIBUTIONS = (
    "hypothesis", "implementation", "environment", "data", "evaluation", "protocol",
    "statistics", "inconclusive", "unknown",
)
NEXT_ACTIONS = (
    "revise_hypothesis", "fix_implementation", "fix_environment", "fix_data",
    "fix_evaluation", "fix_protocol", "increase_precision", "run_diagnostic", "escalate", "stop",
)
ATTRIBUTION_STATES = (
    "symptom_only", "associated", "reproduced", "intervention_confirmed",
    "counterfactually_supported",
)
COUNTERFACTUAL_CHECKS = ("not_tested", "supports", "does_not_support", "inconclusive")
REPLICATION_STATUSES = ("not_attempted", "failed_to_reproduce", "reproduced_once", "replicated")
VALIDITY_FIELDS = (
    "implementation_valid", "data_valid", "evaluation_valid", "protocol_valid", "statistics_valid",
)
_SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_ADVANCED_ATTRIBUTION_STATES = {"intervention_confirmed", "counterfactually_supported"}

_ATTRIBUTION_TO_ACTION = {
    "hypothesis": "revise_hypothesis",
    "implementation": "fix_implementation",
    "environment": "fix_environment",
    "data": "fix_data",
    "evaluation": "fix_evaluation",
    "protocol": "fix_protocol",
    "statistics": "increase_precision",
    "inconclusive": "run_diagnostic",
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


def _binding(value: object, *, label: str) -> dict:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an artifact_ref/sha256 object")
    ref = str(value.get("artifact_ref") or "").strip()
    digest = str(value.get("sha256") or "").strip()
    if not ref or not _SHA256_RE.fullmatch(digest):
        raise ValueError(f"{label} requires a non-empty artifact_ref and sha256:<64 hex>")
    return {"artifact_ref": ref, "sha256": digest}


def _verify_binding(binding: dict, *, required_role: str,
                    verified_execution_bindings: Optional[dict]) -> None:
    trusted = (verified_execution_bindings or {}).get(binding["artifact_ref"])
    if not isinstance(trusted, dict):
        raise ValueError(
            f"{required_role} binding is not present in the verified executor import: "
            f"{binding['artifact_ref']}"
        )
    if trusted.get("sha256") != binding["sha256"]:
        raise ValueError(f"{required_role} binding hash does not match executor import")
    if trusted.get("role") != required_role:
        raise ValueError(
            f"{required_role} binding points to executor role {trusted.get('role')!r}"
        )
    if trusted.get("exit_status") != 0:
        raise ValueError(f"{required_role} binding comes from a failed executor job")


def build_experiment_feedback(run_ref: str, outcome: str, attribution: str, summary: str,
                              evidence_ref: List[str], hypothesis_ref: Optional[str] = None,
                              next_action_hint: Optional[str] = None,
                              metrics_delta: Optional[List[dict]] = None,
                              attribution_state: Optional[str] = None,
                              validity: Optional[dict] = None,
                              counterfactual_check: Optional[str] = None,
                              replication_status: Optional[str] = None,
                              diagnostic_intervention: Optional[dict] = None,
                              replication_artifacts: Optional[List[dict]] = None,
                              verified_execution_bindings: Optional[dict] = None) -> dict:
    """Assemble + fail-validate an ``experiment_feedback`` payload (schema-ready).

    next_action_hint defaults to ``suggest_next_action(outcome, attribution)`` — pass it
    explicitly only to override the routing rule (the override is still enum-checked).
    """
    if not isinstance(run_ref, str) or not run_ref.strip():
        raise ValueError("run_ref must be a non-empty string")
    if not isinstance(summary, str) or not summary.strip():
        raise ValueError("summary must be a non-empty string")
    if not isinstance(hypothesis_ref, str) or not hypothesis_ref.strip():
        raise ValueError("hypothesis_ref must bind feedback to one concrete tested hypothesis")
    if not evidence_ref or not all(isinstance(r, str) and r.strip() for r in evidence_ref):
        raise ValueError("evidence_ref must be a non-empty list of refs (anti-slop binding)")
    hint = next_action_hint if next_action_hint is not None else suggest_next_action(outcome, attribution)
    if hint not in NEXT_ACTIONS:
        raise ValueError(f"next_action_hint must be one of {NEXT_ACTIONS}, got {hint!r}")
    if outcome not in OUTCOMES:
        raise ValueError(f"outcome must be one of {OUTCOMES}, got {outcome!r}")
    if attribution not in ATTRIBUTIONS:
        raise ValueError(f"attribution must be one of {ATTRIBUTIONS}, got {attribution!r}")

    state = attribution_state or "symptom_only"
    if state not in ATTRIBUTION_STATES:
        raise ValueError(f"attribution_state must be one of {ATTRIBUTION_STATES}, got {state!r}")
    counterfactual = counterfactual_check or "not_tested"
    if counterfactual not in COUNTERFACTUAL_CHECKS:
        raise ValueError(
            f"counterfactual_check must be one of {COUNTERFACTUAL_CHECKS}, got {counterfactual!r}"
        )
    replication = replication_status or "not_attempted"
    if replication not in REPLICATION_STATUSES:
        raise ValueError(
            f"replication_status must be one of {REPLICATION_STATUSES}, got {replication!r}"
        )
    validity_values = dict(validity or {})
    for field in VALIDITY_FIELDS:
        value = validity_values.get(field)
        if not isinstance(value, bool):
            raise ValueError(f"{field} must be an explicit boolean for failure attribution")
    if attribution == "hypothesis":
        invalid = [field for field in VALIDITY_FIELDS if validity_values[field] is not True]
        if invalid or replication != "replicated":
            raise ValueError(
                "hypothesis attribution requires every implementation/data/evaluation/protocol/"
                f"statistics validity flag true and replication_status='replicated'; invalid={invalid}, "
                f"replication_status={replication!r}"
            )
    if state == "counterfactually_supported" and counterfactual != "supports":
        raise ValueError(
            "counterfactually_supported attribution_state requires counterfactual_check='supports'"
        )

    diagnostic = None
    if diagnostic_intervention is not None:
        diagnostic = _binding(diagnostic_intervention, label="diagnostic_intervention")
        _verify_binding(
            diagnostic,
            required_role="diagnostic_intervention",
            verified_execution_bindings=verified_execution_bindings,
        )
    replications = [
        _binding(value, label=f"replication_artifacts[{index}]")
        for index, value in enumerate(replication_artifacts or [])
    ]
    for value in replications:
        _verify_binding(
            value,
            required_role="replication_evidence",
            verified_execution_bindings=verified_execution_bindings,
        )
    if replication != "not_attempted" and not replications:
        raise ValueError(
            f"replication_status={replication!r} requires a verified replication artifact"
        )
    if state == "reproduced" and not replications:
        raise ValueError("reproduced attribution_state requires a verified replication artifact")
    if state in _ADVANCED_ATTRIBUTION_STATES and (diagnostic is None or not replications):
        raise ValueError(
            f"{state} attribution_state requires verified diagnostic intervention and "
            "replication artifacts"
        )
    if attribution == "hypothesis" and state not in _ADVANCED_ATTRIBUTION_STATES:
        raise ValueError(
            "hypothesis attribution requires intervention_confirmed or "
            "counterfactually_supported state"
        )

    payload = {"run_ref": run_ref, "outcome": outcome, "attribution": attribution,
               "summary": summary, "next_action_hint": hint,
               "hypothesis_ref": hypothesis_ref.strip(),
               "evidence_ref": list(evidence_ref),
               "attribution_state": state,
               "counterfactual_check": counterfactual,
               "replication_status": replication,
               **{field: validity_values[field] for field in VALIDITY_FIELDS}}
    if diagnostic is not None:
        payload["diagnostic_intervention"] = diagnostic
        payload["evidence_ref"].append(diagnostic["artifact_ref"])
    if replications:
        payload["replication_artifacts"] = replications
        payload["evidence_ref"].extend(value["artifact_ref"] for value in replications)
    payload["evidence_ref"] = list(dict.fromkeys(payload["evidence_ref"]))
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
