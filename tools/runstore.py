"""Run-store: crash-safe stop/resume on top of the hash-chained ledger.

A run lives in runs/<project>/<run_id>/ {manifest.yaml, ledger.jsonl, evidence/, inbox/} when it
belongs to a research project, or flat runs/<run_id>/ (legacy / project-less). `run_dir_for` builds
the path; `find_run_dir` locates an existing run in either layout by id.
The manifest is the single source of truth (single-writer = orchestrator/state-tracker).
Resume reads ONLY manifest + ledger; prior chat memory is non-authoritative.

Crash safety: every manifest write is atomic (temp -> fsync -> os.replace), so a half-written
manifest is never observed. A clean checkpoint ends with a `boundary` event; a `stage_started`
with no following `boundary` means the process died mid-stage -> roll back to that stage and re-run it.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import List, Optional

import yaml

from research_agent_teams.tools.ledger import (
    append_event,
    head_hash,
    read_events,
    verify_chain,
)
from research_agent_teams.tools._latex_sandbox import atomic_write_bytes
from research_agent_teams.tools.validate_artifact import validate_against

STAGES = ["DISCOVER", "IDEATE", "DESIGN", "EXECUTE", "ANALYZE", "VERIFY", "REPORT"]
MANIFEST_SCHEMA = "run_manifest.schema.json"


# ---------- low-level ----------

def next_stage(stage: str) -> Optional[str]:
    i = STAGES.index(stage)
    return STAGES[i + 1] if i + 1 < len(STAGES) else None


def hash_file(path) -> str:
    data = Path(path).read_bytes()
    return "sha256:" + hashlib.sha256(data).hexdigest()


def atomic_write_text(path, text: str) -> None:
    """Atomically publish UTF-8 text without a predictable ``.tmp`` path."""

    atomic_write_bytes(Path(path), text.encode("utf-8"))


def _manifest_path(run_dir) -> Path:
    return Path(run_dir) / "manifest.yaml"


def _ledger_path(run_dir) -> Path:
    return Path(run_dir) / "ledger.jsonl"


def read_manifest(run_dir) -> dict:
    return yaml.safe_load(_manifest_path(run_dir).read_text(encoding="utf-8"))


def _write_manifest(run_dir, manifest: dict) -> None:
    errs = validate_against(MANIFEST_SCHEMA, manifest)
    if errs:
        raise ValueError(f"refusing to write invalid manifest: {errs}")
    atomic_write_text(_manifest_path(run_dir), yaml.safe_dump(manifest, sort_keys=False, allow_unicode=True))


# ---------- run layout (project-grouped or legacy flat) ----------

def run_dir_for(runs_dir, run_id: str, project: Optional[str] = None) -> Path:
    """The run's directory: runs/<project>/<run_id>/ when it belongs to a project, else flat."""
    return (Path(runs_dir) / project / run_id) if project else (Path(runs_dir) / run_id)


def find_run_dir(runs_dir, run_id: str) -> Path:
    """Locate an EXISTING run by id in either layout. Flat wins (legacy precedence); then exactly
    one runs/<project>/<run_id>/ match. Identified by its manifest.yaml (a real run always has one)."""
    flat = Path(runs_dir) / run_id
    if (flat / "manifest.yaml").is_file():
        return flat
    matches = sorted(p for p in Path(runs_dir).glob(f"*/{run_id}") if (p / "manifest.yaml").is_file())
    if len(matches) == 1:
        return matches[0]
    if not matches:
        raise FileNotFoundError(
            f"run {run_id!r} not found under {runs_dir} (neither flat nor in any project group)")
    raise RuntimeError(f"run id {run_id!r} is ambiguous across projects: {[str(m) for m in matches]}")


# ---------- run lifecycle ----------

def create_run(runs_dir, run_id: str, mode: str, entry_stage: str, ts: str,
               domain_profile_ref: Optional[str] = None,
               first_agent_subset: Optional[List[str]] = None,
               project: Optional[str] = None) -> dict:
    run_dir = run_dir_for(runs_dir, run_id, project)
    (run_dir / "evidence").mkdir(parents=True, exist_ok=True)
    (run_dir / "inbox").mkdir(parents=True, exist_ok=True)
    append_event(_ledger_path(run_dir), "run_started", {"mode": mode, "entry_stage": entry_stage}, ts)
    manifest = {
        "schema_version": "1.0.0",
        "run_id": run_id,
        "project": project,
        "status": "running",
        "created_at": ts,
        "updated_at": ts,
        "mode": mode,
        "entry_stage": entry_stage,
        "domain_profile_ref": domain_profile_ref,
        "next_step": {"stage": entry_stage, "action": "run", "agent_subset": first_agent_subset or []},
        "last_boundary_hash": None,
        "completed_work": [],
        "pending_gates": [],
        "promotion_targets": [],
    }
    _write_manifest(run_dir, manifest)
    return manifest


def pin_task_frame(run_dir, ts: str) -> dict:
    """Anchor the run's direction contract into the hash chain (audit H2.3 fix).

    The task_frame (the file that pins the north star) is the one orchestrator-written file that
    previously sat OUTSIDE the tamper-evident record. This appends a `task_frame_pinned` event
    carrying its sha256 + the north-star statement, so silently editing the run's direction after
    PARSE breaks the chain check like any other tamper."""
    tf_path = Path(run_dir) / "task_frame.artifact.json"
    tf = json.loads(tf_path.read_text(encoding="utf-8"))
    payload = tf.get("payload", {}) or {}
    ns = payload.get("north_star") or {}
    return append_event(_ledger_path(run_dir), "task_frame_pinned",
                        {"task_frame_sha256": hash_file(tf_path),
                         "mode": payload.get("mode"),
                         "north_star_statement": ns.get("statement") or payload.get("request_text", "")},
                        ts)


def pin_upstream_grounding(run_dir, grounding_path, ts: str) -> dict:
    """Anchor a cross-mode handoff manifest into the downstream run ledger.

    Artifact hashes protect the referenced upstream files; this additional pin protects the
    transport manifest itself, so paths, product versions, and expected hashes cannot be edited
    together after the downstream run starts.
    """
    path = Path(grounding_path)
    grounding = json.loads(path.read_text(encoding="utf-8"))
    upstream = grounding.get("upstream_runs") or []
    return append_event(
        _ledger_path(run_dir),
        "upstream_handoff_pinned",
        {
            "grounding_sha256": hash_file(path),
            "contract_version": grounding.get("handoff_contract_version"),
            "downstream_mode": grounding.get("downstream_mode"),
            "upstream_run_ids": [str(row.get("run_id") or "") for row in upstream],
        },
        ts,
    )


def start_stage(run_dir, stage: str, ts: str, agent_subset: Optional[List[str]] = None) -> dict:
    manifest = read_manifest(run_dir)
    if manifest.get("status") == "failed":
        failure = manifest.get("failure") or {}
        raise RuntimeError(
            f"cannot start stage {stage!r}: run failed hard gate at "
            f"{failure.get('stage', '?')}: {failure.get('reason', 'unspecified reason')}"
        )
    if manifest.get("status") == "rejected":
        raise RuntimeError(f"cannot start stage {stage!r}: run was rejected by the director")
    if manifest.get("status") == "awaiting_director" or manifest.get("pending_gates"):
        gates = manifest.get("pending_gates") or []
        raise RuntimeError(f"cannot start stage {stage!r}: awaiting director decision at gate(s) {gates}")
    append_event(_ledger_path(run_dir), "stage_started", {"stage": stage}, ts)
    manifest["status"] = "running"
    manifest["updated_at"] = ts
    manifest["next_step"] = {"stage": stage, "action": "run", "agent_subset": agent_subset or []}
    _write_manifest(run_dir, manifest)
    return manifest


def checkpoint_stage(run_dir, stage: str, artifact_paths: List, idempotency_key: str, ts: str,
                     stage_path: Optional[List[str]] = None) -> dict:
    """Finish a stage and advance along its immutable mode path.

    ``STAGES`` remains the compatibility fallback for legacy callers. Operated
    modes pass their frozen task-frame ``stage_path`` so a sparse path such as
    DISCOVER -> IDEATE -> REPORT can never be redirected into DESIGN.
    """
    artifacts = [{"path": str(p), "sha256": hash_file(p)} for p in artifact_paths]
    append_event(_ledger_path(run_dir), "step_done",
                 {"stage": stage, "artifacts": artifacts, "idempotency_key": idempotency_key}, ts)
    if stage_path is None:
        nxt = next_stage(stage)
    else:
        if stage not in stage_path:
            raise ValueError(f"checkpoint stage {stage!r} is not in immutable stage path {stage_path!r}")
        index = stage_path.index(stage)
        nxt = stage_path[index + 1] if index + 1 < len(stage_path) else None
    boundary = append_event(_ledger_path(run_dir), "boundary", {"completed_stage": stage, "next": nxt}, ts)

    manifest = read_manifest(run_dir)
    manifest["completed_work"].append(
        {"stage": stage, "state": "done", "artifacts": artifacts, "idempotency_key": idempotency_key}
    )
    manifest["last_boundary_hash"] = boundary["hash"]
    manifest["updated_at"] = ts
    if nxt is None:
        manifest["status"] = "done"
        manifest["next_step"] = None
    else:
        manifest["next_step"] = {"stage": nxt, "action": "run", "agent_subset": []}
    _write_manifest(run_dir, manifest)
    return manifest


def mark_gate_pending(run_dir, stage: str, ts: str, next_stage: Optional[str],
                      reason: Optional[str] = None,
                      previous_boundary_next: Optional[str] = None) -> dict:
    """Persist a completed-stage director decision boundary before later work may open.

    The evidence/menu remains checkpointed and reviewable, while the next mode
    stage is explicitly held behind a hash-chained ``gate_pending`` event. This
    append-only transition can also reconcile a legacy run created before
    pending-gate state existed.
    """
    manifest = read_manifest(run_dir)
    completed = manifest.get("completed_work") or []
    if not completed or completed[-1].get("stage") != stage:
        raise ValueError(f"cannot mark gate {stage!r} pending before that stage is the latest checkpoint")
    pending = list(manifest.get("pending_gates") or [])
    if stage in pending:
        return manifest
    payload = {"stage": stage, "next_stage": next_stage}
    if reason is not None:
        payload["reason"] = reason
    if previous_boundary_next is not None:
        payload["previous_boundary_next"] = previous_boundary_next
    append_event(_ledger_path(run_dir), "gate_pending", payload, ts)
    pending.append(stage)
    manifest["pending_gates"] = pending
    manifest["status"] = "awaiting_director"
    manifest["updated_at"] = ts
    manifest["next_step"] = (
        {"stage": next_stage, "action": "await_director_decision", "agent_subset": []}
        if next_stage is not None else None
    )
    _write_manifest(run_dir, manifest)
    return manifest


def record_gate(run_dir, stage: str, decision: str, ts: str, reason: Optional[str] = None) -> dict:
    """Record a director gate decision durably — the veto fix.

    Appends a hash-chained `gate_resolved` event so EVERY director_signoff outcome (approved / modify /
    reject) is on the tamper-evident permanent record; a reject can never be silently 'lost' from the
    ledger. On REJECT the run becomes TERMINAL: status='rejected', next_step cleared, and `prepare_resume`
    refuses it — so a plain 'continue' can no longer walk a vetoed run to completion. Approve/modify leave
    the run running (the engine then checkpoints the stage as usual). A final pending gate is different:
    its approval appends ``run_completed`` and leaves the run terminal. """
    dec = (decision or "").strip().lower()
    decision_event = append_event(_ledger_path(run_dir), "gate_resolved",
                                  {"stage": stage, "decision": dec, "reason": reason}, ts)
    manifest = read_manifest(run_dir)
    manifest["updated_at"] = ts
    if dec == "reject":
        manifest["status"] = "rejected"
        manifest["pending_gates"] = [item for item in (manifest.get("pending_gates") or []) if item != stage]
        manifest["rejected"] = {"stage": stage, "reason": reason, "decided_at": ts}
        manifest["next_step"] = None
    elif stage in (manifest.get("pending_gates") or []):
        manifest["pending_gates"] = [item for item in manifest["pending_gates"] if item != stage]
        if not manifest["pending_gates"] and manifest.get("next_step") is None:
            _append_run_completed(
                run_dir,
                stage,
                ts,
                approval_event_hash=decision_event["hash"],
                reconciled=False,
            )
            manifest["status"] = "done"
            manifest["next_step"] = None
        elif manifest["pending_gates"]:
            manifest["status"] = "awaiting_director"
        else:
            manifest["status"] = "running"
            manifest["next_step"]["action"] = "run"
    _write_manifest(run_dir, manifest)
    return manifest


def _append_run_completed(run_dir, stage: str, ts: str, *, approval_event_hash: str,
                          reconciled: bool) -> dict:
    """Append the terminal record that binds a final approved gate to completion.

    A final checkpoint may be followed by a configured human gate.  In that
    shape ``next_step`` is correctly ``None`` *before* the human approves, so
    completion cannot be inferred from the checkpoint alone.  This event makes
    the approval-to-terminal transition explicit in the hash chain.
    """
    return append_event(
        _ledger_path(run_dir),
        "run_completed",
        {
            "stage": stage,
            "approved_gate_event_hash": approval_event_hash,
            "reconciled": reconciled,
        },
        ts,
    )


def reconcile_approved_terminal_gate(run_dir, stage: str, ts: str,
                                      expected_completed_stages: List[str]) -> dict:
    """Append-only repair for the precise historical final-gate terminalization fault.

    The only admissible legacy state is intentionally narrow: all frozen mode
    stages are completed, there is no pending gate or next step, and the ledger
    tip is an approval of this final gate.  No decision is replayed or rewritten;
    the repair only appends ``run_completed`` and makes the manifest terminal.
    """
    events = read_events(_ledger_path(run_dir))
    errors = verify_chain(events)
    if errors:
        raise ValueError("cannot reconcile a tampered ledger")
    manifest = read_manifest(run_dir)
    completed = manifest.get("completed_work") or []
    completed_stages = [row.get("stage") for row in completed if row.get("state") == "done"]
    if completed_stages != list(expected_completed_stages):
        raise ValueError("terminal reconciliation requires every frozen mode stage to be completed exactly once")
    if not completed or completed[-1].get("stage") != stage:
        raise ValueError(f"terminal reconciliation requires {stage!r} to be the final completed stage")
    if manifest.get("status") == "done":
        if manifest.get("pending_gates") or manifest.get("next_step") is not None:
            raise ValueError("terminal completion has inconsistent pending gates or next_step")
        if not events or events[-1].get("event_type") != "run_completed":
            raise ValueError("terminal reconciliation requires run_completed to be the ledger tip")
        completion = events[-1].get("payload") or {}
        approval_hash = completion.get("approved_gate_event_hash")
        approval = next((event for event in reversed(events[:-1]) if event.get("hash") == approval_hash), None)
        approval_payload = (approval or {}).get("payload") or {}
        if (completion.get("stage") != stage or
                (approval or {}).get("event_type") != "gate_resolved" or
                approval_payload.get("stage") != stage or
                approval_payload.get("decision") != "approved"):
            raise ValueError("terminal completion is not bound to an approved final-stage gate")
        return manifest
    if manifest.get("status") != "running":
        raise ValueError("terminal reconciliation requires the historical running manifest state")
    if manifest.get("pending_gates") or manifest.get("next_step") is not None:
        raise ValueError("terminal reconciliation requires no pending gates and next_step=null")
    if not events or events[-1].get("event_type") != "gate_resolved":
        raise ValueError("terminal reconciliation requires gate_resolved to be the ledger tip")
    approval = events[-1]
    payload = approval.get("payload") or {}
    if payload.get("stage") != stage or payload.get("decision") != "approved":
        raise ValueError("terminal reconciliation requires an approved final-stage gate_resolved event")
    _append_run_completed(
        run_dir,
        stage,
        ts,
        approval_event_hash=approval["hash"],
        reconciled=True,
    )
    manifest["status"] = "done"
    manifest["next_step"] = None
    manifest["updated_at"] = ts
    _write_manifest(run_dir, manifest)
    return manifest


def fail_run(run_dir, stage: str, reason: str, ts: str) -> dict:
    """Record a deterministic hard-gate failure as a terminal, append-only state.

    A hard gate is neither a crash nor a retryable worker omission: the current
    run must not remain ``running`` and cannot be resumed past the failed stage.
    Partial scratch evidence is retained for the director packet and provenance;
    a corrected attempt starts a new run.
    """
    manifest = read_manifest(run_dir)
    existing = manifest.get("failure") or {}
    if manifest.get("status") == "failed":
        if existing.get("stage") == stage and existing.get("reason") == reason:
            return manifest
        raise RuntimeError(
            "cannot replace an existing hard-gate failure; start a new run after correcting inputs"
        )
    if manifest.get("status") in {"done", "rejected"}:
        raise RuntimeError(f"cannot mark terminal run status {manifest.get('status')!r} as failed")
    clean_reason = str(reason or "").strip()
    if not clean_reason:
        raise ValueError("hard-gate failure requires a non-empty reason")
    append_event(_ledger_path(run_dir), "run_failed",
                 {"stage": stage, "reason": clean_reason}, ts)
    manifest["status"] = "failed"
    manifest["failure"] = {"stage": stage, "reason": clean_reason, "failed_at": ts}
    manifest["pending_gates"] = []
    manifest["next_step"] = None
    manifest["updated_at"] = ts
    _write_manifest(run_dir, manifest)
    return manifest


# ---------- resume ----------

def classify_status(run_dir) -> str:
    """One of: empty / tampered / inconsistent / failed / rejected / clean_boundary / crashed_mid_stage / ready / awaiting / done / unknown."""
    events = read_events(_ledger_path(run_dir))
    if not events:
        return "empty"
    if verify_chain(events):
        return "tampered"
    manifest = read_manifest(run_dir)
    boundaries = [e for e in events if e["event_type"] == "boundary"]
    if boundaries and manifest.get("last_boundary_hash") != boundaries[-1]["hash"]:
        return "inconsistent"  # manifest anchor disagrees with ledger tip-of-boundaries
    if manifest.get("status") == "rejected":
        return "rejected"      # director vetoed a stage -> terminal, not resumable
    if manifest.get("status") == "failed":
        return "failed"        # deterministic hard gate -> terminal, not resumable
    if manifest.get("status") == "awaiting_director" or manifest.get("pending_gates"):
        return "awaiting"
    if manifest.get("status") == "done":
        return "done"
    et = events[-1]["event_type"]
    return {
        "boundary": "clean_boundary",
        "stage_started": "crashed_mid_stage",
        "run_started": "ready",
        "task_frame_pinned": "ready",
        "upstream_handoff_pinned": "ready",
        "resume": "ready",
        "gate_resolved": "ready",
        "gate_pending": "awaiting",
    }.get(et, "unknown")


def prepare_resume(run_dir, ts: str) -> dict:
    """Determine the stage to resume, guard against tampering / double-resume, log a resume event."""
    status = classify_status(run_dir)
    if status in ("tampered", "inconsistent"):
        raise RuntimeError(f"cannot resume: ledger {status}")
    if status == "done":
        raise RuntimeError("cannot resume: run already done")
    if status == "rejected":
        rej = read_manifest(run_dir).get("rejected") or {}
        raise RuntimeError(
            f"cannot resume: run was REJECTED by the director at stage {rej.get('stage', '?')} "
            "— a vetoed run is terminal and cannot be resumed (start a new run instead)")

    if status == "failed":
        failure = read_manifest(run_dir).get("failure") or {}
        raise RuntimeError(
            f"cannot resume: run hit a hard gate at stage {failure.get('stage', '?')}: "
            f"{failure.get('reason', 'unspecified reason')} — start a new run after correcting inputs")

    if status == "awaiting":
        gates = read_manifest(run_dir).get("pending_gates") or []
        raise RuntimeError(f"cannot resume: awaiting director decision at gate(s) {gates}")

    manifest = read_manifest(run_dir)
    events = read_events(_ledger_path(run_dir))

    if status == "crashed_mid_stage":
        resume_stage = events[-1]["payload"]["stage"]  # re-run the stage that never finished
    elif status in ("clean_boundary", "ready"):
        ns = manifest.get("next_step")
        if ns is None:
            raise RuntimeError("cannot resume: no next_step")
        resume_stage = ns["stage"]
    else:
        raise RuntimeError(f"cannot resume from status '{status}'")

    boundary_hash = manifest.get("last_boundary_hash")
    if boundary_hash is not None:
        for e in events:
            if e["event_type"] == "resume" and e["payload"].get("consumes_hash") == boundary_hash:
                raise RuntimeError("double-resume rejected: this boundary was already resumed")

    append_event(_ledger_path(run_dir), "resume",
                 {"consumes_hash": boundary_hash, "resume_stage": resume_stage}, ts)
    return {"resume_stage": resume_stage, "next_step": manifest.get("next_step"), "from_status": status}
