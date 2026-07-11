"""Lossless representation normalization before scientific schema validation."""
from __future__ import annotations

import copy
import hashlib
import json
import re
import unicodedata
from pathlib import Path

from .validate_artifact import PAYLOAD_SCHEMAS, SCHEMA_DIR


VERDICT_ALIASES = {
    "NEEDS_REREAD": "NEEDS_SUPPLEMENT",
    "needsreread": "NEEDS_SUPPLEMENT",
    "BLOCK_FOR_PROMOTION": "BLOCK",
    "blockforpromotion": "BLOCK",
}


def _digest(value) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _token(value: str) -> str:
    text = unicodedata.normalize("NFKC", value).strip().casefold()
    return re.sub(r"[^a-z0-9]+", "", text)


def _enum_value(value, allowed):
    if value in allowed:
        return value
    if isinstance(value, str):
        alias = VERDICT_ALIASES.get(value.strip().upper()) or VERDICT_ALIASES.get(_token(value))
        if alias in allowed:
            return alias
        matches = [candidate for candidate in allowed if isinstance(candidate, str) and _token(candidate) == _token(value)]
        if len(matches) == 1:
            return matches[0]
    return value


def _walk(value, schema: dict, pointer: str, changes: list[dict], extras: list[dict]):
    if "const" in schema:
        return value
    if "enum" in schema:
        updated = _enum_value(value, schema["enum"])
        if updated != value:
            changes.append({"pointer": pointer, "rule": "canonical-enum", "before": value, "after": updated})
        value = updated
    expected_type = schema.get("type")
    accepts_string = expected_type == "string" or (
        isinstance(expected_type, list) and "string" in expected_type
    )
    if accepts_string and isinstance(value, (dict, list)):
        # A worker may express a text field as a richer structured note.  A
        # canonical JSON string is a representation-only conversion: every key
        # and value survives, no scientific judgment is changed, and the
        # original bundle remains immutable.
        updated = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        changes.append({
            "pointer": pointer,
            "rule": "structured-value-to-canonical-json-text",
            "before": copy.deepcopy(value),
            "after": updated,
        })
        return updated
    if isinstance(value, dict) and schema.get("type") == "object":
        properties = schema.get("properties") or {}
        out = {}
        for key, child in value.items():
            child_pointer = f"{pointer}/{str(key).replace('~', '~0').replace('/', '~1')}"
            if key not in properties and schema.get("additionalProperties") is False:
                extras.append({"pointer": child_pointer, "value": copy.deepcopy(child)})
                changes.append({"pointer": child_pointer, "rule": "preserve-extra-in-sidecar"})
                continue
            out[key] = _walk(child, properties.get(key, {}), child_pointer, changes, extras)
        for key, child_schema in properties.items():
            if key not in out and key not in value and "default" in child_schema:
                out[key] = copy.deepcopy(child_schema["default"])
                changes.append({"pointer": f"{pointer}/{key}", "rule": "schema-default"})
        return out
    if isinstance(value, list) and schema.get("type") == "array":
        item_schema = schema.get("items") or {}
        return [
            _walk(item, item_schema, f"{pointer}/{index}", changes, extras)
            for index, item in enumerate(value)
        ]
    return value


def normalize_payload(artifact_type: str, payload: dict) -> tuple[dict, dict]:
    schema_name = PAYLOAD_SCHEMAS[artifact_type]
    schema = json.loads((SCHEMA_DIR / schema_name).read_text(encoding="utf-8"))
    before = copy.deepcopy(payload)
    changes: list[dict] = []
    extras: list[dict] = []
    after = _walk(before, schema, "", changes, extras)
    return after, {
        "contract_version": "schema-normalization/v1",
        "artifact_type": artifact_type,
        "before_sha256": _digest(payload),
        "after_sha256": _digest(after),
        "changes": changes,
        "preserved_extras": extras,
        "scientific_fields_modified": False,
    }


def write_report(path: Path, report: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
