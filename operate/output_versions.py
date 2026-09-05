"""Immutable supplemental output versions for targeted panel repair."""
from __future__ import annotations

import hashlib
import json
import re
import shutil
from pathlib import Path, PurePosixPath, PureWindowsPath

from ..tools._latex_sandbox import LatexSandboxViolation, atomic_write_bytes
from ..tools.manuscript_security import ManuscriptPathViolation, validate_run_owned_path


CONTRACT_VERSION = "supplement-lineage/v2"
_READABLE_CONTRACT_VERSIONS = {"supplement-lineage/v1", CONTRACT_VERSION}


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
    if value.get("contract_version") not in _READABLE_CONTRACT_VERSIONS:
        raise ValueError(f"supplement lineage contract mismatch at {path}")
    return value


def _validate_plan_file_path(run_dir: Path, path: Path) -> Path:
    """Validate a scheduler-owned plan path before opening it."""
    root = Path(run_dir).absolute()
    target = Path(path).absolute()
    try:
        result = validate_run_owned_path(
            target,
            run_root=root,
            purpose="read",
            owned_output_roots=(root / "inbox" / "supplements",),
        )
    except ManuscriptPathViolation as exc:
        raise ValueError(f"unsafe supplement plan path: {exc}") from exc
    return Path(result["path"])


def _plan_repair_root(
    run_dir: Path,
    plan: dict,
    *,
    plan_file: Path | None = None,
    expected_stage: str | None = None,
    expected_cycle: int | None = None,
) -> Path:
    """Bind the plan's declared identity to one concrete ``repair-NNN`` directory."""
    stage = plan.get("stage")
    cycle = plan.get("cycle")
    if not isinstance(stage, str) or not stage or stage != _safe(stage):
        raise ValueError(f"repair plan has invalid or non-normalized stage {stage!r}")
    if isinstance(cycle, bool) or not isinstance(cycle, int) or cycle < 1:
        raise ValueError(f"repair plan has invalid cycle {cycle!r}")
    if expected_stage is not None and stage != expected_stage:
        raise ValueError(
            f"repair plan stage mismatch: expected {expected_stage!r}, got {stage!r}"
        )
    if expected_cycle is not None and cycle != expected_cycle:
        raise ValueError(
            f"repair plan cycle mismatch: expected {expected_cycle!r}, got {cycle!r}"
        )
    repair_root = _root(Path(run_dir).absolute(), stage, cycle)
    if plan_file is not None:
        actual = _validate_plan_file_path(run_dir, plan_file)
        expected = (repair_root / "repair-plan.json").resolve(strict=False)
        if actual != expected:
            raise ValueError(
                f"repair plan identity does not match its repair-NNN path: {actual}"
            )
    return repair_root


def _read_plan(
    run_dir: Path,
    path: Path,
    *,
    expected_stage: str | None = None,
    expected_cycle: int | None = None,
) -> tuple[dict, Path]:
    safe_path = _validate_plan_file_path(run_dir, path)
    plan = _read(safe_path)
    repair_root = _plan_repair_root(
        run_dir,
        plan,
        plan_file=safe_path,
        expected_stage=expected_stage,
        expected_cycle=expected_cycle,
    )
    return plan, repair_root


def _normalized_run_ref(value: object, field: str) -> str:
    """Accept only canonical POSIX-spelled, run-relative plan references."""
    if not isinstance(value, str) or not value:
        raise ValueError(f"repair plan {field} must be a non-empty run-relative path")
    posix = PurePosixPath(value)
    windows = PureWindowsPath(value)
    if (
        "\\" in value
        or posix.is_absolute()
        or windows.is_absolute()
        or bool(windows.drive)
        or ".." in posix.parts
        or "." in posix.parts
        or posix.as_posix() != value
    ):
        raise ValueError(
            f"repair plan {field} must be a normalized run-relative path: {value!r}"
        )
    return value


def _resolve_plan_ref(
    run_dir: Path,
    value: object,
    field: str,
    *,
    owned_root: Path,
    direct_child: bool = False,
    purpose: str = "read",
) -> Path:
    """Resolve one plan ref through the shared run/link/lane boundary."""
    ref = _normalized_run_ref(value, field)
    root = Path(run_dir).absolute()
    candidate = root / Path(ref)
    try:
        result = validate_run_owned_path(
            candidate,
            run_root=root,
            purpose=purpose,
            owned_output_roots=(owned_root,),
        )
    except ManuscriptPathViolation as exc:
        raise ValueError(f"unsafe repair plan {field}: {exc}") from exc
    resolved = Path(result["path"])
    resolved_lane = owned_root.resolve(strict=False)
    if direct_child and resolved.parent != resolved_lane:
        raise ValueError(
            f"repair plan {field} must be a direct child of {resolved_lane}: {ref!r}"
        )
    return resolved


def _is_prior_corrected_ref(ref: str, stage: str, cycle: int) -> bool:
    parts = PurePosixPath(ref).parts
    if len(parts) != 6 or parts[:3] != ("inbox", "supplements", stage):
        return False
    match = re.fullmatch(r"repair-(\d{3,})", parts[3])
    return bool(
        match
        and parts[4] == "corrected"
        and 1 <= int(match.group(1)) < cycle
    )


def _validated_plan_row_paths(
    run_dir: Path,
    plan: dict,
    repair_root: Path,
    row: dict,
) -> dict[str, Path | None]:
    """Validate every path-bearing row field before any caller uses it."""
    root = Path(run_dir).absolute()
    logical_ref = _normalized_run_ref(row.get("logical_output"), "logical_output")
    logical = _resolve_plan_ref(
        root, logical_ref, "logical_output", owned_root=root, purpose="read"
    )
    physical = _resolve_plan_ref(
        root,
        row.get("physical_output"),
        "physical_output",
        owned_root=repair_root / "corrected",
        direct_child=True,
        purpose="write",
    )

    snapshot_ref = row.get("original_snapshot")
    snapshot = None
    if snapshot_ref is not None:
        snapshot = _resolve_plan_ref(
            root,
            snapshot_ref,
            "original_snapshot",
            owned_root=repair_root / "originals",
            direct_child=True,
            purpose="read",
        )

    supersedes_ref = row.get("supersedes_ref")
    supersedes = None
    if supersedes_ref is not None:
        normalized_supersedes = _normalized_run_ref(supersedes_ref, "supersedes_ref")
        supersedes = _resolve_plan_ref(
            root,
            normalized_supersedes,
            "supersedes_ref",
            owned_root=root,
            purpose="read",
        )
        if normalized_supersedes != logical_ref and not _is_prior_corrected_ref(
            normalized_supersedes, str(plan["stage"]), int(plan["cycle"])
        ):
            raise ValueError(
                "repair plan supersedes_ref must name logical_output or an earlier "
                f"same-stage corrected output: {normalized_supersedes!r}"
            )

    if (snapshot is None) != (supersedes is None):
        raise ValueError(
            "repair plan original_snapshot and supersedes_ref must either both be set or both be null"
        )

    scope = row.get("repair_scope")
    if isinstance(scope, dict) and scope.get("target_artifact_ref") is not None:
        scope_ref = _normalized_run_ref(
            scope.get("target_artifact_ref"), "repair_scope.target_artifact_ref"
        )
        _resolve_plan_ref(
            root,
            scope_ref,
            "repair_scope.target_artifact_ref",
            owned_root=root,
            purpose="read",
        )
        if scope_ref != supersedes_ref:
            raise ValueError(
                "repair scope target_artifact_ref does not match supersedes_ref"
            )

    return {
        "logical_output": logical,
        "physical_output": physical,
        "original_snapshot": snapshot,
        "supersedes_ref": supersedes,
    }


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


def _run_mode(run_dir: Path) -> str:
    try:
        frame = json.loads((run_dir / "task_frame.artifact.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    payload = frame.get("payload") if isinstance(frame, dict) else None
    return str((payload or {}).get("mode") or "")


def _valid_json_pointer(value: object) -> bool:
    """RFC 6901 syntax check (existence is checked against the actual diff later)."""
    if not isinstance(value, str) or not value.startswith("/"):
        return False
    index = 0
    while index < len(value):
        if value[index] == "~":
            if index + 1 >= len(value) or value[index + 1] not in "01":
                return False
            index += 2
            continue
        index += 1
    return True


def _direct_defects(attempt: dict, agent: str) -> list[dict]:
    return [
        row for row in (attempt.get("defects") or [])
        if isinstance(row, dict) and agent in {
            str(value) for value in (row.get("target_agents") or [])
        }
    ]


def _repair_scope(run_dir: Path, node: dict, effective: Path, effective_hash: str | None,
                  attempt: dict) -> dict:
    """Freeze the exact artifact version and the only paths a direct repair may alter.

    Derived refresh/blind-refresh outputs are deliberately regenerated as whole artifacts; the
    fence applies to the directly targeted author. Historical modes did not emit pointer scopes,
    so they remain explicit ``legacy-unrestricted`` rows. The deep-research dossier author is the
    first strict consumer and may never fall back to that compatibility path.
    """
    agent = str(node["label"])
    defects = _direct_defects(attempt, agent)
    raw_pointers = [
        pointer
        for defect in defects
        for pointer in (defect.get("allowed_json_pointers") or [])
    ]
    bad_pointers = [pointer for pointer in raw_pointers if not _valid_json_pointer(pointer)]
    if bad_pointers:
        raise ValueError(
            f"repair scope for {agent} contains invalid RFC 6901 JSON Pointer(s): {bad_pointers!r}"
        )
    allowed = sorted(set(raw_pointers))
    strict_dossier_author = _run_mode(run_dir) == "deep_research" and agent == "landscape-mapper"
    missing_pointer_defects = [
        str(row.get("defect_id") or "DEFECT")
        for row in defects if not row.get("allowed_json_pointers")
    ]
    if strict_dossier_author and missing_pointer_defects:
        raise ValueError(
            "deep_research landscape-mapper targeted repair requires explicit "
            "defects[].allowed_json_pointers; missing on "
            f"{missing_pointer_defects!r}"
        )

    effective_ref = _relative(run_dir, effective) if effective.is_file() else None
    declared_refs = {
        str(row.get("target_artifact_ref"))
        for row in defects if str(row.get("target_artifact_ref") or "").strip()
    }
    declared_hashes = {
        str(row.get("target_artifact_sha256"))
        for row in defects if str(row.get("target_artifact_sha256") or "").strip()
    }
    if len(declared_refs) > 1 or len(declared_hashes) > 1:
        raise ValueError(f"repair defects for {agent} disagree on target artifact identity")
    if declared_refs and effective_ref not in declared_refs:
        raise ValueError(
            f"repair target ref mismatch for {agent}: declared {sorted(declared_refs)!r}, "
            f"current {effective_ref!r}"
        )
    if declared_hashes and effective_hash not in declared_hashes:
        raise ValueError(
            f"repair target hash mismatch for {agent}: declared {sorted(declared_hashes)!r}, "
            f"current {effective_hash!r}"
        )

    refresh_agents = {
        str(value)
        for row in (attempt.get("defects") or []) if isinstance(row, dict)
        for value in ((row.get("refresh_agents") or []) +
                      (row.get("blind_refresh_agents") or []))
    }
    if defects and allowed:
        policy = "json-pointer-fenced"
    elif agent in refresh_agents:
        policy = "derived-refresh-unrestricted"
    else:
        policy = "legacy-unrestricted"
    return {
        "target_artifact_ref": effective_ref,
        "target_artifact_sha256": effective_hash,
        "allowed_json_pointers": allowed if policy == "json-pointer-fenced" else None,
        "scope_policy": policy,
        "source_defect_ids": sorted({
            str(row.get("defect_id") or "DEFECT") for row in defects
        }),
    }


def resolve_effective_output(run_dir: Path, stage: str, logical_path: Path) -> Path:
    """Return the latest completed, hash-intact version of a logical worker output.

    A recorded ``output_sha256`` marks a correction as finalized, not merely present. Recompute the
    physical file's hash every time it is resolved so a post-finalization mutation or deletion cannot
    silently fall back to an older/logical output. This applies equally to readable v1 plans.
    """
    root = run_dir / "inbox" / "supplements" / _safe(stage)
    current = logical_path
    logical_ref = _relative(run_dir, logical_path)
    for plan_file in sorted(root.glob("repair-*/repair-plan.json")) if root.is_dir() else []:
        plan, repair_root = _read_plan(run_dir, plan_file, expected_stage=stage)
        for row in plan.get("outputs") or []:
            paths = _validated_plan_row_paths(run_dir, plan, repair_root, row)
            if row.get("logical_output") != logical_ref:
                continue
            recorded_hash = row.get("output_sha256")
            if not recorded_hash:
                continue
            physical = paths["physical_output"]
            assert physical is not None
            if not physical.is_file():
                raise ValueError(
                    f"finalized repair output is missing for {row.get('worker_id') or 'unknown worker'}: "
                    f"{physical}"
                )
            actual_hash = sha256(physical)
            if actual_hash != recorded_hash:
                raise ValueError(
                    f"finalized repair output hash drift for "
                    f"{row.get('worker_id') or 'unknown worker'}: expected {recorded_hash}, "
                    f"got {actual_hash} at {physical}"
                )
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
        return _read_plan(
            run_dir, path, expected_stage=stage, expected_cycle=cycle,
        )[0]
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
        repair_scope = _repair_scope(run_dir, node, effective, effective_hash, attempt)
        outputs.append({
            "worker_id": node["id"],
            "agent": node["label"],
            "logical_output": node["output_rel"],
            "physical_output": _relative(run_dir, physical),
            "supersedes_ref": _relative(run_dir, effective) if effective.is_file() else None,
            "supersedes_sha256": effective_hash,
            "repair_scope": repair_scope,
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
    repair_root = _plan_repair_root(run_dir, plan)
    for row in plan.get("outputs") or []:
        if row.get("worker_id") == worker_id:
            return _validated_plan_row_paths(
                run_dir, plan, repair_root, row,
            )["physical_output"]
    return None


def _pointer_token(value: object) -> str:
    return str(value).replace("~", "~0").replace("/", "~1")


def _json_changes(before, after, prefix="") -> list[str]:
    """Return leaf-level RFC 6901 pointers changed between two JSON values."""
    if type(before) is not type(after):
        return [prefix]
    if isinstance(before, dict):
        out = []
        for key in sorted(set(before) | set(after)):
            child = f"{prefix}/{_pointer_token(key)}"
            if key not in before or key not in after:
                out.append(child)
            else:
                out.extend(_json_changes(before[key], after[key], child))
        return out
    if isinstance(before, list):
        out = []
        for index in range(max(len(before), len(after))):
            child = f"{prefix}/{index}"
            if index >= len(before) or index >= len(after):
                out.append(child)
            else:
                out.extend(_json_changes(before[index], after[index], child))
        return out
    return [] if before == after else [prefix]


def _pointer_allowed(changed: str, allowed: str) -> bool:
    return changed == allowed or changed.startswith(allowed + "/")


def finalize_output(run_dir: Path, stage: str, cycle: int, worker_id: str, ts: str) -> None:
    """Bind a supplement to its base hash and reject any out-of-scope mutation.

    Failure happens before ``output_sha256``/``completed_at`` are persisted. The existing physical
    correction can therefore be overwritten and finalized again in the *same* repair cycle; the
    bounded-repair attempt counter and cap are neither reset nor incremented by a fence violation.
    """
    path = plan_path(run_dir, stage, cycle)
    _validate_supplement_path(run_dir, path)
    plan, repair_root = _read_plan(
        run_dir, path, expected_stage=stage, expected_cycle=cycle,
    )
    changed = False
    for row in plan.get("outputs") or []:
        if row.get("worker_id") != worker_id:
            continue
        paths = _validated_plan_row_paths(run_dir, plan, repair_root, row)
        physical = paths["physical_output"]
        assert physical is not None
        if not physical.is_file():
            return
        actual = sha256(physical)
        finalized_hash = row.get("output_sha256")
        if finalized_hash:
            if finalized_hash == actual:
                return
            raise ValueError(
                f"finalized repair output hash drift for worker {worker_id}: "
                f"recorded={finalized_hash}, current={actual}"
            )
        before = None
        snapshot_path = paths["original_snapshot"]
        if snapshot_path is not None:
            if sha256(snapshot_path) != row.get("supersedes_sha256"):
                raise ValueError(f"repair base snapshot hash mismatch for worker {worker_id}")
            before = json.loads(snapshot_path.read_text(encoding="utf-8"))
        target_path = paths["supersedes_ref"]
        if target_path is not None and target_path.is_file():
            if sha256(target_path) != row.get("supersedes_sha256"):
                raise ValueError(f"repair target changed after plan freeze for worker {worker_id}")
        after = json.loads(physical.read_text(encoding="utf-8"))
        changed_paths = _json_changes(before, after)
        scope = row.get("repair_scope") or {}
        if not scope and plan.get("contract_version") == "supplement-lineage/v1":
            if _run_mode(run_dir) == "deep_research" and row.get("agent") == "landscape-mapper":
                raise ValueError(
                    "legacy repair plan cannot finalize a deep_research landscape-mapper dossier; "
                    "start a new pointer-fenced repair cycle"
                )
            scope = {"scope_policy": "legacy-unrestricted"}
        elif scope.get("target_artifact_ref") != row.get("supersedes_ref") or \
                scope.get("target_artifact_sha256") != row.get("supersedes_sha256"):
            raise ValueError(f"repair scope target binding mismatch for worker {worker_id}")
        allowed = scope.get("allowed_json_pointers")
        if scope.get("scope_policy") == "json-pointer-fenced":
            unauthorized = [
                pointer for pointer in changed_paths
                if not any(_pointer_allowed(pointer, permit) for permit in (allowed or []))
            ]
            if unauthorized:
                raise ValueError(
                    f"repair changed JSON Pointer(s) outside allowed scope for worker {worker_id}: "
                    f"{unauthorized[:20]!r}"
                )
        row["output_sha256"] = actual
        row["changed_paths"] = changed_paths[:500]
        row["completed_at"] = ts
        changed = True
    if changed:
        _write(run_dir, path, plan)
