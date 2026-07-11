"""Deterministic integrity FLAGGER for the integrity-refusal-recommender (RECOMMENDATION-ONLY).

This tool surfaces a class of integrity risk the machine does NOT otherwise flag: an
**UNSUPPORTED NUMBER** — a claim that asserts a numeric result while carrying no evidence_ref.
It is the dual of the existing citation gates: `citation_existence` / `citation_checker` verify
that the refs a worker DID cite resolve and anchor their claims; this tool catches the case where a
numeric claim cites NOTHING at all (so those gates never see it). It also flags the honest-refusal
case (a result-asserting claim with no evidence whatsoever) and carries pre-computed fabricated-data
/ completion-pressure smells through into the recommendation.

HARD GOVERNANCE BOUNDARY — this is a FLAGGER, not an enforcer. `recommend()` maps flag severities to
an ADVISORY verdict (PROCEED / CAUTION / RECOMMEND_HALT). RECOMMEND_HALT is a *recommendation to a
human to pause for review* — it NEVER blocks, NEVER authorizes, NEVER self-decides. The director's
human gates remain the only deciders (constitution rule: the machine produces honest derived verdicts;
the decision to bet / publish / write the crown jewels is ALWAYS the director's).

Risk-flag kinds (aligned with integrity_recommendation.schema.json `risk_flags[].kind` enum):
  - "unsupported_number"        a numeric claim with no (non-blank) evidence_ref          [detected here]
  - "missing_evidence_refusal"  a result-asserting claim with NO evidence at all          [detected here]
  - "fabricated_data_smell"     a synthetic-data tell (caller-supplied; carried through)
  - "completion_pressure"       a hurried-to-finish tell (caller-supplied; carried through)

Severity to recommendation thresholds (documented, deterministic — see `recommend`):
  - any flag of severity "high"     -> "RECOMMEND_HALT"
  - else any flag of severity "medium" -> "CAUTION"
  - else any flag at all (only "low") -> "CAUTION"   (a flag, however minor, always warrants a look)
  - else (no flags)                 -> "PROCEED"

Pure function: no network, no clock, no random. Deterministic on the same input.
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional

# A numeric token: integers, decimals, percentages, and signed/grouped forms.
# Matches 0.87, 87%, 1,234, -3.2, 42 — enough to detect "this claim states a number".
_NUMBER_RE = re.compile(r"[-+]?\$?\d[\d,]*(?:\.\d+)?\s*%?")

# Severity ordering for the deterministic threshold mapping.
_SEVERITY_RANK: Dict[str, int] = {"low": 1, "medium": 2, "high": 3}

# Flag kinds this module DETECTS (the caller may also pass through fabricated_data_smell /
# completion_pressure flags, which are part of the schema enum but not derived from claim text here).
KIND_UNSUPPORTED_NUMBER = "unsupported_number"
KIND_MISSING_EVIDENCE_REFUSAL = "missing_evidence_refusal"

# Recommendation verdicts (ADVISORY — never an authorization).
PROCEED = "PROCEED"
CAUTION = "CAUTION"
RECOMMEND_HALT = "RECOMMEND_HALT"

# The invariant decision-authority marker (mirrors the schema const).
DECISION_AUTHORITY = "director-human-gate"


def _has_number(text: str) -> bool:
    """Return True if the text contains a numeric token (a stated quantity/result)."""
    return bool(_NUMBER_RE.search(text or ""))


def _has_evidence(claim: dict) -> bool:
    """Return True if the claim carries at least one NON-BLANK evidence_ref.

    Accepts evidence_ref as a list of strings (the project idiom) or a single string. A blank or
    whitespace-only ref does not count as evidence (anti-slop: an empty ref is not a citation).
    """
    refs = claim.get("evidence_ref")
    if refs is None:
        return False
    if isinstance(refs, str):
        return bool(refs.strip())
    if isinstance(refs, (list, tuple)):
        return any(isinstance(r, str) and r.strip() for r in refs)
    return False


def scan_unsupported_numbers(claims: List[dict]) -> List[dict]:
    """Flag numeric claims that lack an evidence_ref (the UNSUPPORTED-NUMBER risk).

    For each claim dict (expects at least ``claim_id`` and ``text``):
      - if the claim text states a number AND the claim has no non-blank evidence_ref
        -> emit an ``unsupported_number`` flag (severity "high": a quantitative result with no
           backing is the strongest unsupported-number signal).
      - if the claim text states NO number but ASSERTS A RESULT (a result-shaped claim, marked by
        ``asserts_result: True``) and has no evidence at all
        -> emit a ``missing_evidence_refusal`` flag (severity "medium": a result-asserting claim with
           no evidence should trigger an honest refusal rather than a confident answer).
      - a properly-cited claim (any non-blank evidence_ref) emits NO flag, regardless of numbers.

    Args:
        claims: List of claim dicts. Each should carry ``claim_id`` and ``text``; ``evidence_ref``
                (list[str] or str) when present is the citation. ``asserts_result`` (bool) optionally
                marks a result-shaped claim for the honest-refusal check.

    Returns:
        A list of risk-flag dicts, each shaped {kind, locus, severity, detail}, conforming to
        integrity_recommendation.schema.json risk_flags[]. Stable order = input order.

    This is a FLAGGER, not an enforcer: it never blocks and never decides — it only surfaces risks.
    """
    flags: List[dict] = []
    for claim in claims:
        if not isinstance(claim, dict):
            continue
        cid = str(claim.get("claim_id", "") or "?")
        text = str(claim.get("text", "") or "")
        has_evidence = _has_evidence(claim)

        if has_evidence:
            # A cited claim is not an unsupported-number risk (the citation gates own ref quality).
            continue

        if _has_number(text):
            flags.append({
                "kind": KIND_UNSUPPORTED_NUMBER,
                "locus": cid,
                "severity": "high",
                "detail": (
                    f"claim {cid!r} states a numeric result but carries no evidence_ref "
                    f"(unsupported number): {text[:80]!r}"
                ),
            })
        elif claim.get("asserts_result") is True:
            flags.append({
                "kind": KIND_MISSING_EVIDENCE_REFUSAL,
                "locus": cid,
                "severity": "medium",
                "detail": (
                    f"claim {cid!r} asserts a result with no evidence_ref — this should trigger an "
                    f"honest refusal rather than a confident answer: {text[:80]!r}"
                ),
            })
    return flags


def recommend(flags: List[dict]) -> str:
    """Map a list of risk flags to an ADVISORY recommendation via documented severity thresholds.

    Thresholds (deterministic, first match wins):
        - any flag of severity "high"   -> "RECOMMEND_HALT"  (recommend a human pause for review)
        - any flag of severity "medium" -> "CAUTION"
        - any flag at all (only "low")   -> "CAUTION"        (any flag warrants a human look)
        - no flags                       -> "PROCEED"

    RECOMMEND_HALT is the STRONGEST signal this function can emit: a RECOMMENDATION that a human pause
    and review — it is NOT an enforced stop, NOT an authorization, and NEVER blocks anything. The
    director's human gates remain the only deciders.

    Unknown/blank severities are treated as the lowest rank (they never escalate to RECOMMEND_HALT),
    so a malformed flag can never silently strengthen a recommendation.

    Args:
        flags: List of risk-flag dicts (each with a ``severity`` key).

    Returns:
        One of "PROCEED" / "CAUTION" / "RECOMMEND_HALT".
    """
    if not flags:
        return PROCEED
    max_rank = 0
    for flag in flags:
        sev = flag.get("severity", "") if isinstance(flag, dict) else ""
        max_rank = max(max_rank, _SEVERITY_RANK.get(sev, 0))
    if max_rank >= _SEVERITY_RANK["high"]:
        return RECOMMEND_HALT
    # Any flag present (medium, low, or even an unrecognised severity) -> CAUTION, never PROCEED.
    return CAUTION


def build_recommendation(
    recommendation_id: str,
    claims: List[dict],
    scanned_artifacts: Optional[List[str]] = None,
    extra_flags: Optional[List[dict]] = None,
) -> dict:
    """Assemble an integrity_recommendation payload from claims (+ optional carried-through flags).

    Combines the claim-derived flags (`scan_unsupported_numbers`) with any caller-supplied
    ``extra_flags`` (e.g. pre-computed fabricated_data_smell / completion_pressure tells), derives the
    advisory recommendation deterministically (`recommend`), and stamps the invariant
    ``decision_authority`` marker so the artifact is self-describing as advisory-only.

    Args:
        recommendation_id: Short unique id, e.g. "IR-001".
        claims: Claim dicts to scan for unsupported-number / honest-refusal risks.
        scanned_artifacts: Optional list of artifact locators this scan covered.
        extra_flags: Optional already-shaped risk-flag dicts to merge in (carried through verbatim;
                     claim-derived flags come first, then these, preserving order).

    Returns:
        A dict conforming to integrity_recommendation.schema.json. The recommendation is DERIVED from
        the flags — never set by hand — so a caller cannot soften RECOMMEND_HALT to PROCEED.

    This builds an ADVISORY recommendation only. It never authorizes, blocks, or self-decides.
    """
    derived = scan_unsupported_numbers(claims)
    flags: List[dict] = derived + list(extra_flags or [])
    rec = recommend(flags)

    if rec == RECOMMEND_HALT:
        rationale = (
            f"{len(flags)} integrity flag(s) found, at least one high-severity; recommending a human "
            f"pause for review (advisory — the director's human gate decides)."
        )
    elif rec == CAUTION:
        rationale = (
            f"{len(flags)} integrity flag(s) found; a human should weigh them before proceeding "
            f"(advisory only)."
        )
    else:
        rationale = "No integrity risks found in the scanned claims; nothing to pause for (advisory)."

    return {
        "recommendation_id": str(recommendation_id),
        "scanned_artifacts": list(scanned_artifacts or []),
        "risk_flags": flags,
        "recommendation": rec,
        "rationale": rationale,
        "decision_authority": DECISION_AUTHORITY,
    }
