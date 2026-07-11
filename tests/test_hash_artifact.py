"""Real tests for the deterministic hasher + hash-chain (tamper-evidence)."""
from __future__ import annotations

import pytest

from research_agent_teams.tools.hash_artifact import (
    canonical_json,
    chain_hash,
    hash_artifact,
    hash_payload,
    stamp_output_hash,
)


def test_canonical_json_is_key_order_independent():
    a = {"b": 1, "a": 2, "nested": {"y": 1, "x": 2}}
    b = {"a": 2, "nested": {"x": 2, "y": 1}, "b": 1}
    assert canonical_json(a) == canonical_json(b)


def test_hash_payload_deterministic_and_prefixed():
    p = {"task_id": "t1", "mode": "design_experiment"}
    h1 = hash_payload(p)
    h2 = hash_payload(dict(reversed(list(p.items()))))
    assert h1 == h2
    assert h1.startswith("sha256:")
    assert len(h1) == len("sha256:") + 64


def test_hash_payload_changes_on_any_content_change():
    base = {"mode": "design_experiment", "n": 3}
    changed = {"mode": "design_experiment", "n": 4}
    assert hash_payload(base) != hash_payload(changed)


def test_hash_artifact_requires_payload():
    with pytest.raises(ValueError):
        hash_artifact({"artifact_type": "task_frame"})  # no payload


def test_chain_hash_links_depend_on_previous():
    e1 = {"event": "stage_started", "stage": "DESIGN"}
    h1 = chain_hash(None, e1)
    e2 = {"event": "boundary", "next": "EXECUTE"}
    h2_after_h1 = chain_hash(h1, e2)
    h2_after_other = chain_hash("sha256:deadbeef", e2)
    # Same event, different predecessor => different chain hash.
    assert h2_after_h1 != h2_after_other


def test_chain_hash_is_tamper_evident():
    e1 = {"event": "stage_started", "stage": "DESIGN"}
    h1 = chain_hash(None, e1)
    # Tampering with the past event must change its hash.
    tampered = {"event": "stage_started", "stage": "EXECUTE"}
    assert chain_hash(None, tampered) != h1


def test_stamp_output_hash_is_immutable_and_correct():
    art = {
        "artifact_type": "task_frame",
        "output_hash": None,
        "payload": {"task_id": "t1", "mode": "x"},
    }
    stamped = stamp_output_hash(art)
    assert art["output_hash"] is None  # original untouched (immutability)
    assert stamped["output_hash"] == hash_payload(art["payload"])
    assert stamped is not art
