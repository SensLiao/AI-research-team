"""Real tests for the budget / stop controller."""
from __future__ import annotations

import pytest

from research_agent_teams.tools.budget_tracker import (
    BudgetExceeded,
    assert_within,
    remaining,
    violations,
    within,
)

BUDGET = {"max_agent_hops": 4, "max_fulltext_reads": None, "max_debug_retries_per_run": 2}


def test_within_when_under_limits():
    assert within(BUDGET, {"agent_hops": 2, "debug_retries": 1})
    assert violations(BUDGET, {"agent_hops": 2}) == []


def test_violation_when_cap_reached():
    v = violations(BUDGET, {"agent_hops": 4})
    assert any("max_agent_hops" in e for e in v)


def test_null_limit_is_unbounded():
    # max_fulltext_reads is None -> never a violation no matter how high
    assert within(BUDGET, {"fulltext_reads": 9999})


def test_assert_within_raises_on_exceed():
    with pytest.raises(BudgetExceeded, match="max_debug_retries_per_run"):
        assert_within(BUDGET, {"debug_retries": 2})


def test_remaining_counts_down_and_handles_unbounded():
    assert remaining(BUDGET, {"agent_hops": 1}, "max_agent_hops") == 3
    assert remaining(BUDGET, {"fulltext_reads": 100}, "max_fulltext_reads") is None
