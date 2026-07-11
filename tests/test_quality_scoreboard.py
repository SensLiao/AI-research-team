from __future__ import annotations

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
    assert scoreboard["summary"]["business_output_advisories"] == 0
    assert scoreboard["summary"]["vault_write"] is False
    assert scoreboard["summary"]["external_skill_execution"] is False
    assert scoreboard["capability"]["operated_modes"] == 10
    assert scoreboard["runs"]["run_count"] == 1
    assert scoreboard["business_outputs"]["completed_run_count"] == 0


def test_completed_run_without_director_markdown_blocks_scoreboard(tmp_path):
    runs = tmp_path / "runs"
    run = runs / "proj" / "r1"
    run.mkdir(parents=True)
    (run / "manifest.yaml").write_text(
        "schema_version: 1.0.0\nrun_id: r1\nproject: proj\nstatus: done\nmode: gap_breadth\n",
        encoding="utf-8",
    )
    scoreboard = build_quality_scoreboard(
        runs_dir=runs,
        aers_root=_fake_aers_root(tmp_path),
        include_manual=False,
    )
    assert scoreboard["overall_status"] == "blocked"
    assert scoreboard["summary"]["business_output_failures"] == 1
    assert scoreboard["business_outputs"]["runs"][0]["failures"] == [
        "primary_director_markdown_missing"
    ]


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
