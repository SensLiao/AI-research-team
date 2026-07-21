"""Concrete independent manuscript-review recipe.

This module deliberately treats the authored manuscript as an immutable
cross-run input.  It records one blind receipt per required capability,
reconciles every finding deterministically, and writes only review-run scratch
artifacts plus a readable reviewer report.  It cannot rewrite the manuscript,
promote the vault, submit a paper, or claim a PDF that the frozen input lacks.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Mapping

from ..artifacts import GateBlock, write_artifact
from ...tools.manuscript_security import ManuscriptPathViolation, validate_run_owned_path
from ...tools.validate_artifact import validate_payload


STAGES = ["VERIFY", "REPORT"]
DEFAULT_VAULT = "AI agent database/PhD-Research-OS"
INPUT_REL = "inbox/manuscript-review/manuscript-review-input.json"
PRECOMMIT_REL = "inbox/manuscript-review/precommit.json"
RECONCILIATION_REL = "inbox/manuscript-review/reconciliation.json"
REVIEWER_REPORT_REL = "director-review/manuscript/reviewer-report.md"

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
_CAPABILITY_RE = re.compile(r"^[a-z_]+$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


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
    return f"inbox/manuscript-review/bundles/{capability}--{suffix}.json"


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


def _read_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeDecodeError) as exc:
        _fail(f"cannot read {label}: {type(exc).__name__}")
    if not isinstance(value, dict):
        _fail(f"{label} must be a JSON object")
    return value


def _source_run(review_dir: Path, payload: Mapping[str, Any]) -> tuple[str, Path]:
    authoring_run_id = payload.get("authoring_run_id")
    source_raw = payload.get("authoring_run_dir")
    if not isinstance(authoring_run_id, str) or not authoring_run_id:
        _fail("review input lacks authoring run id")
    if not isinstance(source_raw, str) or not source_raw:
        _fail("review input lacks authoring run directory")
    source = Path(source_raw).resolve()
    expected_parent = review_dir.parent.resolve()
    if source.name != authoring_run_id or source.parent != expected_parent or not source.is_dir():
        _fail("cross-run authoring input is outside the registered runs root")
    return authoring_run_id, source


def _bound_source_file(source_dir: Path, descriptor: Mapping[str, Any], label: str) -> tuple[str, str]:
    ref = descriptor.get("ref")
    expected = descriptor.get("sha256")
    if not isinstance(ref, str) or not isinstance(expected, str) or not _SHA256_RE.fullmatch(expected):
        _fail(f"{label} lacks a safe ref/hash pair")
    portable = ref.replace("\\", "/")
    if portable.startswith("/") or ".." in portable.split("/") or ":" in portable:
        _fail(f"{label} reference is unsafe")
    candidate = source_dir / portable
    if not candidate.is_file() or _file_hash(candidate) != expected:
        _fail(f"{label} hash does not match frozen authoring input")
    return portable, expected


def _load_input(review_dir: Path) -> tuple[dict[str, Any], str, Path, dict[str, Any]]:
    input_path = _review_path(review_dir, INPUT_REL)
    payload = _read_json(input_path, "review input")
    authoring_run_id, source_dir = _source_run(review_dir, payload)
    for key in ("contract", "integration", "manuscript", "quality_report", "build_receipt"):
        descriptor = payload.get(key)
        if not isinstance(descriptor, Mapping):
            _fail(f"review input lacks {key}")
        _bound_source_file(source_dir, descriptor, key)
    quality_ref, _quality_sha = _bound_source_file(source_dir, payload["quality_report"], "quality report")
    build_ref, _build_sha = _bound_source_file(source_dir, payload["build_receipt"], "build receipt")
    quality = _read_json(source_dir / quality_ref, "quality report")
    build = _read_json(source_dir / build_ref, "build receipt")
    pdf = payload.get("pdf")
    if build.get("build_state") == "COMPILED":
        if not isinstance(pdf, Mapping):
            _fail("compiled PDF input must contain a verified PDF descriptor")
        _bound_source_file(source_dir, pdf, "compiled PDF")
    elif pdf is not None:
        _fail("noncompiled authoring input must not carry a PDF claim")
    return payload, authoring_run_id, source_dir, {"quality": quality, "build": build}


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
        return existing
    payload, authoring_run_id, _source_dir, details = _load_input(review_dir)
    source_only = details["build"].get("build_state") != "COMPILED"
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
        "source_only": source_only,
        "frozen_inputs": frozen,
        "blind_scope_sha256": blind_scope_sha,
        "authorization_receipts": receipts,
        "quality_state": details["quality"].get("daily_state"),
        "build_state": details["build"].get("build_state"),
    }
    _write_json_once(review_dir, PRECOMMIT_REL, precommit)
    return precommit


def llm_step(run_dir: str | Path, stage: str, action: str) -> dict[str, Any]:
    """Expose a sparse blind panel contract for the existing scheduler layer."""

    if stage != "VERIFY" or action != "review":
        raise ManuscriptReviewError("manuscript review only dispatches a VERIFY review panel")
    precommit = prepare_review_precommit(run_dir, "scheduler-precommit")
    workers = []
    for capability in REQUIRED_CAPABILITY_IDS:
        workers.append(
            {
                "capability_id": capability,
                "role": CAPABILITY_ROLES[capability],
                "output": capability_bundle_rel(capability),
                "input_contract": {
                    "blind": True,
                    "frozen_inputs": precommit["frozen_inputs"],
                    "forbidden_inputs": ["authoring-self-audit conclusions", "sibling reviewer conclusions"],
                },
                "prompt": f"Blind {capability} reviewer: sibling reviewer conclusions are forbidden.",
            }
        )
    return {"group_barriers": False, "workers": workers, "precommit": PRECOMMIT_REL}


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
    if not isinstance(identity, Mapping) or identity.get("role") != CAPABILITY_ROLES[capability] or identity.get("independent_from_authoring") is not True:
        _fail(f"reviewer identity is not independent for {capability}")
    if bundle.get("frozen_inputs") != precommit["frozen_inputs"]:
        _fail(f"frozen input mismatch for {capability}")
    expected_hash = _hash({key: value for key, value in bundle.items() if key != "verdict_sha256"})
    if bundle.get("verdict_sha256") != expected_hash:
        _fail(f"review bundle hash mismatch for {capability}")
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
                "rationale": "Preserved from the independent capability or deterministic authoring audit.",
            }
        )
    candidates = [
        {"finding_id": row["finding_id"], "candidate": row["required_fix"], "applied": False}
        for row in normalized if row["status"] == "OPEN"
    ]
    return {
        "source_only": source_only,
        "compiled_pdf_claimed": False,
        "rows": normalized,
        "rebuttal_candidates": candidates,
    }


def _verdict_payload(review_dir: Path, precommit: Mapping[str, Any], reconciliation: Mapping[str, Any]) -> dict[str, Any]:
    findings = [{key: row[key] for key in ("finding_id", "severity", "status", "dimension", "locus", "description", "evidence_refs", "required_fix")} for row in reconciliation["rows"]]
    open_blocking = any(row["status"] == "OPEN" and row["severity"] == "BLOCKING" for row in findings)
    open_advisory = any(row["status"] == "OPEN" for row in findings)
    disposition = "BLOCK" if open_blocking else ("NEEDS_REPAIR" if open_advisory else "PASS")
    receipt_sha = _hash({"review_run_id": review_dir.name, "meta": True, "scope": precommit["blind_scope_sha256"]})
    payload: dict[str, Any] = {
        "schema_version": "1.0.0",
        "review_id": "manuscript-meta-review",
        "review_run_id": review_dir.name,
        "reviewer_identity": {"reviewer_id": "manuscript-meta-reviewer", "role": "SCIENTIFIC", "independent_from_authoring": True},
        "blind_read_receipt": {
            "scheduler_authorization_ref": "inbox/manuscript-review/receipts/meta-review.json",
            "scheduler_authorization_sha256": receipt_sha,
            "blind_scope_sha256": precommit["blind_scope_sha256"],
            "issued_at": str(precommit["created_at"]),
            "other_reviewer_conclusions_visible": False,
            "generation_artifacts_counted_as_independent_evidence": False,
        },
        "frozen_inputs": dict(precommit["frozen_inputs"]),
        "scoped_inputs": [
            {"kind": "CONTRACT", "ref": precommit["frozen_inputs"]["contract_ref"], "sha256": precommit["frozen_inputs"]["contract_sha256"], "authorization_receipt_sha256": receipt_sha},
            {"kind": "MANUSCRIPT", "ref": precommit["frozen_inputs"]["manuscript_ref"], "sha256": precommit["frozen_inputs"]["manuscript_sha256"], "authorization_receipt_sha256": receipt_sha},
            {"kind": "PDF", "ref": precommit["frozen_inputs"]["pdf_ref"], "sha256": precommit["frozen_inputs"]["pdf_sha256"], "authorization_receipt_sha256": receipt_sha},
        ],
        "findings": findings,
        "disposition": disposition,
    }
    payload["verdict_sha256"] = _hash(payload)
    return payload


def _write_reviewer_report(review_dir: Path, reconciliation: Mapping[str, Any], result: Mapping[str, Any]) -> Path:
    path = _review_path(review_dir, REVIEWER_REPORT_REL, write=True)
    lines = [
        "# Independent Manuscript Review",
        "",
        f"- Daily state: `{result['daily_state']}`",
        f"- Submission ready: `{str(result['submission_ready']).lower()}`",
        "- This is a separate review-run product; proposed fixes are advisory and unapplied.",
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
        lines.append("No open findings were recorded by the independent capability panel.")
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "\n".join(lines) + "\n"
    if path.exists() and path.read_text(encoding="utf-8") != text:
        _fail("reviewer report would overwrite different evidence")
    path.write_text(text, encoding="utf-8")
    return path


def run_dets(run_dir: str | Path, stage: str, timestamp: str) -> tuple[list[str], dict[str, Any]]:
    """Verify all blind bundles, derive one review verdict, and render review-only advice."""

    if stage != "VERIFY":
        raise ManuscriptReviewError("manuscript review deterministic work is VERIFY-only")
    review_dir = Path(run_dir).absolute()
    precommit = prepare_review_precommit(review_dir, timestamp)
    _payload, _authoring_id, _source_dir, details = _load_input(review_dir)
    bundles = {capability: _read_bundle(review_dir, capability, precommit) for capability in REQUIRED_CAPABILITY_IDS}
    reconciliation = _reconcile(bundles, details["quality"], bool(precommit["source_only"]))
    _write_json_once(review_dir, RECONCILIATION_REL, reconciliation)
    verdict = _verdict_payload(review_dir, precommit, reconciliation)
    artifact_path = write_artifact(
        review_dir,
        "VERIFY",
        "manuscript-review-verdict.artifact.json",
        "manuscript_review_verdict",
        "manuscript-meta-reviewer",
        verdict,
        timestamp,
    )
    blocking = any(row["severity"] == "BLOCKING" and row["status"] == "OPEN" for row in reconciliation["rows"])
    source_only = bool(precommit["source_only"])
    source_submission_ready = details["quality"].get("submission_ready") is True
    result = {
        "review_run_id": review_dir.name,
        "verdict_sha256": verdict["verdict_sha256"],
        "daily_state": "BLOCK" if blocking else ("USABLE_WITH_CAVEATS" if source_only else "USABLE"),
        "submission_ready": bool(source_submission_ready and not source_only and not blocking),
    }
    report = _write_reviewer_report(review_dir, reconciliation, result)
    return [artifact_path, str(review_dir / RECONCILIATION_REL), str(report)], result


__all__ = [
    "CAPABILITY_ROLES",
    "DEFAULT_VAULT",
    "INPUT_REL",
    "PRECOMMIT_REL",
    "RECONCILIATION_REL",
    "REQUIRED_CAPABILITY_IDS",
    "STAGES",
    "capability_bundle_rel",
    "llm_step",
    "prepare_review_precommit",
    "run_dets",
]
