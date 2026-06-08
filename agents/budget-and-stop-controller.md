---
name: budget-and-stop-controller
model: none
kind: tool
implements: tools/budget_tracker.py
enforces: task_frame.budget limits (max_agent_hops, max_iterations_without_new_evidence, max_fulltext_reads, max_gpu_runs_before_review, max_debug_retries_per_run)
permission_scope:
  read: [task_frame.budget dict, live usage counters passed by the engine]
  write: [nothing — pure function; raises BudgetExceeded if limits are reached]
  never: [be bypassed by an agent, emit a warning and continue, modify the budget]
authority: hard stop — over-budget raises BudgetExceeded immediately; research cannot sprawl forever
---

# budget-and-stop-controller — tool

You are the budget-and-stop-controller. You have no model; you are a deterministic tool called by
the engine before every agent hop. Your ONE job: compare live usage counters against the
`task_frame.budget` limits and raise `BudgetExceeded` the moment any limit is reached. Research
cannot sprawl forever.

## Single responsibility

Enforce the budget declared in `task_frame.payload.budget`. The budget is a dict of limit keys; a
value of `None` means unbounded for that dimension. The live usage dict tracks the same dimensions.
The rule is: `used >= limit` is a violation (the limit is reached; the *next* hop would exceed it,
so we stop now before dispatching it).

Budget dimensions and their usage counter keys:

| budget key | usage counter key | what it bounds |
|---|---|---|
| `max_agent_hops` | `agent_hops` | total stage dispatches (prevents infinite loops) |
| `max_iterations_without_new_evidence` | `iterations_without_new_evidence` | stale grinding with no new findings |
| `max_fulltext_reads` | `fulltext_reads` | expensive PDF / full-text fetches |
| `max_gpu_runs_before_review` | `gpu_runs` | GPU experiment runs before a human review gate |
| `max_debug_retries_per_run` | `debug_retries` | debug/retry cycles before escalation |

## Implemented by

`research_agent_teams/tools/budget_tracker.py`:

- `violations(budget, usage) -> List[str]`: returns the list of limit keys that are reached/exceeded;
  empty list means within budget.
- `within(budget, usage) -> bool`: convenience predicate.
- `assert_within(budget, usage) -> None`: raises `BudgetExceeded("; ".join(violations))` if any
  limit is reached. This is the function the engine calls.
- `remaining(budget, usage, limit_key) -> Optional[int]`: how many more units are available for a
  given dimension (`None` if unbounded).

The engine calls `assert_within(budget, usage)` at the top of the `_drive` loop, before
`start_stage` — i.e. before dispatching the next agent. If the call raises, the loop terminates
immediately with `BudgetExceeded`; the exception propagates to `run_task` / `resume_task` and the
run is stopped. The stage-started ledger event has not been written yet, so the run-store remains
at a clean `boundary` state and is resumable once the director adjusts the budget.

## Guarantee

No agent hop is dispatched when any budget limit has been reached. There is no "warn and continue"
path — `assert_within` either returns silently (within budget) or raises (over budget). A `None`
limit means truly unbounded for that dimension; the tool never enforces an implicit cap.

## BLOCK conditions

- `used >= limit` for any dimension where `limit is not None` → raises `BudgetExceeded` with the
  full list of violations as the message (e.g. `"max_agent_hops reached: 10/10"`)

## You must NOT

- Be bypassed by an agent — agents do not call this tool directly; only the engine calls it, and the
  engine calls it unconditionally before every hop
- Modify the budget — the budget is set by the router from `task_frame.payload.budget` (or overridden
  by `run_task`'s `budget_override` parameter at task creation time); it is never modified at runtime
- Emit a warning and let the hop proceed — there is no soft-stop; over-budget is a hard stop
- Enforce implicit or hidden caps — if a dimension is `None` in the budget, it is unbounded; the
  tool never invents limits that aren't in the budget dict

## How it fits the spine

The budget-and-stop-controller is the anti-sprawl gate in the engine's `_drive` loop. Every time
the loop is about to dispatch the next stage agent, it calls `assert_within` first. This means:

```
for stage in remaining:
    usage["agent_hops"] += 1
    assert_within(budget, usage)   ← budget-and-stop-controller: raises BudgetExceeded if over
    start_stage(...)               ← ledger open (only reached if budget is OK)
    agent_fn(...)                  ← WORK (dispatched; never reaches here if over budget)
    ...
```

The budget for a run is declared in the mode registry (`spec["budget"]`) and embedded in the
`task_frame` by the router. The director may override it at task-creation time via `budget_override`.
A higher gate level (e.g. `director_signoff`) typically carries a tighter hop budget to ensure
human review before the run expands further.
