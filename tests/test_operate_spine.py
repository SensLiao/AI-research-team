"""Operate-layer acceptance — drive `new_direction` through the STEP-WISE spine (operate.spine +
modes.new_direction) the way the research-orchestrator skill does, with stub worker bundles in place of
live sub-agents. Proves the operated twin carries the SAME guarantees the engine-driven test
(test_m3a_new_direction) proves for run_task():
  - the two DISCOVER hard gates are LIVE (thin evidence -> BLOCK, run halts, never ideates);
  - the gap chain + ranked menu are produced and contract-valid;
  - the tamper-evident ledger hash-chain stays intact;
  - the IDEATE boundary is a director_signoff gate; the machine never self-bets.

The ONLY difference from a live run is that the LLM workers' bundles are fixtures here instead of real
vault mining — exactly the tested-vs-operated line. The deterministic governance is the real cores.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from research_agent_teams.operate import spine
from research_agent_teams.operate.artifacts import GateBlock
from research_agent_teams.operate.modes import new_direction
from research_agent_teams.tools.ledger import read_events, verify_chain
from research_agent_teams.tools.runstore import classify_status

TS = "2026-06-09T00:00:00Z"

_EVIDENCE_CLEAN = {
    "query": "gap scan for a new promptable-3D-segmentation direction",
    "sources": [
        {"id": "s1", "kind": "paper", "ref": "[[hu-2021-lora]]", "claim_support": "strong"},
        {"id": "s2", "kind": "paper", "ref": "[[toothfairy-2025]]", "claim_support": "moderate"},
        {"id": "s3", "kind": "paper", "ref": "[[hdilemma-2024]]", "claim_support": "moderate"},
    ],
    "saturation_reached": True,
}
_CLAIM_LIST = {"source_scope": "new-direction gap scan",
               "claims": [{"claim_id": "c1", "text": "Adapter tuning is underexplored for promptable 3D seg.",
                           "source_ref": "[[hu-2021-lora]]"}]}
_CLAIM_MAP = {"mappings": [{"claim_id": "c1", "overall_support": "supported",
              "loci": [{"locus_id": "l1", "source_ref": "[[hu-2021-lora]]", "location": "Sec 5",
                        "kind": "text", "reported_result": "named as open future work",
                        "supports_claim": True}]}]}
_SIGNALS = [
    {"gap_id": "GAP-1", "statement": "Adapter tuning underexplored for promptable 3D segmentation",
     "source_ref": "[[hu-2021-lora]]", "evidence_ref": ["[[hu-2021-lora]]"], "derived_from": ["white_space_present"]},
    {"gap_id": "GAP-2", "statement": "No public fair-budget benchmark for SAM medical adaptation",
     "source_ref": "[[toothfairy-2025]]", "evidence_ref": ["[[toothfairy-2025]]"]},
    {"gap_id": "GAP-3", "locus": "baseline evaluation", "opportunity": "equal-budget comparison",
     "evidence_ref": ["[[hdilemma-2024]]"], "derived_from": ["contrarian_angle", "empirically_untested"]},
]
_HYPOTHESES = [
    {"hypothesis_id": "IH1", "statement": "A LoRA adapter matches full fine-tune for 3D prompts at equal budget.",
     "falsifiable_prediction": "Mean Dice(LoRA) >= Dice(full-ft) within 1% at equal GPU-hours on fold0.",
     "evidence_needed": ["equal-budget ablation"], "evidence_ref": ["GAP-1", "[[hu-2021-lora]]"]},
]
_IDEAS = [
    {"idea_id": "IDEA-1", "summary": "LoRA-vs-full-ft equal-budget ablation for promptable 3D seg.",
     "evidence_ref": ["IH1", "GAP-1"], "from_hypothesis_ref": "IH1",
     "feasibility": {"compute": "medium", "data": "available", "time": "medium"}},
    {"idea_id": "IDEA-2", "summary": "Build the fair-budget SAM-medical benchmark and re-rank the leaderboard.",
     "evidence_ref": ["IH1", "GAP-2"], "from_hypothesis_ref": "IH1",
     "feasibility": {"compute": "low", "data": "available", "time": "short"}},
]
# Audit B3: the IDEATE bundle now carries the worker's pairwise tournament judgments (every
# unordered pair of its ideas) + optional evolved ideas — the dets validate + Elo-rate them.
_TOURNAMENT = [{"round": 1, "pair_a": "IDEA-1", "pair_b": "IDEA-2", "winner": "IDEA-2",
                "rationale": "the benchmark idea is cheaper and unblocks the ablation idea"}]
_EVOLVED: list = []


def _stage_bundle(run_dir, stage, payload):
    inbox = Path(run_dir) / "inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    (inbox / f"{stage}.bundle.json").write_text(json.dumps(payload), encoding="utf-8")


def _discover_bundle(evidence="clean"):
    table = _EVIDENCE_CLEAN if evidence == "clean" else {**_EVIDENCE_CLEAN, "sources": _EVIDENCE_CLEAN["sources"][:1]}
    return {"read_summary": "stub", "evidence_table": table, "claim_list": _CLAIM_LIST,
            "claim_evidence_map": _CLAIM_MAP, "signals": _SIGNALS}


def _drive_discover(run_dir):
    spine.open_stage(run_dir, "DISCOVER", TS)
    paths, rep = new_direction.run_dets(run_dir, "DISCOVER", TS)
    return spine.commit_stage(run_dir, "DISCOVER", paths, TS), rep


def _drive_ideate(run_dir):
    _stage_bundle(run_dir, "IDEATE", {"hypotheses": _HYPOTHESES, "ideas": _IDEAS,
                                      "tournament": _TOURNAMENT, "evolved": _EVOLVED})
    spine.open_stage(run_dir, "IDEATE", TS)
    paths, rep = new_direction.run_dets(run_dir, "IDEATE", TS)
    return spine.commit_stage(run_dir, "IDEATE", paths, TS), rep


def _drive_report(run_dir):
    spine.open_stage(run_dir, "REPORT", TS)
    paths, _ = new_direction.run_dets(run_dir, "REPORT", TS)
    return spine.commit_stage(run_dir, "REPORT", paths, TS)


# --------------------------------------------------------------------------- 1. end-to-end happy path

def test_operate_new_direction_runs_end_to_end(tmp_path):
    runs = tmp_path / "runs"
    plan = spine.begin(str(runs), "op1", "find a promptable segmentation direction worth betting on",
                       "new_direction", TS)
    rd = plan["run_dir"]
    assert plan["stages"] == ["DISCOVER", "IDEATE", "REPORT"]

    _stage_bundle(rd, "DISCOVER", _discover_bundle("clean"))
    d_res, d_rep = _drive_discover(rd)
    assert d_rep["evidence_gate"] == "PASS" and d_rep["citation_gate"] == "PASS"
    assert d_res["next_stage"] == "IDEATE"

    i_res, i_rep = _drive_ideate(rd)
    assert i_rep["ideas_ranked"] == 2
    assert i_res["gate"] == "director_signoff"          # the /idea-bet boundary
    assert i_res["next_stage"] == "REPORT"

    r_res = _drive_report(rd)
    assert r_res["done"] is True
    st = spine.status(rd)
    assert st["run_status"] == "done"
    assert st["completed"] == ["DISCOVER", "IDEATE", "REPORT"]


# --------------------------------------------------------------------------- 2. DISCOVER gates are LIVE

def test_operate_thin_evidence_blocks_and_never_ideates(tmp_path):
    runs = tmp_path / "runs"
    plan = spine.begin(str(runs), "op2", "ideate on thin promptable segmentation evidence",
                       "new_direction", TS)
    rd = plan["run_dir"]
    _stage_bundle(rd, "DISCOVER", _discover_bundle("thin"))
    spine.open_stage(rd, "DISCOVER", TS)
    with pytest.raises(GateBlock):
        new_direction.run_dets(rd, "DISCOVER", TS)
    # the gate artifact was written as 'blocked'; the stage was NOT committed; IDEATE never created
    ev = json.loads((Path(rd) / "evidence" / "DISCOVER" / "evidence-verdict.artifact.json").read_text())
    assert ev["payload"]["verdict"] == "BLOCK"
    assert not (Path(rd) / "evidence" / "IDEATE").exists()
    assert classify_status(rd) != "done"


# --------------------------------------------------------------------------- 3. menu ranked + no self-bet

def test_operate_menu_ranked_by_feasibility_and_no_self_bet(tmp_path):
    runs = tmp_path / "runs"
    plan = spine.begin(str(runs), "op3", "rank promptable segmentation directions", "new_direction", TS)
    rd = plan["run_dir"]
    _stage_bundle(rd, "DISCOVER", _discover_bundle("clean"))
    _drive_discover(rd)
    _drive_ideate(rd)
    rows = new_direction.menu(rd)
    assert [r["rank"] for r in rows] == [1, 2]
    assert rows[0]["idea_id"] == "IDEA-2"               # most feasible (low/available/short) ranks #1
    assert [r["score"] for r in rows] == sorted([r["score"] for r in rows], reverse=True)
    backlog = json.loads((Path(rd) / "evidence" / "IDEATE" / "idea-backlog.artifact.json").read_text())["payload"]
    assert not (set(backlog) & {"selected", "chosen", "bet", "winner"})
    for idea in backlog["ranked_ideas"]:
        assert not (set(idea) & {"selected", "chosen", "bet", "winner"})


# --------------------------------------------------------------------------- 4. tamper-evident ledger intact

def test_operate_ledger_hash_chain_intact(tmp_path):
    runs = tmp_path / "runs"
    plan = spine.begin(str(runs), "op4", "menu the promptable segmentation directions for a human bet",
                       "new_direction", TS)
    rd = plan["run_dir"]
    _stage_bundle(rd, "DISCOVER", _discover_bundle("clean"))
    _drive_discover(rd)
    _drive_ideate(rd)
    _drive_report(rd)
    assert verify_chain(read_events(Path(rd) / "ledger.jsonl")) == []
    # the machine produced only the menu — no bet/adr written by the run
    produced = [p.name for p in (Path(rd) / "evidence").rglob("*.json")]
    assert not any("idea-bet" in n or ".adr." in n for n in produced)
