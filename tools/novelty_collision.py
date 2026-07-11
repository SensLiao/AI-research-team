"""Evidenced prior-art collision verdict (novelty-collision-upgrade; see
``_design/novelty-collision-upgrade-LEDGER.md``).

The machine's standing rule is **"a novelty SCORE never cuts"** (``idea_grounding.py``,
``novelty_aggregate.py``) — a score is a fuzzy opinion and must never silently kill an idea. This
module does NOT repeal that. It adds a different, stronger mechanism keyed on EVIDENCE, not score:

  > A novelty SCORE never cuts (unchanged). An EVIDENCED prior-art COLLISION can cut (new):
  > a *specific, existence-verified paper* that *demonstrably did the same method×problem* and
  > *actually ran/implemented it*. A score is an opinion; a collision is a fact with a citation.

This is the deterministic core (pure given its inputs): the LLM ``novelty-collision-checker`` worker
gathers the per-idea collision findings (semantic judgment), the caller
(``operate.modes._shared.run_collision_gate``) does the real ``citation_existence`` lookup and the
ledger pre-match, and this function combines them into a per-idea verdict. It performs NO I/O, NO
network, and NEVER reads the wall clock — same inputs always yield the same payload (stable ordering).

The four honest verdicts (this IS the director's methodology, encoded):

  DEAD        a real paper (exists ✓) did THIS method × THIS problem AND ran/implemented it
              -> ``cut = hard_block`` + recorded to the known-prior-art ledger by the caller.
  WHITE_SPACE the combination exists but on a different application/problem, OR was proposed but
              never experimentally validated here -> KEEP + flag ◇ (the publishable sweet spot).
  CLEAR       the independent checker emitted an explicit per-idea clear finding after targeted
              retrieval -> KEEP ✓ (honest: "no collision found", not "proven novel").
  UNVERIFIED  retrieval unavailable, OR a claimed collider could not be existence-verified ->
              KEEP but loudly flag; never cut on an unproven/nonexistent paper.

Anti-false-cut safety (the expensive error is killing a good idea): a CUT requires the colliding
paper to PASS ``citation_existence`` — a fabricated/nonexistent/unconfirmable paper can NEVER justify
a cut (it degrades to UNVERIFIED instead). The collision judgment comes from an INDEPENDENT worker,
never the idea's proposer (enforced upstream by the orchestrator).
"""
from __future__ import annotations

from typing import Dict, List, Optional

# Verdict vocabulary (the four honest states; see module docstring + design §1).
VERDICT_DEAD = "DEAD"
VERDICT_WHITE_SPACE = "WHITE_SPACE"
VERDICT_CLEAR = "CLEAR"
VERDICT_UNVERIFIED = "UNVERIFIED"

# Source of a verdict (which channel established it).
SOURCE_WORKER = "worker"
SOURCE_LEDGER = "ledger"

# Worker collision-finding verdicts (the checker worker's semantic judgment per idea).
WORKER_COLLISION = "collision"
WORKER_ADJACENT = "adjacent"
WORKER_CLEAR = "clear"

# Existence states that COUNT as a paper proven to exist. ``citation_existence`` is the single
# source of truth; its real proven-exists string is ``"verified"`` (citation_existence.STATE_VERIFIED).
# The design's §3.1 abstraction names the same state ``"EXISTS"`` — both are accepted so this core is
# robust to either caller convention; everything else (``not_found``/``lookup_error``/``skipped``/
# ``NONEXISTENT``/``UNKNOWN``/missing) is treated as NOT-proven-to-exist and can never justify a cut.
_EXISTS_STATES = frozenset({"verified", "EXISTS"})


def _ref_exists(existence_by_ref: Dict[str, str], ref: str) -> bool:
    """True iff ``ref`` is positively existence-verified (per ``citation_existence``).

    A missing key or any non-exists state (``not_found`` / ``lookup_error`` / ``skipped`` /
    ``NONEXISTENT`` / ``UNKNOWN``) is False: absence of proof is never proof, so it can never cut."""
    return existence_by_ref.get(ref) in _EXISTS_STATES


def _validate_inputs(menu_ideas: List[dict]) -> List[str]:
    """Validate the idea menu exactly like ``idea_grounding.score_idea_grounding`` does, and return
    the ordered idea_id list. Raises ``ValueError`` on a missing / non-string / duplicate idea_id."""
    if not menu_ideas:
        raise ValueError(
            "build_collision_verdict requires at least one idea (every idea must appear in output)")
    ids = [i.get("idea_id") for i in menu_ideas]
    if any(not isinstance(x, str) or not x.strip() for x in ids):
        raise ValueError(f"every idea needs a non-empty idea_id: {ids}")
    if len(set(ids)) != len(ids):
        raise ValueError(f"duplicate idea_id: {sorted(x for x in ids if ids.count(x) > 1)}")
    return ids


def _colliding_paper_view(paper: dict, existence_by_ref: Dict[str, str]) -> dict:
    """Project one worker colliding-paper entry into the report's colliding_papers shape, stamping
    the deterministic existence state from ``existence_by_ref`` (real ``citation_existence`` string)."""
    ref = str(paper.get("ref") or "").strip()
    return {
        "ref": ref,
        "existence": existence_by_ref.get(ref, "UNKNOWN"),
        "experimentally_validated": bool(paper.get("experimentally_validated")),
    }


def _verdict_from_worker(finding: dict, existence_by_ref: Dict[str, str], *,
                         cut_requires_experiments: bool, hard_block: bool,
                         retrieval_grounded: bool) -> dict:
    """Derive a single idea's verdict from its worker collision finding (no ledger hit on this idea).

    DEAD requires ALL of: worker says ``collision`` AND ≥1 colliding ref is existence-verified AND
    that same paper does the same method on the same problem AND (if ``cut_requires_experiments``) it
    was experimentally validated. Anything weaker degrades — never up — to WHITE_SPACE / UNVERIFIED."""
    idea_id = finding["idea_id"]
    worker = finding.get("verdict")
    raw_papers = [p for p in (finding.get("colliding_papers") or []) if isinstance(p, dict)]
    papers_view = [_colliding_paper_view(p, existence_by_ref) for p in raw_papers]

    if worker == WORKER_COLLISION:
        # A paper can justify a CUT only if it EXISTS (fact-checked) AND it did the same
        # method×problem AND (when required) it actually ran/implemented it.
        cut_papers = [
            p for p in raw_papers
            if _ref_exists(existence_by_ref, str(p.get("ref") or "").strip())
            and bool(p.get("does_same_method_on_same_problem"))
            and (bool(p.get("experimentally_validated")) if cut_requires_experiments else True)
        ]
        if cut_papers:
            exp_note = " and ran experiments" if cut_requires_experiments else ""
            refs = ", ".join(str(p.get("ref") or "").strip() for p in cut_papers)
            return {
                "idea_id": idea_id,
                "verdict": VERDICT_DEAD,
                "cut": bool(hard_block),
                "colliding_papers": papers_view,
                "reason": (f"existence-verified prior art did the same method on the same "
                           f"problem{exp_note}: {refs}"),
                "source": SOURCE_WORKER,
            }
        # Worker flagged a collision but no colliding paper is existence-verified (or none meets the
        # same-method/experiment bar): never cut on an unproven/nonexistent paper -> UNVERIFIED.
        any_exists = any(_ref_exists(existence_by_ref, str(p.get("ref") or "").strip())
                         for p in raw_papers)
        if not raw_papers:
            reason = ("worker reported a collision but named no specific paper — "
                      "cannot cut without an existence-verified collider")
        elif not any_exists:
            reason = ("worker reported a collision but no colliding paper passed citation_existence "
                      "(nonexistent / unconfirmable) — never cut on an unproven paper")
        else:
            reason = ("worker reported a collision but no existence-verified paper does the same "
                      "method on the same problem with experiments — downgraded, never cut")
        return {
            "idea_id": idea_id,
            "verdict": VERDICT_UNVERIFIED,
            "cut": False,
            "colliding_papers": papers_view,
            "reason": reason,
            "source": SOURCE_WORKER,
        }

    if worker == WORKER_ADJACENT:
        return {
            "idea_id": idea_id,
            "verdict": VERDICT_WHITE_SPACE,
            "cut": False,
            "colliding_papers": papers_view,
            "reason": ("combination exists on a different application/problem or was proposed but "
                       "not experimentally validated here — keep + flag (publishable white space)"),
            "source": SOURCE_WORKER,
        }

    if worker == WORKER_CLEAR:
        if retrieval_grounded:
            return {
                "idea_id": idea_id,
                "verdict": VERDICT_CLEAR,
                "cut": False,
                "colliding_papers": papers_view,
                "reason": "targeted retrieval surfaced no collision within coverage (no collision "
                          "found, not proven novel)",
                "source": SOURCE_WORKER,
            }
        return {
            "idea_id": idea_id,
            "verdict": VERDICT_UNVERIFIED,
            "cut": False,
            "colliding_papers": papers_view,
            "reason": "worker reported clear but retrieval was not grounded this run — collision "
                      "could not be confirmed; re-run with retrieval before betting",
            "source": SOURCE_WORKER,
        }

    # Unknown / missing worker verdict: never cut on an unrecognized signal.
    return {
        "idea_id": idea_id,
        "verdict": VERDICT_UNVERIFIED,
        "cut": False,
        "colliding_papers": papers_view,
        "reason": f"unrecognized worker verdict {worker!r} — collision unverified, never cut",
        "source": SOURCE_WORKER,
    }


def _verdict_from_ledger(idea_id: str, row: dict, existence_by_ref: Dict[str, str], *,
                         hard_block: bool) -> dict:
    """Pre-established DEAD from the known-prior-art ledger (a prior run already cut this) — the
    machine never re-outputs a known-dead idea. Existence was proven when first recorded; the ledger
    row's colliding refs are echoed, stamped with whatever existence state this run knows for them."""
    refs = [str(r).strip() for r in (row.get("colliding_refs") or []) if str(r).strip()]
    papers_view = [{
        "ref": ref,
        "existence": existence_by_ref.get(ref, "UNKNOWN"),
        "experimentally_validated": bool(row.get("experimentally_validated")),
    } for ref in refs]
    refs_note = f": {', '.join(refs)}" if refs else ""
    return {
        "idea_id": idea_id,
        "verdict": VERDICT_DEAD,
        "cut": bool(hard_block),
        "colliding_papers": papers_view,
        "reason": f"matched the known-prior-art ledger (already cut in a prior run){refs_note}",
        "source": SOURCE_LEDGER,
    }


def build_collision_verdict(
    menu_ideas: List[dict],
    findings: List[dict],
    existence_by_ref: Dict[str, str],
    prior_art_hits: Optional[Dict[str, dict]],
    *,
    hard_block: bool = True,
    cut_requires_experiments: bool = True,
    retrieval_grounded: bool = True,
) -> dict:
    """Combine worker collision findings + existence facts + the prior-art ledger into a per-idea
    collision verdict (the ``novelty_collision_report`` payload). PURE: no I/O, no network, no clock.

    Args:
        menu_ideas: ``[{idea_id, summary, ...}]`` — EVERY idea appears exactly once in ``ideas[]``.
        findings: the checker worker's ``collision_findings`` list, matched by ``idea_id``. An idea
            with no finding and no ledger hit is always UNVERIFIED. Grounded retrieval proves only
            that a search channel ran; it cannot substitute for an explicit per-idea finding.
        existence_by_ref: ``ref -> state`` from ``citation_existence`` (real string ``"verified"``
            means proven-exists; the design alias ``"EXISTS"`` is also accepted). The caller
            (``run_collision_gate``) does the real lookup; this function only reads the result.
        prior_art_hits: ``idea_id -> ledger row`` for ideas pre-matched to the known-prior-art
            ledger (pre-established DEAD); may be ``None`` / ``{}``.
        hard_block: director default ``True`` — a DEAD idea is cut (``cut = hard_block``).
            Profile-tunable; ``False`` keeps every idea (flag-only) while still labelling DEAD.
        cut_requires_experiments: when ``True`` (default) a DEAD verdict additionally requires the
            colliding paper to have actually RUN / implemented it (proposed-only -> WHITE_SPACE).
        retrieval_grounded: ``False`` when no retrieval records exist this run -> every non-ledger
            idea is UNVERIFIED and nothing is cut (never cut without evidence; offline honesty).

    Returns:
        ``dict`` with EXACTLY these keys (``novelty_collision_report.schema.json``):
          ``ideas``              list of ``{idea_id, verdict, cut, colliding_papers, reason, source}``
                                 — one per input idea, in input order (stable).
          ``policy``             ``{hard_block, cut_requires_experiments}`` (the knobs applied).
          ``cut_ids``            idea_ids with ``cut == True``  (input order).
          ``survivors``          idea_ids with ``cut == False`` (input order).
          ``retrieval_grounded`` echo of the ``retrieval_grounded`` flag applied.
          ``evidence_ref``       the collision bundle ref(s) (``["inbox/COLLISION.bundle.json"]``).

    Raises:
        ValueError: missing / non-string / duplicate ``idea_id`` (same discipline as
            ``idea_grounding``); a duplicate ``idea_id`` in ``findings``; or an empty
            ``evidence_ref`` derived from the findings (anti-slop binding).
    """
    ids = _validate_inputs(menu_ideas)
    existence_by_ref = dict(existence_by_ref or {})
    ledger_hits = dict(prior_art_hits or {})

    # Index worker findings by idea_id; a duplicated finding id is an upstream defect, not silently
    # last-wins (mirrors idea_grounding's duplicate-id strictness).
    findings_list = list(findings or [])
    finding_ids = [f.get("idea_id") for f in findings_list if isinstance(f, dict)]
    dupes = sorted({x for x in finding_ids if finding_ids.count(x) > 1 and isinstance(x, str)})
    if dupes:
        raise ValueError(f"duplicate idea_id in collision findings: {dupes}")
    finding_by_id = {f["idea_id"]: f for f in findings_list
                     if isinstance(f, dict) and isinstance(f.get("idea_id"), str)}

    # evidence_ref: prefer the bundle ref the worker stamped; fall back to the canonical bundle path.
    evidence_ref: List[str] = []
    for f in findings_list:
        if isinstance(f, dict):
            for r in (f.get("evidence_ref") or []):
                if isinstance(r, str) and r.strip() and r not in evidence_ref:
                    evidence_ref.append(r)
    if not evidence_ref:
        evidence_ref = ["inbox/COLLISION.bundle.json"]
    if not all(isinstance(r, str) and r.strip() for r in evidence_ref):
        raise ValueError("evidence_ref must be a non-empty list of non-empty strings (anti-slop)")

    out_ideas: List[dict] = []
    for idea_id in ids:
        # Ledger hit wins: a known-dead idea is DEAD regardless of this run's worker output.
        if idea_id in ledger_hits and isinstance(ledger_hits[idea_id], dict):
            out_ideas.append(_verdict_from_ledger(
                idea_id, ledger_hits[idea_id], existence_by_ref, hard_block=hard_block))
            continue

        if not retrieval_grounded:
            # No retrieval this run (and no ledger hit) -> cannot confirm a collision -> never cut.
            out_ideas.append({
                "idea_id": idea_id,
                "verdict": VERDICT_UNVERIFIED,
                "cut": False,
                "colliding_papers": [],
                "reason": "retrieval was not grounded this run — novelty was NOT verified; re-run "
                          "with pre-search + the collision worker before betting",
                "source": SOURCE_WORKER,
            })
            continue

        finding = finding_by_id.get(idea_id)
        if finding is None:
            # Fail closed: another idea's grounded finding proves neither coverage nor clearance for
            # this one. A missing row is an incomplete audit, never implicit evidence of novelty.
            out_ideas.append({
                "idea_id": idea_id,
                "verdict": VERDICT_UNVERIFIED,
                "cut": False,
                "colliding_papers": [],
                "reason": "targeted retrieval ran, but the collision checker emitted no finding for "
                          "this idea; per-idea coverage is missing, so novelty remains UNVERIFIED",
                "source": SOURCE_WORKER,
            })
            continue

        out_ideas.append(_verdict_from_worker(
            finding, existence_by_ref,
            cut_requires_experiments=cut_requires_experiments,
            hard_block=hard_block, retrieval_grounded=retrieval_grounded))

    cut_ids = [e["idea_id"] for e in out_ideas if e["cut"]]
    survivors = [e["idea_id"] for e in out_ideas if not e["cut"]]
    return {
        "ideas": out_ideas,
        "policy": {"hard_block": bool(hard_block),
                   "cut_requires_experiments": bool(cut_requires_experiments)},
        "cut_ids": cut_ids,
        "survivors": survivors,
        "retrieval_grounded": bool(retrieval_grounded),
        "evidence_ref": evidence_ref,
    }
