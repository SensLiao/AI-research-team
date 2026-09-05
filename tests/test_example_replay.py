"""v4 P6 — replaying the recorded example, and proving the replay can actually fail.

A verifier nobody has watched fail is not a verifier. Every property here is paired with a tamper:
the example is copied to a temp tree, one thing is changed, and the replay must go FAIL for that
specific reason.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    not (Path(__file__).resolve().parents[2] / "research_agent_teams" / "projects" / "t4-scribble-m0-mechanism-eval").is_dir(),
    reason="t4-scribble-m0-mechanism-eval project was reset from the machine workspace "
           "(director 2026-08-04); restore the project before re-enabling these tests",
)

from research_agent_teams.tools import example_replay as replay_mod
from research_agent_teams.tools.example_replay import (
    ExampleReplayError,
    REPLAY_STATUS,
    main,
    render_replay,
    replay,
)

NATIVE = "native-eval"


@pytest.fixture()
def example(tmp_path):
    """A private copy of the recorded example, so a tamper cannot touch the real one."""
    target = tmp_path / replay_mod.DEFAULT_PROJECT.name
    shutil.copytree(replay_mod.DEFAULT_PROJECT, target)
    return target


def _load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def _save(path, value):
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)


def _failed(report, fragment):
    return [name for name in report["failed_checks"] if fragment in name]


# ------------------------------------------------------------------ the recorded example replays

def test_the_recorded_example_still_replays_end_to_end():
    report = replay()
    assert report["status"] == REPLAY_STATUS
    assert report["verdict"] == "PASS", report["failed_checks"]
    assert report["checks_failed"] == 0
    assert report["checks_run"] >= 15, "a replay this thin would not be worth running"
    # The hash-binding stage (dispatch completeness, council recompile, triple-blind
    # timeline, repair independence, truth boundary — 5 stages, not 6). The
    # dependency-hash edge inside dispatch is gone too; dispatch is now checked by
    # completion/failure existence and ordering, not by a recomputed digest.
    assert [stage["stage"] for stage in report["stages"]][0].startswith("②")
    assert len(report["stages"]) == 5


def test_the_replay_never_claims_the_example_was_executed():
    report = replay()
    assert report["status"] == "REPLAY_OF_RECORDED_RUN"
    rendered = render_replay(report)
    assert "不是重新跑一次" in rendered
    assert "没有连服务器，没有用 GPU" in rendered
    assert "EXECUTED" not in json.dumps(report, ensure_ascii=False)


def test_the_load_bearing_facts_are_re_derived_not_quoted():
    report = replay()
    detail = " ".join(c["detail"] for stage in report["stages"] for c in stage["checks"])
    assert "重新编译结果与记录完全一致" in detail
    assert "DESCRIPTIVE_REVIEW_PASS" in detail
    assert "FAIL → PASS" in detail, "the kept failure must be reported in real time order"


def test_missing_example_is_an_error_not_a_silent_pass(tmp_path):
    with pytest.raises(ExampleReplayError, match="no recorded example"):
        replay(tmp_path / "not-a-project")


# ------------------------------------------------------------------ tampers must be caught
#
# The path→hash binding stage was deleted whole (R3 §B①): the replay no longer recomputes a
# digest for every declared path→sha256 pair, so a tamper that only a hash recompute could catch
# is no longer a replay property. Removed with it: test_editing_a_referenced_artifact_breaks_the_replay
# (hash-bound markdown edit), test_editing_a_contribution_breaks_the_recompile (byte-identical bundle
# recompile — replaced by a semantic-identical compare that a free-text summary edit doesn't trip),
# test_healing_the_recorded_mismatch_breaks_the_replay (the deliberately-stale-hash mechanism),
# test_breaking_a_dependency_hash_is_caught (the dependency output_sha256 edge inside dispatch), and
# test_cli_exits_nonzero_on_a_tampered_example (its tamper vector was a hash-bound markdown file).
# What is kept below still goes FAIL for a real reason: abandoned-order existence, blind-review
# timeline/ordering, repair independence, and the design-only truth boundary are not hash checks.

def test_a_completion_for_an_abandoned_order_breaks_the_replay(example):
    """The recorded abandonment means NO output was produced; inventing one must be caught."""
    source = example / NATIVE / "completions" / "WO-CAUSAL-R2.json"
    shutil.copyfile(source, example / NATIVE / "completions" / "WO-CAUSAL.json")
    report = replay(example)
    assert report["verdict"] == "FAIL"
    assert _failed(report, "什么都没产出")


def test_revealing_the_mapping_before_review_is_caught(example):
    path = example / NATIVE / "sealed" / "mapping-reveal.json"
    row = _load(path)
    row["revealed_after_review_at"] = "2026-08-01T00:00:00.0000000Z"
    _save(path, row)
    report = replay(example)
    assert report["verdict"] == "FAIL"
    assert _failed(report, "评审全部交稿之后")


def test_flipping_a_judge_vote_breaks_the_reconciliation(example):
    path = example / NATIVE / "reviews" / "reconciliation.json"
    row = _load(path)
    row["winner_votes"] = {"X": 0, "Y": 3, "TIE": 0}
    _save(path, row)
    report = replay(example)
    assert report["verdict"] == "FAIL"


def test_dropping_the_design_only_boundary_is_caught(example):
    path = example / NATIVE / "preflight" / "contract-dry-run.json"
    row = _load(path)
    row["scientific_claims_allowed"] = True
    _save(path, row)
    report = replay(example)
    assert report["verdict"] == "FAIL"
    assert _failed(report, "不是科学证据")


# ------------------------------------------------------------------ the CLI the director types

def test_cli_reports_pass_on_the_real_example(capsys):
    assert main([]) == 0
    out = capsys.readouterr().out
    assert "全部重新推导通过" in out
    assert "REPLAY_OF_RECORDED_RUN" in out


def test_cli_json_view_is_machine_readable(capsys):
    assert main(["--json"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["verdict"] == "PASS"
    assert report["status"] == REPLAY_STATUS
