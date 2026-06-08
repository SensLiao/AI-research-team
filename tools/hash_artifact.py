"""Canonical, deterministic hashing for artifacts and the tamper-evident ledger.

Constitution Rule 2: every artifact carries an output_hash; the run-store ledger is a
hash-chain. Hashing MUST be deterministic and independent of dict key insertion order,
so the same logical content always produces the same hash across sessions / machines.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Optional


def canonical_json(obj: Any) -> str:
    """Deterministic JSON serialization: sorted keys, compact separators, UTF-8.

    Two dicts with the same content but different key order serialize identically.
    """
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sha256(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def hash_payload(payload: Any) -> str:
    """SHA-256 over the canonical JSON of a payload. Stable across key order."""
    return _sha256(canonical_json(payload))


def hash_artifact(artifact: dict) -> str:
    """Hash the payload of an enveloped artifact (the value for envelope.output_hash)."""
    if "payload" not in artifact:
        raise ValueError("artifact has no 'payload' to hash")
    return hash_payload(artifact["payload"])


def chain_hash(prev_hash: Optional[str], event: Any) -> str:
    """Hash-chain link for the ledger: SHA-256 over (prev_hash, canonical event).

    Tamper-evident: changing any past event or the order breaks every subsequent hash.
    The first event uses prev_hash=None.
    """
    material = canonical_json({"prev": prev_hash, "event": event})
    return _sha256(material)


def stamp_output_hash(artifact: dict) -> dict:
    """Return a NEW artifact (immutability) with envelope.output_hash set from its payload."""
    updated = dict(artifact)
    updated["output_hash"] = hash_artifact(artifact)
    return updated
