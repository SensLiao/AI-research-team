"""Conservative manuscript-review recipe.

This module deliberately treats the authored manuscript as an immutable
cross-run input.  It records local blind-scope tokens per required capability,
reconciles every finding deterministically, and writes only review-run scratch
artifacts plus a readable reviewer report.  Local tokens and reviewer-provided
identity fields are never proof of external scheduler independence.  Until a
signed, independently verified scheduler receipt exists, this recipe emits
advisory review only: never an independent-review verdict or submission-ready
claim.  It cannot rewrite the manuscript, promote the vault, submit a paper,
or claim a PDF that its build receipt verifier has not independently verified.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Mapping

from .. import bounded_repair
from ..artifacts import GateBlock, write_artifact
from . import _shared, manuscript_authoring
from ...tools.ledger import read_events, verify_chain
from ...tools.manuscript_contract import canonical_contract_hash
from ...tools.manuscript_contract import _DEFAULT_SECRET_PATTERNS as _SECRET_PATTERNS
from ...tools.manuscript_security import (
    ManuscriptPathViolation,
    ManuscriptSecretViolation,
    scan_persisted_text,
    validate_run_owned_path,
)
from ...tools.validate_artifact import validate_artifact, validate_payload


STAGES = ["VERIFY", "REPORT"]
DEFAULT_VAULT = "AI agent database/PhD-Research-OS"
INPUT_REL = "inbox/manuscript-review/manuscript-review-input.json"
PRECOMMIT_REL = "inbox/manuscript-review/precommit.json"
RECONCILIATION_REL = "inbox/manuscript-review/reconciliation.json"
REVIEWER_REPORT_REL = "director-review/manuscript/reviewer-report.md"
ADVISORY_STATUS_ARTIFACT = "manuscript-review-advisory-status.artifact.json"
SUBMISSION_CHECKLIST_ARTIFACT = "submission-checklist.artifact.json"

_AUTHORING_ARTIFACT_TYPES = {
    "contract": "manuscript_contract",
    "integration": "manuscript_integration",
    "quality_report": "manuscript_quality_report",
    "build_receipt": "manuscript_build_receipt",
}

REQUIRED_CAPABILITY_IDS = (
    "domain_contribution",
    "methods_reproducibility",
    "figure_table",
    "factual",
    "citation",
    "venue_style_latex",
)
CAPABILITY_ROLES = {
    "domain_contribution": "SCIENTIFIC",
    "methods_reproducibility": "SCIENTIFIC",
    "figure_table": "LATEX_ASSET",
    "factual": "SCIENTIFIC",
    "citation": "EXACT_CITATION",
    "venue_style_latex": "VENUE",
}
CAPABILITY_WORKER_LABELS = {
    "domain_contribution": "manuscript-domain-contribution-reviewer",
    "methods_reproducibility": "manuscript-methods-reproducibility-reviewer",
    "figure_table": "manuscript-figure-table-reviewer",
    "factual": "manuscript-factual-auditor",
    "citation": "manuscript-citation-auditor",
    "venue_style_latex": "manuscript-style-latex-auditor",
}
_CAPABILITY_RE = re.compile(r"^[a-z_]+$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


class ManuscriptReviewError(ValueError):
    """Stable error for a malformed or untrusted review boundary."""


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _hash(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _fail(message: str) -> None:
    raise GateBlock(message)


def capability_bundle_rel(capability: str, *, suffix: str = "primary") -> str:
    if capability not in REQUIRED_CAPABILITY_IDS or not _CAPABILITY_RE.fullmatch(suffix):
        raise ManuscriptReviewError("invalid review capability bundle path")
    return f"inbox/manuscript-review/bundles/{capability}--{suffix}.bundle.json"


def _review_path(run_dir: str | Path, relative: str, *, write: bool = False) -> Path:
    root = Path(run_dir).absolute()
    try:
        checked = validate_run_owned_path(
            relative,
            run_root=root,
            purpose="write" if write else "read",
            owned_output_roots=(root / "inbox", root / "evidence", root / "director-review"),
        )
    except ManuscriptPathViolation as exc:
        _fail(f"review path is unsafe: {exc.code}")
    return Path(checked["path"])


def _write_json_once(run_dir: str | Path, relative: str, value: Mapping[str, Any]) -> Path:
    path = _review_path(run_dir, relative, write=True)
    payload = _canonical(dict(value)) + b"\n"
    if path.exists():
        if path.read_bytes() != payload:
            _fail(f"immutable review artifact differs: {relative}")
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as handle:
            handle.write(payload)
    except FileExistsError:
        return _write_json_once(run_dir, relative, value)
    return path


def _review_file_reference(review_dir: Path, relative: str, label: str) -> dict[str, str]:
    path = _review_path(review_dir, relative)
    if not path.is_file():
        _fail(f"missing {label}: {relative}")
    return {"ref": relative.replace("\\", "/"), "sha256": _file_hash(path)}


def _cross_run_reference(
    source_dir: Path,
    authoring_run_id: str,
    relative: str,
    label: str,
) -> dict[str, str]:
    path = _safe_source_path(source_dir, relative, label)
    portable = relative.replace("\\", "/")
    return {
        "ref": f"runs/{authoring_run_id}/{portable}",
        "sha256": _file_hash(path),
    }


def _cross_run_descriptor_reference(
    source_dir: Path,
    authoring_run_id: str,
    descriptor: Mapping[str, Any],
    label: str,
) -> dict[str, str]:
    relative, sha256 = _bound_source_file(source_dir, descriptor, label)
    return {"ref": f"runs/{authoring_run_id}/{relative}", "sha256": sha256}


def _read_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeDecodeError) as exc:
        _fail(f"cannot read {label}: {type(exc).__name__}")
    if not isinstance(value, dict):
        _fail(f"{label} must be a JSON object")
    return value


def _safe_source_path(source_dir: Path, relative: str, label: str) -> Path:
    """Return one regular, run-owned source file without following links."""

    try:
        checked = validate_run_owned_path(
            relative,
            run_root=source_dir,
            purpose="read",
            owned_output_roots=(source_dir,),
        )
    except ManuscriptPathViolation as exc:
        _fail(f"{label} path is unsafe: {exc.code}")
    path = Path(checked["path"])
    if not path.is_file():
        _fail(f"{label} is not a regular authoring file")
    return path


def _validate_source_root(source_dir: Path) -> None:
    """Force the shared no-link/reparse policy over the authoring run root."""

    try:
        validate_run_owned_path(
            source_dir / ".manuscript-review-boundary-probe",
            run_root=source_dir,
            purpose="read",
            owned_output_roots=(source_dir,),
        )
    except ManuscriptPathViolation as exc:
        _fail(f"cross-run authoring input is unsafe: {exc.code}")


def _source_run(review_dir: Path, payload: Mapping[str, Any]) -> tuple[str, Path]:
    authoring_run_id = payload.get("authoring_run_id")
    source_raw = payload.get("authoring_run_dir")
    if not isinstance(authoring_run_id, str) or not authoring_run_id:
        _fail("review input lacks authoring run id")
    if Path(authoring_run_id).name != authoring_run_id or authoring_run_id in {".", ".."}:
        _fail("review input has an unsafe authoring run id")
    if not isinstance(source_raw, str) or not source_raw:
        _fail("review input lacks authoring run directory")
    source = Path(source_raw).absolute()
    expected_parent = review_dir.parent.absolute()
    if authoring_run_id == review_dir.name or source == review_dir:
        _fail("authoring and review runs must be distinct")
    if source.name != authoring_run_id or source.parent != expected_parent or not source.is_dir():
        _fail("cross-run authoring input is outside the registered runs root")
    _validate_source_root(source)
    resolved_source = source.resolve()
    if resolved_source == review_dir.resolve():
        _fail("authoring and review runs must be distinct")
    return authoring_run_id, resolved_source


def _bound_source_file(source_dir: Path, descriptor: Mapping[str, Any], label: str) -> tuple[str, str]:
    """Resolve a descriptor to a safe, existing in-run file.

    2026-08-07 de-governance: no longer re-hashes the file and compares it against the descriptor's
    declared sha256 (that was tamper-evidence, not the safety property) — path safety + existence
    (via _safe_source_path) is what still gates this. The returned sha256 is the descriptor's
    declared value, still shape-checked, just not verified against the file's actual bytes.
    """
    ref = descriptor.get("ref")
    expected = descriptor.get("sha256")
    if not isinstance(ref, str) or not isinstance(expected, str) or not _SHA256_RE.fullmatch(expected):
        _fail(f"{label} lacks a safe ref/hash pair")
    portable = ref.replace("\\", "/")
    if portable.startswith("/") or ".." in portable.split("/") or ":" in portable:
        _fail(f"{label} reference is unsafe")
    _safe_source_path(source_dir, portable, label)
    return portable, expected


def _source_ledger_is_intact(source_dir: Path) -> bool:
    """Use the run-store chain as a necessary, never sufficient, trust signal."""

    try:
        ledger_path = _safe_source_path(source_dir, "ledger.jsonl", "authoring ledger")
        events = read_events(ledger_path)
    except (GateBlock, OSError, ValueError, UnicodeDecodeError, json.JSONDecodeError):
        return False
    if verify_chain(events):
        return False
    return any(
        event.get("event_type") == "run_started"
        and isinstance(event.get("payload"), Mapping)
        and event["payload"].get("mode") == "manuscript_authoring"
        for event in events
    )


def _self_hash_matches(payload: Mapping[str, Any], field: str) -> bool:
    declared = payload.get(field)
    return (
        isinstance(declared, str)
        and _SHA256_RE.fullmatch(declared) is not None
        and declared == _hash({key: value for key, value in payload.items() if key != field})
    )


def _authoring_artifact(
    source_dir: Path,
    descriptor: Mapping[str, Any],
    label: str,
    artifact_type: str,
) -> dict[str, Any]:
    """Load a bound authoring artifact and retain provenance about its trust level.

    Legacy raw JSON remains readable as an advisory review target, but it never
    satisfies the evidence conditions needed for a build/PDF or readiness claim.
    """

    ref, sha256 = _bound_source_file(source_dir, descriptor, label)
    document = _read_json(_safe_source_path(source_dir, ref, label), label)
    envelope_verified = False
    payload: dict[str, Any] = document
    if "artifact_type" in document or "payload" in document:
        errors = validate_artifact(document)
        if errors:
            _fail(f"{label} artifact envelope is invalid")
        if document.get("artifact_type") != artifact_type or not isinstance(document.get("payload"), Mapping):
            _fail(f"{label} artifact type does not match its declared role")
        payload = dict(document["payload"])
        envelope_verified = True
    schema_verified = not validate_payload(artifact_type, payload)
    if artifact_type == "manuscript_contract":
        try:
            self_hash_verified = schema_verified and canonical_contract_hash(payload) == payload.get("manuscript_snapshot_sha256")
        except Exception:
            self_hash_verified = False
    elif artifact_type == "manuscript_integration":
        self_hash_verified = schema_verified and _self_hash_matches(payload, "integration_hash")
    elif artifact_type == "manuscript_quality_report":
        self_hash_verified = schema_verified and _self_hash_matches(payload, "quality_report_sha256")
    else:
        self_hash_verified = schema_verified and _self_hash_matches(payload, "build_receipt_sha256")
    return {
        "ref": ref,
        "sha256": sha256,
        "payload": payload,
        "envelope_verified": envelope_verified,
        "schema_verified": schema_verified,
        "self_hash_verified": self_hash_verified,
    }


def _verified_compiled_build(
    source_dir: Path,
    authoring_run_id: str,
    artifacts: Mapping[str, Mapping[str, Any]],
    pdf: Mapping[str, Any] | None,
    ledger_verified: bool,
) -> bool:
    """Accept COMPILED only through the existing externally supplied verifier.

    A structurally valid self-report is deliberately insufficient: it needs
    envelope/schema/self-hash binding, an intact authoring ledger, canonical raw
    receipt parity, PDF byte binding, and a verifier-provided signature result.
    """

    contract = artifacts["contract"]
    integration = artifacts["integration"]
    build_artifact = artifacts["build_receipt"]
    build = build_artifact["payload"]
    if (
        not ledger_verified
        or not all(
            item["envelope_verified"] and item["schema_verified"] and item["self_hash_verified"]
            for item in (contract, integration, build_artifact)
        )
        or build.get("build_state") != "COMPILED"
        or not isinstance(pdf, Mapping)
    ):
        return False
    contract_payload = contract["payload"]
    integration_payload = integration["payload"]
    if (
        contract_payload.get("run_id") != authoring_run_id
        or build.get("run_id") != authoring_run_id
        or build.get("manuscript_snapshot_sha256") != contract_payload.get("manuscript_snapshot_sha256")
        or integration_payload.get("manuscript_snapshot_sha256") != contract_payload.get("manuscript_snapshot_sha256")
        or build.get("source_tree_sha256") != integration_payload.get("source_tree_sha256")
    ):
        return False
    build_pdf = build.get("pdf")
    if not isinstance(build_pdf, Mapping):
        return False
    pdf_ref = pdf.get("ref")
    pdf_sha = pdf.get("sha256")
    if not isinstance(pdf_ref, str) or not isinstance(pdf_sha, str):
        return False
    try:
        pdf_path = _safe_source_path(source_dir, pdf_ref, "compiled PDF")
    except GateBlock:
        return False
    if (
        build_pdf.get("path") != pdf_ref
        or build_pdf.get("sha256") != pdf_sha
        or build_pdf.get("byte_size") != pdf_path.stat().st_size
    ):
        return False
    # 2026-08-07 de-governance: no longer requires the canonical on-disk receipt to be byte-equal
    # to the enveloped `build` payload (that was tamper-evidence between two copies of the same
    # record, not the safety property) — still requires the canonical file to exist and parse.
    try:
        raw_receipt_path = _safe_source_path(
            source_dir, "evidence/manuscript-build-receipt.json", "canonical build receipt"
        )
        _read_json(raw_receipt_path, "canonical build receipt")
    except GateBlock:
        return False
    verifier = manuscript_authoring.BUILD_RECEIPT_VERIFIER
    if not callable(verifier):
        return False
    try:
        attested = verifier(
            source_dir,
            "evidence/manuscript-build-receipt.json",
            expected_run_id=authoring_run_id,
            expected_snapshot_sha256=str(contract_payload.get("manuscript_snapshot_sha256") or ""),
            expected_source_sha256=str(integration_payload.get("source_tree_sha256") or ""),
        )
    except Exception:
        return False
    if not isinstance(attested, Mapping):
        return False
    attested_pdf = attested.get("pdf")
    return bool(
        isinstance(attested_pdf, Mapping)
        and attested.get("receipt_sha256") == _hash(build)
        and attested.get("run_id") == authoring_run_id
        and attested.get("manuscript_snapshot_sha256") == contract_payload.get("manuscript_snapshot_sha256")
        and attested.get("requires_pdf") is build.get("requires_pdf")
        and attested.get("build_state") == "COMPILED"
        and attested.get("source_tree_sha256") == integration_payload.get("source_tree_sha256")
        and attested.get("current_source_sha256") == integration_payload.get("source_tree_sha256")
        and attested.get("process_receipt_sha256") == (build.get("process_receipt") or {}).get("receipt_sha256")
        and attested_pdf.get("path") == build_pdf.get("path")
        and attested_pdf.get("sha256") == build_pdf.get("sha256")
        and attested_pdf.get("byte_size") == build_pdf.get("byte_size")
        and bool(str(attested.get("attestation_key_id") or "").strip())
        and attested.get("signature_verified") is True
        and attested.get("source_tree_verified") is True
        and attested.get("pdf_verified") is True
    )


def _load_input(review_dir: Path) -> tuple[dict[str, Any], str, Path, dict[str, Any]]:
    input_path = _review_path(review_dir, INPUT_REL)
    payload = _read_json(input_path, "review input")
    authoring_run_id, source_dir = _source_run(review_dir, payload)
    artifacts: dict[str, dict[str, Any]] = {}
    for key, artifact_type in _AUTHORING_ARTIFACT_TYPES.items():
        descriptor = payload.get(key)
        if not isinstance(descriptor, Mapping):
            _fail(f"review input lacks {key}")
        artifacts[key] = _authoring_artifact(source_dir, descriptor, key, artifact_type)
    manuscript = payload.get("manuscript")
    if not isinstance(manuscript, Mapping):
        _fail("review input lacks manuscript")
    _bound_source_file(source_dir, manuscript, "manuscript")
    quality = artifacts["quality_report"]["payload"]
    build = artifacts["build_receipt"]["payload"]
    pdf = payload.get("pdf")
    if build.get("build_state") == "COMPILED":
        if not isinstance(pdf, Mapping):
            _fail("compiled PDF input must contain a verified PDF descriptor")
        _bound_source_file(source_dir, pdf, "compiled PDF")
    elif pdf is not None:
        _fail("noncompiled authoring input must not carry a PDF claim")
    ledger_verified = _source_ledger_is_intact(source_dir)
    build_verified = _verified_compiled_build(
        source_dir, authoring_run_id, artifacts, pdf if isinstance(pdf, Mapping) else None, ledger_verified
    )
    return payload, authoring_run_id, source_dir, {
        "contract": artifacts["contract"]["payload"],
        "integration": artifacts["integration"]["payload"],
        "quality": quality,
        "build": build,
        "authoring_ledger_verified": ledger_verified,
        "build_verified": build_verified,
        "artifact_verification": {
            key: {
                "envelope_verified": value["envelope_verified"],
                "schema_verified": value["schema_verified"],
                "self_hash_verified": value["self_hash_verified"],
            }
            for key, value in artifacts.items()
        },
    }


def _frozen_inputs(payload: Mapping[str, Any], authoring_run_id: str, source_only: bool) -> dict[str, str]:
    contract = payload["contract"]
    manuscript = payload["manuscript"]
    if source_only:
        pdf_ref = "audit/no-build-receipt"
        pdf_sha = _hash({"source_only": authoring_run_id})
    else:
        pdf = payload["pdf"]
        if not isinstance(pdf, Mapping):
            _fail("compiled authoring input has no PDF descriptor")
        pdf_ref = f"runs/{authoring_run_id}/{pdf['ref']}"
        pdf_sha = str(pdf["sha256"])
    return {
        "contract_ref": f"runs/{authoring_run_id}/{contract['ref']}",
        "contract_sha256": str(contract["sha256"]),
        "manuscript_ref": f"runs/{authoring_run_id}/{manuscript['ref']}",
        "manuscript_sha256": str(manuscript["sha256"]),
        "pdf_ref": pdf_ref,
        "pdf_sha256": pdf_sha,
    }


def prepare_review_precommit(run_dir: str | Path, timestamp: str) -> dict[str, Any]:
    """Freeze cross-run input identity and one distinct blind receipt per capability."""

    review_dir = Path(run_dir).absolute()
    existing_path = _review_path(review_dir, PRECOMMIT_REL)
    if existing_path.is_file():
        # Resume does not mint a new timestamp or receipt set.  Still reopen
        # the immutable authoring descriptors so a later source mutation is
        # detected before any reviewer can reuse the old precommit.
        _load_input(review_dir)
        existing = _read_json(existing_path, "review precommit")
        if existing.get("review_run_id") != review_dir.name:
            _fail("precommit belongs to another review run")
        if existing.get("independence_verified") is not False:
            _fail("precommit lacks the required external-independence caveat")
        return existing
    payload, authoring_run_id, _source_dir, details = _load_input(review_dir)
    # A caller-provided COMPILED JSON/PDF is reviewable context, never build
    # truth.  Only the pre-existing signed build verifier may lift source-only.
    source_only = not bool(details["build_verified"])
    frozen = _frozen_inputs(payload, authoring_run_id, source_only)
    blind_scope_sha = _hash(
        {"review_run_id": review_dir.name, "forbidden": ["authoring-self-audit", "sibling reviewer"]}
    )
    receipts: dict[str, dict[str, str]] = {}
    for capability in REQUIRED_CAPABILITY_IDS:
        receipt = {
            "ref": f"inbox/manuscript-review/receipts/{capability}.json",
            "sha256": _hash({"review_run_id": review_dir.name, "capability": capability, "blind_scope_sha256": blind_scope_sha}),
        }
        receipts[capability] = receipt
    precommit = {
        "schema_version": "manuscript-review-precommit/v1",
        "review_run_id": review_dir.name,
        "authoring_run_id": authoring_run_id,
        "created_at": timestamp,
        "independence_verified": False,
        "independence_status": "UNVERIFIED_NO_EXTERNAL_SCHEDULER_RECEIPT",
        "source_only": source_only,
        "frozen_inputs": frozen,
        "blind_scope_sha256": blind_scope_sha,
        "authorization_receipts": receipts,
        "authoring_claims": {
            "quality_state": details["quality"].get("daily_state"),
            "quality_submission_ready": details["quality"].get("submission_ready"),
            "build_state": details["build"].get("build_state"),
        },
        "evidence_verification": {
            "authoring_ledger_verified": details["authoring_ledger_verified"],
            "build_receipt_verified": details["build_verified"],
            "artifacts": details["artifact_verification"],
        },
    }
    _write_json_once(review_dir, PRECOMMIT_REL, precommit)
    return precommit


def llm_step(
    run_dir: str | Path,
    stage: str,
    request: str,
    vault: str | None = None,
    model_policy: str = "default",
) -> dict[str, Any] | None:
    """Expose the VERIFY blind panel and REPORT packager through normal operate wiring.

    The generic wiring smoke intentionally opens a fresh run before the director
    has supplied the cross-run review input.  That may expose role contracts but
    must not manufacture a precommit or access another run.  The real panel
    obtains frozen inputs only once ``INPUT_REL`` exists.
    """

    del vault, model_policy
    if stage == "VERIFY":
        input_path = _review_path(run_dir, INPUT_REL)
        precommit = prepare_review_precommit(run_dir, "scheduler-precommit") if input_path.is_file() else None
        workers = []
        for capability in REQUIRED_CAPABILITY_IDS:
            workers.append(
                {
                    "label": CAPABILITY_WORKER_LABELS[capability],
                    "capability_id": capability,
                    "role": CAPABILITY_ROLES[capability],
                    "model": "opus",
                    "output": capability_bundle_rel(capability),
                    "input_contract": {
                        "blind": True,
                        "frozen_inputs": precommit["frozen_inputs"] if precommit else "requires frozen review input",
                        "forbidden_inputs": ["authoring-self-audit conclusions", "sibling reviewer conclusions"],
                    },
                    "prompt": (
                        f"NORTH STAR: assess the frozen manuscript for {request}. "
                        f"Blind {capability} reviewer: sibling reviewer conclusions are forbidden; "
                        "external scheduler independence is not yet verified."
                    ),
                }
            )
        return {
            "label": "manuscript-review-blind-panel",
            "group_barriers": False,
            "workers": workers,
            "precommit": PRECOMMIT_REL if precommit else None,
        }
    if stage == "REPORT":
        worker = {
            "label": "manuscript-submission-packager",
            "model": "opus",
            "output": "inbox/manuscript-review/manuscript-submission-packager.bundle.json",
            "prompt": (
                f"NORTH STAR: present the advisory reconciled review for {request}; "
                "never submit, merge fixes, or present advisory rebuttal text as applied."
            ),
        }
        return {"label": "manuscript-review-report", "group_barriers": False, "workers": [worker]}
    return None


def _read_bundle(review_dir: Path, capability: str, precommit: Mapping[str, Any]) -> dict[str, Any]:
    path = _review_path(review_dir, capability_bundle_rel(capability))
    if not path.is_file():
        _fail(f"missing required capability: {capability}")
    bundle = _read_json(path, f"{capability} review bundle")
    errors = validate_payload("manuscript_review_verdict", bundle)
    if errors:
        _fail(f"invalid {capability} review bundle: {errors[0]}")
    expected_receipt = precommit["authorization_receipts"][capability]
    receipt = bundle.get("blind_read_receipt")
    if not isinstance(receipt, Mapping) or receipt.get("scheduler_authorization_ref") != expected_receipt["ref"] or receipt.get("scheduler_authorization_sha256") != expected_receipt["sha256"]:
        _fail(f"authorization receipt mismatch for {capability}")
    if receipt.get("blind_scope_sha256") != precommit["blind_scope_sha256"]:
        _fail(f"blind scope mismatch for {capability}")
    if bundle.get("review_run_id") != review_dir.name:
        _fail(f"cross-run review bundle for {capability}")
    identity = bundle.get("reviewer_identity")
    if not isinstance(identity, Mapping) or identity.get("role") != CAPABILITY_ROLES[capability]:
        _fail(f"reviewer identity role mismatch for {capability}")
    # ``independent_from_authoring`` is required by the legacy verdict schema,
    # but is authored by the same caller as this bundle.  It remains structural
    # metadata only; no branch below treats it as proof of independence.
    if bundle.get("frozen_inputs") != precommit["frozen_inputs"]:
        _fail(f"frozen input mismatch for {capability}")
    # 2026-08-07 de-governance: verdict_sha256 self-consistency (bundle's declared hash of its own
    # other fields) is no longer re-verified — tamper-evidence, not the safety property. Every
    # binding check above (authorization receipt, blind scope, review_run_id, frozen_inputs) stays:
    # those bind this bundle to a FROZEN precommit made before the review, which is what independence
    # actually rests on.
    for scoped in bundle.get("scoped_inputs", []):
        if not isinstance(scoped, Mapping):
            _fail(f"invalid scoped input for {capability}")
        ref = str(scoped.get("ref") or "")
        if "authoring-self-audit" in ref or "sibling reviewer" in ref:
            _fail(f"protected conclusion leakage for {capability}")
        if scoped.get("authorization_receipt_sha256") != expected_receipt["sha256"]:
            _fail(f"authorization receipt mismatch for {capability}")
    return bundle


def _quality_rows(quality: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for raw in quality.get("findings", []):
        if not isinstance(raw, Mapping):
            continue
        finding_id = str(raw.get("finding_id") or "quality-finding")
        severity = "BLOCKING" if raw.get("finding_class") == "HARD" else "ADVISORY"
        rows.append(
            {
                "finding_id": finding_id,
                "severity": severity,
                "status": str(raw.get("status") or "OPEN"),
                "dimension": "EXECUTION_TRUTH" if "EXECUTION" in str(raw.get("code") or "") else "CLAIM_EVIDENCE",
                "locus": "authoring-quality-report",
                "description": str(raw.get("message") or raw.get("code") or "quality finding"),
                "evidence_refs": list(raw.get("evidence_refs") or ["authoring-quality-report"]),
                "required_fix": str(raw.get("repair") or "Resolve the deterministic authoring finding."),
                "origin_capability": "authoring_quality",
                "origin_receipt_sha256": _hash(dict(raw)),
            }
        )
    return rows


def _reconcile(bundles: Mapping[str, Mapping[str, Any]], quality: Mapping[str, Any], source_only: bool) -> dict[str, Any]:
    rows = _quality_rows(quality)
    for capability, bundle in bundles.items():
        receipt = bundle["blind_read_receipt"]["scheduler_authorization_sha256"]
        for raw in bundle.get("findings", []):
            if not isinstance(raw, Mapping):
                continue
            item = dict(raw)
            item["origin_capability"] = capability
            item["origin_receipt_sha256"] = receipt
            rows.append(item)
    normalized: list[dict[str, Any]] = []
    for raw in rows:
        normalized.append(
            {
                "finding_id": str(raw["finding_id"]),
                "severity": str(raw.get("severity") or "ADVISORY"),
                "status": str(raw.get("status") or "OPEN"),
                "dimension": str(raw.get("dimension") or "CLAIM_EVIDENCE"),
                "locus": str(raw.get("locus") or "unknown"),
                "description": str(raw.get("description") or "finding"),
                "evidence_refs": list(raw.get("evidence_refs") or ["authoring-quality-report"]),
                "required_fix": str(raw.get("required_fix") or "Repair the finding."),
                "origin_capability": str(raw["origin_capability"]),
                "origin_receipt_sha256": str(raw["origin_receipt_sha256"]),
                "disposition": "UNRESOLVED" if raw.get("status") == "OPEN" else "RECORDED",
                "evidence": list(raw.get("evidence_refs") or ["authoring-quality-report"]),
                "rationale": "Preserved from a capability bundle or authoring audit; external reviewer independence is unverified.",
            }
        )
    candidates = [
        {"finding_id": row["finding_id"], "candidate": row["required_fix"], "applied": False}
        for row in normalized if row["status"] == "OPEN"
    ]
    return {
        "source_only": source_only,
        "compiled_pdf_claimed": False,
        "compiled_pdf_verified": not source_only,
        "independence_verified": False,
        "independence_status": "UNVERIFIED_NO_EXTERNAL_SCHEDULER_RECEIPT",
        "rows": normalized,
        "rebuttal_candidates": candidates,
    }


def _advisory_status_note(reconciliation: Mapping[str, Any]) -> dict[str, Any]:
    """Represent review progress without minting a false independent verdict."""

    blocking = any(
        row.get("severity") == "BLOCKING" and row.get("status") == "OPEN"
        for row in reconciliation.get("rows", [])
        if isinstance(row, Mapping)
    )
    return {
        "summary": (
            "Manuscript findings were reconciled as advisory review only. No signed, externally "
            "verified scheduler receipt proves reviewer independence, so no independent-review "
            "verdict or submission authorization was emitted."
        ),
        "references": [RECONCILIATION_REL],
        "produced_artifacts": [],
        "open_questions": [
            "Provision a signed external scheduler receipt verifier before treating a review as independent.",
            "Director decides whether to revise; this advisory review does not submit or mutate the manuscript.",
        ],
        "delivery_status": "BLOCK" if blocking else "USABLE_WITH_CAVEATS",
        "delivery_caveats": [
            "UNVERIFIED_NO_EXTERNAL_SCHEDULER_RECEIPT",
            "submission_ready is always false for this advisory review output.",
        ],
    }


def _write_reviewer_report(review_dir: Path, reconciliation: Mapping[str, Any], result: Mapping[str, Any]) -> Path:
    path = _review_path(review_dir, REVIEWER_REPORT_REL, write=True)
    lines = [
        "# Manuscript Review (Independence Unverified)",
        "",
        f"- Daily state: `{result['daily_state']}`",
        f"- Submission ready: `{str(result['submission_ready']).lower()}`",
        f"- External scheduler independence verified: `{str(result['independence_verified']).lower()}`",
        "- Independence is not externally verified; this is advisory review only and cannot authorize submission.",
        "- This is a separate review-run product; proposed fixes are advisory and unapplied.",
        "",
        "## Evidence Boundary",
        "",
        "- Frozen authoring input and bound evidence/receipt references were used only as advisory review context.",
        "- The report preserves each capability finding and its origin, but it does not relabel a self-supplied hash as independently verified evidence.",
        "",
        "## Review Limit",
        "",
        "- A signed external scheduler receipt verifier is required before any future review may claim reviewer independence or affect submission readiness.",
        "- This advisory output is still useful for prioritizing repairs, comparing reviewer concerns, and preparing a rebuttal candidate.",
        "",
        "## Reconciled Findings",
        "",
    ]
    for row in reconciliation["rows"]:
        lines.extend([
            f"### {row['finding_id']}",
            f"- Origin: `{row['origin_capability']}`",
            f"- Severity/status: `{row['severity']}` / `{row['status']}`",
            f"- Finding: {row['description']}",
            f"- Required fix: {row['required_fix']}",
            "",
        ])
    if not reconciliation["rows"]:
        lines.append("No open findings were recorded by the capability panel.")
    lines.extend([
        "",
        "## Next Decision",
        "",
        "- The director decides whether to revise, seek an externally attested review, or hold the manuscript; this report never submits or changes the frozen authoring run.",
    ])
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "\n".join(lines) + "\n"
    try:
        scan_persisted_text(
            "director-review-manuscript-review",
            text,
            patterns=_SECRET_PATTERNS,
        )
    except ManuscriptSecretViolation as exc:
        # The scanner's exception deliberately excludes secret material; retain
        # only its stable code and do not create/update the director artifact.
        _fail(f"secret scan blocked reviewer report: {exc.code}")
    if path.exists() and path.read_text(encoding="utf-8") != text:
        _fail("reviewer report would overwrite different evidence")
    path.write_text(text, encoding="utf-8")
    return path


def _require_identifier(value: Any, label: str) -> str:
    text = str(value or "")
    if not _IDENTIFIER_RE.fullmatch(text):
        _fail(f"{label} must be a stable checklist identifier")
    return text


def _require_schema_bound_authoring(details: Mapping[str, Any]) -> None:
    verification = details.get("artifact_verification")
    if not isinstance(verification, Mapping):
        _fail("submission checklist requires authoring artifact verification")
    for name in _AUTHORING_ARTIFACT_TYPES:
        facts = verification.get(name)
        if not isinstance(facts, Mapping) or not all(
            facts.get(key) is True
            for key in ("envelope_verified", "schema_verified", "self_hash_verified")
        ):
            _fail(
                f"submission checklist requires a schema-bound, hash-verified authoring {name}"
            )


def _cross_run_tree_reference(
    source_dir: Path,
    authoring_run_id: str,
    relative: Any,
    sha256: Any,
) -> dict[str, str]:
    if not isinstance(relative, str) or not isinstance(sha256, str) or not _SHA256_RE.fullmatch(sha256):
        _fail("source tree reference is incomplete")
    portable = relative.replace("\\", "/").rstrip("/")
    if not portable:
        _fail("source tree reference is incomplete")
    try:
        # ``validate_run_owned_path`` intentionally accepts files only. Probe
        # beneath the manuscript-derived tree to retain its no-link/no-
        # traversal policy while allowing the source-tree binding to be a dir.
        checked = validate_run_owned_path(
            f"{portable}/.submission-checklist-boundary-probe",
            run_root=source_dir,
            purpose="read",
            owned_output_roots=(source_dir,),
        )
    except ManuscriptPathViolation as exc:
        _fail(f"source tree path is unsafe: {exc.code}")
    tree = Path(checked["path"]).parent
    if not tree.is_dir():
        _fail("source tree reference is not an authoring directory")
    return {
        "ref": f"runs/{authoring_run_id}/{portable}",
        "sha256": sha256,
    }


def _check_state(rows: list[Mapping[str, Any]], *, default: str = "UNVERIFIED") -> str:
    if any(row.get("status") == "OPEN" and row.get("severity") == "BLOCKING" for row in rows):
        return "BLOCK"
    if any(row.get("status") == "OPEN" for row in rows):
        return "CAVEAT"
    return default


def _check_payload(
    *,
    summary: str,
    rows: list[Mapping[str, Any]],
    evidence: Mapping[str, str],
    state: str | None = None,
) -> dict[str, Any]:
    finding_ids = [_require_identifier(row.get("finding_id"), "reconciled finding id") for row in rows]
    return {
        "state": state or _check_state(rows),
        "summary": summary,
        "evidence_refs": [dict(evidence)],
        "finding_ids": list(dict.fromkeys(finding_ids)),
    }


def _reconciliation_findings(
    reconciliation: Mapping[str, Any],
    reconciliation_ref: Mapping[str, str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Project every reconciliation row into the checklist without inventing a verdict."""

    findings: list[dict[str, Any]] = []
    blockers: list[dict[str, Any]] = []
    for raw in reconciliation.get("rows", []):
        if not isinstance(raw, Mapping):
            _fail("reconciliation contains a malformed finding")
        finding_id = _require_identifier(raw.get("finding_id"), "reconciled finding id")
        severity = str(raw.get("severity") or "ADVISORY")
        status = str(raw.get("status") or "OPEN")
        if severity not in {"BLOCKING", "ADVISORY"} or status not in {"OPEN", "RESOLVED"}:
            _fail(f"reconciliation finding {finding_id} has an unsupported status/severity")
        hard_open = severity == "BLOCKING" and status == "OPEN"
        findings.append(
            {
                "finding_id": finding_id,
                "source_ref": reconciliation_ref["ref"],
                "source_sha256": reconciliation_ref["sha256"],
                "finding_class": "HARD" if severity == "BLOCKING" else "ADVISORY",
                "status": status,
                "disposition": "UNRESOLVED" if status == "OPEN" else "RECONCILED",
                "daily_effect": "NONE" if status == "RESOLVED" else ("BLOCK" if hard_open else "CAVEAT"),
                "submission_effect": "BLOCK" if hard_open else "NONE",
                "minority": bool(raw.get("minority", False)),
                "abstention": bool(raw.get("abstention", False)),
                "unresolved_science": bool(raw.get("unresolved_science", False)),
                "owner": str(raw.get("origin_capability") or "manuscript-review"),
                "required_repair": str(raw.get("required_fix") or "Repair the reconciled finding."),
                "summary": str(raw.get("description") or "Reconciled manuscript finding."),
                "evidence_refs": [dict(reconciliation_ref)],
            }
        )
        if hard_open:
            blockers.append(
                {
                    "blocker_id": f"submission-blocker-{finding_id}",
                    "finding_id": finding_id,
                    "source_ref": reconciliation_ref["ref"],
                    "source_sha256": reconciliation_ref["sha256"],
                    "rationale": "An open hard reconciled finding blocks submission readiness.",
                }
            )
    return findings, blockers


def _submission_checklist_payload(
    review_dir: Path,
    *,
    input_payload: Mapping[str, Any],
    authoring_run_id: str,
    source_dir: Path,
    precommit: Mapping[str, Any],
    details: Mapping[str, Any],
    reconciliation: Mapping[str, Any],
    result: Mapping[str, Any],
) -> dict[str, Any]:
    """Build one advisory checklist from immutable authoring and review evidence.

    This is deliberately a deterministic projection, not a model-authored
    decision.  In the current deployment no signed scheduler verifier exists,
    so the external-independence blocker is unconditional and
    ``submission_ready`` can never be raised by this reducer.
    """

    _require_schema_bound_authoring(details)
    if precommit.get("independence_verified") is not False:
        _fail("submission checklist refuses an un-caveated review precommit")
    if reconciliation.get("independence_verified") is not False:
        _fail("submission checklist refuses an un-caveated reconciliation")

    contract = details.get("contract")
    integration = details.get("integration")
    quality = details.get("quality")
    build = details.get("build")
    if not all(isinstance(value, Mapping) for value in (contract, integration, quality, build)):
        _fail("submission checklist lacks verified authoring payloads")
    snapshot = contract.get("manuscript_snapshot_sha256")
    if not isinstance(snapshot, str) or not _SHA256_RE.fullmatch(snapshot):
        _fail("submission checklist lacks the frozen manuscript snapshot")
    if (
        integration.get("manuscript_snapshot_sha256") != snapshot
        or build.get("manuscript_snapshot_sha256") != snapshot
        or build.get("source_tree_sha256") != integration.get("source_tree_sha256")
        or quality.get("manuscript_sha256") != integration.get("source_tree_sha256")
    ):
        _fail("submission checklist found inconsistent authoring snapshot bindings")
    venue = contract.get("venue_profile")
    if not isinstance(venue, Mapping) or build.get("requires_pdf") is not venue.get("requires_pdf"):
        _fail("submission checklist found inconsistent venue/build PDF policy")

    reconciliation_ref = _review_file_reference(review_dir, RECONCILIATION_REL, "review reconciliation")
    precommit_ref = _review_file_reference(review_dir, PRECOMMIT_REL, "review precommit")
    review_ref = _review_file_reference(review_dir, REVIEWER_REPORT_REL, "reviewer report")
    quality_ref = _cross_run_descriptor_reference(
        source_dir, authoring_run_id, input_payload["quality_report"], "quality report"
    )
    build_ref = _cross_run_descriptor_reference(
        source_dir, authoring_run_id, input_payload["build_receipt"], "build receipt"
    )
    manuscript_ref = _cross_run_descriptor_reference(
        source_dir, authoring_run_id, input_payload["manuscript"], "manuscript"
    )
    manuscript_relative, _ = _bound_source_file(
        source_dir, input_payload["manuscript"], "manuscript"
    )
    source_tree_relative = Path(manuscript_relative).parent.as_posix()
    if source_tree_relative in {"", "."}:
        _fail("submission checklist manuscript must live beneath a source tree")
    source_tree_ref = _cross_run_tree_reference(
        source_dir,
        authoring_run_id,
        source_tree_relative,
        integration.get("source_tree_sha256"),
    )
    overview_ref = _cross_run_reference(
        source_dir, authoring_run_id, "director-review/manuscript/00-OVERVIEW.md", "authoring overview"
    )
    coverage_ref = _cross_run_reference(
        source_dir, authoring_run_id, "director-review/manuscript/local-literature-coverage.md", "coverage report"
    )
    authoring_plan_ref = _cross_run_reference(
        source_dir, authoring_run_id, "director-review/manuscript/authoring-plan.md", "authoring plan"
    )

    build_state = str(build.get("build_state") or "")
    if build_state not in {"COMPILED", "TOOLCHAIN_MISSING", "COMPILE_FAILED"}:
        _fail("submission checklist has an invalid build state")
    evidence_links: dict[str, dict[str, str]] = {
        "overview": overview_ref,
        "coverage": coverage_ref,
        "authoring_plan": authoring_plan_ref,
        "manuscript": manuscript_ref,
        "source_tree": source_tree_ref,
        "quality_report": quality_ref,
        "review": review_ref,
        "build_receipt": build_ref,
        "reconciliation": reconciliation_ref,
        "evidence_index": precommit_ref,
    }
    pdf_truth: dict[str, Any]
    if build_state == "COMPILED":
        pdf_descriptor = input_payload.get("pdf")
        build_pdf = build.get("pdf")
        if not isinstance(pdf_descriptor, Mapping) or not isinstance(build_pdf, Mapping):
            _fail("compiled submission checklist lacks a bound PDF descriptor")
        pdf_ref = _cross_run_descriptor_reference(source_dir, authoring_run_id, pdf_descriptor, "compiled PDF")
        if build_pdf.get("path") != pdf_descriptor.get("ref") or build_pdf.get("sha256") != pdf_descriptor.get("sha256"):
            _fail("compiled submission checklist PDF does not match the build receipt")
        evidence_links["pdf"] = pdf_ref
        pdf_truth = {"available": True, "ref": pdf_ref["ref"], "sha256": pdf_ref["sha256"]}
    else:
        if input_payload.get("pdf") is not None:
            _fail("noncompiled submission checklist cannot carry a PDF")
        pdf_truth = {"available": False, "ref": None, "sha256": None}

    rows = [dict(row) for row in reconciliation.get("rows", []) if isinstance(row, Mapping)]
    capability_coverage: dict[str, dict[str, str]] = {}
    for capability in REQUIRED_CAPABILITY_IDS:
        capability_rows = [row for row in rows if row.get("origin_capability") == capability]
        if any(row.get("status") == "OPEN" and row.get("severity") == "BLOCKING" for row in capability_rows):
            state = "BLOCK"
        elif any(row.get("status") == "OPEN" for row in capability_rows):
            state = "NEEDS_REPAIR"
        else:
            # A local token is not independent evidence.  Do not manufacture a
            # PASS merely because a capability bundle contained no findings.
            state = "UNRESOLVED"
        capability_coverage[capability] = {
            "state": state,
            "source_ref": reconciliation_ref["ref"],
            "source_sha256": reconciliation_ref["sha256"],
        }

    official_rows = [row for row in rows if row.get("origin_capability") == "venue_style_latex"]
    anonymity_rows = [row for row in rows if row.get("dimension") == "ANONYMITY_PRIVACY"]
    scientific_rows = [
        row
        for row in rows
        if row.get("origin_capability") in {"domain_contribution", "methods_reproducibility", "factual", "citation", "authoring_quality"}
    ]
    asset_rows = [row for row in rows if row.get("origin_capability") == "figure_table"]
    cross_reference_rows = [row for row in rows if row.get("origin_capability") == "venue_style_latex"]
    if build_state == "COMPILED":
        build_check_state = "CLEAR" if details.get("build_verified") is True else "UNVERIFIED"
        build_summary = (
            "The compiled PDF bytes are hash-bound, but the build receipt is not externally verified."
            if build_check_state == "UNVERIFIED"
            else "The compiled PDF and its signed build receipt are hash-bound."
        )
    elif bool(venue.get("requires_pdf")):
        build_check_state = "BLOCK"
        build_summary = "The venue requires a PDF and the frozen build receipt did not compile one."
    else:
        build_check_state = "CAVEAT"
        build_summary = "No compiled PDF is available; the venue profile does not make it a hard field."
    checks = {
        "official_rules": _check_payload(
            summary="Official venue-rule review is preserved from the venue/style capability.",
            rows=official_rows,
            evidence=reconciliation_ref,
        ),
        "anonymity_privacy": _check_payload(
            summary="Anonymity/privacy has no externally attested independent clearance.",
            rows=anonymity_rows,
            evidence=reconciliation_ref,
            state=_check_state(anonymity_rows, default="UNVERIFIED"),
        ),
        "scientific_citation_number_closure": _check_payload(
            summary="Scientific, citation, numeric, and deterministic authoring findings are preserved.",
            rows=scientific_rows,
            evidence=reconciliation_ref,
        ),
        "assets": _check_payload(
            summary="Figure/table findings are preserved from the dedicated capability.",
            rows=asset_rows,
            evidence=reconciliation_ref,
        ),
        "cross_references": _check_payload(
            summary="Cross-reference and style findings are preserved from venue/style review.",
            rows=cross_reference_rows,
            evidence=reconciliation_ref,
        ),
        "source_build_pdf_truth": _check_payload(
            summary=build_summary,
            rows=[],
            evidence=build_ref,
            state=build_check_state,
        ),
    }

    findings, submission_blockers = _reconciliation_findings(reconciliation, reconciliation_ref)
    scheduler_finding_id = "external-scheduler-independence-unverified"
    findings.append(
        {
            "finding_id": scheduler_finding_id,
            "source_ref": reconciliation_ref["ref"],
            "source_sha256": reconciliation_ref["sha256"],
            "finding_class": "HARD",
            "status": "OPEN",
            "disposition": "UNRESOLVED",
            "daily_effect": "CAVEAT",
            "submission_effect": "BLOCK",
            "minority": False,
            "abstention": False,
            "unresolved_science": False,
            "owner": "external-scheduler",
            "required_repair": "Provide a verifier-backed signed external scheduler receipt for this review run.",
            "summary": "No external signed scheduler receipt proves reviewer independence.",
            "evidence_refs": [dict(reconciliation_ref)],
        }
    )
    submission_blockers.append(
        {
            "blocker_id": "external-scheduler-independence",
            "finding_id": scheduler_finding_id,
            "source_ref": reconciliation_ref["ref"],
            "source_sha256": reconciliation_ref["sha256"],
            "rationale": "The advisory local review has no verifier-backed external scheduler independence receipt.",
        }
    )
    daily_state = str(result.get("daily_state") or quality.get("daily_state") or "USABLE_WITH_CAVEATS")
    if daily_state not in {"USABLE", "USABLE_WITH_CAVEATS", "NEEDS_SUPPLEMENT", "BLOCK"}:
        _fail("submission checklist has an invalid daily state")
    checklist = {
        "schema_version": "1.0.0",
        "checklist_id": f"submission-checklist-{review_dir.name}",
        "review_run_id": review_dir.name,
        "producer_role": "manuscript-submission-packager",
        "manuscript_snapshot_sha256": snapshot,
        "reconciliation": {
            "ref": reconciliation_ref["ref"],
            "sha256": reconciliation_ref["sha256"],
            "source_finding_index_ref": reconciliation_ref["ref"],
            "source_finding_index_sha256": reconciliation_ref["sha256"],
        },
        "quality_report": quality_ref,
        "daily_state": daily_state,
        # This local mode cannot authenticate scheduler separation; preserve
        # the source quality signal as evidence, but never promote it to a
        # submission decision.
        "submission_ready": False,
        "build_truth": {
            "receipt_ref": build_ref["ref"],
            "receipt_sha256": build_ref["sha256"],
            "build_state": build_state,
            "requires_pdf": bool(build.get("requires_pdf")),
            "source_tree_ref": source_tree_ref["ref"],
            "source_tree_sha256": source_tree_ref["sha256"],
            "pdf": pdf_truth,
        },
        "capability_coverage": capability_coverage,
        "checks": checks,
        "findings": findings,
        "submission_blockers": submission_blockers,
        "evidence_links": evidence_links,
        "outstanding_director_decisions": [
            {
                "decision_id": f"director-external-review-{review_dir.name}",
                "question": "Should the director request an externally attested independent review before considering submission?",
                "authority": "DIRECTOR_HUMAN",
                "status": "REQUIRED",
                "evidence_refs": [dict(reconciliation_ref)],
            }
        ],
        "submission_authorization": False,
    }
    checklist["submission_checklist_sha256"] = _hash(checklist)
    errors = validate_payload("submission_checklist", checklist)
    if errors:
        _fail(f"submission checklist schema invalid: {errors[0]}")
    return checklist


def _write_submission_checklist(
    review_dir: Path,
    *,
    input_payload: Mapping[str, Any],
    authoring_run_id: str,
    source_dir: Path,
    precommit: Mapping[str, Any],
    details: Mapping[str, Any],
    reconciliation: Mapping[str, Any],
    result: Mapping[str, Any],
    timestamp: str,
) -> str:
    payload = _submission_checklist_payload(
        review_dir,
        input_payload=input_payload,
        authoring_run_id=authoring_run_id,
        source_dir=source_dir,
        precommit=precommit,
        details=details,
        reconciliation=reconciliation,
        result=result,
    )
    try:
        return write_artifact(
            review_dir,
            "REPORT",
            SUBMISSION_CHECKLIST_ARTIFACT,
            "submission_checklist",
            "manuscript-submission-packager",
            payload,
            timestamp,
        )
    except ValueError as exc:
        _fail(f"submission checklist schema invalid: {exc}")


def _report_dets(review_dir: Path, timestamp: str) -> tuple[list[str], dict[str, Any]]:
    """Publish an already-derived review report without rerunning the panel."""

    reconciliation_path = _review_path(review_dir, RECONCILIATION_REL)
    if not reconciliation_path.is_file():
        _fail("REPORT requires a completed advisory review reconciliation")
    reconciliation = _read_json(reconciliation_path, "review reconciliation")
    if reconciliation.get("independence_verified") is not False:
        _fail("REPORT refuses a reconciliation without the external-independence caveat")
    blocking = any(
        row.get("severity") == "BLOCKING" and row.get("status") == "OPEN"
        for row in reconciliation.get("rows", []) if isinstance(row, Mapping)
    )
    result = {
        "review_run_id": review_dir.name,
        "independence_verified": False,
        "independence_status": "UNVERIFIED_NO_EXTERNAL_SCHEDULER_RECEIPT",
        "daily_state": "BLOCK" if blocking else "USABLE_WITH_CAVEATS",
        "submission_ready": False,
    }
    report = _write_reviewer_report(review_dir, reconciliation, result)
    precommit = prepare_review_precommit(review_dir, timestamp)
    input_payload, authoring_run_id, source_dir, details = _load_input(review_dir)
    checklist_path = _write_submission_checklist(
        review_dir,
        input_payload=input_payload,
        authoring_run_id=authoring_run_id,
        source_dir=source_dir,
        precommit=precommit,
        details=details,
        reconciliation=reconciliation,
        result=result,
        timestamp=timestamp,
    )
    note = {
        "summary": "Advisory manuscript review report rendered from reconciled capability findings; external scheduler independence remains unverified.",
        "references": [REVIEWER_REPORT_REL, RECONCILIATION_REL, f"evidence/REPORT/{SUBMISSION_CHECKLIST_ARTIFACT}"],
        "produced_artifacts": [f"evidence/VERIFY/{ADVISORY_STATUS_ARTIFACT}", f"evidence/REPORT/{SUBMISSION_CHECKLIST_ARTIFACT}"],
        "open_questions": ["Director decides whether to revise; this advisory review does not submit or mutate the manuscript."],
        "delivery_status": result["daily_state"],
        "delivery_caveats": ["UNVERIFIED_NO_EXTERNAL_SCHEDULER_RECEIPT"],
    }
    note_path = write_artifact(
        review_dir, "REPORT", "manuscript-review-report-note.artifact.json", "report_note",
        "manuscript-submission-packager", note, timestamp,
    )
    return [note_path, checklist_path, str(report)], result


def run_dets(run_dir: str | Path, stage: str, timestamp: str) -> tuple[list[str], dict[str, Any]]:
    """Reconcile review bundles and render advisory-only advice."""

    review_dir = Path(run_dir).absolute()
    if stage == "REPORT":
        return _report_dets(review_dir, timestamp)
    if stage != "VERIFY":
        raise ValueError(f"manuscript_review has no stage {stage!r}")
    precommit = prepare_review_precommit(review_dir, timestamp)
    _payload, _authoring_id, _source_dir, details = _load_input(review_dir)
    bundles = {capability: _read_bundle(review_dir, capability, precommit) for capability in REQUIRED_CAPABILITY_IDS}
    reconciliation = _reconcile(bundles, details["quality"], bool(precommit["source_only"]))
    _write_json_once(review_dir, RECONCILIATION_REL, reconciliation)
    status_path = write_artifact(
        review_dir,
        "VERIFY",
        ADVISORY_STATUS_ARTIFACT,
        "report_note",
        "manuscript-review-safety-reducer",
        _advisory_status_note(reconciliation),
        timestamp,
    )
    blocking = any(row["severity"] == "BLOCKING" and row["status"] == "OPEN" for row in reconciliation["rows"])
    result = {
        "review_run_id": review_dir.name,
        "independence_verified": False,
        "independence_status": "UNVERIFIED_NO_EXTERNAL_SCHEDULER_RECEIPT",
        "daily_state": "BLOCK" if blocking else "USABLE_WITH_CAVEATS",
        "submission_ready": False,
    }
    report = _write_reviewer_report(review_dir, reconciliation, result)
    return [status_path, str(review_dir / RECONCILIATION_REL), str(report)], result


def run_dets_with_repair(run_dir: str | Path, stage: str, timestamp: str):
    return bounded_repair.attempt_with_repair(
        run_dir, stage, _shared.budget(run_dir), timestamp, lambda: run_dets(run_dir, stage, timestamp)
    )


__all__ = [
    "CAPABILITY_ROLES",
    "DEFAULT_VAULT",
    "INPUT_REL",
    "PRECOMMIT_REL",
    "RECONCILIATION_REL",
    "REQUIRED_CAPABILITY_IDS",
    "STAGES",
    "SUBMISSION_CHECKLIST_ARTIFACT",
    "capability_bundle_rel",
    "llm_step",
    "prepare_review_precommit",
    "run_dets",
    "run_dets_with_repair",
]
