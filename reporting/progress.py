"""Post-task progress report — what the director reads AFTER the work runs.

Director lock (2026-08-01): "完成完任务后要给我汇报任务进度（通俗易懂的方式，
格式化的汇报，不要带一堆缩写和字母代名词）".

Six questions, in this order:

1. 这次到底做出了什么？（一句话）
2. 走到哪一步了，有没有卡住？
3. 你现在能打开看的东西在哪？
4. 哪些能说，哪些还不能说？（诚实边界）
5. 需要你做什么决定？
6. 下一步是什么？

Deterministic and read-only.  Every claim traces to a file in the run directory;
if a file is absent the report SAYS so rather than filling the gap.  It is pure
— it never imports the operate layer, so the CLI can call in without a cycle.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from ..tools import research_output_quality as quality
from . import plain_words as words

_UNFINISHED_HINT = {
    "failed": "中途停下了，没有跑完",
    "rejected": "被你在决定点上否决了",
    "crashed_mid_stage": "跑到一半中断了，可以从断点续上",
    # `awaiting_director` is what `operate/spine.py` actually writes; `awaiting` is kept for older runs.
    "awaiting": "停在决定点上，等你拍板",
    "awaiting_director": "停在决定点上，等你拍板",
    "awaiting_resume": "停下了，等着从断点续跑",
    "tampered": "记录对不上，这次结果不可信",
    "inconsistent": "记录表和流水对不上，需要人工看一眼",
}

# Every status that means "the machine is deliberately stopped, waiting for the human".
_AWAITING = ("awaiting", "awaiting_director")


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _read_yaml(path: Path) -> dict[str, Any]:
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, yaml.YAMLError):
        return {}
    return value if isinstance(value, dict) else {}


def _director_files(root: Path) -> list[str]:
    """Everything the director can actually open, newest-relevant first."""
    review = root / "director-review"
    if not review.is_dir():
        return []
    return sorted(p.relative_to(root).as_posix() for p in review.rglob("*.md") if p.is_file())


def build_progress(run_dir: str | Path) -> dict[str, Any]:
    """Assemble the structured progress facts for one run."""
    root = Path(run_dir)
    manifest = _read_yaml(root / "manifest.yaml")
    frame = _read_json(root / "task_frame.artifact.json").get("payload") or {}
    report = _read_json(root / "evidence" / "REPORT" / "report-note.artifact.json").get("payload") or {}
    mode = str(manifest.get("mode") or frame.get("mode") or "")
    completed = [str(item.get("stage")) for item in (manifest.get("completed_work") or [])
                 if isinstance(item, dict) and item.get("stage")]
    planned = [str(s) for s in (frame.get("stage_path") or manifest.get("stage_path") or [])]
    grade: dict[str, Any] = {}
    if mode:
        try:
            grade = quality.audit_run_output(root, mode)
        except Exception:  # noqa: BLE001 — a missing product must not break the report
            grade = {}
    return {
        "contract": "director-progress/v1",
        "run_dir": str(root),
        "run_id": str(manifest.get("run_id") or root.name),
        "project": str(manifest.get("project") or frame.get("project") or ""),
        "mode": mode,
        "request": str(frame.get("request_text") or ""),
        "status": str(manifest.get("status") or "unknown"),
        "completed_stages": completed,
        "planned_stages": planned or completed,
        "next_stage": str((manifest.get("next_step") or {}).get("stage") or ""),
        "summary": str(report.get("summary") or ""),
        "cannot_claim": [str(x) for x in (report.get("cannot_claim")
                                          or report.get("limitations") or []) if str(x).strip()],
        "delivery": str(report.get("markdown_delivery_status")
                        or report.get("delivery_status") or ""),
        "caveats": [str(x) for x in (report.get("delivery_caveats") or []) if str(x).strip()],
        "director_files": _director_files(root),
        "quality": grade,
        "pending_stages": [str(s) for s in (manifest.get("pending_gates") or [])],
        "pending_gates": _gates_for_mode(mode),
    }


def _gates_for_mode(mode: str) -> list[str]:
    """Which human gate(s) this mode's pause belongs to — DERIVED, never hand-typed.

    Reuses the status bar's recipe-driven mapping so the two never disagree; an unknown mode
    yields an empty list, and the report then says "waiting on you" without naming a button
    it cannot justify.
    """
    if not mode:
        return []
    try:
        from . import status_bar
        return sorted(gate for gate, modes in status_bar.gate_prerequisites().items()
                      if mode in modes)
    except Exception:  # noqa: BLE001 — a derivation failure must not break the report
        return []


# --------------------------------------------------------------------------- rendering

def _headline(data: dict[str, Any]) -> list[str]:
    summary = data.get("summary") or _paused_headline(data) or "（这次运行还没写出结论）"
    return ["## 1. 一句话结论", "", f"{summary}", ""]


def _paused_headline(data: dict[str, Any]) -> str:
    """A run stopped at a human gate has no REPORT note yet — but it is not a blank.

    The honest headline is the state itself: the work reached a decision boundary and is
    holding there for the director.  Saying "no conclusion" would read as failure.
    """
    if str(data.get("status")) not in _AWAITING:
        return ""
    stages = data.get("pending_stages") or []
    where = "、".join(words.say(s) for s in stages)
    done = len(data.get("completed_stages") or [])
    head = (f"做到「{where}」就停下了" if where else "做到决定点就停下了")
    return (f"{head}，等你拍板才能往下走"
            f"（已跑完 {done} 步，产物在第 3 节，决定在第 5 节）。")


def _progress_bar(data: dict[str, Any]) -> list[str]:
    planned = data.get("planned_stages") or []
    done = set(data.get("completed_stages") or [])
    out = ["## 2. 走到哪一步了", ""]
    if planned:
        steps = [("✅ " if s in done else "⬜ ") + words.say(s) for s in planned]
        out += ["  ".join(steps), ""]
    status = str(data.get("status") or "")
    hint = _UNFINISHED_HINT.get(status)
    if hint:
        out.append(f"- **当前状态**：{hint}")
    else:
        out.append(f"- **当前状态**：{words.say(status)}")
    if data.get("next_stage"):
        out.append(f"- **下一步要做**：{words.say(data['next_stage'])}")
    out.append("")
    return out


def _artifacts(data: dict[str, Any]) -> list[str]:
    files = data.get("director_files") or []
    out = ["## 3. 你现在能打开看什么", ""]
    if not files:
        out += ["- 这次还没有生成给你看的报告文件。", ""]
        return out
    out += [f"- `{path}`" for path in files]
    out += ["", f"（完整目录：`{data.get('run_dir')}`）", ""]
    return out


def _honesty(data: dict[str, Any]) -> list[str]:
    out = ["## 4. 哪些能说，哪些还不能说", ""]
    delivery = data.get("delivery")
    if delivery:
        out.append(f"- **这份产物的可用程度**：{words.say(delivery)}")
    for caveat in data.get("caveats") or []:
        out.append(f"- ⚠️ {caveat}")
    cannot = data.get("cannot_claim") or []
    if cannot:
        out.append("- **现在还不能声称的**：")
        out += [f"    - {item}" for item in cannot]
    grade = data.get("quality") or {}
    if grade.get("status") == "fail":
        out.append("- ❌ 主报告没生成出来，这次结果不能当交付物。")
    elif grade.get("advisories"):
        missing = [a.split(":", 1)[-1] for a in grade["advisories"]
                   if a.startswith("missing_business_concept")]
        if missing:
            out.append("- 📝 报告里还缺这几块内容（不影响使用，但值得补）："
                       + "、".join(words.say(m) for m in missing))
    if len(out) == 2:
        out.append("- 没有额外的保留意见。")
    out.append("")
    return out


def _decisions(data: dict[str, Any]) -> list[str]:
    out = ["## 5. 需要你做的决定", ""]
    if str(data.get("status")) in _AWAITING:
        out.append("- 这次停在决定点上了，**必须你点头才能继续**。机器不会替你决定。")
        gates = data.get("pending_gates") or []
        if gates:
            named = " 或 ".join(words.gate_label(g) for g in gates)
            out.append(f"- **要按的是**：{named}")
        else:
            out.append("- 这个模式没有登记对应的决定点按钮 —— 直接告诉我「继续」或「换方向」即可。")
        out.append("")
        return out
    if str(data.get("status")) == "done":
        out += ["- 没有卡住的决定。唯一可选动作："
                f"{words.gate_label('/promote-to-vault')}——机器不会自己收，得你点头。", ""]
        return out
    out += ["- 先看第 2 节的状态，决定是续跑、重来，还是换方向。", ""]
    return out


def render_progress(data: dict[str, Any]) -> str:
    """The plain-Chinese progress report."""
    title = data.get("request") or data.get("mode") or data.get("run_id")
    lines = ["# 任务进度汇报", "",
             f"> **这次的任务**：{title}",
             f"> **归属项目**：{data.get('project') or '（未指定）'}", ""]
    lines += _headline(data)
    lines += _progress_bar(data)
    lines += _artifacts(data)
    lines += _honesty(data)
    lines += _decisions(data)
    lines += ["## 6. 建议的下一步", "",
              "- 如果结果可用：说「**继续下一步**」，我接着往下推。",
              "- 如果结果不对：说「**哪里不对**」，我从那一步重做，不用整个重来。", ""]
    return "\n".join(lines).rstrip() + "\n"


def report(run_dir: str | Path) -> tuple[dict[str, Any], str]:
    """Convenience: `(structured_progress, markdown)` in one call."""
    data = build_progress(run_dir)
    return data, render_progress(data)


__all__ = ["build_progress", "render_progress", "report"]
