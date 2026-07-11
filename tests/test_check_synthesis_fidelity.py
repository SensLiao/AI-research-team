"""Tests for check_synthesis_fidelity — prose/structured verdict consistency check.

The key invariant: prose verdict word must be consistent with the structured verdict.
  - structured BLOCK + prose "no concerns" → violation (MUST be caught).
  - structured APPROVE + prose "concerns" → violation.
  - structured_verdict in synthesis_text must mirror panel_synthesis.verdict.
"""
from __future__ import annotations

from research_agent_teams.tools.check_synthesis_fidelity import (
    build_report,
    check_synthesis_fidelity,
)


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------

def _panel_synthesis(verdict: str) -> dict:
    return {
        "verdict": verdict,
        "violations": [],
        "addressed_blocks": [],
        "unaddressed_blocks": [],
        "open_critic_flags": [],
    }


def _synthesis_text(structured_verdict: str, prose_verdict_word: str, body: str = "body text") -> dict:
    return {
        "structured_verdict": structured_verdict,
        "prose_verdict_word": prose_verdict_word,
        "body": body,
    }


# ---------------------------------------------------------------------------
# Happy paths
# ---------------------------------------------------------------------------

def test_approve_consistent_no_violation() -> None:
    """APPROVE structure + 'approve' prose → no violations."""
    ps = _panel_synthesis("APPROVE")
    st = _synthesis_text("APPROVE", "approve")
    violations = check_synthesis_fidelity(ps, st)
    assert violations == []
    assert build_report(ps, st)["verdict"] == "PASS"


def test_block_consistent_no_violation() -> None:
    """BLOCK structure + 'block' prose → no violations."""
    ps = _panel_synthesis("BLOCK")
    st = _synthesis_text("BLOCK", "block")
    violations = check_synthesis_fidelity(ps, st)
    assert violations == []
    assert build_report(ps, st)["verdict"] == "PASS"


def test_block_with_concerns_prose_passes() -> None:
    """BLOCK structure + 'concerns' prose (signal word present) → no violations."""
    ps = _panel_synthesis("BLOCK")
    st = _synthesis_text("BLOCK", "concerns")
    assert check_synthesis_fidelity(ps, st) == []


def test_block_with_issues_prose_passes() -> None:
    """BLOCK structure + 'issues' prose → no violations."""
    ps = _panel_synthesis("BLOCK")
    st = _synthesis_text("BLOCK", "issues identified")
    assert check_synthesis_fidelity(ps, st) == []


def test_approve_with_ready_prose_passes() -> None:
    """APPROVE structure + 'ready for submission' (no block signal) → no violations."""
    ps = _panel_synthesis("APPROVE")
    st = _synthesis_text("APPROVE", "ready for submission")
    assert check_synthesis_fidelity(ps, st) == []


# ---------------------------------------------------------------------------
# Critical mismatch: BLOCK structure + "no concerns" prose
# ---------------------------------------------------------------------------

def test_block_structure_but_no_concerns_prose_is_caught() -> None:
    """THE KEY MISMATCH: structured BLOCK but prose says 'no concerns'.

    This is the scenario the fidelity check must catch: the writer crafted
    optimistic prose while the structured verdict is BLOCK.
    "no concerns" is an approve-signal → fidelity check flags it.
    """
    ps = _panel_synthesis("BLOCK")
    st = _synthesis_text("BLOCK", "no concerns")  # approve-signal in BLOCK context

    violations = check_synthesis_fidelity(ps, st)
    assert len(violations) >= 1
    assert any("block" in v.lower() and ("no concerns" in v.lower() or "approve" in v.lower()) for v in violations)
    assert build_report(ps, st)["verdict"] == "BLOCK"


def test_block_structure_but_approve_prose_is_caught() -> None:
    """BLOCK structure + 'approve' prose → violation (approving in prose when blocked structurally)."""
    ps = _panel_synthesis("BLOCK")
    st = _synthesis_text("BLOCK", "approve")  # "approve" IS a block signal? No — it's the opposite.
    # "approve" has no block-signal word → violation
    violations = check_synthesis_fidelity(ps, st)
    assert len(violations) >= 1


def test_block_structure_but_work_is_ready_prose_blocked() -> None:
    """BLOCK structure + 'the work is ready' (no block signal) → violation."""
    ps = _panel_synthesis("BLOCK")
    st = _synthesis_text("BLOCK", "the work is ready")
    violations = check_synthesis_fidelity(ps, st)
    assert len(violations) >= 1


# ---------------------------------------------------------------------------
# Mismatch: APPROVE structure + block-signal prose
# ---------------------------------------------------------------------------

def test_approve_structure_but_concerns_prose_is_caught() -> None:
    """APPROVE structure + 'concerns' prose → violation."""
    ps = _panel_synthesis("APPROVE")
    st = _synthesis_text("APPROVE", "concerns about validity")
    violations = check_synthesis_fidelity(ps, st)
    assert len(violations) >= 1
    assert any("approve" in v.lower() and "concern" in v.lower() for v in violations)
    assert build_report(ps, st)["verdict"] == "BLOCK"


def test_approve_structure_but_fail_prose_is_caught() -> None:
    """APPROVE structure + 'fail' prose → violation."""
    ps = _panel_synthesis("APPROVE")
    st = _synthesis_text("APPROVE", "fails on external validity")
    violations = check_synthesis_fidelity(ps, st)
    assert len(violations) >= 1


# ---------------------------------------------------------------------------
# Internal consistency: structured_verdict mismatch
# ---------------------------------------------------------------------------

def test_structured_verdict_copy_mismatch_is_caught() -> None:
    """synthesis_text.structured_verdict != panel_synthesis.verdict → violation."""
    ps = _panel_synthesis("APPROVE")
    st = _synthesis_text("BLOCK", "no concerns")  # structured_verdict copy says BLOCK, panel says APPROVE
    violations = check_synthesis_fidelity(ps, st)
    assert any("structured_verdict" in v or "does not match" in v.lower() for v in violations)


def test_missing_prose_verdict_word_is_caught() -> None:
    """Empty prose_verdict_word → violation."""
    ps = _panel_synthesis("BLOCK")
    st = _synthesis_text("BLOCK", "")
    violations = check_synthesis_fidelity(ps, st)
    assert any("empty" in v.lower() or "prose_verdict_word" in v.lower() for v in violations)


# ---------------------------------------------------------------------------
# build_report verdict integrity
# ---------------------------------------------------------------------------

def test_build_report_pass_when_consistent() -> None:
    ps = _panel_synthesis("APPROVE")
    st = _synthesis_text("APPROVE", "approved — ready")
    result = build_report(ps, st)
    assert result["verdict"] == "PASS"
    assert result["violations"] == []


def test_build_report_block_on_mismatch() -> None:
    ps = _panel_synthesis("BLOCK")
    st = _synthesis_text("BLOCK", "no issues identified")  # no block signal in prose
    result = build_report(ps, st)
    assert result["verdict"] == "BLOCK"
    assert len(result["violations"]) >= 1


# ---------------------------------------------------------------------------
# M4 regression: word-boundary matching + negated-positive phrase handling
# ---------------------------------------------------------------------------

def test_m4a_approve_no_concerns_identified_no_violation() -> None:
    """M4 regression (a): APPROVE + 'no concerns identified' → NO violation.

    Previously the bare word 'concern' in _BLOCK_SIGNALS fired on substring match
    against 'no concerns identified', producing a false-positive violation when the
    structured verdict was APPROVE.  The fix: negated-positive phrases are recognised
    as APPROVE signals first, and bare block-signal words use word-boundary matching.
    """
    ps = _panel_synthesis("APPROVE")
    st = _synthesis_text("APPROVE", "no concerns identified")
    violations = check_synthesis_fidelity(ps, st)
    assert violations == [], (
        "M4 regression (a) FAILED: false positive — 'no concerns identified' under APPROVE "
        "should produce no violation"
    )
    assert build_report(ps, st)["verdict"] == "PASS"


def test_m4b_block_no_concerns_is_violation() -> None:
    """M4 regression (b): BLOCK + 'no concerns' → MUST be a violation (whitewash caught).

    'no concerns' is an approve-signal; it contradicts a BLOCK structured verdict.
    This must still fire after the word-boundary fix.
    """
    ps = _panel_synthesis("BLOCK")
    st = _synthesis_text("BLOCK", "no concerns")
    violations = check_synthesis_fidelity(ps, st)
    assert len(violations) >= 1, (
        "M4 regression (b) FAILED: 'no concerns' under BLOCK must be a violation (whitewash)"
    )
    assert build_report(ps, st)["verdict"] == "BLOCK"


def test_m4c_block_neutral_prose_no_block_signal_is_violation() -> None:
    """M4 regression (c): BLOCK + neutral prose with no verdict word → violation.

    'done' contains no block-signal or approve-signal word — the writer failed to
    include a verdict word consistent with BLOCK.  The checker must flag absent
    block-signal prose under a BLOCK structure.
    """
    ps = _panel_synthesis("BLOCK")
    st = _synthesis_text("BLOCK", "done")
    violations = check_synthesis_fidelity(ps, st)
    assert len(violations) >= 1, (
        "M4 regression (c) FAILED: neutral prose 'done' under BLOCK should be flagged; "
        "prose must carry a block-consistent signal word"
    )


def test_m4_word_boundary_tissue_no_false_positive() -> None:
    """M4 word-boundary: 'tissue' contains 'issue' but must NOT trigger the block-signal check."""
    ps = _panel_synthesis("APPROVE")
    st = _synthesis_text("APPROVE", "soft tissue analysis complete")
    violations = check_synthesis_fidelity(ps, st)
    assert violations == [], (
        "M4 word-boundary FAILED: 'tissue' must not trigger the 'issue' block signal"
    )


def test_m4_word_boundary_failure_triggers() -> None:
    """M4 word-boundary: standalone 'fail' in prose under APPROVE IS a block signal."""
    ps = _panel_synthesis("APPROVE")
    st = _synthesis_text("APPROVE", "results fail to generalise")
    violations = check_synthesis_fidelity(ps, st)
    assert len(violations) >= 1, (
        "M4 word-boundary FAILED: 'fail' (standalone) under APPROVE should be a violation"
    )
