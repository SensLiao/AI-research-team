"""Retrieval-grounded idea evaluation (absorption wave 1; ScholarEval pattern).

ScholarEval's core finding: idea evaluation is only trustworthy when grounded in retrieved
literature — soundness (is the idea's claimed support real?) and contribution (does it actually
sit apart from its neighbors?) must be derived from retrieval, not from a judge's vibe. This
module is the deterministic core; the LLM workers gather the ideas and run the searches.

Deterministic derivations (documented proxies, profile-tunable thresholds):
  - soundness  = resolved_refs / total_refs — the fraction of the idea's ``evidence_ref``
    entries that actually RESOLVE: internal ids (GAP-/IH-...) found in the run's artifacts
    (caller passes the known-id set), vault ``[[slug]]`` refs (format-valid; their existence is
    enforced by the citation gates), and external refs (DOI / arXiv / title) matched against
    the live-retrieved neighbor records. An idea citing support that does not resolve scores low.
  - contribution = 1 - best_neighbor_overlap(summary vs retrieved titles) — distinctness GIVEN
    retrieval; with zero retrieved records it is a NEUTRAL 0.5 (distinctness cannot be assessed
    without retrieval; an honest unknown, never a free 1.0).
  - n_neighbors = retrieved records whose title-overlap with the summary >= the neighbor
    threshold (same 0.45 default as paper_search.no_semantic_neighbor_found).

SCORE-ONLY discipline (novelty-paradox guard): EVERY input idea appears in the output; profile
thresholds (profiles/*.yaml ``idea_grounding``) only annotate ``below_threshold`` — nothing is
ever cut. The director ranks and bets at /idea-bet.
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional, Set

from research_agent_teams.tools.paper_search import neighbor_overlap
from research_agent_teams.tools.scholar_clients import normalize_arxiv_id, normalize_doi

DEFAULT_THRESHOLDS = {"soundness_min": 0.5, "contribution_min": 0.3}
NEIGHBOR_THRESHOLD = 0.45
_TITLE_MATCH = 0.6
_SLUG_RE = re.compile(r"^\[\[[a-z0-9]+(?:-[a-z0-9]+)*\]\]$")
# Internal artifact ids: a fixed prefix + separator + digits (GAP-1, IH2, IDEA-003, conf1, c1).
# Anchored tightly so a free-text ref that merely STARTS with one of these letters ("cnn",
# "constraint", "evidence") is NOT misread as a fabricated internal id and falsely scored 0.
_INTERNAL_RE = re.compile(r"^(GAP|IH|IDEA|EV|FW|conf|c)[-_]?\d+$")


def thresholds_from_profile(profile: Optional[dict]) -> Dict[str, float]:
    """The active annotation thresholds: profile ``idea_grounding`` block over the defaults."""
    out = dict(DEFAULT_THRESHOLDS)
    block = (profile or {}).get("idea_grounding") or {}
    for k in out:
        if isinstance(block.get(k), (int, float)):
            out[k] = float(block[k])
    return out


def _ref_state(ref: str, records: List[dict], known_internal_ids: Set[str]) -> str:
    """Three-state resolution of one evidence ref:
      resolved     — confirmed grounded (known internal id, format-valid slug, retrieved match)
      unresolved   — confirmed NOT grounded (fabricated internal id, or external ref with retrieval
                     present but no match)
      unresolvable — cannot be checked offline (external DOI/arXiv/title ref with NO retrieval
                     records). 'Cannot check' is NOT 'not supported' — excluded from the soundness
                     denominator instead of scored 0 (the honest-unknown symmetry the contribution
                     channel already had)."""
    r = (ref or "").strip()
    if not r:
        return "unresolved"
    if r in known_internal_ids:
        return "resolved"
    if _SLUG_RE.match(r):
        return "resolved"  # slug existence is the citation gates' job; format-valid counts here
    if _INTERNAL_RE.match(r):
        return "unresolved"  # internal-shaped id NOT in the known set -> a fabricated internal ref
    doi = normalize_doi(r.split("doi:")[-1] if r.lower().startswith("doi:") else r)
    if doi:
        if not records:
            return "unresolvable"
        return "resolved" if any(rec.get("doi") == doi for rec in records) else "unresolved"
    aid = normalize_arxiv_id(r)
    if aid and (r.lower().startswith("arxiv") or re.fullmatch(r"\d{4}\.\d{4,5}(v\d+)?", r)):
        if not records:
            return "unresolvable"
        return "resolved" if any(rec.get("arxiv_id") == aid for rec in records) else "unresolved"
    # free-text ref: needs retrieval to check; resolved only on a close retrieved-title match
    if not records:
        return "unresolvable"
    return "resolved" if any(neighbor_overlap(r, rec.get("title", "")) >= _TITLE_MATCH
                             for rec in records) else "unresolved"


def score_idea_grounding(ideas: List[dict], records: List[dict],
                         known_internal_ids: Optional[Set[str]] = None,
                         profile: Optional[dict] = None,
                         evidence_ref: Optional[List[str]] = None,
                         neighbor_threshold: float = NEIGHBOR_THRESHOLD) -> dict:
    """Score every idea; return the ``idea_grounding_report`` payload (schema-ready).

    ideas: [{idea_id, summary, evidence_ref: [...]}] — every one appears in the output.
    records: live-retrieved neighbor records (paper_search.search()["records"]); may be empty.
    known_internal_ids: valid GAP-/IH-/IDEA- ids from this run's artifacts (default empty).
    """
    ids = [i.get("idea_id") for i in ideas]
    if not ideas:
        raise ValueError("score_idea_grounding requires at least one idea (score-only, none dropped)")
    if any(not isinstance(x, str) or not x.strip() for x in ids):
        raise ValueError(f"every idea needs a non-empty idea_id: {ids}")
    if len(set(ids)) != len(ids):
        raise ValueError(f"duplicate idea_id: {sorted(x for x in ids if ids.count(x) > 1)}")
    if not evidence_ref or not all(isinstance(r, str) and r.strip() for r in evidence_ref):
        raise ValueError("evidence_ref must be a non-empty list (anti-slop binding)")

    known = set(known_internal_ids or set())
    th = thresholds_from_profile(profile)
    out_ideas: List[dict] = []
    for idea in ideas:
        refs = [str(r) for r in (idea.get("evidence_ref") or [])]
        states = [(r, _ref_state(r, records, known)) for r in refs]
        grounded = [r for r, s in states if s == "resolved"]
        checkable = [r for r, s in states if s in ("resolved", "unresolved")]
        n_unresolvable = sum(1 for _, s in states if s == "unresolvable")
        if checkable:
            soundness = round(len(grounded) / len(checkable), 4)
        elif refs:
            soundness = 0.5  # all refs unresolvable offline — honest unknown, not 'unsupported'
        else:
            soundness = 0.0  # no refs at all
        best = 0.0
        n_neighbors = 0
        summary = str(idea.get("summary") or "")
        for rec in records:
            ov = neighbor_overlap(summary, rec.get("title", ""))
            if ov > best:
                best = ov
            if ov >= neighbor_threshold:
                n_neighbors += 1
        contribution = 0.5 if not records else round(max(0.0, 1.0 - best), 4)
        below = []
        if soundness < th["soundness_min"]:
            below.append("soundness")
        if contribution < th["contribution_min"]:
            below.append("contribution")
        entry = {"idea_id": idea["idea_id"], "soundness": soundness,
                 "contribution": contribution, "grounded_refs": grounded,
                 "n_neighbors": n_neighbors}
        if below:
            entry["below_threshold"] = below
        note_parts = []
        if not records:
            note_parts.append("contribution neutral (0.5): no retrieved neighbors to compare against")
        if n_unresolvable:
            note_parts.append(f"{n_unresolvable} external ref(s) unresolvable without retrieval "
                              f"(excluded from soundness — cannot-check is not unsupported)")
        if note_parts:
            entry["notes"] = "; ".join(note_parts)
        out_ideas.append(entry)

    return {"ideas": out_ideas,
            "thresholds": {"soundness_min": th["soundness_min"],
                           "contribution_min": th["contribution_min"]},
            "evidence_ref": list(evidence_ref)}
