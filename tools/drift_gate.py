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

# Keep Latin/number tokens and contiguous CJK text.  The previous ASCII-only
# tokenizer silently reduced a mixed phrase such as ``GT泄漏`` to the single
# token ``gt``.  That made any scientifically necessary mention of
# ``GT-derived`` evidence look like the explicitly excluded topic ``GT泄漏``.
# Preserving the CJK part lets mixed-language phrases remain phrases, so the
# hard gate fires only when the complete excluded concept is present.
_WORD_RE = re.compile(r"[a-z0-9]+|[\u3400-\u4dbf\u4e00-\u9fff]+")

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

# C7 (2026-08-07): a handful of CJK function words common enough to carry no direction
# signal on their own — the bigram-level equivalent of _STOPWORDS. Deliberately small for
# the same reason _STOPWORDS is small: over-aggressive stopwording would delete real anchor
# bigrams from a short Chinese statement.
_CJK_STOPWORD_BIGRAMS = frozenset((
    "研究", "方法", "我们", "本文", "这个", "可以", "进行", "一个",
))


def _tokens(text: str) -> List[str]:
    return _WORD_RE.findall((text or "").lower())


def _norm_phrase(text: str) -> str:
    return " ".join(_tokens(text))


def _anchor_tokens(text: str) -> List[str]:
    """Anchor/coverage tokens: Latin words as before, CJK as adjacent-character bigrams.

    C7 (2026-08-07): Chinese carries no whitespace, so the plain word run _tokens() uses for
    _norm_phrase (an unbroken CJK clause is ONE token) made anchor coverage against a Chinese
    north star structurally near-zero — a real anchor phrase like "医学影像残差校正" could never
    match anything shorter than itself. Latin runs keep the exact _tokens() length/stopword
    rule; a CJK run is split into overlapping 2-character bigrams (a lone single-character run
    keeps the character itself — _MIN_TOKEN_LEN does not apply to CJK, a 2-character bigram is
    already shorter than 3). _norm_phrase/_tokens are UNCHANGED and still own out-of-scope
    PHRASE matching below (the GT泄漏 fix) — this is a second, coverage-only tokenizer.
    """
    tokens: List[str] = []
    for match in _WORD_RE.finditer((text or "").lower()):
        run = match.group(0)
        if run[0].isascii():
            if len(run) >= _MIN_TOKEN_LEN and run not in _STOPWORDS:
                tokens.append(run)
            continue
        if len(run) == 1:
            tokens.append(run)
            continue
        for i in range(len(run) - 1):
            bigram = run[i:i + 2]
            if bigram not in _CJK_STOPWORD_BIGRAMS:
                tokens.append(bigram)
    return tokens


def anchor_terms(statement: str, in_scope: Iterable[str] = ()) -> List[str]:
    """The north star's anchor vocabulary: content tokens of the statement plus every in_scope
    entry's tokens. Deterministic order (first occurrence), de-duplicated, stopwords removed.
    CJK text is tokenized as adjacent-character bigrams — see _anchor_tokens."""
    seen: Dict[str, None] = {}
    for src in [statement, *list(in_scope or [])]:
        for t in _anchor_tokens(src):
            if t not in seen:
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
    # C7: coverage tokens must use the SAME tokenizer as anchor_terms (_anchor_tokens), or a
    # Chinese anchor bigram could never appear in an unbroken Chinese output run tokenized
    # differently. out-of-scope PHRASE matching below still uses _tokens/_norm_phrase.
    out_tokens = set(_anchor_tokens(joined))
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
        if len(toks) == 1:
            present = toks[0] in out_tokens
        else:
            # A scope boundary must not punish an explicit refusal such as
            # "no journal submission", "absence of new experiments", or
            # "rather than a demand for new experiments".  The old substring
            # test treated those safety/limitation statements as the very drift
            # they deny.  Ignore only occurrences with a nearby, explicit
            # negation marker; affirmative occurrences remain hard failures.
            present = False
            for match in re.finditer(re.escape(norm), norm_joined):
                prefix = norm_joined[max(0, match.start() - 64):match.start()]
                if any(marker in prefix for marker in (
                    "no ", "not ", "never ", "without ", "absence of ",
                    "rather than ", "do not ", "does not ", "must not ",
                )):
                    continue
                present = True
                break
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
