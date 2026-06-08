"""Budget / stop controller. Prevents unbounded research sprawl.

Compares live usage counters against the task_frame.budget limits. A limit of None = unbounded
for that dimension. `used >= limit` is a violation (the cap is reached; the next hop would exceed).
"""
from __future__ import annotations

from typing import Dict, List, Optional

# budget key (in task_frame.budget) -> usage counter key
LIMIT_TO_USAGE = {
    "max_agent_hops": "agent_hops",
    "max_iterations_without_new_evidence": "iterations_without_new_evidence",
    "max_fulltext_reads": "fulltext_reads",
    "max_gpu_runs_before_review": "gpu_runs",
    "max_debug_retries_per_run": "debug_retries",
}


class BudgetExceeded(RuntimeError):
    pass


def violations(budget: Dict, usage: Dict) -> List[str]:
    """Return the list of limits that are reached/exceeded; empty == within budget."""
    out = []
    for limit_key, usage_key in LIMIT_TO_USAGE.items():
        limit = budget.get(limit_key)
        if limit is None:
            continue  # unbounded dimension
        used = usage.get(usage_key, 0)
        if used >= limit:
            out.append(f"{limit_key} reached: {used}/{limit}")
    return out


def within(budget: Dict, usage: Dict) -> bool:
    return not violations(budget, usage)


def assert_within(budget: Dict, usage: Dict) -> None:
    v = violations(budget, usage)
    if v:
        raise BudgetExceeded("; ".join(v))


def remaining(budget: Dict, usage: Dict, limit_key: str) -> Optional[int]:
    limit = budget.get(limit_key)
    if limit is None:
        return None
    return max(0, limit - usage.get(LIMIT_TO_USAGE[limit_key], 0))
