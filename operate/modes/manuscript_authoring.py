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
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from .. import bounded_repair
from ..artifacts import GateBlock, write_artifact
from . import _shared
from ...tools.latex_build import build_latex_project
from ...tools.manuscript_audit import audit_manuscript
from ...tools.manuscript_contract import canonical_contract_hash, freeze_manuscript_contract
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

WORKER_ROOT_REL = "inbox/manuscript-authoring"
CONTRACT_REL = f"{WORKER_ROOT_REL}/manuscript-contract.json"
ASSIGNMENTS_REL = f"{WORKER_ROOT_REL}/section-assignments.json"
DISCOVERY_REL = f"{WORKER_ROOT_REL}/manuscript-venue-corpus-scout.bundle.json"
ARCHITECT_REL = f"{WORKER_ROOT_REL}/manuscript-architect.bundle.json"
EVIDENCE_STEWARD_REL = f"{WORKER_ROOT_REL}/manuscript-evidence-steward.bundle.json"
INTEGRATOR_REQUEST_REL = f"{WORKER_ROOT_REL}/manuscript-integrator.bundle.json"
ASSET_ENGINEER_REL = f"{WORKER_ROOT_REL}/manuscript-figure-table-engineer.bundle.json"
VERIFY_SUMMARY_REL = f"{WORKER_ROOT_REL}/authoring-audit-summary.json"

DISCOVERY_COVERAGE_ARTIFACT = "evidence/DISCOVER/local-literature-coverage.artifact.json"
DESIGN_CONTRACT_ARTIFACT = "evidence/DESIGN/manuscript-contract.artifact.json"
ANALYZE_INTEGRATION_ARTIFACT = "evidence/ANALYZE/manuscript-integration.artifact.json"
ANALYZE_ASSET_ARTIFACT = "evidence/ANALYZE/manuscript-asset-manifest.artifact.json"
ANALYZE_BUILD_ARTIFACT = "evidence/ANALYZE/manuscript-build-receipt.artifact.json"
ANALYZE_QUALITY_ARTIFACT = "evidence/ANALYZE/manuscript-quality-report.artifact.json"

_SECTION_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_OFFICIAL_PROFILE_MAX_AGE = timedelta(days=366)

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
            owned_output_roots=(root / "inbox", root / "evidence", root / "source", root / "build", root / "director-review"),
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


def _worker_payload(run_dir: str | Path, role: str, *, key: str, section_id: str | None = None,
                    required: bool = True) -> dict[str, Any] | None:
    raw = _read_json(run_dir, _worker_rel(role, section_id=section_id), required=required)
    return None if raw is None else _payload(raw, key)


def _artifact_payload(run_dir: str | Path, relative: str, *, required: bool = True) -> dict[str, Any] | None:
    raw = _read_json(run_dir, relative, required=required)
    return None if raw is None else _payload(raw)


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
        if bundle.get("content_hash") != _hash(bundle, omit="content_hash"):
            _fail("BUNDLE_CONTENT_HASH_MISMATCH", f"candidate content hash is invalid: {ref}")
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
    bibliography_text: str, integrator_fn: Callable[..., Mapping[str, Any]] = integrate_manuscript,
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
    contract = _read_json(run_dir, CONTRACT_REL)
    errors = validate_payload("manuscript_contract", contract)
    if errors:
        _fail("CONTRACT_SCHEMA_INVALID", errors[0])
    if canonical_contract_hash(contract) != contract.get("manuscript_snapshot_sha256"):
        _fail("CONTRACT_HASH_MISMATCH", "frozen manuscript contract hash does not verify")
    return contract


def repair_budget(run_dir: str | Path) -> dict[str, Any]:
    """Authoring permits at most two schema/format supplements per stage."""

    budget = dict(_shared.budget(run_dir))
    configured = budget.get("max_debug_retries_per_run", 2)
    if isinstance(configured, bool) or not isinstance(configured, int):
        configured = 2
    budget["max_debug_retries_per_run"] = max(0, min(2, configured))
    return budget


def _prompt(role: str, stage: str, request: str, assignment: Mapping[str, str] | None = None) -> str:
    target = ""
    if assignment:
        target = (
            f"\nASSIGNMENT: write only section_id={assignment['section_id']!r}; "
            f"role={assignment['worker_role']!r}; dependency_slice={assignment['dependency_slice_id']!r}."
        )
    return (
        f"You are {role} in manuscript_authoring/{stage}. Use only the frozen local-first inputs, "
        "NORTH STAR: deliver a useful, evidence-grounded AI-research manuscript without overstating "
        "evidence, execution, or venue readiness. "
        "do not access a vault for writing, run a GPU, download content, invoke arbitrary commands, "
        "claim a PDF without the deterministic build receipt, submit, or promote. Return the declared "
        f"JSON bundle only. Director request: {request.strip() or '(pinned task frame)'}{target}"
    )


def _worker(role: str, stage: str, request: str, *, output: str, assignment: Mapping[str, str] | None = None,
            depends_on: Sequence[str] = (), allowed_inputs: Sequence[str] = (),
            forbidden_inputs: Sequence[str] = (), blind: bool = False) -> dict[str, Any]:
    return {
        "label": role,
        # These authoring and audit roles reason over a frozen research
        # contract; keep their logical workload tier explicit so the standard
        # provider-neutral runtime decorator can attach capabilities.
        "model": "opus",
        "output": output,
        "prompt": _prompt(role, stage, request, assignment),
        "assignment": dict(assignment or {}),
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
    authors: list[dict[str, Any]] = []
    for assignment in assignments:
        role = assignment["worker_role"]
        output = _worker_rel(role, section_id=assignment["section_id"] if role == "manuscript-section-author" else None)
        authors.append(
            _worker(
                role,
                "ANALYZE",
                request,
                output=output,
                assignment=assignment,
                allowed_inputs=[CONTRACT_REL, DISCOVERY_COVERAGE_ARTIFACT, "inbox/manuscript-authoring/admitted-evidence.json"],
            )
        )
    asset = _worker(
        "manuscript-figure-table-engineer", "ANALYZE", request,
        output=ASSET_ENGINEER_REL,
        allowed_inputs=[CONTRACT_REL, "inbox/manuscript-authoring/admitted-evidence.json"],
    )
    author_labels = [worker["label"] for worker in authors] + [asset["label"]]
    author_outputs = [worker["output"] for worker in authors] + [asset["output"]]
    integrator = _worker(
        "manuscript-integrator", "ANALYZE", request,
        output=INTEGRATOR_REQUEST_REL,
        depends_on=list(dict.fromkeys(author_labels)),
        allowed_inputs=[CONTRACT_REL, *author_outputs],
        forbidden_inputs=["evidence/VERIFY/**", "director-review/**"],
    )
    return {
        "label": "manuscript-authoring-sparse-panel",
        "workers": [*authors, asset, integrator],
        "worker_order": [*author_labels, "manuscript-integrator"],
        "parallel_groups": [author_labels, ["manuscript-integrator"]],
        "group_barriers": False,
        "panel_note": (
            "Assignments are derived from frozen required outline entries. Candidate writers are sparse and "
            "adaptive; only the deterministic reducer may integrate their exact-one bundle set."
        ),
    }


def llm_step(run_dir: str, stage: str, request: str, vault: str | None = None,
             model_policy: str = "max_quality") -> dict[str, Any] | None:
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
            allowed_inputs=[DISCOVERY_REL, DISCOVERY_COVERAGE_ARTIFACT, "task_frame.artifact.json"],
        )
        steward = _worker(
            "manuscript-evidence-steward", stage, request, output=EVIDENCE_STEWARD_REL,
            depends_on=["manuscript-architect"],
            allowed_inputs=[ARCHITECT_REL, DISCOVERY_COVERAGE_ARTIFACT, "task_frame.artifact.json"],
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
    if stage == "REPORT":
        packager = _worker(
            "manuscript-submission-packager", stage, request,
            output=_worker_rel("manuscript-submission-packager"),
            allowed_inputs=[CONTRACT_REL, DISCOVERY_COVERAGE_ARTIFACT, ANALYZE_INTEGRATION_ARTIFACT,
                            ANALYZE_BUILD_ARTIFACT, ANALYZE_QUALITY_ARTIFACT, VERIFY_SUMMARY_REL],
        )
        return {"label": "manuscript-authoring-report", "workers": [packager],
                "worker_order": [packager["label"]], "parallel_groups": [[packager["label"]]],
                "group_barriers": False}
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


def _design_dets(run_dir: str | Path, ts: str) -> tuple[list[str], dict[str, Any]]:
    draft = _worker_payload(run_dir, "manuscript-architect", key="manuscript_contract_draft")
    steward = _worker_payload(run_dir, "manuscript-evidence-steward", key="manuscript_evidence_admission")
    if steward:
        draft = copy.deepcopy(draft)
        for field in ("evidence_refs", "result_refs", "source_hashes", "dependency_slices", "bibliography", "asset_plan"):
            if field in steward:
                draft[field] = copy.deepcopy(steward[field])
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
    return [path], {"frozen_contract": CONTRACT_REL, "required_section_count": len(assignments)}


def _bundle_payloads(run_dir: str | Path, contract: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    values: dict[str, dict[str, Any]] = {}
    for assignment in assign_section_owners(contract):
        role = assignment["worker_role"]
        section = assignment["section_id"] if role == "manuscript-section-author" else None
        rel = _worker_rel(role, section_id=section)
        raw = _read_json(run_dir, rel)
        values[rel] = _payload(raw, "manuscript_section_bundle")
    return values


def _analyze_dets(run_dir: str | Path, ts: str) -> tuple[list[str], dict[str, Any]]:
    contract = load_frozen_contract(run_dir)
    bundle_payloads = _bundle_payloads(run_dir, contract)
    request = _worker_payload(run_dir, "manuscript-integrator", key="manuscript_integration_request")
    asset = _worker_payload(run_dir, "manuscript-figure-table-engineer", key="manuscript_asset_manifest", required=False)
    bibliography = request.get("bibliography_text")
    if not isinstance(bibliography, str) or not bibliography.strip():
        _fail("BIBLIOGRAPHY_REQUIRED", "integrator request must provide frozen bibliography_text")
    try:
        candidate = integrate_section_bundles(
            run_root=run_dir,
            contract=contract,
            bundle_payloads=bundle_payloads,
            bibliography_text=bibliography,
            asset_manifest=asset,
            asset_sources=request.get("asset_sources") or {},
            director_asset_roots=request.get("director_asset_roots") or (),
            authorization_verifier=AUTHORIZATION_VERIFIER,
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
                       "manuscript-integrator", integration, ts),
        write_artifact(run_dir, "ANALYZE", "manuscript-asset-manifest.artifact.json", "manuscript_asset_manifest",
                       "manuscript-figure-table-engineer", asset_manifest, ts),
    ]
    build = build_latex_project(
        run_dir, source, run_id=str(contract["run_id"]),
        manuscript_snapshot_sha256=str(contract["manuscript_snapshot_sha256"]),
        requires_pdf=bool(contract["venue_profile"]["requires_pdf"]),
    )
    paths.append(write_artifact(run_dir, "ANALYZE", "manuscript-build-receipt.artifact.json", "manuscript_build_receipt",
                                "safe-latex-build", build, ts))
    facts = request.get("manuscript_facts")
    if not isinstance(facts, Mapping):
        _fail("MANUSCRIPT_FACTS_REQUIRED", "integrator request must provide a deterministic manuscript fact inventory")
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


def _report_dets(run_dir: str | Path, ts: str) -> tuple[list[str], dict[str, Any]]:
    # Lazy import allows the recipe file to remain importable while the renderer
    # is developed in its independently owned plan.
    from ...tools.manuscript_renderer import write_manuscript_report_set

    contract = load_frozen_contract(run_dir)
    coverage = _artifact_payload(run_dir, DISCOVERY_COVERAGE_ARTIFACT)
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
    path = write_artifact(run_dir, "REPORT", "manuscript-authoring-report-note.artifact.json", "report_note",
                          "manuscript-authoring-reporter", note, ts)
    return [path], {"director_overview": references[0] if references else None, "daily_state": quality.get("daily_state")}


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
    "CONTRACT_REL", "DEFAULT_VAULT", "ManuscriptAuthoringError", "SPECIALIZED_SECTION_OWNERS",
    "STAGES", "assign_section_owners", "integrate_section_bundles", "llm_step", "load_frozen_contract",
    "repair_budget", "required_sections_from_contract", "run_dets", "run_dets_with_repair",
    "validate_section_bundle_closure",
]
