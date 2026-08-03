"""Bounded in-stage repair — the BFTS / Co-STEER absorption seam (operate layer, wave 1).

Only an explicit ``TargetedGateBlock(verdict="NEEDS_SUPPLEMENT")`` may enter the
revise-and-resubmit loop. A generic ``GateBlock`` has no machine-verifiable repair
scope, and ``TargetedGateBlock(verdict="BLOCK")`` is an explicit terminal refusal;
both are escalated immediately. This module is the bounded controller for the
remaining, local-repair case:

  - the cap comes from the task_frame budget's ``max_debug_retries_per_run`` — the previously
    dead counter in tools/budget_tracker.LIMIT_TO_USAGE — enforced through budget_tracker
    itself (usage key ``debug_retries``); missing budget -> a SAFE default cap, never unbounded;
  - attempt history is persisted to ``<run>/inbox/repair-state.json`` (inbox = worker-handoff
    scratch, NOT validated evidence), so a crashed run resumes with its repair count intact;
  - the loop NEVER crosses a stage boundary: graph.yaml stays forward-only acyclic — repair is
    re-doing THIS stage's WORK with feedback, exactly the engine's micro-protocol slot;
  - when the cap is reached the original GateBlock escalates to the director unchanged — the
    human gate is delayed by at most the cap, never removed.

Recipe usage (see operate/modes/*):
    outcome = attempt_with_repair(run_dir, stage, budget, ts, dets_fn)
    if outcome[0] == "ok":      artifact paths = outcome[1]  (commit the stage)
    if outcome[0] == "retry":   re-dispatch the stage worker with outcome[1] (the feedback
                                text) appended to its prompt, then call again.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Callable, Tuple

from ..tools.budget_tracker import violations
from .artifacts import GateBlock, TargetedGateBlock

DEFAULT_MAX_DEBUG_RETRIES = 3  # safe default: 2 repair attempts, the 3rd failure escalates
REPAIR_CONTRACT_VERSION = "incremental-repair/v2"


def _state_path(run_dir) -> Path:
    return Path(run_dir) / "inbox" / "repair-state.json"


def load_state(run_dir) -> dict:
    p = _state_path(run_dir)
    if not p.exists():
        return {"contract_version": REPAIR_CONTRACT_VERSION, "attempts": []}
    raw = json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"repair state must be an object: {p}")
    version = raw.get("contract_version")
    if version not in {None, REPAIR_CONTRACT_VERSION}:
        raise ValueError(f"unsupported repair-state contract {version!r}: {p}")
    attempts = raw.get("attempts", [])
    if not isinstance(attempts, list) or any(not isinstance(row, dict) for row in attempts):
        raise ValueError(f"repair state attempts must be an object list: {p}")
    return {"contract_version": REPAIR_CONTRACT_VERSION, "attempts": attempts}


def _save_state(run_dir, state: dict) -> None:
    p = _state_path(run_dir)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")


def failures_for_stage(run_dir, stage: str) -> int:
    return sum(1 for a in load_state(run_dir)["attempts"] if a.get("stage") == stage)


def _effective_budget(budget: dict) -> dict:
    """The repair cap, with a SAFE default when the mode's budget omits it (never unbounded)."""
    b = dict(budget or {})
    if b.get("max_debug_retries_per_run") is None:
        b["max_debug_retries_per_run"] = DEFAULT_MAX_DEBUG_RETRIES
    return b


def build_feedback(stage: str, attempt: int, reason: str, defects=None) -> str:
    """The feedback block the skill appends to the re-dispatched worker's prompt."""
    rows = [row for row in (defects or []) if isinstance(row, dict)]
    if rows:
        detail = "\n".join(
            f"- {row.get('defect_id', 'DEFECT')}: "
            f"{row.get('location', 'unspecified')}: "
            f"{row.get('summary') or row.get('reason') or 'targeted supplement required'}"
            for row in rows
        )
    else:
        detail = str(reason)[:12000]
    return (
        f"REPAIR ATTEMPT {attempt} for stage {stage}: submit a TARGETED SUPPLEMENT only.\n"
        f"Fix exactly these defects; preserve all unaffected analysis:\n{detail}\n"
        "The scheduler preserves the previous bundle, records before/after hashes and a diff, then "
        "reconciles the corrected bundle as v2. Do not change unrelated claims and do not relax any "
        "honesty rule."
    )


def _attempt_record(stage: str, ts: str, exc: GateBlock) -> dict:
    record = {
        "stage": stage,
        "reason": str(exc)[:12000],
        "ts": ts,
        "verdict": getattr(exc, "verdict", "NEEDS_SUPPLEMENT"),
        "defects": [],
        "target_agents": [],
        "refresh_agents": [],
    }
    if isinstance(exc, TargetedGateBlock):
        record["defects"] = exc.defects
        record["target_agents"] = sorted({
            str(agent)
            for row in exc.defects
            for agent in (row.get("target_agents") or [])
            if str(agent).strip()
        })
        record["refresh_agents"] = sorted({
            str(agent)
            for row in exc.defects
            for agent in (row.get("refresh_agents") or [])
            if str(agent).strip()
        })
    return record


def attempt_with_repair(run_dir, stage: str, budget: dict, ts: str,
                        dets_fn: Callable[[], object]) -> Tuple[str, object]:
    """Run deterministic producers, repairing only an explicit local supplement request.

    Returns ("ok", result) when dets_fn succeeds, or ("retry", feedback_text) only when
    ``TargetedGateBlock(..., verdict="NEEDS_SUPPLEMENT")`` has a remaining in-stage retry.
    Generic or terminal targeted blocks are re-raised unchanged; the repair cap also re-raises
    when the cap is reached — the director sees the ORIGINAL gate reason, not a wrapper.
    """
    try:
        return ("ok", dets_fn())
    except GateBlock as e:
        # Only an explicit local supplement may use the retry loop.  Generic
        # GateBlocks and explicit targeted BLOCK verdicts are terminal.
        if not isinstance(e, TargetedGateBlock) or e.verdict == "BLOCK":
            raise
        state = load_state(run_dir)
        state["attempts"].append(_attempt_record(stage, ts, e))
        _save_state(run_dir, state)
        n_failures = sum(1 for a in state["attempts"] if a["stage"] == stage)
        # `max_debug_retries_per_run` is a RETRY budget: cap=N must permit N retry prompts. The just-failed
        # attempt has consumed (n_failures - 1) retries so far; escalate only when THIS failure would push
        # the consumed-retry count to the cap. (cap=3 -> 3 retries then escalate; cap=1 -> 1 retry.)
        retries_consumed = n_failures - 1
        if violations(_effective_budget(budget), {"debug_retries": retries_consumed}):
            raise  # retry budget exhausted -> escalate the ORIGINAL GateBlock to the director
        return ("retry", build_feedback(stage, n_failures, str(e), getattr(e, "defects", None)))
