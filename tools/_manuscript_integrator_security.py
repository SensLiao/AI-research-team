"""Private fail-closed validators used by manuscript integration.

This module owns descriptor-stable input reads, bounded JSON repair checks,
run/receipt binding, and durable-output secret scanning.  It has no publishing
authority and deliberately receives the caller's typed ``fail`` function.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import stat
from pathlib import Path
from typing import Any, Callable, Mapping, Pattern, Sequence
from xml.etree import ElementTree

from research_agent_teams.tools.manuscript_contract import canonical_contract_hash
from research_agent_teams.tools.manuscript_security import (
    ManuscriptPathViolation,
    ManuscriptSecretViolation,
    scan_persisted_text,
    validate_run_owned_path,
)
from research_agent_teams.tools.validate_artifact import validate_payload


_JSON_SCALAR_RE = re.compile(
    r'"(?:\\.|[^"\\])*"|-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?|true|false|null'
)
_DEFAULT_SECRET_PATTERNS: dict[str, Pattern[str]] = {
    "private_key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "credential_url": re.compile(r"[A-Za-z][A-Za-z0-9+.-]*://[^\s/:]+:[^\s/@]+@"),
    "aws_access_key": re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    "github_token": re.compile(r"\bgh(?:p|o|u|s|r)_[A-Za-z0-9]{20,}\b"),
}
_DEFAULT_SECRET_BYTE_PATTERNS = {
    name: re.compile(pattern.pattern.encode("ascii"), pattern.flags & ~re.UNICODE)
    for name, pattern in _DEFAULT_SECRET_PATTERNS.items()
}
_TRUSTED_ASSET_INPUT_KINDS = {
    "RESULT": "FROZEN_RESULT",
    "EVIDENCE": "EXTERNAL_EVIDENCE",
    "ASSET": "DIRECTOR_ASSET",
    "TEMPLATE": "SOURCE_DATA",
    "VENUE_RULE": "SOURCE_DATA",
    "TOKEN_OVERLAY": "SOURCE_DATA",
}
_SAFE_SVG_ELEMENTS = {
    "svg", "g", "defs", "title", "desc", "path", "rect", "circle", "ellipse",
    "line", "polyline", "polygon", "text", "tspan", "clipPath", "mask",
    "linearGradient", "radialGradient", "stop", "pattern", "symbol", "use",
}
_SAFE_SVG_ATTRIBUTES = {
    "xmlns", "version", "viewBox", "width", "height", "x", "y", "x1", "x2",
    "y1", "y2", "cx", "cy", "r", "rx", "ry", "d", "points", "fill",
    "fill-opacity", "fill-rule", "stroke", "stroke-width", "stroke-opacity",
    "stroke-linecap", "stroke-linejoin", "stroke-dasharray", "stroke-dashoffset",
    "opacity", "transform", "id", "class", "clip-path", "mask", "offset",
    "stop-color", "stop-opacity", "gradientUnits", "gradientTransform",
    "spreadMethod", "fx", "fy", "font-family", "font-size", "font-weight", "font-style",
    "text-anchor", "dominant-baseline", "aria-label", "role", "href",
}
_DANGEROUS_SVG_VALUE = re.compile(r"(?:javascript|vbscript|data|file|https?):|expression\s*\(", re.I)


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def _canonical_hash(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _hash_without(value: Mapping[str, Any], field: str) -> str:
    return _canonical_hash({key: item for key, item in value.items() if key != field})


def _bytes_hash(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def stable_bytes(path: Path, *, fail: Callable[..., None],
                 expected_sha256: str | None = None) -> bytes:
    """Read one regular file through a no-follow descriptor and detect swaps."""
    flags = os.O_RDONLY | int(getattr(os, "O_BINARY", 0)) | int(getattr(os, "O_NOFOLLOW", 0))
    try:
        before_path = path.lstat()
        descriptor = os.open(path, flags)
        try:
            before_fd = os.fstat(descriptor)
            if not stat.S_ISREG(before_fd.st_mode) or not os.path.samestat(before_path, before_fd):
                fail("UNSTABLE_INPUT", "input path changed before its secure read", path.as_posix())
            chunks = []
            while True:
                chunk = os.read(descriptor, 1024 * 1024)
                if not chunk:
                    break
                chunks.append(chunk)
            after_fd = os.fstat(descriptor)
        finally:
            os.close(descriptor)
        after_path = path.lstat()
    except OSError as exc:
        fail("UNSTABLE_INPUT", f"input could not be read safely: {type(exc).__name__}", path.as_posix())
    if not os.path.samestat(before_fd, after_fd) or not os.path.samestat(after_fd, after_path):
        fail("UNSTABLE_INPUT", "input path changed during its secure read", path.as_posix())
    data = b"".join(chunks)
    if expected_sha256 is not None and _bytes_hash(data) != expected_sha256:
        fail("HASH_MISMATCH", "securely read input bytes do not match their frozen hash", path.as_posix())
    return data


def _json_tokens(text: str) -> tuple[str, ...]:
    return tuple(match.group(0) for match in _JSON_SCALAR_RE.finditer(text))


def _format_skeleton(text: str) -> str:
    output, quoted, escaped = [], False, False
    for character in text:
        if quoted:
            output.append(character)
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                quoted = False
        elif character == '"':
            quoted = True
            output.append(character)
        elif character != "," and not character.isspace():
            output.append(character)
    return "".join(output)


def _object_without_duplicates(pairs: list[tuple[str, Any]],
                               *, fail: Callable[..., None]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            fail("DUPLICATE_JSON_KEY", "section bundle JSON contains a duplicate object key", key)
        value[key] = item
    return value


def read_json(path: Path, *, format_repair: Callable[[str, list[str], int], str] | None,
              fail: Callable[..., None], max_format_repairs: int) -> tuple[dict[str, Any], int, bytes, str]:
    raw = stable_bytes(path, fail=fail)
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        fail("BUNDLE_ENCODING_INVALID", "section bundle must be UTF-8", path.as_posix())
    current = text
    errors: list[str] = []
    for attempt in range(max_format_repairs + 1):
        try:
            value = json.loads(
                current, object_pairs_hook=lambda pairs: _object_without_duplicates(pairs, fail=fail)
            )
        except json.JSONDecodeError as exc:
            errors = [f"line {exc.lineno}, column {exc.colno}: {exc.msg}"]
            if attempt == max_format_repairs:
                code = "REPAIR_LIMIT_EXCEEDED" if format_repair else "BUNDLE_INVALID_JSON"
                fail(code, "section bundle is not valid JSON after the bounded repair budget", path.as_posix())
            if format_repair is None:
                fail("BUNDLE_INVALID_JSON", errors[0], path.as_posix())
            repaired = format_repair(current, list(errors), attempt + 1)
            if not isinstance(repaired, str):
                fail("FORMAT_REPAIR_INVALID", "format repair must return JSON text", path.as_posix())
            if (_json_tokens(repaired) != _json_tokens(current)
                    or _format_skeleton(repaired) != _format_skeleton(current)):
                fail(
                    "FORMAT_REPAIR_CHANGED_CONTENT",
                    "format repair changed scalar content instead of punctuation or whitespace",
                    path.as_posix(),
                )
            current = repaired
            continue
        if not isinstance(value, dict):
            fail("BUNDLE_INVALID_JSON", "section bundle must decode to an object", path.as_posix())
        return value, attempt, raw, _bytes_hash(current.encode("utf-8"))
    raise AssertionError("bounded JSON parser exhausted without returning")


def safe_run_file(reference: str | Path, *, run_root: Path, owned_roots: Sequence[Path],
                  fail: Callable[..., None], expected_sha256: str | None = None) -> Path:
    try:
        result = validate_run_owned_path(
            reference, run_root=run_root, purpose="read", owned_output_roots=owned_roots
        )
    except ManuscriptPathViolation as exc:
        fail("UNSAFE_INPUT_PATH", str(exc), os.fspath(reference))
    path = Path(result["path"])
    if expected_sha256 is not None:
        stable_bytes(path, fail=fail, expected_sha256=expected_sha256)
    return path


def validate_contract(contract: Mapping[str, Any], run_root: Path,
                      *, fail: Callable[..., None]) -> dict[str, Any]:
    if not isinstance(contract, Mapping):
        fail("CONTRACT_INVALID", "manuscript contract must be an object")
    frozen = copy.deepcopy(dict(contract))
    errors = validate_payload("manuscript_contract", frozen)
    if errors:
        fail("CONTRACT_INVALID", "; ".join(errors[:5]))
    if frozen["run_id"] != run_root.name:
        fail("RUN_ID_MISMATCH", "contract run_id does not identify the active run")
    if canonical_contract_hash(frozen) != frozen["manuscript_snapshot_sha256"]:
        fail("CONTRACT_HASH_MISMATCH", "frozen manuscript snapshot hash does not verify")
    for row in frozen["dependency_slices"]:
        if _hash_without(row, "slice_sha256") != row["slice_sha256"]:
            fail(
                "DEPENDENCY_SLICE_HASH_MISMATCH",
                "declared dependency slice hash does not verify",
                row["slice_id"],
            )
    return frozen


def require_verification(verifier: Callable[[Mapping[str, Any]], Mapping[str, Any]] | None,
                         facts: dict[str, Any], *, fail: Callable[..., None],
                         missing: str, invalid: str) -> None:
    if verifier is None:
        fail(missing, "an external authority verifier is required")
    try:
        verdict = verifier(copy.deepcopy(facts))
    except Exception:
        fail(invalid, "external authority rejected the bound facts")
    if (not isinstance(verdict, Mapping) or verdict.get("verified") is not True
            or any(verdict.get(key) != value for key, value in facts.items())):
        fail(invalid, "external authority did not return the exact bound facts")


def receipt_row(bundle: dict[str, Any], *, bundle_ref: str, run_root: Path,
                stage: str, fail: Callable[..., None]) -> dict[str, Any]:
    authorization = bundle["authorization_receipt"]
    receipt_path = safe_run_file(
        authorization["ref"], run_root=run_root, owned_roots=(run_root / "inbox",), fail=fail
    )
    receipt_bytes = stable_bytes(receipt_path, fail=fail)
    try:
        receipt = json.loads(receipt_bytes.decode("utf-8"))
    except (UnicodeError, ValueError):
        fail(
            "AUTHORIZATION_RECEIPT_INVALID",
            "scheduler receipt is not valid UTF-8 JSON",
            authorization["ref"],
        )
    if receipt.get("contract_version") != "panel-dispatch/v1" or receipt.get("stage") != stage:
        fail("UNAUTHORIZED_STAGE", "scheduler receipt does not authorize the requested stage", authorization["ref"])
    rows = [
        row for row in receipt.get("authorizations", [])
        if isinstance(row, dict) and bundle_ref in {row.get("output"), row.get("logical_output")}
    ]
    if len(rows) != 1:
        fail("AUTHORIZATION_MISMATCH", "bundle has no unique scheduler authorization", bundle_ref)
    row = rows[0]
    if row.get("agent") != bundle["worker_role"] or authorization["worker_role"] != bundle["worker_role"]:
        fail("AUTHORIZATION_MISMATCH", "authorization role does not match bundle worker", bundle_ref)
    if row.get("authorization_kind") not in {"initial", "supplement"}:
        fail("AUTHORIZATION_MISMATCH", "authorization kind is invalid", bundle_ref)
    declared_hash = authorization["sha256"]
    if declared_hash not in {_canonical_hash(row), _bytes_hash(receipt_bytes)}:
        fail("AUTHORIZATION_HASH_MISMATCH", "immutable authorization row hash does not verify", bundle_ref)
    return row


def verify_result(reference: str, contract: dict[str, Any], run_root: Path,
                  verifier: Callable[[Mapping[str, Any]], Mapping[str, Any]] | None,
                  *, fail: Callable[..., None]) -> None:
    rows = {row["ref"]: row for row in contract["result_refs"]}
    row = rows.get(reference)
    if row is None:
        fail("UNKNOWN_RESULT", "bundle or asset cites an undeclared result", reference)
    if row["status"] != "FROZEN":
        fail("RESULT_RECEIPT_UNVERIFIED", "result is not frozen", reference)
    path = safe_run_file(reference, run_root=run_root, owned_roots=(run_root,), fail=fail)
    if _bytes_hash(stable_bytes(path, fail=fail)) != row["sha256"]:
        fail("STALE_RESULT", "frozen result bytes no longer match the contract", reference)
    receipt_path = safe_run_file(row["receipt_ref"], run_root=run_root, owned_roots=(run_root,), fail=fail)
    if _bytes_hash(stable_bytes(receipt_path, fail=fail)) != row["receipt_sha256"]:
        fail("RESULT_RECEIPT_UNVERIFIED", "result receipt bytes do not match the contract", reference)
    facts = {
        "result_ref": reference, "result_sha256": row["sha256"],
        "receipt_ref": row["receipt_ref"], "receipt_sha256": row["receipt_sha256"],
        "run_id": contract["run_id"],
    }
    require_verification(
        verifier, facts, fail=fail,
        missing="RESULT_RECEIPT_UNVERIFIED", invalid="RESULT_RECEIPT_UNVERIFIED",
    )


def validate_asset_source_inputs(
    source_inputs: Sequence[Mapping[str, Any]], *, source_inventory: Mapping[str, Mapping[str, Any]],
    provenance_kind: str, contract: dict[str, Any], run_root: Path,
    result_verifier: Callable[[Mapping[str, Any]], Mapping[str, Any]] | None,
    fail: Callable[..., None],
) -> list[dict[str, str]]:
    """Bind every manifest source to its trusted frozen kind, bytes, and receipt."""
    trusted: list[dict[str, str]] = []
    for source_input in source_inputs:
        frozen = source_inventory.get(source_input["ref"])
        expected_kind = _TRUSTED_ASSET_INPUT_KINDS.get(frozen.get("kind")) if frozen else None
        if frozen is None or frozen["sha256"] != source_input["sha256"]:
            fail("ASSET_SOURCE_INPUT_MISMATCH", "asset input hash is absent or stale")
        if expected_kind is None or source_input["kind"] != expected_kind:
            fail(
                "ASSET_SOURCE_KIND_MISMATCH",
                "asset input kind differs from the trusted frozen source inventory",
                source_input["ref"],
            )
        row = {"ref": frozen["ref"], "sha256": frozen["sha256"], "kind": frozen["kind"]}
        trusted.append(row)
        if frozen["kind"] == "RESULT":
            verify_result(source_input["ref"], contract, run_root, result_verifier, fail=fail)
        elif frozen["kind"] == "ASSET":
            if provenance_kind != "EXTERNAL":
                fail(
                    "ASSET_SOURCE_PATH_MISSING",
                    "generated assets cannot consume a director input without an explicit input path",
                    source_input["ref"],
                )
        else:
            input_path = safe_run_file(
                source_input["ref"], run_root=run_root, owned_roots=(run_root,), fail=fail
            )
            stable_bytes(input_path, fail=fail, expected_sha256=source_input["sha256"])
    return trusted


def validate_svg(data: bytes, asset_ref: str, *, fail: Callable[..., None]) -> None:
    """Accept a small inert SVG subset; reject scripting, foreign content, and external refs."""
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        fail("UNSAFE_ASSET_CONTENT", "SVG asset is not UTF-8", asset_ref)
    if re.search(r"<!DOCTYPE|<!ENTITY|<\?", text, re.I):
        fail("UNSAFE_ASSET_CONTENT", "SVG declarations and processing instructions are not allowed", asset_ref)
    try:
        root = ElementTree.fromstring(text)
    except ElementTree.ParseError:
        fail("UNSAFE_ASSET_CONTENT", "SVG is not well-formed XML", asset_ref)
    for element in root.iter():
        tag = element.tag.rsplit("}", 1)[-1] if isinstance(element.tag, str) else ""
        if tag not in _SAFE_SVG_ELEMENTS:
            fail("UNSAFE_ASSET_CONTENT", f"SVG element {tag!r} is not allowed", asset_ref)
        for qualified_name, value in element.attrib.items():
            name = qualified_name.rsplit("}", 1)[-1]
            if name.lower().startswith("on") or name not in _SAFE_SVG_ATTRIBUTES:
                fail("UNSAFE_ASSET_CONTENT", f"SVG attribute {name!r} is not allowed", asset_ref)
            stripped = value.strip()
            if name == "font-style" and stripped not in {"normal", "italic", "oblique"}:
                fail("UNSAFE_ASSET_CONTENT", "SVG font-style must be a static style keyword", asset_ref)
            if _DANGEROUS_SVG_VALUE.search(stripped):
                fail("UNSAFE_ASSET_CONTENT", "SVG contains an active or external value", asset_ref)
            if name == "href" and not stripped.startswith("#"):
                fail("UNSAFE_ASSET_CONTENT", "SVG href must be a local fragment", asset_ref)
            for reference in re.findall(r"url\(([^)]+)\)", stripped, re.I):
                if not reference.strip(" \t\r\n'\"").startswith("#"):
                    fail("UNSAFE_ASSET_CONTENT", "SVG URL must be a local fragment", asset_ref)


def scan_candidate_text(files: Mapping[str, bytes], *, fail: Callable[..., None],
                        sentinels: Mapping[str, str] | None,
                        patterns: Mapping[str, str | Pattern[str]] | None) -> None:
    combined_patterns = dict(_DEFAULT_SECRET_PATTERNS)
    combined_patterns.update(patterns or {})
    for path, data in files.items():
        for name, pattern in _DEFAULT_SECRET_BYTE_PATTERNS.items():
            if pattern.search(data):
                fail("SECRET_LEAKAGE", f"default secret pattern {name!r} found in durable output", path)
        for name, sentinel in (sentinels or {}).items():
            if sentinel and sentinel.encode("utf-8") in data:
                fail("SECRET_LEAKAGE", f"secret sentinel {name!r} found in durable output", path)
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            if Path(path).suffix.lower() in {".tex", ".bib", ".json", ".svg", ".txt", ".md"}:
                fail("TEXT_ENCODING_INVALID", "durable text is not complete UTF-8", path)
            for name, pattern in (patterns or {}).items():
                raw = pattern.pattern if hasattr(pattern, "pattern") else str(pattern)
                flags = getattr(pattern, "flags", 0) & ~re.UNICODE
                try:
                    byte_pattern = re.compile(raw.encode("ascii"), flags)
                except (UnicodeEncodeError, ValueError, re.error):
                    fail("SECRET_SCAN_INDETERMINATE", f"pattern {name!r} cannot scan binary bytes", path)
                if byte_pattern.search(data):
                    fail("SECRET_LEAKAGE", f"secret pattern {name!r} found in durable output", path)
            continue
        try:
            scan_persisted_text(path, text, sentinels=sentinels, patterns=combined_patterns)
        except ManuscriptSecretViolation as exc:
            fail("SECRET_LEAKAGE", str(exc), path)
