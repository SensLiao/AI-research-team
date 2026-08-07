"""Immutable supplemental output versions for targeted panel repair."""
from __future__ import annotations

import hashlib
import json
import re
import shutil
from pathlib import Path

from ..tools._latex_sandbox import LatexSandboxViolation, atomic_write_bytes
from ..tools.manuscript_security import ManuscriptPathViolation, validate_run_owned_path


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


def _validate_supplement_path(run_dir: Path, path: Path) -> Path:
    root = Path(run_dir).absolute()
    target = Path(path).absolute()
    try:
        validate_run_owned_path(
            target,
            run_root=root,
            purpose="write",
            owned_output_roots=(root / "inbox" / "supplements",),
        )
    except ManuscriptPathViolation as exc:
        raise ValueError(f"unsafe supplement plan path: {exc}") from exc
    return target


def _write(run_dir: Path, path: Path, value: dict) -> None:
    target = _validate_supplement_path(run_dir, path)
    try:
        atomic_write_bytes(
            target,
            (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
        )
    except LatexSandboxViolation as exc:
        raise ValueError(f"unsafe supplement plan path: {exc}") from exc


def _read(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if value.get("contract_version") != CONTRACT_VERSION:
        raise ValueError(f"supplement lineage contract mismatch at {path}")
    return value


def _relative(run_dir: Path, path: Path) -> str:
    return path.resolve(strict=False).relative_to(run_dir.resolve()).as_posix()


def _version_stem(node: dict, duplicate_labels: set[str]) -> str:
    """Return the stable filename stem for one repair output.

    Historical plans used the canonical agent label as the filename.  Keep
    that spelling when the label is unique.  A panel may, however, schedule
    the same canonical role more than once with different logical outputs. In
    that case the label alone aliases both supplements, so bind the path to a
    stable worker/output discriminator as well.
    """
    label = str(node["label"])
    stem = _safe(label)
    if label not in duplicate_labels:
        return stem
    discriminator = hashlib.sha256(
        (str(node["id"]) + "\0" + str(node["output_rel"])).encode("utf-8")
    ).hexdigest()
    return f"{stem}--{discriminator}"


def resolve_effective_output(run_dir: Path, stage: str, logical_path: Path) -> Path:
    """Return the latest completed version of a logical worker output.

    2026-08-07 de-governance: no longer chain/hash-verified — "latest" is simply the physical
    output of the highest repair-NNN directory (sorted() below) whose plan row is marked
    completed (has a recorded output_sha256; the field is still written, just no longer compared).
    """
    root = run_dir / "inbox" / "supplements" / _safe(stage)
    current = logical_path
    for plan_file in sorted(root.glob("repair-*/repair-plan.json")) if root.is_dir() else []:
        plan = _read(plan_file)
        for row in plan.get("outputs") or []:
            if row.get("logical_output") != _relative(run_dir, logical_path):
                continue
            physical = run_dir / str(row.get("physical_output") or "")
            if not physical.is_file() or not row.get("output_sha256"):
                continue
            current = physical
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
    _validate_supplement_path(run_dir, path)
    if path.is_file():
        return _read(path)
    outputs = []
    base_dir = path.parent / "originals"
    label_counts: dict[str, int] = {}
    for node in nodes:
        label = str(node["label"])
        label_counts[label] = label_counts.get(label, 0) + 1
    duplicate_labels = {label for label, count in label_counts.items() if count > 1}
    for node in nodes:
        if node["label"] not in targets:
            continue
        version_stem = _version_stem(node, duplicate_labels)
        logical = node["output_path"]
        effective = resolve_effective_output(run_dir, stage, logical)
        effective_hash = sha256(effective) if effective.is_file() else None
        if effective.is_file():
            snapshot = base_dir / f"{version_stem}.bundle.json"
            _validate_supplement_path(run_dir, snapshot)
            snapshot.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(effective, snapshot)
            snapshot_ref = _relative(run_dir, snapshot)
        else:
            snapshot_ref = None
        physical = path.parent / "corrected" / f"{version_stem}.bundle.json"
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
    _write(run_dir, path, plan)
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
    _validate_supplement_path(run_dir, path)
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
        _write(run_dir, path, plan)
