"""Load + validate the FSM graph, roster, and mode registry (all deterministic, data-driven)."""
from __future__ import annotations

from pathlib import Path
from typing import List, Optional, Set

import yaml

from research_agent_teams.tools.runstore import STAGES

ORCH_DIR = Path(__file__).resolve().parent
GATE_LEVELS = {"auto", "record_only", "director_signoff"}


def _load_yaml(name: str) -> dict:
    return yaml.safe_load((ORCH_DIR / name).read_text(encoding="utf-8"))


def load_graph() -> dict:
    return _load_yaml("graph.yaml")


def load_mode_registry() -> dict:
    return _load_yaml("mode_registry.yaml")


def load_roster() -> Set[str]:
    data = _load_yaml("roster.yaml")
    names: Set[str] = set()
    for group in data["agents"].values():
        names.update(group)
    return names


def validate_graph(graph: Optional[dict] = None, roster: Optional[Set[str]] = None) -> List[str]:
    graph = graph if graph is not None else load_graph()
    roster = roster if roster is not None else load_roster()
    errors: List[str] = []
    stages = graph.get("stages", {})
    known_artifacts = set(graph.get("known_artifact_types", []))

    for s in STAGES:
        if s not in stages:
            errors.append(f"graph missing stage {s}")

    for name, spec in stages.items():
        if name not in STAGES:
            errors.append(f"unknown stage {name}")
            continue
        nxt = spec.get("next")
        if nxt is not None and nxt not in STAGES:
            errors.append(f"{name}.next invalid: {nxt}")
        allowed = spec.get("allowed_agents", []) or []
        for a in allowed:
            if a not in roster:
                errors.append(f"{name}.allowed_agents unknown agent: {a}")
        for g in spec.get("blocking_gates", []) or []:
            if g not in allowed:
                errors.append(f"{name}.blocking_gate '{g}' not in its allowed_agents")
        for art in spec.get("exit_artifacts", []) or []:
            if art not in known_artifacts:
                errors.append(f"{name}.exit_artifact unknown type: {art}")

    # the chain must start at STAGES[0], terminate, and reach REPORT (no cycles)
    seen: List[str] = []
    cur: Optional[str] = STAGES[0]
    while cur is not None and cur not in seen:
        seen.append(cur)
        cur = stages.get(cur, {}).get("next")
    if cur is not None:
        errors.append(f"graph has a cycle at {cur}")
    if STAGES[-1] not in seen:
        errors.append("graph chain does not reach REPORT")
    return errors


def validate_mode_registry(registry: Optional[dict] = None, roster: Optional[Set[str]] = None) -> List[str]:
    registry = registry if registry is not None else load_mode_registry()
    roster = roster if roster is not None else load_roster()
    errors: List[str] = []
    for mode, spec in registry.get("modes", {}).items():
        if spec.get("entry_stage") not in STAGES:
            errors.append(f"{mode}.entry_stage invalid: {spec.get('entry_stage')}")
        for a in spec.get("agent_subset", []) or []:
            if a not in roster:
                errors.append(f"{mode}.agent_subset unknown agent: {a}")
        if spec.get("gate_level") not in GATE_LEVELS:
            errors.append(f"{mode}.gate_level invalid: {spec.get('gate_level')}")
        if "max_agent_hops" not in (spec.get("budget") or {}):
            errors.append(f"{mode}.budget missing max_agent_hops")
    return errors
