"""Deterministic director-facing Markdown for evidence and research modes.

The worker bundles and typed artifacts remain the evidence of record. This module
turns those already-validated structures into a decision-grade human brief. It
does not create claims, approve a project decision, or write to the vault.
"""
from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Iterable, Optional

from .research_brief_quality import (
    REQUIRED_HEADINGS,
    EvidenceAssessment,
    assess_evidence as _assess,
    belief_movement as _belief_movement,
    claim_support as _claim_support,
    conflicts as _conflicts,
    gaps as _gaps,
    lint_research_brief_markdown,
    mapping_index as _mapping_index,
    noun as _noun,
    one_line as _one_line,
    source_quality_coverage as _source_quality_coverage,
)
from .evidence_search_trace import evaluate_search_trace
from .source_methodology_audit import audit_source_quality_report

__all__ = [
    "BRIEF_PATHS",
    "REQUIRED_HEADINGS",
    "brief_path",
    "build_research_brief_markdown",
    "lint_research_brief_markdown",
    "write_research_brief_markdown",
]


BRIEF_PATHS = {
    "evidence_review": Path("director-review") / "evidence" / "evidence-review-brief.md",
    "evidence_deep": Path("director-review") / "evidence" / "evidence-deep-brief.md",
    "deep_research": Path("director-review") / "research" / "research-brief.md",
}

def brief_path(run_dir, mode: str) -> Path:
    if mode not in BRIEF_PATHS:
        raise ValueError(f"unsupported research briefing mode: {mode!r}")
    return Path(run_dir) / BRIEF_PATHS[mode]


def _code(value: object) -> str:
    return f"`{_one_line(value) or 'not-recorded'}`"


def _list(values: Iterable[object] | None) -> list[str]:
    return [_one_line(value) for value in (values or []) if _one_line(value)]


def _dedupe(values: Iterable[object]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = _one_line(value)
        key = text.casefold()
        if text and key not in seen:
            seen.add(key)
            out.append(text)
    return out


def _strongest_claim(claims: list[dict], mappings: dict[str, dict]) -> Optional[dict]:
    def key(claim: dict) -> tuple[int, int, int]:
        mapping = mappings.get(str(claim.get("claim_id"))) or {}
        support = _claim_support(mapping)
        direct = any(row.get("directness") == "direct" for row in (mapping.get("loci") or []))
        confidence = {"high": 2, "medium": 1, "low": 0}.get(str(claim.get("confidence")), 1)
        return ({"supported": 3, "partial": 2, "not-found": 1, "contradicted": 0}[support],
                int(direct), confidence)

    return max(claims, key=key) if claims else None


def _bottom_line(
    assessment: EvidenceAssessment,
    claims: list[dict],
    mappings: dict[str, dict],
    conflicts: list[dict],
    gaps: list[dict],
    research_brief: Optional[dict],
) -> str:
    authored = _one_line((research_brief or {}).get("bottom_line"))
    if authored:
        core = authored
    else:
        strongest = _strongest_claim(claims, mappings)
        if strongest:
            core = f"The strongest current update is: {_one_line(strongest.get('text'))}."
        else:
            core = "The available evidence does not yet support a decision-relevant claim."

    qualifier = ""
    partial = next(
        (claim for claim in claims if _claim_support(mappings.get(str(claim.get("claim_id"))) or {}) == "partial"),
        None,
    )
    unresolved = next(
        (row for row in conflicts if row.get("resolution_status", "unresolved") == "unresolved"),
        None,
    )
    if unresolved:
        qualifier = f" The main blocker is unresolved conflict {_code(unresolved.get('conflict_id'))}: {_one_line(unresolved.get('description'))}."
    elif gaps:
        qualifier = f" The main boundary is {_code(gaps[0].get('gap_id'))}: {_one_line(gaps[0].get('description'))}."
    elif partial:
        qualifier = f" The main boundary is partial support for {_code(partial.get('claim_id'))}."
    return f"{core}{qualifier} Evidence grade is {assessment.grade}."


def _next_evidence(
    assessment: EvidenceAssessment,
    claims: list[dict],
    mappings: dict[str, dict],
    conflicts: list[dict],
    gaps: list[dict],
    evidence_table: dict,
    source_quality_report: Optional[dict],
    research_brief: Optional[dict],
    report: dict,
    search_trace: Optional[dict],
) -> tuple[str, str, str]:
    existence_warnings = int(report.get("existence_warnings") or 0)
    search_audit = evaluate_search_trace(search_trace)
    _n_ranked, unranked_refs = _source_quality_coverage(evidence_table, source_quality_report)
    unresolved = next(
        (row for row in conflicts if row.get("resolution_status", "unresolved") == "unresolved"),
        None,
    )
    current_search_required = bool(
        evidence_table.get("evidence_contract_version") == "evidence-table/v2"
        or (search_trace or {}).get("search_contract_version") == "evidence-search-trace/v1"
    )
    if current_search_required and search_audit.get("status") != "COMPLETE":
        target = (
            "Complete the semantic evidence search for uncovered critical claims, counterevidence, "
            "and representativeness dimensions"
        )
        why = (
            "The search trace is not deterministically complete, so retrieval miss risk currently "
            "dominates downstream interpretation."
        )
    elif existence_warnings:
        target = (
            f"Resolve {existence_warnings} source-existence {_noun(existence_warnings, 'warning')} by "
            "retrieving and validating the cited record or full text"
        )
        why = "An unverified source identity makes every downstream quality and claim judgment provisional."
    elif unresolved:
        target = (
            f"Run a protocol-matched adjudication of {_code(unresolved.get('claim_ref_a'))} versus "
            f"{_code(unresolved.get('claim_ref_b'))}: {_one_line(unresolved.get('description'))}"
        )
        why = "It resolves the explicit contradiction that currently caps the conclusion."
    elif source_quality_report is not None and unranked_refs:
        target = (
            "Complete independent source-quality ranking for "
            + ", ".join(_code(ref) for ref in unranked_refs)
        )
        why = "Unranked sources can silently dominate a conclusion without a recorded rigor or recency judgment."
    else:
        questions = _list((research_brief or {}).get("actionable_next_questions"))
        if questions:
            target = questions[0]
            why = "The perspective panel identified this as the shortest path to a decision-changing update."
        elif gaps:
            target = f"Obtain or run evidence that closes {_code(gaps[0].get('gap_id'))}: {_one_line(gaps[0].get('description'))}"
            why = "This is the highest-severity recorded gap in the current evidence landscape."
        else:
            weak_claim = next(
                (claim for claim in claims
                 if _claim_support(mappings.get(str(claim.get("claim_id"))) or {}) != "supported"),
                _strongest_claim(claims, mappings),
            )
            if weak_claim:
                target = (
                    f"Collect independent, high-rigor direct evidence that adjudicates "
                    f"{_code(weak_claim.get('claim_id'))}: {_one_line(weak_claim.get('text'))}"
                )
            else:
                target = "Collect independent, high-rigor direct evidence for the central claim."
            why = (
                "Source quality was not independently ranked, so an independent direct test has the "
                "highest expected information value."
                if not (source_quality_report or {}).get("ranked_sources")
                else "It tests the weakest decision-relevant link in the current claim-evidence chain."
            )

    unlock = (
        f"whether the advisory posture can move from {assessment.posture} to a stronger commitment, "
        "or whether the idea/method should be narrowed or stopped."
    )
    return target.rstrip("."), why, unlock


def build_research_brief_markdown(
    *,
    mode: str,
    evidence_table: dict,
    claim_list: dict,
    claim_evidence_map: dict,
    report: dict,
    source_quality_report: Optional[dict] = None,
    contradiction_report: Optional[dict] = None,
    landscape_map: Optional[dict] = None,
    staleness_reports: Optional[list[dict]] = None,
    dataset_cards: Optional[list[dict]] = None,
    perspective_notes: Optional[list[dict]] = None,
    research_brief: Optional[dict] = None,
    search_trace: Optional[dict] = None,
) -> str:
    """Build a briefing from existing evidence without introducing new claims."""
    if mode not in BRIEF_PATHS:
        raise ValueError(f"unsupported research briefing mode: {mode!r}")

    claims = [row for row in (claim_list.get("claims") or []) if isinstance(row, dict)]
    mappings = _mapping_index(claim_evidence_map)
    conflicts = _conflicts(contradiction_report)
    gaps = _gaps(landscape_map, research_brief)
    assessment = _assess(
        evidence_table,
        claim_list,
        claim_evidence_map,
        source_quality_report,
        contradiction_report,
        landscape_map,
        research_brief,
        report,
        search_trace=search_trace,
    )
    if report.get("citation_legacy_replay") or report.get("evidence_gate") == "LEGACY_UNVERIFIED":
        assessment = replace(
            assessment,
            grade="INSUFFICIENT",
            posture="HOLD",
            rationale="Explicit legacy replay; current source/search/citation contracts are unverified. "
                      + assessment.rationale,
        )
    source_audit = audit_source_quality_report(source_quality_report, evidence_table)
    search_audit = evaluate_search_trace(search_trace)
    query = _one_line(evidence_table.get("query") or (research_brief or {}).get("topic") or "research question")
    bottom_line = _bottom_line(assessment, claims, mappings, conflicts, gaps, research_brief)
    next_target, next_why, next_unlock = _next_evidence(
        assessment,
        claims,
        mappings,
        conflicts,
        gaps,
        evidence_table,
        source_quality_report,
        research_brief,
        report,
        search_trace,
    )

    title = {
        "evidence_review": "Evidence Review Brief",
        "evidence_deep": "Deep Evidence Brief",
        "deep_research": "Deep Research Brief",
    }[mode]
    lines = [
        "---",
        f"mode: {mode}",
        f"evidence_grade: {assessment.grade}",
        f"decision_posture: {assessment.posture}",
        "records_project_decision: false",
        "writes_vault: false",
        "---",
        "",
        f"# {title} - {query}",
        "",
        "## Bottom Line",
        "",
        bottom_line,
        "",
        f"- Evidence grade: `{assessment.grade}`.",
        f"- Decision posture: `{assessment.posture}` (advisory only; no bet, experiment launch, or promotion is recorded).",
        f"- Most valuable next evidence: {next_target}.",
        "",
        "## Evidence Grade And Source Quality",
        "",
        f"- Evidence grade: `{assessment.grade}`.",
        f"- Grade basis: {assessment.rationale}",
        "- Scale: HIGH = direct, consistently supported, quality-ranked evidence with no major gap; "
        "MODERATE = credible but bounded; LIMITED = material quality/verification/coverage ceiling; "
        "INSUFFICIENT = mechanical evidence floor not met.",
        f"- Gates: evidence={_code(report.get('evidence_gate'))}; citation={_code(report.get('citation_gate'))}; "
        f"existence={_code(report.get('existence_gate'))}; existence warnings={report.get('existence_warnings', 0)}.",
        f"- Independent span attribution: gate={_code(report.get('citation_attribution_gate') or 'LEGACY_UNVERIFIED')}; "
        f"citation correctness={_code(report.get('citation_correctness'))}; "
        f"claim completeness={_code(report.get('claim_completeness'))}; citation F1={_code(report.get('citation_f1'))}.",
        f"- Derived source methodology: status={_code(source_audit.get('audit_status') or 'LEGACY_UNVERIFIED')}; "
        f"HIGH={source_audit.get('n_high', 0)}, MODERATE={source_audit.get('n_moderate', 0)}, "
        f"LOW={source_audit.get('n_low', 0)}, UNVERIFIED={source_audit.get('n_unverified', 0)}.",
        f"- Semantic search: status={_code(search_audit.get('status') or 'LEGACY_UNVERIFIED')}; "
        f"critical-claim coverage={_code(search_audit.get('critical_claim_coverage'))}; "
        f"counterevidence coverage={_code(search_audit.get('contradiction_coverage'))}; "
        f"representativeness coverage={_code(search_audit.get('representativeness_coverage'))}; "
        f"unique sources={search_audit.get('n_unique_sources', 0)}.",
    ]

    ranked = [
        row for row in ((source_quality_report or {}).get("ranked_sources") or [])
        if isinstance(row, dict)
    ]
    if ranked:
        lines.append(
            f"- Quality judgment: {_one_line((source_quality_report or {}).get('ranking_rationale'))}"
        )
    else:
        lines.append(
            "- Quality ceiling: source quality was not independently ranked in this lightweight mode; "
            "venue rigor, peer review, and recency therefore cap the grade at LIMITED."
        )
    lines.extend(["", "### Source Register", ""])
    quality_by_ref = {str(row.get("source_ref")): row for row in ranked}
    derived_by_ref = {
        str(row.get("source_ref")): row
        for row in source_audit.get("assessments") or []
        if isinstance(row, dict) and row.get("source_ref")
    }
    stale_by_ref = {
        str(row.get("source_ref")): row
        for row in (staleness_reports or [])
        if isinstance(row, dict) and row.get("source_ref")
    }
    for source in evidence_table.get("sources") or []:
        ref = str(source.get("ref") or source.get("id") or "not-recorded")
        quality = quality_by_ref.get(ref) or quality_by_ref.get(str(source.get("id"))) or {}
        derived = derived_by_ref.get(ref) or derived_by_ref.get(str(source.get("id"))) or {}
        stale = stale_by_ref.get(ref) or {}
        quality_text = (
            f"derived={derived.get('derived_strength')}, tier={quality.get('tier')}, rank={quality.get('rank')}"
            if quality else "LEGACY_UNVERIFIED"
        )
        stale_text = stale.get("status") or "not audited"
        lines.append(
            f"- {_code(ref)}: support={_code(source.get('claim_support') or 'none')}; "
            f"quality={_code(quality_text)}; year={_code(source.get('year') or quality.get('year') or 'unknown')}; "
            f"staleness={_code(stale_text)}; title={_one_line(source.get('title') or 'not recorded')}."
        )

    lines.extend(["", "## Claim-Evidence Ledger", ""])
    for claim in claims:
        cid = str(claim.get("claim_id") or "missing-id")
        mapping = mappings.get(cid) or {}
        support = _claim_support(mapping)
        risk = mapping.get("claim_risk") or {}
        lines.extend([
            f"### {_code(cid)}",
            "",
            f"- Claim: {_one_line(claim.get('text'))}",
            f"- Binding: support={_code(support)}; claim confidence={_code(claim.get('confidence') or 'not-rated')}; "
            f"primary source={_code(claim.get('source_ref'))}.",
            f"- Belief movement: **{_belief_movement(mapping)}**.",
        ])
        if risk:
            lines.append(
                f"- Overclaim risk: {_code(risk.get('level') or 'not-rated')} - {_one_line(risk.get('note') or 'no note')}"
            )
        lines.append("- Evidence loci:")
        for locus in mapping.get("loci") or []:
            verdict = "supports" if locus.get("supports_claim") is True else "does not support"
            lines.append(
                f"  - {_code(locus.get('locus_id'))} at {_code(locus.get('source_ref'))}, "
                f"{_code(locus.get('location'))}: {_one_line(locus.get('reported_result') or 'result not recorded')} "
                f"[{verdict}; relation={_one_line(locus.get('support_relation') or 'legacy-boolean')}; "
                f"directness={_one_line(locus.get('directness') or 'unspecified')}; "
                f"span={_one_line(locus.get('span_id') or 'not-recorded')}]."
            )
        lines.append("")

    lines.extend(["## Contradictions And Counterevidence", ""])
    summary = _one_line((contradiction_report or {}).get("summary"))
    if summary:
        lines.append(f"- Miner summary: {summary}")
    if conflicts:
        for conflict in conflicts:
            lines.append(
                f"- {_code(conflict.get('conflict_id'))} ({_one_line(conflict.get('kind'))}): "
                f"{_code(conflict.get('claim_ref_a'))} versus {_code(conflict.get('claim_ref_b'))}. "
                f"{_one_line(conflict.get('description'))} Resolution={_code(conflict.get('resolution_status') or 'unresolved')}."
            )
    else:
        checked = (contradiction_report or {}).get("n_claims_checked")
        if contradiction_report is None:
            lines.append(
                "- No dedicated contradiction-miner artifact exists for this lightweight review. "
                "No recorded conflict is not evidence of absence; actively search for negative and scope-reversing results."
            )
        else:
            lines.append(
                f"- The contradiction miner reported no explicit conflict after checking {checked} claims. "
                "This is not evidence of absence; disagreements can remain outside the retrieved source set."
            )
    for claim in claims:
        cid = str(claim.get("claim_id"))
        support = _claim_support(mappings.get(cid) or {})
        if support != "supported":
            lines.append(
                f"- Scope-limiting evidence: {_code(cid)} is {_code(support)} and must not be promoted to a broader claim."
            )

    lines.extend([
        "",
        "## Belief Update",
        "",
        f"- Starting position: Treat {_code(query)} as unresolved before reading this evidence set.",
    ])
    for claim in claims:
        cid = str(claim.get("claim_id"))
        mapping = mappings.get(cid) or {}
        support = _claim_support(mapping)
        lines.append(
            f"- {_code(cid)}: **{_belief_movement(mapping)}** because the mapped evidence is {_code(support)}; "
            f"retain the stated scope and confidence boundary."
        )
    consensus = _list((research_brief or {}).get("consensus"))
    disagreements = _list((research_brief or {}).get("live_disagreements"))
    if consensus:
        lines.append(f"- Cross-perspective consensus: {'; '.join(consensus)}.")
    if disagreements:
        lines.append(f"- Live disagreement: {'; '.join(disagreements)}.")
    lines.append(f"- Net update: {bottom_line}")

    lines.extend([
        "",
        "## Decision Implications",
        "",
        f"- For the current project/idea/experiment framed as {_code(query)}, use posture {_code(assessment.posture)}.",
    ])
    if assessment.posture == "HOLD":
        lines.append(
            "- Do not make a method commitment or broad research claim from this packet; obtain the next-most-valuable evidence item first."
        )
    elif assessment.posture == "RUN-DISCRIMINATING-TEST":
        lines.append(
            "- Advance only to a discriminating experiment or targeted evidence search, with the current claim scope frozen."
        )
    else:
        lines.append(
            "- A bounded next-step commitment is defensible, but generalization and promotion remain outside this packet."
        )
    strongest = _strongest_claim(claims, mappings)
    if strongest:
        lines.append(
            f"- What can be used now: {_code(strongest.get('claim_id'))} within its measured setting - "
            f"{_one_line(strongest.get('text'))}."
        )
    lines.append(
        "- Human boundary: this brief informs a decision; it does not choose an idea, launch an experiment, or promote a claim."
    )

    uncertainties: list[str] = []
    _n_ranked, unranked_refs = _source_quality_coverage(evidence_table, source_quality_report)
    if assessment.n_existence_warnings:
        uncertainties.append(
            f"{assessment.n_existence_warnings} source existence {_noun(assessment.n_existence_warnings, 'warning')} "
            "leave cited records unverified."
        )
    if search_audit.get("status") != "COMPLETE":
        uncertainties.append(
            "Semantic search is not complete: " + "; ".join(search_audit.get("reasons") or [])
        )
    if source_audit.get("audit_status") != "PASS":
        uncertainties.append(
            "Source methodology review is not complete: " + "; ".join(source_audit.get("reasons") or [])
        )
    if report.get("citation_attribution_gate") != "PASS":
        uncertainties.append(
            "Claim support was not independently rechecked against immutable exact spans; "
            "the linker/citation-existence pass is not a semantic entailment audit."
        )
    if source_quality_report is not None and unranked_refs:
        uncertainties.append(
            "Independent source-quality ranking is missing for "
            + ", ".join(unranked_refs)
            + "."
        )
    elif not ranked:
        uncertainties.append("Source venue/rigor/recency was not independently ranked.")
    if contradiction_report is None:
        uncertainties.append("No dedicated contradiction-miner pass was available in this lightweight mode.")
    uncertainties.extend(
        f"{row.get('gap_id')}: {row.get('description')} ({row.get('severity', 'unspecified')})"
        for row in gaps
    )
    uncertainties.extend(disagreements)
    for claim in claims:
        cid = str(claim.get("claim_id"))
        mapping = mappings.get(cid) or {}
        risk = mapping.get("claim_risk") or {}
        if _claim_support(mapping) != "supported":
            uncertainties.append(f"{cid} has {_claim_support(mapping)} support.")
        if risk.get("level") in {"high", "medium"}:
            uncertainties.append(f"{cid} overclaim risk: {risk.get('note') or risk.get('level')}.")
    for stale in staleness_reports or []:
        if stale.get("status") not in {"CURRENT", "current"}:
            uncertainties.append(
                f"{stale.get('source_ref')} staleness={stale.get('status')}: {stale.get('staleness_rationale') or 'no rationale'}"
            )
    for note in perspective_notes or []:
        pid = note.get("perspective_id")
        uncertainties.extend(f"{pid}: {item}" for item in (note.get("coverage_limits") or []))
    if not uncertainties:
        uncertainties.append("Residual publication bias and retrieval miss risk remain even after saturation.")

    lines.extend(["", "## Critical Uncertainties", ""])
    for uncertainty in _dedupe(uncertainties):
        lines.append(f"- {uncertainty}")

    lines.extend([
        "",
        "## Next Most Valuable Evidence",
        "",
        f"- Target: {next_target}.",
        f"- Why this is highest value: {next_why}",
        f"- Decision it unlocks: {next_unlock}",
        "- Minimum standard: use a protocol-matched, independently checkable source or experiment with explicit negative-result reporting.",
        "",
    ])

    if perspective_notes:
        lines.extend(["## Perspective Synthesis", ""])
        for note in perspective_notes:
            pid = str(note.get("perspective_id") or "missing-id")
            lines.extend([
                f"### {_code(pid)} - {_one_line(note.get('angle') or 'unnamed angle')}",
                "",
                _one_line(note.get("finding_summary") or "No finding summary recorded."),
                "",
                f"- Confidence: {_code(note.get('confidence') or 'not-rated')}.",
                f"- Source refs: {', '.join(_code(ref) for ref in (note.get('source_refs') or [])) or 'none recorded'}.",
                f"- Opportunity: {'; '.join(_list(note.get('actionable_opportunities'))) or 'none recorded'}.",
                f"- Kill criteria: {'; '.join(_list(note.get('kill_criteria'))) or 'none recorded'}.",
                f"- Coverage limits: {'; '.join(_list(note.get('coverage_limits'))) or 'none recorded'}.",
                "",
            ])

    if dataset_cards:
        lines.extend(["## Dataset Decision Risks", ""])
        for card in dataset_cards:
            lines.append(
                f"- {_code(card.get('dataset_ref'))}: {_one_line(card.get('description'))}; "
                f"leakage risks={len(card.get('leakage_risks') or [])}."
            )
        lines.append("")

    pointers = {
        "evidence_review": [
            "evidence/DISCOVER/evidence-table.artifact.json",
            "evidence/DISCOVER/source-quality-report.artifact.json",
            "evidence/DISCOVER/evidence-search-trace.artifact.json",
            "evidence/DISCOVER/evidence-verdict.artifact.json",
            "evidence/DISCOVER/citation-verdict.artifact.json",
        ],
        "evidence_deep": [
            "evidence/DISCOVER/source-quality-report.artifact.json",
            "evidence/DISCOVER/evidence-search-trace.artifact.json",
            "evidence/DISCOVER/claim-evidence-map.artifact.json",
            "evidence/DISCOVER/citation-attribution-report.artifact.json",
            "evidence/DISCOVER/contradiction-report.artifact.json",
            "evidence/DISCOVER/landscape-map.artifact.json",
        ],
        "deep_research": [
            "evidence/DISCOVER/research-brief.artifact.json",
            "evidence/DISCOVER/evidence-search-trace.artifact.json",
            "evidence/DISCOVER/research-perspective-P*.artifact.json",
            "evidence/DISCOVER/claim-evidence-map.artifact.json",
            "evidence/DISCOVER/citation-attribution-report.artifact.json",
            "evidence/DISCOVER/contradiction-report.artifact.json",
        ],
    }[mode]
    lines.extend(["## Evidence Pointers", ""])
    for pointer in pointers:
        lines.append(f"- {_code(pointer)}")
    lines.extend([
        "- This Markdown is deterministically rendered from the validated worker outputs; it is the human reading layer, not a new evidence source.",
        "- Nothing in this page is vault-grade until the director uses `/promote-to-vault` and that gate re-derives promotability.",
    ])
    return "\n".join(lines).rstrip() + "\n"


def write_research_brief_markdown(run_dir, **kwargs) -> str:
    mode = str(kwargs.get("mode") or "")
    text = build_research_brief_markdown(**kwargs)
    perspective_ids = [
        str(note.get("perspective_id"))
        for note in (kwargs.get("perspective_notes") or [])
        if isinstance(note, dict) and note.get("perspective_id")
    ]
    errors = lint_research_brief_markdown(
        text,
        mode=mode,
        claim_list=kwargs.get("claim_list") or {},
        claim_evidence_map=kwargs.get("claim_evidence_map") or {},
        source_quality_report=kwargs.get("source_quality_report"),
        contradiction_report=kwargs.get("contradiction_report"),
        perspective_ids=perspective_ids,
    )
    out = brief_path(run_dir, mode)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    advisory = {
        "contract_version": "research-markdown-advisory/v1",
        "delivery_blocking": False,
        "delivery_status": "USABLE" if not errors else "USABLE_WITH_CAVEATS",
        "warnings": errors,
    }
    advisory_path = Path(run_dir) / "inbox" / f"{mode}-markdown-quality-advisory.json"
    advisory_path.parent.mkdir(parents=True, exist_ok=True)
    advisory_path.write_text(json.dumps(advisory, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return str(out)


def write_research_brief_fallback(run_dir, *, mode: str, reason: str,
                                  report: Optional[dict] = None) -> str:
    """Deliver a readable working note when the polished renderer fails.

    This is deliberately sparse and visibly caveated. It prevents a formatting
    failure from hiding already completed scientific work; it never upgrades
    evidence or promotion status.
    """
    out = brief_path(run_dir, mode)
    out.parent.mkdir(parents=True, exist_ok=True)
    report = report or {}
    lines = [
        f"# {mode.replace('_', ' ').title()} Working Brief",
        "",
        "> **Delivery status: USABLE_WITH_CAVEATS.** The polished Markdown renderer needs a local fix; "
        "the machine evidence remains available and unchanged.",
        "",
        "## Current Result",
        "",
        f"- Citation gate: `{report.get('citation_gate', 'not recorded')}`",
        f"- Citation attribution: `{report.get('citation_attribution_gate', 'not recorded')}`",
        f"- Claims extracted: `{report.get('n_claims', 'not recorded')}`",
        f"- Evidence mappings: `{report.get('n_mappings', 'not recorded')}`",
        "",
        "## Rendering Caveat",
        "",
        f"- {reason}",
        "",
        "## Next Action",
        "",
        "- Repair only the Markdown renderer or missing presentation section; do not rerun scientific workers.",
    ]
    out.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return str(out)
