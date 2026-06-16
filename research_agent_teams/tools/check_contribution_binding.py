"""Deterministic core of the contribution-ledger-builder binding check (VERIFY panel).

Validates that every contribution entry in a contribution_ledger is fully bound:
  1. ``evidence_refs`` must be non-empty (at least one artifact reference backing this
     claim; an empty list means the contribution is asserted without evidence).
  2. ``condition_id`` must be non-empty (the contribution must trace to a specific
     experimental condition that demonstrates it; a missing condition_id means the
     claim floats free of any experiment).

An unbound contribution is a contribution the reviewers cannot verify — it will be
questioned in peer review and cannot support a strong paper.

Input consumed: ``contribution_ledger`` payload dict.
"""
from __future__ import annotations

from typing import List


def check_contribution_binding(ledger: dict) -> List[str]:
    """Return violations (empty list == every contribution is fully bound).

    Parameters
    ----------
    ledger : dict
        contribution_ledger payload dict (has ``contributions[]``).

    Returns
    -------
    List[str]
        Human-readable violations; empty == all contributions are bound.
    """
    violations: List[str] = []
    contributions = ledger.get("contributions") or []

    for i, contrib in enumerate(contributions):
        claim_text = contrib.get("claim_text", f"<contribution {i}>")
        # Truncate long claim text for readability in violation messages.
        label = claim_text[:60] + "..." if len(claim_text) > 60 else claim_text

        # 1. evidence_refs must be a non-empty list.
        evidence_refs = contrib.get("evidence_refs")
        if not isinstance(evidence_refs, list) or len(evidence_refs) == 0:
            violations.append(
                f"contribution[{i}] '{label}' has empty evidence_refs; "
                "every contribution must be backed by at least one artifact reference"
            )
        else:
            # Check for blank/whitespace-only refs.
            blank_refs = [r for r in evidence_refs if not (isinstance(r, str) and r.strip())]
            if blank_refs:
                violations.append(
                    f"contribution[{i}] '{label}' has {len(blank_refs)} blank evidence_ref(s); "
                    "all evidence_refs must be non-empty strings"
                )

        # 2. condition_id must be a non-empty string.
        condition_id = contrib.get("condition_id", "")
        if not isinstance(condition_id, str) or not condition_id.strip():
            violations.append(
                f"contribution[{i}] '{label}' has no condition_id; "
                "every contribution must reference the experimental condition that demonstrates it"
            )

    return violations


def build_report(ledger: dict) -> dict:
    """Build a contribution-binding check report.

    ``verdict`` is derived from violations — never set by hand.
    """
    v = check_contribution_binding(ledger)
    return {
        "verdict": "BLOCK" if v else "PASS",
        "violations": v,
    }
