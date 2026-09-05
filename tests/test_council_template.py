"""v4 P5 — the council's authoring template and the two opposite renderings.

Every check here is negative-controlled: the derivation tests fail if the template is ever typed in
by hand instead of read out of the schema, and the rendering tests fail if the director card and the
blind card stop being opposites.
"""
from __future__ import annotations

import copy
import json

import pytest

from research_agent_teams.tools import council_template as tpl
from research_agent_teams.tools.mechanism_council import (
    MechanismCouncilError,
    compile_bundle,
    load_contract,
    main as council_main,
    render_anonymous_candidate,
)

from .test_mechanism_council import INPUT_SHA, _all_contributions, _chain, _contribution

CONTRIBUTOR_ROLES = (
    "mathematical_formalizer",
    "domain_reality_auditor",
    "cognitive_intent_modeler",
    "curriculum_design_specialist",
    "research_engineering_planner",
    "causal_mechanism_critic",
)


def _required_paths(rows, out=None):
    out = [] if out is None else out
    for row in rows:
        out.append(row["path"])
        _required_paths(row["children"], out)
    return out


def _fill(value):
    """Naive fill: replace each placeholder with the FIRST legal option / some prose."""
    if isinstance(value, str):
        if not value.startswith(tpl.PLACEHOLDER):
            return value
        inner = value[len(tpl.PLACEHOLDER):].rstrip(">")
        if inner.startswith("从 ") and " 里选一个" in inner:
            return inner[len("从 "):].split(" 里选一个")[0].split("/")[0]
        return "已经填好的内容"
    if isinstance(value, dict):
        return {key: _fill(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_fill(item) for item in value]
    return value


def _bundle(*, compiler_agent_id="agent/compiler", conflicts=None):
    return compile_bundle(
        work_order={"request_id": "SM0-01", "north_star": "State-relative intent.",
                    "input_sha256": INPUT_SHA},
        contributions=_all_contributions(),
        compiled_chain=_chain(),
        conflicts=conflicts if conflicts is not None else [],
        compiler_agent_id=compiler_agent_id,
    )


# ------------------------------------------------------------------ derivation, not hand-typing

def test_every_required_schema_path_has_a_plain_chinese_label():
    """The label table is the only hand-written part, so its coverage of the schema is asserted.

    Non-vacuous by construction: the path list is derived from the two real schemas and must be
    substantial, and a fabricated path must be absent — otherwise this check could pass while
    silently labelling nothing.
    """
    paths: list[str] = []
    for role in CONTRIBUTOR_ROLES[:1] + ("hypothesis_compiler",):
        paths.extend(_required_paths(tpl.role_template(role)["fields"]))
    assert len(set(paths)) >= 40, "derivation returned too few paths to be meaningful"
    missing = sorted(p for p in set(paths) if p not in tpl.FIELD_WORDS)
    assert missing == [], f"schema fields with no Chinese label: {missing}"
    assert "compiled_chain.hypothesis.fabricated" not in tpl.FIELD_WORDS


def test_template_fields_are_read_from_the_schema_not_typed_in(monkeypatch):
    before = _required_paths(tpl.role_template("causal_mechanism_critic")["fields"])
    assert "reviewer_mood" not in before

    real = tpl._schema

    def patched(name):
        schema = copy.deepcopy(real(name))
        if name == tpl.CONTRIBUTION_SCHEMA:
            schema["required"].append("reviewer_mood")
            schema["properties"]["reviewer_mood"] = {"type": "string"}
        return schema

    monkeypatch.setattr(tpl, "_schema", patched)
    after = _required_paths(tpl.role_template("causal_mechanism_critic")["fields"])
    assert "reviewer_mood" in after, "the template ignored a new schema field — it is hand-typed"


def test_template_purpose_and_dependencies_come_from_the_contract():
    contract = copy.deepcopy(load_contract())
    row = next(r for r in contract["roles"] if r["role"] == "causal_mechanism_critic")
    row["purpose"] = "A deliberately altered purpose sentence."
    row["depends_on"] = ["mathematical_formalizer"]

    template = tpl.role_template("causal_mechanism_critic", contract=contract)
    assert template["purpose"] == "A deliberately altered purpose sentence."
    assert template["depends_on"] == ["mathematical_formalizer"]
    rendered = tpl.render_role_template("causal_mechanism_critic", contract=contract)
    assert "A deliberately altered purpose sentence." in rendered
    assert "`mathematical_formalizer`" in rendered


def test_unknown_role_is_refused():
    with pytest.raises(MechanismCouncilError, match="unknown council role"):
        tpl.role_template("marketing_lead")


# ------------------------------------------------------------------ the compiler seat is different

def test_compiler_seat_gets_the_bundle_shape_and_writes_no_contribution():
    compiler = tpl.role_template("hypothesis_compiler")
    assert compiler["produces"] == "mechanism_council_bundle"
    assert compiler["schema"] == tpl.BUNDLE_SCHEMA
    paths = _required_paths(compiler["fields"])
    assert "compiled_chain.falsifiable_experiment.falsifier" in paths
    assert "perspective_summary" not in paths

    contributor = tpl.role_template("causal_mechanism_critic")
    assert contributor["produces"] == "mechanism_council_contribution"
    assert contributor["schema"] == tpl.CONTRIBUTION_SCHEMA

    with pytest.raises(MechanismCouncilError, match="does not write a contribution"):
        tpl.blank_contribution("hypothesis_compiler", input_sha256=INPUT_SHA)


# ------------------------------------------------------------------ a blank is not a submission

def test_blank_template_is_shaped_right_but_cannot_be_submitted():
    blank = tpl.blank_contribution("causal_mechanism_critic", input_sha256=INPUT_SHA)
    assert blank["contract_version"] == "mechanism-council-contribution/v1"
    assert blank["role"] == "causal_mechanism_critic"
    assert blank["input_sha256"] == INPUT_SHA
    assert len(blank["observations"]) == 1, "minItems must decide how many stubs appear"
    assert blank["proposed_mechanisms"] == [] and blank["experiments"] == []

    verdict = tpl.check_contribution(blank)
    assert verdict["ok"] is False
    unfilled = [line for line in verdict["errors"] if "模板占位符" in line]
    assert any("status" in line for line in unfilled)
    assert any("perspective_summary" in line for line in unfilled)
    assert any("observations[0].statement" in line for line in unfilled)


def test_enum_placeholders_name_the_legal_options():
    blank = tpl.blank_contribution("domain_reality_auditor", input_sha256=INPUT_SHA)
    assert "COMPLETE/BLOCKED" in blank["status"]
    assert "support/risk" in blank["observations"][0]["kind"]


def test_naively_filling_the_blank_still_cannot_skip_the_source_requirement():
    """The first enum option for evidence_status is VERIFIED, which the schema binds to a locator."""
    filled = _fill(tpl.blank_contribution("mathematical_formalizer", input_sha256=INPUT_SHA))
    assert filled["observations"][0]["evidence_status"] == "VERIFIED"
    verdict = tpl.check_contribution(filled)
    assert verdict["ok"] is False
    assert any("不合契约" in line for line in verdict["errors"])

    filled["observations"][0]["evidence_status"] = "UNVERIFIED"
    assert tpl.check_contribution(filled)["ok"] is True


def test_schema_looseness_is_disclosed_as_a_warning_not_silently_accepted():
    thin = _contribution("curriculum_design_specialist")
    verdict = tpl.check_contribution(thin)
    assert verdict["ok"] is True, "the schema really does allow this — do not turn it into an error"
    assert len(verdict["warnings"]) == 2
    assert any("没提任何机制" in w for w in verdict["warnings"])
    assert any("没提任何实验" in w for w in verdict["warnings"])

    blocked = _contribution("domain_reality_auditor")
    blocked["status"] = "BLOCKED"
    assert any("卡在哪" in w for w in tpl.check_contribution(blocked)["warnings"])


# ------------------------------------------------------------------ the two renderings are opposites

def test_director_card_attributes_the_seats_and_the_blind_card_never_does():
    bundle = _bundle(compiler_agent_id="secret/compiler-agent")
    rows = _all_contributions()

    director = tpl.render_council_report(bundle, contributions=rows)
    blind = render_anonymous_candidate(bundle)

    assert "secret/compiler-agent" in director
    assert "`causal_mechanism_critic`" in director
    assert "Independent causal_mechanism_critic analysis." in director

    assert "secret/compiler-agent" not in blind
    assert "causal_mechanism_critic" not in blind

    for rendered in (director, blind):
        assert "DESIGN_ONLY" in rendered


def test_director_card_states_the_ceiling_and_the_only_way_into_the_vault():
    director = tpl.render_council_report(_bundle())
    assert "没有跑过任何东西" in director
    assert "/promote-to-vault" in director
    assert "novelty" not in director.lower() or "false" in director.lower()


def test_director_card_puts_unresolved_conflicts_first():
    conflicts = [
        {"conflict_id": "C-RESOLVED", "roles": ["mathematical_formalizer", "domain_reality_auditor"],
         "summary": "Endpoint wording.", "resolution_status": "RESOLVED",
         "resolution": "Adopted the proper scoring rule."},
        {"conflict_id": "C-OPEN", "roles": ["cognitive_intent_modeler", "causal_mechanism_critic"],
         "summary": "Whether synthetic prompts identify human intent.", "resolution_status": "OPEN"},
    ]
    director = tpl.render_council_report(_bundle(conflicts=conflicts))
    assert director.index("C-OPEN") < director.index("C-RESOLVED")
    assert "还有 1 条冲突没解决" in director
    assert "冲突是被**保留**下来的" in director

    none = tpl.render_council_report(_bundle(conflicts=[]))
    assert "没记录到任何典型冲突" in none


def test_director_card_refuses_a_bundle_that_does_not_meet_the_contract():
    broken = _bundle()
    broken["truth_boundary"]["result_claims_allowed"] = True
    with pytest.raises(MechanismCouncilError):
        tpl.render_council_report(broken)


def test_a_receipt_only_bundle_says_so_instead_of_inventing_a_summary():
    director = tpl.render_council_report(_bundle())
    assert "（本次没提供贡献正文，只有回执）" in director


# ------------------------------------------------------------------ the CLI the director actually types

def test_cli_covers_template_check_compile_and_both_renderings(tmp_path, capsys):
    assert council_main(["template", "causal_mechanism_critic"]) == 0
    assert "agent 交稿模板" in capsys.readouterr().out

    blank_path = tmp_path / "blank.json"
    assert council_main(["template", "domain_reality_auditor", "--input-sha256", INPUT_SHA,
                         "--json", "--out", str(blank_path)]) == 0
    assert council_main(["check", str(blank_path)]) == 1, "a blank must not pass the CLI check"
    assert "模板占位符" in capsys.readouterr().out

    good = tmp_path / "good.json"
    good.write_text(json.dumps(_contribution("domain_reality_auditor"), ensure_ascii=False),
                    encoding="utf-8")
    assert council_main(["check", str(good)]) == 0
    assert "符合契约" in capsys.readouterr().out

    order = tmp_path / "order.json"
    order.write_text(json.dumps({"request_id": "SM0-01", "north_star": "State-relative intent.",
                                 "input_sha256": INPUT_SHA}), encoding="utf-8")
    chain = tmp_path / "chain.json"
    chain.write_text(json.dumps(_chain()), encoding="utf-8")
    contributions = []
    for row in _all_contributions():
        path = tmp_path / f"{row['role']}.json"
        path.write_text(json.dumps(row, ensure_ascii=False), encoding="utf-8")
        contributions.extend(["--contribution", str(path)])

    bundle_path = tmp_path / "bundle.json"
    assert council_main(["compile", "--work-order", str(order), "--chain", str(chain),
                         "--compiler-agent-id", "agent/compiler", "--out", str(bundle_path),
                         *contributions]) == 0
    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    assert bundle["truth_boundary"]["execution_status"] == "DESIGN_ONLY"

    assert council_main(["render", str(bundle_path), "--audience", "director", *contributions]) == 0
    director = capsys.readouterr().out
    assert "议会给你的东西" in director and "agent/compiler" in director

    assert council_main(["render", str(bundle_path), "--audience", "blind"]) == 0
    blind = capsys.readouterr().out
    assert "Anonymous design candidate" in blind and "agent/compiler" not in blind


def test_cli_json_blank_needs_the_frozen_hash():
    with pytest.raises(MechanismCouncilError, match="--input-sha256"):
        council_main(["template", "domain_reality_auditor", "--json"])


def test_writing_to_a_file_works_at_all(tmp_path):
    """Regression: `--out` raised TypeError on every call (Path.write_text(newline=) is 3.10+).

    The pre-existing `plan --out` was the only `--out` in this CLI and no test passed it, so the
    whole file-writing path was dead on this interpreter.
    """
    target = tmp_path / "plan.json"
    assert council_main(["plan", "Routine summary request.", "--out", str(target)]) == 0
    assert json.loads(target.read_text(encoding="utf-8"))["enabled"] is False
    assert "\r\n" not in target.read_bytes().decode("utf-8")
