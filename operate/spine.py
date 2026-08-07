"""Step-wise spine driver — the engine's `_drive` loop broken into resumable STEPS.

`engine.run_task()` drives a whole run in one blocking call with an opaque `agent_fn`. Real workers
are Codex-harness sub-agents, which a Python callable cannot spawn — so the operate layer exposes the
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
from ..orchestrator.gate_policy import director_gate_required
from ..orchestrator.model_policy import (
    codex_runtime_fields,
    load_agent_models,
    runtime_observability_fields,
    safe_resolve_model,
)
from ..orchestrator.router import resolve_task, validate_routing
from ..tools.budget_tracker import assert_within
from ..tools.obslog import append_log
from ..tools.ledger import read_events
from ..tools.director_packet import packet_path, write_packet
from ..tools.runstore import (
    checkpoint_stage,
    classify_status,
    create_run,
    mark_gate_pending,
    pin_task_frame,
    read_manifest,
    reconcile_approved_terminal_gate,
    record_gate,
    run_dir_for,
    start_stage,
)
from ..tools.scope_guard import decide, discover_vault_root


def _task_frame(run_dir) -> dict:
    return json.loads((Path(run_dir) / "task_frame.artifact.json").read_text(encoding="utf-8"))


def begin(runs_dir, run_id, request, mode, ts, domain_profile_ref: Optional[str] = None,
          model_policy: str = "default", project: Optional[str] = None,
          north_star: Optional[dict] = None,
          capability_route: Optional[dict] = None) -> dict:
    """PARSE + create the run. Writes the only orchestrator-owned file (task_frame). Returns the run plan.
    With a `project`, the run lives in runs/<project>/<run_id>/ (the per-project grouping).
    `north_star` ({statement, in_scope, out_of_scope}) pins the run's immutable direction contract;
    absent, the verbatim request becomes the statement. The frame's sha256 is anchored into the
    hash-chained ledger (task_frame_pinned) so the direction cannot be silently rewritten."""
    tf = resolve_task(request, mode, run_id, ts, domain_profile_ref=domain_profile_ref,
                      model_policy=model_policy, project=project, north_star=north_star,
                      capability_route=capability_route)
    rerrs = validate_routing(tf)
    if rerrs:
        raise ValueError(f"routing rejected: {rerrs}")
    entry = tf["payload"]["entry_stage"]
    create_run(runs_dir, run_id, mode, entry, ts, domain_profile_ref, tf["payload"]["agent_subset"],
               project=project)
    run_dir = run_dir_for(runs_dir, run_id, project)
    (run_dir / "task_frame.artifact.json").write_text(json.dumps(tf), encoding="utf-8")
    pin_task_frame(run_dir, ts)
    p = tf["payload"]
    return {"run_id": run_id, "run_dir": str(run_dir), "mode": mode, "project": project,
            "stages": _resolve_path(tf), "gate_level": p["gate_level"],
            "north_star": p.get("north_star"),
            "agent_subset": p["agent_subset"], "budget": p["budget"]}


def next_stage(run_dir) -> Optional[str]:
    """The next stage in the mode's path that has not been checkpointed (a crashed mid-stage re-runs)."""
    tf = _task_frame(run_dir)
    done = {c["stage"] for c in read_manifest(run_dir)["completed_work"]}
    for s in _resolve_path(tf):
        if s not in done:
            return s
    return None


def open_stage(run_dir, stage, ts) -> bool:
    """Budget-check and open one idempotent ``stage_started`` boundary.

    The operated CLI may be called once per panel wave. Reopening the same
    unfinished stage must not append duplicate ledger events, while attempting
    to dispatch a future or completed stage is refused.
    """
    tf = _task_frame(run_dir)
    p = tf["payload"]
    manifest = read_manifest(run_dir)
    if manifest.get("status") == "failed":
        failure = manifest.get("failure") or {}
        raise ValueError(
            f"cannot open stage {stage!r}; run failed hard gate at {failure.get('stage', '?')}: "
            f"{failure.get('reason', 'unspecified reason')}"
        )
    if manifest.get("status") == "rejected":
        raise ValueError(f"cannot open stage {stage!r}; run was rejected by the director")
    pending = manifest.get("pending_gates") or []
    if manifest.get("status") == "awaiting_director" or pending:
        raise ValueError(f"cannot open stage {stage!r}; awaiting director decision for gate(s) {pending}")
    expected = next_stage(run_dir)
    if stage != expected:
        raise ValueError(f"cannot open stage {stage!r}; next legal stage is {expected!r}")

    events = read_events(Path(run_dir) / "ledger.jsonl")
    active = None
    for event in reversed(events):
        if event.get("event_type") == "boundary":
            break
        if event.get("event_type") == "stage_started":
            active = (event.get("payload") or {}).get("stage")
            break
    if active is not None:
        if active != stage:
            raise ValueError(f"run already has active stage {active!r}; cannot open {stage!r}")
        return False

    usage = {"agent_hops": len(read_manifest(run_dir)["completed_work"]) + 1}
    assert_within(p["budget"], usage)                       # hard budget cap; over-budget raises
    start_stage(run_dir, stage, ts, p["agent_subset"])      # ledger: stage_started
    return True


def commit_stage(run_dir, stage, artifact_paths: List[str], ts) -> dict:
    """Scope-fence + contract-validate EVERY artifact, then checkpoint the stage (RECORD boundary).

    Returns the configured gate for this stage (the caller PAUSES only at a declared director decision
    boundary) and the next stage (or done). Mirrors the engine's per-stage decide -> validate -> checkpoint, but
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
    obs_event = {"agent_name": lead or "operate", "task_id": p["task_id"], "stage": stage,
                 "started_at": ts, "tool_calls": 1, "model": model_label}
    obs_event.update(codex_runtime_fields(model_label))
    obs_event.update(runtime_observability_fields(model_label))
    append_log(Path(run_dir) / "obs.jsonl", obs_event)
    checkpoint_stage(run_dir, stage, list(artifact_paths), f"idem-{stage}", ts,
                     stage_path=_resolve_path(tf))
    director_review_packet = None
    if stage == "REPORT":
        director_review_packet = str(write_packet(run_dir, generated_at=ts))
    nxt = next_stage(run_dir)
    if director_gate_required(p, stage):
        mark_gate_pending(run_dir, stage, ts, nxt, reason="configured_director_gate")
    out = {"stage": stage, "committed": True,
           "gate": "director_signoff" if director_gate_required(p, stage) else "auto",
           "next_stage": nxt, "done": nxt is None}
    if director_review_packet:
        out["director_review_packet"] = director_review_packet
    return out


def resolve_director_gate(run_dir, stage, decision: str, ts, reason: Optional[str] = None) -> dict:
    """Record the director's decision and release exactly the already-pinned next stage.

    This is intentionally narrower than ``record_gate``: it only resolves a
    persisted configured gate, so a normal CLI/API caller cannot manufacture an
    approval for an arbitrary stage.
    """
    tf = _task_frame(run_dir)
    payload = tf["payload"]
    if not director_gate_required(payload, stage):
        raise ValueError(f"stage {stage!r} is not a configured director gate")
    manifest = read_manifest(run_dir)
    normalized = (decision or "").strip().lower()
    if normalized not in {"approved", "reject"}:
        raise ValueError("director decision must be 'approved' or 'reject'")
    path = _resolve_path(tf)
    if stage in (manifest.get("pending_gates") or []):
        updated = record_gate(run_dir, stage, normalized, ts, reason=reason)
        reconciled = False
        idempotent = False
    elif normalized == "approved" and path and stage == path[-1]:
        # Narrow, append-only repair for the historical state where a final
        # approval had already been ledgered but record_gate left the manifest
        # running because the final checkpoint had no successor.
        already_terminal = manifest.get("status") == "done"
        updated = reconcile_approved_terminal_gate(
            run_dir,
            stage,
            ts,
            expected_completed_stages=path,
        )
        reconciled = not already_terminal
        idempotent = already_terminal
    else:
        raise ValueError(f"stage {stage!r} has no pending director decision")
    return {"stage": stage, "decision": normalized, "status": updated["status"],
            "next_stage": next_stage(run_dir), "pending_gates": updated.get("pending_gates") or [],
            "terminal": updated["status"] == "done", "reconciled": reconciled,
            "idempotent": idempotent}


def reconcile_director_gate(run_dir, stage, ts) -> dict:
    """Append a pending-gate state for a legacy checkpoint without rewriting history.

    Older sparse-path runs could have a correct task frame and menu but an
    incorrect global-FSM successor in their boundary. This migration accepts
    only a pristine latest boundary for the configured gate, derives the true
    successor from the frozen task frame, and appends the correction.
    """
    # 2026-08-07 de-governance: this migration no longer verifies the ledger chain or the task-frame
    # pin hash (both were tamper-evidence, not correctness checks) — it still requires every committed
    # artifact this stage recorded to actually exist on disk (below), which is what reconciliation reads.
    events = read_events(Path(run_dir) / "ledger.jsonl")
    tf = _task_frame(run_dir)
    payload = tf["payload"]
    if not director_gate_required(payload, stage):
        raise ValueError(f"stage {stage!r} is not a configured director gate")
    manifest = read_manifest(run_dir)
    if manifest.get("pending_gates"):
        raise ValueError(f"run already has pending director gate(s) {manifest['pending_gates']}")
    completed = manifest.get("completed_work") or []
    if not completed or completed[-1].get("stage") != stage:
        raise ValueError(f"gate reconciliation requires {stage!r} to be the latest completed stage")
    for record in completed:
        for artifact in record.get("artifacts") or []:
            path = Path(artifact.get("path") or "")
            if not path.is_file():
                raise ValueError(f"cannot reconcile: committed artifact missing at {path}")
    if not events or events[-1].get("event_type") != "boundary":
        raise ValueError("gate reconciliation requires a clean latest boundary")
    boundary_payload = events[-1].get("payload") or {}
    if boundary_payload.get("completed_stage") != stage:
        raise ValueError(f"latest boundary does not belong to gate stage {stage!r}")
    path = _resolve_path(tf)
    index = path.index(stage)
    successor = path[index + 1] if index + 1 < len(path) else None
    mark_gate_pending(
        run_dir, stage, ts, successor,
        reason="retroactive_path_and_gate_reconciliation",
        previous_boundary_next=boundary_payload.get("next"),
    )
    return {"stage": stage, "next_stage": successor, "status": "awaiting_director",
            "previous_boundary_next": boundary_payload.get("next")}


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
    pkt = packet_path(run_dir)
    return {"run_id": tf["payload"]["task_id"], "mode": tf["payload"]["mode"],
            "stages": _resolve_path(tf), "completed": done,
            "next_stage": next_stage(run_dir), "run_status": classify_status(run_dir),
            "director_review_packet": str(pkt) if pkt.is_file() else None}
