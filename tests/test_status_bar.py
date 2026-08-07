"""The director's status bar — 「现在该我按哪个按钮」.

Every test here is paired with a negative control, because the whole value of this bar is that it does
NOT invent a next action. A bar that always names a button is worse than no bar at all.
"""
from __future__ import annotations

import json

import yaml

from research_agent_teams.reporting import status_bar as sb
from research_agent_teams.reporting import plain_words
from research_agent_teams.tools import outcome_recipes


def _run(root, *, project="p", run_id="r", mode="gap_breadth", status="done",
         pending=None, finals=(), admitted=None, promotion_targets=None):
    run = root / project / run_id
    (run / "inbox").mkdir(parents=True)
    manifest = {"run_id": run_id, "project": project, "mode": mode, "status": status}
    if pending:
        manifest["pending_gates"] = list(pending)
    if promotion_targets:
        manifest["promotion_targets"] = list(promotion_targets)
    (run / "manifest.yaml").write_text(yaml.safe_dump(manifest), encoding="utf-8")
    for name in finals:
        target = run / "director-review" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("# final\n", encoding="utf-8")
    if admitted is not None:
        (run / "inbox" / "document-promotion-record-x.json").write_text(
            json.dumps({"admissible": admitted, "vault_slug": "x" if admitted else None}),
            encoding="utf-8")
    return run


# ------------------------------------------------------------------ derivation, not declaration

def test_gate_prerequisites_come_from_the_recipes_including_every_depth_variant():
    prereqs = sb.gate_prerequisites()
    assert set(prereqs) == set(plain_words.known_gates()), "every named gate must get a row"
    # `new_direction` unlocks /idea-bet on the DEFAULT depth, `deep_ideation` only on the DEEPEST one.
    # Reading the resolved default alone would silently tell the director the deep route has no gate.
    assert "new_direction" in prereqs["/idea-bet"]
    assert "deep_ideation" in prereqs["/idea-bet"], "variant depths must be scanned, not just the default"
    assert prereqs["/venue-pick"] == ["venue_readiness"]


def test_no_prerequisite_is_a_mode_that_does_not_exist():
    """Negative control on the derivation: an invented mode name can never appear."""
    known = set(outcome_recipes.wired_modes()) if hasattr(outcome_recipes, "wired_modes") else None
    prereqs = sb.gate_prerequisites()
    flat = {mode for modes in prereqs.values() for mode in modes}
    assert flat, "the derivation produced nothing at all"
    if known:
        assert flat <= known, f"prerequisite names must be real wired modes; stray: {flat - known}"
    assert "not-a-real-mode" not in flat


def test_the_promote_gate_is_declared_as_having_no_mode_prerequisite():
    """It is post-run: it stands on a reviewed artifact existing, not on a mode finishing. Stated
    explicitly so it can never read as 'derivation found nothing, shrug'."""
    assert sb.GATE_WITHOUT_A_MODE == "/promote-to-vault"
    assert sb.gate_prerequisites()[sb.GATE_WITHOUT_A_MODE] == []


# ------------------------------------------------------------------ the bar never invents a button

def test_nothing_waiting_means_the_bar_says_so(tmp_path):
    _run(tmp_path)
    state = sb.build_state("p", runs_root=tmp_path)
    assert state["waiting"] == []
    assert all(row["state"] == sb.NOT_YET for row in state["gates"].values())
    bar = sb.render_bar(state)
    assert "现在没有要你按的按钮" in bar
    assert "现在该你按" not in bar


def test_a_run_awaiting_the_director_names_the_exact_button_and_the_run(tmp_path):
    _run(tmp_path, run_id="ideas-1", mode="deep_ideation", status="awaiting_director",
         pending=["IDEATE"])
    state = sb.build_state("p", runs_root=tmp_path)
    assert state["gates"]["/idea-bet"]["state"] == sb.NOW
    assert state["gates"]["/idea-bet"]["runs"] == ["ideas-1"]
    bar = sb.render_bar(state)
    assert "/idea-bet" in bar and "ideas-1" in bar
    # A different gate must NOT be dragged along by the one that fired.
    assert state["gates"]["/venue-pick"]["state"] == sb.NOT_YET


def test_two_runs_waiting_on_one_gate_surface_the_newest_and_disclose_the_rest(tmp_path):
    """Regression (2026-08-04): with two paused runs the bar named whichever sorted first by
    PATH — so right after finishing a run the director was pointed at an older one and the run
    they had just watched was invisible. Recency is the only defensible tiebreak, and a bar that
    silently drops the second waiting run is worse than one that admits there is a queue."""
    # Deliberately opposed orders: `a-old` sorts FIRST by path but is the OLDER run, so a bar that
    # still leans on path order fails this test and a bar that leans on recency passes it.
    older = _run(tmp_path, run_id="a-old", mode="deep_ideation",
                 status="awaiting_director", pending=["IDEATE"])
    newer = _run(tmp_path, run_id="z-new", mode="new_direction",
                 status="awaiting_director", pending=["IDEATE"])
    _touch_updated(older, "2026-08-04T05:00:00Z")
    _touch_updated(newer, "2026-08-04T07:00:00Z")

    state = sb.build_state("p", runs_root=tmp_path)
    assert [row["run_id"] for row in state["waiting"]] == ["z-new", "a-old"]
    assert state["gates"]["/idea-bet"]["runs"] == ["z-new", "a-old"]
    bar = sb.render_bar(state)
    assert "z-new" in bar, "the bar must point at the run the director just finished"
    assert "a-old" in bar or "还有 1 " in bar, "a second waiting run must not vanish silently"


def _touch_updated(run: Path, stamp: str) -> None:
    manifest = yaml.safe_load((run / "manifest.yaml").read_text(encoding="utf-8"))
    manifest["updated_at"] = stamp
    (run / "manifest.yaml").write_text(yaml.safe_dump(manifest), encoding="utf-8")


def test_a_final_document_makes_promote_optional_and_an_admission_clears_it(tmp_path):
    _run(tmp_path, run_id="paper-1", finals=["papers/note.md"])
    state = sb.build_state("p", runs_root=tmp_path)
    assert state["gates"]["/promote-to-vault"]["state"] == sb.OPTIONAL
    assert state["promotable_runs"] == ["paper-1"]

    _run(tmp_path, project="q", run_id="paper-2", finals=["papers/note.md"], admitted=True)
    done = sb.build_state("q", runs_root=tmp_path)
    assert done["promotable_runs"] == [], "an admitted document must stop counting as promotable"
    assert done["gates"]["/promote-to-vault"]["state"] == sb.NOT_YET


def test_a_rejected_admission_leaves_the_document_still_promotable(tmp_path):
    """The inverse of the test above: the gate ran and REFUSED, so the work is still outstanding."""
    _run(tmp_path, run_id="paper-3", finals=["papers/note.md"], admitted=False)
    state = sb.build_state("p", runs_root=tmp_path)
    assert state["promotable_runs"] == ["paper-3"]
    assert state["gates"]["/promote-to-vault"]["state"] == sb.OPTIONAL


def test_the_review_packet_alone_is_not_a_promotable_document(tmp_path):
    """The packet is the run's cover sheet, not a knowledge page — counting it would put a permanent
    'you have things to promote' nag on every run that ever finished."""
    _run(tmp_path, run_id="packet-only", finals=["00-REVIEW-PACKET.md"])
    assert sb.build_state("p", runs_root=tmp_path)["promotable_runs"] == []


# ------------------------------------------------------------------ it must stay a BAR

def test_the_compact_bar_stays_short_enough_to_read(tmp_path):
    _run(tmp_path, run_id="ideas-1", mode="deep_ideation", status="awaiting_director",
         pending=["IDEATE"], finals=["papers/note.md"])
    lines = sb.render_bar(sb.build_state("p", runs_root=tmp_path)).splitlines()
    assert len(lines) <= 6, f"the bar grew to {len(lines)} lines — it is a bar, not a report"
    assert lines[0].startswith("━━ 项目状态")
    assert "workbench gates" in lines[-1], "the bar must always say where the full table is"


def test_the_bar_works_with_no_projection_index_at_all(tmp_path):
    """It is the verb a lost director runs first, so it must not require a reindex to have happened."""
    _run(tmp_path)
    assert "项目状态" in sb.render_bar(sb.build_state("p", runs_root=tmp_path))
    assert not (tmp_path / ".workbench").exists()


def test_an_empty_runs_root_still_renders_instead_of_crashing(tmp_path):
    state = sb.build_state("nobody", runs_root=tmp_path / "nothing-here")
    assert state["runs"] == 0
    assert "现在没有要你按的按钮" in sb.render_bar(state)


def test_the_gate_table_lists_every_gate_exactly_once(tmp_path):
    _run(tmp_path)
    table = sb.render_gates(sb.build_state("p", runs_root=tmp_path))
    for gate in plain_words.known_gates():
        assert table.count(f"`{gate}`") == 1, f"{gate} must appear exactly once in the table"
    assert "只有你能按" in table, "the table must restate that the machine never presses a gate"


def test_the_state_is_read_only_by_construction():
    source = (sb.__file__ and open(sb.__file__, encoding="utf-8").read()) or ""
    for forbidden in (".write_text(", ".write_bytes(", ".unlink(", "rmtree(", ".mkdir(",
                      "os.remove(", "os.replace("):
        assert forbidden not in source, f"the status bar must never write; found {forbidden!r}"
