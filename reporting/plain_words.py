"""Plain-language vocabulary for every director-facing report.

Director lock (2026-08-01): a report the director reads must NOT be a wall of
acronyms and internal identifiers.  This module is the single place where the
machine's internal vocabulary is translated into ordinary Chinese.

Two rules only:

1. Every internal term that appears in a director report passes through
   :func:`say` (or :func:`explain`), so the wording is consistent everywhere.
2. An unknown term degrades honestly — it is returned unchanged rather than
   silently dropped, and :func:`untranslated` lists what still needs a word.
   A report is never blocked for vocabulary; that would be format policing.
"""
from __future__ import annotations

from typing import Iterable

# Short label: what the director sees instead of the internal token.
_LABEL: dict[str, str] = {
    # the twelve one-button modes, named the way the director talks about them
    "new_direction": "找研究方向（单域深挖）",
    "deep_ideation": "找研究方向（跨域最深）",
    "gap_breadth": "扫空白点",
    "evidence_review": "评证据（快）",
    "evidence_deep": "评证据（深）",
    "deep_research": "深度调研",
    "ingest_paper": "收一篇论文进库",
    "read_paper_deep": "精读一篇论文",
    "full_rigor_minimal": "设计实验（含预注册和统计）",
    "venue_readiness": "投稿前体检",
    "manuscript_authoring": "写稿",
    "manuscript_review": "独立审稿",
    # design-only modes the director may still hear named
    "design_experiment": "设计实验（简版）",
    "design_experiment_minimal": "设计实验（最小版）",
    "verify_result": "复核一个结果",
    "ideate_ring": "把点子排名次",
    "gap_scan": "扫空白点（简版）",
    "debug_failed_run": "查一次失败的运行",
    "tree_explore": "铺实验分支",
    "check_run": "查一次运行的状态",
    "full_new_direction": "找研究方向（全流程）",
    "power_analysis_review": "样本量够不够",
    "repo_code_audit": "审一遍代码仓库",
    "analysis_audit_panel": "复核分析结论",
    "aers_enhanced_research_pack": "科研工具包（参考用）",
    "m2_accept": "验收一个里程碑",
    # run lifecycle
    "running": "进行中",
    "done": "已完成",
    "failed": "中途停下",
    "planned": "只做了计划，还没真跑",
    "paused_for_director": "停下来等你拍板",
    "blocked": "被挡住了",
    # stages of the fixed research spine
    "PARSE": "读懂你的要求",
    "RECALL": "翻已有知识库",
    "DISCOVER": "找资料、找空白点",
    "IDEATE": "想点子、排名次",
    "DESIGN": "设计实验",
    "EXECUTE": "跑实验",
    "ANALYZE": "分析结果",
    "VERIFY": "复核、挑毛病",
    "RECORD": "存档",
    "REVIEW": "等你过目",
    "REPORT": "写给你看的报告",
    # verdicts
    "PASS": "通过",
    "BLOCK": "拦下了",
    "advisory": "有几处可以更好（不影响使用）",
    "pass": "达标",
    "fail": "不达标",
    "USABLE": "可以直接用",
    "USABLE_WITH_CAVEATS": "能用，但有前提要注意",
    "UNVERIFIED": "没能核实（不等于没有）",
    # resource capabilities
    "query_status": "只能查看状态",
    "pull_logs": "只能取日志",
    "submit_job": "可以提交任务去跑",
    # the content blocks a director report is expected to carry
    "research_question": "研究问题",
    "mechanism": "机制（为什么会这样）",
    "prior_art_delta": "跟别人已有工作的差别",
    "falsification": "怎么才能推翻它",
    "baselines_controls": "对照组",
    "kill_criteria": "止损条件",
    "feasibility": "可行性",
    "execution_order": "先做什么后做什么",
    "bottom_line": "核心结论",
    "source_quality": "资料靠不靠谱",
    "claim_evidence": "每句结论的证据出处",
    "counterevidence": "反面证据",
    "belief_update": "判断有什么变化",
    "decision_implication": "对决策的影响",
    "uncertainty": "不确定的地方",
    "next_evidence": "接下来该找什么证据",
    "ranked_gaps": "空白点排序",
    "why_worthwhile": "为什么值得做",
    "novelty_uncertainty": "新颖性还不确定的地方",
    "next_action": "下一步动作",
    "venue_fit": "跟目标会议合不合",
    "verdict": "结论",
    "independent_reviews": "独立审稿意见",
    "dimension_matrix": "各维度打分表",
    "reject_triggers": "会被拒稿的点",
    "repair_plan": "怎么补救",
    "hypothesis": "假设",
    "variables": "变量",
    "data_split": "数据怎么分",
    "metrics_statistics": "指标和统计方法",
    "preregistration": "开跑前先冻结的方案",
    "execution_status": "到底跑没跑",
    "exact_commands": "具体运行命令",
    "takeaway": "要点",
    "claims": "主张",
    "method_data_metrics": "方法、数据和指标",
    "project_relevance": "跟我们项目的关系",
    "next_read_action": "接下来读什么",
    "core_claims": "这篇论文的核心主张",
    "page_loci": "证据在第几页",
    "method_teardown": "方法拆解",
    "results": "结果",
    "critical_read": "值得质疑的地方",
    "project_transfer": "能迁到我们项目的部分",
    "reproducibility": "能不能复现",
    "reviewer_attack": "审稿人会攻击的点",
    # why a machine cannot take jobs yet (registry `execution_blockers`)
    "hdd4_at_100_percent_reported_capacity": "硬盘满了，放不下新数据",
    "hdd4_reported_100_percent_capacity": "硬盘满了，放不下新数据",
    "project_conda_environment_not_configured": "项目的 Python 环境还没装好",
    "slurm_client_present_but_cluster_config_missing": "排队系统装了但没配好，用不了",
    "scheduler_mode_not_operationally_configured": "还没定用哪种方式排队跑任务",
    "remote_write_and_run_preflight_not_authorized_or_verified": "还没做过写入和试跑的授权检查",
    # the four human gates
    "/idea-bet": "选一个研究方向下注",
    "/venue-pick": "选投稿的会议或期刊",
    "/venue-decide": "决定投还是再改",
    "/promote-to-vault": "把结果收进知识库",
}

# Longer gloss: used when a term first appears, or in the glossary block.
_GLOSS: dict[str, str] = {
    "OOF": "留一折预测：模型在没见过这批病人时给出的预测，比自己评自己诚实",
    "M0": "当前这版自动分割的结果，也就是「还没被修过的现状」",
    "scribble": "医生在图上随手划的一笔，告诉模型哪里错了",
    "intent": "这一笔到底想干嘛：加还是删、针对旧病灶还是新病灶、只修附近还是整个补完",
    "baseline": "对照组：用来证明新方法真的更好的旧方法",
    "ablation": "拆件实验：一次只拿掉一个部件，看是不是它在起作用",
    "prior_art": "别人已经做过的工作",
    "novelty": "新颖性：这件事到底有没有人做过",
    "falsifier": "推翻条件：什么结果出现就说明这个想法是错的",
    "kill_criteria": "止损条件：什么情况下应该停手别做了",
    "human_gate": "人类关卡：机器不能自己决定，必须你点头",
    "vault": "知识库：只放已经核实过的东西，是永久资产",
    "run_store": "草稿区：每次跑任务的中间产物，可以随时丢",
    "spec_only": "只有设计、还没做成一键按钮，得手动一步步驱动",
    "operated": "已经做成一键按钮，说一句话就能跑",
}

_GATE_ORDER = ("/idea-bet", "/venue-pick", "/venue-decide", "/promote-to-vault")


def say(term: object) -> str:
    """The director-facing label for one internal term (unknown → unchanged)."""
    key = str(term)
    return _LABEL.get(key, _GLOSS.get(key, key))


def explain(term: object) -> str:
    """`词（人话解释）` when a gloss exists, else just the label."""
    key = str(term)
    gloss = _GLOSS.get(key)
    if gloss:
        return f"{key}（{gloss}）"
    label = _LABEL.get(key)
    return f"{key}（{label}）" if label else key


def gate_label(gate: object) -> str:
    """A human gate rendered as `什么决定（命令）`."""
    key = str(gate)
    return f"{_LABEL[key]}（{key}）" if key in _LABEL else key


def known_gates() -> tuple[str, ...]:
    return _GATE_ORDER


def untranslated(terms: Iterable[object]) -> list[str]:
    """Terms that still have no plain-language word — a to-do list, never a gate."""
    return sorted({
        str(t) for t in terms
        if str(t) and str(t) not in _LABEL and str(t) not in _GLOSS
    })


def glossary_for(terms: Iterable[object]) -> list[tuple[str, str]]:
    """(term, gloss) pairs for the terms in `terms` that actually need explaining."""
    seen: dict[str, str] = {}
    for raw in terms:
        key = str(raw)
        gloss = _GLOSS.get(key)
        if gloss and key not in seen:
            seen[key] = gloss
    return sorted(seen.items())


__all__ = [
    "explain",
    "gate_label",
    "glossary_for",
    "known_gates",
    "say",
    "untranslated",
]
