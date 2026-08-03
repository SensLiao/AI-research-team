"""The "你想得到什么" cards — six outcomes, and one compiled route.

This is the RENDERING half of the outcome layer; the logic and every derived number live in
`tools/outcome_recipes.py`. Two cards:

  :func:`render_menu`    the six-choice menu — what you end up holding, how big, where it stops
  :func:`render_recipe`  ONE outcome compiled into the exact command chain, its three depths, and
                         the honest statement of what that route CANNOT claim

Both are deterministic, read-only, plain Chinese (director lock 2026-08-01: no acronym walls), and
neither can start a run — they print commands for the director to approve.
"""
from __future__ import annotations

from typing import Any, Optional

from ..tools import outcome_recipes as recipes
from . import plain_words as words

#: Deliberately NOT `research_plan.estimate_cost`'s band word here. Its thresholds (heavy above 16
#: hops) were set for single tiers; every one of the six outcomes exceeds them, so the column would
#: read "大工程" six times and carry zero information. The real derived numbers do carry information,
#: and a RELATIVE marker among the six tells the director which is the cheap one. The shared
#: thresholds stay untouched — the plan card still uses them for tier menus.
_RELATIVE_WORDS = ("偏省", "中等", "偏重")


#: `docs/03-WORKFLOWS.md` §1 states the discipline these two numbers must respect: `agent_subset` is
#: the ROSTER a mode may draw from (larger than what actually gets dispatched) and `max_agent_hops` is
#: the hard dispatch ceiling; the real number lands between them, and neither is a concurrency count.
#: So the card says "可上场", never "会派" — a roster read as a promise is an overclaim.
_SEAT_NOTE = ("> 两个数别读成承诺：「席可上场」是这条路**允许**调用的名单上限，"
              "「轮」是硬派发上限；真正派出去的在两者之间，也都不是并发数。")


def _size_words(view: dict[str, Any]) -> str:
    words = f"{view['seats']} 席可上场 · 最多派 {view['cost']['agent_hops']} 轮"
    if view.get("council_only"):
        words += f"（其中 {view['council_only']} 席只在 council 路径上场）"
    return words


def _relative_weight(views: list[dict[str, Any]]) -> dict[str, str]:
    """轻/中/重, measured against the other five rather than an absolute threshold."""
    ranked = sorted(views, key=lambda v: (v["cost"]["agent_hops"], v["seats"]))
    third = max(1, len(ranked) // 3)
    out: dict[str, str] = {}
    for index, view in enumerate(ranked):
        bucket = 0 if index < third else (2 if index >= len(ranked) - third else 1)
        out[view["id"]] = _RELATIVE_WORDS[bucket]
    return out


def _chain_words(modes: list[str]) -> str:
    return " → ".join(words.say(m) for m in modes) or "—"


def _gate_words(view: dict[str, Any]) -> str:
    gates = [g["gate"] for g in view.get("gates") or []]
    return "、".join(words.gate_label(g) for g in gates) if gates else "中途不停，做完直接给你看"


# --------------------------------------------------------------------------------- the menu

def render_menu(*, path: Optional[str] = None) -> str:
    """The six-choice card. Answers "我能得到什么" before asking "要跑哪个模式"."""
    views = recipes.resolve_all(path=path)
    verdict = recipes.validate_all(path=path)

    lines = ["# 你想得到什么", "",
             "> 六选一。不用知道内部模式叫什么 —— 说你想**最后拿到什么**就行。",
             "> 每条都标了规模、会在哪停下来等你拍板、以及**这条路不能声称什么**。", ""]
    weight = _relative_weight(views)
    lines += ["| # | 你想要的 | 最后拿到什么 | 规模（六条之间比） | 会停下来等你 |",
              "|---|---|---|---|---|"]
    for index, view in enumerate(views, start=1):
        size = f"{weight[view['id']]}：{_size_words(view)}"
        lines.append(f"| {index} | **{view['want']}** | {view['deliverable']} | {size} "
                     f"| {_gate_words(view)} |")
    lines += ["", _SEAT_NOTE, ""]

    lines += ["## 每条路的深浅三档", ""]
    for index, view in enumerate(views, start=1):
        lines.append(f"**{index}. {view['want']}** — `{view['id']}`")
        for variant in view["variants"]:
            star = " ⭐建议" if variant["recommended"] else ""
            lines.append(f"- {variant['label']}{star}：{_chain_words(variant['modes'])}")
        lines.append("")

    lines += ["## 挑好了怎么办", "",
              "```bash",
              "# 看某一条的完整命令 + 三档深浅 + 它不能声称什么",
              "python -m research_agent_teams.workbench outcome <上面那个 id> --project <项目>",
              "```", "",
              "> 想直接说人话也行 —— 说「我想要一个能下注的方向」，我会走 `operate brief` "
              "先把计划卡摆给你，再动手。", ""]

    if not verdict["ok"]:
        lines += ["## ⚠️ 这份菜单本身有问题（数据校验没过）", ""]
        lines += [f"- {v}" for v in verdict["violations"]]
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


# --------------------------------------------------------------------------------- one recipe

def _section_depths(view: dict[str, Any]) -> list[str]:
    out = ["## 深浅三档（现在选中的是加粗那档）", "",
           "| 档 | 走什么 | 规模 | 为什么是这条 |", "|---|---|---|---|"]
    for variant in view["variants"]:
        picked = variant["id"] == view["variant"]["id"]
        label = f"**{variant['label']}**" if picked else variant["label"]
        resolved = recipes.resolve(view["id"], variant=variant["id"])
        out.append(f"| {label} | {_chain_words(variant['modes'])} | {_size_words(resolved)} "
                   f"| {variant['why']} |")
    out.append("")
    return out


def _section_steps(view: dict[str, Any], project: Optional[str],
                   request: Optional[str]) -> list[str]:
    steps = recipes.command_chain(view["id"], variant=view["variant"]["id"], project=project,
                                  request=request)
    out = [f"## 这条路怎么跑（{view['variant']['label']}）", "",
           "| 第几步 | 干什么 | 可上场席位 | 你能打开的产物 |", "|---|---|---|---|"]
    for step, facts in zip(steps, view["mode_facts"]):
        out.append(f"| {step['link']} | {words.say(step['mode'])} | {step['seats']} 席 "
                   f"| `{facts['deliverable']}` |")
    out += ["", "> 上场的每一席都是**派出去的 sub-agent**：领一个阶段、写一个产物、就返回。"
            "主线程只负责路由、跑确定性关卡、汇报 —— 它自己不做研究。", _SEAT_NOTE, ""]
    for step in steps:
        out += [f"**第 {step['link']} 步 — {words.say(step['mode'])}**", "", "```bash"]
        out += step["commands"]
        out += ["```", ""]
        if step["stops_at"]:
            stops = "、".join(words.gate_label(g) for g in step["stops_at"])
            out += [f"> ⛔ 这一步跑完**停下来等你**：{stops}。机器不替你决定。", ""]
    return out


def _section_ceiling(view: dict[str, Any]) -> list[str]:
    out = ["## 这条路**不能**声称什么（先说清楚，别事后失望）", ""]
    out += [f"- {line}" for line in view["ceiling"]]
    out.append("")
    return out


def _section_questions(view: dict[str, Any]) -> list[str]:
    questions = view.get("questions") or {}
    if not questions:
        return []
    out = ["## 开跑前它会问你的", ""]
    for mode, asked in questions.items():
        out.append(f"- **{words.say(mode)}**：" + "；".join(q.get("ask", "") for q in asked))
    out.append("")
    return out


def render_recipe(recipe_id: str, *, variant: Optional[str] = None,
                  project: Optional[str] = None, request: Optional[str] = None,
                  path: Optional[str] = None) -> str:
    """ONE outcome, compiled: depths, the exact commands, the gates, and the honest ceiling."""
    view = recipes.resolve(recipe_id, variant=variant, path=path)
    lines = [f"# {view['want']}", "",
             f"> `{view['id']}` · 一共 {_size_words(view)}", ""]
    if view.get("for_you_when"):
        lines += [f"- **什么时候选它**：{view['for_you_when']}"]
    lines += [f"- **最后你拿到**：{view['deliverable']}",
              f"- **会停下来等你**：{_gate_words(view)}", ""]
    lines += _section_depths(view)
    lines += _section_steps(view, project, request)
    lines += _section_ceiling(view)
    lines += _section_questions(view)

    validation = view.get("validation") or {}
    if validation.get("warnings"):
        lines += ["## 提醒", ""] + [f"- {w}" for w in validation["warnings"]] + [""]
    return "\n".join(lines).rstrip() + "\n"


__all__ = ["render_menu", "render_recipe"]
