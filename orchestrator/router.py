"""Deterministic router: request + mode -> validated task_frame; routing guardrails.

This is the PARSE step's machine core. It does not call an LLM; it looks up the mode in the
registry and emits a schema-valid, enveloped task_frame. Guardrails enforce that a high-stakes
task cannot enter a gated stage without that stage's hard gates in its agent_subset.
"""
from __future__ import annotations

from typing import List, Optional

from research_agent_teams.orchestrator.graph_spec import load_graph, load_mode_registry
from research_agent_teams.orchestrator.model_policy import VALID_POLICIES
from research_agent_teams.tools.projects import PROJECT_SLUG_RE
from research_agent_teams.tools.research_capability_router import route_research_capabilities
from research_agent_teams.tools.runstore import STAGES
from research_agent_teams.tools.validate_artifact import validate_artifact


def _capability_overlay_plan(request_text: str, mode: str, registry: dict,
                             capability_route: Optional[dict] = None) -> dict:
    """Freeze the metadata-only quality overlays selected for this task.

    The selector cannot execute an external skill and this compact projection deliberately
    cannot change the mode, workers, stage path, gates, or budget.  It is advisory context for
    the already-authorized workers, hash-pinned with the rest of the task frame.
    """
    route = capability_route or route_research_capabilities(
        request_text, explicit_mode=mode, registry=registry,
    )
    if route.get("routing", {}).get("mode") != mode:
        raise ValueError("capability route selected a different mode than the frozen task mode")
    if route.get("request_text") != request_text:
        raise ValueError("capability route request differs from the task request")
    if route.get("safety", {}).get("external_execution") is not False:
        raise ValueError("capability route attempted to enable external execution")
    if route.get("safety", {}).get("network_default") != "DENY":
        raise ValueError("capability route attempted to enable network access")
    honesty = route["routing"]["honesty"]
    safety = route["safety"]
    return {
        "contract_version": route["contract_version"],
        "mode_source": route["routing"]["selection_source"],
        "mode_status": honesty["state"],
        "one_button_operable": bool(honesty["one_button_operable"]),
        "external_skill_execution": False,
        "network_access": False,
        "vault_write": False,
        "forbidden_actions": list(safety["forbidden_actions"]),
        "overlays": [
            {
                "overlay_id": item["overlay_id"],
                "title": item["title"],
                "guidance": item["summary"],
                "target_stages": list(item["stages"]),
                "selection_reasons": list(item["selection_reasons"]),
                "allowed_use": item["allowed_use"],
                "non_goals": list(item["non_goals"]),
                "provenance": [dict(source) for source in item["provenance"]],
            }
            for item in route["capability_overlays"]
        ],
    }


def _mechanism_council_plan(capability_route: dict) -> dict:
    """Freeze the advisory council route without treating it as dispatched work."""
    plan = capability_route.get("mechanism_council_plan")
    if not isinstance(plan, dict):
        raise ValueError("capability route omitted mechanism_council_plan")
    boundary = plan.get("truth_boundary")
    if not isinstance(boundary, dict):
        raise ValueError("mechanism council route omitted truth boundary")
    if boundary.get("advisory_only") is not True:
        raise ValueError("mechanism council attempted to become an execution authority")
    if boundary.get("may_create_results") is not False:
        raise ValueError("mechanism council attempted to create results")
    if boundary.get("may_claim_novelty") is not False:
        raise ValueError("mechanism council attempted to claim novelty")
    return {
        "contract_version": plan["contract_version"],
        "enabled": bool(plan["enabled"]),
        "selection_source": plan["selection_source"],
        "signal_hits": {
            str(group): [str(hit) for hit in hits]
            for group, hits in dict(plan["signal_hits"]).items()
        },
        "selected_roles": list(plan["selected_roles"]),
        "auto_added_dependencies": list(plan["auto_added_dependencies"]),
        "waves": [list(wave) for wave in plan["waves"]],
        "truth_boundary": dict(boundary),
    }


def resolve_task(request_text: str, mode: str, run_id: str, ts: str,
                 registry: Optional[dict] = None, domain_profile_ref: Optional[str] = None,
                 model_policy: str = "default", project: Optional[str] = None,
                 north_star: Optional[dict] = None,
                 capability_route: Optional[dict] = None) -> dict:
    registry = registry if registry is not None else load_mode_registry()
    modes = registry.get("modes", {})
    if mode not in modes:
        raise ValueError(f"unknown mode '{mode}' (known: {sorted(modes)})")
    if model_policy not in VALID_POLICIES:
        raise ValueError(f"unknown model_policy '{model_policy}' (valid: {list(VALID_POLICIES)})")
    if project is not None and not PROJECT_SLUG_RE.match(project):
        raise ValueError(f"invalid project slug {project!r}: must be lowercase-kebab")
    spec = modes[mode]
    # The run's immutable direction contract (audit H2). The director may supply a sharper
    # statement + in/out-of-scope lists; absent that, the verbatim request IS the north star.
    ns = dict(north_star) if north_star else {}
    ns_statement = str(ns.get("statement") or "").strip() or request_text
    if not (ns_statement or "").strip():
        raise ValueError("north_star requires a non-empty statement (or a non-empty request_text)")
    resolved_north_star = {
        "statement": ns_statement,
        "in_scope": [str(x) for x in (ns.get("in_scope") or []) if str(x).strip()],
        "out_of_scope": [str(x) for x in (ns.get("out_of_scope") or []) if str(x).strip()],
    }
    resolved_capability_route = capability_route or route_research_capabilities(
        request_text,
        explicit_mode=mode,
        registry=registry,
    )
    payload = {
        "task_id": run_id,
        "mode": mode,
        "request_text": request_text,
        "north_star": resolved_north_star,
        "entry_stage": spec["entry_stage"],
        "agent_subset": list(spec["agent_subset"]),
        "gate_level": spec["gate_level"],
        "model_policy": model_policy,
        "domain_profile_ref": domain_profile_ref,
        "budget": dict(spec["budget"]),
        "capability_overlay_plan": _capability_overlay_plan(
            request_text, mode, registry, resolved_capability_route,
        ),
        "mechanism_council_plan": _mechanism_council_plan(resolved_capability_route),
    }
    handoff = spec.get("handoff") or {}
    if isinstance(handoff, dict) and handoff:
        # Freeze the product contract into the task frame. The task frame is hash-pinned in the
        # ledger, so a future mode_registry upgrade cannot silently relabel an old run as a newer
        # scientific product version.
        payload["product_contract"] = {
            "contract_version": str(handoff.get("contract_version") or ""),
            "product_version": str(handoff.get("product_version") or ""),
            "primary_markdown": str(handoff.get("primary_markdown") or ""),
            "reusable_artifacts": [str(x) for x in (handoff.get("reusable_artifacts") or [])],
            "accepts": [str(x) for x in (handoff.get("accepts") or [])],
            "accepts_delivery_statuses": [
                str(x) for x in (handoff.get("accepts_delivery_statuses") or ["USABLE"])
            ],
        }
    if spec.get("stage_path"):                       # a mode may declare its true forward-only shape
        payload["stage_path"] = list(spec["stage_path"])
    if "director_gate_stages" in spec:
        # Freeze the human decision boundary in the task frame.  A later registry edit
        # must not silently change the behavior of a ledger-pinned historical run.
        payload["director_gate_stages"] = list(spec["director_gate_stages"])
    if project is not None:                          # the run's research project (groups the run-store)
        payload["project"] = project
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
    driven_stages = list(p.get("stage_path") or STAGES[STAGES.index(entry):])
    if p.get("gate_level") == "director_signoff":
        for stage in driven_stages:
            if stage not in stages:
                errors.append(f"stage_path contains invalid stage: {stage}")
                continue
            for g in stages[stage].get("blocking_gates", []) or []:
                if g not in subset:
                    errors.append(f"gated stage {stage} requires hard gate '{g}' in agent_subset")

    # Guardrail 2: every chosen agent must be allowed in some stage at or after entry.
    allowed_from_entry = set()
    for s in STAGES[STAGES.index(entry):]:
        allowed_from_entry.update(stages.get(s, {}).get("allowed_agents", []) or [])
    for a in subset:
        if a not in allowed_from_entry:
            errors.append(f"agent '{a}' is not allowed in any stage at/after {entry}")
    return errors
