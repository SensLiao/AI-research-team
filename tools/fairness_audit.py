"""Deterministic core of the fairness-auditor (ANALYZE check-panel).

H2 FIX: replaces the false compliance_audit.py citation in fairness-auditor.md with
a REAL deterministic helper that actually bites.

Round-2 FIX 3: stop false-positives on legitimate per-VALUE stratification.
Real per-subgroup findings carry stratum VALUES (e.g. condition_id "ours_aorta" with
stratum "aorta"), NOT the stratification key NAME ("anatomy_region"). The old check
required the condition_id to ECHO the key name (`key_lower in condition_id`), so a
genuine per-subgroup analysis whose condition_ids never spell out the key name was
wrongly flagged as unstratified.

The fix recognises two stratification signals, in priority order:
  (a) Explicit field — any finding/run_record carrying a non-empty `stratum` or
      `stratum_key` field proves the run was stratified. When such tags are present,
      the result set IS stratified and is NOT flagged. This is the robust, value-based
      signal: it does not depend on the key NAME appearing in the condition_id.
  (b) Legacy key-name echo — when no explicit stratum tag exists, fall back to the
      original per-key coverage: a declared key is "covered" when its NAME appears
      (case-insensitive) in some finding/run_record condition_id/stratum field. A
      declared key with no such echo is flagged.

The only genuine bad case that is ALWAYS flagged: stratification_keys are declared in
the profile AND ZERO findings/records carry ANY stratum tag at all (aggregate-only
results — fairness across subgroups is unverifiable).

Profile-driven: stratification_keys come from profile.split_policy.stratification_keys.
Nothing hardcoded per domain. Pure function; no I/O, no network, no LLM.
"""
from __future__ import annotations

from typing import List, Optional


# --------------------------------------------------------------------------- #
#  Public API                                                                  #
# --------------------------------------------------------------------------- #

def check_fairness(
    result_summary: dict,
    run_records: Optional[List[dict]] = None,
    profile: Optional[dict] = None,
) -> List[str]:
    """Return violation strings (empty == fair).

    Deterministic checks (see module docstring):
    - If any finding/run_record carries an explicit `stratum` or `stratum_key` field,
      the result set IS stratified → no violation (per-VALUE stratification is valid
      even when the condition_id does not echo the key NAME).
    - Otherwise fall back to legacy key-name-echo coverage: each declared key must have
      its NAME appear in some condition_id/stratum field; un-echoed keys are flagged.
    - If stratification_keys are declared and NO stratum tag exists at all (aggregate-only
      results), flag class-imbalance handling as unverified.
    """
    violations: List[str] = []

    strat_keys = _get_stratification_keys(profile)
    if not strat_keys:
        # No stratification declared in profile — skip check (no false BLOCK)
        return violations

    findings = result_summary.get("findings") or []
    records = run_records or []

    # (a) Explicit stratum tags prove the run was stratified per-VALUE. Their presence
    # alone clears the fairness check — we do NOT require the key NAME to echo.
    if _has_explicit_stratum_tag(findings, records):
        return violations

    # (b) No explicit stratum tag — fall back to legacy key-name-echo coverage.
    seen_strata = _collect_seen_strata(findings, records)

    for key in strat_keys:
        key_lower = key.lower()
        if not any(key_lower in s for s in seen_strata):
            violations.append(
                f"stratification_key '{key}' declared in profile but no per-stratum "
                f"finding or run_record references it — evaluation fairness unverifiable "
                f"across '{key}' subgroups."
            )

    # Genuine bad case: stratification_keys declared but NOTHING is stratum-tagged at all.
    if strat_keys and not seen_strata:
        violations.append(
            "class imbalance handling unverified: profile declares stratification_keys "
            "but result_summary contains no per-stratum findings."
        )

    return violations


def build_verdict(
    result_summary: dict,
    run_records: Optional[List[dict]] = None,
    profile: Optional[dict] = None,
    checked_items: Optional[List[str]] = None,
    notes: str = "",
) -> dict:
    """Build an analysis_check_verdict payload with panel_role='fairness'.

    pass is derived from violations — never set by hand.
    """
    violations = check_fairness(result_summary, run_records, profile)

    strat_keys = _get_stratification_keys(profile)
    items = checked_items if checked_items is not None else list(strat_keys)

    return {
        "panel_role": "fairness",
        "pass": len(violations) == 0,
        "violations": violations,
        "checked_items": items,
        "notes": notes,
    }


# --------------------------------------------------------------------------- #
#  Internal helpers                                                            #
# --------------------------------------------------------------------------- #

def _get_stratification_keys(profile: Optional[dict]) -> List[str]:
    """Return the list of stratification_keys from profile.split_policy, or []."""
    if not profile:
        return []
    split_policy = profile.get("split_policy") or {}
    keys = split_policy.get("stratification_keys") or []
    return [str(k) for k in keys if k]


def _has_explicit_stratum_tag(findings: list, run_records: list) -> bool:
    """Return True if ANY finding or run_record carries a non-empty explicit stratum tag.

    The explicit tag fields are `stratum` and `stratum_key`. Their presence is the
    robust, value-based signal that the run was stratified per-subgroup — it does NOT
    require the stratification key NAME to appear in the condition_id.
    """
    for item in list(findings) + list(run_records):
        for field in ("stratum", "stratum_key"):
            val = item.get(field)
            if isinstance(val, str) and val.strip():
                return True
    return False


def _collect_seen_strata(findings: list, run_records: list) -> set:
    """Return a set of lowercased stratum label substrings seen across findings and records.

    Legacy key-name-echo signal: we look in:
      - finding.condition_id / finding.stratum / finding.stratification
      - run_record.condition_id / run_record.stratum / run_record.stratification
    """
    seen = set()
    for f in findings:
        for field in ("condition_id", "stratum", "stratification"):
            val = f.get(field)
            if val and isinstance(val, str):
                seen.add(val.lower())
    for rec in run_records:
        for field in ("condition_id", "stratum", "stratification"):
            val = rec.get(field)
            if val and isinstance(val, str):
                seen.add(val.lower())
    return seen
