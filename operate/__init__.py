"""Operate layer — the machine's "one-button" operated twin of the engine.

The canonical engine (`orchestrator/engine.py`) drives a run in one blocking `run_task()` call with an
opaque `agent_fn`; that is the path the 1709 tests exercise with stub producers. But REAL workers are
Claude-Code sub-agents (the Agent tool), which a Python `agent_fn` cannot spawn. The operate layer
breaks the same FSM into resumable STEPS (`spine.begin` / `open_stage` / `commit_stage`) so the
research-orchestrator skill can fill each WORK slot with a real sub-agent between steps, while the
deterministic governance (gates, scorers) runs as plain Python.

It reuses the SAME control-plane primitives as the engine (router, runstore, scope_guard,
validate_artifact, budget, ledger), so every operated run carries the same guarantees: scope-fenced
writes, contract-validated artifacts, a hash-chained tamper-evident ledger, a hard budget cap, and the
director's human gates preserved. Per-mode recipes live in `operate/modes/`.
"""
from .artifacts import GateBlock, envelope, write_artifact
from . import spine

__all__ = ["GateBlock", "envelope", "write_artifact", "spine"]
