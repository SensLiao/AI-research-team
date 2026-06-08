"""Deterministic core of the review-synthesizer coverage check (VERIFY panel).

The panel's core integrity guarantee:
  - A synthesis verdict of APPROVE is REFUSED if any underlying reviewer's BLOCK finding
    is not explicitly addressed (rebutted) in the addressed_blocks list.
  - A synthesis verdict of APPROVE is REFUSED if any critic block_flag is not explicitly
    addressed (rebutted) in the addressed_blocks list.

This prevents the single most dangerous failure mode: a synthesizer writing "APPROVE"
while a reviewer has BLOCK findings that were simply ignored.

Inputs consumed:
  - ``panel_reviews``: list of panel_review payloads (from methodology-reviewer and
    domain-reviewer); each has ``findings[]`` with ``severity`` and optional ``finding_id``.
  - ``critic_memo``: the critic_memo payload; has ``block_flags[]`` each with ``flag_text``.
  - ``synthesis``: the candidate panel_synthesis payload being validated.

The checker operates PURELY over these dict payloads — no I/O, no LLM.

Matching semantics:
  Reviewer BLOCK findings are matched by EXACT block_source membership
  (``block_id == addr_src``) AND require a *substantive* rebuttal on the matching
  entry.  A reviewer BLOCK is the MORE serious signal, so it must be at least as well
  protected as a critic block_flag — a vacuous 1-char rebuttal must NOT clear it
  (round-2 FIX 2: the reviewer-BLOCK path previously discarded the rebuttal and
  cleared on bare membership, an asymmetry where the more serious signal was less
  protected).

  Critic block_flags are matched with a one-directional containment rule:
    ``flag_text in addr``  — the addressed entry CONTAINS the flag text
  Never the reverse (``addr in flag_text``): that direction lets a single-character
  block_source such as "." match any flag_text that happens to include that character,
  defeating the gate with a vacuous token.

  In BOTH paths, the matching addressed_blocks entry must carry a *substantive*
  rebuttal — a rebuttal that is empty or shorter than _MIN_REBUTTAL_LEN
  non-whitespace characters does NOT count as addressed.
"""
from __future__ import annotations

from typing import List

# A rebuttal must contain at least this many non-whitespace characters to be considered
# substantive.  A single punctuation mark (".", "x", "1 ") cannot clear a BLOCK.
_MIN_REBUTTAL_LEN: int = 4


def _collect_block_finding_ids(panel_reviews: List[dict]) -> List[str]:
    """Collect identifiers for all BLOCK-severity findings across all panel reviews.

    Uses ``finding_id`` when non-empty, otherwise falls back to anchor text.
    """
    block_ids: List[str] = []
    for review in panel_reviews:
        lens = review.get("lens", "<unknown>")
        for finding in review.get("findings") or []:
            if finding.get("severity") == "BLOCK":
                fid = finding.get("finding_id", "")
                anchor = finding.get("anchor", "")
                identifier = fid if (fid and fid.strip()) else anchor
                if not identifier or not identifier.strip():
                    identifier = f"<unnamed-block-{lens}>"
                block_ids.append(identifier)
    return block_ids


def _collect_critic_block_flags(critic_memo: dict) -> List[str]:
    """Collect all block_flag texts from a critic_memo payload."""
    flags: List[str] = []
    for flag in critic_memo.get("block_flags") or []:
        flag_text = flag.get("flag_text", "")
        if flag_text and flag_text.strip():
            flags.append(flag_text)
    return flags


def _addressed_entries(synthesis: dict) -> List[tuple[str, str]]:
    """Return list of (block_source_stripped, rebuttal_stripped) from addressed_blocks.

    Only entries with a non-empty block_source are included (empty source cannot
    address anything).
    """
    entries: List[tuple[str, str]] = []
    for item in synthesis.get("addressed_blocks") or []:
        src = item.get("block_source", "")
        rebuttal = item.get("rebuttal", "")
        if src and src.strip():
            entries.append((src.strip(), rebuttal.strip() if rebuttal else ""))
    return entries


def _is_substantive_rebuttal(rebuttal: str) -> bool:
    """Return True iff the rebuttal has at least _MIN_REBUTTAL_LEN non-whitespace chars."""
    return len(rebuttal.replace(" ", "").replace("\t", "").replace("\n", "")) >= _MIN_REBUTTAL_LEN


def _reviewer_block_is_addressed(block_id: str, entries: List[tuple[str, str]]) -> bool:
    """Return True iff a reviewer BLOCK finding id is addressed by a substantive entry.

    Matching rule for reviewer BLOCK findings is EXACT block_source membership
    (``block_id == addr_src``) — the synthesizer must name the finding id/anchor
    verbatim.  The matching entry must ALSO carry a substantive rebuttal: a reviewer
    BLOCK is the MORE serious signal, so it must be at least as well protected as a
    critic block_flag (which already requires a substantive rebuttal).  A 1-char
    rebuttal like "x" does NOT clear a reviewer BLOCK.
    """
    for addr_src, rebuttal in entries:
        if block_id == addr_src and _is_substantive_rebuttal(rebuttal):
            return True
    return False


def _critic_flag_is_addressed(flag_text: str, entries: List[tuple[str, str]]) -> bool:
    """Return True iff flag_text is addressed by at least one substantive entry.

    Matching rule (one-directional containment):
      ``flag_text in addr_src``  — the stored block_source fully contains the flag text.
    The reverse (``addr_src in flag_text``) is intentionally excluded: it would allow a
    vacuous block_source such as "." to match any flag that contains a period.

    Additionally, the matching entry must carry a substantive rebuttal.
    """
    for addr_src, rebuttal in entries:
        # Exact membership first (most common path when the synthesizer copies the flag verbatim)
        match = (flag_text == addr_src) or (flag_text in addr_src)
        if match and _is_substantive_rebuttal(rebuttal):
            return True
    return False


def check_synthesis_coverage(
    panel_reviews: List[dict],
    critic_memo: dict,
    synthesis: dict,
) -> List[str]:
    """Return violations (empty list == synthesis coverage is complete).

    The core guarantee: APPROVE verdict with any unaddressed BLOCK finding or unaddressed
    critic block_flag → violation. A coverage check that cannot catch this is a dead check.

    Parameters
    ----------
    panel_reviews : list[dict]
        panel_review payloads from all panel reviewers.
    critic_memo : dict
        critic_memo payload from the scientific-critic.
    synthesis : dict
        Candidate panel_synthesis payload to validate.

    Returns
    -------
    List[str]
        Human-readable violations; empty == clean and synthesis may be emitted.
    """
    violations: List[str] = []
    synthesis_verdict = synthesis.get("verdict", "")
    entries = _addressed_entries(synthesis)

    # --- 1. Check reviewer BLOCK findings ---
    # Exact block_source membership AND a substantive rebuttal are required. A reviewer
    # BLOCK is the more serious signal, so it must be at least as protected as a critic
    # block_flag — a vacuous 1-char rebuttal must NOT clear it.
    block_finding_ids = _collect_block_finding_ids(panel_reviews)
    for bid in block_finding_ids:
        if not _reviewer_block_is_addressed(bid, entries):
            violations.append(
                f"reviewer BLOCK finding '{bid}' is not addressed in synthesis.addressed_blocks "
                "with a substantive rebuttal; "
                "synthesis cannot APPROVE with an unaddressed reviewer BLOCK"
            )

    # --- 2. Check critic block_flags ---
    # Matching: flag_text must be contained-in (or equal to) block_source (one direction only).
    # A matching entry must also carry a substantive rebuttal (not a vacuous token like ".").
    critic_flags = _collect_critic_block_flags(critic_memo)
    for flag_text in critic_flags:
        if not _critic_flag_is_addressed(flag_text, entries):
            violations.append(
                f"critic block_flag '{flag_text[:80]}' is not addressed in synthesis.addressed_blocks; "
                "synthesis cannot APPROVE with an undocumented critic block_flag"
            )

    # --- 3. APPROVE-over-unaddressed-BLOCK is the critical dead-gate scenario ---
    # Even if blocks listed in unaddressed_blocks match violations, a hand-set APPROVE
    # with non-empty violations must be caught.
    if synthesis_verdict == "APPROVE" and violations:
        violations.insert(
            0,
            f"synthesis verdict is APPROVE but {len(violations)} unaddressed BLOCK(s)/flag(s) found; "
            "verdict must be BLOCK until all reviewer BLOCKs and critic flags are addressed"
        )

    return violations


def build_report(
    panel_reviews: List[dict],
    critic_memo: dict,
    synthesis: dict,
) -> dict:
    """Build a synthesis coverage check report.

    ``verdict`` is derived from violations — never set by hand.
    BLOCK if any violations; PASS if none.
    """
    v = check_synthesis_coverage(panel_reviews, critic_memo, synthesis)
    return {
        "verdict": "BLOCK" if v else "PASS",
        "violations": v,
    }
