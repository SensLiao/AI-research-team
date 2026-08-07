"""Deterministic local-data-availability probe (R3 C6, 2026-08-07).

An idea or plan can DECLARE that a dataset is "available locally" without anyone having
checked that the path actually exists on THIS machine right now. This module is the
checked fact, not the claim: it reads the filesystem, nothing else — no network, no SSH,
no assumption about a remote host. It never changes a feasibility score; it only adds an
honest signal alongside the worker's self-reported one, so "today runnable" can be told
apart from "declared runnable".

Pure and read-only: Path.exists() plus a directory-non-empty check. Nothing here mutates
the filesystem, calls out to a network, or reads the wall clock.
"""
from __future__ import annotations

from pathlib import Path
from typing import Iterable, Optional

VERDICT_LOCAL = "LOCAL"
VERDICT_REMOTE_OR_ABSENT = "REMOTE_OR_ABSENT"
VERDICT_UNDECLARED = "UNDECLARED"


def _exists_and_nonempty(path: Path) -> bool:
    if not path.exists():
        return False
    if path.is_dir():
        return any(path.iterdir())
    return path.is_file()


def probe(declared_paths: Optional[Iterable[str]], *, project_root: str) -> dict:
    """Check declared local data paths against the real filesystem, right now.

    Args:
        declared_paths: Path strings an idea/plan declares as local data locations.
            Relative entries are resolved against ``project_root``; absolute entries are
            checked as-is. Blank entries are ignored.
        project_root: Root directory relative paths are resolved against.

    Returns:
        {"checked": [...], "present": [...], "absent": [...], "verdict": ...} where verdict is:
          UNDECLARED       — no paths were declared; there is nothing to check.
          LOCAL            — every declared path exists (and, for a directory, is non-empty).
          REMOTE_OR_ABSENT — at least one declared path is missing on this machine right now.
    """
    root = Path(project_root)
    checked = [str(p) for p in (declared_paths or []) if str(p or "").strip()]
    if not checked:
        return {"checked": [], "present": [], "absent": [], "verdict": VERDICT_UNDECLARED}

    present: list[str] = []
    absent: list[str] = []
    for raw in checked:
        candidate = Path(raw)
        resolved = candidate if candidate.is_absolute() else root / candidate
        (present if _exists_and_nonempty(resolved) else absent).append(raw)

    verdict = VERDICT_LOCAL if not absent else VERDICT_REMOTE_OR_ABSENT
    return {"checked": checked, "present": present, "absent": absent, "verdict": verdict}
