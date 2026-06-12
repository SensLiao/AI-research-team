"""Step-wise spine driver — the engine's `_drive` loop broken into resumable STEPS.

`engine.run_task()` drives a whole run in one blocking call with an opaque `agent_fn`. Real workers
are Claude-Code sub-agents, which a Python callable cannot spawn — so the operate layer exposes the
SAME per-stage micro-protocol as discrete steps the orchestrator interleaves with sub-agent dispatches:

    begin(mode, request) -> run_id + ordered stages
    per stage:  open_stage()            # budget-check + ledger boundary (stage_started)
                <WORK: deterministic cores + LLM sub-agents write artifacts into evidence/<stage>/>
                commit_stage([paths])   # scope-fence + contract-validate + checkpoint (RECORD)
                                        # if gate_level == director_signoff -> caller PAUSES for director
    REPORT (mandatory) ; then done.

It calls the SAME primitives `engine._drive` calls (router, runstore.start_stage/checkpoint_stage,
scope_guard.decide, engine._validate_artifact_file, budget_tracker.assert_within, obslog.append_log) —
so an operated run is scope-fenced, contract-validated, hash-chain-checkpointed, budget-capped, and
crash-resumable exactly like an engine-driven one. The engine stays the canonical tested core; this is
its operated twin, not a fork of the FSM.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import List, Optional

from ..orchestrator.engine import _resolve_path, _validate_artifact_file
from ..orchestrator.model_policy import load_agent_models, safe_resolve_model
from ..orchestrator.router import resolve_task, validate_routing
from ..tools.budget_tracker import assert_within
from ..tools.obslog import append_log
from ..tools.runstore import (
    checkpoint_stage,
    classify_status,
    create_run,
    read_manifest,
    record_gate,
    run_dir_for,
    start_stage,
)
from ..tools.scope_guard import decide, discover_vault_root


def _task_frame(run_dir) -> dict:
    return json.loads((Path(run_dir) / "task_frame.artifact.json").read_text(encoding="utf-8"))


def begin(runs_dir, run_id, request, mode, ts, domain_profile_ref: Optional[str] = None,
          model_policy: str = "default", project: Optional[str] = None) -> dict:
    """PARSE + create the run. Writes the only orchestrator-owned file (task_frame). Returns the run plan.
    With a `project`, the run lives in runs/<project>/<run_id>/ (the per-project grouping)."""
    tf = resolve_task(request, mode, run_id, ts, domain_profile_ref=domain_profile_ref,
                      model_policy=model_policy, project=project)
    rerrs = validate_routing(tf)
    if rerrs:
        raise ValueError(f"routing rejected: {rerrs}")
    entry = tf["payload"]["entry_stage"]
    create_run(runs_dir, run_id, mode, entry, ts, domain_profile_ref, tf["payload"]["agent_subset"],
               project=project)
    run_dir = run_dir_for(runs_dir, run_id, project)
    (run_dir / "task_frame.artifact.json").write_text(json.dumps(tf), encoding="utf-8")
    p = tf["payload"]
    return {"run_id": run_id, "run_dir": str(run_dir), "mode": mode, "project": project,
            "stages": _resolve_path(tf), "gate_level": p["gate_level"],
            "agent_subset": p["agent_subset"], "budget": p["budget"]}


def next_stage(run_dir) -> Optional[str]:
    """The next stage in the mode's path that has not been checkpointed (a crashed mid-stage re-runs)."""
    tf = _task_frame(run_dir)
    done = {c["stage"] for c in read_manifest(run_dir)["completed_work"]}
    for s in _resolve_path(tf):
        if s not in done:
            return s
    return None


def open_stage(run_dir, stage, ts) -> None:
    """Budget-check, then open the ledger boundary for a stage (stage_started)."""
    tf = _task_frame(run_dir)
    p = tf["payload"]
    usage = {"agent_hops": len(read_manifest(run_dir)["completed_work"]) + 1}
    assert_within(p["budget"], usage)                       # hard budget cap; over-budget raises
    start_stage(run_dir, stage, ts, p["agent_subset"])      # ledger: stage_started


def commit_stage(run_dir, stage, artifact_paths: List[str], ts) -> dict:
    """Scope-fence + contract-validate EVERY artifact, then checkpoint the stage (RECORD boundary).

    Returns the gate level for this stage (the caller PAUSES for the director when director_signoff)
    and the next stage (or done). Mirrors the engine's per-stage decide -> validate -> checkpoint, but
    validates ALL of the stage's artifacts (the engine validates only the primary returned one).
    """
    if not artifact_paths:
        raise ValueError(f"commit_stage: stage {stage} produced no artifact (constitution: no artifact = stage not done)")
    tf = _task_frame(run_dir)
    p = tf["payload"]
    run_root = str(Path(run_dir).parent)
    for ap in artifact_paths:
        ok, reason = decide("Write", str(ap),
                            {"run_root": run_root, "run_id": p["task_id"], "stage": stage,
                             "vault_root": discover_vault_root()})   # ③: powered-by-default, never None
        if not ok:
            raise PermissionError(f"scope violation at {stage}: {reason}")
        _validate_artifact_file(ap)
    lead = (p["agent_subset"] or [None])[0]
    declared = load_agent_models().get(lead) if lead else None
    model_label = safe_resolve_model(declared, p.get("model_policy", "default"))
    append_log(Path(run_dir) / "obs.jsonl",
               {"agent_name": lead or "operate", "task_id": p["task_id"], "stage": stage,
                "started_at": ts, "tool_calls": 1, "model": model_label})
    checkpoint_stage(run_dir, stage, list(artifact_paths), f"idem-{stage}", ts)
    nxt = next_stage(run_dir)
    return {"stage": stage, "committed": True,
            "gate": "director_signoff" if p["gate_level"] == "director_signoff" else "auto",
            "next_stage": nxt, "done": nxt is None}


def reject_stage(run_dir, stage, ts, reason: Optional[str] = None) -> dict:
    """Record the director's veto at a director_signoff gate — the operate twin of the engine reject path.

    Appends a hash-chained gate_resolved(reject) event and flips the run to status='rejected' (terminal).
    The rejected stage is NOT checkpointed, and runstore.prepare_resume refuses a rejected run — so a plain
    'continue' can never walk past the veto. Director-only (the operate `reject` subcommand)."""
    return record_gate(run_dir, stage, "reject", ts, reason=reason)


def status(run_dir) -> dict:
    """A snapshot of where the run is (completed stages, next, run-store status)."""
    tf = _task_frame(run_dir)
    done = [c["stage"] for c in read_manifest(run_dir)["completed_work"]]
    return {"run_id": tf["payload"]["task_id"], "mode": tf["payload"]["mode"],
            "stages": _resolve_path(tf), "completed": done,
            "next_stage": next_stage(run_dir), "run_status": classify_status(run_dir)}
