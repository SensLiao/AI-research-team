"""Regression tests for the promote-gate entrypoint (governance red line ②).

Closes three gaps in the M⇒D seam write side:
  (a) no runnable entrypoint — only tests called the core;
  (b) the gate trusted caller-passed `signals` instead of reading the candidate's REFERENCED audits and
      verifying their sha256 (a forged signals dict could admit a non-frozen result);
  (c) the vault write left NO ledger trace (the most audit-worthy event went unrecorded).

These prove: a real bundle with sha-verified audits admits + writes a `promote` ledger event; a FORGED
(sha-mismatched) or missing audit hard-rejects before any vault write; the human freeze requires an
out-of-band director authorization the model cannot supply.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from research_agent_teams.tools.ledger import last_of_type, read_events, verify_chain
from research_agent_teams.tools.promote_gate import (
    freeze_is_authorized,
    load_and_verify_signals,
    run_promote_gate,
)
from research_agent_teams.tools.runstore import create_run
from research_agent_teams.tools.validate_artifact import validate_payload

TS = "2026-06-10T12:00:00Z"


def _write_audit(run_dir, name, body):
    p = Path(run_dir) / "evidence" / "VERIFY" / name
    p.parent.mkdir(parents=True, exist_ok=True)
    envelope = {"artifact_id": name, "artifact_type": "verdict", "schema_version": "1.0.0",
                "created_by": "stub", "created_at": TS, "status": "final", "payload": body}
    raw = json.dumps(envelope).encode("utf-8")
    p.write_bytes(raw)
    rel = str(Path("evidence") / "VERIFY" / name)
    return {"path": rel, "sha256": "sha256:" + hashlib.sha256(raw).hexdigest()}, p


def _seed_vault(root):
    (root / "02-wiki" / "results").mkdir(parents=True, exist_ok=True)
    (root / "00-system").mkdir(parents=True, exist_ok=True)
    (root / "07-logs").mkdir(parents=True, exist_ok=True)
    return root


def _setup(tmp_path):
    runs = tmp_path / "runs"
    create_run(runs, "rid", "venue_readiness", "VERIFY", TS)
    run_dir = runs / "rid"
    leak_ref, leak_p = _write_audit(run_dir, "leakage.artifact.json", {"verdict": "PASS", "violations": []})
    fair_ref, _ = _write_audit(run_dir, "fairness.artifact.json",
                               {"panel_role": "fairness", "pass": True, "violations": []})
    _ok = {"pass": True, "evidence": "verified"}
    rev_ref, _ = _write_audit(run_dir, "review.artifact.json", {
        "verdict": "APPROVE-FREEZE",
        "checks": {"leakage": _ok, "fairness": _ok, "eval_frame": _ok, "provenance": _ok, "overclaim": _ok}})
    candidate = {
        "slug": "promoted-frozen-result", "vault_type": "result", "project": "p",
        "title": "Frozen result", "body": "Dice=0.81 on the frozen external split.",
        "leakage_audit_ref": leak_ref, "fairness_audit_ref": fair_ref, "reviewer_ref": rev_ref,
        "_path": "inbox/promotion-candidate.json", "_sha256": "sha256:" + "a" * 64,
    }
    vault = _seed_vault(tmp_path / "vault")
    return run_dir, candidate, vault, leak_p


def test_admit_with_verified_audits_writes_vault_and_records_promote_event(tmp_path):
    run_dir, candidate, vault, _ = _setup(tmp_path)
    rec = run_promote_gate(candidate, run_dir=run_dir, vault_root=vault, human_freeze=True,
                           decided_by="director", decided_at=TS)
    assert rec["admissible"] is True
    assert validate_payload("promotion_record", rec) == []
    assert (vault / "02-wiki" / "results" / "promoted-frozen-result.md").exists()
    # (c) the promotion is on the tamper-evident ledger now
    events = read_events(run_dir / "ledger.jsonl")
    assert verify_chain(events) == []
    pe = last_of_type(events, "promote")
    assert pe is not None and pe["payload"]["admissible"] is True
    assert pe["payload"]["vault_slug"] == "promoted-frozen-result"


def test_forged_audit_sha_mismatch_is_rejected_before_any_vault_write(tmp_path):
    """(b) The gate reads + sha-verifies the REAL referenced audits. Tampering an audit file after the
    candidate's ref was computed → sha mismatch → hard reject, vault untouched."""
    run_dir, candidate, vault, leak_p = _setup(tmp_path)
    leak_p.write_bytes(b'{"artifact_type":"verdict","payload":{"verdict":"PASS","violations":[]},"x":"tampered"}')
    before = set((vault / "02-wiki" / "results").glob("*.md"))
    rec = run_promote_gate(candidate, run_dir=run_dir, vault_root=vault, human_freeze=True,
                           decided_by="director", decided_at=TS)
    assert rec["admissible"] is False
    assert rec["vault_path"] is None
    assert any("sha256 mismatch" in r for r in rec["reasons"])
    assert set((vault / "02-wiki" / "results").glob("*.md")) == before, "forged audit must not write the vault"
    assert validate_payload("promotion_record", rec) == []
    pe = last_of_type(read_events(run_dir / "ledger.jsonl"), "promote")
    assert pe is not None and pe["payload"]["admissible"] is False


def test_missing_audit_ref_fails_closed(tmp_path):
    run_dir, candidate, vault, _ = _setup(tmp_path)
    candidate.pop("reviewer_ref")
    rec = run_promote_gate(candidate, run_dir=run_dir, vault_root=vault, human_freeze=True,
                           decided_by="director", decided_at=TS)
    assert rec["admissible"] is False
    assert any("reviewer_ref missing" in r for r in rec["reasons"])


def test_referenced_audit_outside_run_dir_is_refused(tmp_path):
    run_dir, candidate, vault, _ = _setup(tmp_path)
    candidate["leakage_audit_ref"] = {"path": "../../../etc/passwd", "sha256": "sha256:" + "b" * 64}
    signals, errors = load_and_verify_signals(candidate, run_dir)
    assert any("escapes the run dir" in e for e in errors)
    assert signals["leakage_pass"] is False        # the unverifiable audit fails closed


def test_freeze_accepts_explicit_director_command_or_legacy_exact_authorization(monkeypatch):
    monkeypatch.delenv("RAT_PROMOTE_AUTHORIZED", raising=False)
    assert freeze_is_authorized("rid") is False
    assert freeze_is_authorized("rid", explicit_director_command=True) is True
    monkeypatch.setenv("RAT_PROMOTE_AUTHORIZED", "rid")
    assert freeze_is_authorized("rid") is True
    assert freeze_is_authorized("OTHER") is False   # scoped to the exact run id


def test_no_freeze_means_provisional_not_admissible(tmp_path):
    """Even with all audits verified PASS/APPROVE-FREEZE, no human freeze → ceiling holds → not admissible."""
    run_dir, candidate, vault, _ = _setup(tmp_path)
    rec = run_promote_gate(candidate, run_dir=run_dir, vault_root=vault, human_freeze=False,
                           decided_by="director", decided_at=TS)
    assert rec["admissible"] is False
    assert rec["rederived_result_status"] == "provisional"
