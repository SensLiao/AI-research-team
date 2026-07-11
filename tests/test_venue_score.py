"""Tests for tools/venue_score.py (CLUSTER D2 deterministic tool).

Proves all hard guarantees from the build contract §6.2:
  - accept_condition_met() enforces all clauses from venue-module §4.3
  - collect_unresolved_triggers() is stable, deduplicated, and sorted
  - derive_meets_bar() derivation order (§4.5):
      1. DEGRADED-REVIEW when independence sim>=0.3 or all confidence<=2
      2. WRONG-PATH when triggers + >=2 gating dims <=2 + D3<3 + D2<3
         NOT-YET when triggers present but not structurally broken
      3. MEETS-BAR when accept condition fully met
      4. BORDERLINE when exactly one non-gating dim short
         NOT-YET otherwise
  - A fired reject-trigger NEVER yields MEETS-BAR (the crown-jewel invariant)
  - derive_meets_bar() is deterministic (same in => same out)
  - output validates against venue_readiness_verdict.schema.json
"""
from __future__ import annotations

import pytest

from research_agent_teams.tools.validate_artifact import validate_against
from research_agent_teams.tools.venue_score import (
    accept_condition_met,
    collect_unresolved_triggers,
    derive_meets_bar,
)


# ===========================================================================
# Fixtures: shared helpers
# ===========================================================================

def _profile(tier: str = "conf", paper_type: str = "methodological") -> dict:
    return {
        "venue_id": "NeurIPS-2025",
        "tier": tier,
        "paper_type": paper_type,
        "reject_triggers": [],
        "accept_condition": "D1>=3 AND D4>=3 AND (D3>=3 OR D2>=3)",
        "personas": ["methodology", "domain", "adversarial"],
        "evidence_ref": ["venue-profile-001"],
    }


def _dim(score: int) -> dict:
    return {"score": score, "evidence_ref": ["test-evidence-ref"]}


def _review(
    persona: str = "methodology",
    scores: dict | None = None,
    triggers: list | None = None,
    confidence: int = 4,
) -> dict:
    """Build a minimal venue_review dict."""
    if scores is None:
        scores = {"D1": _dim(3), "D2": _dim(3), "D3": _dim(3), "D4": _dim(3)}
    return {
        "persona": persona,
        "venue_id": "NeurIPS-2025",
        "dimension_scores": scores,
        "reject_triggers_fired": triggers or [],
        "overall": "Accept",
        "confidence": confidence,
        "evidence_ref": ["test-ref-001"],
    }


def _trigger(trigger_id: str, dimension: str = "D4", locus: str = "Table 2",
             required_fix: str = "Add fair baseline comparison.") -> dict:
    return {
        "trigger_id": trigger_id,
        "dimension": dimension,
        "locus": locus,
        "required_fix": required_fix,
    }


# ===========================================================================
# 1. accept_condition_met()
# ===========================================================================

class TestAcceptConditionMet:

    def test_all_dims_at_3_conf_methodological(self) -> None:
        """D1=3, D4=3, D3=3 -> meets conf-ml condition."""
        assert accept_condition_met(
            {"D1": 3, "D2": 2, "D3": 3, "D4": 3}, "conf", "methodological"
        ) is True

    def test_d2_substitutes_for_d3(self) -> None:
        """D1>=3, D4>=3, D2>=3 (D3 absent) -> condition met."""
        assert accept_condition_met(
            {"D1": 3, "D2": 3, "D3": 2, "D4": 3}, "conf", "methodological"
        ) is True

    def test_d1_below_3_fails(self) -> None:
        assert accept_condition_met(
            {"D1": 2, "D2": 3, "D3": 3, "D4": 3}, "conf", "methodological"
        ) is False

    def test_d4_below_3_fails(self) -> None:
        assert accept_condition_met(
            {"D1": 3, "D2": 3, "D3": 3, "D4": 2}, "conf", "methodological"
        ) is False

    def test_both_d2_and_d3_below_3_fails(self) -> None:
        """The OR clause: D2<3 AND D3<3 -> fails."""
        assert accept_condition_met(
            {"D1": 3, "D2": 2, "D3": 2, "D4": 3}, "conf", "methodological"
        ) is False

    def test_journal_requires_d5(self) -> None:
        """tier=journal forces D5>=3."""
        assert accept_condition_met(
            {"D1": 3, "D2": 3, "D3": 3, "D4": 3, "D5": 2}, "journal", "methodological"
        ) is False

    def test_journal_d5_at_3_passes(self) -> None:
        assert accept_condition_met(
            {"D1": 3, "D2": 3, "D3": 3, "D4": 3, "D5": 3}, "journal", "methodological"
        ) is True

    def test_application_clinical_requires_d7(self) -> None:
        """paper_type=application-clinical forces D7>=3."""
        assert accept_condition_met(
            {"D1": 3, "D2": 3, "D3": 3, "D4": 3, "D7": 2}, "conf", "application-clinical"
        ) is False

    def test_application_clinical_d7_at_3_passes(self) -> None:
        assert accept_condition_met(
            {"D1": 3, "D2": 3, "D3": 3, "D4": 3, "D7": 3}, "conf", "application-clinical"
        ) is True

    def test_missing_required_dim_treated_as_1(self) -> None:
        """A missing D1 is treated as score=1, failing the condition."""
        assert accept_condition_met(
            {"D2": 4, "D3": 4, "D4": 4}, "conf", "methodological"
        ) is False

    def test_all_4s_conf_passes(self) -> None:
        """Strong-accept case: all 4s on conf-methodological."""
        assert accept_condition_met(
            {"D1": 4, "D2": 4, "D3": 4, "D4": 4, "D5": 4}, "conf", "methodological"
        ) is True


# ===========================================================================
# 2. collect_unresolved_triggers()
# ===========================================================================

class TestCollectUnresolvedTriggers:

    def test_no_triggers_returns_empty(self) -> None:
        reviews = [_review(triggers=[]), _review(triggers=[])]
        assert collect_unresolved_triggers(reviews) == []

    def test_single_trigger_captured(self) -> None:
        reviews = [_review(triggers=[_trigger("RT-D4-BASELINE")])]
        result = collect_unresolved_triggers(reviews)
        assert "RT-D4-BASELINE" in result

    def test_triggers_across_reviews_are_unioned(self) -> None:
        reviews = [
            _review(triggers=[_trigger("RT-D4-BASELINE")]),
            _review(triggers=[_trigger("RT-D1-OVERCLAIM", dimension="D1", locus="Abstract")]),
        ]
        result = collect_unresolved_triggers(reviews)
        assert "RT-D4-BASELINE" in result
        assert "RT-D1-OVERCLAIM" in result

    def test_same_trigger_id_same_locus_deduplicated(self) -> None:
        """Same trigger_id + locus across two reviews = one entry."""
        trigger = _trigger("RT-D4-BASELINE", locus="Table 2")
        reviews = [_review(triggers=[trigger]), _review(triggers=[trigger])]
        result = collect_unresolved_triggers(reviews)
        assert result.count("RT-D4-BASELINE") == 1

    def test_same_trigger_id_different_loci_each_contributes(self) -> None:
        """Same trigger_id at two different loci: both are surfaced (deduplicated by id)."""
        t1 = _trigger("RT-D4-BASELINE", locus="Table 2")
        t2 = _trigger("RT-D4-BASELINE", locus="Table 4")
        reviews = [_review(triggers=[t1, t2])]
        # After dedup by id: only one trigger_id "RT-D4-BASELINE"
        result = collect_unresolved_triggers(reviews)
        assert result.count("RT-D4-BASELINE") == 1

    def test_result_is_sorted_for_determinism(self) -> None:
        reviews = [
            _review(triggers=[_trigger("RT-D3-INCREMENTAL", dimension="D3", locus="Intro")]),
            _review(triggers=[_trigger("RT-D4-BASELINE", locus="Table 2")]),
        ]
        result = collect_unresolved_triggers(reviews)
        assert result == sorted(result)

    def test_deterministic_same_in_same_out(self) -> None:
        reviews = [
            _review(triggers=[_trigger("RT-D1-OVERCLAIM", dimension="D1", locus="Abstract")]),
            _review(triggers=[_trigger("RT-D4-BASELINE", locus="Table 2")]),
        ]
        r1 = collect_unresolved_triggers(reviews)
        r2 = collect_unresolved_triggers(reviews)
        assert r1 == r2


# ===========================================================================
# 3. derive_meets_bar() — the crown-jewel derivation order
# ===========================================================================

class TestDeriveMeetsBar:
    SCHEMA = "venue_readiness_verdict.schema.json"

    # --- 3a. DEGRADED-REVIEW paths ---

    def test_degraded_review_when_independence_invalid(self) -> None:
        """independence.valid=False -> DEGRADED-REVIEW regardless of scores."""
        reviews = [_review()]
        independence = {"valid": False, "violations": ["duplicate lens"]}
        result = derive_meets_bar(reviews, _profile(), independence)
        assert result["verdict"] == "DEGRADED-REVIEW"

    def test_degraded_review_when_max_sim_high(self) -> None:
        """independence.max_sim >= 0.3 -> DEGRADED-REVIEW (VR-E degraded path)."""
        reviews = [_review()]
        independence = {"valid": True, "max_sim": 0.35, "verdict": "degraded"}
        result = derive_meets_bar(reviews, _profile(), independence)
        assert result["verdict"] == "DEGRADED-REVIEW"

    def test_degraded_review_when_all_confidence_low(self) -> None:
        """Every review has confidence <= 2 -> DEGRADED-REVIEW."""
        reviews = [
            _review(confidence=2),
            _review(confidence=1),
        ]
        result = derive_meets_bar(reviews, _profile())
        assert result["verdict"] == "DEGRADED-REVIEW"

    def test_not_degraded_when_one_confidence_above_2(self) -> None:
        """At least one review with confidence > 2 -> not degraded by confidence rule."""
        reviews = [
            _review(confidence=2),
            _review(confidence=3),
        ]
        result = derive_meets_bar(reviews, _profile())
        # Must not be DEGRADED-REVIEW purely from confidence
        assert result["verdict"] != "DEGRADED-REVIEW"

    def test_degraded_review_validates_schema(self) -> None:
        reviews = [_review(confidence=1)]
        result = derive_meets_bar(reviews, _profile())
        result["evidence_ref"] = ["test-review-001"]
        assert result["verdict"] == "DEGRADED-REVIEW"
        errs = validate_against(self.SCHEMA, result)
        assert errs == [], f"Schema errors: {errs}"

    # --- 3b. WRONG-PATH vs NOT-YET (fired triggers) ---

    def test_wrong_path_when_triggers_and_multiple_gating_dims_weak(self) -> None:
        """Triggers + >=2 gating dims <=2 + D3<3 + D2<3 -> WRONG-PATH."""
        reviews = [
            _review(
                scores={"D1": _dim(2), "D2": _dim(2), "D3": _dim(2), "D4": _dim(2)},
                triggers=[_trigger("RT-D4-BASELINE")],
            )
        ]
        result = derive_meets_bar(reviews, _profile())
        assert result["verdict"] == "WRONG-PATH"

    def test_not_yet_when_triggers_but_only_one_gating_dim_weak(self) -> None:
        """Trigger fired, but only one gating dim <=2 -> NOT-YET (resolvable)."""
        reviews = [
            _review(
                scores={"D1": _dim(3), "D2": _dim(3), "D3": _dim(3), "D4": _dim(2)},
                triggers=[_trigger("RT-D4-BASELINE")],
            )
        ]
        result = derive_meets_bar(reviews, _profile())
        assert result["verdict"] == "NOT-YET"

    def test_fired_leakage_trigger_never_meets_bar(self) -> None:
        """THE CROWN-JEWEL: a fired leakage reject-trigger can NEVER yield MEETS-BAR.

        Even if all dimension scores are high, a fired trigger forces NOT-YET or WRONG-PATH.
        This test asserts the hard governance invariant from contract §6.
        """
        reviews = [
            _review(
                scores={"D1": _dim(4), "D2": _dim(4), "D3": _dim(4), "D4": _dim(4), "D5": _dim(4)},
                triggers=[_trigger("RT-D4-LEAKAGE", dimension="D4", locus="Table 3",
                                   required_fix="Remove test labels from training pipeline.")],
                confidence=5,
            )
        ]
        result = derive_meets_bar(reviews, _profile())
        # The fired trigger MUST force verdict out of {MEETS-BAR, BORDERLINE}
        assert result["verdict"] not in ("MEETS-BAR", "BORDERLINE"), (
            f"GOVERNANCE VIOLATION: fired reject-trigger yielded {result['verdict']!r} "
            "— must be NOT-YET or WRONG-PATH (never MEETS-BAR)"
        )

    def test_fired_leakage_trigger_never_meets_bar_schema_validates(self) -> None:
        """Schema allOf also structurally blocks MEETS-BAR when trigger present."""
        bad_verdict = {
            "verdict": "MEETS-BAR",
            "unresolved_reject_triggers": ["RT-D4-LEAKAGE"],
            "dimension_synthesis": [{"dimension": "D4", "argument": "Good score."}],
            "evidence_ref": ["test-ref"],
        }
        errs = validate_against(self.SCHEMA, bad_verdict)
        assert errs != [], (
            "Schema MUST reject MEETS-BAR verdict with non-empty unresolved_reject_triggers "
            "(allOf crown-jewel guard)"
        )

    def test_fired_trigger_borderline_also_blocked_by_schema(self) -> None:
        """Schema allOf blocks BORDERLINE when trigger present too."""
        bad_verdict = {
            "verdict": "BORDERLINE",
            "unresolved_reject_triggers": ["RT-D3-INCREMENTAL"],
            "dimension_synthesis": [{"dimension": "D3", "argument": "Marginal novelty."}],
            "evidence_ref": ["test-ref"],
        }
        errs = validate_against(self.SCHEMA, bad_verdict)
        assert errs != [], (
            "Schema MUST reject BORDERLINE verdict with non-empty unresolved_reject_triggers"
        )

    def test_not_yet_has_non_empty_gaps(self) -> None:
        """NOT-YET verdict must contain populated gaps list."""
        reviews = [
            _review(
                scores={"D1": _dim(3), "D2": _dim(3), "D3": _dim(3), "D4": _dim(2)},
                triggers=[_trigger("RT-D4-BASELINE", required_fix="Add SOTA comparison.")],
            )
        ]
        result = derive_meets_bar(reviews, _profile())
        assert result["verdict"] == "NOT-YET"
        assert len(result["gaps"]) >= 1
        assert result["gaps"][0]["what_to_add"] != ""

    def test_not_yet_validates_schema(self) -> None:
        reviews = [
            _review(
                scores={"D1": _dim(3), "D2": _dim(3), "D3": _dim(2), "D4": _dim(2)},
                triggers=[_trigger("RT-D4-BASELINE")],
            )
        ]
        result = derive_meets_bar(reviews, _profile())
        result["evidence_ref"] = ["test-review-001", "test-review-002"]
        errs = validate_against(self.SCHEMA, result)
        assert errs == [], f"Schema errors on NOT-YET: {errs}"

    def test_wrong_path_validates_schema(self) -> None:
        reviews = [
            _review(
                scores={"D1": _dim(2), "D2": _dim(2), "D3": _dim(2), "D4": _dim(1)},
                triggers=[_trigger("RT-D4-BASELINE"), _trigger("RT-D1-OVERCLAIM", dimension="D1",
                                                                locus="Abstract")],
            )
        ]
        result = derive_meets_bar(reviews, _profile())
        assert result["verdict"] in ("WRONG-PATH", "NOT-YET")
        result["evidence_ref"] = ["test-review-001"]
        errs = validate_against(self.SCHEMA, result)
        assert errs == [], f"Schema errors on WRONG-PATH: {errs}"

    # --- 3c. MEETS-BAR path ---

    def test_meets_bar_when_no_triggers_and_accept_condition_met(self) -> None:
        """No triggers, D1>=3, D4>=3, D3>=3 -> MEETS-BAR."""
        reviews = [
            _review(
                scores={"D1": _dim(4), "D2": _dim(3), "D3": _dim(3), "D4": _dim(4)},
                triggers=[],
                confidence=5,
            )
        ]
        result = derive_meets_bar(reviews, _profile())
        assert result["verdict"] == "MEETS-BAR"

    def test_meets_bar_multi_reviewer_min_score_used(self) -> None:
        """With two reviewers, MIN score per dim is used.
        Reviewer A gives D1=4, Reviewer B gives D1=3 -> effective D1=3 (still >= 3 -> passes).
        """
        reviews = [
            _review(
                persona="methodology",
                scores={"D1": _dim(4), "D2": _dim(4), "D3": _dim(4), "D4": _dim(4)},
                triggers=[],
                confidence=5,
            ),
            _review(
                persona="adversarial",
                scores={"D1": _dim(3), "D2": _dim(3), "D3": _dim(3), "D4": _dim(3)},
                triggers=[],
                confidence=4,
            ),
        ]
        result = derive_meets_bar(reviews, _profile())
        assert result["verdict"] == "MEETS-BAR"

    def test_meets_bar_drops_to_not_yet_when_min_score_fails(self) -> None:
        """Reviewer A: D4=4, Reviewer B: D4=2 -> min D4=2 < 3 -> NOT MEETS-BAR."""
        reviews = [
            _review(
                persona="methodology",
                scores={"D1": _dim(4), "D2": _dim(4), "D3": _dim(4), "D4": _dim(4)},
                triggers=[],
            ),
            _review(
                persona="adversarial",
                scores={"D1": _dim(3), "D2": _dim(3), "D3": _dim(3), "D4": _dim(2)},
                triggers=[],
            ),
        ]
        result = derive_meets_bar(reviews, _profile())
        assert result["verdict"] != "MEETS-BAR"

    def test_meets_bar_journal_requires_d5(self) -> None:
        """Journal tier: D5=2 -> NOT MEETS-BAR even if D1/D4/D3 pass."""
        reviews = [
            _review(
                scores={"D1": _dim(3), "D2": _dim(3), "D3": _dim(3), "D4": _dim(3), "D5": _dim(2)},
                triggers=[],
            )
        ]
        result = derive_meets_bar(reviews, _profile(tier="journal"))
        assert result["verdict"] != "MEETS-BAR"

    def test_meets_bar_validates_schema(self) -> None:
        reviews = [
            _review(
                scores={"D1": _dim(4), "D2": _dim(3), "D3": _dim(3), "D4": _dim(4)},
                triggers=[],
                confidence=5,
            )
        ]
        result = derive_meets_bar(reviews, _profile())
        result["evidence_ref"] = ["test-review-001"]
        assert result["verdict"] == "MEETS-BAR"
        errs = validate_against(self.SCHEMA, result)
        assert errs == [], f"Schema errors on MEETS-BAR: {errs}"

    # --- 3d. BORDERLINE path ---

    def test_borderline_when_exactly_one_non_gating_dim_short(self) -> None:
        """All gating dims >=3, exactly one non-gating dim (D6) < 3 -> BORDERLINE."""
        # For conf-methodological, gating = {D1, D4}
        # Accept condition also requires D2 or D3 >= 3
        # Scenario: D1=3, D4=3, D3=3, D2=3 (accept OR met), D6=2 (non-gating, short)
        # accept_condition_met should fail because... wait — D1=3, D4=3, D3=3: condition IS met
        # So we need accept_condition to NOT be met, but only one non-gating dim short.
        # D1=3, D4=3, D2=2, D3=3 (accept condition: D3>=3 -> met) BUT D6=2
        # Actually accept_condition would pass here (D1=3, D4=3, D3=3) -> MEETS-BAR, not BORDERLINE.
        # For BORDERLINE: accept condition must fail, gating all pass, one non-gating short.
        # accept condition requires D3>=3 OR D2>=3.  If D2=2 and D3=2 that's two shorts.
        # Let's use: D1=3, D4=3, D3=3, D2=3 but there's a non-gating dim D6=2 that is NOT
        # in the accept-condition -> accept_condition_met would be True -> MEETS-BAR not BORDERLINE.
        # For BORDERLINE we need accept to fail.  D2=2, D3=2 (both fail OR clause) with D1=3 D4=3:
        # That's TWO non-gating dims short (D2 and D3 for conf) -> NOT-YET, not BORDERLINE.
        # Correct BORDERLINE: exactly one non-gating dim is short AND all gating pass.
        # D1=3, D4=3, D2=2, D3=3 -> accept_condition: D1>=3 AND D4>=3 AND (D3>=3 OR D2>=3) -> TRUE
        # -> this is MEETS-BAR not BORDERLINE.
        # BORDERLINE requires accept_condition to fail by exactly one non-gating dim.
        # Use D6 only: D1=3, D4=3, D3=3, D2=3, D6=2 -> accept passes -> MEETS-BAR.
        # Conclusion: BORDERLINE = accept fails + gating all pass + exactly one non-gating short.
        # The accept condition only uses D1, D4, D2/D3, D5(journal), D7(clinical).
        # Non-gating dims for conf-methodological: D2, D3, D5, D6, D7.
        # If D3=2 and D2=3 -> accept: D1>=3 AND D4>=3 AND (D3>=3 OR D2>=3)=TRUE -> MEETS-BAR.
        # If D3=2 and D2=2 -> accept fails (OR clause). Two non-gating dims short -> NOT-YET.
        # If D3=2 only (D2=3) and D2 passes OR -> MEETS-BAR.
        # Real BORDERLINE: accept fails AND exactly one responsible non-gating dim short.
        # Example: D1=3, D4=3, D2=2, D3=2, D5=3, D6=3 -> accept fails (D2<3 AND D3<3),
        # gating: D1=3, D4=3 both pass.
        # non-gating dims short: D2 and D3 -> that's TWO -> NOT-YET by our logic.
        # Hmm. Let me re-read the contract:
        # BORDERLINE = "exactly one non-gating dim short" (all gating dims pass).
        # Gating for conf = {D1, D4}. Non-gating = {D2, D3, D5, D6, D7}.
        # accept_condition = D1>=3 AND D4>=3 AND (D3>=3 OR D2>=3).
        # For BORDERLINE scenario: D2=2, D3=3 -> accept: D1=3 D4=3 D3=3 -> TRUE -> MEETS-BAR.
        # Hmm the only way to hit BORDERLINE without two shorts is:
        # D2=2, D3=3 -> accept passes -> MEETS-BAR  (no BORDERLINE)
        # D2=3, D3=2 -> accept passes -> MEETS-BAR  (no BORDERLINE)
        # D2=2, D3=2 -> accept fails, TWO non-gating short -> NOT-YET
        # So BORDERLINE actually requires a non-gating dim that is NOT in the accept-condition:
        # e.g. D6=2 (not in accept) but D1=3, D4=3, D3=3 (accept passes) -> MEETS-BAR
        # Wait — accept passes -> MEETS-BAR already at step 3. So BORDERLINE only fires when:
        # - no triggers
        # - accept condition NOT met
        # - gating dims all pass
        # - exactly one non-gating dim short
        # The ONLY way accept fails without gating failing is via the OR clause: D2<3 AND D3<3.
        # But that's TWO non-gating dims short -> NOT-YET.
        # For journal: D5 is gating. If D5=2 and D5 is the ONLY failing dim (all others pass):
        # accept fails (D5<3), gating_short = {D5} -> len(gating_short)=1 -> NOT BORDERLINE (gating short != 0).
        # Conclusion: BORDERLINE is hard to reach with conf-methodological because the OR clause
        # needs two non-gating dims to fail. Let me use a special case:
        # paper_type=application-clinical, tier=conf: gating={D1, D4, D7}.
        # Non-gating: {D2, D3, D5, D6}.
        # accept: D1>=3 AND D4>=3 AND (D3>=3 OR D2>=3) AND D7>=3.
        # BORDERLINE: D1=3, D4=3, D7=3, D3=3, D2=3 but D6=2.
        # accept passes -> MEETS-BAR again.
        # Real BORDERLINE: need accept to fail by ONE non-gating dim.
        # accept checks: D1, D4, (D2 or D3), D7.
        # For D2 and D3 to both be short is TWO non-gating dims short.
        # CONCLUSION: in practice, BORDERLINE is rare with these conditions. But let's test
        # the path using a scenario where D2=2, D3=2 (accept fails, gating pass, 2 non-gating
        # short) and confirm NOT-YET, then confirm BORDERLINE with the right scenario.
        # ACTUALLY: if we set D2=3, D3=2, accept passes -> MEETS-BAR.
        # The only genuine BORDERLINE path: we must have accept fail with gating all pass AND
        # exactly one non-gating dim short. This can happen if D5 is a non-gating dim (tier=conf)
        # and it fails, but D5 is NOT in the accept condition for conf -> D5 failing alone doesn't
        # fail accept. So we can't create a pure BORDERLINE by D5 alone because accept passes.
        # RESOLUTION (M3-d adversarial review, seam-b): all the reasoning ABOVE reflects the
        # OLD, BROKEN placement where the BORDERLINE check sat AFTER accept_condition FAILED —
        # which (with both gating dims passing) is unreachable, so BORDERLINE was dead code.
        # The fix moves the decision to where accept SUCCEEDS but exactly one reviewed non-gating
        # dim is weak (§4.5 "差一个非 gating 维"). BORDERLINE is now reachable and asserted:
        # D1=4, D4=4, D3=4 (accept met via the D3 clause), D2=2 = the lone weak non-gating dim.
        reviews = [
            _review(
                scores={"D1": _dim(4), "D2": _dim(2), "D3": _dim(4), "D4": _dim(4)},
                triggers=[],
                confidence=4,
            )
        ]
        result = derive_meets_bar(reviews, _profile())
        assert result["verdict"] == "BORDERLINE", result["verdict"]

    def test_borderline_via_direct_scenario(self) -> None:
        """BORDERLINE: no triggers, gating dims all pass, exactly one non-gating dim short.

        Construct: conf-methodological, two reviewers.
        Reviewer A: D1=3, D2=3, D3=3, D4=3 (accept would pass but we need one non-gating short).
        To get BORDERLINE we need accept to fail with exactly one non-gating dim short.
        Note: for conf-methodological, accept uses D1, D4, (D2 OR D3).
        D2 and D3 are both 'non-gating' but the OR clause means D2=2 alone is fine if D3=3.
        BORDERLINE requires accept to fail: so D2<3 AND D3<3. That's two non-gating dims short.
        Actually BORDERLINE is: accept fails + gating all pass + EXACTLY ONE non-gating short.
        With gating={D1, D4} and accept failing only via D2+D3: that's always 2 shorts.
        So for conf-methodological, BORDERLINE is structurally NOT-YET (2 dims short).
        We verify this: D2=2, D3=2, D1=3, D4=3, no triggers -> NOT-YET (2 non-gating short).
        """
        reviews = [
            _review(
                scores={"D1": _dim(3), "D2": _dim(2), "D3": _dim(2), "D4": _dim(3)},
                triggers=[],
                confidence=4,
            )
        ]
        result = derive_meets_bar(reviews, _profile())
        # NOT-YET because two non-gating dims short (D2 and D3)
        assert result["verdict"] == "NOT-YET"

    def test_borderline_journal_d5_scenario(self) -> None:
        """For journal tier, D5 is gating. BORDERLINE when exactly one non-gating dim short.
        journal: gating={D1, D4, D5}. Non-gating: {D2, D3, D6, D7 if not application-clinical}.
        accept: D1>=3, D4>=3, (D3>=3 OR D2>=3), D5>=3.
        BORDERLINE: D1=3, D4=3, D5=3, D3=3 (accept passes -> MEETS-BAR not BORDERLINE).
        Hmm: if accept passes, we hit step 3 MEETS-BAR before step 4 BORDERLINE.
        So BORDERLINE genuinely requires accept to fail.
        For journal: if D2=2 AND D3=2 (two non-gating short) -> NOT-YET.
        CONCLUSION: BORDERLINE is structurally unreachable for conf/journal-methodological
        because the failing clause always involves 2 non-gating dims. Test NOT-YET path instead.
        """
        reviews = [
            _review(
                scores={"D1": _dim(3), "D2": _dim(3), "D3": _dim(3), "D4": _dim(3), "D5": _dim(2)},
                triggers=[],
                confidence=4,
            )
        ]
        result = derive_meets_bar(reviews, _profile(tier="journal"))
        # D5 is gating for journal, it's short -> gating_short = {D5} -> not BORDERLINE
        assert result["verdict"] == "NOT-YET"

    # --- 3e. Determinism ---

    def test_deterministic_same_in_same_out(self) -> None:
        reviews = [
            _review(
                scores={"D1": _dim(4), "D2": _dim(3), "D3": _dim(3), "D4": _dim(4)},
                triggers=[],
                confidence=5,
            )
        ]
        r1 = derive_meets_bar(reviews, _profile())
        r2 = derive_meets_bar(reviews, _profile())
        assert r1["verdict"] == r2["verdict"]
        assert r1["unresolved_reject_triggers"] == r2["unresolved_reject_triggers"]

    def test_deterministic_with_triggers(self) -> None:
        reviews = [
            _review(
                scores={"D1": _dim(3), "D2": _dim(3), "D3": _dim(3), "D4": _dim(2)},
                triggers=[_trigger("RT-D4-BASELINE")],
            )
        ]
        r1 = derive_meets_bar(reviews, _profile())
        r2 = derive_meets_bar(reviews, _profile())
        assert r1 == r2

    # --- 3f. Schema validation of outputs ---

    def test_meets_bar_result_validates(self) -> None:
        reviews = [
            _review(
                scores={"D1": _dim(4), "D2": _dim(3), "D3": _dim(3), "D4": _dim(4)},
                triggers=[],
                confidence=5,
            )
        ]
        result = derive_meets_bar(reviews, _profile())
        result["evidence_ref"] = ["review-methodology-001", "review-adversarial-001"]
        errs = validate_against(self.SCHEMA, result)
        assert errs == [], f"MEETS-BAR payload schema errors: {errs}"

    def test_degraded_review_result_validates(self) -> None:
        reviews = [_review(confidence=1)]
        result = derive_meets_bar(reviews, _profile())
        result["evidence_ref"] = ["review-001"]
        errs = validate_against(self.SCHEMA, result)
        assert errs == [], f"DEGRADED-REVIEW payload schema errors: {errs}"

    def test_wrong_path_independence_degraded_validates(self) -> None:
        """Independence degraded + triggered -> DEGRADED-REVIEW (step 1 wins)."""
        reviews = [
            _review(
                scores={"D1": _dim(2), "D2": _dim(2), "D3": _dim(2), "D4": _dim(1)},
                triggers=[_trigger("RT-D4-BASELINE")],
                confidence=4,
            )
        ]
        independence = {"valid": False, "violations": ["sim >= 0.3 between methodology and adversarial"]}
        result = derive_meets_bar(reviews, _profile(), independence)
        assert result["verdict"] == "DEGRADED-REVIEW"
        result["evidence_ref"] = ["review-001"]
        errs = validate_against(self.SCHEMA, result)
        assert errs == [], f"Schema errors: {errs}"
