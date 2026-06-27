"""Cross-domain query GENERATOR (a retrieval widener for the cross-domain-transfer-scout).

Honest scope: this module is a *query generator*, NOT a knowledge source. It holds no facts
about any field and decides nothing. Its only job is to take a concrete research problem,
strip the domain-specific nouns down to a mechanism-level phrasing, and emit a small set of
*other-field* query strings around that mechanism — so the scout's live retrieval reaches
analogous solved problems in distant fields instead of mining only the project's own vault.

Whether any retrieved paper is actually a transferable solution is the scout's judgment
(and downstream gates'); this file never claims a transfer exists.

Domain-general by construction: there is NO hardcoded single research domain. The mechanism
verbs and the distant-field list are deliberately field-agnostic (segmentation, forecasting,
ranking, control, generation, classification, retrieval, …), so the same generator works for
NLP, vision, RL, graphs, speech, etc. — thin-structure image segmentation is merely one example
the scout might feed in. The output is deterministic given the same input (no network, no clock,
no randomness): the same problem + same ``k`` always yields the same ordered query list.

Public API:
    abstract_problem(problem) -> str
    cross_domain_queries(problem, *, k=6) -> list[str]
"""
from __future__ import annotations

import re
from typing import List

# ------------------------------------------------------------------------- vocab (field-agnostic)

# Domain-specific NOUNS to strip so the phrasing becomes mechanism-level. These are concrete
# *objects of study* across many fields (anatomy, modalities, data kinds, task nouns). Stripping
# them leaves the underlying mechanism verbs/relations. The list is intentionally broad and
# cross-field — never a single research domain.
_DOMAIN_NOUNS = frozenset({
    # medical / vision objects (one example domain among many)
    "canal", "nerve", "tooth", "teeth", "dental", "mandibular", "vessel", "vessels",
    "vascular", "airway", "tubular", "organ", "tumor", "lesion", "cell", "cells",
    "ct", "cbct", "mri", "scan", "scans", "radiograph", "image", "images", "imaging",
    "pixel", "pixels", "voxel", "voxels", "slice", "slices", "volume", "volumes",
    "patient", "patients", "clinical", "anatomy", "anatomical", "medical",
    # language / nlp objects
    "text", "texts", "sentence", "sentences", "token", "tokens", "document", "documents",
    "corpus", "language", "linguistic", "word", "words", "dialogue", "speech", "audio",
    # rl / control / robotics objects
    "robot", "robots", "agent", "agents", "policy", "trajectory", "trajectories",
    "environment", "reward", "actuator", "sensor", "sensors",
    # graph / tabular / generic data objects
    "graph", "graphs", "node", "nodes", "edge", "edges", "network", "networks",
    "table", "tabular", "row", "rows", "column", "columns", "dataset", "datasets",
    "sample", "samples", "record", "records", "signal", "signals", "series", "video",
})

# Mechanism VERBS / relations that name what is being DONE. These survive abstraction and become
# the seed mechanism phrase. Order = priority when several appear in one problem.
_MECHANISM_TERMS = (
    "segment", "segmentation", "detect", "detection", "classify", "classification",
    "predict", "prediction", "forecast", "forecasting", "rank", "ranking",
    "retrieve", "retrieval", "generate", "generation", "reconstruct", "reconstruction",
    "denoise", "denoising", "register", "registration", "track", "tracking",
    "cluster", "clustering", "align", "alignment", "translate", "translation",
    "compress", "compression", "calibrate", "calibration", "control",
    "adapt", "adaptation", "transfer", "fine-tune", "finetune",
)

# Salient PROBLEM-STRUCTURE qualifiers worth keeping — they describe the *difficulty regime*
# (thin/elongated structures, class imbalance, scarce labels, distribution shift), which is
# exactly what makes a distant-field analog relevant. Domain-neutral.
_STRUCTURE_TERMS = (
    "thin", "elongated", "tubular", "sparse", "imbalanced", "imbalance", "rare",
    "few-shot", "low-resource", "scarce", "noisy", "long-tail", "boundary",
    "fine-grained", "continuity", "connectivity", "topology", "topological",
    "small", "tiny", "weak", "weakly-supervised", "self-supervised", "frozen",
    "low-rank", "out-of-distribution", "domain-shift", "distribution-shift",
)

# Distant FIELDS to probe for analogous solved problems. Field-agnostic spread so the widener
# always reaches OTHER disciplines regardless of the input's home field.
_DISTANT_FIELDS = (
    "natural language processing",
    "computer vision",
    "reinforcement learning",
    "graph neural networks",
    "signal processing",
    "time-series forecasting",
    "information retrieval",
    "robotics and control",
    "speech processing",
    "computational geometry",
    "remote sensing",
    "bioinformatics",
)

# Query TEMPLATES pairing the abstracted mechanism with a distant field. Each template asks for a
# *solved analog* in another discipline. ``{m}`` = mechanism phrase, ``{f}`` = distant field.
_TEMPLATES = (
    "{m} in {f}",
    "how does {f} solve {m}",
    "{m} methods from {f} transferable to other domains",
    "analogous problem to {m} addressed in {f}",
    "state-of-the-art {m} techniques in {f}",
    "{f} approaches for {m} under limited supervision",
)

_WORD_RE = re.compile(r"[A-Za-z][A-Za-z\-]*")
_WS_RE = re.compile(r"\s+")


def _tokens(text: str) -> List[str]:
    """Lowercased word tokens (hyphenated terms kept as one token: ``few-shot``, ``low-rank``)."""
    return [t.lower() for t in _WORD_RE.findall(text or "")]


def abstract_problem(problem: str) -> str:
    """Strip domain-specific nouns from ``problem`` to a mechanism-level phrasing.

    Keeps mechanism verbs (segment/predict/rank/…) and difficulty-regime qualifiers
    (thin/sparse/few-shot/…); drops concrete objects of study (organ/text/graph/CT/…).
    Deterministic and field-agnostic. Falls back gracefully so the result is never empty.

    Examples (illustrative — the vocab is domain-general):
        "segment the thin tubular structure in 3D scans" -> "segment thin structure"
        "few-shot classification of rare text documents"     -> "few-shot classify rare"
    """
    if not (problem or "").strip():
        raise ValueError("abstract_problem requires a non-empty problem string")

    toks = _tokens(problem)
    mechanisms = [t for t in toks if t in _MECHANISM_TERMS]
    structures = [t for t in toks if t in _STRUCTURE_TERMS]

    # De-duplicate while preserving first-seen order (stable, deterministic).
    def _dedup(seq: List[str]) -> List[str]:
        seen: set = set()
        out: List[str] = []
        for t in seq:
            if t not in seen:
                seen.add(t)
                out.append(t)
        return out

    mechanisms = _dedup(mechanisms)
    structures = _dedup(structures)

    parts: List[str] = []
    parts.extend(mechanisms[:2])  # at most two mechanism verbs keeps the phrase tight
    parts.extend(structures[:2])  # at most two difficulty qualifiers

    if not parts:
        # No known mechanism/structure term matched: fall back to the non-domain content words
        # (drop domain nouns + short stopword-ish tokens) so we still emit a usable phrase.
        residual = [t for t in toks if t not in _DOMAIN_NOUNS and len(t) > 3]
        parts = _dedup(residual)[:4]

    phrase = " ".join(parts).strip()
    if not phrase:  # ultra-degenerate input (all domain nouns / all tiny tokens)
        phrase = _WS_RE.sub(" ", problem.strip().lower())
    return phrase


def cross_domain_queries(problem: str, *, k: int = 6) -> List[str]:
    """Generate up to ``k`` other-field query strings around the abstracted mechanism of a problem.

    Pairs the mechanism-level phrasing (see :func:`abstract_problem`) with a fixed spread of
    distant fields via field-agnostic templates, so the scout's retrieval reaches analogous
    *solved* problems outside the project's home domain. Pure, deterministic, no network: the
    same ``(problem, k)`` always yields the same ordered, de-duplicated list.

    This WIDENS retrieval; it asserts no transfer. ``k`` is clamped to ``[1, len(fields)]`` so a
    caller can never request more distinct-field queries than fields exist.

    Args:
        problem: a concrete research problem (any field).
        k: number of queries to return (default 6).

    Returns:
        Deterministically ordered, de-duplicated query strings (length ``min(k, fields)``).
    """
    if k < 1:
        raise ValueError(f"k must be >= 1, got {k}")
    mechanism = abstract_problem(problem)
    k = min(k, len(_DISTANT_FIELDS))

    queries: List[str] = []
    seen: set = set()
    # Walk fields first (one per field => k distinct fields), cycling templates so the phrasings
    # vary. This guarantees breadth across disciplines before repeating a field.
    for i in range(k):
        field = _DISTANT_FIELDS[i]
        template = _TEMPLATES[i % len(_TEMPLATES)]
        q = _WS_RE.sub(" ", template.format(m=mechanism, f=field)).strip()
        if q not in seen:
            seen.add(q)
            queries.append(q)
    return queries


__all__ = ["abstract_problem", "cross_domain_queries"]
