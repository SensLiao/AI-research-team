"""Deterministic scan of the knowledge base + the machine, for the pre-task briefing.

Director lock (2026-08-01): "每次做任务前，先计划，扫描 database 然后汇报给我看计划".
This module is the SCAN half.  It reads only — it never starts a run, never
writes the vault, never resolves a credential.  Every number it reports comes
from a file on disk, so a briefing can never invent a fact.

Each section degrades independently: a missing vault, an unregistered project or
an unreadable resource pool yields an honest `available: False` entry instead of
raising, because a briefing must still render when part of the world is absent.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from ..tools import projects as projects_tool
from ..tools import recall as recall_tool
from ..tools import research_plan
from ..tools import resources as resources_tool
from ..tools import workspace as workspace_tool
from ..tools.scope_guard import discover_vault_root

# The order the director likes to read kinds in.  This controls ORDER ONLY — the set of
# kinds is enumerated from disk (see `scan_vault`), because a hardcoded set silently hides
# whole folders: this tuple used to BE the set, and it listed a `risks` folder that does not
# exist while omitting `comparisons` / `meetings` / `models` / `papers` — 47 real pages, about
# a tenth of the vault, that never reached a briefing.
_WIKI_READING_ORDER = (
    "sources", "papers", "concepts", "methods", "datasets", "experiments", "results",
    "ideas", "decisions", "syntheses", "protocols", "models", "comparisons", "meetings",
    "entities", "risks",
)

# Chinese labels where we have one; an unlabelled folder falls back to its own name so that a
# newly created kind still shows up instead of vanishing.
_WIKI_LABELS = {
    "sources": "论文与外部来源",
    "papers": "论文",
    "concepts": "概念定义",
    "methods": "方法",
    "datasets": "数据集",
    "experiments": "实验",
    "results": "结果",
    "ideas": "想法",
    "decisions": "决定",
    "syntheses": "综述与汇总",
    "protocols": "实验规程",
    "models": "模型",
    "comparisons": "对比",
    "meetings": "会议记录",
    "entities": "机构与人",
    "risks": "风险",
}


def wiki_kinds_on_disk(wiki: Path) -> list[str]:
    """Every kind folder that really exists, known ones first in reading order."""
    if not wiki.is_dir():
        return []
    present = {d.name for d in wiki.iterdir() if d.is_dir()}
    known = [kind for kind in _WIKI_READING_ORDER if kind in present]
    return known + sorted(present - set(known))

# Resources that can actually run a job vs. resources that can only be watched.
_EXECUTION_CAPABILITY = "submit_job"


def _safe(fn, default):
    """Run a read-only probe; a broken corner of the world degrades, never raises."""
    try:
        return fn()
    except Exception:  # noqa: BLE001 — a briefing must render even when a probe fails
        return default


def scan_vault(vault_root: Optional[str] = None) -> dict[str, Any]:
    """What the permanent knowledge base currently holds, counted by kind."""
    root = Path(vault_root or _safe(discover_vault_root, "") or "")
    wiki = root / "02-wiki"
    if not wiki.is_dir():
        return {"available": False, "root": str(root),
                "note": "没有找到知识库目录，这次任务只能靠现查的资料"}
    counts: list[dict[str, Any]] = []
    total = 0
    for folder in wiki_kinds_on_disk(wiki):
        n = len(list((wiki / folder).glob("*.md")))
        total += n
        if n:
            counts.append({"kind": folder, "label": _WIKI_LABELS.get(folder, folder),
                           "count": n})
    raw = root / "01-raw"
    inbox = len(list(raw.rglob("*.pdf"))) if raw.is_dir() else 0
    return {"available": True, "root": str(root), "total_pages": total,
            "by_kind": counts, "unprocessed_raw_files": inbox}


def scan_related_knowledge(request: str, *, vault_root: Optional[str] = None,
                           project: Optional[str] = None, top_k: int = 6) -> dict[str, Any]:
    """What the knowledge base ALREADY knows about this specific request."""
    root = vault_root or _safe(discover_vault_root, "")
    if not root or not Path(root).is_dir() or not (request or "").strip():
        return {"available": False, "hits": []}
    note = _safe(lambda: recall_tool.recall(request, vault_root=root,
                                            project=project, top_k=top_k), None)
    if not note:
        return {"available": False, "hits": []}
    citations = note.get("citations") or note.get("payload", {}).get("citations") or []
    hits = [{"slug": c.get("slug"), "section": c.get("section") or "",
             "why": c.get("supports") or ""}
            for c in citations if isinstance(c, dict) and c.get("slug")]
    return {"available": True, "hits": hits}


def scan_projects(*, projects_root: Optional[str] = None, runs_dir: Optional[str] = None,
                  vault_root: Optional[str] = None) -> dict[str, Any]:
    """Registered research projects and how much work each already carries."""
    root = vault_root if vault_root is not None else _safe(discover_vault_root, None)
    rows = _safe(lambda: projects_tool.list_projects(
        projects_root or "research_agent_teams/projects",
        runs_dir or str(Path(__file__).resolve().parents[1] / "runs"),
        root), [])
    return {"available": bool(rows), "projects": list(rows)}


def scan_recent_runs(project: Optional[str], *, runs_dir: Optional[str] = None,
                     limit: int = 3) -> dict[str, Any]:
    """The project's most recent runs — where the last one stopped, and why."""
    if not project:
        return {"available": False, "runs": []}
    rows = _safe(lambda: workspace_tool.project_runs(project, runs_dir), [])
    return {"available": bool(rows), "runs": list(rows)[:limit]}


def scan_resources(*, resources_root_path: Optional[str] = None) -> dict[str, Any]:
    """What compute and search the team may use, split by "can run" vs "can only watch".

    A resource DECLARES what its hardware could support; whether the team may
    actually use it is a separate governance fact.  The briefing must never show
    a declared `submit_job` on a machine whose status blocks execution — that
    would read as "we can train here" when we cannot.  So watch-only rows report
    their EFFECTIVE capabilities and, when the registry says why, the blocker.
    """
    registry = _safe(lambda: resources_tool.load_registry(resources_root_path), {})
    pool = _safe(lambda: resources_tool.pool_overview(
        resources_root_path=resources_root_path), [])
    can_run, watch_only, other = [], [], []
    for row in pool:
        rid = row.get("resource_id")
        declared = list(row.get("capabilities") or [])
        full = registry.get(rid) or {}
        entry = {"resource_id": rid,
                 "display_name": row.get("display_name") or rid,
                 "status": row.get("status"), "declared_capabilities": declared}
        if not str(row.get("type") or "").startswith("hardware"):
            entry["capabilities"] = declared
            other.append(entry)
            continue
        usable = _EXECUTION_CAPABILITY in declared and bool(full.get("execution_ready"))
        if usable:
            entry["capabilities"] = declared
            can_run.append(entry)
            continue
        # Effective, not declared: strip the capability governance currently denies.
        entry["capabilities"] = [c for c in declared if c != _EXECUTION_CAPABILITY]
        entry["blocked_from_running"] = True
        entry["blockers"] = [str(b) for b in (full.get("execution_blockers") or [])]
        watch_only.append(entry)
    return {"available": bool(pool), "compute_ready": can_run,
            "compute_watch_only": watch_only, "other": other}


def scan_capabilities() -> dict[str, Any]:
    """The single source of truth for what the team can actually do one-button today."""
    wired = sorted(_safe(research_plan.wired_modes, set()))
    every = sorted(_safe(research_plan.all_modes, set()))
    return {"available": bool(every),
            "one_button": wired,
            "design_only": [m for m in every if m not in set(wired)]}


def scan_all(request: str, *, project: Optional[str] = None,
             vault_root: Optional[str] = None, projects_root: Optional[str] = None,
             runs_dir: Optional[str] = None,
             resources_root_path: Optional[str] = None) -> dict[str, Any]:
    """One read-only sweep of everything a pre-task briefing needs."""
    return {
        "request": request,
        "project": project,
        "vault": scan_vault(vault_root),
        "related_knowledge": scan_related_knowledge(
            request, vault_root=vault_root, project=project),
        "projects": scan_projects(projects_root=projects_root, runs_dir=runs_dir,
                                  vault_root=vault_root),
        "recent_runs": scan_recent_runs(project, runs_dir=runs_dir),
        "resources": scan_resources(resources_root_path=resources_root_path),
        "capabilities": scan_capabilities(),
    }


__all__ = [
    "wiki_kinds_on_disk",
    "scan_all",
    "scan_capabilities",
    "scan_projects",
    "scan_recent_runs",
    "scan_related_knowledge",
    "scan_resources",
    "scan_vault",
]
