"""Adversarial regression tests for the QC-tool hardening (Tier 3).

Each test feeds the exact input that produced a wrong verdict / crash before the fix, and asserts the
corrected behaviour. These FAIL on the old code.
"""
from __future__ import annotations

from research_agent_teams.tools.check_review_independence import check_review_independence
from research_agent_teams.tools.check_synthesis_coverage import build_report as synth_report
from research_agent_teams.tools.fairness_audit import check_fairness
from research_agent_teams.tools.feasibility_score import score_feasibility
from research_agent_teams.tools.figure_critique_check import critique_figure
from research_agent_teams.tools.goal_alignment_audit import check_goal_alignment
from research_agent_teams.tools.variance_audit import build_report as variance_report
from research_agent_teams.tools.viz_audit import check_viz_truncation


# 1. variance: distinct fractional float seeds must not collapse via int() truncation
def test_variance_fractional_seeds_stay_distinct():
    recs = [{"seed": 1.1, "metrics": {"dice": 0.85}},
            {"seed": 1.5, "metrics": {"dice": 0.80}},
            {"seed": 1.9, "metrics": {"dice": 0.70}}]
    rep = variance_report("c1", recs, profile={"min_seeds": 3})
    assert rep["n_seeds"] == 3, "1.1/1.5/1.9 were collapsed to one seed (int truncation) before the fix"
    # FIX 4(b) preserved: int-valued forms still collapse to a single distinct seed
    rep2 = variance_report("c2", [{"seed": 42}, {"seed": "42"}, {"seed": 42.0}])
    assert rep2["n_seeds"] == 1


# 2. synthesis coverage: a short flag must not be cleared by a substring inside an unrelated word
def test_synthesis_short_flag_not_cleared_by_substring():
    reviews = [{"lens": "methodology", "findings": []}]
    memo = {"block_flags": [{"flag_text": "leak", "source": "critic"}]}
    synthesis = {"verdict": "APPROVE", "violations": [],
                 "addressed_blocks": [{"block_source": "we improved the data leakage diagram",
                                       "rebuttal": "a substantive multi-word rebuttal here"}],
                 "unaddressed_blocks": [], "open_critic_flags": []}
    assert synth_report(reviews, memo, synthesis)["verdict"] == "BLOCK", \
        "'leak' is not a whole token in 'leakage' — the blocker must NOT be cleared"
    # legitimate whole-token containment (source ⊇ flag) still passes
    memo2 = {"block_flags": [{"flag_text": "data leakage", "source": "critic"}]}
    synth2 = {"verdict": "APPROVE", "violations": [],
              "addressed_blocks": [{"block_source": "fixed the data leakage split [resolved]",
                                    "rebuttal": "re-derived the loader; no test mask read (loader.py:88)"}],
              "unaddressed_blocks": [], "open_critic_flags": []}
    assert synth_report(reviews, memo2, synth2)["verdict"] == "PASS"


# 3. goal alignment: a condition merely NAMED *transfer* must not self-satisfy a generalization claim
def test_goal_alignment_transfer_name_no_longer_self_satisfies():
    matrix = {"research_question": "Does the method generalize / transfer to new domains?",
              "conditions": [{"id": "ours_transfer_time_ablation", "factors": {}},
                             {"id": "ours_main", "factors": {}}]}
    violations = check_goal_alignment(matrix, {"findings": []})
    assert any("generaliz" in v.lower() or "ood" in v.lower() or "external" in v.lower() for v in violations), \
        "a *transfer*-named internal baseline must not count as OOD evidence"
    # a genuine external/held-out condition DOES clear it
    matrix_ok = dict(matrix, conditions=[{"id": "ours_external_heldout", "factors": {}}])
    assert check_goal_alignment(matrix_ok, {"findings": []}) == []


# 4. review independence: case/whitespace-variant lenses are one perspective, not two
def test_review_independence_case_variant_lenses_flagged():
    config = {"lenses": [
        {"lens": "methodology", "anchor": "section 3", "reviewer_agent": "r1"},
        {"lens": "Methodology", "anchor": "section 4", "reviewer_agent": "r2"}]}
    violations = check_review_independence(config)
    assert any("duplicate" in v.lower() for v in violations), \
        "'methodology' + 'Methodology' must be flagged as one lens, not two independent ones"


# 5. feasibility: a string "high" compute is penalized under a tight GPU budget
def test_feasibility_high_string_compute_penalized_under_budget():
    idea = {"idea_id": "X", "feasibility": {"compute": "high", "data": "available", "time": "short"}}
    with_budget = score_feasibility(idea, budget={"max_gpu_runs_before_review": 1})
    without = score_feasibility(idea)
    assert with_budget["score"] < without["score"], \
        "a 'high'-compute plan must be penalized by a tight budget (string form was skipped before)"


# 6. fairness: malformed (non-list-truthy) input fails closed, never crashes
def test_fairness_malformed_input_fails_closed():
    profile = {"split_policy": {"stratification_keys": ["anatomy"]}}
    v = check_fairness({"findings": 42}, run_records=99, profile=profile)   # would crash list(42) before
    assert isinstance(v, list) and len(v) >= 1
    assert isinstance(check_fairness(None, None, profile), list)            # None result_summary is safe too


# 7 & 8. figure tools: a non-numeric axis min ("auto") must not crash the advisory producers
def test_viz_audit_non_numeric_axis_min_no_crash():
    bundle = {"figures": [{"figure_id": "f1", "metrics": ["dice"], "y_axis": {"min": "auto"}}]}
    profile = {"metrics": [{"name": "dice", "valid_range": [0, 1]}]}
    assert check_viz_truncation(bundle, profile) == []   # must not raise float("auto")


def test_figure_critique_non_numeric_axis_min_no_crash():
    spec = {"figure_id": "f1", "figure_type": "bar", "y_axis": {"min": "auto"}}
    findings = critique_figure(spec)   # must not raise
    assert all(f["finding_type"] != "truncated_axis" for f in findings)
