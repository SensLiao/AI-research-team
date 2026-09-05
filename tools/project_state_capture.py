"""Deterministically capture current project state into a research run.

This module is the producer-side seam for ``project_state_snapshot``.  It copies
explicitly selected source bytes into the run-local project-state lane and writes
one approved, schema-valid artifact which binds those copies to the run's pinned
task frame.  It does not discover files, infer facts, or read secret-shaped paths.

CLI example::

    python -m research_agent_teams.tools.project_state_capture \
      --run-dir runs/my-project/run-1 \
      --project my-project \
      --source-of-truth-id current-project-contract \
      --captured-at 2026-08-13T10:00:00Z \
      --valid-until 2026-08-14T10:00:00Z \
      --source canonical=CANONICAL_STATE=projects/my-project/CANONICAL-PROJECT.md \
      --fact scope-current="The canonical project contract is current." \
      --fact-source scope-current=canonical

``--source ROLE=PATH`` is also accepted.  In that shorthand, deterministic
aliases such as ``canonical-state`` and ``canonical-state-2`` are assigned.
Facts without any ``--fact-source`` entry are conservatively grounded in every
declared source rather than being left ungrounded.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Mapping, Sequence

from research_agent_teams.operate.artifacts import envelope
from research_agent_teams.tools.hash_artifact import hash_payload
from research_agent_teams.tools.validate_artifact import validate_artifact


CONTRACT_VERSION = "project-state-snapshot/v1"
CREATED_BY = "project-state-capture"
PROJECT_STATE_REL = Path("inbox") / "project-state"
SOURCE_LANE_REL = PROJECT_STATE_REL / "sources"
ALLOWED_ROLES = frozenset({
    "CANONICAL_STATE",
    "LIVE_MANIFEST",
    "CODE_CONTRACT",
    "DATA_CONTRACT",
    "RESOURCE_STATUS",
    "SUPPORTING",
})
CURRENT_ROLES = frozenset({"CANONICAL_STATE", "LIVE_MANIFEST"})

_PROJECT_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_SAFE_ALIAS_RE = re.compile(r"[^a-z0-9._-]+")
_SAFE_SUFFIX_RE = re.compile(r"^\.[A-Za-z0-9]{1,12}$")
_SENSITIVE_TOKEN_RE = re.compile(
    r"(?:^|[._-])(?:"
    r"credentials?|tokens?|secrets?|passwords?|passwd|"
    r"api[._-]?keys?|private[._-]?keys?"
    r")(?:[._-]|$)",
    re.IGNORECASE,
)
_SENSITIVE_SUFFIXES = frozenset({".pem", ".key", ".p12", ".pfx"})
_PRIVATE_KEY_NAMES = frozenset({"id_rsa", "id_dsa", "id_ecdsa", "id_ed25519"})


class ProjectStateCaptureError(ValueError):
    """The requested capture would be invalid, ambiguous, or unsafe."""


class ProjectStateConflictError(ProjectStateCaptureError):
    """A deterministic destination already exists with different bytes."""


@dataclass(frozen=True)
class SourceSpec:
    """One explicit source file and the role asserted for it."""

    role: str
    path: str | Path
    name: str | None = None


@dataclass(frozen=True)
class FactSpec:
    """One stated fact and the declared source aliases which ground it."""

    fact_id: str
    statement: str
    source_names: tuple[str, ...] = ()


@dataclass(frozen=True)
class _PreparedSource:
    name: str
    role: str
    original_path: Path
    source_ref: str
    destination: Path
    data: bytes
    sha256: str


def _canonical_json_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def _sha256_bytes(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _parse_timestamp(value: str, label: str) -> datetime:
    raw = str(value or "").strip()
    if not raw:
        raise ProjectStateCaptureError(f"{label} is required")
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ProjectStateCaptureError(
            f"{label} must be an ISO-8601 timestamp: {value!r}"
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ProjectStateCaptureError(f"{label} must include a timezone")
    return parsed.astimezone(timezone.utc)


def _format_timestamp(value: datetime) -> str:
    timespec = "microseconds" if value.microsecond else "seconds"
    return value.isoformat(timespec=timespec).replace("+00:00", "Z")


def _safe_slug(value: str, label: str) -> str:
    normalized = _SAFE_ALIAS_RE.sub("-", str(value or "").strip().casefold())
    normalized = re.sub(r"[-_.]{2,}", "-", normalized).strip("-_.")
    if not normalized:
        raise ProjectStateCaptureError(f"{label} has no usable filename characters")
    return normalized[:80].rstrip("-_.")


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def _is_link_like(path: Path) -> bool:
    """Treat symbolic links and Windows junctions as indirection boundaries."""

    if path.is_symlink():
        return True
    is_junction = getattr(path, "is_junction", None)
    return bool(is_junction and is_junction())


def _path_has_link_component(path: Path) -> bool:
    """Inspect the lexical path before ``resolve`` can erase link components."""

    absolute = path.absolute()
    return any(_is_link_like(component) for component in (absolute, *absolute.parents))


def _assert_not_sensitive(path: Path) -> None:
    """Reject secret-shaped input paths before opening them."""

    for component in path.parts:
        name = component.casefold()
        if name == ".env" or name.startswith(".env"):
            raise ProjectStateCaptureError(
                f"refusing secret-shaped source path component: {component!r}"
            )
        if Path(name).suffix in _SENSITIVE_SUFFIXES:
            raise ProjectStateCaptureError(
                f"refusing private-key source path component: {component!r}"
            )
        stem = Path(name).stem
        if stem in _PRIVATE_KEY_NAMES or _SENSITIVE_TOKEN_RE.search(name):
            raise ProjectStateCaptureError(
                f"refusing credential/token-shaped source path component: {component!r}"
            )


def _source_input(value: SourceSpec | Mapping[str, object] | Sequence[object]) -> SourceSpec:
    if isinstance(value, SourceSpec):
        return value
    if isinstance(value, Mapping):
        return SourceSpec(
            role=str(value.get("role") or ""),
            path=str(value.get("path") or ""),
            name=str(value["name"]) if value.get("name") is not None else None,
        )
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        items = list(value)
        if len(items) == 2:
            return SourceSpec(role=str(items[0]), path=str(items[1]))
        if len(items) == 3:
            return SourceSpec(role=str(items[1]), path=str(items[2]), name=str(items[0]))
    raise ProjectStateCaptureError(
        "each source must be SourceSpec, {role,path[,name]}, (role,path), or (name,role,path)"
    )


def _fact_input(value: FactSpec | Mapping[str, object] | Sequence[object]) -> FactSpec:
    if isinstance(value, FactSpec):
        return value
    if isinstance(value, Mapping):
        names = value.get("source_names")
        if names is None:
            names = value.get("sources")
        if names is None:
            names = value.get("source_refs")
        if names is None:
            names = ()
        if isinstance(names, str):
            names = (names,)
        return FactSpec(
            fact_id=str(value.get("fact_id") or ""),
            statement=str(value.get("statement") or ""),
            source_names=tuple(str(item) for item in names),
        )
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        items = list(value)
        if len(items) == 2:
            return FactSpec(str(items[0]), str(items[1]))
        if len(items) == 3:
            names = items[2]
            if isinstance(names, str):
                names = (names,)
            return FactSpec(str(items[0]), str(items[1]), tuple(str(x) for x in names))
    raise ProjectStateCaptureError(
        "each fact must be FactSpec, {fact_id,statement[,source_names]}, or a 2/3-tuple"
    )


def _load_bound_task_frame(run_root: Path, project: str) -> tuple[dict, str]:
    path = run_root / "task_frame.artifact.json"
    if _is_link_like(path) or not path.is_file():
        raise ProjectStateCaptureError(
            "run-dir must contain a non-symlink task_frame.artifact.json"
        )
    try:
        raw = path.read_bytes()
        task_frame = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise ProjectStateCaptureError("task_frame.artifact.json is not valid UTF-8 JSON") from exc
    if not isinstance(task_frame, dict) or task_frame.get("artifact_type") != "task_frame":
        raise ProjectStateCaptureError("task_frame.artifact.json is not a task_frame artifact")
    errors = validate_artifact(task_frame)
    if errors:
        raise ProjectStateCaptureError(f"task frame fails artifact validation: {errors}")
    task_project = str((task_frame.get("payload") or {}).get("project") or "").strip()
    if not task_project:
        raise ProjectStateCaptureError(
            "task frame has no project binding; project-state capture requires a project run"
        )
    if task_project != project:
        raise ProjectStateCaptureError(
            f"project mismatch: task frame is bound to {task_project!r}, not {project!r}"
        )
    return task_frame, _sha256_bytes(raw)


def _resolve_source(path_value: str | Path) -> Path:
    raw = Path(path_value).expanduser()
    if not raw.is_absolute():
        raw = Path.cwd() / raw
    raw = raw.absolute()
    _assert_not_sensitive(raw)
    if _path_has_link_component(raw):
        raise ProjectStateCaptureError(
            f"source path must not contain a symlink or junction: {raw}"
        )
    if raw.is_dir():
        raise ProjectStateCaptureError(f"source must be a file, not a directory: {raw}")
    if not raw.is_file():
        raise ProjectStateCaptureError(f"source file does not exist: {raw}")
    resolved = raw.resolve(strict=True)
    _assert_not_sensitive(resolved)
    if not resolved.is_file():
        raise ProjectStateCaptureError(f"source must be a regular file: {raw}")
    return resolved


def _assert_lane_component(path: Path, label: str) -> None:
    if _is_link_like(path):
        raise ProjectStateCaptureError(f"{label} must not be a symlink or junction: {path}")
    if path.exists() and not path.is_dir():
        raise ProjectStateCaptureError(f"{label} must be a directory: {path}")


def _resolve_output(run_root: Path, lane: Path, output: str | Path | None,
                    default_name: str) -> Path:
    if output is None:
        candidate = lane / default_name
    else:
        raw = Path(output).expanduser()
        if raw.is_absolute():
            candidate = raw
        elif len(raw.parts) == 1:
            candidate = lane / raw
        else:
            candidate = run_root / raw
    resolved = candidate.resolve(strict=False)
    lane_resolved = lane.resolve(strict=False)
    if resolved.parent != lane_resolved or not _is_relative_to(resolved, run_root):
        raise ProjectStateCaptureError(
            "output target must be a direct child of run-dir/inbox/project-state"
        )
    if not resolved.name.endswith(".artifact.json"):
        raise ProjectStateCaptureError("output target must end with .artifact.json")
    if _is_link_like(candidate) or (candidate.exists() and not candidate.is_file()):
        raise ProjectStateCaptureError(f"output target must be a non-symlink file: {candidate}")
    return resolved


def _write_idempotent(path: Path, data: bytes, label: str) -> bool:
    """Create ``path`` once; equal existing bytes are a no-op, different bytes conflict."""

    if path.exists() or _is_link_like(path):
        if _is_link_like(path) or not path.is_file():
            raise ProjectStateCaptureError(f"{label} destination is not a regular file: {path}")
        if path.read_bytes() != data:
            raise ProjectStateConflictError(
                f"{label} conflict: destination already exists with different bytes: {path}"
            )
        return False
    try:
        with path.open("xb") as handle:
            handle.write(data)
    except FileExistsError:
        if _is_link_like(path) or not path.is_file() or path.read_bytes() != data:
            raise ProjectStateConflictError(
                f"{label} conflict: destination appeared with different bytes: {path}"
            )
        return False
    return True


def _prepare_sources(
    values: Sequence[SourceSpec | Mapping[str, object] | Sequence[object]],
    run_root: Path,
    source_lane: Path,
) -> tuple[list[_PreparedSource], dict[str, str]]:
    if not values:
        raise ProjectStateCaptureError("at least one --source is required")
    prepared: list[_PreparedSource] = []
    selectors: dict[str, str] = {}
    role_counts: dict[str, int] = {}
    aliases: set[str] = set()
    for index, raw_value in enumerate(values, start=1):
        spec = _source_input(raw_value)
        role = spec.role.strip().upper()
        if role not in ALLOWED_ROLES:
            raise ProjectStateCaptureError(
                f"source {index} has unsupported role {spec.role!r}; allowed={sorted(ALLOWED_ROLES)}"
            )
        role_counts[role] = role_counts.get(role, 0) + 1
        if spec.name is None:
            base = role.casefold().replace("_", "-")
            alias = base if role_counts[role] == 1 else f"{base}-{role_counts[role]}"
        else:
            alias = _safe_slug(spec.name, f"source {index} name")
        if alias in aliases:
            raise ProjectStateCaptureError(f"duplicate normalized source name: {alias!r}")
        aliases.add(alias)
        source_path = _resolve_source(spec.path)
        try:
            data = source_path.read_bytes()
        except OSError as exc:
            raise ProjectStateCaptureError(f"cannot read source file: {source_path}") from exc
        digest = _sha256_bytes(data)
        suffix = source_path.suffix if _SAFE_SUFFIX_RE.fullmatch(source_path.suffix) else ".source"
        filename = f"{alias}--{digest.removeprefix('sha256:')}{suffix.casefold()}"
        destination = source_lane / filename
        source_ref = destination.relative_to(run_root).as_posix()
        prepared.append(_PreparedSource(
            name=alias,
            role=role,
            original_path=source_path,
            source_ref=source_ref,
            destination=destination,
            data=data,
            sha256=digest,
        ))
        selectors[alias] = alias
        selectors[str(index)] = alias
        if spec.name is not None:
            selectors[str(spec.name)] = alias

    if not any(item.role in CURRENT_ROLES for item in prepared):
        raise ProjectStateCaptureError(
            "sources must include at least one CANONICAL_STATE or LIVE_MANIFEST role"
        )
    for role in ALLOWED_ROLES:
        matching = [item.name for item in prepared if item.role == role]
        if len(matching) == 1:
            selectors[role] = matching[0]
            selectors[role.casefold()] = matching[0]
    prepared.sort(key=lambda item: item.name)
    return prepared, selectors


def _prepare_facts(
    values: Sequence[FactSpec | Mapping[str, object] | Sequence[object]],
    sources: Sequence[_PreparedSource],
    selectors: Mapping[str, str],
) -> list[dict]:
    if not values:
        raise ProjectStateCaptureError("at least one --fact is required")
    source_by_name = {item.name: item for item in sources}
    fact_ids: set[str] = set()
    rows: list[dict] = []
    for raw_value in values:
        spec = _fact_input(raw_value)
        fact_id = spec.fact_id.strip()
        statement = spec.statement.strip()
        if not fact_id or not statement:
            raise ProjectStateCaptureError("fact_id and statement must both be non-empty")
        if fact_id in fact_ids:
            raise ProjectStateCaptureError(f"duplicate fact_id: {fact_id!r}")
        fact_ids.add(fact_id)
        selected_names: list[str] = []
        raw_names = spec.source_names or tuple(item.name for item in sources)
        for raw_name in raw_names:
            selector = str(raw_name).strip()
            name = selectors.get(selector)
            if name is None:
                normalized = _safe_slug(selector, f"source selector for fact {fact_id}")
                name = selectors.get(normalized)
            if name is None or name not in source_by_name:
                raise ProjectStateCaptureError(
                    f"fact {fact_id!r} references undeclared source {selector!r}"
                )
            if name not in selected_names:
                selected_names.append(name)
        refs = sorted(source_by_name[name].source_ref for name in selected_names)
        if not refs:
            raise ProjectStateCaptureError(f"fact {fact_id!r} has no declared source")
        rows.append({"fact_id": fact_id, "statement": statement, "source_refs": refs})
    rows.sort(key=lambda row: row["fact_id"])
    return rows


def capture_project_state(
    *,
    run_dir: str | Path,
    project: str,
    source_of_truth_id: str,
    captured_at: str,
    sources: Sequence[SourceSpec | Mapping[str, object] | Sequence[object]],
    facts: Sequence[FactSpec | Mapping[str, object] | Sequence[object]],
    valid_until: str | None = None,
    validity_seconds: int | None = None,
    output: str | Path | None = None,
) -> Path:
    """Capture sources and return the absolute snapshot artifact path.

    Exactly one of ``valid_until`` or ``validity_seconds`` is required.  Every
    write is deterministic and create-once: repeating an identical capture is a
    no-op, while attempting to reuse a destination for different bytes raises
    :class:`ProjectStateConflictError`.
    """

    project_id = str(project or "").strip()
    if not _PROJECT_RE.fullmatch(project_id) or len(project_id) > 50:
        raise ProjectStateCaptureError("project must be a lowercase-kebab slug of at most 50 chars")
    truth_id = str(source_of_truth_id or "").strip()
    if not truth_id or len(truth_id) > 200 or any(ord(char) < 32 for char in truth_id):
        raise ProjectStateCaptureError("source_of_truth_id must be a non-empty printable identifier")
    if (valid_until is None) == (validity_seconds is None):
        raise ProjectStateCaptureError(
            "exactly one of valid_until or validity_seconds is required"
        )

    captured_dt = _parse_timestamp(captured_at, "captured_at")
    if validity_seconds is not None:
        if isinstance(validity_seconds, bool) or int(validity_seconds) <= 0:
            raise ProjectStateCaptureError("validity_seconds must be a positive integer")
        valid_dt = captured_dt + timedelta(seconds=int(validity_seconds))
    else:
        valid_dt = _parse_timestamp(str(valid_until), "valid_until")
    if valid_dt <= captured_dt:
        raise ProjectStateCaptureError("valid_until must be later than captured_at")
    captured_iso = _format_timestamp(captured_dt)
    valid_iso = _format_timestamp(valid_dt)

    raw_run = Path(run_dir).expanduser()
    if not raw_run.is_absolute():
        raw_run = Path.cwd() / raw_run
    raw_run = raw_run.absolute()
    if _path_has_link_component(raw_run) or not raw_run.is_dir():
        raise ProjectStateCaptureError(
            "run-dir must be an existing directory whose path contains no symlink or junction"
        )
    run_root = raw_run.resolve(strict=True)
    _task_frame, task_frame_hash = _load_bound_task_frame(run_root, project_id)

    inbox = run_root / "inbox"
    lane = run_root / PROJECT_STATE_REL
    source_lane = run_root / SOURCE_LANE_REL
    _assert_lane_component(inbox, "run inbox")
    _assert_lane_component(lane, "project-state lane")
    _assert_lane_component(source_lane, "project-state source lane")

    prepared_sources, selectors = _prepare_sources(sources, run_root, source_lane)
    fact_rows = _prepare_facts(facts, prepared_sources, selectors)
    payload = {
        "contract_version": CONTRACT_VERSION,
        "project_id": project_id,
        "source_of_truth_id": truth_id,
        "captured_at": captured_iso,
        "valid_until": valid_iso,
        "sources": [
            {
                "source_ref": item.source_ref,
                "source_sha256": item.sha256,
                "role": item.role,
            }
            for item in prepared_sources
        ],
        "facts": fact_rows,
    }
    payload_hash = hash_payload(payload)
    artifact = envelope(
        "project_state_snapshot", CREATED_BY, payload, captured_iso, status="approved"
    )
    artifact["artifact_id"] = (
        "project-state-snapshot-" + payload_hash.removeprefix("sha256:")[:16]
    )
    artifact["input_artifact_hashes"] = [task_frame_hash]
    artifact["output_hash"] = payload_hash
    errors = validate_artifact(artifact)
    if errors:
        raise ProjectStateCaptureError(
            f"project-state capture produced an invalid artifact: {errors}"
        )

    captured_token = captured_dt.strftime("%Y%m%dT%H%M%S")
    if captured_dt.microsecond:
        captured_token += f"{captured_dt.microsecond:06d}"
    captured_token += "Z"
    default_name = (
        f"project-state-{_safe_slug(truth_id, 'source_of_truth_id')}-"
        f"{captured_token}.artifact.json"
    )
    artifact_path = _resolve_output(run_root, lane, output, default_name)
    artifact_bytes = _canonical_json_bytes(artifact)

    # Preflight every existing destination before making any writes.  A changed
    # recapture therefore fails without depositing a new source beside a
    # conflicting artifact.
    for item in prepared_sources:
        if item.destination.exists() or _is_link_like(item.destination):
            if (
                _is_link_like(item.destination)
                or not item.destination.is_file()
                or item.destination.read_bytes() != item.data
            ):
                raise ProjectStateConflictError(
                    "source-copy conflict: destination exists with different bytes: "
                    f"{item.destination}"
                )
    if artifact_path.exists() or _is_link_like(artifact_path):
        if (
            _is_link_like(artifact_path)
            or not artifact_path.is_file()
            or artifact_path.read_bytes() != artifact_bytes
        ):
            raise ProjectStateConflictError(
                f"artifact conflict: destination exists with different bytes: {artifact_path}"
            )

    source_lane.mkdir(parents=True, exist_ok=True)
    for item in prepared_sources:
        _write_idempotent(item.destination, item.data, "source-copy")
    _write_idempotent(artifact_path, artifact_bytes, "artifact")
    return artifact_path


def _parse_cli_source(value: str) -> SourceSpec:
    if "=" not in value:
        raise argparse.ArgumentTypeError("source must be ROLE=PATH or NAME=ROLE=PATH")
    first, rest = value.split("=", 1)
    if first.strip().upper() in ALLOWED_ROLES:
        if not rest:
            raise argparse.ArgumentTypeError("source path must be non-empty")
        return SourceSpec(role=first, path=rest)
    if "=" not in rest:
        raise argparse.ArgumentTypeError("named source must be NAME=ROLE=PATH")
    role, path = rest.split("=", 1)
    if not first or not role or not path:
        raise argparse.ArgumentTypeError("named source must be NAME=ROLE=PATH")
    return SourceSpec(role=role, path=path, name=first)


def _parse_cli_fact(value: str) -> tuple[str, str]:
    if "=" not in value:
        raise argparse.ArgumentTypeError("fact must be FACT_ID=STATEMENT")
    fact_id, statement = value.split("=", 1)
    if not fact_id.strip() or not statement.strip():
        raise argparse.ArgumentTypeError("fact id and statement must be non-empty")
    return fact_id.strip(), statement.strip()


def _parse_cli_fact_source(value: str) -> tuple[str, str]:
    if "=" not in value:
        raise argparse.ArgumentTypeError("fact source must be FACT_ID=SOURCE_NAME")
    fact_id, source_name = value.split("=", 1)
    if not fact_id.strip() or not source_name.strip():
        raise argparse.ArgumentTypeError("fact id and source name must be non-empty")
    return fact_id.strip(), source_name.strip()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Capture a deterministic, hash-bound project_state_snapshot for one run."
    )
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--project", required=True)
    parser.add_argument("--source-of-truth-id", required=True)
    parser.add_argument("--captured-at", required=True)
    validity = parser.add_mutually_exclusive_group(required=True)
    validity.add_argument("--valid-until")
    validity.add_argument(
        "--validity-seconds", "--validity", dest="validity_seconds", type=int
    )
    parser.add_argument(
        "--source", action="append", required=True, type=_parse_cli_source,
        metavar="[NAME=]ROLE=PATH",
    )
    parser.add_argument(
        "--fact", action="append", required=True, type=_parse_cli_fact,
        metavar="FACT_ID=STATEMENT",
    )
    parser.add_argument(
        "--fact-source", action="append", default=[], type=_parse_cli_fact_source,
        metavar="FACT_ID=SOURCE_NAME",
    )
    parser.add_argument(
        "--output",
        help="Optional .artifact.json name/path; it must remain directly in inbox/project-state/.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    fact_sources: dict[str, list[str]] = {}
    for fact_id, source_name in args.fact_source:
        fact_sources.setdefault(fact_id, []).append(source_name)
    fact_ids = {fact_id for fact_id, _statement in args.fact}
    unknown = sorted(set(fact_sources) - fact_ids)
    if unknown:
        parser.error(f"--fact-source names undeclared fact(s): {unknown}")
    facts = [
        FactSpec(fact_id, statement, tuple(fact_sources.get(fact_id, ())))
        for fact_id, statement in args.fact
    ]
    try:
        artifact_path = capture_project_state(
            run_dir=args.run_dir,
            project=args.project,
            source_of_truth_id=args.source_of_truth_id,
            captured_at=args.captured_at,
            valid_until=args.valid_until,
            validity_seconds=args.validity_seconds,
            sources=args.source,
            facts=facts,
            output=args.output,
        )
    except ProjectStateCaptureError as exc:
        parser.error(str(exc))
    artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
    print(json.dumps({
        "artifact_path": str(artifact_path),
        "artifact_sha256": _sha256_bytes(artifact_path.read_bytes()),
        "project_id": artifact["payload"]["project_id"],
        "captured_at": artifact["payload"]["captured_at"],
        "valid_until": artifact["payload"]["valid_until"],
        "source_refs": [row["source_ref"] for row in artifact["payload"]["sources"]],
    }, ensure_ascii=False, sort_keys=True))
    return 0


__all__ = [
    "ALLOWED_ROLES",
    "CURRENT_ROLES",
    "FactSpec",
    "ProjectStateCaptureError",
    "ProjectStateConflictError",
    "SourceSpec",
    "capture_project_state",
    "main",
]


if __name__ == "__main__":  # pragma: no cover - exercised through the module CLI
    raise SystemExit(main())
