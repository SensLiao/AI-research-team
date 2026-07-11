"""Real tests for the permission-scope decision core."""
from __future__ import annotations

from pathlib import Path

import pytest

from research_agent_teams.tools import scope_guard
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


# ---- ③ machine-root guard: powered by default even when the caller omits vault_root ----

def test_vault_block_powered_when_scope_omits_vault_root(tmp_path, monkeypatch):
    """The operate.commit_stage gap: a caller passes NO vault_root, yet a direct vault write is still blocked
    because decide discovers the vault (here via RAT_VAULT_ROOT). Guard is on by default, not dependent on
    the caller remembering to wire it."""
    monkeypatch.setenv("RAT_VAULT_ROOT", str(tmp_path / "vault"))
    scope = {"run_root": str(tmp_path / "runs"), "run_id": "r1", "stage": "DESIGN"}  # no vault_root key
    ok, reason = decide("Write", str(tmp_path / "vault" / "02-wiki" / "x.md"), scope)
    assert not ok and "vault" in reason


def test_vault_block_via_two_repo_layout_discovery(tmp_path, monkeypatch):
    """With no env override and no scope vault_root, decide blocks writes into the layout-discovered real
    vault (the sibling PhD-Research-OS) — the always-on absolute-path guard the audit asked for."""
    monkeypatch.delenv("RAT_VAULT_ROOT", raising=False)
    vault = scope_guard.discover_vault_root()
    if not vault:
        pytest.skip("real PhD-Research-OS vault not resolvable in this checkout")
    scope = {"run_root": str(tmp_path / "runs"), "run_id": "r1", "stage": "DESIGN"}
    ok, reason = decide("Write", str(Path(vault) / "02-wiki" / "results" / "forged.md"), scope)
    assert not ok and "vault" in reason


# ---- adversarial: the boundary check resists `..` traversal + Windows case (previously untested) ----

def test_vault_block_resists_dotdot_traversal(tmp_path):
    s = _scope(tmp_path)   # vault = tmp_path/vault, stage = DESIGN
    # a path that climbs out of the stage dir with ../ and lands in the vault — must still be blocked
    sneaky = f"{s['run_root']}/r1/evidence/DESIGN/../../../../vault/02-wiki/x.md"
    ok, reason = decide("Write", sneaky, s)
    assert not ok and "vault" in reason


def test_stage_scope_resists_dotdot_into_sibling_stage(tmp_path):
    s = _scope(tmp_path)   # stage = DESIGN
    sneaky = f"{s['run_root']}/r1/evidence/DESIGN/../EXECUTE/y.md"   # climbs to a sibling stage
    ok, reason = decide("Write", sneaky, s)
    assert not ok and "stage scope" in reason


def test_vault_block_is_case_insensitive_on_windows(tmp_path, monkeypatch):
    import os
    monkeypatch.setenv("RAT_VAULT_ROOT", str(tmp_path / "Vault"))   # capital V
    scope = {"run_root": str(tmp_path / "runs"), "run_id": "r1", "stage": "DESIGN"}
    target = str(tmp_path / "vault" / "02-wiki" / "x.md")           # lowercase v
    ok, reason = decide("Write", target, scope)
    if os.name == "nt":
        assert not ok and "vault" in reason     # NTFS is case-insensitive -> a case-flip cannot bypass
    else:
        assert ok                                # case-sensitive FS: 'vault' != 'Vault' (correct)
