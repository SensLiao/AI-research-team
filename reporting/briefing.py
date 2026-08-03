"""Pre-task briefing — the plan card the director sees BEFORE any work starts.

Director lock (2026-08-01): "每次做任务前，先计划，扫描 database 然后汇报给我看计划".

The briefing answers five questions and nothing else:

1. 这次要做什么？
2. 库里已经有什么，能省掉哪些重复劳动？
3. 打算怎么做，为什么是这条路线？
4. 会在哪里停下来等你拍板？
5. 现在有什么资源，什么做不了？

It is deterministic (no model call), read-only, and renders plain Chinese via
:mod:`plain_words`. It proposes the tier menu and names the same operated auto
entry that ``operate begin --mode auto`` will use; it never starts a run.
"""
from __future__ import annotations

from typing import Any, Optional

from ..tools import research_plan
from ..tools.research_capability_router import resolve_operated_mode
from . import plain_words as words
from .scan import scan_all

_MAX_RELATED = 6
_MAX_PROJECTS = 8

_BAND_WORDS = {
    "light": "小活儿，几个研究员就够",
    "medium": "中等规模，一个小组",
    "heavy": "大工程，全队上",
}


def _route_options(request: str, intent: Optional[str] = None) -> dict[str, Any]:
    """The candidate routes for this request, annotated with cost and human gates."""
    try:
        resolution = resolve_operated_mode(request, intent=intent)
        proposal = resolution.get("proposal") or research_plan.propose_for_request(
            request, intent=intent
        )
    except Exception:  # noqa: BLE001 — a briefing still renders without a route match
        return {"available": False, "matched": False, "auto_mode": None, "routes": []}
    routes: list[dict[str, Any]] = []
    resolved_tier = resolution.get("tier")
    for intent_block in proposal.get("intents", [])[:1]:
        for tier in intent_block.get("tiers") or []:
            cost = tier.get("cost") or {}
            validation = tier.get("validation") or {}
            routes.append({
                "id": tier.get("id"),
                "label": tier.get("label", ""),
                "recommended": (
                    str(tier.get("id") or "") == resolved_tier
                    if resolved_tier else bool(tier.get("recommended"))
                ),
                "why": tier.get("why", ""),
                "modes": list(tier.get("modes") or []),
                "size": _BAND_WORDS.get(str(cost.get("band")), str(cost.get("band") or "")),
                "gates": [g.get("gate") for g in (tier.get("gates") or []) if g.get("gate")],
                "hand_driven": list(validation.get("spec_only") or []),
            })
    return {
        "available": bool(routes),
        "matched": bool(proposal.get("matched")),
        "intent": (proposal.get("intents") or [{}])[0].get("intent", ""),
        "auto_mode": resolution["mode"],
        "auto_intent": resolution.get("intent"),
        "auto_tier": resolved_tier,
        "auto_matched_signals": list(resolution.get("matched_signals") or []),
        "routes": routes,
    }


def build_briefing(request: str, *, project: Optional[str] = None,
                   intent: Optional[str] = None, **scan_kwargs: Any) -> dict[str, Any]:
    """Scan the world, then assemble the structured pre-task briefing."""
    facts = scan_all(request, project=project, **scan_kwargs)
    return {"contract": "director-briefing/v1", "request": request, "project": project,
            "facts": facts, "routes": _route_options(request, intent)}


# --------------------------------------------------------------------------- rendering

def _section_what(briefing: dict[str, Any]) -> list[str]:
    project = briefing.get("project") or "（还没指定研究项目）"
    return ["## 1. 这次要做什么", "",
            f"- **你的要求**：{briefing.get('request') or '（空）'}",
            f"- **归属项目**：{project}", ""]


def _section_known(facts: dict[str, Any]) -> list[str]:
    vault = facts.get("vault") or {}
    related = facts.get("related_knowledge") or {}
    out = ["## 2. 库里已经有什么", ""]
    if not vault.get("available"):
        out += [f"- {vault.get('note', '没能读到知识库')}", ""]
        return out
    kinds = "、".join(f"{row['label']} {row['count']} 篇" for row in vault.get("by_kind") or [])
    out.append(f"- **知识库总量**：{vault.get('total_pages', 0)} 篇已核实的条目"
               + (f"（{kinds}）" if kinds else ""))
    pending = vault.get("unprocessed_raw_files") or 0
    if pending:
        out.append(f"- **还没整理进库的原始文件**：{pending} 份")
    hits = (related.get("hits") or [])[:_MAX_RELATED]
    if hits:
        out += ["- **跟这次要求直接相关的已有条目**（可以直接复用，不用重查）："]
        out += [f"    - `{h['slug']}`" + (f" —— {h['section']}" if h.get("section") else "")
                for h in hits]
    else:
        out.append("- **相关条目**：库里没搜到对口的现成知识，这次要从头查")
    out.append("")
    return out


def _section_how(briefing: dict[str, Any]) -> list[str]:
    routes = briefing.get("routes") or {}
    out = ["## 3. 打算怎么做", ""]
    if not routes.get("available"):
        out += ["- 这条要求没有匹配到现成路线，我会把候选做法列给你选，不会自己猜。", ""]
        return out
    if not routes.get("matched"):
        out.append("> 说明：你的措辞没有精确命中某条既定路线，下面是全部候选，由你挑。")
        out.append("")
    auto_mode = routes.get("auto_mode")
    if auto_mode:
        out += [f"- **自动开工入口**：{words.say(str(auto_mode))}", ""]
    out += ["| 方案 | 做什么 | 规模 | 需要手动驱动的环节 |",
            "|---|---|---|---|"]
    for route in routes.get("routes") or []:
        star = " ⭐建议" if route.get("recommended") else ""
        steps = " → ".join(words.say(m) if words.say(m) != m else m
                           for m in route.get("modes") or []) or "—"
        manual = "、".join(route.get("hand_driven") or []) or "无，全程一键"
        out.append(f"| {route.get('label') or route.get('id')}{star} | {steps} "
                   f"| {route.get('size') or '—'} | {manual} |")
    out.append("")
    for route in routes.get("routes") or []:
        if route.get("recommended") and route.get("why"):
            out += [f"**为什么建议这条**：{route['why']}", ""]
    return out


def _section_gates(briefing: dict[str, Any]) -> list[str]:
    routes = briefing.get("routes") or {}
    picked = next((r for r in routes.get("routes") or [] if r.get("recommended")), None)
    gates = list((picked or {}).get("gates") or [])
    out = ["## 4. 会在哪里停下来等你拍板", ""]
    if not gates:
        out += ["- 这条路线中途没有需要你签字的关卡；做完直接给你看结果。", ""]
        return out
    out += [f"- {words.gate_label(g)}" for g in gates]
    out += ["", "> 这些决定机器永远不会替你做——它只把依据摆出来。", ""]
    return out


def _section_resources(facts: dict[str, Any]) -> list[str]:
    res = facts.get("resources") or {}
    out = ["## 5. 现在有什么资源 / 什么做不了", ""]
    ready = res.get("compute_ready") or []
    watch = res.get("compute_watch_only") or []
    if ready:
        out += [f"- ✅ **能真跑实验的机器**：{r['display_name']}" for r in ready]
    else:
        out.append("- ⚠️ **目前没有可以直接提交任务的机器** —— 这次只能出设计和脚本，不能出实验结果。")
    for r in watch:
        caps = "、".join(words.say(c) for c in r.get("capabilities") or []) or "什么都做不了"
        out.append(f"- 👀 **{r['display_name']}**：现在{caps}，**不能提交任务**")
        for blocker in r.get("blockers") or []:
            out.append(f"    - 卡在：{words.say(blocker)}")
    out.append("")
    return out


def _section_footer(briefing: dict[str, Any]) -> list[str]:
    terms: list[str] = []
    for route in (briefing.get("routes") or {}).get("routes") or []:
        terms.extend(route.get("modes") or [])
    glossary = words.glossary_for(terms)
    out = ["## 6. 你现在可以做的选择", "",
           "- 说「**开始**」→ 我按建议方案跑",
           "- 说「**换成 X 方案**」→ 换一条路线",
           "- 说「**先别跑，我要改要求**」→ 停下重新对齐", ""]
    if glossary:
        out += ["<details><summary>名词对照（点开看）</summary>", ""]
        out += [f"- **{term}**：{gloss}" for term, gloss in glossary]
        out += ["", "</details>", ""]
    return out


def render_briefing(briefing: dict[str, Any]) -> str:
    """The plain-Chinese plan card. No acronym soup, no internal identifiers in the body."""
    facts = briefing.get("facts") or {}
    lines = ["# 开工前计划", "",
             "> 这是**动手之前**给你看的计划。我已经扫过知识库和现有资源，下面每个数字都来自真实文件。", ""]
    lines += _section_what(briefing)
    lines += _section_known(facts)
    lines += _section_how(briefing)
    lines += _section_gates(briefing)
    lines += _section_resources(facts)
    lines += _section_footer(briefing)
    return "\n".join(lines).rstrip() + "\n"


def brief(request: str, *, project: Optional[str] = None, intent: Optional[str] = None,
          **scan_kwargs: Any) -> tuple[dict[str, Any], str]:
    """Convenience: `(structured_briefing, markdown)` in one call."""
    data = build_briefing(request, project=project, intent=intent, **scan_kwargs)
    return data, render_briefing(data)


__all__ = ["brief", "build_briefing", "render_briefing"]
