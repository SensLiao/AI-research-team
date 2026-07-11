"""Immutable supplemental output versions for targeted panel repair."""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
from pathlib import Path


CONTRACT_VERSION = "supplement-lineage/v1"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _safe(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-") or "worker"


def _root(run_dir: Path, stage: str, cycle: int) -> Path:
    return run_dir / "inbox" / "supplements" / _safe(stage) / f"repair-{cycle:03d}"


def plan_path(run_dir: Path, stage: str, cycle: int) -> Path:
    return _root(run_dir, stage, cycle) / "repair-plan.json"


def _write(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _read(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if value.get("contract_version") != CONTRACT_VERSION:
        raise ValueError(f"supplement lineage contract mismatch at {path}")
    return value


def _relative(run_dir: Path, path: Path) -> str:
    return path.resolve(strict=False).relative_to(run_dir.resolve()).as_posix()


def resolve_effective_output(run_dir: Path, stage: str, logical_path: Path) -> Path:
    """Return the latest hash-linked completed version of a logical worker output."""
    root = run_dir / "inbox" / "supplements" / _safe(stage)
    current = logical_path
    current_hash = sha256(current) if current.is_file() else None
    for plan_file in sorted(root.glob("repair-*/repair-plan.json")) if root.is_dir() else []:
        plan = _read(plan_file)
        for row in plan.get("outputs") or []:
            if row.get("logical_output") != _relative(run_dir, logical_path):
                continue
            physical = run_dir / str(row.get("physical_output") or "")
            if not physical.is_file() or not row.get("output_sha256"):
                continue
            if row.get("supersedes_sha256") != current_hash:
                raise ValueError(
                    f"supplement chain mismatch for {row.get('logical_output')}: "
                    f"expected {current_hash}, got {row.get('supersedes_sha256')}"
                )
            actual = sha256(physical)
            if actual != row.get("output_sha256"):
                raise ValueError(f"supplement hash mismatch at {physical}")
            current, current_hash = physical, actual
    return current


def prepare_plan(
    run_dir: Path,
    stage: str,
    cycle: int,
    nodes: list[dict],
    targets: set[str],
    attempt: dict,
) -> dict:
    """Create an idempotent repair plan without modifying any prior bundle."""
    path = plan_path(run_dir, stage, cycle)
    if path.is_file():
        return _read(path)
    outputs = []
    base_dir = path.parent / "originals"
    for node in nodes:
        if node["label"] not in targets:
            continue
        logical = node["output_path"]
        effective = resolve_effective_output(run_dir, stage, logical)
        effective_hash = sha256(effective) if effective.is_file() else None
        if effective.is_file():
            snapshot = base_dir / f"{_safe(node['label'])}.bundle.json"
            snapshot.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(effective, snapshot)
            snapshot_ref = _relative(run_dir, snapshot)
        else:
            snapshot_ref = None
        physical = path.parent / "corrected" / f"{_safe(node['label'])}.bundle.json"
        outputs.append({
            "worker_id": node["id"],
            "agent": node["label"],
            "logical_output": node["output_rel"],
            "physical_output": _relative(run_dir, physical),
            "supersedes_ref": _relative(run_dir, effective) if effective.is_file() else None,
            "supersedes_sha256": effective_hash,
            "original_snapshot": snapshot_ref,
            "output_sha256": None,
            "changed_paths": [],
            "completed_at": None,
        })
    plan = {
        "contract_version": CONTRACT_VERSION,
        "repair_id": f"{_safe(stage)}-repair-{cycle:03d}",
        "stage": stage,
        "cycle": cycle,
        "verdict": attempt.get("verdict", "NEEDS_SUPPLEMENT"),
        "defects": attempt.get("defects") or [],
        "targets": sorted(targets),
        "outputs": outputs,
    }
    _write(path, plan)
    return plan


def physical_output(run_dir: Path, plan: dict, worker_id: str) -> Path | None:
    for row in plan.get("outputs") or []:
        if row.get("worker_id") == worker_id:
            return run_dir / row["physical_output"]
    return None


def _json_changes(before, after, prefix="$") -> list[str]:
    if type(before) is not type(after):
        return [prefix]
    if isinstance(before, dict):
        out = []
        for key in sorted(set(before) | set(after)):
            if key not in before or key not in after:
                out.append(f"{prefix}.{key}")
            else:
                out.extend(_json_changes(before[key], after[key], f"{prefix}.{key}"))
        return out
    if isinstance(before, list):
        if before == after:
            return []
        return [prefix]
    return [] if before == after else [prefix]


def finalize_output(run_dir: Path, stage: str, cycle: int, worker_id: str, ts: str) -> None:
    """Bind a completed supplement to its base hash and record a compact diff."""
    path = plan_path(run_dir, stage, cycle)
    plan = _read(path)
    changed = False
    for row in plan.get("outputs") or []:
        if row.get("worker_id") != worker_id:
            continue
        physical = run_dir / row["physical_output"]
        if not physical.is_file():
            return
        actual = sha256(physical)
        if row.get("output_sha256") == actual:
            return
        before = None
        snapshot = row.get("original_snapshot")
        if snapshot:
            before = json.loads((run_dir / snapshot).read_text(encoding="utf-8"))
        after = json.loads(physical.read_text(encoding="utf-8"))
        row["output_sha256"] = actual
        row["changed_paths"] = _json_changes(before, after)[:500]
        row["completed_at"] = ts
        changed = True
    if changed:
        _write(path, plan)
