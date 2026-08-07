"""Append-only, hash-chained run ledger.

Each line in runs/<id>/ledger.jsonl is a ledger_event:
    hash = chain_hash(prev_hash, {seq, ts, event_type, payload})

2026-08-07 de-governance: the hash chain is still computed and written on every append (this
module's core primitive; downstream schemas and resume still read `hash`/`prev_hash`), but it no
longer GATES anything. `verify_chain` stays available as a read-only diagnostic (workbench
governance calls it to report on chain health) — appending no longer calls it first, and
`runstore.classify_status` no longer derives a "tampered"/"inconsistent" run status from it.
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
    "resume", "gate_pending", "gate_resolved", "run_completed", "run_failed", "run_reopened", "promote",
}
#: `run_reopened` (D8, 2026-08-06) is the ONLY event that may follow `run_failed` on the same run,
#: and it never replaces it: the hard-gate failure stays on the chain verbatim, and the reopen is
#: appended after it carrying the director's authority, the reason, and a SHA-256 digest of every
#: worker bundle as it stood at reopen time. Reading the chain therefore still shows that this run
#: failed — the override is recorded, not laundered.


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

    2026-08-07 de-governance: no longer refuses to append just because `verify_chain` would flag the
    existing chain (that was tamper-evidence, not a correctness gate on THIS write) — the chain is
    still computed and written every append, `verify_chain` just isn't called first anymore. Audit
    M13: the read-seq-append section still runs under an OS file lock so concurrent writers cannot
    silently fork the chain."""
    if event_type not in EVENT_TYPES:
        raise ValueError(f"unknown event_type '{event_type}'")
    with _ledger_lock(ledger_path):
        events = read_events(ledger_path)
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
