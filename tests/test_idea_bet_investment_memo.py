"""Decision-quality contract for the Markdown-first /idea-bet menu.

The operated IDEATE panel must keep authorship, comparative ranking, prior-art
prosecution, and experiment planning in separate workers.  Their bundles are
then assembled into one director-facing investment memo per surviving idea.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from research_agent_teams.operate.artifacts import GateBlock, TargetedGateBlock
from research_agent_teams.operate.modes import deep_ideation, new_direction
from research_agent_teams.operate.output_versions import (
    finalize_output,
    physical_output,
    prepare_plan,
)
from research_agent_teams.tests.test_operate_deep_ideation import (
    COLLISION_BUNDLE,
    EXPERIMENT_BUNDLE,
    IDEATE_BUNDLE,
    TS,
    _begin,
    _drop,
    _drop_discover,
    _payload,
)
from research_agent_teams.tools import idea_bet_markdown as idea_bet_md
from research_agent_teams.tools.idea_bet_markdown import lint_idea_bet_menu
from research_agent_teams.tools.research_output_quality import audit_markdown_text


MEMO_VERSION = "idea-investment-memo/v2"


def _rich_split_bundles():
    proposal = {
        "memo_contract_version": MEMO_VERSION,
        "hypotheses": copy.deepcopy(IDEATE_BUNDLE["hypotheses"]),
        "ideas": copy.deepcopy(IDEATE_BUNDLE["ideas"]),
    }
    proposal["ideas"][0].update({
        "research_question": (
            "Can parameter-efficient adaptation preserve thin-structure accuracy "
            "at matched compute?"
        ),
        "mechanism_hypothesis": (
            "Low-rank updates preserve pretrained prompt features while concentrating "
            "capacity on topology-sensitive channels."
        ),
        "causal_chain": [
            "low-rank adaptation limits destructive feature drift",
            "stable prompt features preserve thin-structure continuity",
            "preserved continuity improves boundary F1 at matched GPU-hours",
        ],
        "intended_contribution": (
            "A mechanism-tested, compute-matched adaptation result rather than another "
            "uncontrolled accuracy comparison."
        ),
        "why_now": (
            "Public 3D prompt datasets and reproducible adapter baselines now make the "
            "claim testable within one review cycle."
        ),
    })
    proposal["ideas"][1].update({
        "research_question": (
            "Does equalizing adaptation budget materially reorder the SAM-medical leaderboard?"
        ),
        "mechanism_hypothesis": (
            "Published ranks partly reflect unequal optimization budgets rather than method quality."
        ),
        "causal_chain": [
            "unequal budgets change convergence opportunity",
            "convergence opportunity inflates reported method differences",
            "budget matching reveals a different method ordering",
        ],
        "intended_contribution": "A controlled leaderboard with budget-confounding quantified.",
        "why_now": "Training recipes and public checkpoints are now available for a matched rerun.",
    })

    ranking = {
        "memo_contract_version": MEMO_VERSION,
        "tournament": copy.deepcopy(IDEATE_BUNDLE["tournament"]),
        "evolved": [],
        "investment_assessments": [
            {
                "idea_id": "IDEA-1",
                "investment_case": (
                    "A small oracle-first test can retire the mechanism cheaply before training."
                ),
                "rank_rationale": "Higher mechanism upside, but more compute than IDEA-2.",
                "dimension_scores": {
                    "importance": 5,
                    "mechanism_coherence": 5,
                    "novelty_exposure": 4,
                    "falsifiability": 5,
                    "information_gain": 5,
                    "downstream_leverage": 5,
                },
                "strongest_rejection_case": (
                    "The oracle intervention may reveal headroom that no deployable learner can capture."
                ),
            },
            {
                "idea_id": "IDEA-2",
                "investment_case": "Fastest path to a field-level measurement artifact.",
                "rank_rationale": "Public data and low compute make this the fastest result.",
                "dimension_scores": {
                    "importance": 3,
                    "mechanism_coherence": 2,
                    "novelty_exposure": 2,
                    "falsifiability": 4,
                    "information_gain": 3,
                    "downstream_leverage": 3,
                },
                "strongest_rejection_case": (
                    "A reordered leaderboard may diagnose reporting practice without yielding a new method."
                ),
            },
        ],
    }

    collision = copy.deepcopy(COLLISION_BUNDLE)
    collision["memo_contract_version"] = MEMO_VERSION
    collision["findings"][0].update({
        "difference_from_prior_art": (
            "Nearby LoRA papers do not isolate topology preservation under matched GPU-hours."
        ),
        "closest_prior_art": [
            {
                "ref": "[[a]]",
                "title": "Adapter tuning baseline",
                "relationship": "partial_component_prior",
                "difference": "2D adaptation without the oracle topology intervention.",
            }
        ],
    })
    collision["findings"][1].update({
        "difference_from_prior_art": (
            "Existing leaderboards report heterogeneous budgets and do not rerun methods under one cap."
        ),
        "closest_prior_art": [
            {
                "ref": "[[b]]",
                "title": "Published SAM-medical leaderboard",
                "relationship": "enabling_base",
                "difference": "No compute-matched reranking.",
            }
        ],
    })

    experiment = copy.deepcopy(EXPERIMENT_BUNDLE)
    experiment["memo_contract_version"] = MEMO_VERSION
    experiment["sketches"][0].update({
        "baselines": ["full fine-tuning at matched GPU-hours", "frozen encoder"],
        "success_thresholds": [
            "oracle topology intervention improves boundary F1 by >=3 points",
            "learned adapter retains >=80% of the oracle gain and stays within 1 Dice point of full FT",
        ],
        "failure_thresholds": [
            "oracle intervention improves boundary F1 by <1 point",
            "learned adapter captures <40% of the oracle gain",
        ],
        "kill_criteria": [
            "kill the direction if the oracle stage fails on two preregistered folds",
            "kill the learned branch if gain per GPU-hour is no better than full fine-tuning",
        ],
        "resource_feasibility": {
            "compute": "one oracle inference sweep plus 12 matched training runs",
            "data": "public promptable 3D dataset; labels already available",
            "time": "two weeks to first falsification",
            "dependencies": ["one 24GB GPU", "released full-FT checkpoint"],
        },
        "main_risks": [
            {
                "risk": "oracle mask leaks target information",
                "mitigation": "restrict the oracle to a topology-preserving operator available at inference",
            },
            {
                "risk": "matched hours still hide tuning effort",
                "mitigation": "cap both search trials and total GPU-hours",
            },
        ],
        "execution_order": [
            "audit data and reproduce the full-FT baseline",
            "run the oracle upper-bound stage",
            "train the learned proxy only if the oracle clears its threshold",
            "run the end-to-end matched-compute comparison",
        ],
        "stages": [
            {
                "stage_id": "S1",
                "stage_type": "oracle_upper_bound",
                "name": "Oracle topology intervention",
                "purpose": "Test whether fixing topology can move the target metric at all.",
                "setup": "Apply the idealized topology repair to frozen model outputs.",
                "baselines": ["unmodified frozen-model output"],
                "controls": ["same cases and post-processing budget"],
                "success_threshold": "boundary F1 gain >=3 points",
                "failure_threshold": "boundary F1 gain <1 point",
                "kill_criteria": "stop the entire direction after failure on two folds",
                "depends_on": [],
            },
            {
                "stage_id": "S2",
                "stage_type": "learned_model",
                "name": "Learned topology proxy",
                "purpose": "Measure how much of the oracle headroom is learnable without leakage.",
                "setup": "Train a low-rank adapter to predict the oracle intervention.",
                "baselines": ["plain LoRA", "full fine-tuning"],
                "controls": ["matched search trials and GPU-hours"],
                "success_threshold": "retain >=80% of oracle boundary-F1 gain",
                "failure_threshold": "retain <40% of oracle gain",
                "kill_criteria": "do not advance if efficiency is no better than full fine-tuning",
                "depends_on": ["S1"],
            },
            {
                "stage_id": "S3",
                "stage_type": "end_to_end",
                "name": "Matched-compute confirmation",
                "purpose": "Confirm the complete claim on held-out data.",
                "setup": "Evaluate the learned adapter and baselines on the preregistered folds.",
                "baselines": ["full fine-tuning", "plain LoRA", "frozen encoder"],
                "controls": ["same splits, prompts, seeds, and GPU-hour cap"],
                "success_threshold": "within 1 Dice point of full FT and >=3 boundary-F1 points over plain LoRA",
                "failure_threshold": "miss either primary threshold",
                "kill_criteria": "do not scale or write the method paper",
                "depends_on": ["S2"],
            },
        ],
    })
    experiment["sketches"][1].update({
        "baselines": ["published leaderboard", "parameter-count-matched rerun"],
        "success_thresholds": [">=2 methods swap rank under the common budget"],
        "failure_thresholds": ["rank correlation with the published table remains >=0.95"],
        "kill_criteria": ["stop if all released methods cannot be reproduced within tolerance"],
        "resource_feasibility": {
            "compute": "20 capped reruns",
            "data": "all evaluation sets are public",
            "time": "three weeks",
            "dependencies": ["released checkpoints for four of five methods"],
        },
        "main_risks": [
            {
                "risk": "missing training code makes the comparison incomplete",
                "mitigation": "preregister a minimum four-method coverage rule",
            }
        ],
        "execution_order": [
            "reproduce published scores",
            "freeze the common budget protocol",
            "run capped tuning and final seeds",
        ],
        "stages": [
            {
                "stage_id": "S1",
                "stage_type": "direct",
                "name": "Budget-matched rerun",
                "purpose": "Test whether budget controls change rank order.",
                "setup": "Rerun each method under one GPU-hour and search-trial cap.",
                "baselines": ["published leaderboard"],
                "controls": ["same splits, seeds, and evaluation code"],
                "success_threshold": ">=2 rank swaps",
                "failure_threshold": "rank correlation >=0.95",
                "kill_criteria": "stop if fewer than four methods reproduce",
                "depends_on": [],
            }
        ],
    })
    return proposal, ranking, collision, experiment


def test_ideate_panel_keeps_proposer_ranker_collision_planner_separate(tmp_path):
    rd = _begin(tmp_path)
    spec = new_direction.llm_step(rd, "IDEATE", "find a direction")
    workers = spec["workers"]

    assert [w["label"] for w in workers] == [
        "hypothesis-generator",
        "idea-tournament-ranker",
        "novelty-collision-checker",
        "experiment-planner",
    ]
    assert [Path(w["output"]).name for w in workers] == [
        "IDEATE.bundle.json",
        "RANKING.bundle.json",
        "COLLISION.bundle.json",
        "EXPERIMENT.bundle.json",
    ]


def test_split_worker_bundles_render_complete_bet_memos_and_staged_ladder(tmp_path):
    rd = _begin(tmp_path)
    _drop_discover(rd)
    deep_ideation.run_dets(rd, "DISCOVER", TS)
    proposal, ranking, collision, experiment = _rich_split_bundles()
    _drop(rd, "IDEATE", proposal)
    _drop(rd, "RANKING", ranking)
    _drop(rd, "COLLISION", collision)
    _drop(rd, "EXPERIMENT", experiment)

    deep_ideation.run_dets(rd, "IDEATE", TS)

    backlog = _payload(rd, "IDEATE", "idea-backlog.artifact.json")["ranked_ideas"]
    assert backlog[0]["idea_id"] == "IDEA-1"
    assert backlog[0]["feasibility"]["score"] < backlog[1]["feasibility"]["score"]
    assert backlog[0]["scientific_investment"]["score"] > backlog[1]["scientific_investment"]["score"]
    assert backlog[0]["scientific_investment"]["policy_version"] == "scientific-investment/v1"

    menu = Path(rd, "director-review", "ideas", "idea-bet-menu.md")
    text = menu.read_text(encoding="utf-8")
    assert lint_idea_bet_menu(rd) == []
    assert "## Portfolio Execution Map" in text
    assert "| Rank | Research direction | First decisive stage | Primary kill criterion |" in text
    assert "### Direction 1 |" in text
    assert "<!-- idea_key: IDEA-1 -->" in text
    assert "### Rank 1 - IDEA-1" not in text
    assert "## Internal Keys And Ranking Appendix" in text
    for label in (
        "Research question",
        "Independent scientific value",
        "Mechanism hypothesis",
        "Causal chain",
        "Difference from prior art",
        "Novelty status",
        "Why now",
        "Minimal falsification experiment",
        "Baselines",
        "Controls",
        "Success thresholds",
        "Failure thresholds",
        "Kill criteria",
        "Resource and data feasibility",
        "Main risks",
        "Execution order",
        "Strongest rejection case",
    ):
        assert text.count(f"**{label}:**") == 2
    assert "Oracle topology intervention" in text
    assert "`oracle_upper_bound`" in text
    assert "Learned topology proxy" in text
    assert "`learned_model`" in text
    assert text.index("Oracle topology intervention") < text.index("Learned topology proxy")
    assert "records_selection: false" in text
    assert audit_markdown_text("deep_ideation", text)["status"] == "pass"
    cards = sorted(Path(rd, "director-review", "ideas", "cards").glob("direction-*.md"))
    assert [p.name for p in cards] == ["direction-01.md", "direction-02.md"]
    assert cards[0].read_text(encoding="utf-8").startswith("# ")
    assert "# Rank" not in cards[0].read_text(encoding="utf-8")


def test_idea_bet_heading_alias_is_advisory_but_human_gate_stays_ready(
    tmp_path, monkeypatch
):
    rd = _begin(tmp_path)
    _drop_discover(rd)
    deep_ideation.run_dets(rd, "DISCOVER", TS)
    proposal, ranking, collision, experiment = _rich_split_bundles()
    _drop(rd, "IDEATE", proposal)
    _drop(rd, "RANKING", ranking)
    _drop(rd, "COLLISION", collision)
    _drop(rd, "EXPERIMENT", experiment)
    original_builder = idea_bet_md.build_idea_bet_menu_markdown

    def _aliased_builder(*args, **kwargs):
        return original_builder(*args, **kwargs).replace(
            "## Evidence And Quality", "## Evidence & Quality"
        )

    monkeypatch.setattr(
        idea_bet_md,
        "build_idea_bet_menu_markdown",
        _aliased_builder,
    )

    _paths, report = deep_ideation.run_dets(rd, "IDEATE", TS)

    assert report["director_idea_bet_menu"]
    assert "## Evidence & Quality" in Path(report["director_idea_bet_menu"]).read_text(
        encoding="utf-8"
    )
    advisory = json.loads(
        (Path(rd) / "inbox" / "idea-bet-markdown-quality-advisory.json")
        .read_text(encoding="utf-8")
    )
    assert advisory["delivery_blocking"] is False
    assert advisory["delivery_status"] == "USABLE_WITH_CAVEATS"
    assert advisory["gate_ready"] is True
    assert "missing heading: ## Evidence And Quality" in advisory["warnings"]


def test_idea_bet_hidden_human_boundary_still_blocks_gate(tmp_path, monkeypatch):
    rd = _begin(tmp_path)
    _drop_discover(rd)
    deep_ideation.run_dets(rd, "DISCOVER", TS)
    proposal, ranking, collision, experiment = _rich_split_bundles()
    _drop(rd, "IDEATE", proposal)
    _drop(rd, "RANKING", ranking)
    _drop(rd, "COLLISION", collision)
    _drop(rd, "EXPERIMENT", experiment)
    original_builder = idea_bet_md.build_idea_bet_menu_markdown

    def _hidden_boundary_builder(*args, **kwargs):
        return original_builder(*args, **kwargs).replace(
            "records_selection: false", "records_selection: hidden"
        )

    monkeypatch.setattr(
        idea_bet_md,
        "build_idea_bet_menu_markdown",
        _hidden_boundary_builder,
    )

    with pytest.raises(GateBlock, match="records_selection: false"):
        deep_ideation.run_dets(rd, "IDEATE", TS)

    advisory = json.loads(
        (Path(rd) / "inbox" / "idea-bet-markdown-quality-advisory.json")
        .read_text(encoding="utf-8")
    )
    assert advisory["gate_ready"] is False
    assert advisory["gate_blockers"] == [
        "Markdown menu must state records_selection: false"
    ]


def test_idea_bet_without_true_candidates_remains_hard_block(tmp_path):
    with pytest.raises(ValueError, match="idea-backlog has no ranked_ideas"):
        idea_bet_md.write_idea_bet_menu(tmp_path, generated_at=TS)


def test_current_panel_uses_hash_linked_collision_supplement(tmp_path):
    """A targeted collision repair must replace the logical bundle for every IDEATE gate."""
    rd = _begin(tmp_path)
    _drop_discover(rd)
    deep_ideation.run_dets(rd, "DISCOVER", TS)
    proposal, ranking, collision, experiment = _rich_split_bundles()
    collision.pop("memo_contract_version")
    _drop(rd, "IDEATE", proposal)
    _drop(rd, "RANKING", ranking)
    _drop(rd, "COLLISION", collision)
    _drop(rd, "EXPERIMENT", experiment)

    run_dir = Path(rd)
    logical = run_dir / "inbox" / "COLLISION.bundle.json"
    node = {
        "id": "2:novelty-collision-checker:inbox/COLLISION.bundle.json",
        "label": "novelty-collision-checker",
        "output_path": logical,
        "output_rel": "inbox/COLLISION.bundle.json",
    }
    plan = prepare_plan(
        run_dir, "IDEATE", 1, [node], {"novelty-collision-checker"},
        {"verdict": "NEEDS_SUPPLEMENT", "defects": []},
    )
    corrected = copy.deepcopy(collision)
    corrected["memo_contract_version"] = MEMO_VERSION
    corrected_path = physical_output(run_dir, plan, node["id"])
    corrected_path.parent.mkdir(parents=True, exist_ok=True)
    corrected_path.write_text(json.dumps(corrected), encoding="utf-8")
    finalize_output(run_dir, "IDEATE", 1, node["id"], TS)

    deep_ideation.run_dets(rd, "IDEATE", TS)

    backlog = _payload(rd, "IDEATE", "idea-backlog.artifact.json")
    assert backlog["ranked_ideas"]


def test_current_panel_format_gap_is_targeted_supplement_not_terminal_block(tmp_path):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "RANKING.bundle.json").write_text(
        json.dumps({"tournament": []}), encoding="utf-8"
    )

    with pytest.raises(TargetedGateBlock) as exc_info:
        new_direction._load_current_panel_bundle(
            str(tmp_path), "RANKING", ("tournament", "investment_assessments")
        )

    exc = exc_info.value
    assert exc.verdict == "NEEDS_SUPPLEMENT"
    assert exc.defects[0]["target_agents"] == ["idea-tournament-ranker"]
    assert "memo_contract_version" in str(exc)


def test_deep_ideation_uses_hash_linked_experiment_supplement(tmp_path):
    """Deep sketch validation must consume the effective repaired planner bundle too."""
    rd = _begin(tmp_path)
    _drop_discover(rd)
    deep_ideation.run_dets(rd, "DISCOVER", TS)
    proposal, ranking, collision, experiment = _rich_split_bundles()
    experiment["sketches"][0].pop("kill_criteria")
    _drop(rd, "IDEATE", proposal)
    _drop(rd, "RANKING", ranking)
    _drop(rd, "COLLISION", collision)
    _drop(rd, "EXPERIMENT", experiment)

    run_dir = Path(rd)
    logical = run_dir / "inbox" / "EXPERIMENT.bundle.json"
    node = {
        "id": "3:experiment-planner:inbox/EXPERIMENT.bundle.json",
        "label": "experiment-planner",
        "output_path": logical,
        "output_rel": "inbox/EXPERIMENT.bundle.json",
    }
    plan = prepare_plan(
        run_dir, "IDEATE", 1, [node], {"experiment-planner"},
        {"verdict": "NEEDS_SUPPLEMENT", "defects": []},
    )
    corrected = copy.deepcopy(experiment)
    corrected["sketches"][0]["kill_criteria"] = ["stop if the oracle branch has no material gain"]
    corrected_path = physical_output(run_dir, plan, node["id"])
    corrected_path.parent.mkdir(parents=True, exist_ok=True)
    corrected_path.write_text(json.dumps(corrected), encoding="utf-8")
    finalize_output(run_dir, "IDEATE", 1, node["id"], TS)

    deep_ideation.run_dets(rd, "IDEATE", TS)

    sketches = list((run_dir / "evidence" / "IDEATE").glob("experiment-sketch-*.artifact.json"))
    assert sketches


def test_strict_memo_contract_blocks_a_survivor_without_kill_criteria(tmp_path):
    rd = _begin(tmp_path)
    _drop_discover(rd)
    deep_ideation.run_dets(rd, "DISCOVER", TS)
    proposal, ranking, collision, experiment = _rich_split_bundles()
    experiment["sketches"][0].pop("kill_criteria")
    _drop(rd, "IDEATE", proposal)
    _drop(rd, "RANKING", ranking)
    _drop(rd, "COLLISION", collision)
    _drop(rd, "EXPERIMENT", experiment)

    with pytest.raises(GateBlock, match="kill_criteria"):
        deep_ideation.run_dets(rd, "IDEATE", TS)


def test_omitting_current_memo_version_cannot_fall_back_to_legacy(tmp_path):
    rd = _begin(tmp_path)
    _drop_discover(rd)
    deep_ideation.run_dets(rd, "DISCOVER", TS)
    _drop(rd, "IDEATE", copy.deepcopy(IDEATE_BUNDLE))
    _drop(rd, "COLLISION", copy.deepcopy(COLLISION_BUNDLE))
    _drop(rd, "EXPERIMENT", copy.deepcopy(EXPERIMENT_BUNDLE))

    with pytest.raises(GateBlock, match="explicit hash-bound IDEA-LEGACY-REPLAY.json"):
        deep_ideation.run_dets(rd, "IDEATE", TS)


def test_current_panel_missing_collision_worker_blocks_instead_of_ranking(tmp_path):
    rd = _begin(tmp_path)
    _drop_discover(rd)
    deep_ideation.run_dets(rd, "DISCOVER", TS)
    proposal, ranking, _collision, experiment = _rich_split_bundles()
    _drop(rd, "IDEATE", proposal)
    _drop(rd, "RANKING", ranking)
    _drop(rd, "EXPERIMENT", experiment)

    with pytest.raises(GateBlock, match="COLLISION.bundle.json missing"):
        deep_ideation.run_dets(rd, "IDEATE", TS)


def test_current_ranker_cannot_smuggle_proposer_fields(tmp_path):
    rd = _begin(tmp_path)
    _drop_discover(rd)
    deep_ideation.run_dets(rd, "DISCOVER", TS)
    proposal, ranking, collision, experiment = _rich_split_bundles()
    ranking["ideas"] = copy.deepcopy(proposal["ideas"])
    _drop(rd, "IDEATE", proposal)
    _drop(rd, "RANKING", ranking)
    _drop(rd, "COLLISION", collision)
    _drop(rd, "EXPERIMENT", experiment)

    with pytest.raises(GateBlock, match="crossed worker ownership boundary"):
        deep_ideation.run_dets(rd, "IDEATE", TS)


def test_explicit_hash_bound_legacy_replay_stays_unverified_and_unranked(tmp_path):
    rd = _begin(tmp_path)
    _drop_discover(rd)
    deep_ideation.run_dets(rd, "DISCOVER", TS)
    _drop(rd, "IDEATE", copy.deepcopy(IDEATE_BUNDLE))
    _drop(rd, "COLLISION", copy.deepcopy(COLLISION_BUNDLE))
    _drop(rd, "EXPERIMENT", copy.deepcopy(EXPERIMENT_BUNDLE))
    new_direction.write_legacy_replay_receipt(
        rd, source_run_id="historical-di1", reason="render a frozen pre-panel scratch run")

    _paths, report = deep_ideation.run_dets(rd, "IDEATE", TS)
    backlog = _payload(rd, "IDEATE", "idea-backlog.artifact.json")["ranked_ideas"]
    assert report["idea_contract_status"] == "LEGACY_UNVERIFIED"
    assert report["current_scientific_rank"] is False
    assert all("scientific_investment" not in row for row in backlog)
    assert all(any("LEGACY_UNVERIFIED" in caveat for caveat in row.get("caveats", []))
               for row in backlog)
    assert all(row["trust_status"] == "LEGACY_UNVERIFIED" for row in new_direction.menu(rd))


def test_tampering_legacy_bundle_after_receipt_blocks_replay(tmp_path):
    rd = _begin(tmp_path)
    _drop(rd, "IDEATE", copy.deepcopy(IDEATE_BUNDLE))
    new_direction.write_legacy_replay_receipt(
        rd, source_run_id="historical-di1", reason="frozen replay")
    path = Path(rd) / "inbox" / "IDEATE.bundle.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["ideas"][0]["summary"] += " tampered"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(GateBlock, match="hash mismatch"):
        new_direction._load_ideate_bundle(rd)
