"""tools/project_memory — cross-run gap inventory (audit C1)."""
from __future__ import annotations

import json

import pytest

from research_agent_teams.tools.project_memory import (
    append_gap_inventory,
    load_gap_inventory,
    prior_overlaps,
    workspace_for_run,
)

GAPS = [{"gap_id": "GAP-1", "statement": "prompt efficiency for canal segmentation is unstudied",
         "gap_type": "coverage_gap"},
        {"gap_id": "GAP-2", "statement": "no cross-scanner robustness evaluation exists",
         "gap_type": "empirical_gap"}]


def _machine(tmp_path):
    (tmp_path / "runs" / "proj-a" / "r1").mkdir(parents=True)
    ws = tmp_path / "projects" / "proj-a"
    (ws / "notes").mkdir(parents=True)
    return tmp_path


def test_workspace_resolution_project_layout_vs_flat(tmp_path):
    m = _machine(tmp_path)
    assert workspace_for_run(m / "runs" / "proj-a" / "r1") == m / "projects" / "proj-a"
    (m / "runs" / "flat-run").mkdir()
    assert workspace_for_run(m / "runs" / "flat-run") is None        # legacy flat -> no memory


def test_append_is_idempotent_per_run_and_gap(tmp_path):
    ws = _machine(tmp_path) / "projects" / "proj-a"
    assert append_gap_inventory(ws, "r1", "2026-06-13T00:00:00Z", GAPS) == 2
    assert append_gap_inventory(ws, "r1", "2026-06-13T00:00:01Z", GAPS) == 0   # repair re-run: no dupes
    assert append_gap_inventory(ws, "r2", "2026-06-13T00:00:02Z", GAPS[:1]) == 1
    assert len(load_gap_inventory(ws)) == 3


def test_load_skips_corrupt_lines(tmp_path):
    ws = _machine(tmp_path) / "projects" / "proj-a"
    append_gap_inventory(ws, "r1", "2026-06-13T00:00:00Z", GAPS)
    p = ws / "notes" / "gap-inventory.jsonl"
    p.write_text(p.read_text(encoding="utf-8") + "{corrupt\n", encoding="utf-8")
    assert len(load_gap_inventory(ws)) == 2


def test_prior_overlaps_match_other_runs_only(tmp_path):
    ws = _machine(tmp_path) / "projects" / "proj-a"
    append_gap_inventory(ws, "r1", "2026-06-13T00:00:00Z", GAPS)
    inv = load_gap_inventory(ws)
    near = [{"gap_id": "GAP-9",
             "statement": "prompt efficiency for canal segmentation is unstudied today"}]
    hits = prior_overlaps(near, inv, run_id="r2")
    assert hits and hits[0]["prior_run_id"] == "r1" and hits[0]["prior_gap_id"] == "GAP-1"
    assert prior_overlaps(near, inv, run_id="r1") == []              # same-run rows excluded
    far = [{"gap_id": "GAP-9", "statement": "completely different topic about pricing engines"}]
    assert prior_overlaps(far, inv, run_id="r2") == []


def test_inventory_refuses_to_live_in_the_vault(tmp_path):
    bad = tmp_path / "PhD-Research-OS" / "projects" / "p"
    (bad / "notes").mkdir(parents=True)
    with pytest.raises(ValueError):
        append_gap_inventory(bad, "r1", "2026-06-13T00:00:00Z", GAPS)
