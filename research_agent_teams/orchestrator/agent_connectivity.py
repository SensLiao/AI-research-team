"""Agent connectivity contract for Research Agent Teams.

This module is intentionally boring and deterministic: it answers the question
"can the research-orchestrator route every research worker somewhere?" without
relying on prose comments or a one-off audit script.
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional, Set

from research_agent_teams.orchestrator.graph_spec import (
    ORCH_DIR,
    load_graph,
    load_mode_registry,
    _load_yaml,
    validate_graph,
    validate_mode_registry,
)
from research_agent_teams.orchestrator.router import resolve_task, validate_routing

AGENTS_DIR = ORCH_DIR.parent / "agents"
TS = "2026-07-01T00:00:00Z"


def load_roster_groups() -> Dict[str, List[str]]:
    data = _load_yaml("roster.yaml")
    return {group: list(names or []) for group, names in data["agents"].items()}


def _all_roster(groups: Dict[str, List[str]]) -> Set[str]:
    return {name for names in groups.values() for name in names}


def _graph_index(graph: dict) -> Dict[str, List[str]]:
    out: Dict[str, List[str]] = {}
    for stage, spec in graph.get("stages", {}).items():
        for agent in spec.get("allowed_agents", []) or []:
            out.setdefault(agent, []).append(stage)
    return {agent: sorted(stages) for agent, stages in out.items()}


def _mode_index(registry: dict, *, operated: Optional[bool] = None) -> Dict[str, List[str]]:
    out: Dict[str, List[str]] = {}
    for mode, spec in registry.get("modes", {}).items():
        if operated is not None and bool(spec.get("operated")) is not operated:
            continue
        for agent in spec.get("agent_subset", []) or []:
            out.setdefault(agent, []).append(mode)
    return {agent: sorted(modes) for agent, modes in out.items()}


def build_agent_connectivity() -> dict:
    groups = load_roster_groups()
    roster = _all_roster(groups)
    control = set(groups.get("control", []))
    graph = load_graph()
    registry = load_mode_registry()
    graph_idx = _graph_index(graph)
    mode_idx = _mode_index(registry)
    operated_idx = _mode_index(registry, operated=True)

    agents = {}
    for agent in sorted(roster):
        is_control = agent in control
        modes = mode_idx.get(agent, [])
        operated_modes = operated_idx.get(agent, [])
        stages = graph_idx.get(agent, [])
        if is_control:
            status = "control"
        elif operated_modes:
            status = "operated"
        elif modes:
            status = "mode-routable"
        elif stages:
            status = "graph-only"
        else:
            status = "roster-only"
        agents[agent] = {
            "status": status,
            "roster_group": next(group for group, names in groups.items() if agent in names),
            "graph_stages": stages,
            "modes": modes,
            "operated_modes": operated_modes,
            "spec_path": str((AGENTS_DIR / f"{agent}.md").relative_to(ORCH_DIR.parent)),
        }

    non_control = roster - control
    return {
        "summary": {
            "roster_agents": len(roster),
            "control_agents": len(control),
            "non_control_agents": len(non_control),
            "graph_connected_non_control": len(non_control & set(graph_idx)),
            "mode_connected_non_control": len(non_control & set(mode_idx)),
            "operated_modes": sorted(
                mode for mode, spec in registry.get("modes", {}).items() if spec.get("operated")
            ),
            "operated_agent_count": len(set(operated_idx)),
        },
        "agents": agents,
    }


def validate_agent_connectivity() -> List[str]:
    groups = load_roster_groups()
    roster = _all_roster(groups)
    control = set(groups.get("control", []))
    graph = load_graph()
    registry = load_mode_registry()
    graph_idx = _graph_index(graph)
    mode_idx = _mode_index(registry)
    errors: List[str] = []

    errors.extend(validate_graph(graph, roster))
    errors.extend(validate_mode_registry(registry, roster))

    for agent in sorted(roster):
        if not (AGENTS_DIR / f"{agent}.md").exists():
            errors.append(f"{agent}: missing agents/{agent}.md")

    for agent in sorted(roster - control):
        if agent not in graph_idx:
            errors.append(f"{agent}: non-control agent is not in graph.allowed_agents")
        if agent not in mode_idx:
            errors.append(f"{agent}: non-control agent is not in any mode agent_subset")

    for mode in sorted(registry.get("modes", {})):
        task_frame = resolve_task("connectivity smoke", mode, f"conn-{mode}", TS, registry=registry)
        routing_errors = validate_routing(task_frame, graph)
        for err in routing_errors:
            errors.append(f"{mode}: {err}")

    return errors
