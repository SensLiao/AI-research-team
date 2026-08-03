"""`python -m research_agent_teams.workbench <verb>` — the workbench's own CLI.

Deliberately NOT added to `operate/cli.py`: that file is already over the 800-line ceiling,
and these verbs are read-only navigation while `operate` runs research.  Keeping them apart
means a navigation command can never start a run by accident.

    reindex   rebuild `.workbench/` from the machine + the vault, and regenerate the pages
    home      print the global research home
    status    one project's headline (`--json` for an agent)
    search    full-text over machine + vault + runs
    next      what is worth doing now, and what is waiting on the director
    open      resolve an artifact id to its real path
    outcomes  the six-choice "你想得到什么" menu — outcomes, not mode names
    outcome   ONE outcome compiled into its exact command chain + what it cannot claim

`reindex` is the only verb that writes, and it only ever writes inside `.workbench/` plus
one generated `PROJECT-HOME.md` per existing workspace.  Nothing here writes the vault,
starts a run, or resolves a credential.  `outcomes` / `outcome` PRINT the commands for a
research route; executing one stays exclusively `operate`'s job.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from ..reporting.outcomes import render_menu, render_recipe
from ..tools import outcome_recipes
from .indexer import build_projection
from .model import EVIDENCE_STATE_WORDS, WORK_STATE_WORDS, coerce_evidence_state, coerce_work_state
from .projectors import render_research_home, write_home_pages
from .store import WorkbenchStore, destroy, workbench_root


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _emit(payload: Any) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def _store(args: argparse.Namespace) -> WorkbenchStore:
    return WorkbenchStore(args.workbench_root)


def _require_index(store: WorkbenchStore) -> bool:
    if store.exists():
        return True
    print("还没建索引。先跑：python -m research_agent_teams.workbench reindex", file=sys.stderr)
    return False


# --------------------------------------------------------------------------- verbs

def cmd_reindex(args: argparse.Namespace) -> None:
    built_at = args.ts or _now()
    projection = build_projection(
        projects_root=args.projects_dir, runs_dir=args.runs_dir, vault_root=args.vault
    )
    store = _store(args)
    meta = store.rebuild(
        projects=projection["projects"],
        artifacts=projection["artifacts"],
        tasks=projection["tasks"],
        capabilities=projection["capabilities"],
        built_at=built_at,
        sources=projection["sources"],
    )
    pages = write_home_pages(
        projects=projection["projects"],
        tasks=projection["tasks"],
        artifacts=projection["artifacts"],
        capabilities=projection["capabilities"],
        built_at=built_at,
        workbench_dir=store.root,
    )
    store.close()
    _emit({"rebuilt": True, "root": str(store.root), "meta": meta, **pages,
           "note": "这层是投影，删掉再 reindex 可完整重建；不是任何事实的来源"})


def cmd_home(args: argparse.Namespace) -> None:
    store = _store(args)
    if args.fresh or not store.exists():
        projection = build_projection(
            projects_root=args.projects_dir, runs_dir=args.runs_dir, vault_root=args.vault
        )
        print(render_research_home(
            projection["projects"], tasks=projection["tasks"],
            artifacts=projection["artifacts"], capabilities=projection["capabilities"],
            built_at=args.ts or _now(),
        ))
        return
    page = store.root / "RESEARCH-HOME.md"
    store.close()
    if page.is_file():
        print(page.read_text(encoding="utf-8"))
    else:
        print("索引在但首页不在 —— 跑一次 reindex。", file=sys.stderr)
        sys.exit(2)


def cmd_status(args: argparse.Namespace) -> None:
    store = _store(args)
    if not _require_index(store):
        sys.exit(2)
    projects = store.projects()
    if args.project:
        projects = [p for p in projects if p["slug"] == args.project]
        if not projects:
            _emit({"error": f"没有这个项目：{args.project}",
                   "known": [p["slug"] for p in store.projects()]})
            store.close()
            sys.exit(2)
    payload = {"meta": store.meta(), "projects": projects,
               "tasks": store.tasks(args.project)}
    store.close()
    if args.json:
        _emit(payload)
        return
    for project in payload["projects"]:
        mark = " ← 当前主线" if project["active"] else ""
        print(f"\n{project['title']}{mark}　生命周期 {project['lifecycle']}")
        if project["question"]:
            print(f"  在问：{project['question']}")
        for line in project["truth_boundary"][:3]:
            print(f"  边界：{line}")
        counts = project["counts"]
        print(f"  运行 {counts.get('runs', 0)}　文档 {counts.get('docs', 0)}　"
              f"任务 {counts.get('tasks', 0)}　等你决定 {len(project['open_decisions'])}　"
              f"卡住 {len(project['blockers'])}")
    tasks = payload["tasks"]
    if tasks:
        print("\n任务（工作进度 / 证据强度 / 项目原文）：")
        for task in tasks:
            work = coerce_work_state(task["work_state"])
            evidence = coerce_evidence_state(task["evidence_state"])
            print(f"  {task['title'][:52]:<52} {WORK_STATE_WORDS[work]:<6} "
                  f"{EVIDENCE_STATE_WORDS[evidence] if evidence else '—':<22} "
                  f"`{task.get('source_status') or '—'}`")


def cmd_search(args: argparse.Namespace) -> None:
    store = _store(args)
    if not _require_index(store):
        sys.exit(2)
    result = store.search(args.query, project=args.project, source=args.source,
                          limit=args.limit)
    store.close()
    if args.json:
        _emit(result)
        return
    if result.get("note"):
        print(result["note"], file=sys.stderr)
    hits = result["hits"]
    print(f"「{result['query']}」命中 {len(hits)} 条（引擎：{result['engine']}）")
    for hit in hits:
        evidence = coerce_evidence_state(hit.get("evidence_state"))
        print(f"\n  {hit['title'][:80]}")
        print(f"    {hit['artifact_id']}　[{hit['source']}/{hit['kind']}]"
              f"　{EVIDENCE_STATE_WORDS[evidence] if evidence else ''}")
        excerpt = (hit.get("excerpt") or "").replace("\n", " ").strip()
        if excerpt:
            print(f"    …{excerpt[:160]}…")


def cmd_next(args: argparse.Namespace) -> None:
    store = _store(args)
    if not _require_index(store):
        sys.exit(2)
    tasks = store.tasks(args.project)
    store.close()
    buckets: dict[str, list[dict[str, Any]]] = {"ready": [], "needs_decision": [],
                                                "active": [], "blocked": []}
    for task in tasks:
        state = str(task.get("work_state") or "")
        if state in buckets:
            buckets[state].append(task)
    if args.json:
        _emit({"project": args.project, **buckets})
        return
    labels = {"ready": "可以现在动手", "needs_decision": "等你决定",
              "active": "正在做", "blocked": "卡住了"}
    for key, label in labels.items():
        rows = buckets[key]
        print(f"\n{label}（{len(rows)}）")
        if not rows:
            print("  —")
        for task in rows:
            blockers = ("　卡在：" + "；".join(task["blockers"])) if task.get("blockers") else ""
            print(f"  · {task['title']}　`{task.get('source_status') or '—'}`{blockers}")


def cmd_open(args: argparse.Namespace) -> None:
    store = _store(args)
    if not _require_index(store):
        sys.exit(2)
    row = store.artifact(args.artifact_id)
    store.close()
    if not row:
        _emit({"error": f"索引里没有这个产物：{args.artifact_id}"})
        sys.exit(2)
    if args.json or not args.print_body:
        _emit(row)
        return
    path = Path(row["path"])
    if not path.is_file():
        _emit({**row, "error": "索引里有这条，但磁盘上的文件不在了 —— reindex 一次"})
        sys.exit(2)
    print(path.read_text(encoding="utf-8", errors="replace"))


def cmd_outcomes(args: argparse.Namespace) -> None:
    """The six-choice menu. Needs no index — it reads the registries, not the projection."""
    verdict = outcome_recipes.validate_all()
    if args.json:
        _emit({"menu": outcome_recipes.resolve_all(), "validation": verdict})
    else:
        print(render_menu())
    if not verdict["ok"]:
        sys.exit(2)


def cmd_outcome(args: argparse.Namespace) -> None:
    """ONE outcome, compiled into the exact commands. Prints them; never runs them."""
    try:
        if args.json:
            _emit({"outcome": outcome_recipes.resolve(args.outcome_id, variant=args.variant),
                   "steps": outcome_recipes.command_chain(
                       args.outcome_id, variant=args.variant, project=args.project,
                       request=args.request)})
        else:
            print(render_recipe(args.outcome_id, variant=args.variant, project=args.project,
                                request=args.request))
    except KeyError as exc:
        _emit({"error": str(exc), "known": outcome_recipes.recipe_ids()})
        sys.exit(2)


def cmd_destroy(args: argparse.Namespace) -> None:
    """Prove the rebuildable claim: this is safe, because the store holds no source of truth."""
    _emit({**destroy(args.workbench_root),
           "note": "已删除投影。reindex 一次即可完整恢复 —— 没有任何事实存在这里"})


# --------------------------------------------------------------------------- wiring

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m research_agent_teams.workbench",
        description="研究工作台：只读导航层，架在机器和库之上的可重建投影",
    )
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--workbench-root", default=None, help="投影目录（默认机器包下的 .workbench/）")
    common.add_argument("--projects-dir", default=None)
    common.add_argument("--runs-dir", default=None)
    common.add_argument("--vault", default=None, help="库的根目录（默认自动发现）")
    common.add_argument("--ts", default=None, help="生成时间戳（测试用，保证确定性）")
    common.add_argument("--json", action="store_true", help="给 agent 读的结构化输出")

    sub = parser.add_subparsers(dest="verb", required=True)

    ri = sub.add_parser("reindex", parents=[common], help="重建投影 + 重新生成首页")
    ri.set_defaults(func=cmd_reindex)

    hm = sub.add_parser("home", parents=[common], help="打印全局研究首页")
    hm.add_argument("--fresh", action="store_true", help="不用索引，现场扫一遍再渲染")
    hm.set_defaults(func=cmd_home)

    st = sub.add_parser("status", parents=[common], help="项目状态一览")
    st.add_argument("--project", default=None)
    st.set_defaults(func=cmd_status)

    se = sub.add_parser("search", parents=[common], help="全文搜索：机器 + 库 + 运行")
    se.add_argument("query")
    se.add_argument("--project", default=None)
    se.add_argument("--source", default=None, choices=["machine", "vault", "run"])
    se.add_argument("--limit", type=int, default=20)
    se.set_defaults(func=cmd_search)

    nx = sub.add_parser("next", parents=[common], help="现在最值得做什么 / 什么在等你")
    nx.add_argument("--project", default=None)
    nx.set_defaults(func=cmd_next)

    op = sub.add_parser("open", parents=[common], help="把产物 id 解析成真实路径")
    op.add_argument("artifact_id")
    op.add_argument("--print-body", action="store_true", help="直接打印文件内容")
    op.set_defaults(func=cmd_open)

    oc = sub.add_parser("outcomes", parents=[common], help="你想得到什么：六选一菜单")
    oc.set_defaults(func=cmd_outcomes)

    on = sub.add_parser("outcome", parents=[common],
                        help="看某一条路的完整命令 + 深浅三档 + 它不能声称什么")
    on.add_argument("outcome_id", help="菜单里的 id，例如 direction-to-bet")
    on.add_argument("--variant", default=None, help="深浅档：quick / default / deep（默认走推荐档）")
    on.add_argument("--project", default=None, help="填进命令里的项目 slug")
    on.add_argument("--request", default=None,
                    help="你的原话（会被钉成运行的北极星）；不给就在命令里留占位提示")
    on.set_defaults(func=cmd_outcome)

    de = sub.add_parser("destroy", parents=[common], help="删掉投影（安全 —— reindex 可完整恢复）")
    de.set_defaults(func=cmd_destroy)
    return parser


def main(argv: Optional[list[str]] = None) -> None:
    args = build_parser().parse_args(argv)
    args.func(args)


__all__ = ["build_parser", "main"]
