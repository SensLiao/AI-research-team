"""The indexer must not lose things: not a vault kind, not a decision, not a status word.

Every test here is anchored to a defect class that really happened in this repo:

* a hardcoded kind list hid 47 vault pages (`reporting/scan.py`);
* `pending_director_decisions` lives in its own array, so reading only `tasks` reported
  "nothing is waiting on you" while two decisions sat unmade;
* `UNBLOCKED_PENDING_RERUN` contains "PENDING" but means ready — a regex that outranks the
  curated table turns a ready task into a blocked one;
* the vault serializes the same value as `status: active` and `status: "active"`.
"""
from __future__ import annotations

import json

from research_agent_teams.workbench.indexer import (
    _task_work_state,
    index_runs,
    index_tasks,
    index_vault,
    ledger_boundaries,
    parse_frontmatter,
    vault_kinds,
)
from research_agent_teams.workbench.model import EvidenceState, WorkState


# --------------------------------------------------------------------------- frontmatter

def test_the_same_value_serialized_two_ways_parses_identically():
    quoted = parse_frontmatter('---\nstatus: "active"\ntype: "result"\n---\nbody\n')
    bare = parse_frontmatter("---\nstatus: active\ntype: result\n---\nbody\n")
    assert quoted == bare == {"status": "active", "type": "result"}


def test_list_items_and_missing_frontmatter_are_both_handled():
    front = parse_frontmatter("---\ntitle: T\nrq:\n- RQ1\n- RQ2\n---\n")
    assert front["title"] == "T" and front["rq"] == ["RQ1", "RQ2"]
    assert parse_frontmatter("no frontmatter here") == {}


# ------------------------------------------------------------------- vault kinds from disk

def _vault(tmp_path, kind: str, name: str, front: str, body: str = "内容") -> None:
    folder = tmp_path / "02-wiki" / kind
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{name}.md").write_text(f"---\n{front}\n---\n\n# {name}\n\n{body}\n", encoding="utf-8")


def test_a_brand_new_vault_kind_is_indexed_without_touching_any_code(tmp_path):
    """A hardcoded kind list is how 47 pages went missing. Kinds come from disk."""
    _vault(tmp_path, "results", "r1", "type: result\nstatus: active")
    _vault(tmp_path, "a-kind-nobody-anticipated", "x1", "type: whatever\nstatus: active")
    assert "a-kind-nobody-anticipated" in vault_kinds(tmp_path)
    ids = {row.artifact_id for row in index_vault(str(tmp_path))}
    assert "vault:a-kind-nobody-anticipated/x1" in ids


def test_a_vault_without_a_wiki_directory_yields_nothing_rather_than_raising(tmp_path):
    assert index_vault(str(tmp_path)) == []
    assert vault_kinds(tmp_path) == []


# ------------------------------------------------- the vault's own two axes, read not recomputed

def test_frozen_comes_from_the_vaults_own_result_status(tmp_path):
    _vault(tmp_path, "results", "frozen-one",
           "type: result\nstatus: active\nresult-status: frozen\ncan-cite-thesis: true")
    row = index_vault(str(tmp_path))[0]
    assert row.evidence_state == EvidenceState.FROZEN.value
    assert "result-status=frozen" in row.evidence_reason
    assert row.lifecycle == "active", "the lifecycle word is carried through verbatim"


def test_provisional_is_a_real_measurement_that_still_cannot_be_cited(tmp_path):
    _vault(tmp_path, "results", "prov",
           "type: result\nstatus: active\nresult-status: provisional\ncan-cite-thesis: false")
    row = index_vault(str(tmp_path))[0]
    assert row.evidence_state == EvidenceState.OBSERVED.value
    assert "不能当论文事实引用" in row.evidence_reason


def test_a_deprecated_page_is_superseded_no_matter_what_else_it_claims(tmp_path):
    _vault(tmp_path, "results", "old",
           "type: result\nstatus: deprecated\nresult-status: frozen\ncan-cite-thesis: true")
    assert index_vault(str(tmp_path))[0].evidence_state == EvidenceState.SUPERSEDED.value


def test_a_result_page_missing_the_evidence_field_is_treated_as_weakest(tmp_path):
    _vault(tmp_path, "results", "bare", "type: result\nstatus: active")
    row = index_vault(str(tmp_path))[0]
    assert row.evidence_state == EvidenceState.PROPOSED.value
    assert "没有 result-status" in row.evidence_reason


def test_a_concept_page_is_not_dressed_up_as_evidence(tmp_path):
    _vault(tmp_path, "concepts", "c1", "type: concept\nstatus: active")
    row = index_vault(str(tmp_path))[0]
    assert row.evidence_state == EvidenceState.PROPOSED.value
    assert "不承载证据等级" in row.evidence_reason


# ------------------------------------------------------------------------------ work states

def test_the_curated_status_table_outranks_the_pending_regex():
    """`UNBLOCKED_PENDING_RERUN` contains PENDING but means the opposite."""
    assert _task_work_state("UNBLOCKED_PENDING_RERUN", ())[0] is WorkState.READY
    state, blockers = _task_work_state("BUILT_PENDING_N04", ())
    assert state is WorkState.BLOCKED and blockers == ("等 N04",)


def test_a_word_naming_a_human_needs_a_decision_not_a_dependency():
    for word in ("DRAFT_PENDING_DIRECTOR", "MUST_FREEZE_BEFORE_THE_NUMBER_IS_SEEN"):
        assert _task_work_state(word, ())[0] is WorkState.NEEDS_DECISION


def test_an_unknown_word_is_never_optimistically_read_as_progress():
    assert _task_work_state("PROBABLY_FINE", ())[0] is WorkState.BACKLOG


def test_a_real_blocker_blocks_but_does_not_un_finish_a_done_task():
    assert _task_work_state("NOT_STARTED", ("audit B6",))[0] is WorkState.BLOCKED
    assert _task_work_state("DONE", ("stale",))[0] is WorkState.DONE


# ---------------------------------------------------------------------------------- tasks

def _ledger(tmp_path, payload: dict) -> None:
    records = tmp_path / "records"
    records.mkdir(parents=True, exist_ok=True)
    (records / "n-task-ledger.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )


def test_a_task_is_graded_by_the_ledgers_own_receipt_plus_number_rule(tmp_path):
    _ledger(tmp_path, {"tasks": [
        {"id": "A", "name": "有回执有数", "status": "DONE",
         "evidence": "server-evidence/x.json", "facts": {"cases": 597}},
        {"id": "B", "name": "有回执没有可核对的数", "status": "DONE",
         "evidence": "server-evidence/y.json", "facts": {}},
        {"id": "C", "name": "什么都没有", "status": "DONE"},
    ]})
    rows = {r.task_id.split(":")[-1]: r for r in index_tasks("p", tmp_path)}
    assert rows["A"].evidence_state == EvidenceState.OBSERVED.value
    assert "不代表科学结论成立" in rows["A"].evidence_reason
    assert rows["B"].evidence_state == EvidenceState.PROPOSED.value
    assert rows["C"].evidence_state == EvidenceState.PROPOSED.value
    assert all(r.work_state == WorkState.DONE.value for r in rows.values()), (
        "work progress and evidence strength are independent axes"
    )


def test_the_projects_own_status_word_is_never_flattened_away(tmp_path):
    _ledger(tmp_path, {"tasks": [
        {"id": "A", "name": "n", "status": "BUILT_PENDING_N04"}]})
    row = index_tasks("p", tmp_path)[0]
    assert row.source_status == "BUILT_PENDING_N04"
    assert row.work_state == WorkState.BLOCKED.value


def test_decisions_owed_to_the_director_are_read_from_their_own_array(tmp_path):
    """Reading only `tasks` reported "nothing waiting on you" while two decisions sat unmade."""
    _ledger(tmp_path, {
        "tasks": [{"id": "A", "name": "done thing", "status": "DONE"}],
        "pending_director_decisions": [
            {"id": "D-1", "title": "预注册读数表", "status": "MUST_FREEZE_BEFORE_THE_NUMBER_IS_SEEN",
             "record": "director-review/x.md",
             "why_now": "先看到数再写读数表就是事后合理化"},
        ],
    })
    rows = index_tasks("p", tmp_path)
    waiting = [r for r in rows if r.work_state == WorkState.NEEDS_DECISION.value]
    assert len(waiting) == 1
    assert waiting[0].task_id == "p:decision:D-1"
    assert "事后合理化" in waiting[0].why_now
    assert waiting[0].next_action == "director-review/x.md"
    assert waiting[0].evidence_state == EvidenceState.PROPOSED.value, "a decision is not evidence"


def test_boundaries_the_last_run_held_are_surfaced_as_truth_boundary(tmp_path):
    _ledger(tmp_path, {"tasks": [], "hard_boundaries_held_this_run": [
        "no GPU job submitted", "the 91-case locked test never touched"]})
    held = ledger_boundaries(tmp_path)
    assert len(held) == 2
    assert all(line.startswith("（上次运行守住的）") for line in held), "provenance stays visible"


def test_a_workspace_without_a_ledger_yields_no_tasks_and_no_boundaries(tmp_path):
    assert index_tasks("p", tmp_path) == []
    assert ledger_boundaries(tmp_path) == ()


def test_a_corrupt_ledger_degrades_instead_of_failing_the_whole_index(tmp_path):
    records = tmp_path / "records"
    records.mkdir(parents=True)
    (records / "n-task-ledger.json").write_text("{not json", encoding="utf-8")
    assert index_tasks("p", tmp_path) == []
    assert ledger_boundaries(tmp_path) == ()


# ------------------------------------------------------------------------------------ runs

def test_a_finished_run_without_a_receipt_is_a_dry_run_not_a_result(tmp_path):
    run = tmp_path / "proj" / "deep_ideation-20260711T080452Z"
    (run / "director-review").mkdir(parents=True)
    (run / "manifest.yaml").write_text(
        "run_id: deep_ideation-20260711T080452Z\nproject: proj\nstatus: done\n"
        "mode: deep_ideation\nupdated_at: '2026-07-11T08:21:10Z'\n", encoding="utf-8")
    (run / "director-review" / "00-REVIEW-PACKET.md").write_text("# 评审包\n", encoding="utf-8")
    rows = index_runs(str(tmp_path))
    assert len(rows) == 1
    assert rows[0].evidence_state == EvidenceState.DRY_RUN.value
    assert rows[0].run_id == "deep_ideation-20260711T080452Z"
    assert rows[0].kind == "deep_ideation"


def test_a_run_with_a_receipt_bound_to_a_result_reaches_observed(tmp_path):
    run = tmp_path / "proj" / "run-2"
    (run / "evidence").mkdir(parents=True)
    (run / "manifest.yaml").write_text("run_id: run-2\nproject: proj\nstatus: done\n",
                                       encoding="utf-8")
    (run / "evidence" / "executor-receipt.json").write_text("{}", encoding="utf-8")
    (run / "evidence" / "raw-result.json").write_text("{}", encoding="utf-8")
    assert index_runs(str(tmp_path))[0].evidence_state == EvidenceState.OBSERVED.value


def test_a_missing_runs_directory_yields_nothing(tmp_path):
    assert index_runs(str(tmp_path / "absent")) == []
