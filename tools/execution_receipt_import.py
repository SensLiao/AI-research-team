"""Trusted import boundary for externally executed experiment results.

Reasoning workers may point at receipts, but they cannot mint trusted execution.
An external executor signs a receipt with a control-plane key that is not exposed
to worker processes.  This module verifies the attestation, command identity,
timestamps, and every referenced file before constructing a checkpointable import
manifest.  Consumers re-run those checks instead of trusting the stored manifest.

The verifier intentionally exposes no signing function.  Production signing belongs
to the non-LLM executor integration.  The research control plane receives only an
Ed25519 public key; the signing key remains outside every reasoning-worker runtime.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Iterable, Mapping

from jsonschema import Draft202012Validator, FormatChecker
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey


RECEIPT_VERSION = "executor-receipt/v1"
IMPORT_VERSION = "execution-import/v1"
IMPORT_ARTIFACT_REL = Path("evidence/EXECUTE/execution-import.artifact.json")
RECEIPT_ROOT = PurePosixPath("executor-receipts")
RESULT_ROOT = PurePosixPath("execution-results")
_SCHEMA_ROOT = Path(__file__).resolve().parent.parent / "schemas"
_SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


class ExecutionReceiptError(ValueError):
    """A receipt, attestation, file binding, or import manifest is untrusted."""


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def receipt_attestation_message(receipt: Mapping[str, Any]) -> bytes:
    unsigned = dict(receipt)
    attestation = dict(unsigned.get("attestation") or {})
    attestation.pop("signature", None)
    unsigned["attestation"] = attestation
    return canonical_json_bytes(unsigned)


def trust_public_key_env_name(key_id: str) -> str:
    token = re.sub(r"[^A-Za-z0-9]", "_", key_id).upper()
    return f"RAT_EXECUTOR_TRUST_PUBLIC_KEY_{token}"


def _default_key_resolver(key_id: str) -> bytes | None:
    encoded = os.environ.get(trust_public_key_env_name(key_id))
    if not encoded:
        return None
    try:
        key = base64.b64decode(encoded, validate=True)
    except (ValueError, TypeError) as exc:
        raise ExecutionReceiptError(
            f"executor trust public key {key_id!r} is not valid base64"
        ) from exc
    if len(key) != 32:
        raise ExecutionReceiptError(
            f"executor trust public key {key_id!r} must be 32 raw Ed25519 bytes"
        )
    return key


def _schema(name: str) -> dict:
    return json.loads((_SCHEMA_ROOT / name).read_text(encoding="utf-8"))


def _validate_schema(value: dict, name: str, label: str) -> None:
    validator = Draft202012Validator(_schema(name), format_checker=FormatChecker())
    errors = sorted(validator.iter_errors(value), key=lambda error: list(error.path))
    if errors:
        details = "; ".join(
            f"{'/'.join(str(part) for part in error.path) or '<root>'}: {error.message}"
            for error in errors[:8]
        )
        raise ExecutionReceiptError(f"{label} schema BLOCK: {details}")


def _safe_member(run_dir: Path, ref: str, required_root: PurePosixPath) -> Path:
    normalized = str(ref or "").replace("\\", "/")
    pure = PurePosixPath(normalized)
    if pure.is_absolute() or ".." in pure.parts or not pure.parts:
        raise ExecutionReceiptError(f"unsafe execution evidence path: {ref!r}")
    if pure.parts[0].casefold() != required_root.parts[0].casefold():
        raise ExecutionReceiptError(
            f"execution evidence path {ref!r} must live under {required_root.as_posix()}/"
        )
    root = run_dir.resolve()
    candidate = root / Path(*pure.parts)
    cursor = candidate
    while cursor != root:
        if cursor.is_symlink():
            raise ExecutionReceiptError(f"execution evidence path contains a symlink: {ref!r}")
        cursor = cursor.parent
    path = candidate.resolve()
    if path == root or root not in path.parents:
        raise ExecutionReceiptError(f"execution evidence escaped run directory: {ref!r}")
    if not path.is_file():
        raise ExecutionReceiptError(f"execution evidence file is missing: {ref!r}")
    return path


def _verify_file_binding(run_dir: Path, binding: Mapping[str, Any]) -> dict:
    path = _safe_member(run_dir, str(binding.get("path") or ""), RESULT_ROOT)
    expected_size = binding.get("size_bytes")
    actual_size = path.stat().st_size
    if expected_size != actual_size:
        raise ExecutionReceiptError(
            f"execution file size mismatch for {binding.get('path')!r}: "
            f"receipt={expected_size!r} actual={actual_size}"
        )
    expected_hash = str(binding.get("sha256") or "")
    actual_hash = sha256_file(path)
    if not hmac.compare_digest(expected_hash, actual_hash):
        raise ExecutionReceiptError(
            f"execution file hash mismatch for {binding.get('path')!r}"
        )
    verified = {
        "path": str(binding["path"]).replace("\\", "/"),
        "sha256": actual_hash,
        "size_bytes": actual_size,
    }
    for key in ("role", "media_type"):
        if key in binding:
            verified[key] = binding[key]
    return verified


def _parse_time(value: str, label: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ExecutionReceiptError(f"invalid {label} timestamp: {value!r}") from exc
    if parsed.tzinfo is None:
        raise ExecutionReceiptError(f"{label} timestamp must include a timezone")
    return parsed


def verify_executor_receipt(
    run_dir: str | Path,
    receipt_ref: str,
    *,
    expected_run_id: str,
    key_resolver: Callable[[str], bytes | None] | None = None,
) -> dict:
    """Verify one signed receipt and every file it binds; return normalized facts."""
    root = Path(run_dir)
    receipt_path = _safe_member(root, receipt_ref, RECEIPT_ROOT)
    try:
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ExecutionReceiptError(f"executor receipt is not valid JSON: {receipt_ref}") from exc
    if not isinstance(receipt, dict):
        raise ExecutionReceiptError(f"executor receipt must be an object: {receipt_ref}")
    _validate_schema(receipt, "executor_receipt.schema.json", "executor receipt")

    if receipt["run_id"] != expected_run_id:
        raise ExecutionReceiptError(
            f"executor receipt run_id mismatch: {receipt['run_id']!r} != {expected_run_id!r}"
        )
    command_hash = sha256_bytes(canonical_json_bytes(receipt["command"]["argv"]))
    if not hmac.compare_digest(command_hash, receipt["command"]["command_hash"]):
        raise ExecutionReceiptError(
            f"executor receipt command hash mismatch for job {receipt['job_id']!r}"
        )
    started = _parse_time(receipt["started_at"], "started_at")
    finished = _parse_time(receipt["finished_at"], "finished_at")
    if finished < started:
        raise ExecutionReceiptError(
            f"executor receipt finished before it started for job {receipt['job_id']!r}"
        )

    key_id = receipt["attestation"]["key_id"]
    resolver = key_resolver or _default_key_resolver
    public_key_bytes = resolver(key_id)
    if not public_key_bytes:
        raise ExecutionReceiptError(
            f"no executor trust public key is configured for key_id {key_id!r}"
        )
    try:
        signature = base64.b64decode(
            receipt["attestation"]["signature"].removeprefix("ed25519:"), validate=True
        )
        Ed25519PublicKey.from_public_bytes(public_key_bytes).verify(
            signature, receipt_attestation_message(receipt)
        )
    except (ValueError, InvalidSignature) as exc:
        raise ExecutionReceiptError(
            f"executor receipt attestation failed for job {receipt['job_id']!r}"
        ) from exc

    stdout = _verify_file_binding(root, receipt["stdout"])
    stderr = _verify_file_binding(root, receipt["stderr"])
    result_files = [
        _verify_file_binding(root, binding) for binding in receipt["result_files"]
    ]
    return {
        "receipt_ref": str(receipt_ref).replace("\\", "/"),
        "receipt_sha256": sha256_file(receipt_path),
        "job_id": receipt["job_id"],
        "condition_id": receipt["condition_id"],
        "seed": receipt["seed"],
        "command_hash": receipt["command"]["command_hash"],
        "code_hash": receipt["code_hash"],
        "config_hash": receipt["config_hash"],
        "data_hash": receipt["data_hash"],
        "exit_status": receipt["exit_status"],
        "started_at": receipt["started_at"],
        "finished_at": receipt["finished_at"],
        "attestation_key_id": key_id,
        "stdout": stdout,
        "stderr": stderr,
        "result_files": result_files,
    }


def build_execution_import(
    run_dir: str | Path,
    receipt_refs: Iterable[str],
    *,
    run_id: str,
    created_at: str,
    key_resolver: Callable[[str], bytes | None] | None = None,
) -> dict:
    refs = [str(ref) for ref in receipt_refs]
    if not refs:
        raise ExecutionReceiptError("provisional execution requires at least one executor receipt")
    verified = [
        verify_executor_receipt(
            run_dir, ref, expected_run_id=run_id, key_resolver=key_resolver
        )
        for ref in refs
    ]
    job_ids = [row["job_id"] for row in verified]
    if len(job_ids) != len(set(job_ids)):
        raise ExecutionReceiptError("duplicate job_id in executor receipt import")
    pairs = [(row["condition_id"], row["seed"]) for row in verified]
    if len(pairs) != len(set(pairs)):
        raise ExecutionReceiptError(
            "duplicate condition_id/seed binding in executor receipt import"
        )
    verified.sort(key=lambda row: row["job_id"])
    core = {
        "manifest_version": IMPORT_VERSION,
        "source_boundary": "attested-non-llm-executor",
        "run_id": run_id,
        "created_at": created_at,
        "receipts": verified,
    }
    manifest = {**core, "import_id": sha256_bytes(canonical_json_bytes(core))}
    _validate_schema(
        manifest, "execution_import_manifest.schema.json", "execution import manifest"
    )
    return manifest


def import_note_payload(manifest: dict) -> dict:
    refs: list[str] = []
    for receipt in manifest["receipts"]:
        refs.append(receipt["receipt_ref"])
        refs.extend(row["path"] for row in receipt["result_files"])
        refs.extend((receipt["stdout"]["path"], receipt["stderr"]["path"]))
    return {
        "title": "Verified non-LLM execution import",
        "body": canonical_json_bytes(manifest).decode("utf-8"),
        "refs": list(dict.fromkeys(refs)),
    }


def load_import_manifest(run_dir: str | Path) -> dict:
    path = Path(run_dir) / IMPORT_ARTIFACT_REL
    try:
        artifact = json.loads(path.read_text(encoding="utf-8"))
        if artifact.get("artifact_type") != "note":
            raise KeyError("artifact_type")
        if artifact.get("created_by") != "execution-receipt-importer":
            raise KeyError("created_by")
        manifest = json.loads(artifact["payload"]["body"])
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise ExecutionReceiptError(
            f"verified execution import artifact is missing or malformed: "
            f"{IMPORT_ARTIFACT_REL.as_posix()}"
        ) from exc
    if not isinstance(manifest, dict):
        raise ExecutionReceiptError("execution import manifest body must be an object")
    _validate_schema(
        manifest, "execution_import_manifest.schema.json", "execution import manifest"
    )
    return manifest


def reverify_execution_import(
    run_dir: str | Path,
    *,
    expected_run_id: str,
    key_resolver: Callable[[str], bytes | None] | None = None,
) -> dict:
    """Re-open receipts and files, then require byte-equivalent derived facts."""
    stored = load_import_manifest(run_dir)
    if stored["run_id"] != expected_run_id:
        raise ExecutionReceiptError("execution import manifest is bound to a different run")
    rebuilt = build_execution_import(
        run_dir,
        [row["receipt_ref"] for row in stored["receipts"]],
        run_id=expected_run_id,
        created_at=stored["created_at"],
        key_resolver=key_resolver,
    )
    if not hmac.compare_digest(canonical_json_bytes(stored), canonical_json_bytes(rebuilt)):
        raise ExecutionReceiptError(
            "execution import manifest no longer matches freshly verified receipts/files"
        )
    return rebuilt


def validate_records_against_import(records: list[dict], manifest: dict) -> None:
    """Bind every provisional record to one successful, hash-identical executor job."""
    provisional = [row for row in records if row.get("status") == "provisional"]
    receipts = {
        (row["condition_id"], row["seed"]): row for row in manifest["receipts"]
    }
    seen: set[tuple[str, int | None]] = set()
    for index, record in enumerate(provisional, start=1):
        provenance = record.get("provenance") or {}
        key = (str(record.get("condition_id") or ""), provenance.get("seed"))
        receipt = receipts.get(key)
        if receipt is None:
            raise ExecutionReceiptError(
                f"provisional run_record {index} has no executor receipt for {key}"
            )
        if receipt["exit_status"] != 0:
            raise ExecutionReceiptError(
                f"provisional run_record {index} binds failed executor job {receipt['job_id']!r}"
            )
        expected = {
            "config_hash": receipt["config_hash"],
            "data_hash": receipt["data_hash"],
            "git_sha": receipt["code_hash"],
        }
        for field, truth in expected.items():
            if provenance.get(field) != truth:
                raise ExecutionReceiptError(
                    f"provisional run_record {index} {field} does not match executor receipt"
                )
        if not any(row.get("role") == "raw_result_rows" for row in receipt["result_files"]):
            raise ExecutionReceiptError(
                f"executor job {receipt['job_id']!r} has no raw_result_rows result file"
            )
        if key in seen:
            raise ExecutionReceiptError(f"duplicate provisional run_record binding for {key}")
        seen.add(key)

    receipt_result_keys = {
        (row["condition_id"], row["seed"])
        for row in manifest["receipts"]
        if any(item.get("role") == "raw_result_rows" for item in row["result_files"])
    }
    if seen != receipt_result_keys:
        extras = sorted(receipt_result_keys - seen, key=str)
        raise ExecutionReceiptError(
            f"executor receipts with raw results have no provisional run_record: {extras}"
        )


def receipt_bound_raw_rows(run_dir: str | Path, manifest: dict) -> list[dict]:
    """Load raw rows only from freshly hash-verified receipt-bound result files."""
    root = Path(run_dir)
    rows: list[dict] = []
    row_ids: set[str] = set()
    for receipt in manifest["receipts"]:
        for binding in receipt["result_files"]:
            if binding.get("role") != "raw_result_rows":
                continue
            path = _safe_member(root, binding["path"], RESULT_ROOT)
            if sha256_file(path) != binding["sha256"]:
                raise ExecutionReceiptError(
                    f"raw result file changed after import: {binding['path']!r}"
                )
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                raise ExecutionReceiptError(
                    f"raw result file is not valid JSON: {binding['path']!r}"
                ) from exc
            file_rows = payload.get("raw_result_rows") if isinstance(payload, dict) else payload
            if not isinstance(file_rows, list) or not file_rows:
                raise ExecutionReceiptError(
                    f"raw result file has no raw_result_rows: {binding['path']!r}"
                )
            for row in file_rows:
                if not isinstance(row, dict):
                    raise ExecutionReceiptError("receipt-bound raw result row is not an object")
                if row.get("job_id") != receipt["job_id"]:
                    raise ExecutionReceiptError("raw result row job_id does not match its receipt")
                if row.get("condition_id") != receipt["condition_id"]:
                    raise ExecutionReceiptError(
                        "raw result row condition_id does not match its receipt"
                    )
                if row.get("seed") != receipt["seed"]:
                    raise ExecutionReceiptError("raw result row seed does not match its receipt")
                row_id = str(row.get("row_id") or "")
                if not row_id or row_id in row_ids:
                    raise ExecutionReceiptError(
                        "raw result rows require globally unique non-empty row_id values"
                    )
                row_ids.add(row_id)
                rows.append(dict(row))
    if not rows:
        raise ExecutionReceiptError("verified executor receipts contain no raw result rows")
    return rows


def verified_binding_index(manifest: dict) -> dict[str, dict]:
    """Return artifact bindings eligible for deterministic failure-attribution gates."""
    bindings: dict[str, dict] = {}
    for receipt in manifest["receipts"]:
        for row in receipt["result_files"]:
            bindings[row["path"]] = {
                "sha256": row["sha256"],
                "role": row.get("role"),
                "job_id": receipt["job_id"],
                "exit_status": receipt["exit_status"],
            }
    return bindings


__all__ = [
    "ExecutionReceiptError",
    "IMPORT_ARTIFACT_REL",
    "build_execution_import",
    "canonical_json_bytes",
    "import_note_payload",
    "load_import_manifest",
    "receipt_attestation_message",
    "receipt_bound_raw_rows",
    "reverify_execution_import",
    "sha256_bytes",
    "sha256_file",
    "trust_public_key_env_name",
    "validate_records_against_import",
    "verified_binding_index",
    "verify_executor_receipt",
]
