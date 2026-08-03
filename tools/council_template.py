"""Authoring template + director-facing rendering for the mechanism council (v4 P5).

ADDITION over the existing council — **not** a rewrite. ``tools/mechanism_council.py`` already owns
the contract: who sits on the panel, when it activates, how six independent contributions are bound
by hash to one compiled chain, and the blind (identity-free) rendering that feeds a review. Three
things it did not have, and this module adds:

  1. an AUTHORING TEMPLATE per role, DERIVED from the JSON Schema + the contract, so a contributor is
     handed the exact required shape instead of guessing it (a guess either fails validation or
     silently under-fills — the schema lets ``proposed_mechanisms`` and ``experiments`` be empty);
  2. a DIRECTOR-facing rendering — the existing ``render_anonymous_candidate`` deliberately strips
     producer identity and receipts *because* it feeds a blind review, which makes it exactly the
     wrong artifact for the person who has to decide;
  3. field-level errors in plain Chinese, and refusal of a template that was never filled in.

Two honesty properties hold by construction, and both are test-pinned:

  * **The template cannot drift from the contract.** Every field, enum, and array minimum is read out
    of the schema at call time; the only hand-written part is the Chinese label table, whose coverage
    of the schema's required fields is asserted.
  * **A blank template is not a submission.** Every field a human must decide is left as a
    ``<TODO：…>`` placeholder, and :func:`check_contribution` rejects any placeholder that survived.

Nothing here can claim a result. The report path reads the truth boundary off the bundle instead of
asserting one of its own, so a bundle that says ``DESIGN_ONLY`` renders as design-only.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional

from research_agent_teams.tools.mechanism_council import (
    MechanismCouncilError,
    load_contract,
)
from research_agent_teams.tools.validate_artifact import SCHEMA_DIR, validate_against

CONTRIBUTION_SCHEMA = "mechanism_council_contribution.schema.json"
BUNDLE_SCHEMA = "mechanism_council_bundle.schema.json"
COMPILER_ROLE = "hypothesis_compiler"

#: Any string still carrying this prefix was never filled in by a human.
PLACEHOLDER = "<TODO："

#: Plain-Chinese label per schema field path. This table is the ONLY hand-written part of the
#: template; `tests/test_council_template.py` asserts it covers every required path the two schemas
#: actually declare, so adding a schema field without a label fails the suite rather than rendering a
#: bare English key at the director.
FIELD_WORDS: dict[str, str] = {
    # --- contribution ---
    "contract_version": "契约版本（固定值，不用你填）",
    "role": "你这一席的角色（固定值，不用你填）",
    "input_sha256": "冻结工单的哈希（固定值 —— 六席必须完全一致，不一致视为看的不是同一份题）",
    "status": "你这一席的收尾状态",
    "perspective_summary": "一句话说清你这一席看到的核心",
    "observations": "观察条目（这一席的证据清单）",
    "observations[].observation_id": "条目编号（本席内唯一）",
    "observations[].kind": "条目类型",
    "observations[].statement": "结论本身，一句话",
    "observations[].evidence_status": "证据状态",
    "observations[].source_refs": "证据出处（写成 VERIFIED 就必须至少给一条）",
    "proposed_mechanisms": "你提的机制（可以为空数组 —— 但空掉就等于这一席没给可实现的东西）",
    "proposed_mechanisms[].mechanism_id": "机制编号",
    "proposed_mechanisms[].description": "机制在做什么",
    "proposed_mechanisms[].inputs": "输入是什么",
    "proposed_mechanisms[].transformation": "怎么变换",
    "proposed_mechanisms[].expected_signal": "预期能看到什么信号",
    "proposed_mechanisms[].failure_mode": "它会怎么失败",
    "experiments": "你提的实验（可以为空数组 —— 但空掉就等于这一席没给可证伪的东西）",
    "experiments[].experiment_id": "实验编号",
    "experiments[].comparison": "跟什么比",
    "experiments[].held_constant": "必须固定住的变量",
    "experiments[].observable": "看什么量",
    "experiments[].falsifier": "什么结果算这条被推翻",
    "blockers": "卡住你的东西（没有就空数组）",
    # --- bundle (compiler seat) ---
    "work_order": "冻结工单",
    "work_order.request_id": "请求编号",
    "work_order.north_star": "北极星（这轮不许偏离的方向）",
    "work_order.input_sha256": "工单哈希",
    "contribution_receipts": "六席贡献的哈希回执（由代码算，不许手填）",
    "contribution_receipts[].role": "角色",
    "contribution_receipts[].sha256": "该席贡献的哈希",
    "compiled_chain": "编译出的三段链",
    "compiled_chain.hypothesis": "假设",
    "compiled_chain.hypothesis.statement": "假设本身",
    "compiled_chain.hypothesis.alternative": "最强的替代解释",
    "compiled_chain.hypothesis.observable_prediction": "可观测的预测",
    "compiled_chain.mechanism": "可实现的机制",
    "compiled_chain.mechanism.inputs": "输入（至少两项）",
    "compiled_chain.mechanism.representation": "表示形式",
    "compiled_chain.mechanism.transformation": "变换",
    "compiled_chain.mechanism.output": "输出",
    "compiled_chain.mechanism.distinguishing_signal": "区分性信号（这才是机制成立的证据）",
    "compiled_chain.mechanism.failure_modes": "失败模式",
    "compiled_chain.falsifiable_experiment": "可证伪的实验",
    "compiled_chain.falsifiable_experiment.intervention": "干预是什么",
    "compiled_chain.falsifiable_experiment.comparator": "对照是什么",
    "compiled_chain.falsifiable_experiment.held_constant": "固定住什么",
    "compiled_chain.falsifiable_experiment.analysis_unit": "独立分析单位",
    "compiled_chain.falsifiable_experiment.primary_outcome": "主结局",
    "compiled_chain.falsifiable_experiment.leakage_checks": "泄漏检查",
    "compiled_chain.falsifiable_experiment.falsifier": "证伪条件",
    "compiled_chain.falsifiable_experiment.stop_condition": "停止条件",
    "conflicts": "角色之间的冲突（保留，不许抹平）",
    "conflicts[].conflict_id": "冲突编号",
    "conflicts[].roles": "涉及哪几席（至少两席）",
    "conflicts[].summary": "冲突是什么",
    "conflicts[].resolution_status": "解决状态",
    "conflicts[].resolution": "怎么解决的（未解决可留空）",
    "truth_boundary": "真相边界",
    "truth_boundary.execution_status": "执行状态（固定 DESIGN_ONLY）",
    "truth_boundary.result_claims_allowed": "允许声称结果（固定 false）",
    "truth_boundary.novelty_claim_allowed": "允许声称新颖性（固定 false）",
    "truth_boundary.compiler_agent_id": "编译这份的 agent id",
}

_KIND_WORDS = {
    "support": "支持",
    "risk": "风险",
    "assumption": "假设",
    "confound": "混杂",
    "requirement": "硬需求",
    "VERIFIED": "已核实",
    "UNVERIFIED": "未核实",
    "CONTRADICTED": "被反证",
    "COMPLETE": "做完了",
    "BLOCKED": "被卡住",
    "RESOLVED": "已解决",
    "OPEN": "仍未解决",
}


# --------------------------------------------------------------------------- schema derivation

def _schema(name: str) -> dict[str, Any]:
    return json.loads((SCHEMA_DIR / name).read_text(encoding="utf-8"))


def schema_for_role(role: str, *, contract: Optional[Mapping[str, Any]] = None) -> str:
    """The compiler seat produces the BUNDLE; the other six produce a CONTRIBUTION.

    A template that ignored this distinction would hand the compiler the wrong shape entirely, which
    is the single most likely way to get this wrong.
    """
    cfg = dict(contract) if contract is not None else load_contract()
    known = [str(row["role"]) for row in cfg["roles"]]
    if role not in known:
        raise MechanismCouncilError(f"unknown council role {role!r}; known roles: {known}")
    return BUNDLE_SCHEMA if role == COMPILER_ROLE else CONTRIBUTION_SCHEMA


def _constraint_words(node: Mapping[str, Any]) -> str:
    """Human words for whatever the schema actually constrains — never a guess."""
    parts: list[str] = []
    if "const" in node:
        parts.append(f"固定值 `{node['const']}`")
    if node.get("enum"):
        options = "/".join(f"`{v}`" for v in node["enum"])
        parts.append(f"只能选：{options}")
    node_type = node.get("type")
    if node_type == "array":
        minimum = node.get("minItems")
        parts.append(f"数组，至少 {minimum} 项" if minimum else "数组，可以为空")
        if node.get("uniqueItems"):
            parts.append("不许重复")
    elif node_type == "string" and node.get("pattern", "").startswith("^sha256:"):
        parts.append("`sha256:` + 64 位十六进制")
    return "；".join(parts)


def _describe(node: Mapping[str, Any], prefix: str = "") -> list[dict[str, Any]]:
    """Flatten one object schema into ordered rows. Required-only: the template teaches the floor."""
    rows: list[dict[str, Any]] = []
    required = list(node.get("required") or [])
    properties = node.get("properties") or {}
    for name in required:
        child = properties.get(name)
        if not isinstance(child, Mapping):
            continue
        path = f"{prefix}{name}"
        row = {
            "path": path,
            "label": FIELD_WORDS.get(path, ""),
            "type": str(child.get("type") or ("const" if "const" in child else "")),
            "constraint": _constraint_words(child),
            "fixed": "const" in child,
            "children": [],
        }
        if child.get("type") == "object":
            row["children"] = _describe(child, prefix=f"{path}.")
        elif child.get("type") == "array" and isinstance(child.get("items"), Mapping):
            items = child["items"]
            if items.get("type") == "object":
                row["children"] = _describe(items, prefix=f"{path}[].")
        rows.append(row)
    return rows


def role_template(role: str, *, contract: Optional[Mapping[str, Any]] = None) -> dict[str, Any]:
    """Everything a contributor needs, derived: purpose + dependencies + required shape + ceiling."""
    cfg = dict(contract) if contract is not None else load_contract()
    schema_name = schema_for_role(role, contract=cfg)  # refuses an unknown role before anything else
    row = next(r for r in cfg["roles"] if str(r["role"]) == role)
    return {
        "role": role,
        "produces": "mechanism_council_bundle" if role == COMPILER_ROLE
        else "mechanism_council_contribution",
        "purpose": str(row["purpose"]),
        "depends_on": [str(d) for d in row.get("depends_on") or []],
        "agent_spec": str(row["agent_spec"]),
        "schema": schema_name,
        "fields": _describe(_schema(schema_name)),
        "truth_boundary": dict(cfg["truth_boundary"]),
        "required_final_chain": list(cfg["truth_boundary"]["required_final_chain"]),
    }


# --------------------------------------------------------------------------- blank + checking

def _blank_value(node: Mapping[str, Any], path: str, known: Mapping[str, Any]) -> Any:
    if path in known:
        return known[path]
    if "const" in node:
        return node["const"]
    node_type = node.get("type")
    if node_type == "object":
        return {
            name: _blank_value(child, f"{path}.{name}" if path else name, known)
            for name, child in (node.get("properties") or {}).items()
            if name in (node.get("required") or [])
        }
    if node_type == "array":
        items = node.get("items")
        count = int(node.get("minItems") or 0)
        if not isinstance(items, Mapping) or count == 0:
            return []
        return [_blank_value(items, f"{path}[]", known) for _ in range(count)]
    if node.get("enum"):
        options = "/".join(str(v) for v in node["enum"])
        return f"{PLACEHOLDER}从 {options} 里选一个>"
    label = FIELD_WORDS.get(path, path)
    return f"{PLACEHOLDER}{label}>"


def blank_contribution(role: str, *, input_sha256: str,
                       contract: Optional[Mapping[str, Any]] = None) -> dict[str, Any]:
    """A schema-shaped skeleton whose every human decision is still an unfilled placeholder.

    Deliberately **not** submittable: :func:`check_contribution` fails on a surviving placeholder, so
    a worker cannot hand the blank back as a contribution.
    """
    cfg = dict(contract) if contract is not None else load_contract()
    if role == COMPILER_ROLE:
        raise MechanismCouncilError(
            "the compiler seat does not write a contribution — it compiles the six into a bundle; "
            "use compile_bundle() and render the result"
        )
    schema = _schema(schema_for_role(role, contract=cfg))
    known = {"role": role, "input_sha256": str(input_sha256)}
    return _blank_value(schema, "", known)


def _unfilled(value: Any, path: str = "") -> list[str]:
    if isinstance(value, str):
        return [path or "(root)"] if PLACEHOLDER in value else []
    if isinstance(value, Mapping):
        out: list[str] = []
        for key, item in value.items():
            out.extend(_unfilled(item, f"{path}.{key}" if path else str(key)))
        return out
    if isinstance(value, list):
        out = []
        for index, item in enumerate(value):
            out.extend(_unfilled(item, f"{path}[{index}]"))
        return out
    return []


def check_contribution(row: Mapping[str, Any]) -> dict[str, Any]:
    """Plain-Chinese field-level verdict on one filled contribution.

    Errors block. Warnings do not: they name places the schema is *looser* than the contract's intent
    (``proposed_mechanisms`` / ``experiments`` carry no ``minItems``, so a COMPLETE contribution can
    legally contain neither a mechanism nor a falsifier). Tightening the schema would retro-invalidate
    already-recorded contributions, so this discloses instead of silently changing a live contract.
    """
    errors: list[str] = []
    warnings: list[str] = []
    for path in _unfilled(row):
        label = FIELD_WORDS.get(path.split("[")[0], path)
        errors.append(f"`{path}` 还是模板占位符，没填：{label}")
    for raw in validate_against(CONTRIBUTION_SCHEMA, dict(row)):
        errors.append(f"不合契约：{raw}")
    if not row.get("proposed_mechanisms"):
        warnings.append("这一席没提任何机制（schema 允许空，但这一席等于没给可实现的东西）")
    if not row.get("experiments"):
        warnings.append("这一席没提任何实验（schema 允许空，但这一席等于没给可证伪的东西）")
    if str(row.get("status")) == "BLOCKED" and not row.get("blockers"):
        warnings.append("状态写了被卡住，但 blockers 是空的 —— 说不出卡在哪就不算被卡住")
    return {"ok": not errors, "errors": errors, "warnings": warnings}


# --------------------------------------------------------------------------- renderings

def _field_lines(rows: Iterable[Mapping[str, Any]], depth: int = 0) -> list[str]:
    out: list[str] = []
    for row in rows:
        indent = "  " * depth
        bits = [f"{indent}- `{row['path'].split('.')[-1].rstrip('[]') or row['path']}`"]
        if row["label"]:
            bits.append(f" — {row['label']}")
        if row["constraint"]:
            bits.append(f"（{row['constraint']}）")
        out.append("".join(bits))
        out.extend(_field_lines(row["children"], depth + 1))
    return out


def render_role_template(role: str, *, input_sha256: Optional[str] = None,
                         contract: Optional[Mapping[str, Any]] = None) -> str:
    """The authoring sheet one council seat gets handed. Plain Chinese, derived from the contract."""
    template = role_template(role, contract=contract)
    chain = " → ".join(template["required_final_chain"])
    lines = [f"# 席位交稿模板 —— `{role}`", "",
             f"> 你要产出的东西叫 `{template['produces']}`，按 `schemas/{template['schema']}` 校验。",
             f"> 这一席的职责：{template['purpose']}", ""]
    if template["depends_on"]:
        deps = "、".join(f"`{d}`" for d in template["depends_on"])
        lines += [f"- **你要先读**：{deps} 的产出（契约里写死的依赖，不是建议）", ""]
    else:
        lines += ["- **你不依赖任何其他席位** —— 独立看，别去对齐别人的结论（独立性就是这一席的价值）", ""]
    lines += ["## 必填的字段（下面每一条都是 schema 真的要求的，不是我编的）", ""]
    lines += _field_lines(template["fields"])
    lines += ["", "## 这一席**不能**做的事", "",
              "- 不能声称结果：这条链最终只到设计，`execution_status` 固定 `DESIGN_ONLY`。",
              "- 不能声称新颖性 —— 查重不是这一席的活。",
              f"- 外部事实拿不到出处就标 `{template['truth_boundary']['unverified_external_fact_status']}`，"
              "不许写成已核实。",
              f"- 整个议会最后必须闭合成：{chain}。你这一席交不出对应的东西，就写进 `blockers`，"
              "不要用一句漂亮话糊过去。", ""]
    if input_sha256:
        lines += ["## 空白骨架（把 `<TODO：…>` 全填掉；留一个都不算交稿）", "", "```json",
                  json.dumps(blank_contribution(role, input_sha256=input_sha256,
                                                contract=contract),
                             ensure_ascii=False, indent=2),
                  "```", ""]
    else:
        lines += ["> 要空白骨架就带上冻结工单的哈希："
                  f"`python -m research_agent_teams.tools.mechanism_council template {role} "
                  "--input-sha256 sha256:…`", ""]
    return "\n".join(lines).rstrip() + "\n"


def _say(value: Any) -> str:
    return _KIND_WORDS.get(str(value), str(value))


def render_council_report(bundle: Mapping[str, Any],
                          *, contributions: Optional[Iterable[Mapping[str, Any]]] = None) -> str:
    """The DIRECTOR's card: who said what, what is still unresolved, and where this stops.

    The blind rendering (``render_anonymous_candidate``) must stay identity-free because it feeds a
    review; this one is the opposite by design — attribution is the point. The truth boundary is READ
    from the bundle, never asserted here.
    """
    errors = validate_against(BUNDLE_SCHEMA, dict(bundle))
    if errors:
        raise MechanismCouncilError("; ".join(errors))
    order = bundle["work_order"]
    chain = bundle["compiled_chain"]
    boundary = bundle["truth_boundary"]
    conflicts = list(bundle["conflicts"])
    open_conflicts = [c for c in conflicts if c["resolution_status"] == "OPEN"]
    by_role = {str(r.get("role")): r for r in (contributions or [])}

    lines = ["# 议会给你的东西（设计稿，不是结果）", "",
             f"> 请求 `{order['request_id']}` · 编译人 `{boundary['compiler_agent_id']}`",
             f"> 北极星：{order['north_star']}", ""]

    lines += ["## 一句话结论", "", chain["hypothesis"]["statement"], "",
              f"**最强的反面说法**：{chain['hypothesis']['alternative']}", "",
              f"**能看到什么才算成立**：{chain['hypothesis']['observable_prediction']}", ""]

    if open_conflicts:
        lines += [f"## ⚠️ 还有 {len(open_conflicts)} 条冲突没解决 —— 先看这个", ""]
        for conflict in open_conflicts:
            who = "、".join(f"`{r}`" for r in conflict["roles"])
            lines += [f"- **{conflict['conflict_id']}**（{who}）：{conflict['summary']}"]
        lines += ["", "> 冲突是被**保留**下来的，不是没发现。要不要在这上面下注是你的决定。", ""]

    mechanism = chain["mechanism"]
    lines += ["## 怎么实现（机制）", "",
              f"- **输入**：" + "；".join(mechanism["inputs"]),
              f"- **表示**：{mechanism['representation']}",
              f"- **变换**：{mechanism['transformation']}",
              f"- **输出**：{mechanism['output']}",
              f"- **区分性信号**：{mechanism['distinguishing_signal']}",
              "- **会怎么坏**：" + "；".join(mechanism["failure_modes"]), ""]

    experiment = chain["falsifiable_experiment"]
    lines += ["## 怎么证伪（实验）", "",
              "| 项 | 内容 |", "|---|---|",
              f"| 干预 | {experiment['intervention']} |",
              f"| 对照 | {experiment['comparator']} |",
              f"| 固定住 | {'；'.join(experiment['held_constant'])} |",
              f"| 独立分析单位 | {experiment['analysis_unit']} |",
              f"| 主结局 | {experiment['primary_outcome']} |",
              f"| 泄漏检查 | {'；'.join(experiment['leakage_checks'])} |",
              f"| **什么结果算它被推翻** | {experiment['falsifier']} |",
              f"| 什么时候停 | {experiment['stop_condition']} |", ""]

    lines += ["## 谁出的力（六席 + 编译）", "",
              "| 席位 | 这一席看了什么 | 哈希回执 |", "|---|---|---|"]
    for receipt in bundle["contribution_receipts"]:
        role = str(receipt["role"])
        row = by_role.get(role)
        summary = str(row.get("perspective_summary")) if row else "（本次没提供贡献正文，只有回执）"
        lines.append(f"| `{role}` | {summary} | `{receipt['sha256'][:19]}…` |")
    lines += ["", "> 六席各写各的，被哈希绑到同一份冻结工单上 —— 谁看的不是同一份题，编译会当场拒。", ""]

    resolved = [c for c in conflicts if c["resolution_status"] == "RESOLVED"]
    if resolved:
        lines += ["## 已经解决的冲突", ""]
        for conflict in resolved:
            lines += [f"- **{conflict['conflict_id']}** {_say(conflict['resolution_status'])}："
                      f"{conflict['summary']}"]
            if conflict.get("resolution"):
                lines.append(f"  - 解法：{conflict['resolution']}")
        lines.append("")
    if not conflicts:
        lines += ["## 冲突", "", "这轮没记录到任何典型冲突。", ""]

    lines += ["## 到这就停了（别读多）", "",
              f"- 执行状态：`{boundary['execution_status']}` —— **没有跑过任何东西**，没有数字。",
              f"- 允许声称结果：`{str(boundary['result_claims_allowed']).lower()}`；"
              f"允许声称新颖性：`{str(boundary['novelty_claim_allowed']).lower()}`。",
              "- 想让它进库只有一条路：`/promote-to-vault` 人工关卡。议会自己写不进库。", ""]
    return "\n".join(lines).rstrip() + "\n"


__all__ = [
    "PLACEHOLDER",
    "FIELD_WORDS",
    "blank_contribution",
    "check_contribution",
    "render_council_report",
    "render_role_template",
    "role_template",
    "schema_for_role",
]
