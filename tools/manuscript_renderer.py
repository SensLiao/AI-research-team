"""Deterministic, human-first Markdown delivery for manuscript authoring.

The canonical manuscript is the run-owned ``source/`` tree created by the
integrator.  This module only renders a read-only director presentation under
``director-review/manuscript/``; it never changes canonical source, build
truth, audit truth, a review verdict, or submission readiness.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path, PureWindowsPath
from typing import Any, Mapping, Pattern, Sequence
from urllib.parse import quote

from research_agent_teams.tools.manuscript_contract import canonical_contract_hash
from research_agent_teams.tools.manuscript_security import (
    ManuscriptPathViolation,
    ManuscriptSecretViolation,
    scan_persisted_text,
    validate_run_owned_path,
)
from research_agent_teams.tools.runstore import atomic_write_text
from research_agent_teams.tools.validate_artifact import validate_payload


MANUSCRIPT_DIR_REL = Path("director-review") / "manuscript"
OVERVIEW_REL = MANUSCRIPT_DIR_REL / "00-OVERVIEW.md"
COVERAGE_REL = MANUSCRIPT_DIR_REL / "local-literature-coverage.md"
AUTHORING_PLAN_REL = MANUSCRIPT_DIR_REL / "authoring-plan.md"
QUALITY_REPORT_REL = MANUSCRIPT_DIR_REL / "quality-report.md"
REVIEWER_REPORT_REL = MANUSCRIPT_DIR_REL / "reviewer-report.md"
SUBMISSION_CHECKLIST_REL = MANUSCRIPT_DIR_REL / "submission-checklist.md"
LATEX_PROJECTION_REL = MANUSCRIPT_DIR_REL / "latex"
PROJECTION_MANIFEST_REL = LATEX_PROJECTION_REL / "projection-manifest.json"

REQUIRED_REPORT_FILES = (
    "00-OVERVIEW.md",
    "local-literature-coverage.md",
    "authoring-plan.md",
    "quality-report.md",
    "reviewer-report.md",
    "submission-checklist.md",
    "latex",
)

_WINDOWS_ABSOLUTE_RE = re.compile(r"(?<![A-Za-z0-9_.-])[A-Za-z]:[\\/][^\s`<>\]\[)}]+")
_UNC_RE = re.compile(r"(?<![A-Za-z0-9_.-])\\\\[^\s`<>\]\[)}]+")
_POSIX_ABSOLUTE_RE = re.compile(r"(?<![A-Za-z0-9_.-])/(?:[^\s`<>\]\[)}]+/)+[^\s`<>\]\[)}]+")


class ManuscriptRenderError(ValueError):
    """Stable fail-closed error for a presentation/evidence boundary breach."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.findings = [{"code": code, "policy": "manuscript_renderer", "message": message}]
        super().__init__(f"{code}: {message}")


def _fail(code: str, message: str) -> None:
    raise ManuscriptRenderError(code, message)


def _canonical_bytes(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        _fail("NON_CANONICAL_VALUE", f"renderer input is not canonical JSON: {type(exc).__name__}")


def _object_hash(value: Mapping[str, Any], omit: str) -> str:
    return hashlib.sha256(
        _canonical_bytes({key: item for key, item in value.items() if key != omit})
    ).hexdigest()


def _file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _as_mapping(value: Mapping[str, Any] | object, label: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        _fail("BUNDLE_INVALID", f"{label} must be a mapping")
    return dict(value)


def _validate_bundle(artifact_type: str, value: Mapping[str, Any] | object) -> dict[str, Any]:
    payload = _as_mapping(value, artifact_type)
    errors = validate_payload(artifact_type, payload)
    if errors:
        _fail("BUNDLE_INVALID", f"{artifact_type} did not pass its registered schema")
    return payload


def _verify_self_hash(payload: Mapping[str, Any], field: str, label: str) -> None:
    declared = payload.get(field)
    actual = _object_hash(payload, field)
    if not isinstance(declared, str) or declared != actual:
        _fail("BUNDLE_HASH_MISMATCH", f"{label} {field} does not verify")


def _safe_relative(value: object, *, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        _fail("UNSAFE_REFERENCE", f"{label} must be a non-empty relative reference")
    raw = value.strip()
    windows = PureWindowsPath(raw)
    portable = raw.replace("\\", "/")
    parts = portable.split("/")
    if (
        raw.startswith(("/", "\\\\", "//", "~"))
        or windows.is_absolute()
        or bool(windows.drive)
        or "\x00" in raw
        or any(part in {"", ".", ".."} for part in parts)
    ):
        _fail("UNSAFE_REFERENCE", f"{label} is not a bounded run-relative path")
    if ":" in raw or "\\" in raw:
        _fail("UNSAFE_REFERENCE", f"{label} is not a portable run-relative path")
    return "/".join(parts)


def _maybe_run_reference(value: object) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return _safe_relative(value, label="evidence reference")
    except ManuscriptRenderError:
        return None


def _validate_existing_file(root: Path, relative: str, *, expected_sha256: str | None = None) -> Path:
    safe = _safe_relative(relative, label="file reference")
    path = root / safe
    try:
        validate_run_owned_path(path, run_root=root, purpose="read", owned_output_roots=(root,))
    except ManuscriptPathViolation as exc:
        _fail("UNSAFE_REFERENCE", f"file reference is outside the active run: {exc.code}")
    if not path.is_file():
        _fail("EVIDENCE_FILE_MISSING", "bound evidence file is missing")
    if expected_sha256 is not None and _file_hash(path) != expected_sha256:
        _fail("EVIDENCE_HASH_MISMATCH", "bound evidence file hash does not verify")
    return path


def _validate_output_path(root: Path, relative: Path) -> Path:
    path = root / relative
    try:
        validate_run_owned_path(
            path,
            run_root=root,
            purpose="write",
            owned_output_roots=(root / MANUSCRIPT_DIR_REL,),
        )
    except ManuscriptPathViolation as exc:
        _fail("UNSAFE_OUTPUT_PATH", f"director presentation path was rejected: {exc.code}")
    return path


def _atomic_write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def _write_projection_file(root: Path, relative: Path, data: bytes) -> Path:
    target = _validate_output_path(root, relative)
    if target.exists():
        if not target.is_file() or target.read_bytes() != data:
            _fail("PROJECTION_CONFLICT", "existing LaTeX projection differs from canonical source")
        return target
    _atomic_write_bytes(target, data)
    if target.read_bytes() != data:
        _fail("PROJECTION_WRITE_MISMATCH", "LaTeX projection bytes changed during write")
    return target


def _redact_text(
    value: str,
    *,
    sentinels: Mapping[str, str] | None,
    patterns: Mapping[str, str | Pattern[str]] | None,
) -> str:
    text = value
    for sentinel in (sentinels or {}).values():
        if not isinstance(sentinel, str) or not sentinel:
            continue
        candidates = {sentinel, quote(sentinel, safe=""), quote(sentinel, safe="-._~")}
        for candidate in candidates:
            text = text.replace(candidate, "[REDACTED]")
    for expression in (patterns or {}).values():
        compiled = re.compile(expression) if isinstance(expression, str) else expression
        text = compiled.sub("[REDACTED]", text)
    text = _WINDOWS_ABSOLUTE_RE.sub("[REDACTED_PATH]", text)
    text = _UNC_RE.sub("[REDACTED_PATH]", text)
    return _POSIX_ABSOLUTE_RE.sub("[REDACTED_PATH]", text)


def _final_markdown(
    text: str,
    *,
    sentinels: Mapping[str, str] | None,
    patterns: Mapping[str, str | Pattern[str]] | None,
) -> str:
    rendered = _redact_text(text, sentinels=sentinels, patterns=patterns).rstrip() + "\n"
    try:
        scan_persisted_text("director-review-markdown", rendered, sentinels=sentinels, patterns=patterns)
    except ManuscriptSecretViolation as exc:
        _fail("SECRET_LEAKAGE", "secret material remained after redaction")
    return rendered


def _plain(value: object) -> str:
    text = " ".join(str(value or "").split())
    text = text.replace("\\", "\\\\")
    for character in "[]<>*_#|":
        text = text.replace(character, "\\" + character)
    return text


def _code(value: object) -> str:
    return "`" + " ".join(str(value or "").split()).replace("`", "'") + "`"


def _link(relative: str, label: str) -> str:
    safe = _safe_relative(relative, label="Markdown link")
    href = quote((Path("..") / ".." / Path(safe)).as_posix(), safe="/._-")
    return f"[{_plain(label)}]({href})"


def _evidence_ref(value: object) -> str:
    relative = _maybe_run_reference(value)
    return _link(relative, relative) if relative is not None else _code(value)


def _finding_lines(findings: Sequence[Mapping[str, Any]], *, title: str) -> list[str]:
    lines = [title, ""]
    if not findings:
        return lines + ["- None recorded."]
    for finding in findings:
        refs = ", ".join(_evidence_ref(ref) for ref in finding.get("evidence_refs") or [])
        lines.extend(
            [
                f"### {_code(finding.get('finding_id'))} — {_code(finding.get('code'))}",
                "",
                f"- Class/scope/status: {_code(finding.get('finding_class'))} / {_code(finding.get('scope'))} / {_code(finding.get('status'))}",
                f"- Daily effect: {_code(finding.get('daily_effect'))}; submission effect: {_code(finding.get('submission_effect'))}.",
                f"- Finding: {_plain(finding.get('message'))}",
                f"- Evidence: {refs or 'none recorded'}.",
                f"- Required repair: {_plain(finding.get('repair'))}",
                "",
            ]
        )
    return lines


def _review_finding_lines(findings: Sequence[Mapping[str, Any]]) -> list[str]:
    if not findings:
        return ["- No independent-review findings were recorded."]
    lines: list[str] = []
    for finding in findings:
        refs = ", ".join(_evidence_ref(ref) for ref in finding.get("evidence_refs") or [])
        lines.extend(
            [
                f"### {_code(finding.get('finding_id'))} — {_code(finding.get('severity'))}",
                "",
                f"- Dimension/locus/status: {_code(finding.get('dimension'))} / {_code(finding.get('locus'))} / {_code(finding.get('status'))}.",
                f"- Finding: {_plain(finding.get('description'))}",
                f"- Evidence: {refs or 'none recorded'}.",
                f"- Required fix: {_plain(finding.get('required_fix'))}",
                "",
            ]
        )
    return lines


def _verify_inputs(
    root: Path,
    *,
    manuscript_contract: Mapping[str, Any] | object,
    literature_coverage: Mapping[str, Any] | object,
    integration: Mapping[str, Any] | object,
    quality_report: Mapping[str, Any] | object,
    build_receipt: Mapping[str, Any] | object,
    independent_review: Mapping[str, Any] | object | None,
    independent_review_run_id: str | None,
    verified_review_verdict_sha256: str | None,
    verified_review_receipt_sha256: str | None,
) -> dict[str, Any]:
    contract = _validate_bundle("manuscript_contract", manuscript_contract)
    coverage = _validate_bundle("local_literature_coverage", literature_coverage)
    integration_payload = _validate_bundle("manuscript_integration", integration)
    quality = _validate_bundle("manuscript_quality_report", quality_report)
    build = _validate_bundle("manuscript_build_receipt", build_receipt)

    if contract.get("run_id") != root.name or build.get("run_id") != root.name or quality.get("run_id") != root.name:
        _fail("RUN_ID_MISMATCH", "authoring bundles must belong to the active run")
    if contract.get("manuscript_snapshot_sha256") != canonical_contract_hash(contract):
        _fail("BUNDLE_HASH_MISMATCH", "manuscript contract snapshot hash does not verify")
    _verify_self_hash(integration_payload, "integration_hash", "integration")
    _verify_self_hash(quality, "quality_report_sha256", "quality report")
    _verify_self_hash(build, "build_receipt_sha256", "build receipt")

    snapshot = contract["manuscript_snapshot_sha256"]
    if coverage.get("manuscript_snapshot_sha256") != snapshot or integration_payload.get("manuscript_snapshot_sha256") != snapshot:
        _fail("SNAPSHOT_MISMATCH", "coverage or integration is not bound to the frozen contract")
    if build.get("manuscript_snapshot_sha256") != snapshot:
        _fail("SNAPSHOT_MISMATCH", "build receipt is not bound to the frozen contract")
    quality_build = quality.get("build") or {}
    if (
        quality_build.get("receipt_sha256") != build.get("build_receipt_sha256")
        or quality_build.get("state") != build.get("build_state")
        or quality_build.get("source_sha256") != build.get("source_tree_sha256")
    ):
        _fail("BUILD_TRUTH_MISMATCH", "quality report does not faithfully reference the build receipt")

    state = build.get("build_state")
    if state == "COMPILED":
        pdf = build.get("pdf") or {}
        if quality_build.get("pdf_sha256") != pdf.get("sha256"):
            _fail("BUILD_TRUTH_MISMATCH", "quality report PDF hash differs from build receipt")
        _validate_existing_file(root, str(build.get("log_ref") or ""), expected_sha256=build.get("log_sha256"))
        _validate_existing_file(root, str(build.get("recorder_ref") or ""), expected_sha256=build.get("recorder_sha256"))
        _validate_existing_file(root, str(pdf.get("path") or ""), expected_sha256=pdf.get("sha256"))
    elif state == "TOOLCHAIN_MISSING":
        if build.get("pdf") is not None or quality_build.get("pdf_sha256") is not None:
            _fail("FALSE_PDF_CLAIM", "toolchain-missing state may not expose a PDF")
    elif state == "COMPILE_FAILED":
        _validate_existing_file(root, str(build.get("log_ref") or ""), expected_sha256=build.get("log_sha256"))
    else:
        _fail("BUILD_TRUTH_MISMATCH", "unknown build state")

    verified_review = None
    if independent_review is not None:
        review = _validate_bundle("manuscript_review_verdict", independent_review)
        _verify_self_hash(review, "verdict_sha256", "independent review verdict")
        review_run_id = review.get("review_run_id")
        receipt_sha = (review.get("blind_read_receipt") or {}).get("scheduler_authorization_sha256")
        if (
            not isinstance(independent_review_run_id, str)
            or independent_review_run_id != review_run_id
            or review_run_id == root.name
        ):
            _fail("INDEPENDENT_REVIEW_RUN", "independent review must use a distinct supplied run id")
        if verified_review_verdict_sha256 != review.get("verdict_sha256") or verified_review_receipt_sha256 != receipt_sha:
            _fail("INDEPENDENT_REVIEW_HASH", "independent review verdict/receipt hash was not verified")
        frozen = review.get("frozen_inputs") or {}
        if frozen.get("contract_sha256") != snapshot or frozen.get("manuscript_sha256") != quality.get("manuscript_sha256"):
            _fail("INDEPENDENT_REVIEW_INPUT", "independent review is bound to a different manuscript")
        if state == "COMPILED" and frozen.get("pdf_sha256") != (build.get("pdf") or {}).get("sha256"):
            _fail("INDEPENDENT_REVIEW_INPUT", "independent review is bound to a different PDF")
        verified_review = review

    return {
        "contract": contract,
        "coverage": coverage,
        "integration": integration_payload,
        "quality": quality,
        "build": build,
        "review": verified_review,
    }


def _projection_plan(root: Path, integration: Mapping[str, Any]) -> tuple[list[tuple[str, bytes, str]], dict[str, Any]]:
    source_root = root / "source"
    if not source_root.is_dir():
        _fail("CANONICAL_SOURCE_MISSING", "canonical source tree is missing")
    inventory = integration.get("canonical_file_inventory") or []
    if _hash_inventory(inventory) != integration.get("source_tree_sha256"):
        _fail("CANONICAL_HASH_MISMATCH", "canonical source inventory hash does not verify")
    seen: set[str] = set()
    copies: list[tuple[str, bytes, str]] = []
    rows: list[dict[str, str]] = []
    for item in sorted(inventory, key=lambda row: str(row.get("path") or "")):
        relative = _safe_relative(item.get("path"), label="canonical source path")
        if relative in seen:
            _fail("CANONICAL_HASH_MISMATCH", "canonical source inventory has duplicate paths")
        seen.add(relative)
        source = _validate_existing_file(source_root, relative)
        if _file_hash(source) != item.get("sha256"):
            _fail("CANONICAL_HASH_MISMATCH", "canonical source file hash does not verify")
        data = source.read_bytes()
        projection_ref = (LATEX_PROJECTION_REL / relative).as_posix()
        rows.append(
            {
                "source_ref": f"source/{relative}",
                "projection_ref": projection_ref,
                "sha256": item["sha256"],
                "kind": str(item.get("kind") or "OTHER"),
            }
        )
        copies.append((relative, data, item["sha256"]))
    if not copies:
        _fail("CANONICAL_SOURCE_MISSING", "canonical source inventory is empty")
    manifest: dict[str, Any] = {
        "contract_version": "manuscript-latex-projection/v1",
        "presentation_only": True,
        "canonical_mutable_state": False,
        "canonical_source_ref": "source",
        "canonical_source_tree_sha256": integration["source_tree_sha256"],
        "projection_root": LATEX_PROJECTION_REL.as_posix(),
        "files": rows,
    }
    manifest["manifest_sha256"] = _object_hash(manifest, "manifest_sha256")
    return copies, manifest


def _hash_inventory(inventory: object) -> str:
    return hashlib.sha256(_canonical_bytes(inventory)).hexdigest()


def _project_latex(root: Path, copies: Sequence[tuple[str, bytes, str]], manifest: Mapping[str, Any]) -> Path:
    for relative, data, expected in copies:
        if hashlib.sha256(data).hexdigest() != expected:
            _fail("CANONICAL_HASH_MISMATCH", "canonical source changed before projection")
        _write_projection_file(root, LATEX_PROJECTION_REL / relative, data)
    manifest_data = json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8") + b"\n"
    return _write_projection_file(root, PROJECTION_MANIFEST_REL, manifest_data)


def render_overview(
    manuscript_contract: Mapping[str, Any],
    integration: Mapping[str, Any],
    quality_report: Mapping[str, Any],
    build_receipt: Mapping[str, Any],
    *,
    independent_review: Mapping[str, Any] | None = None,
) -> str:
    brief = manuscript_contract.get("paper_brief") or {}
    build_state = build_receipt.get("build_state")
    quality_build = quality_report.get("build") or {}
    open_findings = [item for item in quality_report.get("findings") or [] if item.get("status") == "OPEN"]
    hard = [
        item for item in open_findings
        if item.get("finding_class") == "HARD" or item.get("daily_effect") == "BLOCK" or item.get("submission_effect") == "BLOCK"
    ]
    caveats = [item for item in open_findings if item.get("daily_effect") in {"CAVEAT", "SUPPLEMENT"}]
    lines = [
        "# Manuscript Overview",
        "",
        "This is a read-only director presentation. The run-owned `source/` tree remains the sole canonical manuscript state.",
        "",
        "## Status Snapshot",
        "",
        f"- daily_state: {_code(quality_report.get('daily_state'))}.",
        f"- Daily rationale: {_plain(quality_report.get('daily_rationale'))}",
        f"- submission_ready: {_code(str(bool(quality_report.get('submission_ready'))).lower())}.",
        f"- Build state: {_code(build_state)}.",
        f"- Canonical source-tree hash: {_code(integration.get('source_tree_sha256'))}.",
        f"- Frozen manuscript-contract hash: {_code(manuscript_contract.get('manuscript_snapshot_sha256'))}.",
        f"- Quality-report hash: {_code(quality_report.get('quality_report_sha256'))}.",
    ]
    if build_state == "COMPILED":
        pdf = build_receipt.get("pdf") or {}
        lines.append(f"- Compiled PDF evidence: {_link(pdf.get('path'), 'compiled PDF')} with hash {_code(pdf.get('sha256'))}.")
    elif build_state == "TOOLCHAIN_MISSING":
        lines.append("- No compiled PDF is available: `TOOLCHAIN_MISSING` is an honest environment state, while readable source and reports remain available.")
    else:
        lines.append("- No compiled PDF is available: the recorded build did not complete successfully.")
    lines.extend(["", "## Blocking Findings", ""])
    if hard:
        for finding in hard:
            lines.append(f"- {_code(finding.get('code'))}: {_plain(finding.get('message'))} (repair: {_plain(finding.get('repair'))}).")
    else:
        lines.append("- No open hard finding is recorded.")
    lines.extend(["", "## Caveats And Supplements", ""])
    if caveats:
        for finding in caveats:
            lines.append(f"- {_code(finding.get('code'))}: {_plain(finding.get('message'))}.")
    else:
        lines.append("- No open caveat or supplement finding is recorded.")
    lines.extend([
        "",
        "## Manuscript And Evidence Links",
        "",
        f"- Canonical source: {_link('source/main.tex', 'main.tex')} (hash bound by {_code(integration.get('source_tree_sha256'))}).",
        f"- Read-only LaTeX projection: [projection manifest](latex/projection-manifest.json).",
        f"- {_link(quality_build.get('receipt_ref'), 'build receipt evidence')} (receipt hash {_code(quality_build.get('receipt_sha256'))}).",
        "- [Local-literature coverage](local-literature-coverage.md).",
        "- [Authoring plan](authoring-plan.md).",
        "- [Quality report](quality-report.md).",
        "- [Reviewer report](reviewer-report.md).",
        "- [Submission checklist](submission-checklist.md).",
        "",
        "## Review Separation",
        "",
        "- Internal authoring audits are generation-side evidence and are not independent manuscript review evidence.",
    ])
    if independent_review is None:
        lines.append("- No verified independent manuscript review was supplied.")
    else:
        lines.append(
            f"- Independent review run {_code(independent_review.get('review_run_id'))}: disposition {_code(independent_review.get('disposition'))}, verdict hash {_code(independent_review.get('verdict_sha256'))}."
        )
    lines.extend([
        "",
        "## Delivery Boundary",
        "",
        "- This packet does not submit, publish, promote, or alter the canonical manuscript.",
        "- JSON bundles, source hashes, build receipts, logs, and PDF evidence remain the machine evidence referenced by this Markdown entry point.",
    ])
    return "\n".join(lines)


def render_coverage_report(literature_coverage: Mapping[str, Any]) -> str:
    lines = [
        "# Local Literature Coverage",
        "",
        f"- Coverage id: {_code(literature_coverage.get('coverage_id'))}.",
        f"- Frozen manuscript-contract hash: {_code(literature_coverage.get('manuscript_snapshot_sha256'))}.",
        f"- Assessed at: {_code(literature_coverage.get('assessed_at'))}.",
        "- This report records bounded local evidence first; retrieved metadata is not silently promoted into manuscript support.",
        "",
        "## Coverage Axes",
        "",
    ]
    for axis, row in sorted((literature_coverage.get("axes") or {}).items()):
        lines.extend([
            f"## {_plain(str(axis).replace('_', ' '))}",
            "",
            f"- Status: {_code(row.get('status'))}.",
            f"- Criterion: {_plain(row.get('criterion'))}",
            f"- Local references: {', '.join(_evidence_ref(ref) for ref in row.get('local_source_refs') or []) or 'none recorded'}.",
            f"- Rationale: {_plain(row.get('rationale'))}",
        ])
        authorization = row.get("query_authorization")
        if isinstance(authorization, Mapping):
            lines.extend([
                f"- Deficit-search outcome: {_code(authorization.get('outcome'))}.",
                f"- Terminal trace hash: {_code(authorization.get('terminal_trace_sha256'))}.",
                "- Metadata rows remain follow-up references, not manuscript-ready entailed evidence.",
            ])
        lines.append("")
    lines.extend(["## Local Corpus References", ""])
    for row in literature_coverage.get("local_corpus_refs") or []:
        lines.append(f"- {_code(row.get('ref'))} — {_code(row.get('source_kind'))}; hash {_code(row.get('sha256'))}.")
    return "\n".join(lines)


def render_authoring_plan(manuscript_contract: Mapping[str, Any]) -> str:
    brief = manuscript_contract.get("paper_brief") or {}
    venue = manuscript_contract.get("venue_profile") or {}
    lines = [
        "# Frozen Authoring Plan",
        "",
        f"- Working title: {_plain(brief.get('working_title'))}",
        f"- Paper type: {_code(manuscript_contract.get('paper_type'))}.",
        f"- Venue profile: {_code(venue.get('venue_id'))}; PDF required: {_code(str(bool(venue.get('requires_pdf'))).lower())}.",
        f"- North star: {_plain(manuscript_contract.get('north_star'))}",
        f"- Frozen contract hash: {_code(manuscript_contract.get('manuscript_snapshot_sha256'))}.",
        "",
        "## Paper Brief",
        "",
        f"- Research question: {_plain(brief.get('research_question'))}",
        f"- Contribution: {_plain(brief.get('contribution_statement'))}",
        "",
        "## Required Sections",
        "",
        "| Section | Required | Dependencies | Purpose |",
        "|---|---:|---|---|",
    ]
    for section in manuscript_contract.get("outline") or []:
        lines.append(
            f"| {_code(section.get('section_id'))} | {'yes' if section.get('required') else 'no'} | {_plain(', '.join(section.get('depends_on') or []) or 'none')} | {_plain(section.get('purpose'))} |"
        )
    lines.extend(["", "## Claim Ledger", ""])
    for claim in manuscript_contract.get("claim_ledger") or []:
        refs = ", ".join(_evidence_ref(ref) for ref in claim.get("evidence_refs") or [])
        lines.append(f"- {_code(claim.get('claim_id'))} ({_code(claim.get('importance'))}): {_plain(claim.get('text'))} (evidence: {refs or 'none recorded'}).")
    lines.extend(["", "## Authorized Dependency Slices", ""])
    for row in manuscript_contract.get("dependency_slices") or []:
        lines.append(f"- {_code(row.get('slice_id'))} for {_code(row.get('worker_role'))}; hash {_code(row.get('slice_sha256'))}.")
    lines.extend(["", "## Asset Plan", ""])
    for asset in manuscript_contract.get("asset_plan") or []:
        lines.append(f"- {_code(asset.get('asset_id'))}: {_code(asset.get('kind'))} {_code(asset.get('label'))} at {_code(asset.get('planned_path'))}.")
    return "\n".join(lines)


def render_quality_report(quality_report: Mapping[str, Any], build_receipt: Mapping[str, Any]) -> str:
    blockers = quality_report.get("submission_blockers") or []
    lines = [
        "# Deterministic Quality Report",
        "",
        f"- Daily delivery state: {_code(quality_report.get('daily_state'))}.",
        f"- Daily rationale: {_plain(quality_report.get('daily_rationale'))}",
        f"- submission_ready: {_code(str(bool(quality_report.get('submission_ready'))).lower())}.",
        f"- Build state (reported): {_code(build_receipt.get('build_state'))}.",
        f"- Quality-report hash: {_code(quality_report.get('quality_report_sha256'))}.",
        "",
    ]
    lines.extend(_finding_lines(quality_report.get("findings") or [], title="## Findings"))
    lines.extend(["", "## Submission Blockers", ""])
    if blockers:
        for blocker in blockers:
            lines.append(f"- {_code(blocker.get('code'))} from {_code(blocker.get('source_ref'))}: {_plain(blocker.get('rationale'))}")
    else:
        lines.append("- None recorded by the deterministic quality report.")
    lines.extend(["", "## Build Evidence", ""])
    lines.append(f"- Receipt hash: {_code(build_receipt.get('build_receipt_sha256'))}.")
    if build_receipt.get("build_state") == "COMPILED":
        pdf = build_receipt.get("pdf") or {}
        lines.append(f"- PDF: {_link(pdf.get('path'), 'compiled PDF')}; hash {_code(pdf.get('sha256'))}.")
        lines.append(f"- Log: {_link(build_receipt.get('log_ref'), 'build log')}; hash {_code(build_receipt.get('log_sha256'))}.")
    elif build_receipt.get("build_state") == "TOOLCHAIN_MISSING":
        failure = build_receipt.get("failure") or {}
        lines.append(f"- No compiled PDF is available. Recorded cause: {_code(failure.get('code'))} — {_plain(failure.get('safe_message'))}")
    else:
        failure = build_receipt.get("failure") or {}
        lines.append(f"- Compilation failed; no PDF is claimed. Recorded cause: {_code(failure.get('code'))} — {_plain(failure.get('safe_message'))}")
    return "\n".join(lines)


def render_reviewer_report(
    authoring_run_id: str,
    quality_report: Mapping[str, Any],
    *,
    independent_review: Mapping[str, Any] | None = None,
) -> str:
    lines = [
        "# Manuscript Reviewer Report",
        "",
        "## Internal Authoring Audit (Not Independent Review)",
        "",
        f"- Authoring run: {_code(authoring_run_id)}.",
        f"- Internal quality-report hash: {_code(quality_report.get('quality_report_sha256'))}.",
        f"- Internal daily state: {_code(quality_report.get('daily_state'))}; submission_ready: {_code(str(bool(quality_report.get('submission_ready'))).lower())}.",
        "- This authoring self-audit is not independent manuscript review evidence and cannot upgrade submission readiness.",
        "",
        "## Independent Review",
        "",
    ]
    if independent_review is None:
        lines.append("- No verified independent manuscript review was supplied.")
        return "\n".join(lines)
    blind = independent_review.get("blind_read_receipt") or {}
    lines.extend([
        f"- Independent review run: {_code(independent_review.get('review_run_id'))}.",
        f"- Reviewer identity: {_code((independent_review.get('reviewer_identity') or {}).get('reviewer_id'))} ({_code((independent_review.get('reviewer_identity') or {}).get('role'))}).",
        f"- Independent review disposition: {_code(independent_review.get('disposition'))}.",
        f"- Verdict hash: {_code(independent_review.get('verdict_sha256'))}.",
        f"- Receipt hash: {_code(blind.get('scheduler_authorization_sha256'))}.",
        f"- Blind-scope hash: {_code(blind.get('blind_scope_sha256'))}.",
        "",
        "## Independent Review Findings",
        "",
    ])
    lines.extend(_review_finding_lines(independent_review.get("findings") or []))
    return "\n".join(lines)


def render_submission_checklist(
    manuscript_contract: Mapping[str, Any],
    quality_report: Mapping[str, Any],
    build_receipt: Mapping[str, Any],
    *,
    independent_review: Mapping[str, Any] | None = None,
) -> str:
    venue = manuscript_contract.get("venue_profile") or {}
    lines = [
        "# Submission Checklist",
        "",
        "This checklist reports frozen evidence. It does not submit, promise acceptance, or upgrade readiness.",
        "",
        "| Check | Reported state | Evidence |",
        "|---|---|---|",
        f"| Daily delivery | {_code(quality_report.get('daily_state'))} | quality report {_code(quality_report.get('quality_report_sha256'))} |",
        f"| Submission readiness | {_code(str(bool(quality_report.get('submission_ready'))).lower())} | deterministic blockers below |",
        f"| Venue PDF requirement | {_code(str(bool(venue.get('requires_pdf'))).lower())} | {_code(venue.get('venue_id'))} profile |",
        f"| Build state | {_code(build_receipt.get('build_state'))} | receipt {_code(build_receipt.get('build_receipt_sha256'))} |",
        f"| Canonical source | available | {_link('source/main.tex', 'main.tex')} |",
        f"| Independent review | {_code((independent_review or {}).get('disposition', 'NOT_SUPPLIED'))} | {'verified verdict supplied' if independent_review else 'not supplied'} |",
        "",
        "## Open Submission Blockers",
        "",
    ]
    blockers = quality_report.get("submission_blockers") or []
    if blockers:
        for blocker in blockers:
            lines.append(f"- {_code(blocker.get('code'))}: {_plain(blocker.get('rationale'))} (source: {_code(blocker.get('source_ref'))}).")
    else:
        lines.append("- None reported. This does not independently authorize submission.")
    lines.extend(["", "## Human Boundary", "", "- The director retains every submission, publication, and promotion decision."])
    return "\n".join(lines)


def write_manuscript_report_set(
    run_dir: str | os.PathLike[str],
    *,
    manuscript_contract: Mapping[str, Any],
    literature_coverage: Mapping[str, Any],
    integration: Mapping[str, Any],
    quality_report: Mapping[str, Any],
    build_receipt: Mapping[str, Any],
    independent_review: Mapping[str, Any] | None = None,
    independent_review_run_id: str | None = None,
    verified_review_verdict_sha256: str | None = None,
    verified_review_receipt_sha256: str | None = None,
    secret_sentinels: Mapping[str, str] | None = None,
    secret_patterns: Mapping[str, str | Pattern[str]] | None = None,
) -> dict[str, Path]:
    """Write the complete director manuscript report set from validated bundles.

    ``source/`` is verified and projected byte-for-byte; it is never written by
    this renderer.  All status and readiness words are copied from validated
    report/receipt data rather than re-derived here.
    """

    root = Path(run_dir).absolute()
    if not root.is_dir():
        _fail("RUN_ROOT_MISSING", "active manuscript run directory is missing")
    inputs = _verify_inputs(
        root,
        manuscript_contract=manuscript_contract,
        literature_coverage=literature_coverage,
        integration=integration,
        quality_report=quality_report,
        build_receipt=build_receipt,
        independent_review=independent_review,
        independent_review_run_id=independent_review_run_id,
        verified_review_verdict_sha256=verified_review_verdict_sha256,
        verified_review_receipt_sha256=verified_review_receipt_sha256,
    )
    copies, manifest = _projection_plan(root, inputs["integration"])

    documents: list[tuple[str, Path, str]] = [
        ("overview", OVERVIEW_REL, render_overview(inputs["contract"], inputs["integration"], inputs["quality"], inputs["build"], independent_review=inputs["review"])),
        ("coverage", COVERAGE_REL, render_coverage_report(inputs["coverage"])),
        ("authoring_plan", AUTHORING_PLAN_REL, render_authoring_plan(inputs["contract"])),
        ("quality_report", QUALITY_REPORT_REL, render_quality_report(inputs["quality"], inputs["build"])),
        ("reviewer_report", REVIEWER_REPORT_REL, render_reviewer_report(root.name, inputs["quality"], independent_review=inputs["review"])),
        ("submission_checklist", SUBMISSION_CHECKLIST_REL, render_submission_checklist(inputs["contract"], inputs["quality"], inputs["build"], independent_review=inputs["review"])),
    ]
    rendered_documents = [
        (name, relative, _final_markdown(text, sentinels=secret_sentinels, patterns=secret_patterns))
        for name, relative, text in documents
    ]

    # Validate all source bytes and report text before publishing any derived file.
    for _relative, data, _sha in copies:
        try:
            decoded = data.decode("utf-8")
        except UnicodeDecodeError:
            decoded = ""
        if decoded:
            try:
                scan_persisted_text("latex-projection", decoded, sentinels=secret_sentinels, patterns=secret_patterns)
            except ManuscriptSecretViolation:
                _fail("SECRET_LEAKAGE", "canonical source cannot be projected with secret material")
    manifest_text = _redact_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        sentinels=secret_sentinels,
        patterns=secret_patterns,
    )
    if manifest_text != json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n":
        _fail("SECRET_LEAKAGE", "projection manifest unexpectedly required redaction")

    outputs: dict[str, Path] = {}
    for name, relative, text in rendered_documents:
        target = _validate_output_path(root, relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(target, text)
        outputs[name] = target
    outputs["projection_manifest"] = _project_latex(root, copies, manifest)
    return outputs


def write_manuscript_delivery(*args: Any, **kwargs: Any) -> dict[str, Path]:
    """Compatibility alias for operated recipes that use the delivery name."""

    return write_manuscript_report_set(*args, **kwargs)


def write_manuscript_markdown(*args: Any, **kwargs: Any) -> dict[str, Path]:
    """Compatibility alias for callers that use the mode-specific Markdown name."""

    return write_manuscript_report_set(*args, **kwargs)


__all__ = [
    "AUTHORING_PLAN_REL",
    "COVERAGE_REL",
    "LATEX_PROJECTION_REL",
    "MANUSCRIPT_DIR_REL",
    "ManuscriptRenderError",
    "OVERVIEW_REL",
    "PROJECTION_MANIFEST_REL",
    "QUALITY_REPORT_REL",
    "REQUIRED_REPORT_FILES",
    "REVIEWER_REPORT_REL",
    "SUBMISSION_CHECKLIST_REL",
    "render_authoring_plan",
    "render_coverage_report",
    "render_overview",
    "render_quality_report",
    "render_reviewer_report",
    "render_submission_checklist",
    "write_manuscript_delivery",
    "write_manuscript_markdown",
    "write_manuscript_report_set",
]
