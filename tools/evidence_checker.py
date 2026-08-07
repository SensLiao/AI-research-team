"""Deterministic core of the evidence-verifier (hard gate).

Two-tier discipline: a deterministic thin-evidence test runs FIRST and can refuse on its own; only
evidence that clears the mechanical floor is worth an LLM's judgement. The LLM agent gathers and
grades the sources (the evidence_table); this checker — not the LLM — decides PASS/BLOCK, so a
release-grade conclusion can never rest on an unsaturated or too-thin evidence base.

Mechanical floor (domain-general):
  1. enough sources at all          (n_sources >= min_sources)   -> BLOCK
  2. at least some STRONG support   (n_strong  >= min_strong)    -> BLOCK
  3. snowball search saturated      (no obvious missed-evidence risk) -> WARNING (see below)
Thresholds default conservatively and may be tightened (never silently loosened) by the active
profile's `evidence_thresholds`; the profile's `evidence_invariants` are recorded for the auditor.

Saturation is a WARNING, not a BLOCK (director lock 2026-08-07). In the legacy contract path the
worker copied `saturation_reached: true` straight out of its own prompt skeleton and this gate
accepted it, so for its whole life the check verified nothing while being able to halt a run. The
honest fix is measurement, not enforcement: `saturation_reached` is now DERIVED by
`tools/saturation_meter.py` from the worker's recorded retrieval rounds (a single round reports
INSUFFICIENT_DATA and never SATURATED), and an unsaturated search is reported to the director instead
of stopping the run. The CURRENT evidence contract (`evidence-table/v2` / source-methodology /
search-trace) is untouched: its `semantic_complete` path still BLOCKs, because that one is really
verified.
"""
from __future__ import annotations

from typing import List, Optional, Tuple

from .evidence_search_trace import SEARCH_TRACE_VERSION, evaluate_search_trace
from .source_methodology_audit import QUALITY_CONTRACT_VERSION, audit_source_quality_report

DEFAULTS = {"min_sources": 3, "min_strong": 1, "require_saturation": True}


def _thresholds(profile: Optional[dict], override: Optional[dict]) -> dict:
    cfg = dict(DEFAULTS)
    cfg.update((profile or {}).get("evidence_thresholds") or {})
    cfg.update(override or {})
    return cfg


def check_evidence(
    table: dict,
    profile: Optional[dict] = None,
    thresholds: Optional[dict] = None,
    *,
    source_quality_report: Optional[dict] = None,
    search_trace: Optional[dict] = None,
    strict_current: bool = False,
) -> Tuple[List[str], dict]:
    """Return (reasons, facts). Empty reasons == evidence clears the mechanical floor.

    ``facts["warnings"]`` carries advisory findings that are REPORTED but do not block — currently the
    legacy-contract saturation read. They are facts about the evidence base the director should see,
    not grounds to halt a run (see the module docstring for why saturation moved here).
    """
    cfg = _thresholds(profile, thresholds)
    sources = table.get("sources", []) or []
    n = len(sources)
    uses_current_contract = bool(
        strict_current
        or table.get("evidence_contract_version") == "evidence-table/v2"
        or (source_quality_report or {}).get("quality_contract_version") == QUALITY_CONTRACT_VERSION
        or (search_trace or {}).get("search_contract_version") == SEARCH_TRACE_VERSION
    )
    quality_audit = audit_source_quality_report(source_quality_report, table)
    search_audit = evaluate_search_trace(search_trace)
    if uses_current_contract:
        n_strong = int(quality_audit.get("n_high") or 0)
        sat = search_audit.get("status") == "COMPLETE"
    else:
        n_strong = sum(1 for s in sources if s.get("claim_support") == "strong")
        sat = bool(table.get("saturation_reached", False))

    reasons: List[str] = []
    if uses_current_contract:
        if quality_audit.get("contract_status") != "CURRENT":
            reasons.append("current evidence requires source-methodology/v1; legacy source quality is unverified")
        elif quality_audit.get("audit_status") != "PASS":
            reasons.extend(
                f"source methodology audit: {reason}"
                for reason in quality_audit.get("reasons") or ["incomplete"]
            )
        search_status = str(search_audit.get("status") or "INCOMPLETE")
        if search_status != "COMPLETE":
            reasons.append(f"semantic evidence search is {search_status}")
            reasons.extend(
                f"search trace: {reason}" for reason in search_audit.get("reasons") or []
            )
    if n < cfg["min_sources"]:
        reasons.append(f"too few sources: {n} < required {cfg['min_sources']}")
    if n_strong < cfg["min_strong"]:
        reasons.append(f"too few strong-support sources: {n_strong} < required {cfg['min_strong']}")
    warnings: List[str] = []
    if cfg["require_saturation"] and not sat:
        # ADVISORY, not a block. Under the CURRENT contract this mirrors the search-trace status,
        # which already blocks above on its own evidence; under the legacy contract the flag used to
        # be self-declared by the worker, so blocking on it enforced nothing.
        warnings.append(
            "snowball saturation not reached (search may have missed key counter-evidence) — "
            "measured from the recorded retrieval rounds, advisory only")
    return reasons, {"n_sources": n, "n_strong": n_strong, "saturation_reached": sat,
                     "warnings": warnings}


def build_verdict(
    table: dict,
    profile: Optional[dict] = None,
    thresholds: Optional[dict] = None,
    *,
    source_quality_report: Optional[dict] = None,
    search_trace: Optional[dict] = None,
    strict_current: bool = False,
) -> dict:
    """Build an evidence_verdict payload (verdict derived from the floor checks, never set by hand).

    The payload keeps the `evidence_verdict` contract exactly as-is; the advisory saturation finding
    is visible through the `saturation_reached` field it already carries. A caller that wants the
    warning text calls `check_evidence` directly and reads `facts["warnings"]`.
    """
    reasons, facts = check_evidence(
        table,
        profile,
        thresholds,
        source_quality_report=source_quality_report,
        search_trace=search_trace,
        strict_current=strict_current,
    )
    return {
        "verdict": "BLOCK" if reasons else "PASS",
        "reasons": reasons,
        "tier": "deterministic",
        "n_sources": facts["n_sources"],
        "n_strong": facts["n_strong"],
        "saturation_reached": facts["saturation_reached"],
        "checked_invariants": list((profile or {}).get("evidence_invariants", [])),
    }
