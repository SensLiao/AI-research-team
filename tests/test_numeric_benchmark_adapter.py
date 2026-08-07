from __future__ import annotations

import hashlib
import json

import pytest

from research_agent_teams.operate.cli import main as operate_main
from research_agent_teams.tools.numeric_benchmark_adapter import (
    build_report_from_files,
    main,
)
from research_agent_teams.tools.path_boundaries import PathBoundaryError, default_vault_root
from research_agent_teams.tools.validate_artifact import validate_against


def _write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def _manifest(lines):
    stdout = "\n".join(lines) + "\n"
    return {
        "mode": "live",
        "lines": lines,
        "missing": [],
        "stdout_sha256": "sha256:" + hashlib.sha256(stdout.encode("utf-8")).hexdigest(),
    }


def _inputs(tmp_path, *, claimed=0.85, live=True, journal=True):
    run_records = _write(
        tmp_path / "run-records.json",
        [{"condition_id": "c1", "status": "provisional", "provenance": {"config_hash": "cfg"}, "metrics": {"Dice": claimed}}],
    )
    results = _write(
        tmp_path / "results.json",
        [
            {"condition_id": "c1", "metric": "Dice", "value": 0.80, "case_id": "a"},
            {"condition_id": "c1", "metric": "Dice", "value": 0.90, "case_id": "b"},
        ],
    )
    line = "a" * 64 + "  results.json"
    manifest = _write(
        tmp_path / "hash-manifest.json",
        _manifest([line]) if live else {"mode": "plan", "lines": [line], "missing": []},
    )
    journal_data = {"status": "executed", "run_id": "r1"} if journal else {}
    journal_path = _write(tmp_path / "journal.json", journal_data)
    return run_records, results, manifest, journal_path


def test_numeric_benchmark_passes_when_claim_matches_recomputed_rows(tmp_path):
    run_records, results, manifest, journal = _inputs(tmp_path)
    report = build_report_from_files(
        run_records_path=run_records,
        result_artifact_paths=[results],
        hash_manifest_path=manifest,
        journal_path=journal,
        required_paths=["results.json"],
    )
    assert validate_against("numeric_benchmark_report.schema.json", report) == []
    assert report["verdict"] == "PASS"
    assert report["summary"]["matched_metric_count"] == 1
    assert report["trust_boundary"]["prose_summaries_trusted"] is False


def test_numeric_benchmark_blocks_metric_mismatch(tmp_path):
    run_records, results, manifest, journal = _inputs(tmp_path, claimed=0.9)
    report = build_report_from_files(
        run_records_path=run_records,
        result_artifact_paths=[results],
        hash_manifest_path=manifest,
        journal_path=journal,
        required_paths=["results.json"],
    )
    assert report["verdict"] == "BLOCK"
    assert report["summary"]["mismatch_count"] == 1
    assert any("claimed=0.9" in violation for violation in report["violations"])


def test_numeric_benchmark_non_live_hash_manifest_is_informational_not_blocking(tmp_path):
    """R3 §B①: a non-live (offline-plan) hash manifest no longer drives BLOCK on its own — the
    adapter's own `requires_live_hash_manifest` gate is now informational. `hash_check` itself
    (from hash_manifest_validator, untouched — see test_hash_manifest_validator.py) still says
    BLOCK internally; it is just no longer folded into the top-level violations that decide the
    adapter's verdict."""
    run_records, results, manifest, journal = _inputs(tmp_path, live=False, journal=True)
    report = build_report_from_files(
        run_records_path=run_records,
        result_artifact_paths=[results],
        hash_manifest_path=manifest,
        journal_path=journal,
        required_paths=["results.json"],
    )
    assert report["verdict"] == "PASS"
    assert not any(v.startswith("hash:") for v in report["violations"])
    assert report["hash_check"]["verdict"] == "BLOCK"
    assert any("not live evidence" in v for v in report["hash_check"]["violations"])


def test_numeric_benchmark_blocks_missing_journal(tmp_path):
    """The run-journal requirement is untouched by R3 — only the hash-manifest gate was downgraded."""
    run_records, results, manifest, journal = _inputs(tmp_path, live=True, journal=False)
    report = build_report_from_files(
        run_records_path=run_records,
        result_artifact_paths=[results],
        hash_manifest_path=manifest,
        journal_path=journal,
        required_paths=["results.json"],
    )
    assert report["verdict"] == "BLOCK"
    assert any("run journal" in violation for violation in report["violations"])


def test_numeric_benchmark_cli_rejects_default_vault_out(tmp_path):
    run_records, results, manifest, journal = _inputs(tmp_path)
    blocked = default_vault_root() / "_blocked-numeric-benchmark.json"
    with pytest.raises(PathBoundaryError, match="inside vault"):
        main([
            "--run-records",
            str(run_records),
            "--result-artifact",
            str(results),
            "--hash-manifest",
            str(manifest),
            "--journal",
            str(journal),
            "--required-path",
            "results.json",
            "--out",
            str(blocked),
        ])
    assert not blocked.exists()


def test_operate_numeric_benchmark_cli_runs(tmp_path, capsys):
    run_records, results, manifest, journal = _inputs(tmp_path)
    operate_main([
        "numeric-benchmark",
        "--run-records",
        str(run_records),
        "--result-artifact",
        str(results),
        "--hash-manifest",
        str(manifest),
        "--journal",
        str(journal),
        "--required-path",
        "results.json",
    ])
    out = capsys.readouterr().out
    assert '"adapter": "numeric_benchmark_adapter"' in out
    assert '"verdict": "PASS"' in out
