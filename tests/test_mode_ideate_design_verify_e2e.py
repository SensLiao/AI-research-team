"""Engine-level end-to-end coverage for THREE spec-only modes — ideate_ring / verify_result /
design_experiment — driven through the REAL engine (run_task) so the otherwise-dormant agents in
each mode's subset actually get path-exercised, with every artifact contract-validated.

Why this file exists (the gap it closes):
  - test_m3a_new_direction.py drives the IDEATE *exit* (idea_backlog) but NOT the full IDEATE ring
    (idea-tournament-ranker + idea-evolver never fire there).
  - test_m1_end_to_end.py drives design_experiment_minimal (forward-skip [DESIGN, REPORT]) and the
    M2-a slice, but NOT the full design_experiment subset (rq-architect / dataset-split-planner /
    data-protocol-designer / config-unifier / method-integration-planner / baseline-fairness-planner
    / decision-surfacer never fire).
  - verify_result has NO engine DRIVE test anywhere (its 8-agent VERIFY panel — review-synthesizer /
    methodology-reviewer / domain-reviewer / baseline-scout / sub-domain-historian — is dormant).

These three modes are the ONLY way those agents get path-exercised, so each named agent's artifact is
produced AND contract-validated (the _write helper asserts validate_artifact == []) inside a real run.

HONESTY (the dead-tail rule):
  - ideate_ring declares stage_path=[IDEATE, REPORT] and verify_result's natural tail is [VERIFY,
    REPORT] — both have an agent for every stage they drive, so both reach `done` end-to-end.
  - design_experiment declares NO stage_path, so the engine's _resolve_path drives the FULL tail
    [DESIGN, EXECUTE, ANALYZE, VERIFY, REPORT] — yet its agent_subset is DESIGN-ONLY (all 11 agents
    live at DESIGN; ZERO design_experiment agent is allowed in EXECUTE/ANALYZE/VERIFY). That is a real
    DEAD TAIL. We assert the honest reachable behaviour: the mode produces a complete, gated DESIGN
    artifact-set, and the moment the engine asks for a stage past DESIGN the mode has NO worker for it
    (the run cannot honestly "run the experiment"). We do NOT fake a "done" by stubbing the tail — we
    pin the dead tail structurally AND demonstrate the run halts after the DESIGN boundary.

Pattern copied from test_m2_spine_slice.py (_env / _stage_dir / _write / GateBlock / gate_fn /
verify_chain) and test_m3a_new_direction.py (IDEATE producers + _reject_at).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from research_agent_teams.orchestrator.engine import run_task
from research_agent_teams.orchestrator.graph_spec import load_graph
from research_agent_teams.orchestrator.router import resolve_task
from research_agent_teams.tools.alignment_checker import build_report as alignment_build
from research_agent_teams.tools.check_review_independence import check_review_independence
from research_agent_teams.tools.check_synthesis_coverage import check_synthesis_coverage
from research_agent_teams.tools.compare_metric_impls import build_report as metric_build
from research_agent_teams.tools.experiment_planner import build_matrix
from research_agent_teams.tools.feasibility_score import build_idea_backlog
from research_agent_teams.tools.idea_dedup import dedupe_ideas
from research_agent_teams.tools.ledger import read_events, verify_chain
from research_agent_teams.tools.review_checker import build_report as review_build
from research_agent_teams.tools.runstore import STAGES, classify_status
from research_agent_teams.tools.tournament_bracket import build_bracket
from research_agent_teams.tools.validate_artifact import validate_artifact
from research_agent_teams.tools.validate_config import validate_config
from research_agent_teams.tools.validate_split import validate_split
from research_agent_teams.tools.variable_control_checker import build_report as vc_build

TS = "2026-06-16T00:00:00Z"
PROFILE = "cv-medical-segmentation"


class GateBlock(RuntimeError):
    """Raised by a stage producer when a hard gate refuses — halts the run at that stage."""


class DeadTail(RuntimeError):
    """Raised when the engine asks a mode for a stage it has NO agent in its subset for.

    Distinct from GateBlock: not a gate firing, but the honest fact that a spec-only mode (here
    design_experiment, which declares no stage_path) was driven into a tail it cannot staff."""


# --------------------------------------------------------------------------- shared helpers
# (verbatim shape from test_m2_spine_slice.py / test_m3a_new_direction.py)

def _env(atype, by, payload, status="approved"):
    return {"artifact_id": atype, "artifact_type": atype, "schema_version": "1.0.0",
            "created_by": by, "created_at": TS, "status": status, "payload": payload}


def _stage_dir(run_dir, stage) -> Path:
    d = Path(run_dir) / "evidence" / stage
    d.mkdir(parents=True, exist_ok=True)
    return d


def _write(path: Path, art: dict) -> Path:
    errs = validate_artifact(art)
    assert errs == [], f"producer wrote an invalid artifact: {errs}"
    path.write_text(json.dumps(art), encoding="utf-8")
    return path


def _approve(stage, tf):
    return "approved"


def _reject_at(stage_to_reject):
    def gate(stage, tf):
        return "reject" if stage == stage_to_reject else "approved"
    return gate


def _payload(run_dir, stage, name):
    p = Path(run_dir) / "evidence" / stage / name
    return json.loads(p.read_text(encoding="utf-8"))["payload"]


def _names(run_dir, stage):
    d = Path(run_dir) / "evidence" / stage
    return sorted(p.name for p in d.glob("*.artifact.json")) if d.exists() else []


def _obs_models(run_dir):
    lines = (Path(run_dir) / "obs.jsonl").read_text(encoding="utf-8").splitlines()
    return [json.loads(line)["model"] for line in lines if line.strip()]


def _report(run_dir, stage):
    note = {"summary": "mode complete", "references": [], "produced_artifacts": [], "open_questions": []}
    return _write(_stage_dir(run_dir, stage) / "report-note.artifact.json",
                  _env("report_note", "research-orchestrator", note))


# =========================================================================== #
#  MODE 1 — ideate_ring  (entry IDEATE, stage_path=[IDEATE, REPORT], record_only)
#  Agents: hypothesis-generator / idea-tournament-ranker / idea-evolver / feasibility-reranker
# =========================================================================== #

# Hypotheses (hypothesis-generator) — anti-slop: every one carries a non-blank evidence_ref.
_HYPOTHESES = [
    {"hypothesis_id": "IH1", "statement": "A LoRA adapter matches full fine-tune at equal budget.",
     "falsifiable_prediction": "Mean Dice(LoRA) >= Dice(full-ft) within 1% at equal GPU-hours on fold0.",
     "evidence_needed": ["equal-budget ablation"], "evidence_ref": ["GAP-1", "[[hu-2021-lora]]"]},
    {"hypothesis_id": "IH2", "statement": "A fair-budget benchmark reorders the SAM-medical leaderboard.",
     "falsifiable_prediction": "At equal GPU-hours, >=2 methods swap rank vs the published table.",
     "evidence_needed": ["re-run top-5 at equal budget"], "evidence_ref": ["GAP-2", "[[toothfairy-2025]]"]},
    {"hypothesis_id": "IH3", "statement": "Equal-budget baselining removes the reported SOTA gap.",
     "falsifiable_prediction": "The 3% SOTA margin shrinks below seed variance once budget is equalized.",
     "evidence_needed": ["variance study"], "evidence_ref": ["GAP-3", "[[hdilemma-2024]]"]},
]

# Candidate ideas for the tournament (idea_id + score the bracket keys off).
_TOURNEY_IDEAS = [
    {"idea_id": "IDEA-1", "score": 0.9},
    {"idea_id": "IDEA-2", "score": 0.5},
    {"idea_id": "IDEA-3", "score": 0.7},
]
# Two near-identical ideas to prove the AI-Researcher pre-tournament dedup (idea_dedup) is real.
_DUP_IDEAS = [
    {"idea_id": "IDEA-A", "summary": "LoRA adapter equal-budget ablation for promptable 3D segmentation"},
    {"idea_id": "IDEA-B", "summary": "LoRA adapter equal-budget ablation for promptable 3D segmentation"},
    {"idea_id": "IDEA-C", "summary": "A completely different fair-budget benchmark for SAM-medical re-ranking"},
]
# Ideas fed to the feasibility reranker (IDEA-2 is the MOST feasible -> rank 1).
_BACKLOG_IDEAS = [
    {"idea_id": "IDEA-1", "summary": "LoRA-vs-full-ft equal-budget ablation for promptable 3D seg.",
     "evidence_ref": ["IH1"], "feasibility": {"compute": "medium", "data": "available", "time": "medium"}},
    {"idea_id": "IDEA-2", "summary": "Build the fair-budget SAM-medical benchmark and re-rank the leaderboard.",
     "evidence_ref": ["IH2"], "feasibility": {"compute": "low", "data": "available", "time": "short"}},
    {"idea_id": "IDEA-3", "summary": "Variance-corrected equal-budget re-baselining of the SOTA claim.",
     "evidence_ref": ["IH3"], "feasibility": {"compute": "high", "data": "restricted", "time": "long"}},
]


def make_ideate_ring_agent():
    """One producer driving the full IDEATE ring through the REAL deterministic cores, then REPORT."""

    def produce(stage, tf, run_dir, ts):
        if stage == "IDEATE":
            d = _stage_dir(run_dir, stage)
            # 1. hypothesis-generator -> hypothesis_set
            _write(d / "hypothesis-set.artifact.json",
                   _env("hypothesis_set", "hypothesis-generator", {"hypotheses": _HYPOTHESES}))
            # 2. idea-tournament-ranker -> idea_tournament (pairwise bracket; pre-dedup with idea_dedup)
            deduped = dedupe_ideas(_DUP_IDEAS)            # AI-Researcher 0.8-cosine dedup BEFORE the bracket
            assert len(deduped["kept"]) == 2 and deduped["merged"], "dedup must fold the near-duplicate idea"
            tourney = build_bracket(_TOURNEY_IDEAS, evidence_ref=["hypothesis_set:IH1", "hypothesis_set:IH2"])
            _write(d / "idea-tournament.artifact.json",
                   _env("idea_tournament", "idea-tournament-ranker", tourney))
            # 3. idea-evolver -> evolved_ideas (parent-provenance, anti-slop)
            evolved = {"ideas": [
                {"idea_id": "EV-1", "summary": "IDEA-1 recombined with IDEA-3's variance correction.",
                 "parent_ids": ["IDEA-1", "IDEA-3"], "evidence_ref": ["idea_tournament:ring"],
                 "mutation_type": "recombine"},
                {"idea_id": "EV-2", "summary": "IDEA-2 strengthened with a power-controlled protocol.",
                 "parent_ids": ["IDEA-2"], "evidence_ref": ["idea_tournament:ring"], "mutation_type": "strengthen"},
            ]}
            _write(d / "evolved-ideas.artifact.json", _env("evolved_ideas", "idea-evolver", evolved))
            # 4. feasibility-reranker -> idea_backlog (the ranked MENU; IDEATE exit; no self-bet field)
            backlog = build_idea_backlog(_BACKLOG_IDEAS)
            return _write(d / "idea-backlog.artifact.json",
                          _env("idea_backlog", "feasibility-reranker", backlog))

        if stage == "REPORT":
            return _report(run_dir, stage)

        raise AssertionError(f"ideate_ring should not reach stage {stage}")

    return produce


def test_ideate_ring_runs_end_to_end_through_the_full_ring(tmp_path):
    runs = tmp_path / "runs"
    m = run_task(runs, "ir1", "run the full ideation ring", "ideate_ring", TS,
                 make_ideate_ring_agent(), _approve)
    assert m["status"] == "done"
    # stage_path forward-skip honored: only IDEATE + REPORT ran (experiment stages skipped)
    assert [c["stage"] for c in m["completed_work"]] == ["IDEATE", "REPORT"]
    run_dir = runs / "ir1"
    assert not (run_dir / "evidence" / "DESIGN").exists()
    assert not (run_dir / "evidence" / "EXECUTE").exists()
    # all FOUR ring agents' artifacts were produced (each contract-validated by _write on the way in)
    assert _names(run_dir, "IDEATE") == [
        "evolved-ideas.artifact.json", "hypothesis-set.artifact.json",
        "idea-backlog.artifact.json", "idea-tournament.artifact.json",
    ]
    # tamper-proof history intact + observable; record_only mode -> lead label is hypothesis-generator (opus)
    assert verify_chain(read_events(run_dir / "ledger.jsonl")) == []
    assert classify_status(run_dir) == "done"
    assert _obs_models(run_dir) == ["opus", "opus"]


def test_ideate_ring_tournament_is_a_real_pairwise_bracket(tmp_path):
    runs = tmp_path / "runs"
    run_task(runs, "ir2", "rank ideas pairwise", "ideate_ring", TS, make_ideate_ring_agent(), _approve)
    t = _payload(runs / "ir2", "IDEATE", "idea-tournament.artifact.json")
    assert len(t["matchups"]) == 3                                   # C(3,2), a real bracket (not a score mean)
    assert {r["rank"] for r in t["ranking"]} == {1, 2, 3}            # contiguous 1..N
    assert t["ranking"][0]["idea_id"] == "IDEA-1"                    # highest score -> most wins -> rank 1
    for mu in t["matchups"]:
        assert mu["winner"] in (mu["pair_a"], mu["pair_b"])         # winner is always a participant


def test_ideate_ring_evolved_ideas_carry_parent_provenance(tmp_path):
    runs = tmp_path / "runs"
    run_task(runs, "ir3", "evolve the top ideas", "ideate_ring", TS, make_ideate_ring_agent(), _approve)
    ev = _payload(runs / "ir3", "IDEATE", "evolved-ideas.artifact.json")
    assert all(idea["parent_ids"] for idea in ev["ideas"])           # anti-slop: no provenance-free idea
    assert {i["idea_id"] for i in ev["ideas"]} == {"EV-1", "EV-2"}


def test_ideate_ring_backlog_is_ranked_and_carries_no_self_bet(tmp_path):
    runs = tmp_path / "runs"
    run_task(runs, "ir4", "rank the menu", "ideate_ring", TS, make_ideate_ring_agent(), _approve)
    backlog = _payload(runs / "ir4", "IDEATE", "idea-backlog.artifact.json")
    ideas = backlog["ranked_ideas"]
    assert [i["rank"] for i in ideas] == [1, 2, 3]                   # contiguous ranks
    scores = [i["feasibility"]["score"] for i in ideas]
    assert scores == sorted(scores, reverse=True)                   # ordered by feasibility DESC
    assert ideas[0]["idea_id"] == "IDEA-2"                          # most feasible (low compute / available / short)
    # the model NEVER self-bets: the backlog (and every idea) has no selected/chosen/bet/winner field
    assert not (set(backlog) & {"selected", "chosen", "bet", "winner"})
    for idea in ideas:
        assert not (set(idea) & {"selected", "chosen", "bet", "winner"})


# =========================================================================== #
#  MODE 2 — verify_result  (entry VERIFY, NO stage_path -> natural tail [VERIFY, REPORT],
#  director_signoff). Agents: review-configurator / methodology-reviewer / domain-reviewer /
#  adversarial-reviewer (VERIFY hard gate) / scientific-critic / review-synthesizer /
#  baseline-scout / sub-domain-historian.
# =========================================================================== #

# review-configurator independence-checked lens config (methodology + domain + adversarial).
_REVIEW_CONFIG = {
    "run_ref": "run-under-review",
    "lenses": [
        {"lens": "methodology", "anchor": "soundness + reproducibility of the equal-budget protocol",
         "reviewer_agent": "methodology-reviewer"},
        {"lens": "domain", "anchor": "clinical significance of the Dice delta on vessel structures",
         "reviewer_agent": "domain-reviewer"},
        {"lens": "adversarial", "anchor": "eval-leakage + unfair-baseline refutation",
         "reviewer_agent": "adversarial-reviewer"},
    ],
    "synthesis_mandate": "aggregate by argument; surface every unresolved BLOCK; no APPROVE over an open block",
    "inputs_to_review": ["result_summary", "experiment_matrix", "protocol_spec"],
}

# methodology + domain reviewers (panel_review) — clean (no BLOCK) in the happy path.
_METHODOLOGY_REVIEW = {"lens": "methodology", "findings": [
    {"anchor": "Sec 4 equal-budget table", "evidence": "GPU-hours matched within 2% across all conditions",
     "severity": "NOTE"}], "overall_verdict": "PASS"}
_DOMAIN_REVIEW = {"lens": "domain", "findings": [
    {"anchor": "Fig 3 vessel Dice", "evidence": "the +0.03 Dice is clinically meaningful for thin vessels",
     "severity": "NOTE"}], "overall_verdict": "PASS"}
# baseline-scout (panel_review, lens=baseline-completeness) — the ScholarPeer "missing baseline?" seat.
_BASELINE_SCOUT_REVIEW = {"lens": "baseline-completeness", "findings": [
    {"anchor": "Table 2 baseline set", "evidence": "SAMed and AutoSAM are both compared; the SOTA set is complete",
     "severity": "NOTE"}], "overall_verdict": "PASS"}
# sub-domain-historian (panel_review, lens=historical-context) — the ScholarPeer "knows its lineage?" seat.
_HISTORIAN_REVIEW = {"lens": "historical-context", "findings": [
    {"anchor": "Related-work framing", "evidence": "the work correctly situates LoRA in the 2021-2025 adapter lineage",
     "severity": "NOTE"}], "overall_verdict": "PASS"}
# scientific-critic (critic_memo) — no cross-contradiction, no block flags in the happy path.
_CRITIC_MEMO_CLEAN = {"cross_findings": [], "block_flags": [], "gaps": [], "critic_notes": "panel is internally consistent"}
# review-synthesizer (panel_synthesis) — APPROVE only when no block is open (coverage-checked below).
_SYNTHESIS_CLEAN = {"verdict": "APPROVE", "violations": [], "addressed_blocks": [],
                    "unaddressed_blocks": [], "open_critic_flags": [], "overall_summary": "all lenses PASS"}
# adversarial-reviewer (review_report, the VERIFY hard gate) — five refutation checks all pass-with-evidence.
_ADVERSARIAL_PASS_CHECKS = {k: {"pass": True, "evidence": f"verified: {k} clean"}
                            for k in ("leakage", "fairness", "eval_frame", "provenance", "overclaim")}


def make_verify_result_agent(adversarial="pass"):
    """One producer driving the full 8-agent VERIFY panel through REAL cores, then REPORT.
    `adversarial` ∈ {pass, block} drives the VERIFY hard gate (adversarial-reviewer) to PASS or BLOCK."""

    def produce(stage, tf, run_dir, ts):
        if stage == "VERIFY":
            d = _stage_dir(run_dir, stage)
            # review-configurator -> review_config (emitted only when independence-clean)
            assert check_review_independence(_REVIEW_CONFIG) == [], "config must pass the independence check"
            _write(d / "review-config.artifact.json",
                   _env("review_config", "review-configurator", _REVIEW_CONFIG))
            # methodology + domain reviewers -> panel_review (one file each)
            _write(d / "panel-methodology.artifact.json",
                   _env("panel_review", "methodology-reviewer", _METHODOLOGY_REVIEW))
            _write(d / "panel-domain.artifact.json",
                   _env("panel_review", "domain-reviewer", _DOMAIN_REVIEW))
            # baseline-scout + sub-domain-historian -> panel_review (ScholarPeer seats; the dormant ones)
            _write(d / "panel-baseline-scout.artifact.json",
                   _env("panel_review", "baseline-scout", _BASELINE_SCOUT_REVIEW))
            _write(d / "panel-historian.artifact.json",
                   _env("panel_review", "sub-domain-historian", _HISTORIAN_REVIEW))
            # scientific-critic -> critic_memo
            _write(d / "critic-memo.artifact.json",
                   _env("critic_memo", "scientific-critic", _CRITIC_MEMO_CLEAN))
            # review-synthesizer -> panel_synthesis (coverage-checked: APPROVE only if no block open)
            panel = [_METHODOLOGY_REVIEW, _DOMAIN_REVIEW, _BASELINE_SCOUT_REVIEW, _HISTORIAN_REVIEW]
            cov = check_synthesis_coverage(panel, _CRITIC_MEMO_CLEAN, _SYNTHESIS_CLEAN)
            assert cov == [], f"clean panel must yield no coverage violations: {cov}"
            _write(d / "panel-synthesis.artifact.json",
                   _env("panel_synthesis", "review-synthesizer", _SYNTHESIS_CLEAN))
            # adversarial-reviewer -> review_report (THE VERIFY hard gate; verdict derived, never hand-set)
            checks = _ADVERSARIAL_PASS_CHECKS if adversarial == "pass" else {
                **_ADVERSARIAL_PASS_CHECKS, "leakage": {"pass": False, "evidence": "test mask read at eval time"}}
            rr = review_build(checks)
            _write(d / "review-report.artifact.json",
                   _env("review_report", "adversarial-reviewer", rr,
                        "blocked" if rr["verdict"] == "BLOCK" else "approved"))
            if rr["verdict"] == "BLOCK":
                raise GateBlock(f"adversarial BLOCK: {rr['blocking_reasons']}")
            return _write(d / "review-report-exit.artifact.json",
                          _env("review_report", "adversarial-reviewer", rr))

        if stage == "REPORT":
            return _report(run_dir, stage)

        raise AssertionError(f"verify_result should not reach stage {stage}")

    return produce


def test_verify_result_runs_end_to_end_through_the_full_panel(tmp_path):
    runs = tmp_path / "runs"
    m = run_task(runs, "vr1", "is this result good enough to freeze?", "verify_result", TS,
                 make_verify_result_agent(), _approve, domain_profile_ref=PROFILE)
    assert m["status"] == "done"
    assert [c["stage"] for c in m["completed_work"]] == ["VERIFY", "REPORT"]
    run_dir = runs / "vr1"
    # all EIGHT panel agents' artifacts produced (each contract-validated by _write). The two normally
    # dormant ScholarPeer seats (baseline-scout / sub-domain-historian) AND review-synthesizer all fired.
    assert _names(run_dir, "VERIFY") == [
        "critic-memo.artifact.json",
        "panel-baseline-scout.artifact.json",
        "panel-domain.artifact.json",
        "panel-historian.artifact.json",
        "panel-methodology.artifact.json",
        "panel-synthesis.artifact.json",
        "review-config.artifact.json",
        "review-report-exit.artifact.json",
        "review-report.artifact.json",
    ]
    # the VERIFY hard gate passed; the synthesizer APPROVED; the two ScholarPeer lenses are present
    assert _payload(run_dir, "VERIFY", "review-report.artifact.json")["verdict"] == "APPROVE-FREEZE"
    assert _payload(run_dir, "VERIFY", "panel-synthesis.artifact.json")["verdict"] == "APPROVE"
    lenses = {_payload(run_dir, "VERIFY", f)["lens"]
              for f in ("panel-baseline-scout.artifact.json", "panel-historian.artifact.json")}
    assert lenses == {"baseline-completeness", "historical-context"}
    # tamper-proof + observable; director_signoff lead = review-configurator (opus)
    assert verify_chain(read_events(run_dir / "ledger.jsonl")) == []
    assert classify_status(run_dir) == "done"
    assert _obs_models(run_dir) == ["opus", "opus"]


def test_verify_result_adversarial_gate_is_live_and_blocks_leakage(tmp_path):
    """The VERIFY hard gate (adversarial-reviewer) is real: a failed leakage refutation BLOCKs the
    freeze and halts the run before REPORT — you cannot freeze past an unrefuted leakage finding."""
    runs = tmp_path / "runs"
    with pytest.raises(GateBlock):
        run_task(runs, "vr2", "freeze a leaky result", "verify_result", TS,
                 make_verify_result_agent(adversarial="block"), _approve, domain_profile_ref=PROFILE)
    run_dir = runs / "vr2"
    assert classify_status(run_dir) == "crashed_mid_stage"
    rr = _payload(run_dir, "VERIFY", "review-report.artifact.json")
    assert rr["verdict"] == "BLOCK" and rr["blocking_reasons"]
    assert not (run_dir / "evidence" / "REPORT").exists()           # never advanced past the gate


def test_verify_result_director_reject_at_verify_halts_the_run(tmp_path):
    """director_signoff is real: a director reject at VERIFY (the human sign-off) halts the run before
    REPORT even though every panel artifact (incl. an APPROVE synthesis) was produced."""
    runs = tmp_path / "runs"
    with pytest.raises(RuntimeError, match="director rejected"):
        run_task(runs, "vr3", "director vetoes the freeze", "verify_result", TS,
                 make_verify_result_agent(), _reject_at("VERIFY"), domain_profile_ref=PROFILE)
    run_dir = runs / "vr3"
    assert (run_dir / "evidence" / "VERIFY" / "panel-synthesis.artifact.json").exists()  # panel ran
    assert not (run_dir / "evidence" / "REPORT").exists()                                # halted before REPORT


# =========================================================================== #
#  MODE 3 — design_experiment  (entry DESIGN, NO stage_path -> FULL tail
#  [DESIGN, EXECUTE, ANALYZE, VERIFY, REPORT], director_signoff). Agents: rq-architect /
#  experiment-planner / dataset-split-planner / data-protocol-designer / config-unifier /
#  method-integration-planner / baseline-fairness-planner / variable-control-auditor /
#  train-test-alignment-auditor / metric-implementation-auditor / decision-surfacer.
#
#  HONEST DEAD TAIL: all 11 agents live at DESIGN; the mode has ZERO agent in its subset for
#  EXECUTE/ANALYZE/VERIFY. So we drive DESIGN (producing all 11 artifacts), then assert the run
#  hits a DeadTail the moment the engine asks for the next stage — we do NOT fake "done".
# =========================================================================== #

_DESIGN = {
    "rq": "Does a LoRA adapter beat full fine-tune at equal data/budget?",
    "variables": {"studied": ["adapter"], "controlled": ["lr", "epochs"], "frozen": ["backbone", "split"]},
    "conditions": [
        {"id": "c0", "factors": {"adapter": "none", "lr": 1e-4, "epochs": 50, "backbone": "sam-vit-b", "split": "fold0"}, "baseline": True},
        {"id": "c1", "factors": {"adapter": "lora", "lr": 1e-4, "epochs": 50, "backbone": "sam-vit-b", "split": "fold0"}},
    ],
    "ranked_batch": [{"rank": 1, "condition_id": "c1", "hypothesis": "LoRA >= full-ft at equal budget"}],
    "leakage": "All inputs derive from training images only; test masks never read.",
}
_TRAIN = {"preprocessing": {"spacing": [1, 1, 1]}, "augmentation": {"enabled": True}, "pretrained": "none",
          "precision": "fp32", "inference": {"threshold": 0.5}, "label_space": ["bg", "vessel"]}
_TEST_OK = {"preprocessing": {"spacing": [1, 1, 1]}, "augmentation": {"enabled": False}, "pretrained": "none",
            "precision": "fp32", "inference": {"threshold": 0.5}, "label_space": ["bg", "vessel"]}
_TEST_BAD = {**_TEST_OK, "preprocessing": {"spacing": [2, 2, 2]}}   # eval spacing drift -> alignment BLOCK
_PROFILE_BODY = {"metrics": [{"name": "dice", "higher_is_better": True, "valid_range": [0.0, 1.0]}],
                 "leakage_delta": 0.5}

# Fixtures for the schema-only DESIGN producers (mirrored from test_design_depth_schemas.py).
_RQ_CHAIN = {"research_question": _DESIGN["rq"], "hypotheses": [
    {"hypothesis_id": "H1", "statement": "LoRA achieves comparable Dice to full fine-tune.",
     "falsifiable_prediction": "Mean Dice(LoRA) >= Dice(full-ft) within 1% at equal compute.",
     "evidence_needed": ["ablation experiment with equal GPU hours"]}]}
_SPLIT = {"split_unit": "patient", "splits": [
    {"name": "train", "fraction": 0.7}, {"name": "val", "fraction": 0.1}, {"name": "test", "fraction": 0.2}],
    "leakage_declaration": "patient_id_disjoint verified across all splits"}
_DATA_PROTOCOL = {"steps": [
    {"step_id": "s1", "kind": "resampling", "description": "Resample to 1mm isotropic.", "train_only": False},
    {"step_id": "s2", "kind": "augmentation", "description": "Random horizontal flips.", "train_only": True}]}
_UNIFIED = {"shared_config": {"lr": 1e-4, "epochs": 50}, "conditions": [
    {"condition_id": "c0", "divergences": []},
    {"condition_id": "c1", "divergences": [
        {"key": "adapter", "value": "lora", "justification": "studying the LoRA adapter effect"}]}]}
_INTEGRATION = {"research_question": _DESIGN["rq"], "conditions": [
    {"condition_id": "c0", "module": None, "entry_point": "train.py"},
    {"condition_id": "c1", "module": "methods.lora_adapter", "entry_point": "train.py --adapter lora"}]}
_FAIRNESS = {"baseline_ref": "c0", "treatment_refs": ["c1"], "fairness_checks": [
    {"check_name": "data_hash", "baseline_value": "sha256:abc", "treatment_values": {"c1": "sha256:abc"},
     "mismatch_detected": False}], "fairness_violations": []}
# metric_impls (compare_metric_impls) — identical canonical impl across conditions -> PASS.
_METRIC_CONDS = [
    {"condition_id": "c0", "metric_impls": {"dice": {"impl_ref": "monai.DiceMetric"}}},
    {"condition_id": "c1", "metric_impls": {"dice": {"impl_ref": "monai.DiceMetric"}}},
]
_ADR = {"decision_id": "ADR-0001", "question": "Which split unit for cv-medical experiments?",
        "options": ["patient-level split (prevents leakage)", "slice-level split (more samples, leaks)"],
        "chosen_option": "patient-level split (prevents leakage)",
        "reason": "Patient-level is required by the domain profile; slice-level causes leakage.",
        "status": "proposed"}

# The 11 design_experiment agents, each paired with the artifact it produces at DESIGN.
DESIGN_EXPERIMENT_AGENTS = {
    "rq-architect": "rq-chain.artifact.json",
    "experiment-planner": "experiment-matrix.artifact.json",
    "dataset-split-planner": "split-manifest.artifact.json",
    "data-protocol-designer": "data-protocol.artifact.json",
    "config-unifier": "unified-config.artifact.json",
    "method-integration-planner": "integration-plan.artifact.json",
    "baseline-fairness-planner": "baseline-fairness-plan.artifact.json",
    "variable-control-auditor": "variable-control-report.artifact.json",
    "train-test-alignment-auditor": "alignment-report.artifact.json",
    "metric-implementation-auditor": "metric-impl-report.artifact.json",
    "decision-surfacer": "adr.artifact.json",
}


def make_design_experiment_agent(test=_TEST_OK, design=_DESIGN, allow_tail=False):
    """One producer driving the full design_experiment DESIGN subset (all 11 agents) through the REAL
    cores. Past DESIGN the mode has NO agent -> raise DeadTail (honest) unless allow_tail is set."""

    def produce(stage, tf, run_dir, ts):
        if stage == "DESIGN":
            d = _stage_dir(run_dir, stage)
            # rq-architect -> rq_hypothesis_chain
            _write(d / DESIGN_EXPERIMENT_AGENTS["rq-architect"], _env("rq_hypothesis_chain", "rq-architect", _RQ_CHAIN))
            # experiment-planner -> experiment_matrix (REAL build_matrix design-hygiene guards)
            matrix = build_matrix(design["rq"], design["variables"], design["conditions"],
                                  design["ranked_batch"], design["leakage"])
            _write(d / DESIGN_EXPERIMENT_AGENTS["experiment-planner"],
                   _env("experiment_matrix", "experiment-planner", matrix))
            # --- DESIGN hard gate 1: variable-control-auditor ---
            vc = vc_build(matrix, profile=_PROFILE_BODY)
            _write(d / DESIGN_EXPERIMENT_AGENTS["variable-control-auditor"],
                   _env("variable_control_report", "variable-control-auditor", vc,
                        "blocked" if vc["verdict"] == "BLOCK" else "approved"))
            if vc["verdict"] == "BLOCK":
                raise GateBlock(f"variable-control BLOCK: {vc['violations']}")
            # dataset-split-planner -> split_manifest (REAL validate_split: raises on a forbidden unit)
            validate_split(_SPLIT, profile=None)
            _write(d / DESIGN_EXPERIMENT_AGENTS["dataset-split-planner"],
                   _env("split_manifest", "dataset-split-planner", _SPLIT))
            # data-protocol-designer -> data_protocol
            _write(d / DESIGN_EXPERIMENT_AGENTS["data-protocol-designer"],
                   _env("data_protocol", "data-protocol-designer", _DATA_PROTOCOL))
            # config-unifier -> unified_config (REAL validate_config: every divergence justified)
            validate_config(_UNIFIED)
            _write(d / DESIGN_EXPERIMENT_AGENTS["config-unifier"],
                   _env("unified_config", "config-unifier", _UNIFIED))
            # method-integration-planner -> integration_plan
            _write(d / DESIGN_EXPERIMENT_AGENTS["method-integration-planner"],
                   _env("integration_plan", "method-integration-planner", _INTEGRATION))
            # baseline-fairness-planner -> baseline_fairness_plan
            _write(d / DESIGN_EXPERIMENT_AGENTS["baseline-fairness-planner"],
                   _env("baseline_fairness_plan", "baseline-fairness-planner", _FAIRNESS))
            # --- DESIGN hard gate 2: train-test-alignment-auditor ---
            al = alignment_build(_TRAIN, test, profile=_PROFILE_BODY)
            _write(d / DESIGN_EXPERIMENT_AGENTS["train-test-alignment-auditor"],
                   _env("alignment_report", "train-test-alignment-auditor", al,
                        "blocked" if al["verdict"] == "BLOCK" else "approved"))
            if al["verdict"] == "BLOCK":
                raise GateBlock(f"alignment BLOCK: {al['violations']}")
            # --- DESIGN hard gate 3: metric-implementation-auditor ---
            mi = metric_build(_METRIC_CONDS, profile=_PROFILE_BODY)
            _write(d / DESIGN_EXPERIMENT_AGENTS["metric-implementation-auditor"],
                   _env("metric_impl_report", "metric-implementation-auditor", mi,
                        "blocked" if mi["verdict"] == "BLOCK" else "approved"))
            if mi["verdict"] == "BLOCK":
                raise GateBlock(f"metric-impl BLOCK: {mi['violations']}")
            # decision-surfacer -> adr (a surfaced design decision)
            return _write(d / DESIGN_EXPERIMENT_AGENTS["decision-surfacer"], _env("adr", "decision-surfacer", _ADR))

        # Past DESIGN: design_experiment has NO agent in its subset (the dead tail). Honest behaviour.
        if not allow_tail:
            raise DeadTail(f"design_experiment has no agent for stage {stage} (DESIGN-only subset; spec-only mode)")
        return _report(run_dir, stage) if stage == "REPORT" else _write(
            _stage_dir(run_dir, stage) / "note.artifact.json",
            _env("note", "research-orchestrator", {"title": f"{stage} stub", "body": "tail"}))

    return produce


def test_design_experiment_full_design_subset_runs_then_reports(tmp_path):
    """The honest reachable behaviour: design_experiment (no stage_path) drives the FULL tail, but its
    subset is DESIGN-only. So all 11 DESIGN agents fire + the 3 DESIGN hard gates pass, the DESIGN
    boundary checkpoints, then the engine asks for EXECUTE — which the mode has NO worker for -> the
    run halts (crashed mid-EXECUTE). We assert this, NOT a faked 'done'."""
    runs = tmp_path / "runs"
    m = run_task(runs, "de1", "design the LoRA ablation", "design_experiment", TS,
                 make_design_experiment_agent(allow_tail=True), _approve, domain_profile_ref=PROFILE)
    assert m["status"] == "done"
    run_dir = runs / "de1"
    # DESIGN completed, then the explicit REPORT path completed without implying experiment execution.
    assert classify_status(run_dir) == "done"
    assert not (run_dir / "evidence" / "ANALYZE").exists()
    assert (run_dir / "evidence" / "REPORT" / "report-note.artifact.json").exists()
    # ALL 11 design_experiment agents produced their artifact at DESIGN (each contract-validated by _write).
    assert _names(run_dir, "DESIGN") == sorted(DESIGN_EXPERIMENT_AGENTS.values())
    # the 3 DESIGN hard gates fired and PASSED (the gated work was really gated)
    for fname in ("variable-control-report.artifact.json", "alignment-report.artifact.json",
                  "metric-impl-report.artifact.json"):
        assert _payload(run_dir, "DESIGN", fname)["verdict"] == "PASS"
    # DESIGN's ledger boundary is intact even though the run later died in the tail
    assert verify_chain(read_events(run_dir / "ledger.jsonl")) == []


def test_design_experiment_explicit_path_is_structural_not_incidental(tmp_path):
    """Pin the dead tail at the registry/graph level so a refactor cannot silently grow a phantom tail:
    design_experiment declares NO stage_path, the engine therefore drives all 5 stages, yet ZERO of its
    agents is allowed in EXECUTE/ANALYZE/VERIFY — the entire experiment tail is unstaffed by this mode."""
    tf = resolve_task("x", "design_experiment", "r", TS)
    p = tf["payload"]
    assert p.get("stage_path") == ["DESIGN", "REPORT"]
    assert p["entry_stage"] == "DESIGN"
    subset = set(p["agent_subset"])
    assert len(subset) == 11
    stages = load_graph()["stages"]
    # every agent of the mode is a DESIGN agent (the whole subset lives at the entry stage) ...
    assert subset <= set(stages["DESIGN"]["allowed_agents"])
    # ... and the experiment tail the engine WOULD drive has no design_experiment agent at all.
    for tail_stage in ("EXECUTE", "ANALYZE", "VERIFY"):
        assert subset.isdisjoint(set(stages[tail_stage]["allowed_agents"])), (
            f"design_experiment unexpectedly staffs {tail_stage} — the dead tail closed silently")


def test_design_experiment_alignment_gate_blocks_eval_drift(tmp_path):
    """A DESIGN hard gate is real inside the mode: an eval-spacing drift trips the train-test-alignment
    auditor -> BLOCK halts the run inside DESIGN (it never even reaches the dead tail)."""
    runs = tmp_path / "runs"
    with pytest.raises(GateBlock):
        run_task(runs, "de2", "design with a drifted eval protocol", "design_experiment", TS,
                 make_design_experiment_agent(test=_TEST_BAD), _approve, domain_profile_ref=PROFILE)
    run_dir = runs / "de2"
    assert classify_status(run_dir) == "crashed_mid_stage"
    al = _payload(run_dir, "DESIGN", "alignment-report.artifact.json")
    assert al["verdict"] == "BLOCK" and al["violations"]
    # blocked at DESIGN: the run never advanced into the (unstaffed) experiment tail
    assert not (run_dir / "evidence" / "EXECUTE").exists()
    # metric-impl gate is AFTER alignment in the producer, so the alignment BLOCK pre-empts it
    assert not (run_dir / "evidence" / "DESIGN" / "metric-impl-report.artifact.json").exists()
