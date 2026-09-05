"""导演状态栏 —— 「我在哪一步，现在该我按哪个按钮」。

Director lock 2026-08-04, in the director's own words: *"这东西我都不知道什么时候用它，什么时候摁它。
就得告诉我：我目前 project 到了一个什么状态，到了哪一步后才需要进行这个 idea-bet。"*
So every plan card and every progress report now ends with this bar, and one verb prints it on demand.

Four deliberate design limits, so a status bar stays a status bar:

* **Five lines.** A bar nobody reads is worse than no bar. The full gate table is a separate verb.
* **Nothing hand-written that can be derived.** Which mode unlocks which gate comes from
  ``outcome_recipes``; the gate names from ``plain_words.known_gates()``; what is pending from the runs'
  own ``manifest.yaml``. A typed-in mapping would rot the first time a recipe changed — which is exactly
  the failure this file exists to prevent.
* **Index-free and read-only.** It reads manifests straight off disk, so it works before a
  ``workbench reindex`` and can never be the reason a report fails. It writes nothing, starts nothing.
* **A button is never invented.** If nothing is waiting on the director the bar says so. "现在没有要你按的"
  is a useful answer; a fabricated next action is not.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

import yaml

from ..tools import outcome_recipes
from . import plain_words

MACHINE_ROOT = Path(__file__).resolve().parents[1]
RUNS_ROOT = MACHINE_ROOT / "runs"

# `/promote-to-vault` is the one gate no research route unlocks: it is post-run and stands on a reviewed
# artifact existing, not on a mode having finished.  Stated here as data, and asserted by a test, rather
# than silently falling out of the derivation as "no prerequisite".
GATE_WITHOUT_A_MODE = "/promote-to-vault"
_PROMOTE_PREREQ = "有一份你已经看过的最终产物（论文卡 / 综述 / 点子 / 冻结结果）"

NOW, OPTIONAL, NOT_YET = "NOW", "OPTIONAL", "NOT_YET"
_MARK = {NOW: "✅ 现在就该按", OPTIONAL: "🟡 可以按，不强制", NOT_YET: "⏳ 还不到"}


# --------------------------------------------------------------------------- derivation

def gate_prerequisites() -> dict[str, list[str]]:
    """gate -> the modes that unlock it, derived from every recipe × every depth variant.

    Scanning variants matters: `direction-to-bet`'s default depth reaches `/idea-bet` after
    `new_direction`, its deepest depth after `deep_ideation`.  Reading only the resolved default would
    tell the director that the deep route has no gate.
    """
    unlocks: dict[str, set[str]] = {gate: set() for gate in plain_words.known_gates()}
    for recipe_id in outcome_recipes.recipe_ids():
        variants = [None]
        try:
            view = outcome_recipes.resolve(recipe_id)
        except (KeyError, ValueError):
            continue
        variants += [str(v.get("id")) for v in (view.get("variants") or []) if v.get("id")]
        for variant in variants:
            try:
                resolved = outcome_recipes.resolve(recipe_id, variant=variant)
            except (KeyError, ValueError):
                continue
            for entry in resolved.get("gates") or []:
                gate, after = entry.get("gate"), entry.get("after")
                if gate in unlocks and after:
                    unlocks[gate].add(str(after))
    return {gate: sorted(modes) for gate, modes in unlocks.items()}


def _manifests(runs_root: Path, project: Optional[str]) -> list[dict[str, Any]]:
    if not runs_root.is_dir():
        return []
    out: list[dict[str, Any]] = []
    for manifest_path in sorted(runs_root.glob("*/*/manifest.yaml")):
        try:
            data = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError):
            continue
        if project and str(data.get("project")) != project:
            continue
        data["_dir"] = manifest_path.parent
        out.append(data)
    return out


def _has_unadmitted_final_document(run_dir: Path) -> bool:
    """A finished run whose director-facing final Markdown has not been admitted to the vault.

    The review packet itself is excluded: it is the cover sheet for the run, not a knowledge page.
    """
    review = run_dir / "director-review"
    if not review.is_dir():
        return False
    finals = [p for p in review.rglob("*.md") if p.name != "00-REVIEW-PACKET.md"]
    if not finals:
        return False
    inbox = run_dir / "inbox"
    if inbox.is_dir():
        for record in inbox.rglob("*promotion-record-*.json"):
            try:
                import json
                if (json.loads(record.read_text(encoding="utf-8")) or {}).get("admissible"):
                    return False
            except (OSError, ValueError):
                continue
    return True


def build_state(project: Optional[str] = None, *, runs_root: Optional[Path | str] = None) -> dict[str, Any]:
    """Everything the bar needs, measured off disk. No estimate, no index, no writes."""
    root = Path(runs_root) if runs_root else RUNS_ROOT
    manifests = _manifests(root, project)
    prereqs = gate_prerequisites()
    modes_run = {str(m.get("mode")) for m in manifests}

    waiting: list[dict[str, Any]] = []
    for manifest in manifests:
        if str(manifest.get("status")) != "awaiting_director" and not manifest.get("pending_gates"):
            continue
        stages = [str(s) for s in (manifest.get("pending_gates") or [])]
        mode = str(manifest.get("mode"))
        gates = sorted(g for g, modes in prereqs.items() if mode in modes)
        waiting.append({
            "run_id": str(manifest.get("run_id")),
            "project": str(manifest.get("project")),
            "mode": mode,
            "stages": stages,
            "stage_words": "、".join(plain_words.say(s) for s in stages),
            "gates": gates,
            "_when": str(manifest.get("updated_at") or manifest.get("created_at") or ""),
        })
    # Newest first.  Path order (the manifest glob) is meaningless to the director: with two runs
    # paused on the same gate it pointed at whichever run_id sorted first, so right after finishing
    # a run they were sent to an older one.  Recency is the only defensible tiebreak.
    waiting.sort(key=lambda row: (row["_when"], row["run_id"]), reverse=True)

    promotable = [str(m.get("run_id")) for m in manifests
                  if _has_unadmitted_final_document(m["_dir"])]
    frozen_candidates = [str(m.get("run_id")) for m in manifests if m.get("promotion_targets")]

    due: dict[str, dict[str, Any]] = {}
    for gate in plain_words.known_gates():
        if gate == GATE_WITHOUT_A_MODE:
            n = len(promotable) + len(frozen_candidates)
            due[gate] = {
                "state": OPTIONAL if n else NOT_YET,
                "prerequisite": _PROMOTE_PREREQ,
                "why": (f"有 {n} 份跑完的最终产物还没收进库" if n
                        else "还没有跑完、你审过的最终产物"),
                "runs": promotable + frozen_candidates,
            }
            continue
        blocked_on = prereqs.get(gate) or []
        hits = [row for row in waiting if gate in row["gates"]]
        if hits:
            queued = "" if len(hits) == 1 else f"（还有 {len(hits) - 1} 个运行也在等同一个按钮）"
            due[gate] = {
                "state": NOW,
                "prerequisite": "跑完 " + " / ".join(blocked_on),
                "why": "运行 `%s` 停在「%s」等你%s" % (
                    hits[0]["run_id"], hits[0]["stage_words"] or "检查点", queued),
                "runs": [row["run_id"] for row in hits],
            }
        else:
            ran = [m for m in blocked_on if m in modes_run]
            due[gate] = {
                "state": NOT_YET,
                "prerequisite": "跑完 " + " / ".join(blocked_on) if blocked_on else "—",
                "why": ("跑过 %s 但没有停在决定点上" % "、".join(ran)) if ran
                       else ("要先跑一次 " + " 或 ".join(blocked_on) if blocked_on else "没有前置模式"),
                "runs": [],
            }

    statuses: dict[str, int] = {}
    for manifest in manifests:
        key = str(manifest.get("status"))
        statuses[key] = statuses.get(key, 0) + 1

    return {
        "project": project,
        "runs": len(manifests),
        "run_status": statuses,
        "waiting": waiting,
        "gates": due,
        "gate_prerequisites": prereqs,
        "promotable_runs": promotable,
        "frozen_candidate_runs": frozen_candidates,
        "modes_ever_run": sorted(modes_run - {"None"}),
    }


# --------------------------------------------------------------------------- rendering

def render_bar(state: dict[str, Any]) -> str:
    """The five-line bar that ends every card and every report."""
    title = state["project"] or "全部项目"
    done = state["run_status"].get("done", 0)
    head = (f"━━ 项目状态 · {title} ━━ 运行 {state['runs']} 次"
            f"（跑完 {done}｜停着等你 {len(state['waiting'])}）")
    lines = [head]

    now = [g for g, row in state["gates"].items() if row["state"] == NOW]
    optional = [g for g, row in state["gates"].items() if row["state"] == OPTIONAL]
    not_yet = [g for g, row in state["gates"].items() if row["state"] == NOT_YET]

    if now:
        for gate in now:
            lines.append(f"👉 现在该你按：{gate} —— {state['gates'][gate]['why']}")
    else:
        lines.append("👉 现在没有要你按的按钮 —— 机器这边没有停在等你的东西")
    for gate in optional:
        lines.append(f"   可选：{gate} —— {state['gates'][gate]['why']}")
    if not_yet:
        lines.append("⏳ 还不到：" + " · ".join(not_yet)
                     + " —— " + state["gates"][not_yet[0]]["why"])
    lines.append("📖 每个按钮什么时候按：python -m research_agent_teams.workbench gates"
                 + (f" --project {title}" if state["project"] else ""))
    return "\n".join(lines)


def render_gates(state: dict[str, Any]) -> str:
    """The bar plus the one table the director asked for: 四个按钮，各自什么时候才需要按。"""
    lines = [render_bar(state), "", "## 四个按钮，什么时候按", "",
             "| 按钮 | 决定什么 | 什么时候才需要按 | 现在 |", "|---|---|---|---|"]
    for gate in plain_words.known_gates():
        row = state["gates"][gate]
        decides = plain_words.gate_label(gate).split("（")[0]
        lines.append(f"| `{gate}` | {decides} | {row['prerequisite']} | "
                     f"{_MARK[row['state']]}：{row['why']} |")
    lines += ["", "> 四个按钮都只有你能按（机器永远不自己按）。没到条件的那几个，"
              "按了也没有依据可看 —— 先把前置那一步跑完。", ""]
    if state["waiting"]:
        lines += ["## 停着等你的运行", ""]
        for row in state["waiting"]:
            gates = "、".join(row["gates"]) or "（这个模式没有声明导演决定点）"
            lines.append(f"- `{row['run_id']}`（{row['mode']}）停在「{row['stage_words']}」→ {gates}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def bar_for(project: Optional[str] = None, *,
            runs_root: Optional[Path | str] = None) -> tuple[dict[str, Any], str]:
    """Deliberately NOT named `status_bar`: a function of that name, exported from the package
    ``__init__``, shadows this MODULE and breaks `from ..reporting import status_bar`."""
    state = build_state(project, runs_root=runs_root)
    return state, render_bar(state)


__all__ = ["bar_for", "build_state", "gate_prerequisites", "render_bar", "render_gates",
           "NOW", "OPTIONAL", "NOT_YET", "GATE_WITHOUT_A_MODE"]
