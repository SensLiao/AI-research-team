"""Deterministic core of the adversarial-reviewer (hard gate, no Write).

The reviewer tries to REFUTE a result before it can freeze, across five checks:
  leakage · fairness · eval_frame · provenance · overclaim
The LLM agent does the investigating and supplies, per check, a {pass, evidence} finding. This
checker decides the verdict mechanically: APPROVE-FREEZE only if ALL five pass AND each carries
evidence; otherwise BLOCK. A claimed pass with no evidence is treated as not-defensible and forces
the default-to-BLOCK rule — freezing an unverified number is the expensive failure the gate exists to
prevent. The reviewer has no Write tool; it issues a verdict, the human executes any freeze.
"""
from __future__ import annotations

from typing import List

CHECKS = ["leakage", "fairness", "eval_frame", "provenance", "overclaim"]


def build_report(checks: dict, require_evidence: bool = True) -> dict:
    """Build a review_report payload. verdict is derived from the five checks, never set by hand."""
    norm: dict = {}
    blocking: List[str] = []
    default_block = False

    for name in CHECKS:
        c = checks.get(name) or {}
        passed = bool(c.get("pass", False))
        evidence = str(c.get("evidence", "")).strip()

        if name not in checks:
            blocking.append(f"{name}: not investigated (default to BLOCK under uncertainty)")
            passed = False
            default_block = True
        elif passed and require_evidence and not evidence:
            blocking.append(f"{name}: claimed pass but no evidence cited (default to BLOCK under uncertainty)")
            passed = False
            default_block = True
        elif not passed:
            blocking.append(f"{name}: not defensible{(' - ' + evidence) if evidence else ''}")

        norm[name] = {"pass": passed}
        if evidence:
            norm[name]["evidence"] = evidence

    return {
        "verdict": "APPROVE-FREEZE" if not blocking else "BLOCK",
        "checks": norm,
        "blocking_reasons": blocking,
        "default_block_applied": default_block,
    }
