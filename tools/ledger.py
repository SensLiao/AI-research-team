"""Append-only, hash-chained run ledger (tamper-evident history).

Each line in runs/<id>/ledger.jsonl is a ledger_event:
    hash = chain_hash(prev_hash, {seq, ts, event_type, payload})

Tamper model:
  - Changing ANY non-tip event (payload, ts, type, order) is always detected by verify_chain
    (either the event's own hash stops matching, or the next event's prev_hash linkage breaks).
  - The tip event can be re-hashed by a tamperer; that is caught one level up by the run manifest,
    which independently stores last_boundary_hash (see runstore.classify_status -> "inconsistent").
"""
from __future__ import annotations

import json
import os
from contextlib import contextmanager
from pathlib import Path
from typing import Any, List, Optional

from research_agent_teams.tools.hash_artifact import canonical_json, chain_hash

EVENT_TYPES = {
    "run_started", "task_frame_pinned", "upstream_handoff_pinned", "stage_started", "step_done", "boundary",
    "resume", "gate_pending", "gate_resolved", "promote",
}


@contextmanager
def _ledger_lock(ledger_path):
    """OS-level exclusive lock on a sidecar file for the read-seq-append critical section.

    Audit M13: the documented single-writer constraint (orchestrator only) is now also enforced —
    two processes appending concurrently would both read the same prev_hash and fork the chain.
    Windows uses msvcrt.locking, POSIX uses fcntl.flock; both block until the lock is free. The
    sidecar `<ledger>.lock` is transient bookkeeping, never part of the tamper-evident record."""
    lock_path = str(ledger_path) + ".lock"
    fh = open(lock_path, "a+")
    try:
        if os.name == "nt":
            import msvcrt
            fh.seek(0)
            msvcrt.locking(fh.fileno(), msvcrt.LK_LOCK, 1)
            try:
                yield
            finally:
                fh.seek(0)
                msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
    finally:
        fh.close()


def read_events(ledger_path) -> List[dict]:
    p = Path(ledger_path)
    if not p.exists():
        return []
    events = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            events.append(json.loads(line))
    return events


def _core(seq: int, ts: str, event_type: str, payload: Any) -> dict:
    return {"seq": seq, "ts": ts, "event_type": event_type, "payload": payload}


def append_event(ledger_path, event_type: str, payload: dict, ts: str) -> dict:
    """Append one event, computing seq + hash-chain from existing events. Returns the event.

    Audit M4: the existing chain is verified BEFORE every append — tampering now fails loud at the
    next write instead of waiting for a resume/status check. Audit M13: the read-seq-append section
    runs under an OS file lock so concurrent writers cannot silently fork the chain."""
    if event_type not in EVENT_TYPES:
        raise ValueError(f"unknown event_type '{event_type}'")
    with _ledger_lock(ledger_path):
        events = read_events(ledger_path)
        errors = verify_chain(events)
        if errors:
            raise ValueError(
                f"refusing to append to a corrupted ledger ({ledger_path}): {errors[:3]}")
        seq = len(events)
        prev_hash: Optional[str] = events[-1]["hash"] if events else None
        core = _core(seq, ts, event_type, payload)
        event = {**core, "prev_hash": prev_hash, "hash": chain_hash(prev_hash, core)}
        with open(ledger_path, "a", encoding="utf-8") as fh:
            fh.write(canonical_json(event) + "\n")
    return event


def verify_chain(events: List[dict]) -> List[str]:
    """Return a list of integrity errors; empty list == intact chain."""
    errors = []
    prev_hash: Optional[str] = None
    for i, e in enumerate(events):
        if e.get("seq") != i:
            errors.append(f"event {i}: seq mismatch (got {e.get('seq')})")
        if e.get("prev_hash") != prev_hash:
            errors.append(f"event {i}: prev_hash linkage broken")
        expected = chain_hash(e.get("prev_hash"), _core(e.get("seq"), e.get("ts"), e.get("event_type"), e.get("payload")))
        if e.get("hash") != expected:
            errors.append(f"event {i}: hash mismatch (content tampered)")
        prev_hash = e.get("hash")
    return errors


def head_hash(events: List[dict]) -> Optional[str]:
    return events[-1]["hash"] if events else None


def last_of_type(events: List[dict], event_type: str) -> Optional[dict]:
    for e in reversed(events):
        if e.get("event_type") == event_type:
            return e
    return None
