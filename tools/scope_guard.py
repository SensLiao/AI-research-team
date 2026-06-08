"""Permission-scope decision logic (the enforcement core).

A fenced (work-stage) agent may ONLY:
  - write inside runs/<active_run>/evidence/<active_stage>/   (its own stage scope)
  - write inside runs/<active_run>/inbox/                      (promotion staging)
It may NOT:
  - run Bash (a command string cannot be proven safe -> fail closed)
  - write the run infra files (manifest.yaml / ledger.jsonl / LOCK -> single-writer = orchestrator)
  - write the vault directly (knowledge enters only via the human promotion gate)
  - write another run / another stage
Paths outside every governed tree are a NO-OP (allowed) so the guard never bricks unrelated work.

This Python core is used by the engine + tests; hooks/permission-scope-guard.js mirrors it for the
Claude Code runtime. Keep the two rule sets in sync.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Tuple

WRITE_TOOLS = {"Write", "Edit", "NotebookEdit"}
INFRA_FILES = {"manifest.yaml", "ledger.jsonl", "LOCK"}


def _norm(p) -> str:
    return os.path.normcase(os.path.normpath(os.path.abspath(str(p))))


def _within(child, root) -> bool:
    c, r = _norm(child), _norm(root)
    return c == r or c.startswith(r + os.sep)


def decide(tool: str, target_path, scope: dict) -> Tuple[bool, str]:
    """Return (allowed, reason). scope = {run_root, run_id, stage, vault_root?}."""
    if tool == "Bash":
        return False, "fenced agent: Bash is blocked (cannot prove command safety)"
    if tool not in WRITE_TOOLS:
        return True, "read-only tool, allowed"
    if not target_path:
        return False, "fail-closed: write with no target path"

    run_dir = Path(scope["run_root"]) / scope["run_id"]

    if Path(target_path).name in INFRA_FILES and _within(target_path, run_dir):
        return False, f"blocked: {Path(target_path).name} is single-writer infra (orchestrator only)"

    if _within(target_path, run_dir / "evidence" / scope["stage"]) or _within(target_path, run_dir / "inbox"):
        return True, "within agent's stage scope"

    vault_root = scope.get("vault_root")
    if vault_root and _within(target_path, vault_root):
        return False, "blocked: cannot write the vault directly (promote via the human gate)"

    if _within(target_path, scope["run_root"]):
        return False, "blocked: outside this agent's stage scope (another run/stage)"

    return True, "non-governed path (no-op)"
