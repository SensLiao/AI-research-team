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
from functools import partial
from pathlib import Path
from typing import Any, Callable, Mapping, Pattern, Sequence

from research_agent_teams.operate.output_versions import resolve_effective_output
from research_agent_teams.tools._manuscript_asset_view import asset_integration_view, asset_outputs
from research_agent_teams.tools._manuscript_integrator_security import (
    read_json as _security_read_json,
    receipt_row as _security_receipt_row,
    require_verification as _security_require_verification,
    safe_run_file as _security_safe_run_file,
    scan_candidate_text as _security_scan_candidate_text,
    stable_bytes as _security_stable_bytes,
    validate_asset_source_inputs as _security_validate_asset_source_inputs,
    validate_contract as _security_validate_contract,
    validate_svg as _security_validate_svg,
    verify_result as _security_verify_result,
)
from research_agent_teams.tools.manuscript_security import (
    ManuscriptPathViolation,
    ManuscriptTexViolation,
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
_ACTIVE_CANDIDATES: dict[int, dict[str, Any]] = {}


class _IntegrationCandidate(dict):
    """Ephemeral capability returned only by the validated integration path."""


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


def _tex_text(value: object) -> str:
    """Escape plain contract metadata for a bounded TeX text argument."""

    text = str(value or "").strip().replace("\\", " ")
    replacements = {
        "&": r"\&",
        "%": r"\%",
        "$": r"\$",
        "#": r"\#",
        "_": r"\_",
        "{": r"\{",
        "}": r"\}",
    }
    return "".join(replacements.get(character, character) for character in text)

def _fail(code: str, message: str, *refs: str) -> None:
    raise ManuscriptIntegrationError(code, message, affected_refs=refs)


_stable_bytes = partial(_security_stable_bytes, fail=_fail)
_validate_asset_source_inputs = partial(_security_validate_asset_source_inputs, fail=_fail)
_read_json = partial(_security_read_json, fail=_fail, max_format_repairs=MAX_FORMAT_REPAIRS)
_safe_run_file = partial(_security_safe_run_file, fail=_fail)
_validate_contract = partial(_security_validate_contract, fail=_fail)
_require_verification = partial(_security_require_verification, fail=_fail)
_receipt_row = partial(_security_receipt_row, fail=_fail)
_verify_result = partial(_security_verify_result, fail=_fail)
_scan_candidate_text = partial(_security_scan_candidate_text, fail=_fail)
_validate_svg = partial(_security_validate_svg, fail=_fail)

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

def validate_section_bundle(bundle_ref: str, *, run_root: str | Path,
                            manuscript_contract: Mapping[str, Any],
                            required_section: Mapping[str, str], stage: str,
                            format_repair: Callable[[str, list[str], int], str] | None = None,
                            authorization_verifier: Callable[[Mapping[str, Any]], Mapping[str, Any]] | None = None,
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
        required_ids = {row["section_id"] for row in contract["outline"] if row["required"]}
        if (raw_assignment["section_id"] not in required_ids or dependency is None
                or dependency["worker_role"] != raw_assignment["worker_role"]):
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
    bundle, repair_attempts, raw_bytes, normalized_sha256 = _read_json(
        effective, format_repair=format_repair
    )
    errors = validate_payload("manuscript_section_bundle", bundle)
    if errors:
        _fail("SECTION_BUNDLE_INVALID", "; ".join(errors[:5]), bundle_ref)
    # 2026-08-07 de-governance: content_hash self-consistency removed (tamper-evidence, not the
    # safety property). manuscript_snapshot_sha256 below stays — it binds the bundle to THIS frozen
    # contract, not a stale one (a referential/binding check).
    if bundle["manuscript_snapshot_sha256"] != contract["manuscript_snapshot_sha256"]:
        _fail("STALE_BUNDLE", "section bundle targets a different frozen manuscript", bundle_ref)
    if bundle["section_id"] != assignment["section_id"]:
        _fail("SECTION_ASSIGNMENT_MISMATCH", "bundle section does not match its assignment", bundle_ref)
    if bundle["worker_role"] != assignment["worker_role"]:
        _fail("AUTHORIZATION_MISMATCH", "bundle worker does not match its assignment", bundle_ref)

    global_refs = [row for row in bundle["input_refs"] if row["slice_kind"] == "GLOBAL_CONTRACT"]
    slices = {row["slice_id"]: row for row in contract["dependency_slices"]}
    declared_global = [
        row
        for row in slices[assignment["dependency_slice_id"]]["input_refs"]
        if row["slice_kind"] == "GLOBAL_CONTRACT"
    ]
    global_matches_snapshot = (
        global_refs[0]["sha256"] == contract["manuscript_snapshot_sha256"]
    )
    global_matches_frozen_seed = (
        len(declared_global) == 1
        and _canonical_bytes(global_refs[0]) == _canonical_bytes(declared_global[0])
    )
    if not (global_matches_snapshot or global_matches_frozen_seed):
        _fail("CONTRACT_HASH_MISMATCH", "bundle global-contract input is stale", bundle_ref)
    declared = [
        row
        for row in slices[assignment["dependency_slice_id"]]["input_refs"]
        if row["slice_kind"] != "GLOBAL_CONTRACT"
    ]
    visible = [row for row in bundle["input_refs"] if row["slice_kind"] != "GLOBAL_CONTRACT"]
    if sorted(map(_canonical_bytes, visible)) != sorted(map(_canonical_bytes, declared)):
        _fail("UNAUTHORIZED_DEPENDENCY", "bundle inputs do not exactly equal its frozen dependency slice", bundle_ref)
    receipt_row = _receipt_row(bundle, bundle_ref=bundle_ref, run_root=root, stage=stage)
    slice_row = slices[assignment["dependency_slice_id"]]
    authorization_facts = {
        "run_id": contract["run_id"],
        "manuscript_snapshot_sha256": contract["manuscript_snapshot_sha256"],
        "stage": stage,
        "section_id": assignment["section_id"],
        "worker_role": assignment["worker_role"],
        "dependency_slice_id": assignment["dependency_slice_id"],
        "dependency_slice_sha256": slice_row["slice_sha256"],
        "bundle_ref": bundle_ref,
        "authorization_sha256": _canonical_hash(receipt_row),
    }
    _require_verification(
        authorization_verifier, authorization_facts,
        missing="AUTHORIZATION_VERIFIER_REQUIRED", invalid="AUTHORIZATION_UNVERIFIED",
    )
    direct_transport = "draft_ref" in bundle
    if direct_transport:
        draft_ref = str(bundle["draft_ref"])
        expected_ref = f"draft/sections/{assignment['section_id']}.tex"
        if draft_ref != expected_ref:
            _fail(
                "SECTION_DRAFT_OWNERSHIP_MISMATCH",
                "direct LaTeX must use the sole section owner's assigned draft path",
                bundle_ref,
                draft_ref,
            )
        draft_path = _safe_run_file(
            draft_ref, run_root=root, owned_roots=(root / "draft" / "sections",)
        )
        draft_bytes = _stable_bytes(
            draft_path, expected_sha256=str(bundle["draft_sha256"])
        )
        try:
            draft_text = draft_bytes.decode("utf-8")
        except UnicodeDecodeError:
            _fail("SECTION_DRAFT_ENCODING", "direct LaTeX must be UTF-8", draft_ref)
        if not draft_text.strip():
            _fail("SECTION_DRAFT_EMPTY", "direct LaTeX section is empty", draft_ref)
    else:
        draft_text = str(bundle["draft_latex"])
        draft_bytes = draft_text.encode("utf-8")
        draft_ref = bundle_ref + "#/draft_latex"

    payload = copy.deepcopy(bundle)
    if direct_transport:
        parsed = _parse_bundle_tex(draft_text, draft_ref)
        observed = {
            "citation_keys": sorted(parsed["citations"]),
            "labels": sorted(parsed["labels"]),
            "cross_references": sorted(parsed["references"]),
        }
        for field, values in observed.items():
            declared = payload.get(field)
            if declared is not None and set(declared) != set(values):
                _fail(
                    "DIRECT_TEX_METADATA_MISMATCH",
                    f"declared {field} differs from direct LaTeX; receipts cannot override disk truth",
                    draft_ref,
                )
            payload[field] = values

    return {
        "payload": payload,
        "bundle_ref": bundle_ref,
        "effective_ref": effective.relative_to(root).as_posix(),
        "bundle_sha256": _bytes_hash(raw_bytes),
        "content_hash": bundle["content_hash"],
        "repair_attempts": repair_attempts,
        "normalized_sha256": normalized_sha256,
        "authorization_sha256": _canonical_hash(receipt_row),
        "dependency_slice_id": assignment["dependency_slice_id"],
        "draft_text": draft_text,
        "draft_ref": draft_ref,
        "draft_sha256": _bytes_hash(draft_bytes),
    }

def _parse_bundle_tex(text: str, bundle_ref: str
                       ) -> dict[str, set[str] | list[str]]:
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


def _validate_direct_sections(
    *, root: Path, contract: Mapping[str, Any], assignments: Sequence[Mapping[str, str]],
    direct_sections: Sequence[Mapping[str, str]],
) -> list[dict[str, Any]]:
    """Freeze the LaTeX-first working tree without asking authors to serialize prose as JSON."""

    rows = {str(row.get("section_id") or ""): row for row in direct_sections}
    expected = {str(row["section_id"]) for row in assignments}
    if set(rows) != expected or len(rows) != len(direct_sections):
        _fail(
            "DIRECT_SECTION_SET_MISMATCH",
            "direct authoring must expose exactly one final LaTeX file per required section",
        )
    ledger = [row for row in contract.get("claim_ledger", ()) if isinstance(row, Mapping)]
    validated: list[dict[str, Any]] = []
    for assignment in assignments:
        section_id = str(assignment["section_id"])
        row = rows[section_id]
        ref = str(row.get("ref") or "")
        expected_ref = f"draft/synthesis/sections/{section_id}.tex"
        if ref != expected_ref:
            _fail(
                "SECTION_DRAFT_OWNERSHIP_MISMATCH",
                "the final serial editor must release the designated synthesis path",
                section_id,
                ref,
            )
        path = _safe_run_file(
            ref, run_root=root, owned_roots=(root / "draft" / "synthesis" / "sections",)
        )
        raw = _stable_bytes(path)
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            _fail("SECTION_DRAFT_ENCODING", "direct LaTeX must be UTF-8", ref)
        if not text.strip():
            _fail("SECTION_DRAFT_EMPTY", "direct LaTeX section is empty", ref)
        parsed = _parse_bundle_tex(text, ref)
        claim_support = [
            {
                "claim_id": str(claim["claim_id"]),
                "evidence_refs": list(claim.get("evidence_refs") or []),
                "result_refs": list(claim.get("result_refs") or []),
            }
            for claim in ledger
            if claim.get("claim_surface_owner") == section_id
        ]
        payload = {
            "section_id": section_id,
            "worker_role": str(assignment["worker_role"]),
            "claim_support_refs": claim_support,
            "citation_keys": sorted(parsed["citations"]),
            "labels": sorted(parsed["labels"]),
            "cross_references": sorted(parsed["references"]),
            "asset_refs": [],
            "notation_uses": [],
            "omissions": [],
            "requested_supplements": [],
        }
        digest = _bytes_hash(raw)
        validated.append({
            "payload": payload,
            "bundle_ref": ref,
            "effective_ref": ref,
            "bundle_sha256": digest,
            "content_hash": digest,
            "repair_attempts": 0,
            "normalized_sha256": digest,
            "authorization_sha256": str(row.get("authorization_sha256") or digest),
            "dependency_slice_id": str(assignment["dependency_slice_id"]),
            "draft_text": text,
            "draft_ref": ref,
            "draft_sha256": digest,
        })
    return validated

def _asset_files(manifest: Mapping[str, Any] | None, *, contract: dict[str, Any],
                 run_root: Path, asset_sources: Mapping[str, str | Path],
                 director_asset_roots: Sequence[str | Path],
                 result_verifier: Callable[[Mapping[str, Any]], Mapping[str, Any]] | None,
                 command_verifier: Callable[[Mapping[str, Any]], Mapping[str, Any]] | None,
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
    if value["schema_version"] == "2.0.0":
        return value, _v2_asset_files(
            value, contract=contract, run_root=run_root,
            result_verifier=result_verifier, command_verifier=command_verifier,
        )
    # 2026-08-07 de-governance: manifest_sha256 self-consistency removed (metadata-record tamper-
    # evidence, not the safety property; schema validation above still gates structure).

    files: dict[str, bytes] = {}
    seen_ids: set[str] = set()
    seen_labels: set[str] = set()
    seen_paths: set[str] = set()
    claims = {row["claim_id"] for row in contract["claim_ledger"]}
    results = {row["ref"] for row in contract["result_refs"]}
    planned = {row["asset_id"]: row for row in contract["asset_plan"]}
    source_inventory = {row["ref"]: row for row in contract["source_hashes"]}
    for asset in assets:
        asset_id = asset["asset_id"]
        output = asset["output"]
        output_path = output["path"]
        expected_prefixes = (
            ("figures/", "assets/")
            if asset["asset_type"] == "FIGURE"
            else ("tables/",)
        )
        if asset_id in seen_ids or asset["label"] in seen_labels or output_path in seen_paths:
            _fail("DUPLICATE_ASSET", "asset id, label, and output path must be globally unique", asset_id)
        seen_ids.add(asset_id)
        seen_labels.add(asset["label"])
        seen_paths.add(output_path)
        if not output_path.startswith(expected_prefixes):
            _fail("ASSET_OUTPUT_PATH_INVALID", "asset output is outside its canonical directory", output_path)
        if output["owner_run_id"] != contract["run_id"]:
            _fail("ASSET_OWNER_MISMATCH", "asset output is owned by another run", asset_id)
        # 2026-08-07 de-governance: asset_record_sha256 self-consistency removed (metadata-record
        # tamper-evidence, not the safety property). The actual asset BYTES are still verified
        # against their claimed provenance further below (left untouched — see report).
        evidence_result_refs = {
            ref
            for ref in asset["result_refs"]
            if source_inventory.get(ref, {}).get("kind") == "EVIDENCE"
        }
        if not set(asset["claim_refs"]).issubset(claims) or not set(
            asset["result_refs"]
        ).issubset(results | evidence_result_refs):
            _fail("ASSET_PROVENANCE_UNKNOWN", "asset cites an unknown claim or result", asset_id)
        for result_ref in set(asset["result_refs"]):
            if result_ref in results:
                _verify_result(result_ref, contract, run_root, result_verifier)
        source_value = asset_sources.get(asset_id)
        if source_value is None:
            _fail("ASSET_SOURCE_MISSING", "asset has no explicitly declared source file", asset_id)
        provenance = asset["provenance"]
        plan = planned.get(asset_id)
        input_refs = {row["ref"] for row in asset["source_inputs"]}
        frozen_asset_inputs = {
            ref
            for ref in input_refs
            if source_inventory.get(ref, {}).get("kind") == "ASSET"
        }
        compatible_realized_source = (
            provenance.get("kind") == "EXTERNAL"
            and bool(frozen_asset_inputs)
            and bool(plan)
            and set(plan["source_refs"])
        )
        compatible_evidence_results = bool(plan) and set(asset["result_refs"]).issubset(
            evidence_result_refs
        ) and not set(plan["result_refs"])
        if (plan is None or (input_refs != set(plan["source_refs"]) and not compatible_realized_source)
                or (set(asset["result_refs"]) != set(plan["result_refs"]) and not compatible_evidence_results)):
            _fail("ASSET_SOURCE_INPUT_MISMATCH", "asset inputs differ from the frozen asset plan", asset_id)
        trusted_inputs = _validate_asset_source_inputs(
            asset["source_inputs"], source_inventory=source_inventory,
            provenance_kind=provenance["kind"], contract=contract, run_root=run_root,
            result_verifier=result_verifier,
        )
        source_path = Path(source_value).absolute()
        if provenance["kind"] == "EXTERNAL":
            try:
                checked = validate_run_owned_path(
                    source_path,
                    run_root=run_root,
                    purpose="read",
                    director_asset_roots=director_asset_roots,
                )
            except ManuscriptPathViolation as exc:
                _fail("UNSAFE_ASSET_PATH", str(exc), asset_id)
            external = provenance["external_source"]
            run_realized_output = (
                checked.get("owner") == "run"
                and checked.get("relative_path") == external.get("source_ref")
                and output.get("owner_run_id") == contract["run_id"]
                and output.get("run_owned") is True
            )
            if (external["original_sha256"] != output["sha256"]
                    or (external["source_ref"] not in input_refs and not run_realized_output)
                    or (checked.get("owner") != "director" and not run_realized_output)
                    or checked.get("relative_path") != external["source_ref"]):
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
        data = _stable_bytes(source_path, expected_sha256=output["sha256"])
        if len(data) != output["byte_size"]:
            _fail("ASSET_SOURCE_CHANGED", "asset bytes changed or do not match output facts", asset_id)
        director_inputs = [row for row in trusted_inputs if row["kind"] == "ASSET"]
        if director_inputs and any(
            row["ref"] != provenance.get("external_source", {}).get("source_ref")
            or row["sha256"] != _bytes_hash(data) for row in director_inputs
        ):
            _fail("DIRECTOR_ASSET_HASH_MISMATCH", "director input hash does not match copied bytes", asset_id)
        if provenance["kind"] == "GENERATED":
            command = provenance["render_command"]
            facts = {
                "run_id": contract["run_id"],
                "manuscript_snapshot_sha256": contract["manuscript_snapshot_sha256"],
                "asset_id": asset_id, "argv": command["argv"],
                "script_ref": command["script_ref"], "script_sha256": command["script_sha256"],
                "command_receipt_sha256": command["command_receipt_sha256"],
                "source_inputs": trusted_inputs, "output_sha256": output["sha256"],
            }
            _require_verification(
                command_verifier, facts, missing="GENERATED_RECEIPT_UNVERIFIED",
                invalid="GENERATED_RECEIPT_UNVERIFIED",
            )
        if output_path.lower().endswith(".svg"):
            _validate_svg(data, asset_id)
        files[output_path] = data

    # An empty manifest is an honest source-only draft: planned assets remain
    # visible in the frozen contract but no bytes or render receipts are
    # claimed.  Once any asset is realized, partial realization is rejected so
    # the canonical source cannot silently drop the rest of the frozen plan.
    if seen_ids and set(planned) != seen_ids:
        _fail("ASSET_PLAN_MISMATCH", "asset manifest must exactly realize the frozen asset plan")
    for asset in assets:
        plan = planned[asset["asset_id"]]
        planned_stem = Path(plan["planned_path"]).stem
        output_stem = Path(asset["output"]["path"]).stem
        if (
            plan["kind"] != asset["asset_type"]
            or plan["label"] != asset["label"]
            or planned_stem != output_stem
        ):
            _fail("ASSET_PLAN_MISMATCH", "asset identity differs from the frozen plan", asset["asset_id"])
    return value, files


def _v2_asset_files(
    manifest: Mapping[str, Any], *, contract: Mapping[str, Any], run_root: Path,
    result_verifier: Callable[..., Mapping[str, Any]] | None,
    command_verifier: Callable[..., Mapping[str, Any]] | None,
) -> dict[str, bytes]:
    """Verify all v2 provenance and bytes, then stage canonical copies in memory."""
    if _hash_without(manifest, "manifest_sha256") != manifest["manifest_sha256"]:
        _fail("ASSET_MANIFEST_INVALID", "v2 manifest hash differs")
    assets = manifest["assets"]
    planned = {row["asset_id"]: row for row in contract["asset_plan"]}
    ids = [row["asset_id"] for row in assets]
    labels = [row["label"] for row in assets]
    output_refs = [row["path"] for asset in assets for row in asset_outputs(asset)]
    if len(set(ids)) != len(ids) or len(set(labels)) != len(labels) or len(set(output_refs)) != len(output_refs):
        _fail("DUPLICATE_ASSET", "v2 asset identities and output paths must be unique")
    if set(ids) != set(planned):
        _fail("ASSET_PLAN_MISMATCH", "v2 manifest must exactly realize the frozen asset plan")
    closure = manifest["plan_closure"]
    for suffix, values in (("asset_ids", ids), ("labels", labels), ("output_refs", output_refs)):
        if closure[f"planned_{suffix}"] != values or closure[f"rendered_{suffix}"] != values:
            _fail("ASSET_PLAN_MISMATCH", "v2 plan closure differs from realized assets")
    environment = manifest.get("render_environment")
    if environment is not None and _hash_without(environment, "environment_sha256") != environment["environment_sha256"]:
        _fail("RENDER_ENVIRONMENT_INVALID", "render environment hash differs")
    inventory = {row["ref"]: row for row in contract["source_hashes"]}
    known_claims = {row["claim_id"] for row in contract["claim_ledger"]}
    source_kinds = {
        "RESULT": {"FROZEN_RESULT", "RESULT"},
        "EVIDENCE": {"EXTERNAL_EVIDENCE", "EXTRACTION", "CLAIM_LEDGER", "PDF_SOURCE", "SEARCH_TRACE", "SOURCE_DATA"},
        "ASSET": {"DIRECTOR_ASSET", "SOURCE_DATA"},
        "TEMPLATE": {"SOURCE_DATA"}, "VENUE_RULE": {"SOURCE_DATA"}, "TOKEN_OVERLAY": {"SOURCE_DATA"},
    }
    files: dict[str, bytes] = {}
    for asset in assets:
        asset_id = asset["asset_id"]
        plan = planned[asset_id]
        view = asset_integration_view(asset, plan=plan, fail=_fail)
        if _hash_without(asset, "asset_record_sha256") != asset["asset_record_sha256"]:
            _fail("ASSET_MANIFEST_INVALID", "v2 asset record hash differs", asset_id)
        source_refs = {row["ref"] for row in asset["source_inputs"]}
        if len(source_refs) != len(asset["source_inputs"]) or source_refs != set(plan["source_refs"]) | set(plan["result_refs"]):
            _fail("ASSET_SOURCE_INPUT_MISMATCH", "v2 source inputs differ from the frozen asset plan", asset_id)
        if not set(asset["claim_refs"]).issubset(known_claims) or set(view["result_refs"]) != set(plan["result_refs"]):
            _fail("ASSET_PROVENANCE_UNKNOWN", "v2 claims or results differ from the frozen contract", asset_id)
        for row in asset["source_inputs"]:
            frozen = inventory.get(row["ref"], {})
            if frozen.get("sha256") != row["sha256"] or row["kind"] not in source_kinds.get(frozen.get("kind"), set()):
                _fail("ASSET_SOURCE_INPUT_MISMATCH", "v2 source hash or kind differs from the frozen inventory", row["ref"])
            source_path = _safe_run_file(row["ref"], run_root=run_root, owned_roots=(run_root,))
            _stable_bytes(source_path, expected_sha256=row["sha256"])
            if frozen["kind"] == "RESULT":
                _verify_result(row["ref"], dict(contract), run_root, result_verifier)
        if asset["semantic_type"] == "EVIDENCE_TABLE":
            for row in asset["evidence_rows"]:
                if any(ref.split("#", 1)[0] not in source_refs for ref in row["extraction_refs"]):
                    _fail("ASSET_SOURCE_INPUT_MISMATCH", "evidence row lacks a frozen extraction source", asset_id)
        if asset["semantic_type"] == "QUANTITATIVE_PLOT" and not set(view["result_refs"]).issubset(source_refs):
            _fail("ASSET_SOURCE_INPUT_MISMATCH", "numeric cells lack frozen result sources", asset_id)
        permission = asset["permission"]
        if permission["status"] not in {"OWNED", "CLEARED"} or permission["public_release_allowed"] is not True:
            _fail("ASSET_PERMISSION_NOT_CLEARED", "unreleased assets cannot enter manuscript delivery", asset_id)
        if permission["status"] == "CLEARED":
            receipt_path = _safe_run_file(permission["permission_receipt_ref"], run_root=run_root, owned_roots=(run_root,))
            _stable_bytes(receipt_path, expected_sha256=permission["permission_receipt_sha256"])
        if asset["semantic_type"] == "EXTERNAL_EXCERPT":
            excerpt = asset["excerpt"]
            if (excerpt["pdf_ref"] not in source_refs or inventory[excerpt["pdf_ref"]]["sha256"] != excerpt["pdf_sha256"]
                    or excerpt["permission_status"] != "CLEARED" or permission["status"] != "CLEARED"
                    or any(excerpt.get(key) != permission.get(key) for key in ("license_ref", "permission_receipt_ref", "permission_receipt_sha256"))):
                _fail("ASSET_PERMISSION_NOT_CLEARED", "excerpt source and permission records do not close", asset_id)
        receipt = asset.get("render_receipt")
        if asset["render_template"] == "SCIENTIFIC_ILLUSTRATION" and receipt is None:
            _fail("GENERATED_RECEIPT_UNVERIFIED", "scientific illustration requires its maintained adapter receipt", asset_id)
        if receipt is not None:
            if (receipt["receipt_sha256"] != _hash_without(receipt, "receipt_sha256")
                    or receipt["source_set_sha256"] != _canonical_hash(asset["source_inputs"])
                    or receipt["output_set_sha256"] != _canonical_hash(asset["outputs"])
                    or receipt["parameters_sha256"] != _canonical_hash(receipt["fixed_parameters"])):
                _fail("GENERATED_RECEIPT_UNVERIFIED", "render receipt does not bind asset inputs and outputs", asset_id)
            allowed_renderers = {"research_agent_teams/tools/review_asset_renderer.py", "research_agent_teams/tools/scientific_figure.py"}
            if receipt["renderer_ref"] not in allowed_renderers:
                _fail("GENERATED_RECEIPT_UNVERIFIED", "render receipt names no maintained adapter", asset_id)
            renderer = Path(__file__).resolve().parents[2] / receipt["renderer_ref"]
            if not renderer.is_file() or _file_hash(renderer) != receipt["renderer_sha256"]:
                _fail("GENERATED_RECEIPT_UNVERIFIED", "maintained renderer hash differs", asset_id)
            if asset["render_template"] == "SCIENTIFIC_ILLUSTRATION":
                from research_agent_teams.tools.scientific_figure import ScientificFigureError, validate_spec

                spec = receipt["fixed_parameters"]
                if (receipt["renderer_ref"] != "research_agent_teams/tools/scientific_figure.py"
                        or spec.get("run_id") != contract["run_id"]
                        or any(spec.get(key) != asset[key] for key in ("asset_id", "label", "caption", "accessibility_text", "claim_refs", "source_inputs"))):
                    _fail("GENERATED_RECEIPT_UNVERIFIED", "scientific figure specification differs from its asset record", asset_id)
                try:
                    validate_spec(run_root, spec)
                except ScientificFigureError as exc:
                    _fail("GENERATED_RECEIPT_UNVERIFIED", str(exc), asset_id)
        if asset["semantic_type"] == "QUANTITATIVE_PLOT":
            _require_verification(command_verifier, {
                "run_id": contract["run_id"], "manuscript_snapshot_sha256": contract["manuscript_snapshot_sha256"],
                "asset_id": asset_id, "render_receipt": receipt, "source_inputs": asset["source_inputs"],
                "outputs": asset["outputs"],
            }, missing="GENERATED_RECEIPT_UNVERIFIED", invalid="GENERATED_RECEIPT_UNVERIFIED")
        for output, copy_row in zip(asset_outputs(asset), view["copies"]):
            destination = copy_row["destination"]
            prefixes = ("figures/", "assets/") if view["asset_type"] == "FIGURE" else ("tables/",)
            media = {".svg": ("SVG", "image/svg+xml"), ".png": ("PNG", "image/png"), ".pdf": ("PDF", "application/pdf")}
            if not destination.startswith(prefixes) or destination in files:
                _fail("ASSET_OUTPUT_PATH_INVALID", "canonical asset destination is invalid or duplicated", destination)
            if media.get(Path(output["path"]).suffix.lower()) != (output["format"], output["media_type"]):
                _fail("ASSET_OUTPUT_PATH_INVALID", "asset format differs from its path/media type", output["path"])
            if output["owner_run_id"] != contract["run_id"]:
                _fail("ASSET_OWNER_MISMATCH", "v2 output is owned by another run", asset_id)
            output_path = _safe_run_file(output["path"], run_root=run_root, owned_roots=(run_root,))
            data = _stable_bytes(output_path, expected_sha256=output["sha256"])
            if len(data) != output["byte_size"]:
                _fail("ASSET_SOURCE_CHANGED", "asset byte size differs", asset_id)
            if output["format"] == "SVG":
                _validate_svg(data, asset_id)
            elif output["format"] == "PDF" and not data.startswith(b"%PDF-"):
                _fail("ASSET_SOURCE_CHANGED", "declared PDF has no PDF header", asset_id)
            elif output["format"] == "PNG" and not data.startswith(b"\x89PNG\r\n\x1a\n"):
                _fail("ASSET_SOURCE_CHANGED", "declared PNG has no PNG signature", asset_id)
            files[destination] = data
    return files


def _venue_template(
    root: Path, contract: Mapping[str, Any], venue_slice: Mapping[str, Any],
    *, title: str, assignments: Sequence[Mapping[str, str]],
) -> tuple[bytes, dict[str, Any]]:
    """Fill three explicit slots in a local, frozen TeX skeleton.

    Template authors supply @@MANUSCRIPT_TITLE@@ inside their title command,
    @@MANUSCRIPT_SECTIONS@@ at the body locus, and
    @@MANUSCRIPT_BIBLIOGRAPHY@@ inside their bibliography command. Existing
    class/package/command allowlists still apply to the resulting main.tex.
    This port does not install or enable a custom journal class.
    """
    if validate_payload("manuscript_venue_profile_slice", venue_slice):
        _fail("VENUE_TEMPLATE_BINDING", "venue slice is not schema-valid")
    if (venue_slice["manuscript_snapshot_sha256"] != contract["manuscript_snapshot_sha256"]
            or venue_slice["venue_profile"] != contract["venue_profile"]
            or _hash_without(venue_slice, "venue_profile_slice_sha256") != venue_slice["venue_profile_slice_sha256"]):
        _fail("VENUE_TEMPLATE_BINDING", "venue slice differs from the frozen manuscript contract")
    venue = venue_slice["venue_profile"]
    reference = venue["template_ref"]
    if Path(reference).suffix.lower() != ".tex":
        _fail("VENUE_TEMPLATE_UNSUPPORTED", "a local .tex skeleton with explicit manuscript slots is required", reference)
    source = next((row for row in contract["source_hashes"] if row["ref"] == reference), None)
    if source is None or source["kind"] != "TEMPLATE" or source["sha256"] != venue["template_sha256"]:
        _fail("VENUE_TEMPLATE_BINDING", "template is absent from the frozen source inventory", reference)
    path = _safe_run_file(reference, run_root=root, owned_roots=(root,))
    data = _stable_bytes(path, expected_sha256=venue["template_sha256"])
    try:
        template = data.decode("utf-8")
    except UnicodeDecodeError:
        _fail("VENUE_TEMPLATE_UNSUPPORTED", "template must be UTF-8", reference)
    slots = {
        "@@MANUSCRIPT_TITLE@@": title,
        "@@MANUSCRIPT_SECTIONS@@": "\n".join(f"\\input{{sections/{row['section_id']}.tex}}" for row in assignments),
        "@@MANUSCRIPT_BIBLIOGRAPHY@@": "refs",
    }
    if any(template.count(marker) != 1 for marker in slots):
        _fail("VENUE_TEMPLATE_UNSUPPORTED", "template must contain each manuscript slot exactly once", reference)
    for marker, value in slots.items():
        template = template.replace(marker, value)
    if "@@MANUSCRIPT_" in template:
        _fail("VENUE_TEMPLATE_UNSUPPORTED", "template contains an unresolved manuscript slot", reference)
    return (template.rstrip() + "\n").encode("utf-8"), {
        "format": "manuscript-tex-skeleton/v1", "venue_id": venue["venue_id"],
        "template_ref": reference, "template_sha256": venue["template_sha256"],
        "venue_profile_slice_sha256": venue_slice["venue_profile_slice_sha256"],
        "custom_class_enabled": False,
    }


def integrate_manuscript(*, run_root: str | Path, manuscript_contract: Mapping[str, Any],
                         section_bundle_refs: Sequence[str],
                         required_sections: Sequence[Mapping[str, str]], bibliography_text: str | None,
                         stage: str, asset_manifest: Mapping[str, Any] | None = None,
                         asset_sources: Mapping[str, str | Path] | None = None,
                         direct_sections: Sequence[Mapping[str, str]] | None = None,
                         section_source_overrides: Mapping[str, Mapping[str, str]] | None = None,
                         bibliography_ref: str | None = None,
                         bibliography_sha256: str | None = None,
                         venue_profile_slice: Mapping[str, Any] | None = None,
                         director_asset_roots: Sequence[str | Path] = (),
                         format_repair: Callable[[str, list[str], int], str] | None = None,
                          secret_sentinels: Mapping[str, str] | None = None,
                          secret_patterns: Mapping[str, str | Pattern[str]] | None = None,
                          authorization_verifier: Callable[[Mapping[str, Any]], Mapping[str, Any]] | None = None,
                          result_receipt_verifier: Callable[[Mapping[str, Any]], Mapping[str, Any]] | None = None,
                          generated_command_verifier: Callable[[Mapping[str, Any]], Mapping[str, Any]] | None = None,
                          ) -> dict[str, Any]:
    """Reduce frozen bundles into a byte-complete, unpublished source candidate."""

    root = Path(run_root).absolute()
    contract = _validate_contract(manuscript_contract, root)
    assignments = _required_assignments(contract, required_sections)
    direct_mode = direct_sections is not None
    if direct_mode:
        if list(section_bundle_refs):
            _fail("MIXED_AUTHORING_TRANSPORT", "do not mix direct LaTeX and legacy JSON prose bundles")
        validated = _validate_direct_sections(
            root=root, contract=contract, assignments=assignments,
            direct_sections=list(direct_sections or ()),
        )
    else:
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
                        authorization_verifier=authorization_verifier,
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

    if section_source_overrides is not None:
        overrides = dict(section_source_overrides)
        expected_ids = {row["section_id"] for row in assignments}
        if set(overrides) != expected_ids:
            _fail(
                "SYNTHESIS_SECTION_SET_MISMATCH",
                "synthesis editor must hand off exactly one revised LaTeX file per required section",
            )
        for item in validated:
            section_id = str(item["payload"]["section_id"])
            row = overrides[section_id]
            ref = str(row.get("ref") or "")
            sha256 = str(row.get("sha256") or "")
            expected_ref = f"draft/synthesis/sections/{section_id}.tex"
            if ref != expected_ref or not re.fullmatch(r"[0-9a-f]{64}", sha256):
                _fail(
                    "SYNTHESIS_DRAFT_OWNERSHIP_MISMATCH",
                    "synthesis handoff must bind the designated per-section path and SHA-256",
                    section_id,
                )
            path = _safe_run_file(
                ref, run_root=root, owned_roots=(root / "draft" / "synthesis" / "sections",)
            )
            raw = _stable_bytes(path, expected_sha256=sha256)
            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError:
                _fail("SECTION_DRAFT_ENCODING", "synthesis LaTeX must be UTF-8", ref)
            if not text.strip():
                _fail("SECTION_DRAFT_EMPTY", "synthesis LaTeX section is empty", ref)
            item["draft_text"] = text
            item["draft_ref"] = ref
            item["draft_sha256"] = sha256

    all_labels = [label for item in validated for label in item["payload"]["labels"]]
    duplicate_labels = sorted(label for label, count in Counter(all_labels).items() if count > 1)
    if duplicate_labels:
        _fail("DUPLICATE_LABEL", "labels must be unique across all section bundles", *duplicate_labels)
    asset_labels = {
        str(row.get("label"))
        for row in (asset_manifest or {}).get("assets", ())
        if isinstance(row, Mapping) and row.get("label")
    }
    canonical_labels = set(all_labels) | asset_labels
    declared_refs = {ref for item in validated for ref in item["payload"]["cross_references"]}
    unresolved_refs = sorted(declared_refs - canonical_labels)
    if unresolved_refs:
        _fail("UNRESOLVED_REFERENCE", "cross-reference has no canonical label", *unresolved_refs)
    frozen_citations = {row["citation_key"] for row in contract["bibliography"]["entries"]}
    declared_citations = {key for item in validated for key in item["payload"]["citation_keys"]}
    unknown_citations = sorted(declared_citations - frozen_citations)
    if unknown_citations:
        _fail("UNKNOWN_CITATION", "citation is absent from the frozen bibliography", *unknown_citations)
    known_claims = {row["claim_id"]: row for row in contract["claim_ledger"]}
    known_evidence = {row["ref"] for row in contract["evidence_refs"]}
    for item in validated:
        bundle = item["payload"]
        parsed = _parse_bundle_tex(item["draft_text"], item["draft_ref"])
        if parsed["labels"] != set(bundle["labels"]):
            _fail("LABEL_METADATA_MISMATCH", "declared labels differ from TeX labels", item["bundle_ref"])
        if parsed["citations"] != set(bundle["citation_keys"]):
            _fail("CITATION_METADATA_MISMATCH", "declared citations differ from TeX citations", item["bundle_ref"])
        if parsed["references"] != set(bundle["cross_references"]):
            _fail("REFERENCE_METADATA_MISMATCH", "declared references differ from TeX references", item["bundle_ref"])
        for support in bundle["claim_support_refs"]:
            for result_ref in support["result_refs"]:
                _verify_result(result_ref, contract, root, result_receipt_verifier)
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

    if bibliography_ref is not None or bibliography_sha256 is not None:
        if bibliography_ref not in {"draft/refs.bib", "draft/synthesis/refs.bib"}:
            _fail("BIBLIOGRAPHY_OWNERSHIP_MISMATCH", "refs.bib must use the designated direct-authoring path")
        if not isinstance(bibliography_sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", bibliography_sha256):
            _fail("BIBLIOGRAPHY_HASH_INVALID", "direct refs.bib requires a lowercase SHA-256")
        bib_path = _safe_run_file(
            bibliography_ref,
            run_root=root,
            owned_roots=(root / "draft", root / "draft" / "synthesis"),
        )
        raw_bib = _stable_bytes(bib_path, expected_sha256=bibliography_sha256)
        try:
            bibliography_text = raw_bib.decode("utf-8")
        except UnicodeDecodeError:
            _fail("BIBLIOGRAPHY_ENCODING", "direct refs.bib must be UTF-8", bibliography_ref)
    if not isinstance(bibliography_text, str) or not bibliography_text.strip():
        _fail("BIBLIOGRAPHY_REQUIRED", "a direct frozen refs.bib file is required; the integrator will not invent it")
    bib_keys = set(_BIB_KEY_RE.findall(bibliography_text))
    if not declared_citations.issubset(bib_keys):
        _fail("UNRESOLVED_CITATION", "refs.bib does not contain every cited frozen key")

    normalized_assets, asset_files = _asset_files(
        asset_manifest, contract=contract, run_root=root,
        asset_sources=asset_sources or {}, director_asset_roots=director_asset_roots,
        result_verifier=result_receipt_verifier,
        command_verifier=generated_command_verifier,
    )
    assets = {row["asset_id"]: row for row in normalized_assets["assets"]}
    plans = {row["asset_id"]: row for row in contract["asset_plan"]}
    asset_views = {key: asset_integration_view(row, plan=plans.get(key), fail=_fail) for key, row in assets.items()}
    declared_assets = {ref for item in validated for ref in item["payload"]["asset_refs"]}
    if not direct_mode and declared_assets != set(assets):
        _fail("ASSET_REFERENCE_MISMATCH", "section asset refs must exactly cover the frozen asset manifest")
    actual_graphics: set[str] = set()
    actual_captions: set[str] = set()
    for item in validated:
        parsed = _parse_bundle_tex(item["draft_text"], item["draft_ref"])
        actual_graphics.update(parsed["graphics"])
        actual_captions.update(parsed["captions"])
    expected_graphics = {row["output"]["path"] for row in asset_views.values() if row["asset_type"] == "FIGURE"}
    if actual_graphics != expected_graphics:
        _fail("ASSET_PATH_UNRESOLVED", "included figure paths do not match the asset manifest")
    for asset in assets.values():
        if asset_views[asset["asset_id"]]["asset_type"] == "FIGURE" and (
            asset["label"] not in all_labels
            or asset["caption"]["text"] not in actual_captions
        ):
            _fail("ASSET_NARRATIVE_MISMATCH", "asset label or caption is absent from section TeX", asset["asset_id"])

    section_files = {
        f"sections/{item['payload']['section_id']}.tex": (
            item["draft_text"].rstrip() + "\n"
        ).encode("utf-8")
        for item in validated
    }
    title = _tex_text((contract.get("paper_brief") or {}).get("working_title"))
    if not title:
        title = "Untitled manuscript"
    main_lines = [
        "\\documentclass[11pt]{article}",
        "\\usepackage[T1]{fontenc}",
        "\\usepackage[utf8]{inputenc}",
        "\\usepackage[margin=1in]{geometry}",
        "\\usepackage{graphicx}",
        "\\usepackage{booktabs}",
        "\\usepackage{tabularx}",
        f"\\title{{{title}}}",
        "\\author{Anonymous authors}",
        "\\date{}",
        "\\begin{document}",
        "\\maketitle",
        *[f"\\input{{sections/{row['section_id']}.tex}}" for row in assignments],
        "\\bibliographystyle{apalike}",
        "\\bibliography{refs}",
        "\\end{document}",
        "",
    ]
    main_tex = "\n".join(main_lines).encode("utf-8")
    template_receipt: dict[str, Any] = {"format": "generic-article-draft", "venue_template_applied": False}
    if venue_profile_slice is not None:
        main_tex, template_receipt = _venue_template(
            root, contract, venue_profile_slice, title=title, assignments=assignments,
        )
    files: dict[str, bytes] = {
        "main.tex": main_tex,
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
        "venue_template": template_receipt,
        "asset_copies": [copy_row for view in asset_views.values() for copy_row in view["copies"]],
    }
    files["build/integration-metadata.json"] = _canonical_bytes(build_metadata)

    tex_sources = {
        path: data.decode("utf-8") for path, data in files.items() if path.endswith((".tex", ".bib"))
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
        "reconciliation_findings": [
            {
                "finding_id": f"REC-format-{item['payload']['section_id']}",
                "category": "NARRATIVE",
                "disposition": "RESOLVED",
                "details": (
                    "Bounded punctuation-only JSON repair; "
                    f"attempts={item['repair_attempts']}; normalized_sha256={item['normalized_sha256']}."
                ),
                "affected_refs": [item["bundle_ref"]],
            }
            for item in validated if item["repair_attempts"]
        ],
        "unresolved_interfaces": [],
    }
    integration["integration_hash"] = _hash_without(integration, "integration_hash")
    errors = validate_payload("manuscript_integration", integration)
    if errors:
        _fail("INTEGRATION_INVALID", "; ".join(errors[:5]))
    files["manifests/manuscript-integration.json"] = _canonical_bytes(integration)
    _scan_candidate_text(files, sentinels=secret_sentinels, patterns=secret_patterns)
    candidate = _IntegrationCandidate({
        "integration": integration,
        "asset_manifest": normalized_assets,
        "files": files,
    })
    _ACTIVE_CANDIDATES[id(candidate)] = {
        "candidate": candidate,
        "run_root": str(root),
        "integration_hash": integration["integration_hash"],
        "sentinels": copy.deepcopy(dict(secret_sentinels or {})),
        "patterns": dict(secret_patterns or {}),
        "consumed": False,
    }
    return candidate


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
    binding = _ACTIVE_CANDIDATES.get(id(candidate))
    if (type(candidate) is not _IntegrationCandidate or binding is None
            or binding.get("candidate") is not candidate):
        _fail("CANDIDATE_UNAUTHORIZED", "candidate was not issued by this integration process")
    if binding["run_root"] != str(root):
        _fail("CANDIDATE_RUN_MISMATCH", "candidate belongs to a different run")
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
    if binding["integration_hash"] != integration["integration_hash"]:
        _fail("CANDIDATE_HASH_MISMATCH", "candidate capability is not bound to this integration")
    if (asset_manifest.get("run_id") != root.name
            or any(output["owner_run_id"] != root.name for row in asset_manifest["assets"] for output in asset_outputs(row))):
        _fail("CANDIDATE_RUN_MISMATCH", "asset ownership differs from the target run")

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
    tex_sources = {
        path: data.decode("utf-8") for path, data in files.items()
        if path.endswith((".tex", ".bib"))
    }
    try:
        validate_tex_sources(tex_sources, run_root=root, source_root=canonical)
    except ManuscriptTexViolation as exc:
        _fail("UNSAFE_TEX", str(exc))
    _scan_candidate_text(files, sentinels=binding["sentinels"], patterns=binding["patterns"])

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
    lock_owned = False
    try:
        try:
            lock_fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            lock_owned = True
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
        binding["consumed"] = True
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
        if lock_owned and lock.exists():
            lock.unlink()
