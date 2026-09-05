"""Deterministic director-facing Markdown for evidence and research modes.

The worker bundles and typed artifacts remain the evidence of record. This module
turns those already-validated structures into a decision-grade human brief. It
does not create claims, approve a project decision, or write to the vault.
"""
from __future__ import annotations

import json
import re
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


def _delivery_boundary(report: dict) -> dict:
    """Return the machine boundary, with a fail-closed legacy projection."""
    value = report.get("delivery_boundary")
    if isinstance(value, dict):
        return value
    blockers = [
        dict(row) for row in report.get("content_external_blocker_details") or []
        if isinstance(row, dict)
    ]
    gates = {
        "evidence": str(report.get("evidence_gate") or "UNVERIFIED"),
        "citation": str(report.get("citation_gate") or "UNVERIFIED"),
        "citation_attribution": str(report.get("citation_attribution_gate") or "UNVERIFIED"),
        "existence": str(report.get("existence_gate") or "UNVERIFIED"),
    }
    projected_status = str(report.get("markdown_delivery_status") or "")
    content_convergence = str(report.get("content_convergence") or "NOT_REVIEWED")
    clean_delivery = (
        content_convergence == "CONTENT_CONVERGED"
        and not blockers
        and all(value == "PASS" for value in gates.values())
        and projected_status != "USABLE_WITH_CAVEATS"
    )
    projected_status = "USABLE" if clean_delivery else "USABLE_WITH_CAVEATS"
    return {
        "contract_version": "research-delivery-boundary/legacy-projection",
        "content_convergence": content_convergence,
        "scientific_gates": gates,
        "novelty": {
            "status": "UNVERIFIED",
            "independent_hash_bound_gate_pass": False,
            "reasons": ["NO_INDEPENDENT_HASH_BOUND_NOVELTY_GATE_PASS"],
        },
        "external_blockers": blockers,
        "delivery_status": projected_status,
        "claim_boundaries": {
            "content_convergence_only": True,
            "novelty_claim_allowed": False,
            "project_approval": False,
        },
    }


_UNVERIFIED_NOVELTY_PATTERNS = (
    re.compile(r"(?i)\bnovelty\s*(?:status\s*)?(?:=|:|is)?\s*`?PASS\b`?"),
    re.compile(r"(?i)\bnovelty[_ -]clearance\s*(?:=|:|is)?\s*(?:`?PASS\b`?|true\b)"),
    re.compile(r"(?i)\bnovelty\s+(?:is\s+)?(?:verified|proven|confirmed|cleared)\b"),
    re.compile(r"(?i)\b(?:is|are)\s+(?:globally\s+)?novel\b"),
    re.compile(
        r"(?i)\b(?:the|this|our|a|an)\s+(?:globally\s+)?novel\s+"
        r"(?:method|approach|contribution|idea|architecture|framework|mechanism)\b"
    ),
    re.compile(
        r"(?i)\b(?:the|this|our)\s+(?:is\s+the\s+)?first\s+"
        r"(?:method|approach|framework|system|model|technique|algorithm|study|work)\b"
    ),
    re.compile(
        r"(?i)\bno\s+prior\s+"
        r"(?:work|study|method|approach|framework|system|model|technique|algorithm)\b"
    ),
    re.compile(
        r"(?i)\bthere\s+(?:has|have)\s+been\s+no\s+(?:previous|prior)\s+"
        r"(?:work|study|research|method|approach|framework|system|model|technique|algorithm)\b"
    ),
    re.compile(
        r"(?i)\b(?:has|have)\s+not\s+(?:previously\s+)?appeared\s+in\s+"
        r"(?:the\s+)?(?:prior|previous|existing)\s+literature\b"
    ),
    re.compile(r"(?i)\b(?:uniquely\s+original|never\s+(?:been\s+)?reported)\b"),
    re.compile(
        r"(?i)\babsent\s+from\s+(?:all\s+)?(?:earlier|prior|previous|existing)\s+"
        r"(?:studies|work|literature|methods|approaches)\b"
    ),
    re.compile(r"(?i)\b(?:unprecedented|first[- ]of[- ]its[- ]kind|without\s+precedent|never\s+before)\b"),
    re.compile(r"(?:新颖性|创新性)(?:已经|已|得到)?(?:通过|验证|证实|成立)"),
    re.compile(r"(?:首次|首个)(?:提出|实现|证明|构建|开发|系统性研究|方法|框架|系统|模型|算法)"),
    re.compile(r"(?:这是|该|本(?:文|研究|工作))?第(?:一|1)个.{0,40}?(?:方法|框架|系统|模型|算法|研究|工作)"),
    re.compile(r"(?:前所未有|史无前例|空前|从未实现过)"),
    re.compile(r"尚无(?:任何)?(?:相关)?(?:研究|工作|方法|框架|系统|模型|算法)"),
    re.compile(r"(?:此前|迄今|过去)?从未有(?:任何)?(?:相关)?(?:研究|工作|方法|框架|系统|模型|算法)"),
    re.compile(r"(?:国内外)?(?:尚未|未曾|从未)(?:见|有)?(?:相关)?(?:报道|发表|提出|实现)"),
)

_UNVERIFIED_NOVELTY_CLAIM_LINES = (
    re.compile(r"(?i)\bto\s+the\s+best\s+of\s+(?:our|the\s+authors?['’]?)\s+knowledge\b"),
    re.compile(r"(?i)\bwe\s+(?:are\s+)?(?:unaware|not\s+aware)\b"),
    re.compile(
        r"(?i)\b(?:no|none|never|not\s+any|without|absent\s+from)\b.{0,100}\b"
        r"(?:prior|previous|earlier|existing|comparable|literature|publication|study|studies|"
        r"work|method|approach)\b"
    ),
    re.compile(
        r"(?i)\b(?:prior|previous|earlier|existing|comparable)\b.{0,100}\b"
        r"(?:does\s+not|do\s+not|has\s+not|have\s+not|never|absent|unknown)\b"
    ),
    re.compile(
        r"(?i)(?<![-\w])(?:first|only|unique|uniquely\s+original|original|novel|unprecedented|"
        r"entirely\s+new|previously\s+unknown)\b.{0,100}\b"
        r"(?:method|approach|framework|system|model|technique|algorithm|study|work|contribution|"
        r"mechanism|direction|solution)\b"
    ),
    re.compile(
        r"(?i)\b(?:method|approach|framework|system|model|technique|algorithm|study|work|"
        r"contribution|mechanism|direction|solution)\b.{0,100}\b"
        r"(?:the\s+first|the\s+only|unique|original|novel|unprecedented|new\s+to\s+the\s+field|"
        r"previously\s+unknown)\b"
    ),
    re.compile(r"据(?:我们|作者|本(?:文|研究|团队))所知"),
    re.compile(r"(?:唯一|首次|首个|第一个|全新|原创|独创|未知).{0,60}(?:方法|框架|系统|模型|算法|研究|工作|贡献|机制|方向|方案)"),
    re.compile(r"(?:方法|框架|系统|模型|算法|研究|工作|贡献|机制|方向|方案).{0,60}(?:唯一|首次|首个|第一个|全新|原创|独创|前所未有|史无前例)"),
    re.compile(r"(?:目前|此前|迄今|过去|国内外)?.{0,20}(?:没有|尚无|暂无|未有|从未有).{0,60}(?:文献|论文|报道|研究|工作|方法)"),
    re.compile(
        r"(?i)\b(?:nothing|no\s+(?:published|known|existing|prior|previous|earlier)?\s*"
        r"(?:work|study|system|method|approach|publication|literature))\b.{0,120}\b"
        r"(?:resembl\w*|similar|comparable|implement\w*|cover\w*|address\w*|solve\w*)\b"
    ),
    re.compile(
        r"(?i)\b(?:we\s+)?(?:could|can)\s+(?:not|never)\s+find\b.{0,120}\b"
        r"(?:similar|comparable|related|precedent|counterpart)\b"
    ),
    re.compile(
        r"(?i)\b(?:territory|space|area|problem|mechanism|combination|direction)\b.{0,100}\b"
        r"(?:untouched|unexplored|uncovered|unaddressed|unreported|unpublished)\b"
    ),
    re.compile(
        r"(?i)\b(?:prior|previous|earlier|existing)\s+(?:work|studies|literature|methods|systems)\b"
        r".{0,120}\b(?:stop(?:s|ped)?\s+short|fail(?:s|ed)?\s+to|do(?:es)?\s+not|omit(?:s|ted)?|"
        r"leave(?:s)?\s+(?:this|the)\s+\w+\s+(?:open|untouched|uncovered))\b"
    ),
    re.compile(r"(?:据.{0,12}(?:检索|调查|查阅)).{0,30}(?:找不到|未找到|没有找到).{0,60}(?:类似|相似|可比|相关).{0,20}(?:方法|工作|研究|文献|系统|机制)?"),
    re.compile(r"(?:现有|已有|既有|此前|相关).{0,20}(?:工作|研究|文献|方法|系统).{0,50}(?:均|都)?(?:未|没有)(?:覆盖|涉及|实现|解决|触及|报告|发表)"),
    re.compile(r"(?:研究|文献|方法|方向|机制|问题).{0,30}(?:仍属|属于|构成)?(?:空白|无人涉足|未被覆盖|尚未覆盖|尚待首次)"),
)


def _quarantine_unverified_novelty_claim_lines(text: str) -> str:
    """Remove whole prose lines that semantically claim unverified novelty.

    Exact phrase replacement is too easy to paraphrase around. This deliberately
    conservative second layer quarantines any author-facing line that combines
    exclusivity/originality or absence-of-prior-art language with a research
    object. Losing one mixed prose line is safer than delivering a global novelty
    claim without an independent hash-bound novelty gate.
    """
    output = []
    for line in text.splitlines(keepends=True):
        if not any(pattern.search(line) for pattern in _UNVERIFIED_NOVELTY_CLAIM_LINES):
            output.append(line)
            continue
        newline = "\n" if line.endswith("\n") else ""
        prefix_match = re.match(r"^(\s*(?:(?:[-*+] |\d+[.)] )|(?:> )))", line)
        prefix = prefix_match.group(1) if prefix_match else ""
        output.append(
            f"{prefix}[Novelty statement quarantined — effective status: UNVERIFIED.]"
            f"{newline}"
        )
    return "".join(output)


def _enforce_novelty_boundary(text: str, boundary: dict) -> str:
    novelty = boundary.get("novelty") or {}
    if novelty.get("status") == "VERIFIED_PASS" and (
        boundary.get("claim_boundaries") or {}
    ).get("novelty_claim_allowed") is True:
        return text
    safe = _quarantine_unverified_novelty_claim_lines(text)
    for pattern in _UNVERIFIED_NOVELTY_PATTERNS:
        safe = pattern.sub("novelty `UNVERIFIED`", safe)
    return safe


def _full_verified_render_allowed(boundary: dict) -> bool:
    novelty = boundary.get("novelty") or {}
    claims = boundary.get("claim_boundaries") or {}
    return (
        novelty.get("status") == "VERIFIED_PASS"
        and novelty.get("independent_hash_bound_gate_pass") is True
        and claims.get("novelty_claim_allowed") is True
    )


def _safe_enum(value: object, allowed: set[str], default: str = "UNKNOWN") -> str:
    text = str(value or "").strip()
    return text if text in allowed else default


def _safe_sha256(value: object) -> Optional[str]:
    text = str(value or "").strip().lower()
    if re.fullmatch(r"(?:sha256:)?[0-9a-f]{64}", text):
        return text if text.startswith("sha256:") else "sha256:" + text
    return None


def _machine_only_unverified_deep_research_markdown(
    *,
    evidence_table: dict,
    claim_list: dict,
    claim_evidence_map: dict,
    report: dict,
    contradiction_report: Optional[dict],
    perspective_notes: Optional[list[dict]],
    delivery_boundary: dict,
) -> str:
    """Render the authoritative UNVERIFIED brief from typed fields only.

    Worker prose remains intact in the JSON artifacts, but is not copied into
    the authoritative claim channel. This allowlist projection, rather than the
    natural-language denylist, is the novelty-boundary security control.
    """
    claims = [row for row in claim_list.get("claims") or [] if isinstance(row, dict)]
    mappings = _mapping_index(claim_evidence_map)
    conflicts = _conflicts(contradiction_report)
    perspectives = [
        row for row in perspective_notes or [] if isinstance(row, dict)
    ]
    gates = delivery_boundary.get("scientific_gates") or {}
    novelty = delivery_boundary.get("novelty") or {}
    boundary_claims = delivery_boundary.get("claim_boundaries") or {}
    sources = [
        row for row in evidence_table.get("sources") or [] if isinstance(row, dict)
    ]
    source_aliases: dict[str, str] = {}
    duplicate_source_refs: set[str] = set()
    for index, source in enumerate(sources, start=1):
        alias = f"S{index:03d}"
        raw_ref = str(source.get("ref") or "")
        if not raw_ref:
            continue
        if raw_ref in source_aliases:
            duplicate_source_refs.add(raw_ref)
        else:
            source_aliases[raw_ref] = alias
    for raw_ref in duplicate_source_refs:
        source_aliases[raw_ref] = "AMBIGUOUS"
    claim_aliases = {
        str(claim.get("claim_id") or ""): f"C{index:03d}"
        for index, claim in enumerate(claims, start=1)
    }
    safe_gate_values = {
        "PASS", "BLOCK", "WARN", "UNVERIFIED", "LEGACY_UNVERIFIED",
        "NOT_APPLICABLE", "NOT_REVIEWED", "UNKNOWN",
    }
    lines = [
        "---",
        "mode: deep_research",
        "render_policy: MACHINE_ONLY_UNVERIFIED",
        "records_project_decision: false",
        "writes_vault: false",
        "---",
        "",
        "# Deep Research Machine Evidence Brief",
        "",
        "> **Authoritative surface policy:** novelty is not independently verified. Raw researcher,",
        "> reviewer, paper, and source prose is retained in hash-bound JSON artifacts for audit and",
        "> ideation, but is excluded from scientific conclusion sections in this Markdown.",
        "",
        "## Bottom Line",
        "",
        f"- Delivery status: {_code(_safe_enum(delivery_boundary.get('delivery_status'), {'USABLE', 'USABLE_WITH_CAVEATS'}, 'USABLE_WITH_CAVEATS'))}.",
        f"- Content convergence: {_code(_safe_enum(delivery_boundary.get('content_convergence'), {'REVISE', 'CONTENT_CONVERGED', 'CONTENT_CONVERGED_WITH_EXTERNAL_BLOCKERS', 'NOT_REVIEWED'}, 'NOT_REVIEWED'))}.",
        f"- Effective novelty status: {_code(_safe_enum(novelty.get('status'), {'VERIFIED_PASS', 'UNVERIFIED'}, 'UNVERIFIED'))}.",
        f"- Independent hash-bound novelty gate: {_code(novelty.get('independent_hash_bound_gate_pass') is True)}.",
        f"- Novelty claim allowed: {_code(boundary_claims.get('novelty_claim_allowed') is True)}.",
        "- No narrative scientific conclusion or prior-art absence claim is authorized on this surface.",
        "",
        "## Delivery Boundary",
        "",
        f"- Evidence gate: {_code(_safe_enum(gates.get('evidence') or report.get('evidence_gate'), safe_gate_values))}.",
        f"- Citation gate: {_code(_safe_enum(gates.get('citation') or report.get('citation_gate'), safe_gate_values))}.",
        f"- Citation-attribution gate: {_code(_safe_enum(gates.get('citation_attribution') or report.get('citation_attribution_gate'), safe_gate_values))}.",
        f"- Existence gate: {_code(_safe_enum(gates.get('existence') or report.get('existence_gate'), safe_gate_values))}.",
        f"- Novelty boundary reason count: `{len(novelty.get('reasons') or [])}`; raw reasons remain in the boundary JSON.",
        "",
        "## Evidence Grade And Source Quality",
        "",
        "- Evidence grade: `NOT_RENDERED_FROM_PROSE`.",
        f"- Typed source count: `{len(sources)}`.",
        f"- Typed claim count: `{len(claims)}`.",
        f"- Typed mapping count: `{len(mappings)}`.",
        "- Source Register (identifiers and enums only):",
    ]
    for index, source in enumerate(sources, start=1):
        lines.append(
            f"  - source={_code(f'S{index:03d}')}; "
            f"kind={_code(_safe_enum(source.get('kind'), {'paper', 'repo', 'dataset', 'benchmark', 'blog', 'doc'}))}; "
            f"year={_code(source.get('year') if isinstance(source.get('year'), int) else 'UNKNOWN')}; "
            f"support={_code(_safe_enum(source.get('claim_support'), {'strong', 'moderate', 'weak', 'none'}))}."
        )

    lines.extend(["", "## Claim-Evidence Ledger", ""])
    if not claims:
        lines.append("- No typed claims were recorded.")
    locus_index = 0
    for claim in claims:
        claim_id = str(claim.get("claim_id") or "")
        claim_alias = claim_aliases.get(claim_id, "C000")
        mapping = mappings.get(claim_id) or {}
        lines.extend([
            f"### {_code(claim_alias)}",
            "",
            f"- kind={_code(_safe_enum(claim.get('kind'), {'performance', 'method', 'dataset', 'comparison', 'limitation', 'other'}, 'other'))}; "
            f"confidence={_code(_safe_enum(claim.get('confidence'), {'high', 'medium', 'low'}, 'medium'))}; "
            f"source={_code(source_aliases.get(str(claim.get('source_ref') or ''), 'UNMAPPED'))}; "
            f"overall_support={_code(_safe_enum(mapping.get('overall_support'), {'supported', 'partial', 'contradicted', 'not-found'}, 'not-found'))}.",
        ])
        loci = [row for row in mapping.get("loci") or [] if isinstance(row, dict)]
        for locus in loci:
            locus_index += 1
            document_hash = _safe_sha256(locus.get("document_hash"))
            locator = (
                f"page={_code(locus.get('page') if isinstance(locus.get('page'), int) else 'UNKNOWN')}; "
                f"document_hash={_code(document_hash or 'UNVERIFIED')}; "
                f"char_start={_code(locus.get('char_start') if isinstance(locus.get('char_start'), int) else 'UNKNOWN')}; "
                f"char_end={_code(locus.get('char_end') if isinstance(locus.get('char_end'), int) else 'UNKNOWN')}"
            )
            lines.append(
                f"- locus={_code(f'L{locus_index:03d}')}; "
                f"source={_code(source_aliases.get(str(locus.get('source_ref') or ''), 'UNMAPPED'))}; "
                f"kind={_code(_safe_enum(locus.get('kind'), {'table', 'figure', 'text', 'code', 'dataset', 'appendix', 'other'}))}; "
                f"relation={_code(_safe_enum(locus.get('support_relation'), {'entails', 'partial', 'contradicts', 'insufficient'}))}; "
                f"supports_claim={_code(locus.get('supports_claim') if isinstance(locus.get('supports_claim'), bool) else 'UNKNOWN')}; "
                f"directness={_code(_safe_enum(locus.get('directness'), {'direct', 'indirect', 'proxy', 'assumed'}))}; {locator}."
            )

    lines.extend(["", "## Contradictions And Counterevidence", ""])
    if not conflicts:
        lines.append("- No typed conflict row was recorded; this is not evidence of absence.")
    for index, row in enumerate(conflicts, start=1):
        lines.append(
            f"- conflict={_code(f'F{index:03d}')}; "
            f"kind={_code(_safe_enum(row.get('kind'), {'numerical-disagreement', 'directional-flip', 'scope-mismatch', 'method-conflict', 'other'}))}; "
            f"status={_code(_safe_enum(row.get('resolution_status'), {'unresolved', 'explained-by-scope', 'explained-by-protocol', 'resolved'}, 'unresolved'))}; "
            f"claims={_code(claim_aliases.get(str(row.get('claim_ref_a') or ''), 'UNMAPPED'))},"
            f"{_code(claim_aliases.get(str(row.get('claim_ref_b') or ''), 'UNMAPPED'))}."
        )

    lines.extend(["", "## Perspective Synthesis", ""])
    if not perspectives:
        lines.append("- No typed perspective row was recorded.")
    for index, note in enumerate(perspectives, start=1):
        refs = [str(ref) for ref in note.get("source_refs") or [] if str(ref).strip()]
        mapped_refs = sorted({source_aliases.get(ref, "UNMAPPED") for ref in refs})
        lines.append(
            f"### {_code(f'P{index:03d}')}\n\n"
            f"- confidence={_code(_safe_enum(note.get('confidence'), {'high', 'medium', 'low'}))}; "
            f"source_count=`{len(refs)}`; "
            f"sources={','.join(_code(ref) for ref in mapped_refs) or '`none-recorded`'}."
        )

    lines.extend([
        "",
        "## Belief Update",
        "",
        "- Starting position: no narrative belief statement is imported into this authoritative surface.",
        *[
            f"- claim={_code(claim_aliases.get(str(claim.get('claim_id') or ''), 'C000'))}; "
            f"support={_code(_safe_enum((mappings.get(str(claim.get('claim_id'))) or {}).get('overall_support'), {'supported', 'partial', 'contradicted', 'not-found'}, 'not-found'))}."
            for claim in claims
        ],
        "- Net update: consult typed support states and the delivery boundary; no novelty conclusion is licensed.",
        "",
        "## Decision Implications",
        "",
        "- For the current project/idea/experiment, this packet is an audit and planning input only.",
        "- Human boundary: it does not choose a direction, launch an experiment, approve a project, or write to the vault.",
        "- A full narrative claim surface requires an independent, exact-author-bound, hash-bound novelty gate PASS.",
        "",
        "## Critical Uncertainties",
        "",
        *(
            [
                f"- blocker={_code(f'B{index:03d}')}; "
                f"evidence_ref_count=`{len(row.get('evidence_refs') or [])}`."
                for index, row in enumerate(delivery_boundary.get("external_blockers") or [], start=1)
                if isinstance(row, dict)
            ]
            or ["- No external blocker identifier was recorded; novelty remains UNVERIFIED independently of this count."]
        ),
        "",
        "## Next Most Valuable Evidence",
        "",
        "- Target: close the non-PASS scientific gates or obtain the independent novelty-gate artifact required by the delivery boundary.",
        "- Why this is highest value: it is the only route that can change the machine claim boundary.",
        "- Decision it unlocks: whether a full narrative surface may be rendered for director review.",
        "- Minimum standard: exact artifact references and SHA-256 bindings to the reviewed author bundle and gate output.",
        "",
        "## Evidence Pointers",
        "",
        "- `evidence/DISCOVER/research-brief.artifact.json` (raw author prose retained for audit; non-authoritative here)",
        "- `evidence/DISCOVER/research-delivery-boundary.artifact.json`",
        "- `evidence/DISCOVER/research-convergence-verdict.artifact.json`",
        "- `evidence/DISCOVER/claim-evidence-map.artifact.json`",
        "- `evidence/DISCOVER/contradiction-report.artifact.json`",
        "- `evidence/DISCOVER/research-perspective-P*.artifact.json` (raw perspective prose retained; non-authoritative here)",
        "",
        "## Verbatim External Blocker Inputs — Non-authoritative",
        "",
        "> The following source-preserved reviewer inputs are audit records, not scientific or novelty conclusions.",
    ])
    blockers = [
        row for row in delivery_boundary.get("external_blockers") or []
        if isinstance(row, dict)
    ]
    if not blockers:
        lines.append("- No external blocker prose was recorded.")
    for index, row in enumerate(blockers, start=1):
        lines.extend([
            f"### {_code(f'B{index:03d}')}",
            "",
            "    " + json.dumps({
                "kind": row.get("kind"),
                "description": row.get("description"),
                "required_input": row.get("required_input"),
            }, ensure_ascii=False, sort_keys=True),
        ])
    return "\n".join(lines).rstrip() + "\n"


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
    delivery_boundary = _delivery_boundary(report)
    if mode == "deep_research" and not _full_verified_render_allowed(delivery_boundary):
        return _machine_only_unverified_deep_research_markdown(
            evidence_table=evidence_table,
            claim_list=claim_list,
            claim_evidence_map=claim_evidence_map,
            report=report,
            contradiction_report=contradiction_report,
            perspective_notes=perspective_notes,
            delivery_boundary=delivery_boundary,
        )
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
        "## Delivery Boundary",
        "",
        f"- Delivery status: {_code(delivery_boundary.get('delivery_status') or 'USABLE_WITH_CAVEATS')}.",
        f"- Content convergence: {_code(delivery_boundary.get('content_convergence') or 'NOT_REVIEWED')}; "
        "this covers internal dossier defects only.",
        f"- Effective novelty status: {_code((delivery_boundary.get('novelty') or {}).get('status') or 'UNVERIFIED')}.",
        f"- Independent hash-bound novelty gate PASS: "
        f"{_code((delivery_boundary.get('novelty') or {}).get('independent_hash_bound_gate_pass', False))}.",
        f"- Novelty claim allowed: "
        f"{_code((delivery_boundary.get('claim_boundaries') or {}).get('novelty_claim_allowed', False))}.",
        "- This machine-derived boundary overrides any broader novelty-clearance wording in author or reviewer prose.",
        "- Scientific gates: "
        f"evidence={_code((delivery_boundary.get('scientific_gates') or {}).get('evidence'))}; "
        f"citation={_code((delivery_boundary.get('scientific_gates') or {}).get('citation'))}; "
        f"citation attribution={_code((delivery_boundary.get('scientific_gates') or {}).get('citation_attribution'))}; "
        f"existence={_code((delivery_boundary.get('scientific_gates') or {}).get('existence'))}.",
        *(
            [
                f"- External blocker {_code(blocker.get('blocker_id'))}: "
                f"kind={_code(blocker.get('kind'))}; "
                f"description={_one_line(blocker.get('description'))}; "
                f"required input={_one_line(blocker.get('required_input'))}."
                for blocker in delivery_boundary.get("external_blockers") or []
                if isinstance(blocker, dict)
            ]
            or ["- External blockers: none recorded in the delivery boundary."]
        ),
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
        f"- Content convergence: disposition={_code(report.get('content_convergence') or 'NOT_REVIEWED')}; "
        f"review round={report.get('content_review_round', 0)}; "
        f"open CRITICAL={report.get('open_content_critical', 0)}; "
        f"open MAJOR={report.get('open_content_major', 0)}; "
        f"open MINOR={report.get('open_content_minor', 0)}; "
        f"external blockers={report.get('content_external_blockers', 0)}. This is content-only, not novelty/project approval.",
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
    uncertainties.extend(
        f"{row.get('blocker_id')} [{row.get('kind')}]: {row.get('description')} "
        f"Required input: {row.get('required_input')}"
        for row in delivery_boundary.get("external_blockers") or []
        if isinstance(row, dict)
    )
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
            "evidence/DISCOVER/research-delivery-boundary.artifact.json",
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
    return _enforce_novelty_boundary("\n".join(lines).rstrip() + "\n", delivery_boundary)


def write_research_brief_markdown(run_dir, **kwargs) -> str:
    mode = str(kwargs.get("mode") or "")
    text = build_research_brief_markdown(**kwargs)
    perspective_ids = [
        str(note.get("perspective_id"))
        for note in (kwargs.get("perspective_notes") or [])
        if isinstance(note, dict) and note.get("perspective_id")
    ]
    machine_only = (
        mode == "deep_research"
        and not _full_verified_render_allowed(
            _delivery_boundary(kwargs.get("report") or {})
        )
    )
    if machine_only:
        required = (
            "render_policy: MACHINE_ONLY_UNVERIFIED",
            "## Delivery Boundary",
            "## Claim-Evidence Ledger",
            "## Verbatim External Blocker Inputs — Non-authoritative",
        )
        errors = [f"machine-only brief missing: {item}" for item in required if item not in text]
    else:
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
    boundary_status = _delivery_boundary(kwargs.get("report") or {}).get("delivery_status")
    advisory = {
        "contract_version": "research-markdown-advisory/v1",
        "delivery_blocking": False,
        "delivery_status": (
            "USABLE" if not errors and boundary_status == "USABLE" else "USABLE_WITH_CAVEATS"
        ),
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
    delivery_boundary = _delivery_boundary(report)
    if mode == "deep_research" and not _full_verified_render_allowed(delivery_boundary):
        gates = delivery_boundary.get("scientific_gates") or {}
        novelty = delivery_boundary.get("novelty") or {}
        blockers = [
            row for row in delivery_boundary.get("external_blockers") or []
            if isinstance(row, dict)
        ]
        safe_gate_values = {
            "PASS", "BLOCK", "WARN", "UNVERIFIED", "LEGACY_UNVERIFIED",
            "NOT_APPLICABLE", "NOT_REVIEWED", "UNKNOWN",
        }
        lines = [
            "---",
            "mode: deep_research",
            "render_policy: MACHINE_ONLY_UNVERIFIED",
            "records_project_decision: false",
            "writes_vault: false",
            "---",
            "",
            "# Deep Research Machine Evidence Brief — Renderer Fallback",
            "",
            "> **Delivery status: USABLE_WITH_CAVEATS.** The full deterministic renderer failed;",
            "> this fallback exposes only machine-controlled boundary fields. Raw worker prose remains",
            "> in JSON artifacts and is not imported into the authoritative claim surface.",
            "",
            "## Delivery Boundary",
            "",
            f"- Content convergence: {_code(_safe_enum(delivery_boundary.get('content_convergence'), {'REVISE', 'CONTENT_CONVERGED', 'CONTENT_CONVERGED_WITH_EXTERNAL_BLOCKERS', 'NOT_REVIEWED'}, 'NOT_REVIEWED'))}.",
            f"- Effective novelty status: {_code(_safe_enum(novelty.get('status'), {'VERIFIED_PASS', 'UNVERIFIED'}, 'UNVERIFIED'))}.",
            f"- Evidence gate: {_code(_safe_enum(gates.get('evidence') or report.get('evidence_gate'), safe_gate_values))}.",
            f"- Citation gate: {_code(_safe_enum(gates.get('citation') or report.get('citation_gate'), safe_gate_values))}.",
            f"- Citation-attribution gate: {_code(_safe_enum(gates.get('citation_attribution') or report.get('citation_attribution_gate'), safe_gate_values))}.",
            f"- Existence gate: {_code(_safe_enum(gates.get('existence') or report.get('existence_gate'), safe_gate_values))}.",
            f"- External blocker count: `{len(blockers)}`.",
            "",
            "## Claim-Evidence Ledger",
            "",
            "- Unavailable in the fallback surface; use the hash-bound JSON artifacts listed below.",
            "",
            "## Rendering Caveat",
            "",
            "- A deterministic renderer failure was recorded outside this claim surface.",
            "- Repair presentation only; do not rerun scientific workers.",
            "",
            "## Evidence Pointers",
            "",
            "- `evidence/DISCOVER/research-brief.artifact.json`",
            "- `evidence/DISCOVER/research-delivery-boundary.artifact.json`",
            "- `evidence/DISCOVER/claim-evidence-map.artifact.json`",
            "",
            "## Verbatim External Blocker Inputs — Non-authoritative",
            "",
            "> Source-preserved reviewer inputs below are audit records, not scientific or novelty conclusions.",
        ]
        if not blockers:
            lines.append("- No external blocker prose was recorded.")
        for index, row in enumerate(blockers, start=1):
            lines.extend([
                f"### {_code(f'B{index:03d}')}",
                "",
                "    " + json.dumps({
                    "kind": row.get("kind"),
                    "description": row.get("description"),
                    "required_input": row.get("required_input"),
                }, ensure_ascii=False, sort_keys=True),
            ])
        out.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
        return str(out)
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
        f"- Content convergence: `{delivery_boundary.get('content_convergence', 'NOT_REVIEWED')}`",
        f"- Effective novelty status: `{(delivery_boundary.get('novelty') or {}).get('status', 'UNVERIFIED')}`",
        f"- Claims extracted: `{report.get('n_claims', 'not recorded')}`",
        f"- Evidence mappings: `{report.get('n_mappings', 'not recorded')}`",
        "",
        "## External Blockers",
        "",
        *(
            [
                f"- `{row.get('blocker_id', 'not-recorded')}`: kind=`{row.get('kind', 'not-recorded')}`; "
                f"description={_one_line(row.get('description'))}; "
                f"required input={_one_line(row.get('required_input'))}."
                for row in delivery_boundary.get("external_blockers") or []
                if isinstance(row, dict)
            ]
            or ["- None recorded in the delivery boundary."]
        ),
        "",
        "## Rendering Caveat",
        "",
        f"- {reason}",
        "",
        "## Next Action",
        "",
        "- Repair only the Markdown renderer or missing presentation section; do not rerun scientific workers.",
    ]
    out.write_text(
        _enforce_novelty_boundary("\n".join(lines).rstrip() + "\n", delivery_boundary),
        encoding="utf-8",
    )
    return str(out)
