from __future__ import annotations

import json
from pathlib import Path

import pytest

from research_agent_teams.tools.path_boundaries import PathBoundaryError, default_vault_root
from research_agent_teams.tools.quality_scoreboard import (
    build_quality_scoreboard,
    main,
    scan_run_manifests,
)
from research_agent_teams.operate.cli import main as operate_main
from research_agent_teams.tools.runstore import checkpoint_stage, create_run
from research_agent_teams.tools.validate_artifact import validate_against

TS = "2026-07-05T00:00:00Z"


def _fake_aers_root(tmp_path):
    root = tmp_path / "AERS"
    (root / "skills" / "safe").mkdir(parents=True)
    (root / "skills" / "safe" / "SKILL.md").write_text("---\nname: safe\n---\n", encoding="utf-8")
    (root / "catalog").mkdir()
    (root / "catalog" / "skills-enriched.json").write_text(
        '{"skills":[{"name":"safe","path":"skills/safe/SKILL.md","collection":"safe",'
        '"description_effective":"safe","tags":{},"license":"MIT","commercial_use":"allowed",'
        '"quality_score":90,"quality_flags":[],"line_count":10,"has_references":false}]}',
        encoding="utf-8",
    )
    (root / "catalog" / "provenance.json").write_text(
        '{"collections":[{"id":"safe","path":"skills/safe","license":"MIT",'
        '"commercial_use":"allowed","source_confidence":"high","source_url":"x",'
        '"security_review":"SECURITY.md"}]}',
        encoding="utf-8",
    )
    (root / "catalog" / "skill-audit.json").write_text(
        '{"records":[{"path":"skills/safe/SKILL.md","collection":"safe","exact_case":true,'
        '"has_description":true,"has_frontmatter":true,"has_name":true,"line_count":10}]}',
        encoding="utf-8",
    )
    return root


def test_scan_run_manifests_reads_metadata_only(tmp_path):
    runs = tmp_path / "runs"
    create_run(runs, "r1", "new_direction", "DISCOVER", TS, project="proj")
    report = scan_run_manifests(runs)
    assert report["run_count"] == 1
    assert report["by_status"] == {"running": 1}
    row = report["runs"][0]
    assert row["run_id"] == "r1"
    assert row["project"] == "proj"
    assert row["current_stage"] == "DISCOVER"
    assert "request" not in row


def test_scan_run_manifests_records_invalid_manifests(tmp_path):
    bad = tmp_path / "runs" / "bad"
    bad.mkdir(parents=True)
    (bad / "manifest.yaml").write_text("[not, a, mapping]", encoding="utf-8")
    report = scan_run_manifests(tmp_path / "runs")
    assert report["run_count"] == 0
    assert report["invalid_manifests"][0]["path"] == str(Path("bad") / "manifest.yaml")


def test_quality_scoreboard_schema_and_status(tmp_path):
    runs = tmp_path / "runs"
    create_run(runs, "r1", "new_direction", "DISCOVER", TS, project="proj")
    scoreboard = build_quality_scoreboard(
        runs_dir=runs,
        aers_root=_fake_aers_root(tmp_path),
        include_manual=True,
    )
    assert validate_against("rat_quality_scoreboard.schema.json", scoreboard) == []
    assert scoreboard["overall_status"] == "needs_manual"
    assert scoreboard["summary"]["required_machine_failures"] == 0
    assert scoreboard["summary"]["manual_open"] == 1
    assert scoreboard["summary"]["business_output_failures"] == 0
    assert scoreboard["summary"]["business_output_failures_current_contract"] == 0
    assert scoreboard["summary"]["business_output_failures_legacy_contract"] == 0
    assert scoreboard["summary"]["business_output_advisories"] == 0
    assert scoreboard["summary"]["vault_write"] is False
    assert scoreboard["summary"]["external_skill_execution"] is False
    # The catalog is registry-derived. Wave 2 (2026-08-04) took the operated surface from twelve
    # to twenty-one; the 2026-08-07 backlog close (ideate_ring, aers_enhanced_research_pack) took
    # it to twenty-three. This stays a hard number on purpose, so wiring a mode without wiring the
    # rest of its panel (menu, intent, drill-down, output contract) cannot pass unnoticed.
    assert scoreboard["capability"]["operated_modes"] == 23
    assert scoreboard["runs"]["run_count"] == 1
    assert scoreboard["business_outputs"]["completed_run_count"] == 0


def _completed_run_without_markdown(runs: Path, run_id: str, *, pin_contract: bool) -> Path:
    """A finished run that produced no director Markdown, with or without today's product contract."""
    run = runs / "proj" / run_id
    run.mkdir(parents=True)
    (run / "manifest.yaml").write_text(
        f"schema_version: 1.0.0\nrun_id: {run_id}\nproject: proj\nstatus: done\nmode: gap_breadth\n",
        encoding="utf-8",
    )
    if pin_contract:
        (run / "task_frame.artifact.json").write_text(json.dumps({
            "payload": {"mode": "gap_breadth", "project": "proj",
                        "product_contract": {"contract_version": "mode-handoff/v2",
                                             "product_version": "gap-dossier/v1",
                                             "primary_markdown": "director-review/gaps/gap-scan.md"}},
        }), encoding="utf-8")
    return run


def test_current_contract_run_without_director_markdown_blocks_scoreboard(tmp_path):
    """A run made under today's contract that ships no product is a live regression — it blocks."""
    runs = tmp_path / "runs"
    _completed_run_without_markdown(runs, "r1", pin_contract=True)
    scoreboard = build_quality_scoreboard(
        runs_dir=runs,
        aers_root=_fake_aers_root(tmp_path),
        include_manual=False,
    )
    assert scoreboard["overall_status"] == "blocked"
    assert scoreboard["summary"]["business_output_failures"] == 1
    assert scoreboard["summary"]["business_output_failures_current_contract"] == 1
    assert scoreboard["business_outputs"]["runs"][0]["failures"] == [
        "primary_director_markdown_missing"
    ]


def test_pre_contract_run_is_counted_and_named_but_does_not_block(tmp_path):
    """History that cannot be repaired by re-rendering must not pin the board red forever.

    It is still counted and named — the backlog stays visible, it just stops
    masking whether TODAY's work is healthy.
    """
    runs = tmp_path / "runs"
    _completed_run_without_markdown(runs, "legacy-1", pin_contract=False)
    scoreboard = build_quality_scoreboard(
        runs_dir=runs,
        aers_root=_fake_aers_root(tmp_path),
        include_manual=False,
    )
    assert scoreboard["overall_status"] == "machine_clean"
    assert scoreboard["summary"]["business_output_failures"] == 1
    assert scoreboard["summary"]["business_output_failures_current_contract"] == 0
    assert scoreboard["summary"]["business_output_failures_legacy_contract"] == 1
    assert scoreboard["business_outputs"]["legacy_failure_run_ids"] == ["legacy-1"]


def test_a_live_regression_is_not_hidden_by_a_legacy_backlog(tmp_path):
    """The whole point of the split: one bad new run still blocks amid any amount of history."""
    runs = tmp_path / "runs"
    _completed_run_without_markdown(runs, "legacy-1", pin_contract=False)
    _completed_run_without_markdown(runs, "legacy-2", pin_contract=False)
    _completed_run_without_markdown(runs, "fresh-1", pin_contract=True)
    scoreboard = build_quality_scoreboard(
        runs_dir=runs,
        aers_root=_fake_aers_root(tmp_path),
        include_manual=False,
    )
    assert scoreboard["overall_status"] == "blocked"
    assert scoreboard["summary"]["business_output_failures_current_contract"] == 1
    assert scoreboard["summary"]["business_output_failures_legacy_contract"] == 2


def test_every_one_button_mode_pins_a_product_contract():
    """The legacy split is only safe while new runs really are tagged `current`.

    If a mode ever ships without a pinned product contract, its runs would be
    graded as history and a real regression could slip past the board.
    """
    import yaml as _yaml

    from research_agent_teams.operate.modes import REGISTRY

    registry_path = (Path(__file__).resolve().parents[1]
                     / "orchestrator" / "mode_registry.yaml")
    modes = (_yaml.safe_load(registry_path.read_text(encoding="utf-8")) or {}).get("modes") or {}
    unpinned = sorted(m for m in REGISTRY
                      if not ((modes.get(m) or {}).get("handoff") or {}).get("product_version"))
    assert unpinned == [], f"these one-button modes would be graded as legacy history: {unpinned}"


def test_invalid_manifest_blocks_scoreboard_machine_clean(tmp_path):
    runs = tmp_path / "runs"
    create_run(runs, "r1", "new_direction", "DISCOVER", TS, project="proj")
    bad = runs / "proj" / "bad-run"
    bad.mkdir(parents=True)
    (bad / "manifest.yaml").write_text("[]", encoding="utf-8")
    scoreboard = build_quality_scoreboard(
        runs_dir=runs,
        aers_root=_fake_aers_root(tmp_path),
        include_manual=False,
    )
    assert scoreboard["overall_status"] == "blocked"
    assert scoreboard["summary"]["invalid_manifests"] == 1


def test_quality_scoreboard_cli_rejects_default_vault_out(tmp_path):
    blocked = default_vault_root() / "_blocked-quality-scoreboard.json"
    with pytest.raises(PathBoundaryError, match="inside vault"):
        main([
            "--runs-dir",
            str(tmp_path / "runs"),
            "--aers-root",
            str(_fake_aers_root(tmp_path)),
            "--out",
            str(blocked),
            "--no-manual",
        ])
    assert not blocked.exists()


def test_operate_scoreboard_cli_runs(tmp_path, capsys):
    operate_main([
        "scoreboard",
        "--runs-dir",
        str(tmp_path / "runs"),
        "--aers-root",
        str(_fake_aers_root(tmp_path)),
        "--no-manual",
    ])
    out = capsys.readouterr().out
    assert '"scoreboard": "rat_quality_scoreboard"' in out
    assert '"overall_status": "machine_clean"' in out
