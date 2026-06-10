"""Bounded in-stage repair — the BFTS / Co-STEER absorption seam (operate layer, wave 1).

Before this module, a deterministic hard-gate BLOCK (GateBlock) halted a run with ZERO
revise-and-resubmit attempts: the director was escalated to on the first failure. The landscape's
core primitive (AI-Scientist-v2 BFTS debug-depth bound, RD-Agent Co-STEER repair, AIDE
draft/debug/improve) is a BOUNDED in-stage loop: feed the gate's feedback back to the worker a
few times, THEN escalate. This module is that loop's deterministic controller:

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
from .artifacts import GateBlock

DEFAULT_MAX_DEBUG_RETRIES = 3  # safe default: 2 repair attempts, the 3rd failure escalates


def _state_path(run_dir) -> Path:
    return Path(run_dir) / "inbox" / "repair-state.json"


def load_state(run_dir) -> dict:
    p = _state_path(run_dir)
    if not p.exists():
        return {"attempts": []}
    return json.loads(p.read_text(encoding="utf-8"))


def _save_state(run_dir, state: dict) -> None:
    p = _state_path(run_dir)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")


def failures_for_stage(run_dir, stage: str) -> int:
    return sum(1 for a in load_state(run_dir)["attempts"] if a["stage"] == stage)


def _effective_budget(budget: dict) -> dict:
    """The repair cap, with a SAFE default when the mode's budget omits it (never unbounded)."""
    b = dict(budget or {})
    if b.get("max_debug_retries_per_run") is None:
        b["max_debug_retries_per_run"] = DEFAULT_MAX_DEBUG_RETRIES
    return b


def build_feedback(stage: str, attempt: int, reason: str) -> str:
    """The feedback block the skill appends to the re-dispatched worker's prompt."""
    return (f"REPAIR ATTEMPT {attempt} for stage {stage}: your previous bundle was BLOCKED by a "
            f"deterministic hard gate.\nGate feedback (fix EXACTLY this, change nothing else):\n"
            f"    {reason}\nRe-emit the COMPLETE corrected bundle to the same output path. "
            f"Do not argue with the gate; do not relax any honesty rule to pass it.")


def attempt_with_repair(run_dir, stage: str, budget: dict, ts: str,
                        dets_fn: Callable[[], object]) -> Tuple[str, object]:
    """Run a stage's deterministic producers once, absorbing ONE GateBlock into the repair loop.

    Returns ("ok", result) when dets_fn succeeds, or ("retry", feedback_text) when it was
    blocked and the budget allows another in-stage attempt. Re-raises the GateBlock unchanged
    when the cap is reached — the director sees the ORIGINAL gate reason, not a wrapper.
    """
    try:
        return ("ok", dets_fn())
    except GateBlock as e:
        state = load_state(run_dir)
        state["attempts"].append({"stage": stage, "reason": str(e), "ts": ts})
        _save_state(run_dir, state)
        n_failures = sum(1 for a in state["attempts"] if a["stage"] == stage)
        # `max_debug_retries_per_run` is a RETRY budget: cap=N must permit N retry prompts. The just-failed
        # attempt has consumed (n_failures - 1) retries so far; escalate only when THIS failure would push
        # the consumed-retry count to the cap. (cap=3 -> 3 retries then escalate; cap=1 -> 1 retry.)
        retries_consumed = n_failures - 1
        if violations(_effective_budget(budget), {"debug_retries": retries_consumed}):
            raise  # retry budget exhausted -> escalate the ORIGINAL GateBlock to the director
        return ("retry", build_feedback(stage, n_failures, str(e)))
