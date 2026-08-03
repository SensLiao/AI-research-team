"""Replay a recorded multi-agent example from its own receipts (v4 P6).

**What this is, stated before anything else.** It is a REPLAY, not a re-run. It calls no model,
opens no network, touches no GPU, and dispatches no sub-agent. It takes the artifacts a recorded
collaboration left on disk and re-derives them: every declared ``path`` → ``sha256`` binding is
recomputed from the file, the council bundle is recompiled from the recorded contributions by the
CURRENT code, the three-judge reconciliation is recomputed from the recorded sheets, and the
blind-mapping and repair orderings are re-checked. The verdict is stamped
:data:`REPLAY_STATUS` — never ``EXECUTED``.

**Why a replay is worth more than the tests that already exist.** ``tests/test_t4_*`` pin *this*
example's specific ids, hashes and verdicts, so they answer "did anyone edit the example?". The
replay answers a different question: "is the recorded run still internally consistent, and does the
code that produced it still produce it?" It discovers the chain from disk instead of hardcoding it,
so it survives the example changing, and it fails loudly if a single recorded byte moves.

Deliberately NOT here: any path that could turn a design-only example into a result. If the recorded
example says ``DESIGN_ONLY``, the replay says ``DESIGN_ONLY``.
"""
from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional

from research_agent_teams.tools import native_dispatch_trace as native
from research_agent_teams.tools.mechanism_council import compile_bundle

_PKG_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PROJECT = _PKG_ROOT / "projects" / "t4-scribble-m0-mechanism-eval"

#: The only status this module may emit. A recorded run is evidence that the CONTRACTS operated; it
#: is never evidence that anything was executed, measured, or scientifically established.
REPLAY_STATUS = "REPLAY_OF_RECORDED_RUN"

#: Keys under which a recorded artifact declares the digest of a file it names.
_HASH_KEYS = ("sha256", "file_sha256")


class ExampleReplayError(ValueError):
    """Raised when the example cannot be located or read at all (not when a check fails)."""


# --------------------------------------------------------------------------------- plumbing

def _json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _utc(value: str) -> datetime:
    rendered = value[:-1] + "+00:00" if value.endswith("Z") else value
    rendered = re.sub(r"(\.\d{6})\d+(?=[+-]\d{2}:\d{2}$)", r"\1", rendered)
    return datetime.fromisoformat(rendered).astimezone(timezone.utc)


def _resolve(project: Path, raw: str) -> Optional[Path]:
    """Recorded paths appear project-relative AND repo-relative, on both path separators."""
    text = str(raw).replace("\\", "/")
    marker = f"projects/{project.name}/"
    candidates = [project / text]
    if marker in text:
        candidates.append(project / text.split(marker, 1)[1])
    candidates.append(_PKG_ROOT.parent / text)
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def _bare(digest: str) -> str:
    return str(digest).split(":", 1)[-1].strip().lower()


def _check(name: str, ok: bool, detail: str) -> dict[str, Any]:
    return {"name": name, "ok": bool(ok), "detail": detail}


def _walk_bindings(value: Any, out: list[tuple[str, str, str]]) -> None:
    """Collect every (declared path, declared digest, which key) pair, at any depth."""
    if isinstance(value, Mapping):
        declared = value.get("path")
        if isinstance(declared, str):
            for key in _HASH_KEYS:
                digest = value.get(key)
                if isinstance(digest, str) and len(_bare(digest)) == 64:
                    out.append((declared, digest, key))
        for item in value.values():
            _walk_bindings(item, out)
    elif isinstance(value, list):
        for item in value:
            _walk_bindings(item, out)


# --------------------------------------------------------------------------------- the stages

def _deliberately_stale(project: Path) -> set[tuple[Path, str]]:
    """Digests a recorded abort says were ALREADY WRONG when the worker checked them.

    One of this example's honesty records is a worker that stopped because the file it was dispatched
    against no longer matched its packet (``SOURCE_HASH_MISMATCH_AFTER_DISPATCH``). The stale digest
    is preserved on purpose — in the abort record and in the superseded packet that caused it. A
    replay that demanded every recorded digest still match would report the *finding* as a defect.

    So these pairs get the INVERSE assertion: they must still fail to match. Erasing the recorded
    mismatch — "fixing" the example — then breaks the replay, which is the point. Derived from the
    failure records themselves, never a hardcoded allowlist.
    """
    stale: set[tuple[Path, str]] = set()
    failures = project / "native-eval" / "failures"
    if not failures.is_dir():
        return stale
    for path in sorted(failures.glob("*.json")):
        row = _json(path)
        if not str(row.get("reason_code") or "").endswith("_MISMATCH_AFTER_DISPATCH"):
            continue
        block = row.get("expected") or {}
        declared, digest = block.get("path"), block.get("sha256")
        if not (isinstance(declared, str) and isinstance(digest, str)):
            continue
        target = _resolve(project, declared)
        if target is not None:
            stale.add((target, _bare(digest)))
    return stale


def _stage_bindings(project: Path) -> dict[str, Any]:
    """Every recorded path→digest binding, recomputed from the bytes on disk.

    This is the tamper-detecting core: one edited byte anywhere the example points at breaks it.
    """
    bindings: list[tuple[str, str, str]] = []
    for path in sorted(project.rglob("*.json")):
        try:
            _walk_bindings(_json(path), bindings)
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
    stale = _deliberately_stale(project)
    checks: list[dict[str, Any]] = []
    unresolved: list[str] = []
    mismatched: list[str] = []
    healed: list[str] = []
    verified = 0
    stale_confirmed = 0
    for declared, digest, key in sorted(set(bindings)):
        target = _resolve(project, declared)
        if target is None:
            unresolved.append(declared)
            continue
        actual = native.sha256_file(target)
        expected = _bare(digest)
        if (target, expected) in stale:
            if actual == expected:
                healed.append(f"{declared}（记录说这个哈希当时就已经对不上了，现在却对上了）")
            else:
                stale_confirmed += 1
        elif actual != expected:
            mismatched.append(f"{declared} ({key}: 记录 {expected[:12]}… 实际 {actual[:12]}…)")
        else:
            verified += 1
    checks.append(_check("每条 path→哈希 绑定都用磁盘上的字节重算过",
                         not mismatched and verified > 0,
                         f"{verified} 条重算一致"
                         + (f"，{len(mismatched)} 条不一致：{'；'.join(mismatched)}" if mismatched else "")))
    checks.append(_check("被引用的文件都还在",
                         not unresolved,
                         "全部找到" if not unresolved else f"找不到 {len(unresolved)} 个：{unresolved}"))
    if stale or healed:
        checks.append(_check("那次「派发后发现源文件已变」的失败记录仍然成立（旧哈希仍然对不上）",
                             not healed and stale_confirmed > 0,
                             f"{stale_confirmed} 条刻意保留的旧哈希，仍然对不上 —— 失败记录没被抹掉"
                             if not healed else "；".join(healed)))
    return {"stage": "① 记录的哈希绑定", "checks": checks,
            "verified_bindings": verified, "stale_bindings_confirmed": stale_confirmed}


def _stage_dispatch(project: Path) -> dict[str, Any]:
    """Work orders, their completions, and the two recorded failures that produced nothing."""
    orders_dir = project / "native-eval" / "work-orders"
    completions_dir = project / "native-eval" / "completions"
    failures_dir = project / "native-eval" / "failures"
    if not orders_dir.is_dir():
        raise ExampleReplayError(f"no work-orders directory under {project}")

    orders = {p.stem: _json(p) for p in sorted(orders_dir.glob("*.json"))}
    completions = {p.stem: _json(p) for p in sorted(completions_dir.glob("*.json"))}
    failures = {p.stem: _json(p) for p in sorted(failures_dir.glob("*.json"))} \
        if failures_dir.is_dir() else {}

    broken_deps: list[str] = []
    dependency_edges = 0
    for order_id, order in orders.items():
        for dependency in order.get("dependencies") or []:
            dependency_edges += 1
            upstream = str(dependency.get("work_order_id"))
            recorded = completions.get(upstream)
            if recorded is None:
                broken_deps.append(f"{order_id} 依赖 {upstream}，但没有它的完成记录")
            elif _bare(dependency.get("output_sha256", "")) != _bare(
                    recorded.get("output", {}).get("sha256", "")):
                broken_deps.append(f"{order_id} 记的 {upstream} 输出哈希和该完成记录不符")

    leaked: list[str] = []
    for failure_id, failure in failures.items():
        if failure_id in completions:
            leaked.append(f"{failure_id} 被记为失败，却还有完成记录")
        declared = failure.get("output", {}).get("path") or failure.get("output_path")
        if isinstance(declared, str) and _resolve(project, declared) is not None:
            leaked.append(f"{failure_id} 被记为失败，但它声称的产物文件真的存在：{declared}")

    unmatched = sorted(set(orders) - set(completions) - set(failures))
    checks = [
        _check("每条工单要么有完成记录，要么有失败记录",
               not unmatched, f"{len(orders)} 条工单 · {len(completions)} 条完成 · "
                              f"{len(failures)} 条失败"
                              + (f"；无归属：{unmatched}" if unmatched else "")),
        _check("下游工单记的上游输出哈希，和上游完成记录一致",
               not broken_deps, f"{dependency_edges} 条依赖边全部对上"
                                if not broken_deps else "；".join(broken_deps)),
        _check("被放弃/中止的工单确实什么都没产出",
               not leaked, f"{len(failures)} 条失败记录，没有一条留下产物"
                           if not leaked else "；".join(leaked)),
    ]
    return {"stage": "② 派发与失败", "checks": checks,
            "orders": len(orders), "completions": len(completions), "failures": len(failures)}


def _stage_compile(project: Path) -> dict[str, Any]:
    """Recompile the council bundle from the recorded contributions with the CURRENT code."""
    native_dir = project / "native-eval"
    recorded_path = native_dir / "candidates" / "council-bundle.json"
    compiler_input = native_dir / "compiler-input.json"
    if not recorded_path.is_file() or not compiler_input.is_file():
        return {"stage": "③ 议会编译可复现", "checks": [
            _check("能找到编译输入和编译产物", False,
                   "缺 council-bundle.json 或 compiler-input.json —— 这一段无法复现")]}

    recorded = _json(recorded_path)
    order = _json(compiler_input)["work_order"]
    contributions = [
        _json(path) for path in sorted((native_dir / "contributions").glob("*.json"))
    ]
    checks: list[dict[str, Any]] = []
    try:
        rebuilt = compile_bundle(
            work_order={key: order[key] for key in ("request_id", "north_star", "input_sha256")},
            contributions=contributions,
            compiled_chain=recorded["compiled_chain"],
            conflicts=recorded["conflicts"],
            compiler_agent_id=recorded["truth_boundary"]["compiler_agent_id"],
        )
    except Exception as exc:  # a contract failure IS the finding, not a crash
        checks.append(_check("现在的代码能从记录的贡献重新编译出这份 bundle", False,
                             f"重新编译被拒：{exc}"))
        return {"stage": "③ 议会编译可复现", "checks": checks}

    identical = native.sha256_value(rebuilt) == native.sha256_value(recorded)
    checks.append(_check("现在的代码能从记录的贡献重新编译出**字节相同**的 bundle", identical,
                         "重新编译结果与记录完全一致" if identical
                         else "重新编译结果与记录不一致 —— 要么贡献被改过，要么编译逻辑变了"))
    receipts_match = [r for r in recorded["contribution_receipts"]] == \
                     [r for r in rebuilt["contribution_receipts"]]
    checks.append(_check("六席的哈希回执就是这六份贡献正文算出来的", receipts_match,
                         f"{len(recorded['contribution_receipts'])} 条回执逐条重算一致"
                         if receipts_match else "回执与贡献正文不符"))
    frozen = {row.get("input_sha256") for row in contributions}
    checks.append(_check("六席看的是同一份冻结工单", len(frozen) == 1,
                         f"input_sha256 只有 1 个取值：{next(iter(frozen))[:19]}…"
                         if len(frozen) == 1 else f"出现 {len(frozen)} 个不同取值：{frozen}"))
    return {"stage": "③ 议会编译可复现", "checks": checks}


def _stage_blind_review(project: Path) -> dict[str, Any]:
    """Recompute the three-judge aggregation, and re-check the commit-before / reveal-after order."""
    native_dir = project / "native-eval"
    sealed = native_dir / "sealed"
    packet = sealed / "blind-packet.json"
    sheets_dir = native_dir / "reviews" / "sheets"
    stored_path = native_dir / "reviews" / "reconciliation.json"
    checks: list[dict[str, Any]] = []
    if not (packet.is_file() and sheets_dir.is_dir() and stored_path.is_file()):
        return {"stage": "④ 三盲评审", "checks": [
            _check("能找到盲审包、评审表和汇总", False, "这一段的记录不全，无法复现")]}

    sheets = sorted(sheets_dir.glob("*.json"))
    try:
        report = native.reconcile_native_judges(blind_packet_path=packet, judge_sheets=sheets)
        stored = _json(stored_path)
        same_votes = report["winner_votes"] == stored["winner_votes"]
        same_state = report["evaluation_state"] == stored["evaluation_state"]
        checks.append(_check("现在重算三位评审的汇总，和记录一致", same_votes and same_state,
                             f"票数 {stored['winner_votes']} · 状态 {stored['evaluation_state']}"
                             if same_votes and same_state else
                             f"重算 {report['winner_votes']}/{report['evaluation_state']} "
                             f"≠ 记录 {stored['winner_votes']}/{stored['evaluation_state']}"))
        checks.append(_check("汇总只做描述，不声称统计推断",
                             stored.get("inferential_statistics_claimed") is False,
                             "inferential_statistics_claimed = false"))
    except Exception as exc:
        checks.append(_check("现在重算三位评审的汇总，和记录一致", False, f"重算被拒：{exc}"))
        return {"stage": "④ 三盲评审", "checks": checks}

    commitment_path = sealed / "mapping-commitment.json"
    reveal_path = sealed / "mapping-reveal.json"
    try:
        commitment = native.validate_mapping_commitment(commitment_path)
        reveal = native.validate_mapping_reveal(reveal_path, commitment=commitment_path)
    except Exception as exc:
        checks.append(_check("X/Y 映射先承诺、后揭晓", False, f"映射校验被拒：{exc}"))
        return {"stage": "④ 三盲评审", "checks": checks}

    review_orders = [p for p in (native_dir / "work-orders").glob("*REVIEW*.json")
                     if "PRECOMMIT" not in p.stem and "TARGETED" not in p.stem]
    review_completions = [native_dir / "completions" / p.name for p in review_orders]
    authorized = [_utc(_json(p)["authorized_at"]) for p in review_orders]
    completed = [_utc(_json(p)["completed_at"]) for p in review_completions if p.is_file()]
    before = bool(authorized) and _utc(commitment["created_at"]) <= min(authorized)
    after = bool(completed) and _utc(reveal["revealed_after_review_at"]) >= max(completed)
    checks.append(_check("映射在评审被派发之前就承诺了", before,
                         f"承诺时间 ≤ {len(authorized)} 份评审工单里最早的授权时间"
                         if before else "承诺时间晚于评审派发 —— 盲性不成立"))
    checks.append(_check("映射在评审全部交稿之后才揭晓", after,
                         f"揭晓时间 ≥ {len(completed)} 份评审里最晚的交稿时间"
                         if after else "揭晓时间早于评审交稿 —— 盲性不成立"))
    checks.append(_check("揭晓出来的对应关系保留在记录里", bool(reveal.get("mapping")),
                         f"X/Y → {reveal.get('mapping')}"))
    return {"stage": "④ 三盲评审", "checks": checks}


def _stage_repair(project: Path) -> dict[str, Any]:
    """Re-validate each targeted re-review against digests recomputed from the files it names."""
    native_dir = project / "native-eval"
    sealed = native_dir / "sealed"
    # Sort by the review's OWN recorded time, not by filename — `-r2` sorts before the unsuffixed
    # name, so a filename sort would have reported the rounds in the wrong order.
    reviews = sorted((native_dir / "reviews").glob("targeted-re-review*.json"),
                     key=lambda p: _utc(_json(p)["reviewed_at"]))
    checks: list[dict[str, Any]] = []
    if not reviews:
        return {"stage": "⑤ 修复与独立复审", "checks": [
            _check("能找到定向复审记录", False, "没有 targeted-re-review*.json")]}

    verdicts: list[str] = []
    for review_path in reviews:
        recorded = _json(review_path)
        packets = [p for p in sealed.glob("targeted-re-review-packet*.json")
                   if _json(p).get("output_path", "").endswith(review_path.name)]
        if not packets:
            checks.append(_check(f"{review_path.name} 有对应的授权包", False,
                                 "找不到指向它的 packet —— 无法独立复算"))
            continue
        packet = _json(packets[0])
        # The substantive independence property is "the reviewer is not the author of the repair it
        # reviews". One round's packet declares an explicit forbidden list and the other does not, so
        # the author is DERIVED from the repair completion the packet names. Otherwise the check would
        # pass vacuously against an empty list in the round that has none.
        forbidden = set(packet.get("forbidden_agent_ids") or [])
        declared_count = len(forbidden)
        repair_completion = _resolve(project, (packet.get("repair_completion") or {}).get("path", ""))
        if repair_completion is not None:
            author = _json(repair_completion).get("agent_id")
            if isinstance(author, str):
                forbidden.add(author)
        try:
            replayed = native.validate_targeted_re_review(
                review_path,
                repair_packet_sha256=_bare(packet["repair_packet"]["sha256"]),
                source_candidate_sha256=_bare(packet["source_candidate"]["sha256"]),
                repaired_candidate_sha256=_bare(packet["repaired_candidate"]["sha256"]),
                reconciliation_sha256=_bare(packet["reconciliation"]["sha256"]),
                forbidden_agent_ids=forbidden,
            )
        except Exception as exc:
            checks.append(_check(f"{review_path.name} 能按它自己的授权包重新校验", False, str(exc)))
            continue
        verdicts.append(str(replayed["overall_verdict"]))
        independent = bool(forbidden) and replayed["agent_id"] not in forbidden
        checks.append(_check(f"{review_path.name}：复审人不是它所审那份修复的作者", independent,
                             f"复审人 `{replayed['agent_id']}`；禁用 {len(forbidden)} 人"
                             f"（授权包声明 {declared_count} 人 + 从修复交稿记录推出的作者）"
                             if independent else "复审人就是修复作者，或禁用名单推不出来 —— 独立性不成立"))
        checks.append(_check(f"{review_path.name}：记录的结论和重算的结论一致",
                             replayed["overall_verdict"] == recorded["overall_verdict"],
                             f"结论 {replayed['overall_verdict']}"))

    kept_failure = verdicts[:1] == ["FAIL"] if verdicts else False
    checks.append(_check("第一次不通过的复审被**留在记录里**，没有被后来的通过覆盖掉", kept_failure,
                         f"按各自记录的时间排序：{' → '.join(verdicts)}" if verdicts else "没有结论"))
    return {"stage": "⑤ 修复与独立复审", "checks": checks, "verdicts": verdicts}


def _stage_boundary(project: Path) -> dict[str, Any]:
    """The example must still say design-only everywhere it said design-only."""
    native_dir = project / "native-eval"
    checks: list[dict[str, Any]] = []

    bundle = native_dir / "candidates" / "council-bundle.json"
    if bundle.is_file():
        boundary = _json(bundle)["truth_boundary"]
        ok = (boundary["execution_status"] == "DESIGN_ONLY"
              and boundary["result_claims_allowed"] is False
              and boundary["novelty_claim_allowed"] is False)
        checks.append(_check("议会产物仍然是 DESIGN_ONLY、不许声称结果或新颖性", ok,
                             f"execution_status = {boundary['execution_status']}"))

    dry_run = native_dir / "preflight" / "contract-dry-run.json"
    if dry_run.is_file():
        row = _json(dry_run)
        ok = (row.get("evidence_class") == "NOT_SCIENTIFIC_EVIDENCE"
              and row.get("scientific_claims_allowed") is False)
        checks.append(_check("预检记录仍然把自己标成「不是科学证据」", ok,
                             f"evidence_class = {row.get('evidence_class')} · "
                             f"preflight_state = {row.get('preflight_state')}"))

    manifest = project / "inputs" / "source-manifest.json"
    if manifest.is_file():
        row = _json(manifest).get("truth_boundary", {})
        ok = (row.get("server_query_performed") is False
              and row.get("gpu_experiment_performed") is False
              and row.get("scientific_result_allowed") is False)
        checks.append(_check("记录仍然写着：没连服务器、没跑 GPU、不许出科学结论", ok,
                             "三项全为 false" if ok else f"{row}"))
    if not checks:
        checks.append(_check("能找到真相边界声明", False, "这个例子没有任何边界声明文件"))
    return {"stage": "⑥ 真相边界", "checks": checks}


# --------------------------------------------------------------------------------- driver

def replay(project: str | Path = DEFAULT_PROJECT) -> dict[str, Any]:
    """Re-derive a recorded example. Never executes anything; returns a per-stage verdict."""
    root = Path(project)
    if not root.is_dir():
        raise ExampleReplayError(
            f"no recorded example at {root} — this project's durable workspace is not on disk"
        )
    stages = [
        _stage_bindings(root),
        _stage_dispatch(root),
        _stage_compile(root),
        _stage_blind_review(root),
        _stage_repair(root),
        _stage_boundary(root),
    ]
    failed = [c["name"] for stage in stages for c in stage["checks"] if not c["ok"]]
    total = sum(len(stage["checks"]) for stage in stages)
    return {
        "status": REPLAY_STATUS,
        "project": root.name,
        "verdict": "PASS" if not failed else "FAIL",
        "checks_run": total,
        "checks_failed": len(failed),
        "failed_checks": failed,
        "stages": stages,
        "what_this_is_not": [
            "没有调用任何模型，没有派任何 sub-agent",
            "没有连服务器，没有用 GPU，没有产生任何数字",
            "这是把记录下来的那次协作**按它自己的回执重新推导一遍**，不是重新跑一次",
        ],
    }


def render_replay(report: Mapping[str, Any]) -> str:
    """Plain-Chinese card. Leads with what a PASS does and does not mean."""
    verdict = report["verdict"]
    head = "✅ 全部重新推导通过" if verdict == "PASS" else f"❌ {report['checks_failed']} 项没通过"
    lines = [f"# 例子重新推导：{report['project']}", "",
             f"> {head} —— 一共重算 {report['checks_run']} 项检查。",
             f"> 状态 `{report['status']}`：**不是重新跑一次**。", ""]
    lines += ["## 这次重新推导做了什么 / 没做什么", ""]
    lines += [f"- {line}" for line in report["what_this_is_not"]]
    lines += ["", "> 通过说明的是：那次协作的**契约仍然成立、记录没被动过、现在的代码仍能复现它**。"
              "它不说明方法有效、结论新颖、或可以投稿。", ""]
    for stage in report["stages"]:
        lines += [f"## {stage['stage']}", ""]
        for check in stage["checks"]:
            mark = "✓" if check["ok"] else "✗"
            lines.append(f"- {mark} {check['name']} —— {check['detail']}")
        lines.append("")
    if verdict != "PASS":
        lines += ["## 没通过的项", ""] + [f"- {name}" for name in report["failed_checks"]] + [""]
    return "\n".join(lines).rstrip() + "\n"


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Re-derive a recorded multi-agent example from its own receipts (never re-runs it)."
    )
    parser.add_argument("--project", default=str(DEFAULT_PROJECT))
    parser.add_argument("--json", action="store_true", help="emit the machine-readable report")
    args = parser.parse_args(argv)

    report = replay(args.project)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(render_replay(report), end="")
    return 0 if report["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["ExampleReplayError", "REPLAY_STATUS", "main", "render_replay", "replay"]
