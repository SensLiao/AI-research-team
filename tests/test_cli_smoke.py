"""Smoke tests for the CLI entry layer (execute / operate / promote_gate `main()`).

The audit flagged 0 coverage on the CLI layer. These drive each `main(argv)` end-to-end with deterministic
inputs and assert it parses, runs the core, and emits parseable JSON without crashing — no live server, no
real credentials, no real vault.
"""
from __future__ import annotations

import json

from research_agent_teams.tools.runstore import create_run

TS = "2026-06-10T00:00:00Z"
NO_DOTENV = "research_agent_teams/.env.__nonexistent_for_tests__"


# ----------------------------- execute CLI (offline `plan`) -----------------------------

def test_execute_cli_plan_smoke(capsys, monkeypatch):
    from research_agent_teams.execute import cli
    for k, v in {"RAT_SERVER_HOST": "fake.lab.edu", "RAT_SERVER_USER": "tester",
                 "RAT_REMOTE_WORKDIR": "/home/tester/runs", "RAT_REMOTE_PYTHON": "python3"}.items():
        monkeypatch.setenv(k, v)
    cli.main(["plan", "--run-id", "exp-1", "--script", "train.py", "--args", "--epochs 3", "--env", NO_DOTENV])
    out = capsys.readouterr().out
    parsed = json.loads(out)
    assert parsed["remote_run_dir"].endswith("/exp-1")
    assert parsed["connection"].startswith("NOT CONNECTED")


# ----------------------------- operate CLI (begin / status / reject) -----------------------------

def test_operate_cli_begin_status_reject_smoke(tmp_path, capsys):
    from research_agent_teams.operate import cli
    runs = str(tmp_path / "runs")
    cli.main(["begin", "--mode", "new_direction", "--request", "find a direction",
              "--run-id", "op-smoke", "--runs-dir", runs, "--ts", TS])
    begin_out = json.loads(capsys.readouterr().out)
    assert begin_out["run_id"] == "op-smoke" and begin_out["stages"][0] == "DISCOVER"

    cli.main(["status", "--run-id", "op-smoke", "--runs-dir", runs, "--ts", TS])
    assert "run_status" in json.loads(capsys.readouterr().out)

    # the director veto subcommand is wired and terminal
    cli.main(["reject", "--run-id", "op-smoke", "--stage", "DISCOVER", "--runs-dir", runs,
              "--ts", TS, "--reason", "pivot"])
    rej = json.loads(capsys.readouterr().out)
    assert rej["rejected"] is True and rej["status"] == "rejected"

    cli.main(["status", "--run-id", "op-smoke", "--runs-dir", runs, "--ts", TS])
    assert json.loads(capsys.readouterr().out)["run_status"] == "rejected"


# ----------------------------- promote_gate CLI -----------------------------

def test_promote_gate_cli_smoke_rejects_without_freeze(tmp_path, capsys, monkeypatch):
    from research_agent_teams.tools import promote_gate
    monkeypatch.delenv("RAT_PROMOTE_AUTHORIZED", raising=False)   # no out-of-band freeze
    runs = tmp_path / "runs"
    create_run(runs, "pg", "venue_readiness", "VERIFY", TS)
    cand = tmp_path / "cand.json"
    cand.write_text(json.dumps({"slug": "x", "vault_type": "result"}), encoding="utf-8")
    rc = promote_gate.main(["--run-id", "pg", "--runs-dir", str(runs),
                            "--candidate", str(cand), "--vault", str(tmp_path / "vault"), "--ts", TS])
    assert rc == 3                                   # not admissible (no freeze, no verified audits)
    rec = json.loads(capsys.readouterr().out)
    assert rec["admissible"] is False
    assert "gate_note" in rec                         # explains the freeze was not authorized
