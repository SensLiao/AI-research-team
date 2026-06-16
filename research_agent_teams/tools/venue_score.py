"""Deterministic venue-readiness score derivation (VERIFY stage, CLUSTER D2).

Computes the venue readiness verdict from 7-dim scores + reject-triggers + independence
information gathered from multiple blind review artifacts.  This tool is the single source
of truth for the derivation order defined in venue-review-module §4.5:

    1. DEGRADED-REVIEW  — independence sim >= 0.3 OR every review has confidence <= 2
    2. WRONG-PATH       — unresolved reject-trigger(s) AND >= 2 gating dims have min score
                          <= 2 AND D3 < 3 AND D2 < 3 (structural weakness, not just a fix gap)
       NOT-YET          — unresolved reject-trigger(s) (resolvable by adding experiments)
    3. MEETS-BAR        — accept_condition_met() with MIN scores across reviews
    4. BORDERLINE       — exactly ONE non-gating dim is short (all gating dims pass, but one
                          non-essential dim is below 3)
       NOT-YET          — more than one dim short or gating dim short

The area-chair-synthesizer calls derive_meets_bar() to get the payload, then emits the
venue_readiness_verdict artifact.  The allOf in the schema is a structural redundancy guard —
the verdict is computed here, never set by hand.

GATING DIMS (per rubric): D1, D4 are always gating.  D5 is gating when tier == "journal".
D7 is gating when paper_type == "application-clinical".

MISSING DIMENSION POLICY: a dimension absent from all reviews is treated as score = 1
(failing that clause) when it is required by the accept-condition.  This is documented so
callers are not surprised.
"""
from __future__ import annotations

from typing import List, Optional


# ---------------------------------------------------------------------------
# Gating dimension helpers
# ---------------------------------------------------------------------------

def _gating_dims(tier: str, paper_type: str) -> set:
    """Return the set of dimension keys that are gating for this venue configuration."""
    gating = {"D1", "D4"}
    if tier == "journal":
        gating.add("D5")
    if paper_type == "application-clinical":
        gating.add("D7")
    return gating


def _min_score_per_dim(reviews: List[dict]) -> dict:
    """Return {dim -> min_score} across all reviews (most-critical perspective).

    A dimension absent from every review is treated as score 1 (worst-case,
    conservative — missing evidence cannot be assumed good).
    """
    scores: dict = {}
    for review in reviews:
        dim_scores = review.get("dimension_scores") or {}
        for dim, ds in dim_scores.items():
            if isinstance(ds, dict):
                s = ds.get("score")
                if isinstance(s, int):
                    if dim not in scores:
                        scores[dim] = s
                    else:
                        scores[dim] = min(scores[dim], s)
    return scores


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def accept_condition_met(dim_scores: dict, tier: str, paper_type: str) -> bool:
    """Return True iff the accept-condition from venue-review-module §4.3 is fully met.

    Conditions (all must hold):
      D1 >= 3
      D4 >= 3
      D3 >= 3 OR D2 >= 3
      tier == "journal"  =>  D5 >= 3
      paper_type == "application-clinical"  =>  D7 >= 3

    Parameters
    ----------
    dim_scores : dict
        Mapping of dim key (e.g. "D1") to integer score.  Missing keys are treated as
        score = 1 (fail) because absent evidence cannot be treated as passing evidence.
    tier : str
        Venue tier: one of "conf", "med", "journal".
    paper_type : str
        Paper type: one of "methodological", "application-clinical".

    Returns
    -------
    bool
        True if every clause passes.
    """
    def _s(dim: str) -> int:
        return dim_scores.get(dim, 1)  # missing = 1 (fail)

    if _s("D1") < 3:
        return False
    if _s("D4") < 3:
        return False
    if _s("D3") < 3 and _s("D2") < 3:
        return False
    if tier == "journal" and _s("D5") < 3:
        return False
    if paper_type == "application-clinical" and _s("D7") < 3:
        return False
    return True


def collect_unresolved_triggers(reviews: List[dict]) -> List[str]:
    """Return a stable, deduplicated list of trigger IDs from all fired reject-triggers.

    Deduplication key is trigger_id + ":" + locus (so the same trigger firing at
    different loci is counted once per locus, consistent with area-chair practice).
    The returned list is sorted for determinism.

    Parameters
    ----------
    reviews : List[dict]
        List of venue_review payload dicts.

    Returns
    -------
    List[str]
        Sorted, deduplicated trigger_id strings (without locus suffix — the unique
        trigger IDs surfaced in the unresolved list).
    """
    seen: set = set()
    result: list = []
    for review in reviews:
        for trigger in (review.get("reject_triggers_fired") or []):
            trigger_id = trigger.get("trigger_id", "")
            # A blank trigger_id cannot be surfaced (it would fail the venue_readiness_verdict
            # \S pattern and is unreachable from a valid venue_review anyway) — skip defensively
            # so a malformed upstream cannot inject an empty unresolved entry (M3-b review F6).
            if not (isinstance(trigger_id, str) and trigger_id.strip()):
                continue
            locus = trigger.get("locus", "")
            key = f"{trigger_id}:{locus}"
            if key not in seen:
                seen.add(key)
                result.append(trigger_id)
    # Stable, deduplicated by trigger_id (keep first occurrence order, then sort)
    # Final output: unique trigger IDs, sorted for determinism
    unique_sorted = sorted(set(result))
    return unique_sorted


def derive_meets_bar(
    reviews: List[dict],
    profile: dict,
    independence: Optional[dict] = None,
) -> dict:
    """Derive the venue_readiness_verdict payload from reviews + profile + independence.

    Derivation order (venue-review-module §4.5):
      1. DEGRADED-REVIEW  — independence sim >= 0.3 OR all reviews have confidence <= 2
      2. (Unresolved triggers exist) ->
         WRONG-PATH if >= 2 gating dims have min score <= 2 AND D3 < 3 AND D2 < 3
         else NOT-YET
      3. accept_condition_met() -> MEETS-BAR
      4. Exactly one non-gating dim short -> BORDERLINE
         else NOT-YET

    Parameters
    ----------
    reviews : List[dict]
        List of venue_review payload dicts from the blind review panel.
    profile : dict
        venue_profile payload (provides tier, paper_type, reject_triggers,
        accept_condition).
    independence : Optional[dict]
        Output of check_review_independence.build_report().  If provided, a
        ``valid=False`` or a pair with ``sim >= 0.3`` triggers DEGRADED-REVIEW.

    Returns
    -------
    dict
        venue_readiness_verdict payload (ready for schema validation).
    """
    tier = profile.get("tier", "conf")
    paper_type = profile.get("paper_type", "methodological")
    gating = _gating_dims(tier, paper_type)
    min_scores = _min_score_per_dim(reviews)

    # Step 1: DEGRADED-REVIEW check
    degraded = False
    if independence is not None:
        # check_review_independence returns {valid, violations} but the venue module's VR-E
        # script emits {pairs: [{a,b,sim}], max_sim, verdict}. Honour BOTH shapes fully, incl.
        # the explicit verdict label AND any per-pair sim >= 0.3 (an echo-chamber panel must
        # never reach a publication verdict — defence in depth, the M3-b review de-F3).
        if not independence.get("valid", True):
            degraded = True
        if independence.get("verdict") == "degraded":
            degraded = True
        max_sim = independence.get("max_sim")
        if isinstance(max_sim, (int, float)) and max_sim >= 0.3:
            degraded = True
        for pair in (independence.get("pairs") or []):
            sim = pair.get("sim") if isinstance(pair, dict) else None
            if isinstance(sim, (int, float)) and sim >= 0.3:
                degraded = True

    all_low_confidence = bool(reviews) and all(
        (r.get("confidence") or 5) <= 2 for r in reviews
    )
    if all_low_confidence:
        degraded = True

    if degraded:
        return _build_payload(
            verdict="DEGRADED-REVIEW",
            unresolved=collect_unresolved_triggers(reviews),
            reviews=reviews,
            min_scores=min_scores,
            profile=profile,
        )

    # Step 2: Reject-trigger check
    unresolved = collect_unresolved_triggers(reviews)
    if unresolved:
        # WRONG-PATH: >= 2 gating dims with min score <= 2 AND D3 < 3 AND D2 < 3
        gating_weak = sum(1 for d in gating if min_scores.get(d, 1) <= 2)
        d2 = min_scores.get("D2", 1)
        d3 = min_scores.get("D3", 1)
        if gating_weak >= 2 and d3 < 3 and d2 < 3:
            verdict = "WRONG-PATH"
        else:
            verdict = "NOT-YET"
        return _build_payload(
            verdict=verdict,
            unresolved=unresolved,
            reviews=reviews,
            min_scores=min_scores,
            profile=profile,
        )

    # Step 3: Accept condition met -> MEETS-BAR, REFINED to BORDERLINE when exactly one
    # REVIEWED non-gating dimension is weak (<3). This is the §4.5 "差一个非 gating 维" case
    # (e.g. D6=2 clarity, or D2 significance weak while D3 novelty carries the accept clause).
    #
    # WHY the check lives here and not below: BORDERLINE was previously placed AFTER
    # accept_condition_met *failed* — but with both gating dims (D1,D4,+journal D5,+clinical D7)
    # passing, accept can only fail via the (D3>=3 OR D2>=3) clause, i.e. BOTH D2<3 AND D3<3,
    # which is always >=2 non-gating shorts. So the old "exactly one non-gating short" branch
    # was unreachable dead code (a dead verdict = a dead gate; M3-d review seam-b). The borderline
    # case is genuinely "accept is met but one non-essential dim is weak", so it is decided here.
    if accept_condition_met(min_scores, tier, paper_type):
        non_gating_short = [
            d for d in min_scores  # only dimensions that were ACTUALLY reviewed
            if d not in gating and min_scores[d] < 3
        ]
        verdict = "BORDERLINE" if len(non_gating_short) == 1 else "MEETS-BAR"
        return _build_payload(
            verdict=verdict,
            unresolved=[],
            reviews=reviews,
            min_scores=min_scores,
            profile=profile,
        )

    # Step 4: accept condition not met, no reject-trigger fired -> NOT-YET (needs strengthening
    # before it is venue-ready; the gaps list points at the responsible stage).
    return _build_payload(
        verdict="NOT-YET",
        unresolved=[],
        reviews=reviews,
        min_scores=min_scores,
        profile=profile,
    )


# ---------------------------------------------------------------------------
# Internal payload builder
# ---------------------------------------------------------------------------

def _build_payload(
    verdict: str,
    unresolved: List[str],
    reviews: List[dict],
    min_scores: dict,
    profile: dict,
) -> dict:
    """Assemble the venue_readiness_verdict payload dict (minus evidence_ref and
    independence_ref — those are bound by the calling agent from real artifact paths)."""
    tier = profile.get("tier", "conf")
    paper_type = profile.get("paper_type", "methodological")

    # Build dimension_synthesis: one entry per dim that appears in any review
    dims_seen: list = []
    seen_set: set = set()
    for review in reviews:
        for dim in (review.get("dimension_scores") or {}).keys():
            if dim not in seen_set:
                seen_set.add(dim)
                dims_seen.append(dim)
    dims_seen_sorted = sorted(dims_seen)  # stable order D1..D7

    dimension_synthesis = []
    for dim in dims_seen_sorted:
        scores_for_dim = [
            (r.get("dimension_scores") or {}).get(dim, {}).get("score")
            for r in reviews
            if isinstance((r.get("dimension_scores") or {}).get(dim, None), dict)
        ]
        scores_for_dim = [s for s in scores_for_dim if isinstance(s, int)]
        min_s = min(scores_for_dim) if scores_for_dim else None
        personas = [r.get("persona", "unknown") for r in reviews]
        argument = (
            f"Min score across {personas} reviewers: {min_s}/4 "
            f"(most-critical perspective used per derivation policy)."
        )
        entry: dict = {"dimension": dim, "argument": argument}
        if min_s is not None:
            entry["agreed_score"] = min_s
        dimension_synthesis.append(entry)

    payload: dict = {
        "verdict": verdict,
        "unresolved_reject_triggers": unresolved,
        "dimension_synthesis": dimension_synthesis,
        "gaps": [],
        "strengths": [],
        "shore_up": [],
        "evidence_ref": ["<bound-by-area-chair-synthesizer>"],
    }

    # Populate gaps for NOT-YET / WRONG-PATH
    if verdict in ("NOT-YET", "WRONG-PATH"):
        gaps = []
        for trigger_id in unresolved:
            # Find the first matching trigger entry across reviews for locus + required_fix
            locus = ""
            required_fix = ""
            for review in reviews:
                for t in (review.get("reject_triggers_fired") or []):
                    if t.get("trigger_id") == trigger_id and not locus:
                        locus = t.get("locus", "")
                        required_fix = t.get("required_fix", "")
            stage_hint = _stage_hint(trigger_id)
            gaps.append({
                "gap": f"{trigger_id}: {locus}" if locus else trigger_id,
                "stage": stage_hint,
                "what_to_add": required_fix if required_fix else f"Resolve {trigger_id}.",
            })
        payload["gaps"] = gaps

    # Populate strengths/shore_up for MEETS-BAR / BORDERLINE
    if verdict in ("MEETS-BAR", "BORDERLINE"):
        gating = _gating_dims(tier, paper_type)
        strong_dims = [
            d for d in ["D1", "D2", "D3", "D4", "D5", "D6", "D7"]
            if min_scores.get(d, 1) >= 4
        ]
        payload["strengths"] = [f"{d}=4 (excellent)" for d in strong_dims]
        weak_dims = [
            d for d in ["D1", "D2", "D3", "D4", "D5", "D6", "D7"]
            if 2 <= min_scores.get(d, 1) <= 2
        ]
        payload["shore_up"] = [f"Strengthen {d} (currently fair=2)" for d in weak_dims]

    return payload


def _stage_hint(trigger_id: str) -> str:
    """Map a trigger_id prefix to a responsible research stage."""
    tid = trigger_id.upper()
    if "D4" in tid or "BASELINE" in tid or "LEAKAGE" in tid or "EVAL" in tid:
        return "S3-EXECUTE / S4-ANALYZE (evaluation redesign)"
    if "D1" in tid or "OVERCLAIM" in tid or "INVALID" in tid:
        return "S2-DESIGN / S4-ANALYZE (claims realignment)"
    if "D5" in tid or "REPRO" in tid:
        return "S3-EXECUTE (reproducibility package)"
    if "D3" in tid or "INCREMENTAL" in tid:
        return "S2-DESIGN (method novelty)"
    if "D7" in tid or "CLINICAL" in tid:
        return "S3-EXECUTE (clinical validation)"
    if "ETHICS" in tid:
        return "S2-DESIGN (ethics/compliance)"
    return "S2-DESIGN / S3-EXECUTE"
