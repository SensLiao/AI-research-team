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

Plateau stopping (2026-08-07, OPT-IN): a caller that can measure the bundle's quality may hand this
module a score series or a ``quality_fn``. When two consecutive repair rounds move quality by less
than ``plateau_delta``, the loop stops spending rounds and escalates the SAME GateBlock it would have
escalated at the cap — earlier, with a reason. This buys fewer wasted rounds; it is NOT a new block
and it can never stop a run that the round cap would not have stopped anyway. **Callers that pass no
quality information behave exactly as before: the round cap is the only stop, labelled `round_cap`.**

Recipe usage (see operate/modes/*):
    outcome = attempt_with_repair(run_dir, stage, budget, ts, dets_fn)
    if outcome[0] == "ok":      artifact paths = outcome[1]  (commit the stage)
    if outcome[0] == "retry":   re-dispatch the stage worker with outcome[1] (the feedback
                                text) appended to its prompt, then call again.
    # optional, to stop early on a flat quality curve:
    outcome = attempt_with_repair(run_dir, stage, budget, ts, dets_fn, quality_fn=score_bundle)
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Callable, Optional, Sequence, Tuple

from ..tools.budget_tracker import violations
from .artifacts import GateBlock, TargetedGateBlock

DEFAULT_MAX_DEBUG_RETRIES = 3  # safe default: 2 repair attempts, the 3rd failure escalates
REPAIR_CONTRACT_VERSION = "incremental-repair/v2"

#: This repo scores quality on [0.0, 1.0] (schemas/idea_quality_eval.schema.json: every dimension has
#: minimum 0 / maximum 1, and tools/idea_quality_eval.py rounds to 3 dp on that scale). The upstream
#: stopping rule this absorbs is "< 0.5 on a 10-point scale", i.e. 5% of the range -> 0.05 here.
DEFAULT_PLATEAU_DELTA = 0.05

#: Two CONSECUTIVE sub-threshold deltas need three scores. One flat round is noise; two is a curve.
PLATEAU_MIN_SCORES = 3

#: Why the loop stopped spending rounds. `round_cap` is the pre-existing stop and the only one a
#: caller without quality information can ever see; the other three explain a plateau stop.
STOP_REASONS = ("plateau", "round_cap", "missing_evidence", "specialist_conflict")

#: Evidence-absence vocabulary, used ONLY to label an already-decided stop (never to trigger one).
_MISSING_EVIDENCE_TOKENS = (
    "missing", "no source", "not found", "unresolvable", "unresolved", "absent", "empty",
    "unverified", "no evidence", "evidence", "citation", "source_ref", "缺", "找不到", "无证据",
)


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
    state = {"contract_version": REPAIR_CONTRACT_VERSION, "attempts": attempts}
    # `last_stop` is an OPTIONAL receipt added alongside plateau stopping. It is deliberately not a
    # contract bump: a state file written before it exists still loads, and one written with it still
    # loads in an older checkout (which simply drops the key).
    last_stop = raw.get("last_stop")
    if isinstance(last_stop, dict):
        state["last_stop"] = last_stop
    return state


def last_stop(run_dir) -> Optional[dict]:
    """The stop receipt of the most recent escalation: stop_reason + state_summary, or None."""
    return load_state(run_dir).get("last_stop")


def _save_state(run_dir, state: dict) -> None:
    p = _state_path(run_dir)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")


def failures_for_stage(run_dir, stage: str) -> int:
    return sum(1 for a in load_state(run_dir)["attempts"] if a.get("stage") == stage)


def _effective_budget(budget: dict, run_dir=None) -> dict:
    """The repair cap, plus an explicit run-local director extension when present."""
    b = dict(budget or {})
    if b.get("max_debug_retries_per_run") is None:
        b["max_debug_retries_per_run"] = DEFAULT_MAX_DEBUG_RETRIES
    if run_dir is None:
        return b
    path = Path(run_dir) / "inbox" / "director-repair-budget-extension.json"
    if not path.is_file():
        return b
    try:
        extension = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"invalid director repair extension: {exc}") from exc
    base = b["max_debug_retries_per_run"]
    if (
        extension.get("contract_version") != "director-repair-extension/v1"
        or extension.get("authorized_by") != "director"
        or extension.get("dimension") != "max_debug_retries_per_run"
        or extension.get("base_limit") != base
        or not isinstance(extension.get("extended_limit"), int)
        or extension["extended_limit"] <= int(base)
        or not str(extension.get("reason") or "").strip()
    ):
        raise ValueError(
            "director repair extension must bind the current base limit, a larger integer "
            "limit, director authority, and a non-empty reason"
        )
    b["max_debug_retries_per_run"] = extension["extended_limit"]
    return b


def build_feedback(stage: str, attempt: int, reason: str, defects=None) -> str:
    """The feedback block the skill appends to the re-dispatched worker's prompt."""
    rows = [row for row in (defects or []) if isinstance(row, dict)]
    if rows:
        lines = []
        for row in rows:
            scope = row.get("allowed_json_pointers")
            target_ref = row.get("target_artifact_ref")
            target_hash = row.get("target_artifact_sha256")
            binding = ""
            if target_ref or target_hash or scope:
                binding = (
                    f" [target={target_ref or 'scheduler-bound'} @ "
                    f"{target_hash or 'scheduler-frozen-hash'}; allowed_json_pointers={scope or []}]"
                )
            lines.append(
                f"- {row.get('defect_id', 'DEFECT')}: "
                f"{row.get('location', 'unspecified')}: "
                f"{row.get('summary') or row.get('reason') or 'targeted supplement required'}"
                f"{binding}"
            )
        detail = "\n".join(lines)
    else:
        detail = str(reason)[:12000]
    return (
        f"REPAIR ATTEMPT {attempt} for stage {stage}: submit a TARGETED SUPPLEMENT only.\n"
        f"Fix exactly these defects; preserve all unaffected analysis:\n{detail}\n"
        "The scheduler preserves the previous bundle, records before/after hashes and a diff, then "
        "reconciles the corrected bundle as v2. Do not change unrelated claims and do not relax any "
        "honesty rule."
    )


def _attempt_record(stage: str, ts: str, exc: GateBlock, quality: Optional[float] = None,
                    quality_error: Optional[str] = None) -> dict:
    record = {
        "stage": stage,
        "reason": str(exc)[:12000],
        "ts": ts,
        "verdict": getattr(exc, "verdict", "NEEDS_SUPPLEMENT"),
        "defects": [],
        "target_agents": [],
        "refresh_agents": [],
        "blind_refresh_agents": [],
    }
    if quality is not None:
        record["quality"] = quality
    if quality_error:
        # A caller-supplied scorer that blew up must be VISIBLE, not silently treated as "no signal".
        record["quality_error"] = quality_error[:2000]
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
        record["blind_refresh_agents"] = sorted({
            str(agent)
            for row in exc.defects
            for agent in (row.get("blind_refresh_agents") or [])
            if str(agent).strip()
        })
    return record


def _defect_key(attempt: dict) -> tuple:
    """A comparable fingerprint of one attempt's defects — same key twice means no progress."""
    return tuple(sorted(
        f"{row.get('defect_id', '')}|{row.get('location', '')}"
        for row in (attempt.get("defects") or []) if isinstance(row, dict)
    ))


def _is_plateau(series: Sequence[float], delta: float) -> bool:
    """Two CONSECUTIVE rounds that moved quality by less than ``delta``.

    A DROP counts as a plateau: the point is "another round is not buying anything", and a round
    that made the bundle worse has not bought anything either.
    """
    if len(series) < PLATEAU_MIN_SCORES:
        return False
    last = series[-PLATEAU_MIN_SCORES:]
    return all(last[i + 1] - last[i] < delta for i in range(len(last) - 1))


def _classify_plateau(stage_attempts: list[dict]) -> str:
    """Label a plateau stop. Labelling only — this never decides whether to stop."""
    if len(stage_attempts) >= 2 and _defect_key(stage_attempts[-1]) == _defect_key(stage_attempts[-2]):
        agents = set(stage_attempts[-1].get("target_agents") or [])
        if len(agents) >= 2:
            return "specialist_conflict"
        haystack = (stage_attempts[-1].get("reason") or "").casefold() + " " + " ".join(
            str(row.get("summary") or row.get("reason") or "").casefold()
            for row in (stage_attempts[-1].get("defects") or []) if isinstance(row, dict)
        )
        if any(token in haystack for token in _MISSING_EVIDENCE_TOKENS):
            return "missing_evidence"
    return "plateau"


_NEXT_STEP = {
    "plateau": (
        "Two repair rounds moved quality by less than the plateau threshold. Escalate the remaining "
        "defects to the director instead of spending another round — the next round is unlikely to "
        "change the artifact."
    ),
    "round_cap": (
        "The stage's retry budget is spent and the ORIGINAL gate reason is unchanged. The director "
        "decides: widen the budget, supply the missing input, or accept the artifact with its "
        "caveats stated."
    ),
    "missing_evidence": (
        "The same evidence defects came back unchanged. More rounds cannot produce a source that is "
        "not there — supply the source, widen the retrieval channel, or record the claim UNVERIFIED."
    ),
    "specialist_conflict": (
        "The same defects keep bouncing between two or more seats. Another round repeats the "
        "exchange — a single accountable seat, or the director, has to settle which reading holds."
    ),
}


def build_state_summary(stage: str, stage_attempts: list[dict], stop_reason: str,
                        reason: str, series: Sequence[float]) -> dict:
    """The director-facing half of a stop receipt: where we are, what is open, why we stopped, next."""
    last = stage_attempts[-1] if stage_attempts else {}
    return {
        "stage": stage,
        "attempts": len(stage_attempts),
        "current_state": (
            f"{len(stage_attempts)} repair attempt(s) on {stage}; the last one still failed its gate."
        ),
        "open_problems": [
            {
                "defect_id": row.get("defect_id", "DEFECT"),
                "location": row.get("location", "unspecified"),
                "summary": row.get("summary") or row.get("reason") or "unresolved",
            }
            for row in (last.get("defects") or []) if isinstance(row, dict)
        ] or [{"defect_id": "GATE", "location": stage, "summary": str(reason)[:2000]}],
        "why_stopped": stop_reason,
        "quality_series": [round(float(s), 4) for s in series],
        "recommended_next_step": _NEXT_STEP[stop_reason],
        "honesty_note": "Do not hide unresolved evidence gaps with smoother prose.",
    }


def _record_stop(run_dir, state: dict, stage: str, ts: str, stop_reason: str,
                 reason: str, series: Sequence[float], exc: GateBlock) -> None:
    """Persist the stop receipt and pin it on the escalating exception (no wrapper, no swallow)."""
    stage_attempts = [a for a in state["attempts"] if a.get("stage") == stage]
    summary = build_state_summary(stage, stage_attempts, stop_reason, reason, series)
    state["last_stop"] = {"stage": stage, "ts": ts, "stop_reason": stop_reason,
                          "state_summary": summary}
    _save_state(run_dir, state)
    exc.stop_reason = stop_reason
    exc.state_summary = summary


def attempt_with_repair(run_dir, stage: str, budget: dict, ts: str,
                        dets_fn: Callable[[], object], *,
                        quality_fn: Optional[Callable[[], Optional[float]]] = None,
                        quality_scores: Optional[Sequence[float]] = None,
                        plateau_delta: float = DEFAULT_PLATEAU_DELTA) -> Tuple[str, object]:
    """Run deterministic producers, repairing only an explicit local supplement request.

    Returns ("ok", result) when dets_fn succeeds, or ("retry", feedback_text) only when
    ``TargetedGateBlock(..., verdict="NEEDS_SUPPLEMENT")`` has a remaining in-stage retry.
    Generic or terminal targeted blocks are re-raised unchanged; the repair cap also re-raises
    when the cap is reached — the director sees the ORIGINAL gate reason, not a wrapper.

    Optional quality signal (both forms are OPT-IN; supplying neither keeps the pre-existing
    behaviour exactly, with the round cap as the only stop):

      * ``quality_fn`` — called once after a failed attempt to score the current bundle on this
        repo's [0.0, 1.0] scale; the score is persisted per attempt, so the series survives a crash.
      * ``quality_scores`` — a caller-maintained series, used verbatim instead of the persisted one.

    When two consecutive rounds move quality by less than ``plateau_delta``, the ORIGINAL GateBlock
    escalates now rather than after more rounds. That is fewer wasted rounds, not a new block: the
    same gate was already refusing, and the loop always ended in this same escalation at the cap.
    Either way the escalating exception carries ``stop_reason`` and ``state_summary``, also written
    to ``<run>/inbox/repair-state.json`` under ``last_stop``.
    """
    try:
        return ("ok", dets_fn())
    except GateBlock as e:
        # Only an explicit local supplement may use the retry loop.  Generic
        # GateBlocks and explicit targeted BLOCK verdicts are terminal.
        if not isinstance(e, TargetedGateBlock) or e.verdict == "BLOCK":
            raise
        quality: Optional[float] = None
        quality_error: Optional[str] = None
        if quality_fn is not None:
            try:
                scored = quality_fn()
                quality = None if scored is None else float(scored)
            except Exception as scorer_exc:            # caller-supplied callback: record, never crash
                quality_error = f"{type(scorer_exc).__name__}: {scorer_exc}"
        state = load_state(run_dir)
        state["attempts"].append(_attempt_record(stage, ts, e, quality, quality_error))
        _save_state(run_dir, state)
        stage_attempts = [a for a in state["attempts"] if a["stage"] == stage]
        n_failures = len(stage_attempts)
        # `max_debug_retries_per_run` is a RETRY budget: cap=N must permit N retry prompts. The just-failed
        # attempt has consumed (n_failures - 1) retries so far; escalate only when THIS failure would push
        # the consumed-retry count to the cap. (cap=3 -> 3 retries then escalate; cap=1 -> 1 retry.)
        retries_consumed = n_failures - 1
        if quality_scores is not None:
            series = [float(s) for s in quality_scores]
        else:
            series = [float(a["quality"]) for a in stage_attempts if a.get("quality") is not None]
        if violations(_effective_budget(budget, run_dir), {"debug_retries": retries_consumed}):
            # retry budget exhausted -> escalate the ORIGINAL GateBlock to the director
            _record_stop(run_dir, state, stage, ts, "round_cap", str(e), series, e)
            raise
        # Plateau stopping is strictly ADDITIVE: it can only fire EARLIER than the cap above, and
        # only when the caller supplied a quality signal. No signal -> this branch cannot trigger.
        if (quality_scores is not None or quality_fn is not None) and _is_plateau(series, plateau_delta):
            _record_stop(run_dir, state, stage, ts, _classify_plateau(stage_attempts),
                         str(e), series, e)
            raise
        return ("retry", build_feedback(stage, n_failures, str(e), getattr(e, "defects", None)))
