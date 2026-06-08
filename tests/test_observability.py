"""Real tests for the observability log + ADR governance record."""
from __future__ import annotations

import pytest

from research_agent_teams.tools.obslog import append_log, read_logs
from research_agent_teams.tools.validate_artifact import validate_against

TS = "2026-06-08T00:00:00Z"


# ---------- observability log ----------

def _log(**over):
    base = {"agent_name": "lit-scout", "task_id": "run-1", "started_at": TS, "tool_calls": 3}
    base.update(over)
    return base


def test_append_and_read_log(tmp_path):
    log = tmp_path / "obs.jsonl"
    append_log(log, _log())
    append_log(log, _log(agent_name="evidence-verifier", confidence=0.8))
    rows = read_logs(log)
    assert len(rows) == 2
    assert rows[1]["agent_name"] == "evidence-verifier"


def test_invalid_log_rejected(tmp_path):
    log = tmp_path / "obs.jsonl"
    with pytest.raises(ValueError, match="invalid agent_run_log"):
        append_log(log, {"task_id": "run-1", "started_at": TS})  # missing agent_name


def test_confidence_out_of_range_rejected(tmp_path):
    log = tmp_path / "obs.jsonl"
    with pytest.raises(ValueError):
        append_log(log, _log(confidence=1.5))


# ---------- ADR ----------

def _adr(**over):
    base = {
        "decision_id": "ADR-0042",
        "question": "rank=4 and rank=16, or full sweep?",
        "options": ["rank 4+16 first", "full sweep [4,8,16]"],
        "status": "proposed",
    }
    base.update(over)
    return base


def test_valid_adr_passes():
    assert validate_against("adr.schema.json", _adr()) == []


def test_adr_requires_two_options():
    assert validate_against("adr.schema.json", _adr(options=["only one"])) != []


def test_adr_bad_id_pattern_rejected():
    assert validate_against("adr.schema.json", _adr(decision_id="42")) != []


def test_adr_approved_shape():
    adr = _adr(status="approved", chosen_option="rank 4+16 first",
               approved_by="director", approved_at=TS, downstream_locked_artifacts=["experiment_matrix"])
    assert validate_against("adr.schema.json", adr) == []
