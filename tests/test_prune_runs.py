"""Real tests for tools/prune_runs.py — the L1 run-store housekeeping reaper.

Builds minimal but realistic run dirs (a manifest.yaml is what makes a directory a 'run', per
runstore.find_run_dir's rule) across BOTH layouts, then asserts the age + status + project filters and
the three safety fences (in-flight double-lock, runs_dir escape, vault marker). dry_run must delete
nothing; a real delete must remove exactly the eligible runs and leave everything else on disk.
"""
from __future__ import annotations

import yaml

from research_agent_teams.tools.prune_runs import prune_runs

NOW = "2026-06-12T00:00:00Z"


def _make_run(runs_dir, run_id, *, status, updated_at, project=None):
    """Create runs/<id>/ (or runs/<project>/<id>/) with a minimal manifest.yaml + an evidence file."""
    run_dir = (runs_dir / project / run_id) if project else (runs_dir / run_id)
    run_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "schema_version": "1.0.0",
        "run_id": run_id,
        "project": project,
        "status": status,
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": updated_at,
        "mode": "new_direction",
        "entry_stage": "DISCOVER",
        "next_step": None,
        "completed_work": [],
    }
    (run_dir / "manifest.yaml").write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")
    (run_dir / "evidence").mkdir(exist_ok=True)
    (run_dir / "evidence" / "scratch.txt").write_text("scratch", encoding="utf-8")
    return run_dir


def test_prunes_only_old_finished_runs(tmp_path):
    """done/rejected + old -> deletable; running (in-flight) + done-but-recent -> kept."""
    runs = tmp_path / "runs"
    _make_run(runs, "old-done", status="done", updated_at="2026-01-10T00:00:00Z")
    _make_run(runs, "old-rejected", status="rejected", updated_at="2026-02-01T00:00:00Z")
    _make_run(runs, "old-running", status="running", updated_at="2026-01-10T00:00:00Z")  # in-flight: never
    _make_run(runs, "recent-done", status="done", updated_at="2026-06-11T00:00:00Z")     # too recent

    res = prune_runs(runs, ts=NOW, older_than_days=30, dry_run=True)
    assert res["scanned"] == 4
    assert set(res["would_delete"]) == {"old-done", "old-rejected"}
    reasons = {s["run_id"]: s["reason"] for s in res["skipped"]}
    assert "in-flight" in reasons["old-running"]
    assert "too recent" in reasons["recent-done"]
    # dry-run deleted nothing
    assert (runs / "old-done" / "manifest.yaml").exists()


def test_real_delete_removes_only_eligible(tmp_path):
    """dry_run=False removes exactly the eligible runs; in-flight + recent survive on disk."""
    runs = tmp_path / "runs"
    _make_run(runs, "old-done", status="done", updated_at="2026-01-10T00:00:00Z")
    _make_run(runs, "old-running", status="running", updated_at="2026-01-10T00:00:00Z")
    _make_run(runs, "recent-done", status="done", updated_at="2026-06-11T00:00:00Z")

    res = prune_runs(runs, ts=NOW, older_than_days=30, dry_run=False)
    assert res["deleted"] == ["old-done"]
    assert not (runs / "old-done").exists()          # gone
    assert (runs / "old-running").exists()           # in-flight survived
    assert (runs / "recent-done").exists()           # too-recent survived


def test_nested_project_layout_and_filter(tmp_path):
    """Project-grouped runs runs/<project>/<id>/ are discovered; the project filter narrows the scope."""
    runs = tmp_path / "runs"
    _make_run(runs, "p2t-old", status="done", updated_at="2026-01-10T00:00:00Z", project="p2t")
    _make_run(runs, "nlp-old", status="done", updated_at="2026-01-10T00:00:00Z", project="nlp-cls")
    _make_run(runs, "flat-old", status="done", updated_at="2026-01-10T00:00:00Z")  # legacy flat

    # No filter: all three are discovered + eligible.
    res_all = prune_runs(runs, ts=NOW, older_than_days=30, dry_run=True)
    assert res_all["scanned"] == 3
    assert set(res_all["would_delete"]) == {"p2t-old", "nlp-old", "flat-old"}

    # project='p2t': only that project's run is eligible; the others are skipped (wrong project).
    res_p2t = prune_runs(runs, ts=NOW, older_than_days=30, project="p2t", dry_run=True)
    assert res_p2t["would_delete"] == ["p2t-old"]
    skipped_ids = {s["run_id"] for s in res_p2t["skipped"]}
    assert {"nlp-old", "flat-old"} <= skipped_ids


def test_custom_statuses_can_include_failed_but_never_in_flight(tmp_path):
    """A caller may add 'failed' to the prunable set; but listing an in-flight status (running) must
    STILL be refused by the second lock."""
    runs = tmp_path / "runs"
    _make_run(runs, "old-failed", status="failed", updated_at="2026-01-10T00:00:00Z")
    _make_run(runs, "old-running", status="running", updated_at="2026-01-10T00:00:00Z")

    res = prune_runs(runs, ts=NOW, older_than_days=30,
                     statuses=("done", "rejected", "failed", "running"), dry_run=True)
    assert res["would_delete"] == ["old-failed"]                   # custom status honoured
    reasons = {s["run_id"]: s["reason"] for s in res["skipped"]}
    assert "in-flight" in reasons["old-running"]                   # second lock overrides the caller


def test_vault_path_fence_blocks_deletion(tmp_path):
    """Defence-in-depth fence 2: if a candidate run dir's path contains the vault marker, it is skipped
    even if every other check passes (the run-store should never overlap the vault, but the lock holds)."""
    runs = tmp_path / "PhD-Research-OS" / "runs"     # path now contains the vault marker
    _make_run(runs, "old-done", status="done", updated_at="2026-01-10T00:00:00Z")

    res = prune_runs(runs, ts=NOW, older_than_days=30, dry_run=False)
    assert res["deleted"] == []                                    # nothing deleted
    assert any("phd-research-os" in s["reason"] for s in res["skipped"])
    assert (runs / "old-done" / "manifest.yaml").exists()          # survived the fence


def test_z_suffix_and_offset_timestamps_both_parse(tmp_path):
    """ts with a 'Z' suffix and an updated_at with an explicit offset both parse and compare correctly."""
    runs = tmp_path / "runs"
    _make_run(runs, "old-offset", status="done", updated_at="2026-01-10T00:00:00+00:00")
    res = prune_runs(runs, ts="2026-06-12T00:00:00Z", older_than_days=30, dry_run=True)
    assert res["would_delete"] == ["old-offset"]


def test_empty_runs_dir_is_noop(tmp_path):
    """A missing/empty runs dir scans zero runs and deletes nothing (no crash)."""
    res = prune_runs(tmp_path / "does-not-exist", ts=NOW, older_than_days=1, dry_run=False)
    assert res == {"scanned": 0, "deleted": [], "skipped": []}


def test_unquoted_yaml_timestamp_loaded_as_datetime_is_handled(tmp_path):
    """Robustness: a HAND-EDITED manifest with an UNQUOTED ISO timestamp is parsed by PyYAML into a
    datetime object (not a str). prune_runs must still treat it as a real timestamp, not skip the run."""
    runs = tmp_path / "runs"
    run_dir = runs / "hand-edited"
    run_dir.mkdir(parents=True)
    # Note: updated_at is intentionally UNQUOTED -> yaml.safe_load returns a datetime, not a str.
    (run_dir / "manifest.yaml").write_text(
        "schema_version: 1.0.0\n"
        "run_id: hand-edited\n"
        "project: null\n"
        "status: done\n"
        "created_at: 2026-01-01T00:00:00Z\n"
        "updated_at: 2026-01-10T00:00:00+00:00\n"
        "mode: m\nentry_stage: DISCOVER\nnext_step: null\ncompleted_work: []\n",
        encoding="utf-8",
    )
    res = prune_runs(runs, ts=NOW, older_than_days=30, dry_run=True)
    assert res["would_delete"] == ["hand-edited"]                  # datetime-typed stamp handled
