"""Invention-first ideation contract (director lock 2026-08-07).

The rule these tests pin: **ideation must be allowed to invent.** Feasibility, cost, schedule and
today's hardware belong to the experiment-design stage; when they leak upstream into ideation the menu
fills with audits and measurements, because those are always cheaper than a new mechanism.

Four separate mechanisms enforce that, and each is tested here rather than assumed:

* the packets ask for invention and record what kind of contribution each idea is
  (`contribution_tier` / `invention_claim`) plus which research coordinate it rewrites;
* the deterministic ranker WAIVES the feasibility signal for an invention tier, and records the waiver;
* the quality harness scores `mechanism_invention` per idea, so a re-labelling and a new mechanism no
  longer tie on every dimension;
* saturation is MEASURED from recorded retrieval rounds instead of self-declared, and reports rather
  than blocks.

Also pinned: the two advisory artifacts (`divergence_trace`, `direction_recommendation`) degrade to
absent instead of to invented content.
"""
from __future__ import annotations

import json
from pathlib import Path

from research_agent_teams.operate.modes import _ideation_prompts, _shared, new_direction
from research_agent_teams.tools import idea_bet_markdown as idea_bet_md
from research_agent_teams.tools.idea_quality_eval import build_quality_eval
from research_agent_teams.tools.scientific_investment_score import rank_scientific_investments
from research_agent_teams.tools.validate_artifact import validate_payload

from .test_operate_deep_ideation import TS, _begin


# --------------------------------------------------------------------------- packets

def _proposer_packet(run_dir: str = "RD") -> str:
    return _ideation_prompts.PROPOSER_WORKER_PROMPT.format(
        request="find a direction", run_dir=run_dir, out="OUT", vault="V", north_star="NS",
        divergence_operators=_ideation_prompts.DIVERGENCE_OPERATOR_BLOCK,
        divergence_trace=_ideation_prompts.DIVERGENCE_TRACE_JSON)


def test_proposer_packet_does_not_bound_an_idea_by_cost_or_schedule():
    packet = _proposer_packet()
    assert "runnable next quarter" not in packet, (
        "the old sentence forbade research programmes outright — the exact leak this lock removes")
    assert "scope, cost and schedule are the experiment-design stage's job" in packet


def test_proposer_packet_requires_an_invention_quota_with_a_stateable_claim():
    packet = _proposer_packet()
    assert "contribution_tier" in packet and "invention_claim" in packet
    assert "at least SIX ideas must carry" in packet
    # graded on upside, explicitly NOT on cost
    assert "cost, schedule and current" in packet


def test_proposer_packet_runs_divergence_operators_before_proposing():
    packet = _proposer_packet()
    for operator in ("CONSTRAINT CLASSIFICATION", "ASSUMPTION NEGATION", "PROBLEM REFORMULATION",
                     "MECHANISM CROSS-PRODUCT", "ENABLER WINDOW", "TENSION SYNTHESIS"):
        assert operator in packet, f"divergence operator {operator} missing from the proposer packet"
    assert "divergence_trace" in packet and "origin_operator" in packet
    # anomaly-first: the packet must forbid starting from "what method could I apply"
    assert "START FROM THE ANOMALY" in packet


def test_proposer_packet_carries_the_innovation_coordinates_and_depth_ladder():
    packet = _proposer_packet()
    assert "innovation_layers" in packet and "depth_target" in packet
    assert "conventional_base" in packet and "unusual_connection" in packet
    assert "at least THREE different innovation_layers" in packet


def test_proposer_packet_treats_hardware_as_information_not_a_filter():
    packet = _proposer_packet()
    assert "resource_envelope" in packet
    assert "research_agent_teams/resources/" in packet
    assert "exceeds_current_hardware" in packet
    assert "NOT A FILTER" in packet
    assert "never invent a spec" in packet.lower() or "never invent a spec" in packet


def test_ranker_packet_can_kill_but_never_on_a_novelty_score():
    packet = _ideation_prompts.RANKER_WORKER_PROMPT.format(
        request="r", run_dir="RD", out="OUT", north_star="NS")
    for reason in ("not_yet_clear", "no_one_suffers", "complexity_unjustified", "no_beneficiary"):
        assert reason in packet
    assert "a novelty score never kills an idea" in packet
    assert "killed" in packet and "kill_reason" in packet


def test_ranker_packet_lists_all_ten_pseudo_innovation_red_flags():
    packet = _ideation_prompts.RANKER_WORKER_PROMPT.format(
        request="r", run_dir="RD", out="OUT", north_star="NS")
    for flag in ("acronym_innovation", "benchmark_painting", "demo_as_evidence",
                 "architecture_superstition", "scaling_without_a_law", "agent_role_play",
                 "mechanism_storytelling", "synthetic_data_circularity",
                 "open_weights_not_open_science", "safety_by_refusal_rate"):
        assert flag in packet, f"red flag {flag} missing"
    assert "A flag is a signal to the director, not a cut." in packet


def test_ranker_packet_never_lets_expense_decide_a_pairing():
    packet = _ideation_prompts.RANKER_WORKER_PROMPT.format(
        request="r", run_dir="RD", out="OUT", north_star="NS")
    assert "must never lose a pairing because it" in packet
    assert "You may evolve at most two proposals" not in packet, "the evolution cap must be gone"
    assert "FLOOR-only operation" in packet


def test_north_star_block_states_that_in_scope_is_a_topic_not_a_solution_menu(tmp_path):
    block = _shared.north_star_block(_begin(tmp_path))
    assert "TOPIC boundary" in block
    assert "NOT a solution menu" in block
    assert "Proposing a solution the north star did not anticipate is the point of the run" in block


# --------------------------------------------------------------------------- feasibility waiver

def _ideas_with_tiers() -> list[dict]:
    return [
        {"idea_id": "INV-1", "rank": 1, "summary": "new mechanism",
         "evidence_ref": ["GAP-1"], "feasibility": {"score": 0.05},
         "contribution_tier": "mechanism_invention"},
        {"idea_id": "AUD-1", "rank": 2, "summary": "cheap audit",
         "evidence_ref": ["GAP-2"], "feasibility": {"score": 1.0},
         "contribution_tier": "audit"},
    ]


def _assessments(score: int) -> list[dict]:
    return [
        {"idea_id": iid, "strongest_rejection_case": "it may not work",
         "dimension_scores": {"importance": score, "mechanism_coherence": score,
                              "novelty_exposure": score, "falsifiability": score,
                              "information_gain": score, "downstream_leverage": score}}
        for iid in ("INV-1", "AUD-1")
    ]


def test_invention_tier_feasibility_is_waived_and_the_waiver_is_recorded():
    ranked = rank_scientific_investments(_ideas_with_tiers(), assessments=_assessments(4))
    by_id = {row["idea_id"]: row["scientific_investment"] for row in ranked}
    assert by_id["INV-1"]["feasibility_waived"] is True
    assert by_id["AUD-1"]["feasibility_waived"] is False
    # waived == the idea's own scientific merit, so logistics can neither reward nor punish it
    assert by_id["INV-1"]["feasibility"] == by_id["INV-1"]["scientific_merit"]
    # the audit tier keeps the ordinary signal
    assert by_id["AUD-1"]["feasibility"] == 1.0


def test_the_waiver_removes_the_cost_penalty_it_does_not_grant_a_cost_bonus():
    """What the waiver is, precisely — and what it deliberately is not.

    A 0.05-feasibility invention used to carry a real drag against a 1.0-feasibility audit
    (0.10 weight x 0.95 gap = 0.095 of composite). The waiver replaces the invention's logistics
    score with its own scientific merit, which removes that drag. It does NOT strip the ordinary
    feasibility signal from measurement/audit ideas, so at *identical* merit a perfectly feasible
    audit still edges an invention by the residual 0.10 x (1.0 - merit). That residual is the design:
    the lock is "never penalised for cost", not "cost is abolished".
    """
    ideas = _ideas_with_tiers()
    waived = rank_scientific_investments(ideas, assessments=_assessments(4))
    waived_by = {row["idea_id"]: row["scientific_investment"]["score"] for row in waived}

    unwaived_ideas = [dict(row) for row in ideas]
    for row in unwaived_ideas:                       # same ideas, tier stripped -> no waiver
        row.pop("contribution_tier", None)
    unwaived = rank_scientific_investments(unwaived_ideas, assessments=_assessments(4))
    unwaived_by = {row["idea_id"]: row["scientific_investment"]["score"] for row in unwaived}

    assert waived_by["INV-1"] > unwaived_by["INV-1"], "the waiver must lift the invention"
    assert waived_by["AUD-1"] == unwaived_by["AUD-1"], "it must not touch the audit tier"
    gap_before = unwaived_by["AUD-1"] - unwaived_by["INV-1"]
    gap_after = waived_by["AUD-1"] - waived_by["INV-1"]
    assert 0 < gap_after < gap_before, (
        f"the cost drag must shrink, not invert: {gap_before} -> {gap_after}")


def test_the_waiver_never_rescues_a_weak_invention():
    """The waiver removes a cost penalty; it does not invent merit."""
    ideas = _ideas_with_tiers()
    ranked = rank_scientific_investments(
        ideas,
        assessments=[
            {"idea_id": "INV-1", "strongest_rejection_case": "thin",
             "dimension_scores": {k: 1 for k in ("importance", "mechanism_coherence",
                                                 "novelty_exposure", "falsifiability",
                                                 "information_gain", "downstream_leverage")}},
            {"idea_id": "AUD-1", "strongest_rejection_case": "narrow",
             "dimension_scores": {k: 5 for k in ("importance", "mechanism_coherence",
                                                 "novelty_exposure", "falsifiability",
                                                 "information_gain", "downstream_leverage")}},
        ])
    assert [row["idea_id"] for row in ranked][0] == "AUD-1"


def test_backlog_projection_carries_the_invention_block():
    projected = new_direction._backlog_candidate({
        "idea_id": "IDEA-1", "summary": "s", "evidence_ref": ["GAP-1"],
        "feasibility": {"compute": "high"},
        "contribution_tier": "mechanism_invention", "invention_claim": "a new gating loss",
        "mechanism_graph_refs": ["N1"], "innovation_layers": ["mechanism"],
        "resource_envelope": "exceeds_current_hardware",
        "some_worker_prose": "must be dropped",
    })
    assert projected["contribution_tier"] == "mechanism_invention"
    assert projected["invention_claim"] == "a new gating loss"
    assert projected["resource_envelope"] == "exceeds_current_hardware"
    assert "some_worker_prose" not in projected


# --------------------------------------------------------------------------- measured saturation

def test_saturation_is_false_without_recorded_rounds():
    assert new_direction._measured_saturation({}) is False
    assert new_direction._measured_saturation({"saturation_rounds": []}) is False


def test_one_retrieval_round_can_never_be_saturated():
    bundle = {"saturation_rounds": [
        {"round_index": 1, "queries_run": 4, "new_unique_sources": 9,
         "cumulative_unique_sources": 9},
    ]}
    assert new_direction._measured_saturation(bundle) is False


def test_a_genuinely_flat_search_history_measures_as_saturated():
    """The meter needs the last TWO rounds each at/below the 10% marginal-yield threshold.

    Round 1 always has a marginal rate of 1.0 (everything is new), so two rounds can never satisfy
    that window — a third, still-flat pass is what SATURATED actually costs.
    """
    bundle = {"saturation_rounds": [
        {"round_index": 1, "queries_run": 4, "new_unique_sources": 20,
         "cumulative_unique_sources": 20},
        {"round_index": 2, "queries_run": 4, "new_unique_sources": 1,
         "cumulative_unique_sources": 21},
        {"round_index": 3, "queries_run": 4, "new_unique_sources": 0,
         "cumulative_unique_sources": 21},
    ]}
    assert new_direction._measured_saturation(bundle) is True


def test_a_still_productive_search_does_not_measure_as_saturated():
    bundle = {"saturation_rounds": [
        {"round_index": 1, "queries_run": 4, "new_unique_sources": 20,
         "cumulative_unique_sources": 20},
        {"round_index": 2, "queries_run": 4, "new_unique_sources": 18,
         "cumulative_unique_sources": 38},
    ]}
    assert new_direction._measured_saturation(bundle) is False


def test_a_malformed_round_history_degrades_to_false_not_to_a_crash():
    assert new_direction._measured_saturation({"saturation_rounds": ["not a round"]}) is False


# --------------------------------------------------------------------------- advisory artifacts

_TRACE = {
    "trace_id": "DT-001",
    "divergence_trace": {
        "constraints": [{"constraint": "labels must be dense", "class": "soft",
                         "if_dropped": "a sparse-supervision variant", "out_of_north_star": False}],
        "negations": [{"assumption": "the encoder must be frozen",
                       "negated_system": "co-adapt encoder and adapter under a budget",
                       "verdict": "unexplored_coherent"}],
        "reformulations": [], "cross_product": [], "enablers": [], "tensions": [],
    },
    "operators_run": ["constraint", "negation", "reformulation", "cross_product", "enabler",
                      "tension"],
}


def _write(run_dir: str, name: str, payload: dict) -> None:
    path = Path(run_dir) / "inbox" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_divergence_trace_is_absent_rather_than_invented(tmp_path):
    run_dir = _begin(tmp_path)
    assert new_direction._produce_divergence_trace(run_dir, TS, {}) is None


def test_divergence_trace_from_the_independent_seat_is_schema_valid(tmp_path):
    run_dir = _begin(tmp_path)
    _write(run_dir, "DIVERGENCE.bundle.json", _TRACE)
    path = new_direction._produce_divergence_trace(run_dir, TS, {})
    payload = json.loads(Path(path).read_text(encoding="utf-8"))["payload"]
    assert validate_payload("divergence_trace", payload) == []
    assert payload["produced_by"] == "divergence-operator-runner"
    # an operator that yielded nothing is RECORDED as empty, not dropped
    assert payload["tensions"] == []


def test_the_proposer_inline_trace_is_the_fallback_for_a_lighter_run(tmp_path):
    run_dir = _begin(tmp_path)
    path = new_direction._produce_divergence_trace(run_dir, TS, _TRACE)
    payload = json.loads(Path(path).read_text(encoding="utf-8"))["payload"]
    assert payload["produced_by"] == "hypothesis-generator"
    assert validate_payload("divergence_trace", payload) == []


def _recommendation() -> dict:
    def side(text):
        return [{"observation": text, "evidence_ref": ["evidence/IDEATE/idea-backlog.artifact.json"]}]
    return {
        "recommendation_id": "DR-001", "recommended": "DEEPEN", "confidence": "medium",
        "rationale": "three intervention points are still uncovered",
        "options": [{"option": name, "supporting_evidence": side(f"for {name}"),
                     "opposing_evidence": side(f"against {name}"), "trigger_met": name == "DEEPEN"}
                    for name in ("DEEPEN", "BROADEN", "PIVOT", "CONCLUDE")],
        "unresolved": ["saturation was never measured this run"],
        "evidence_ref": ["evidence/IDEATE/idea-backlog.artifact.json"],
    }


def test_direction_recommendation_is_absent_when_the_seat_did_not_run(tmp_path):
    run_dir = _begin(tmp_path)
    assert new_direction._produce_direction_recommendation(run_dir, TS) is None


def test_direction_recommendation_is_schema_valid_and_assesses_all_four_options(tmp_path):
    run_dir = _begin(tmp_path)
    _write(run_dir, "DIRECTION_ADVICE.bundle.json", _recommendation())
    path = new_direction._produce_direction_recommendation(run_dir, TS)
    payload = json.loads(Path(path).read_text(encoding="utf-8"))["payload"]
    assert validate_payload("direction_recommendation", payload) == []
    assert {row["option"] for row in payload["options"]} == {
        "DEEPEN", "BROADEN", "PIVOT", "CONCLUDE"}


def test_a_recommendation_carries_no_selection_field(tmp_path):
    """It advises where to go next; it never picks an idea. The schema is the guard."""
    run_dir = _begin(tmp_path)
    payload = dict(_recommendation())
    payload["selected_idea"] = "IDEA-1"
    _write(run_dir, "DIRECTION_ADVICE.bundle.json", payload)
    written = json.loads(
        Path(new_direction._produce_direction_recommendation(run_dir, TS)).read_text(encoding="utf-8")
    )["payload"]
    assert "selected_idea" not in written


# --------------------------------------------------------------------------- quality harness

# --------------------------------------------------------------------------- the R2 §A1 ⚠ dependency

def test_divergence_trace_survives_the_ideate_bundle_round_trip(tmp_path):
    """R2 §A1 flagged a hard dependency: an invented TOP-LEVEL bundle key can be moved into a
    normalization sidecar the next stage never reads, which would make `divergence_trace` a silent
    no-op. Measured rather than assumed — the IDEATE bundle has NO allow-set to extend:

    * `new_direction._load_bundle` reads the bundle with a bare `json.loads` — no normalizer, so
      nothing can strip a key on this path (`operate/modes/new_direction.py:318-327`);
    * `_shared.require_bundle_keys` checks REQUIRED keys only and has no allow-list
      (`operate/modes/_shared.py:431-439`);
    * `_require_worker_boundaries` is a FORBIDDEN-key check and `divergence_trace` is in none of the
      four forbidden sets (`operate/modes/new_direction.py:468-477`);
    * `_shared.normalize_worker_payload` — the function `_OUTPUT_SHAPE_FENCE` warns about — is never
      called on the IDEATE bundle by new_direction or deep_ideation.

    This test pins all of that behaviourally, so a future normalizer added to this path fails here.
    """
    run_dir = _begin(tmp_path)
    bundle = {
        "memo_contract_version": "idea-investment-memo/v2",
        "hypotheses": [], "ideas": [],
        **_TRACE,
    }
    path = Path(run_dir) / "inbox" / "IDEATE.bundle.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(bundle), encoding="utf-8")

    loaded = new_direction._load_bundle(run_dir, "IDEATE")
    assert "divergence_trace" in loaded, "the key must survive the bundle read in its ORIGINAL place"
    assert loaded["divergence_trace"]["constraints"][0]["class"] == "soft"

    # ...and it reaches a typed artifact from there, under its own schema (so idea_backlog's
    # additionalProperties:false never applies to it).
    written = new_direction._produce_divergence_trace(run_dir, TS, loaded)
    payload = json.loads(Path(written).read_text(encoding="utf-8"))["payload"]
    assert validate_payload("divergence_trace", payload) == []
    assert payload["constraints"][0]["constraint"] == "labels must be dense"


def test_the_new_idea_fields_survive_into_the_backlog_artifact(tmp_path):
    """The ideas-level half of the same dependency: schema-registered, so nothing is stripped."""
    idea = {
        "idea_id": "IDEA-1", "rank": 1, "summary": "s", "evidence_ref": ["GAP-1"],
        "feasibility": {"score": 0.5},
        "contribution_tier": "mechanism_invention", "invention_claim": "a new gating loss",
        "mechanism_graph_refs": ["N1"], "intervention_point": "N1 (REPLACE)",
        "addresses_conflicts": ["CF-1"], "origin_operator": "negation",
        "innovation_layers": ["mechanism"], "depth_target": "D3 — needs an intervention ablation",
        "conventional_base": "frozen-encoder adaptation", "unusual_connection": "gating theory",
        "resource_envelope": "exceeds_current_hardware",
    }
    assert validate_payload("idea_backlog", {"ranked_ideas": [idea]}) == []


# --------------------------------------------------------------------------- director-facing render

def test_an_out_of_north_star_candidate_reaches_the_director(tmp_path):
    """The compromise this section implements: the worker may neither act on an out-of-scope
    candidate nor delete it. Only the director widens a run, so the candidate has exactly one
    legitimate destination — the menu."""
    run_dir = _begin(tmp_path)
    trace = json.loads(json.dumps(_TRACE))
    trace["divergence_trace"]["reformulations"] = [{
        "changed": "objective", "restatement": "optimise for clinician trust instead of Dice",
        "effect": "usefully_different", "out_of_north_star": True,
    }]
    _write(run_dir, "DIVERGENCE.bundle.json", trace)
    new_direction._produce_divergence_trace(run_dir, TS, {})
    rendered = "\n".join(idea_bet_md._out_of_north_star_lines(Path(run_dir)))
    assert "Candidates Outside The North Star" in rendered
    assert "clinician trust" in rendered
    assert "only you may widen the run" in rendered.lower()


def test_nothing_out_of_scope_renders_no_section(tmp_path):
    run_dir = _begin(tmp_path)
    _write(run_dir, "DIVERGENCE.bundle.json", _TRACE)
    new_direction._produce_divergence_trace(run_dir, TS, {})
    assert idea_bet_md._out_of_north_star_lines(Path(run_dir)) == []


def test_the_direction_recommendation_renders_all_four_options_for_the_director(tmp_path):
    run_dir = _begin(tmp_path)
    _write(run_dir, "DIRECTION_ADVICE.bundle.json", _recommendation())
    new_direction._produce_direction_recommendation(run_dir, TS)
    rendered = "\n".join(idea_bet_md._direction_recommendation_lines(Path(run_dir)))
    for option in ("DEEPEN", "BROADEN", "PIVOT", "CONCLUDE"):
        assert option in rendered
    assert "advisory — the machine never decides this" in rendered
    assert "saturation was never measured this run" in rendered


def test_killed_and_flagged_ideas_are_shown_not_hidden():
    assessments = {
        "IDEA-1": {"idea_id": "IDEA-1", "killed": True, "kill_reason": "no_one_suffers"},
        "IDEA-2": {"idea_id": "IDEA-2", "pseudo_innovation_flags": ["acronym_innovation"]},
        "IDEA-3": {"idea_id": "IDEA-3"},
    }
    proposals = {"IDEA-1": {"summary": "an audit nobody needs"},
                 "IDEA-2": {"summary": "a renamed pipeline"},
                 "IDEA-3": {"summary": "a real mechanism"}}
    rendered = "\n".join(idea_bet_md._killed_by_ranker_lines(assessments, proposals))
    assert "CUT `IDEA-1`" in rendered and "no_one_suffers" in rendered
    assert "Flagged `IDEA-2`" in rendered and "acronym_innovation" in rendered
    assert "IDEA-3" not in rendered, "an idea with no verdict against it does not belong in this section"
    assert "A flag is a signal, not a cut" in rendered


def test_no_section_is_rendered_when_the_ranker_cut_and_flagged_nothing():
    assert idea_bet_md._killed_by_ranker_lines({"IDEA-1": {"idea_id": "IDEA-1"}}, {}) == []


def test_a_declared_but_absent_local_dataset_is_told_to_the_director(tmp_path):
    """R3 C6: "today runnable" is a claim; the probe is the checked fact. Only the second one may
    be reported as fact, and when they disagree the director hears about it."""
    probe = {"checked": ["data/petct/train", "data/petct/val"], "present": ["data/petct/val"],
             "absent": ["data/petct/train"], "verdict": "REMOTE_OR_ABSENT"}
    line = idea_bet_md._local_data_line({"score": 0.9, "local_data_probe": probe}, {})
    assert line is not None
    assert "本机没有找到这些输入" in line
    assert "data/petct/train" in line
    assert "不是核对过的事实" in line


def test_the_probe_is_also_read_from_the_planner_sketch(tmp_path):
    probe = {"checked": ["/mnt/scratch/autopet"], "present": [], "absent": ["/mnt/scratch/autopet"],
             "verdict": "REMOTE_OR_ABSENT"}
    line = idea_bet_md._local_data_line({}, {"resource_feasibility": {"local_data_probe": probe}})
    assert line is not None and "/mnt/scratch/autopet" in line


def test_a_local_verdict_renders_no_honesty_line():
    probe = {"checked": ["data/x"], "present": ["data/x"], "absent": [], "verdict": "LOCAL"}
    assert idea_bet_md._local_data_line({"local_data_probe": probe}, {}) is None


def test_no_probe_means_no_line_and_no_invented_claim():
    """Nothing is asserted about data nobody declared — the capability is wired, not forced."""
    assert idea_bet_md._local_data_line({"score": 0.5}, {}) is None
    assert idea_bet_md._local_data_line({}, {}) is None


def test_a_probe_survives_into_the_backlog_artifact():
    """The optional schema property that makes the wired capability actually reachable."""
    idea = {
        "idea_id": "IDEA-1", "rank": 1, "summary": "s", "evidence_ref": ["GAP-1"],
        "feasibility": {"score": 0.5, "compute": "high", "data": "available", "time": "medium",
                        "local_data_probe": {"checked": ["data/x"], "present": [],
                                             "absent": ["data/x"], "verdict": "REMOTE_OR_ABSENT"}},
    }
    assert validate_payload("idea_backlog", {"ranked_ideas": [idea]}) == []


def test_mechanism_invention_separates_an_invention_from_a_relabelling():
    graph = {"graph_id": "MG-1", "problem_ref": "PA-1",
             "nodes": [{"node_id": "N1", "label": "gating", "kind": "mechanism",
                        "evidence_ref": ["[[a]]"]}],
             "edges": []}
    invention = {"idea_id": "I-1", "contribution_tier": "mechanism_invention",
                 "invention_claim": "a closed-form gate over boundary residuals",
                 "mechanism_graph_refs": ["N1"]}
    relabel = {"idea_id": "I-2", "contribution_tier": "audit"}
    out = build_quality_eval("QE-1", [invention, relabel], mechanism_graph=graph)
    scores = {row["idea_id"]: row["scores"]["mechanism_invention"] for row in out["per_idea"]}
    assert scores["I-1"] > scores["I-2"]
    # and the pairwise comparison on that dimension is no longer a forced tie
    winners = [row["winner"] for row in out["pairwise"] if row["dimension"] == "mechanism_invention"]
    assert winners == ["I-1"]
