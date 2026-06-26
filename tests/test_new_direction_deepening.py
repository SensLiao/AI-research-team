"""RAT-2 Wave-3: new_direction REPORT-stage deepening — additive contract test.

Verifies that `new_direction` now emits all three REPORT-stage quality artifacts
(global-quality-scorecard, integrity-recommendation, idea-quality-eval) IN ADDITION
to its proven base (report-note + idea-backlog), while the governance contract is
completely unchanged:

  - The idea-backlog carries no self-bet field (top-level or per-idea).
  - integrity-recommendation has decision_authority == "director-human-gate".
  - idea-quality-eval per_idea covers the menu's idea_ids.
  - GRACEFUL path (deep workers NOT dispatched): depth == 0.0, breadth == 0.0 (base only).
  - DEEP-BY-DEFAULT path (deep SINGLE-DOMAIN panel dispatched): new_direction produces
    problem_abstraction / mechanism_graph / contradiction / experiment_sketch / idea_lineage and
    depth > 0, but NEVER a cross-domain mechanism_mapping (breadth == 0 — that breadth layer is
    deep_ideation's signature).

Pattern: offline operate harness (spine.begin + new_direction.run_dets), using the
clean worker-bundle fixtures imported from test_operate_deep_ideation — exactly the
same pattern used for deep_ideation in that test file.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from research_agent_teams.operate import spine
from research_agent_teams.operate.modes import new_direction
from research_agent_teams.tools.validate_artifact import validate_artifact
# Import the clean fixtures from the deep_ideation test (offline operate harness).
from research_agent_teams.tests.test_operate_deep_ideation import (
    COLLISION_BUNDLE,
    CONTRADICTION_BUNDLE,
    DISCOVER_BUNDLE,
    EXPERIMENT_BUNDLE,
    FORMALIZE_BUNDLE,
    IDEATE_BUNDLE,
    MECHANISM_BUNDLE,
)

TS = "2026-06-19T00:00:00Z"
REQ = "find a promptable 3D segmentation direction worth betting on"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _begin(tmp_path):
    runs = tmp_path / "runs"
    runs.mkdir(exist_ok=True)
    return spine.begin(str(runs), "nd-deep", REQ, "new_direction", TS)["run_dir"]


def _drop(rd, stem, payload):
    p = Path(rd) / "inbox" / f"{stem}.bundle.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(payload), encoding="utf-8")


def _payload(rd, stage, name):
    return json.loads(Path(rd, "evidence", stage, name).read_text(encoding="utf-8"))["payload"]


def _run_full(tmp_path):
    """Drive new_direction through DISCOVER -> IDEATE -> REPORT offline and return run_dir."""
    rd = _begin(tmp_path)
    # DISCOVER
    _drop(rd, "DISCOVER", DISCOVER_BUNDLE)
    new_direction.run_dets(rd, "DISCOVER", TS)
    # IDEATE (needs both IDEATE + COLLISION bundles)
    _drop(rd, "IDEATE", IDEATE_BUNDLE)
    _drop(rd, "COLLISION", COLLISION_BUNDLE)
    new_direction.run_dets(rd, "IDEATE", TS)
    # REPORT
    new_direction.run_dets(rd, "REPORT", TS)
    return rd


# ---------------------------------------------------------------------------
# 1. REPORT emits all required quality artifacts, each contract-valid
# ---------------------------------------------------------------------------

def test_report_emits_report_note(tmp_path):
    rd = _run_full(tmp_path)
    p = Path(rd) / "evidence" / "REPORT" / "report-note.artifact.json"
    assert p.exists(), "report-note.artifact.json must be written in REPORT"
    assert validate_artifact(json.loads(p.read_text(encoding="utf-8"))) == []


def test_report_emits_global_quality_scorecard(tmp_path):
    rd = _run_full(tmp_path)
    p = Path(rd) / "evidence" / "REPORT" / "global-quality-scorecard.artifact.json"
    assert p.exists(), "global-quality-scorecard.artifact.json must be written in REPORT"
    assert validate_artifact(json.loads(p.read_text(encoding="utf-8"))) == []


def test_report_emits_integrity_recommendation(tmp_path):
    rd = _run_full(tmp_path)
    p = Path(rd) / "evidence" / "REPORT" / "integrity-recommendation.artifact.json"
    assert p.exists(), "integrity-recommendation.artifact.json must be written in REPORT"
    assert validate_artifact(json.loads(p.read_text(encoding="utf-8"))) == []


def test_report_emits_idea_quality_eval(tmp_path):
    rd = _run_full(tmp_path)
    p = Path(rd) / "evidence" / "REPORT" / "idea-quality-eval.artifact.json"
    assert p.exists(), "idea-quality-eval.artifact.json must be written in REPORT"
    assert validate_artifact(json.loads(p.read_text(encoding="utf-8"))) == []


def test_all_report_stage_artifacts_are_contract_valid(tmp_path):
    """Belt-and-suspenders: every artifact written in the REPORT stage validates."""
    rd = _run_full(tmp_path)
    bad = []
    for p in sorted(Path(rd, "evidence", "REPORT").glob("*.artifact.json")):
        art = json.loads(p.read_text(encoding="utf-8"))
        errs = validate_artifact(art)
        if errs:
            bad.append((p.name, errs))
    assert bad == [], f"contract violations in REPORT artifacts: {bad}"


# ---------------------------------------------------------------------------
# 2. Proven base unchanged: idea-backlog still exists with ranked_ideas,
#    carries no self-bet field (top-level or per-idea)
# ---------------------------------------------------------------------------

def test_ideate_idea_backlog_still_exists(tmp_path):
    rd = _run_full(tmp_path)
    p = Path(rd) / "evidence" / "IDEATE" / "idea-backlog.artifact.json"
    assert p.exists(), "idea-backlog.artifact.json must still be written in IDEATE"


def test_idea_backlog_has_ranked_ideas(tmp_path):
    rd = _run_full(tmp_path)
    backlog = _payload(rd, "IDEATE", "idea-backlog.artifact.json")
    assert "ranked_ideas" in backlog, "idea-backlog must carry ranked_ideas"
    assert len(backlog["ranked_ideas"]) >= 1, "ranked_ideas must not be empty"


def test_idea_backlog_top_level_carries_no_self_bet_field(tmp_path):
    """The model must never inject a selection field at top level."""
    rd = _run_full(tmp_path)
    backlog = _payload(rd, "IDEATE", "idea-backlog.artifact.json")
    assert not (set(backlog) & {"selected", "chosen", "bet", "winner"}), (
        f"idea-backlog top-level must not contain self-bet fields, found: "
        f"{set(backlog) & {'selected', 'chosen', 'bet', 'winner'}}"
    )


def test_idea_backlog_per_idea_carries_no_self_bet_field(tmp_path):
    """No individual idea object may carry a selection field."""
    rd = _run_full(tmp_path)
    backlog = _payload(rd, "IDEATE", "idea-backlog.artifact.json")
    for idea in backlog["ranked_ideas"]:
        bad = set(idea) & {"selected", "chosen", "bet", "winner"}
        assert not bad, (
            f"idea {idea.get('idea_id')!r} in idea-backlog must not contain self-bet "
            f"fields, found: {bad}"
        )


# ---------------------------------------------------------------------------
# 3. integrity-recommendation has decision_authority == "director-human-gate"
# ---------------------------------------------------------------------------

def test_integrity_recommendation_decision_authority_is_director_human_gate(tmp_path):
    """The integrity recommender is advisory only; the director is always the decision authority."""
    rd = _run_full(tmp_path)
    rec = _payload(rd, "REPORT", "integrity-recommendation.artifact.json")
    assert rec.get("decision_authority") == "director-human-gate", (
        f"decision_authority must be 'director-human-gate', got {rec.get('decision_authority')!r}"
    )


# ---------------------------------------------------------------------------
# 4. idea-quality-eval per_idea covers the menu's idea_ids and each scores dict
#    has the 6 required dims; depth == 0.0 and breadth == 0.0 (no mechanism graph /
#    no mappings in new_direction)
# ---------------------------------------------------------------------------

def test_idea_quality_eval_per_idea_covers_menu_idea_ids(tmp_path):
    """Every idea in the /idea-bet menu appears in the quality eval."""
    rd = _run_full(tmp_path)
    backlog = _payload(rd, "IDEATE", "idea-backlog.artifact.json")
    menu_ids = {str(i["idea_id"]) for i in backlog["ranked_ideas"]}
    qe = _payload(rd, "REPORT", "idea-quality-eval.artifact.json")
    eval_ids = {str(pi["idea_id"]) for pi in qe["per_idea"]}
    assert menu_ids <= eval_ids, (
        f"idea-quality-eval must cover all menu idea_ids; missing: {menu_ids - eval_ids}"
    )


def test_idea_quality_eval_per_idea_has_6_required_score_dims(tmp_path):
    """Each per_idea entry must have all 6 required score dimensions."""
    REQUIRED_DIMS = {"depth", "breadth", "grounding", "refutation", "falsifiability", "novelty"}
    rd = _run_full(tmp_path)
    qe = _payload(rd, "REPORT", "idea-quality-eval.artifact.json")
    for pi in qe["per_idea"]:
        scores = pi.get("scores", {})
        missing = REQUIRED_DIMS - set(scores)
        assert not missing, (
            f"idea {pi.get('idea_id')!r} scores missing required dims: {missing}"
        )


def test_idea_quality_eval_depth_is_zero_for_new_direction(tmp_path):
    """GRACEFUL path (no deep worker bundles dispatched) -> no mechanism_graph -> depth 0.0.
    (Deep-by-default path has depth > 0 — see the deep-by-default tests below.)"""
    rd = _run_full(tmp_path)
    qe = _payload(rd, "REPORT", "idea-quality-eval.artifact.json")
    for pi in qe["per_idea"]:
        assert pi["scores"]["depth"] == 0.0, (
            f"idea {pi.get('idea_id')!r}: depth must be 0.0 in new_direction "
            f"(no mechanism graph), got {pi['scores']['depth']}"
        )


def test_idea_quality_eval_breadth_is_zero_for_new_direction(tmp_path):
    """new_direction produces no mechanism_mappings -> breadth must be 0.0 (honest shallower score)."""
    rd = _run_full(tmp_path)
    qe = _payload(rd, "REPORT", "idea-quality-eval.artifact.json")
    for pi in qe["per_idea"]:
        assert pi["scores"]["breadth"] == 0.0, (
            f"idea {pi.get('idea_id')!r}: breadth must be 0.0 in new_direction "
            f"(no mechanism mappings), got {pi['scores']['breadth']}"
        )


# ---------------------------------------------------------------------------
# 5. DEEP-BY-DEFAULT: when the deep SINGLE-DOMAIN panel IS dispatched, new_direction produces the
#    deep artifacts (problem_abstraction / mechanism_graph / contradiction / experiment_sketch /
#    idea_lineage) — but NEVER a cross-domain mechanism_mapping (that breadth layer is deep_ideation's
#    signature). depth > 0, breadth == 0.
# ---------------------------------------------------------------------------

def _run_full_deep(tmp_path):
    """Drive new_direction with its DEEP single-domain panel dispatched: formalize / mechanism /
    contradiction / experiment bundles present; NO analogy bundle (single-domain). Returns run_dir."""
    rd = _begin(tmp_path)
    _drop(rd, "DISCOVER", DISCOVER_BUNDLE)
    _drop(rd, "FORMALIZE", FORMALIZE_BUNDLE)
    _drop(rd, "MECHANISM", MECHANISM_BUNDLE)
    _drop(rd, "CONTRADICTION", CONTRADICTION_BUNDLE)
    new_direction.run_dets(rd, "DISCOVER", TS)
    _drop(rd, "IDEATE", IDEATE_BUNDLE)
    _drop(rd, "COLLISION", COLLISION_BUNDLE)
    _drop(rd, "EXPERIMENT", EXPERIMENT_BUNDLE)
    new_direction.run_dets(rd, "IDEATE", TS)
    new_direction.run_dets(rd, "REPORT", TS)
    return rd


def test_deep_by_default_produces_deep_discover_artifacts(tmp_path):
    rd = _run_full_deep(tmp_path)
    for name in ("problem-abstraction.artifact.json", "mechanism-graph.artifact.json",
                 "contradiction-report.artifact.json"):
        assert (Path(rd) / "evidence" / "DISCOVER" / name).exists(), f"deep DISCOVER missing {name}"


def test_deep_by_default_produces_experiment_sketches_and_lineage(tmp_path):
    rd = _run_full_deep(tmp_path)
    sketches = list(Path(rd, "evidence", "IDEATE").glob("experiment-sketch-*.artifact.json"))
    assert sketches, "deep new_direction must produce experiment sketches when EXPERIMENT bundle present"
    assert (Path(rd) / "evidence" / "IDEATE" / "idea-lineage.artifact.json").exists()


def test_deep_by_default_omits_cross_domain_mapping(tmp_path):
    """new_direction is deep SINGLE-DOMAIN: it must NEVER emit a mechanism_mapping (no analogy worker)."""
    rd = _run_full_deep(tmp_path)
    mappings = list(Path(rd, "evidence", "DISCOVER").glob("mechanism-mapping-*.artifact.json"))
    assert mappings == [], f"new_direction must omit cross-domain mappings, found: {mappings}"


def test_deep_by_default_depth_positive_breadth_zero(tmp_path):
    rd = _run_full_deep(tmp_path)
    qe = _payload(rd, "REPORT", "idea-quality-eval.artifact.json")
    assert all(pi["scores"]["depth"] > 0.0 for pi in qe["per_idea"]), "depth>0 once mechanism graph present"
    assert all(pi["scores"]["breadth"] == 0.0 for pi in qe["per_idea"]), "breadth 0 (single-domain)"


def test_deep_by_default_all_artifacts_valid(tmp_path):
    rd = _run_full_deep(tmp_path)
    bad = []
    for p in Path(rd, "evidence").rglob("*.artifact.json"):
        errs = validate_artifact(json.loads(p.read_text(encoding="utf-8")))
        if errs:
            bad.append((p.name, errs))
    assert bad == [], f"contract violations: {bad}"
