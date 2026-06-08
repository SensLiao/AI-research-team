"""Real tests for the permission-scope decision core."""
from __future__ import annotations

from research_agent_teams.tools.scope_guard import decide


def _scope(tmp_path):
    return {
        "run_root": str(tmp_path / "runs"),
        "run_id": "r1",
        "stage": "DESIGN",
        "vault_root": str(tmp_path / "vault"),
    }


def test_in_stage_scope_allowed(tmp_path):
    s = _scope(tmp_path)
    target = f"{s['run_root']}/r1/evidence/DESIGN/note.md"
    ok, _ = decide("Write", target, s)
    assert ok


def test_inbox_allowed(tmp_path):
    s = _scope(tmp_path)
    ok, _ = decide("Write", f"{s['run_root']}/r1/inbox/cand.md", s)
    assert ok


def test_bash_blocked(tmp_path):
    ok, reason = decide("Bash", None, _scope(tmp_path))
    assert not ok and "Bash" in reason


def test_vault_write_blocked(tmp_path):
    s = _scope(tmp_path)
    ok, reason = decide("Write", f"{s['vault_root']}/02-wiki/x.md", s)
    assert not ok and "vault" in reason


def test_other_stage_blocked(tmp_path):
    s = _scope(tmp_path)
    ok, reason = decide("Write", f"{s['run_root']}/r1/evidence/EXECUTE/y.md", s)
    assert not ok and "stage scope" in reason


def test_infra_write_blocked(tmp_path):
    s = _scope(tmp_path)
    ok, reason = decide("Write", f"{s['run_root']}/r1/manifest.yaml", s)
    assert not ok and "single-writer infra" in reason


def test_nongoverned_path_is_noop_allowed(tmp_path):
    s = _scope(tmp_path)
    ok, _ = decide("Write", str(tmp_path / "elsewhere" / "z.md"), s)
    assert ok


def test_read_tool_allowed(tmp_path):
    ok, _ = decide("Read", "anything", _scope(tmp_path))
    assert ok
