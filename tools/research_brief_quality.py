"""Deterministic evidence grading and Markdown lint for research briefings."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .evidence_search_trace import SEARCH_TRACE_VERSION, evaluate_search_trace
from .source_methodology_audit import QUALITY_CONTRACT_VERSION, audit_source_quality_report


SUPPORTED_MODES = {"evidence_review", "evidence_deep", "deep_research"}

REQUIRED_HEADINGS = (
    "## Bottom Line",
    "## Evidence Grade And Source Quality",
    "## Claim-Evidence Ledger",
    "## Contradictions And Counterevidence",
    "## Belief Update",
    "## Decision Implications",
    "## Critical Uncertainties",
    "## Next Most Valuable Evidence",
    "## Evidence Pointers",
)

GRADE_ORDER = {"INSUFFICIENT": 0, "LIMITED": 1, "MODERATE": 2, "HIGH": 3}


@dataclass(frozen=True)
class EvidenceAssessment:
    grade: str
    posture: str
    rationale: str
    n_sources: int
    n_strong: int
    n_claims: int
    n_mapped: int
    n_direct_loci: int
    n_peer_reviewed: int
    n_ranked_sources: int
    n_existence_warnings: int
    n_unresolved_conflicts: int
    n_major_gaps: int
    source_quality_status: str
    search_completion_status: str


def one_line(value: object) -> str:
    return " ".join(str(value or "").replace("`", "'").split())


def noun(count: int, singular: str, plural: Optional[str] = None) -> str:
    return singular if count == 1 else (plural or f"{singular}s")


def mapping_index(claim_evidence_map: dict) -> dict[str, dict]:
    return {
        str(mapping.get("claim_id")): mapping
        for mapping in (claim_evidence_map.get("mappings") or [])
        if isinstance(mapping, dict) and mapping.get("claim_id")
    }


def conflicts(contradiction_report: Optional[dict]) -> list[dict]:
    return [
        row for row in ((contradiction_report or {}).get("conflicts") or [])
        if isinstance(row, dict)
    ]


def source_quality_coverage(
    evidence_table: dict,
    source_quality_report: Optional[dict],
) -> tuple[int, list[str]]:
    ranked_refs = {
        str(row.get("source_ref"))
        for row in ((source_quality_report or {}).get("ranked_sources") or [])
        if isinstance(row, dict) and row.get("source_ref")
    }
    covered = 0
    missing: list[str] = []
    for source in evidence_table.get("sources") or []:
        candidates = {str(source.get("id") or ""), str(source.get("ref") or "")}
        if candidates & ranked_refs:
            covered += 1
        else:
            missing.append(str(source.get("ref") or source.get("id") or "not-recorded"))
    return covered, missing


def gaps(landscape_map: Optional[dict], research_brief: Optional[dict]) -> list[dict]:
    rows = [
        dict(row) for row in ((landscape_map or {}).get("coverage_gaps") or [])
        if isinstance(row, dict)
    ]
    known = {one_line(row.get("description")).casefold() for row in rows}
    for i, text in enumerate((research_brief or {}).get("evidence_gaps") or [], start=1):
        description = one_line(text)
        if description and description.casefold() not in known:
            rows.append({
                "gap_id": f"research-gap-{i}",
                "description": description,
                "gap_kind": "other",
                "severity": "major",
            })
            known.add(description.casefold())
    return rows


def claim_support(mapping: dict) -> str:
    loci = [row for row in (mapping.get("loci") or []) if isinstance(row, dict)]
    if any(row.get("supports_claim") is False for row in loci):
        return "contradicted"
    support = str(mapping.get("overall_support") or "").strip().lower()
    if support in {"supported", "partial", "contradicted", "not-found"}:
        return support
    return "supported" if loci and all(row.get("supports_claim") is True for row in loci) else "not-found"


def belief_movement(mapping: dict) -> str:
    support = claim_support(mapping)
    loci = mapping.get("loci") or []
    direct = any(row.get("directness") == "direct" for row in loci if isinstance(row, dict))
    risk = str((mapping.get("claim_risk") or {}).get("level") or "").lower()
    if support == "contradicted":
        return "Decrease"
    if support == "not-found":
        return "Hold"
    if support == "partial":
        return "Increase slightly"
    if direct and risk in {"", "low"}:
        return "Increase"
    return "Increase, but keep bounded"


def assess_evidence(
    evidence_table: dict,
    claim_list: dict,
    claim_evidence_map: dict,
    source_quality_report: Optional[dict],
    contradiction_report: Optional[dict],
    landscape_map: Optional[dict],
    research_brief: Optional[dict],
    report: dict,
    search_trace: Optional[dict] = None,
) -> EvidenceAssessment:
    sources = [row for row in (evidence_table.get("sources") or []) if isinstance(row, dict)]
    claims = [row for row in (claim_list.get("claims") or []) if isinstance(row, dict)]
    mappings = mapping_index(claim_evidence_map)
    ranked = [
        row for row in ((source_quality_report or {}).get("ranked_sources") or [])
        if isinstance(row, dict)
    ]
    conflict_rows = conflicts(contradiction_report)
    gap_rows = gaps(landscape_map, research_brief)

    source_audit = audit_source_quality_report(source_quality_report, evidence_table)
    search_audit = evaluate_search_trace(search_trace)
    strict_current = bool(
        evidence_table.get("evidence_contract_version") == "evidence-table/v2"
        or (source_quality_report or {}).get("quality_contract_version") == QUALITY_CONTRACT_VERSION
        or (search_trace or {}).get("search_contract_version") == SEARCH_TRACE_VERSION
    )
    source_quality_current = (
        source_audit.get("contract_status") == "CURRENT"
        and source_audit.get("audit_status") == "PASS"
    )
    semantic_search_complete = search_audit.get("status") == "COMPLETE"
    if strict_current:
        n_strong = int(source_audit.get("n_high") or 0)
    else:
        n_strong = sum(row.get("claim_support") == "strong" for row in sources)
    n_direct = sum(
        row.get("directness") == "direct" and row.get("supports_claim") is True
        for mapping in mappings.values()
        for row in (mapping.get("loci") or [])
        if isinstance(row, dict)
    )
    if strict_current:
        high_refs = {
            str(row.get("source_ref") or "")
            for row in source_audit.get("assessments") or []
            if row.get("derived_strength") == "HIGH"
        }
        n_peer = sum(
            row.get("tier") == "peer-reviewed" and str(row.get("source_ref") or "") in high_refs
            for row in ranked
        )
    else:
        n_peer = sum(
            row.get("tier") == "peer-reviewed" and float(row.get("rigor_score") or 0) >= 0.7
            for row in ranked
        )
    n_ranked, unranked_refs = source_quality_coverage(evidence_table, source_quality_report)
    n_existence_warnings = int(report.get("existence_warnings") or 0)
    n_unresolved = sum(
        row.get("resolution_status", "unresolved") == "unresolved" for row in conflict_rows
    )
    n_major = sum(row.get("severity") in {"major", "critical"} for row in gap_rows)
    support_states = [claim_support(mappings.get(str(claim.get("claim_id"))) or {}) for claim in claims]
    n_high_risk = sum(
        str(((mappings.get(str(claim.get("claim_id"))) or {}).get("claim_risk") or {}).get("level"))
        == "high"
        for claim in claims
    )
    strict_attribution = claim_evidence_map.get("attribution_contract_version") == "claim-span/v1"
    attribution_gate = str(report.get("citation_attribution_gate") or "")
    attribution_complete = (
        strict_attribution
        and attribution_gate == "PASS"
        and float(report.get("citation_correctness") or 0) == 1.0
        and float(report.get("claim_completeness") or 0) == 1.0
    )

    search_floor = semantic_search_complete if strict_current else bool(
        evidence_table.get("saturation_reached")
    )
    source_floor = source_quality_current if strict_current else True
    structural_floor = (
        len(sources) >= 3
        and n_strong >= 1
        and search_floor
        and source_floor
        and len(mappings) >= len(claims)
        and bool(claims)
    )
    if not structural_floor:
        grade = "INSUFFICIENT"
    elif strict_attribution and not attribution_complete:
        grade = "LIMITED"
    elif n_existence_warnings > 0 or (ranked and unranked_refs):
        grade = "LIMITED"
    elif not ranked:
        grade = "LIMITED"
    elif (
        source_quality_current
        and semantic_search_complete
        and n_peer >= 2
        and n_direct >= 2
        and all(state == "supported" for state in support_states)
        and n_unresolved == 0
        and n_major == 0
        and n_high_risk == 0
    ):
        grade = "HIGH"
    elif n_peer >= 1 and n_direct >= 1 and n_unresolved == 0 and n_high_risk == 0:
        grade = "MODERATE"
    else:
        grade = "LIMITED"

    if grade in {"INSUFFICIENT", "LIMITED"} or n_unresolved or any(
        row.get("severity") == "critical" for row in gap_rows
    ):
        posture = "HOLD"
    elif n_major or any(state in {"partial", "not-found"} for state in support_states):
        posture = "RUN-DISCRIMINATING-TEST"
    else:
        posture = "PROVISIONAL-GO"

    rationale = (
        f"{len(sources)} sources ({n_strong} strong); {len(mappings)}/{len(claims)} claims mapped; "
        f"{n_direct} direct supporting {noun(n_direct, 'locus', 'loci')}; "
        f"{n_peer} high-rigor peer-reviewed {noun(n_peer, 'source')}; "
        f"ranked source coverage={n_ranked}/{len(sources)}; "
        f"source existence warnings={n_existence_warnings}; "
        f"independent span attribution={attribution_gate or 'LEGACY_UNVERIFIED'}; "
        f"citation correctness={report.get('citation_correctness')}; "
        f"claim completeness={report.get('claim_completeness')}; "
        f"{n_unresolved} unresolved {noun(n_unresolved, 'conflict')}; "
        f"{n_major} major/critical evidence {noun(n_major, 'gap')}; "
        f"source methodology={source_audit.get('audit_status') or 'LEGACY_UNVERIFIED'}; "
        f"search completion={search_audit.get('status') or 'LEGACY_UNVERIFIED'}; "
        f"legacy saturation mirror={bool(evidence_table.get('saturation_reached'))}."
    )
    return EvidenceAssessment(
        grade=grade,
        posture=posture,
        rationale=rationale,
        n_sources=len(sources),
        n_strong=n_strong,
        n_claims=len(claims),
        n_mapped=len(mappings),
        n_direct_loci=n_direct,
        n_peer_reviewed=n_peer,
        n_ranked_sources=n_ranked,
        n_existence_warnings=n_existence_warnings,
        n_unresolved_conflicts=n_unresolved,
        n_major_gaps=n_major,
        source_quality_status=str(source_audit.get("audit_status") or "LEGACY_UNVERIFIED"),
        search_completion_status=str(search_audit.get("status") or "LEGACY_UNVERIFIED"),
    )


def _section(text: str, heading: str) -> str:
    start = text.find(heading)
    if start < 0:
        return ""
    start += len(heading)
    end = text.find("\n## ", start)
    return text[start:] if end < 0 else text[start:end]


def lint_research_brief_markdown(
    markdown: str,
    *,
    mode: str,
    claim_list: dict,
    claim_evidence_map: dict,
    source_quality_report: Optional[dict] = None,
    contradiction_report: Optional[dict] = None,
    perspective_ids: Optional[list[str]] = None,
) -> list[str]:
    """Fail closed when the human brief drops decision-critical evidence."""
    errors: list[str] = []
    if mode not in SUPPORTED_MODES:
        errors.append(f"unsupported mode: {mode}")
    if not isinstance(markdown, str) or not markdown.strip():
        return errors + ["Markdown brief is empty"]

    positions = []
    for heading in REQUIRED_HEADINGS:
        if heading not in markdown:
            errors.append(f"missing heading: {heading}")
        else:
            positions.append(markdown.index(heading))
    if positions != sorted(positions):
        errors.append("required briefing headings are out of order")
    if mode == "deep_research" and "## Perspective Synthesis" not in markdown:
        errors.append("missing heading: ## Perspective Synthesis")
    if not any(f"Evidence grade: `{grade}`" in markdown for grade in GRADE_ORDER):
        errors.append("missing deterministic evidence grade")

    section_semantics = {
        "## Bottom Line": ("Evidence grade:", "Decision posture:", "Most valuable next evidence:"),
        "## Evidence Grade And Source Quality": ("Grade basis:", "Scale:", "### Source Register"),
        "## Belief Update": ("Starting position:", "Net update:"),
        "## Decision Implications": ("For the current project/idea/experiment", "Human boundary:"),
        "## Next Most Valuable Evidence": ("Target:", "Why this is highest value:",
                                            "Decision it unlocks:", "Minimum standard:"),
    }
    for heading, phrases in section_semantics.items():
        section = _section(markdown, heading)
        for phrase in phrases:
            if phrase not in section:
                errors.append(f"{heading} missing semantic: {phrase}")

    mappings = mapping_index(claim_evidence_map)
    for claim in claim_list.get("claims") or []:
        cid = str(claim.get("claim_id") or "")
        if f"### `{one_line(cid)}`" not in markdown:
            errors.append(f"Markdown brief omits claim heading: {cid}")
        mapping = mappings.get(cid) or {}
        for locus in mapping.get("loci") or []:
            for label, value in (
                ("source_ref", locus.get("source_ref")),
                ("location", locus.get("location")),
                ("reported_result", locus.get("reported_result")),
            ):
                rendered = one_line(value)
                if rendered and rendered not in markdown:
                    errors.append(f"claim {cid} omits locus {label}: {rendered}")

    ranked = (source_quality_report or {}).get("ranked_sources") or []
    for source in ranked:
        ref = one_line(source.get("source_ref"))
        if ref and ref not in markdown:
            errors.append(f"Markdown brief omits ranked source: {ref}")
    if not ranked and "source quality was not independently ranked" not in markdown:
        errors.append("lightweight brief hides the missing independent source-quality rank")

    conflict_rows = conflicts(contradiction_report)
    for conflict in conflict_rows:
        conflict_id = one_line(conflict.get("conflict_id"))
        if conflict_id and conflict_id not in markdown:
            errors.append(f"Markdown brief omits conflict: {conflict_id}")
    if not conflict_rows and "not evidence of absence" not in markdown:
        errors.append("brief turns no recorded conflict into an unsupported absence claim")

    for pid in perspective_ids or []:
        if f"### `{one_line(pid)}`" not in markdown:
            errors.append(f"Markdown brief omits perspective: {pid}")

    minimum_sections = {
        "## Bottom Line": 220,
        "## Evidence Grade And Source Quality": 450,
        "## Contradictions And Counterevidence": 120,
        "## Belief Update": 180,
        "## Decision Implications": 260,
        "## Critical Uncertainties": 40,
        "## Next Most Valuable Evidence": 220,
    }
    for heading, minimum in minimum_sections.items():
        if len(_section(markdown, heading).strip()) < minimum:
            errors.append(f"{heading} is too thin to guide a research decision")

    minimum = 1800 if mode in {"evidence_deep", "deep_research"} else 1400
    if len(markdown.strip()) < minimum:
        errors.append(f"{mode} Markdown brief is too short to be decision-useful")
    return errors
