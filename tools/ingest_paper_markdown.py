"""Deterministic verification and Markdown rendering for Tier-S paper ingest.

The two LLM workers only extract and inspect evidence. This module owns the
trust boundary: it checks their independent handoff, removes unsupported
content, and renders the director-facing skim note. It never writes the vault.
"""
from __future__ import annotations

import hashlib
import re
import unicodedata
from pathlib import Path
from typing import Iterable


SUPPORTED = "SUPPORTED"
NEEDS_DEEP_READ = "NEEDS_DEEP_READ"
BLOCK = "BLOCK"
LEGACY_UNVERIFIED = "LEGACY_UNVERIFIED"
_ITEM_FIELDS = ("methods", "datasets", "metrics")


def _one_line(value: object) -> str:
    return " ".join(str(value or "").split())


def _normal(value: object) -> str:
    return _one_line(value).casefold()


def _require_dict(value: object, label: str) -> dict:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return value


def _require_list(value: object, label: str) -> list:
    if not isinstance(value, list):
        raise ValueError(f"{label} must be an array")
    return value


def _unique_by(rows: list[dict], key: str, label: str) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError(f"{label} entries must be objects")
        value = _one_line(row.get(key))
        if not value:
            raise ValueError(f"{label} entry missing {key}")
        if value in out:
            raise ValueError(f"{label} contains duplicate {key} {value!r}")
        out[value] = row
    return out


def _verify_local_snapshot(run_dir: str | Path, snapshot: dict) -> bool:
    """Verify snapshot bytes and return whether they were reopened locally.

    An external identifier can identify a source, but it cannot prove which
    bytes either worker read. Quick ingest therefore cannot receive PASS when
    the referenced snapshot is not locally reopenable and hash-verifiable.
    """
    snapshot_ref = _one_line(snapshot.get("snapshot_ref"))
    fingerprint = _one_line(snapshot.get("snapshot_fingerprint"))
    if not snapshot_ref or not fingerprint:
        raise ValueError("source_snapshot requires snapshot_ref and snapshot_fingerprint")

    candidate = Path(snapshot_ref)
    if not candidate.is_absolute():
        candidate = Path(run_dir) / candidate
    if not candidate.is_file():
        return False

    expected = fingerprint.removeprefix("sha256:")
    if not re.fullmatch(r"[0-9a-fA-F]{64}", expected):
        raise ValueError("a local source snapshot requires a sha256 fingerprint")
    actual = hashlib.sha256(candidate.read_bytes()).hexdigest()
    if actual.casefold() != expected.casefold():
        raise ValueError("source snapshot hash does not match snapshot_fingerprint")
    return True


def verify_and_filter_panel(run_dir: str | Path, extractor_bundle: dict,
                            verifier_bundle: dict) -> tuple[dict, dict]:
    """Validate a two-worker ingest panel and return a filtered paper note.

    Raises ``ValueError`` for structural dishonesty, incomplete coverage, a
    BLOCK verdict, or a worker verdict inconsistent with deterministic facts.
    ``NEEDS_DEEP_READ`` is a valid output: unsupported content is removed and
    the surviving note is visibly provisional.
    """
    extractor_contract = _require_dict(
        extractor_bundle.get("worker_contract"), "extractor worker_contract")
    verifier_contract = _require_dict(
        verifier_bundle.get("worker_contract"), "verifier worker_contract")
    if extractor_contract.get("role") != "paper-note-extractor":
        raise ValueError("extractor bundle was not produced by paper-note-extractor")
    if verifier_contract.get("role") != "source-claim-verifier":
        raise ValueError("verifier bundle was not produced by source-claim-verifier")
    if verifier_contract.get("independent_of_extractor") is not True:
        raise ValueError("verifier must declare independent_of_extractor=true")
    if verifier_contract.get("reopened_source_snapshot") is not True:
        raise ValueError("verifier must reopen the source snapshot")
    if "paper_note" in verifier_bundle or "claim_records" in verifier_bundle:
        raise ValueError("verifier may judge claims but may not extract or rewrite paper_note")

    paper_note = _require_dict(extractor_bundle.get("paper_note"), "paper_note")
    snapshot = _require_dict(extractor_bundle.get("source_snapshot"), "source_snapshot")
    verification = _require_dict(verifier_bundle.get("verification"), "verification")
    identity = _require_dict(verification.get("source_identity"), "source_identity")
    snapshot_locally_verified = _verify_local_snapshot(run_dir, snapshot)

    source_ref = _one_line(paper_note.get("source_ref"))
    title = _one_line(paper_note.get("title"))
    identity_fields = (
        (source_ref, snapshot.get("source_ref"), "paper_note/source_snapshot source_ref"),
        (source_ref, identity.get("source_ref"), "paper_note/verifier source_ref"),
        (snapshot.get("snapshot_ref"), identity.get("snapshot_ref"), "snapshot_ref"),
        (snapshot.get("snapshot_fingerprint"), identity.get("snapshot_fingerprint"),
         "snapshot_fingerprint"),
        (title, snapshot.get("title"), "paper_note/source_snapshot title"),
        (title, identity.get("verified_title"), "paper_note/verifier title"),
    )
    mismatches = [label for left, right, label in identity_fields
                  if not _normal(left) or _normal(left) != _normal(right)]
    if identity.get("source_ref_match") is not True:
        mismatches.append("verifier source_ref_match")
    if identity.get("title_match") is not True:
        mismatches.append("verifier title_match")
    if mismatches:
        raise ValueError(f"source identity BLOCK: {sorted(set(mismatches))}")

    note_claims = [_one_line(value) for value in _require_list(
        paper_note.get("claims"), "paper_note.claims")]
    records = _unique_by(
        _require_list(extractor_bundle.get("claim_records"), "claim_records"),
        "claim_id", "claim_records")
    results = _unique_by(
        _require_list(verification.get("claim_results"), "claim_results"),
        "claim_id", "claim_results")
    if len(records) != len(note_claims):
        raise ValueError("claim_records must cover every paper_note claim exactly once")
    if set(records) != set(results):
        raise ValueError("verifier claim_results must completely cover extractor claim_records")

    record_texts = [_one_line(row.get("claim")) for row in records.values()]
    if sorted(_normal(value) for value in record_texts) != sorted(_normal(value) for value in note_claims):
        raise ValueError("claim_records text does not exactly cover paper_note claims")

    supported_claims: list[str] = []
    dropped_claims: list[dict] = []
    claim_findings: list[dict] = []
    for claim_id, record in records.items():
        result = results[claim_id]
        claim = _one_line(record.get("claim"))
        if _normal(claim) != _normal(result.get("claim")):
            raise ValueError(f"verifier changed claim text for {claim_id}")
        verdict = _one_line(result.get("verdict")).upper()
        if verdict not in {SUPPORTED, "UNSUPPORTED", "UNCLEAR"}:
            raise ValueError(f"claim {claim_id} has invalid verifier verdict {verdict!r}")
        reason = _one_line(result.get("reason"))
        if not reason:
            raise ValueError(f"claim {claim_id} is missing a claim-level reason")
        finding = {
            "claim_id": claim_id,
            "claim": claim,
            "verdict": verdict,
            "reason": reason,
            "source_location": _one_line(result.get("source_location")),
            "section_confusion": bool(result.get("section_confusion", False)),
        }
        claim_findings.append(finding)
        if verdict == SUPPORTED and not finding["section_confusion"]:
            supported_claims.append(claim)
        else:
            dropped_claims.append(finding)

    summary_result = _require_dict(verification.get("summary_result"), "summary_result")
    summary_verdict = _one_line(summary_result.get("verdict")).upper()
    if summary_verdict not in {SUPPORTED, "PARTIAL", "UNSUPPORTED"}:
        raise ValueError("summary_result verdict must be SUPPORTED, PARTIAL, or UNSUPPORTED")
    if not _one_line(summary_result.get("reason")):
        raise ValueError("summary_result requires a reason")

    field_results = _require_list(verification.get("field_results"), "field_results")
    field_index: dict[tuple[str, str], dict] = {}
    for row in field_results:
        if not isinstance(row, dict):
            raise ValueError("field_results entries must be objects")
        field = _one_line(row.get("field"))
        item = _one_line(row.get("item"))
        verdict = _one_line(row.get("verdict")).upper()
        if field not in _ITEM_FIELDS or not item:
            raise ValueError("field_results must identify methods/datasets/metrics items")
        if verdict not in {SUPPORTED, "UNSUPPORTED", "UNCLEAR"}:
            raise ValueError(f"invalid field verdict {verdict!r}")
        if not _one_line(row.get("reason")):
            raise ValueError(f"field result {field}:{item} requires a reason")
        key = (field, _normal(item))
        if key in field_index:
            raise ValueError(f"duplicate field result for {field}:{item}")
        field_index[key] = row

    filtered_fields: dict[str, list[str]] = {}
    dropped_fields: list[dict] = []
    for field in _ITEM_FIELDS:
        values = [_one_line(value) for value in (paper_note.get(field) or [])]
        expected = {(field, _normal(value)) for value in values}
        actual = {key for key in field_index if key[0] == field}
        if expected != actual:
            raise ValueError(f"field_results must completely cover paper_note.{field}")
        filtered_fields[field] = []
        for value in values:
            row = field_index[(field, _normal(value))]
            if _one_line(row.get("verdict")).upper() == SUPPORTED:
                filtered_fields[field].append(value)
            else:
                dropped_fields.append({
                    "field": field,
                    "item": value,
                    "verdict": _one_line(row.get("verdict")).upper(),
                    "reason": _one_line(row.get("reason")),
                })

    confusion = _require_dict(
        verification.get("section_confusion_check"), "section_confusion_check")
    confusion_detected = confusion.get("abstract_or_method_presented_as_result") is True
    confusion_reasons = [_one_line(value) for value in (confusion.get("reasons") or [])
                         if _one_line(value)]
    if confusion_detected and not confusion_reasons:
        raise ValueError("section_confusion_check requires reasons when confusion is detected")

    deep_read_reasons = [_one_line(value) for value in (verification.get("deep_read_reasons") or [])
                         if _one_line(value)]
    if not snapshot_locally_verified:
        deep_read_reasons.append(
            "Snapshot bytes were not locally reopenable and hash-verifiable; fetch a fulltext "
            "snapshot before scientific use."
        )
    requires_deep_read = bool(
        not note_claims or dropped_claims or dropped_fields or summary_verdict != SUPPORTED
        or confusion_detected or deep_read_reasons
    )
    derived_verdict = NEEDS_DEEP_READ if requires_deep_read else "PASS"
    declared_verdict = _one_line(verification.get("verdict")).upper()
    if declared_verdict == BLOCK:
        reasons = deep_read_reasons or confusion_reasons or ["verifier returned BLOCK"]
        raise ValueError(f"source/claim verifier BLOCK: {reasons}")
    if declared_verdict not in {"PASS", NEEDS_DEEP_READ}:
        raise ValueError(f"invalid verifier verdict {declared_verdict!r}")
    if declared_verdict != derived_verdict:
        raise ValueError(
            f"verifier verdict inconsistent: declared {declared_verdict}, derived {derived_verdict}")

    filtered_note = dict(paper_note)
    filtered_note["claims"] = supported_claims
    filtered_note.update(filtered_fields)
    filtered_note["reading_status"] = "skimmed"
    if summary_verdict != SUPPORTED:
        filtered_note["summary"] = (
            "Quick-ingest summary retained only independently supported claims: "
            + ("; ".join(supported_claims) if supported_claims
               else "no claim survived; a deep read is required before scientific use.")
        )

    summary = {
        "verdict": derived_verdict,
        "legacy_unverified": False,
        "independent_verifier": True,
        "source_ref": source_ref,
        "snapshot_ref": _one_line(snapshot.get("snapshot_ref")),
        "snapshot_fingerprint": _one_line(snapshot.get("snapshot_fingerprint")),
        "snapshot_locally_verified": snapshot_locally_verified,
        "claim_findings": claim_findings,
        "n_claims_submitted": len(note_claims),
        "n_claims_retained": len(supported_claims),
        "dropped_claims": dropped_claims,
        "dropped_fields": dropped_fields,
        "summary_verdict": summary_verdict,
        "summary_reason": _one_line(summary_result.get("reason")),
        "section_confusion_detected": confusion_detected,
        "section_confusion_reasons": confusion_reasons,
        "deep_read_reasons": deep_read_reasons,
    }
    return filtered_note, summary


def legacy_verification(paper_note: dict) -> dict:
    """Describe a replayed pre-panel bundle without upgrading its trust level."""
    return {
        "verdict": LEGACY_UNVERIFIED,
        "legacy_unverified": True,
        "independent_verifier": False,
        "source_ref": _one_line(paper_note.get("source_ref")),
        "snapshot_ref": "not-recorded",
        "snapshot_fingerprint": "not-recorded",
        "snapshot_locally_verified": False,
        "claim_findings": [],
        "n_claims_submitted": len(paper_note.get("claims") or []),
        "n_claims_retained": len(paper_note.get("claims") or []),
        "dropped_claims": [],
        "dropped_fields": [],
        "summary_verdict": LEGACY_UNVERIFIED,
        "summary_reason": "Historical single-worker bundle; no independent source/claim verification.",
        "section_confusion_detected": False,
        "section_confusion_reasons": [],
        "deep_read_reasons": ["Replay is compatible, but scientific use requires read_paper_deep."],
    }


def safe_paper_name(title: object, source_ref: object) -> str:
    ascii_title = unicodedata.normalize("NFKD", _one_line(title)).encode(
        "ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", ascii_title).strip("-").lower()
    if slug:
        return slug[:72].rstrip("-")
    digest = hashlib.sha256(_one_line(source_ref).encode("utf-8")).hexdigest()[:12]
    return f"paper-{digest}"


def _bullets(values: Iterable[object], empty: str = "- Not recorded in this skim.") -> str:
    rows = [f"- {_one_line(value)}" for value in values if _one_line(value)]
    return "\n".join(rows) if rows else empty


def build_quick_note_markdown(paper_note: dict, verification: dict) -> str:
    title = _one_line(paper_note.get("title")) or "Untitled paper"
    verdict = _one_line(verification.get("verdict")) or LEGACY_UNVERIFIED
    contract = paper_note.get("paper_contract") if isinstance(paper_note.get("paper_contract"), dict) else {}
    claims = paper_note.get("claims") or []
    findings = verification.get("claim_findings") or []

    finding_lines = []
    for row in findings:
        finding_lines.append(
            f"- `{_one_line(row.get('claim_id'))}` **{_one_line(row.get('verdict'))}**: "
            f"{_one_line(row.get('reason'))}"
            + (f" Location: `{_one_line(row.get('source_location'))}`."
               if _one_line(row.get("source_location")) else "")
        )
    if not finding_lines:
        finding_lines = ["- No independent claim-level findings exist for this legacy replay."]

    next_action = (
        "Run `read_paper_deep` before citing, designing an experiment from, or promoting this note."
        if verdict != "PASS"
        else "Use this only for triage; schedule `read_paper_deep` if the paper affects an idea, method, baseline, or claim."
    )
    warning = (
        "**SKIMMED DRAFT / QUICK NOTE. This is not a deep read, not a frozen result, and has not been "
        "promoted to the vault.**"
    )
    legacy_warning = (
        "\n\n**LEGACY UNVERIFIED:** this replay predates the independent verifier and must not be treated as checked."
        if verification.get("legacy_unverified") else ""
    )

    text = f"""# Quick Note: {title}

> {warning}{legacy_warning}

## Status / Use Boundary

- Reading status: `skimmed`
- Verification verdict: `{verdict}`
- Independent verifier: `{str(bool(verification.get('independent_verifier'))).lower()}`
- Promotion status: `NOT_PROMOTED`
- Scientific use: triage only; this note is not evidence-equivalent to `read_paper_deep`.

## Source

- Source ref: `{_one_line(paper_note.get('source_ref')) or 'not-recorded'}`
- Snapshot ref: `{_one_line(verification.get('snapshot_ref')) or 'not-recorded'}`
- Snapshot fingerprint: `{_one_line(verification.get('snapshot_fingerprint')) or 'not-recorded'}`
- Snapshot bytes locally verified: `{str(bool(verification.get('snapshot_locally_verified'))).lower()}`
- Title checked against source: `{str(verdict in {'PASS', NEEDS_DEEP_READ}).lower()}`

## Paper Contract

- Category: {_one_line(contract.get('category')) or _one_line(paper_note.get('paper_type')) or 'not-recorded'}
- Context: {_one_line(contract.get('context')) or 'not-recorded'}
- Correctness prior: {_one_line(contract.get('correctness_prior')) or 'not-recorded'}
- Contract sentence: {_one_line(contract.get('contract_sentence')) or 'not-recorded'}
- Contributions:
{_bullets(contract.get('contributions') or [])}

## Summary / Takeaway

{_one_line(paper_note.get('summary'))}

Verifier summary judgment: **{_one_line(verification.get('summary_verdict'))}**.
{_one_line(verification.get('summary_reason'))}

## Atomic Claims

Retained only after deterministic claim-level filtering:
`{verification.get('n_claims_retained', len(claims))}/{verification.get('n_claims_submitted', len(claims))}`.

{_bullets(claims, '- No independently supported atomic claim was retained.')}

## Methods / Datasets / Metrics

### Methods
{_bullets(paper_note.get('methods') or [])}

### Datasets
{_bullets(paper_note.get('datasets') or [])}

### Metrics
{_bullets(paper_note.get('metrics') or [])}

These fields describe what the quick ingest could verify. They do not establish implementation details,
fairness of comparison, statistical validity, reproducibility, or applicability to the current project.

## Verifier Findings

{chr(10).join(finding_lines)}

- Abstract/method presented as result: `{str(bool(verification.get('section_confusion_detected'))).lower()}`
- Dropped claims: `{len(verification.get('dropped_claims') or [])}`
- Dropped method/dataset/metric items: `{len(verification.get('dropped_fields') or [])}`
- Deep-read reasons: {_one_line('; '.join(verification.get('deep_read_reasons') or [])) or 'none recorded'}

## Project Relevance / Relation to Thesis

- Relation to thesis: `{_one_line(paper_note.get('relation_to_thesis')) or 'not-classified'}`
- Read purpose: `{_one_line(paper_note.get('read_purpose')) or 'not-classified'}`
- Reading objective: {_one_line(paper_note.get('reading_objective')) or 'not-recorded'}

The quick note does not decide whether the paper is novel, correct, reproducible, or suitable for a research bet.
Those judgments require the deep-reading and evidence-review panels.

## Next Read Action

{next_action}

Before promotion, a human must review the deep-read Markdown and explicitly invoke `/promote-to-vault`.
"""
    return text.strip() + "\n"


def write_quick_note_markdown(run_dir: str | Path, paper_note: dict,
                              verification: dict) -> str:
    out = (Path(run_dir) / "director-review" / "papers" /
           f"{safe_paper_name(paper_note.get('title'), paper_note.get('source_ref'))}-quick-note.md")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(build_quick_note_markdown(paper_note, verification), encoding="utf-8")
    return str(out)
