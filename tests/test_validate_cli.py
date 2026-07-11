"""Unit tests for tools/validate_cli (the JS-hook shell-out wrapper). Covers every branch:
file-arg / --stdin / no-arg / unreadable / valid / invalid. validate_artifact is monkeypatched so this
isolates the CLI's load + exit-code logic from the artifact schema (tested in test_validate_artifact).
Closes the scan-flagged 0%-coverage gap on validate_cli.py.
"""
from __future__ import annotations

import io
import json

from research_agent_teams.tools import validate_cli


def test_main_valid_file(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(validate_cli, "validate_artifact", lambda a: [])
    p = tmp_path / "a.json"
    p.write_text(json.dumps({"x": 1}), encoding="utf-8")
    rc = validate_cli.main(["validate_cli", str(p)])
    assert rc == 0
    assert "OK" in capsys.readouterr().out


def test_main_invalid_file(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(validate_cli, "validate_artifact", lambda a: ["missing field y"])
    p = tmp_path / "a.json"
    p.write_text("{}", encoding="utf-8")
    rc = validate_cli.main(["validate_cli", str(p)])
    assert rc == 2
    assert "missing field y" in capsys.readouterr().err


def test_main_no_args(capsys):
    rc = validate_cli.main(["validate_cli"])
    assert rc == 2
    assert "cannot read artifact" in capsys.readouterr().err


def test_main_nonexistent_file(capsys):
    rc = validate_cli.main(["validate_cli", "no_such_dir/nope.json"])
    assert rc == 2
    assert "cannot read artifact" in capsys.readouterr().err


def test_main_stdin_valid(monkeypatch, capsys):
    monkeypatch.setattr(validate_cli, "validate_artifact", lambda a: [])
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"k": "v"})))
    rc = validate_cli.main(["validate_cli", "--stdin"])
    assert rc == 0
    assert "OK" in capsys.readouterr().out


def test_main_stdin_unparsable(monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin", io.StringIO("not json at all"))
    rc = validate_cli.main(["validate_cli", "--stdin"])
    assert rc == 2
    assert "cannot read artifact" in capsys.readouterr().err
