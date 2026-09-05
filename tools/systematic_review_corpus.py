"""Deterministic execution manifest for a systematic-review source corpus.

The tool deliberately separates *retrieval occurrences*, *reports*, and *studies*.
It never treats an internal memo, abstract, or database card as a scientific
full-text paper, and it derives every count from the underlying rows rather
than trusting a stale scalar supplied by an authoring bundle.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from jsonschema import Draft202012Validator


SCHEMA_PATH = (
    Path(__file__).resolve().parents[1]
    / "schemas"
    / "systematic_review_execution_manifest.schema.json"
)
SCHEMA_VERSION = "systematic-review-execution-manifest/v1"
IDENTITY_POLICY_VERSION = "report-identity/doi-arxiv-pmid-title/v1"
TOOL_VERSION = "systematic-review-corpus/v1"

PAPER_DOCUMENT_TYPES = frozenset(
    {"journal_article", "conference_paper", "preprint", "thesis", "book_chapter"}
)
NON_PAPER_DOCUMENT_TYPES = frozenset({"internal_doc", "abstract", "card"})
DOCUMENT_TYPES = PAPER_DOCUMENT_TYPES | NON_PAPER_DOCUMENT_TYPES
FULLTEXT_FORBIDDEN_TYPES = frozenset({"abstract", "card"})
SOURCE_TIERS = frozenset({"tier_1", "tier_2", "tier_3", "tier_4", "unrated"})
ORACLE_RUNGS = frozenset({f"O{index}" for index in range(6)})
REPORT_ORACLE_RUNGS = ORACLE_RUNGS | {"UNCLASSIFIED"}
EXTRACTION_STATES = ("present", "absent", "unclear", "NA")
SCREENING_DECISIONS = frozenset({"include", "exclude"})
PERMISSION_STATUSES = frozenset(
    {"open_access", "licensed", "author_permission", "public_domain", "restricted", "unknown"}
)
ALLOWED_USES = frozenset({"text_mining", "quotation", "figure_reuse", "redistribution"})
_IDENTITY_TYPE_ORDER = {"doi": 0, "arxiv": 1, "pmid": 2, "title": 3}


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256(value: Any) -> str:
    return "sha256:" + hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _normalized_words(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).casefold().strip()
    text = re.sub(r"[^\w]+", " ", text, flags=re.UNICODE)
    return " ".join(text.split())


def _require_text(value: Any, field: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field} must be a non-empty string")
    return text


def _identity_sort_key(identity: str) -> tuple[int, str]:
    prefix = identity.partition(":")[0]
    return (_IDENTITY_TYPE_ORDER.get(prefix, 99), identity)


def canonical_report_identity(record: Mapping[str, Any]) -> str:
    """Return the stable report identity using DOI > arXiv > PMID > title."""
    doi = str(record.get("doi") or "").strip().casefold()
    if doi:
        doi = re.sub(r"^(?:https?://(?:dx\.)?doi\.org/|doi\s*:\s*)", "", doi).strip()
        if doi:
            return f"doi:{doi}"

    arxiv = str(record.get("arxiv") or "").strip().casefold()
    if arxiv:
        arxiv = re.sub(r"^(?:https?://arxiv\.org/(?:abs|pdf)/|arxiv\s*:\s*)", "", arxiv)
        arxiv = re.sub(r"\.pdf$", "", arxiv)
        arxiv = re.sub(r"v\d+$", "", arxiv).strip()
        if arxiv:
            return f"arxiv:{arxiv}"

    pmid = str(record.get("pmid") or "").strip().casefold()
    if pmid:
        pmid = re.sub(r"^(?:pmid\s*:\s*)", "", pmid).strip()
        if pmid:
            return f"pmid:{pmid}"

    title = _normalized_words(record.get("title"))
    if not title:
        raise ValueError("report identity requires DOI, arXiv, PMID, or a non-empty title")
    return f"title:{title}"


def _study_id(record: Mapping[str, Any], identity: str) -> str:
    explicit = _normalized_words(record.get("study_key"))
    return f"study:{explicit}" if explicit else f"study:{identity}"


def _normalize_decision(identity: str, stage: str, raw: Mapping[str, Any] | None) -> dict:
    if not isinstance(raw, Mapping):
        raise ValueError(f"{identity} requires two-reviewer {stage} screening")
    reviewer_1 = raw.get("reviewer_1")
    reviewer_2 = raw.get("reviewer_2")
    if reviewer_1 not in SCREENING_DECISIONS or reviewer_2 not in SCREENING_DECISIONS:
        raise ValueError(f"{identity} has invalid {stage} screening decision")
    conflict = reviewer_1 != reviewer_2
    resolution = raw.get("resolution")
    normalized: dict[str, Any] = {
        "identity": identity,
        "stage": stage,
        "reviewer_1": reviewer_1,
        "reviewer_2": reviewer_2,
        "conflict": conflict,
    }
    if conflict:
        if resolution is None:
            normalized["final_decision"] = "unresolved"
            return normalized
        if not isinstance(resolution, Mapping):
            raise ValueError(f"{identity} {stage} conflict resolution must be an object")
        decision = resolution.get("decision")
        if decision not in SCREENING_DECISIONS:
            raise ValueError(f"{identity} {stage} conflict resolution has invalid decision")
        normalized["final_decision"] = decision
        normalized["resolution"] = {
            "decision": decision,
            "resolver": _require_text(resolution.get("resolver"), "screening resolution resolver"),
            "reason": _require_text(resolution.get("reason"), "screening resolution reason"),
        }
        return normalized
    if resolution is not None:
        raise ValueError(f"{identity} {stage} has a resolution but no reviewer conflict")
    normalized["final_decision"] = reviewer_1
    return normalized


def _normalize_fulltext(identity: str, document_type: str, raw: Any) -> dict | None:
    if raw is None:
        return None
    if not isinstance(raw, Mapping):
        raise ValueError(f"{identity} fulltext must be an object")
    if document_type in FULLTEXT_FORBIDDEN_TYPES:
        raise ValueError(f"{document_type} record {identity} cannot be treated as fulltext")
    ref = _require_text(raw.get("ref"), "fulltext ref")
    digest = _require_text(raw.get("sha256"), "fulltext sha256").casefold()
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
        raise ValueError(f"{identity} fulltext sha256 must be a canonical sha256 digest")
    content_type = _require_text(raw.get("content_type"), "fulltext content_type")
    permission_raw = raw.get("permission")
    if permission_raw is None:
        permission = {"status": "unknown", "basis": "not supplied", "allowed_uses": []}
    elif not isinstance(permission_raw, Mapping):
        raise ValueError(f"{identity} fulltext permission must be an object")
    else:
        status = permission_raw.get("status")
        if status not in PERMISSION_STATUSES:
            raise ValueError(f"{identity} has invalid permission status")
        uses = sorted(set(permission_raw.get("allowed_uses") or []))
        if any(use not in ALLOWED_USES for use in uses):
            raise ValueError(f"{identity} has invalid permission allowed_uses")
        permission = {
            "status": status,
            "basis": _require_text(permission_raw.get("basis"), "permission basis"),
            "allowed_uses": uses,
        }
    return {
        "ref": ref,
        "sha256": digest,
        "content_type": content_type,
        "permission": permission,
    }


def _normalize_extractions(identity: str, raw: Any) -> dict[str, dict]:
    if raw is None:
        return {}
    if not isinstance(raw, Mapping):
        raise ValueError(f"{identity} extraction must be an object keyed by field")
    result: dict[str, dict] = {}
    for field in sorted(raw):
        field_name = _require_text(field, "extraction field")
        item = raw[field]
        if not isinstance(item, Mapping):
            raise ValueError(f"{identity} extraction {field_name} must be an object")
        status = item.get("status")
        if status not in EXTRACTION_STATES:
            raise ValueError(
                f"{identity} extraction status for {field_name} must be one of {EXTRACTION_STATES}"
            )
        evidence_refs = sorted(
            set(_require_text(value, f"{field_name} evidence ref") for value in item.get("evidence_refs") or [])
        )
        normalized: dict[str, Any] = {"status": status, "evidence_refs": evidence_refs}
        if status == "present":
            if "value" not in item or item.get("value") is None or item.get("value") == "":
                raise ValueError(f"present extraction {field_name} for {identity} requires a value")
            normalized["value"] = copy.deepcopy(item["value"])
        elif "value" in item and item.get("value") not in (None, ""):
            raise ValueError(f"non-present extraction {field_name} for {identity} cannot carry a value")
        result[field_name] = normalized
    return result


def _normalize_record(record: Mapping[str, Any]) -> dict:
    if not isinstance(record, Mapping):
        raise ValueError("each record must be an object")
    record_id = _require_text(record.get("record_id"), "record_id")
    title = _require_text(record.get("title"), f"{record_id} title")
    identity = canonical_report_identity(record)
    document_type = record.get("document_type")
    if document_type not in DOCUMENT_TYPES:
        raise ValueError(f"{identity} has invalid document_type")
    tier = record.get("source_tier", "unrated")
    if tier not in SOURCE_TIERS:
        raise ValueError(f"{identity} has invalid source tier")
    requested_rungs = record.get("oracle_rungs")
    if requested_rungs is None:
        oracle_rungs = [record.get("oracle_rung")]
    elif not isinstance(requested_rungs, Sequence) or isinstance(
        requested_rungs, (str, bytes)
    ) or not requested_rungs:
        raise ValueError(f"{identity} oracle_rungs must be a non-empty list")
    else:
        oracle_rungs = list(requested_rungs)
    if len(oracle_rungs) != len(set(oracle_rungs)) or any(
        rung not in REPORT_ORACLE_RUNGS for rung in oracle_rungs
    ):
        raise ValueError(f"{identity} has invalid oracle rung; expected O0-O5 or UNCLASSIFIED")
    if "UNCLASSIFIED" in oracle_rungs and len(oracle_rungs) != 1:
        raise ValueError(f"{identity} cannot mix UNCLASSIFIED with O0-O5 oracle rungs")
    oracle_rungs = sorted(oracle_rungs)
    oracle_rung = oracle_rungs[-1]
    fulltext = _normalize_fulltext(identity, document_type, record.get("fulltext"))
    normalized: dict[str, Any] = {
        "record_id": record_id,
        "identity": identity,
        "title": title,
        "document_type": document_type,
        "is_paper": document_type in PAPER_DOCUMENT_TYPES,
        "study_id": _study_id(record, identity),
        "source_tier": tier,
        "oracle_rung": oracle_rung,
        "oracle_rungs": oracle_rungs,
        "fulltext": fulltext,
        "extractions": _normalize_extractions(identity, record.get("extraction")),
    }
    if normalized["is_paper"]:
        screening = record.get("screening")
        if not isinstance(screening, Mapping):
            raise ValueError(f"{identity} requires screening decisions")
        title_decision = _normalize_decision(identity, "title_abstract", screening.get("title_abstract"))
        normalized["title_decision"] = title_decision
        if title_decision["final_decision"] == "include" and fulltext is not None:
            normalized["fulltext_decision"] = _normalize_decision(
                identity, "fulltext", screening.get("fulltext")
            )
        else:
            normalized["fulltext_decision"] = None
        exclusion_reason = record.get("fulltext_exclusion_reason")
        if (
            normalized["fulltext_decision"] is not None
            and normalized["fulltext_decision"]["final_decision"] == "exclude"
        ):
            normalized["fulltext_exclusion_reason"] = _require_text(
                exclusion_reason, f"{identity} fulltext exclusion reason"
            )
        elif exclusion_reason not in (None, ""):
            raise ValueError(f"{identity} supplies a fulltext exclusion reason without an exclusion")
    return normalized


def _merge_duplicate_group(group: list[dict]) -> tuple[dict, dict | None]:
    group = sorted(group, key=lambda row: row["record_id"])
    kept = copy.deepcopy(group[0])
    record_ids = sorted(row["record_id"] for row in group)
    for field in (
        "document_type",
        "is_paper",
        "study_id",
        "source_tier",
        "oracle_rung",
        "oracle_rungs",
        "title_decision",
        "fulltext_decision",
        "fulltext_exclusion_reason",
        "extractions",
    ):
        values = [_canonical_json(row.get(field)) for row in group]
        if len(set(values)) > 1:
            raise ValueError(f"duplicate identity {kept['identity']} has conflicting {field}")
    fulltexts = [row["fulltext"] for row in group if row.get("fulltext") is not None]
    if fulltexts:
        if len({_canonical_json(value) for value in fulltexts}) > 1:
            raise ValueError(f"duplicate identity {kept['identity']} has conflicting fulltext snapshots")
        kept["fulltext"] = copy.deepcopy(fulltexts[0])
    kept["retrieval_record_ids"] = record_ids
    duplicate = None
    if len(group) > 1:
        duplicate = {
            "identity": kept["identity"],
            "record_ids": record_ids,
            "kept_record_id": kept["record_id"],
        }
    return kept, duplicate


def _normalize_search_logs(search_logs: Sequence[Mapping[str, Any]], record_ids: set[str]) -> list[dict]:
    normalized: list[dict] = []
    seen_sources: set[str] = set()
    seen_record_ids: set[str] = set()
    for raw in search_logs:
        if not isinstance(raw, Mapping):
            raise ValueError("each search log must be an object")
        source_id = _require_text(raw.get("source_id"), "search source_id")
        if source_id in seen_sources:
            raise ValueError(f"duplicate search source_id: {source_id}")
        seen_sources.add(source_id)
        source_type = raw.get("source_type")
        if source_type not in {"database", "register", "other_methods"}:
            raise ValueError(f"search source {source_id} has invalid source_type")
        ids = sorted(set(_require_text(value, "search record_id") for value in raw.get("record_ids") or []))
        if len(ids) != len(raw.get("record_ids") or []):
            raise ValueError(f"search source {source_id} repeats a record_id")
        unknown = sorted(set(ids) - record_ids)
        if unknown:
            raise ValueError(f"search source {source_id} references unknown record_id: {unknown[0]}")
        overlap = sorted(set(ids) & seen_record_ids)
        if overlap:
            raise ValueError(f"record_id appears in more than one search log: {overlap[0]}")
        seen_record_ids.update(ids)
        if "records_retrieved" in raw and raw["records_retrieved"] != len(ids):
            raise ValueError(f"search source {source_id} has stale records_retrieved scalar")
        entry = {
            "source_id": source_id,
            "source_type": source_type,
            "query": _require_text(raw.get("query"), "search query"),
            "executed_at": _require_text(raw.get("executed_at"), "search executed_at"),
            "record_ids": ids,
            "records_retrieved": len(ids),
        }
        entry["log_sha256"] = _sha256(entry)
        normalized.append(entry)
    missing = sorted(record_ids - seen_record_ids)
    if missing:
        raise ValueError(f"record_id absent from search logs: {missing[0]}")
    return sorted(normalized, key=lambda row: (row["source_type"], row["source_id"]))


def _conflict_row(decision: Mapping[str, Any]) -> dict:
    result = {
        "identity": decision["identity"],
        "stage": decision["stage"],
        "reviewer_1": decision["reviewer_1"],
        "reviewer_2": decision["reviewer_2"],
        "status": "resolved" if decision["final_decision"] != "unresolved" else "unresolved",
    }
    if "resolution" in decision:
        result["resolution"] = copy.deepcopy(decision["resolution"])
    return result


def _study_extractions(reports: list[dict]) -> list[dict]:
    by_field: dict[str, list[tuple[dict, str]]] = defaultdict(list)
    for report in reports:
        for field, value in report["extractions"].items():
            by_field[field].append((value, report["identity"]))
    merged: list[dict] = []
    for field in sorted(by_field):
        rows = by_field[field]
        statuses = {row[0]["status"] for row in rows}
        evidence_refs = sorted({ref for row, _ in rows for ref in row["evidence_refs"]})
        identities = sorted({identity for _, identity in rows})
        values = [_canonical_json(row["value"]) for row, _ in rows if "value" in row]
        if len(statuses) == 1 and (not values or len(set(values)) == 1):
            status = next(iter(statuses))
            item: dict[str, Any] = {
                "field": field,
                "status": status,
                "evidence_refs": evidence_refs,
                "report_identities": identities,
            }
            if status == "present":
                item["value"] = copy.deepcopy(rows[0][0]["value"])
        else:
            status_summary = sorted(statuses)
            item = {
                "field": field,
                "status": "unclear",
                "evidence_refs": evidence_refs,
                "report_identities": identities,
                "note": f"conflicting report-level extraction states: {', '.join(status_summary)}",
            }
        merged.append(item)
    return merged


def _public_report(report: Mapping[str, Any]) -> dict:
    result = {
        "identity": report["identity"],
        "record_id": report["record_id"],
        "retrieval_record_ids": report["retrieval_record_ids"],
        "title": report["title"],
        "document_type": report["document_type"],
        "study_id": report["study_id"],
        "source_tier": report["source_tier"],
        "oracle_rung": report["oracle_rung"],
        "oracle_rungs": report["oracle_rungs"],
        "fulltext_available": report["fulltext"] is not None,
    }
    return result


def build_execution_manifest(
    records: Sequence[Mapping[str, Any]],
    search_logs: Sequence[Mapping[str, Any]],
    *,
    review_id: str,
    oracle_rulebook_version: str,
    claimed_source_count: int | None = None,
) -> dict:
    """Build, semantically validate, and return a deterministic review manifest."""
    review_id = _require_text(review_id, "review_id")
    oracle_rulebook_version = _require_text(oracle_rulebook_version, "oracle_rulebook_version")
    normalized_records = [_normalize_record(row) for row in records]
    record_ids = [row["record_id"] for row in normalized_records]
    if len(record_ids) != len(set(record_ids)):
        raise ValueError("record_id values must be unique retrieval occurrences")
    normalized_logs = _normalize_search_logs(search_logs, set(record_ids))

    grouped: dict[str, list[dict]] = defaultdict(list)
    for row in normalized_records:
        grouped[row["identity"]].append(row)
    canonical_records: list[dict] = []
    duplicate_groups: list[dict] = []
    for identity in sorted(grouped):
        report, duplicate = _merge_duplicate_group(grouped[identity])
        canonical_records.append(report)
        if duplicate:
            duplicate_groups.append(duplicate)

    paper_reports = [row for row in canonical_records if row["is_paper"]]
    non_paper_records = [
        {
            "identity": row["identity"],
            "record_id": row["record_id"],
            "document_type": row["document_type"],
            "reason": "non-paper record excluded before screening",
        }
        for row in canonical_records
        if not row["is_paper"]
    ]

    screening_decisions: list[dict] = []
    conflicts: list[dict] = []
    fulltext_exclusions: list[dict] = []
    included_reports: list[dict] = []
    for report in paper_reports:
        title_decision = report["title_decision"]
        screening_decisions.append(copy.deepcopy(title_decision))
        if title_decision["conflict"]:
            conflicts.append(_conflict_row(title_decision))
        if title_decision["final_decision"] != "include" or report["fulltext"] is None:
            continue
        fulltext_decision = report["fulltext_decision"]
        screening_decisions.append(copy.deepcopy(fulltext_decision))
        if fulltext_decision["conflict"]:
            conflicts.append(_conflict_row(fulltext_decision))
        if fulltext_decision["final_decision"] == "include":
            included_reports.append(report)
        elif fulltext_decision["final_decision"] == "exclude":
            fulltext_exclusions.append(
                {"identity": report["identity"], "reason": report["fulltext_exclusion_reason"]}
            )
    screening_decisions.sort(key=lambda row: (row["identity"], row["stage"]))
    conflicts.sort(key=lambda row: (row["identity"], row["stage"]))
    fulltext_exclusions.sort(key=lambda row: row["identity"])

    for report in included_reports:
        if any(rung not in ORACLE_RUNGS for rung in report["oracle_rungs"]):
            raise ValueError(
                f"included report {report['identity']} must have a classified O0-O5 oracle rung"
            )

    by_study: dict[str, list[dict]] = defaultdict(list)
    for report in included_reports:
        by_study[report["study_id"]].append(report)
    included_studies: list[dict] = []
    for study_id in sorted(by_study):
        reports = sorted(by_study[study_id], key=lambda row: (row["source_tier"], row["identity"]))
        included_studies.append(
            {
                "study_id": study_id,
                "primary_report_identity": reports[0]["identity"],
                "report_identities": sorted(row["identity"] for row in reports),
                "oracle_rungs": sorted(
                    {rung for row in reports for rung in row["oracle_rungs"]}
                ),
                "extractions": _study_extractions(reports),
            }
        )

    tier_counts = dict(sorted(Counter(row["source_tier"] for row in paper_reports).items()))
    source_tier_counts: dict[str, Any] = {
        "basis": "unique_paper_reports_after_deduplication",
        "total": len(paper_reports),
        "by_tier": tier_counts,
        "legacy_claimed_total": claimed_source_count,
        "legacy_scalar_matches": claimed_source_count == len(paper_reports)
        if claimed_source_count is not None
        else None,
    }

    permission_ledger = []
    for report in sorted(paper_reports, key=lambda row: _identity_sort_key(row["identity"])):
        fulltext = report["fulltext"]
        if fulltext is None:
            continue
        permission = fulltext["permission"]
        permission_ledger.append(
            {
                "identity": report["identity"],
                "material_ref": fulltext["ref"],
                "material_sha256": fulltext["sha256"],
                "status": permission["status"],
                "basis": permission["basis"],
                "allowed_uses": permission["allowed_uses"],
                "figure_reuse_allowed": "figure_reuse" in permission["allowed_uses"],
            }
        )

    title_unresolved = sum(
        row["title_decision"]["final_decision"] == "unresolved" for row in paper_reports
    )
    title_excluded = sum(
        row["title_decision"]["final_decision"] == "exclude" for row in paper_reports
    )
    title_included = [
        row for row in paper_reports if row["title_decision"]["final_decision"] == "include"
    ]
    not_retrieved = sum(row["fulltext"] is None for row in title_included)
    assessed = [row for row in title_included if row["fulltext"] is not None]
    fulltext_unresolved = sum(
        row["fulltext_decision"]["final_decision"] == "unresolved" for row in assessed
    )
    prisma: dict[str, int] = {
        "records_identified": len(normalized_records),
        "duplicate_records_removed": len(normalized_records) - len(canonical_records),
        "records_removed_other_reasons": len(non_paper_records),
        "records_screened": len(paper_reports),
        "records_excluded": title_excluded,
        "reports_sought_for_retrieval": len(title_included),
        "reports_not_retrieved": not_retrieved,
        "reports_assessed_for_eligibility": len(assessed),
        "reports_excluded": len(fulltext_exclusions),
        "reports_included": len(included_reports),
        "studies_included": len(included_studies),
    }
    if title_unresolved:
        prisma["records_awaiting_resolution"] = title_unresolved
    if fulltext_unresolved:
        prisma["reports_awaiting_resolution"] = fulltext_unresolved

    search_core = [
        {key: value for key, value in row.items() if key != "log_sha256"}
        for row in normalized_logs
    ]
    manifest: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "review_id": review_id,
        "generated_by": TOOL_VERSION,
        "identity_policy_version": IDENTITY_POLICY_VERSION,
        "oracle_rulebook_version": oracle_rulebook_version,
        "extraction_status_vocabulary": list(EXTRACTION_STATES),
        "search_sources": normalized_logs,
        "reports": [_public_report(row) for row in paper_reports],
        "non_paper_records": sorted(non_paper_records, key=lambda row: row["identity"]),
        "deduplication": {
            "identified_occurrences": len(normalized_records),
            "unique_reports": len(canonical_records),
            "duplicates_removed": len(normalized_records) - len(canonical_records),
            "duplicate_groups": duplicate_groups,
        },
        "screening": {
            "decisions": screening_decisions,
            "conflicts": conflicts,
            "has_unresolved_conflicts": any(row["status"] == "unresolved" for row in conflicts),
            "fulltext_exclusions": fulltext_exclusions,
        },
        "included_studies": included_studies,
        "source_tier_counts": source_tier_counts,
        "permission_ledger": permission_ledger,
        "prisma": prisma,
        "integrity": {
            "input_corpus_sha256": _sha256(
                sorted(normalized_records, key=lambda row: row["record_id"])
            ),
            "search_logs_sha256": _sha256(search_core),
        },
    }
    manifest["integrity"]["manifest_payload_sha256"] = _manifest_payload_sha(manifest)
    validate_manifest(manifest)
    return manifest


def _manifest_payload_sha(manifest: Mapping[str, Any]) -> str:
    payload = copy.deepcopy(dict(manifest))
    integrity = dict(payload.get("integrity") or {})
    integrity.pop("manifest_payload_sha256", None)
    payload["integrity"] = integrity
    return _sha256(payload)


def _schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def validate_manifest(manifest: Mapping[str, Any]) -> None:
    """Validate structural closure, hashes, tier counts, and PRISMA arithmetic."""
    errors = sorted(Draft202012Validator(_schema()).iter_errors(manifest), key=lambda err: list(err.path))
    if errors:
        first = errors[0]
        pointer = "/" + "/".join(str(value) for value in first.path)
        raise ValueError(f"manifest schema validation failed at {pointer}: {first.message}")

    tier_counts = manifest["source_tier_counts"]
    derived_tier_total = sum(tier_counts["by_tier"].values())
    if tier_counts["total"] != derived_tier_total:
        raise ValueError("source tier total does not equal the sum of source-level tier counts")
    observed_tiers = Counter(row["source_tier"] for row in manifest["reports"])
    if dict(sorted(observed_tiers.items())) != tier_counts["by_tier"]:
        raise ValueError("source tier total/counts do not match deduplicated report rows")

    prisma = manifest["prisma"]
    title_waiting = prisma.get("records_awaiting_resolution", 0)
    fulltext_waiting = prisma.get("reports_awaiting_resolution", 0)
    arithmetic = (
        prisma["records_identified"]
        - prisma["duplicate_records_removed"]
        - prisma["records_removed_other_reasons"]
        == prisma["records_screened"]
        and prisma["records_screened"]
        - prisma["records_excluded"]
        - title_waiting
        == prisma["reports_sought_for_retrieval"]
        and prisma["reports_sought_for_retrieval"]
        - prisma["reports_not_retrieved"]
        == prisma["reports_assessed_for_eligibility"]
        and prisma["reports_assessed_for_eligibility"]
        - prisma["reports_excluded"]
        - fulltext_waiting
        == prisma["reports_included"]
        and prisma["studies_included"] == len(manifest["included_studies"])
    )
    if not arithmetic:
        raise ValueError("PRISMA arithmetic is inconsistent with screening and inclusion counts")
    if prisma["records_identified"] != sum(
        row["records_retrieved"] for row in manifest["search_sources"]
    ):
        raise ValueError("PRISMA arithmetic does not match search-source logs")

    known_report_identities = {row["identity"] for row in manifest["reports"]}
    included_report_identities: list[str] = []
    for study in manifest["included_studies"]:
        if study["primary_report_identity"] not in study["report_identities"]:
            raise ValueError(f"study {study['study_id']} primary report is not in its report ledger")
        included_report_identities.extend(study["report_identities"])
    if (
        len(included_report_identities) != len(set(included_report_identities))
        or not set(included_report_identities) <= known_report_identities
        or len(included_report_identities) != prisma["reports_included"]
    ):
        raise ValueError("included report ledger does not match unique screened report rows")
    oracle_rungs_by_identity = {}
    included_identity_set = set(included_report_identities)
    for report in manifest["reports"]:
        rungs = list(report.get("oracle_rungs") or [report["oracle_rung"]])
        if report["identity"] in included_identity_set and (
            report["oracle_rung"] not in ORACLE_RUNGS
            or any(rung not in ORACLE_RUNGS for rung in rungs)
        ):
            raise ValueError(
                f"included report {report['identity']} must have a classified O0-O5 oracle rung"
            )
        expected_primary = sorted(rungs)[-1]
        if report["oracle_rung"] != expected_primary:
            raise ValueError(
                f"report {report['identity']} oracle_rung is not the highest declared protocol rung"
            )
        oracle_rungs_by_identity[report["identity"]] = rungs
    for identity in included_report_identities:
        if any(rung not in ORACLE_RUNGS for rung in oracle_rungs_by_identity[identity]):
            raise ValueError(
                f"included report {identity} must have a classified O0-O5 oracle rung"
            )

    for permission in manifest["permission_ledger"]:
        if permission["identity"] not in known_report_identities:
            raise ValueError("permission ledger references an unknown report identity")
        expected_figure_reuse = "figure_reuse" in permission["allowed_uses"]
        if permission["figure_reuse_allowed"] is not expected_figure_reuse:
            raise ValueError("figure_reuse_allowed does not match the permission allowed_uses ledger")

    search_core = [
        {key: value for key, value in row.items() if key != "log_sha256"}
        for row in manifest["search_sources"]
    ]
    for row, core in zip(manifest["search_sources"], search_core):
        if row["log_sha256"] != _sha256(core):
            raise ValueError(f"search-source log hash mismatch for {row['source_id']}")
    if manifest["integrity"]["search_logs_sha256"] != _sha256(search_core):
        raise ValueError("aggregate search-source log hash mismatch")
    if manifest["integrity"]["manifest_payload_sha256"] != _manifest_payload_sha(manifest):
        raise ValueError("manifest payload hash mismatch")


def write_manifest(path: str | Path, manifest: Mapping[str, Any]) -> Path:
    """Validate and write canonical, stable UTF-8 JSON."""
    validate_manifest(manifest)
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    return destination


def _load_input(path: str | Path) -> dict:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("input JSON must be an object")
    return value


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, help="JSON with review metadata, records, and search_logs")
    parser.add_argument("--output", required=True, help="validated execution manifest path")
    args = parser.parse_args(list(argv) if argv is not None else None)
    source = _load_input(args.input)
    manifest = build_execution_manifest(
        source.get("records") or [],
        source.get("search_logs") or [],
        review_id=source.get("review_id"),
        oracle_rulebook_version=source.get("oracle_rulebook_version"),
        claimed_source_count=source.get("claimed_source_count"),
    )
    write_manifest(args.output, manifest)
    print(
        json.dumps(
            {
                "output": str(Path(args.output)),
                "manifest_sha256": manifest["integrity"]["manifest_payload_sha256"],
                "unique_reports": manifest["deduplication"]["unique_reports"],
                "included_studies": manifest["prisma"]["studies_included"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised through the CLI entry point
    raise SystemExit(main())
