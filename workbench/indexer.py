"""Build the projection rows by reading the machine and the vault.  Read-only, always.

Every mapping in here is grounded in a real on-disk contract, not invented:

* **The vault already separates the two axes** and says so —
  `05-registry/status-registry.md`: "Both fields coexist; they measure different things."
  So `status:` (draft/active/completed/deprecated/parked) is *lifecycle* and is carried
  through verbatim, while `result-status:` (provisional/frozen) is the *evidence* axis.
  `can-cite-thesis == (result-status == "frozen")` is the vault's own **derived** field and
  manual override is forbidden — we read it and never recompute it.
* **The task ledger states its own rule** —
  `records/n-task-ledger.json`: "a task is 'done' only with a real receipt path plus a
  checkable number or hash; narrative never sets status".  That is exactly
  `derive_evidence_state(has_executor_receipt=..., has_raw_result=...)`, so tasks are graded
  by that rule rather than by the word in their `status` field.
* **Directory kinds are enumerated from disk, never hardcoded.**  A hardcoded kind list is
  how `reporting/scan.py` came to miss `comparisons` / `meetings` / `models` / `papers`
  (47 pages, ~10% of the vault) while listing a `risks` folder that does not exist.

A project's own vocabulary is never flattened away: `TaskRow.source_status` and
`ArtifactRow.lifecycle` keep the source word so a reader can always see the original.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Iterable, Optional

from ..tools import projects as projects_tool
from ..tools import workspace as workspace_tool
from ..tools.scope_guard import discover_vault_root
from .model import (
    ArtifactRow,
    EvidenceState,
    ProjectRow,
    TaskRow,
    WorkState,
    derive_evidence_state,
)

_PKG_ROOT = Path(__file__).resolve().parent.parent          # research_agent_teams/

# Indexed body cap.  Enough for full-text recall, small enough that the store stays a cache.
_BODY_CHARS = 20_000

# Vault lifecycle words (05-registry/status-registry.md, universal `status:`).
_DEPRECATED = "deprecated"
_PARKED = "parked"

# Result-status words (the vault's evidence axis).
_FROZEN = "frozen"
_PROVISIONAL = "provisional"

# Project task words → work states.  The source word is preserved on the row regardless.
_TASK_WORK_STATE = {
    "DONE": WorkState.DONE,
    "COMPLETE": WorkState.DONE,
    "COMPLETED": WorkState.DONE,
    "NOT_STARTED": WorkState.BACKLOG,
    "TODO": WorkState.BACKLOG,
    "BACKLOG": WorkState.BACKLOG,
    "IN_PROGRESS": WorkState.ACTIVE,
    "ACTIVE": WorkState.ACTIVE,
    "WIP": WorkState.ACTIVE,
    "UNBLOCKED_PENDING_RERUN": WorkState.READY,
    "READY": WorkState.READY,
    "BLOCKED": WorkState.BLOCKED,
    "FORBIDDEN": WorkState.BLOCKED,
}
# Words that name a HUMAN as the thing being waited on → a decision is owed.
_NEEDS_DECISION_HINTS = ("PENDING_DIRECTOR", "AWAITING_DIRECTOR", "MUST_FREEZE", "NEEDS_DECISION")
# Words that name ANOTHER TASK as the thing being waited on → blocked, and by whom.
# e.g. `BUILT_PENDING_N04` is not a backlog item; it is built and waiting on N04.
_PENDING_ON = re.compile(r"PENDING_([A-Z0-9][A-Z0-9._\-]*)")

# A "checkable number or hash" per the ledger's own rule.
_CHECKABLE = re.compile(r"(sha256|[0-9a-f]{32,}|\d)", re.IGNORECASE)

_FRONTMATTER = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
_SCALAR = re.compile(r"^([A-Za-z][A-Za-z0-9_-]*)\s*:\s*(.*)$")


def _safe(fn, default):
    """Read-only probe; a broken corner degrades to a default instead of failing the build."""
    try:
        return fn()
    except Exception:  # noqa: BLE001 — the projection must build even when a corner is unreadable
        return default


def _read_text(path: Path, limit: int = _BODY_CHARS) -> str:
    return _safe(lambda: path.read_text(encoding="utf-8", errors="replace")[:limit], "")


def parse_frontmatter(text: str) -> dict[str, Any]:
    """Top-level scalars + simple list items from a YAML frontmatter block.

    Deliberately shallow: the projection only needs `title` / `status` / `result-status` /
    `type` / `updated` / `can-cite-thesis`.  Quotes are stripped because the vault contains
    both `status: active` and `status: "active"` — the same value serialized two ways.
    """
    match = _FRONTMATTER.match(text)
    if not match:
        return {}
    out: dict[str, Any] = {}
    key: Optional[str] = None
    for raw in match.group(1).splitlines():
        line = raw.rstrip()
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if line.lstrip().startswith("- ") and key:
            item = line.lstrip()[2:].strip().strip("'\"")
            bucket = out.setdefault(key, [])
            if isinstance(bucket, list):
                bucket.append(item)
            continue
        found = _SCALAR.match(line)
        if not found:
            continue
        key = found.group(1)
        value = found.group(2).strip()
        out[key] = [] if value == "" else value.strip("'\"")
    return out


def _title_from(text: str, fallback: str) -> str:
    for line in text.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return fallback


# --------------------------------------------------------------------------- vault

def vault_kinds(vault_root: Path) -> list[str]:
    """Enumerate wiki kinds FROM DISK.  Never a hardcoded list — that is how pages go missing."""
    wiki = vault_root / "02-wiki"
    if not wiki.is_dir():
        return []
    return sorted(d.name for d in wiki.iterdir() if d.is_dir())


def _vault_evidence(front: dict[str, Any], kind: str) -> tuple[EvidenceState, str]:
    """Read the vault's own two fields.  Never recompute `can-cite-thesis`."""
    lifecycle = str(front.get("status") or "").lower()
    if lifecycle == _DEPRECATED:
        return EvidenceState.SUPERSEDED, "库内标记为 deprecated —— 已被别的页面取代"
    result_status = str(front.get("result-status") or "").lower()
    can_cite = str(front.get("can-cite-thesis") or "").lower()
    if result_status == _FROZEN or can_cite == "true":
        return EvidenceState.FROZEN, "库自己的 result-status=frozen（can-cite-thesis 由它推导，本层只读不算）"
    if result_status == _PROVISIONAL:
        return EvidenceState.OBSERVED, "真测出来的数，但库标 provisional —— 不能当论文事实引用"
    if kind in {"results", "experiments"}:
        return EvidenceState.PROPOSED, "结果类页面但没有 result-status 字段 —— 按最弱处理"
    return EvidenceState.PROPOSED, "非结果类知识页面，本身不承载证据等级"


def index_vault(vault_root: Optional[str] = None) -> list[ArtifactRow]:
    root = Path(vault_root or _safe(discover_vault_root, "") or "")
    if not (root / "02-wiki").is_dir():
        return []
    rows: list[ArtifactRow] = []
    for kind in vault_kinds(root):
        for path in sorted((root / "02-wiki" / kind).glob("*.md")):
            text = _read_text(path)
            front = parse_frontmatter(text)
            state, reason = _vault_evidence(front, kind)
            rows.append(
                ArtifactRow(
                    artifact_id=f"vault:{kind}/{path.stem}",
                    project=str(front.get("project") or ""),
                    kind=str(front.get("type") or kind),
                    title=str(front.get("title") or _title_from(text, path.stem)),
                    path=str(path),
                    source="vault",
                    updated=str(front.get("updated") or ""),
                    evidence_state=state.value,
                    evidence_reason=reason,
                    lifecycle=str(front.get("status") or ""),
                    text=text,
                )
            )
    return rows


# --------------------------------------------------------------------------- runs

def _run_evidence(manifest: dict[str, Any], run_dir: Path) -> tuple[EvidenceState, str]:
    """A run's own bundles are not experimental evidence unless a receipt says so."""
    receipts = list((run_dir / "evidence").glob("*receipt*")) if (run_dir / "evidence").is_dir() else []
    raw = list((run_dir / "evidence").glob("*result*")) if (run_dir / "evidence").is_dir() else []
    verdict = derive_evidence_state(
        has_executor_receipt=bool(receipts),
        has_raw_result=bool(raw),
        ran_dry=str(manifest.get("status") or "").lower() in {"done", "complete", "completed"},
    )
    return verdict.state, verdict.reason


def index_runs(runs_dir: Optional[str] = None) -> list[ArtifactRow]:
    root = Path(runs_dir) if runs_dir else _PKG_ROOT / "runs"
    if not root.is_dir():
        return []
    rows: list[ArtifactRow] = []
    for manifest_path in sorted(root.glob("*/*/manifest.yaml")) + sorted(root.glob("*/manifest.yaml")):
        run_dir = manifest_path.parent
        manifest = {}
        for line in _read_text(manifest_path, 4000).splitlines():
            found = _SCALAR.match(line)
            if found:
                manifest[found.group(1)] = found.group(2).strip().strip("'\"")
        run_id = str(manifest.get("run_id") or run_dir.name)
        project = str(manifest.get("project") or "")
        state, reason = _run_evidence(manifest, run_dir)
        # The director-facing review packet is the artifact a human actually opens.
        for path in sorted(run_dir.glob("director-review/*.md")) or [manifest_path]:
            text = _read_text(path)
            rows.append(
                ArtifactRow(
                    artifact_id=f"run:{run_id}/{path.name}",
                    project=project,
                    kind=str(manifest.get("mode") or "run"),
                    title=_title_from(text, f"{run_id} · {path.name}"),
                    path=str(path),
                    source="run",
                    updated=str(manifest.get("updated_at") or manifest.get("created_at") or ""),
                    run_id=run_id,
                    evidence_state=state.value,
                    evidence_reason=reason,
                    lifecycle=str(manifest.get("status") or ""),
                    text=text,
                )
            )
    return rows


# --------------------------------------------------------------------------- project workspace

def _project_docs(slug: str, workspace: Path) -> list[ArtifactRow]:
    rows: list[ArtifactRow] = []
    for path in sorted(workspace.rglob("*.md")):
        if any(part.startswith(".") for part in path.relative_to(workspace).parts):
            continue
        text = _read_text(path)
        rel = path.relative_to(workspace).as_posix()
        rows.append(
            ArtifactRow(
                artifact_id=f"project:{slug}/{rel}",
                project=slug,
                kind=path.parent.name if path.parent != workspace else "workspace",
                title=_title_from(text, path.stem),
                path=str(path),
                source="machine",
                evidence_state=EvidenceState.PROPOSED.value,
                evidence_reason="项目工作区文档 —— 工作现场，不是已审的证据",
                text=text,
            )
        )
    return rows


def _task_work_state(word: str, blockers: tuple[str, ...]) -> tuple[WorkState, tuple[str, ...]]:
    """Map the project's own status word without discarding or over-promoting it.

    Order matters, and the curated table outranks the regex.  `UNBLOCKED_PENDING_RERUN`
    contains "PENDING" but means the opposite — it is unblocked and ready — so the explicit
    mapping must win; only a word the table does not know is guessed at.  A guessed
    `..._PENDING_<TASK>` (e.g. `BUILT_PENDING_N04`) blocks *and* names the dependency, so a
    reader sees the reason and not just the state.  Unrecognised words stay BACKLOG rather
    than being optimistically read as progress.
    """
    if any(hint in word for hint in _NEEDS_DECISION_HINTS):
        return WorkState.NEEDS_DECISION, blockers
    mapped = _TASK_WORK_STATE.get(word)
    if mapped is None:
        depends_on = _PENDING_ON.search(word)
        if depends_on:
            return WorkState.BLOCKED, blockers + (f"等 {depends_on.group(1)}",)
    if blockers and mapped is not WorkState.DONE:
        return WorkState.BLOCKED, blockers
    return mapped or WorkState.BACKLOG, blockers


def _ledger_path(workspace: Path) -> Path:
    return workspace / "records" / "n-task-ledger.json"


def _load_ledger(workspace: Path) -> dict[str, Any]:
    path = _ledger_path(workspace)
    if not path.is_file():
        return {}
    return _safe(lambda: json.loads(path.read_text(encoding="utf-8")), {})


def _pending_decision_rows(slug: str, ledger_path: Path, data: dict[str, Any]) -> list[TaskRow]:
    """The ledger keeps decisions owed to the director in their OWN array, not in `tasks`.

    Missing this array is how a home page comes to say "nothing is waiting on you" while two
    decisions sit unmade — the exact failure this workbench exists to prevent, so it is read
    explicitly rather than inferred from task words.
    """
    rows: list[TaskRow] = []
    for item in data.get("pending_director_decisions") or []:
        if not isinstance(item, dict) or not item.get("id"):
            continue
        rows.append(
            TaskRow(
                task_id=f"{slug}:decision:{item['id']}",
                project=slug,
                title=str(item.get("title") or item["id"]),
                work_state=WorkState.NEEDS_DECISION.value,
                evidence_state=EvidenceState.PROPOSED.value,
                evidence_reason="这是一个待你拍板的决定，不是一条证据",
                why_now=str(item.get("why_now") or ""),
                next_action=str(item.get("record") or ""),
                source_path=str(ledger_path),
                source_status=str(item.get("status") or ""),
            )
        )
    return rows


def ledger_boundaries(workspace: Path) -> tuple[str, ...]:
    """Boundaries the last run actually held — honest statements of what was NOT done."""
    data = _load_ledger(workspace)
    return tuple(
        f"（上次运行守住的）{line}"
        for line in (data.get("hard_boundaries_held_this_run") or [])
        if isinstance(line, str) and line.strip()
    )


def index_tasks(slug: str, workspace: Path) -> list[TaskRow]:
    """Grade tasks by the ledger's OWN rule: a receipt path plus a checkable number or hash."""
    ledger = _ledger_path(workspace)
    data = _load_ledger(workspace)
    if not data:
        return []
    rows: list[TaskRow] = []
    for task in data.get("tasks") or []:
        if not isinstance(task, dict) or not task.get("id"):
            continue
        word = str(task.get("status") or "").upper()
        blocked_by = task.get("blocked_by")
        blockers = tuple(
            str(b) for b in (blocked_by if isinstance(blocked_by, list) else [blocked_by] if blocked_by else [])
        )
        work, blockers = _task_work_state(word, blockers)

        facts = task.get("facts") if isinstance(task.get("facts"), dict) else {}
        checkable = bool(facts) and bool(_CHECKABLE.search(json.dumps(facts, ensure_ascii=False)))
        verdict = derive_evidence_state(
            has_executor_receipt=bool(task.get("evidence")),
            has_raw_result=checkable,
        )
        if verdict.state is EvidenceState.OBSERVED:
            # Be explicit about the scope of this receipt: it backs THIS task's own artifact.
            # It is not a scientific finding — that axis lives in the vault's `result-status`.
            reason = "这条任务自己有回执 + 可核对的数／哈希；只证明这项工作真做了，不代表科学结论成立"
        else:
            reason = verdict.reason
        rows.append(
            TaskRow(
                task_id=f"{slug}:{task['id']}",
                project=slug,
                title=str(task.get("name") or task["id"]),
                work_state=work.value,
                evidence_state=verdict.state.value,
                evidence_reason=reason,
                next_action=str(task.get("evidence") or ""),
                blockers=blockers,
                source_path=str(ledger),
                source_status=str(task.get("status") or ""),
            )
        )
    return rows + _pending_decision_rows(slug, ledger, data)


def _canonical_facts(workspace: Path) -> tuple[str, tuple[str, ...]]:
    """The frozen paper question and the truth boundary, read from the project's contract."""
    path = workspace / "CANONICAL-PROJECT.md"
    if not path.is_file():
        return "", ()
    lines = _read_text(path).splitlines()
    question, boundary, current = "", [], ""
    for line in lines:
        if line.startswith("## "):
            current = line[3:].strip().lower()
            continue
        body = line.strip()
        if not body or body.startswith(("|", "---", "```")):
            continue
        if "paper question" in current and not question:
            question = body.lstrip("*_ ").rstrip("*_")
        elif "truth boundary" in current and len(boundary) < 6:
            boundary.append(body.lstrip("-* ").strip())
    return question, tuple(boundary)


def index_projects(
    *,
    projects_root: Optional[str] = None,
    runs_dir: Optional[str] = None,
    vault_root: Optional[str] = None,
) -> tuple[list[ProjectRow], list[ArtifactRow], list[TaskRow]]:
    proot = Path(projects_root) if projects_root else _PKG_ROOT / "projects"
    rroot = str(Path(runs_dir) if runs_dir else _PKG_ROOT / "runs")
    vroot = vault_root if vault_root is not None else _safe(discover_vault_root, None)
    listed = _safe(lambda: projects_tool.list_projects(str(proot), rroot, vroot), [])
    active = str(
        _safe(lambda: workspace_tool.read_workspace_state().get("active_project"), "") or ""
    )

    projects: list[ProjectRow] = []
    artifacts: list[ArtifactRow] = []
    tasks: list[TaskRow] = []
    for row in listed:
        slug = str(row.get("project") or "")
        if not slug or slug == "(no-project)":
            continue
        workspace = proot / slug
        question, boundary = _canonical_facts(workspace)
        boundary = boundary + ledger_boundaries(workspace)
        docs = _project_docs(slug, workspace) if workspace.is_dir() else []
        project_tasks = index_tasks(slug, workspace) if workspace.is_dir() else []
        artifacts.extend(docs)
        tasks.extend(project_tasks)
        runs = _safe(lambda s=slug: workspace_tool.project_runs(s, rroot), [])
        latest = runs[0] if runs else {}
        blocked = tuple(
            t.title for t in project_tasks if t.work_state == WorkState.BLOCKED.value
        )
        decisions = tuple(
            t.title for t in project_tasks if t.work_state == WorkState.NEEDS_DECISION.value
        )
        projects.append(
            ProjectRow(
                slug=slug,
                title=slug,
                question=question,
                truth_boundary=boundary,
                lifecycle=str(row.get("status") or ("registered" if row.get("registered") else "unregistered")),
                active=slug == active,
                latest_run_id=str(latest.get("run_id") or ""),
                latest_run_stage=str(latest.get("stage") or latest.get("status") or ""),
                open_decisions=decisions,
                blockers=blocked,
                counts={
                    "runs": int(row.get("runs") or 0),
                    "docs": len(docs),
                    "tasks": len(project_tasks),
                    "decided": len(_load_ledger(workspace).get("director_decisions") or []),
                },
                home_path=str(workspace / "PROJECT-HOME.md"),
            )
        )
    return projects, artifacts, tasks


# --------------------------------------------------------------------------- capabilities

def index_capabilities() -> list[dict[str, Any]]:
    """One row per mode, flagged by whether it is really one-button today."""
    from ..tools import research_plan

    wired = set(_safe(research_plan.wired_modes, set()))
    every = sorted(_safe(research_plan.all_modes, set()))
    return [
        {"mode": mode, "one_button": mode in wired,
         "note": "一键可跑" if mode in wired else "只有定义，还没接线（不要当能跑的说）"}
        for mode in every
    ]


def build_projection(
    *,
    projects_root: Optional[str] = None,
    runs_dir: Optional[str] = None,
    vault_root: Optional[str] = None,
) -> dict[str, Any]:
    """One read-only sweep producing every projection row.  Writes nothing."""
    projects, artifacts, tasks = index_projects(
        projects_root=projects_root, runs_dir=runs_dir, vault_root=vault_root
    )
    artifacts = list(artifacts) + index_vault(vault_root) + index_runs(runs_dir)
    return {
        "projects": projects,
        "artifacts": artifacts,
        "tasks": tasks,
        "capabilities": index_capabilities(),
        "sources": {
            "machine": str(_PKG_ROOT),
            "vault": str(vault_root or _safe(discover_vault_root, "") or ""),
            "runs": str(Path(runs_dir) if runs_dir else _PKG_ROOT / "runs"),
        },
    }


__all__ = [
    "build_projection",
    "ledger_boundaries",
    "index_capabilities",
    "index_projects",
    "index_runs",
    "index_tasks",
    "index_vault",
    "parse_frontmatter",
    "vault_kinds",
]
