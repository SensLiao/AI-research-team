"""M3-b..f main-thread integration tests.

The cluster builders verified each schema via validate_against (the schema FILE).
These tests verify the INTEGRATION the main thread owns:
  - every new artifact_type is REGISTERED in validate_artifact.PAYLOAD_SCHEMAS
    (the validate_payload path, not just the file path);
  - the full freedom-layer agent census exists on disk AND in the roster;
  - the three human gates exist and are disable-model-invocation;
  - the five new modes resolve + route clean;
  - the cross-cluster data flows wire end-to-end through the REGISTERED schemas.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from research_agent_teams.orchestrator.graph_spec import load_roster
from research_agent_teams.orchestrator.router import resolve_task, validate_routing
from research_agent_teams.tools import classify_gap, novelty_aggregate, tournament_bracket
from research_agent_teams.tools.validate_artifact import (
    PAYLOAD_SCHEMAS,
    validate_payload,
)

PKG_ROOT = Path(__file__).resolve().parents[2] / "research_agent_teams"
AGENTS_DIR = PKG_ROOT / "agents"
GATES_DIR = PKG_ROOT / "gates"
SCHEMA_DIR = PKG_ROOT / "schemas"
TS = "2026-06-09T00:00:00Z"

# The 15 artifact_types this build adds (B:3, C:4, D1:2, D2:2, E:2, F:2).
M3BF_ARTIFACT_TYPES = [
    "debug_session", "experiment_tree", "variable_touch_verdict",
    "weakness_report", "white_space_map", "transfer_candidates", "contrarian_angles",
    "venue_candidates", "venue_profile",
    "venue_review", "venue_readiness_verdict",
    "figure_critique", "monitor_alert",
    "idea_tournament", "evolved_ideas",
]

# The 18 freedom-layer agents (the complete form: M3-a's 5 + this build's 13)
# plus the 2 infra agents (the gate checker + the VR configurator) this build added.
FREEDOM_LAYER_AGENTS = [
    # gap (7)
    "future-work-miner", "weakness-spotter", "white-space-mapper",
    "cross-domain-transfer-scout", "contrarian-angle-generator", "gap-classifier",
    "novelty-scorer",
    # ideate (4)
    "hypothesis-generator", "idea-tournament-ranker", "idea-evolver", "feasibility-reranker",
    # execute-menu (2)
    "auto-debugger", "experiment-tree-explorer",
    # analyze-menu (1)
    "figure-vlm-critic",
    # venue (3)
    "venue-selector", "venue-reviewer-persona", "area-chair-synthesizer",
    # monitor (1)
    "monitor",
]
INFRA_AGENTS = ["variable-touch-guard", "venue-review-configurator"]

NEW_MODES = ["gap_breadth", "ideate_ring", "debug_failed_run", "tree_explore", "venue_readiness"]


# --------------------------------------------------------------------------- #
#  Registration                                                               #
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("atype", M3BF_ARTIFACT_TYPES)
def test_artifact_type_is_registered(atype):
    """Each new type is in the registry and its schema file exists."""
    assert atype in PAYLOAD_SCHEMAS, f"{atype} not registered in PAYLOAD_SCHEMAS"
    assert (SCHEMA_DIR / PAYLOAD_SCHEMAS[atype]).exists(), f"schema file for {atype} missing"


@pytest.mark.parametrize("atype", M3BF_ARTIFACT_TYPES)
def test_registered_path_runs_the_real_schema(atype):
    """validate_payload finds and runs the schema (an empty payload yields a
    required-field error, NOT 'unknown artifact_type' — proving registration)."""
    errors = validate_payload(atype, {})
    assert not any("unknown artifact_type" in e for e in errors), (
        f"{atype} routed to the unknown-type branch (registration failed): {errors}"
    )


# --------------------------------------------------------------------------- #
#  Agent census                                                               #
# --------------------------------------------------------------------------- #

def test_freedom_layer_agents_exist_on_disk_and_in_roster():
    roster = load_roster()
    for agent in FREEDOM_LAYER_AGENTS + INFRA_AGENTS:
        assert (AGENTS_DIR / f"{agent}.md").exists(), f"agent spec {agent}.md missing"
        assert agent in roster, f"agent {agent} not in roster.yaml"


def test_full_18_freedom_layer_agents_present():
    """The headline count: exactly the 18 freedom-layer agents exist (complete form)."""
    present = [a for a in FREEDOM_LAYER_AGENTS if (AGENTS_DIR / f"{a}.md").exists()]
    assert len(present) == 18, f"expected 18 freedom-layer agents, found {len(present)}: {present}"


# --------------------------------------------------------------------------- #
#  Human gates                                                                 #
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("gate", ["idea-bet", "venue-pick", "venue-decide"])
def test_human_gate_is_disable_model_invocation(gate):
    """All three director gates exist and are human-only (model never self-invokes)."""
    path = GATES_DIR / f"{gate}.md"
    assert path.exists(), f"gate spec {gate}.md missing"
    text = path.read_text(encoding="utf-8")
    assert "disable-model-invocation: true" in text, f"{gate} is not disable-model-invocation"
    assert "kind: human-gate" in text, f"{gate} is not kind: human-gate"


# --------------------------------------------------------------------------- #
#  Mode admissibility                                                          #
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("mode", NEW_MODES)
def test_new_mode_resolves_and_routes_clean(mode):
    tf = resolve_task("req", mode, f"run-{mode}", TS)
    assert validate_routing(tf) == [], f"{mode} routing rejected"


def test_execute_menu_modes_force_the_variable_touch_gate():
    """A director_signoff EXECUTE-entry menu mode MUST carry variable-touch-guard
    (router guardrail 1 forces it because it is an EXECUTE blocking gate)."""
    for mode in ["debug_failed_run", "tree_explore"]:
        tf = resolve_task("req", mode, f"run-{mode}", TS)
        subset = tf["payload"]["agent_subset"]
        assert "variable-touch-guard" in subset, f"{mode} missing the ⛔ gate"
        # Remove it -> routing must now reject (the gate is structurally mandatory).
        tf["payload"]["agent_subset"] = [a for a in subset if a != "variable-touch-guard"]
        errors = validate_routing(tf)
        assert any("variable-touch-guard" in e and "hard gate" in e for e in errors), (
            f"{mode} did not enforce variable-touch-guard as a mandatory gate"
        )


# --------------------------------------------------------------------------- #
#  Cross-cluster data flows (registered path)                                 #
# --------------------------------------------------------------------------- #

def test_gap_breadth_wires_into_classify_and_novelty_via_registered_schemas():
    """A weakness item -> build_classification -> methodological_gap -> aggregate_novelty,
    validated through the REGISTERED schemas (validate_payload)."""
    weakness_item = {
        "gap_id": "G-1",
        "locus": "Section 4.2 of [[paper-smith2024]] uses a single train/test split",
        "opportunity": "a cross-validated protocol would expose variance the paper hides",
        "evidence_ref": ["[[paper-smith2024]]"],
    }
    gc = classify_gap.build_classification([weakness_item])
    assert gc["gaps"][0]["gap_type"] == "methodological_gap"
    assert gc["gaps"][0]["reason_code"] == "WEAK_LOCUS"
    assert validate_payload("gap_classification", gc) == []

    ns = novelty_aggregate.aggregate_novelty(gc["gaps"])
    assert len(ns["scores"]) == 1, "novelty must score every gap, dropping none"
    assert validate_payload("novelty_score", ns) == []


def test_ideate_ring_tournament_validates_via_registered_schema():
    """build_bracket -> a complete pairwise idea_tournament, validated through the registry."""
    ideas = [
        {"idea_id": "IDEA-1", "score": 0.9},
        {"idea_id": "IDEA-2", "score": 0.5},
        {"idea_id": "IDEA-3", "score": 0.7},
    ]
    out = tournament_bracket.build_bracket(ideas, evidence_ref=["hypothesis_set:hs-1"])
    assert len(out["matchups"]) == 3   # C(3,2)
    assert {r["rank"] for r in out["ranking"]} == {1, 2, 3}
    assert out["ranking"][0]["idea_id"] == "IDEA-1"   # highest score -> most wins -> rank 1
    assert validate_payload("idea_tournament", out) == []


# --------------------------------------------------------------------------- #
#  Adversarial-review fixes (paired proof tests)                              #
# --------------------------------------------------------------------------- #

def test_tournament_raises_on_duplicate_idea_id():
    """F-1 (HIGH): a duplicate idea_id must FAIL LOUD, not silently collapse an idea
    (the M3-a 'an identified item must never vanish' discipline)."""
    dupes = [
        {"idea_id": "IDEA-1", "score": 0.9},
        {"idea_id": "IDEA-1", "score": 0.5},   # same id -> would silently vanish + self-match
        {"idea_id": "IDEA-2", "score": 0.7},
    ]
    with pytest.raises(ValueError, match="duplicate idea_id"):
        tournament_bracket.build_bracket(dupes)


def test_tournament_raises_on_missing_idea_id():
    """F-2 (MEDIUM): an idea with no idea_id raises a clear error, not an opaque KeyError."""
    with pytest.raises(ValueError, match="idea_id"):
        tournament_bracket.build_bracket([{"score": 0.9}, {"idea_id": "IDEA-2", "score": 0.5}])


def test_review_config_accepts_the_adversarial_lens():
    """Seam (a) (HIGH): the venue panel's adversarial lens (the eval-leakage / unfair-baseline
    reviewer — the #1 venue reject driver) must be representable in review_config. Before the fix
    the lens enum was [methodology, domain] and an adversarial-lens config was schema-REJECTED,
    orphaning the hardest reviewer's pre-commitment anchor."""
    cfg = {
        "run_ref": "run-venue-1",
        "lenses": [
            {"lens": "methodology", "anchor": "soundness + reproducibility", "reviewer_agent": "venue-reviewer-persona"},
            {"lens": "domain", "anchor": "significance + clarity", "reviewer_agent": "venue-reviewer-persona"},
            {"lens": "adversarial", "anchor": "novelty + evaluation fairness; opens the eval code for leakage",
             "reviewer_agent": "venue-reviewer-persona"},
        ],
        "synthesis_mandate": "aggregate by argument, surface every unresolved reject-trigger, apply anti-bias suppressors",
    }
    assert validate_payload("review_config", cfg) == [], "an adversarial-lens config must validate"


def test_monitor_finds_cost_nested_under_resources():
    """de-F5 regression: an over-budget run must not hide its cost under resources.{cost,gpu_cost}
    (the monitor pins this branch so a refactor cannot silently stop watching that location)."""
    from research_agent_teams.tools import monitor_scan
    runs = [{"run_id": "r-hot", "status": "provisional", "resources": {"gpu_cost": 500.0}}]
    alerts = monitor_scan.scan_runs(runs, budget={"max_cost": 100.0})
    assert any(a["alert_type"] == "over_budget" and a["run_ref"] == "r-hot" for a in alerts), alerts


# --------------------------------------------------------------------------- #
#  M3-accept — complete-form smoke (the whole freedom layer threads end-to-end) #
# --------------------------------------------------------------------------- #

def test_complete_freedom_layer_smoke():
    """The M3-accept capstone: the whole freedom layer threads end-to-end through the REGISTERED
    schemas — DISCOVER gap-hunting breadth (all 4 hunters) -> 7-type classify -> score-only novelty
    (low retained, multi-signal ranks higher) -> IDEATE ring (tournament -> evolved). Proves the
    complete-form data path, not just isolated clusters. (The engine-level DISCOVER->IDEATE->REPORT
    drive is already proven by test_m3a_new_direction.py.)"""
    # 1. one item from each of the 4 breadth hunters (each item IS a classify_gap signal)
    breadth = [
        {"gap_id": "G-w", "locus": "[[p1]] uses a single split", "opportunity": "cross-validate it",
         "evidence_ref": ["[[p1]]"]},                                              # -> methodological_gap
        {"gap_id": "G-s", "region": "no work on 3D low-dose CT", "hole": True,
         "evidence_ref": ["[[landscape]]"]},                                       # -> coverage_gap
        {"gap_id": "G-t", "source_domain": "NLP retrieval", "target_hook": "slice indexing",
         "evidence_ref": ["[[p2]]"]},                                              # -> transfer_gap
        {"gap_id": "G-c", "challenged_assumption": "more data always helps",
         "evidence_ref": ["[[p3]]"]},                                             # -> assumption_gap
    ]
    gc = classify_gap.build_classification(breadth)
    types = {g["gap_id"]: g["gap_type"] for g in gc["gaps"]}
    assert types == {"G-w": "methodological_gap", "G-s": "coverage_gap",
                     "G-t": "transfer_gap", "G-c": "assumption_gap"}
    assert validate_payload("gap_classification", gc) == []

    # 2. novelty scores EVERY gap (score-only, none cut); a multi-signal gap outranks a single one
    ns = novelty_aggregate.aggregate_novelty(gc["gaps"])
    assert len(ns["scores"]) == 4, "score-only: every gap scored, none dropped"
    assert validate_payload("novelty_score", ns) == []
    multi = novelty_aggregate.aggregate_novelty([{
        "gap_id": "G-multi", "reason_code": "WEAK_LOCUS",
        "derived_from": ["weakness_opportunity", "white_space_present"],
        "evidence_ref": ["[[p1]]"]}])["scores"][0]
    single = next(s for s in ns["scores"] if s["gap_id"] == "G-w")
    assert multi["novelty"] > single["novelty"], "more corroborating signals -> higher novelty"

    # 3. IDEATE ring: tournament over candidate ideas -> a complete bracket; then an evolved variant
    ideas = [{"idea_id": "H-1", "score": 0.8}, {"idea_id": "H-2", "score": 0.6}, {"idea_id": "H-3", "score": 0.9}]
    tourney = tournament_bracket.build_bracket(ideas, evidence_ref=["hypothesis_set:hs-smoke"])
    assert tourney["ranking"][0]["idea_id"] == "H-3"   # highest score wins the bracket
    assert validate_payload("idea_tournament", tourney) == []
    evolved = {"ideas": [{
        "idea_id": "H-3b", "summary": "H-3 recombined with H-1's contrastive prior",
        "parent_ids": ["H-3", "H-1"], "evidence_ref": ["idea_tournament:smoke"],
        "mutation_type": "recombine"}]}
    assert validate_payload("evolved_ideas", evolved) == [], "evolved idea with provenance must validate"
