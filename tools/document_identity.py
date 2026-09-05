"""Hardened document-identity verification (distinctive-word comparator + self-test guard).

Closes failure-catalog items (``_design/2026-08-20-team-upgrade/00-inputs-failure-catalog.md``):
  B2 — "verifier with no discriminative power": the naive character-bigram Jaccard check
       passed a wrong-content PDF because long words shared across a field carried the
       similarity. The machine comparator scores DISTINCTIVE-WORD containment instead, and
       ships with ``KNOWN_BAD_PAIRS`` — regression pins distilled from that contamination
       incident (same-field different-paper titles the naive bigram measure passes). A lazy
       ``self_test()`` re-proves the guard on first use; if any known-bad pair passes, every
       subsequent ``title_match`` call refuses to run. **A verifier must be validated against
       known-bad inputs before it guards anything.**
  B3 — PDF-identity verification was run-local only; this module makes it a machine
       capability (generalized from the run's ``verify_corpus.py`` comparator).

Domain-generality: the run's comparator carried a medical-imaging stop list. Here the
domain stop-vocabulary is an INJECTED parameter (profiles supply it); the built-in default
is a generic cross-field academic stop set (function words + title boilerplate that carries
no paper identity in any field). Injected vocabularies EXTEND the generic set.

This module never writes files and never touches the network. PDF text extraction
(``pdf_text``) needs PyMuPDF; when it is unavailable the failure is reported honestly
(never silently treated as "empty document").
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import FrozenSet, Iterable, Optional, Tuple

COMPARATOR_VERSION = "document-identity/distinctive-word-containment/v1"

DEFAULT_THRESHOLD = 0.5
_MIN_DISTINCTIVE_TOKENS = 3     # below this, containment loses discriminative power
_PREFIX_FUZZ_LEN = 5            # plural / verb-form / PDF-ligature drift tolerance

# Generic cross-field academic stop vocabulary: English function words plus title
# boilerplate that appears across ALL research fields and therefore carries no identity.
# Deliberately contains NO domain science vocabulary — domain stop lists live in
# profiles/*.yaml and are passed in through ``stop_vocab``.
GENERIC_STOP_VOCAB: FrozenSet[str] = frozenset({
    # function words (>= 3 chars; shorter tokens are dropped by tokenization anyway)
    "the", "and", "for", "with", "from", "via", "into", "over", "under", "between",
    "across", "without", "within", "using", "based", "through", "towards", "toward",
    "can", "does", "are", "our", "your", "their", "its", "this", "that", "these",
    "those", "what", "when", "how", "why", "not", "all", "any",
    # ubiquitous academic/title boilerplate (cross-field)
    "novel", "new", "improved", "efficient", "effective", "robust", "scalable",
    "unified", "general", "simple", "fast", "method", "methods", "approach",
    "approaches", "framework", "frameworks", "model", "models", "modeling",
    "modelling", "analysis", "evaluation", "assessment", "study", "survey", "review",
    "benchmark", "benchmarks", "benchmarking", "learning", "deep", "machine",
    "neural", "network", "networks", "artificial", "intelligence", "data", "dataset",
    "datasets", "results", "performance", "accuracy", "quality", "system", "systems",
    "estimation", "prediction", "detection", "classification", "recognition",
    "optimization", "optimisation", "automated", "automatic", "algorithm",
    "algorithms", "application", "applications", "task", "tasks", "problem",
    "problems", "toward", "towards",
    # front-matter noise commonly present in first-page text
    "abstract", "introduction", "keywords", "university", "department", "institute",
    "laboratory", "conference", "proceedings", "journal", "preprint", "arxiv",
    "corresponding", "author", "authors", "email",
})


class IdentityGuardError(RuntimeError):
    """The comparator failed its own known-bad regression pins — it must not guard anything."""


@dataclass(frozen=True)
class IdentityVerdict:
    """Outcome of one title-vs-document comparison (auditable, not just a bool)."""

    score: float
    passed: bool
    method: str
    threshold: float
    matched: Tuple[str, ...] = field(default_factory=tuple)
    missing: Tuple[str, ...] = field(default_factory=tuple)
    comparator_version: str = COMPARATOR_VERSION


# --------------------------------------------------------------------------- tokenization

def _tokens(text: str) -> list:
    return [t for t in re.split(r"[^a-z0-9]+", (text or "").lower()) if len(t) >= 3]


def distinctive_words(text: str, stop_vocab: Optional[FrozenSet[str]] = None) -> set:
    """Identity-bearing tokens of ``text``: >= 3 chars, split on hyphens as well as spaces
    (a title's "out of distribution" must meet a PDF's "out-of-distribution"), minus the
    generic academic stop set and any injected domain stop vocabulary."""
    stops = GENERIC_STOP_VOCAB if stop_vocab is None else (GENERIC_STOP_VOCAB | frozenset(stop_vocab))
    return {t for t in _tokens(text) if t not in stops}


def bigram_jaccard(a: str, b: str) -> float:
    """The NAIVE character-bigram comparator — the documented B2 failure mode.

    Kept only (1) as the regression yardstick ``self_test`` uses to prove each
    ``KNOWN_BAD_PAIRS`` entry really is a trap the naive measure falls into, and (2) as a
    confirm-only fallback where no distinctive word exists. It must never be a document's
    sole identity gate.
    """
    def grams(s: str) -> set:
        s = re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()
        s = re.sub(r"\s+", " ", s)
        return {s[i:i + 2] for i in range(len(s) - 1)} or {"__"}

    ga, gb = grams(a), grams(b)
    return len(ga & gb) / max(1, len(ga | gb))


# --------------------------------------------------------------------------- comparator

def _containment(want: set, have: set) -> Tuple[float, Tuple[str, ...], Tuple[str, ...]]:
    """Containment of ``want`` in ``have`` with a bounded prefix-fuzz second pass
    (plural / verb-form drift and PDF-extraction ligature damage)."""
    matched = sorted(want & have)
    missing = []
    for w in sorted(want - have):
        if len(w) >= _PREFIX_FUZZ_LEN and any(
            len(h) >= _PREFIX_FUZZ_LEN
            and (h.startswith(w[:_PREFIX_FUZZ_LEN]) or w.startswith(h[:_PREFIX_FUZZ_LEN]))
            for h in have
        ):
            matched.append(w)
        else:
            missing.append(w)
    score = len(matched) / max(1, len(want))
    return score, tuple(sorted(matched)), tuple(missing)


def _title_match_unguarded(pdf_first_page_text: str, expected_title: str, *,
                           stop_vocab: Optional[FrozenSet[str]] = None,
                           threshold: float = DEFAULT_THRESHOLD) -> IdentityVerdict:
    want = distinctive_words(expected_title, stop_vocab)
    if not want:
        # A title made entirely of stop vocabulary cannot be verified discriminatively.
        # Refuse to pass (callers may adjudicate by eye) — never wave it through.
        return IdentityVerdict(score=0.0, passed=False, method="no-distinctive-tokens",
                               threshold=threshold)
    have = set(_tokens(pdf_first_page_text))
    score, matched, missing = _containment(want, have)
    if len(want) >= _MIN_DISTINCTIVE_TOKENS:
        return IdentityVerdict(score=round(score, 3), passed=score >= threshold,
                               method="distinctive-word-containment", threshold=threshold,
                               matched=matched, missing=missing)
    # 1–2 distinctive tokens: too weak for a ratio test — require EVERY distinctive token.
    return IdentityVerdict(score=round(score, 3), passed=score >= 1.0,
                           method="weak-distinctive-containment(all-required)",
                           threshold=1.0, matched=matched, missing=missing)


def title_match(pdf_first_page_text: str, expected_title: str, *,
                stop_vocab: Optional[FrozenSet[str]] = None,
                threshold: float = DEFAULT_THRESHOLD) -> IdentityVerdict:
    """Does the document's first-page text plausibly belong to ``expected_title``?

    Score = containment of the expected title's DISTINCTIVE words in the page text
    (prefix-fuzzed). Runs ``self_test`` lazily on first call and refuses to operate if the
    known-bad regression pins fail (B2: an unvalidated verifier guards nothing).
    """
    _ensure_guard()
    return _title_match_unguarded(pdf_first_page_text, expected_title,
                                  stop_vocab=stop_vocab, threshold=threshold)


# --------------------------------------------------------------------------- known-bad pins

# Distilled from the run's corpus-contamination incident (verify_corpus.py:43-48): a PDF
# whose content was a DIFFERENT same-field paper passed the naive character-bigram check
# because shared long boilerplate words supplied the bigrams. Each pin below is a pair of
# same-field, different-paper texts (neutral vocabulary — the machine stays domain-general)
# that the naive measure scores as similar and the distinctive-word comparator must reject.
KNOWN_BAD_PAIRS: Tuple[dict, ...] = (
    {
        "expected_title": "Can uncertainty scores predict failure severity of deployed learning systems",
        "wrong_title": "Margin aware loss functions for highly unbalanced learning systems",
        "wrong_text": ("Margin aware loss functions for highly unbalanced learning systems\n"
                       "Proceedings of the Conference on Learning Systems\n"
                       "Abstract. We study loss functions for training on highly unbalanced data "
                       "and introduce a margin aware objective with strong empirical performance."),
        "note": "shape of the original incident: a score-prediction title vs a loss-function paper",
    },
    {
        "expected_title": "Spectral kernels for community discovery in evolving interaction graphs",
        "wrong_title": "A unified framework for scalable community detection in dynamic interaction graphs",
        "wrong_text": ("A unified framework for scalable community detection in dynamic interaction graphs\n"
                       "Abstract. We present a unified framework for detection of communities in large "
                       "dynamic graphs, with scalable optimization and extensive evaluation."),
        "note": "one shared distinctive word (community); everything else is boilerplate",
    },
    {
        "expected_title": "Wavelet packet features for anomaly screening in streaming telemetry archives",
        "wrong_title": "Autoencoder ensembles for anomaly detection in high frequency telemetry streams",
        "wrong_text": ("Autoencoder ensembles for anomaly detection in high frequency telemetry streams\n"
                       "Journal of Data Systems\n"
                       "Abstract. We evaluate autoencoder ensembles for detection of anomalies in "
                       "high frequency telemetry data across three benchmark datasets."),
        "note": "same application words (anomaly, telemetry), different method paper",
    },
    {
        "expected_title": "Curriculum ordering strategies for compositional generalization in sequence models",
        "wrong_title": "Benchmarking systematic generalization of transformer architectures",
        "wrong_text": ("Benchmarking systematic generalization of transformer architectures\n"
                       "Abstract. We benchmark systematic generalization across transformer "
                       "architectures and analyze failure modes on synthetic tasks."),
        "note": "shared: generalization + boilerplate; the papers are unrelated",
    },
    {
        "expected_title": "Provable convergence of asynchronous gossip aggregation on sparse topologies",
        "wrong_title": "Convergence analysis of synchronous aggregation methods for distributed optimization",
        "wrong_text": ("Convergence analysis of synchronous aggregation methods for distributed optimization\n"
                       "Abstract. We analyze the convergence of synchronous aggregation methods for "
                       "distributed optimization and prove complexity bounds under standard assumptions."),
        "note": "shared: convergence, aggregation + boilerplate; asynchronous-gossip paper vs synchronous-methods paper",
    },
)

# A verifier that rejects everything is as useless as one that passes everything: the guard
# also proves a correct pair — the expected title re-typeset with header noise, ligature
# damage and hyphenation drift — still passes.
KNOWN_GOOD_CONTROL: dict = {
    "expected_title": "Wavelet packet features for anomaly screening in streaming telemetry archives",
    "text": ("Wavelet packet features for anomaly screen-\n"
             "ing in streaming telemetry archives\n"
             "A. Author, B. Author\n"
             "Institute for Data Systems\n"
             "Abstract. Wavelet packet features enable anomaly screening over streaming "
             "telemetry archives at low cost."),
}

# The naive bigram score each pin must reach to count as a genuine trap (the incident pair
# scored in this region); a pin below this no longer documents the failure mode.
_NAIVE_TRAP_FLOOR = 0.30

_guard_state: Optional[str] = None  # None = not run; "" = passed; non-empty = failure text


def self_test() -> dict:
    """Prove the comparator against the known-bad pins (and the known-good control).

    For every ``KNOWN_BAD_PAIRS`` entry BOTH must hold:
      1. the naive bigram comparator scores the pair >= _NAIVE_TRAP_FLOOR (the pin really
         documents the B2 trap — otherwise the pin itself has rotted), and
      2. ``title_match`` REJECTS the pair.
    The known-good control must PASS. Raises IdentityGuardError listing every violation.
    Returns a summary dict when all pins hold.
    """
    failures = []
    rows = []
    for pair in KNOWN_BAD_PAIRS:
        naive = bigram_jaccard(pair["expected_title"], pair["wrong_title"])
        verdict = _title_match_unguarded(pair["wrong_text"], pair["expected_title"])
        rows.append({"expected_title": pair["expected_title"], "naive_bigram": round(naive, 3),
                     "distinctive_score": verdict.score, "rejected": not verdict.passed})
        if naive < _NAIVE_TRAP_FLOOR:
            failures.append(
                f"pin rotted (naive bigram {naive:.3f} < {_NAIVE_TRAP_FLOOR}): "
                f"{pair['expected_title']!r} vs {pair['wrong_title']!r}")
        if verdict.passed:
            failures.append(
                f"KNOWN-BAD PAIR PASSED (score {verdict.score}): "
                f"{pair['expected_title']!r} vs {pair['wrong_title']!r} — {pair['note']}")
    good = _title_match_unguarded(KNOWN_GOOD_CONTROL["text"],
                                  KNOWN_GOOD_CONTROL["expected_title"])
    if not good.passed:
        failures.append(f"known-good control REJECTED (score {good.score}) — "
                        f"the comparator rejects correct documents")
    if failures:
        raise IdentityGuardError(
            "document_identity failed its known-bad regression pins; refusing to guard:\n  - "
            + "\n  - ".join(failures))
    return {"comparator_version": COMPARATOR_VERSION, "n_known_bad": len(KNOWN_BAD_PAIRS),
            "known_good_score": good.score, "pins": rows}


def _ensure_guard() -> None:
    global _guard_state
    if _guard_state is None:
        try:
            self_test()
            _guard_state = ""
        except IdentityGuardError as e:
            _guard_state = str(e)
    if _guard_state:
        raise IdentityGuardError(_guard_state)


# --------------------------------------------------------------------------- PDF text (optional dependency)

def pdf_text(pdf_path, max_pages: Optional[int] = None) -> Tuple[str, int]:
    """Extract text from a PDF via PyMuPDF -> (text, n_pages).

    Honesty rule (fulltext_qa): when extraction is impossible — PyMuPDF missing or the file
    unreadable — this RAISES with a named reason. Absence of text is reported, never
    silently returned as an empty document (an empty string would read as "content checked,
    nothing there").
    """
    try:
        import fitz  # PyMuPDF — optional; callers may inject their own extractor instead
    except ImportError as e:  # pragma: no cover - environment-dependent
        raise RuntimeError(
            "PyMuPDF (fitz) is not installed — cannot extract PDF text. Install pymupdf "
            "or inject a page-text extractor; the document was NOT checked.") from e
    doc = fitz.open(Path(pdf_path))
    try:
        n = doc.page_count
        pages = range(n if max_pages is None else min(n, max_pages))
        text = "\n".join(doc[i].get_text("text") for i in pages)
    finally:
        doc.close()
    return text, n


def clean_text(text: str) -> str:
    """Normalize PDF-extracted text: ligatures, soft hyphens, de-hyphenation, whitespace."""
    t = (text or "").replace("ﬁ", "fi").replace("ﬂ", "fl").replace("­", "")
    t = re.sub(r"-\n(?=[a-z])", "", t)
    t = re.sub(r"[ \t]+", " ", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()
