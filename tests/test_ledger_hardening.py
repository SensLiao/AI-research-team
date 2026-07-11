"""Ledger hardening (audit M4/M13): verify-before-append + the lock sidecar + the new event type."""
from __future__ import annotations

import json

import pytest

from research_agent_teams.tools.ledger import EVENT_TYPES, append_event, read_events, verify_chain
from research_agent_teams.tools.validate_artifact import validate_against

TS = "2026-06-13T00:00:00Z"


def test_append_refuses_a_corrupted_ledger(tmp_path):
    lp = tmp_path / "ledger.jsonl"
    append_event(lp, "run_started", {"mode": "x", "entry_stage": "DISCOVER"}, TS)
    append_event(lp, "stage_started", {"stage": "DISCOVER"}, TS)
    events = read_events(lp)
    events[0]["payload"]["mode"] = "tampered"                      # corrupt a non-tip event
    lp.write_text("\n".join(json.dumps(e) for e in events) + "\n", encoding="utf-8")
    assert verify_chain(read_events(lp))                           # detectably broken
    with pytest.raises(ValueError, match="refusing to append to a corrupted ledger"):
        append_event(lp, "stage_started", {"stage": "IDEATE"}, TS)  # M4: fails at the NEXT write


def test_lock_sidecar_never_enters_the_chain_and_appends_stay_clean(tmp_path):
    lp = tmp_path / "ledger.jsonl"
    for i in range(5):
        append_event(lp, "stage_started" if i else "run_started",
                     {"stage": f"s{i}"} if i else {"mode": "m", "entry_stage": "DISCOVER"}, TS)
    assert (tmp_path / "ledger.jsonl.lock").exists()               # M13: the lock sidecar
    events = read_events(lp)
    assert len(events) == 5 and verify_chain(events) == []


def test_task_frame_pinned_is_a_first_class_event_type(tmp_path):
    assert "task_frame_pinned" in EVENT_TYPES
    lp = tmp_path / "ledger.jsonl"
    e = append_event(lp, "task_frame_pinned",
                     {"task_frame_sha256": "sha256:abc", "mode": "m", "north_star_statement": "s"}, TS)
    assert validate_against("ledger_event.schema.json", e) == []
    assert verify_chain(read_events(lp)) == []


def test_upstream_handoff_pinned_is_a_first_class_event_type():
    assert "upstream_handoff_pinned" in EVENT_TYPES
