"""Real tests for the hash-chained ledger (append + tamper detection)."""
from __future__ import annotations

import json

from research_agent_teams.tools.ledger import (
    append_event,
    head_hash,
    read_events,
    verify_chain,
)
from research_agent_teams.tools.validate_artifact import validate_against

TS = "2026-06-08T00:00:00Z"


def _seed(ledger):
    append_event(ledger, "run_started", {"mode": "design_experiment"}, TS)
    append_event(ledger, "stage_started", {"stage": "DESIGN"}, TS)
    append_event(ledger, "boundary", {"completed_stage": "DESIGN", "next": "EXECUTE"}, TS)


def test_append_builds_increasing_seq_and_links(tmp_path):
    ledger = tmp_path / "ledger.jsonl"
    _seed(ledger)
    events = read_events(ledger)
    assert [e["seq"] for e in events] == [0, 1, 2]
    assert events[0]["prev_hash"] is None
    assert events[1]["prev_hash"] == events[0]["hash"]
    assert events[2]["prev_hash"] == events[1]["hash"]
    assert head_hash(events) == events[2]["hash"]


def test_each_event_is_schema_valid(tmp_path):
    ledger = tmp_path / "ledger.jsonl"
    _seed(ledger)
    for e in read_events(ledger):
        assert validate_against("ledger_event.schema.json", e) == []


def test_verify_chain_intact(tmp_path):
    ledger = tmp_path / "ledger.jsonl"
    _seed(ledger)
    assert verify_chain(read_events(ledger)) == []


def test_empty_ledger_ok(tmp_path):
    ledger = tmp_path / "ledger.jsonl"
    assert read_events(ledger) == []
    assert verify_chain([]) == []


def test_tampered_past_event_detected(tmp_path):
    ledger = tmp_path / "ledger.jsonl"
    _seed(ledger)
    lines = ledger.read_text(encoding="utf-8").splitlines()
    e0 = json.loads(lines[0])
    e0["payload"]["mode"] = "HACKED"  # change content but leave hash field
    lines[0] = json.dumps(e0, sort_keys=True, separators=(",", ":"))
    ledger.write_text("\n".join(lines) + "\n", encoding="utf-8")
    errors = verify_chain(read_events(ledger))
    assert any("event 0" in e and "tampered" in e for e in errors)


def test_reordering_detected(tmp_path):
    ledger = tmp_path / "ledger.jsonl"
    _seed(ledger)
    lines = ledger.read_text(encoding="utf-8").splitlines()
    lines[1], lines[2] = lines[2], lines[1]  # swap two events
    ledger.write_text("\n".join(lines) + "\n", encoding="utf-8")
    assert verify_chain(read_events(ledger)) != []
