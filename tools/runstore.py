"""Run-store: crash-safe stop/resume on top of the hash-chained ledger.

A run lives in runs/<run_id>/ {manifest.yaml, ledger.jsonl, evidence/, inbox/}.
The manifest is the single source of truth (single-writer = orchestrator/state-tracker).
Resume reads ONLY manifest + ledger; prior chat memory is non-authoritative.

Crash safety: every manifest write is atomic (temp -> fsync -> os.replace), so a half-written
manifest is never observed. A clean checkpoint ends with a `boundary` event; a `stage_started`
with no following `boundary` means the process died mid-stage -> roll back to that stage and re-run it.
"""
from __future__ import annotations

import hashlib
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
    tmp = str(path) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(text)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)  # atomic on same volume (POSIX + Windows)


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


# ---------- run lifecycle ----------

def create_run(runs_dir, run_id: str, mode: str, entry_stage: str, ts: str,
               domain_profile_ref: Optional[str] = None,
               first_agent_subset: Optional[List[str]] = None) -> dict:
    run_dir = Path(runs_dir) / run_id
    (run_dir / "evidence").mkdir(parents=True, exist_ok=True)
    (run_dir / "inbox").mkdir(parents=True, exist_ok=True)
    append_event(_ledger_path(run_dir), "run_started", {"mode": mode, "entry_stage": entry_stage}, ts)
    manifest = {
        "schema_version": "1.0.0",
        "run_id": run_id,
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


def start_stage(run_dir, stage: str, ts: str, agent_subset: Optional[List[str]] = None) -> dict:
    append_event(_ledger_path(run_dir), "stage_started", {"stage": stage}, ts)
    manifest = read_manifest(run_dir)
    manifest["status"] = "running"
    manifest["updated_at"] = ts
    manifest["next_step"] = {"stage": stage, "action": "run", "agent_subset": agent_subset or []}
    _write_manifest(run_dir, manifest)
    return manifest


def checkpoint_stage(run_dir, stage: str, artifact_paths: List, idempotency_key: str, ts: str) -> dict:
    """Finish a stage: record step_done + boundary, update manifest atomically. Resumable after this."""
    artifacts = [{"path": str(p), "sha256": hash_file(p)} for p in artifact_paths]
    append_event(_ledger_path(run_dir), "step_done",
                 {"stage": stage, "artifacts": artifacts, "idempotency_key": idempotency_key}, ts)
    nxt = next_stage(stage)
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


def record_gate(run_dir, stage: str, decision: str, ts: str, reason: Optional[str] = None) -> dict:
    """Record a director gate decision durably — the veto fix.

    Appends a hash-chained `gate_resolved` event so EVERY director_signoff outcome (approved / modify /
    reject) is on the tamper-evident permanent record; a reject can never be silently 'lost' from the
    ledger. On REJECT the run becomes TERMINAL: status='rejected', next_step cleared, and `prepare_resume`
    refuses it — so a plain 'continue' can no longer walk a vetoed run to completion. Approve/modify leave
    the run running (the engine then checkpoints the stage as usual)."""
    dec = (decision or "").strip().lower()
    append_event(_ledger_path(run_dir), "gate_resolved",
                 {"stage": stage, "decision": dec, "reason": reason}, ts)
    manifest = read_manifest(run_dir)
    manifest["updated_at"] = ts
    if dec == "reject":
        manifest["status"] = "rejected"
        manifest["rejected"] = {"stage": stage, "reason": reason, "decided_at": ts}
        manifest["next_step"] = None
    _write_manifest(run_dir, manifest)
    return manifest


# ---------- resume ----------

def classify_status(run_dir) -> str:
    """One of: empty / tampered / inconsistent / rejected / clean_boundary / crashed_mid_stage / ready / awaiting / done / unknown."""
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
    if manifest.get("status") == "done":
        return "done"
    et = events[-1]["event_type"]
    return {
        "boundary": "clean_boundary",
        "stage_started": "crashed_mid_stage",
        "run_started": "ready",
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
