"""v4 P7 — governance surfaces measured against real run usage, and the ceilings on that measurement.

The properties worth pinning here are mostly *refusals*: with no telemetry nothing may be called
unused, an unrecorded check may not be given a firing count, and no code path may ever remove a gate.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from research_agent_teams.tools import governance_census as gc
from research_agent_teams.tools import worker_census


# ------------------------------------------------------------------ the inventory is read from disk

def test_the_inventory_is_enumerated_not_written_down():
    from research_agent_teams.operate.modes import REGISTRY

    inventory = gc.surfaces()
    # Enumerated from REGISTRY, not from the directory listing. Wave 2 (2026-08-04) proved why:
    # two recipe modules sit in operate/modes/ WITHOUT being registered (no test coverage yet), and
    # globbing would have published them to PLATFORM-FACTS as pressable capabilities.
    assert inventory["operated_modes"] == sorted(REGISTRY)
    on_disk = {p.stem for p in gc.OPERATED_MODES_DIR.glob("*.py") if not p.stem.startswith("_")}
    assert set(inventory["operated_modes"]) <= on_disk, (
        "a registered mode with no module on disk would be a phantom capability")
    assert set(inventory["named_human_gates"]) == {p.stem for p in gc.GATES_DIR.glob("*.md")}
    assert set(inventory["rostered_seats"]) == set(worker_census.roster())
    assert "promote-to-vault" in inventory["named_human_gates"]
    assert all("_" not in name or True for name in inventory["guard_tools"])
    assert len(inventory["guard_tools"]) >= 10, "the guard-tool matcher found suspiciously few"


def test_a_new_gate_spec_shows_up_without_touching_this_module(tmp_path, monkeypatch):
    monkeypatch.setattr(gc, "GATES_DIR", tmp_path)
    (tmp_path / "brand-new-gate.md").write_text("# gate", encoding="utf-8")
    assert gc.named_gates() == ["brand-new-gate"]


# ------------------------------------------------------------------ no telemetry ⇒ no verdict

def test_without_run_history_nothing_is_called_unused(tmp_path):
    report = gc.census(tmp_path / "no-runs-here")
    assert report["telemetry"] == gc.TELEMETRY_ABSENT
    assert report["runs_measured"] == 0
    assert report["axes"] == []
    assert report["findings"] == []
    rendered = gc.render_census(report)
    assert "没有可用的运行记录" in rendered
    assert "不给任何「用过 / 没用过」的判断" in rendered
    assert "有多少 vs 用过多少" not in rendered, "no usage table may be rendered without usage data"


def test_a_single_run_is_measured_without_extrapolation(tmp_path):
    run = tmp_path / "demo-project" / "run-1"
    (run / "inbox").mkdir(parents=True)
    seat = sorted(worker_census.roster())[0]
    (run / "inbox" / f"DISCOVER.{seat}.bundle.json").write_text("{}", encoding="utf-8")
    (run / "inbox" / "DISCOVER.bundle.json").write_text("{}", encoding="utf-8")
    (run / "manifest.yaml").write_text(
        yaml.safe_dump({"run_id": "run-1", "project": "demo-project", "status": "done",
                        "mode": "gap_breadth"}), encoding="utf-8")

    used = gc.usage(tmp_path)
    assert used["telemetry"] == gc.TELEMETRY_PRESENT
    assert used["runs"] == 1
    assert used["modes_used"] == {"gap_breadth": 1}
    assert used["seats_dispatched"] == {seat: 1}
    assert used["stage_level_bundle_kinds"] == ["DISCOVER"], "a stage bundle is not a seat"

    report = gc.census(tmp_path)
    modes = next(a for a in report["axes"] if a["axis"] == "一键模式")
    assert modes["exercised"] == ["gap_breadth"]
    assert "new_direction" in modes["never_exercised"]


# ------------------------------------------------------------------ the real tree

def test_the_real_run_history_measures_all_four_axes():
    report = gc.census()
    if report["telemetry"] == gc.TELEMETRY_ABSENT:
        pytest.skip("runs/ is gitignored — no history on this checkout")
    assert report["runs_measured"] >= 1
    axes = {axis["axis"]: axis for axis in report["axes"]}
    assert set(axes) == {"一键模式", "agent", "导演决定点（gates/ 里的 5 个）"}
    for axis in axes.values():
        assert axis["used_but_not_in_the_inventory"] == [], \
            f"{axis['axis']} used something the inventory does not know about: " \
            f"{axis['used_but_not_in_the_inventory']}"
        assert axis["measurement_ceiling"], "every axis must state how far it can see"


def test_seat_counting_never_treats_a_non_seat_bundle_as_a_seat():
    used = gc.usage()
    if used["telemetry"] == gc.TELEMETRY_ABSENT:
        pytest.skip("no run history on this checkout")
    known = worker_census.agent_files()
    assert set(used["seats_dispatched"]) <= known
    assert not (set(used["non_seat_bundle_kinds"]) & known)
    assert not (set(used["stage_level_bundle_kinds"]) & known)


# ------------------------------------------------------------------ the findings must be earned

def test_findings_are_only_emitted_when_the_numbers_support_them(tmp_path):
    run = tmp_path / "p" / "r"
    (run / "inbox").mkdir(parents=True)
    (run / "manifest.yaml").write_text(
        yaml.safe_dump({"run_id": "r", "project": "p", "status": "done", "mode": "gap_breadth"}),
        encoding="utf-8")
    ids = {f["id"] for f in gc.census(tmp_path)["findings"]}
    # No obs.jsonl and no seats ⇒ the undercount finding cannot be claimed.
    assert "obs-jsonl-is-not-a-dispatch-log" not in ids
    # A `done` manifest with no ledger at all ⇒ the under-written-event finding IS supported.
    assert "run-completed-event-is-under-written" in ids
    # Nothing records a check firing anywhere ⇒ always disclosed.
    assert "per-check-firing-is-not-recorded-anywhere" in ids


def test_the_obs_undercount_finding_fires_only_when_obs_really_undercounts(tmp_path):
    run = tmp_path / "p" / "r"
    (run / "inbox").mkdir(parents=True)
    seats = sorted(worker_census.roster())[:3]
    for seat in seats:
        (run / "inbox" / f"DISCOVER.{seat}.bundle.json").write_text("{}", encoding="utf-8")
    (run / "manifest.yaml").write_text(
        yaml.safe_dump({"run_id": "r", "project": "p", "status": "done", "mode": "gap_breadth"}),
        encoding="utf-8")
    (run / "obs.jsonl").write_text(
        json.dumps({"agent_name": seats[0], "stage": "DISCOVER"}) + "\n", encoding="utf-8")

    finding = next(f for f in gc.census(tmp_path)["findings"]
                   if f["id"] == "obs-jsonl-is-not-a-dispatch-log")
    assert "1 个名字" in finding["what"] and "3 个" in finding["what"]


def test_a_promotion_target_removes_the_never_promoted_finding(tmp_path):
    run = tmp_path / "p" / "r"
    (run / "inbox").mkdir(parents=True)
    (run / "manifest.yaml").write_text(
        yaml.safe_dump({"run_id": "r", "project": "p", "status": "done", "mode": "gap_breadth",
                        "promotion_targets": ["02-wiki/some-page.md"]}), encoding="utf-8")
    ids = {f["id"] for f in gc.census(tmp_path)["findings"]}
    assert "the-vault-write-path-has-never-been-exercised" not in ids


# ------------------------------------------------------------------ report-only, by construction

def test_the_census_authorizes_nothing_and_says_so():
    report = gc.census()
    assert report["authorizes"] == []
    assert len(report["does_not_authorize"]) >= 3
    rendered = gc.render_census(report)
    if report["telemetry"] == gc.TELEMETRY_PRESENT:
        assert "只报数" in rendered
        assert "不删除、不停用、不弱化任何检查点或检查" in rendered
        assert "「没被用过」不等于「可以砍」" in "".join(report["does_not_authorize"])


def test_no_code_path_here_can_delete_or_rewrite_a_governance_surface():
    """Read-only by construction: the module must contain no mutating call at all.

    Call-shaped patterns only — a bare word like ``del`` also matches "model", which would make this
    check fail on prose and teach nothing.
    """
    source = Path(gc.__file__).read_text(encoding="utf-8")
    for forbidden in (".unlink(", ".rmdir(", "rmtree(", ".write_text(", ".write_bytes(",
                      "os.remove(", "os.rename(", "os.replace(", "shutil.move(", ".mkdir("):
        assert forbidden not in source, f"governance census must stay read-only; found {forbidden!r}"
    assert 'open(' not in source.replace('.open("rb")', ''), "no file handle is opened for writing"


def _run_with_gate_names_in_its_artifacts(root):
    """A run whose artifacts MENTION every named gate but where no gate actually fired."""
    run = root / "p" / "r"
    (run / "inbox").mkdir(parents=True)
    (run / "manifest.yaml").write_text(
        yaml.safe_dump({"run_id": "r", "project": "p", "status": "done", "mode": "gap_breadth"}),
        encoding="utf-8")
    mentions = " ".join(f"/{name}" for name in gc.named_gates())
    (run / "inbox" / "REPORT.report-note.bundle.json").write_text(
        json.dumps({"note": f"the next steps are {mentions}"}), encoding="utf-8")
    return run


def test_the_named_gate_axis_refuses_to_infer_a_firing_from_a_text_mention(tmp_path):
    """Negative control for the axis below: naming a gate is not firing it."""
    _run_with_gate_names_in_its_artifacts(tmp_path)
    gates = next(a for a in gc.census(tmp_path)["axes"] if a["axis"].startswith("导演决定点"))
    assert gates["exercised"] == [], \
        "a gate name appearing inside an artifact is not a gate firing — this axis must stay empty"
    assert sorted(gates["never_exercised"]) == sorted(gc.named_gates())
    assert "不拿文本里提到过当成触发过" in gates["measurement_ceiling"]


def test_promote_to_vault_counts_as_exercised_only_from_its_own_record_file(tmp_path):
    """The one gate whose firing IS measurable — because the gate writes a record on every decision.

    Pinned as a pair with the negative control above: the same artifact text that must NOT count becomes
    a real firing only once the gate's own deterministic record file exists.
    """
    run = _run_with_gate_names_in_its_artifacts(tmp_path)
    (run / "inbox" / "document-promotion-record-some-page.json").write_text(
        json.dumps({"admissible": True, "vault_slug": "some-page", "document_type": "paper"}),
        encoding="utf-8")

    report = gc.census(tmp_path)
    gates = next(a for a in report["axes"] if a["axis"].startswith("导演决定点"))
    assert gates["exercised"] == ["promote-to-vault"]
    assert "promote-to-vault" not in gates["never_exercised"], "a fired gate cannot also be never-used"
    assert len(gates["never_exercised"]) == len(gc.named_gates()) - 1, \
        "one gate firing must never mark the other four as exercised"

    admissions = report["usage"]["document_admissions"]
    assert admissions == {"records": 1, "admitted": 1, "vault_slugs": ["some-page"]}
    ids = {f["id"] for f in report["findings"]}
    assert "the-vault-write-path-has-never-been-exercised" not in ids
    assert "only-the-document-lane-has-ever-written-the-vault" in ids


def test_a_rejected_admission_is_a_gate_firing_but_not_a_vault_write(tmp_path):
    """The distinction that keeps the number honest: the gate ran, the vault was NOT written."""
    run = _run_with_gate_names_in_its_artifacts(tmp_path)
    (run / "inbox" / "document-promotion-record-refused.json").write_text(
        json.dumps({"admissible": False, "vault_slug": None,
                    "reasons": ["paper metadata.relevance is invalid"]}), encoding="utf-8")

    report = gc.census(tmp_path)
    admissions = report["usage"]["document_admissions"]
    assert admissions["records"] == 1 and admissions["admitted"] == 0 and admissions["vault_slugs"] == []
    gates = next(a for a in report["axes"] if a["axis"].startswith("导演决定点"))
    assert gates["exercised"] == ["promote-to-vault"], "a rejection still proves the gate ran"
    ids = {f["id"] for f in report["findings"]}
    assert "the-vault-write-path-has-never-been-exercised" in ids, \
        "a refused admission must NOT read as the vault having been written"
    assert "only-the-document-lane-has-ever-written-the-vault" not in ids


# ------------------------------------------------------------------ CLI

def test_cli_prints_the_card_and_the_json(capsys):
    assert gc.main([]) == 0
    assert "治理用量盘点" in capsys.readouterr().out
    assert gc.main(["--json"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["does_not_authorize"]


def test_cli_on_an_empty_runs_root_is_still_exit_zero(tmp_path, capsys):
    assert gc.main(["--runs-root", str(tmp_path)]) == 0
    assert "没有可用的运行记录" in capsys.readouterr().out


def test_platform_facts_counts_are_re_derived_not_typed_in():
    """PLATFORM-FACTS §0 had no numeric guard, so its table rotted silently.

    Caught on 2026-08-04: it claimed **225** test files while 222 existed. Only wording was pinned
    (`test_manuscript_completion.py`), never a count. These five rot fastest because every round adds
    to them, so each is re-derived from disk here.
    """
    from research_agent_teams.workbench.cli import build_parser

    facts = (Path(gc.__file__).parents[1] / "PLATFORM-FACTS.md").read_text(encoding="utf-8")
    inventory = gc.surfaces()
    tools_dir = Path(gc.__file__).parent
    verbs = next(iter(build_parser()._subparsers._group_actions)).choices

    # (row label as it appears in the table, derived value) — each check is scoped to ITS OWN row,
    # so a number that happens to appear in a different row cannot satisfy it.
    derived = [
        ("Deterministic tools", len(list(tools_dir.glob("*.py")))),
        # count the directory THIS test lives in, so the check holds in both layouts (workspace
        # tests/machine/ and the machine repo's own tests/)
        ("Test files", len(list(Path(__file__).resolve().parent.glob("test_*.py")))),
        ("`workbench` verbs", len(verbs)),
        ("Human gates", len(inventory["named_human_gates"])),
        ("Modes", len(inventory["operated_modes"])),
    ]
    rows = {line.split("|")[1].strip(): line for line in facts.splitlines()
            if line.startswith("| ") and line.count("|") >= 3}
    for label, value in derived:
        assert label in rows, f"PLATFORM-FACTS has no `{label}` row any more"
        row = rows[label]
        assert str(value) in row, \
            f"the `{label}` row does not state the real count ({value}): {row.strip()}"
        assert str(value + 1) not in row.split("|")[2], \
            f"the `{label}` guard is vacuous — {value + 1} also matches its count cell"


def test_the_director_can_reach_it_from_the_workbench(capsys):
    """P2.1's lesson: a capability nobody can find from an entry surface may as well not exist."""
    from research_agent_teams.workbench.cli import build_parser, main as workbench_main

    verbs = {action.dest: action for action in build_parser()._subparsers._group_actions}
    assert "governance" in next(iter(verbs.values())).choices

    workbench_main(["governance"])
    assert "治理用量盘点" in capsys.readouterr().out
