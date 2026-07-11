"""Derive semantic evidence-search completion from a question/search trace."""
from __future__ import annotations

from typing import Optional


SEARCH_TRACE_VERSION = "evidence-search-trace/v1"
LEGACY_UNVERIFIED = "LEGACY_UNVERIFIED"
MIN_ROUNDS = 3
TRAILING_LOW_GAIN_ROUNDS = 2
MARGINAL_GAIN_THRESHOLD = 0.10
MIN_UNIQUE_SOURCES = 3


def _items(values: object) -> set[str]:
    return {str(value).strip() for value in (values or []) if str(value).strip()}


def _source_identity(hit: dict) -> str:
    source_hash = str(hit.get("source_hash") or "").strip().lower()
    return f"sha256:{source_hash}" if source_hash else f"ref:{str(hit.get('source_ref') or '').strip()}"


def evaluate_search_trace(trace: Optional[dict]) -> dict:
    """Recompute completion; never consume a worker-provided saturation verdict."""
    payload = trace or {}
    if payload.get("search_contract_version") != SEARCH_TRACE_VERSION:
        return {
            "contract_status": LEGACY_UNVERIFIED,
            "status": LEGACY_UNVERIFIED,
            "semantic_complete": False,
            "round_information_gain": [],
            "n_unique_sources": 0,
            "critical_claim_coverage": 0.0,
            "contradiction_coverage": 0.0,
            "representativeness_coverage": 0.0,
            "reasons": ["search completion is LEGACY_UNVERIFIED"],
        }

    critical_claims = {
        str(row.get("claim_id") or "").strip()
        for row in payload.get("critical_claims") or []
        if isinstance(row, dict) and str(row.get("claim_id") or "").strip()
    }
    dimensions = _items(payload.get("representativeness_dimensions"))
    rounds = [row for row in (payload.get("rounds") or []) if isinstance(row, dict)]
    seen_sources: set[str] = set()
    seen_source_refs: set[str] = set()
    seen_findings: set[str] = set()
    covered_claims: set[str] = set()
    contradiction_claims: set[str] = set()
    covered_dimensions: set[str] = set()
    gains: list[float] = []
    reasons: list[str] = []

    indices = [row.get("round_index") for row in rounds]
    if indices != list(range(len(rounds))):
        reasons.append("round_index must be contiguous and chronological from zero")

    for round_row in rounds:
        source_hits = [row for row in (round_row.get("source_hits") or []) if isinstance(row, dict)]
        round_refs = {
            str(row.get("source_ref") or "").strip()
            for row in source_hits
            if str(row.get("source_ref") or "").strip()
        }
        round_identities = {_source_identity(row) for row in source_hits if _source_identity(row) != "ref:"}
        new_sources = round_identities - seen_sources
        seen_sources.update(round_identities)
        seen_source_refs.update(round_refs)

        addressed = _items(round_row.get("claim_ids_addressed")) & critical_claims
        contradiction = _items(round_row.get("contradiction_claim_ids_queried")) & critical_claims
        dimension_hits = _items(round_row.get("representativeness_dimensions_queried")) & dimensions

        valid_finding_ids: set[str] = set()
        finding_claims: set[str] = set()
        for finding in round_row.get("findings") or []:
            if not isinstance(finding, dict):
                continue
            finding_id = str(finding.get("finding_id") or "").strip()
            refs = _items(finding.get("source_refs"))
            if not finding_id or not refs or not refs.issubset(seen_source_refs):
                reasons.append(f"finding {finding_id or '<missing>'} is not grounded in a seen source ref")
                continue
            valid_finding_ids.add(finding_id)
            finding_claims.update(_items(finding.get("claim_ids")) & critical_claims)

        newly_covered_claims = (addressed & finding_claims) - covered_claims
        new_contradiction = contradiction - contradiction_claims
        new_dimensions = dimension_hits - covered_dimensions
        new_findings = valid_finding_ids - seen_findings
        numerator = (
            len(new_sources)
            + 2 * len(new_findings)
            + 3 * len(newly_covered_claims)
            + 2 * len(new_contradiction)
            + len(new_dimensions)
        )
        opportunity = max(
            1,
            len(round_identities)
            + 2 * len(valid_finding_ids)
            + 3 * len(critical_claims)
            + 2 * len(critical_claims)
            + len(dimensions),
        )
        gains.append(round(numerator / opportunity, 6))
        covered_claims.update(addressed & finding_claims)
        contradiction_claims.update(contradiction)
        covered_dimensions.update(dimension_hits)
        seen_findings.update(valid_finding_ids)

    def coverage(covered: set[str], required: set[str]) -> float:
        return round(len(covered & required) / len(required), 6) if required else 0.0

    claim_coverage = coverage(covered_claims, critical_claims)
    contradiction_coverage = coverage(contradiction_claims, critical_claims)
    dimension_coverage = coverage(covered_dimensions, dimensions)
    if len(rounds) < MIN_ROUNDS:
        reasons.append(f"too few query rounds: {len(rounds)} < {MIN_ROUNDS}")
    if len(seen_sources) < MIN_UNIQUE_SOURCES:
        reasons.append(f"too few unique source hashes/refs: {len(seen_sources)} < {MIN_UNIQUE_SOURCES}")
    if claim_coverage < 1.0:
        reasons.append("critical claims are not all covered by grounded findings")
    if contradiction_coverage < 1.0:
        reasons.append("counterevidence queries do not cover every critical claim")
    if dimension_coverage < 1.0:
        reasons.append("representativeness dimensions are not fully covered")
    trailing = gains[-TRAILING_LOW_GAIN_ROUNDS:]
    if len(trailing) < TRAILING_LOW_GAIN_ROUNDS or any(
        gain > MARGINAL_GAIN_THRESHOLD for gain in trailing
    ):
        reasons.append("marginal information gain has not stayed low for the trailing rounds")

    stop_reason = str(payload.get("stop_reason") or "").strip().lower()
    budget_exhausted = bool(payload.get("budget_exhausted")) or stop_reason == "budget_exhausted"
    if stop_reason != "semantic_complete":
        reasons.append(f"stop_reason is {stop_reason or 'missing'}, not semantic_complete")
    if budget_exhausted:
        reasons.append("budget exhaustion is not evidence saturation")

    if budget_exhausted or stop_reason in {"source_access_blocked", "human_stop"}:
        status = "NEEDS_HUMAN"
    elif reasons:
        status = "INCOMPLETE"
    else:
        status = "COMPLETE"

    return {
        "contract_status": "CURRENT",
        "status": status,
        "semantic_complete": status == "COMPLETE",
        "round_information_gain": gains,
        "n_unique_sources": len(seen_sources),
        "critical_claim_coverage": claim_coverage,
        "contradiction_coverage": contradiction_coverage,
        "representativeness_coverage": dimension_coverage,
        "reasons": reasons,
    }
