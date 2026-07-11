"""Workspace control plane — the machine-side "today's research" view.

Sits ON TOP of the existing project dimension (tools/projects.py) WITHOUT changing it:

 - workspace_state.yaml : the active-project pointer + last_touched (the only mutable global state).
 - project_index()      : a DERIVED list of projects — reuses ``projects.list_projects`` (which mirrors
                          the vault registry and NEVER writes it), enriched with lifecycle status.
 - dashboard(slug)      : a per-project snapshot derived from the latest run manifests + resource
                          bindings (current stage / blockers / recent runs / bound resources).

The vault registry stays the identity source of truth; everything here is a derived, regenerable
mirror. Nothing in this module writes the vault.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import List, Optional

import yaml

from research_agent_teams.tools import projects as pj
from research_agent_teams.tools import resources as rp
from research_agent_teams.tools import runstore
from research_agent_teams.tools.lease_manager import workspace_root
from research_agent_teams.tools.scope_guard import discover_projects_root, discover_vault_root

_PKG_ROOT = Path(__file__).resolve().parent.parent          # research_agent_teams/


def _runs_dir(runs_dir: Optional[str]) -> Path:
    if runs_dir:
        return Path(runs_dir)
    return Path(os.environ.get("RAT_RUNS_DIR") or (_PKG_ROOT / "runs"))


def _projects_root(projects_root: Optional[str]) -> Path:
    return Path(projects_root) if projects_root else Path(discover_projects_root())


# --------------------------------------------------------------------------- workspace_state

def state_path(ws_root: Optional[str] = None) -> Path:
    return workspace_root(ws_root) / "workspace_state.yaml"


def read_workspace_state(ws_root: Optional[str] = None) -> dict:
    p = state_path(ws_root)
    if not p.exists():
        return {"schema_version": 1, "active_project": None, "last_touched": None}
    return yaml.safe_load(p.read_text(encoding="utf-8")) or {}


def set_active_project(slug: Optional[str], ts: str, ws_root: Optional[str] = None) -> dict:
    """Point the workspace at a project (or None). Records last_touched; does not validate the slug
    against the registry here (the caller / picker does that — this is just the pointer)."""
    st = read_workspace_state(ws_root)
    st.update({"schema_version": 1, "active_project": slug, "last_touched": ts})
    p = state_path(ws_root)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(yaml.safe_dump(st, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return st


# --------------------------------------------------------------------------- per-project derivation

def _current_stage(manifest: dict) -> Optional[str]:
    if manifest.get("status") == "done":
        return "REPORT"
    ns = manifest.get("next_step") or {}
    if ns.get("stage"):
        return ns["stage"]
    cw = manifest.get("completed_work") or []
    return cw[-1]["stage"] if cw else manifest.get("entry_stage")


def project_runs(slug: str, runs_dir: Optional[str] = None) -> List[dict]:
    """Recent runs for a project (newest first), read from their manifests. Read-only."""
    d = _runs_dir(runs_dir) / slug
    out: List[dict] = []
    if d.is_dir():
        for rd in d.iterdir():
            if not (rd.is_dir() and (rd / "manifest.yaml").is_file()):
                continue
            try:
                m = runstore.read_manifest(rd)
            except Exception:
                continue
            out.append({"run_id": m.get("run_id", rd.name), "mode": m.get("mode"),
                        "status": m.get("status"), "stage": _current_stage(m),
                        "updated_at": m.get("updated_at")})
    out.sort(key=lambda r: r.get("updated_at") or "", reverse=True)
    return out


def _blockers(latest: Optional[dict], bindings: dict) -> List[dict]:
    b: List[dict] = []
    if latest:
        if latest.get("status") == "rejected":
            b.append({"type": "run_rejected", "severity": "high",
                      "note": f"run {latest['run_id']} was vetoed at the director gate"})
        if latest.get("stage") in ("EXECUTE", "ANALYZE") and rp.binding_for(bindings, "primary_gpu") is None:
            b.append({"type": "no_gpu_binding", "severity": "high",
                      "note": "EXECUTE/ANALYZE needs a primary_gpu binding (server.honor.gpu)"})
    return b


def dashboard(slug: str, *, projects_root: Optional[str] = None, runs_dir: Optional[str] = None,
              vault_root: Optional[str] = None) -> dict:
    """A per-project snapshot derived from registry + run manifests + bindings. Read-only, regenerable."""
    proot = _projects_root(projects_root)
    vroot = vault_root if vault_root is not None else discover_vault_root()
    registered = pj.load_registered_projects(vroot)
    reg = registered.get(slug)
    bindings = rp.load_bindings(proot, slug)
    runs = project_runs(slug, runs_dir)
    latest = runs[0] if runs else None

    # lifecycle status is owned by lifecycle.py; read it without importing (avoid a cycle)
    lc_path = proot / slug / "lifecycle.yaml"
    lifecycle_status = "active"
    if lc_path.exists():
        lifecycle_status = (yaml.safe_load(lc_path.read_text(encoding="utf-8")) or {}).get("status", "active")

    resources = {b["alias"]: {"resource_ref": b.get("resource_ref"), "bound": True}
                 for b in bindings.get("bindings", []) if b.get("alias")}

    return {
        "project": slug,
        "registered": reg is not None,
        "registry_status": reg["status"] if reg else None,
        "lifecycle_status": lifecycle_status,
        "current_stage": latest["stage"] if latest else None,
        "workspace": (proot / slug).is_dir(),
        "blockers": _blockers(latest, bindings),
        "recent_runs": runs[:5],
        "resources": resources,
    }


# --------------------------------------------------------------------------- index

def project_index(*, projects_root: Optional[str] = None, runs_dir: Optional[str] = None,
                  vault_root: Optional[str] = None, include_hidden: bool = False) -> List[dict]:
    """One row per project (union of registry + workspaces + run groups) enriched with lifecycle status
    + current stage. Reuses projects.list_projects (vault registry mirror, read-only). Hidden
    (archived / soft_deleted) projects are excluded unless include_hidden."""
    proot = _projects_root(projects_root)
    rroot = _runs_dir(runs_dir)
    vroot = vault_root if vault_root is not None else discover_vault_root()
    rows = []
    for r in pj.list_projects(proot, rroot, vroot):
        slug = r["project"]
        if slug == "(no-project)":
            rows.append(r)
            continue
        lc_path = proot / slug / "lifecycle.yaml"
        lc = "active"
        if lc_path.exists():
            lc = (yaml.safe_load(lc_path.read_text(encoding="utf-8")) or {}).get("status", "active")
        if lc in ("archived", "soft_deleted", "purged") and not include_hidden:
            continue
        runs = project_runs(slug, runs_dir)
        rows.append({**r, "lifecycle_status": lc,
                     "current_stage": runs[0]["stage"] if runs else None,
                     "last_run": runs[0]["run_id"] if runs else None})
    return rows


def write_project_state(slug: str, ts: str, *, projects_root: Optional[str] = None,
                        runs_dir: Optional[str] = None, vault_root: Optional[str] = None) -> Path:
    """Cache a dashboard() snapshot to projects/<slug>/project_state.yaml (DERIVED — regenerable)."""
    proot = _projects_root(projects_root)
    snap = dashboard(slug, projects_root=projects_root, runs_dir=runs_dir, vault_root=vault_root)
    snap["generated_at"] = ts
    snap["_note"] = "DERIVED snapshot — regenerated by workspace.write_project_state; NOT the identity source"
    out = proot / slug / "project_state.yaml"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(yaml.safe_dump(snap, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return out
