"""Deterministic core of the citation-integrity-auditor (DISCOVER hard gate).

Checks that every claim in a claim_list is:
  1. Anchored — has at least one non-empty locus in the claim_evidence_map.
  2. Not contradicted — no locus has supports_claim=False (i.e. no locus reports
     the opposite of what the claim asserts), and no locus is MISSING supports_claim.
  3. Resolvable — the source_ref on every locus is present in the provided
     resolvable_refs set (or left unchecked when the caller passes None).

The LLM agent gathers the claim_list and claim_evidence_map; this checker — not
the LLM — decides PASS/BLOCK.  A BLOCK halts the DISCOVER stage.

All three checks are always-on structural checks; no domain profile is needed.

=== Contradiction detection is the linker's explicit decision ===
There is NO automatic numeric comparison in this checker. A robust numeric
contradiction check would need metric-direction awareness (higher-is-better vs
lower-is-better, e.g. HD95) plus entity-binding (which number is "ours" vs
"baseline"), neither of which this deterministic checker has — attempting it
false-positives on correct citations (parenthetical sample sizes like
"0.87 (n=50) vs 0.61 (n=48)", lower-is-better metrics like HD95 "2.1 vs 4.5",
baseline-listed-first ordering like "baseline 0.61, ours 0.89").

Instead, the division of labour is:
  - The claim-evidence-linker (LLM) READS the `reported_result` at each locus and
    EXPLICITLY sets `supports_claim` per locus (true = locus supports the claim,
    false = locus contradicts it).  That is where the fact is gathered.
  - This checker ENFORCES that decision deterministically: it BLOCKs when any
    locus has supports_claim=false (linker judged contradiction) or is MISSING
    supports_claim (linker failed to decide — cannot verify).

=== supports_claim is REQUIRED ===
supports_claim has no default in the schema — the linker must explicitly set it for
every locus.  A locus that is missing supports_claim cannot be verified; this
checker conservatively BLOCKs rather than silently treating it as supporting.

=== Empty claim_id ===
A claim or mapping with an empty string claim_id ("") is treated as invalid —
empty-id claims are flagged as unanchored violations (they cannot be looked up),
and empty-id mappings are ignored (they would wrongly match each other).
"""
from __future__ import annotations

from typing import List, Optional


# ---------------------------------------------------------------------------
# Public check functions
# ---------------------------------------------------------------------------

def check_no_locus(
    claim_list: dict,
    claim_evidence_map: dict,
) -> List[str]:
    """Return violations for claims with no valid locus.

    A claim has no valid locus when:
      - its claim_id is empty (invalid — cannot be anchored)
      - its claim_id does not appear in the mappings list, OR
      - it appears but its loci[] is empty.

    Mappings with empty claim_id are ignored (they cannot validly anchor any claim).
    """
    violations: List[str] = []
    # Build a set of claim_ids that have at least one locus entry.
    # Ignore mappings with empty claim_id — they are invalid and must not match "".
    locus_map: dict[str, list] = {}
    for mapping in (claim_evidence_map.get("mappings") or []):
        cid = mapping.get("claim_id", "")
        if not cid:
            continue  # skip empty-id mappings; they cannot anchor anything
        loci = mapping.get("loci") or []
        locus_map[cid] = loci

    for claim in (claim_list.get("claims") or []):
        cid = claim.get("claim_id", "")
        text = claim.get("text", "")
        if not cid:
            violations.append(
                f"claim with empty claim_id ({text[:60]!r}) is invalid — "
                f"claim_id must be a non-empty string (empty-id claim is unanchored)"
            )
            continue
        loci = locus_map.get(cid)
        if loci is None:
            violations.append(
                f"claim {cid!r} ({text[:60]!r}) has no entry in claim_evidence_map (unanchored)"
            )
        elif len(loci) == 0:
            violations.append(
                f"claim {cid!r} ({text[:60]!r}) has an empty loci[] in claim_evidence_map (unanchored)"
            )
    return violations


def check_contradicted(
    claim_list: dict,
    claim_evidence_map: dict,
    coverage_based_absence_claim_ids: Optional[set[str]] = None,
) -> List[str]:
    """Return violations for claims where a locus contradicts them.

    Two mechanisms — both conservative, both always-on, both driven by the
    linker's explicit per-locus `supports_claim` decision (no automatic numeric
    comparison happens here):

    1. supports_claim=False (linker judgment):
       The LLM linker, having read the locus `reported_result`, explicitly marked
       supports_claim=False — meaning the locus reports the OPPOSITE of what the
       claim asserts.  The checker BLOCKs deterministically on that decision.

    2. Missing supports_claim (cannot verify):
       supports_claim has no default — every locus must carry an explicit decision.
       A locus missing supports_claim is a linker error; we BLOCK conservatively.
    """
    violations: List[str] = []
    allowed_absence = set(coverage_based_absence_claim_ids or set())
    # Index mappings by claim_id (skip empty-id mappings)
    mapping_index: dict[str, dict] = {}
    for mapping in (claim_evidence_map.get("mappings") or []):
        cid = mapping.get("claim_id", "")
        if not cid:
            continue
        mapping_index[cid] = mapping

    for claim in (claim_list.get("claims") or []):
        cid = claim.get("claim_id", "")
        if not cid:
            continue  # already caught by check_no_locus
        mapping = mapping_index.get(cid)
        if mapping is None:
            continue  # already caught by check_no_locus

        for locus in (mapping.get("loci") or []):
            loc_id = locus.get("locus_id", "?")
            reported = locus.get("reported_result")

            # --- Mechanism 2: missing supports_claim (conservative BLOCK) ---
            if "supports_claim" not in locus:
                violations.append(
                    f"claim {cid!r}: locus {loc_id!r} is missing supports_claim — "
                    f"the linker must explicitly set supports_claim (true or false) "
                    f"on every locus; cannot verify without it (conservative BLOCK)"
                )
                continue

            supports = locus["supports_claim"]

            # --- Mechanism 1: supports_claim=False (linker judgment) ---
            if supports is False:
                if (cid in allowed_absence
                        and mapping.get("overall_support") == "not-found"
                        and locus.get("support_relation") == "insufficient"):
                    continue
                reported_str = reported if reported is not None else "(not recorded)"
                violations.append(
                    f"claim {cid!r} is contradicted by locus {loc_id!r}: "
                    f"locus reports {reported_str!r} (supports_claim=false)"
                )

    return violations


def check_unresolvable_refs(
    claim_evidence_map: dict,
    resolvable_refs: Optional[set] = None,
) -> List[str]:
    """Return violations for locus source_refs not in resolvable_refs.

    If resolvable_refs is None (caller did not provide a known-good set),
    this check is skipped (returns []).  This prevents false BLOCKs when
    the caller cannot supply a ref registry.
    """
    if resolvable_refs is None:
        return []
    violations: List[str] = []
    seen_bad: set[str] = set()
    for mapping in (claim_evidence_map.get("mappings") or []):
        cid = mapping.get("claim_id", "")
        for locus in (mapping.get("loci") or []):
            ref = locus.get("source_ref", "")
            if ref and ref not in resolvable_refs and ref not in seen_bad:
                seen_bad.add(ref)
                violations.append(
                    f"locus source_ref {ref!r} (used by claim {cid!r}) is not in the "
                    f"resolvable refs set (unresolvable reference)"
                )
    return violations


def build_report(
    claim_list: dict,
    claim_evidence_map: dict,
    resolvable_refs: Optional[set] = None,
    coverage_based_absence_claim_ids: Optional[set[str]] = None,
) -> dict:
    """Build a citation_integrity_verdict payload.

    verdict is derived from violations — never set by hand.
    BLOCKs when:
      - any claim has an empty claim_id                    (invalid unanchored claim)
      - any claim has no valid locus                        (unanchored claim)
      - any locus is missing supports_claim                (linker must decide — conservative BLOCK)
      - any claim is contradicted by a locus               (supports_claim=False)
      - any locus source_ref is unresolvable               (when resolvable_refs provided)
    """
    v_no_locus = check_no_locus(claim_list, claim_evidence_map)
    v_contradicted = check_contradicted(
        claim_list, claim_evidence_map, coverage_based_absence_claim_ids,
    )
    v_unresolvable = check_unresolvable_refs(claim_evidence_map, resolvable_refs)

    all_violations: List[str] = v_no_locus + v_contradicted + v_unresolvable

    # Collect structured fields
    no_locus_claims = [
        claim.get("claim_id", "")
        for claim in (claim_list.get("claims") or [])
        if _has_no_valid_locus(claim.get("claim_id", ""), claim_evidence_map)
    ]

    contradicted_claims = _extract_contradicted_claim_ids(
        claim_list, claim_evidence_map, coverage_based_absence_claim_ids,
    )

    unresolvable_refs_list: List[str] = []
    if resolvable_refs is not None:
        unresolvable_refs_list = _collect_unresolvable_refs(claim_evidence_map, resolvable_refs)

    n_claims = len(claim_list.get("claims") or [])

    return {
        "verdict": "BLOCK" if all_violations else "PASS",
        "violations": all_violations,
        "unresolvable_refs": unresolvable_refs_list,
        "no_locus_claims": no_locus_claims,
        "contradicted_claims": contradicted_claims,
        "n_claims_checked": n_claims,
    }


# ---------------------------------------------------------------------------
# Internal helpers (not exported as the primary API)
# ---------------------------------------------------------------------------

def _has_no_valid_locus(claim_id: str, claim_evidence_map: dict) -> bool:
    if not claim_id:
        return True  # empty-id claim cannot be anchored
    for mapping in (claim_evidence_map.get("mappings") or []):
        cid = mapping.get("claim_id", "")
        if not cid:
            continue  # skip invalid empty-id mappings
        if cid == claim_id:
            return len(mapping.get("loci") or []) == 0
    return True  # not found in map at all


def _extract_contradicted_claim_ids(
    claim_list: dict,
    claim_evidence_map: dict,
    coverage_based_absence_claim_ids: Optional[set[str]] = None,
) -> List[str]:
    """Collect claim_ids that are contradicted (by supports_claim=False or a
    missing supports_claim)."""
    index: dict[str, dict] = {}
    for mapping in (claim_evidence_map.get("mappings") or []):
        cid = mapping.get("claim_id", "")
        if not cid:
            continue
        index[cid] = mapping

    result: List[str] = []
    allowed_absence = set(coverage_based_absence_claim_ids or set())
    for claim in (claim_list.get("claims") or []):
        cid = claim.get("claim_id", "")
        if not cid:
            continue
        mapping = index.get(cid)
        if mapping is None:
            continue
        for locus in (mapping.get("loci") or []):
            if "supports_claim" not in locus:
                result.append(cid)
                break
            if locus["supports_claim"] is False:
                if (cid in allowed_absence
                        and mapping.get("overall_support") == "not-found"
                        and locus.get("support_relation") == "insufficient"):
                    continue
                result.append(cid)
                break
    return result


def _collect_unresolvable_refs(
    claim_evidence_map: dict,
    resolvable_refs: set,
) -> List[str]:
    bad: List[str] = []
    seen: set[str] = set()
    for mapping in (claim_evidence_map.get("mappings") or []):
        for locus in (mapping.get("loci") or []):
            ref = locus.get("source_ref", "")
            if ref and ref not in resolvable_refs and ref not in seen:
                seen.add(ref)
                bad.append(ref)
    return bad
