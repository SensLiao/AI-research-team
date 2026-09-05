"""What the machine's governance actually costs, measured against what it actually gets used (v4 P7).

The memo put "governance slimming" last and said it must be **telemetry-driven**. This module is that
telemetry, and it is deliberately the *whole* of P7: it measures, buckets, and reports — it removes
nothing. Dropping a gate is the director's decision, and a model may not take it (the same reason P4
refused to auto-prune seats: the surfaces that look redundant are usually the independence
machinery).

It complements ``tools/worker_census.py`` rather than repeating it. P4 measured **reachability** — is
a seat wired to anything? (answer: all 163 are). P7 measures **exercise** — has a seat, mode, stage or
gate ever actually been used in a recorded run? Those are different questions and the answers differ
sharply, which is exactly the gap worth showing.

**Three measurement ceilings, stated rather than papered over:**

  1. ``obs.jsonl`` looks like a dispatch log and is not one — it records ONE per-stage *lead* label,
     so reading it as "which seats ran" undercounts by roughly an order of magnitude. The real
     dispatch record is one ``inbox/<STAGE>.<agent>.bundle.json`` per worker.
  2. The ledger's ``run_completed`` event is written far less often than runs finish, so counting
     completions from the ledger undercounts. The manifest's ``status`` is the reliable field.
  3. **Nothing records an individual check firing.** The ~two dozen checker/guard tools therefore sit
     in an ``unmeasurable`` bucket: this module will not invent a firing count for them, and their
     silence here is not evidence that they are dead.

With no run history on disk at all, everything reports ``telemetry: ABSENT`` and NOTHING is bucketed
as unused — you cannot call a surface unused when you have no usage data.
"""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any, Optional

import yaml

from research_agent_teams.tools import worker_census

_PKG = Path(__file__).resolve().parents[1]
RUNS_ROOT = _PKG / "runs"
GATES_DIR = _PKG / "gates"
TOOLS_DIR = _PKG / "tools"
OPERATED_MODES_DIR = _PKG / "operate" / "modes"

#: Tool-name shapes that make a tool a governance surface rather than a capability.
_GUARD_PATTERN = re.compile(r"(guard|gate|checker|check_|drift|validate_|verify|parity|sanity)")

#: Bundle basenames that are not a seat (they are artifact kinds), kept visible instead of dropped.
_NON_SEAT_BUNDLES = ("profile",)

TELEMETRY_ABSENT = "ABSENT"
TELEMETRY_PRESENT = "PRESENT"


# --------------------------------------------------------------------------- what the machine has

def operated_modes() -> list[str]:
    """The modes a director can actually press — read from REGISTRY, not from the directory.

    Globbing `operate/modes/*.py` over-counts: wave 2 (2026-08-04) left two recipe modules on disk
    that are deliberately NOT registered, because they have no test coverage yet. A file that exists
    is not a capability; only REGISTRY membership makes a mode one-button, and this census is the
    number that reaches PLATFORM-FACTS. Counting files here would have published two capabilities
    the director cannot press — the exact "claims outrun the code" drift this file exists to catch.
    """
    from research_agent_teams.operate.modes import REGISTRY

    return sorted(REGISTRY)


def named_gates() -> list[str]:
    return sorted(path.stem for path in GATES_DIR.glob("*.md"))


def guard_tools() -> list[str]:
    return sorted(
        path.stem for path in TOOLS_DIR.glob("*.py")
        if _GUARD_PATTERN.search(path.stem) and not path.stem.startswith("_")
    )


def surfaces() -> dict[str, Any]:
    """The governance inventory, enumerated from disk — never a written-down count."""
    roster = worker_census.roster()
    return {
        "operated_modes": operated_modes(),
        "named_human_gates": named_gates(),
        "guard_tools": guard_tools(),
        "rostered_seats": sorted(roster),
    }


# --------------------------------------------------------------------------- what has been used

def _run_dirs(runs_root: Path) -> list[Path]:
    if not runs_root.is_dir():
        return []
    return sorted(path.parent for path in runs_root.glob("*/*/manifest.yaml"))


def _seats_from_inbox(run_dir: Path) -> tuple[set[str], set[str], set[str]]:
    """Real dispatch evidence: one bundle per worker.

    An inbox holds three kinds of bundle and conflating them inflates the seat count (an earlier
    hand-count read 54 seats where there are 50, by treating four non-seat kinds as seats):

      ``<STAGE>.<seat>.bundle.json``  one dispatched worker — the only thing that counts as a seat
      ``<STAGE>.bundle.json``        a stage-level exit bundle, not a worker
      anything else                  another artifact kind (``profile``, ``review.<lens>``, …)

    Returns (seats, stage-level names, other names) so none of the three is silently dropped.
    """
    inbox = run_dir / "inbox"
    seats: set[str] = set()
    stage_level: set[str] = set()
    other: set[str] = set()
    if not inbox.is_dir():
        return seats, stage_level, other
    known = worker_census.agent_files()
    for path in inbox.glob("*.bundle.json"):
        stem = path.name[: -len(".bundle.json")]
        match = re.match(r"^([A-Z_]+)\.(.+)$", stem)
        if match is None:
            stage_level.add(stem)
        elif match.group(2) in known:
            seats.add(match.group(2))
        else:
            other.add(match.group(2))
    return seats, stage_level, other


def usage(runs_root: Path = RUNS_ROOT) -> dict[str, Any]:
    """Everything the recorded runs can honestly tell us. No estimate, no extrapolation."""
    run_dirs = _run_dirs(runs_root)
    if not run_dirs:
        return {"telemetry": TELEMETRY_ABSENT, "runs": 0}

    statuses: Counter = Counter()
    modes: Counter = Counter()
    stages: Counter = Counter()
    events: Counter = Counter()
    seats: Counter = Counter()
    stage_bundles: set[str] = set()
    other_bundles: set[str] = set()
    obs_lead_labels: set[str] = set()
    gate_decisions: Counter = Counter()
    pending_gates: list[dict[str, Any]] = []
    promotion_targets = 0
    doc_admission_records = 0
    doc_admissions_admitted = 0
    admitted_vault_slugs: set[str] = set()

    for run_dir in run_dirs:
        manifest = yaml.safe_load((run_dir / "manifest.yaml").read_text(encoding="utf-8")) or {}
        statuses[str(manifest.get("status"))] += 1
        modes[str(manifest.get("mode"))] += 1
        if manifest.get("pending_gates"):
            pending_gates.append({"run_id": manifest.get("run_id"),
                                  "gates": list(manifest["pending_gates"])})
        if manifest.get("promotion_targets"):
            promotion_targets += 1

        # Vault writes through the DOCUMENT lane. Counted from the gate's own record files rather than
        # from a ledger event, because the record file is written by the gate on every decision and works
        # retroactively for admissions that predate the ledger event being added at all.
        inbox = run_dir / "inbox"
        if inbox.is_dir():
            for record_path in sorted(inbox.rglob("document-promotion-record-*.json")):
                try:
                    record = json.loads(record_path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    continue
                doc_admission_records += 1
                if record.get("admissible") and record.get("vault_slug"):
                    doc_admissions_admitted += 1
                    admitted_vault_slugs.add(str(record["vault_slug"]))

        ledger = run_dir / "ledger.jsonl"
        if ledger.is_file():
            for line in ledger.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                kind = str(event.get("event_type"))
                events[kind] += 1
                payload = event.get("payload") or {}
                if kind == "stage_started":
                    stages[str(payload.get("stage"))] += 1
                if kind == "gate_resolved":
                    gate_decisions[str(payload.get("decision"))] += 1

        obs = run_dir / "obs.jsonl"
        if obs.is_file():
            for line in obs.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                try:
                    obs_lead_labels.add(str(json.loads(line).get("agent_name")))
                except json.JSONDecodeError:
                    continue

        dispatched, stage_only, other = _seats_from_inbox(run_dir)
        stage_bundles |= stage_only
        other_bundles |= other
        for seat in dispatched:
            seats[seat] += 1

    return {
        "telemetry": TELEMETRY_PRESENT,
        "runs": len(run_dirs),
        "run_status": dict(statuses),
        "modes_used": dict(modes.most_common()),
        "stages_entered": dict(stages.most_common()),
        "ledger_events": dict(events.most_common()),
        "seats_dispatched": dict(seats.most_common()),
        "stage_level_bundle_kinds": sorted(stage_bundles),
        "non_seat_bundle_kinds": sorted(other_bundles),
        "obs_lead_labels": sorted(obs_lead_labels),
        "gate_decisions": dict(gate_decisions),
        "runs_with_a_pending_gate": pending_gates,
        "runs_with_a_promotion_target": promotion_targets,
        "document_admissions": {
            "records": doc_admission_records,
            "admitted": doc_admissions_admitted,
            "vault_slugs": sorted(admitted_vault_slugs),
        },
    }


# --------------------------------------------------------------------------- the join

def _axis(name: str, have: list[str], used: list[str], ceiling: str) -> dict[str, Any]:
    used_set = set(used)
    return {
        "axis": name,
        "have": len(have),
        "exercised": sorted(used_set & set(have)),
        "never_exercised": sorted(set(have) - used_set),
        "used_but_not_in_the_inventory": sorted(used_set - set(have)),
        "measurement_ceiling": ceiling,
    }


def _findings(inventory: dict[str, Any], used: dict[str, Any]) -> list[dict[str, str]]:
    """Only findings the numbers above actually support."""
    out: list[dict[str, str]] = []

    leads = used.get("obs_lead_labels") or []
    dispatched = used.get("seats_dispatched") or {}
    if leads and dispatched and len(leads) < len(dispatched):
        out.append({
            "id": "obs-jsonl-is-not-a-dispatch-log",
            "what": f"`obs.jsonl` 里只有 {len(leads)} 个名字，而真实派发过的 agent 是 {len(dispatched)} 个。",
            "why": "它记的是每个阶段的 lead 标签（`agent_name: lead or \"operate\"`），不是每个 worker 的"
                   "派发记录。把它当派发日志读会少算一个数量级。真实记录是 "
                   "`inbox/<阶段>.<agent>.bundle.json` —— 一个 worker 一份。",
        })

    done = int((used.get("run_status") or {}).get("done", 0))
    completed_events = int((used.get("ledger_events") or {}).get("run_completed", 0))
    if done and completed_events < done:
        out.append({
            "id": "run-completed-event-is-under-written",
            "what": f"{done} 次运行按 manifest 是 done，但账本里只有 {completed_events} 条 "
                    f"`run_completed` 事件。",
            "why": "从账本事件数统计「完成了多少次」会严重少算。可信字段是 manifest 的 `status`；"
                   "账本的终结事件不是每次都写。",
        })

    doc = used.get("document_admissions") or {}
    vault_writes = int(doc.get("admitted", 0))
    frozen_promotes = int((used.get("ledger_events") or {}).get("promote", 0))
    if used.get("runs_with_a_promotion_target") == 0 and not frozen_promotes and not vault_writes:
        out.append({
            "id": "the-vault-write-path-has-never-been-exercised",
            "what": f"{used.get('runs')} 次真实运行里，promotion_target 为 0，promote 事件为 0，"
                    f"文档收录 0 次。",
            "why": "唯一能写进库的那条路（`/promote-to-vault`）在真实运行史上从没走过一次。"
                   "它不是多余 —— 是**没被实测过**。要减治理之前，先知道哪条路根本没试过。",
        })
    elif vault_writes and not frozen_promotes:
        rejected = max(0, int(doc.get("records", 0)) - vault_writes)
        out.append({
            "id": "only-the-document-lane-has-ever-written-the-vault",
            "what": f"库真的被写过 {vault_writes} 次，全部走**文档收录**通道"
                    + (f"（另有 {rejected} 次申请被检查拒了）" if rejected else "")
                    + "；**冻结结果**通道仍是 0 次。",
            "why": "两条通道不是一回事，不能混着报。文档收录只是把导演审过的 Markdown 收进库，"
                   "结构上不产生 `result-status`、不产生 `can-cite-thesis`、不产生任何我们自己的指标。"
                   "「能被论文引用的实验结果入库」这条路至今**没被实测过** —— 它要求 reviewer "
                   "APPROVE-FREEZE + leakage PASS + fairness pass，而那要先有真跑出来的结果。",
        })

    tools = inventory.get("guard_tools") or []
    if tools:
        out.append({
            "id": "per-check-firing-is-not-recorded-anywhere",
            "what": f"{len(tools)} 个 checker / guard 工具，真实运行记录里 0 条「某个检查跑了」的痕迹。",
            "why": "这不是说它们没跑 —— 是**没有任何东西记录它们跑没跑**。所以这一类既不能算"
                   "「用过」也不能算「没用过」，只能列进不可测。要真的做治理减法，第一步是给检查"
                   "加一行记录，而不是凭感觉砍。",
        })
    return out


def census(runs_root: Path = RUNS_ROOT) -> dict[str, Any]:
    """Join the inventory with the measured usage. Report-only: removes nothing, proposes nothing."""
    inventory = surfaces()
    used = usage(runs_root)
    absent = used["telemetry"] == TELEMETRY_ABSENT

    axes: list[dict[str, Any]] = []
    if not absent:
        axes.append(_axis("一键模式", inventory["operated_modes"],
                          list(used["modes_used"]),
                          "按 manifest 的 mode 字段精确计数；只覆盖 runs/ 里还在的运行。"))
        axes.append(_axis("agent", inventory["rostered_seats"],
                          list(used["seats_dispatched"]),
                          "来自 inbox 的 bundle 文件名（一个 worker 一份）；没有 inbox 的运行无法计入。"))
        # `/promote-to-vault` is the ONE named gate whose firing leaves a deterministic on-disk trace:
        # the gate itself writes a record file on every decision, admit or reject. The other four leave
        # nothing name-bearing, so they stay unclaimed rather than guessed.
        gates_evidenced = (
            ["promote-to-vault"]
            if (used.get("document_admissions") or {}).get("records")
            or (used.get("ledger_events") or {}).get("promote")
            else []
        )
        axes.append(_axis("导演决定点（gates/ 里的 5 个）", inventory["named_human_gates"], gates_evidenced,
                          "账本里的 gate 事件是**阶段**导演决定点（`configured_director_gate`），"
                          "不带 gates/ 里的检查点名，所以这一轴多数无法从账本判定。唯一例外是 "
                          "`/promote-to-vault` —— 它每次决定（收录或拒绝）都自己落一份 "
                          "`*promotion-record-*.json`，那是确定性痕迹，算「用过」。"
                          "其余四个一律留空，不拿文本里提到过当成触发过。"))

    return {
        "telemetry": used["telemetry"],
        "runs_measured": used.get("runs", 0),
        "inventory": {key: len(value) for key, value in inventory.items()},
        "usage": used,
        "axes": axes,
        "findings": _findings(inventory, used) if not absent else [],
        "authorizes": [],
        "does_not_authorize": [
            "不删除、不停用、不弱化任何检查点或检查 —— 这份只报数",
            "「没被用过」不等于「可以砍」：互相独立的搜索 agent / 独立审计 / 不能自查的查重员，"
            "正是结论可信的理由",
            "真要减治理，必须由导演拍板，并且逐项说清减掉之后失去什么",
        ],
    }


# --------------------------------------------------------------------------- rendering

def _bar(part: int, whole: int) -> str:
    return f"{part}/{whole}" + (f"（{round(100 * part / whole)}%）" if whole else "")


def render_census(report: dict[str, Any]) -> str:
    """Plain Chinese. Leads with the one sentence the director needs, then the numbers behind it."""
    if report["telemetry"] == TELEMETRY_ABSENT:
        return ("# 治理用量盘点\n\n"
                "> **没有可用的运行记录**（`runs/` 是空的或不存在）。\n\n"
                "所以这份不给任何「用过 / 没用过」的判断 —— 没有用量数据的时候，"
                "把任何东西说成没人用都是编的。先真跑几次，再回来看这份。\n")

    used = report["usage"]
    lines = ["# 治理用量盘点", "",
             f"> 基于 **{report['runs_measured']} 次真实运行**（不是估算，不是抽样）。",
             "> 这份**只报数**：不删任何检查点，也不建议删。要不要减是导演的决定。", ""]

    lines += ["## 一句话", "",
              "机器造出来的治理面，比真实用到的多得多 —— 但「没用到」的大部分原因是"
              "**那条路还没走过**，不是那道检查点多余。", ""]

    lines += ["## 有多少 vs 用过多少", "", "| 轴 | 造了多少 | 真用过 | 从没用过 |", "|---|---|---|---|"]
    for axis in report["axes"]:
        exercised, never = len(axis["exercised"]), len(axis["never_exercised"])
        lines.append(f"| {axis['axis']} | {axis['have']} | {_bar(exercised, axis['have'])} | {never} |")
    lines += [f"| checker / guard 工具 | {report['inventory']['guard_tools']} "
              "| **测不出来** | 测不出来 |", ""]

    for axis in report["axes"]:
        if axis["never_exercised"] and len(axis["never_exercised"]) <= 12:
            names = "、".join(f"`{n}`" for n in axis["never_exercised"])
            lines += [f"- **{axis['axis']}** 从没用过的是：{names}"]
        elif axis["never_exercised"]:
            lines += [f"- **{axis['axis']}** 从没用过 {len(axis['never_exercised'])} 项"
                      f"（前 8 个：{'、'.join(axis['never_exercised'][:8])} …）"]
    lines.append("")

    lines += ["## 每一轴能测到什么程度（先说清，别过度解读）", ""]
    for axis in report["axes"]:
        lines.append(f"- **{axis['axis']}**：{axis['measurement_ceiling']}")
    lines.append("")

    lines += ["## 真实运行长什么样", "",
              f"- 状态：{used['run_status']}",
              f"- 阶段进入次数：{used['stages_entered']}",
              f"- 导演决定点：{used['ledger_events'].get('gate_pending', 0)} 次挂起 / "
              f"{used['ledger_events'].get('gate_resolved', 0)} 次拍板，决定分布 {used['gate_decisions']}", ]
    doc = used.get("document_admissions") or {}
    if doc.get("records"):
        detail = "、".join(f"`{slug}`" for slug in doc.get("vault_slugs") or [])
        rejected = max(0, int(doc["records"]) - int(doc["admitted"]))
        lines.append(f"- 📥 入库：**文档收录**通道成功写进库 {doc['admitted']} 次"
                     + (f"（另有 {rejected} 次被检查拒了）" if rejected else "")
                     + (f"，已入库页：{detail}" if detail else "")
                     + "；冻结结果通道 "
                     + f"{used['ledger_events'].get('promote', 0)} 次")
    if used["runs_with_a_pending_gate"]:
        for row in used["runs_with_a_pending_gate"]:
            lines.append(f"- ⏸ 还在等你拍板：`{row['run_id']}`（卡在 {row['gates']}）")
    if used["stage_level_bundle_kinds"] or used["non_seat_bundle_kinds"]:
        lines.append(f"- inbox 里另有 {len(used['stage_level_bundle_kinds'])} 类**阶段级**产物 + "
                     f"{len(used['non_seat_bundle_kinds'])} 类其他产物"
                     f"（{'、'.join(used['non_seat_bundle_kinds'])}）—— 都不是 agent，"
                     "没算进 agent 统计，也没悄悄丢掉")
    lines.append("")

    if report["findings"]:
        lines += ["## 量出来的问题", ""]
        for finding in report["findings"]:
            lines += [f"**{finding['what']}**", "", finding["why"], ""]

    lines += ["## 这份**不**授权什么", ""]
    lines += [f"- {line}" for line in report["does_not_authorize"]]
    lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Measure governance surfaces against real run usage. Reports only; removes nothing."
    )
    parser.add_argument("--runs-root", default=str(RUNS_ROOT))
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    report = census(Path(args.runs_root))
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(render_census(report), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["census", "guard_tools", "main", "named_gates", "operated_modes", "render_census",
           "surfaces", "usage"]
