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


def _compute_layout_vault() -> Optional[str]:
    """Locate System D (the vault) by the two-repo layout, identified by its 00-system marker dir.
    Walks up from this file (machine pkg) to a parent that holds `AI agent database/PhD-Research-OS/`.
    Returns an absolute path, or None in a bare tree (e.g. an isolated test checkout)."""
    here = Path(__file__).resolve()
    for base in here.parents:
        cand = base / "AI agent database" / "PhD-Research-OS"
        if (cand / "00-system").is_dir():
            return str(cand)
    return None


# Computed ONCE (the layout is static); only the env override is re-read per call (cheap, never stale).
_LAYOUT_VAULT = _compute_layout_vault()


def discover_vault_root() -> Optional[str]:
    """The vault's absolute path for the always-on machine-root guard. `RAT_VAULT_ROOT` wins (lets the
    director / a test point elsewhere); otherwise the static two-repo layout. None only when neither
    resolves — and a None vault simply means 'cannot path-locate the vault here', not 'guard disabled'."""
    env = (os.environ.get("RAT_VAULT_ROOT") or "").strip()
    if env:
        return env
    return _LAYOUT_VAULT


def decide(tool: str, target_path, scope: dict) -> Tuple[bool, str]:
    """Return (allowed, reason). scope = {run_root, run_id, stage, vault_root?}."""
    if tool == "Bash":
        return False, "fenced agent: Bash is blocked (cannot prove command safety)"
    if tool not in WRITE_TOOLS:
        return True, "read-only tool, allowed"
    if not target_path:
        return False, "fail-closed: write with no target path"

    # MACHINE-ROOT GUARD (always on, highest priority): a fenced agent may NEVER write System D directly.
    # The vault root is the caller's scope value OR the discovered one (env / two-repo layout), so this
    # fires even when a caller forgot to pass vault_root — closing the gap where operate.commit_stage
    # passed None and the guard went dark. Knowledge enters the vault ONLY through the human
    # /promote-to-vault gate, which does NOT route through this fenced-agent guard.
    effective_vault = scope.get("vault_root") or discover_vault_root()
    if effective_vault and _within(target_path, effective_vault):
        return False, "blocked: cannot write the vault directly (promote via the human gate)"

    run_dir = Path(scope["run_root"]) / scope["run_id"]

    if Path(target_path).name in INFRA_FILES and _within(target_path, run_dir):
        return False, f"blocked: {Path(target_path).name} is single-writer infra (orchestrator only)"

    if _within(target_path, run_dir / "evidence" / scope["stage"]) or _within(target_path, run_dir / "inbox"):
        return True, "within agent's stage scope"

    if _within(target_path, scope["run_root"]):
        return False, "blocked: outside this agent's stage scope (another run/stage)"

    return True, "non-governed path (no-op)"
