"""M3-d integration: the VR-1 venue-readiness flow, proven through the REGISTERED schemas.

The crown jewels of the venue module:
  - a reviewer NEVER self-decides (venue_review has no verdict/meets_bar field — structural);
  - the readiness verdict is DERIVED by venue_score.py, never prose;
  - a fired, unresolved reject-trigger can NEVER yield MEETS-BAR (hard, derived + schema allOf);
  - independence degradation -> DEGRADED-REVIEW (no publication decision admissible).
This test exercises venue_score.derive_meets_bar and validates every payload via validate_payload.
"""
from __future__ import annotations

from research_agent_teams.tools import venue_score
from research_agent_teams.tools.validate_artifact import validate_payload


def _profile(tier: str = "conf", paper_type: str = "methodological") -> dict:
    """A schema-valid venue_profile scorecard."""
    p = {
        "venue_id": "NeurIPS-2025",
        "tier": tier,
        "paper_type": paper_type,
        "dimension_weights": {
            "D1": {"weight": 1.0, "gating": True},
            "D2": {"weight": 0.8},
            "D3": {"weight": 1.0},
            "D4": {"weight": 1.0, "gating": True},
            "D5": {"weight": 0.5},
            "D6": {"weight": 0.5},
            "D7": {"weight": 0.0},
        },
        "reject_triggers": [
            {"trigger_id": "RT-D4-BASELINE", "dimension": "D4",
             "description": "weak or unfair baseline / test-set tuning / leakage"},
        ],
        "accept_condition": "D1>=3 AND D4>=3 AND (D3>=3 OR D2>=3) AND no reject-trigger fire",
        "personas": ["methodology", "domain", "adversarial"],
        "evidence_ref": ["contribution_ledger:cl-1"],
    }
    assert validate_payload("venue_profile", p) == [], "fixture profile must be schema-valid"
    return p


def _review(persona: str, scores: dict, *, fired=None, confidence: int = 4,
            overall: str = "Weak Accept") -> dict:
    """A schema-valid venue_review. `scores` maps Dn -> int; `fired` is an optional trigger."""
    dimension_scores = {
        d: {"score": s, "evidence_ref": [f"eval.py:{d}"]} for d, s in scores.items()
    }
    r = {
        "persona": persona,
        "venue_id": "NeurIPS-2025",
        "dimension_scores": dimension_scores,
        "reject_triggers_fired": fired or [],
        "overall": overall,
        "confidence": confidence,
        "evidence_ref": ["review:" + persona],
    }
    assert validate_payload("venue_review", r) == [], "fixture review must be schema-valid"
    return r


def test_reviewer_cannot_self_decide():
    """A venue_review carrying a meets_bar / verdict field is schema-REJECTED."""
    r = _review("methodology", {"D1": 4, "D4": 4, "D3": 4})
    bad = dict(r, meets_bar="yes")
    assert validate_payload("venue_review", bad) != [], "a self-decision field must be rejected"
    bad2 = dict(r, verdict="MEETS-BAR")
    assert validate_payload("venue_review", bad2) != []


def test_fired_reject_trigger_can_never_meet_bar():
    """Even with strong scores, a fired unresolved reject-trigger forbids MEETS-BAR (derived + schema)."""
    fired = [{"trigger_id": "RT-D4-BASELINE", "dimension": "D4",
              "locus": "Table 2 baseline", "required_fix": "re-run against a tuned, fair baseline"}]
    reviews = [
        _review("methodology", {"D1": 4, "D2": 4, "D3": 4, "D4": 4}),
        _review("adversarial", {"D1": 4, "D2": 4, "D3": 4, "D4": 4}, fired=fired, overall="Reject"),
    ]
    verdict = venue_score.derive_meets_bar(reviews, _profile())
    assert verdict["verdict"] in ("NOT-YET", "WRONG-PATH")
    assert verdict["verdict"] != "MEETS-BAR"
    assert "RT-D4-BASELINE" in verdict["unresolved_reject_triggers"]
    assert validate_payload("venue_readiness_verdict", verdict) == []
    # the gap names the responsible stage to route back to (not a patch)
    assert verdict["gaps"] and verdict["gaps"][0]["stage"]


def test_clean_strong_reviews_meet_bar():
    reviews = [
        _review("methodology", {"D1": 4, "D2": 3, "D3": 4, "D4": 4}, overall="Accept"),
        _review("domain", {"D1": 3, "D2": 4, "D3": 3, "D4": 3}, overall="Weak Accept"),
    ]
    verdict = venue_score.derive_meets_bar(reviews, _profile())
    assert verdict["verdict"] == "MEETS-BAR"
    assert verdict["unresolved_reject_triggers"] == []
    assert validate_payload("venue_readiness_verdict", verdict) == []


def test_degraded_independence_blocks_a_publication_verdict():
    reviews = [
        _review("methodology", {"D1": 4, "D2": 4, "D3": 4, "D4": 4}),
        _review("adversarial", {"D1": 4, "D2": 4, "D3": 4, "D4": 4}),
    ]
    independence = {"max_sim": 0.42, "valid": False}   # reviews not independent (echo chamber)
    verdict = venue_score.derive_meets_bar(reviews, _profile(), independence=independence)
    assert verdict["verdict"] == "DEGRADED-REVIEW"
    assert validate_payload("venue_readiness_verdict", verdict) == []


def test_journal_tier_forces_reproducibility_gate():
    """tier=journal makes D5 gating: strong D1/D3/D4 but weak D5 cannot MEETS-BAR."""
    reviews = [
        _review("methodology", {"D1": 4, "D2": 4, "D3": 4, "D4": 4, "D5": 2}, overall="Major Revision"),
    ]
    verdict = venue_score.derive_meets_bar(reviews, _profile(tier="journal"))
    assert verdict["verdict"] != "MEETS-BAR"
    assert validate_payload("venue_readiness_verdict", verdict) == []


def test_borderline_is_reachable():
    """Seam (b) (HIGH): BORDERLINE must be a REACHABLE verdict, not dead code (a dead verdict =
    a dead gate). It fires when the accept-condition IS met (both gating dims pass + the D2/D3
    clause holds) but exactly one reviewed non-gating dimension is weak — §4.5 "差一个非 gating 维"."""
    # conf-methodological, gating={D1,D4}. D1=4,D4=4,D3=4 (accept met via D3); D2=2 is the lone
    # weak non-gating dim -> BORDERLINE, not MEETS-BAR (the work is close, one dim shy).
    reviews = [
        _review("methodology", {"D1": 4, "D2": 2, "D3": 4, "D4": 4}, overall="Borderline"),
    ]
    verdict = venue_score.derive_meets_bar(reviews, _profile())
    assert verdict["verdict"] == "BORDERLINE", verdict["verdict"]
    assert verdict["unresolved_reject_triggers"] == []
    assert validate_payload("venue_readiness_verdict", verdict) == []
    # and an all-strong panel is still cleanly MEETS-BAR (BORDERLINE didn't swallow it)
    strong = [_review("methodology", {"D1": 4, "D2": 4, "D3": 4, "D4": 4})]
    assert venue_score.derive_meets_bar(strong, _profile())["verdict"] == "MEETS-BAR"


def test_independence_degraded_by_either_report_shape():
    """de-F3 regression: the tool honours BOTH independence shapes — the {verdict:'degraded'}
    label (no max_sim) AND a per-pair sim>=0.3 (no max_sim). Either forces DEGRADED-REVIEW so a
    refactor cannot silently drop one branch (an echo-chamber panel must never reach a verdict)."""
    reviews = [
        _review("methodology", {"D1": 4, "D2": 4, "D3": 4, "D4": 4}),
        _review("adversarial", {"D1": 4, "D2": 4, "D3": 4, "D4": 4}),
    ]
    by_label = venue_score.derive_meets_bar(reviews, _profile(), independence={"verdict": "degraded"})
    assert by_label["verdict"] == "DEGRADED-REVIEW"
    by_pair = venue_score.derive_meets_bar(
        reviews, _profile(), independence={"pairs": [{"a": "r1", "b": "r2", "sim": 0.41}]})
    assert by_pair["verdict"] == "DEGRADED-REVIEW"
    assert validate_payload("venue_readiness_verdict", by_label) == []
    assert validate_payload("venue_readiness_verdict", by_pair) == []
