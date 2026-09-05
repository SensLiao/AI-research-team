"""Who is actually on the team — the seat census behind every "N 席" the director is ever shown.

The v4 memo asked P4 for a *smallest-sufficient-team policy* and *dynamic dispatch of dormant
workers*. Measuring first (2026-08-04) changed both halves of that:

  - The memo's "157 workers, 120 used by operated modes, 37 spec-only" split is **correct** — it had
    never been verified, and now it is, in code, by :func:`census`.
  - **There are no dormant workers.** All 163 rostered agents are reachable from a recipe, the
    mechanism-council config, a tool, or the engine. Nothing needs waking up, so the "dynamic
    dispatch of dormant workers" half solves a problem this tree does not have.
  - What is real is a **roster-versus-dispatch gap**: 15 seats are declared in an operated mode's
    `agent_subset` yet never named by that mode's recipe — they fire only on the mechanism-council
    path. So "35 个 agent" for `full_rigor_minimal` is a ceiling, not a plan, and this module is what lets
    a card say so honestly (`docs/03-WORKFLOWS.md` §1 discipline).
  - And a **scalability fact**: only ONE of the twelve operated modes (`deep_research`) has a real
    depth knob in `plan_catalog.yaml`. For the other eleven the team is fixed, so a policy that
    claims to shrink teams would be claiming a control that does not exist. :func:`team_plan`
    therefore reports what CAN be scaled instead of pretending to prune.

Deliberately NOT built: any mechanism that drops seats on its own. Most seats that look redundant are
the independence machinery — blind hunters, independent auditors, the collision checker that must not
be the idea's author. Pruning those to save budget would silently remove the reason the output can be
trusted. Narrowing belongs in a recipe's own depth knob, where the recipe author decides what is safe
to skip.

Read-only. No model call. Never starts a run.

    python -m research_agent_teams.tools.worker_census census   # the roster, and where each seat is reachable from
    python -m research_agent_teams.tools.worker_census teams    # per operated mode: ceiling / dispatch floor / council-only
    python -m research_agent_teams.tools.worker_census verify   # the invariants (exit 2 on violation)
"""
from __future__ import annotations

import argparse
import json
import sys
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

import yaml

from . import research_plan

_PKG = Path(__file__).resolve().parents[1]                        # research_agent_teams/
ROSTER_PATH = _PKG / "orchestrator" / "roster.yaml"
AGENTS_DIR = _PKG / "agents"

#: The main thread (director rule D7). It is named by every recipe because the recipe describes the
#: run, but it is NOT a seat and must never appear in a mode's `agent_subset`.
MAIN_THREAD = "research-orchestrator"

CONTROL_GROUP = "control"

#: Where a worker's name can legitimately come from. The census reports the source per seat so
#: "reachable" is never a bare yes — `council` means the seat fires on the mechanism-council path,
#: not on the recipe's own dispatch.
REACH_SOURCES: dict[str, tuple[str, ...]] = {
    "recipe": ("operate/modes/*.py",),
    "council": ("orchestrator/*.json", "orchestrator/*.yaml"),
    "tools": ("tools/*.py",),
    "engine": ("orchestrator/engine.py", "orchestrator/router.py"),
}


@lru_cache(maxsize=1)
def roster() -> dict[str, str]:
    """agent name -> its stage group (`control` for the six control-plane roles)."""
    groups = yaml.safe_load(ROSTER_PATH.read_text(encoding="utf-8"))["agents"]
    return {name: group for group, names in groups.items() for name in names}


def agent_files() -> set[str]:
    return {path.stem for path in AGENTS_DIR.glob("*.md")}


def workers() -> list[str]:
    return sorted(name for name, group in roster().items() if group != CONTROL_GROUP)


@lru_cache(maxsize=1)
def _source_text() -> dict[str, str]:
    out: dict[str, str] = {}
    for source, patterns in REACH_SOURCES.items():
        chunks: list[str] = []
        for pattern in patterns:
            if "*" in pattern:
                chunks += [p.read_text(encoding="utf-8", errors="replace")
                           for p in sorted(_PKG.glob(pattern))]
            elif (_PKG / pattern).is_file():
                chunks.append((_PKG / pattern).read_text(encoding="utf-8", errors="replace"))
        out[source] = "\n".join(chunks)
    return out


def dispatched_by_recipe(agent: str) -> bool:
    """Whether a mode's own recipe names this seat, as opposed to only the council config."""
    return agent in _source_text()["recipe"]


def reachable_from(agent: str) -> list[str]:
    """Which source families mention this agent by name.

    Honesty ceiling: this is a NAME scan. A dispatch whose agent name is assembled at run time from
    fragments would not be seen here — no such construction exists in the tree today (checked
    2026-08-04), but a future one would read as unreachable rather than be silently counted.
    """
    return [source for source, text in _source_text().items() if agent in text]


# ------------------------------------------------------------------------------------- census

def _declared() -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    registry = research_plan.load_mode_registry()["modes"]
    by_operated: dict[str, list[str]] = {}
    by_spec: dict[str, list[str]] = {}
    for mode, spec in registry.items():
        target = by_operated if spec.get("operated") else by_spec
        for agent in spec.get("agent_subset") or []:
            target.setdefault(agent, []).append(mode)
    return by_operated, by_spec


def census() -> dict[str, Any]:
    """Every rostered agent with its group, who declares it, and where it is reachable from."""
    by_operated, by_spec = _declared()
    rows: list[dict[str, Any]] = []
    for name, group in sorted(roster().items()):
        rows.append({
            "agent": name,
            "group": group,
            "is_worker": group != CONTROL_GROUP,
            "declared_by_operated": sorted(by_operated.get(name, [])),
            "declared_by_spec_only": sorted(by_spec.get(name, [])),
            "reachable_from": reachable_from(name),
        })
    worker_rows = [r for r in rows if r["is_worker"]]
    operated_workers = [r for r in worker_rows if r["declared_by_operated"]]
    spec_only_workers = [r for r in worker_rows
                         if not r["declared_by_operated"] and r["declared_by_spec_only"]]
    return {
        "contract": "worker-census/v1",
        "totals": {
            "rostered": len(rows),
            "control": len(rows) - len(worker_rows),
            "workers": len(worker_rows),
            "declared_by_operated": len(operated_workers),
            "spec_only": len(spec_only_workers),
            "in_no_subset": len([r for r in worker_rows if not r["declared_by_operated"]
                                 and not r["declared_by_spec_only"]]),
            "unreachable": len([r for r in rows if not r["reachable_from"]]),
        },
        "agents": rows,
    }


# --------------------------------------------------------------------------------- mode teams

def _depth_knob(mode: str) -> Optional[dict[str, Any]]:
    """The mode's own budget knob from `plan_catalog.yaml`, if the recipe author gave it one."""
    for question in research_plan.mode_questions(mode):
        if question.get("maps_to") == "budget":
            return {"key": question.get("key"),
                    "options": [o.get("value") for o in question.get("options") or []]}
    return None


def mode_teams() -> dict[str, Any]:
    """Per operated mode: the declared ceiling, the recipe's own dispatch floor, and the gap."""
    registry = research_plan.load_mode_registry()["modes"]
    recipe_text = _source_text()["recipe"]
    teams: list[dict[str, Any]] = []
    for mode in sorted(m for m, spec in registry.items() if spec.get("operated")):
        declared = list(registry[mode].get("agent_subset") or [])
        named = [a for a in declared if a in recipe_text]
        council_only = [a for a in declared if a not in recipe_text]
        teams.append({
            "mode": mode,
            "ceiling": len(declared),
            "recipe_floor": len(named),
            "council_only": sorted(council_only),
            "hops": int((registry[mode].get("budget") or {}).get("max_agent_hops") or 0),
            "depth_knob": _depth_knob(mode),
        })
    return {
        "contract": "mode-teams/v1",
        "totals": {
            "modes": len(teams),
            "ceiling": sum(t["ceiling"] for t in teams),
            "recipe_floor": sum(t["recipe_floor"] for t in teams),
            "council_only": sum(len(t["council_only"]) for t in teams),
            "scalable_modes": len([t for t in teams if t["depth_knob"]]),
        },
        "teams": teams,
    }


def team_plan(mode: str) -> dict[str, Any]:
    """What can honestly be said about ONE mode's team size — and what cannot.

    There is no pruning here on purpose: the seats that look redundant are usually the independence
    machinery (blind hunters, independent auditors, the collision checker that must not be the idea's
    own author). Dropping those to save budget removes the reason the output can be trusted, so
    narrowing stays with the recipe's own depth knob.
    """
    for team in mode_teams()["teams"]:
        if team["mode"] == mode:
            knob = team["depth_knob"]
            return {**team,
                    "scalable": bool(knob),
                    "note": (f"团队规模可缩：用 `{knob['key']}`（{'/'.join(knob['options'])}）"
                             if knob else
                             "这个模式的团队是固定的 —— 没有 depth 旋钮，不能只派一部分 agent")}
    raise KeyError(f"{mode!r} is not an operated mode")


# ---------------------------------------------------------------------------------- invariants

def verify() -> dict[str, Any]:
    """Guards that a future edit cannot quietly break."""
    violations: list[str] = []
    data = census()
    rostered = set(roster())
    files = agent_files()

    for missing in sorted(rostered - files):
        violations.append(f"roster names {missing!r} but agents/{missing}.md does not exist")
    for extra in sorted(files - rostered):
        violations.append(f"agents/{extra}.md exists but roster.yaml does not list it")

    for row in data["agents"]:
        if not row["reachable_from"]:
            violations.append(
                f"orphan seat: {row['agent']!r} is rostered but no recipe, council config, tool or "
                "the engine ever names it — a seat nothing can dispatch is a capability that does "
                "not exist")
        if row["group"] == CONTROL_GROUP and row["declared_by_operated"]:
            violations.append(
                f"{row['agent']!r} is control-plane yet declared as a seat by "
                f"{row['declared_by_operated']} — control is not a worker (D7)")

    registry = research_plan.load_mode_registry()["modes"]
    for mode, spec in registry.items():
        for agent in spec.get("agent_subset") or []:
            if agent not in rostered:
                violations.append(f"mode {mode!r} declares unknown agent {agent!r}")

    recipe_text = _source_text()["recipe"]
    declared_anywhere = {a for spec in registry.values() for a in (spec.get("agent_subset") or [])}
    for agent in sorted(a for a in rostered if a in recipe_text and a not in declared_anywhere):
        if agent == MAIN_THREAD:
            continue
        violations.append(
            f"undeclared dispatch: a recipe names {agent!r} but no mode's agent_subset declares it — "
            "the subset is what bounds a mode's permission scope")

    return {"ok": not violations, "violations": violations, "totals": data["totals"],
            "teams": mode_teams()["totals"]}


# ------------------------------------------------------------------------------------ render

def render_report() -> str:
    """Plain Chinese: who is on the bench, who actually plays, what can be made cheaper."""
    data = census()
    teams = mode_teams()
    t = data["totals"]
    lines = ["# 团队 agent 盘点", "",
             f"- **在册**：{t['rostered']} 个 agent = {t['control']} 个控制 agent + {t['workers']} 个工人 agent",
             f"- **被一键模式声明**：{t['declared_by_operated']} 个 agent；"
             f"**只在未接线模式里**：{t['spec_only']} 个 agent",
             f"- **无处可达的 agent**：{t['unreachable']} 个 agent"
             + ("（没有闲置 agent —— 每一个 agent 都有地方能派它）" if not t["unreachable"] else "（⚠️ 有闲置 agent）"),
             ""]
    lines += ["## 每个一键模式：名单上限 vs 真正派发", "",
              "| 模式 | 可上场 | recipe 真派 | 只在 council 路径 | 能不能缩规模 |",
              "|---|---:|---:|---:|---|"]
    for team in teams["teams"]:
        knob = team["depth_knob"]
        scale = f"可以（`{knob['key']}`）" if knob else "不能，团队固定"
        lines.append(f"| `{team['mode']}` | {team['ceiling']} | {team['recipe_floor']} "
                     f"| {len(team['council_only'])} | {scale} |")
    tt = teams["totals"]
    lines += ["",
              f"合计：可上场 {tt['ceiling']} 个名额，recipe 真派 {tt['recipe_floor']} 个名额，"
              f"{tt['council_only']} 个名额只在 council 路径上场。"
              f"{tt['scalable_modes']}/{tt['modes']} 个模式有真的深浅旋钮。", "",
              "> 「可上场」是 registry 允许调用的名单上限，不是承诺会派这么多。"
              "看起来多余的 agent 多半是**独立性机制**（互相独立的搜索 agent 、独立审计、不能自己查自己的查重员）——"
              "为省预算砍掉它们，等于砍掉结论可信的理由。缩规模只能由 recipe 自己的旋钮来做。", ""]
    return "\n".join(lines).rstrip() + "\n"


def _emit(payload: Any) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m research_agent_teams.tools.worker_census",
        description="agent 盘点：谁在册、谁真被派、哪个模式能缩规模（只读）")
    sub = parser.add_subparsers(dest="verb", required=True)
    for verb, helptext in (("census", "the roster + where each seat is reachable from"),
                           ("teams", "per operated mode: ceiling / dispatch floor / council-only"),
                           ("verify", "the invariants (exit 2 on violation)")):
        p = sub.add_parser(verb, help=helptext)
        p.add_argument("--json", action="store_true", help="structured output for an agent")

    args = parser.parse_args(argv)
    if args.verb == "verify":
        result = verify()
        _emit(result)
        return 0 if result["ok"] else 2
    if args.json:
        _emit(census() if args.verb == "census" else mode_teams())
    else:
        print(render_report())
    return 0


__all__ = ["CONTROL_GROUP", "MAIN_THREAD", "REACH_SOURCES", "agent_files", "census",
           "dispatched_by_recipe", "main", "mode_teams", "reachable_from", "render_report",
           "roster", "team_plan", "verify", "workers"]


if __name__ == "__main__":
    sys.exit(main())
