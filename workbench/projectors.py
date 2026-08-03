"""Render the two Markdown pages a human actually opens.  Generated — never hand-edited.

`PROJECT-HOME.md` (per project) and `RESEARCH-HOME.md` (global) exist so the director never
has to walk into a run directory to find out where things stand.  Both are **projections**:
regenerating them is always safe, and editing them by hand is always wrong — the next
`research reindex` overwrites the file.  Each page says so at the top.

Two honesty rules the renderer keeps:

* A number is never printed without the axis it belongs to.  "48 可引用 / 62 只是暫定" is
  printed as two numbers, never summed into "110 results", because the sum reads as strength.
* A task's own status word is printed next to the mapped state, so a reader can always see
  what the project actually wrote.
"""
from __future__ import annotations

import os
from collections import Counter
from pathlib import Path
from typing import Any, Iterable, Optional

from .model import (
    EVIDENCE_STATE_WORDS,
    WORK_STATE_WORDS,
    ArtifactRow,
    EvidenceState,
    ProjectRow,
    TaskRow,
    WorkState,
    coerce_evidence_state,
    coerce_work_state,
)

_BANNER = (
    "> ⚠ 这一页是**自动生成**的投影，不要手改 —— 下一次 `research reindex` 会整页覆盖。\n"
    "> 事实的来源是机器（`research_agent_teams/`）和库（`PhD-Research-OS/`），不是这一页。\n"
)

# The order a director wants to see work in: what can move, what needs them, what is stuck.
_ACTION_ORDER = (
    WorkState.READY,
    WorkState.NEEDS_DECISION,
    WorkState.ACTIVE,
    WorkState.BLOCKED,
    WorkState.BACKLOG,
    WorkState.DONE,
)


def _link(target: str, *, relative_to: Optional[Path]) -> str:
    """A clickable link target.

    An absolute Windows path with spaces and backslashes is not a usable Markdown link, so
    render it relative and POSIX-separated.  Different drives (or no anchor) fall back to the
    raw path — a wrong-looking link beats a crash.
    """
    if not target:
        return ""
    if relative_to is None:
        return Path(target).as_posix()
    try:
        return Path(os.path.relpath(target, relative_to)).as_posix()
    except (ValueError, OSError):
        return Path(target).as_posix()


def _evidence_split(artifacts: Iterable[ArtifactRow]) -> Counter:
    return Counter(
        (coerce_evidence_state(a.evidence_state) or EvidenceState.PROPOSED) for a in artifacts
    )


def _tasks_by_state(tasks: Iterable[TaskRow]) -> dict[WorkState, list[TaskRow]]:
    out: dict[WorkState, list[TaskRow]] = {}
    for task in tasks:
        out.setdefault(coerce_work_state(task.work_state), []).append(task)
    return out


def _task_lines(tasks: list[TaskRow]) -> list[str]:
    lines = []
    for task in tasks:
        blockers = ("　卡在：" + "；".join(task.blockers)) if task.blockers else ""
        word = f"（项目自己写的是 `{task.source_status}`）" if task.source_status else ""
        lines.append(f"- **{task.title}** {word}{blockers}")
        if task.why_now:
            lines.append(f"    - 为什么不能拖：{task.why_now}")
        if task.next_action:
            lines.append(f"    - 材料在：`{task.next_action}`")
    return lines


def render_project_home(
    project: ProjectRow,
    *,
    tasks: Iterable[TaskRow] = (),
    artifacts: Iterable[ArtifactRow] = (),
    built_at: str = "",
) -> str:
    tasks = [t for t in tasks if t.project == project.slug]
    artifacts = [a for a in artifacts if a.project == project.slug]
    grouped = _tasks_by_state(tasks)
    split = _evidence_split(artifacts)

    out: list[str] = [f"# {project.title or project.slug} — 项目首页", "", _BANNER]
    out.append(f"生成时间：{built_at or '—'}　·　生命周期：`{project.lifecycle}`"
               f"{'　·　**当前主线**' if project.active else ''}")
    out.append("")

    out.append("## 这个项目在问什么")
    out.append("")
    out.append(project.question or "_项目契约里还没写下冻结的论文问题。_")
    out.append("")

    out.append("## 真值边界（什么还不能说）")
    out.append("")
    if project.truth_boundary:
        out.extend(f"- {line}" for line in project.truth_boundary)
    else:
        out.append("_契约里没有写真值边界 —— 这本身就该补。_")
    out.append("")

    out.append("## 下一步最值得做什么")
    out.append("")
    movable = grouped.get(WorkState.READY, [])
    if movable:
        out.extend(_task_lines(movable))
    else:
        out.append("_没有立刻可动的任务 —— 要么在等你，要么被卡住，见下面两节。_")
    out.append("")

    out.append("## 等你决定")
    out.append("")
    waiting = grouped.get(WorkState.NEEDS_DECISION, [])
    out.extend(_task_lines(waiting) if waiting else ["_没有待你拍板的事。_"])
    out.append("")

    out.append("## 卡住了")
    out.append("")
    stuck = grouped.get(WorkState.BLOCKED, [])
    out.extend(_task_lines(stuck) if stuck else ["_没有被卡住的任务。_"])
    out.append("")

    out.append("## 任务全表（工作进度 与 证据强度 分开看）")
    out.append("")
    out.append("| 任务 | 工作进度 | 证据强度 | 项目原文 | 凭据 |")
    out.append("|---|---|---|---|---|")
    for state in _ACTION_ORDER:
        for task in grouped.get(state, []):
            evidence = coerce_evidence_state(task.evidence_state) or EvidenceState.PROPOSED
            out.append(
                f"| {task.title} | {WORK_STATE_WORDS[state]} | {EVIDENCE_STATE_WORDS[evidence]} "
                f"| `{task.source_status or '—'}` | `{task.next_action or '—'}` |"
            )
    if not tasks:
        out.append("| _这个项目还没有机器可读的任务账本_ | — | — | — | — |")
    out.append("")

    out.append("## 产物")
    out.append("")
    out.append(f"- 工作区文档：{len(artifacts)}　·　运行：{project.counts.get('runs', 0)}")
    if split:
        parts = [f"{EVIDENCE_STATE_WORDS[state]} {count}" for state, count in
                 sorted(split.items(), key=lambda kv: kv[0].value)]
        out.append(f"- 按证据强度：{'　·　'.join(parts)}")
    out.append(f"- 最近一次运行：`{project.latest_run_id or '—'}`"
               f"（{project.latest_run_stage or '状态未知'}）")
    out.append("")
    out.append("找东西：`python -m research_agent_teams.workbench search \"关键词\" "
               f"--project {project.slug}`")
    out.append("")
    return "\n".join(out)


def render_research_home(
    projects: Iterable[ProjectRow],
    *,
    tasks: Iterable[TaskRow] = (),
    artifacts: Iterable[ArtifactRow] = (),
    capabilities: Iterable[dict[str, Any]] = (),
    built_at: str = "",
    page_dir: Optional[Path] = None,
) -> str:
    projects = list(projects)
    tasks = list(tasks)
    artifacts = list(artifacts)
    capabilities = list(capabilities)
    vault = [a for a in artifacts if a.source == "vault"]
    split = _evidence_split(vault)
    grouped = _tasks_by_state(tasks)
    active = next((p for p in projects if p.active), None)

    out: list[str] = ["# 研究首页", "", _BANNER]
    out.append(f"生成时间：{built_at or '—'}")
    out.append("")

    out.append("## 当前主线")
    out.append("")
    if active:
        out.append(f"**{active.title or active.slug}**")
        if active.question:
            out.append("")
            out.append(active.question)
    else:
        out.append("_没有设定当前主线项目。_　设一个：`operate set-active --project <slug>`")
    out.append("")

    out.append("## 我现在有哪些项目")
    out.append("")
    out.append("| 项目 | 主线 | 生命周期 | 运行 | 文档 | 任务 | 已决 | 等你决定 | 卡住 |")
    out.append("|---|---|---|---:|---:|---:|---:|---:|---:|")
    for project in projects:
        href = _link(project.home_path, relative_to=page_dir)
        name = f"[{project.slug}]({href})" if href else project.slug
        out.append(
            f"| {name} "
            f"| {'✅' if project.active else ''} | `{project.lifecycle}` "
            f"| {project.counts.get('runs', 0)} | {project.counts.get('docs', 0)} "
            f"| {project.counts.get('tasks', 0)} | {project.counts.get('decided', 0)} "
            f"| {len(project.open_decisions)} | {len(project.blockers)} |"
        )
    out.append("")

    out.append("## 库里什么能引用、什么不能")
    out.append("")
    citable = split.get(EvidenceState.FROZEN, 0)
    measured = split.get(EvidenceState.OBSERVED, 0)
    dead = split.get(EvidenceState.SUPERSEDED, 0)
    out.append(f"- **可以进论文的：{citable} 页**（库自己的 `result-status=frozen` 推导出来的，本层只读不算）")
    out.append(f"- **真测出来但还不能引用的：{measured} 页**（库标 `provisional`，审计没关）")
    out.append(f"- **已作废／被取代的：{dead} 页**（`deprecated`，别再引）")
    out.append(f"- 其余 {len(vault) - citable - measured - dead} 页是不承载证据等级的知识页面")
    out.append("")
    out.append(f"库里一共 {len(vault)} 页。这几个数字**不要相加当成实力** —— 它们量的是不同的东西。")
    out.append("")

    out.append("## 等你决定")
    out.append("")
    waiting = grouped.get(WorkState.NEEDS_DECISION, [])
    out.extend(_task_lines(waiting) if waiting else ["_没有待你拍板的事。_"])
    out.append("")

    out.append("## 下一步最值得做什么")
    out.append("")
    movable = grouped.get(WorkState.READY, [])
    if movable:
        out.extend(_task_lines(movable))
    else:
        out.append("_没有立刻可动的任务。_")
    out.append("")

    out.append("## 卡在哪")
    out.append("")
    stuck = grouped.get(WorkState.BLOCKED, [])
    out.extend(_task_lines(stuck[:8]) if stuck else ["_没有被卡住的任务。_"])
    if len(stuck) > 8:
        out.append(f"- _……还有 {len(stuck) - 8} 条，见各项目首页_")
    out.append("")

    one_button = [c["mode"] for c in capabilities if c.get("one_button")]
    out.append("## 这台机器现在真能一键跑什么")
    out.append("")
    out.append(f"{len(one_button)} 个（共 {len(capabilities)} 个有定义）："
               + "　".join(f"`{m}`" for m in one_button))
    out.append("")
    out.append("其余的只有定义、还没接线 —— **不要当成能跑的说**。")
    out.append("")
    return "\n".join(out)


def write_home_pages(
    *,
    projects: Iterable[ProjectRow],
    tasks: Iterable[TaskRow] = (),
    artifacts: Iterable[ArtifactRow] = (),
    capabilities: Iterable[dict[str, Any]] = (),
    built_at: str = "",
    workbench_dir: Optional[Path] = None,
) -> dict[str, Any]:
    """Write `RESEARCH-HOME.md` into the workbench dir and one `PROJECT-HOME.md` per project."""
    projects = list(projects)
    tasks = list(tasks)
    artifacts = list(artifacts)
    written: list[str] = []

    for project in projects:
        if not project.home_path:
            continue
        target = Path(project.home_path)
        if not target.parent.is_dir():
            continue                      # an unmaterialised workspace gets no page
        target.write_text(
            render_project_home(project, tasks=tasks, artifacts=artifacts, built_at=built_at),
            encoding="utf-8",
        )
        written.append(str(target))

    if workbench_dir is not None:
        workbench_dir.mkdir(parents=True, exist_ok=True)
        home = workbench_dir / "RESEARCH-HOME.md"
        home.write_text(
            render_research_home(projects, tasks=tasks, artifacts=artifacts,
                                 capabilities=capabilities, built_at=built_at,
                                 page_dir=workbench_dir),
            encoding="utf-8",
        )
        written.append(str(home))
    return {"written": written}


__all__ = ["render_project_home", "render_research_home", "write_home_pages"]
