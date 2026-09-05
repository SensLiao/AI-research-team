"""W-team wave (2026-08-07): three new seats, four new overlay cards, a fourth standing fence,
and plateau stopping in the bounded repair loop.

What each group of tests is actually guarding:

* the three seat cards exist AND say the thing that makes them safe — the divergence runner must not
  propose or rank, must flag rather than delete an out-of-north-star candidate, and must read the
  hardware registry rather than recall a spec; the trajectory extractor must prefer omission over a
  fabricated dead end; the direction advisor must be an argument map, never a verdict;
* the four overlay cards are real guidance (not label lines) and are reachable through the router;
* the widened window is ONE number in three files (catalog / router ceiling / schema maxItems);
* the rebuttal fence is WIRED into a dispatched packet, not merely defined — the failure mode the
  previous fence round was about;
* plateau stopping is OPT-IN and strictly additive: without a quality signal the loop behaves exactly
  as before, and with one it can only stop EARLIER than the round cap, never later and never in a
  case the cap would not have stopped anyway.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from research_agent_teams.operate import bounded_repair, panel_scheduler
from research_agent_teams.operate.artifacts import GateBlock, TargetedGateBlock
from research_agent_teams.tools import research_capability_router as router

ROOT = Path(__file__).resolve().parents[2] / "research_agent_teams"
AGENTS_DIR = ROOT / "agents"
CATALOG = json.loads(router.DEFAULT_OVERLAY_CATALOG.read_text(encoding="utf-8"))
OVERLAYS_BY_ID = {o["overlay_id"]: o for o in CATALOG["overlays"]}

NEW_SEATS = {
    "divergence-operator-runner": ("opus", "IDEATE", "producer", "divergence_trace"),
    "research-trajectory-extractor": ("sonnet", "DISCOVER", "producer", "exploration_tree"),
    "direction-decision-advisor": ("opus", "REPORT", "advisory-recommender",
                                   "direction_recommendation"),
}

NEW_CARDS = (
    "creative_operator_ladder",
    "ai_research_failure_modes",
    "productive_disagreement_council",
    "innovation_cognitive_map",
)


def _card(path: Path) -> tuple[dict, str]:
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    assert lines and lines[0].strip() == "---", f"{path.name}: no frontmatter"
    end = next(i for i, line in enumerate(lines[1:], start=1) if line.strip() == "---")
    return yaml.safe_load("\n".join(lines[1:end])) or {}, "\n".join(lines[end + 1:])


# ------------------------------------------------------------------------------- the three new seats

@pytest.mark.parametrize("seat", sorted(NEW_SEATS))
def test_new_seat_frontmatter_matches_the_agreed_contract(seat):
    model, stage, kind, produces = NEW_SEATS[seat]
    fm, body = _card(AGENTS_DIR / f"{seat}.md")
    assert fm["name"] == seat, "frontmatter name must equal the filename (roster/graph key)"
    assert fm["model"] == model
    assert fm["stage"] == stage
    assert fm["kind"] == kind
    # The produces name is the interface with the artifact schemas; a typo here is a silent no-op.
    assert fm["produces"] == produces
    assert "Bash" not in [str(t) for t in (fm.get("tools") or [])]
    assert "North-star discipline" in body, "every seat carries the north-star block"


def test_divergence_runner_refuses_to_propose_rank_or_self_censor():
    """This seat exists to WIDEN the space before the proposer runs. Three ways it could quietly

    defeat its own purpose: proposing (then it is just a second proposer), ranking (then it
    pre-decides the menu before the director sees it), and deleting an out-of-scope candidate
    (then the most interesting operator output is the one that never leaves the run).
    """
    _, body = _card(AGENTS_DIR / "divergence-operator-runner.md")
    lowered = body.lower()
    for operator in ("constraint classification", "assumption negation", "problem reformulation",
                     "mechanism cross-product", "enabler window", "tension synthesis"):
        assert operator in lowered, f"six-operator ladder is missing {operator!r}"
    assert "out_of_north_star" in body, "the flag-do-not-delete rule must be named"
    must_not = lowered.split("you must not", 1)[-1]
    assert "propose ideas" in must_not and "rank" in must_not


def test_divergence_runner_reads_hardware_and_never_invents_it():
    _, body = _card(AGENTS_DIR / "divergence-operator-runner.md")
    assert "resources/resource_registry.yaml" in body, "the real registry must be named, not implied"
    assert "unknown" in body.lower(), "an unreadable spec must have somewhere honest to go"
    assert "never invent a specification" in body.lower()
    # Hardware is an enabler and a signal — never a reason to down-rank an idea (director lock).
    assert "down-rank" in body.lower() or "down rank" in body.lower()


def test_trajectory_extractor_prefers_omission_over_a_fabricated_dead_end():
    _, body = _card(AGENTS_DIR / "research-trajectory-extractor.md")
    lowered = body.lower()
    for node_type in ("dead_end", "decision", "pivot", "support_level"):
        assert node_type in body, f"exploration tree node contract missing {node_type!r}"
    assert "prefer omission over fabricating" in lowered
    assert "explicit" in lowered and "inferred" in lowered


def test_direction_advisor_is_an_argument_map_not_a_verdict():
    fm, body = _card(AGENTS_DIR / "direction-decision-advisor.md")
    lowered = body.lower()
    for option in ("DEEPEN", "BROADEN", "PIVOT", "CONCLUDE"):
        assert option in body, f"the four-option menu is missing {option}"
    assert "argument map, not a verdict" in lowered
    assert "decision_authority" in body and "director-human-gate" in body
    # Same posture as integrity-refusal-recommender: advisory worker, NOT a human-only gate.
    assert fm.get("disable-model-invocation") is None
    assert "supporting_evidence" in body and "opposing_evidence" in body
    assert "trigger_criteria" in body
    # A score must never be enough to recommend abandoning a line of work.
    assert "novelty" in lowered and "evidenced" in lowered


def test_direction_advisor_matches_the_existing_advisory_recommender_posture():
    """Whatever the existing advisory seat promises, this one must promise too."""
    _, existing = _card(AGENTS_DIR / "integrity-refusal-recommender.md")
    _, new = _card(AGENTS_DIR / "direction-decision-advisor.md")
    for promise in ("NEVER self-authorizes", "decision_authority", "/idea-bet", "/promote-to-vault"):
        assert promise in existing, f"baseline card changed shape: {promise!r} is gone"
        assert promise in new, f"direction-decision-advisor drops the advisory promise {promise!r}"


# --------------------------------------------------------------------------- the four overlay cards

@pytest.mark.parametrize("overlay_id", NEW_CARDS)
def test_new_overlay_card_is_real_guidance(overlay_id):
    card = OVERLAYS_BY_ID.get(overlay_id)
    assert card, f"overlay {overlay_id} is missing from the catalog"
    # A card is guidance a worker can act on, not a label. (Same floor the family cards use.)
    assert len(card["summary"]) >= 400, f"{overlay_id} summary is too thin to be guidance"
    assert card["stages"] and card["modes"] and card["provenance_refs"] and card["non_goals"]
    assert card["allowed_use"].startswith("internal_")


def test_creative_operator_ladder_carries_all_six_operators_and_the_flag_rule():
    summary = OVERLAYS_BY_ID["creative_operator_ladder"]["summary"].lower()
    for operator in ("constraint classification", "assumption negation", "problem reformulation",
                     "mechanism cross-product", "enabler window", "tension synthesis"):
        assert operator in summary
    card = OVERLAYS_BY_ID["creative_operator_ladder"]
    assert card["priority"] == 99
    assert card["stages"] == ["IDEATE"]
    # Director lock: the escape-hatch non-goal is the FLAG rule, never a self-censorship rule.
    assert "hide_an_out_of_scope_candidate_instead_of_flagging_it" in card["non_goals"]
    assert "let_a_reformulation_escape_the_north_star_scope" not in card["non_goals"]


def test_failure_modes_card_has_seven_modes_and_a_three_way_verdict():
    card = OVERLAYS_BY_ID["ai_research_failure_modes"]
    summary = card["summary"]
    assert all(marker in summary for marker in ("(1)", "(2)", "(3)", "(4)", "(5)", "(6)", "(7)"))
    for verdict in ("CLEAR", "SUSPECTED", "INSUFFICIENT"):
        assert verdict in summary, f"three-way verdict missing {verdict}"
    assert "never silently skip" in summary.lower()
    # Advisory, never a block (director lock: no new hard gates this wave).
    assert "block_a_run_on_a_suspicion" in card["non_goals"]
    assert set(card["stages"]) == {"ANALYZE", "VERIFY", "REPORT"}


def test_disagreement_card_forbids_both_manufactured_dissent_and_averaging():
    card = OVERLAYS_BY_ID["productive_disagreement_council"]
    summary = card["summary"].lower()
    assert "specialize" in summary and "blind spot" in summary
    assert "core tension" in summary
    assert "manufacture_disagreement_to_look_rigorous" in card["non_goals"]
    assert "average_the_panel_into_a_consensus" in card["non_goals"]


def test_innovation_map_card_carries_the_six_layers_depth_ladder_and_red_flags():
    card = OVERLAYS_BY_ID["innovation_cognitive_map"]
    summary = card["summary"]
    assert card["priority"] == 98
    assert set(card["stages"]) == {"IDEATE", "VERIFY"}
    for layer in ("PROBLEM SPACE", "LEARNING MACHINE", "CAPABILITY-GROWTH ENGINE",
                  "MODEL-WORLD CONNECTION", "TRUTH AND CONTROL", "RESEARCH COMPOUNDING"):
        assert layer in summary, f"six-layer map is missing {layer!r}"
    for rung in ("D0", "D1", "D2", "D3", "D4", "D5", "D6"):
        assert rung in summary, f"depth ladder is missing {rung}"
    assert "innovation_layers" in summary and "conventional_base" in summary
    assert "unusual_connection" in summary and "depth_target" in summary
    # Hardware is an enabler and a signal, never a ranking penalty (director lock 2026-08-07).
    assert "rank_down_an_idea_for_exceeding_current_hardware" in card["non_goals"]
    # The card is the director's own synthesis; the vendored refs must not be passed off as its origin.
    assert "innovation-cognitive-map.md" in summary
    assert "not the origin" in summary


def test_the_new_cards_are_reachable_through_the_router():
    """A card in the catalog that the router never selects is a card nobody ever reads."""
    route = router.route_research_capabilities("深度找方向，帮我想几个有创新的研究方向")
    ids = {o["overlay_id"] for o in route["capability_overlays"]}
    assert {"creative_operator_ladder", "innovation_cognitive_map"} <= ids
    assert route["safety"]["external_execution"] is False


def test_the_catalog_still_loads_with_the_four_new_cards():
    catalog = router.load_overlay_catalog()
    assert len(catalog["overlays"]) >= 25
    assert catalog["policy"]["selection_max"] == 28


# ------------------------------------------------------------------ C4: the fourth standing fence

def test_rebuttal_fence_scores_rather_than_stonewalls():
    fence = panel_scheduler._REBUTTAL_DISCIPLINE_FENCE
    lowered = fence.lower()
    assert "rebuttal discipline" in lowered
    # It must be a SCORING rubric: a 5/5 rebuttal still withdraws the finding.
    assert "withdraw the finding" in lowered, "a good rebuttal must still be able to win"
    assert "hold" in lowered, "a bad rebuttal must be resistible"
    assert "pressure is not evidence" in lowered
    assert "more than half your findings" in lowered


def test_rebuttal_fence_actually_reaches_a_dispatched_packet(tmp_path):
    """Wired, not merely defined — the same failure mode the earlier fence round was about."""
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "task_frame.artifact.json").write_text(
        json.dumps({"payload": {"mode": "new_direction"}}), encoding="utf-8")
    node = {"id": "w1", "label": "lit-scout",
            "worker": {"prompt": "BASE PROMPT", "output": str(run_dir / "x.json")},
            "output_rel": "x.json", "barrier_deps": set(), "data_deps": set(),
            "external_deps": set(), "allowed_inputs": [], "forbidden_inputs": [],
            "read_scope_declared": False}
    worker = panel_scheduler._worker_for_dispatch(
        run_dir, "DISCOVER", node, {"w1": node}, cycle=0, feedback=None, authorized=True)
    marker = panel_scheduler._REBUTTAL_DISCIPLINE_FENCE.strip().splitlines()[0]
    assert marker in worker["prompt"], "_REBUTTAL_DISCIPLINE_FENCE never reaches the worker"
    # ...and it is unconditional, exactly like the other three.
    for attr in ("_OUTPUT_SHAPE_FENCE", "_ASSISTANT_FANOUT_GRANT", "_RETRIEVAL_HONESTY_FENCE"):
        assert getattr(panel_scheduler, attr).strip().splitlines()[0] in worker["prompt"]


# -------------------------------------------- A5: the unreceipted-output halt is now a diagnostic

def _scheduler_run(tmp_path: Path, mode: str = "full_rigor_minimal") -> Path:
    run_dir = tmp_path / "run"
    (run_dir / "inbox").mkdir(parents=True)
    (run_dir / "task_frame.artifact.json").write_text(json.dumps({"payload": {
        "mode": mode,
        "budget": {"max_agent_hops": 8},
        "agent_subset": ["baseline-fairness-critic", "protocol-critic", "design-synthesizer",
                         "script-author"],
    }}), encoding="utf-8")
    return run_dir


def test_a_prewritten_output_no_longer_halts_the_stage(tmp_path):
    """De-governance (director 2026-08-07): an output with no in-run authorization receipt is
    REPORTED, not halted on. The halt used to be `unverified_unreceipted_outputs`."""
    run_dir = _scheduler_run(tmp_path)
    worker = {"label": "baseline-fairness-critic", "model": "opus", "prompt": "work",
              "output": str(run_dir / "inbox" / "prewritten.bundle.json")}
    Path(worker["output"]).write_text(json.dumps({"ok": True}), encoding="utf-8")
    decision = panel_scheduler.schedule_next_wave(run_dir, "DESIGN", worker, ts=TS)
    assert decision["status"] == "complete", "the unreceipted-output halt is back"
    # ...and the diagnostic survives, or the director loses the signal entirely.
    assert decision["unreceipted_agents"] == ["baseline-fairness-critic"]


def test_the_no_spec_branch_reports_missing_receipts_without_halting(tmp_path):
    run_dir = _scheduler_run(tmp_path, mode="venue_readiness")
    payload = json.loads((run_dir / "task_frame.artifact.json").read_text(encoding="utf-8"))
    payload["payload"]["agent_subset"] = ["venue-selector", "venue-review-configurator",
                                          "area-chair-synthesizer"]
    (run_dir / "task_frame.artifact.json").write_text(json.dumps(payload), encoding="utf-8")
    decision = panel_scheduler.schedule_next_wave(run_dir, "VERIFY", None, ts=TS)
    assert decision["status"] == "complete"
    assert "area-chair-synthesizer" in decision["unreceipted_agents"]
    # The pure counters stay — they feed the hop budget and the director packet, not a gate.
    assert {"authorized_agent_hops", "authorized_initial_hops",
            "authorized_supplement_hops"} <= set(decision)


def test_the_halt_status_is_gone_from_the_scheduler_source():
    """A status string left behind in one branch is how a removed gate quietly comes back."""
    source = (ROOT / "operate" / "panel_scheduler.py").read_text(encoding="utf-8")
    assert "unverified_unreceipted_outputs" not in source


# --------------------------------------------------------------------- C5: plateau stopping (opt-in)

TS = "2026-08-07T12:00:00Z"
BUDGET = {"max_agent_hops": 6, "max_debug_retries_per_run": 9}


class _AlwaysBlocks:
    def __init__(self, defects=None):
        self.defects = defects if defects is not None else [{
            "defect_id": "D-source", "location": "DISCOVER/evidence-table",
            "summary": "refresh the missing strong source", "target_agents": ["lit-scout"],
        }]

    def __call__(self):
        raise TargetedGateBlock("evidence gate: missing strong source", self.defects)


def test_without_a_quality_signal_nothing_changes(tmp_path):
    """Back-compat is the whole point: no signal -> the round cap is still the only stop."""
    dets = _AlwaysBlocks()
    budget = {"max_agent_hops": 6, "max_debug_retries_per_run": 3}
    for _ in range(3):
        assert bounded_repair.attempt_with_repair(tmp_path, "DISCOVER", budget, TS, dets)[0] == "retry"
    with pytest.raises(GateBlock) as ei:
        bounded_repair.attempt_with_repair(tmp_path, "DISCOVER", budget, TS, dets)
    assert "missing strong source" in str(ei.value)               # ORIGINAL reason, no wrapper
    assert bounded_repair.last_stop(tmp_path)["stop_reason"] == "round_cap"


def test_a_flat_quality_curve_stops_before_the_cap(tmp_path):
    """Three sub-threshold rounds under a cap of 9 — the loop must not spend the other six."""
    dets = _AlwaysBlocks()
    scores = iter([0.40, 0.41, 0.415, 0.417])
    quality_fn = lambda: next(scores)                              # noqa: E731 - test-local stub
    assert bounded_repair.attempt_with_repair(
        tmp_path, "DISCOVER", BUDGET, TS, dets, quality_fn=quality_fn)[0] == "retry"
    assert bounded_repair.attempt_with_repair(
        tmp_path, "DISCOVER", BUDGET, TS, dets, quality_fn=quality_fn)[0] == "retry"
    with pytest.raises(GateBlock) as ei:                           # 3rd score -> two flat deltas
        bounded_repair.attempt_with_repair(
            tmp_path, "DISCOVER", BUDGET, TS, dets, quality_fn=quality_fn)
    assert "missing strong source" in str(ei.value)                # still the ORIGINAL gate reason
    assert bounded_repair.failures_for_stage(tmp_path, "DISCOVER") == 3   # not 9
    stop = bounded_repair.last_stop(tmp_path)
    assert stop["stop_reason"] in {"plateau", "missing_evidence", "specialist_conflict"}
    assert getattr(ei.value, "stop_reason") == stop["stop_reason"]


def test_real_improvement_is_never_stopped(tmp_path):
    """The dial must not fire on a run that IS getting better — that would be a new block."""
    dets = _AlwaysBlocks()
    scores = iter([0.30, 0.50, 0.70, 0.90])
    quality_fn = lambda: next(scores)                              # noqa: E731 - test-local stub
    for _ in range(4):
        assert bounded_repair.attempt_with_repair(
            tmp_path, "DISCOVER", BUDGET, TS, dets, quality_fn=quality_fn)[0] == "retry"
    assert bounded_repair.last_stop(tmp_path) is None


def test_a_caller_supplied_series_is_used_verbatim(tmp_path):
    """`quality_scores` overrides the persisted series, so a caller that already tracks quality
    does not have to hand over a scorer — a flat series stops on the very first call."""
    dets = _AlwaysBlocks()
    with pytest.raises(GateBlock):
        bounded_repair.attempt_with_repair(
            tmp_path, "DISCOVER", BUDGET, TS, dets, quality_scores=[0.80, 0.81, 0.815])
    stop = bounded_repair.last_stop(tmp_path)
    assert stop["stop_reason"] in bounded_repair.STOP_REASONS
    assert stop["state_summary"]["quality_series"] == [0.8, 0.81, 0.815]
    # A rising caller-supplied series must NOT stop.
    assert bounded_repair.attempt_with_repair(
        tmp_path, "IDEATE", BUDGET, TS, dets, quality_scores=[0.2, 0.5, 0.9])[0] == "retry"


def test_a_dropping_curve_counts_as_a_plateau(tmp_path):
    """Rounds that make the bundle WORSE have not bought anything either."""
    assert bounded_repair._is_plateau([0.9, 0.7, 0.5], bounded_repair.DEFAULT_PLATEAU_DELTA)
    assert not bounded_repair._is_plateau([0.3, 0.5], bounded_repair.DEFAULT_PLATEAU_DELTA)
    assert not bounded_repair._is_plateau([0.3, 0.5, 0.7], bounded_repair.DEFAULT_PLATEAU_DELTA)


def test_a_recurring_multi_seat_defect_is_labelled_a_specialist_conflict(tmp_path):
    dets = _AlwaysBlocks([{
        "defect_id": "D-claim", "location": "ANALYZE/claims", "summary": "two seats disagree",
        "target_agents": ["result-analyzer", "scientific-critic"],
    }])
    scores = iter([0.60, 0.60, 0.60])
    quality_fn = lambda: next(scores)                              # noqa: E731 - test-local stub
    for _ in range(2):
        bounded_repair.attempt_with_repair(
            tmp_path, "ANALYZE", BUDGET, TS, dets, quality_fn=quality_fn)
    with pytest.raises(GateBlock):
        bounded_repair.attempt_with_repair(
            tmp_path, "ANALYZE", BUDGET, TS, dets, quality_fn=quality_fn)
    assert bounded_repair.last_stop(tmp_path)["stop_reason"] == "specialist_conflict"


def test_the_stop_receipt_answers_the_four_director_questions(tmp_path):
    dets = _AlwaysBlocks()
    scores = iter([0.5, 0.5, 0.5])
    quality_fn = lambda: next(scores)                              # noqa: E731 - test-local stub
    for _ in range(2):
        bounded_repair.attempt_with_repair(
            tmp_path, "DISCOVER", BUDGET, TS, dets, quality_fn=quality_fn)
    with pytest.raises(GateBlock):
        bounded_repair.attempt_with_repair(
            tmp_path, "DISCOVER", BUDGET, TS, dets, quality_fn=quality_fn)
    summary = bounded_repair.last_stop(tmp_path)["state_summary"]
    assert summary["current_state"] and summary["open_problems"]
    assert summary["why_stopped"] in bounded_repair.STOP_REASONS
    assert summary["recommended_next_step"]
    assert summary["quality_series"] == [0.5, 0.5, 0.5]
    assert "smoother prose" in summary["honesty_note"]


def test_a_broken_scorer_is_recorded_not_swallowed_and_never_crashes_the_loop(tmp_path):
    def explode():
        raise RuntimeError("scorer is broken")

    out = bounded_repair.attempt_with_repair(
        tmp_path, "DISCOVER", BUDGET, TS, _AlwaysBlocks(), quality_fn=explode)
    assert out[0] == "retry", "a broken caller callback must not turn a repairable gate into a crash"
    attempt = bounded_repair.load_state(tmp_path)["attempts"][-1]
    assert "scorer is broken" in attempt["quality_error"]
    assert "quality" not in attempt


def test_terminal_blocks_still_bypass_the_loop_entirely(tmp_path):
    """Plateau logic must not have given a terminal refusal a retry path."""
    def hard_block():
        raise TargetedGateBlock("terminal collision", [], verdict="BLOCK")

    with pytest.raises(TargetedGateBlock, match="terminal collision"):
        bounded_repair.attempt_with_repair(
            tmp_path, "DISCOVER", BUDGET, TS, hard_block, quality_fn=lambda: 0.5)
    assert bounded_repair.load_state(tmp_path)["attempts"] == []
    assert bounded_repair.last_stop(tmp_path) is None
