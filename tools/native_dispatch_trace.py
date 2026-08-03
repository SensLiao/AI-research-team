"""Fail-closed native collaboration dispatch and blind-review contracts.

This module records local orchestration evidence only.  It never calls a model,
network, provider, or server, and it never estimates provider usage or cost.
Stage-B provider receipts and sealing remain separate, stricter contracts.
"""
from __future__ import annotations

import hashlib
import json
import re
import statistics
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from jsonschema import Draft202012Validator


_PKG_ROOT = Path(__file__).resolve().parent.parent
WORK_ORDER_SCHEMA = _PKG_ROOT / "schemas" / "native_dispatch_work_order.schema.json"
COMPLETION_SCHEMA = _PKG_ROOT / "schemas" / "native_dispatch_completion.schema.json"
JUDGE_SCHEMA = _PKG_ROOT / "schemas" / "native_content_quality_judge.schema.json"
PRECOMMIT_SCHEMA = _PKG_ROOT / "schemas" / "native_review_precommit.schema.json"
TARGETED_RE_REVIEW_SCHEMA = _PKG_ROOT / "schemas" / "native_targeted_re_review.schema.json"

WORK_ORDER_CONTRACT = "native-dispatch-work-order/v1"
COMPLETION_CONTRACT = "native-dispatch-completion/v1"
BLIND_PACKET_CONTRACT = "native-blind-packet/v1"
MAPPING_COMMITMENT_CONTRACT = "native-blind-mapping-commitment/v1"
MAPPING_REVEAL_CONTRACT = "native-blind-mapping-reveal/v1"
JUDGE_CONTRACT = "native-content-quality-judge/v1"
PRECOMMIT_CONTRACT = "native-review-precommit/v1"
TARGETED_RE_REVIEW_CONTRACT = "native-targeted-re-review/v1"
JUDGE_ROLES = ("domain_mechanism", "methods_statistics", "evidence_integrity")
SCORE_KEYS = tuple(f"Q{i}" for i in range(1, 9))
CORE_SCORE_KEYS = ("Q1", "Q3", "Q4", "Q6")
APPLICABLE = "APPLICABLE"
RESULT_ROLE_NO_EXECUTOR = "RESULT_ROLE_NO_EXECUTOR"
COMPLETED = "COMPLETED"
NOT_APPLICABLE_NO_EXECUTOR = "NOT_APPLICABLE_NO_EXECUTOR"
UNOBSERVED_USAGE = {"status": "UNOBSERVED"}


class NativeDispatchTraceError(ValueError):
    """Typed fail-closed stop for an invalid native dispatch trace."""


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def sha256_value(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_json(path: str | Path) -> dict[str, Any]:
    candidate = Path(path)
    if not candidate.is_file():
        raise NativeDispatchTraceError(f"required JSON file is missing: {candidate}")
    try:
        value = json.loads(candidate.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise NativeDispatchTraceError(f"cannot parse strict UTF-8 JSON: {candidate}") from exc
    if not isinstance(value, dict):
        raise NativeDispatchTraceError(f"JSON root must be an object: {candidate}")
    return value


def _record(value: Mapping[str, Any] | str | Path) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    return _read_json(value)


def _validate_schema(value: Mapping[str, Any], schema_path: Path, *, label: str) -> None:
    schema = _read_json(schema_path)
    Draft202012Validator.check_schema(schema)
    errors = sorted(
        Draft202012Validator(schema).iter_errors(value),
        key=lambda error: list(error.absolute_path),
    )
    if errors:
        details = "; ".join(
            f"/{'/'.join(str(part) for part in error.absolute_path)}: {error.message}"
            for error in errors[:12]
        )
        raise NativeDispatchTraceError(f"{label} schema validation failed: {details}")


def _parse_time(value: Any, *, label: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise NativeDispatchTraceError(f"{label} must be an ISO-8601 date-time")
    rendered = value.strip()
    if rendered.endswith("Z"):
        rendered = rendered[:-1] + "+00:00"
    # ISO-8601 permits arbitrary fractional-second precision.  Windows/.NET
    # round-trip timestamps commonly carry seven digits while Python's
    # datetime stores microseconds, so normalize only the excess precision.
    rendered = re.sub(
        r"(\.\d{6})\d+(?=[+-]\d{2}:\d{2}$)",
        r"\1",
        rendered,
    )
    try:
        parsed = datetime.fromisoformat(rendered)
    except ValueError as exc:
        raise NativeDispatchTraceError(f"{label} must be an ISO-8601 date-time") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise NativeDispatchTraceError(f"{label} must include a UTC offset")
    return parsed.astimezone(timezone.utc)


def _resolve_beneath(root: str | Path, relative: Any, *, label: str) -> Path:
    base = Path(root).resolve()
    raw = str(relative or "")
    rel = Path(raw)
    if not raw or rel.is_absolute() or rel.drive:
        raise NativeDispatchTraceError(f"{label} must be a safe relative path")
    candidate = (base / rel).resolve()
    try:
        candidate.relative_to(base)
    except ValueError as exc:
        raise NativeDispatchTraceError(f"{label} escapes the run root") from exc
    return candidate


def _normalize_dependencies(
    dependencies: Iterable[Mapping[str, Any]] | None,
) -> list[dict[str, Any]]:
    rows = [dict(item) for item in (dependencies or [])]
    ids = [str(item.get("work_order_id") or "") for item in rows]
    if len(ids) != len(set(ids)):
        raise NativeDispatchTraceError("dependency work_order_id values must be unique")
    return rows


def validate_work_order(
    run_root: str | Path,
    work_order: Mapping[str, Any] | str | Path,
    *,
    require_output_absent: bool = False,
) -> dict[str, Any]:
    order = _record(work_order)
    _validate_schema(order, WORK_ORDER_SCHEMA, label="native dispatch work order")

    authorized_at = _parse_time(order["authorized_at"], label="authorized_at")
    recorded_at = _parse_time(order["recorded_at"], label="recorded_at")
    checked_at = _parse_time(
        order["output_precondition"]["checked_at"],
        label="output_precondition.checked_at",
    )
    if recorded_at < authorized_at:
        raise NativeDispatchTraceError("work order recorded_at precedes authorization")
    if checked_at != recorded_at:
        raise NativeDispatchTraceError(
            "output precondition must be checked when the work order is recorded"
        )

    input_path = _resolve_beneath(
        run_root, order["input_packet_path"], label="input packet path"
    )
    authorization_path = _resolve_beneath(
        run_root, order["authorization_path"], label="authorization path"
    )
    if not input_path.is_file():
        raise NativeDispatchTraceError("work order input packet is missing")
    if not authorization_path.is_file():
        raise NativeDispatchTraceError("work order authorization evidence is missing")
    if sha256_file(input_path) != order["input_packet_sha256"]:
        raise NativeDispatchTraceError("work order input packet SHA-256 mismatch")
    if sha256_file(authorization_path) != order["authorization_sha256"]:
        raise NativeDispatchTraceError("work order authorization SHA-256 mismatch")

    dependencies = _normalize_dependencies(order["dependencies"])
    if any(item["work_order_id"] == order["work_order_id"] for item in dependencies):
        raise NativeDispatchTraceError("work order cannot depend on itself")

    output_rel = order["expected_output_path"]
    if output_rel is not None:
        output_path = _resolve_beneath(run_root, output_rel, label="expected output path")
        if require_output_absent and output_path.exists():
            raise NativeDispatchTraceError(
                "preexisting output cannot satisfy a new work order"
            )
    return order


def create_work_order(
    run_root: str | Path,
    *,
    run_id: str,
    work_order_id: str,
    stage: str,
    role: str,
    applicability: str,
    agent_id: str | None,
    canonical_agent_task_name: str | None,
    input_packet_path: str,
    authorization_path: str,
    nonce: str,
    dependencies: Iterable[Mapping[str, Any]] | None,
    expected_output_path: str | None,
    authorized_at: str,
    recorded_at: str,
) -> dict[str, Any]:
    root = Path(run_root).resolve()
    input_path = _resolve_beneath(root, input_packet_path, label="input packet path")
    authorization = _resolve_beneath(
        root, authorization_path, label="authorization path"
    )
    if not input_path.is_file():
        raise NativeDispatchTraceError("input packet must exist before dispatch")
    if not authorization.is_file():
        raise NativeDispatchTraceError("authorization evidence must exist before dispatch")
    if applicability == APPLICABLE:
        if not expected_output_path:
            raise NativeDispatchTraceError("applicable work order requires an output path")
        output = _resolve_beneath(root, expected_output_path, label="expected output path")
        if output.exists():
            raise NativeDispatchTraceError(
                "preexisting output cannot satisfy a new work order"
            )
    elif applicability == RESULT_ROLE_NO_EXECUTOR:
        if expected_output_path is not None or agent_id is not None or canonical_agent_task_name is not None:
            raise NativeDispatchTraceError(
                "no-executor result role must not fabricate agent ownership or output"
            )
    else:
        raise NativeDispatchTraceError(f"unknown applicability: {applicability}")

    order = {
        "schema_version": WORK_ORDER_CONTRACT,
        "run_id": run_id,
        "work_order_id": work_order_id,
        "stage": stage,
        "role": role,
        "applicability": applicability,
        "agent_id": agent_id,
        "canonical_agent_task_name": canonical_agent_task_name,
        "input_packet_path": input_packet_path,
        "input_packet_sha256": sha256_file(input_path),
        "authorization_path": authorization_path,
        "authorization_sha256": sha256_file(authorization),
        "nonce": nonce,
        "dependencies": _normalize_dependencies(dependencies),
        "expected_output_path": expected_output_path,
        "authorized_at": authorized_at,
        "recorded_at": recorded_at,
        "output_precondition": {
            "exists_at_authorization": False,
            "checked_at": recorded_at,
        },
        "runtime_usage": dict(UNOBSERVED_USAGE),
    }
    return validate_work_order(root, order, require_output_absent=True)


def validate_completion(
    run_root: str | Path,
    completion: Mapping[str, Any] | str | Path,
    *,
    work_order: Mapping[str, Any] | str | Path,
) -> dict[str, Any]:
    order = validate_work_order(run_root, work_order)
    record = _record(completion)
    _validate_schema(record, COMPLETION_SCHEMA, label="native dispatch completion")

    echoed_fields = (
        "run_id",
        "work_order_id",
        "stage",
        "role",
        "applicability",
        "agent_id",
        "canonical_agent_task_name",
        "input_packet_sha256",
        "authorization_sha256",
    )
    for field in echoed_fields:
        if record[field] != order[field]:
            raise NativeDispatchTraceError(f"completion does not echo work order {field}")
    if record["work_order_sha256"] != sha256_value(order):
        raise NativeDispatchTraceError("completion work_order_sha256 mismatch")
    if record["nonce_echo"] != order["nonce"]:
        raise NativeDispatchTraceError("completion nonce echo mismatch")
    if _canonical_bytes(record["dependencies"]) != _canonical_bytes(order["dependencies"]):
        raise NativeDispatchTraceError("completion dependency echo mismatch")

    authorized_at = _parse_time(order["authorized_at"], label="authorized_at")
    order_recorded_at = _parse_time(order["recorded_at"], label="work-order recorded_at")
    started_at = _parse_time(record["started_at"], label="started_at")
    completed_at = _parse_time(record["completed_at"], label="completed_at")
    recorded_at = _parse_time(record["recorded_at"], label="completion recorded_at")
    if started_at < authorized_at or started_at < order_recorded_at:
        raise NativeDispatchTraceError("completion started before authorization/work-order record")
    if completed_at < started_at:
        raise NativeDispatchTraceError("completion completed_at precedes started_at")
    if recorded_at < completed_at:
        raise NativeDispatchTraceError("completion record precedes completed_at")

    if record["completion_state"] == COMPLETED:
        expected = order["expected_output_path"]
        output = record["output"]
        if expected is None or output["path"] != expected:
            raise NativeDispatchTraceError("completion output path differs from work order")
        path = _resolve_beneath(run_root, expected, label="completion output path")
        if not path.is_file():
            raise NativeDispatchTraceError("completion output is missing")
        stat = path.stat()
        if sha256_file(path) != output["sha256"]:
            raise NativeDispatchTraceError("completion output SHA-256 mismatch")
        if stat.st_size != output["size_bytes"] or stat.st_mtime_ns != output["mtime_ns"]:
            raise NativeDispatchTraceError("completion output metadata mismatch")
        mtime = datetime.fromtimestamp(stat.st_mtime_ns / 1_000_000_000, tz=timezone.utc)
        if mtime < authorized_at:
            raise NativeDispatchTraceError(
                "fixture/preexisting output predates this authorization"
            )
        if mtime > completed_at:
            raise NativeDispatchTraceError("output was modified after claimed completion")
    elif record["completion_state"] == NOT_APPLICABLE_NO_EXECUTOR:
        if order["applicability"] != RESULT_ROLE_NO_EXECUTOR:
            raise NativeDispatchTraceError("only a typed result role may use no-executor N/A")
    else:
        raise NativeDispatchTraceError("unknown completion state")
    return record


def create_completion(
    run_root: str | Path,
    *,
    work_order: Mapping[str, Any] | str | Path,
    nonce_echo: str,
    started_at: str,
    completed_at: str,
    recorded_at: str,
) -> dict[str, Any]:
    root = Path(run_root).resolve()
    order = validate_work_order(root, work_order)
    applicable = order["applicability"] == APPLICABLE
    if applicable:
        output_path = _resolve_beneath(
            root, order["expected_output_path"], label="completion output path"
        )
        if not output_path.is_file():
            raise NativeDispatchTraceError("applicable completion requires a real output file")
        stat = output_path.stat()
        output: dict[str, Any] | None = {
            "path": order["expected_output_path"],
            "sha256": sha256_file(output_path),
            "size_bytes": stat.st_size,
            "mtime_ns": stat.st_mtime_ns,
        }
        guard: dict[str, Any] | None = {
            "absent_at_authorization": True,
            "mtime_not_before_authorization": True,
            "mtime_not_after_completion": True,
        }
        completion_state = COMPLETED
        n_a_reason = None
    else:
        output = None
        guard = None
        completion_state = NOT_APPLICABLE_NO_EXECUTOR
        n_a_reason = "NO_EXECUTOR_RECEIPT"

    completion = {
        "schema_version": COMPLETION_CONTRACT,
        "run_id": order["run_id"],
        "work_order_id": order["work_order_id"],
        "work_order_sha256": sha256_value(order),
        "stage": order["stage"],
        "role": order["role"],
        "applicability": order["applicability"],
        "completion_state": completion_state,
        "agent_id": order["agent_id"],
        "canonical_agent_task_name": order["canonical_agent_task_name"],
        "input_packet_sha256": order["input_packet_sha256"],
        "authorization_sha256": order["authorization_sha256"],
        "nonce_echo": nonce_echo,
        "dependencies": [dict(item) for item in order["dependencies"]],
        "started_at": started_at,
        "completed_at": completed_at,
        "recorded_at": recorded_at,
        "output": output,
        "preexisting_output_guard": guard,
        "n_a_reason": n_a_reason,
        "runtime_usage": dict(UNOBSERVED_USAGE),
    }
    return validate_completion(root, completion, work_order=order)


def _assert_acyclic(
    orders_by_id: Mapping[str, Mapping[str, Any]],
) -> None:
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(work_order_id: str) -> None:
        if work_order_id in visiting:
            raise NativeDispatchTraceError("dispatch dependency graph contains a cycle")
        if work_order_id in visited:
            return
        visiting.add(work_order_id)
        for dependency in orders_by_id[work_order_id]["dependencies"]:
            dep_id = dependency["work_order_id"]
            if dep_id not in orders_by_id:
                raise NativeDispatchTraceError(
                    f"dependency {dep_id} is outside the dispatch trace"
                )
            visit(dep_id)
        visiting.remove(work_order_id)
        visited.add(work_order_id)

    for identifier in orders_by_id:
        visit(identifier)


def validate_dispatch_trace(
    run_root: str | Path,
    *,
    work_orders: Iterable[Mapping[str, Any] | str | Path],
    completions: Iterable[Mapping[str, Any] | str | Path],
    expected_roles: Mapping[str, str],
    result_roles: Iterable[str] = (),
    executor_receipt_present: bool,
    external_work_orders: Iterable[Mapping[str, Any] | str | Path] = (),
    external_completions: Iterable[Mapping[str, Any] | str | Path] = (),
) -> dict[str, Any]:
    """Validate one dispatch phase plus receipt-bound predecessor phases.

    Agent uniqueness is enforced inside the current phase.  A reviewer may own
    a precommit in a prior phase and its later blind review, provided the prior
    work order and completion are supplied as immutable external dependencies.
    """

    expected = dict(expected_roles)
    if not expected or any(
        value not in {APPLICABLE, RESULT_ROLE_NO_EXECUTOR}
        for value in expected.values()
    ):
        raise NativeDispatchTraceError("expected_roles must declare each role's applicability")
    result_role_set = set(result_roles)
    if not result_role_set.issubset(expected):
        raise NativeDispatchTraceError("result_roles must be present in expected_roles")
    for role in result_role_set:
        state = expected[role]
        if executor_receipt_present and state != APPLICABLE:
            raise NativeDispatchTraceError(
                f"result role {role} cannot be N/A when an executor receipt exists"
            )
        if not executor_receipt_present and state != RESULT_ROLE_NO_EXECUTOR:
            raise NativeDispatchTraceError(
                f"no-executor result role {role} must be typed N/A"
            )
    for role, state in expected.items():
        if state == RESULT_ROLE_NO_EXECUTOR and role not in result_role_set:
            raise NativeDispatchTraceError(
                f"non-result role {role} cannot use no-executor N/A"
            )

    orders = [validate_work_order(run_root, item) for item in work_orders]
    order_ids = [item["work_order_id"] for item in orders]
    order_roles = [item["role"] for item in orders]
    if len(order_ids) != len(set(order_ids)):
        raise NativeDispatchTraceError("work_order_id values must be unique")
    if len(order_roles) != len(set(order_roles)):
        raise NativeDispatchTraceError("each expected role must own exactly one work order")
    actual_roles = set(order_roles)
    if actual_roles != set(expected):
        missing = sorted(set(expected) - actual_roles)
        extra = sorted(actual_roles - set(expected))
        raise NativeDispatchTraceError(
            f"dispatch role coverage mismatch; missing={missing}, extra={extra}"
        )
    orders_by_id = {item["work_order_id"]: item for item in orders}
    run_ids = {item["run_id"] for item in orders}
    if len(run_ids) != 1:
        raise NativeDispatchTraceError("dispatch trace cannot mix run_id values")
    for item in orders:
        if item["applicability"] != expected[item["role"]]:
            raise NativeDispatchTraceError(
                f"role {item['role']} has the wrong applicability"
            )

    raw_completions = [_record(item) for item in completions]
    completion_ids = [item.get("work_order_id") for item in raw_completions]
    if len(completion_ids) != len(set(completion_ids)):
        raise NativeDispatchTraceError("completion work_order_id values must be unique")
    if set(completion_ids) != set(order_ids):
        missing = sorted(set(order_ids) - set(completion_ids))
        extra = sorted(set(completion_ids) - set(order_ids))
        raise NativeDispatchTraceError(
            f"completion coverage mismatch; missing={missing}, extra={extra}"
        )
    completions_by_id = {
        item["work_order_id"]: validate_completion(
            run_root, item, work_order=orders_by_id[item["work_order_id"]]
        )
        for item in raw_completions
    }

    predecessor_orders = [
        validate_work_order(run_root, item) for item in external_work_orders
    ]
    predecessor_ids = [item["work_order_id"] for item in predecessor_orders]
    if len(predecessor_ids) != len(set(predecessor_ids)):
        raise NativeDispatchTraceError("external work_order_id values must be unique")
    if set(predecessor_ids) & set(order_ids):
        raise NativeDispatchTraceError("external and current work orders overlap")
    predecessor_orders_by_id = {
        item["work_order_id"]: item for item in predecessor_orders
    }
    raw_external_completions = [_record(item) for item in external_completions]
    external_completion_ids = [
        item.get("work_order_id") for item in raw_external_completions
    ]
    if set(external_completion_ids) != set(predecessor_ids):
        raise NativeDispatchTraceError("external completion coverage mismatch")
    predecessor_completions_by_id = {
        item["work_order_id"]: validate_completion(
            run_root,
            item,
            work_order=predecessor_orders_by_id[item["work_order_id"]],
        )
        for item in raw_external_completions
    }
    all_orders_by_id = {**predecessor_orders_by_id, **orders_by_id}
    all_completions_by_id = {
        **predecessor_completions_by_id,
        **completions_by_id,
    }
    if {item["run_id"] for item in all_orders_by_id.values()} != run_ids:
        raise NativeDispatchTraceError("external dependencies must belong to the same run_id")

    applicable_orders = [item for item in orders if item["applicability"] == APPLICABLE]
    agent_ids = [item["agent_id"] for item in applicable_orders]
    task_names = [item["canonical_agent_task_name"] for item in applicable_orders]
    if len(agent_ids) != len(set(agent_ids)):
        raise NativeDispatchTraceError("applicable roles require unique agent ownership")
    if len(task_names) != len(set(task_names)):
        raise NativeDispatchTraceError(
            "applicable roles require unique canonical agent task names"
        )
    output_paths = [item["expected_output_path"] for item in applicable_orders]
    if len(output_paths) != len(set(output_paths)):
        raise NativeDispatchTraceError("applicable roles require unique output paths")

    _assert_acyclic(all_orders_by_id)
    for order in orders:
        child = completions_by_id[order["work_order_id"]]
        child_authorized = _parse_time(order["authorized_at"], label="child authorized_at")
        child_started = _parse_time(child["started_at"], label="child started_at")
        for dependency in order["dependencies"]:
            dep_id = dependency["work_order_id"]
            predecessor_order = all_orders_by_id.get(dep_id)
            if predecessor_order is None:
                raise NativeDispatchTraceError(
                    f"dependency {dep_id} is outside the dispatch trace"
                )
            predecessor = all_completions_by_id[dep_id]
            if dependency["role"] != predecessor_order["role"]:
                raise NativeDispatchTraceError("dependency role binding mismatch")
            if predecessor["completion_state"] != COMPLETED or predecessor["output"] is None:
                raise NativeDispatchTraceError(
                    "a typed N/A record cannot satisfy a data dependency"
                )
            if dependency["output_sha256"] != predecessor["output"]["sha256"]:
                raise NativeDispatchTraceError("dependency output SHA-256 mismatch")
            predecessor_completed = _parse_time(
                predecessor["completed_at"], label="predecessor completed_at"
            )
            if predecessor_completed > child_authorized:
                raise NativeDispatchTraceError(
                    "dependent role was authorized before its predecessor completed"
                )
            if predecessor_completed > child_started:
                raise NativeDispatchTraceError(
                    "dependent role started before its predecessor completed"
                )

    return {
        "schema_version": "native-dispatch-trace-validation/v1",
        "status": "PASS",
        "run_id": orders[0]["run_id"],
        "expected_role_count": len(expected),
        "applicable_role_count": len(applicable_orders),
        "typed_n_a_role_count": len(orders) - len(applicable_orders),
        "external_dependency_role_count": len(predecessor_orders),
        "roles": sorted(expected),
        "agent_ids": sorted(agent_ids),
        "canonical_agent_task_names": sorted(task_names),
        "runtime_usage": dict(UNOBSERVED_USAGE),
        "claim_boundary": (
            "This validates local collaboration dispatch records, dependency closure and artifact "
            "bindings only. It does not attest provider identity, tokens, cost, model, or service tier."
        ),
    }


_BLIND_PACKET_KEYS = {
    "schema_version",
    "evaluation_id",
    "project_id",
    "case_id",
    "request",
    "source_packet_sha256",
    "candidates",
}
_BLIND_CANDIDATE_KEYS = {"content", "sha256"}


def validate_blind_packet(packet: Mapping[str, Any]) -> dict[str, Any]:
    value = dict(packet)
    if set(value) != _BLIND_PACKET_KEYS:
        forbidden = sorted(set(value) - _BLIND_PACKET_KEYS)
        missing = sorted(_BLIND_PACKET_KEYS - set(value))
        raise NativeDispatchTraceError(
            f"blind packet field contract mismatch; forbidden={forbidden}, missing={missing}"
        )
    if value.get("schema_version") != BLIND_PACKET_CONTRACT:
        raise NativeDispatchTraceError("blind packet schema_version mismatch")
    for key in ("evaluation_id", "project_id", "case_id", "request"):
        if not isinstance(value.get(key), str) or not value[key].strip():
            raise NativeDispatchTraceError(f"blind packet {key} must be non-empty")
    source_hash = value.get("source_packet_sha256")
    if (
        not isinstance(source_hash, str)
        or len(source_hash) != 64
        or any(character not in "0123456789abcdef" for character in source_hash)
    ):
        raise NativeDispatchTraceError("blind packet source_packet_sha256 is invalid")
    candidates = value.get("candidates")
    if not isinstance(candidates, Mapping) or set(candidates) != {"X", "Y"}:
        raise NativeDispatchTraceError("blind packet must contain only candidates X and Y")
    for label in ("X", "Y"):
        candidate = candidates[label]
        if not isinstance(candidate, Mapping) or set(candidate) != _BLIND_CANDIDATE_KEYS:
            raise NativeDispatchTraceError(
                f"blind candidate {label} contains mapping/runtime/review metadata"
            )
        content = candidate.get("content")
        digest = candidate.get("sha256")
        if not isinstance(content, str) or not content.strip():
            raise NativeDispatchTraceError(f"blind candidate {label} content is empty")
        if digest != hashlib.sha256(content.encode("utf-8")).hexdigest():
            raise NativeDispatchTraceError(f"blind candidate {label} content SHA-256 mismatch")
    return value


def build_blind_packet(
    *,
    evaluation_id: str,
    project_id: str,
    case_id: str,
    request: str,
    source_packet_sha256: str,
    candidate_paths: Mapping[str, str | Path],
) -> dict[str, Any]:
    if set(candidate_paths) != {"X", "Y"}:
        raise NativeDispatchTraceError("candidate_paths must contain exactly X and Y")
    candidates = {}
    for label in ("X", "Y"):
        path = Path(candidate_paths[label])
        if not path.is_file():
            raise NativeDispatchTraceError(f"candidate {label} file is missing")
        try:
            content = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            raise NativeDispatchTraceError(
                f"candidate {label} is not strict UTF-8 text"
            ) from exc
        candidates[label] = {
            "content": content,
            "sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
        }
    return validate_blind_packet(
        {
            "schema_version": BLIND_PACKET_CONTRACT,
            "evaluation_id": evaluation_id,
            "project_id": project_id,
            "case_id": case_id,
            "request": request,
            "source_packet_sha256": source_packet_sha256,
            "candidates": candidates,
        }
    )


def write_new_json(path: str | Path, value: Mapping[str, Any]) -> Path:
    target = Path(path)
    if target.exists():
        raise NativeDispatchTraceError(f"refusing to overwrite immutable artifact: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8", errors="strict", newline="") as handle:
        handle.write(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n")
    return target


def seal_blind_packet(path: str | Path, packet: Mapping[str, Any]) -> dict[str, Any]:
    value = validate_blind_packet(packet)
    target = write_new_json(path, value)
    return {"path": str(target), "sha256": sha256_file(target)}


def validate_blind_packet_file(path: str | Path) -> tuple[dict[str, Any], str]:
    target = Path(path)
    value = validate_blind_packet(_read_json(target))
    return value, sha256_file(target)


_MAPPING_COMMITMENT_KEYS = {
    "schema_version",
    "evaluation_id",
    "project_id",
    "case_id",
    "algorithm",
    "mapping_labels",
    "commitment_sha256",
    "source_packet_sha256",
    "candidate_source_sha256_sorted",
    "created_before_judge_dispatch",
    "created_at",
}


def _is_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def validate_mapping_commitment(
    commitment: Mapping[str, Any] | str | Path,
) -> dict[str, Any]:
    value = _record(commitment)
    if set(value) != _MAPPING_COMMITMENT_KEYS:
        raise NativeDispatchTraceError("mapping commitment field contract mismatch")
    if value["schema_version"] != MAPPING_COMMITMENT_CONTRACT:
        raise NativeDispatchTraceError("mapping commitment schema_version mismatch")
    if value["mapping_labels"] != ["X", "Y"]:
        raise NativeDispatchTraceError("mapping commitment labels must be frozen as X/Y")
    if value["created_before_judge_dispatch"] is not True:
        raise NativeDispatchTraceError("mapping must be committed before judge dispatch")
    _parse_time(value["created_at"], label="mapping commitment created_at")
    for field in ("commitment_sha256", "source_packet_sha256"):
        if not _is_sha256(value[field]):
            raise NativeDispatchTraceError(f"mapping commitment {field} is invalid")
    source_hashes = value["candidate_source_sha256_sorted"]
    if (
        not isinstance(source_hashes, list)
        or len(source_hashes) != 2
        or source_hashes != sorted(source_hashes)
        or len(set(source_hashes)) != 2
        or not all(_is_sha256(item) for item in source_hashes)
    ):
        raise NativeDispatchTraceError(
            "mapping commitment candidate source hashes must be two unique sorted SHA-256 values"
        )
    return value


def validate_mapping_reveal(
    reveal: Mapping[str, Any] | str | Path,
    *,
    commitment: Mapping[str, Any] | str | Path,
) -> dict[str, Any]:
    value = _record(reveal)
    frozen = validate_mapping_commitment(commitment)
    commitment_file_hash = (
        sha256_file(commitment)
        if isinstance(commitment, (str, Path))
        else None
    )
    required = {
        "schema_version",
        "evaluation_id",
        "project_id",
        "case_id",
        "mapping",
        "salt",
        "commitment_sha256",
        "commitment_file_sha256",
        "judge_sheet_sha256_sorted",
        "revealed_after_review_at",
    }
    if set(value) != required:
        raise NativeDispatchTraceError("mapping reveal field contract mismatch")
    if value["schema_version"] != MAPPING_REVEAL_CONTRACT:
        raise NativeDispatchTraceError("mapping reveal schema_version mismatch")
    for field in ("evaluation_id", "project_id", "case_id", "commitment_sha256"):
        if value[field] != frozen[field]:
            raise NativeDispatchTraceError(f"mapping reveal {field} mismatch")
    mapping = value["mapping"]
    if (
        not isinstance(mapping, Mapping)
        or set(mapping) != {"X", "Y"}
        or any(not isinstance(item, str) or not item for item in mapping.values())
        or len(set(mapping.values())) != 2
    ):
        raise NativeDispatchTraceError("mapping reveal must bind X/Y to two unique conditions")
    salt = value["salt"]
    if not isinstance(salt, str) or not re.fullmatch(r"[0-9a-f]{64}", salt):
        raise NativeDispatchTraceError("mapping reveal salt must be 32-byte lowercase hex")
    if sha256_value({"mapping": dict(mapping), "salt": salt}) != frozen["commitment_sha256"]:
        raise NativeDispatchTraceError("mapping reveal does not open the frozen commitment")
    if not _is_sha256(value["commitment_file_sha256"]):
        raise NativeDispatchTraceError("mapping reveal commitment_file_sha256 is invalid")
    if (
        commitment_file_hash is not None
        and value["commitment_file_sha256"] != commitment_file_hash
    ):
        raise NativeDispatchTraceError("mapping reveal commitment file SHA-256 mismatch")
    judge_hashes = value["judge_sheet_sha256_sorted"]
    if (
        not isinstance(judge_hashes, list)
        or len(judge_hashes) != 3
        or judge_hashes != sorted(judge_hashes)
        or len(set(judge_hashes)) != 3
        or not all(_is_sha256(item) for item in judge_hashes)
    ):
        raise NativeDispatchTraceError(
            "mapping reveal requires three unique sorted judge sheet SHA-256 values"
        )
    _parse_time(value["revealed_after_review_at"], label="revealed_after_review_at")
    return value


def _candidate_total(candidate: Mapping[str, Any]) -> int:
    return sum(int(candidate["scores"][key]) for key in SCORE_KEYS)


def validate_judge_sheet(
    sheet: Mapping[str, Any] | str | Path,
    *,
    packet_sha256: str,
) -> dict[str, Any]:
    value = _record(sheet)
    _validate_schema(value, JUDGE_SCHEMA, label="native content-quality judge sheet")
    if value["packet_sha256"] != packet_sha256:
        raise NativeDispatchTraceError(
            f"judge {value['judge_id']} reviewed a different blind packet"
        )
    totals = {
        label: _candidate_total(value["candidates"][label])
        for label in ("X", "Y")
    }
    expected_winner = (
        "X" if totals["X"] > totals["Y"] else "Y" if totals["Y"] > totals["X"] else "TIE"
    )
    if value["winner"] != expected_winner:
        raise NativeDispatchTraceError(
            f"judge {value['judge_id']} winner conflicts with Q1-Q8 totals"
        )
    finding_ids = [item["finding_id"] for item in value["findings"]]
    if len(finding_ids) != len(set(finding_ids)):
        raise NativeDispatchTraceError(
            f"judge {value['judge_id']} duplicates finding_id"
        )
    return value


def validate_review_precommit(
    precommit: Mapping[str, Any] | str | Path,
    *,
    precommit_brief_sha256: str,
) -> dict[str, Any]:
    """Validate a reviewer commitment made before candidate exposure."""

    value = _record(precommit)
    _validate_schema(value, PRECOMMIT_SCHEMA, label="native review precommit")
    if value["precommit_brief_sha256"] != precommit_brief_sha256:
        raise NativeDispatchTraceError(
            f"judge {value['judge_id']} precommitted against a different brief"
        )
    _parse_time(value["declared_at"], label="declared_at")
    keys = [item["replication_key"] for item in value["priority_failure_modes"]]
    if len(keys) != len(set(keys)):
        raise NativeDispatchTraceError(
            f"judge {value['judge_id']} duplicates priority failure modes"
        )
    return value


def validate_review_precommit_panel(
    precommits: Sequence[Mapping[str, Any] | str | Path],
    *,
    precommit_brief_sha256: str,
    evaluation_id: str,
) -> dict[str, Any]:
    """Require three mutually distinct, role-complete precommitments."""

    if len(precommits) != 3:
        raise NativeDispatchTraceError("native review requires exactly three precommits")
    rows = [
        validate_review_precommit(
            item,
            precommit_brief_sha256=precommit_brief_sha256,
        )
        for item in precommits
    ]
    if {item["judge_role"] for item in rows} != set(JUDGE_ROLES):
        raise NativeDispatchTraceError("precommit panel requires one reviewer per frozen role")
    for field in ("judge_id", "agent_id", "canonical_agent_task_name"):
        values = [item[field] for item in rows]
        if len(values) != len(set(values)):
            raise NativeDispatchTraceError(f"precommit panel requires unique {field}")
    if {item["evaluation_id"] for item in rows} != {evaluation_id}:
        raise NativeDispatchTraceError("precommit panel evaluation_id mismatch")
    return {
        "status": "PASS",
        "evaluation_id": evaluation_id,
        "judge_roles": sorted(item["judge_role"] for item in rows),
        "judge_ids": sorted(item["judge_id"] for item in rows),
        "runtime_usage": dict(UNOBSERVED_USAGE),
    }


def validate_targeted_re_review(
    review: Mapping[str, Any] | str | Path,
    *,
    repair_packet_sha256: str,
    source_candidate_sha256: str,
    repaired_candidate_sha256: str,
    reconciliation_sha256: str,
    forbidden_agent_ids: Iterable[str] = (),
) -> dict[str, Any]:
    value = _record(review)
    _validate_schema(
        value,
        TARGETED_RE_REVIEW_SCHEMA,
        label="native targeted repair re-review",
    )
    expected_hashes = {
        "repair_packet_sha256": repair_packet_sha256,
        "source_candidate_sha256": source_candidate_sha256,
        "repaired_candidate_sha256": repaired_candidate_sha256,
        "reconciliation_sha256": reconciliation_sha256,
    }
    for field, expected in expected_hashes.items():
        if value[field] != expected:
            raise NativeDispatchTraceError(f"targeted re-review {field} mismatch")
    if value["agent_id"] in set(forbidden_agent_ids):
        raise NativeDispatchTraceError("targeted re-review requires a fresh agent")
    keys = [item["replication_key"] for item in value["reviewed_repairs"]]
    expected_keys = {
        "primary_endpoint_not_frozen",
        "no_m0_neutralization_not_frozen",
        "ambiguity_strata_not_frozen",
        "curriculum_schedule_not_frozen",
    }
    if set(keys) != expected_keys or len(keys) != len(set(keys)):
        raise NativeDispatchTraceError("targeted re-review repair coverage mismatch")
    _parse_time(value["reviewed_at"], label="targeted re-review reviewed_at")
    should_pass = (
        all(item["status"] == "CLOSED" for item in value["reviewed_repairs"])
        and all(value["regression_checks"].values())
        and not value["fatal_defects"]
    )
    if (value["overall_verdict"] == "PASS") != should_pass:
        raise NativeDispatchTraceError(
            "targeted re-review verdict conflicts with repair/regression evidence"
        )
    return value


def reconcile_native_judges(
    *,
    blind_packet_path: str | Path,
    judge_sheets: Sequence[Mapping[str, Any] | str | Path],
) -> dict[str, Any]:
    """Validate three independent judges and produce descriptive-only aggregation."""

    packet, packet_sha256 = validate_blind_packet_file(blind_packet_path)
    if len(judge_sheets) != 3:
        raise NativeDispatchTraceError("native review requires exactly three judges")
    sheet_refs = list(judge_sheets)
    sheets = [
        validate_judge_sheet(item, packet_sha256=packet_sha256)
        for item in sheet_refs
    ]
    roles = [item["judge_role"] for item in sheets]
    if sorted(roles) != sorted(JUDGE_ROLES):
        raise NativeDispatchTraceError("native review requires one judge per frozen role")
    judge_ids = [item["judge_id"] for item in sheets]
    agent_ids = [item["agent_id"] for item in sheets]
    task_names = [item["canonical_agent_task_name"] for item in sheets]
    if len(set(judge_ids)) != 3:
        raise NativeDispatchTraceError("judge_id values must be unique")
    if len(set(agent_ids)) != 3:
        raise NativeDispatchTraceError("three judges require unique agent ownership")
    if len(set(task_names)) != 3:
        raise NativeDispatchTraceError(
            "three judges require unique canonical agent task names"
        )
    identity_fields = ("evaluation_id", "project_id", "case_id")
    for field in identity_fields:
        values = {item[field] for item in sheets}
        if values != {packet[field]}:
            raise NativeDispatchTraceError(
                f"judge sheets disagree with blind packet {field}"
            )

    totals = {"X": [], "Y": []}
    dimension_values = {
        label: {key: [] for key in SCORE_KEYS} for label in ("X", "Y")
    }
    votes = {"X": 0, "Y": 0, "TIE": 0}
    fatal_defects: list[dict[str, Any]] = []
    finding_groups: dict[tuple[str, str, str], dict[str, Any]] = {}
    judge_evidence = []
    for sheet_ref, sheet in zip(sheet_refs, sheets):
        file_bound = isinstance(sheet_ref, (str, Path))
        bound_sha256 = sha256_file(sheet_ref) if file_bound else sha256_value(sheet)
        judge_evidence.append(
            {
                "judge_id": sheet["judge_id"],
                "judge_role": sheet["judge_role"],
                "agent_id": sheet["agent_id"],
                "canonical_agent_task_name": sheet["canonical_agent_task_name"],
                "sheet_sha256": bound_sha256,
                "sheet_hash_kind": "FILE_BYTES" if file_bound else "CANONICAL_VALUE",
                "sheet_value_sha256": sha256_value(sheet),
            }
        )
        votes[sheet["winner"]] += 1
        for label in ("X", "Y"):
            candidate = sheet["candidates"][label]
            totals[label].append(_candidate_total(candidate))
            for key in SCORE_KEYS:
                dimension_values[label][key].append(candidate["scores"][key])
            for defect in candidate["fatal_defects"]:
                fatal_defects.append(
                    {
                        "judge_id": sheet["judge_id"],
                        "candidate": label,
                        **dict(defect),
                    }
                )
        for finding in sheet["findings"]:
            if not finding["substantive"]:
                continue
            key = (
                finding["replication_key"],
                finding["candidate"],
                finding["kind"],
            )
            group = finding_groups.setdefault(
                key,
                {
                    "replication_key": finding["replication_key"],
                    "candidate": finding["candidate"],
                    "kind": finding["kind"],
                    "judge_ids": set(),
                    "locators": [],
                    "summaries": [],
                    "repairs": [],
                },
            )
            group["judge_ids"].add(sheet["judge_id"])
            group["locators"].append(
                {"judge_id": sheet["judge_id"], "locator": finding["locator"]}
            )
            group["summaries"].append(finding["summary"])
            group["repairs"].append(finding["repair"])

    replicated_findings = []
    for key in sorted(finding_groups):
        group = finding_groups[key]
        if len(group["judge_ids"]) >= 2:
            replicated_findings.append(
                {
                    **group,
                    "judge_ids": sorted(group["judge_ids"]),
                    "replication_count": len(group["judge_ids"]),
                    "meets_two_of_three_rule": True,
                }
            )
    paired_deltas = [
        y_total - x_total
        for x_total, y_total in zip(totals["X"], totals["Y"])
    ]
    majority_winner = next(
        (label for label in ("X", "Y", "TIE") if votes[label] >= 2),
        "NO_MAJORITY",
    )
    failures = []
    if not replicated_findings:
        failures.append(
            {
                "code": "NO_REPLICATED_SUBSTANTIVE_FINDING",
                "required_distinct_judges": 2,
                "observed": 0,
            }
        )

    return {
        "schema_version": "native-content-quality-report/v1",
        "evaluation_state": "DESCRIPTIVE_REVIEW_PASS" if not failures else "DESCRIPTIVE_REVIEW_BLOCKED",
        "analysis_mode": "SINGLE_PROJECT_DESCRIPTIVE_ONLY",
        "inferential_statistics_claimed": False,
        "evaluation_id": packet["evaluation_id"],
        "project_id": packet["project_id"],
        "case_id": packet["case_id"],
        "blind_packet": {
            "path": str(Path(blind_packet_path)),
            "sha256": packet_sha256,
        },
        "judges": judge_evidence,
        "candidate_mean_totals": {
            label: sum(values) / 3.0 for label, values in totals.items()
        },
        "candidate_dimension_means": {
            label: {
                key: sum(values) / 3.0
                for key, values in dimensions.items()
            }
            for label, dimensions in dimension_values.items()
        },
        "core_dimensions": list(CORE_SCORE_KEYS),
        "paired_delta_y_minus_x": {
            "values": paired_deltas,
            "mean": sum(paired_deltas) / 3.0,
            "median": statistics.median(paired_deltas),
        },
        "winner_votes": votes,
        "majority_winner": majority_winner,
        "fatal_defects": fatal_defects,
        "replicated_substantive_findings": replicated_findings,
        "failure_cases": failures,
        "runtime_usage": dict(UNOBSERVED_USAGE),
        "claim_boundary": (
            "This is a descriptive review of one frozen project case by three judges. "
            "It reports no confidence interval, p-value, population generalization, provider usage, "
            "cost efficiency, or causal architecture superiority."
        ),
    }


__all__ = [
    "APPLICABLE",
    "BLIND_PACKET_CONTRACT",
    "COMPLETED",
    "COMPLETION_CONTRACT",
    "COMPLETION_SCHEMA",
    "JUDGE_CONTRACT",
    "JUDGE_ROLES",
    "JUDGE_SCHEMA",
    "MAPPING_COMMITMENT_CONTRACT",
    "MAPPING_REVEAL_CONTRACT",
    "PRECOMMIT_CONTRACT",
    "PRECOMMIT_SCHEMA",
    "TARGETED_RE_REVIEW_CONTRACT",
    "TARGETED_RE_REVIEW_SCHEMA",
    "NOT_APPLICABLE_NO_EXECUTOR",
    "NativeDispatchTraceError",
    "RESULT_ROLE_NO_EXECUTOR",
    "UNOBSERVED_USAGE",
    "WORK_ORDER_CONTRACT",
    "WORK_ORDER_SCHEMA",
    "build_blind_packet",
    "create_completion",
    "create_work_order",
    "reconcile_native_judges",
    "seal_blind_packet",
    "sha256_file",
    "sha256_value",
    "validate_blind_packet",
    "validate_blind_packet_file",
    "validate_completion",
    "validate_dispatch_trace",
    "validate_judge_sheet",
    "validate_mapping_commitment",
    "validate_mapping_reveal",
    "validate_review_precommit",
    "validate_review_precommit_panel",
    "validate_targeted_re_review",
    "validate_work_order",
    "write_new_json",
]
