"""Project lifecycle — archive / soft-delete / hard-purge / restore over a project's MACHINE-SIDE
footprint, with GC safety.

Sits on top of ``tools/projects.delete_project`` (which already fences the vault + demands a typed
confirmation). Hard rules:
  - hard_purge NEVER touches the vault (System D) and NEVER deletes shared pool resources — it removes
    only ``projects/<slug>`` + ``runs/<slug>`` machine-side scratch, and refuses while the project has
    an active run, an active lease, or promoted vault claims (unless explicitly overridden).
  - soft_delete is REVERSIBLE: it hides the project + revokes its active leases, but deletes nothing —
    the artifacts remain on disk for restore, and the audit log + promoted claims are preserved.

Lifecycle states: active | paused | archived | soft_deleted | purge_pending | purged.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import List, Optional

import yaml

from research_agent_teams.tools import projects as pj
from research_agent_teams.tools import runstore
from research_agent_teams.tools.lease_manager import LeaseManager, workspace_root
from research_agent_teams.tools.scope_guard import discover_projects_root, discover_vault_root

_PKG_ROOT = Path(__file__).resolve().parent.parent

ALLOWED_STATES = {"active", "paused", "archived", "soft_deleted", "purge_pending", "purged"}
_HIDDEN_STATES = {"archived", "soft_deleted", "purged"}


def _projects_root(projects_root: Optional[str]) -> Path:
    return Path(projects_root) if projects_root else Path(discover_projects_root())


def _runs_dir(runs_dir: Optional[str]) -> Path:
    if runs_dir:
        return Path(runs_dir)
    return Path(os.environ.get("RAT_RUNS_DIR") or (_PKG_ROOT / "runs"))


def lifecycle_path(projects_root, slug: str) -> Path:
    return _projects_root(projects_root) / slug / "lifecycle.yaml"


def _tombstone_path(ws_root=None) -> Path:
    """Central record of purged projects (their per-project dir is gone, so the marker lives here)."""
    return workspace_root(ws_root) / "purged_projects.jsonl"


def is_purged(slug: str, ws_root=None) -> bool:
    p = _tombstone_path(ws_root)
    if not p.exists():
        return False
    for line in p.read_text(encoding="utf-8").splitlines():
        try:
            if json.loads(line).get("project") == slug:
                return True
        except Exception:
            continue
    return False


def read_lifecycle(projects_root, slug: str, ws_root=None) -> dict:
    p = lifecycle_path(projects_root, slug)
    if p.exists():
        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        data.setdefault("project", slug)
        data.setdefault("status", "active")
        data.setdefault("transitions", [])
        return data
    if is_purged(slug, ws_root):                 # dir gone but purge is terminal — honor the tombstone
        return {"project": slug, "status": "purged", "transitions": []}
    return {"project": slug, "status": "active", "transitions": []}


def _write_lifecycle(projects_root, slug: str, data: dict) -> None:
    p = lifecycle_path(projects_root, slug)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")


def transition(slug: str, to: str, ts: str, *, projects_root: Optional[str] = None,
               by: str = "director", reason: str = "") -> dict:
    if to not in ALLOWED_STATES:
        raise ValueError(f"invalid lifecycle state {to!r} (allowed: {sorted(ALLOWED_STATES)})")
    proot = _projects_root(projects_root)
    data = read_lifecycle(proot, slug)
    if data["status"] == "purged" and to != "purged":
        raise ValueError(f"project {slug!r} is purged (terminal) — cannot transition to {to!r}")
    data["status"] = to
    data["transitions"].append({"to": to, "at": ts, "by": by, "reason": reason})
    _write_lifecycle(proot, slug, data)
    return data


# --------------------------------------------------------------------------- simple transitions

def archive(slug: str, ts: str, *, projects_root: Optional[str] = None, reason: str = "") -> dict:
    """Hide from the active picker; keep everything. Fully reversible via restore."""
    return transition(slug, "archived", ts, projects_root=projects_root, reason=reason or "archived")


def pause(slug: str, ts: str, *, projects_root: Optional[str] = None, reason: str = "") -> dict:
    return transition(slug, "paused", ts, projects_root=projects_root, reason=reason or "paused")


def restore(slug: str, ts: str, *, projects_root: Optional[str] = None,
            workspace_root_path: Optional[str] = None) -> dict:
    """Bring an archived / soft_deleted project back to active. A purged project cannot be restored."""
    proot = _projects_root(projects_root)
    data = read_lifecycle(proot, slug, workspace_root_path)
    if data["status"] == "purged":
        raise ValueError(f"project {slug!r} is purged — its machine-side footprint is gone; "
                         "re-create it (the vault registry + any promoted knowledge survive)")
    return transition(slug, "active", ts, projects_root=projects_root, reason="restored")


# --------------------------------------------------------------------------- soft delete (reversible)

def soft_delete(slug: str, ts: str, *, projects_root: Optional[str] = None,
                workspace_root_path: Optional[str] = None, reason: str = "") -> dict:
    """Reversible removal: mark soft_deleted (hidden + scheduled work disabled) and REVOKE the project's
    active leases. Deletes NOTHING — artifacts stay on disk for restore; the audit log + promoted vault
    claims are preserved. (Physical removal is a separate, guarded hard_purge.)"""
    proot = _projects_root(projects_root)
    lm = LeaseManager(workspace_root_path)
    revoked = []
    for lease in lm.active_leases():
        if lease.get("project") == slug:
            lm.revoke(lease["lease_id"], reason=f"project {slug} soft-deleted")
            revoked.append(lease["lease_id"])
    data = transition(slug, "soft_deleted", ts, projects_root=proot,
                      reason=reason or "soft-deleted (reversible)")
    data["leases_revoked"] = revoked
    _write_lifecycle(proot, slug, data)
    return {"project": slug, "status": "soft_deleted", "leases_revoked": revoked,
            "note": "reversible — artifacts retained on disk; audit + promoted claims preserved; "
                    "run `restore` to reactivate or `hard_purge` to remove machine-side scratch"}


# --------------------------------------------------------------------------- hard purge (guarded)

def _active_run_ids(slug: str, runs_dir) -> List[str]:
    d = _runs_dir(runs_dir) / slug
    out = []
    if d.is_dir():
        for rd in d.iterdir():
            if rd.is_dir() and (rd / "manifest.yaml").is_file():
                try:
                    if runstore.read_manifest(rd).get("status") == "running":
                        out.append(rd.name)
                except Exception:
                    continue
    return out


def _active_lease_ids(slug: str, workspace_root_path: Optional[str]) -> List[str]:
    lm = LeaseManager(workspace_root_path)
    return [l["lease_id"] for l in lm.active_leases() if l.get("project") == slug]


def has_promoted_claims(slug: str, vault_root=None) -> bool:
    """True if the vault holds any page tagged `project: "<slug>"` (promoted knowledge to preserve)."""
    vr = vault_root if vault_root is not None else discover_vault_root()
    if not vr:
        return False
    wiki = Path(vr) / "02-wiki"
    if not wiki.is_dir():
        return False
    needle = f'project: "{slug}"'
    for md in wiki.rglob("*.md"):
        try:
            if needle in md.read_text(encoding="utf-8"):
                return True
        except Exception:
            continue
    return False


def hard_purge(slug: str, ts: str, *, confirm: str, projects_root: Optional[str] = None,
               runs_dir: Optional[str] = None, vault_root=None,
               workspace_root_path: Optional[str] = None, allow_promoted: bool = False) -> dict:
    """Physically remove a project's machine-side scratch (projects/<slug> + runs/<slug>). GUARDED:
    requires a typed confirmation, the project to be hidden first (archived / soft_deleted), and NO
    active run / NO active lease / NO promoted vault claims (unless allow_promoted). NEVER touches the
    vault or shared pool resources (delegates the delete to projects.delete_project, vault-fenced)."""
    proot = _projects_root(projects_root)
    if confirm != slug:
        raise ValueError(f"confirmation mismatch: pass confirm={slug!r} to hard-purge project {slug!r}")

    status = read_lifecycle(proot, slug)["status"]
    if status not in ("archived", "soft_deleted", "purge_pending"):
        raise ValueError(
            f"refusing hard_purge: project {slug!r} is {status!r} — archive or soft_delete it first "
            "(hard_purge only removes a project that was already taken out of active service)")

    active_runs = _active_run_ids(slug, runs_dir)
    if active_runs:
        raise ValueError(f"refusing hard_purge: project {slug!r} has active (running) runs {active_runs}")

    active_leases = _active_lease_ids(slug, workspace_root_path)
    if active_leases:
        raise ValueError(f"refusing hard_purge: project {slug!r} has active leases {active_leases} "
                         "(soft_delete first to revoke them)")

    if not allow_promoted and has_promoted_claims(slug, vault_root):
        raise ValueError(
            f"refusing hard_purge: project {slug!r} has PROMOTED knowledge in the vault — that is the "
            "crown jewels. Pass allow_promoted=True only if you understand the machine scratch is gone "
            "while the vault pages (and the registry row) remain.")

    # delegate the actual delete — projects.delete_project re-fences the vault + demands the same confirm
    result = pj.delete_project(proot, _runs_dir(runs_dir), slug, confirm=confirm, vault_root=vault_root)
    # the project dir is gone — record the terminal 'purged' state in the CENTRAL tombstone (writing a
    # per-project lifecycle.yaml here would recreate the just-deleted directory).
    tomb = _tombstone_path(workspace_root_path)
    tomb.parent.mkdir(parents=True, exist_ok=True)
    with tomb.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"project": slug, "purged_at": ts}, ensure_ascii=False) + "\n")
    result["lifecycle_status"] = "purged"
    result["note"] = ("machine-side scratch removed; the vault (promoted knowledge + registry row) and "
                      "the shared resource pool are untouched")
    return result
