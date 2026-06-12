"""Project-workspace layer — the per-project resource dimension of the machine.

A research PROJECT (one paper / thesis chapter / experiment programme) groups every machine-side
resource that belongs to it:

  runs/<project>/<run_id>/        grouped scratch runs (legacy flat runs/<run_id>/ still readable)
  projects/<project>/             the durable per-project workspace: pulled results, scripts,
                                  figures, notes that are NOT (yet) vault-grade
  <remote workdir>/<project>/<run_id>   the GPU server's per-project grouping (execute layer)

Ground rules (the seam with System D):
  - A project slug is lowercase-kebab AND must be registered in the vault's
    `05-registry/project-registry.md` — the single source of truth, so the machine and the DB
    always agree on what a project is. The registry is READ here, never written (crown-jewel).
  - Deleting a project removes ONLY machine-side scratch (projects/<slug> + runs/<slug>). The
    vault is NEVER touched: promoted knowledge stays in the permanent library, and the registry
    row is flipped by the director (status: completed/abandoned), not by this module.
  - Deletion demands a typed confirmation (confirm == slug) — easy, but never accidental.
"""
from __future__ import annotations

import os
import re
import shutil
from pathlib import Path
from typing import Dict, List, Optional

from research_agent_teams.tools.scope_guard import discover_vault_root

# Same kebab discipline as vault slugs (schema-contract §5); a strict subset of the execute layer's
# _RUN_ID_RE, so a project slug is always safe as a remote path segment and inside a tmux name.
PROJECT_SLUG_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
MAX_SLUG_LEN = 50

REGISTRY_REL = Path("05-registry") / "project-registry.md"

# registry statuses that refuse NEW machine work (the director closed the project)
_CLOSED_STATUSES = {"completed", "abandoned"}

_WORKSPACE_SUBDIRS = ("results", "scripts", "figures", "notes")

_WORKSPACE_README = """# Project workspace: {slug}

Machine-side durable resources for the `{slug}` research project — pulled experiment results,
scripts, figures and notes that are NOT (yet) vault-grade. Validated knowledge enters the vault
only via the human `/promote-to-vault` gate; everything here is deletable scratch.

- `results/`  pulled experiment outputs (execute layer `pull` lands per-run results here or in runs/)
- `scripts/`  project-owned runnable scripts (training / eval / analysis)
- `figures/`  plots and visualisations
- `notes/`    working notes

Delete the whole project's machine-side footprint with:
`python -m research_agent_teams.operate project-delete --project {slug} --confirm {slug}`
"""


# --------------------------------------------------------------------------- registry (read-only)

def registry_path(vault_root) -> Path:
    return Path(vault_root) / REGISTRY_REL


def parse_registry(text: str) -> Dict[str, dict]:
    """Parse the project rows out of the registry markdown. Robust to prose around the tables:
    any pipe-table whose header contains a `project-slug` column contributes rows. Returns
    {slug: {"slug", "title", "status"}} — unknown/malformed rows are skipped, never fatal."""
    projects: Dict[str, dict] = {}
    header_cols: Optional[List[str]] = None
    for line in text.splitlines():
        s = line.strip()
        if not (s.startswith("|") and s.endswith("|") and len(s) > 1):
            header_cols = None
            continue
        cells = [c.strip() for c in s.strip("|").split("|")]
        if any(set(c) <= {"-", ":", " "} and c for c in cells):
            continue                                   # the |---|---| separator row
        if "project-slug" in cells:
            header_cols = cells                        # a header row that defines the columns
            continue
        if header_cols is None:
            continue                                   # a table we don't recognize
        row = dict(zip(header_cols, cells))
        slug = (row.get("project-slug") or "").strip().strip("`")
        if not PROJECT_SLUG_RE.match(slug):
            continue                                   # schema/example rows etc.
        projects[slug] = {"slug": slug,
                          "title": row.get("title", ""),
                          "status": (row.get("status") or "").strip().lower()}
    return projects


def has_registry(vault_root) -> bool:
    """True iff this vault root HAS a project-registry file (regardless of parseability)."""
    return bool(vault_root) and registry_path(vault_root).exists()


def load_registered_projects(vault_root) -> Dict[str, dict]:
    """The registered projects of a vault, or {} when the vault has no registry (bare test trees)."""
    if not has_registry(vault_root):
        return {}
    return parse_registry(registry_path(vault_root).read_text(encoding="utf-8"))


def require_project(slug: str, vault_root=None) -> dict:
    """Validate a project slug for NEW machine work. Raises ValueError with an actionable message.

    Rules: kebab format (always) ; when the vault HAS a registry, the slug must be registered and
    not closed (completed/abandoned). A registry file that exists but parses to ZERO rows fails
    CLOSED (a malformed/emptied registry must not silently disable the gate). Only a vault with NO
    registry file at all (isolated test tree) gets the format-only check — the real two-repo layout
    always has one, so production is always enforced."""
    slug = (slug or "").strip()
    if not PROJECT_SLUG_RE.match(slug) or len(slug) > MAX_SLUG_LEN:
        raise ValueError(
            f"invalid project slug {slug!r}: must be lowercase-kebab (e.g. 'iac-cbct-seg'), "
            f"max {MAX_SLUG_LEN} chars")
    registered = load_registered_projects(vault_root)
    if not registered:
        if has_registry(vault_root):
            raise ValueError(
                f"project registry {REGISTRY_REL} exists but contains no parseable project rows — "
                f"cannot validate {slug!r} (fail-closed). Fix the registry table (header must "
                "include a 'project-slug' column)")
        return {"slug": slug, "registered": False, "status": None,
                "note": "no project registry found at this vault root — format-only check"}
    row = registered.get(slug)
    if row is None:
        raise ValueError(
            f"project {slug!r} is not registered in {REGISTRY_REL} (known: {sorted(registered)}). "
            "Register it there first — the registry is the single source of truth for projects "
            "(the machine never writes it; the director adds the row)")
    if row["status"] in _CLOSED_STATUSES:
        raise ValueError(
            f"project {slug!r} is {row['status']} in the registry — closed projects take no new "
            "machine work (flip its status in the registry to reopen)")
    return {"slug": slug, "registered": True, "status": row["status"]}


# --------------------------------------------------------------------------- workspace

def workspace_dir(projects_root, slug: str) -> Path:
    return Path(projects_root) / slug


def ensure_workspace(projects_root, slug: str) -> dict:
    """Create projects/<slug>/{results,scripts,figures,notes} (+ README) if missing. Idempotent."""
    if not PROJECT_SLUG_RE.match(slug or ""):
        raise ValueError(f"invalid project slug {slug!r}")
    ws = workspace_dir(projects_root, slug)
    created = not ws.exists()
    for sub in _WORKSPACE_SUBDIRS:
        (ws / sub).mkdir(parents=True, exist_ok=True)
    readme = ws / "README.md"
    if not readme.exists():
        readme.write_text(_WORKSPACE_README.format(slug=slug), encoding="utf-8")
    return {"project": slug, "workspace": str(ws), "created": created,
            "subdirs": list(_WORKSPACE_SUBDIRS)}


# --------------------------------------------------------------------------- overview

def _count_runs(project_runs_dir: Path) -> int:
    if not project_runs_dir.is_dir():
        return 0
    return sum(1 for d in project_runs_dir.iterdir()
               if d.is_dir() and (d / "manifest.yaml").is_file())


def list_projects(projects_root, runs_dir, vault_root=None) -> List[dict]:
    """One row per project the machine knows about (union of registry + workspaces + run groups),
    plus a trailing '(no-project)' row counting legacy flat runs. Read-only."""
    registered = load_registered_projects(vault_root if vault_root is not None else discover_vault_root())
    slugs = set(registered)
    proot, rroot = Path(projects_root), Path(runs_dir)
    if proot.is_dir():
        slugs.update(d.name for d in proot.iterdir() if d.is_dir() and PROJECT_SLUG_RE.match(d.name))
    legacy_flat = 0
    if rroot.is_dir():
        for d in rroot.iterdir():
            if not d.is_dir():
                continue
            if (d / "manifest.yaml").is_file():
                legacy_flat += 1                          # a flat (pre-project) run
            elif PROJECT_SLUG_RE.match(d.name) and _count_runs(d):
                slugs.add(d.name)                         # a project run-group
    rows = []
    for slug in sorted(slugs):
        row = registered.get(slug)
        rows.append({"project": slug,
                     "registered": row is not None,
                     "status": row["status"] if row else None,
                     "workspace": (proot / slug).is_dir(),
                     "runs": _count_runs(rroot / slug)})
    if legacy_flat:
        rows.append({"project": "(no-project)", "registered": False, "status": None,
                     "workspace": False, "runs": legacy_flat,
                     "note": "legacy flat runs predating the project dimension"})
    return rows


# --------------------------------------------------------------------------- deletion (machine-side only)

def delete_project(projects_root, runs_dir, slug: str, *, confirm: str,
                   vault_root=None) -> dict:
    """Delete a project's ENTIRE machine-side footprint: projects/<slug> + runs/<slug>.

    Safety: typed confirmation (confirm == slug); the vault is NEVER touched — each target is
    re-checked against the (discovered) vault root and the call refuses if one resolves inside it
    (defence-in-depth; cannot happen in the normal layout). Promoted knowledge survives by design."""
    if not PROJECT_SLUG_RE.match(slug or ""):
        raise ValueError(f"invalid project slug {slug!r}")
    if confirm != slug:
        raise ValueError(
            f"confirmation mismatch: pass confirm={slug!r} (typed confirmation) to delete "
            f"project {slug!r} — refusing")
    targets = [workspace_dir(projects_root, slug), Path(runs_dir) / slug]
    # A legacy FLAT RUN named exactly like the project slug has its manifest.yaml at the group
    # root — that is one run, not this project's run-group. Refuse rather than silently destroy it.
    if (targets[1] / "manifest.yaml").is_file():
        raise ValueError(
            f"refused: {targets[1]} is a legacy flat RUN whose id collides with project {slug!r} "
            "(manifest.yaml at its root), not a project run-group — remove/rename that run "
            "explicitly first")
    vr = vault_root if vault_root is not None else discover_vault_root()
    if vr:
        vroot = os.path.normcase(str(Path(vr).resolve()))
        for t in targets:
            tr = os.path.normcase(str(t.resolve()))
            if tr == vroot or tr.startswith(vroot + os.sep):
                raise PermissionError(
                    f"refused: {t} resolves inside the vault — project deletion is machine-side "
                    "only and never touches System D")
    runs_deleted = _count_runs(targets[1])
    deleted_paths = []
    for t in targets:
        if t.exists():
            shutil.rmtree(t)
            deleted_paths.append(str(t))
    return {"project": slug, "deleted_paths": deleted_paths, "runs_deleted": runs_deleted,
            "workspace_deleted": str(targets[0]) in deleted_paths,
            "note": "machine-side scratch removed; the vault (promoted knowledge + registry) is untouched"}
