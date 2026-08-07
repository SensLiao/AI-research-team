"""D8 (2026-08-06): director-only reopen of a hard-gate-failed run.

Provenance — why this exists at all. `gap_breadth-20260804T142806Z` raised a plain
`GateBlock` at 05:41:10Z over ONE prose field of ONE closure record (lexical binding to
its own quoted span measured 0.21 against a 0.25 floor). The field was repaired at
06:00:40Z and re-measured at 0.52, with all six snapshot hashes still verifying. The
content was correct; the run was dead anyway, and 8 opus seats' worth of a 2.2 MB
114-gap dossier could not be shipped. `fail_run` being terminal is right; being
terminal FOREVER, with no audited human override, is what these tests fix.

Everything that made the failure trustworthy must survive the override, so the tests
below spend most of their weight on what reopen must REFUSE, not on the happy path.
"""
from __future__ import annotations

import json

import pytest

from research_agent_teams.tools import runstore


TS0 = "2026-08-06T00:00:00Z"
TS1 = "2026-08-06T01:00:00Z"
TS2 = "2026-08-06T02:00:00Z"


RUN_ID = "gap_breadth-20260806T000000Z"


def _new_run(tmp_path):
    runstore.create_run(tmp_path, RUN_ID, "gap_breadth", "DISCOVER", TS0)
    return runstore.run_dir_for(tmp_path, RUN_ID)


def _failed_run(tmp_path):
    run_dir = _new_run(tmp_path)
    runstore.start_stage(run_dir, "DISCOVER", TS0)
    runstore.fail_run(run_dir, "DISCOVER", "closure scope BLOCK: FW-4 overlap=0.21", TS1)
    return run_dir


def test_reopen_restores_running_and_keeps_the_failure(tmp_path):
    run_dir = _failed_run(tmp_path)
    assert runstore.read_manifest(run_dir)["status"] == "failed"

    manifest = runstore.reopen_failed_run(
        run_dir, "FW-4 completed_scope rewritten; binding re-measured 0.21 -> 0.52",
        "director", TS2,
        inbox_digest=[{"path": "DISCOVER.gap-prosecutor.bundle.json", "sha256": "sha256:" + "a" * 64}],
    )

    assert manifest["status"] == "running"
    assert manifest["failure"] is None
    # The failure is MOVED, never erased — the run stays marked as having failed.
    assert len(manifest["failure_history"]) == 1
    row = manifest["failure_history"][0]
    assert row["reason"] == "closure scope BLOCK: FW-4 overlap=0.21"
    assert row["failed_at"] == TS1
    assert row["reopened_at"] == TS2
    assert row["authorized_by"] == "director"
    assert "0.52" in row["reopen_reason"]


def test_reopen_appends_to_the_ledger_and_leaves_run_failed_intact(tmp_path):
    run_dir = _failed_run(tmp_path)
    runstore.reopen_failed_run(run_dir, "repaired and re-verified", "director", TS2)

    events = [json.loads(line) for line in
              (run_dir / "ledger.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    types = [e.get("event_type") for e in events]
    # The original hard-gate event is still there, in order, untouched.
    assert "run_failed" in types
    assert types.index("run_failed") < types.index("run_reopened")
    reopened = events[[i for i, t in enumerate(types) if t == "run_reopened"][0]]
    assert reopened["payload"]["authorized_by"] == "director"
    assert reopened["payload"]["reopened_failure"]["failed_at"] == TS1


def test_reopen_records_the_evidence_fingerprint(tmp_path):
    """'What changed between the failure and the reopen' must be computable later."""
    run_dir = _failed_run(tmp_path)
    digest = [{"path": "DISCOVER.gap-prosecutor.bundle.json", "sha256": "sha256:" + "b" * 64}]
    runstore.reopen_failed_run(run_dir, "repaired", "director", TS2, inbox_digest=digest)
    events = [json.loads(line) for line in
              (run_dir / "ledger.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    reopened = [e for e in events if e.get("event_type") == "run_reopened"][0]
    assert reopened["payload"]["inbox_digest"] == digest


# --- what reopen must REFUSE -------------------------------------------------

def test_only_the_director_may_reopen(tmp_path):
    """No model, worker or recipe may authorize this — that is the whole gate."""
    run_dir = _failed_run(tmp_path)
    for impostor in ("model", "gap-prosecutor", "orchestrator", "", None):
        with pytest.raises(PermissionError):
            runstore.reopen_failed_run(run_dir, "repaired", impostor, TS2)
    assert runstore.read_manifest(run_dir)["status"] == "failed"


def test_reopen_requires_a_reason(tmp_path):
    run_dir = _failed_run(tmp_path)
    with pytest.raises(ValueError):
        runstore.reopen_failed_run(run_dir, "   ", "director", TS2)
    assert runstore.read_manifest(run_dir)["status"] == "failed"


def test_reopen_refuses_a_run_that_did_not_fail(tmp_path):
    """Reopen is for hard-gate death only — it is not a general status editor."""
    run_dir = _new_run(tmp_path)
    with pytest.raises(RuntimeError):
        runstore.reopen_failed_run(run_dir, "no reason to be here", "director", TS2)


def test_the_same_failure_cannot_be_reopened_twice(tmp_path):
    """One reopen per failure, or this becomes a retry loop that grinds a gate down."""
    run_dir = _failed_run(tmp_path)
    runstore.reopen_failed_run(run_dir, "first repair", "director", TS2)
    runstore.fail_run(run_dir, "DISCOVER", "closure scope BLOCK: FW-4 overlap=0.21", TS1)
    with pytest.raises(RuntimeError) as exc:
        runstore.reopen_failed_run(run_dir, "second repair", "director", TS2)
    assert "already been reopened" in str(exc.value)


def test_a_reopened_run_can_be_failed_again_by_the_same_gate(tmp_path):
    """Reopen releases the stage; it does not pass it. An unrepaired defect dies again."""
    run_dir = _failed_run(tmp_path)
    runstore.reopen_failed_run(run_dir, "claimed repair", "director", TS2)
    runstore.fail_run(run_dir, "DISCOVER", "closure scope BLOCK: FW-4 STILL 0.21", TS2)
    manifest = runstore.read_manifest(run_dir)
    assert manifest["status"] == "failed"
    assert manifest["failure"]["reason"].endswith("STILL 0.21")
    assert len(manifest["failure_history"]) == 1  # the first failure is still on record
