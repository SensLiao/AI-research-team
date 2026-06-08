"""Deterministic router: request + mode -> validated task_frame; routing guardrails.

This is the PARSE step's machine core. It does not call an LLM; it looks up the mode in the
registry and emits a schema-valid, enveloped task_frame. Guardrails enforce that a high-stakes
task cannot enter a gated stage without that stage's hard gates in its agent_subset.
"""
from __future__ import annotations

from typing import List, Optional

from research_agent_teams.orchestrator.graph_spec import load_graph, load_mode_registry
from research_agent_teams.orchestrator.model_policy import VALID_POLICIES
from research_agent_teams.tools.runstore import STAGES
from research_agent_teams.tools.validate_artifact import validate_artifact


def resolve_task(request_text: str, mode: str, run_id: str, ts: str,
                 registry: Optional[dict] = None, domain_profile_ref: Optional[str] = None,
                 model_policy: str = "default") -> dict:
    registry = registry if registry is not None else load_mode_registry()
    modes = registry.get("modes", {})
    if mode not in modes:
        raise ValueError(f"unknown mode '{mode}' (known: {sorted(modes)})")
    if model_policy not in VALID_POLICIES:
        raise ValueError(f"unknown model_policy '{model_policy}' (valid: {list(VALID_POLICIES)})")
    spec = modes[mode]
    payload = {
        "task_id": run_id,
        "mode": mode,
        "request_text": request_text,
        "entry_stage": spec["entry_stage"],
        "agent_subset": list(spec["agent_subset"]),
        "gate_level": spec["gate_level"],
        "model_policy": model_policy,
        "domain_profile_ref": domain_profile_ref,
        "budget": dict(spec["budget"]),
    }
    if spec.get("stage_path"):                       # a mode may declare its true forward-only shape
        payload["stage_path"] = list(spec["stage_path"])
    artifact = {
        "artifact_id": f"task_frame-{run_id}",
        "artifact_type": "task_frame",
        "schema_version": "1.0.0",
        "created_by": "orchestrator",
        "created_at": ts,
        "status": "draft",
        "input_artifact_hashes": [],
        "output_hash": None,
        "domain_profile_ref": domain_profile_ref,
        "payload": payload,
    }
    errs = validate_artifact(artifact)
    if errs:
        raise ValueError(f"router produced an invalid task_frame: {errs}")
    return artifact


def validate_routing(task_frame: dict, graph: Optional[dict] = None) -> List[str]:
    """Routing guardrails. Empty list == routing is admissible."""
    graph = graph if graph is not None else load_graph()
    stages = graph["stages"]
    p = task_frame["payload"]
    entry = p["entry_stage"]
    errors: List[str] = []
    if entry not in STAGES:
        return [f"entry_stage invalid: {entry}"]

    subset = set(p["agent_subset"])

    # Guardrail 1: a director_signoff (high-stakes) task entering a gated stage must include that
    # stage's hard gates — you cannot run gated work and skip the gate.
    if p.get("gate_level") == "director_signoff":
        for g in stages[entry].get("blocking_gates", []) or []:
            if g not in subset:
                errors.append(f"gated stage {entry} requires hard gate '{g}' in agent_subset")

    # Guardrail 2: every chosen agent must be allowed in some stage at or after entry.
    allowed_from_entry = set()
    for s in STAGES[STAGES.index(entry):]:
        allowed_from_entry.update(stages.get(s, {}).get("allowed_agents", []) or [])
    for a in subset:
        if a not in allowed_from_entry:
            errors.append(f"agent '{a}' is not allowed in any stage at/after {entry}")
    return errors
