"""Tests for the director reporting layer (plan card before, progress report after).

Scope discipline (director lock 2026-08-01): these check ARCHITECTURE and
HONESTY, not prose. They assert that the layer reads real files, that it never
claims a blocked machine can run jobs, that it never invents a knowledge-base
number, and that internal identifiers reach the director translated. They
deliberately do NOT assert word counts, heading order, or exact wording — the
report is allowed to read differently as long as it stays true.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from research_agent_teams.reporting import briefing, plain_words, progress, scan


# --------------------------------------------------------------------------- plain language

def test_known_terms_are_translated_and_unknown_terms_survive():
    assert plain_words.say("DISCOVER") != "DISCOVER"
    assert plain_words.say("new_direction") != "new_direction"
    assert plain_words.say("submit_job") != "submit_job"
    # An unknown term degrades honestly instead of vanishing.
    assert plain_words.say("some_future_token") == "some_future_token"


def test_every_one_button_mode_has_a_plain_name():
    """A mode the director can actually run must never surface as a bare code name."""
    from research_agent_teams.operate.modes import REGISTRY

    untranslated = plain_words.untranslated(REGISTRY)
    assert untranslated == [], f"these modes still read as code names: {untranslated}"


def test_gate_label_names_the_decision_not_just_the_command():
    label = plain_words.gate_label("/idea-bet")
    assert "/idea-bet" in label and label != "/idea-bet"


# --------------------------------------------------------------------------- scan honesty

def _write_pool(tmp_path: Path, *, execution_ready: bool) -> Path:
    root = tmp_path / "resources"
    root.mkdir()
    (root / "resource_registry.yaml").write_text(yaml.safe_dump({
        "schema_version": 1,
        "resources": [{
            "resource_id": "server.test.gpu",
            "type": "hardware.ssh_server",
            "display_name": "Test GPU box",
            "scope": "shared",
            "capabilities": ["query_status", "pull_logs", "submit_job"],
            "execution_ready": execution_ready,
            "execution_blockers": [] if execution_ready else ["hdd4_at_100_percent_reported_capacity"],
            "status": "available" if execution_ready else "read_only_verified",
        }],
    }, sort_keys=False), encoding="utf-8")
    return root


def test_a_blocked_machine_never_advertises_that_it_can_run_jobs(tmp_path):
    root = _write_pool(tmp_path, execution_ready=False)
    result = scan.scan_resources(resources_root_path=str(root))
    assert result["compute_ready"] == []
    (watched,) = result["compute_watch_only"]
    assert "submit_job" not in watched["capabilities"], "a blocked box claimed job submission"
    assert "submit_job" in watched["declared_capabilities"], "the declared fact must stay auditable"
    assert watched["blockers"], "a blocked box must say why"


def test_an_execution_ready_machine_is_reported_as_runnable(tmp_path):
    root = _write_pool(tmp_path, execution_ready=True)
    result = scan.scan_resources(resources_root_path=str(root))
    assert [r["resource_id"] for r in result["compute_ready"]] == ["server.test.gpu"]
    assert result["compute_watch_only"] == []


def test_a_missing_knowledge_base_degrades_instead_of_raising(tmp_path):
    result = scan.scan_vault(str(tmp_path / "no-such-vault"))
    assert result["available"] is False
    assert "total_pages" not in result, "an absent knowledge base must not report a count"


def test_vault_counts_come_from_real_files(tmp_path):
    wiki = tmp_path / "02-wiki" / "sources"
    wiki.mkdir(parents=True)
    (wiki / "a.md").write_text("x", encoding="utf-8")
    (wiki / "b.md").write_text("y", encoding="utf-8")
    result = scan.scan_vault(str(tmp_path))
    assert result["total_pages"] == 2
    assert result["by_kind"] == [{"kind": "sources", "label": "论文与外部来源", "count": 2}]


def test_no_vault_kind_can_hide_from_the_count(tmp_path):
    """A hardcoded kind list once hid `comparisons`/`meetings`/`models`/`papers` — 47 pages,
    about a tenth of the real vault, invisible to every briefing.  Kinds come from disk now."""
    wiki = tmp_path / "02-wiki"
    for kind in ("sources", "papers", "models", "comparisons", "meetings", "brand-new-kind"):
        (wiki / kind).mkdir(parents=True)
        (wiki / kind / "a.md").write_text("x", encoding="utf-8")
    result = scan.scan_vault(str(tmp_path))
    counted = {row["kind"] for row in result["by_kind"]}
    assert counted == {"sources", "papers", "models", "comparisons", "meetings",
                       "brand-new-kind"}
    assert result["total_pages"] == 6
    assert sum(row["count"] for row in result["by_kind"]) == result["total_pages"]
    labels = {row["kind"]: row["label"] for row in result["by_kind"]}
    assert labels["models"] == "模型", "known kinds keep their Chinese label"
    assert labels["brand-new-kind"] == "brand-new-kind", "an unlabelled kind shows, unlabelled"


def test_known_kinds_keep_their_reading_order_and_extras_come_after(tmp_path):
    wiki = tmp_path / "02-wiki"
    for kind in ("zz-extra", "results", "sources"):
        (wiki / kind).mkdir(parents=True)
        (wiki / kind / "a.md").write_text("x", encoding="utf-8")
    order = [row["kind"] for row in scan.scan_vault(str(tmp_path))["by_kind"]]
    assert order == ["sources", "results", "zz-extra"]


def test_capability_scan_mirrors_the_wired_registry():
    from research_agent_teams.operate.modes import REGISTRY

    caps = scan.scan_capabilities()
    assert set(caps["one_button"]) == set(REGISTRY), (
        "the briefing must offer exactly the modes that are really one-button")
    assert not (set(caps["one_button"]) & set(caps["design_only"]))


# --------------------------------------------------------------------------- briefing

def test_briefing_renders_without_a_world(tmp_path):
    """A plan card must still render when the vault, projects and pool are all absent."""
    data = briefing.build_briefing(
        "帮我找个研究方向", project=None,
        vault_root=str(tmp_path / "nope"), projects_root=str(tmp_path / "nope"),
        runs_dir=str(tmp_path / "nope"), resources_root_path=str(tmp_path / "nope"))
    text = briefing.render_briefing(data)
    assert "开工前计划" in text
    assert "没有可以直接提交任务的机器" in text, "no compute must be stated, not omitted"


def test_briefing_names_the_human_gates_it_will_stop_at():
    data = briefing.build_briefing("帮我找个研究方向", project="iac-cbct-seg")
    text = briefing.render_briefing(data)
    recommended = [r for r in data["routes"]["routes"] if r["recommended"]]
    assert recommended, "a matched request must carry a recommended route"
    for gate in recommended[0]["gates"]:
        assert gate in text, f"the plan card hid the human gate {gate}"


def test_briefing_starts_no_run(tmp_path):
    runs = tmp_path / "runs"
    runs.mkdir()
    data = briefing.build_briefing("设计这个实验", project="iac-cbct-seg", runs_dir=str(runs))
    assert data["routes"]["auto_mode"] == "full_rigor_minimal"
    assert list(runs.iterdir()) == [], "the plan card must never create a run"


# --------------------------------------------------------------------------- progress

def _fake_run(tmp_path: Path, *, status: str, with_product: bool) -> Path:
    root = tmp_path / "run-1"
    (root / "evidence" / "REPORT").mkdir(parents=True)
    (root / "manifest.yaml").write_text(yaml.safe_dump({
        "run_id": "run-1", "mode": "evidence_review", "project": "demo",
        "status": status,
        "completed_work": [{"stage": "DISCOVER"}],
    }, sort_keys=False), encoding="utf-8")
    (root / "task_frame.artifact.json").write_text(json.dumps({
        "payload": {"mode": "evidence_review", "project": "demo",
                    "request_text": "评一下证据",
                    "stage_path": ["DISCOVER", "REPORT"]},
    }), encoding="utf-8")
    (root / "evidence" / "REPORT" / "report-note.artifact.json").write_text(json.dumps({
        "payload": {"summary": "两篇来源支持结论。", "cannot_claim": ["还不能说方法更好"]},
    }, ensure_ascii=False), encoding="utf-8")
    if with_product:
        product = root / "director-review" / "evidence"
        product.mkdir(parents=True)
        (product / "evidence-review-brief.md").write_text("## 核心结论\n\n略。\n", encoding="utf-8")
    return root


def test_progress_shows_stage_completion_from_the_manifest(tmp_path):
    data = progress.build_progress(_fake_run(tmp_path, status="running", with_product=True))
    assert data["completed_stages"] == ["DISCOVER"]
    assert data["planned_stages"] == ["DISCOVER", "REPORT"]
    text = progress.render_progress(data)
    assert plain_words.say("DISCOVER") in text
    assert "DISCOVER" not in text.replace(plain_words.say("DISCOVER"), ""), (
        "a stage code name leaked into the director's report")


def test_progress_carries_the_cannot_claim_boundary(tmp_path):
    data = progress.build_progress(_fake_run(tmp_path, status="done", with_product=True))
    text = progress.render_progress(data)
    assert "还不能说方法更好" in text, "an honesty boundary must survive into the report"


def test_progress_says_when_the_product_is_missing(tmp_path):
    data = progress.build_progress(_fake_run(tmp_path, status="done", with_product=False))
    text = progress.render_progress(data)
    assert data["quality"]["status"] == "fail"
    assert "不能当交付物" in text


def test_progress_flags_a_run_waiting_on_the_director(tmp_path):
    data = progress.build_progress(_fake_run(tmp_path, status="awaiting", with_product=True))
    text = progress.render_progress(data)
    assert "必须你点头" in text


def test_progress_never_writes_to_the_run(tmp_path):
    root = _fake_run(tmp_path, status="done", with_product=True)
    before = {p: p.stat().st_mtime_ns for p in sorted(root.rglob("*")) if p.is_file()}
    progress.report(root)
    after = {p: p.stat().st_mtime_ns for p in sorted(root.rglob("*")) if p.is_file()}
    assert before == after, "the progress report mutated the run it was reading"


@pytest.mark.parametrize("status", ["failed", "crashed_mid_stage", "rejected"])
def test_an_unfinished_run_is_never_reported_as_finished(tmp_path, status):
    data = progress.build_progress(_fake_run(tmp_path, status=status, with_product=True))
    text = progress.render_progress(data)
    assert "已完成" not in text, f"status {status!r} was rendered as complete"


# --------------------------------------------------------------------------- entry-point truth
# 2026-08-01: the director's entry documents had drifted to "SEVEN"/"EIGHT" wired modes while the code
# carried twelve, so five real capabilities were invisible to the person the machine exists for. These
# two checks are ARCHITECTURE checks — they assert the entry docs name the real modes, not that they
# use particular wording or length.

_ENTRY_DOCS = (
    ".agents/skills/research-orchestrator/SKILL.md",
    ".claude/skills/research-orchestrator/SKILL.md",
    ".claude/CLAUDE.md",
    ".claude/commands/run-mode.md",
)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _entry_docs() -> list[Path]:
    root = _repo_root()
    return [root / rel for rel in _ENTRY_DOCS if (root / rel).is_file()]


def test_entry_documents_name_every_one_button_mode():
    """A capability the director cannot see might as well not exist."""
    from research_agent_teams.operate.modes import REGISTRY

    docs = _entry_docs()
    if not docs:
        pytest.skip("entry documents are not part of this checkout")
    for doc in docs:
        text = doc.read_text(encoding="utf-8")
        missing = sorted(m for m in REGISTRY if m not in text)
        assert not missing, f"{doc.name} hides these one-button modes from the director: {missing}"


def test_entry_documents_do_not_quote_a_stale_mode_count():
    """The count must match the registry — a hard-coded number is how the last drift happened."""
    from research_agent_teams.operate.modes import REGISTRY

    docs = _entry_docs()
    if not docs:
        pytest.skip("entry documents are not part of this checkout")
    real = len(REGISTRY)
    wrong = {"SEVEN": 7, "EIGHT": 8, "NINE": 9, "TEN": 10, "ELEVEN": 11, "TWELVE": 12,
             "THIRTEEN": 13, "FOURTEEN": 14}
    for doc in docs:
        text = doc.read_text(encoding="utf-8")
        for word, value in wrong.items():
            if value != real:
                assert word not in text, (
                    f"{doc.name} claims {word} wired modes; the registry has {real}")


def test_every_one_button_mode_is_reachable_from_some_intent():
    """A mode with no route is a capability the director cannot ask for in their own words.

    Until 2026-08-01 four modes (paper reading, experiment design, manuscript
    authoring and review) had no intent at all, so those requests silently fell
    through to the direction-finding arc.
    """
    from research_agent_teams.operate.modes import REGISTRY
    from research_agent_teams.tools import research_plan

    catalog = research_plan.load_catalog()
    routed: set[str] = set()
    for spec in (catalog.get("intents") or {}).values():
        for tier in (spec or {}).get("tiers") or []:
            routed.update(str(m) for m in (tier.get("modes") or []))
    unreachable = sorted(set(REGISTRY) - routed)
    assert unreachable == [], f"no intent routes to these one-button modes: {unreachable}"


def test_each_intent_matches_its_own_phrasing():
    """An intent whose own aliases do not match it would never fire in practice."""
    from research_agent_teams.tools import research_plan

    catalog = research_plan.load_catalog()
    for intent_id, spec in (catalog.get("intents") or {}).items():
        aliases = list((spec or {}).get("aliases") or [])
        assert aliases, f"intent {intent_id!r} has no trigger phrases"
        hits, matched = research_plan.best_intents(aliases[0])
        assert matched and hits[0] == intent_id, (
            f"intent {intent_id!r} does not win on its own first alias {aliases[0]!r} "
            f"(got {hits[:2]}) — the director's natural wording would be misrouted")


def test_entry_skill_requires_the_reporting_bracket():
    """Plan before, report after — the director lock must be visible at the entry, not just in code."""
    skills = [
        _repo_root() / ".agents" / "skills" / "research-orchestrator" / "SKILL.md",
        _repo_root() / ".claude" / "skills" / "research-orchestrator" / "SKILL.md",
    ]
    skills = [skill for skill in skills if skill.is_file()]
    if not skills:
        pytest.skip("entry skill is not part of this checkout")
    for skill in skills:
        text = skill.read_text(encoding="utf-8")
        assert "operate brief" in text, f"{skill} lost the pre-task plan card"
        assert "operate report" in text, f"{skill} lost the post-task progress report"
