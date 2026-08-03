"""Fail-closed import boundary for provider-observed model-call receipts.

The research control plane can prepare a one-time challenge, but it cannot
observe or attest a provider call.  A host adapter outside every reasoning
worker must bind the challenge to the provider response, measure elapsed time
with a monotonic clock, and sign the resulting receipt.  This module exposes no
signing function: it accepts only an Ed25519 public key, verifies the signed
receipt and bound author artifact, and returns normalized provider-attested
facts.

Requested runtime settings are intentionally separate from observed runtime
facts.  Environment values, worker self-reports, token estimates, and wall-clock
timing assembled after the call are never upgraded to provider evidence.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import secrets
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Mapping, MutableMapping

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from jsonschema import Draft202012Validator, FormatChecker


PROVIDER_CHALLENGE_VERSION = "provider-call-challenge/v1"
PROVIDER_RECEIPT_VERSION = "provider-call-receipt/v1"
PROVIDER_PRODUCER_KIND = "provider-host-adapter"
_SCHEMA_PATH = Path(__file__).resolve().parent.parent / "schemas" / "provider_call_receipt.schema.json"
_SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_NONCE_RE = re.compile(r"^[A-Za-z0-9_-]{32,256}$")


class ProviderCallReceiptError(ValueError):
    """A provider receipt, challenge binding, or artifact is untrusted."""


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _required_text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ProviderCallReceiptError(f"{label} must be a non-empty string")
    return value.strip()


def _safe_relative(value: Any, label: str) -> str:
    text = _required_text(value, label).replace("\\", "/")
    pure = PurePosixPath(text)
    if pure.is_absolute() or ".." in pure.parts or not pure.parts:
        raise ProviderCallReceiptError(f"{label} must be a safe relative path")
    if re.match(r"^[A-Za-z]:", text):
        raise ProviderCallReceiptError(f"{label} must not contain a drive-qualified path")
    return pure.as_posix()


def create_provider_call_challenge(
    *,
    run_id: str,
    task_id: str,
    stage: str,
    worker_id: str,
    dispatch_spec: Mapping[str, Any],
    artifact_path: str,
    nonce: str | None = None,
) -> dict[str, str]:
    """Create an unsigned, immutable challenge for one future provider call.

    The challenge is safe for the control plane to create because it contains
    no execution claim.  ``nonce`` is injectable solely for deterministic unit
    tests; production callers should leave it unset so ``secrets`` supplies it.
    """
    if not isinstance(dispatch_spec, Mapping) or not dispatch_spec:
        raise ProviderCallReceiptError("dispatch_spec must be a non-empty mapping")
    challenge_nonce = nonce or secrets.token_hex(32)
    if not isinstance(challenge_nonce, str) or not _NONCE_RE.fullmatch(challenge_nonce):
        raise ProviderCallReceiptError("challenge nonce must be 32-256 URL-safe characters")
    core = {
        "challenge_version": PROVIDER_CHALLENGE_VERSION,
        "run_id": _required_text(run_id, "run_id"),
        "task_id": _required_text(task_id, "task_id"),
        "stage": _required_text(stage, "stage"),
        "worker_id": _required_text(worker_id, "worker_id"),
        "nonce": challenge_nonce,
        "dispatch_spec_sha256": sha256_bytes(canonical_json_bytes(dict(dispatch_spec))),
        "artifact_path": _safe_relative(artifact_path, "artifact_path"),
    }
    invocation_seed = canonical_json_bytes(core)
    return {
        **core,
        "invocation_id": "pcall-" + hashlib.sha256(invocation_seed).hexdigest(),
    }


def receipt_attestation_message(receipt: Mapping[str, Any]) -> bytes:
    """Canonical bytes signed by the out-of-process host adapter."""
    unsigned = dict(receipt)
    attestation = dict(unsigned.get("attestation") or {})
    attestation.pop("signature", None)
    unsigned["attestation"] = attestation
    return canonical_json_bytes(unsigned)


def trust_public_key_env_name(key_id: str) -> str:
    token = re.sub(r"[^A-Za-z0-9]", "_", key_id).upper()
    return f"RAT_PROVIDER_RECEIPT_TRUST_PUBLIC_KEY_{token}"


def _default_key_resolver(key_id: str) -> bytes | None:
    encoded = os.environ.get(trust_public_key_env_name(key_id))
    if not encoded:
        return None
    try:
        value = base64.b64decode(encoded, validate=True)
    except (TypeError, ValueError) as exc:
        raise ProviderCallReceiptError(
            f"provider receipt public key {key_id!r} is not valid base64"
        ) from exc
    if len(value) != 32:
        raise ProviderCallReceiptError(
            f"provider receipt public key {key_id!r} must be 32 raw Ed25519 bytes"
        )
    return value


def _schema() -> dict[str, Any]:
    try:
        value = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ProviderCallReceiptError("provider call receipt schema is unavailable or invalid") from exc
    if not isinstance(value, dict):
        raise ProviderCallReceiptError("provider call receipt schema root must be an object")
    return value


def _validate_schema(receipt: Mapping[str, Any]) -> None:
    validator = Draft202012Validator(_schema(), format_checker=FormatChecker())
    errors = sorted(validator.iter_errors(receipt), key=lambda error: list(error.absolute_path))
    if errors:
        details = "; ".join(
            f"/{'/'.join(str(part) for part in error.absolute_path)}: {error.message}"
            for error in errors[:10]
        )
        raise ProviderCallReceiptError(f"provider call receipt schema BLOCK: {details}")


def _safe_member(root: Path, relative: Any, label: str) -> Path:
    rel = _safe_relative(relative, label)
    candidate = (root / Path(*PurePosixPath(rel).parts)).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ProviderCallReceiptError(f"{label} escapes the artifact root") from exc
    return candidate


def _parse_time(value: str, label: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise ProviderCallReceiptError(f"invalid {label}: {value!r}") from exc
    if parsed.tzinfo is None:
        raise ProviderCallReceiptError(f"{label} must include a timezone")
    return parsed


def _claim_replay_key(
    replay_guard: MutableMapping[str, str] | None,
    key: str,
    receipt_sha256: str,
) -> None:
    if replay_guard is None:
        return
    previous = replay_guard.get(key)
    if previous is not None and not hmac.compare_digest(previous, receipt_sha256):
        raise ProviderCallReceiptError(f"provider receipt replay conflict for {key}")
    replay_guard[key] = receipt_sha256


def verify_provider_call_receipt(
    artifact_root: str | Path,
    receipt_ref: str,
    *,
    expected_challenge: Mapping[str, Any],
    key_resolver: Callable[[str], bytes | None] | None = None,
    replay_guard: MutableMapping[str, str] | None = None,
) -> dict[str, Any]:
    """Verify one signed host receipt and return normalized observed usage.

    The returned ``status=PROVIDER_ATTESTED`` exists only after schema, challenge,
    signature, artifact, timing, token-total, and replay checks all succeed.
    There is deliberately no unobserved fallback here: callers that require
    usage must stop when the receipt or host callback is absent.
    """
    root = Path(artifact_root).resolve()
    receipt_path = _safe_member(root, receipt_ref, "receipt_ref")
    try:
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ProviderCallReceiptError(f"provider receipt is missing or invalid JSON: {receipt_ref}") from exc
    if not isinstance(receipt, dict):
        raise ProviderCallReceiptError("provider receipt root must be an object")
    _validate_schema(receipt)

    if expected_challenge.get("challenge_version") != PROVIDER_CHALLENGE_VERSION:
        raise ProviderCallReceiptError("expected challenge has an unknown contract version")
    for field in (
        "run_id",
        "task_id",
        "stage",
        "worker_id",
        "invocation_id",
        "nonce",
        "dispatch_spec_sha256",
    ):
        if receipt.get(field) != expected_challenge.get(field):
            raise ProviderCallReceiptError(f"provider receipt {field} does not match the frozen challenge")

    started = _parse_time(receipt["started_at"], "started_at")
    finished = _parse_time(receipt["finished_at"], "finished_at")
    if finished < started:
        raise ProviderCallReceiptError("provider receipt finished_at precedes started_at")

    observed = receipt["observed"]
    input_tokens = observed["input_tokens"]["value"]
    output_tokens = observed["output_tokens"]["value"]
    total_tokens = observed["total_tokens"]["value"]
    if total_tokens != input_tokens + output_tokens:
        raise ProviderCallReceiptError("provider receipt token totals are inconsistent")

    artifact = receipt["artifact"]
    expected_artifact = _safe_relative(expected_challenge.get("artifact_path"), "challenge artifact_path")
    if artifact["path"] != expected_artifact:
        raise ProviderCallReceiptError("provider receipt artifact path does not match the challenge")
    artifact_path = _safe_member(root, artifact["path"], "artifact.path")
    if not artifact_path.is_file():
        raise ProviderCallReceiptError("provider receipt bound artifact is missing")
    actual_artifact_sha = sha256_file(artifact_path)
    if not hmac.compare_digest(actual_artifact_sha, artifact["sha256"]):
        raise ProviderCallReceiptError("provider receipt artifact SHA-256 mismatch")
    if artifact_path.stat().st_size != artifact["size_bytes"]:
        raise ProviderCallReceiptError("provider receipt artifact size mismatch")

    key_id = receipt["attestation"]["key_id"]
    resolver = key_resolver or _default_key_resolver
    public_key = resolver(key_id)
    if not public_key:
        raise ProviderCallReceiptError(
            f"no trusted provider receipt public key is configured for key_id {key_id!r}"
        )
    if len(public_key) != 32:
        raise ProviderCallReceiptError("trusted provider receipt public key must be 32 bytes")
    try:
        signature = base64.b64decode(
            receipt["attestation"]["signature"].removeprefix("ed25519:"), validate=True
        )
        Ed25519PublicKey.from_public_bytes(public_key).verify(
            signature, receipt_attestation_message(receipt)
        )
    except (TypeError, ValueError, InvalidSignature) as exc:
        raise ProviderCallReceiptError("provider receipt Ed25519 attestation failed") from exc

    receipt_sha = sha256_file(receipt_path)
    _claim_replay_key(replay_guard, f"invocation:{receipt['invocation_id']}", receipt_sha)
    _claim_replay_key(replay_guard, f"nonce:{receipt['nonce']}", receipt_sha)
    _claim_replay_key(
        replay_guard, f"provider-request:{receipt['provider_request_id']}", receipt_sha
    )

    sources = {key: value["source"] for key, value in observed.items()}
    values = {key: value["value"] for key, value in observed.items()}
    return {
        "status": "PROVIDER_ATTESTED",
        "receipt_version": receipt["receipt_version"],
        "producer_kind": receipt["producer_kind"],
        "receipt_ref": _safe_relative(receipt_ref, "receipt_ref"),
        "receipt_sha256": receipt_sha,
        "run_id": receipt["run_id"],
        "task_id": receipt["task_id"],
        "stage": receipt["stage"],
        "worker_id": receipt["worker_id"],
        "invocation_id": receipt["invocation_id"],
        "dispatch_spec_sha256": receipt["dispatch_spec_sha256"],
        "provider_request_id": receipt["provider_request_id"],
        "requested": dict(receipt["requested"]),
        "observed": values,
        "observation_sources": sources,
        "started_at": receipt["started_at"],
        "finished_at": receipt["finished_at"],
        "artifact": {
            "path": artifact["path"],
            "sha256": artifact["sha256"],
            "size_bytes": artifact["size_bytes"],
        },
        "attestation": {
            "scheme": receipt["attestation"]["scheme"],
            "key_id": key_id,
            "signature_verified": True,
        },
    }


__all__ = [
    "PROVIDER_CHALLENGE_VERSION",
    "PROVIDER_PRODUCER_KIND",
    "PROVIDER_RECEIPT_VERSION",
    "ProviderCallReceiptError",
    "canonical_json_bytes",
    "create_provider_call_challenge",
    "receipt_attestation_message",
    "sha256_bytes",
    "sha256_file",
    "trust_public_key_env_name",
    "verify_provider_call_receipt",
]
