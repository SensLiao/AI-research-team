"""Cross-impl PARITY tests for the vault write-fence.

The fence is enforced by TWO hand-synced implementations:
  - research_agent_teams/tools/scope_guard.py            (Python `decide()`, used by the engine)
  - research_agent_teams/hooks/permission-scope-guard.js (JS hook, used at the Claude-Code tool boundary)

`test_scope_guard.py` and `test_hooks_js.py` each test ONE side. Neither asserts the two reach the SAME
allow/deny VERDICT on the same input. This file closes that gap: for each fence-critical case it computes
the Python allow/deny BIT and the JS allow/deny BIT over IDENTICAL inputs+env, and asserts the BITS are
EQUAL. Silent drift (the audit found the two differ in rule ORDER, `..`-equivalence, and fail-closed-on-
fault) becomes a LOUD test failure here.

DESIGN NOTES (why this is the right minimal fix, not codegen):
  * We assert the VERDICT BIT only, never the reason string — the two legitimately word reasons
    differently (casing, phrasing). A reason-string parity test would be brittle and meaningless.
  * Hermetic by construction: every case uses tmp_path-rooted fake run/vault/projects roots, wired via
    env vars that BOTH sides honor (`RAT_VAULT_ROOT` / `RAT_PROJECTS_ROOT` win over layout discovery on
    both impls; `RAT_RUN_ROOT`/`RAT_RUN_ID`/`RAT_STAGE` feed the JS hook, mirrored into the Python scope
    dict). So a real PhD-Research-OS being present in the checkout cannot leak into a case.
  * The JS hook is invoked exactly the way Claude Code runs it (node + stdin JSON), reusing
    test_hooks_js.py's subprocess pattern; skipped where `node` is unavailable.

The case table (`PARITY_CASES`) is the single source of truth. `expect` of "DENY"/"ALLOW" additionally
pins the absolute verdict both sides must produce; `expect=None` (none used today) would assert
parity-only. If a fence-critical case ever diverges, the failure prints BOTH verdicts so the lead can see
the genuine security finding (not a masked mismatch).
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from research_agent_teams.tools.scope_guard import decide

ROOT = Path(__file__).resolve().parents[2]
HOOKS = ROOT / "research_agent_teams" / "hooks"
HOOK = HOOKS / "permission-scope-guard.js"
NODE = shutil.which("node")

pytestmark = pytest.mark.skipif(NODE is None, reason="node not available")


# --------------------------------------------------------------------------------------------------
# Shared harness: build IDENTICAL (tool, target, env, scope) for both impls from one set of fake roots.
# --------------------------------------------------------------------------------------------------

def _roots(tmp_path: Path) -> dict:
    """Hermetic fake roots — never touch a real PhD-Research-OS. Returns absolute string paths."""
    return {
        "run_root": str(tmp_path / "runs"),
        "run_id": "r1",
        "stage": "DESIGN",
        "vault_root": str(tmp_path / "vault"),
        "projects_root": str(tmp_path / "projects"),
    }


def _python_bit(tool: str, target, roots: dict) -> bool:
    """Python verdict BIT (True=allow). decide() takes scope as a dict; env is irrelevant to it EXCEPT
    via discover_* fallbacks — we pass vault_root/projects_root explicitly so discovery never fires, and
    we also set the matching env (see _js_bit) so both sides see byte-identical roots regardless."""
    scope = {
        "run_root": roots["run_root"],
        "run_id": roots["run_id"],
        "stage": roots["stage"],
        "vault_root": roots["vault_root"],
        "projects_root": roots["projects_root"],
    }
    ok, _reason = decide(tool, target, scope)
    return bool(ok)


def _js_bit(tool: str, target, roots: dict) -> bool:
    """JS verdict BIT (True=allow == exit 0). Invoke the hook the way Claude Code does: node + stdin JSON,
    with the SAME roots as the Python side wired through the env the hook reads. tool_input carries the
    target as file_path (or omitted entirely when target is None, to exercise the no-target path)."""
    env = dict(os.environ)
    env.update({
        "RAT_RUN_ROOT": roots["run_root"],
        "RAT_RUN_ID": roots["run_id"],
        "RAT_STAGE": roots["stage"],
        "RAT_VAULT_ROOT": roots["vault_root"],
        "RAT_PROJECTS_ROOT": roots["projects_root"],
    })
    # Never leak a test-only fault injector into a parity case.
    env.pop("RAT_GUARD_FORCE_FAULT", None)

    tool_input: dict = {}
    if target is not None:
        tool_input["file_path"] = target
    payload = {"tool_name": tool, "tool_input": tool_input}

    proc = subprocess.run(
        [NODE, str(HOOK)],
        input=json.dumps(payload), text=True, capture_output=True, env=env,
    )
    # Contract: exit 0 = ALLOW, exit 2 = BLOCK. Any other nonzero is a hook crash, NOT a verdict — surface
    # it loudly rather than silently treating it as deny (which would mask a broken hook as "parity").
    if proc.returncode not in (0, 2):
        raise AssertionError(
            f"JS hook returned unexpected exit {proc.returncode} (not a 0/2 verdict). stderr:\n{proc.stderr}"
        )
    return proc.returncode == 0


# --------------------------------------------------------------------------------------------------
# Case table — the single source of truth. target is a factory taking the resolved roots dict.
# expect: "DENY" | "ALLOW" pins the absolute verdict both sides must produce.
# --------------------------------------------------------------------------------------------------

def _t_vault_direct(r):      return f"{r['vault_root']}/02-wiki/x.md"
def _t_dotdot_to_vault(r):   return f"{r['run_root']}/r1/evidence/DESIGN/../../../../{Path(r['vault_root']).name}/02-wiki/x.md"
def _t_dotdot_sibling(r):    return f"{r['run_root']}/r1/evidence/DESIGN/../EXECUTE/y.md"
def _t_infra(name):
    def _f(r):               return f"{r['run_root']}/r1/{name}"
    return _f
def _t_project_ws(r):        return f"{r['projects_root']}/proj-a/results/x.json"
def _t_in_stage(r):          return f"{r['run_root']}/r1/evidence/DESIGN/note.md"
def _t_inbox(r):             return f"{r['run_root']}/r1/inbox/cand.md"
def _t_outside(r):           return str(Path(r['run_root']).parent / "elsewhere" / "z.md")


# Each entry: (case_id, tool, target_factory_or_None, expect)
PARITY_CASES = [
    # --- MUST be DENY in BOTH ---------------------------------------------------------------------
    ("a_vault_direct_write",            "Write", _t_vault_direct,            "DENY"),
    ("b_dotdot_traversal_into_vault",   "Write", _t_dotdot_to_vault,        "DENY"),
    ("c_dotdot_traversal_sibling_stage","Write", _t_dotdot_sibling,         "DENY"),
    ("d_infra_manifest",                "Write", _t_infra("manifest.yaml"), "DENY"),
    ("d_infra_ledger",                  "Write", _t_infra("ledger.jsonl"),  "DENY"),
    ("d_infra_lock",                    "Write", _t_infra("LOCK"),          "DENY"),
    ("e_project_workspace_write",       "Write", _t_project_ws,             "DENY"),
    ("f_bash_tool",                     "Bash",  None,                      "DENY"),
    ("g_write_no_target",               "Write", None,                      "DENY"),

    # --- MUST be ALLOW in BOTH (proves it's not "deny everything") --------------------------------
    ("h_in_stage_scope",                "Write", _t_in_stage,               "ALLOW"),
    ("i_inbox_staging",                 "Write", _t_inbox,                  "ALLOW"),
    ("j_readonly_tool_any_path",        "Read",  _t_vault_direct,           "ALLOW"),
    ("k_nongoverned_outside_all_roots", "Write", _t_outside,                "ALLOW"),
]

_CASE_IDS = [c[0] for c in PARITY_CASES]


@pytest.mark.parametrize("case_id,tool,target_factory,expect", PARITY_CASES, ids=_CASE_IDS)
def test_python_js_verdict_parity(tmp_path, case_id, tool, target_factory, expect):
    """The crux: Python `decide()` and the JS hook must return the SAME allow/deny BIT on identical
    fence-critical input. Asserts the BIT (not the reason). On divergence, prints BOTH verdicts so a
    genuine security finding is reported precisely, never masked."""
    roots = _roots(tmp_path)
    target = target_factory(roots) if target_factory is not None else None

    py = _python_bit(tool, target, roots)
    js = _js_bit(tool, target, roots)

    py_word = "ALLOW" if py else "DENY"
    js_word = "ALLOW" if js else "DENY"

    # 1) PARITY — the load-bearing assertion. A mismatch here is a real cross-impl divergence.
    assert py == js, (
        f"[FENCE PARITY DIVERGENCE] case={case_id} tool={tool} target={target!r}: "
        f"Python verdict={py_word} but JS verdict={js_word}. "
        f"These two enforce the same vault write-fence and MUST agree — this is a genuine security "
        f"finding, not a test artifact (env/roots are identical for both sides)."
    )

    # 2) ABSOLUTE verdict — pins the intended direction so a both-wrong-the-same drift is also caught.
    assert py_word == expect, (
        f"case={case_id}: both impls agree on {py_word} but the fence REQUIRES {expect}. "
        f"They drifted together (parity held, intent broke)."
    )


def test_case_table_covers_required_scenarios():
    """Guard the guard: assert the case table still contains every fence-critical scenario the audit
    mandated, so a future edit can't silently drop coverage (e.g. delete the `..`-traversal cases)."""
    required = {
        "a_vault_direct_write", "b_dotdot_traversal_into_vault", "c_dotdot_traversal_sibling_stage",
        "d_infra_manifest", "d_infra_ledger", "d_infra_lock", "e_project_workspace_write",
        "f_bash_tool", "g_write_no_target",
        "h_in_stage_scope", "i_inbox_staging", "j_readonly_tool_any_path",
        "k_nongoverned_outside_all_roots",
    }
    present = set(_CASE_IDS)
    missing = required - present
    assert not missing, f"parity case table lost required fence-critical cases: {sorted(missing)}"
