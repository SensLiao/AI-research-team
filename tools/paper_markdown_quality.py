"""Deterministic body-level coverage audit for deep paper-reading Markdown.

Writer-declared ``covered_*`` arrays are useful navigation metadata, but they
are not evidence that the prose contains the promised content.  This module
checks the rendered body against the validated reading artifacts themselves.
"""
from __future__ import annotations

import math
import re
import unicodedata

from .delivery_status import USABLE, USABLE_WITH_CAVEATS


_STOP = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "in", "is",
    "it", "of", "on", "or", "that", "the", "this", "to", "was", "were", "with",
    "claim", "paper", "reported", "reports", "result", "results", "test",
}

_SECTION_ALIASES = {
    "decision-need": ("decision need", "decision question", "reading objective", "decision summary", "决策问题", "阅读目的", "一屏决策摘要", "阅读判断"),
    "project-alignment": ("project alignment", "thesis relevance", "项目关联", "课题关联"),
    "claims-and-evidence": ("claims and evidence", "claim evidence", "conclusions and evidence", "主张与证据", "关键结论与证据", "证据映射"),
    "method-or-theory": ("method reconstruction", "method teardown", "method", "algorithm and math", "方法", "理论"),
    "numeric-results": ("numeric results", "result audit", "quantitative results", "数值结果", "结果审计"),
    "figures-and-tables": ("figure table reading", "figures and tables", "figure/table reading", "图表解读", "图表"),
    "critical-appraisal": ("critical appraisal", "appraisal and transfer", "reviewer appraisal", "批判性评价", "局限性"),
    "reproducibility": ("reproducibility", "复现", "可复现性"),
    "domain-transfer": ("domain transfer", "appraisal and transfer", "transfer boundary", "跨域迁移", "项目迁移", "迁移边界"),
    "independent-critique": ("independent critique", "second reader", "blind reader", "独立复核", "盲读"),
    "next-actions": ("next actions", "next steps", "下一步", "后续行动"),
    "medical-imaging-checklist": ("medical imaging checklist", "医学影像检查表"),
    "transfer-matrix": ("transfer matrix", "迁移矩阵"),
}


def _normalize(value) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).lower()
    return " ".join(re.findall(r"[a-z0-9]+|[\u4e00-\u9fff]+", text))


def _tokens(value) -> list[str]:
    out: list[str] = []
    for token in _normalize(value).split():
        if re.fullmatch(r"[\u4e00-\u9fff]+", token):
            out.extend(token[i:i + 2] for i in range(max(1, len(token) - 1)))
        elif token not in _STOP and len(token) > 1:
            out.append(token)
    return out


def _semantic_covered(markdown: str, target, *, ratio: float = 0.5, cap: int = 4) -> bool:
    target_norm = _normalize(target)
    body_norm = _normalize(markdown)
    if not target_norm:
        return True
    if target_norm in body_norm:
        return True
    target_tokens = set(_tokens(target))
    if not target_tokens:
        return False
    body_tokens = set(_tokens(markdown))
    required = min(cap, max(1, math.ceil(len(target_tokens) * ratio)))
    return len(target_tokens & body_tokens) >= required


def _headings(markdown: str) -> list[str]:
    return [_normalize(match.group(1)) for line in markdown.splitlines()
            if (match := re.match(r"^#{1,6}\s+(.+?)\s*$", line.strip()))]


def _heading_present(headings: list[str], aliases: tuple[str, ...]) -> bool:
    normalized_aliases = tuple(_normalize(alias) for alias in aliases)
    return any(any(alias in heading for alias in normalized_aliases) for heading in headings)


def _unique_text(values) -> list[str]:
    out: list[str] = []
    seen = set()
    for value in values:
        text = str(value or "").strip()
        key = _normalize(text)
        if text and key and key not in seen:
            seen.add(key)
            out.append(text)
    return out


def _numeric_present(markdown: str, value: str) -> bool:
    body = unicodedata.normalize("NFKC", markdown).replace("−", "-")
    needle = unicodedata.normalize("NFKC", value).replace("−", "-")
    return bool(re.search(rf"(?<![\d.]){re.escape(needle)}(?![\d.])", body))


def audit_paper_markdown(markdown: str, bundles: dict, *, medical: bool = False) -> dict:
    """Return a body-derived coverage verdict; never consult writer declarations."""
    errors: list[str] = []
    coverage = {
        "claims": [],
        "visual_refs": [],
        "visual_content": [],
        "method_components": [],
        "numeric_results": [],
        "limitations_and_transfer": [],
        "sections": [],
    }
    body = str(markdown or "")
    headings = _headings(body)

    required_sections = [
        "decision-need", "project-alignment", "claims-and-evidence", "method-or-theory",
        "numeric-results", "figures-and-tables", "critical-appraisal", "reproducibility",
        "domain-transfer", "independent-critique", "next-actions",
    ]
    if medical:
        required_sections += ["medical-imaging-checklist", "transfer-matrix"]
    for section in required_sections:
        present = _heading_present(headings, _SECTION_ALIASES[section])
        coverage["sections"].append({"section": section, "covered": present})
        if not present:
            errors.append(f"Markdown body missing semantic section: {section}")

    for claim in (bundles.get("claim_list") or {}).get("claims") or []:
        claim_id = str(claim.get("claim_id") or "").strip()
        text = str(claim.get("text") or "").strip()
        id_present = bool(claim_id and re.search(rf"(?<![A-Za-z0-9_-]){re.escape(claim_id)}(?![A-Za-z0-9_-])", body, re.I))
        meaning_present = _semantic_covered(body, text, ratio=0.35)
        covered = id_present and meaning_present
        coverage["claims"].append({"claim_id": claim_id, "covered": covered})
        if not covered:
            errors.append(f"Markdown body does not substantively cover load-bearing claim {claim_id}")

    structure = bundles.get("paper_structure") or {}
    visual_refs = []
    visual_refs += [item.get("figure_ref") for item in structure.get("figures") or [] if item.get("load_bearing")]
    visual_refs += [item.get("table_ref") for item in structure.get("tables") or [] if item.get("load_bearing")]
    for ref in _unique_text(visual_refs):
        covered = _normalize(ref) in _normalize(body)
        coverage["visual_refs"].append({"ref": ref, "covered": covered})
        if not covered:
            errors.append(f"Markdown body omits load-bearing visual reference: {ref}")

    readings = {
        _normalize(item.get("figure_ref")): item
        for item in (bundles.get("figure_reading") or {}).get("figures") or []
        if isinstance(item, dict) and item.get("figure_ref")
    }
    for ref in _unique_text(visual_refs):
        item = readings.get(_normalize(ref)) or {}
        axes = str(item.get("axes") or "").strip()
        take_home = str(item.get("take_home") or "").strip()
        distrust = str(item.get("distrust") or "").strip()
        content_covered = bool(
            axes and take_home
            and _semantic_covered(body, axes, ratio=0.3, cap=3)
            and _semantic_covered(body, take_home, ratio=0.35, cap=3)
            and (not distrust or _semantic_covered(body, distrust, ratio=0.35, cap=3))
        )
        coverage["visual_content"].append({"ref": ref, "covered": content_covered})
        if not content_covered:
            errors.append(
                f"Markdown body names {ref} but does not explain its visual content, supported "
                "conclusion, and distrust boundary"
            )

    method = bundles.get("method_teardown") or {}
    method_targets = [method.get("representation"), method.get("training_flow"), method.get("inference_flow")]
    method_targets += [term.get("term") for term in method.get("loss_terms") or [] if isinstance(term, dict)]
    for component in _unique_text(method_targets):
        covered = _semantic_covered(body, component, ratio=0.3, cap=3)
        coverage["method_components"].append({"component": component, "covered": covered})
        if not covered:
            errors.append(f"Markdown body omits method component: {component}")

    for item in (bundles.get("result_table_audit") or {}).get("audited_items") or []:
        item_ref = str(item.get("item_ref") or "").strip()
        comparison = str(item.get("reported_comparison") or "").strip()
        metric = str(item.get("metric") or "").strip()
        numbers = re.findall(r"(?<![A-Za-z])[-+]?\d+(?:\.\d+)?%?", comparison)
        comparison_covered = (
            all(_numeric_present(body, number) for number in numbers)
            if numbers else _semantic_covered(body, comparison, ratio=0.5, cap=3)
        )
        covered = (
            _normalize(item_ref) in _normalize(body)
            and _semantic_covered(body, metric, ratio=1.0, cap=2)
            and comparison_covered
        )
        coverage["numeric_results"].append({"item_ref": item_ref, "covered": covered})
        if not covered:
            errors.append(f"Markdown body omits key audited result: {item_ref} / {metric} / {comparison}")

    appraisal = bundles.get("paper_appraisal") or {}
    transfer = bundles.get("domain_transfer_note") or {}
    caveats = []
    caveats += appraisal.get("limitations_acknowledged") or []
    caveats += appraisal.get("limitations_unacknowledged") or []
    caveats += transfer.get("evidence_limits") or []
    caveats += transfer.get("not_usable_for") or []
    caveats += transfer.get("required_local_validation") or []
    for caveat in _unique_text(caveats):
        covered = _semantic_covered(body, caveat, ratio=0.5, cap=3)
        coverage["limitations_and_transfer"].append({"caveat": caveat, "covered": covered})
        if not covered:
            errors.append(f"Markdown body omits limitation/transfer caveat: {caveat}")

    reconciliation = bundles.get("paper_reading_reconciliation") or {}
    warning = str(reconciliation.get("director_warning") or "").strip()
    if warning and not _semantic_covered(body, warning, ratio=0.35, cap=4):
        errors.append("Markdown body omits the reconciler's director warning")
    saturation_boundary = (
        "evidence saturation was not assessed",
        "evidence saturation not assessed",
        "未评估多来源证据饱和度",
        "单篇论文不能判断证据饱和",
    )
    if not any(_normalize(signal) in _normalize(body) for signal in saturation_boundary):
        errors.append("Markdown body must state that multi-source evidence saturation was not assessed")

    return {
        "verdict": "PASS" if not errors else "PASS_WITH_CAVEATS",
        "delivery_status": USABLE if not errors else USABLE_WITH_CAVEATS,
        "delivery_blocking": False,
        "errors": errors,
        "coverage": coverage,
        "writer_declarations_consulted": False,
    }
