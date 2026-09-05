"""Concrete, local-first operated recipe for manuscript authoring.

The recipe deliberately owns orchestration only.  It cannot promote, submit,
download a corpus, run a GPU job, or turn a self-reported PDF into a trusted
claim.  Existing deterministic modules own frozen contracts, exact-one section
integration, bounded LaTeX compilation, audit reduction, and director-facing
rendering.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from .. import bounded_repair
from ..artifacts import GateBlock, write_artifact
from . import _shared
from ...tools.latex_build import build_latex_project
from ...tools.latex_gen_lint import lint_tex_tree
from ...tools._manuscript_asset_view import asset_integration_view
from ...tools.manuscript_audit import audit_manuscript
from ...tools.manuscript_contract import freeze_manuscript_contract
from ...tools.manuscript_integrator import (
    ManuscriptIntegrationError,
    integrate_manuscript,
    materialize_source_tree,
)
from ...tools.manuscript_literature import assess_local_coverage, route_coverage_deficits
from ...tools.manuscript_security import ManuscriptPathViolation, validate_run_owned_path
from ...tools.validate_artifact import validate_payload


STAGES = ["DISCOVER", "DESIGN", "ANALYZE", "VERIFY", "REPORT"]
DEFAULT_VAULT = "AI agent database/PhD-Research-OS"

SPECIALIZED_SECTION_OWNERS = {
    "introduction": "manuscript-introduction-author",
    "related_work": "manuscript-related-work-author",
    "methods": "manuscript-methods-author",
    "results": "manuscript-results-author",
}
SECTION_AUTHOR_ROLES = {
    "manuscript-introduction-author",
    "manuscript-related-work-author",
    "manuscript-methods-author",
    "manuscript-results-author",
    "manuscript-section-author",
}

WORKER_ROOT_REL = "inbox/manuscript-authoring"
CONTRACT_REL = f"{WORKER_ROOT_REL}/manuscript-contract.json"
ASSIGNMENTS_REL = f"{WORKER_ROOT_REL}/section-assignments.json"
DISCOVERY_REL = f"{WORKER_ROOT_REL}/manuscript-venue-corpus-scout.bundle.json"
ARCHITECT_REL = f"{WORKER_ROOT_REL}/manuscript-architect.bundle.json"
EVIDENCE_STEWARD_REL = f"{WORKER_ROOT_REL}/manuscript-evidence-steward.bundle.json"
ASSET_ENGINEER_REL = f"{WORKER_ROOT_REL}/manuscript-figure-table-engineer.bundle.json"
SYNTHESIS_EDITOR_REL = f"{WORKER_ROOT_REL}/manuscript-synthesis-editor.bundle.json"
VERIFY_SUMMARY_REL = f"{WORKER_ROOT_REL}/authoring-audit-summary.json"

DISCOVERY_COVERAGE_ARTIFACT = "evidence/DISCOVER/local-literature-coverage.artifact.json"
DESIGN_CONTRACT_ARTIFACT = "evidence/DESIGN/manuscript-contract.artifact.json"
ANALYZE_INTEGRATION_ARTIFACT = "evidence/ANALYZE/manuscript-integration.artifact.json"
ANALYZE_ASSET_ARTIFACT = "evidence/ANALYZE/manuscript-asset-manifest.artifact.json"
ANALYZE_BUILD_ARTIFACT = "evidence/ANALYZE/manuscript-build-receipt.artifact.json"
ANALYZE_QUALITY_ARTIFACT = "evidence/ANALYZE/manuscript-quality-report.artifact.json"
DESIGN_CLAIM_EVIDENCE_MAP_ARTIFACT = "evidence/DESIGN/claim-evidence-map.artifact.json"
DESIGN_VENUE_PROFILE_SLICE_ARTIFACT = "evidence/DESIGN/manuscript-venue-profile-slice.artifact.json"
DESIGN_EVIDENCE_SLICE_ARTIFACT = "evidence/DESIGN/manuscript-evidence-slice.artifact.json"

_SECTION_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_OFFICIAL_PROFILE_MAX_AGE = timedelta(days=366)
AGENT_SPEC_DIR = Path(__file__).resolve().parents[2] / "agents"

# Deployment integrations set these explicit authority adapters.  Leaving one
# unset never upgrades a claim: the downstream deterministic utility fails
# closed when the relevant external fact is required.
AUTHORIZATION_VERIFIER: Callable[[Mapping[str, Any]], Mapping[str, Any]] | None = None
RESULT_RECEIPT_VERIFIER: Callable[[Mapping[str, Any]], Mapping[str, Any]] | None = None
GENERATED_COMMAND_VERIFIER: Callable[[Mapping[str, Any]], Mapping[str, Any]] | None = None
BUILD_RECEIPT_VERIFIER: Callable[..., Mapping[str, Any]] | None = None


class ManuscriptAuthoringError(ValueError):
    """A stable recipe-level refusal before an unsafe downstream transform."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(f"{code}: {message}")


def _fail(code: str, message: str) -> None:
    raise ManuscriptAuthoringError(code, message)


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        _fail("NON_CANONICAL_VALUE", str(exc))


def _hash(value: Any, *, omit: str | None = None) -> str:
    if omit is not None:
        value = {key: item for key, item in dict(value).items() if key != omit}
    return hashlib.sha256(_canonical(value)).hexdigest()


def _path(run_dir: str | Path, relative: str, *, purpose: str = "read") -> Path:
    root = Path(run_dir).absolute()
    try:
        checked = validate_run_owned_path(
            relative,
            run_root=root,
            purpose=purpose,
            owned_output_roots=(root / "inbox", root / "evidence", root / "draft", root / "source", root / "build", root / "director-review"),
        )
    except ManuscriptPathViolation as exc:
        _fail("PATH_ESCAPE_OR_AMBIGUITY", str(exc))
    return Path(checked["path"])


def _read_json(run_dir: str | Path, relative: str, *, required: bool = True) -> dict[str, Any] | None:
    path = _path(run_dir, relative)
    if not path.is_file():
        if required:
            _fail("MISSING_ARTIFACT", f"required manuscript artifact is missing: {relative}")
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        _fail("CORRUPT_ARTIFACT", f"cannot parse {relative}: {type(exc).__name__}")
    if not isinstance(value, dict):
        _fail("CORRUPT_ARTIFACT", f"{relative} must contain an object")
    return value


def _write_json_once(run_dir: str | Path, relative: str, value: Mapping[str, Any]) -> str:
    path = _path(run_dir, relative, purpose="write")
    data = _canonical(dict(value)) + b"\n"
    if path.exists():
        try:
            existing = path.read_bytes()
        except OSError as exc:
            _fail("ARTIFACT_READ_FAILED", f"cannot read existing {relative}: {type(exc).__name__}")
        if existing != data:
            _fail("IMMUTABLE_ARTIFACT_CONFLICT", f"existing artifact differs: {relative}")
        return relative
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as handle:
            handle.write(data)
    except FileExistsError:
        return _write_json_once(run_dir, relative, value)
    return relative


def _payload(value: Mapping[str, Any], key: str | None = None) -> dict[str, Any]:
    raw = value.get("payload") if isinstance(value.get("payload"), Mapping) else value
    if key is None:
        return copy.deepcopy(dict(raw))
    candidate = raw.get(key) if isinstance(raw, Mapping) else None
    if not isinstance(candidate, Mapping):
        _fail("WORKER_BUNDLE_MISSING", f"worker bundle is missing object {key!r}")
    return copy.deepcopy(dict(candidate))


def _worker_rel(role: str, *, section_id: str | None = None) -> str:
    if not _SECTION_ID.fullmatch(role):
        _fail("INVALID_WORKER_ROLE", f"unsafe worker role {role!r}")
    suffix = f"--{section_id}" if section_id is not None else ""
    if section_id is not None and not _SECTION_ID.fullmatch(section_id):
        _fail("INVALID_SECTION_ID", f"unsafe section id {section_id!r}")
    return f"{WORKER_ROOT_REL}/{role}{suffix}.bundle.json"


def _draft_section_ref(section_id: str, *, synthesis: bool = False) -> str:
    if not _SECTION_ID.fullmatch(section_id):
        _fail("INVALID_SECTION_ID", f"unsafe section id {section_id!r}")
    prefix = "draft/synthesis/sections" if synthesis else "draft/sections"
    return f"{prefix}/{section_id}.tex"


def _worker_payload(run_dir: str | Path, role: str, *, key: str, section_id: str | None = None,
                    required: bool = True) -> dict[str, Any] | None:
    raw = _read_json(run_dir, _worker_rel(role, section_id=section_id), required=required)
    return None if raw is None else _payload(raw, key)


def _artifact_payload(run_dir: str | Path, relative: str, *, required: bool = True) -> dict[str, Any] | None:
    raw = _read_json(run_dir, relative, required=required)
    return None if raw is None else _payload(raw)


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        _fail("ARTIFACT_READ_FAILED", f"cannot hash {path.name}: {type(exc).__name__}")
    return digest.hexdigest()


def _bound_run_reference(run_dir: str | Path, ref: Any, sha256: Any, *, label: str) -> dict[str, str]:
    """Return a run-owned ref after checking it resolves to a real, in-run file.

    The slice schemas intentionally store generic safe refs.  At this operated
    boundary we make the scheduler/worker provenance concrete: a reference to
    a missing or escaped run file is not admissible evidence.

    2026-08-07 de-governance: `sha256` (the worker's declared hash) is accepted for call-site
    compatibility but no longer re-verified against the file's freshly-computed hash (that was
    tamper-evidence, not the safety property) — existence + path fencing (via _path) is what still
    gates this. The returned sha256 is always freshly computed, not the caller's claim.
    """
    del sha256
    if not isinstance(ref, str) or not ref.strip():
        _fail("REFERENCE_HASH_REQUIRED", f"{label} requires a safe ref")
    portable = ref.replace("\\", "/")
    path = _path(run_dir, portable)
    if not path.is_file():
        _fail("MISSING_ARTIFACT", f"{label} is missing: {portable}")
    return {"ref": portable, "sha256": _file_sha256(path)}


def _authorization_receipt(
    run_dir: str | Path,
    slice_seed: Mapping[str, Any],
    *,
    worker_role: str,
    label: str,
) -> dict[str, str]:
    receipt = slice_seed.get("authorization_receipt")
    if not isinstance(receipt, Mapping) or receipt.get("worker_role") != worker_role:
        _fail("AUTHORIZATION_RECEIPT_REQUIRED", f"{label} lacks the declared {worker_role} authorization receipt")
    bound = _bound_run_reference(
        run_dir,
        receipt.get("ref"),
        receipt.get("sha256"),
        label=f"{label} authorization receipt",
    )
    return {**bound, "worker_role": worker_role}


def _slice_seed(bundle: Mapping[str, Any], key: str, *, label: str) -> dict[str, Any]:
    value = bundle.get(key)
    if not isinstance(value, Mapping):
        _fail("WORKER_BUNDLE_MISSING", f"{label} must include object {key!r}")
    return copy.deepcopy(dict(value))


def _stamped_payload(value: Mapping[str, Any], field: str) -> dict[str, Any]:
    stamped = copy.deepcopy(dict(value))
    stamped[field] = _hash(stamped, omit=field)
    return stamped


def _with_deterministic_asset_slice(
    contract_draft: Mapping[str, Any],
) -> dict[str, Any]:
    """Project the frozen asset plan into one least-privilege dependency slice.

    The architect and evidence steward jointly define the contract draft, but
    the asset worker is scheduled only after that draft is frozen. Deriving
    this slice in the DESIGN reducer closes that timing gap without asking a
    worker to predict the final contract hash or repairing an immutable
    snapshot after the fact.

    The projection is deliberately metadata-only. It reuses the declared
    ``asset_plan``, ``source_hashes`` and ``result_refs`` and never creates a
    result, executor receipt, render receipt, or permission fact. An empty
    plan still receives one declared global-contract seed so the asset engineer
    can truthfully return an empty manifest under the same scheduler contract.
    The final canonical contract hash binds that seed, the slice and the empty
    or populated plan together.
    """

    if not isinstance(contract_draft, Mapping):
        _fail("INVALID_CONTRACT", "contract draft must be an object")
    candidate = copy.deepcopy(dict(contract_draft))

    asset_plan = candidate.get("asset_plan")
    source_hashes = candidate.get("source_hashes")
    dependency_slices = candidate.get("dependency_slices")
    result_refs = candidate.get("result_refs")
    if not isinstance(asset_plan, Sequence) or isinstance(
        asset_plan, (str, bytes)
    ):
        _fail("ASSET_PLAN_INVALID", "asset_plan must be a list before contract freeze")
    if not isinstance(source_hashes, Sequence) or isinstance(
        source_hashes, (str, bytes)
    ):
        _fail(
            "ASSET_SOURCE_HASH_INVALID",
            "source_hashes must be a list before contract freeze",
        )
    if not isinstance(dependency_slices, Sequence) or isinstance(
        dependency_slices, (str, bytes)
    ):
        _fail(
            "INVALID_DEPENDENCY_SLICE",
            "dependency_slices must be a list before contract freeze",
        )
    if not isinstance(result_refs, Sequence) or isinstance(
        result_refs, (str, bytes)
    ):
        _fail("ASSET_RESULT_INVALID", "result_refs must be a list before contract freeze")

    source_by_ref: dict[str, dict[str, Any]] = {}
    for index, raw in enumerate(source_hashes):
        if not isinstance(raw, Mapping):
            _fail("ASSET_SOURCE_HASH_INVALID", f"source_hashes[{index}] must be an object")
        row = copy.deepcopy(dict(raw))
        ref = row.get("ref")
        sha256 = row.get("sha256")
        if (
            not isinstance(ref, str)
            or not ref
            or not isinstance(sha256, str)
            or not _SHA256.fullmatch(sha256)
        ):
            _fail(
                "ASSET_SOURCE_HASH_INVALID",
                f"source_hashes[{index}] has no valid ref/hash",
            )
        if ref in source_by_ref:
            _fail("ASSET_SOURCE_HASH_AMBIGUOUS", f"source hash is duplicated: {ref}")
        source_by_ref[ref] = row

    result_by_ref: dict[str, dict[str, Any]] = {}
    for index, raw in enumerate(result_refs):
        if not isinstance(raw, Mapping):
            _fail("ASSET_RESULT_INVALID", f"result_refs[{index}] must be an object")
        row = copy.deepcopy(dict(raw))
        ref = row.get("ref")
        if not isinstance(ref, str) or not ref:
            _fail("ASSET_RESULT_INVALID", f"result_refs[{index}] has no valid ref")
        if ref in result_by_ref:
            _fail("ASSET_RESULT_AMBIGUOUS", f"result ref is duplicated: {ref}")
        result_by_ref[ref] = row

    requested: dict[str, str] = {}
    referenced_source_rows: dict[str, dict[str, Any]] = {}
    for asset_index, raw_asset in enumerate(asset_plan):
        if not isinstance(raw_asset, Mapping):
            _fail("ASSET_PLAN_INVALID", f"asset_plan[{asset_index}] must be an object")
        asset_id = str(raw_asset.get("asset_id") or f"index-{asset_index}")
        for field, slice_kind in (
            ("source_refs", "ASSET"),
            ("result_refs", "RESULT"),
        ):
            refs = raw_asset.get(field)
            if not isinstance(refs, Sequence) or isinstance(refs, (str, bytes)):
                _fail("ASSET_PLAN_INVALID", f"asset {asset_id!r} {field} must be a list")
            for raw_ref in refs:
                if not isinstance(raw_ref, str) or not raw_ref:
                    _fail(
                        "ASSET_PLAN_INVALID",
                        f"asset {asset_id!r} has an invalid {field} ref",
                    )
                prior_kind = requested.get(raw_ref)
                if prior_kind is not None and prior_kind != slice_kind:
                    _fail(
                        "ASSET_DEPENDENCY_KIND_CONFLICT",
                        f"asset dependency {raw_ref!r} is declared as both source and result",
                    )
                source = source_by_ref.get(raw_ref)
                if source is None:
                    _fail(
                        "ASSET_SOURCE_HASH_MISSING",
                        f"asset dependency is not frozen: {raw_ref}",
                    )
                if slice_kind == "RESULT":
                    result = result_by_ref.get(raw_ref)
                    if result is None:
                        _fail(
                            "ASSET_RESULT_UNDECLARED",
                            f"asset result is not declared: {raw_ref}",
                        )
                    if source.get("kind") != "RESULT" or source.get(
                        "sha256"
                    ) != result.get("sha256"):
                        _fail(
                            "ASSET_RESULT_HASH_MISMATCH",
                            f"asset result hash is not closed: {raw_ref}",
                        )
                elif source.get("kind") not in {"ASSET", "EVIDENCE"}:
                    _fail(
                        "ASSET_SOURCE_KIND_INVALID",
                        f"asset source has invalid kind: {raw_ref}",
                    )
                requested[raw_ref] = slice_kind
                referenced_source_rows[raw_ref] = source

    global_seeds: dict[tuple[str, str], dict[str, str]] = {}
    for raw_slice in dependency_slices:
        if not isinstance(raw_slice, Mapping) or raw_slice.get(
            "worker_role"
        ) == "manuscript-figure-table-engineer":
            continue
        for raw_input in raw_slice.get("input_refs", ()):
            if not isinstance(raw_input, Mapping) or raw_input.get(
                "slice_kind"
            ) != "GLOBAL_CONTRACT":
                continue
            ref = raw_input.get("ref")
            sha256 = raw_input.get("sha256")
            source = source_by_ref.get(str(ref))
            if (
                not isinstance(ref, str)
                or not isinstance(sha256, str)
                or source is None
                or source.get("sha256") != sha256
            ):
                _fail(
                    "ASSET_GLOBAL_SEED_INVALID",
                    "an existing GLOBAL_CONTRACT input is not closed by source_hashes",
                )
            global_seeds[(ref, sha256)] = {
                "ref": ref,
                "sha256": sha256,
                "slice_kind": "GLOBAL_CONTRACT",
            }
    if len(global_seeds) > 1:
        _fail(
            "ASSET_GLOBAL_SEED_AMBIGUOUS",
            "dependency slices declare more than one global-contract seed",
        )
    if global_seeds:
        global_input = next(iter(global_seeds.values()))
    else:
        if not source_by_ref:
            _fail(
                "ASSET_GLOBAL_SEED_MISSING",
                "an empty or populated asset plan requires one declared source hash seed",
            )
        seed_ref = (
            "task_frame.artifact.json"
            if "task_frame.artifact.json" in source_by_ref
            else sorted(source_by_ref)[0]
        )
        global_input = {
            "ref": seed_ref,
            "sha256": str(source_by_ref[seed_ref]["sha256"]),
            "slice_kind": "GLOBAL_CONTRACT",
        }
    input_refs = [
        global_input,
        *[
            {
                "ref": ref,
                "sha256": str(referenced_source_rows[ref]["sha256"]),
                "slice_kind": requested[ref],
            }
            for ref in sorted(requested)
        ],
    ]
    asset_slice = {
        "slice_id": "slice-assets",
        "worker_role": "manuscript-figure-table-engineer",
        "input_refs": input_refs,
    }
    asset_slice["slice_sha256"] = _hash(asset_slice)

    preserved: list[dict[str, Any]] = []
    for index, raw in enumerate(dependency_slices):
        if not isinstance(raw, Mapping):
            _fail(
                "INVALID_DEPENDENCY_SLICE",
                f"dependency_slices[{index}] must be an object",
            )
        row = copy.deepcopy(dict(raw))
        if row.get("worker_role") == "manuscript-figure-table-engineer":
            continue
        if row.get("slice_id") == "slice-assets":
            _fail(
                "ASSET_SLICE_ID_COLLISION",
                "slice-assets is reserved for manuscript-figure-table-engineer",
            )
        preserved.append(row)
    candidate["dependency_slices"] = [*preserved, asset_slice]
    return candidate


def _write_schema_artifact(
    run_dir: str | Path,
    stage: str,
    filename: str,
    artifact_type: str,
    created_by: str,
    payload: Mapping[str, Any],
    ts: str,
) -> str:
    """Schema-check a deterministic payload before the normal envelope writer.

    ``write_artifact`` validates again at the persistence boundary.  Keeping a
    local check gives each operated mode a stable, actionable error before any
    file is written, while retaining the standard double validation.
    """

    body = copy.deepcopy(dict(payload))
    errors = validate_payload(artifact_type, body)
    if errors:
        _fail("SLICE_SCHEMA_INVALID", f"{artifact_type}: {errors[0]}")
    try:
        return write_artifact(run_dir, stage, filename, artifact_type, created_by, body, ts)
    except ValueError as exc:
        _fail("SLICE_SCHEMA_INVALID", f"{artifact_type}: {exc}")


def _same_frozen_value(label: str, supplied: Any, frozen: Any) -> None:
    if supplied != frozen:
        _fail("FROZEN_SLICE_MISMATCH", f"{label} does not match the frozen manuscript contract")


def required_sections_from_contract(contract: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Derive the adaptive required-section list solely from frozen outline rows."""

    outline = contract.get("outline") if isinstance(contract, Mapping) else None
    if not isinstance(outline, Sequence) or isinstance(outline, (str, bytes)):
        _fail("INVALID_CONTRACT_OUTLINE", "frozen contract outline must be a list")
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in outline:
        if not isinstance(raw, Mapping):
            _fail("INVALID_CONTRACT_OUTLINE", "outline entries must be objects")
        if raw.get("required") is not True:
            continue
        section_id = str(raw.get("section_id") or "")
        if not _SECTION_ID.fullmatch(section_id):
            _fail("INVALID_SECTION_ID", f"invalid required section id {section_id!r}")
        if section_id in seen:
            _fail("DUPLICATE_REQUIRED_SECTION", f"required section is duplicated: {section_id}")
        seen.add(section_id)
        result.append(copy.deepcopy(dict(raw)))
    if not result:
        _fail("MISSING_REQUIRED_SECTION", "frozen manuscript has no required sections")
    return result


def _slice_for_assignment(contract: Mapping[str, Any], section_id: str, role: str) -> dict[str, Any]:
    slices = contract.get("dependency_slices") if isinstance(contract, Mapping) else None
    if not isinstance(slices, Sequence) or isinstance(slices, (str, bytes)):
        _fail("UNAUTHORIZED_DEPENDENCY", "contract has no frozen dependency slices")
    matches = [dict(row) for row in slices if isinstance(row, Mapping) and row.get("worker_role") == role]
    if len(matches) == 1:
        return matches[0]
    keyed = [
        row for row in matches
        if str(row.get("slice_id") or "") in {section_id, f"slice-{section_id}", f"{section_id}-slice"}
        or section_id in str(row.get("slice_id") or "").replace("-", "_")
    ]
    if len(keyed) == 1:
        return keyed[0]
    _fail(
        "UNAUTHORIZED_DEPENDENCY",
        f"required section {section_id!r} does not have one unambiguous frozen slice for {role!r}",
    )


def assign_section_owners(contract: Mapping[str, Any]) -> list[dict[str, str]]:
    """Return the exact adaptive assignment map used by scheduler and integrator."""

    assignments = []
    for section in required_sections_from_contract(contract):
        section_id = str(section["section_id"])
        role = SPECIALIZED_SECTION_OWNERS.get(section_id, "manuscript-section-author")
        slice_row = _slice_for_assignment(contract, section_id, role)
        slice_id = str(slice_row.get("slice_id") or "")
        if not _SECTION_ID.fullmatch(slice_id):
            _fail("UNAUTHORIZED_DEPENDENCY", f"invalid dependency slice for {section_id!r}")
        assignments.append(
            {
                "section_id": section_id,
                "worker_role": role,
                "dependency_slice_id": slice_id,
                "draft_ref": _draft_section_ref(section_id),
            }
        )
    return assignments


def validate_section_bundle_closure(
    contract: Mapping[str, Any], bundle_payloads: Mapping[str, Mapping[str, Any]],
) -> list[str]:
    """Reject missing, duplicate, stale, wrong-role, and extra bundles before integration.

    This is intentionally a preflight only.  ``integrate_manuscript`` still
    re-validates each bundle's authorization receipt and dependency bytes.
    """

    expected = assign_section_owners(contract)
    expected_by_id = {row["section_id"]: row for row in expected}
    snapshot = str(contract.get("manuscript_snapshot_sha256") or "")
    if not _SHA256.fullmatch(snapshot):
        _fail("CONTRACT_HASH_MISMATCH", "frozen manuscript snapshot hash is invalid")
    observed: dict[str, str] = {}
    for ref, raw in bundle_payloads.items():
        if not isinstance(ref, str) or not ref.startswith("inbox/"):
            _fail("UNDECLARED_BUNDLE", "candidate bundle must use a run inbox reference")
        if not isinstance(raw, Mapping):
            _fail("SECTION_BUNDLE_INVALID", f"candidate {ref} is not an object")
        bundle = dict(raw)
        errors = validate_payload("manuscript_section_bundle", bundle)
        if errors:
            _fail("SECTION_BUNDLE_INVALID", f"{ref}: {errors[0]}")
        # 2026-08-07 de-governance: content_hash self-consistency (bundle's declared hash of its
        # own other fields) is no longer re-verified — tamper-evidence, not the safety property.
        # manuscript_snapshot_sha256 below stays: it binds the bundle to THIS frozen contract, not
        # a stale one, which is a referential/binding check, not file-content tamper-detection.
        if bundle.get("manuscript_snapshot_sha256") != snapshot:
            _fail("STALE_BUNDLE", f"candidate targets another snapshot: {ref}")
        section_id = str(bundle.get("section_id") or "")
        expected_row = expected_by_id.get(section_id)
        if expected_row is None:
            _fail("UNDECLARED_BUNDLE", f"candidate section is not required: {section_id!r}")
        if bundle.get("worker_role") != expected_row["worker_role"]:
            _fail("AUTHORIZATION_MISMATCH", f"candidate role is not owner of {section_id!r}")
        if section_id in observed:
            _fail("DUPLICATE_REQUIRED_SECTION", f"more than one candidate for {section_id!r}")
        observed[section_id] = ref
    missing = [row["section_id"] for row in expected if row["section_id"] not in observed]
    if missing:
        _fail("MISSING_REQUIRED_SECTION", f"no candidate bundle for {missing}")
    return [observed[row["section_id"]] for row in expected]


def integrate_section_bundles(
    *, run_root: str | Path, contract: Mapping[str, Any], bundle_payloads: Mapping[str, Mapping[str, Any]],
    bibliography_text: str | None, integrator_fn: Callable[..., Mapping[str, Any]] = integrate_manuscript,
    **kwargs: Any,
) -> Mapping[str, Any]:
    """Call the canonical integrator only after exact-one preflight closure."""

    ordered_refs = validate_section_bundle_closure(contract, bundle_payloads)
    return integrator_fn(
        run_root=run_root,
        manuscript_contract=contract,
        section_bundle_refs=ordered_refs,
        required_sections=assign_section_owners(contract),
        bibliography_text=bibliography_text,
        stage="ANALYZE",
        **kwargs,
    )


def _contract_now(ts: str) -> datetime:
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return datetime.now(timezone.utc)


def load_frozen_contract(run_dir: str | Path) -> dict[str, Any]:
    # 2026-08-07 de-governance: no longer re-verifies canonical_contract_hash(contract) against the
    # contract's own declared manuscript_snapshot_sha256 (self-consistency tamper-evidence, not the
    # safety property) — schema conformance below is what still gates this.
    contract = _read_json(run_dir, CONTRACT_REL)
    errors = validate_payload("manuscript_contract", contract)
    if errors:
        _fail("CONTRACT_SCHEMA_INVALID", errors[0])
    return contract


def repair_budget(run_dir: str | Path) -> dict[str, Any]:
    """Authoring permits at most two schema/format supplements per stage."""

    budget = dict(_shared.budget(run_dir))
    configured = budget.get("max_debug_retries_per_run", 2)
    if isinstance(configured, bool) or not isinstance(configured, int):
        configured = 2
    budget["max_debug_retries_per_run"] = max(0, min(2, configured))
    return budget


def _agent_spec(role: str) -> str:
    if not _SECTION_ID.fullmatch(role):
        _fail("INVALID_WORKER_ROLE", f"unsafe worker role {role!r}")
    path = AGENT_SPEC_DIR / f"{role}.md"
    try:
        spec = path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeDecodeError) as exc:
        _fail("MISSING_AGENT_SPEC", f"cannot read {role} contract: {type(exc).__name__}")
    if not spec:
        _fail("MISSING_AGENT_SPEC", f"empty role contract for {role}")
    return spec


def _prompt(role: str, stage: str, request: str, assignment: Mapping[str, str] | None = None) -> str:
    target = ""
    if assignment:
        target = (
            f"\nASSIGNMENT: write only section_id={assignment['section_id']!r}; "
            f"role={assignment['worker_role']!r}; dependency_slice={assignment['dependency_slice_id']!r}; "
            f"sole LaTeX write target={assignment['draft_ref']!r}."
        )
    role_contract = _agent_spec(role)
    role_contract_sha256 = hashlib.sha256(role_contract.encode("utf-8")).hexdigest()
    if role in SECTION_AUTHOR_ROLES:
        delivery = (
            "Write manuscript prose directly to the assigned UTF-8 .tex output. Do not write JSON, code, or "
            "a helper script; the deterministic reducer derives the stage receipt from the file on disk. "
            "Use only section-scoped evidence. Query the Markdown ontology and TSV ledgers on demand rather "
            "than loading or copying the full corpus. Literature "
            "synthesis separates synthesis_question, consensus, contradiction, boundary, and implication. "
            "Methods distinguish a protocol from an executed workflow_execution_manifest."
        )
    elif role == "manuscript-synthesis-editor":
        delivery = (
            "After section writers release their files, edit serially into draft/synthesis/sections/*.tex. "
            "Remove repetition, harmonize terminology, and close revision requirements without adding evidence "
            "or numbers. Write a concise Markdown handoff and review-closure table; do not write JSON or scripts."
        )
    elif role == "manuscript-architect":
        delivery = (
            "Freeze the machine contract, then write the human/AI working surface directly as "
            "draft/REVIEW-METHOD.md and draft/MANUSCRIPT-ONTOLOGY.md. The ontology owns canonical terms, "
            "claim boundaries, denominators, section ownership, and external-review requirements. Do not "
            "create helper scripts or duplicate prose across JSON and Markdown."
        )
    elif role == "manuscript-evidence-steward":
        delivery = (
            "Keep the machine evidence boundary compact, and write the author-facing retrieval surface as "
            "draft/SOURCES.tsv, draft/EVIDENCE.tsv, and draft/refs.bib. Preserve version_read, access scope, "
            "source locus, and value origin. Do not write a one-off script; use existing deterministic tools only."
        )
    else:
        delivery = "Return a compact control/evidence bundle; never duplicate manuscript prose in JSON."
    return (
        f"You are {role} in manuscript_authoring/{stage}. Use only the frozen local-first inputs, "
        "NORTH STAR: deliver a useful, evidence-grounded AI-research manuscript without overstating "
        "evidence, execution, or venue readiness. "
        "do not access a vault for writing, run a GPU, download content, invoke arbitrary commands, "
        "claim a PDF without the deterministic build receipt, submit, or promote. "
        f"{delivery} Director request: {request.strip() or '(pinned task frame)'}{target}\n\n"
        f"ROLE CONTRACT: agents/{role}.md sha256={role_contract_sha256}. The compact dispatch above is the "
        "runtime projection of that contract; the frozen north star and assignment remain authoritative."
    )


def _worker(role: str, stage: str, request: str, *, output: str, assignment: Mapping[str, str] | None = None,
            depends_on: Sequence[str] = (), allowed_inputs: Sequence[str] = (),
            forbidden_inputs: Sequence[str] = (), blind: bool = False,
            owned_outputs: Sequence[str] = ()) -> dict[str, Any]:
    return {
        "label": role,
        # These authoring and audit roles reason over a frozen research
        # contract; keep their logical workload tier explicit so the standard
        # provider-neutral runtime decorator can attach capabilities.
        "model": "opus",
        "output": output,
        "prompt": _prompt(role, stage, request, assignment),
        "assignment": dict(assignment or {}),
        "owned_outputs": list(owned_outputs),
        "depends_on": list(depends_on),
        "input_contract": {
            "allowed_inputs": list(allowed_inputs),
            "allowed_bundle_agents": list(depends_on),
            "forbidden_inputs": list(forbidden_inputs),
            "blind": blind,
        },
    }


def _author_panel(run_dir: str | Path, request: str) -> dict[str, Any]:
    contract = load_frozen_contract(run_dir)
    assignments = assign_section_owners(contract)
    revision_requirements = [
        row for row in contract.get("revision_requirements", ()) if isinstance(row, Mapping)
    ]
    affected_sections = {
        str(row.get("target_section") or "") for row in revision_requirements
        if row.get("target_section")
    }
    author_assignments = (
        [row for row in assignments if row["section_id"] in affected_sections]
        if revision_requirements else assignments
    )

    def allowed_for(role: str, section_id: str) -> list[str]:
        dependency_slice = _slice_for_assignment(contract, section_id, role)
        declared = [
            str(row.get("ref") or "")
            for row in dependency_slice.get("input_refs", ())
            if isinstance(row, Mapping)
            and row.get("slice_kind") != "GLOBAL_CONTRACT"
        ]
        return list(dict.fromkeys([
            CONTRACT_REL,
            "draft/REVIEW-METHOD.md",
            "draft/MANUSCRIPT-ONTOLOGY.md",
            "draft/SOURCES.tsv",
            "draft/EVIDENCE.tsv",
            "draft/refs.bib",
            "inbox/manuscript-inputs/current-source/**",
            *filter(None, declared),
        ]))

    authors: list[dict[str, Any]] = []
    for assignment in author_assignments:
        role = assignment["worker_role"]
        output = assignment["draft_ref"]
        authors.append(
            _worker(
                role,
                "ANALYZE",
                request,
                output=output,
                assignment=assignment,
                allowed_inputs=allowed_for(role, assignment["section_id"]),
            )
        )
    asset = _worker(
        "manuscript-figure-table-engineer", "ANALYZE", request,
        output=ASSET_ENGINEER_REL,
        allowed_inputs=allowed_for(
            "manuscript-figure-table-engineer", "assets"
        ),
    )
    author_labels = [worker["label"] for worker in authors] + [asset["label"]]
    author_outputs = [worker["output"] for worker in authors] + [asset["output"]]
    synthesis = _worker(
        "manuscript-synthesis-editor", "ANALYZE", request,
        output="draft/SYNTHESIS-HANDOFF.md",
        depends_on=list(dict.fromkeys(author_labels)),
        allowed_inputs=[CONTRACT_REL, *author_outputs, "draft/sections/**"],
        forbidden_inputs=["evidence/VERIFY/**", "director-review/**"],
        owned_outputs=[
            *[_draft_section_ref(row["section_id"], synthesis=True) for row in assignments],
            "draft/REVIEW-CLOSURE.md",
        ],
    )
    return {
        "label": "manuscript-authoring-sparse-panel",
        "workers": [*authors, asset, synthesis],
        "worker_order": [*author_labels, "manuscript-synthesis-editor"],
        "parallel_groups": [author_labels, ["manuscript-synthesis-editor"]],
        "group_barriers": False,
        "panel_note": (
            "Assignments are derived from frozen required outline entries. Candidate writers are sparse and "
            "adaptive; revision runs dispatch only affected section owners and preserve unchanged files. "
            "A single synthesis editor receives their explicit handoff, then the deterministic "
            "reducer freezes the canonical source tree. No prose or BibTeX is transported through JSON."
        ),
    }


def _prepare_revision_baseline(run_dir: str | Path, contract: Mapping[str, Any]) -> None:
    requirements = [row for row in contract.get("revision_requirements", ()) if isinstance(row, Mapping)]
    if not requirements:
        return
    root = Path(run_dir).absolute()
    current = root / "inbox" / "manuscript-inputs" / "current-source"
    if not current.is_dir():
        _fail("REVISION_SOURCE_REQUIRED", "revision authoring requires the staged current LaTeX source")
    destination = root / "draft" / "sections"
    destination.mkdir(parents=True, exist_ok=True)
    for assignment in assign_section_owners(contract):
        section_id = assignment["section_id"]
        candidates = [
            current / "sections" / f"{section_id}.tex",
            current / "sec" / f"{section_id}.tex",
            current / f"{section_id}.tex",
        ]
        source = next((path for path in candidates if path.is_file()), None)
        if source is None:
            _fail("REVISION_SECTION_SOURCE_MISSING", f"cannot locate current source for section {section_id}")
        target = destination / f"{section_id}.tex"
        if not target.is_file():
            target.write_bytes(source.read_bytes())


def llm_step(run_dir: str, stage: str, request: str, vault: str | None = None,
             model_policy: str = "default") -> dict[str, Any] | None:
    """Expose only legal sparse-DAG workers; deterministic code owns all writes/gates."""

    del vault, model_policy
    if stage == "DISCOVER":
        scout = _worker(
            "manuscript-venue-corpus-scout", stage, request, output=DISCOVERY_REL,
            allowed_inputs=["task_frame.artifact.json", "inbox/manuscript-inputs/**"],
        )
        return {"label": "manuscript-discovery", "workers": [scout], "worker_order": [scout["label"]],
                "parallel_groups": [[scout["label"]]], "group_barriers": False}
    if stage == "DESIGN":
        architect = _worker(
            "manuscript-architect", stage, request, output=ARCHITECT_REL,
            allowed_inputs=[
                DISCOVERY_REL,
                DISCOVERY_COVERAGE_ARTIFACT,
                "task_frame.artifact.json",
                "inbox/upstream-grounding.json",
                "inbox/manuscript-inputs/**",
            ],
            owned_outputs=["draft/REVIEW-METHOD.md", "draft/MANUSCRIPT-ONTOLOGY.md"],
        )
        steward = _worker(
            "manuscript-evidence-steward", stage, request, output=EVIDENCE_STEWARD_REL,
            depends_on=["manuscript-architect"],
            allowed_inputs=[
                ARCHITECT_REL,
                DISCOVERY_COVERAGE_ARTIFACT,
                "inbox/upstream-grounding.json",
                "inbox/upstream-citation-handoff/**",
                "inbox/manuscript-inputs/**",
                "task_frame.artifact.json",
            ],
            owned_outputs=["draft/SOURCES.tsv", "draft/EVIDENCE.tsv", "draft/refs.bib"],
        )
        return {"label": "manuscript-design", "workers": [architect, steward],
                "worker_order": [architect["label"], steward["label"]],
                "parallel_groups": [[architect["label"]], [steward["label"]]], "group_barriers": False}
    if stage == "ANALYZE":
        # The adaptive section panel is derived from the frozen contract.  A
        # just-created run has not reached DESIGN yet, so it legitimately has
        # no analysis workers to schedule rather than a fabricated outline.
        # Once the contract exists, invalid content still fails closed in
        # ``_author_panel``/``load_frozen_contract``.
        if not (Path(run_dir) / CONTRACT_REL).is_file():
            return None
        frozen_contract = load_frozen_contract(run_dir)
        _prepare_revision_baseline(run_dir, frozen_contract)
        return _author_panel(run_dir, request)
    if stage == "VERIFY":
        workers = [
            _worker(role, stage, request, output=_worker_rel(role), blind=True,
                    allowed_inputs=["task_frame.artifact.json", CONTRACT_REL, "source/**", "build/**", ANALYZE_INTEGRATION_ARTIFACT],
                    forbidden_inputs=["evidence/VERIFY/**", "inbox/manuscript-authoring/*author*.bundle.json"])
            for role in ("manuscript-factual-auditor", "manuscript-citation-auditor", "manuscript-style-latex-auditor")
        ]
        return {"label": "manuscript-authoring-independent-audits", "workers": workers,
                "worker_order": [row["label"] for row in workers],
                "parallel_groups": [[row["label"] for row in workers]], "group_barriers": False}
    # Submission packaging is a review-run responsibility. The authoring
    # REPORT stage renders only its frozen manuscript evidence; dispatching
    # the review-only packager here would give it the wrong run scope and could
    # not truthfully populate ``review_run_id``.
    if stage == "REPORT":
        return None
    return None


def _coverage_from_discovery(run_dir: str | Path, ts: str) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    discovery = _worker_payload(run_dir, "manuscript-venue-corpus-scout", key="manuscript_discovery")
    coverage = discovery.get("local_literature_coverage")
    if isinstance(coverage, Mapping):
        coverage = copy.deepcopy(dict(coverage))
    else:
        criteria = discovery.get("coverage_criteria")
        vault_root = discovery.get("vault_root")
        allowed = discovery.get("allowed_vault_roots")
        if not isinstance(criteria, Mapping) or not vault_root or not isinstance(allowed, Sequence):
            _fail("LOCAL_COVERAGE_REQUIRED", "discovery must provide a validated local coverage record or bounded recall inputs")
        snapshot = str(discovery.get("manuscript_snapshot_sha256") or "")
        coverage = assess_local_coverage(
            coverage_id=str(discovery.get("coverage_id") or "local-literature-coverage"),
            manuscript_snapshot_sha256=snapshot,
            assessed_at=ts,
            criteria=criteria,
            vault_root=str(vault_root),
            allowed_vault_roots=[str(item) for item in allowed],
            project=str(discovery.get("project") or "") or None,
        )
    errors = validate_payload("local_literature_coverage", coverage)
    if errors:
        _fail("LOCAL_COVERAGE_INVALID", errors[0])
    plans = discovery.get("named_deficit_query_plans") or []
    if not isinstance(plans, Sequence) or isinstance(plans, (str, bytes)):
        _fail("LOCAL_COVERAGE_INVALID", "named deficit plans must be a list")
    if not plans:
        return coverage, [], []
    routed = route_coverage_deficits(coverage, query_plans=list(plans))
    return dict(routed["coverage"]), list(routed["frozen_query_plans"]), list(routed["search_traces"])


def _discover_dets(run_dir: str | Path, ts: str) -> tuple[list[str], dict[str, Any]]:
    coverage, plans, traces = _coverage_from_discovery(run_dir, ts)
    path = write_artifact(run_dir, "DISCOVER", "local-literature-coverage.artifact.json",
                          "local_literature_coverage", "manuscript-venue-corpus-scout", coverage, ts)
    if plans:
        _write_json_once(run_dir, f"{WORKER_ROOT_REL}/named-deficit-query-plans.json", {"plans": plans, "traces": traces})
    states = {row["status"] for row in coverage["axes"].values()}
    return [path], {"coverage_states": sorted(states), "metadata_search_authorized": bool(plans)}


def _write_frozen_slice_artifacts(
    run_dir: str | Path,
    frozen: Mapping[str, Any],
    *,
    ts: str,
) -> list[str]:
    """Persist the two authoring slices only after a contract snapshot exists.

    Scout/steward bundles are planning inputs.  Their final schema artifacts
    cannot honestly bind a frozen manuscript hash until the architect's draft
    has passed ``freeze_manuscript_contract``.  This reducer keeps the worker
    provenance (including a byte-checked authorization receipt), reuses only
    values that exactly match the frozen contract, and emits the final slices
    through the normal artifact writer.
    """

    snapshot = frozen.get("manuscript_snapshot_sha256")
    run_id = frozen.get("run_id")
    if not isinstance(snapshot, str) or not _SHA256.fullmatch(snapshot) or not isinstance(run_id, str) or not _SECTION_ID.fullmatch(run_id):
        _fail("CONTRACT_HASH_MISMATCH", "frozen contract has no valid run id/snapshot hash")

    discovery = _worker_payload(
        run_dir,
        "manuscript-venue-corpus-scout",
        key="manuscript_discovery",
    )
    steward = _worker_payload(
        run_dir,
        "manuscript-evidence-steward",
        key="manuscript_evidence_admission",
    )
    assert discovery is not None and steward is not None

    coverage = _artifact_payload(run_dir, DISCOVERY_COVERAGE_ARTIFACT)
    if coverage is None:
        _fail("MISSING_ARTIFACT", "local literature coverage is required before freezing slices")
    coverage_errors = validate_payload("local_literature_coverage", coverage)
    if coverage_errors:
        _fail("LOCAL_COVERAGE_INVALID", coverage_errors[0])
    coverage_ref = _bound_run_reference(
        run_dir,
        DISCOVERY_COVERAGE_ARTIFACT,
        _file_sha256(_path(run_dir, DISCOVERY_COVERAGE_ARTIFACT)),
        label="local literature coverage artifact",
    )

    slice_paths: list[str] = []
    pdf_policy = (
        frozen.get("venue_profile", {})
        .get("hard_field_policy", {})
        .get("requires_pdf", {})
    )
    # A provisional authoring profile deliberately has no official venue
    # authority.  Freezing a scout-attributed official venue slice in that
    # state would manufacture provenance.  Keep the provisional profile in
    # the manuscript contract and defer the venue slice until /venue-pick
    # supplies an OFFICIAL_HARD rule snapshot.
    if pdf_policy.get("classification") == "OFFICIAL_HARD":
        venue_seed = _slice_seed(
            discovery,
            "manuscript_venue_profile_slice",
            label="venue scout bundle",
        )
        _same_frozen_value(
            "venue profile slice",
            venue_seed.get("venue_profile"),
            frozen.get("venue_profile"),
        )
        venue_receipt = _authorization_receipt(
            run_dir,
            venue_seed,
            worker_role="manuscript-venue-corpus-scout",
            label="venue profile slice",
        )
        venue_slice = _stamped_payload(
            {
                "contract_version": "1.0",
                "venue_profile_slice_id": f"venue-profile-slice-{run_id}",
                "worker_role": "manuscript-venue-corpus-scout",
                "authorization_receipt": venue_receipt,
                "manuscript_snapshot_sha256": snapshot,
                "local_literature_coverage_ref": coverage_ref["ref"],
                "local_literature_coverage_sha256": coverage_ref["sha256"],
                "venue_profile": copy.deepcopy(dict(frozen["venue_profile"])),
            },
            "venue_profile_slice_sha256",
        )
        slice_paths.append(
            _write_schema_artifact(
                run_dir,
                "DESIGN",
                "manuscript-venue-profile-slice.artifact.json",
                "manuscript_venue_profile_slice",
                "manuscript-venue-corpus-scout",
                venue_slice,
                ts,
            )
        )

    claim_map = steward.get("claim_evidence_map")
    if not isinstance(claim_map, Mapping):
        _fail("WORKER_BUNDLE_MISSING", "evidence steward must include claim_evidence_map")
    claim_map_path = _write_schema_artifact(
        run_dir,
        "DESIGN",
        "claim-evidence-map.artifact.json",
        "claim_evidence_map",
        "manuscript-evidence-steward",
        claim_map,
        ts,
    )
    claim_map_relative = Path(claim_map_path).relative_to(Path(run_dir).absolute()).as_posix()
    claim_map_ref = _bound_run_reference(
        run_dir,
        claim_map_relative,
        _file_sha256(_path(run_dir, claim_map_relative)),
        label="claim evidence map artifact",
    )

    evidence_seed = _slice_seed(
        steward,
        "manuscript_evidence_slice",
        label="evidence steward bundle",
    )
    for field in ("evidence_refs", "result_refs", "bibliography"):
        _same_frozen_value(f"evidence slice {field}", evidence_seed.get(field), frozen.get(field))
    evidence_receipt = _authorization_receipt(
        run_dir,
        evidence_seed,
        worker_role="manuscript-evidence-steward",
        label="evidence slice",
    )
    evidence_slice = _stamped_payload(
        {
            "contract_version": "1.0",
            "evidence_slice_id": f"evidence-slice-{run_id}",
            "worker_role": "manuscript-evidence-steward",
            "authorization_receipt": evidence_receipt,
            "manuscript_snapshot_sha256": snapshot,
            "claim_evidence_map_ref": claim_map_ref["ref"],
            "claim_evidence_map_sha256": claim_map_ref["sha256"],
            "evidence_refs": copy.deepcopy(frozen["evidence_refs"]),
            "result_refs": copy.deepcopy(frozen["result_refs"]),
            "bibliography": copy.deepcopy(dict(frozen["bibliography"])),
        },
        "evidence_slice_sha256",
    )
    evidence_path = _write_schema_artifact(
        run_dir,
        "DESIGN",
        "manuscript-evidence-slice.artifact.json",
        "manuscript_evidence_slice",
        "manuscript-evidence-steward",
        evidence_slice,
        ts,
    )
    return [*slice_paths, claim_map_path, evidence_path]


def _design_dets(run_dir: str | Path, ts: str) -> tuple[list[str], dict[str, Any]]:
    draft = _worker_payload(run_dir, "manuscript-architect", key="manuscript_contract_draft")
    steward = _worker_payload(run_dir, "manuscript-evidence-steward", key="manuscript_evidence_admission")
    if steward:
        draft = copy.deepcopy(draft)
        for field in ("evidence_refs", "result_refs", "source_hashes", "dependency_slices", "bibliography", "asset_plan"):
            if field in steward:
                draft[field] = copy.deepcopy(steward[field])
    draft = _with_deterministic_asset_slice(draft)
    frozen = freeze_manuscript_contract(
        draft,
        _path(run_dir, CONTRACT_REL, purpose="write"),
        run_root=run_dir,
        now=_contract_now(ts),
        max_official_age=_OFFICIAL_PROFILE_MAX_AGE,
        result_receipt_verifier=RESULT_RECEIPT_VERIFIER,
    )
    assignments = assign_section_owners(frozen)
    _write_json_once(run_dir, ASSIGNMENTS_REL, {"contract_sha256": frozen["manuscript_snapshot_sha256"], "assignments": assignments})
    path = write_artifact(run_dir, "DESIGN", "manuscript-contract.artifact.json", "manuscript_contract",
                          "manuscript-architect", frozen, ts)
    slice_paths = _write_frozen_slice_artifacts(run_dir, frozen, ts=ts)
    venue_slice_ref = (
        DESIGN_VENUE_PROFILE_SLICE_ARTIFACT
        if any(
            item.endswith("manuscript-venue-profile-slice.artifact.json")
            for item in slice_paths
        )
        else None
    )
    return [path, *slice_paths], {
        "frozen_contract": CONTRACT_REL,
        "required_section_count": len(assignments),
        "venue_profile_slice": venue_slice_ref,
        "evidence_slice": DESIGN_EVIDENCE_SLICE_ARTIFACT,
    }


def _bundle_payloads(run_dir: str | Path, contract: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    values: dict[str, dict[str, Any]] = {}
    for assignment in assign_section_owners(contract):
        role = assignment["worker_role"]
        section = assignment["section_id"] if role == "manuscript-section-author" else None
        rel = _worker_rel(role, section_id=section)
        raw = _read_json(run_dir, rel)
        direct = raw.get("payload") if isinstance(raw.get("payload"), Mapping) else raw
        if isinstance(direct, Mapping) and not validate_payload(
            "manuscript_section_bundle", direct
        ):
            values[rel] = copy.deepcopy(dict(direct))
        else:
            values[rel] = _payload(raw, "manuscript_section_bundle")
    return values


def _asset_manifest_payload(run_dir: str | Path) -> dict[str, Any] | None:
    raw = _read_json(run_dir, ASSET_ENGINEER_REL, required=False)
    if raw is None:
        return None
    direct = raw.get("payload") if isinstance(raw.get("payload"), Mapping) else raw
    if isinstance(direct, Mapping) and not validate_payload(
        "manuscript_asset_manifest", direct
    ):
        return copy.deepcopy(dict(direct))
    return _payload(raw, "manuscript_asset_manifest")


def _synthesis_handoff(run_dir: str | Path, contract: Mapping[str, Any]) -> tuple[list[dict[str, str]], str, str]:
    root = Path(run_dir).absolute()
    handoff = _path(root, "draft/SYNTHESIS-HANDOFF.md")
    closure = _path(root, "draft/REVIEW-CLOSURE.md")
    if not handoff.is_file() or not closure.is_file():
        _fail("SYNTHESIS_HANDOFF_REQUIRED", "serial synthesis Markdown and review-closure Markdown are required")
    handoff_text = handoff.read_text(encoding="utf-8")
    closure_text = closure.read_text(encoding="utf-8")
    if "synthesis" not in handoff_text.casefold() or "files" not in handoff_text.casefold():
        _fail("SYNTHESIS_HANDOFF_INVALID", "SYNTHESIS-HANDOFF.md must name the synthesis pass and released files")
    for requirement in contract.get("revision_requirements") or []:
        issue_id = str(requirement.get("issue_id") or "")
        line = next((row for row in closure_text.splitlines() if issue_id and issue_id in row), "")
        if not line or "closed" not in line.casefold():
            _fail("REVIEW_ISSUE_OPEN", f"external-review issue {issue_id!r} is not CLOSED in REVIEW-CLOSURE.md")
    rows = []
    for assignment in assign_section_owners(contract):
        ref = _draft_section_ref(assignment["section_id"], synthesis=True)
        path = _path(root, ref)
        if not path.is_file():
            _fail("MISSING_REQUIRED_SECTION", f"synthesis editor did not release {ref}")
        rows.append({
            "section_id": assignment["section_id"],
            "worker_role": assignment["worker_role"],
            "ref": ref,
        })
    bibliography_ref = "draft/synthesis/refs.bib" if _path(root, "draft/synthesis/refs.bib").is_file() else "draft/refs.bib"
    bibliography_path = _path(root, bibliography_ref)
    if not bibliography_path.is_file() or not bibliography_path.read_text(encoding="utf-8").strip():
        _fail("BIBLIOGRAPHY_REQUIRED", "the evidence/bibliography owner must maintain a real draft/refs.bib")
    return rows, bibliography_ref, closure_text


def _direct_audit_payloads(
    run_dir: str | Path, contract: Mapping[str, Any], direct_rows: Sequence[Mapping[str, str]],
) -> dict[str, dict[str, Any]]:
    root = Path(run_dir).absolute()
    claims = [row for row in contract.get("claim_ledger", ()) if isinstance(row, Mapping)]
    payloads: dict[str, dict[str, Any]] = {}
    citation_re = re.compile(r"\\cite(?:p|t)?\s*\{([^{}]+)\}")
    label_re = re.compile(r"\\label\s*\{([^{}]+)\}")
    ref_re = re.compile(r"\\(?:ref|eqref|autoref|cref|Cref)\s*\{([^{}]+)\}")
    for row in direct_rows:
        ref = str(row["ref"])
        text = _path(root, ref).read_text(encoding="utf-8")
        citation_keys = sorted({
            key.strip() for group in citation_re.findall(text)
            for key in group.split(",") if key.strip()
        })
        section_id = str(row["section_id"])
        payloads[ref] = {
            "section_id": section_id,
            "worker_role": str(row["worker_role"]),
            "claim_support_refs": [
                {
                    "claim_id": str(claim["claim_id"]),
                    "evidence_refs": list(claim.get("evidence_refs") or []),
                    "result_refs": list(claim.get("result_refs") or []),
                }
                for claim in claims if claim.get("claim_surface_owner") == section_id
            ],
            "citation_keys": citation_keys,
            "labels": sorted(set(label_re.findall(text))),
            "cross_references": sorted(set(ref_re.findall(text))),
            "asset_refs": [],
        }
    return payloads


def _normalize_asset_manifest_for_integration(
    run_dir: str | Path, manifest: Mapping[str, Any] | None
) -> dict[str, Any] | None:
    """Project evidence-run assets into canonical source-tree destinations."""

    if manifest is None:
        return None
    value = copy.deepcopy(dict(manifest))
    if value.get("schema_version") == "2.0.0":
        # A v2 conceptual original has no numeric/results fields. Preserve its
        # provenance record; the integrator records canonical copies separately.
        return value
    for asset in value.get("assets", ()):
        if not isinstance(asset, dict):
            continue
        asset_id = str(asset.get("asset_id") or "asset")
        output = asset.get("output") if isinstance(asset.get("output"), dict) else {}
        provenance = (
            asset.get("provenance") if isinstance(asset.get("provenance"), dict) else {}
        )
        if asset.get("asset_type") == "FIGURE":
            source_ref = str(output.get("path") or "")
            source_sha = str(output.get("sha256") or "")
            suffix = Path(source_ref).suffix.lower() or ".png"
            source_kind = "DIRECTOR_ASSET"
            output["path"] = f"assets/{asset_id}{suffix}"
        else:
            source_ref = str(output.get("path") or "")
            source_sha = str(output.get("sha256") or "")
            suffix = Path(source_ref).suffix.lower() or ".csv"
            output["path"] = f"tables/{asset_id}{suffix}"
        # Preserve the frozen evidence inputs from the asset plan.  The realized
        # PDF/TeX bytes are bound separately through ``asset_sources`` below;
        # replacing evidence inputs with the output file breaks plan closure.
        provenance["kind"] = "EXTERNAL"
        provenance["external_source"] = {
            "source_ref": source_ref,
            "original_sha256": source_sha,
            "acquired_at": provenance.get("created_at") or "2026-08-17T06:20:00Z",
        }
        asset["provenance"] = provenance
        asset["output"] = output
    return value


def _bound_asset_sources(
    run_dir: str | Path, sources: Mapping[str, Any] | None
) -> dict[str, Path]:
    bound: dict[str, Path] = {}
    for asset_id, value in (sources or {}).items():
        path = Path(str(value))
        bound[str(asset_id)] = path if path.is_absolute() else _path(run_dir, path.as_posix())
    return bound


def _manifest_asset_sources(manifest: Mapping[str, Any] | None) -> dict[str, str]:
    """Derive the run-local source map already declared by a legacy asset manifest."""
    sources: dict[str, str] = {}
    for row in (manifest or {}).get("assets", ()):
        if not isinstance(row, Mapping) or not row.get("asset_id"):
            continue
        if "semantic_type" in row:
            sources[str(row["asset_id"])] = asset_integration_view(row, fail=_fail)["source_output"]["path"]
            continue
        provenance = row.get("provenance") if isinstance(row.get("provenance"), Mapping) else {}
        external = (
            provenance.get("external_source")
            if isinstance(provenance.get("external_source"), Mapping)
            else {}
        )
        output = row.get("output") if isinstance(row.get("output"), Mapping) else {}
        source_ref = str(external.get("source_ref") or output.get("path") or "").strip()
        if source_ref:
            sources[str(row["asset_id"])] = source_ref
    return sources


def _run_authorization_verifier(
    run_dir: str | Path,
) -> Callable[[Mapping[str, Any]], Mapping[str, Any]]:
    """Independently re-open the scheduler and frozen contract for one bundle."""

    root = Path(run_dir).absolute()

    def verify(facts: Mapping[str, Any]) -> Mapping[str, Any]:
        if not isinstance(facts, Mapping):
            return {"verified": False}
        try:
            stage = str(facts.get("stage") or "")
            bundle_ref = str(facts.get("bundle_ref") or "")
            receipt = _read_json(root, f"inbox/panel-scheduler/{stage}.json")
            contract = _read_json(root, CONTRACT_REL)
            rows = [
                row
                for row in receipt.get("authorizations", ())
                if isinstance(row, Mapping)
                and bundle_ref in {row.get("output"), row.get("logical_output")}
            ]
            slices = {
                row.get("slice_id"): row
                for row in contract.get("dependency_slices", ())
                if isinstance(row, Mapping)
            }
            dependency = slices.get(facts.get("dependency_slice_id"))
            outline_ids = {
                row.get("section_id")
                for row in contract.get("outline", ())
                if isinstance(row, Mapping) and row.get("required") is True
            }
            valid = (
                receipt.get("contract_version") == "panel-dispatch/v1"
                and receipt.get("stage") == stage
                and len(rows) == 1
                and rows[0].get("agent") == facts.get("worker_role")
                and rows[0].get("authorization_kind") in {"initial", "supplement"}
                and _hash(rows[0]) == facts.get("authorization_sha256")
                and contract.get("run_id") == facts.get("run_id")
                and contract.get("manuscript_snapshot_sha256")
                == facts.get("manuscript_snapshot_sha256")
                and facts.get("section_id") in outline_ids
                and isinstance(dependency, Mapping)
                and dependency.get("worker_role") == facts.get("worker_role")
                and dependency.get("slice_sha256")
                == facts.get("dependency_slice_sha256")
            )
        except (OSError, ValueError, TypeError, ManuscriptAuthoringError):
            valid = False
        return {"verified": bool(valid), **copy.deepcopy(dict(facts))}

    return verify


def _derive_manuscript_audit_facts(
    *,
    contract: Mapping[str, Any],
    bundle_payloads: Mapping[str, Mapping[str, Any]],
    claim_map: Mapping[str, Any],
    integration: Mapping[str, Any],
    request: Mapping[str, Any],
    asset_manifest: Mapping[str, Any] | None = None,
    run_root: str | Path | None = None,
) -> dict[str, Any]:
    """Project frozen integration evidence into the audit module's fact vocabulary."""

    by_section = {
        str(bundle.get("section_id") or ""): bundle
        for bundle in bundle_payloads.values()
        if isinstance(bundle, Mapping)
    }
    sections = []
    for outline in contract.get("outline", ()):
        if not isinstance(outline, Mapping) or outline.get("required") is not True:
            continue
        section_id = str(outline.get("section_id") or "")
        bundle = by_section.get(section_id, {})
        sections.append(
            {
                "section_id": section_id,
                "claim_ids": [
                    str(row.get("claim_id"))
                    for row in bundle.get("claim_support_refs", ())
                    if isinstance(row, Mapping) and row.get("claim_id")
                ],
                "citation_keys": [
                    str(item) for item in bundle.get("citation_keys", ()) if item
                ],
            }
        )

    evidence = {
        str(row.get("ref")): row
        for row in contract.get("evidence_refs", ())
        if isinstance(row, Mapping) and row.get("ref")
    }
    bibliography_rows = [
        row for row in contract.get("bibliography", {}).get("entries", ())
        if isinstance(row, Mapping) and row.get("citation_key")
    ]
    bibliography = {
        str(row.get("source_ref")): row for row in bibliography_rows if row.get("source_ref")
    }
    bibliography_by_key = {str(row.get("citation_key")): row for row in bibliography_rows}
    publication_keys: dict[str, str] = {}
    doi_keys: dict[str, str] = {}
    citation_audit_rows: dict[str, Mapping[str, Any]] = {}
    citation_audit_independent = False
    if run_root is not None:
        root = Path(run_root)
        for source_ref in sorted({str(row.get("source_ref") or "") for row in bibliography_rows}):
            if not source_ref:
                continue
            try:
                registry = json.loads((root / source_ref).read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                continue
            for row in registry.get("entries", ()) if isinstance(registry, Mapping) else ():
                if not isinstance(row, Mapping):
                    continue
                identity = str(row.get("source_ref") or "")
                key = str(row.get("bibtex_key") or row.get("citation_key") or "")
                if identity and key:
                    publication_keys[identity] = key
        try:
            bibtex = (root / "draft" / "refs.bib").read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            bibtex = ""
        for entry in re.finditer(
            r"@\w+\{(?P<key>[^,\s]+),(?P<body>.*?)(?:\n\}|\Z)",
            bibtex,
            flags=re.DOTALL,
        ):
            doi = re.search(
                r"\bdoi\s*=\s*\{(?P<doi>[^}]+)\}",
                entry.group("body"),
                flags=re.IGNORECASE,
            )
            if doi:
                doi_keys[doi.group("doi").strip().casefold()] = entry.group("key").strip()
        audit_path = (
            root
            / "inbox"
            / "manuscript-inputs"
            / "evidence"
            / "DISCOVER.citation-coverage-auditor.bundle.json"
        )
        try:
            audit_document = json.loads(audit_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            audit_document = {}
        if isinstance(audit_document, Mapping) and isinstance(
            audit_document.get("payload"), Mapping
        ):
            audit_document = audit_document["payload"]
        citation_audit = (
            audit_document.get("citation_audit")
            if isinstance(audit_document, Mapping)
            else None
        )
        if isinstance(citation_audit, Mapping):
            citation_audit_independent = citation_audit.get("independent_of_linker") is True
            citation_audit_rows = {
                (
                    str(row.get("claim_id"))
                    if str(row.get("claim_id") or "").startswith("CLM-")
                    else f"CLM-{row.get('claim_id')}"
                ): row
                for row in citation_audit.get("claim_results", ())
                if isinstance(row, Mapping) and row.get("claim_id")
            }
    mappings = {
        (
            str(row.get("claim_id"))
            if str(row.get("claim_id") or "").startswith("CLM-")
            else f"CLM-{row.get('claim_id')}"
        ): row
        for row in claim_map.get("mappings", ())
        if isinstance(row, Mapping) and row.get("claim_id")
    }
    links: list[dict[str, Any]] = []
    cited_by_claim: dict[str, list[str]] = {}
    for bundle in bundle_payloads.values():
        if not isinstance(bundle, Mapping):
            continue
        keys = [str(key) for key in bundle.get("citation_keys", ()) if key]
        for support in bundle.get("claim_support_refs", ()):
            if isinstance(support, Mapping) and support.get("claim_id"):
                cited_by_claim.setdefault(str(support["claim_id"]), []).extend(keys)
    closure = request.get("citation_closure") if isinstance(request, Mapping) else {}
    closure_verified = bool(
        isinstance(closure, Mapping)
        and closure.get("unverified_identity_count") == 0
        and int(closure.get("verified_identity_count") or 0) > 0
    ) or bool(
        bibliography_rows
        and all(row.get("identity_status") == "VERIFIED" for row in bibliography_rows)
    )
    for claim in contract.get("claim_ledger", ()):
        if not isinstance(claim, Mapping):
            continue
        claim_id = str(claim.get("claim_id") or "")
        mapping = mappings.get(claim_id, {})
        audit_row = citation_audit_rows.get(claim_id, {})
        loci = [row for row in mapping.get("loci", ()) if isinstance(row, Mapping)]
        aggregate_supported = bool(
            loci
            and audit_row.get("verdict") == "entails"
            and audit_row.get("locator_verified") is True
            and any(row.get("supports_claim") is True for row in loci)
        )
        locus_keys = [
            (
                doi_keys.get(
                    re.sub(
                        r"^(?:doi:|https?://(?:dx\.)?doi\.org/)",
                        "",
                        str(row.get("source_ref") or "").strip(),
                        flags=re.IGNORECASE,
                    ).casefold(),
                    "",
                )
                or publication_keys.get(str(row.get("source_ref") or ""), "")
            )
            for row in loci
        ]
        cited_keys = list(dict.fromkeys(cited_by_claim.get(claim_id, ())))
        key = next((item for item in locus_keys if item and item in cited_keys), "")
        if not key and len(cited_keys) == 1:
            key = cited_keys[0]
        identity_verified = bool(
            key
            and (bibliography_by_key.get(key) or {}).get("identity_status") == "VERIFIED"
            and closure_verified
        )
        for evidence_ref in claim.get("evidence_refs", ()):
            ref = str(evidence_ref)
            matched = [row for row in loci if str(row.get("snapshot_ref") or "") == ref]
            first = matched[0] if matched else (loci[0] if loci else {})
            source = evidence.get(ref, {})
            bibliography_row = bibliography.get(ref, {})
            legacy_key = str(bibliography_row.get("citation_key") or "")
            link_key = key or legacy_key
            entailed = aggregate_supported
            links.append(
                {
                    "claim_id": claim_id,
                    "evidence_ref": ref,
                    "source_sha256": source.get("sha256"),
                    "citation_key": link_key,
                    "observed_citation_key": link_key,
                    "exact_span": str(first.get("exact_quote") or ""),
                    "entailment": "ENTAILED" if entailed else "PARTIAL",
                    "metadata_only": source.get("claim_support") == "NONCITABLE_CONTEXT",
                    "independent_audit": bool(
                        loci
                        and citation_audit_independent
                        and audit_row.get("locator_verified") is True
                    ),
                    "evidence_chain_verified": aggregate_supported,
                    "citation_identity_verified": identity_verified,
                }
            )

    glossary = contract.get("glossary", {})
    realized_assets = []
    asset_plans = {row["asset_id"]: row for row in contract.get("asset_plan", ())}
    for asset in (asset_manifest or {}).get("assets", ()):
        if not isinstance(asset, Mapping):
            continue
        view = asset_integration_view(asset, plan=asset_plans.get(asset.get("asset_id")), fail=_fail)
        output = view["output"]
        realized_assets.append(
            {
                "asset_id": asset.get("asset_id"),
                "label": asset.get("label"),
                "path": output.get("path"),
                "owner": "run",
                "mutation_requested": False,
                "source_refs": [
                    row.get("ref")
                    for row in asset.get("source_inputs", ())
                    if isinstance(row, Mapping)
                ],
                "result_refs": view["result_refs"],
                "provenance_valid": True,
            }
        )
    warnings = request.get("preserved_warnings", ())
    advisories = [
        {
            "code": str(row.get("warning_id") or "MANUSCRIPT_ADVISORY"),
            "effect": "CAVEAT",
            "message": str(row.get("detail") or row.get("status") or "preserved warning"),
        }
        for row in warnings
        if isinstance(row, Mapping)
    ]
    return {
        "manuscript_sha256": integration.get("source_tree_sha256"),
        "requires_pdf": contract.get("venue_profile", {}).get("requires_pdf"),
        "sections": sections,
        "claim_evidence": links,
        "numeric_claims": [],
        "result_facts": [],
        "bibliography_keys": [
            str(row.get("citation_key"))
            for row in contract.get("bibliography", {}).get("entries", ())
            if isinstance(row, Mapping) and row.get("citation_key")
        ],
        "term_usage": {
            str(row.get("term")): "CONSISTENT"
            for row in glossary.get("terms", ())
            if isinstance(row, Mapping) and row.get("term")
        },
        "notation_usage": {
            str(row.get("symbol")): "CONSISTENT"
            for row in glossary.get("notation", ())
            if isinstance(row, Mapping) and row.get("symbol")
        },
        "labels": sorted(
            {
                str(label)
                for bundle in bundle_payloads.values()
                for label in bundle.get("labels", ())
            }
            | {
                str(asset.get("label"))
                for asset in (asset_manifest or {}).get("assets", ())
                if isinstance(asset, Mapping) and asset.get("label")
            }
        ),
        "cross_references": [
            str(ref)
            for bundle in bundle_payloads.values()
            for ref in bundle.get("cross_references", ())
        ],
        "assets": realized_assets,
        "anonymity_violations": [],
        "official_rule_violations": [],
        "persisted_texts": {},
        "tex_sources": {},
        "advisories": advisories,
    }


def _analyze_dets(run_dir: str | Path, ts: str) -> tuple[list[str], dict[str, Any]]:
    contract = load_frozen_contract(run_dir)
    direct_rows, bibliography_ref, _closure_text = _synthesis_handoff(run_dir, contract)
    bundle_payloads = _direct_audit_payloads(run_dir, contract, direct_rows)
    raw_asset = _asset_manifest_payload(run_dir)
    # Optional compact SVG plan is produced by the existing figure engineer.
    # The host resolves the real journal question once; this adapter renders
    # and checks the planned figures before source integration, without another
    # model pass or a separate orchestration system.
    scientific_plan = Path(run_dir) / "draft" / "scientific-figures.json"
    if raw_asset is None and scientific_plan.is_file():
        from ...tools.journal_render import prepare_figure_plan
        from ...tools.scientific_figure import ScientificFigureError
        try:
            prepared = prepare_figure_plan(
                run_dir, "draft/scientific-figures.json",
                manuscript_sha256=str(contract["manuscript_snapshot_sha256"]),
                expected_journal=str(contract["venue_profile"]["venue_id"]),
            )
            raw_asset = prepared["manifest"]
        except ScientificFigureError as exc:
            raise GateBlock(str(exc)) from exc
    asset = _normalize_asset_manifest_for_integration(run_dir, raw_asset)
    try:
        candidate = integrate_manuscript(
            run_root=run_dir,
            manuscript_contract=contract,
            section_bundle_refs=[],
            required_sections=assign_section_owners(contract),
            bibliography_text=None,
            bibliography_ref=bibliography_ref,
            bibliography_sha256=_file_sha256(_path(run_dir, bibliography_ref)),
            venue_profile_slice=_artifact_payload(run_dir, DESIGN_VENUE_PROFILE_SLICE_ARTIFACT, required=False),
            direct_sections=direct_rows,
            stage="ANALYZE",
            asset_manifest=asset,
            asset_sources=_bound_asset_sources(
                run_dir,
                (raw_asset or {}).get("asset_sources")
                or _manifest_asset_sources(raw_asset),
            ),
            director_asset_roots=(),
            authorization_verifier=(
                AUTHORIZATION_VERIFIER or _run_authorization_verifier(run_dir)
            ),
            result_receipt_verifier=RESULT_RECEIPT_VERIFIER,
            generated_command_verifier=GENERATED_COMMAND_VERIFIER,
        )
        source = materialize_source_tree(candidate, run_root=run_dir)
    except ManuscriptIntegrationError as exc:
        raise GateBlock(str(exc)) from exc
    integration = dict(candidate["integration"])
    asset_manifest = dict(candidate["asset_manifest"])
    paths = [
        write_artifact(run_dir, "ANALYZE", "manuscript-integration.artifact.json", "manuscript_integration",
                       "deterministic-source-freezer", integration, ts),
        write_artifact(run_dir, "ANALYZE", "manuscript-asset-manifest.artifact.json", "manuscript_asset_manifest",
                       "manuscript-figure-table-engineer", asset_manifest, ts),
    ]
    build = build_latex_project(
        run_dir, source, run_id=str(contract["run_id"]),
        manuscript_snapshot_sha256=str(contract["manuscript_snapshot_sha256"]),
        requires_pdf=bool(contract["venue_profile"]["requires_pdf"]),
        prefer_direct=(
            os.name == "nt" and any(ord(char) > 127 for char in str(Path(run_dir).absolute()))
        ),
    )
    paths.append(write_artifact(run_dir, "ANALYZE", "manuscript-build-receipt.artifact.json", "manuscript_build_receipt",
                                "safe-latex-build", build, ts))
    canonical_terms = {
        str(row.get("term")): tuple(str(alias) for alias in row.get("aliases") or [])
        for row in contract.get("glossary", {}).get("terms", ())
        if isinstance(row, Mapping) and row.get("term")
    }
    lint_report = lint_tex_tree(Path(source), canonical_terms=canonical_terms)
    if lint_report.errors:
        raise GateBlock("LaTeX-first source lint failed: " + lint_report.errors[0]["detail"])
    fact_summary: Mapping[str, Any] = {
        "preserved_warnings": [],
        "advisories": [
            {
                "code": str(row.get("check") or "LATEX_SOURCE_REVIEW"),
                "effect": "SUPPLEMENT" if row in lint_report.warnings else "CAVEAT",
            }
            for row in [*lint_report.warnings, *lint_report.reports]
        ],
    }
    claim_map = _artifact_payload(run_dir, DESIGN_CLAIM_EVIDENCE_MAP_ARTIFACT)
    if not isinstance(claim_map, Mapping):
        _fail("MANUSCRIPT_FACTS_REQUIRED", "design claim-evidence map is required for audit projection")
    facts = _derive_manuscript_audit_facts(
        contract=contract,
        bundle_payloads=bundle_payloads,
        claim_map=claim_map,
        integration=integration,
        request=fact_summary,
        asset_manifest=asset_manifest,
        run_root=run_dir,
    )
    tex_sources = {
        path.relative_to(Path(source)).as_posix(): path.read_text(encoding="utf-8")
        for path in sorted(Path(source).rglob("*.tex"))
    }
    facts["tex_sources"] = tex_sources
    facts["persisted_texts"] = {"latex_source": "\n".join(tex_sources.values())}
    inconsistent_terms = {
        str(row.get("canonical"))
        for row in lint_report.reports
        if row.get("check") == "terminology_alias" and row.get("canonical")
    }
    facts["term_usage"] = {
        term: "INCONSISTENT" if term in inconsistent_terms else "CONSISTENT"
        for term in canonical_terms
    }
    quality = audit_manuscript(
        contract, dict(facts), run_root=run_dir, current_source_sha256=integration["source_tree_sha256"],
        build_receipt=build, build_receipt_verifier=BUILD_RECEIPT_VERIFIER,
    )
    paths.append(write_artifact(run_dir, "ANALYZE", "manuscript-quality-report.artifact.json", "manuscript_quality_report",
                                "manuscript-truth-auditor", quality, ts))
    return paths, {"source": str(source), "build_state": build["build_state"], "daily_state": quality["daily_state"]}


def _verify_dets(run_dir: str | Path, ts: str) -> tuple[list[str], dict[str, Any]]:
    rows = []
    for role in ("manuscript-factual-auditor", "manuscript-citation-auditor", "manuscript-style-latex-auditor"):
        row = _worker_payload(run_dir, role, key="manuscript_authoring_audit")
        if row.get("review_mode") == "manuscript_review" or row.get("independent_review") is True:
            _fail("AUTHOR_REVIEW_BOUNDARY", "authoring self-audit cannot claim independent manuscript_review status")
        rows.append({"role": role, "audit": row})
    _write_json_once(run_dir, VERIFY_SUMMARY_REL, {"contract_version": "manuscript-authoring-audits/v1", "audits": rows})
    note = {"summary": "Authoring-scoped factual, citation, and style audits are recorded; independent review remains a separate run.",
            "references": [VERIFY_SUMMARY_REL], "produced_artifacts": [], "open_questions": []}
    path = write_artifact(run_dir, "VERIFY", "authoring-audit-note.artifact.json", "report_note",
                          "manuscript-authoring-audit-reducer", note, ts)
    return [path], {"audit_roles": [row["role"] for row in rows], "independent_review": False}


def _section_bundle_inventory_note(contract: Mapping[str, Any]) -> dict[str, Any]:
    references = [
        _draft_section_ref(assignment["section_id"], synthesis=True)
        for assignment in assign_section_owners(contract)
    ]
    return {
        "summary": "Frozen direct-LaTeX section inventory for the integrated manuscript source.",
        "references": references,
        "produced_artifacts": list(references),
        "open_questions": [],
    }


def _report_dets(run_dir: str | Path, ts: str) -> tuple[list[str], dict[str, Any]]:
    # Lazy import allows the recipe file to remain importable while the renderer
    # is developed in its independently owned plan.
    from ...tools.manuscript_renderer import write_manuscript_report_set

    contract = load_frozen_contract(run_dir)
    coverage = _artifact_payload(run_dir, DISCOVERY_COVERAGE_ARTIFACT)
    venue_slice = _artifact_payload(run_dir, DESIGN_VENUE_PROFILE_SLICE_ARTIFACT)
    coverage_artifact = _path(run_dir, DISCOVERY_COVERAGE_ARTIFACT)
    if (
        not isinstance(coverage, Mapping)
        or not isinstance(venue_slice, Mapping)
        or venue_slice.get("manuscript_snapshot_sha256")
        != contract.get("manuscript_snapshot_sha256")
        or venue_slice.get("local_literature_coverage_ref")
        != DISCOVERY_COVERAGE_ARTIFACT
        or venue_slice.get("local_literature_coverage_sha256")
        != _file_sha256(coverage_artifact)
    ):
        _fail(
            "COVERAGE_BINDING_MISMATCH",
            "the frozen venue slice does not bind the pre-contract coverage artifact",
        )
    # Coverage is assessed before the manuscript contract exists.  The frozen
    # venue slice is the authenticated bridge from those pre-contract bytes to
    # the final manuscript snapshot; project that binding for the renderer
    # without mutating the committed DISCOVER artifact.
    coverage = copy.deepcopy(dict(coverage))
    coverage["manuscript_snapshot_sha256"] = contract["manuscript_snapshot_sha256"]
    integration = _artifact_payload(run_dir, ANALYZE_INTEGRATION_ARTIFACT)
    build = _artifact_payload(run_dir, ANALYZE_BUILD_ARTIFACT)
    quality = _artifact_payload(run_dir, ANALYZE_QUALITY_ARTIFACT)
    reports = write_manuscript_report_set(
        run_dir,
        manuscript_contract=contract,
        literature_coverage=coverage,
        integration=integration,
        quality_report=quality,
        build_receipt=build,
    )
    references = [Path(value).relative_to(Path(run_dir)).as_posix() for value in reports.values()]
    daily_state = str(quality.get("daily_state") or "USABLE_WITH_CAVEATS")
    delivery_status = {
        "USABLE": "USABLE",
        "USABLE_WITH_CAVEATS": "USABLE_WITH_CAVEATS",
        "NEEDS_SUPPLEMENT": "USABLE_WITH_CAVEATS",
        "BLOCK": "BLOCK",
    }.get(daily_state, "USABLE_WITH_CAVEATS")
    open_questions = [
        f"{row.get('code') or row.get('blocker_id') or 'BLOCKER'}: {row.get('rationale') or 'submission repair required'}"
        for row in (quality.get("submission_blockers") or [])
        if isinstance(row, Mapping)
    ]
    note = {
        "summary": "Manuscript authoring report rendered from frozen contract, local coverage, canonical source, build, and deterministic quality evidence.",
        "references": references,
        "produced_artifacts": [ANALYZE_INTEGRATION_ARTIFACT, ANALYZE_BUILD_ARTIFACT, ANALYZE_QUALITY_ARTIFACT],
        "open_questions": open_questions,
        "delivery_status": delivery_status,
    }
    paths = [
        write_artifact(run_dir, "REPORT", "report-note.artifact.json",
                       "report_note", "manuscript-authoring-reporter", note, ts),
    ]
    return paths, {"director_overview": references[0] if references else None, "daily_state": quality.get("daily_state")}


def run_dets(run_dir: str, stage: str, ts: str) -> tuple[list[str], dict[str, Any]]:
    """Execute the deterministic half of one operated authoring stage."""

    if stage == "DISCOVER":
        return _discover_dets(run_dir, ts)
    if stage == "DESIGN":
        return _design_dets(run_dir, ts)
    if stage == "ANALYZE":
        return _analyze_dets(run_dir, ts)
    if stage == "VERIFY":
        return _verify_dets(run_dir, ts)
    if stage == "REPORT":
        return _report_dets(run_dir, ts)
    raise ValueError(f"manuscript_authoring has no stage {stage!r}")


def run_dets_with_repair(run_dir: str, stage: str, ts: str):
    return bounded_repair.attempt_with_repair(
        run_dir, stage, repair_budget(run_dir), ts, lambda: run_dets(run_dir, stage, ts)
    )


__all__ = [
    "ANALYZE_BUILD_ARTIFACT", "ANALYZE_INTEGRATION_ARTIFACT", "ANALYZE_QUALITY_ARTIFACT",
    "CONTRACT_REL", "DEFAULT_VAULT", "DESIGN_CLAIM_EVIDENCE_MAP_ARTIFACT",
    "DESIGN_EVIDENCE_SLICE_ARTIFACT", "DESIGN_VENUE_PROFILE_SLICE_ARTIFACT",
    "ManuscriptAuthoringError", "SPECIALIZED_SECTION_OWNERS",
    "STAGES", "assign_section_owners", "integrate_section_bundles", "llm_step", "load_frozen_contract",
    "repair_budget", "required_sections_from_contract", "run_dets", "run_dets_with_repair",
    "validate_section_bundle_closure",
]
