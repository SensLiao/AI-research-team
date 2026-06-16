"""Execution-granularity registries — run ONE stage / skill / bridge mid-flight, with guardrails.

The existing operate loop drives WHOLE modes (begin -> worker -> run-dets -> commit, stage by stage).
This module adds the finer grain the director asked for: a declarative registry of the 7 FSM stages,
the mid-stage skills, and the 6 stage-transition bridges, PLUS a readiness check grounded in the run's
tamper-evident manifest (completed_work + next_step) — never in a stray file on disk, never fabricated.
A not-ready target returns repair ACTIONS for the director; nothing is auto-created.

The registries are committed config under research_agent_teams/workspace/registries/ (a FIXED package
path, independent of the mutable RAT_WORKSPACE_ROOT runtime-state dir, so they are always loadable).
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, Optional, Tuple

import yaml

from research_agent_teams.tools import runstore

_PKG_ROOT = Path(__file__).resolve().parent.parent          # research_agent_teams/
STAGES = runstore.STAGES


def registries_root(root: Optional[str] = None) -> Path:
    """Where the committed stage / skill / bridge registries live. FIXED package path by default (NOT
    the mutable workspace-state dir), so the registries load regardless of RAT_WORKSPACE_ROOT; `root`
    overrides only for tests."""
    return Path(root) if root else (_PKG_ROOT / "workspace" / "registries")


def _load(name: str, root: Optional[str] = None) -> dict:
    p = registries_root(root) / name
    data = yaml.safe_load(p.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{p} must parse to a mapping")
    return data


def load_stages(root: Optional[str] = None) -> Dict[str, dict]:
    out: Dict[str, dict] = {}
    for s in _load("stage_registry.yaml", root).get("stages", []):
        stage = s.get("stage")
        if stage not in STAGES:
            raise ValueError(f"stage_registry: {stage!r} is not a real FSM stage {STAGES}")
        out[stage] = s
    return out


def load_skills(root: Optional[str] = None) -> Dict[str, dict]:
    out: Dict[str, dict] = {}
    for s in _load("skill_registry.yaml", root).get("skills", []):
        sid = s.get("skill_id")
        if not sid:
            raise ValueError("skill_registry: every entry needs a skill_id")
        if s.get("stage") not in STAGES:
            raise ValueError(f"skill_registry: skill {sid!r} maps to non-stage {s.get('stage')!r}")
        out[sid] = s
    return out


def load_bridges(root: Optional[str] = None) -> Dict[str, dict]:
    out: Dict[str, dict] = {}
    for b in _load("bridge_registry.yaml", root).get("bridges", []):
        bid = b.get("bridge_id")
        if not bid:
            raise ValueError("bridge_registry: every entry needs a bridge_id")
        for key in ("from_stage", "to_stage"):
            if b.get(key) not in STAGES:
                raise ValueError(f"bridge_registry: bridge {bid!r} {key}={b.get(key)!r} is not a stage")
        out[bid] = b
    return out


# --------------------------------------------------------------------------- manifest-grounded readiness

def _manifest_facts(run_dir) -> Tuple[dict, list, Optional[str]]:
    m = runstore.read_manifest(run_dir)
    completed = [w.get("stage") for w in (m.get("completed_work") or [])]
    nxt = (m.get("next_step") or {}).get("stage") if m.get("next_step") else None
    return m, completed, nxt


def stage_readiness(run_dir, target_stage: str) -> dict:
    """Is `target_stage` runnable on this run RIGHT NOW? Grounded in the manifest, never fabricated.

    ready        -> target is exactly the run's pending next_step
    already_done -> target is already committed (re-running would duplicate; start a new run)
    rejected     -> the run was vetoed (terminal)
    done         -> the run is complete (no pending stage)
    needs_prior  -> target is a FUTURE stage; missing[] = the pending stages before it on this path
    not_in_path  -> target precedes next_step but was never committed (not on this run's path)
    """
    if target_stage not in STAGES:
        raise ValueError(f"unknown stage {target_stage!r} (real stages: {STAGES})")
    m, completed, nxt = _manifest_facts(run_dir)
    if m.get("status") == "rejected":
        return {"ready": False, "status": "rejected", "missing": [],
                "repair_actions": ["this run was vetoed at the director gate — start a NEW run to proceed"]}
    if target_stage in completed:
        return {"ready": False, "status": "already_done", "missing": [],
                "repair_actions": [f"stage {target_stage} is already committed on this run — "
                                   "run a later stage, or start a new run"]}
    if nxt is None:
        return {"ready": False, "status": "done", "missing": [],
                "repair_actions": ["this run is complete (no pending stage) — start a new run"]}
    if target_stage == nxt:
        return {"ready": True, "status": "ready", "missing": [], "repair_actions": []}
    i_next, i_target = STAGES.index(nxt), STAGES.index(target_stage)
    if i_target < i_next:
        return {"ready": False, "status": "not_in_path", "missing": [],
                "repair_actions": [f"this run's next pending stage is {nxt}; {target_stage} is behind it "
                                   "and was not part of this run's path"]}
    missing = [s for s in STAGES[i_next:i_target] if s not in completed]
    return {"ready": False, "status": "needs_prior", "missing": missing,
            "repair_actions": ([f"run stage {missing[0]} first (run-stage --stage {missing[0]})"]
                               if missing else [])}


def skill_readiness(run_dir, skill_id: str, root: Optional[str] = None) -> dict:
    """A skill runs within its stage. Ready if that stage is the run's current stage OR already
    committed (a committed stage can still be re-mined by a skill). Otherwise the stage's repair."""
    sk = load_skills(root).get(skill_id)
    if sk is None:
        raise ValueError(f"unknown skill {skill_id!r}")
    stage = sk["stage"]
    m, completed, nxt = _manifest_facts(run_dir)
    base = {"skill": skill_id, "stage": stage}
    if m.get("status") == "rejected":
        return {**base, "ready": False, "status": "rejected", "missing": [],
                "repair_actions": ["this run was vetoed — start a new run"]}
    if stage in completed or stage == nxt:
        return {**base, "ready": True, "status": ("stage_done" if stage in completed else "ready"),
                "missing": [], "repair_actions": []}
    return {**base, **stage_readiness(run_dir, stage)}


def bridge_readiness(run_dir, bridge_id: str, root: Optional[str] = None) -> dict:
    """A bridge A->B is ready when A is committed AND B is the run's pending next stage."""
    br = load_bridges(root).get(bridge_id)
    if br is None:
        raise ValueError(f"unknown bridge {bridge_id!r}")
    frm, to = br["from_stage"], br["to_stage"]
    m, completed, nxt = _manifest_facts(run_dir)
    base = {"bridge": bridge_id, "from_stage": frm, "to_stage": to}
    if m.get("status") == "rejected":
        return {**base, "ready": False, "status": "rejected", "missing": [],
                "repair_actions": ["this run was vetoed — start a new run"]}
    if frm in completed and to == nxt:
        return {**base, "ready": True, "status": "ready", "missing": [], "repair_actions": []}
    missing = [] if frm in completed else [frm]
    repair = ([f"commit stage {frm} first (it produces this bridge's inputs)"] if missing
              else [f"this run's next pending stage is {nxt}, not {to} — the bridge does not apply here"])
    return {**base, "ready": False, "status": "needs_prior", "missing": missing, "repair_actions": repair}
