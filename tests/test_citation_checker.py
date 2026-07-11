"""Tests for citation_checker.py — the DISCOVER hard-gate deterministic core.

Three test tiers required by the M2 contract:
  1. Happy path  → PASS, violations == []
  2. BLOCK-on-injected → each failure mode individually causes BLOCK
  3. Realistic BLOCK case → a locus reports the OPPOSITE result (the core gate invariant)

The realistic BLOCK test (test_locus_reports_opposite_result_blocks) is the critical
"no dead gate" proof: we load the cv-medical domain profile to confirm the shape is
realistic, and craft an input where a locus's reported_result directly contradicts the claim.
"""
from __future__ import annotations

import yaml

from research_agent_teams.tools.citation_checker import (
    build_report,
    check_contradicted,
    check_no_locus,
    check_unresolvable_refs,
)
from research_agent_teams.tools.validate_artifact import PROFILE_DIR


# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------

def _claim_list(*claims) -> dict:
    """Build a minimal claim_list from (claim_id, text, source_ref) triples."""
    return {
        "source_scope": "test-scope",
        "claims": [
            {"claim_id": cid, "text": txt, "source_ref": ref}
            for cid, txt, ref in claims
        ],
    }


def _mapping(claim_id: str, loci: list) -> dict:
    return {"claim_id": claim_id, "loci": loci, "overall_support": "supported"}


def _locus(locus_id: str, source_ref: str, location: str,
           reported_result=None, supports_claim: bool = True) -> dict:
    entry: dict = {
        "locus_id": locus_id,
        "source_ref": source_ref,
        "location": location,
        "kind": "text",
        "supports_claim": supports_claim,
    }
    if reported_result is not None:
        entry["reported_result"] = reported_result
    else:
        entry["reported_result"] = None
    return entry


def _cem(*mappings) -> dict:
    """Build a claim_evidence_map from mapping dicts."""
    return {"mappings": list(mappings)}


# ---------------------------------------------------------------------------
# Happy path — all checks pass
# ---------------------------------------------------------------------------

def test_clean_claim_passes():
    """A claim with a valid locus and no contradictions → PASS."""
    cl = _claim_list(("c1", "Method X achieves 0.87 Dice on DatasetA.", "ref-paper-1"))
    cem = _cem(_mapping("c1", [_locus("l1", "ref-paper-1", "Table 2 row 1", "0.87 Dice")]))
    refs = {"ref-paper-1"}
    report = build_report(cl, cem, refs)
    assert report["verdict"] == "PASS"
    assert report["violations"] == []
    assert report["n_claims_checked"] == 1
    assert report["no_locus_claims"] == []
    assert report["contradicted_claims"] == []
    assert report["unresolvable_refs"] == []


def test_multiple_clean_claims_pass():
    """Multiple well-formed claims with loci → PASS."""
    cl = _claim_list(
        ("c1", "Model A outperforms Model B on Task T.", "ref-1"),
        ("c2", "Dataset D contains 500 patients.", "ref-2"),
    )
    cem = _cem(
        _mapping("c1", [_locus("l1", "ref-1", "Table 3", "A=0.90, B=0.85")]),
        _mapping("c2", [_locus("l2", "ref-2", "Section 2.1", "500 patients")]),
    )
    refs = {"ref-1", "ref-2"}
    report = build_report(cl, cem, refs)
    assert report["verdict"] == "PASS"
    assert report["violations"] == []


def test_no_resolvable_refs_argument_skips_ref_check():
    """When resolvable_refs=None, the ref check is skipped (no false BLOCK)."""
    cl = _claim_list(("c1", "Claim text.", "any-ref"))
    cem = _cem(_mapping("c1", [_locus("l1", "any-ref", "Table 1", "value")]))
    report = build_report(cl, cem, resolvable_refs=None)
    assert report["verdict"] == "PASS"
    assert report["unresolvable_refs"] == []


# ---------------------------------------------------------------------------
# BLOCK on injected failures — each cause individually triggers BLOCK
# ---------------------------------------------------------------------------

def test_claim_not_in_map_blocks():
    """A claim_id missing entirely from claim_evidence_map → BLOCK (unanchored)."""
    cl = _claim_list(("c1", "Some claim.", "ref-1"))
    cem = _cem()  # no mappings at all
    report = build_report(cl, cem)
    assert report["verdict"] == "BLOCK"
    assert "c1" in report["no_locus_claims"]
    assert any("unanchored" in v for v in report["violations"])


def test_empty_loci_blocks():
    """A claim in the map but with loci=[] → BLOCK (unanchored)."""
    cl = _claim_list(("c1", "Claim with empty loci.", "ref-1"))
    cem = _cem(_mapping("c1", []))  # loci is empty list
    report = build_report(cl, cem)
    assert report["verdict"] == "BLOCK"
    assert "c1" in report["no_locus_claims"]


def test_supports_claim_false_blocks():
    """A locus with supports_claim=False → BLOCK (claim contradicted by locus)."""
    cl = _claim_list(("c1", "Method A achieves 0.90 Dice.", "ref-1"))
    cem = _cem(_mapping("c1", [
        _locus("l1", "ref-1", "Table 2", "0.72 Dice", supports_claim=False)
    ]))
    report = build_report(cl, cem)
    assert report["verdict"] == "BLOCK"
    assert "c1" in report["contradicted_claims"]
    assert any("contradicted" in v or "supports_claim=false" in v for v in report["violations"])


def test_unresolvable_ref_blocks():
    """A locus source_ref not in resolvable_refs → BLOCK."""
    cl = _claim_list(("c1", "Claim text.", "ref-known"))
    cem = _cem(_mapping("c1", [_locus("l1", "ref-UNKNOWN", "Table 1", "some result")]))
    refs = {"ref-known"}  # ref-UNKNOWN is not in this set
    report = build_report(cl, cem, refs)
    assert report["verdict"] == "BLOCK"
    assert "ref-UNKNOWN" in report["unresolvable_refs"]
    assert any("unresolvable" in v for v in report["violations"])


def test_multiple_violations_all_reported():
    """Two independent violations both appear in violations list."""
    cl = _claim_list(
        ("c1", "Claim without locus.", "ref-1"),
        ("c2", "Claim with contradicting locus.", "ref-1"),
    )
    cem = _cem(
        # c1: not in map at all
        _mapping("c2", [_locus("l1", "ref-1", "Table 1", "0.50", supports_claim=False)]),
    )
    report = build_report(cl, cem)
    assert report["verdict"] == "BLOCK"
    assert len(report["violations"]) >= 2


# ---------------------------------------------------------------------------
# Realistic BLOCK case: locus reports the OPPOSITE result (the core gate invariant)
# ---------------------------------------------------------------------------

def test_locus_reports_opposite_result_blocks():
    """THE CORE GATE PROOF:

    A paper claims 'Method SAM3 achieves Dice=0.87 on ToothFairy3 dataset'.
    The locus at Table 3 of the same paper reports Dice=0.61 (the actual number).
    The agent that built the claim_evidence_map correctly set supports_claim=False.

    The citation-integrity-auditor MUST BLOCK on this — it is the primary gate invariant:
    a claim whose only locus contradicts it cannot be cited honestly.

    This test loads the cv-medical-segmentation profile to confirm the domain shape is
    realistic (3D medical segmentation with Dice metric), though the profile is not
    consumed by citation_checker (it has no profile-driven checks — all checks are
    always-on structural checks).
    """
    # Load the real shipped profile to confirm the domain shape (no dead gate)
    profile_path = PROFILE_DIR / "cv-medical-segmentation.profile.yaml"
    with open(profile_path, encoding="utf-8") as fh:
        profile = yaml.safe_load(fh)

    # Confirm the profile has Dice in its metrics (realistic domain check)
    metric_names = {m["name"].lower() for m in profile.get("metrics", [])}
    assert "dice" in metric_names, "cv-medical profile must declare Dice metric"

    # Build the realistic bad input:
    # Claim: "SAM3 achieves Dice=0.87 on ToothFairy3 dataset (Table 3, arXiv:2409.12345)"
    # Locus: Table 3 of arXiv:2409.12345 actually shows Dice=0.61 for SAM3
    # => supports_claim=False (the number in the paper is the OPPOSITE of what the claim says)
    claim_text = "SAM3 achieves Dice=0.87 on ToothFairy3 dataset."
    cl = {
        "source_scope": "3D medical segmentation survey",
        "claims": [
            {
                "claim_id": "c1",
                "text": claim_text,
                "source_ref": "arxiv:2409.12345",
                "kind": "performance",
                "confidence": "high",
            }
        ],
    }

    cem = {
        "mappings": [
            {
                "claim_id": "c1",
                "loci": [
                    {
                        "locus_id": "l1",
                        "source_ref": "arxiv:2409.12345",
                        "location": "Table 3, row SAM3, column Dice",
                        "kind": "table",
                        # The paper ACTUALLY says 0.61, not 0.87 — opposite of the claim
                        "reported_result": "0.61",
                        "supports_claim": False,  # ← this is what the linker flagged
                    }
                ],
                "overall_support": "contradicted",
            }
        ]
    }

    resolvable_refs = {"arxiv:2409.12345"}

    report = build_report(cl, cem, resolvable_refs)

    # The gate MUST BLOCK
    assert report["verdict"] == "BLOCK", (
        f"Expected BLOCK when locus contradicts the claim, got {report['verdict']}. "
        f"Violations: {report['violations']}"
    )
    assert "c1" in report["contradicted_claims"]
    assert report["violations"], "violations list must be non-empty on BLOCK"
    # Confirm the violation message names the locus and the mismatch
    violation_text = " ".join(report["violations"])
    assert "c1" in violation_text
    assert "l1" in violation_text or "contradicted" in violation_text or "supports_claim=false" in violation_text.lower()


# ---------------------------------------------------------------------------
# supports_claim is REQUIRED — missing it → BLOCK (conservative)
# ---------------------------------------------------------------------------

def test_locus_missing_supports_claim_blocks():
    """C3-b: A locus with supports_claim omitted entirely → BLOCK (conservative).

    The linker MUST decide per locus — no default is provided. When supports_claim is
    absent, citation_checker cannot verify the claim; it BLOCKs conservatively.
    """
    cl = _claim_list(("c1", "Method A achieves 0.90 Dice.", "ref-1"))
    # Build a locus without supports_claim at all (bypass _locus helper)
    locus_no_sc = {
        "locus_id": "l1",
        "source_ref": "ref-1",
        "location": "Table 2",
        "kind": "table",
        "reported_result": "0.90 Dice",
        # supports_claim intentionally OMITTED
    }
    cem = _cem(_mapping("c1", [locus_no_sc]))
    report = build_report(cl, cem)
    assert report["verdict"] == "BLOCK", (
        "A locus without supports_claim must BLOCK (conservative: linker must decide explicitly)"
    )
    assert "c1" in report["contradicted_claims"]
    violation_text = " ".join(report["violations"])
    assert "supports_claim" in violation_text.lower(), (
        f"violation should mention supports_claim; got: {report['violations']}"
    )


# ---------------------------------------------------------------------------
# Round-2 FIX 1: numeric backstop REMOVED — formerly-false-positive vectors now PASS
#
# The round-1 numeric backstop compared numbers in reported_result and BLOCKed
# correct citations. A robust numeric check needs metric-direction awareness and
# entity-binding the deterministic checker does not have, so the backstop was
# removed entirely. Contradiction is now ONLY the linker's explicit supports_claim
# decision (read from reported_result), enforced deterministically by the gate.
#
# These three tests pin the exact false-positive vectors the reviewers proved, with
# supports_claim=True (the linker read reported_result and correctly judged support):
# they MUST now PASS.
# ---------------------------------------------------------------------------

def test_fix1_parenthetical_sample_sizes_passes():
    """FIX 1 vector (a): parenthetical sample sizes must NOT be mistaken for the metric.

    Claim 'Our method beats baseline' + reported_result '0.87 (n=50) vs 0.61 (n=48)'.
    The old backstop compared 0.87 vs 50 (the first two numbers) and wrongly BLOCKed.
    With supports_claim=True (the linker correctly read 0.87 > 0.61 as a WIN) → PASS.
    """
    claim_text = "Our method beats the baseline."
    cl = _claim_list(("c1", claim_text, "ref-paper-A"))
    locus = _locus("l1", "ref-paper-A", "Table 3",
                   reported_result="0.87 (n=50) vs 0.61 (n=48)",
                   supports_claim=True)
    cem = _cem(_mapping("c1", [locus]))
    report = build_report(cl, cem)
    assert report["verdict"] == "PASS", (
        f"Parenthetical sample sizes must not trigger a contradiction; "
        f"got verdict={report['verdict']}, violations={report['violations']}"
    )
    assert report["contradicted_claims"] == []
    assert report["violations"] == []


def test_fix1_lower_is_better_metric_win_passes():
    """FIX 1 vector (b): lower-is-better metric (HD95) — a LOWER number is a WIN.

    Claim 'beats baseline on HD95 (2.1 vs 4.5)' + reported_result 'ours 2.1, baseline 4.5'.
    The old backstop saw 2.1 < 4.5 and wrongly read it as a LOSS → wrong BLOCK.
    With supports_claim=True (the linker knows HD95 is lower-is-better) → PASS.
    """
    claim_text = "Our method beats the baseline on HD95 (2.1 vs 4.5)."
    cl = _claim_list(("c1", claim_text, "ref-paper-B"))
    locus = _locus("l1", "ref-paper-B", "Table 4",
                   reported_result="ours 2.1, baseline 4.5",
                   supports_claim=True)
    cem = _cem(_mapping("c1", [locus]))
    report = build_report(cl, cem)
    assert report["verdict"] == "PASS", (
        f"Lower-is-better HD95 win must not trigger a contradiction; "
        f"got verdict={report['verdict']}, violations={report['violations']}"
    )
    assert report["contradicted_claims"] == []
    assert report["violations"] == []


def test_fix1_baseline_listed_first_passes():
    """FIX 1 vector (c): baseline-listed-first ordering must NOT be read as a loss.

    Claim 'Our method outperforms the baseline' + reported_result 'baseline 0.61, ours 0.89'.
    The old backstop saw 0.61 < 0.89 (baseline first) and wrongly read it as a LOSS → wrong BLOCK.
    With supports_claim=True (the linker bound 'ours'=0.89 > 'baseline'=0.61) → PASS.
    """
    claim_text = "Our method outperforms the baseline."
    cl = _claim_list(("c1", claim_text, "ref-paper-C"))
    locus = _locus("l1", "ref-paper-C", "Table 5",
                   reported_result="baseline 0.61, ours 0.89",
                   supports_claim=True)
    cem = _cem(_mapping("c1", [locus]))
    report = build_report(cl, cem)
    assert report["verdict"] == "PASS", (
        f"Baseline-listed-first ordering must not trigger a contradiction; "
        f"got verdict={report['verdict']}, violations={report['violations']}"
    )
    assert report["contradicted_claims"] == []
    assert report["violations"] == []


# ---------------------------------------------------------------------------
# L2: empty claim_id treated as anchored — must now BLOCK
# ---------------------------------------------------------------------------

def test_empty_claim_id_in_claim_list_blocks():
    """L2: a claim with claim_id='' cannot be anchored — must BLOCK.

    An empty-id claim and an empty-id mapping would wrongly match each other.
    The checker flags empty-id claims as invalid/unanchored violations.
    """
    cl = _claim_list(("", "Some claim with no ID.", "ref-1"))
    # Even if there's an empty-id mapping, it must not satisfy the empty-id claim
    cem = _cem(_mapping("", [_locus("l1", "ref-1", "Table 1", "value")]))
    report = build_report(cl, cem)
    assert report["verdict"] == "BLOCK", (
        "A claim with empty claim_id must BLOCK — empty-id cannot be anchored"
    )
    violation_text = " ".join(report["violations"])
    assert "empty" in violation_text.lower() or "claim_id" in violation_text.lower(), (
        f"violation should mention empty claim_id; got: {report['violations']}"
    )


def test_empty_claim_id_mapping_ignored_valid_claim_passes():
    """L2: empty-id mappings are skipped; a valid claim with a real mapping still passes."""
    cl = _claim_list(("c1", "A real claim.", "ref-1"))
    cem = {
        "mappings": [
            # Invalid empty-id mapping — must be ignored
            {"claim_id": "", "loci": [{"locus_id": "lx", "source_ref": "ref-1",
                                        "location": "T1", "supports_claim": True}],
             "overall_support": "supported"},
            # Valid mapping for c1
            _mapping("c1", [_locus("l1", "ref-1", "Table 1", "value")]),
        ]
    }
    report = build_report(cl, cem)
    assert report["verdict"] == "PASS", (
        f"Empty-id mapping must be ignored; valid c1 mapping should let it pass; "
        f"violations={report['violations']}"
    )


# ---------------------------------------------------------------------------
# Isolated check functions
# ---------------------------------------------------------------------------

def test_check_no_locus_clean():
    cl = _claim_list(("c1", "Text.", "r1"))
    cem = _cem(_mapping("c1", [_locus("l1", "r1", "S1")]))
    assert check_no_locus(cl, cem) == []


def test_check_no_locus_missing():
    cl = _claim_list(("c1", "Text.", "r1"))
    cem = _cem()
    violations = check_no_locus(cl, cem)
    assert len(violations) == 1
    assert "c1" in violations[0]


def test_check_contradicted_clean():
    cl = _claim_list(("c1", "Text.", "r1"))
    cem = _cem(_mapping("c1", [_locus("l1", "r1", "T1", supports_claim=True)]))
    assert check_contradicted(cl, cem) == []


def test_check_contradicted_fires():
    cl = _claim_list(("c1", "Text.", "r1"))
    cem = _cem(_mapping("c1", [_locus("l1", "r1", "T1", "0.50", supports_claim=False)]))
    violations = check_contradicted(cl, cem)
    assert len(violations) == 1
    assert "c1" in violations[0]


def test_check_unresolvable_skipped_when_no_refs():
    cem = _cem(_mapping("c1", [_locus("l1", "ghost-ref", "T1")]))
    assert check_unresolvable_refs(cem, None) == []


def test_check_unresolvable_fires():
    cem = _cem(_mapping("c1", [_locus("l1", "ghost-ref", "T1")]))
    violations = check_unresolvable_refs(cem, {"known-ref"})
    assert len(violations) == 1
    assert "ghost-ref" in violations[0]
