"""Deterministic core of the evidence-verifier (hard gate).

Two-tier discipline: a deterministic thin-evidence test runs FIRST and can refuse on its own; only
evidence that clears the mechanical floor is worth an LLM's judgement. The LLM agent gathers and
grades the sources (the evidence_table); this checker — not the LLM — decides PASS/BLOCK, so a
release-grade conclusion can never rest on an unsaturated or too-thin evidence base.

Mechanical floor (domain-general):
  1. enough sources at all          (n_sources >= min_sources)
  2. at least some STRONG support   (n_strong  >= min_strong)
  3. snowball search saturated      (no obvious missed-evidence risk)
Thresholds default conservatively and may be tightened (never silently loosened) by the active
profile's `evidence_thresholds`; the profile's `evidence_invariants` are recorded for the auditor.
"""
from __future__ import annotations

from typing import List, Optional, Tuple

DEFAULTS = {"min_sources": 3, "min_strong": 1, "require_saturation": True}


def _thresholds(profile: Optional[dict], override: Optional[dict]) -> dict:
    cfg = dict(DEFAULTS)
    cfg.update((profile or {}).get("evidence_thresholds") or {})
    cfg.update(override or {})
    return cfg


def check_evidence(table: dict, profile: Optional[dict] = None,
                   thresholds: Optional[dict] = None) -> Tuple[List[str], dict]:
    """Return (reasons, facts). Empty reasons == evidence clears the mechanical floor."""
    cfg = _thresholds(profile, thresholds)
    sources = table.get("sources", []) or []
    n = len(sources)
    n_strong = sum(1 for s in sources if s.get("claim_support") == "strong")
    sat = bool(table.get("saturation_reached", False))

    reasons: List[str] = []
    if n < cfg["min_sources"]:
        reasons.append(f"too few sources: {n} < required {cfg['min_sources']}")
    if n_strong < cfg["min_strong"]:
        reasons.append(f"too few strong-support sources: {n_strong} < required {cfg['min_strong']}")
    if cfg["require_saturation"] and not sat:
        reasons.append("snowball saturation not reached (search may have missed key counter-evidence)")
    return reasons, {"n_sources": n, "n_strong": n_strong, "saturation_reached": sat}


def build_verdict(table: dict, profile: Optional[dict] = None,
                  thresholds: Optional[dict] = None) -> dict:
    """Build an evidence_verdict payload (verdict derived from the floor checks, never set by hand)."""
    reasons, facts = check_evidence(table, profile, thresholds)
    return {
        "verdict": "BLOCK" if reasons else "PASS",
        "reasons": reasons,
        "tier": "deterministic",
        "n_sources": facts["n_sources"],
        "n_strong": facts["n_strong"],
        "saturation_reached": facts["saturation_reached"],
        "checked_invariants": list((profile or {}).get("evidence_invariants", [])),
    }
