"""Ledger hardening (audit M13 + R3 §B①): the lock sidecar + the new event types.

M4's original "verify-before-append" GATE is gone — append no longer refuses to write onto a
corrupted chain (resume/reopen must keep working even when history upstream is imperfect).
`verify_chain` itself is untouched and stays load-bearing as a read-only diagnostic (still what
`workbench governance` reads); only its power to BLOCK a write was removed.
"""
from __future__ import annotations

import json

from research_agent_teams.tools.ledger import EVENT_TYPES, append_event, read_events, verify_chain
from research_agent_teams.tools.validate_artifact import validate_against

TS = "2026-06-13T00:00:00Z"


def test_append_tolerates_a_corrupted_ledger_but_verify_chain_still_reports_it(tmp_path):
    lp = tmp_path / "ledger.jsonl"
    append_event(lp, "run_started", {"mode": "x", "entry_stage": "DISCOVER"}, TS)
    append_event(lp, "stage_started", {"stage": "DISCOVER"}, TS)
    events = read_events(lp)
    events[0]["payload"]["mode"] = "tampered"                      # corrupt a non-tip event
    lp.write_text("\n".join(json.dumps(e) for e in events) + "\n", encoding="utf-8")
    assert verify_chain(read_events(lp))                           # still detectably broken —
                                                                    # the diagnostic itself is intact
    new_event = append_event(lp, "stage_started", {"stage": "IDEATE"}, TS)  # no longer refuses
    assert new_event["seq"] == 2
    assert read_events(lp)[-1] == new_event
    assert verify_chain(read_events(lp))                           # the prior corruption still shows


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
