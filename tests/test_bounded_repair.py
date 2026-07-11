"""bounded_repair — in-stage repair loop: caps, persistence, escalation semantics (wave 1)."""
from __future__ import annotations

import pytest

from research_agent_teams.operate.artifacts import GateBlock
from research_agent_teams.operate.bounded_repair import (
    DEFAULT_MAX_DEBUG_RETRIES,
    attempt_with_repair,
    build_feedback,
    failures_for_stage,
    load_state,
)

TS = "2026-06-10T12:00:00Z"
BUDGET = {"max_agent_hops": 6, "max_debug_retries_per_run": 3}


class FlakyDets:
    """Raises GateBlock for the first `fail_times` calls, then succeeds."""

    def __init__(self, fail_times):
        self.fail_times = fail_times
        self.calls = 0

    def __call__(self):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise GateBlock(f"evidence gate BLOCK: missing strong source (call {self.calls})")
        return ["evidence/DISCOVER/ok.artifact.json"]


def test_success_passes_through_untouched(tmp_path):
    out = attempt_with_repair(tmp_path, "DISCOVER", BUDGET, TS, FlakyDets(0))
    assert out == ("ok", ["evidence/DISCOVER/ok.artifact.json"])
    assert load_state(tmp_path)["attempts"] == []              # no failure, no state


def test_three_repairs_then_success_under_cap_3(tmp_path):
    # cap=3 is a RETRY budget: it must permit 3 retry prompts; the 4th failure escalates.
    dets = FlakyDets(3)
    for i in (1, 2, 3):
        out = attempt_with_repair(tmp_path, "DISCOVER", BUDGET, TS, dets)
        assert out[0] == "retry" and f"REPAIR ATTEMPT {i}" in out[1]
    assert "missing strong source" in out[1]                   # gate feedback travels verbatim
    ok = attempt_with_repair(tmp_path, "DISCOVER", BUDGET, TS, dets)
    assert ok[0] == "ok"
    assert failures_for_stage(tmp_path, "DISCOVER") == 3


def test_cap_reached_reraises_the_original_gateblock(tmp_path):
    dets = FlakyDets(99)
    for _ in range(3):                                         # cap=3 -> 3 retry prompts
        assert attempt_with_repair(tmp_path, "DISCOVER", BUDGET, TS, dets)[0] == "retry"
    with pytest.raises(GateBlock) as ei:
        attempt_with_repair(tmp_path, "DISCOVER", BUDGET, TS, dets)   # 4th failure == retry budget exhausted
    assert "missing strong source" in str(ei.value)            # ORIGINAL reason, no wrapper
    assert failures_for_stage(tmp_path, "DISCOVER") == 4


def test_cap_one_permits_exactly_one_retry(tmp_path):
    dets = FlakyDets(99)
    budget1 = {"max_agent_hops": 6, "max_debug_retries_per_run": 1}
    assert attempt_with_repair(tmp_path, "DISCOVER", budget1, TS, dets)[0] == "retry"  # the 1 retry
    with pytest.raises(GateBlock):
        attempt_with_repair(tmp_path, "DISCOVER", budget1, TS, dets)  # 2nd failure escalates


def test_missing_budget_key_uses_safe_default_never_unbounded(tmp_path):
    dets = FlakyDets(99)
    outcomes = []
    for _ in range(DEFAULT_MAX_DEBUG_RETRIES):                 # cap=default permits `default` retries
        outcomes.append(attempt_with_repair(tmp_path, "IDEATE", {"max_agent_hops": 4}, TS, dets)[0])
    assert outcomes == ["retry"] * DEFAULT_MAX_DEBUG_RETRIES
    with pytest.raises(GateBlock):                             # the next failure escalates
        attempt_with_repair(tmp_path, "IDEATE", {"max_agent_hops": 4}, TS, dets)


def test_state_survives_a_crash_and_stages_are_independent(tmp_path):
    dets = FlakyDets(99)
    for _ in range(3):                                         # exhaust the cap=3 retry budget
        attempt_with_repair(tmp_path, "DISCOVER", BUDGET, TS, dets)
    # 'crash': a fresh process reads the same run_dir — count is persisted, cap still enforced
    assert failures_for_stage(tmp_path, "DISCOVER") == 3
    with pytest.raises(GateBlock):
        attempt_with_repair(tmp_path, "DISCOVER", BUDGET, TS, FlakyDets(99))
    # a different stage in the same run has its own independent count (per-stage, documented)
    assert attempt_with_repair(tmp_path, "IDEATE", BUDGET, TS, FlakyDets(99))[0] == "retry"


def test_feedback_text_is_repair_shaped():
    fb = build_feedback("DISCOVER", 2, "citation gate BLOCK: claim c2 unanchored")
    assert "REPAIR ATTEMPT 2" in fb and "citation gate BLOCK" in fb
    assert "do not relax any honesty rule" in fb.lower()
