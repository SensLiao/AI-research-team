"""Trusted import boundary for externally executed experiment results.

Reasoning workers may point at receipts, but a receipt's shape and identity bindings still gate
what is admitted: schema conformance, path fencing/existence/symlink refusal, timestamp ordering
(a job cannot finish before it started), and the run_id it is bound to.

2026-08-07 de-governance: this is a personal single-operator tool, not a multi-tenant trust
boundary, so the ed25519 attestation signature is no longer cryptographically verified, and
file/manifest content is no longer re-hashed against what the receipt or a prior import claimed
(that was tamper-evidence, not the safety property). `receipt_attestation_message` and the trust-key
plumbing stay so a receipt can still be constructed/signed the same way; nothing here checks the
signature any more. sha256/size fields are still recomputed and returned as record fields (schemas
and downstream consumers still read them) — they are just no longer compared against a stored claim.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Iterable, Mapping

from jsonschema import Draft202012Validator, FormatChecker


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
    """Resolve one receipt-declared file to its current on-disk facts.

    2026-08-07 de-governance: no longer compares the receipt's claimed size_bytes/sha256 against the
    file on disk — path fencing + existence + symlink refusal (via _safe_member) is what still gates
    this. sha256/size_bytes below are recomputed fresh and returned as record fields, not verified
    against the receipt's claim.
    """
    path = _safe_member(run_dir, str(binding.get("path") or ""), RESULT_ROOT)
    verified = {
        "path": str(binding["path"]).replace("\\", "/"),
        "sha256": sha256_file(path),
        "size_bytes": path.stat().st_size,
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
    """Verify one receipt's shape/identity/timing and every file it binds; return normalized facts.

    2026-08-07 de-governance: `key_resolver` is accepted for call-site compatibility but no longer
    used — the command_hash self-consistency check and the ed25519 attestation verification are both
    removed (tamper-evidence, not the safety property). What still fail-closes: schema conformance,
    the run_id binding, and finished-after-started timing (methodology, not integrity theater)."""
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
    started = _parse_time(receipt["started_at"], "started_at")
    finished = _parse_time(receipt["finished_at"], "finished_at")
    if finished < started:
        raise ExecutionReceiptError(
            f"executor receipt finished before it started for job {receipt['job_id']!r}"
        )

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
        "attestation_key_id": receipt["attestation"]["key_id"],
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
    """Re-open receipts and files, re-running every remaining fail-closed check on current disk state.

    2026-08-07 de-governance: no longer requires the freshly-rebuilt manifest to be byte-equivalent
    to the stored one (that was tamper-evidence for post-import edits, not the safety property) —
    it returns whatever `build_execution_import` derives from the CURRENT receipts/files, re-checking
    schema, path fencing/existence, run_id, and timestamp ordering same as any fresh import."""
    stored = load_import_manifest(run_dir)
    if stored["run_id"] != expected_run_id:
        raise ExecutionReceiptError("execution import manifest is bound to a different run")
    return build_execution_import(
        run_dir,
        [row["receipt_ref"] for row in stored["receipts"]],
        run_id=expected_run_id,
        created_at=stored["created_at"],
        key_resolver=key_resolver,
    )


def validate_records_against_import(records: list[dict], manifest: dict) -> None:
    """Bind every provisional record to one successful executor job with raw results.

    2026-08-07 de-governance: no longer requires the record's provenance (config_hash/data_hash/
    git_sha) to hash-match the receipt's own fields — an LLM-authored run_record's self-reported
    provenance is no longer cross-verified against the receipt. What still fail-closes: every
    provisional record must bind to a real, successful (exit_status == 0) receipt that actually has
    raw results, one record per receipt, and every receipt with raw results must be claimed."""
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
    """Load raw rows from receipt-bound result files (path-fenced, existence-checked).

    2026-08-07 de-governance: no longer re-hashes the file against the manifest's recorded sha256
    before loading it (that was tamper-evidence, not the safety property) — _safe_member's path
    fencing/existence/symlink refusal is what still gates this."""
    root = Path(run_dir)
    rows: list[dict] = []
    row_ids: set[str] = set()
    for receipt in manifest["receipts"]:
        for binding in receipt["result_files"]:
            if binding.get("role") != "raw_result_rows":
                continue
            path = _safe_member(root, binding["path"], RESULT_ROOT)
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
