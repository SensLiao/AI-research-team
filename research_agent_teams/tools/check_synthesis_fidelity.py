"""Deterministic core of the synthesis-writer fidelity check (VERIFY panel).

Validates that the prose verdict written in synthesis_text is consistent with the
structured verdict declared in panel_synthesis. The classic failure mode: a writer
crafting prose that says "no concerns, the work is ready" while the structured verdict
is BLOCK — the prose and structure diverge, and a reader of only the prose would be
misled.

Rules:
  - If structured_verdict is BLOCK: prose_verdict_word must NOT contain an approve-only
    signal word (case-insensitive: "approve", "ready", "no concerns", "no issues",
    "no problem", "pass", "cleared", "accepted").  Prose saying "block", "concerns",
    "issues" or "reject" is fine.  Prose saying "no concerns" is a mismatch.
  - If structured_verdict is APPROVE: prose_verdict_word must NOT contain a hard-block
    signal word (case-insensitive: "block", "reject", "fail", "concern", "issue",
    "problem", "not ready", "incomplete").
  - A mismatch in either direction is a violation.

The two rule sets are deliberately asymmetric:
  - BLOCK gate: catches prose that whitewashes a BLOCK ("no concerns" / "approve").
  - APPROVE gate: catches prose that raises concerns when everything passed.

Inputs consumed (both are payload dicts, not enveloped artifacts):
  - ``panel_synthesis``: the panel_synthesis payload (has ``verdict``).
  - ``synthesis_text``: the synthesis_text payload (has ``structured_verdict``,
    ``prose_verdict_word``).

The checker also validates internal consistency of synthesis_text itself: the
``structured_verdict`` field in synthesis_text must match panel_synthesis.verdict.

Matching semantics (M4 fix):
  Signal words are matched on WORD BOUNDARIES using ``re.search(r'\\b<word>\\b', text)``.
  This prevents false positives from substrings (e.g. the word "issue" inside "tissue").

  Negated-positive phrases ("no concerns", "no issues", "no problems") are APPROVE
  signals — they belong in _APPROVE_SIGNALS and are matched as multi-word phrases.
  The bare negative words ("concern", "issue", "problem") remain in _BLOCK_SIGNALS for
  APPROVE-gate checking; they are NOT incorrectly fired when the phrase begins with "no "
  because phrase-level approve-signal detection runs first and the per-word block-signal
  detection uses word-boundary matching that only fires on the isolated word.

  Consequence: "no concerns identified" under an APPROVE verdict triggers no violation
  (the approve signal "no concerns" is expected); under a BLOCK verdict it still triggers
  a violation (the approve signal "no concerns" contradicts the BLOCK structure).
"""
from __future__ import annotations

import re
from typing import List

# Words/phrases that signal an approving / positive verdict in prose.
# Used to detect "no concerns" / "approve" / "ready" in a BLOCK-structured text.
# Multi-word negated-positive phrases ("no concerns") must live here, not in _BLOCK_SIGNALS,
# so they are treated as APPROVE signals rather than BLOCK signals.
_APPROVE_SIGNALS: frozenset[str] = frozenset([
    "approve",
    "approved",
    "no concerns",
    "no issues",
    "no problem",
    "no problems",
    "ready",
    "pass",
    "passed",
    "cleared",
    "accepted",
    "all clear",
    "looks good",
])

# Words/phrases that signal a blocking / negative verdict in prose.
# Used to detect "concerns" / "block" / "fail" in an APPROVE-structured text.
# These are single words matched at WORD BOUNDARIES — they do not fire inside "no concerns"
# because the phrase-level approve-signal check has already classified that phrase.
_BLOCK_SIGNALS: frozenset[str] = frozenset([
    "block",
    "reject",
    "fail",
    "concern",
    "issue",
    "problem",
    "not ready",
    "incomplete",
])

# Negated-positive phrases: when the prose contains one of these phrases, the bare
# negative word that appears in it (e.g. "concern" inside "no concerns") must NOT
# independently fire the block-signal check.  We strip these first before word-boundary
# checking to avoid double-counting.
_NEGATED_POSITIVE_PHRASES: tuple[str, ...] = (
    "no concerns",
    "no issues",
    "no problem",
    "no problems",
)


def _contains_approve_signal(text: str) -> bool:
    """True if ``text`` (lowercased) contains any approve-signal word/phrase.

    Multi-word phrases are checked as literal substrings (they include their own
    word-boundary context).  Single words are matched with a leading ``\\b`` word
    boundary (prefix match) so inflected forms like "approved" also match "approve".
    """
    lower = text.lower()
    for signal in _APPROVE_SIGNALS:
        if " " in signal:
            # multi-word phrase: substring match is unambiguous
            if signal in lower:
                return True
        else:
            # prefix match: \b<signal> catches "ready", "readying", etc.
            if re.search(r"\b" + re.escape(signal), lower):
                return True
    return False


def _contains_block_signal(text: str) -> bool:
    """True if ``text`` (lowercased) contains any block-signal word/phrase.

    Before checking bare negative words, negated-positive phrases ("no concerns" etc.)
    are removed from the text so they do not trigger the block-signal check for their
    constituent words.

    Single signal words use a leading ``\\b`` word boundary (prefix match) so
    inflected forms like "concerns", "fails", "issues" match their signal roots
    ("concern", "fail", "issue") without matching unrelated substrings like "tissue".
    """
    lower = text.lower()
    # Remove negated-positive phrases so "no concerns" does not fire "concern".
    scrubbed = lower
    for phrase in _NEGATED_POSITIVE_PHRASES:
        scrubbed = scrubbed.replace(phrase, " ")
    for signal in _BLOCK_SIGNALS:
        if " " in signal:
            # multi-word phrase: substring match (already negation-scrubbed above)
            if signal in scrubbed:
                return True
        else:
            # prefix match: \b<signal> catches inflected forms (concerns, fails, issues…)
            if re.search(r"\b" + re.escape(signal), scrubbed):
                return True
    return False


def check_synthesis_fidelity(
    panel_synthesis: dict,
    synthesis_text: dict,
) -> List[str]:
    """Return violations (empty list == prose and structured verdict are consistent).

    Parameters
    ----------
    panel_synthesis : dict
        panel_synthesis payload; must have ``verdict``.
    synthesis_text : dict
        synthesis_text payload; must have ``structured_verdict`` and ``prose_verdict_word``.

    Returns
    -------
    List[str]
        Human-readable violations; empty == fidelity confirmed.
    """
    violations: List[str] = []

    structured_from_synthesis = panel_synthesis.get("verdict", "")
    structured_copy_in_text = synthesis_text.get("structured_verdict", "")
    prose_word = synthesis_text.get("prose_verdict_word", "")

    # 1. Internal consistency: structured_verdict in synthesis_text must mirror panel_synthesis.
    if structured_from_synthesis and structured_copy_in_text:
        if structured_from_synthesis != structured_copy_in_text:
            violations.append(
                f"synthesis_text.structured_verdict='{structured_copy_in_text}' does not match "
                f"panel_synthesis.verdict='{structured_from_synthesis}'; "
                "structured_verdict must be copied verbatim from panel_synthesis"
            )

    # Use the authoritative structured verdict (from panel_synthesis if available).
    authoritative_verdict = structured_from_synthesis or structured_copy_in_text

    if not authoritative_verdict:
        violations.append(
            "cannot determine structured verdict: neither panel_synthesis.verdict nor "
            "synthesis_text.structured_verdict is set"
        )
        return violations

    if not prose_word or not prose_word.strip():
        violations.append(
            "synthesis_text.prose_verdict_word is empty; "
            "writer must provide the verdict word as it appears in the prose body"
        )
        return violations

    prose_has_approve_signal = _contains_approve_signal(prose_word)
    prose_has_block_signal = _contains_block_signal(prose_word)

    # 2. BLOCK structure → prose must NOT whitewash with approve-only language.
    #    "no concerns", "approve", "ready", "no issues" etc. contradict a BLOCK verdict.
    if authoritative_verdict == "BLOCK" and prose_has_approve_signal:
        violations.append(
            f"structured verdict is BLOCK but prose_verdict_word='{prose_word}' contains "
            f"an approve-signal word/phrase {sorted(_APPROVE_SIGNALS)}; "
            "prose must not say 'no concerns' / 'approve' / 'ready' when the panel blocks"
        )

    # 2b. BLOCK structure → prose MUST carry a block-signal word (or phrase).
    #     Neutral prose ("done", "complete", "finished") that carries no verdict word
    #     allows a reader of the prose alone to miss the BLOCK verdict — this is the
    #     "absence of signal" failure mode.  Prose must explicitly signal the block.
    if authoritative_verdict == "BLOCK" and not prose_has_approve_signal and not prose_has_block_signal:
        violations.append(
            f"structured verdict is BLOCK but prose_verdict_word='{prose_word}' contains "
            f"neither a block-signal {sorted(_BLOCK_SIGNALS)} nor an approve-signal; "
            "prose under a BLOCK verdict must include a word that signals the blocking "
            "(e.g. 'block', 'concerns', 'issues', 'fail', 'reject', 'incomplete')"
        )

    # 3. APPROVE structure → prose must NOT signal BLOCK.
    if authoritative_verdict == "APPROVE" and prose_has_block_signal:
        violations.append(
            f"structured verdict is APPROVE but prose_verdict_word='{prose_word}' contains "
            f"a block-signal word {sorted(_BLOCK_SIGNALS)}; "
            "prose cannot raise concerns when the structured verdict is APPROVE"
        )

    return violations


def build_report(
    panel_synthesis: dict,
    synthesis_text: dict,
) -> dict:
    """Build a synthesis fidelity check report.

    ``verdict`` is derived from violations — never set by hand.
    """
    v = check_synthesis_fidelity(panel_synthesis, synthesis_text)
    return {
        "verdict": "BLOCK" if v else "PASS",
        "violations": v,
    }
