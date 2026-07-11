"""Derive source strength from explicit methodology review evidence.

``rigor_score`` remains a backwards-compatible ranking hint, but it is never
used here.  A current source earns strength only from categorical methodology
judgements and locators that make the judgement inspectable.
"""
from __future__ import annotations

from typing import Optional


QUALITY_CONTRACT_VERSION = "source-methodology/v1"
LEGACY_UNVERIFIED = "LEGACY_UNVERIFIED"

_METHODOLOGY_DIMENSIONS = (
    "design_appropriateness",
    "bias_control",
    "measurement_validity",
    "statistical_validity",
    "reproducibility",
)
_EVALUATION_DIMENSIONS = (
    "sample_adequacy",
    "evaluation_independence",
    "comparator_fairness",
    "uncertainty_reporting",
)
_LEVEL = {"strong": 3, "adequate": 2, "weak": 1, "unclear": 0}


def _normal(value: object) -> str:
    return str(value or "").strip().lower()


def _inspectable_evidence_refs(row: dict) -> list[dict]:
    valid: list[dict] = []
    for item in row.get("evidence_refs") or []:
        if not isinstance(item, dict):
            continue
        if not str(item.get("evidence_ref") or "").strip():
            continue
        if not str(item.get("locator") or "").strip():
            continue
        if not (
            str(item.get("exact_quote") or "").strip()
            or str(item.get("reported_result") or "").strip()
        ):
            continue
        valid.append(item)
    return valid


def _dimension_values(row: dict) -> tuple[list[str], list[str], list[str]]:
    methodology = row.get("methodology_review") or {}
    evaluation = row.get("sample_evaluation_review") or {}
    values: list[str] = []
    missing: list[str] = []
    invalid: list[str] = []
    for key in _METHODOLOGY_DIMENSIONS:
        value = _normal(methodology.get(key))
        if not value:
            missing.append(f"methodology_review.{key}")
        elif value != "not-applicable" and value not in _LEVEL:
            invalid.append(f"methodology_review.{key}")
        else:
            values.append(value)
    for key in _EVALUATION_DIMENSIONS:
        value = _normal(evaluation.get(key))
        if not value:
            missing.append(f"sample_evaluation_review.{key}")
        elif value != "not-applicable" and value not in _LEVEL:
            invalid.append(f"sample_evaluation_review.{key}")
        else:
            values.append(value)
    return values, missing, invalid


def audit_source(row: dict) -> dict:
    """Return an inspectable categorical strength assessment for one source."""
    source_ref = str(row.get("source_ref") or "")
    review_status = _normal(row.get("review_status"))
    directness = _normal(row.get("directness"))
    applicability = _normal(row.get("applicability"))
    study_design = _normal(row.get("study_design"))
    evidence_refs = _inspectable_evidence_refs(row)
    values, missing, invalid = _dimension_values(row)
    applicable_values = [_LEVEL[value] for value in values if value != "not-applicable"]

    reasons: list[str] = []
    if review_status not in {"verified", "partial"}:
        reasons.append("source methodology review is not verified")
    if not study_design:
        reasons.append("study design is not classified")
    if directness not in {"direct", "indirect", "background"}:
        reasons.append("directness is not classified")
    if applicability not in {"direct", "partial", "indirect", "unclear"}:
        reasons.append("applicability is not classified")
    if not evidence_refs:
        reasons.append("no inspectable evidence ref with locator and quote/result")
    if missing:
        reasons.append("missing dimensions: " + ", ".join(sorted(missing)))
    if invalid:
        reasons.append("invalid dimensions: " + ", ".join(sorted(invalid)))
    if len(applicable_values) < 4:
        reasons.append("fewer than four applicable methodology/evaluation dimensions")

    complete = not missing and not invalid and len(applicable_values) >= 4
    no_weak_or_unclear = complete and all(value >= 2 for value in applicable_values)
    at_most_one_weak = complete and sum(value < 2 for value in applicable_values) <= 1

    if (
        review_status == "verified"
        and directness == "direct"
        and applicability == "direct"
        and evidence_refs
        and no_weak_or_unclear
    ):
        strength = "HIGH"
    elif (
        review_status in {"verified", "partial"}
        and directness in {"direct", "indirect"}
        and applicability in {"direct", "partial"}
        and evidence_refs
        and at_most_one_weak
    ):
        strength = "MODERATE"
    elif review_status in {"verified", "partial"} and evidence_refs and complete:
        strength = "LOW"
    else:
        strength = "UNVERIFIED"

    if strength == "HIGH":
        reasons.append("all applicable methodology and evaluation dimensions are adequate or strong")
    elif strength == "MODERATE":
        reasons.append("review is inspectable but indirect, partially applicable, or has one weak dimension")
    elif strength == "LOW":
        reasons.append("inspectable review contains material methodology or applicability weaknesses")

    return {
        "source_ref": source_ref,
        "derived_strength": strength,
        "review_status": review_status or "unverified",
        "directness": directness or "unclassified",
        "applicability": applicability or "unclassified",
        "n_applicable_dimensions": len(applicable_values),
        "n_inspectable_evidence_refs": len(evidence_refs),
        "reasons": reasons,
    }


def audit_source_quality_report(
    report: Optional[dict],
    evidence_table: Optional[dict] = None,
) -> dict:
    """Audit a report without trusting its rank or scalar rigor score.

    Reports without ``source-methodology/v1`` remain readable, but are marked
    ``LEGACY_UNVERIFIED`` and cannot establish current high-rigor evidence.
    """
    payload = report or {}
    rows = [row for row in (payload.get("ranked_sources") or []) if isinstance(row, dict)]
    if payload.get("quality_contract_version") != QUALITY_CONTRACT_VERSION:
        return {
            "contract_status": LEGACY_UNVERIFIED,
            "audit_status": LEGACY_UNVERIFIED,
            "assessments": [
                {
                    "source_ref": str(row.get("source_ref") or ""),
                    "derived_strength": "UNVERIFIED",
                    "reasons": ["legacy report has no source-methodology/v1 review"],
                }
                for row in rows
            ],
            "n_high": 0,
            "n_moderate": 0,
            "n_low": 0,
            "n_unverified": len(rows),
            "missing_source_refs": [],
            "reasons": ["source quality is LEGACY_UNVERIFIED"],
        }

    assessments = [audit_source(row) for row in rows]
    seen_refs = [assessment["source_ref"] for assessment in assessments if assessment["source_ref"]]
    duplicates = sorted({ref for ref in seen_refs if seen_refs.count(ref) > 1})
    table_refs: list[str] = []
    for source in (evidence_table or {}).get("sources") or []:
        if not isinstance(source, dict):
            continue
        table_refs.append(str(source.get("ref") or source.get("id") or ""))
    missing_refs = sorted(ref for ref in table_refs if ref and ref not in set(seen_refs))
    unverified = [a for a in assessments if a["derived_strength"] == "UNVERIFIED"]

    reasons: list[str] = []
    if _normal(payload.get("review_status")) != "current":
        reasons.append("report review_status is not CURRENT")
    if duplicates:
        reasons.append("duplicate source reviews: " + ", ".join(duplicates))
    if missing_refs:
        reasons.append("evidence sources lack methodology review: " + ", ".join(missing_refs))
    if unverified:
        reasons.append(f"{len(unverified)} source review(s) remain UNVERIFIED")

    return {
        "contract_status": "CURRENT",
        "audit_status": "PASS" if not reasons else "INCOMPLETE",
        "assessments": assessments,
        "n_high": sum(a["derived_strength"] == "HIGH" for a in assessments),
        "n_moderate": sum(a["derived_strength"] == "MODERATE" for a in assessments),
        "n_low": sum(a["derived_strength"] == "LOW" for a in assessments),
        "n_unverified": len(unverified),
        "missing_source_refs": missing_refs,
        "reasons": reasons,
    }
