"""Deterministic core of the citation-integrity-auditor (DISCOVER hard gate).

Checks that every claim in a claim_list is:
  1. Anchored — has at least one non-empty locus in the claim_evidence_map.
  2. Not contradicted — no locus has support_relation="contradicts" with
     supports_claim=False, and every claim has at least one genuinely supporting
     locus (see "Boundary vs refutation" below for what does and does not count).
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
    false = locus contradicts it), plus a `support_relation` naming WHY.
  - This checker ENFORCES that decision deterministically over the full closed
    `support_relation` enum (entails/partial/contradicts/insufficient).

=== Boundary vs refutation (R3 A1, 2026-08-07) ===
A `supports_claim=False` locus is not automatically a contradiction. Only
`support_relation="contradicts"` is — that is the ONE per-locus hard BLOCK.
`"partial"` (a scope qualification, e.g. "contextualizes_and_bounds") and
`"insufficient"` (D9: could not be checked) are both non-support but NEVER block
on their own; they are surfaced as `bounded_loci` / `unverified_loci` on the
verdict. A missing `supports_claim`, or a `support_relation` this checker does
not recognise, is likewise non-blocking (`undecided_loci`) — this REPLACES the
old conservative BLOCK-on-missing. A claim is still BLOCKed if it ends up with
NO genuinely supporting locus at all (every locus bounded/unverified/undecided,
or itself individually contradicted) — that aggregate check is unchanged in
kind, only widened and reworded to stop calling an absence of support a
contradiction.

=== Empty claim_id ===
A claim or mapping with an empty string claim_id ("") is treated as invalid —
empty-id claims are flagged as unanchored violations (they cannot be looked up),
and empty-id mappings are ignored (they would wrongly match each other).
"""
from __future__ import annotations

from typing import List, Optional

#: The one `support_relation` value that means "I could not check this", as opposed to
#: "I checked this and it says the opposite".  Declared in claim_evidence_map.schema.json
#: since claim-span/v1; promoted to a gate-relevant constant by D9 (2026-08-06).
UNVERIFIED_RELATION = "insufficient"

#: "This locus narrows or qualifies the claim's scope" — a boundary, not a refutation.
#: R3 A1 (2026-08-07): the pre-fix checker treated ANY non-insufficient supports_claim=false
#: locus as a contradiction, so a linker labelling a locus 'contextualizes_and_bounds' (or any
#: of its 21-of-22 2026-08-04 siblings) was reported to the director as a claim being refuted
#: when it was only being bounded. Declared in claim_evidence_map.schema.json since claim-span/v1.
BOUNDED_RELATION = "partial"

#: "This locus reports the opposite of what the claim asserts" — the ONE per-locus hard BLOCK.
CONTRADICTED_RELATION = "contradicts"

#: The full closed enum (claim_evidence_map.schema.json claim-span/v1). Any support_relation
#: outside this set — including a missing one — is handled by the undecided/non-blocking path
#: below, never assumed to be a contradiction.
_KNOWN_RELATIONS = frozenset({"entails", BOUNDED_RELATION, CONTRADICTED_RELATION, UNVERIFIED_RELATION})


def _index_mappings(claim_evidence_map: dict) -> dict:
    """claim_id -> mapping, skipping empty-id mappings (they cannot anchor anything)."""
    index: dict = {}
    for mapping in (claim_evidence_map.get("mappings") or []):
        cid = mapping.get("claim_id", "")
        if cid:
            index[cid] = mapping
    return index


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
    """Return violations for claims where a locus contradicts them, or where a claim
    ends up with no genuinely supporting locus at all.

    R3 A1 (2026-08-07) widens the per-locus routing to the full closed enum, keyed on
    (support_relation, supports_claim) — still all conservative, all always-on, all
    driven by the linker's explicit per-locus decision (no automatic numeric
    comparison happens here):

    1. supports_claim=True (any relation): the locus SUPPORTS the claim.

    2. support_relation="contradicts" + supports_claim=False (linker judgment):
       the linker, having read the locus `reported_result`, explicitly marked the
       locus the OPPOSITE of what the claim asserts.  This is the ONLY per-locus
       hard BLOCK — a real refutation.

    3. support_relation="partial" + supports_claim=False: the locus narrows or
       qualifies the claim's scope rather than refuting it — this is precisely the
       "划界≠反证" (a boundary is not a refutation) defect the pre-fix checker had:
       it collapsed 'contextualizes_and_bounds' and 21 of its 22 2026-08-04 siblings
       into a reported contradiction. Non-support, but only a warning (bounded_loci
       on the verdict) — never a per-locus BLOCK.

    4. support_relation="insufficient" (D9, 2026-08-06) + supports_claim=False —
       UNVERIFIED, not refuted: "the source was 403 / paywalled / truncated / silent
       on the point" is not "the source says the opposite". Non-support, warning
       only (unverified_loci).

    5. Missing supports_claim, or a support_relation this checker does not
       recognise (with supports_claim false or absent): the linker did not make a
       clean decision.  This was formerly a conservative hard BLOCK (the old
       Mechanism 2); it is downgraded to a warning (undecided_loci) — the director
       sees it, it does not halt the stage on its own.

    A claim left with NO supporting locus at all (mechanisms 3-5 combined, or every
    locus already BLOCKed via mechanism 2) still BLOCKs — that aggregate check is
    unchanged in kind, only broadened from "every locus is insufficient" to "every
    locus is non-supporting", with wording that no longer calls it a contradiction.
    """
    violations: List[str] = []
    allowed_absence = set(coverage_based_absence_claim_ids or set())
    mapping_index = _index_mappings(claim_evidence_map)

    for claim in (claim_list.get("claims") or []):
        cid = claim.get("claim_id", "")
        if not cid:
            continue  # already caught by check_no_locus
        mapping = mapping_index.get(cid)
        if mapping is None:
            continue  # already caught by check_no_locus

        loci = mapping.get("loci") or []
        # Computed once per claim: does anything actually hold this claim up?
        supported_by_something = any(
            locus.get("supports_claim") is True for locus in loci
        )
        non_supporting_here: List[str] = []

        for locus in loci:
            loc_id = locus.get("locus_id", "?")
            reported = locus.get("reported_result")
            relation = locus.get("support_relation")

            # --- Mechanism 5a: missing supports_claim (downgraded from BLOCK) ---
            if "supports_claim" not in locus:
                non_supporting_here.append(f"{loc_id!r} (missing supports_claim)")
                continue

            supports = locus["supports_claim"]
            if supports is not False:
                continue  # True => support, nothing to flag

            # --- from here supports_claim is False ---

            # --- Mechanism 2: the one real refutation ---
            if relation == CONTRADICTED_RELATION:
                reported_str = reported if reported is not None else "(not recorded)"
                violations.append(
                    f"claim {cid!r} is contradicted by locus {loc_id!r}: "
                    f"locus reports {reported_str!r} (supports_claim=false)"
                )
                continue

            # --- Mechanism 4: insufficient == unverified, never refuted ---
            if relation == UNVERIFIED_RELATION:
                # The pre-existing narrow exemption for coverage-based absence claims
                # is now the general rule's special case; keep its exact conditions.
                if cid in allowed_absence and mapping.get("overall_support") == "not-found":
                    continue
                non_supporting_here.append(f"{loc_id!r} (insufficient — unverified)")
                continue

            # --- Mechanism 3: a boundary, not a refutation ---
            if relation == BOUNDED_RELATION:
                non_supporting_here.append(f"{loc_id!r} (partial — bounded, not refuted)")
                continue

            # --- Mechanism 5b: an unrecognised support_relation ---
            non_supporting_here.append(f"{loc_id!r} (support_relation={relation!r} not recognised)")

        if non_supporting_here and not supported_by_something:
            violations.append(
                f"claim {cid!r} has no supporting locus — {', '.join(non_supporting_here)}; "
                f"a claim with no genuine support is unsupported"
            )

    return violations


def _loci_matching(
    claim_list: dict,
    claim_evidence_map: dict,
    predicate,
) -> List[str]:
    """Return ``"<claim_id>:<locus_id>"`` for every locus where ``predicate(locus)`` is true."""
    matches: List[str] = []
    mapping_index = _index_mappings(claim_evidence_map)
    for claim in (claim_list.get("claims") or []):
        cid = claim.get("claim_id", "")
        mapping = mapping_index.get(cid) if cid else None
        if mapping is None:
            continue
        for locus in (mapping.get("loci") or []):
            if predicate(locus):
                matches.append(f"{cid}:{locus.get('locus_id', '?')}")
    return matches


def collect_unverified_loci(
    claim_list: dict,
    claim_evidence_map: dict,
) -> List[str]:
    """Return ``"<claim_id>:<locus_id>"`` for every tolerated-but-unverified locus.

    These are the loci D9 stops calling contradictions.  They are surfaced on the
    verdict so a claim that survives on partial coverage is never silently
    presented as fully verified — the director sees exactly which spans nobody
    could open.
    """
    return _loci_matching(
        claim_list, claim_evidence_map,
        lambda locus: (locus.get("supports_claim") is False
                       and locus.get("support_relation") == UNVERIFIED_RELATION),
    )


def collect_bounded_loci(
    claim_list: dict,
    claim_evidence_map: dict,
) -> List[str]:
    """Return ``"<claim_id>:<locus_id>"`` for every locus that bounds rather than refutes.

    R3 A1 (2026-08-07): ``support_relation="partial"`` + ``supports_claim=False`` is a
    scope qualification, not a contradiction. Surfaced on the verdict so a claim that
    survives on a narrower-than-claimed locus is never silently read as fully entailed.
    """
    return _loci_matching(
        claim_list, claim_evidence_map,
        lambda locus: (locus.get("supports_claim") is False
                       and locus.get("support_relation") == BOUNDED_RELATION),
    )


def collect_undecided_loci(
    claim_list: dict,
    claim_evidence_map: dict,
) -> List[str]:
    """Return ``"<claim_id>:<locus_id>"`` for every locus the linker left undecided.

    R3 A1 (2026-08-07): a missing ``supports_claim``, or a ``support_relation`` this
    checker does not recognise, no longer BLOCKs on its own (the old Mechanism 2) —
    it is downgraded to a visible, non-blocking flag here.
    """
    return _loci_matching(
        claim_list, claim_evidence_map,
        lambda locus: (
            "supports_claim" not in locus
            or (locus.get("supports_claim") is False
                and locus.get("support_relation") not in _KNOWN_RELATIONS - {"entails"})
        ),
    )


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
      - any locus has support_relation="contradicts" with
        supports_claim=False                                (the one real refutation)
      - any claim ends up with no genuinely supporting locus (R3 A1: bounded/unverified/
        undecided loci alone are never enough — see module docstring)
      - any locus source_ref is unresolvable               (when resolvable_refs provided)
    A missing supports_claim, or a "partial"/"insufficient"/unrecognised support_relation,
    is surfaced (undecided_loci / bounded_loci / unverified_loci) but never blocks alone.
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
        # D9: tolerated-but-unchecked spans are surfaced, never dropped. A PASS that
        # rests on partial coverage must say which spans nobody could open.
        "unverified_loci": collect_unverified_loci(claim_list, claim_evidence_map),
        # R3 A1 (2026-08-07): bounded (partial) and undecided (missing/unrecognised
        # decision) loci are surfaced the same way — non-blocking, but never silent.
        "bounded_loci": collect_bounded_loci(claim_list, claim_evidence_map),
        "undecided_loci": collect_undecided_loci(claim_list, claim_evidence_map),
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
    """Collect claim_ids contradicted by a genuine refutation.

    R3 A1 (2026-08-07): only ``support_relation="contradicts"`` + ``supports_claim=False``
    lands here now.  A missing ``supports_claim`` is "undecided", not "contradicted" (see
    ``collect_undecided_loci``) — the old Mechanism 2 hard-BLOCK-on-missing is gone, so this
    list must not claim a refutation that never happened.  Mirrors ``check_contradicted``
    exactly: an ``insufficient`` locus is UNVERIFIED and a ``partial`` locus is BOUNDED —
    neither is a contradiction, so ``coverage_based_absence_claim_ids`` (which only ever
    exempted the insufficient+not-found combo) has nothing left to exempt here.
    """
    del coverage_based_absence_claim_ids  # kept for call-site compatibility; see docstring
    index = _index_mappings(claim_evidence_map)
    result: List[str] = []
    for claim in (claim_list.get("claims") or []):
        cid = claim.get("claim_id", "")
        if not cid:
            continue
        mapping = index.get(cid)
        if mapping is None:
            continue
        for locus in (mapping.get("loci") or []):
            if (locus.get("supports_claim") is False
                    and locus.get("support_relation") == CONTRADICTED_RELATION):
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
