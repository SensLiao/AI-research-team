"""Tests for check_synthesis_coverage — the panel's core integrity guarantee.

The critical invariant: APPROVE while any reviewer BLOCK or critic block_flag is unaddressed
MUST be caught. A coverage check that cannot catch this is a dead gate (CRITICAL bug).

Tests include:
  - clean path: all blocks addressed → PASS
  - APPROVE-over-unaddressed-BLOCK (the primary dead-gate scenario)
  - unaddressed critic block_flag
  - empty panel (no blocks) → PASS
  - real-profile-shaped test proving the gate fires
"""
from __future__ import annotations

import yaml

from research_agent_teams.tools.check_synthesis_coverage import (
    build_report,
    check_synthesis_coverage,
)
from research_agent_teams.tools.validate_artifact import PROFILE_DIR


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------

def _review(lens: str, findings: list) -> dict:
    return {"lens": lens, "findings": findings}


def _finding(severity: str, anchor: str = "section 3.2", finding_id: str = "") -> dict:
    return {
        "severity": severity,
        "anchor": anchor,
        "evidence": "specific text from paper",
        "finding_id": finding_id,
    }


def _critic_memo(block_flags: list) -> dict:
    return {
        "cross_findings": [],
        "block_flags": [{"flag_text": f, "source": "critic"} for f in block_flags],
    }


def _synthesis(verdict: str, addressed: list, unaddressed: list = None, open_flags: list = None) -> dict:
    return {
        "verdict": verdict,
        "violations": [],
        "addressed_blocks": [{"block_source": s, "rebuttal": "evidence-backed rebuttal"} for s in addressed],
        "unaddressed_blocks": unaddressed or [],
        "open_critic_flags": open_flags or [],
    }


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------

def test_clean_all_blocks_addressed_passes() -> None:
    """All reviewer BLOCKs and critic flags addressed → PASS."""
    reviews = [
        _review("methodology", [_finding("BLOCK", "section 3.2", finding_id="meth-01")]),
        _review("domain", [_finding("WARN", "table 2")]),
    ]
    memo = _critic_memo(["insufficient power"])
    synthesis = _synthesis(
        verdict="APPROVE",
        addressed=["meth-01", "insufficient power"],
    )
    result = build_report(reviews, memo, synthesis)
    assert result["verdict"] == "PASS"
    assert result["violations"] == []


def test_no_blocks_no_flags_passes() -> None:
    """No BLOCK findings and no critic flags → PASS regardless of synthesis verdict."""
    reviews = [
        _review("methodology", [_finding("WARN"), _finding("NOTE")]),
        _review("domain", []),
    ]
    memo = _critic_memo([])
    synthesis = _synthesis(verdict="APPROVE", addressed=[])
    result = build_report(reviews, memo, synthesis)
    assert result["verdict"] == "PASS"


def test_empty_panel_passes() -> None:
    """Completely empty panel → PASS."""
    result = build_report([], {}, _synthesis("APPROVE", []))
    assert result["verdict"] == "PASS"
    assert result["violations"] == []


# ---------------------------------------------------------------------------
# CRITICAL: APPROVE-over-unaddressed-BLOCK (the primary dead-gate scenario)
# ---------------------------------------------------------------------------

def test_approve_over_unaddressed_block_is_caught() -> None:
    """THE CORE INTEGRITY GUARANTEE.

    Synthesis says APPROVE but reviewer has an unaddressed BLOCK finding.
    This MUST be caught — a check that misses this is a dead gate (CRITICAL bug).
    """
    reviews = [
        _review("methodology", [_finding("BLOCK", "section 3.2", finding_id="meth-block-01")]),
    ]
    memo = _critic_memo([])
    # Synthesis declares APPROVE but does NOT address the BLOCK
    synthesis = _synthesis(verdict="APPROVE", addressed=[])  # meth-block-01 NOT addressed

    violations = check_synthesis_coverage(reviews, memo, synthesis)
    assert len(violations) >= 1
    # Must mention that synthesis cannot APPROVE with unaddressed BLOCK
    assert any("unaddressed" in v.lower() or "block" in v.lower() for v in violations)
    # Must mention the specific finding
    assert any("meth-block-01" in v for v in violations)

    result = build_report(reviews, memo, synthesis)
    assert result["verdict"] == "BLOCK"


def test_approve_over_unaddressed_block_no_finding_id_still_caught() -> None:
    """BLOCK finding without a finding_id — falls back to anchor text. Must still be caught."""
    reviews = [
        _review("domain", [
            {"severity": "BLOCK", "anchor": "hard_invariant: patient-level split required", "evidence": "patch-level split found", "finding_id": ""}
        ]),
    ]
    memo = _critic_memo([])
    synthesis = _synthesis(verdict="APPROVE", addressed=[])  # anchor not addressed

    violations = check_synthesis_coverage(reviews, memo, synthesis)
    assert len(violations) >= 1
    result = build_report(reviews, memo, synthesis)
    assert result["verdict"] == "BLOCK"


def test_block_verdict_over_unaddressed_block_passes_check() -> None:
    """Synthesis correctly says BLOCK when block is unaddressed → coverage check passes (no additional violation)."""
    reviews = [
        _review("methodology", [_finding("BLOCK", "figure 4", finding_id="meth-02")]),
    ]
    memo = _critic_memo([])
    synthesis = _synthesis(verdict="BLOCK", addressed=[], unaddressed=["meth-02"])
    # Synthesis is honest about being BLOCK — coverage check should not add extra violations
    violations = check_synthesis_coverage(reviews, memo, synthesis)
    # "meth-02" is not in addressed, so there IS a violation about it being unaddressed.
    # But the synthesis verdict is already BLOCK, so the primary "APPROVE over BLOCK" check doesn't fire.
    # Some violations may still be present (the unaddressed block is recorded) but not the compound one.
    # Key: no "synthesis verdict is APPROVE" compound message.
    assert not any(
        "synthesis verdict is approve" in v.lower() and "unaddressed" in v.lower()
        for v in violations
    )


# ---------------------------------------------------------------------------
# Critic block_flag coverage
# ---------------------------------------------------------------------------

def test_unaddressed_critic_flag_blocks() -> None:
    """Critic block_flag not in addressed_blocks → violation."""
    reviews = [_review("methodology", [])]
    memo = _critic_memo(["insufficient statistical power: n=1 seed"])
    synthesis = _synthesis(verdict="APPROVE", addressed=[])  # flag not addressed

    violations = check_synthesis_coverage(reviews, memo, synthesis)
    assert len(violations) >= 1
    assert any("insufficient statistical power" in v for v in violations)
    result = build_report(reviews, memo, synthesis)
    assert result["verdict"] == "BLOCK"


def test_addressed_critic_flag_passes() -> None:
    """Critic block_flag addressed in synthesis → no violation for that flag."""
    flag = "insufficient power: only 1 seed"
    reviews = [_review("methodology", [])]
    memo = _critic_memo([flag])
    synthesis = _synthesis(verdict="APPROVE", addressed=[flag])

    violations = check_synthesis_coverage(reviews, memo, synthesis)
    assert violations == []


# ---------------------------------------------------------------------------
# C1 regression: vacuous block_source cannot clear a critic flag
# ---------------------------------------------------------------------------

def test_c1_critic_flag_vacuous_block_source_dot_is_blocked() -> None:
    """C1 regression (a): critic flag + addressed block_source='.' → MUST be BLOCK.

    Previously the addr-in-flag_text direction (``'.' in 'insufficient power.'``) made
    a single-dot block_source match any flag that happened to contain a period, allowing
    an APPROVE to ship over an un-rebutted critic block.  The fix: only flag_text-in-addr
    direction is permitted (never addr-in-flag_text).
    """
    reviews = [_review("methodology", [])]
    flag = "insufficient power."
    memo = _critic_memo([flag])
    # block_source is a single dot — a vacuous token that should NOT match the flag
    synthesis = {
        "verdict": "APPROVE",
        "violations": [],
        "addressed_blocks": [{"block_source": ".", "rebuttal": "evidence-backed rebuttal here"}],
        "unaddressed_blocks": [],
        "open_critic_flags": [],
    }
    result = build_report(reviews, memo, synthesis)
    assert result["verdict"] == "BLOCK", (
        "C1 regression FAILED: vacuous block_source='.' cleared the critic flag; "
        "addr-in-flag_text direction must be disabled"
    )
    assert any("insufficient power" in v for v in result["violations"])


def test_c1_critic_flag_vacuous_rebuttal_dot_is_blocked() -> None:
    """C1 regression (b): critic flag + rebuttal='.' → MUST be BLOCK.

    A matching block_source with a non-substantive rebuttal (a single punctuation mark)
    must not count as addressed.
    """
    reviews = [_review("methodology", [])]
    flag = "insufficient power: only 1 seed"
    memo = _critic_memo([flag])
    synthesis = {
        "verdict": "APPROVE",
        "violations": [],
        "addressed_blocks": [{"block_source": flag, "rebuttal": "."}],  # rebuttal is a dot
        "unaddressed_blocks": [],
        "open_critic_flags": [],
    }
    result = build_report(reviews, memo, synthesis)
    assert result["verdict"] == "BLOCK", (
        "C1 regression FAILED: vacuous rebuttal='.' cleared the critic flag; "
        "rebuttal must be substantive"
    )


def test_c1_genuinely_addressed_critic_flag_passes() -> None:
    """C1 regression (c): genuine rebuttal with exact block_source matching flag text → PASS."""
    reviews = [_review("methodology", [])]
    flag = "insufficient power: only 1 seed"
    memo = _critic_memo([flag])
    synthesis = {
        "verdict": "APPROVE",
        "violations": [],
        "addressed_blocks": [
            {
                "block_source": flag,
                "rebuttal": "We ran 5 independent seeds; variance is 0.3% Dice (see run-record §4.2).",
            }
        ],
        "unaddressed_blocks": [],
        "open_critic_flags": [],
    }
    result = build_report(reviews, memo, synthesis)
    assert result["verdict"] == "PASS", (
        "C1 regression FAILED: a genuinely addressed flag with a real rebuttal should PASS"
    )
    assert result["violations"] == []


def test_c1_block_source_superset_of_flag_passes() -> None:
    """C1 regression: block_source that CONTAINS the flag text (flag_text in addr direction) → PASS.

    The correct one-directional containment: block_source may be a longer string that
    fully includes the flag (e.g. block_source = 'insufficient power: only 1 seed [resolved]').
    """
    reviews = [_review("methodology", [])]
    flag = "insufficient power: only 1 seed"
    memo = _critic_memo([flag])
    synthesis = {
        "verdict": "APPROVE",
        "violations": [],
        "addressed_blocks": [
            {
                "block_source": "insufficient power: only 1 seed [resolved per §4.2]",
                "rebuttal": "We ran 5 independent seeds; variance is 0.3% Dice (see run-record §4.2).",
            }
        ],
        "unaddressed_blocks": [],
        "open_critic_flags": [],
    }
    result = build_report(reviews, memo, synthesis)
    assert result["verdict"] == "PASS", (
        "C1 regression FAILED: block_source superset of flag_text (correct direction) should PASS"
    )


# ---------------------------------------------------------------------------
# Round-2 FIX 2: reviewer-BLOCK path also requires a SUBSTANTIVE rebuttal
#
# Before fix: the reviewer-BLOCK loop checked only exact block_source membership and
# DISCARDED the rebuttal — so a reviewer's BLOCK (the MORE serious signal) cleared
# with a 1-char rebuttal, while a critic block_flag (less serious) already required a
# substantive rebuttal. That asymmetry left the more serious signal LESS protected.
# After fix: reviewer-BLOCK requires exact membership AND a substantive rebuttal,
# mirroring the critic path.
# ---------------------------------------------------------------------------

def test_fix2_reviewer_block_one_char_rebuttal_is_blocked() -> None:
    """FIX 2 (proof of bug): reviewer BLOCK + exact block_source but 1-char rebuttal → MUST BLOCK.

    The block_source exactly names the finding id, so the OLD code cleared it on bare
    membership. The rebuttal is a single character ('x') — not substantive — so the gate
    must NOT treat the reviewer BLOCK as addressed.
    """
    reviews = [
        _review("methodology", [_finding("BLOCK", "section 3.2", finding_id="meth-block-01")]),
    ]
    memo = _critic_memo([])
    synthesis = {
        "verdict": "APPROVE",
        "violations": [],
        # block_source matches the finding id exactly, but rebuttal is a single char
        "addressed_blocks": [{"block_source": "meth-block-01", "rebuttal": "x"}],
        "unaddressed_blocks": [],
        "open_critic_flags": [],
    }
    violations = check_synthesis_coverage(reviews, memo, synthesis)
    assert any("meth-block-01" in v for v in violations), (
        f"reviewer BLOCK with a 1-char rebuttal must still be flagged unaddressed; got: {violations}"
    )
    result = build_report(reviews, memo, synthesis)
    assert result["verdict"] == "BLOCK", (
        "FIX 2 FAILED: a 1-char rebuttal cleared a reviewer BLOCK; the reviewer-BLOCK path "
        "must require a substantive rebuttal (mirroring the critic path)"
    )


def test_fix2_reviewer_block_exact_source_substantive_rebuttal_passes() -> None:
    """FIX 2 (no over-correction): reviewer BLOCK + exact block_source + substantive rebuttal → PASS.

    A genuine, substantive rebuttal that exactly names the finding id must still clear the
    reviewer BLOCK — the fix tightens vacuous rebuttals only, it must not break real ones.
    """
    reviews = [
        _review("methodology", [_finding("BLOCK", "section 3.2", finding_id="meth-block-01")]),
    ]
    memo = _critic_memo([])
    synthesis = {
        "verdict": "APPROVE",
        "violations": [],
        "addressed_blocks": [
            {
                "block_source": "meth-block-01",
                "rebuttal": "Re-ran the ablation with a held-out split; the effect persists (Δ=2.1 Dice, §4.3).",
            }
        ],
        "unaddressed_blocks": [],
        "open_critic_flags": [],
    }
    violations = check_synthesis_coverage(reviews, memo, synthesis)
    assert violations == [], (
        f"FIX 2 over-correction: a substantive rebuttal exactly naming the finding must clear "
        f"the reviewer BLOCK; got: {violations}"
    )
    result = build_report(reviews, memo, synthesis)
    assert result["verdict"] == "PASS"


# ---------------------------------------------------------------------------
# Real-profile shaped test: proves gate fires on realistic input
# ---------------------------------------------------------------------------

def test_real_profile_shaped_block_approve_over_unaddressed_fires() -> None:
    """Load cv-medical profile, construct a realistic APPROVE-over-unaddressed-BLOCK, confirm the gate fires.

    This test proves the gate is NOT dead on realistic, profile-shaped inputs — the exact scenario
    the contract demands.
    """
    with open(PROFILE_DIR / "cv-medical-segmentation.profile.yaml", encoding="utf-8") as fh:
        profile = yaml.safe_load(fh)

    # A realistic domain BLOCK: hard_invariant violated (patch-level split)
    domain_block_anchor = profile["hard_invariants"][0]  # "all splits must be patient-level or case-level"
    reviews = [
        _review("domain", [
            {
                "severity": "BLOCK",
                "anchor": domain_block_anchor,
                "evidence": "experiment_matrix.conditions[c2].split_unit='patch' violates profile invariant",
                "finding_id": "dom-block-real-01",
            }
        ]),
        _review("methodology", []),
    ]
    memo = _critic_memo([])

    # Synthesizer (incorrectly) says APPROVE without addressing the domain BLOCK
    synthesis = _synthesis(verdict="APPROVE", addressed=[])

    violations = check_synthesis_coverage(reviews, memo, synthesis)
    assert len(violations) >= 1, (
        "CRITICAL: gate did not fire on a realistic APPROVE-over-unaddressed-BLOCK; "
        "this is a dead gate"
    )
    result = build_report(reviews, memo, synthesis)
    assert result["verdict"] == "BLOCK"
