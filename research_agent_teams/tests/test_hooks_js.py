"""Real tests for the runtime .js hooks — invoked through node (the real artifacts Claude Code runs)."""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
HOOKS = ROOT / "research_agent_teams" / "hooks"
NODE = shutil.which("node")

pytestmark = pytest.mark.skipif(NODE is None, reason="node not available")


def _run_hook(hook_name, payload, env_extra=None):
    import os
    env = dict(os.environ)
    if env_extra:
        env.update(env_extra)
    proc = subprocess.run(
        [NODE, str(HOOKS / hook_name)],
        input=json.dumps(payload), text=True, capture_output=True, env=env,
    )
    return proc.returncode, proc.stderr


# ---------- permission-scope-guard.js ----------

def _scope_env(tmp_path):
    return {
        "RAT_RUN_ROOT": str(tmp_path / "runs"),
        "RAT_RUN_ID": "r1",
        "RAT_STAGE": "DESIGN",
        "RAT_VAULT_ROOT": str(tmp_path / "vault"),
    }


def test_scope_guard_allows_in_scope(tmp_path):
    env = _scope_env(tmp_path)
    payload = {"tool_name": "Write", "tool_input": {"file_path": f"{env['RAT_RUN_ROOT']}/r1/evidence/DESIGN/n.md"}}
    rc, _ = _run_hook("permission-scope-guard.js", payload, env)
    assert rc == 0


def test_scope_guard_blocks_vault(tmp_path):
    env = _scope_env(tmp_path)
    payload = {"tool_name": "Write", "tool_input": {"file_path": f"{env['RAT_VAULT_ROOT']}/x.md"}}
    rc, err = _run_hook("permission-scope-guard.js", payload, env)
    assert rc == 2 and "vault" in err


def test_scope_guard_blocks_bash(tmp_path):
    env = _scope_env(tmp_path)
    rc, err = _run_hook("permission-scope-guard.js", {"tool_name": "Bash", "tool_input": {"command": "ls"}}, env)
    assert rc == 2 and "Bash" in err


def test_scope_guard_blocks_project_workspace(tmp_path):
    # projects/<slug>/ is operator-managed — a fenced agent may never write it (mirror of scope_guard.py)
    env = _scope_env(tmp_path)
    env["RAT_PROJECTS_ROOT"] = str(tmp_path / "projects")
    payload = {"tool_name": "Write",
               "tool_input": {"file_path": f"{env['RAT_PROJECTS_ROOT']}/proj-a/results/x.json"}}
    rc, err = _run_hook("permission-scope-guard.js", payload, env)
    assert rc == 2 and "operator-managed" in err


def test_scope_guard_noop_without_scope(tmp_path):
    # No RAT_RUN_ID in env -> not operating a fenced agent -> NO-OP allow.
    import os
    env = {k: v for k, v in os.environ.items() if k != "RAT_RUN_ID"}
    proc = subprocess.run(
        [NODE, str(HOOKS / "permission-scope-guard.js")],
        input=json.dumps({"tool_name": "Write", "tool_input": {"file_path": "/anything"}}),
        text=True, capture_output=True, env=env,
    )
    assert proc.returncode == 0


def test_scope_guard_fail_closed_on_vault_path_internal_error(tmp_path):
    """Governance fail-closed (Wave D): a FORCED internal error while the target is a vault path
    (contains 'phd-research-os') must BLOCK (exit 2), not silently fail open into the crown jewels."""
    env = _scope_env(tmp_path)
    env["RAT_GUARD_FORCE_FAULT"] = "1"
    payload = {"tool_name": "Write",
               "tool_input": {"file_path": "/some/AI agent database/PhD-Research-OS/02-wiki/x.md"}}
    rc, err = _run_hook("permission-scope-guard.js", payload, env)
    assert rc == 2 and "GOVERNANCE" in err and "CLOSED" in err


def test_scope_guard_fail_closed_on_infra_basename_internal_error(tmp_path):
    """Governance fail-closed: a forced internal error targeting single-writer run-infra
    (basename ledger.jsonl / manifest.yaml) BLOCKs even with forward-slash + mixed-case input."""
    env = _scope_env(tmp_path)
    env["RAT_GUARD_FORCE_FAULT"] = "1"
    for fname in ("ledger.jsonl", "manifest.yaml", "MANIFEST.YAML"):
        payload = {"tool_name": "Write", "tool_input": {"file_path": f"{env['RAT_RUN_ROOT']}/r1/{fname}"}}
        rc, err = _run_hook("permission-scope-guard.js", payload, env)
        assert rc == 2 and "CLOSED" in err, f"{fname} should fail closed, got rc={rc}"


def test_scope_guard_fail_open_on_nongovernance_internal_error(tmp_path):
    """A forced internal error on an ordinary (non-governance) path stays fail-OPEN (exit 0 + warning)
    — a flaky guard must never brick an unrelated session."""
    env = _scope_env(tmp_path)
    env["RAT_GUARD_FORCE_FAULT"] = "1"
    payload = {"tool_name": "Write", "tool_input": {"file_path": f"{env['RAT_RUN_ROOT']}/r1/evidence/DESIGN/n.md"}}
    rc, err = _run_hook("permission-scope-guard.js", payload, env)
    assert rc == 0 and "OPEN" in err


def test_scope_guard_fail_open_on_unparseable_payload(tmp_path):
    """A completely unparseable payload (no recoverable target) stays fail-OPEN: we cannot prove it is a
    governance write, and we must not brick the session on garbage input."""
    import os
    env = dict(os.environ)
    env.update(_scope_env(tmp_path))
    proc = subprocess.run(
        [NODE, str(HOOKS / "permission-scope-guard.js")],
        input="this is not json {{{", text=True, capture_output=True, env=env,
    )
    assert proc.returncode == 0 and "OPEN" in proc.stderr


def test_scope_guard_blocks_vault_via_layout_discovery_without_env(tmp_path):
    """③: a fenced write into the layout-discovered real vault is BLOCKED even with RAT_VAULT_ROOT UNSET.
    The hook walks the two-repo layout to the sibling PhD-Research-OS, so the vault block no longer depends
    on the optional env var being wired."""
    import os
    vault = ROOT / "AI agent database" / "PhD-Research-OS"
    if not (vault / "00-system").is_dir():
        pytest.skip("real PhD-Research-OS vault not present in this checkout")
    env = {k: v for k, v in os.environ.items() if k != "RAT_VAULT_ROOT"}  # the optional env is ABSENT
    env["RAT_RUN_ROOT"] = str(tmp_path / "runs")
    env["RAT_RUN_ID"] = "r1"
    env["RAT_STAGE"] = "DESIGN"
    proc = subprocess.run(
        [NODE, str(HOOKS / "permission-scope-guard.js")],
        input=json.dumps({"tool_name": "Write",
                          "tool_input": {"file_path": str(vault / "02-wiki" / "results" / "forged.md")}}),
        text=True, capture_output=True, env=env,
    )
    assert proc.returncode == 2 and "vault" in proc.stderr


# ---------- artifact-contract-enforcer.js ----------

def _valid_artifact():
    return {
        "artifact_id": "task_frame-x", "artifact_type": "task_frame", "schema_version": "1.0.0",
        "created_by": "orchestrator", "created_at": "2026-06-08T00:00:00Z", "status": "draft",
        "payload": {"task_id": "x", "mode": "m", "entry_stage": "DESIGN",
                    "agent_subset": ["experiment-planner"], "gate_level": "auto",
                    "budget": {"max_agent_hops": 2}},
    }


def test_contract_enforcer_allows_valid_artifact(tmp_path):
    payload = {"tool_name": "Write",
               "tool_input": {"file_path": "x.artifact.json", "content": json.dumps(_valid_artifact())}}
    rc, _ = _run_hook("artifact-contract-enforcer.js", payload, {"RAT_PYTHON": sys.executable})
    assert rc == 0


def test_contract_enforcer_blocks_invalid_artifact(tmp_path):
    bad = _valid_artifact()
    del bad["payload"]["mode"]
    payload = {"tool_name": "Write",
               "tool_input": {"file_path": "x.artifact.json", "content": json.dumps(bad)}}
    rc, err = _run_hook("artifact-contract-enforcer.js", payload, {"RAT_PYTHON": sys.executable})
    assert rc == 2 and "mode" in err


def test_contract_enforcer_ignores_non_artifact_files(tmp_path):
    payload = {"tool_name": "Write", "tool_input": {"file_path": "notes.txt", "content": "not json"}}
    rc, _ = _run_hook("artifact-contract-enforcer.js", payload, {"RAT_PYTHON": sys.executable})
    assert rc == 0


def test_contract_enforcer_fail_closed_when_validator_cannot_run(tmp_path):
    """Governance fail-closed (Wave D): if the validator process cannot run (here: a bogus interpreter
    path), an ARTIFACT write must BLOCK (exit 2) — an unvalidated artifact must never land."""
    payload = {"tool_name": "Write",
               "tool_input": {"file_path": "x.artifact.json", "content": json.dumps(_valid_artifact())}}
    rc, err = _run_hook("artifact-contract-enforcer.js", payload,
                        {"RAT_PYTHON": "/nonexistent/python-binary-for-test"})
    assert rc == 2 and "CLOSED" in err


def test_contract_enforcer_fail_closed_on_internal_error_for_artifact(tmp_path):
    """A forced internal error on a recoverable ARTIFACT write fails CLOSED (exit 2)."""
    payload = {"tool_name": "Write",
               "tool_input": {"file_path": "x.artifact.json", "content": json.dumps(_valid_artifact())}}
    rc, err = _run_hook("artifact-contract-enforcer.js", payload,
                        {"RAT_PYTHON": sys.executable, "RAT_ENFORCER_FORCE_FAULT": "1"})
    assert rc == 2 and "CLOSED" in err


def test_contract_enforcer_fail_open_on_internal_error_for_nonartifact(tmp_path):
    """A forced internal error on a NON-artifact write stays fail-OPEN (exit 0): the hook must never
    brick an unrelated session. (Forcing the fault for a non-artifact path: the early NO-OP fires first,
    so we instead feed an unparseable payload — no recoverable artifact target -> fail open.)"""
    import os
    env = {**os.environ, "RAT_PYTHON": sys.executable}
    proc = subprocess.run(
        [NODE, str(HOOKS / "artifact-contract-enforcer.js")],
        input="not json at all {{{", text=True, capture_output=True, env=env,
    )
    assert proc.returncode == 0 and "OPEN" in proc.stderr
