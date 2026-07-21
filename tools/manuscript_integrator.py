"""Deterministic single-writer integration for frozen manuscript bundles.

The reducer reads only explicitly named, receipt-authorized inputs.  It builds a
complete source candidate in memory; :func:`materialize_source_tree` is the only
operation in this module that writes, and it publishes ``run_root/source`` once.
It never compiles TeX, calls a model, executes an asset command, or writes a vault.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import shutil
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any, Callable, Mapping, Pattern, Sequence

from research_agent_teams.operate.output_versions import resolve_effective_output
from research_agent_teams.tools.manuscript_contract import canonical_contract_hash
from research_agent_teams.tools.manuscript_security import (
    ManuscriptPathViolation,
    ManuscriptSecretViolation,
    ManuscriptTexViolation,
    scan_persisted_text,
    validate_run_owned_path,
    validate_tex_sources,
)
from research_agent_teams.tools.validate_artifact import validate_payload


INTEGRATOR_ROLE = "manuscript-integrator"
MAX_FORMAT_REPAIRS = 2
_REQUIRED_DIRS = ("sections", "figures", "tables", "manifests", "build")
_LABEL_RE = re.compile(r"\\label\s*\{([^{}]+)\}")
_REFERENCE_RE = re.compile(r"\\(?:ref|eqref|autoref|cref|Cref)\s*\{([^{}]+)\}")
_CITATION_RE = re.compile(r"\\cite(?:p|t)?\s*\{([^{}]+)\}")
_GRAPHIC_RE = re.compile(r"\\includegraphics(?:\[[^\[\]]*\])?\s*\{([^{}]+)\}")
_CAPTION_RE = re.compile(r"\\caption\s*\{([^{}]+)\}")
_BIB_KEY_RE = re.compile(r"@[A-Za-z]+\s*\{\s*([^,\s{}]+)\s*,")
_JSON_SCALAR_RE = re.compile(
    r'"(?:\\.|[^"\\])*"|-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?|true|false|null'
)
_DEFAULT_SECRET_PATTERNS: dict[str, Pattern[str]] = {
    "private_key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "credential_url": re.compile(r"[A-Za-z][A-Za-z0-9+.-]*://[^\s/:]+:[^\s/@]+@"),
    "aws_access_key": re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    "github_token": re.compile(r"\bgh(?:p|o|u|s|r)_[A-Za-z0-9]{20,}\b"),
}


class ManuscriptIntegrationError(ValueError):
    """Stable, machine-readable hard finding raised before canonical publish."""

    def __init__(self, code: str, message: str, *, affected_refs: Sequence[str] = ()) -> None:
        self.code = code
        self.findings = [
            {
                "code": code,
                "severity": "HARD",
                "message": message,
                "affected_refs": list(affected_refs),
            }
        ]
        super().__init__(f"{code}: {message}")

def _fail(code: str, message: str, *refs: str) -> None:
    raise ManuscriptIntegrationError(code, message, affected_refs=refs)

def _canonical_bytes(value: Any) -> bytes:
    try:
        return json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        _fail("NON_CANONICAL_VALUE", f"candidate is not canonical JSON: {exc}")

def _canonical_hash(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()

def _hash_without(value: Mapping[str, Any], field: str) -> str:
    return _canonical_hash({key: item for key, item in value.items() if key != field})

def _bytes_hash(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()

def _file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()

def _json_tokens(text: str) -> tuple[str, ...]:
    return tuple(match.group(0) for match in _JSON_SCALAR_RE.finditer(text))

def _read_json(path: Path, *, format_repair: Callable[[str, list[str], int], str] | None
               ) -> tuple[dict[str, Any], int, bytes]:
    raw = path.read_bytes()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        _fail("BUNDLE_ENCODING_INVALID", "section bundle must be UTF-8", path.as_posix())
    current = text
    errors: list[str] = []
    for attempt in range(MAX_FORMAT_REPAIRS + 1):
        try:
            value = json.loads(current)
        except json.JSONDecodeError as exc:
            errors = [f"line {exc.lineno}, column {exc.colno}: {exc.msg}"]
            if attempt == MAX_FORMAT_REPAIRS:
                code = "REPAIR_LIMIT_EXCEEDED" if format_repair else "BUNDLE_INVALID_JSON"
                _fail(code, "section bundle is not valid JSON after the bounded repair budget", path.as_posix())
            if format_repair is None:
                _fail("BUNDLE_INVALID_JSON", errors[0], path.as_posix())
            repaired = format_repair(current, list(errors), attempt + 1)
            if not isinstance(repaired, str):
                _fail("FORMAT_REPAIR_INVALID", "format repair must return JSON text", path.as_posix())
            if _json_tokens(repaired) != _json_tokens(current):
                _fail(
                    "FORMAT_REPAIR_CHANGED_CONTENT",
                    "format repair changed scalar content instead of punctuation or whitespace",
                    path.as_posix(),
                )
            current = repaired
            continue
        if not isinstance(value, dict):
            _fail("BUNDLE_INVALID_JSON", "section bundle must decode to an object", path.as_posix())
        return value, attempt, raw
    raise AssertionError("bounded JSON parser exhausted without returning")

def _safe_run_file(reference: str | Path, *, run_root: Path, owned_roots: Sequence[Path],
                   expected_sha256: str | None = None) -> Path:
    try:
        result = validate_run_owned_path(
            reference,
            run_root=run_root,
            purpose="read",
            owned_output_roots=owned_roots,
            expected_sha256=expected_sha256,
        )
    except ManuscriptPathViolation as exc:
        _fail("UNSAFE_INPUT_PATH", str(exc), os.fspath(reference))
    return Path(result["path"])

def _validate_contract(contract: Mapping[str, Any], run_root: Path) -> dict[str, Any]:
    if not isinstance(contract, Mapping):
        _fail("CONTRACT_INVALID", "manuscript contract must be an object")
    frozen = copy.deepcopy(dict(contract))
    errors = validate_payload("manuscript_contract", frozen)
    if errors:
        _fail("CONTRACT_INVALID", "; ".join(errors[:5]))
    if frozen["run_id"] != run_root.name:
        _fail("RUN_ID_MISMATCH", "contract run_id does not identify the active run")
    if canonical_contract_hash(frozen) != frozen["manuscript_snapshot_sha256"]:
        _fail("CONTRACT_HASH_MISMATCH", "frozen manuscript snapshot hash does not verify")
    for row in frozen["dependency_slices"]:
        if _hash_without(row, "slice_sha256") != row["slice_sha256"]:
            _fail("DEPENDENCY_SLICE_HASH_MISMATCH", "declared dependency slice hash does not verify", row["slice_id"])
    return frozen

def _required_assignments(contract: dict[str, Any], required: Sequence[Mapping[str, str]]
                          ) -> list[dict[str, str]]:
    if not isinstance(required, Sequence) or isinstance(required, (str, bytes)):
        _fail("REQUIRED_SECTION_ASSIGNMENT_INVALID", "required_sections must be an explicit assignment list")
    assignments: dict[str, dict[str, str]] = {}
    for raw in required:
        if not isinstance(raw, Mapping):
            _fail("REQUIRED_SECTION_ASSIGNMENT_INVALID", "each required section needs an explicit assignment")
        row = {
            key: str(raw.get(key) or "")
            for key in ("section_id", "worker_role", "dependency_slice_id")
        }
        if not all(row.values()):
            _fail("REQUIRED_SECTION_ASSIGNMENT_INVALID", "section, role, and dependency slice are required")
        if row["section_id"] in assignments:
            _fail("DUPLICATE_REQUIRED_SECTION", "required section assignment is duplicated", row["section_id"])
        assignments[row["section_id"]] = row

    outline_order = [row["section_id"] for row in contract["outline"] if row["required"]]
    if set(assignments) != set(outline_order):
        _fail("REQUIRED_SECTION_ASSIGNMENT_MISMATCH", "assignments must exactly cover frozen required outline sections")
    slices = {row["slice_id"]: row for row in contract["dependency_slices"]}
    for row in assignments.values():
        dependency = slices.get(row["dependency_slice_id"])
        if dependency is None or dependency["worker_role"] != row["worker_role"]:
            _fail("UNAUTHORIZED_DEPENDENCY", "section assignment is not bound to its declared slice", row["section_id"])
    return [assignments[section_id] for section_id in outline_order]

def _receipt_row(bundle: dict[str, Any], *, bundle_ref: str, run_root: Path,
                 stage: str) -> dict[str, Any]:
    authorization = bundle["authorization_receipt"]
    receipt_path = _safe_run_file(
        authorization["ref"],
        run_root=run_root,
        owned_roots=(run_root / "inbox",),
    )
    try:
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError):
        _fail("AUTHORIZATION_RECEIPT_INVALID", "scheduler receipt is not valid UTF-8 JSON", authorization["ref"])
    if receipt.get("contract_version") != "panel-dispatch/v1" or receipt.get("stage") != stage:
        _fail("UNAUTHORIZED_STAGE", "scheduler receipt does not authorize the requested stage", authorization["ref"])
    rows = [
        row
        for row in receipt.get("authorizations", [])
        if isinstance(row, dict)
        and bundle_ref in {row.get("output"), row.get("logical_output")}
    ]
    if len(rows) != 1:
        _fail("AUTHORIZATION_MISMATCH", "bundle has no unique scheduler authorization", bundle_ref)
    row = rows[0]
    if row.get("agent") != bundle["worker_role"] or authorization["worker_role"] != bundle["worker_role"]:
        _fail("AUTHORIZATION_MISMATCH", "authorization role does not match bundle worker", bundle_ref)
    if row.get("authorization_kind") not in {"initial", "supplement"}:
        _fail("AUTHORIZATION_MISMATCH", "authorization kind is invalid", bundle_ref)
    if _canonical_hash(row) != authorization["sha256"]:
        _fail("AUTHORIZATION_HASH_MISMATCH", "immutable authorization row hash does not verify", bundle_ref)
    return row

def validate_section_bundle(bundle_ref: str, *, run_root: str | Path,
                            manuscript_contract: Mapping[str, Any],
                            required_section: Mapping[str, str], stage: str,
                            format_repair: Callable[[str, list[str], int], str] | None = None,
                            ) -> dict[str, Any]:
    """Load and verify one explicitly assigned section bundle without mutating it."""

    root = Path(run_root).absolute()
    contract = _validate_contract(manuscript_contract, root)
    required_count = sum(bool(row["required"]) for row in contract["outline"])
    assignments = _required_assignments(contract, [required_section]) if required_count == 1 else None
    if assignments is None:
        raw_assignment = {
            key: str(required_section.get(key) or "")
            for key in ("section_id", "worker_role", "dependency_slice_id")
        }
        if not all(raw_assignment.values()):
            _fail("REQUIRED_SECTION_ASSIGNMENT_INVALID", "section, role, and dependency slice are required")
        slices = {row["slice_id"]: row for row in contract["dependency_slices"]}
        dependency = slices.get(raw_assignment["dependency_slice_id"])
        if dependency is None or dependency["worker_role"] != raw_assignment["worker_role"]:
            _fail("UNAUTHORIZED_DEPENDENCY", "section assignment is not bound to its declared slice")
        assignment = raw_assignment
    else:
        assignment = assignments[0]

    if not isinstance(bundle_ref, str) or not bundle_ref.startswith("inbox/"):
        _fail("UNDECLARED_BUNDLE", "bundle reference must be an explicit run inbox path")
    logical = _safe_run_file(bundle_ref, run_root=root, owned_roots=(root / "inbox",))
    try:
        effective = resolve_effective_output(root, stage, logical)
    except ValueError as exc:
        _fail("STALE_BUNDLE", str(exc), bundle_ref)
    effective = _safe_run_file(effective, run_root=root, owned_roots=(root / "inbox",))
    bundle, repair_attempts, raw_bytes = _read_json(effective, format_repair=format_repair)
    errors = validate_payload("manuscript_section_bundle", bundle)
    if errors:
        _fail("SECTION_BUNDLE_INVALID", "; ".join(errors[:5]), bundle_ref)
    if _hash_without(bundle, "content_hash") != bundle["content_hash"]:
        _fail("BUNDLE_CONTENT_HASH_MISMATCH", "section content hash does not verify", bundle_ref)
    if bundle["manuscript_snapshot_sha256"] != contract["manuscript_snapshot_sha256"]:
        _fail("STALE_BUNDLE", "section bundle targets a different frozen manuscript", bundle_ref)
    if bundle["section_id"] != assignment["section_id"]:
        _fail("SECTION_ASSIGNMENT_MISMATCH", "bundle section does not match its assignment", bundle_ref)
    if bundle["worker_role"] != assignment["worker_role"]:
        _fail("AUTHORIZATION_MISMATCH", "bundle worker does not match its assignment", bundle_ref)

    global_refs = [row for row in bundle["input_refs"] if row["slice_kind"] == "GLOBAL_CONTRACT"]
    if global_refs[0]["sha256"] != contract["manuscript_snapshot_sha256"]:
        _fail("CONTRACT_HASH_MISMATCH", "bundle global-contract input is stale", bundle_ref)
    slices = {row["slice_id"]: row for row in contract["dependency_slices"]}
    declared = slices[assignment["dependency_slice_id"]]["input_refs"]
    visible = [row for row in bundle["input_refs"] if row["slice_kind"] != "GLOBAL_CONTRACT"]
    if sorted(map(_canonical_bytes, visible)) != sorted(map(_canonical_bytes, declared)):
        _fail("UNAUTHORIZED_DEPENDENCY", "bundle inputs do not exactly equal its frozen dependency slice", bundle_ref)
    receipt_row = _receipt_row(bundle, bundle_ref=bundle_ref, run_root=root, stage=stage)
    return {
        "payload": copy.deepcopy(bundle),
        "bundle_ref": bundle_ref,
        "effective_ref": effective.relative_to(root).as_posix(),
        "bundle_sha256": _bytes_hash(raw_bytes),
        "content_hash": bundle["content_hash"],
        "repair_attempts": repair_attempts,
        "authorization_sha256": _canonical_hash(receipt_row),
        "dependency_slice_id": assignment["dependency_slice_id"],
    }

def _parse_bundle_tex(bundle: dict[str, Any], bundle_ref: str
                      ) -> dict[str, set[str] | list[str]]:
    text = bundle["draft_latex"]
    labels = _LABEL_RE.findall(text)
    if len(labels) != len(set(labels)):
        _fail("DUPLICATE_LABEL", "a section defines the same label more than once", bundle_ref)
    citations = {
        key.strip()
        for group in _CITATION_RE.findall(text)
        for key in group.split(",")
        if key.strip()
    }
    references = {item.strip() for item in _REFERENCE_RE.findall(text) if item.strip()}
    graphics = {item.strip() for item in _GRAPHIC_RE.findall(text) if item.strip()}
    return {
        "labels": set(labels),
        "citations": citations,
        "references": references,
        "graphics": graphics,
        "captions": _CAPTION_RE.findall(text),
    }

def _verify_result(reference: str, contract: dict[str, Any], run_root: Path) -> None:
    rows = {row["ref"]: row for row in contract["result_refs"]}
    row = rows.get(reference)
    if row is None:
        _fail("UNKNOWN_RESULT", "bundle or asset cites an undeclared result", reference)
    path = _safe_run_file(reference, run_root=run_root, owned_roots=(run_root,))
    if _file_hash(path) != row["sha256"]:
        _fail("STALE_RESULT", "frozen result bytes no longer match the contract", reference)

def _asset_files(manifest: Mapping[str, Any] | None, *, contract: dict[str, Any],
                 run_root: Path, asset_sources: Mapping[str, str | Path],
                 director_asset_roots: Sequence[str | Path]
                 ) -> tuple[dict[str, Any], dict[str, bytes]]:
    if manifest is None:
        value: dict[str, Any] = {
            "schema_version": "1.0.0",
            "run_id": contract["run_id"],
            "manuscript_sha256": contract["manuscript_snapshot_sha256"],
            "assets": [],
        }
        value["manifest_sha256"] = _hash_without(value, "manifest_sha256")
    elif isinstance(manifest, Mapping):
        value = copy.deepcopy(dict(manifest))
    else:
        _fail("ASSET_MANIFEST_INVALID", "asset manifest must be an object")

    if value.get("run_id") != contract["run_id"] or value.get("manuscript_sha256") != contract["manuscript_snapshot_sha256"]:
        _fail("ASSET_MANIFEST_STALE", "asset manifest is not bound to this frozen manuscript")
    assets = value.get("assets") if isinstance(value.get("assets"), list) else []
    for asset in assets:
        if not isinstance(asset, dict):
            _fail("ASSET_MANIFEST_INVALID", "asset records must be objects")
        provenance = asset.get("provenance") or {}
        if provenance.get("kind") == "GENERATED":
            command = provenance.get("render_command")
            if (
                not isinstance(command, dict)
                or not isinstance(command.get("argv"), list)
                or not command["argv"]
            ):
                _fail(
                    "GENERATED_COMMAND_REQUIRED",
                    "generated assets require a non-empty argv receipt",
                    str(asset.get("asset_id")),
                )

    errors = validate_payload("manuscript_asset_manifest", value)
    if errors:
        _fail("ASSET_MANIFEST_INVALID", "; ".join(errors[:5]))
    if _hash_without(value, "manifest_sha256") != value["manifest_sha256"]:
        _fail("ASSET_MANIFEST_HASH_MISMATCH", "asset manifest hash does not verify")

    files: dict[str, bytes] = {}
    seen_ids: set[str] = set()
    seen_labels: set[str] = set()
    seen_paths: set[str] = set()
    claims = {row["claim_id"] for row in contract["claim_ledger"]}
    results = {row["ref"] for row in contract["result_refs"]}
    for asset in assets:
        asset_id = asset["asset_id"]
        output = asset["output"]
        output_path = output["path"]
        expected_prefix = "figures/" if asset["asset_type"] == "FIGURE" else "tables/"
        if asset_id in seen_ids or asset["label"] in seen_labels or output_path in seen_paths:
            _fail("DUPLICATE_ASSET", "asset id, label, and output path must be globally unique", asset_id)
        seen_ids.add(asset_id)
        seen_labels.add(asset["label"])
        seen_paths.add(output_path)
        if not output_path.startswith(expected_prefix):
            _fail("ASSET_OUTPUT_PATH_INVALID", "asset output is outside its canonical directory", output_path)
        if output["owner_run_id"] != contract["run_id"]:
            _fail("ASSET_OWNER_MISMATCH", "asset output is owned by another run", asset_id)
        if _hash_without(asset, "asset_record_sha256") != asset["asset_record_sha256"]:
            _fail("ASSET_RECORD_HASH_MISMATCH", "asset record hash does not verify", asset_id)
        if not set(asset["claim_refs"]).issubset(claims) or not set(
            asset["result_refs"]
        ).issubset(results):
            _fail("ASSET_PROVENANCE_UNKNOWN", "asset cites an unknown claim or result", asset_id)
        for result_ref in set(asset["result_refs"]):
            _verify_result(result_ref, contract, run_root)
        source_value = asset_sources.get(asset_id)
        if source_value is None:
            _fail("ASSET_SOURCE_MISSING", "asset has no explicitly declared source file", asset_id)
        source_path = Path(source_value).absolute()
        provenance = asset["provenance"]
        if provenance["kind"] == "EXTERNAL":
            try:
                checked = validate_run_owned_path(
                    source_path,
                    run_root=run_root,
                    purpose="read",
                    director_asset_roots=director_asset_roots,
                    expected_sha256=output["sha256"],
                )
            except ManuscriptPathViolation as exc:
                _fail("UNSAFE_ASSET_PATH", str(exc), asset_id)
            external = provenance["external_source"]
            if external["original_sha256"] != output["sha256"] or checked.get("owner") != "director":
                _fail("DIRECTOR_ASSET_HASH_MISMATCH", "director asset provenance does not match source bytes", asset_id)
        else:
            source_path = _safe_run_file(source_path, run_root=run_root, owned_roots=(run_root,))
            command = provenance["render_command"]
            script_path = _safe_run_file(
                command["script_ref"],
                run_root=run_root,
                owned_roots=(run_root,),
                expected_sha256=command["script_sha256"],
            )
            del script_path  # Validation only: this reducer never invokes the command.
        before = _file_hash(source_path)
        data = source_path.read_bytes()
        after = _file_hash(source_path)
        if before != after or before != output["sha256"] or len(data) != output["byte_size"]:
            _fail("ASSET_SOURCE_CHANGED", "asset bytes changed or do not match output facts", asset_id)
        director_inputs = [row for row in asset["source_inputs"] if row["kind"] == "DIRECTOR_ASSET"]
        if director_inputs and any(row["sha256"] != before for row in director_inputs):
            _fail("DIRECTOR_ASSET_HASH_MISMATCH", "director input hash does not match copied bytes", asset_id)
        files[output_path] = data

    planned = {row["asset_id"]: row for row in contract["asset_plan"]}
    if set(planned) != seen_ids:
        _fail("ASSET_PLAN_MISMATCH", "asset manifest must exactly realize the frozen asset plan")
    for asset in assets:
        plan = planned[asset["asset_id"]]
        if (plan["kind"], plan["label"], plan["planned_path"]) != (
            asset["asset_type"], asset["label"], asset["output"]["path"]
        ):
            _fail("ASSET_PLAN_MISMATCH", "asset identity differs from the frozen plan", asset["asset_id"])
    return value, files


def _scan_candidate_text(files: Mapping[str, bytes], *, sentinels: Mapping[str, str] | None,
                         patterns: Mapping[str, str | Pattern[str]] | None) -> None:
    combined_patterns = dict(_DEFAULT_SECRET_PATTERNS)
    combined_patterns.update(patterns or {})
    for path, data in files.items():
        if not path.endswith((".tex", ".bib", ".json")):
            continue
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            _fail("TEXT_ENCODING_INVALID", "durable manuscript text must be UTF-8", path)
        try:
            scan_persisted_text(path, text, sentinels=sentinels, patterns=combined_patterns)
        except ManuscriptSecretViolation as exc:
            _fail("SECRET_LEAKAGE", str(exc), path)


def integrate_manuscript(*, run_root: str | Path, manuscript_contract: Mapping[str, Any],
                         section_bundle_refs: Sequence[str],
                         required_sections: Sequence[Mapping[str, str]], bibliography_text: str,
                         stage: str, asset_manifest: Mapping[str, Any] | None = None,
                         asset_sources: Mapping[str, str | Path] | None = None,
                         director_asset_roots: Sequence[str | Path] = (),
                         format_repair: Callable[[str, list[str], int], str] | None = None,
                         secret_sentinels: Mapping[str, str] | None = None,
                         secret_patterns: Mapping[str, str | Pattern[str]] | None = None,
                         ) -> dict[str, Any]:
    """Reduce frozen bundles into a byte-complete, unpublished source candidate."""

    root = Path(run_root).absolute()
    contract = _validate_contract(manuscript_contract, root)
    assignments = _required_assignments(contract, required_sections)
    refs = list(section_bundle_refs)
    if len(refs) < len(assignments):
        _fail("MISSING_REQUIRED_SECTION", "one or more required section bundles are absent")
    if len(refs) > len(assignments):
        _fail("DUPLICATE_REQUIRED_SECTION", "required section bundle cardinality exceeds one")
    if len(set(refs)) != len(refs):
        _fail("DUPLICATE_REQUIRED_SECTION", "the same section bundle was declared more than once")

    by_section: dict[str, dict[str, Any]] = {}
    for ref in refs:
        matches: list[dict[str, Any]] = []
        for assignment in assignments:
            try:
                candidate = validate_section_bundle(
                    ref,
                    run_root=root,
                    manuscript_contract=contract,
                    required_section=assignment,
                    stage=stage,
                    format_repair=format_repair,
                )
            except ManuscriptIntegrationError as exc:
                if exc.code == "SECTION_ASSIGNMENT_MISMATCH":
                    continue
                raise
            matches.append(candidate)
        if len(matches) != 1:
            _fail("UNDECLARED_BUNDLE", "bundle does not map to exactly one required assignment", ref)
        section_id = matches[0]["payload"]["section_id"]
        if section_id in by_section:
            _fail("DUPLICATE_REQUIRED_SECTION", "required section has more than one bundle", section_id)
        by_section[section_id] = matches[0]
    missing = [row["section_id"] for row in assignments if row["section_id"] not in by_section]
    if missing:
        _fail("MISSING_REQUIRED_SECTION", "required section has no authorized bundle", *missing)
    validated = [by_section[row["section_id"]] for row in assignments]

    all_labels = [label for item in validated for label in item["payload"]["labels"]]
    duplicate_labels = sorted(label for label, count in Counter(all_labels).items() if count > 1)
    if duplicate_labels:
        _fail("DUPLICATE_LABEL", "labels must be unique across all section bundles", *duplicate_labels)
    declared_refs = {ref for item in validated for ref in item["payload"]["cross_references"]}
    unresolved_refs = sorted(declared_refs - set(all_labels))
    if unresolved_refs:
        _fail("UNRESOLVED_REFERENCE", "cross-reference has no canonical label", *unresolved_refs)
    frozen_citations = {row["citation_key"] for row in contract["bibliography"]["entries"]}
    declared_citations = {key for item in validated for key in item["payload"]["citation_keys"]}
    unknown_citations = sorted(declared_citations - frozen_citations)
    if unknown_citations:
        _fail("UNKNOWN_CITATION", "citation is absent from the frozen bibliography", *unknown_citations)
    claims = [row["claim_id"] for item in validated for row in item["payload"]["claim_support_refs"]]
    duplicates = sorted(claim for claim, count in Counter(claims).items() if count > 1)
    if duplicates:
        _fail("DUPLICATE_CLAIM", "claim ownership is duplicated across section bundles", *duplicates)

    known_claims = {row["claim_id"]: row for row in contract["claim_ledger"]}
    known_evidence = {row["ref"] for row in contract["evidence_refs"]}
    for item in validated:
        bundle = item["payload"]
        parsed = _parse_bundle_tex(bundle, item["bundle_ref"])
        if parsed["labels"] != set(bundle["labels"]):
            _fail("LABEL_METADATA_MISMATCH", "declared labels differ from TeX labels", item["bundle_ref"])
        if parsed["citations"] != set(bundle["citation_keys"]):
            _fail("CITATION_METADATA_MISMATCH", "declared citations differ from TeX citations", item["bundle_ref"])
        if parsed["references"] != set(bundle["cross_references"]):
            _fail("REFERENCE_METADATA_MISMATCH", "declared references differ from TeX references", item["bundle_ref"])
        for support in bundle["claim_support_refs"]:
            for result_ref in support["result_refs"]:
                _verify_result(result_ref, contract, root)
            claim = known_claims.get(support["claim_id"])
            if claim is None:
                _fail("UNKNOWN_CLAIM", "section owns a claim absent from the frozen ledger", support["claim_id"])
            if not set(support["evidence_refs"]).issubset(set(claim["evidence_refs"])) or not set(
                support["result_refs"]
            ).issubset(set(claim["result_refs"])):
                _fail("CLAIM_SUPPORT_MISMATCH", "section support exceeds the frozen claim ledger", support["claim_id"])
            if not set(support["evidence_refs"]).issubset(known_evidence):
                _fail("UNKNOWN_EVIDENCE", "section cites unknown evidence", support["claim_id"])
        if bundle["omissions"] or bundle["requested_supplements"]:
            _fail("SECTION_INCOMPLETE", "section bundle still declares omissions or supplements", item["bundle_ref"])
        known_symbols = {row["symbol"] for row in contract["glossary"]["notation"]}
        if any(row["symbol"] not in known_symbols for row in bundle["notation_uses"]):
            _fail("UNKNOWN_NOTATION", "section uses notation absent from the frozen glossary", item["bundle_ref"])

    if not isinstance(bibliography_text, str) or not bibliography_text.strip():
        _fail("BIBLIOGRAPHY_REQUIRED", "frozen refs.bib content is required; the integrator will not invent it")
    bib_keys = set(_BIB_KEY_RE.findall(bibliography_text))
    if not declared_citations.issubset(bib_keys):
        _fail("UNRESOLVED_CITATION", "refs.bib does not contain every cited frozen key")

    normalized_assets, asset_files = _asset_files(
        asset_manifest, contract=contract, run_root=root,
        asset_sources=asset_sources or {}, director_asset_roots=director_asset_roots,
    )
    assets = {row["asset_id"]: row for row in normalized_assets["assets"]}
    declared_assets = {ref for item in validated for ref in item["payload"]["asset_refs"]}
    if declared_assets != set(assets):
        _fail("ASSET_REFERENCE_MISMATCH", "section asset refs must exactly cover the frozen asset manifest")
    actual_graphics: set[str] = set()
    actual_captions: set[str] = set()
    for item in validated:
        parsed = _parse_bundle_tex(item["payload"], item["bundle_ref"])
        actual_graphics.update(parsed["graphics"])
        actual_captions.update(parsed["captions"])
    expected_graphics = {row["output"]["path"] for row in assets.values() if row["asset_type"] == "FIGURE"}
    if actual_graphics != expected_graphics:
        _fail("ASSET_PATH_UNRESOLVED", "included figure paths do not match the asset manifest")
    for asset in assets.values():
        if asset["label"] not in all_labels or asset["caption"]["text"] not in actual_captions:
            _fail("ASSET_NARRATIVE_MISMATCH", "asset label or caption is absent from section TeX", asset["asset_id"])

    section_files = {
        f"sections/{item['payload']['section_id']}.tex": (
            item["payload"]["draft_latex"].rstrip() + "\n"
        ).encode("utf-8")
        for item in validated
    }
    main_lines = [
        "\\documentclass{article}",
        "\\usepackage{graphicx}",
        "\\usepackage{natbib}",
        "\\begin{document}",
        *[f"\\input{{sections/{row['section_id']}.tex}}" for row in assignments],
        "\\bibliographystyle{plain}",
        "\\bibliography{refs}",
        "\\end{document}",
        "",
    ]
    files: dict[str, bytes] = {
        "main.tex": "\n".join(main_lines).encode("utf-8"),
        "refs.bib": (bibliography_text.rstrip() + "\n").encode("utf-8"),
        **section_files,
        **asset_files,
    }
    files["manifests/asset-manifest.json"] = _canonical_bytes(normalized_assets)
    build_metadata = {
        "contract_version": "manuscript-integration-inputs/v1",
        "manuscript_snapshot_sha256": contract["manuscript_snapshot_sha256"],
        "section_order": [row["section_id"] for row in assignments],
        "bundle_inputs": [
            {
                "section_id": item["payload"]["section_id"],
                "bundle_ref": item["bundle_ref"],
                "bundle_sha256": item["bundle_sha256"],
                "authorization_sha256": item["authorization_sha256"],
                "dependency_slice_id": item["dependency_slice_id"],
                "repair_attempts": item["repair_attempts"],
            }
            for item in validated
        ],
        "compiled_pdf_claim": False,
    }
    files["build/integration-metadata.json"] = _canonical_bytes(build_metadata)

    tex_sources = {
        path: data.decode("utf-8") for path, data in files.items() if path.endswith(".tex")
    }
    try:
        validate_tex_sources(tex_sources, run_root=root, source_root=root / "source")
    except ManuscriptTexViolation as exc:
        _fail("UNSAFE_TEX", str(exc))
    _scan_candidate_text(files, sentinels=secret_sentinels, patterns=secret_patterns)

    def kind(path: str) -> str:
        if path == "main.tex":
            return "MAIN_TEX"
        if path == "refs.bib":
            return "BIBLIOGRAPHY"
        if path.startswith("sections/"):
            return "SECTION"
        if path == "manifests/asset-manifest.json":
            return "ASSET_MANIFEST"
        if path.startswith("figures/"):
            return "FIGURE"
        if path.startswith("tables/"):
            return "TABLE"
        return "OTHER"

    inventory = [
        {"path": path, "sha256": _bytes_hash(data), "kind": kind(path)}
        for path, data in sorted(files.items())
    ]
    integration: dict[str, Any] = {
        "contract_version": "1.0",
        "integration_id": f"manuscript-integration/{contract['run_id']}",
        "integrator_role": INTEGRATOR_ROLE,
        "manuscript_snapshot_sha256": contract["manuscript_snapshot_sha256"],
        "section_bundle_refs": [
            {
                "section_id": item["payload"]["section_id"],
                "bundle_ref": item["bundle_ref"],
                "bundle_sha256": item["bundle_sha256"],
                "content_hash": item["content_hash"],
            }
            for item in validated
        ],
        "canonical_file_inventory": inventory,
        "source_tree_sha256": _canonical_hash(inventory),
        "reconciliation_findings": [],
        "unresolved_interfaces": [],
    }
    integration["integration_hash"] = _hash_without(integration, "integration_hash")
    errors = validate_payload("manuscript_integration", integration)
    if errors:
        _fail("INTEGRATION_INVALID", "; ".join(errors[:5]))
    files["manifests/manuscript-integration.json"] = _canonical_bytes(integration)
    _scan_candidate_text(files, sentinels=secret_sentinels, patterns=secret_patterns)
    return {
        "integration": integration,
        "asset_manifest": normalized_assets,
        "files": files,
    }


def _write_candidate_file(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())


def materialize_source_tree(candidate: Mapping[str, Any], *, run_root: str | Path,
                            target: str | Path | None = None,
                            integrator_role: str = INTEGRATOR_ROLE) -> Path:
    """Atomically publish exactly one validated ``source/`` tree for this run."""

    root = Path(run_root).absolute()
    canonical = root / "source"
    destination = Path(target).absolute() if target is not None else canonical
    if destination != canonical:
        _fail("CANONICAL_TARGET_REQUIRED", "the integrator may publish only the active run's source directory")
    integration = candidate.get("integration") if isinstance(candidate, Mapping) else None
    asset_manifest = candidate.get("asset_manifest") if isinstance(candidate, Mapping) else None
    files = candidate.get("files") if isinstance(candidate, Mapping) else None
    if (
        integrator_role != INTEGRATOR_ROLE
        or not isinstance(integration, dict)
        or integration.get("integrator_role") != INTEGRATOR_ROLE
    ):
        _fail("INTEGRATOR_AUTHORITY_REQUIRED", "only manuscript-integrator owns canonical source")
    if not isinstance(asset_manifest, dict) or not isinstance(files, Mapping):
        _fail("CANDIDATE_INVALID", "candidate is missing validated integration, assets, or files")
    if validate_payload("manuscript_integration", integration) or validate_payload("manuscript_asset_manifest", asset_manifest):
        _fail("CANDIDATE_INVALID", "candidate payload no longer satisfies its schema")
    if _hash_without(integration, "integration_hash") != integration["integration_hash"]:
        _fail("CANDIDATE_HASH_MISMATCH", "integration hash no longer verifies")

    expected = {row["path"]: row["sha256"] for row in integration["canonical_file_inventory"]}
    if len(expected) != len(integration["canonical_file_inventory"]):
        _fail("DUPLICATE_CANONICAL_PATH", "canonical inventory contains duplicate paths")
    expected_manifest = "manifests/manuscript-integration.json"
    if set(files) != set(expected) | {expected_manifest}:
        _fail("CANDIDATE_INVENTORY_MISMATCH", "candidate files differ from canonical inventory")
    for path, expected_hash in expected.items():
        data = files[path]
        if not isinstance(data, bytes) or _bytes_hash(data) != expected_hash:
            _fail("CANDIDATE_HASH_MISMATCH", "candidate file hash does not verify", path)
    if files[expected_manifest] != _canonical_bytes(integration):
        _fail("CANDIDATE_HASH_MISMATCH", "integration manifest bytes do not verify")
    if _canonical_hash(integration["canonical_file_inventory"]) != integration["source_tree_sha256"]:
        _fail("CANDIDATE_HASH_MISMATCH", "source-tree inventory hash does not verify")

    try:
        for path in files:
            validate_run_owned_path(
                destination / path,
                run_root=root,
                purpose="write",
                owned_output_roots=(canonical,),
            )
    except ManuscriptPathViolation as exc:
        _fail("UNSAFE_OUTPUT_PATH", str(exc))
    if os.path.lexists(destination):
        _fail("SOURCE_ALREADY_EXISTS", "canonical source tree is create-once")

    lock = root / ".source-integration.lock"
    staging: Path | None = None
    lock_fd: int | None = None
    try:
        try:
            lock_fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            _fail("SOURCE_WRITER_BUSY", "another canonical source writer holds the run lock")
        os.write(lock_fd, integration["integration_hash"].encode("ascii"))
        os.fsync(lock_fd)
        os.close(lock_fd)
        lock_fd = None
        if os.path.lexists(destination):
            _fail("SOURCE_ALREADY_EXISTS", "canonical source tree is create-once")
        staging = Path(tempfile.mkdtemp(prefix=".source-integration-", dir=root))
        for directory in _REQUIRED_DIRS:
            (staging / directory).mkdir(parents=True, exist_ok=False)
        for path, data in sorted(files.items()):
            _write_candidate_file(staging / path, data)
        for path, expected_hash in expected.items():
            if _file_hash(staging / path) != expected_hash:
                _fail("PUBLISH_HASH_MISMATCH", "staged source hash does not verify", path)
        if os.path.lexists(destination):
            _fail("SOURCE_ALREADY_EXISTS", "canonical source appeared during publish")
        try:
            for path in files:
                validate_run_owned_path(
                    destination / path,
                    run_root=root,
                    purpose="write",
                    owned_output_roots=(canonical,),
                )
        except ManuscriptPathViolation as exc:
            _fail("UNSAFE_OUTPUT_PATH", str(exc))
        os.rename(staging, destination)
        staging = None
        return destination
    except ManuscriptIntegrationError:
        raise
    except Exception as exc:
        _fail("PUBLISH_FAILED", f"atomic source publication failed: {type(exc).__name__}")
    finally:
        if lock_fd is not None:
            os.close(lock_fd)
        if staging is not None and staging.exists():
            shutil.rmtree(staging)
        if lock.exists():
            lock.unlink()
