"""operate/modes/gap_breadth — the 5-hunter panel, really parallel (audit B3/W4)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from research_agent_teams.operate import spine
from research_agent_teams.operate.artifacts import GateBlock
from research_agent_teams.operate.modes import _shared, gap_breadth

TS = "2026-06-13T00:00:00Z"
REQ = "scan for mandibular canal segmentation gaps"

BUNDLES = {
    "future-work-miner": [{"gap_id": "FW-1", "statement": "canal segmentation prompt budgets are an open problem",
                           "source_ref": "[[p1]]", "evidence_ref": ["[[p1]]"], "derived_from": ["future_work"]}],
    "weakness-spotter": [{"gap_id": "WK-1", "statement": "canal segmentation evals ignore scanner shift",
                          "locus": "[[p2]] §4", "opportunity": "add cross-scanner eval",
                          "source_ref": "[[p2]]", "evidence_ref": ["[[p2]]"],
                          "derived_from": ["weakness_opportunity"]}],
    "white-space-mapper": [{"gap_id": "WS-1", "statement": "no one studies canal segmentation with sparse clicks",
                            "white_space_present": True, "source_ref": "[[p3]]", "evidence_ref": ["[[p3]]"],
                            "derived_from": ["white_space_present"]}],
    "cross-domain-transfer-scout": [{"gap_id": "XF-1", "statement": "vessel tracking priors untried on canal segmentation",
                                     "source_domain": "vessel tracking", "target_hook": "tubular prior",
                                     "source_ref": "[[p4]]", "evidence_ref": ["[[p4]]"],
                                     "derived_from": ["transfer_potential"]}],
    "contrarian-angle-generator": [{"gap_id": "CA-1", "statement": "canal segmentation may not need 3D context",
                                    "challenged_assumption": "3D context is required",
                                    "source_ref": "[[p5]]", "evidence_ref": ["[[p5]]"],
                                    "derived_from": ["contrarian_angle"]}],
}


def _begin(tmp_path, **kw):
    runs = tmp_path / "runs"
    runs.mkdir(exist_ok=True)
    plan = spine.begin(str(runs), "gb1", REQ, "gap_breadth", TS, **kw)
    return plan["run_dir"]


def _drop_bundles(rd, only=None, override=None):
    for hunter, signals in (override or BUNDLES).items():
        if only and hunter not in only:
            continue
        p = Path(rd) / "inbox" / f"DISCOVER.{hunter}.bundle.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({"signals": signals}), encoding="utf-8")


def test_llm_step_returns_five_independent_hunters(tmp_path):
    rd = _begin(tmp_path)
    panel = gap_breadth.llm_step(rd, "DISCOVER", REQ)
    assert len(panel["workers"]) == 5
    labels = {w["label"] for w in panel["workers"]}
    assert labels == set(gap_breadth.HUNTERS)
    for w in panel["workers"]:
        assert "NORTH STAR" in w["prompt"] and "ONLY this" in w["prompt"]
    assert gap_breadth.llm_step(rd, "REPORT", REQ) is None


def test_happy_path_merges_classifies_and_scores(tmp_path):
    rd = _begin(tmp_path)
    _drop_bundles(rd)
    paths, report = gap_breadth.run_dets(rd, "DISCOVER", TS)
    assert report["gaps_classified"] == 5
    assert report["signals_per_hunter"]["weakness-spotter"] == 1
    gc = json.loads(Path(rd, "evidence", "DISCOVER", "gap-classification.artifact.json").read_text(encoding="utf-8"))
    types = {g["gap_id"]: g["gap_type"] for g in gc["payload"]["gaps"]}
    assert types["XF-1"] == "transfer_gap" and types["CA-1"] == "assumption_gap"
    assert types["WK-1"] == "methodological_gap" and types["WS-1"] == "coverage_gap"
    nv = json.loads(Path(rd, "evidence", "DISCOVER", "novelty-score.artifact.json").read_text(encoding="utf-8"))
    assert len(nv["payload"]["scores"]) == 5                       # SCORE-ONLY: none dropped
    assert report["novelty_grounded"] is False                     # no pre-search bundle
    rpaths, _ = gap_breadth.run_dets(rd, "REPORT", TS)
    assert rpaths


def test_missing_hunter_bundle_blocks_by_name(tmp_path):
    rd = _begin(tmp_path)
    _drop_bundles(rd, only={"future-work-miner", "weakness-spotter"})
    with pytest.raises(GateBlock, match="white-space-mapper"):
        gap_breadth.run_dets(rd, "DISCOVER", TS)


def test_invented_slug_blocks_when_the_vault_is_reachable(tmp_path, monkeypatch):
    vault = tmp_path / "vault"
    (vault / "02-wiki").mkdir(parents=True)
    (vault / "02-wiki" / "p1.md").write_text("# p1", encoding="utf-8")
    monkeypatch.setattr(_shared, "VAULT_ROOT_OVERRIDE", str(vault))
    rd = _begin(tmp_path)
    _drop_bundles(rd, only={"future-work-miner"})
    _drop_bundles(rd, override={h: s for h, s in BUNDLES.items() if h != "future-work-miner"})
    with pytest.raises(GateBlock, match="vault-slug integrity BLOCK"):
        gap_breadth.run_dets(rd, "DISCOVER", TS)                   # [[p2]]..[[p5]] don't exist


def test_out_of_scope_drift_blocks_the_panel(tmp_path):
    rd_runs = tmp_path / "runs"
    rd_runs.mkdir()
    plan = spine.begin(str(rd_runs), "gb2", REQ, "gap_breadth", TS,
                       north_star={"statement": REQ, "in_scope": [], "out_of_scope": ["pricing"]})
    rd = plan["run_dir"]
    poisoned = {h: [dict(s[0], statement=s[0]["statement"] + " with a pricing angle")]
                for h, s in BUNDLES.items()}
    _drop_bundles(rd, override=poisoned)
    with pytest.raises(GateBlock, match="drift gate BLOCK"):
        gap_breadth.run_dets(rd, "DISCOVER", TS)
