"""Business-quality audit for director-facing research Markdown.

This module grades the product a researcher actually reads.  It deliberately
does not score ledgers, hashes, JSON volume, or safety metadata.  The checks are
small known-failure traps inspired by AERS' eval philosophy: a candidate output
must contain the scientific decisions that make the mode useful, not merely be
well-formed Markdown.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import yaml

from .delivery_status import USABLE, USABLE_WITH_CAVEATS


@dataclass(frozen=True)
class OutputContract:
    primary_globs: tuple[str, ...]
    min_chars: int
    concepts: dict[str, tuple[str, ...]]


_IDEA_CONCEPTS = {
    "research_question": ("research question", "problem statement", "研究问题"),
    "mechanism": ("mechanism", "causal chain", "机制"),
    "prior_art_delta": ("prior art", "novelty", "collision", "现有工作", "创新性"),
    "falsification": ("falsification", "falsifiable", "minimum experiment", "可证伪"),
    "baselines_controls": ("baseline", "control arm", "controls", "基线", "对照"),
    "kill_criteria": ("kill criteria", "stop condition", "停止条件", "终止标准"),
    "feasibility": ("feasibility", "resource", "data access", "可行性", "资源"),
    "execution_order": ("execution order", "next actions", "first wave", "执行顺序", "下一步"),
}

_EVIDENCE_CONCEPTS = {
    "bottom_line": ("bottom line", "executive read", "conclusion", "核心结论"),
    "source_quality": ("source quality", "evidence grade", "source ranking", "来源质量"),
    "claim_evidence": ("claim", "evidence map", "locus", "主张", "证据"),
    "counterevidence": ("contradiction", "counterevidence", "invalidation", "反证", "矛盾"),
    "belief_update": ("belief update", "confidence update", "更新判断", "置信度变化"),
    "decision_implication": ("decision implication", "project implication", "should we", "决策含义"),
    "uncertainty": ("uncertainty", "uncertainties", "limitation", "caveat", "不确定性", "局限"),
    "next_evidence": ("next evidence", "evidence to collect", "next search", "下一份证据"),
}


MODE_OUTPUT_CONTRACTS: dict[str, OutputContract] = {
    "new_direction": OutputContract(
        ("director-review/ideas/idea-bet-menu.md",), 1200, _IDEA_CONCEPTS
    ),
    "deep_ideation": OutputContract(
        ("director-review/ideas/idea-bet-menu.md",), 1400, _IDEA_CONCEPTS
    ),
    "evidence_review": OutputContract(
        ("director-review/evidence/evidence-review-brief.md",), 800, _EVIDENCE_CONCEPTS
    ),
    "evidence_deep": OutputContract(
        ("director-review/evidence/evidence-deep-brief.md",), 1200, _EVIDENCE_CONCEPTS
    ),
    "deep_research": OutputContract(
        ("director-review/research/research-brief.md",), 1400, _EVIDENCE_CONCEPTS
    ),
    "gap_breadth": OutputContract(
        ("director-review/gaps/gap-scan.md",),
        900,
        {
            "ranked_gaps": ("ranked gaps", "gap ranking", "空白点排序"),
            "why_worthwhile": ("why worth studying", "value of the gap", "为什么值得"),
            "evidence": ("evidence anchor", "source", "证据锚点"),
            "novelty_uncertainty": ("novelty uncertainty", "unverified", "创新性不确定"),
            "falsification": ("falsification experiment", "first experiment", "可证伪实验"),
            "kill_criteria": ("kill criteria", "stop condition", "终止标准"),
            "next_action": ("next action", "next step", "下一步"),
        },
    ),
    "venue_readiness": OutputContract(
        ("director-review/venue/venue-readiness.md",),
        1000,
        {
            "venue_fit": ("venue fit", "venue rubric", "投稿匹配"),
            "verdict": ("verdict", "readiness", "结论"),
            "independent_reviews": ("reviewer panel", "reviewer", "审稿人"),
            "dimension_matrix": ("dimension matrix", "score matrix", "维度矩阵"),
            "reject_triggers": ("reject trigger", "fatal flaw", "拒稿风险"),
            "repair_plan": ("fix", "repair", "required revision", "修复"),
            "next_action": ("next action", "next step", "下一步"),
        },
    ),
    "full_rigor_minimal": OutputContract(
        ("director-review/experiments/experiment-plan.md",),
        1400,
        {
            "research_question": ("research question", "研究问题"),
            "hypothesis": ("hypothesis", "假设"),
            "variables": ("variables", "independent variable", "变量"),
            "baselines_controls": ("baseline", "control arm", "基线", "对照"),
            "data_split": ("data and split", "split", "数据划分"),
            "metrics_statistics": ("statistical plan", "confidence interval", "metric", "统计计划"),
            "preregistration": ("preregistration", "frozen", "预注册"),
            "execution_status": ("execution status", "planned", "执行状态"),
            "kill_criteria": ("kill criteria", "failure criteria", "终止标准"),
            "exact_commands": ("exact run commands", "python ", "运行命令"),
        },
    ),
    "ingest_paper": OutputContract(
        ("director-review/papers/paper-note.md", "director-review/papers/*.md"),
        600,
        {
            "source": ("source", "doi", "arxiv", "来源"),
            "takeaway": ("takeaway", "summary", "核心结论"),
            "claims": ("claim", "主张"),
            "method_data_metrics": ("method", "dataset", "metric", "方法", "数据"),
            "project_relevance": ("project relevance", "relation to thesis", "项目关系"),
            "next_read_action": ("next read", "deep read", "下一步阅读"),
        },
    ),
    "read_paper_deep": OutputContract(
        ("director-review/papers/*.md",),
        1800,
        {
            "core_claims": ("core claim", "claim", "核心主张"),
            "page_loci": ("page ", "locus", "table ", "figure ", "页码"),
            "method_teardown": ("method", "loss", "training", "inference", "方法拆解"),
            "results": ("result", "metric", "baseline", "结果"),
            "critical_read": ("limitation", "weakness", "distrust", "局限", "质疑"),
            "project_transfer": ("project implication", "transfer", "thesis", "项目启示"),
            "reproducibility": ("reproducibility", "code", "material", "可复现"),
            "reviewer_attack": ("reviewer", "attack point", "审稿"),
            "next_action": ("next action", "next experiment", "下一步"),
        },
    ),
    "manuscript_authoring": OutputContract(
        ("director-review/manuscript/00-OVERVIEW.md",),
        600,
        {
            "local_evidence": ("local-literature coverage", "local evidence", "coverage"),
            "frozen_contract": ("frozen manuscript-contract", "manuscript-contract", "frozen"),
            "canonical_source": ("canonical source", "source-tree", "source/"),
            "build_truth": ("build state", "compiled PDF", "toolchain_missing"),
            "quality_status": ("daily_state", "submission_ready", "quality-report"),
            "review_boundary": ("independent manuscript review", "review separation", "self-audit"),
            "decision_boundary": ("does not submit", "does not publish", "does not promote"),
        },
    ),
    "manuscript_review": OutputContract(
        ("director-review/manuscript/reviewer-report.md",),
        600,
        {
            "review_status": ("daily state", "submission ready", "separate review-run"),
            "frozen_input": ("frozen", "authoring", "manuscript"),
            "findings": ("reconciled findings", "finding", "severity"),
            "evidence": ("evidence", "origin", "receipt"),
            "repair": ("required fix", "repair", "advisory"),
            "independence_limit": ("not independent", "not independently", "advisory"),
            "decision_boundary": ("unapplied", "does not submit", "director"),
        },
    ),
    "manuscript_reconstruction": OutputContract(
        ("director-review/manuscript/reconstruction-report.md",),
        600,
        {
            "review_decomposition": ("review decomposition", "reviewer point", "current_status"),
            "lossless_coverage": ("segment", "coverage", "non-actionable"),
            "claim_verification": ("claim verification", "verified-true", "unverifiable-here"),
            "repair_lanes": ("repair lanes and owners", "prose_repair", "mechanical_recompute"),
            "closure_criteria": ("acceptance", "already_satisfied", "current locus"),
            "decision_boundary": ("decisions for the director", "director_decision", "does not edit"),
        },
    ),
    # ---- wave 2 (2026-08-04) -----------------------------------------------------------------
    # Every operated mode must declare what BUSINESS content its director Markdown has to carry —
    # the eval harness treats a missing contract as a critical failure, because a mode with no
    # depth contract can ship a well-formed but empty page. Each concept below is anchored to a
    # `required_sections` entry the renderer BLOCKs on, so the graded phrases are guaranteed to be
    # renderable rather than aspirational.
    "gap_scan": OutputContract(
        ("director-review/gaps/gap-scan.md",), 700,
        {
            "search_scope": ("search scope", "检索范围"),
            "candidate_gaps": ("candidate gaps", "候选空白"),
            "evidence_anchors": ("evidence and source anchors", "source anchor", "证据锚点"),
            "gap_classification": ("gap classification", "空白分类"),
            "unknowns": ("unknowns and next searches", "unknown", "还缺"),
            "no_novelty_claim": ("not a novelty", "no novelty claim", "不谈新颖性", "未核实"),
        },
    ),
    "full_new_direction": OutputContract(
        ("director-review/ideas/full-new-direction-brief.md",), 900,
        {
            "problem_landscape": ("problem landscape", "问题版图"),
            "model_dataset": ("model and dataset opportunities", "dataset", "数据集"),
            "evidence_quality": ("evidence quality", "证据质量"),
            "direction_theses": ("candidate direction theses", "direction thesis", "方向论纲"),
            "collision_uncertainty": ("collision and uncertainty", "collision", "查重", "未核实"),
            "handoff": ("recommended handoff", "/idea-bet", "交接"),
        },
    ),
    "design_experiment": OutputContract(
        ("director-review/experiments/experiment-design.md",), 900,
        {
            "research_question": ("research question and hypotheses", "研究问题"),
            "variables_conditions": ("variables and conditions", "变量", "对照"),
            "data_split": ("data and split protocol", "split", "数据划分"),
            "baseline_fairness": ("method and baseline fairness", "baseline", "基线"),
            "metrics_analysis": ("metrics and analysis plan", "metric", "指标"),
            "director_decisions": ("risks and director decisions", "unresolved", "待你决定"),
        },
    ),
    "power_analysis_review": OutputContract(
        ("director-review/experiments/power-analysis-review.md",), 700,
        {
            "decision_question": ("decision question", "决定问题"),
            "assumptions": ("inputs and assumptions", "assumption", "假设"),
            "power_analysis": ("power or precision analysis", "power", "功效"),
            "sensitivity": ("sensitivity scenarios", "sensitivity", "敏感性"),
            "design_changes": ("recommended design changes", "design change", "设计改法"),
            "remaining_uncertainty": ("remaining uncertainty", "uncertainty", "不确定"),
        },
    ),
    "m2_accept": OutputContract(
        ("director-review/experiments/m2-acceptance-report.md",), 1000,
        {
            "frozen_design": ("frozen design", "冻结设计"),
            "execution_journal": ("execution journal", "journal", "执行记录"),
            "result_analysis": ("result analysis", "结果分析"),
            "sanity_parity": ("sanity and parity checks", "parity", "一致性"),
            "adversarial": ("adversarial verification", "adversarial", "对抗复核"),
            "acceptance_inputs": ("acceptance decision inputs", "acceptance", "验收"),
            "execution_boundary": ("plan, not a result", "Really ran", "没有真实"),
        },
    ),
    "analysis_audit_panel": OutputContract(
        ("director-review/analysis/analysis-audit-report.md",), 900,
        {
            "analysis_scope": ("analysis scope", "分析范围"),
            "sanity_baseline": ("sanity and baseline findings", "baseline", "基线"),
            "variance_subgroup": ("variance and subgroup findings", "variance", "方差"),
            "failure_cases": ("failure cases", "失败案例"),
            "figure_audit": ("figure and visualization audit", "figure", "图表"),
            "calibrated_claims": ("calibrated claims", "claim", "主张强度"),
            "blocking_issues": ("blocking issues and repairs", "blocking", "阻断"),
        },
    ),
    "verify_result": OutputContract(
        ("director-review/verification/result-verification.md",), 900,
        {
            "result_under_review": ("result under review", "被审结果"),
            "review_config": ("review configuration", "review lens", "审视镜头"),
            "panel_findings": ("independent panel findings", "panel", "独立审稿"),
            "baseline_history": ("baseline and historical context", "baseline", "历史"),
            "claim_calibration": ("claim calibration", "cannot claim", "不能声称"),
            "next_actions": ("required next actions", "next action", "下一步"),
        },
    ),
    "check_run": OutputContract(
        ("director-review/operations/run-health-brief.md",), 600,
        {
            "run_status": ("current run status", "运行状态"),
            "alerts": ("evidence-backed alerts", "alert", "告警"),
            "intervention_options": ("intervention options", "intervention", "干预"),
            "unresolved": ("unresolved decisions", "unresolved", "待定"),
            "read_only_boundary": ("not been done", "read-only", "只读", "还没做"),
            "execution_boundary": ("plan, not a result", "Really ran", "没有真实"),
        },
    ),
    "repo_code_audit": OutputContract(
        ("director-review/code/repo-code-audit.md",), 800,
        {
            "repo_scope": ("repository scope", "仓库范围"),
            "prioritized_findings": ("prioritized findings", "finding", "发现"),
            "patch_plan": ("patch plan", "补丁计划"),
            "authorized_changes": ("authorized changes", "authorized", "已授权改动"),
            "test_evidence": ("test and reproduction evidence", "reproduction", "复现证据"),
            "residual_risks": ("residual risks", "residual", "残留风险"),
        },
    ),
    # ---- wave-2 backlog closed (2026-08-07) -------------------------------------------------
    # The last two modules had recipes written but no tests, so they were deliberately left
    # unregistered until now. Each concept below is anchored to a `required_sections` entry the
    # renderer BLOCKs on, matching every other wave-2 contract's discipline.
    "ideate_ring": OutputContract(
        ("director-review/ideas/idea-bet-menu.md",), 900,
        {
            "opportunity_set": ("opportunity set", "机会点"),
            "falsifiable_hypotheses": ("falsifiable hypotheses", "falsifiable", "可证伪"),
            "tournament_results": ("tournament results", "pairwise", "淘汰赛"),
            "evolved_lineage": ("evolved ideas and lineage", "lineage", "血缘", "进化"),
            "prior_art_collisions": ("prior-art collisions", "collision", "查重"),
            "no_self_bet": ("director bet menu", "/idea-bet", "下注"),
        },
    ),
    "aers_enhanced_research_pack": OutputContract(
        ("director-review/research/aers-enhanced-research-pack.md",), 1000,
        {
            "aers_applicability": ("aers references and applicability", "applicab", "适用性"),
            "search_strategy": ("literature search strategy", "search strategy", "检索策略"),
            "data_protocol": ("data-wrangling protocol", "data protocol", "数据协议"),
            "reproducibility": ("reproducibility package", "reproducib", "复现"),
            "benchmark_evidence": ("benchmark evidence", "benchmark", "基准证据"),
            "no_execution_claim": ("did not run", "plan, not a result", "没有真实"),
            "submission_checklist": ("submission checklist", "投稿清单"),
            "bibliography_audit": ("bibliography audit", "bibliography", "文献核验"),
        },
    ),
}


# Correct UTF-8 Chinese aliases are layered over the historical contract.  The
# older mojibake literals remain readable as legacy data but never determine a
# Chinese report's score.
_CN_TERMS = {
    "research_question": ("研究问题",), "mechanism": ("机制", "因果链"),
    "prior_art_delta": ("现有工作", "创新性"), "falsification": ("可证伪",),
    "baselines_controls": ("基线", "对照"), "kill_criteria": ("停止条件", "终止标准"),
    "feasibility": ("可行性", "资源"), "execution_order": ("执行顺序", "下一步"),
    "bottom_line": ("核心结论",), "source_quality": ("来源质量",),
    "claim_evidence": ("主张", "证据"), "counterevidence": ("反证", "矛盾"),
    "belief_update": ("更新判断", "置信度变化"), "decision_implication": ("决策含义",),
    "uncertainty": ("不确定性", "局限"), "next_evidence": ("下一份证据",),
    "ranked_gaps": ("空白点排序",), "why_worthwhile": ("为什么值得",),
    "evidence": ("证据锚点",), "novelty_uncertainty": ("创新性不确定",),
    "next_action": ("下一步",), "venue_fit": ("投稿匹配",), "verdict": ("结论",),
    "independent_reviews": ("审稿人", "独立评审"), "dimension_matrix": ("维度矩阵",),
    "reject_triggers": ("拒稿风险",), "repair_plan": ("修复", "补充计划"),
    "hypothesis": ("假设",), "variables": ("变量",), "data_split": ("数据划分",),
    "metrics_statistics": ("统计计划", "指标"), "preregistration": ("预注册",),
    "execution_status": ("执行状态",), "exact_commands": ("运行命令",),
    "source": ("来源",), "takeaway": ("核心结论",), "claims": ("主张",),
    "method_data_metrics": ("方法", "数据", "指标"), "project_relevance": ("项目关系",),
    "next_read_action": ("下一步阅读",), "core_claims": ("核心主张",),
    "page_loci": ("页码", "证据位置"), "method_teardown": ("方法拆解",),
    "results": ("结果",), "critical_read": ("局限", "质疑"),
    "project_transfer": ("项目启示", "迁移"), "reproducibility": ("可复现",),
    "reviewer_attack": ("审稿攻击点",),
}

MODE_OUTPUT_CONTRACTS = {
    mode: OutputContract(
        contract.primary_globs,
        contract.min_chars,
        {
            concept: tuple(terms) + tuple(_CN_TERMS.get(concept, ()))
            for concept, terms in contract.concepts.items()
        },
    )
    for mode, contract in MODE_OUTPUT_CONTRACTS.items()
}


def _contains_any(text: str, terms: Iterable[str]) -> bool:
    normalized = text.casefold()
    return any(str(term).casefold() in normalized for term in terms)


def audit_markdown_text(mode: str, markdown: str) -> dict[str, Any]:
    """Grade one mode's Markdown without turning presentation gaps into a stop."""
    if mode not in MODE_OUTPUT_CONTRACTS:
        raise KeyError(f"no research output contract for mode {mode!r}")
    contract = MODE_OUTPUT_CONTRACTS[mode]
    text = str(markdown or "")
    advisories: list[str] = []
    if len(text.strip()) < contract.min_chars:
        advisories.append(f"too_short:{len(text.strip())}<{contract.min_chars}")
    if text.lstrip().startswith("{") and "## " not in text:
        advisories.append("json_or_machine_payload_is_not_director_markdown")
    heading_count = sum(1 for line in text.splitlines() if line.startswith("## "))
    if heading_count < 4:
        advisories.append(f"too_few_director_sections:{heading_count}<4")

    concept_results = {
        concept: _contains_any(text, terms)
        for concept, terms in contract.concepts.items()
    }
    advisories.extend(
        f"missing_business_concept:{concept}"
        for concept, passed in concept_results.items()
        if not passed
    )
    passed = sum(1 for value in concept_results.values() if value)
    total = len(concept_results)
    return {
        "mode": mode,
        "status": "pass" if not advisories else "advisory",
        "delivery_status": USABLE if not advisories else USABLE_WITH_CAVEATS,
        "score": round(passed / total, 3) if total else 0.0,
        "character_count": len(text.strip()),
        "heading_count": heading_count,
        "concepts": concept_results,
        # Kept as an alias for callers that still render the old field.
        "failures": advisories,
        "advisories": advisories,
    }


def audit_run_output(run_dir: str | Path, mode: str) -> dict[str, Any]:
    """Read a completed run's primary Markdown product and grade it."""
    root = Path(run_dir)
    contract = MODE_OUTPUT_CONTRACTS.get(mode)
    if contract is None:
        return {"mode": mode, "status": "not_scored", "paths": [], "failures": ["no_contract"]}
    paths: list[Path] = []
    for pattern in contract.primary_globs:
        paths.extend(path for path in root.glob(pattern) if path.is_file())
    unique_paths = sorted(set(paths))
    if not unique_paths:
        return {
            "mode": mode,
            "status": "fail",
            "delivery_status": "BLOCK",
            "paths": [],
            "score": 0.0,
            "failures": ["primary_director_markdown_missing"],
        }
    combined = "\n\n".join(path.read_text(encoding="utf-8") for path in unique_paths)
    result = audit_markdown_text(mode, combined)
    result["paths"] = [path.relative_to(root).as_posix() for path in unique_paths]
    return result


def _contract_era(run_dir: Path) -> str:
    """`current` if the run pinned a product contract, else `legacy`.

    A run that predates the product contract cannot grow a conforming Markdown
    product by re-rendering — only by re-running it, which is the director's
    call and not always worth the compute.  Grading such runs against today's
    contract and then blocking on the result produces a board that is red
    forever and therefore stops being read.  So the era is recorded, and the
    caller decides what blocks.  This hides nothing: a legacy failure is still
    counted, listed and named.
    """
    frame = run_dir / "task_frame.artifact.json"
    if not frame.is_file():
        return "legacy"
    try:
        payload = (json.loads(frame.read_text(encoding="utf-8")) or {}).get("payload") or {}
    except (OSError, ValueError):
        return "legacy"
    contract = payload.get("product_contract")
    return "current" if isinstance(contract, dict) and contract.get("product_version") else "legacy"


def audit_completed_runs(runs_dir: str | Path) -> dict[str, Any]:
    """Audit only completed operated runs; unfinished historical work is reported separately."""
    root = Path(runs_dir)
    rows: list[dict[str, Any]] = []
    if root.exists():
        for manifest_path in sorted(root.rglob("manifest.yaml")):
            try:
                manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
            except Exception as exc:
                rows.append({"status": "invalid_manifest", "path": str(manifest_path), "error": str(exc)})
                continue
            if not isinstance(manifest, dict) or manifest.get("status") != "done":
                continue
            mode = str(manifest.get("mode") or "")
            result = audit_run_output(manifest_path.parent, mode)
            result.update({
                "run_id": str(manifest.get("run_id") or manifest_path.parent.name),
                "project": manifest.get("project"),
                "contract_era": _contract_era(manifest_path.parent),
            })
            rows.append(result)
    failures = [row for row in rows if row.get("status") == "fail"]
    return {
        "completed_run_count": len(rows),
        "pass": sum(1 for row in rows if row.get("status") == "pass"),
        "advisory": sum(1 for row in rows if row.get("status") == "advisory"),
        "fail": len(failures),
        # Split so a permanently-unrepairable backlog cannot mask a fresh regression.
        "fail_current": sum(1 for row in failures if row.get("contract_era") == "current"),
        "fail_legacy": sum(1 for row in failures if row.get("contract_era") != "current"),
        "legacy_failure_run_ids": sorted(str(row.get("run_id") or "") for row in failures
                                         if row.get("contract_era") != "current"),
        "not_scored": sum(1 for row in rows if row.get("status") == "not_scored"),
        "runs": rows,
    }


def contract_summary() -> dict[str, Any]:
    return {
        mode: {
            "primary_globs": list(contract.primary_globs),
            "min_chars": contract.min_chars,
            "business_concepts": sorted(contract.concepts),
        }
        for mode, contract in sorted(MODE_OUTPUT_CONTRACTS.items())
    }


__all__ = [
    "MODE_OUTPUT_CONTRACTS",
    "OutputContract",
    "audit_completed_runs",
    "audit_markdown_text",
    "audit_run_output",
    "contract_summary",
]
