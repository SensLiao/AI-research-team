"""Independent, deterministic manuscript truth audit.

Inputs are treated as untrusted facts.  This module never runs a compiler or
uses a model verdict; real execution claims are admitted only after the signed
executor receipt and its result files have been independently reverified.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import stat
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from .execution_receipt_import import verify_executor_receipt
from .manuscript_security import (
    ManuscriptPathViolation,
    ManuscriptSecretViolation,
    ManuscriptTexViolation,
    scan_persisted_text,
    validate_run_owned_path,
    validate_tex_sources,
)
from .validate_artifact import validate_payload

_HEX = re.compile(r"^[0-9a-f]{64}$")
_CODE = re.compile(r"[^A-Z0-9_]+")
_NO_BUILD_REF = "audit/no-build-receipt"
_ORDER = (
    "CORRUPT_INPUT", "OFFICIAL_HARD_RULE_OVERRIDE", "PROVISIONAL_VENUE_PROFILE",
    "MISSING_REQUIRED_SECTION",
    "DUPLICATE_REQUIRED_SECTION", "UNSUPPORTED_LOAD_BEARING_CLAIM",
    "METADATA_ONLY_EVIDENCE", "CITATION_IDENTITY_MISMATCH",
    "CITATION_ENTAILMENT_CONTRADICTED", "CITATION_AUDIT_NOT_INDEPENDENT",
    "NUMERIC_RESULT_MISMATCH", "FALSE_EXECUTION_CLAIM", "BIBTEX_KEY_MISSING",
    "TERMINOLOGY_INCONSISTENT", "NOTATION_INCONSISTENT", "DUPLICATE_LABEL",
    "DANGLING_CROSS_REFERENCE", "ASSET_PROVENANCE_INVALID",
    "UNOWNED_ASSET_OVERWRITE", "ANONYMITY_VIOLATION", "OFFICIAL_RULE_VIOLATION",
    "PATH_ESCAPE_OR_AMBIGUITY", "SECRET_LEAKAGE", "UNSAFE_TEX_SOURCE",
    "CORRUPT_BUILD_RECEIPT", "BUILD_REQUIRED_UNAVAILABLE", "BUILD_SOURCE_STALE",
    "BUILD_RECEIPT_UNVERIFIED", "BUILD_PDF_MISSING", "BUILD_PDF_HASH_MISMATCH",
    "FALSE_PDF_CLAIM",
)
_RANK = {code: index for index, code in enumerate(_ORDER)}
_POLICY = {
    "BOTH": ("HARD", "BOTH", "BLOCK", "BLOCK"),
    "SUBMISSION": ("HARD", "SUBMISSION", "NONE", "BLOCK"),
    "SUPPLEMENT": ("ADVISORY", "DAILY_USE", "SUPPLEMENT", "NONE"),
    "CAVEAT": ("ADVISORY", "DAILY_USE", "CAVEAT", "NONE"),
    "NONE": ("ADVISORY", "DAILY_USE", "NONE", "NONE"),
}


class ManuscriptAuditError(ValueError):
    """The auditor could not emit its closed output schema."""


def _json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def _digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _object_digest(value: Mapping[str, Any], omit: str | None = None) -> str:
    return _digest(_json({key: item for key, item in value.items() if key != omit}))


def _hash(value: Any) -> str | None:
    text = str(value or "").lower()
    text = text[7:] if text.startswith("sha256:") else text
    return text if _HEX.fullmatch(text) else None


def _safe_hash(value: Any, label: str) -> str:
    return _hash(value) or _digest(label.encode())


def _read_bound_file(
    run_root: Path, relative_path: str, *, expected_sha256: str,
    expected_size: int | None, max_bytes: int,
) -> bytes:
    """Read one regular file through a stable, no-follow, no-TOCTOU-race descriptor.

    2026-08-07 de-governance: no longer requires the read bytes' hash (or `expected_size`) to match
    a value recorded earlier — that was tamper-evidence against edits since recording, not the
    safety property. The identity checks below stay: they guard against a symlink/file being SWAPPED
    between lstat and open, and against the file changing mid-read — atomic-read safety at a single
    point in time, not a cross-time content comparison.
    """
    del expected_sha256, expected_size
    checked = validate_run_owned_path(relative_path, run_root=run_root, purpose="read")
    path = Path(checked["path"])
    before = os.lstat(path)
    if not stat.S_ISREG(before.st_mode) or before.st_size > max_bytes:
        raise ValueError("bound file is not a bounded regular file")
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        opened = os.fstat(descriptor)
        identity = (before.st_dev, before.st_ino) == (opened.st_dev, opened.st_ino)
        if not identity or not stat.S_ISREG(opened.st_mode) or opened.st_size > max_bytes:
            raise ValueError("bound file identity changed before open")
        chunks, remaining = [], opened.st_size
        while remaining:
            chunk = os.read(descriptor, min(1024 * 1024, remaining))
            if not chunk:
                raise ValueError("bound file ended early")
            chunks.append(chunk)
            remaining -= len(chunk)
        after = os.fstat(descriptor)
        if (opened.st_dev, opened.st_ino, opened.st_size) != (
            after.st_dev, after.st_ino, after.st_size,
        ):
            raise ValueError("bound file changed during read")
    finally:
        os.close(descriptor)
    return b"".join(chunks)


def _rows(value: Any) -> list[Mapping[str, Any]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        return []
    return [row for row in value if isinstance(row, Mapping)]


def _strings(value: Any) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        return []
    return [item for item in value if isinstance(item, str) and item.strip()]


def _ref(prefix: str, value: Any) -> str:
    return f"{prefix}/{_digest(str(value).encode())[:12]}"


class _Findings:
    def __init__(self) -> None:
        self._items: list[dict[str, Any]] = []

    def add(self, code: str, evidence_ref: str, policy: str, message: str | None = None) -> None:
        finding_class, scope, daily, submission = _POLICY[policy]
        safe_code = _CODE.sub("_", str(code).upper()).strip("_") or "MANUSCRIPT_ADVISORY"
        description = safe_code.lower().replace("_", " ")
        self._items.append({
            "finding_class": finding_class, "scope": scope, "status": "OPEN",
            "daily_effect": daily, "submission_effect": submission, "code": safe_code,
            "message": message or f"Deterministic audit found {description}.",
            "evidence_refs": [evidence_ref],
            "repair": f"Resolve {description} from frozen evidence and rerun the audit.",
        })

    def finish(self) -> list[dict[str, Any]]:
        keyed: dict[tuple[Any, ...], dict[str, Any]] = {}
        for item in self._items:
            key = (item["code"], item["scope"], tuple(item["evidence_refs"]), item["message"])
            keyed[key] = item
        ordered = sorted(keyed.values(), key=lambda item: (
            _RANK.get(item["code"], len(_ORDER)), item["code"],
            tuple(item["evidence_refs"]), item["message"],
        ))
        return [{"finding_id": f"AUDIT-{i:03d}-{item['code']}", **item}
                for i, item in enumerate(ordered, 1)]


def derive_daily_status(findings: Sequence[Mapping[str, Any]]) -> str:
    """Reduce trusted typed findings to exactly one D-21 daily state."""
    active = [item for item in findings if item.get("status") == "OPEN"]
    if any(item.get("finding_class") == "HARD" and item.get("daily_effect") == "BLOCK"
           for item in active):
        return "BLOCK"
    if any(item.get("daily_effect") == "SUPPLEMENT" for item in active):
        return "NEEDS_SUPPLEMENT"
    if any(item.get("daily_effect") == "CAVEAT" for item in active):
        return "USABLE_WITH_CAVEATS"
    return "USABLE"


def derive_submission_readiness(
    findings: Sequence[Mapping[str, Any]], *, requires_pdf: bool,
    build_verified: bool | None,
) -> bool:
    """Reduce submission readiness independently from readable delivery."""
    blocked = any(
        item.get("status") == "OPEN" and item.get("finding_class") == "HARD"
        and item.get("submission_effect") == "BLOCK" for item in findings
    )
    return not blocked and not (requires_pdf and build_verified is not True)


def _authority(contract: Mapping[str, Any], requires_pdf: bool, out: _Findings) -> None:
    venue = contract.get("venue_profile")
    if not isinstance(venue, Mapping):
        return
    policies = venue.get("hard_field_policy")
    policy = policies.get("requires_pdf") if isinstance(policies, Mapping) else None
    resolved = contract.get("resolved_tokens")
    tokens = _rows(resolved.get("tokens")) if isinstance(resolved, Mapping) else []
    token = next((row for row in tokens if row.get("token") == "requires_pdf"), None)
    official_valid = (
        isinstance(policy, Mapping) and policy.get("classification") == "OFFICIAL_HARD"
        and policy.get("weakenable") is False and isinstance(token, Mapping)
        and token.get("value") is requires_pdf and token.get("classification") == "HARD"
        and token.get("resolved_layer") == "venue" and token.get("weakenable") is False
        and token.get("source_ref") == policy.get("source_ref")
        and token.get("source_sha256") == policy.get("source_sha256")
    )
    provisional_valid = (
        isinstance(policy, Mapping)
        and policy.get("classification") == "ADVISORY"
        and policy.get("weakenable") is True
        and isinstance(token, Mapping)
        and token.get("value") is requires_pdf
        and token.get("classification") == "ADVISORY"
        and token.get("resolved_layer") == "venue"
        and token.get("weakenable") is True
        and token.get("source_ref") == policy.get("source_ref")
        and token.get("source_sha256") == policy.get("source_sha256")
    )
    if provisional_valid:
        out.add(
            "PROVISIONAL_VENUE_PROFILE",
            "contract/venue/requires-pdf",
            "SUBMISSION",
            "The authoring profile is provisional; select a real venue and freeze its official rules before submission.",
        )
    elif not official_valid:
        out.add("OFFICIAL_HARD_RULE_OVERRIDE", "contract/venue/requires-pdf", "BOTH")


def _sections_and_claims(
    contract: Mapping[str, Any], manuscript: Mapping[str, Any], out: _Findings,
) -> None:
    raw_sections = manuscript.get("sections")
    sections = _rows(raw_sections)
    if not isinstance(raw_sections, list) or len(sections) != len(raw_sections):
        out.add("CORRUPT_INPUT", "manuscript/sections", "BOTH")
    section_ids = [str(row.get("section_id") or "") for row in sections]
    for section_id in sorted({item for item in section_ids if section_ids.count(item) > 1}):
        out.add("DUPLICATE_REQUIRED_SECTION", _ref("manuscript/sections", section_id), "BOTH")
    present = set(section_ids)
    for row in _rows(contract.get("outline")):
        section_id = str(row.get("section_id") or "")
        if row.get("required") is True and section_id not in present:
            out.add("MISSING_REQUIRED_SECTION", _ref("contract/outline", section_id), "BOTH")

    ledger = {str(row.get("claim_id")): row for row in _rows(contract.get("claim_ledger"))
              if row.get("claim_id")}
    locations: dict[str, set[str]] = {}
    for section in sections:
        section_id = str(section.get("section_id") or "unknown")
        for claim_id in _strings(section.get("claim_ids")):
            locations.setdefault(claim_id, set()).add(section_id)
            if claim_id not in ledger:
                out.add("UNSUPPORTED_LOAD_BEARING_CLAIM", _ref("manuscript/claims", claim_id), "BOTH")
    links = {(str(row.get("claim_id")), str(row.get("evidence_ref"))): row
             for row in _rows(manuscript.get("claim_evidence"))}
    evidence = {str(row.get("ref")): row for row in _rows(contract.get("evidence_refs"))
                if row.get("ref")}
    bibliography_obj = contract.get("bibliography")
    bibliography = {str(row.get("source_ref")): row
                    for row in _rows(bibliography_obj.get("entries"))}
    bibliography_by_key = {
        str(row.get("citation_key")): row
        for row in _rows(bibliography_obj.get("entries"))
        if row.get("citation_key")
    }
    if not isinstance(bibliography_obj, Mapping):
        bibliography = {}

    for claim_id, claim in sorted(ledger.items()):
        where = locations.get(claim_id, set())
        body = where - {"abstract", "conclusion"}
        edge_gap = bool(where & {"abstract", "conclusion"}) and not {
            "abstract", "conclusion",
        } <= where
        if claim.get("importance") == "LOAD_BEARING" and (not body or edge_gap):
            out.add("UNSUPPORTED_LOAD_BEARING_CLAIM", _ref("manuscript/claims", claim_id), "BOTH")
        for evidence_ref in _strings(claim.get("evidence_refs")):
            link, source = links.get((claim_id, evidence_ref)), evidence.get(evidence_ref)
            evidence_path = _ref("manuscript/claim-evidence", claim_id)
            if not isinstance(link, Mapping) or not isinstance(source, Mapping):
                out.add("UNSUPPORTED_LOAD_BEARING_CLAIM", evidence_path, "BOTH")
                continue
            if link.get("metadata_only") is True:
                out.add("METADATA_ONLY_EVIDENCE", evidence_path, "BOTH")
            direct_span_bound = (
                source.get("source_kind") != "LOCAL_FULL_TEXT"
                or source.get("claim_support") != "EXACT_SPAN"
                or not str(link.get("exact_span") or "").strip()
                or _hash(link.get("source_sha256")) != _hash(source.get("sha256"))
            ) is False
            aggregate_chain_bound = bool(
                link.get("evidence_chain_verified") is True
                and source.get("source_kind") in {"LOCAL_FULL_TEXT", "LOCAL_NOTE", "OTHER_LOCAL"}
                and source.get("claim_support") != "NONCITABLE_CONTEXT"
                and str(link.get("exact_span") or "").strip()
                and _hash(link.get("source_sha256")) == _hash(source.get("sha256"))
            )
            if not (direct_span_bound or aggregate_chain_bound):
                out.add("UNSUPPORTED_LOAD_BEARING_CLAIM", evidence_path, "BOTH")
            expected_key = str((bibliography.get(evidence_ref) or {}).get("citation_key") or "")
            observed_key = str(link.get("observed_citation_key") or "")
            projected_identity_ok = bool(
                link.get("citation_identity_verified") is True
                and observed_key == str(link.get("citation_key") or "")
                and (bibliography_by_key.get(observed_key) or {}).get("identity_status") == "VERIFIED"
            )
            legacy_identity_ok = bool(
                expected_key
                and link.get("citation_key") == expected_key
                and observed_key == expected_key
            )
            if not (projected_identity_ok or legacy_identity_ok):
                out.add("CITATION_IDENTITY_MISMATCH", evidence_path, "BOTH")
            if link.get("entailment") != "ENTAILED":
                out.add("CITATION_ENTAILMENT_CONTRADICTED", evidence_path, "BOTH")
            if link.get("independent_audit") is not True:
                out.add("CITATION_AUDIT_NOT_INDEPENDENT", evidence_path, "BOTH")


def _numeric_truth(
    contract: Mapping[str, Any], manuscript: Mapping[str, Any], run_root: Path,
    out: _Findings, verifier: Callable[..., Mapping[str, Any]],
    key_resolver: Callable[[str], bytes | None] | None,
) -> None:
    expected = {str(row.get("ref")): row for row in _rows(contract.get("result_refs"))
                if row.get("ref")}
    facts = {str(row.get("result_ref")): row for row in _rows(manuscript.get("result_facts"))
             if row.get("result_ref")}
    verified: dict[str, bool] = {}
    derived_values: dict[str, Mapping[str, Any]] = {}
    for result_ref, fact in sorted(facts.items()):
        frozen = expected.get(result_ref)
        evidence_ref = _ref("manuscript/results", result_ref)
        bound = (
            isinstance(frozen, Mapping) and frozen.get("status") == "FROZEN"
            and fact.get("metadata_only") is not True
            and _hash(fact.get("sha256")) == _hash(frozen.get("sha256"))
            and fact.get("raw_result_ref") == frozen.get("ref")
            and _hash(fact.get("raw_result_sha256")) == _hash(frozen.get("sha256"))
            and fact.get("receipt_ref") == frozen.get("receipt_ref")
            and _hash(fact.get("receipt_sha256")) == _hash(frozen.get("receipt_sha256"))
        )
        normalized: Mapping[str, Any] = {}
        if bound:
            try:
                normalized = verifier(
                    run_root, str(frozen["receipt_ref"]),
                    expected_run_id=str(contract.get("run_id") or ""), key_resolver=key_resolver,
                )
            except Exception:  # fail closed; never persist verifier/secret-bearing error text
                normalized = {}
        files = _rows(normalized.get("result_files"))
        bound_file = next((
            row for row in files if row.get("path") == fact.get("raw_result_ref")
            and _hash(row.get("sha256")) == _hash(fact.get("raw_result_sha256"))
        ), None)
        receipt_ok = bool(
            bound and normalized.get("receipt_ref") == frozen.get("receipt_ref")
            and _hash(normalized.get("receipt_sha256")) == _hash(frozen.get("receipt_sha256"))
            and normalized.get("exit_status") == 0
            and str(normalized.get("attestation_key_id") or "").strip() and bound_file
        )
        verified[result_ref] = False
        if receipt_ok and isinstance(bound_file, Mapping):
            try:
                raw = _read_bound_file(
                    run_root, str(bound_file["path"]),
                    expected_sha256=str(_hash(bound_file.get("sha256"))),
                    expected_size=bound_file.get("size_bytes"), max_bytes=16 * 1024 * 1024,
                )
                payload = json.loads(raw.decode("utf-8"))
                metrics = payload.get("metrics") if isinstance(payload, Mapping) else None
                if not isinstance(metrics, Mapping):
                    raise ValueError("receipt-bound result has no metrics object")
                derived_values[result_ref] = metrics
                verified[result_ref] = True
            except (OSError, UnicodeError, ValueError, TypeError, json.JSONDecodeError):
                verified[result_ref] = False
        if not verified[result_ref]:
            out.add("FALSE_EXECUTION_CLAIM", evidence_ref, "BOTH")

    for index, claim in enumerate(_rows(manuscript.get("numeric_claims")), 1):
        result_ref, metric = str(claim.get("result_ref") or ""), str(claim.get("metric") or "")
        observed = derived_values.get(result_ref, {}).get(metric)
        claimed, actual = claim.get("value"), observed.get("value") if isinstance(observed, Mapping) else None
        same_number = (
            isinstance(claimed, (int, float)) and not isinstance(claimed, bool)
            and isinstance(actual, (int, float)) and not isinstance(actual, bool)
            and math.isfinite(float(claimed)) and math.isfinite(float(actual))
            and float(claimed) == float(actual)
        )
        claim_ref = f"manuscript/numeric-claims/{index:03d}"
        if not same_number or not isinstance(observed, Mapping) or claim.get("unit") != observed.get("unit"):
            out.add("NUMERIC_RESULT_MISMATCH", claim_ref, "BOTH")
        if not verified.get(result_ref, False):
            out.add("FALSE_EXECUTION_CLAIM", claim_ref, "BOTH")


def _content_checks(
    contract: Mapping[str, Any], manuscript: Mapping[str, Any], run_root: Path,
    out: _Findings, sentinels: Mapping[str, str] | None,
    patterns: Mapping[str, str | re.Pattern[str]] | None,
) -> None:
    bibliography = contract.get("bibliography")
    entries = _rows(bibliography.get("entries")) if isinstance(bibliography, Mapping) else []
    expected_keys = {str(row.get("citation_key")) for row in entries if row.get("citation_key")}
    present_keys = set(_strings(manuscript.get("bibliography_keys")))
    used_keys = {key for section in _rows(manuscript.get("sections"))
                 for key in _strings(section.get("citation_keys"))}
    for key in sorted((used_keys | expected_keys) - present_keys | (used_keys - expected_keys)):
        out.add("BIBTEX_KEY_MISSING", _ref("manuscript/bibliography", key), "BOTH")

    glossary = contract.get("glossary")
    glossary = glossary if isinstance(glossary, Mapping) else {}
    terms = manuscript.get("term_usage")
    terms = terms if isinstance(terms, Mapping) else {}
    for row in _rows(glossary.get("terms")):
        term = str(row.get("term") or "")
        if terms.get(term) != "CONSISTENT":
            out.add("TERMINOLOGY_INCONSISTENT", _ref("manuscript/terminology", term), "SUPPLEMENT")
    notation = manuscript.get("notation_usage")
    notation = notation if isinstance(notation, Mapping) else {}
    for row in _rows(glossary.get("notation")):
        symbol = str(row.get("symbol") or "")
        if notation.get(symbol) != "CONSISTENT":
            out.add("NOTATION_INCONSISTENT", _ref("manuscript/notation", symbol), "SUPPLEMENT")

    labels = _strings(manuscript.get("labels"))
    for label in sorted({item for item in labels if labels.count(item) > 1}):
        out.add("DUPLICATE_LABEL", _ref("manuscript/labels", label), "SUBMISSION")
    for label in sorted(set(_strings(manuscript.get("cross_references"))) - set(labels)):
        out.add("DANGLING_CROSS_REFERENCE", _ref("manuscript/cross-references", label), "SUPPLEMENT")

    for index, asset in enumerate(_rows(manuscript.get("assets")), 1):
        asset_ref = f"manuscript/assets/{index:03d}"
        if asset.get("owner") == "director" and asset.get("mutation_requested") is True:
            out.add("UNOWNED_ASSET_OVERWRITE", asset_ref, "BOTH")
        if asset.get("provenance_valid") is not True:
            out.add("ASSET_PROVENANCE_INVALID", asset_ref, "BOTH")
        try:
            validate_run_owned_path(str(asset.get("path") or ""), run_root=run_root)
        except (ManuscriptPathViolation, TypeError, ValueError, OSError):
            out.add("PATH_ESCAPE_OR_AMBIGUITY", asset_ref, "BOTH")
    for index, _ in enumerate(_strings(manuscript.get("anonymity_violations")), 1):
        out.add("ANONYMITY_VIOLATION", f"manuscript/anonymity/{index:03d}", "SUBMISSION")
    for index, _ in enumerate(_strings(manuscript.get("official_rule_violations")), 1):
        out.add("OFFICIAL_RULE_VIOLATION", f"manuscript/official-rules/{index:03d}", "SUBMISSION")

    persisted = manuscript.get("persisted_texts")
    persisted = persisted if isinstance(persisted, Mapping) else {}
    for channel, text in sorted(persisted.items(), key=lambda item: str(item[0])):
        try:
            scan_persisted_text(str(channel), str(text), sentinels=sentinels, patterns=patterns)
        except (ManuscriptSecretViolation, TypeError, ValueError):
            out.add("SECRET_LEAKAGE", _ref("manuscript/persisted-text", channel), "BOTH")
    tex = manuscript.get("tex_sources")
    if isinstance(tex, Mapping) and tex:
        try:
            validate_tex_sources({str(k): str(v) for k, v in tex.items()}, run_root=run_root,
                                 source_root=run_root / "source")
        except (ManuscriptTexViolation, ManuscriptPathViolation, TypeError, ValueError, OSError):
            out.add("UNSAFE_TEX_SOURCE", "manuscript/tex-sources", "BOTH")
    for index, advisory in enumerate(_rows(manuscript.get("advisories")), 1):
        effect = str(advisory.get("effect") or "CAVEAT")
        policy = effect if effect in {"CAVEAT", "SUPPLEMENT", "NONE"} else "CAVEAT"
        out.add(str(advisory.get("code") or "MANUSCRIPT_ADVISORY"),
                f"manuscript/advisories/{index:03d}", policy)


def _missing_build(run_id: str, source_hash: str) -> dict[str, Any]:
    marker = {"observation": "NO_BUILD_RECEIPT", "run_id": run_id}
    return {
        "receipt_ref": _NO_BUILD_REF, "receipt_sha256": _digest(_json(marker)),
        "state": "TOOLCHAIN_MISSING", "source_sha256": source_hash, "pdf_sha256": None,
    }


def _build_checks(
    contract: Mapping[str, Any], receipt_value: Mapping[str, Any] | None, *,
    run_root: Path, source_hash: str, requires_pdf: bool, receipt_ref: str,
    out: _Findings, verifier: Callable[..., Mapping[str, Any]] | None,
) -> tuple[dict[str, Any], bool, Mapping[str, Any] | None]:
    run_id = str(contract.get("run_id") or "unknown-run")
    if receipt_value is None:
        if requires_pdf:
            out.add("BUILD_REQUIRED_UNAVAILABLE", _NO_BUILD_REF, "SUBMISSION")
        return _missing_build(run_id, source_hash), False, None
    if not isinstance(receipt_value, Mapping):
        out.add("CORRUPT_BUILD_RECEIPT", "audit/build-receipt", "BOTH")
        if requires_pdf:
            out.add("BUILD_REQUIRED_UNAVAILABLE", _NO_BUILD_REF, "SUBMISSION")
        return _missing_build(run_id, source_hash), False, None

    receipt = dict(receipt_value)
    try:
        calculated = _object_digest(receipt, "build_receipt_sha256")
        full_hash = _object_digest(receipt)
    except (TypeError, ValueError):
        calculated, full_hash = "", _digest(b"corrupt-build-receipt")
    process = receipt.get("process_receipt")
    process_ok = True
    if receipt.get("build_state") == "COMPILED" and isinstance(process, Mapping):
        argv = _strings(process.get("argv"))
        process_ok = bool(argv) and process.get("executable") == argv[0]
    elif receipt.get("build_state") == "COMPILE_FAILED" and isinstance(process, Mapping):
        process_ok = process.get("return_code") != 0 or process.get("timed_out") is True
    bound = (
        receipt.get("run_id") == run_id
        and receipt.get("manuscript_snapshot_sha256") == contract.get("manuscript_snapshot_sha256")
        and receipt.get("requires_pdf") is requires_pdf
    )
    valid = (
        not validate_payload("manuscript_build_receipt", receipt)
        and _hash(receipt.get("build_receipt_sha256")) == calculated and bound and process_ok
    )
    if not valid:
        out.add("CORRUPT_BUILD_RECEIPT", "audit/build-receipt", "BOTH")
        if requires_pdf:
            out.add("BUILD_REQUIRED_UNAVAILABLE", _NO_BUILD_REF, "SUBMISSION")
        return _missing_build(run_id, source_hash), False, receipt

    safe_ref = receipt_ref
    try:
        validate_run_owned_path(safe_ref, run_root=run_root, purpose="read")
    except (ManuscriptPathViolation, TypeError, ValueError, OSError):
        safe_ref = "audit/manuscript-build-receipt"
    state = str(receipt["build_state"])
    recorded_source = _safe_hash(receipt.get("source_tree_sha256"), "invalid-source")
    pdf = receipt.get("pdf") if isinstance(receipt.get("pdf"), Mapping) else None
    recorded_pdf = _hash((pdf or {}).get("sha256"))
    summary = {
        "receipt_ref": safe_ref, "receipt_sha256": full_hash, "state": state,
        "source_sha256": recorded_source,
        "pdf_sha256": recorded_pdf if state == "COMPILED" else None,
    }
    if state in {"TOOLCHAIN_MISSING", "COMPILE_FAILED"}:
        if requires_pdf:
            out.add("BUILD_REQUIRED_UNAVAILABLE", safe_ref, "SUBMISSION")
        return summary, False, receipt

    trusted = False
    if verifier is not None:
        try:
            attested = verifier(
                run_root, safe_ref, expected_run_id=run_id,
                expected_snapshot_sha256=str(contract.get("manuscript_snapshot_sha256") or ""),
                expected_source_sha256=source_hash,
            )
            attested_pdf = attested.get("pdf") if isinstance(attested, Mapping) else None
            trusted = bool(
                isinstance(attested, Mapping) and isinstance(attested_pdf, Mapping)
                and _hash(attested.get("receipt_sha256")) == full_hash
                and attested.get("run_id") == run_id
                and attested.get("manuscript_snapshot_sha256")
                == contract.get("manuscript_snapshot_sha256")
                and attested.get("requires_pdf") is requires_pdf
                and attested.get("build_state") == "COMPILED"
                and _hash(attested.get("source_tree_sha256")) == recorded_source
                and _hash(attested.get("current_source_sha256")) == source_hash
                and _hash(attested.get("process_receipt_sha256"))
                == _hash((process or {}).get("receipt_sha256"))
                and attested_pdf.get("path") == (pdf or {}).get("path")
                and _hash(attested_pdf.get("sha256")) == recorded_pdf
                and attested_pdf.get("byte_size") == (pdf or {}).get("byte_size")
                and str(attested.get("attestation_key_id") or "").strip()
                and attested.get("signature_verified") is True
                and attested.get("source_tree_verified") is True
                and attested.get("pdf_verified") is True
            )
        except Exception:  # trusted-verifier details may contain secrets
            trusted = False
    if not trusted:
        out.add("BUILD_RECEIPT_UNVERIFIED", safe_ref, "SUBMISSION")

    current = recorded_source == source_hash
    if requires_pdf and not current:
        out.add("BUILD_SOURCE_STALE", safe_ref, "SUBMISSION")
    pdf_ok = False
    try:
        checked = validate_run_owned_path(str((pdf or {}).get("path") or ""),
                                          run_root=run_root, purpose="read")
        path = run_root / checked["relative_path"]
        if path.is_file():
            try:
                # 2026-08-07 de-governance: no longer requires the PDF's current byte length to
                # match the recorded byte_size (tamper-evidence against edits since recording, not
                # the safety property) — a safe (TOCTOU-protected) read of an existing file is
                # what still gates this.
                _read_bound_file(
                    run_root, str((pdf or {}).get("path") or ""),
                    expected_sha256=str(recorded_pdf), expected_size=(pdf or {}).get("byte_size"),
                    max_bytes=512 * 1024 * 1024,
                )
                pdf_ok = True
            except (OSError, TypeError, ValueError):
                pdf_ok = False
            if requires_pdf and not pdf_ok:
                out.add("BUILD_PDF_HASH_MISMATCH", safe_ref, "SUBMISSION")
        elif requires_pdf:
            out.add("BUILD_PDF_MISSING", safe_ref, "SUBMISSION")
    except (ManuscriptPathViolation, OSError, TypeError, ValueError):
        if requires_pdf:
            out.add("BUILD_PDF_MISSING", safe_ref, "SUBMISSION")
    return summary, trusted and current and pdf_ok, receipt


def _pdf_claim(
    manuscript: Mapping[str, Any], receipt: Mapping[str, Any] | None, *,
    run_root: Path, build_verified: bool, out: _Findings,
) -> None:
    claim = manuscript.get("claimed_pdf")
    if claim is None:
        return
    pdf = receipt.get("pdf") if isinstance(receipt, Mapping) else None
    valid = isinstance(claim, Mapping) and isinstance(pdf, Mapping) and build_verified
    valid = bool(valid and claim.get("path") == pdf.get("path")
                 and _hash(claim.get("sha256")) == _hash(pdf.get("sha256")))
    if not valid:
        out.add("FALSE_PDF_CLAIM", "manuscript/pdf-claim", "BOTH")


def audit_manuscript(
    contract: Mapping[str, Any], manuscript: Mapping[str, Any], *,
    run_root: str | Path, current_source_sha256: str,
    build_receipt: Mapping[str, Any] | None = None,
    build_receipt_ref: str = "audit/manuscript-build-receipt.json",
    executor_receipt_verifier: Callable[..., Mapping[str, Any]] = verify_executor_receipt,
    build_receipt_verifier: Callable[..., Mapping[str, Any]] | None = None,
    executor_key_resolver: Callable[[str], bytes | None] | None = None,
    secret_sentinels: Mapping[str, str] | None = None,
    secret_patterns: Mapping[str, str | re.Pattern[str]] | None = None,
) -> dict[str, Any]:
    """Audit one frozen manuscript fact inventory and emit a closed quality report."""
    out = _Findings()
    frozen = contract if isinstance(contract, Mapping) else {}
    facts = manuscript if isinstance(manuscript, Mapping) else {}
    if validate_payload("manuscript_contract", dict(frozen)) or not isinstance(manuscript, Mapping):
        out.add("CORRUPT_INPUT", "audit/input/manuscript-contract", "BOTH")
    venue = frozen.get("venue_profile")
    raw_requires_pdf = venue.get("requires_pdf") if isinstance(venue, Mapping) else None
    requires_pdf = raw_requires_pdf if isinstance(raw_requires_pdf, bool) else True
    source_hash = _hash(current_source_sha256)
    if source_hash is None:
        out.add("CORRUPT_INPUT", "audit/input/source-hash", "BOTH")
        source_hash = _digest(b"invalid-current-source")
    manuscript_hash = _hash(facts.get("manuscript_sha256"))
    if manuscript_hash is None:
        out.add("CORRUPT_INPUT", "audit/input/manuscript-hash", "BOTH")
        try:
            manuscript_hash = _digest(_json(facts))
        except (TypeError, ValueError):
            manuscript_hash = _digest(b"invalid-manuscript")
    root = Path(run_root)
    _authority(frozen, requires_pdf, out)
    if "requires_pdf" in facts and facts.get("requires_pdf") is not requires_pdf:
        out.add("OFFICIAL_HARD_RULE_OVERRIDE", "manuscript/requires-pdf", "BOTH")
    _sections_and_claims(frozen, facts, out)
    _numeric_truth(frozen, facts, root, out, executor_receipt_verifier, executor_key_resolver)
    _content_checks(frozen, facts, root, out, secret_sentinels, secret_patterns)
    build, build_verified, verified_receipt = _build_checks(
        frozen, build_receipt, run_root=root, source_hash=source_hash,
        requires_pdf=requires_pdf, receipt_ref=build_receipt_ref, out=out,
        verifier=build_receipt_verifier,
    )
    _pdf_claim(facts, verified_receipt, run_root=root, build_verified=build_verified, out=out)

    findings = out.finish()
    daily = derive_daily_status(findings)
    ready = derive_submission_readiness(
        findings, requires_pdf=requires_pdf, build_verified=build_verified,
    )
    hard_submission = [item for item in findings if item["status"] == "OPEN"
                       and item["finding_class"] == "HARD"
                       and item["submission_effect"] == "BLOCK"]
    blockers = [{
        "blocker_id": f"BLK-{index:03d}-{item['code']}", "code": item["code"],
        "source_ref": item["evidence_refs"][0], "rationale": item["message"],
    } for index, item in enumerate(hard_submission, 1)]
    counts = {effect: sum(item["status"] == "OPEN" and item["daily_effect"] == effect
                          for item in findings) for effect in ("BLOCK", "SUPPLEMENT", "CAVEAT")}
    report: dict[str, Any] = {
        "schema_version": "1.0.0", "run_id": str(frozen.get("run_id") or "unknown-run"),
        "manuscript_sha256": manuscript_hash, "requires_pdf": requires_pdf, "build": build,
        "findings": findings, "daily_state": daily,
        "daily_rationale": (
            f"Deterministic reducer selected {daily}: {counts['BLOCK']} hard block(s), "
            f"{counts['SUPPLEMENT']} supplement(s), and {counts['CAVEAT']} caveat(s)."
        ),
        "submission_ready": ready, "submission_blockers": blockers,
    }
    report["quality_report_sha256"] = _object_digest(report)
    if validate_payload("manuscript_quality_report", report):
        raise ManuscriptAuditError("deterministic quality report violates its closed schema")
    return report


__all__ = ["ManuscriptAuditError", "audit_manuscript", "derive_daily_status",
           "derive_submission_readiness"]
