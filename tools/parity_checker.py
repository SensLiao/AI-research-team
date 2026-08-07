"""Deterministic core of the train-test-parity-verifier (EXECUTE hard gate).

Post-run, re-verify that the train/test alignment contract ACTUALLY held — that the pipeline that
really ran still satisfies parity. Drift between the designed pipeline and the executed one (e.g. eval
augmentation silently turned on at run time, or precision changed) silently invalidates the
comparison; this gate catches it after the fact.

It REUSES the alignment checker on the ACTUAL run pipeline captured in the journal entry, so the
EXECUTE-stage parity check and the DESIGN-stage alignment check share one tested definition of
"aligned" — there is no second, drifting copy of the rule.
"""
from __future__ import annotations

from typing import List, Optional

from research_agent_teams.tools.alignment_checker import check_alignment

# the pipeline facts that must match between the DESIGNED and the EXECUTED run for the comparison to hold
PARITY_FIELDS = ["preprocessing", "augmentation", "precision", "pretrained", "inference", "label_space"]


def _designed_vs_actual_drift(designed: dict, actual: dict, side: str) -> List[str]:
    out: List[str] = []
    for k in PARITY_FIELDS:
        if k in designed or k in actual:
            if designed.get(k) != actual.get(k):
                out.append(f"{side} {k} drifted from design: designed={designed.get(k)!r} actual={actual.get(k)!r}")
    return out


def check_parity(journal_entry: dict, alignment_report: dict, profile: Optional[dict] = None,
                 *, zero_training: bool = False) -> List[str]:
    """Return parity violations; empty == the alignment contract held at run time.

    zero_training (R3 A2, 2026-08-07): passed straight through to the internal
    check_alignment self-consistency re-check below, so a legitimately zero_training
    actual pipeline is not flagged for a training-only mismatch it was never meant to
    have. alignment_report.verdict already reflects the same escape hatch — the caller
    computed it once when building that report — so this parameter only needs to reach
    the ONE place this function makes its own fresh check_alignment call.
    """
    violations: List[str] = []

    if alignment_report.get("verdict") != "PASS":
        violations.append("run proceeded without a PASS alignment contract to hold to")

    actual_train = journal_entry.get("actual_train") or {}
    actual_test = journal_entry.get("actual_test") or {}
    if not actual_train or not actual_test:
        violations.append("journal did not capture the actual run pipeline (parity is unverifiable)")
        return violations

    # (a) the executed pipeline must itself be internally aligned (catches eval aug turned on, etc.)
    for v in check_alignment(actual_train, actual_test, profile, zero_training=zero_training):
        violations.append(f"post-run drift: {v}")

    # (b) the executed pipeline must match the DESIGNED one (catches self-consistent drift, e.g. both
    #     train+test silently switched fp32 -> fp16 — internally aligned but no longer the designed run)
    designed_train = journal_entry.get("designed_train") or {}
    designed_test = journal_entry.get("designed_test") or {}
    if not designed_train or not designed_test:
        violations.append("journal did not capture the designed pipeline (designed-vs-actual parity is unverifiable)")
    else:
        violations += _designed_vs_actual_drift(designed_train, actual_train, "train")
        violations += _designed_vs_actual_drift(designed_test, actual_test, "test")
    return violations


def build_report(journal_entry: dict, alignment_report: dict, profile: Optional[dict] = None,
                 journal_ref: Optional[str] = None, alignment_ref: Optional[str] = None,
                 *, zero_training: bool = False) -> dict:
    """Build a parity_verdict payload (verdict derived from violations — never set by hand)."""
    violations = check_parity(journal_entry, alignment_report, profile, zero_training=zero_training)
    return {
        "verdict": "BLOCK" if violations else "PASS",
        "violations": violations,
        "drift_checks": ["alignment_contract_present", "actual_pipeline_captured", "post_run_alignment"],
        "journal_ref": journal_ref,
        "alignment_ref": alignment_ref,
    }
