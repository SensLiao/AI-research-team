"""Prune old, finished scratch runs from the machine's run-store (L1 housekeeping).

The run-store (`research_agent_teams/runs/`) is ephemeral scratch — a run is a messy workshop bench,
not the crown jewels. Over time finished runs (`done` / `rejected`) accumulate. This tool reaps them
under tight, caller-supplied bounds, with a dry-run default and three independent safety fences so it
can NEVER touch an in-flight run or the read-only vault.

Design invariants (consistent with the rest of the machine):
- caller-supplied timestamp: `ts` is an ISO-8601 string the caller provides (the tool NEVER reads the
  wall clock); a run is eligible only if its manifest `updated_at` is older than `ts - older_than_days`.
- both run layouts: flat `runs/<run_id>/` and project-grouped `runs/<project>/<run_id>/`. A directory is
  a run ONLY if it holds a `manifest.yaml` (mirrors runstore.find_run_dir's identification rule).
- status fence: only manifests whose `status` is in `statuses` (default done/rejected) are candidates;
  IN-FLIGHT statuses (running / awaiting_director / awaiting_resume / interrupted / promoting) are NEVER
  deletable, even if a caller passes them in `statuses` — a double-lock against reaping live work.
- path fences (defence in depth): every resolved delete path must (1) really live under the resolved
  `runs_dir` (realpath prefix check — defeats symlink / `..` escapes) AND (2) not contain the vault marker
  'phd-research-os' anywhere in its path. Either failing => the run is skipped, never deleted.
- dry_run defaults True: returns the would-delete plan and deletes NOTHING until explicitly told to.

Pure-ish: the only I/O is reading manifests + (when dry_run=False) shutil.rmtree. No network, no LLM.
"""
from __future__ import annotations

import os
import shutil
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional, Tuple

import yaml

# Statuses that mean "this run is finished and safe to consider for pruning". Caller-overridable.
_DEFAULT_PRUNABLE = ("done", "rejected")

# Statuses that are NEVER prunable regardless of the caller's `statuses` arg (second safety lock).
_IN_FLIGHT = frozenset({"running", "awaiting_director", "awaiting_resume", "interrupted", "promoting"})

_VAULT_MARKER = "phd-research-os"


def _parse_iso(value) -> datetime:
    """Coerce an ISO-8601 timestamp to a tz-aware UTC datetime.

    Accepts a str (with optional trailing 'Z') OR a datetime/date — PyYAML's safe_load silently parses
    an UNQUOTED ISO timestamp in a hand-edited manifest into a datetime object, so a str-only check would
    otherwise skip such a run. Naive datetimes are assumed UTC so every comparison is tz-aware (no
    naive/aware TypeError)."""
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, date):                      # date (no time) -> midnight
        dt = datetime(value.year, value.month, value.day)
    else:
        s = str(value or "").strip()
        if s.endswith("Z") or s.endswith("z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _iter_run_dirs(runs_dir: Path) -> List[Path]:
    """Every directory that is a run (holds manifest.yaml), across BOTH layouts:
    flat runs/<id>/ and project-grouped runs/<project>/<id>/. Sorted for deterministic output."""
    if not runs_dir.is_dir():
        return []
    found: List[Path] = []
    for child in sorted(runs_dir.iterdir()):
        if not child.is_dir():
            continue
        if (child / "manifest.yaml").is_file():
            found.append(child)                       # flat run
            continue
        # else: maybe a project group dir holding runs/<project>/<id>/
        for grandchild in sorted(child.iterdir()):
            if grandchild.is_dir() and (grandchild / "manifest.yaml").is_file():
                found.append(grandchild)
    return found


def _path_is_safe(run_dir: Path, runs_dir: Path) -> Tuple[bool, str]:
    """Both path fences. Returns (ok, reason_if_not)."""
    rd = os.path.realpath(str(run_dir))
    root = os.path.realpath(str(runs_dir))
    # Fence 1: resolved path must really live under the resolved runs_dir (defeats symlink / .. escape).
    if not (rd == root or rd.startswith(root + os.sep)):
        return False, "resolved path escapes runs_dir"
    # Fence 2: never anywhere near the vault (double-lock; the run-store should never overlap it anyway).
    if _VAULT_MARKER in rd.lower():
        return False, "path contains the vault marker 'phd-research-os'"
    return True, ""


def _run_id_of(run_dir: Path, manifest: dict) -> str:
    """Prefer the manifest's run_id; fall back to the directory name."""
    rid = manifest.get("run_id")
    return rid if isinstance(rid, str) and rid else run_dir.name


def prune_runs(
    runs_dir,
    *,
    ts: str,
    older_than_days: int,
    project: Optional[str] = None,
    statuses: Tuple[str, ...] = _DEFAULT_PRUNABLE,
    dry_run: bool = True,
) -> dict:
    """Reap finished scratch runs older than a cutoff, under tight safety fences.

    Args:
        runs_dir: the machine run-store root (e.g. research_agent_teams/runs).
        ts: caller-supplied ISO-8601 'now' (tool never reads the clock). Trailing 'Z' tolerated.
        older_than_days: a run is eligible only if updated_at < ts - older_than_days.
        project: if set, only consider runs belonging to this project (manifest.project == project).
                 None considers every run (both layouts).
        statuses: which manifest statuses are prunable (default done/rejected). In-flight statuses are
                  NEVER prunable regardless (second lock).
        dry_run: True (default) -> delete nothing, just return the plan. False -> shutil.rmtree the runs.

    Returns:
        {"scanned": int,
         "would_delete" | "deleted": [run_id, ...],   # key name depends on dry_run
         "skipped": [{"run_id", "reason"}, ...]}
        The deleted/would_delete list and skipped list are sorted by run_id for determinism.
    """
    runs_dir = Path(runs_dir)
    cutoff = _parse_iso(ts) - timedelta(days=int(older_than_days))
    prunable_statuses = set(statuses)

    scanned = 0
    targets: List[Tuple[str, Path]] = []     # (run_id, run_dir) that pass EVERY check
    skipped: List[dict] = []

    for run_dir in _iter_run_dirs(runs_dir):
        scanned += 1
        try:
            manifest = yaml.safe_load((run_dir / "manifest.yaml").read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError) as exc:
            skipped.append({"run_id": run_dir.name, "reason": f"unreadable manifest: {exc}"})
            continue

        run_id = _run_id_of(run_dir, manifest)
        status = manifest.get("status")

        # Project filter (when asked).
        if project is not None and manifest.get("project") != project:
            skipped.append({"run_id": run_id, "reason": f"not in project '{project}'"})
            continue

        # In-flight double-lock: never reap a live run even if the caller listed its status.
        if status in _IN_FLIGHT:
            skipped.append({"run_id": run_id, "reason": f"in-flight status '{status}' (never prunable)"})
            continue

        # Status fence.
        if status not in prunable_statuses:
            skipped.append({"run_id": run_id, "reason": f"status '{status}' not in {sorted(prunable_statuses)}"})
            continue

        # Age fence. updated_at may be a str OR a datetime/date (PyYAML coerces unquoted ISO stamps).
        updated_at = manifest.get("updated_at")
        if updated_at is None or (isinstance(updated_at, str) and not updated_at.strip()):
            skipped.append({"run_id": run_id, "reason": "missing/invalid updated_at"})
            continue
        try:
            updated_dt = _parse_iso(updated_at)
        except (ValueError, TypeError) as exc:
            skipped.append({"run_id": run_id, "reason": f"unparseable updated_at: {exc}"})
            continue
        if not (updated_dt < cutoff):
            skipped.append({"run_id": run_id, "reason": f"too recent (updated_at {updated_at} >= cutoff {cutoff.isoformat()})"})
            continue

        # Path fences (defence in depth).
        ok, reason = _path_is_safe(run_dir, runs_dir)
        if not ok:
            skipped.append({"run_id": run_id, "reason": f"safety fence: {reason}"})
            continue

        targets.append((run_id, run_dir))

    targets.sort(key=lambda t: t[0])
    skipped.sort(key=lambda s: s["run_id"])

    acted: List[str] = []
    for run_id, run_dir in targets:
        if not dry_run:
            shutil.rmtree(run_dir)
        acted.append(run_id)

    key = "would_delete" if dry_run else "deleted"
    return {"scanned": scanned, key: acted, "skipped": skipped}


def main(argv=None) -> int:
    import argparse
    import json

    p = argparse.ArgumentParser(
        prog="python -m research_agent_teams.tools.prune_runs",
        description="Prune old, FINISHED scratch runs (done/rejected) from the run-store. Dry-run by "
                    "default; a real delete requires --confirm DELETE. Never touches in-flight runs or "
                    "the read-only vault (three safety fences). The vault (promoted knowledge) is NEVER "
                    "in scope.")
    p.add_argument("--runs-dir", default="research_agent_teams/runs")
    p.add_argument("--ts", required=True, help="caller-supplied ISO-8601 'now' (e.g. 2026-06-12T00:00:00Z)")
    p.add_argument("--older-than-days", type=int, required=True)
    p.add_argument("--project", default=None, help="only this project's runs (default: all)")
    p.add_argument("--status", action="append", default=None,
                   help="prunable status (repeatable; default: done, rejected)")
    p.add_argument("--confirm", default=None,
                   help="must be the exact word DELETE to actually delete; otherwise dry-run only")
    a = p.parse_args(argv)

    statuses = tuple(a.status) if a.status else _DEFAULT_PRUNABLE
    do_delete = a.confirm == "DELETE"
    result = prune_runs(
        a.runs_dir, ts=a.ts, older_than_days=a.older_than_days,
        project=a.project, statuses=statuses, dry_run=not do_delete,
    )
    if not do_delete:
        result["note"] = "DRY-RUN (nothing deleted). Re-run with --confirm DELETE to delete the listed runs."
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
