"""Deterministic per-stage drift gate (audit H2 fix — the north-star contract's enforcement core).

Every run pins an immutable ``north_star`` in its task_frame ({statement, in_scope, out_of_scope}).
This module checks, at EVERY stage boundary of an operated mode, that the stage's textual output
still serves that north star. It is a TEXT-LEVEL deterministic proxy, not a semantic judge — and is
documented as such (honesty note below). Division of labour:

  - HARD violations (the caller raises GateBlock):
      * an ``out_of_scope`` term/phrase appears in the stage output (the director explicitly
        excluded it — producing it is drift by definition);
      * ZERO anchor-term coverage (>=2 anchor terms exist, the output is non-empty, and not one
        anchor term appears) — the output is provably about something else.
  - ADVISORY (recorded in the verdict's notes, surfaced to the director, never a block):
      * low (but non-zero) anchor coverage — possible soft drift; a human judgment call.

Honesty note: this gate catches *provable* drift (excluded topics, total disconnection). Semantic
drift that re-uses the north star's words while answering a different question is beyond a
deterministic text check — the per-worker north-star prompt injection and the director gates remain
the defence for that layer. This gate narrows the hole; it does not claim to close it.

Pure functions: no I/O, no network, no LLM, no clock. Verdict payloads conform to
``analysis_check_verdict.schema.json`` (panel_role "goal_alignment"; pass derived from violations).
"""
from __future__ import annotations

import re
from typing import Dict, Iterable, List, Tuple

_WORD_RE = re.compile(r"[a-z0-9]+")

# Minimal English stopword set — only words so common they carry no direction signal. Deliberately
# small: over-aggressive stopwording would delete real anchor terms from short statements.
_STOPWORDS = frozenset((
    "the a an and or of in on for to with without from by at as is are was were be been being "
    "do does did done can could should would may might must will shall not no nor this that "
    "these those it its their our your my his her they them we you i he she than then so such "
    "into onto over under more most less least very really just only also both either neither "
    "what which who whom whose when where why how all any each few some own same other another "
    "again once here there about against between through during before after above below up down "
    "out off further new using use used via per vs versus study research find finds find"
).split())

_MIN_TOKEN_LEN = 3
LOW_COVERAGE_THRESHOLD = 0.4  # advisory only — below this, note possible soft drift


def _tokens(text: str) -> List[str]:
    return _WORD_RE.findall((text or "").lower())


def _norm_phrase(text: str) -> str:
    return " ".join(_tokens(text))


def anchor_terms(statement: str, in_scope: Iterable[str] = ()) -> List[str]:
    """The north star's anchor vocabulary: content tokens of the statement plus every in_scope
    entry's tokens. Deterministic order (first occurrence), de-duplicated, stopwords removed."""
    seen: Dict[str, None] = {}
    for src in [statement, *list(in_scope or [])]:
        for t in _tokens(src):
            if len(t) >= _MIN_TOKEN_LEN and t not in _STOPWORDS and t not in seen:
                seen[t] = None
    return list(seen)


def check_drift(north_star: dict, texts: Iterable[str]) -> dict:
    """Check stage output ``texts`` against the ``north_star`` contract.

    north_star: {"statement": str, "in_scope": [str], "out_of_scope": [str]} (in/out optional).
    texts: the stage's textual output (signal statements, claims, idea summaries, ...).

    Returns {coverage, matched_terms, missing_terms, out_of_scope_hits, violations, warnings}.
    ``violations`` non-empty == provable drift (the caller should BLOCK).
    """
    statement = str((north_star or {}).get("statement") or "")
    in_scope = list((north_star or {}).get("in_scope") or [])
    out_of_scope = list((north_star or {}).get("out_of_scope") or [])

    anchors = anchor_terms(statement, in_scope)
    joined = " ".join(str(t) for t in texts if t)
    out_tokens = set(_tokens(joined))
    norm_joined = _norm_phrase(joined)

    matched = [a for a in anchors if a in out_tokens]
    missing = [a for a in anchors if a not in out_tokens]
    coverage = round(len(matched) / len(anchors), 4) if anchors else 1.0

    violations: List[str] = []
    warnings: List[str] = []

    # HARD 1: explicitly-excluded topics present in the output.
    hits: List[str] = []
    for phrase in out_of_scope:
        norm = _norm_phrase(str(phrase))
        if not norm:
            continue
        toks = norm.split()
        present = (toks[0] in out_tokens) if len(toks) == 1 else (norm in norm_joined)
        if present:
            hits.append(str(phrase))
    for h in hits:
        violations.append(
            f"out-of-scope topic {h!r} appears in this stage's output — the north star explicitly "
            "excludes it (drift; the run must not silently re-scope itself)")

    # HARD 2: total disconnection from the north star's vocabulary.
    if len(anchors) >= 2 and norm_joined and not matched:
        violations.append(
            "zero north-star anchor coverage: not one anchor term "
            f"({', '.join(anchors[:8])}{'…' if len(anchors) > 8 else ''}) appears in the stage "
            "output — the output is provably about something else than the run's direction")

    # ADVISORY: low-but-nonzero coverage is a soft-drift signal for the director, never a block.
    if matched and coverage < LOW_COVERAGE_THRESHOLD:
        warnings.append(
            f"low north-star anchor coverage ({coverage}): possible soft drift — "
            f"missing anchors: {', '.join(missing[:8])}{'…' if len(missing) > 8 else ''}")

    return {"coverage": coverage, "matched_terms": matched, "missing_terms": missing,
            "out_of_scope_hits": hits, "violations": violations, "warnings": warnings}


def build_verdict(north_star: dict, texts: Iterable[str], stage: str) -> Tuple[dict, dict]:
    """Build the drift verdict as an ``analysis_check_verdict`` payload (panel_role goal_alignment).

    Returns (payload, facts) — payload is schema-ready (pass derived from violations, never set by
    hand); facts is the raw check_drift dict for the caller's report line."""
    facts = check_drift(north_star, texts)
    note_bits = [f"stage={stage}", f"anchor_coverage={facts['coverage']}"]
    note_bits += facts["warnings"]
    payload = {
        "panel_role": "goal_alignment",
        "pass": not facts["violations"],
        "violations": list(facts["violations"]),
        "checked_items": anchor_terms(str((north_star or {}).get("statement") or ""),
                                      (north_star or {}).get("in_scope") or []),
        "notes": "; ".join(note_bits),
    }
    return payload, facts
