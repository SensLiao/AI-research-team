"""Pre-tournament idea dedup (absorption wave 1; AI-Researcher 0.8-cosine pattern).

Stanford AI-Researcher's pipeline dedups generated ideas at 0.8 cosine similarity BEFORE ranking —
without it, near-duplicates flood the tournament and the ranking measures phrasing luck, not idea
quality. This port keeps the mechanism and the machine's determinism rules:

  - default similarity is LEXICAL and dependency-free (max of token-Jaccard and difflib
    SequenceMatcher over the idea text) — fully deterministic, offline, 3.9-stdlib;
  - an ``embed_fn`` is injectable (text -> vector); when provided (e.g. a sentence-transformers
    wrapper, or a test fake), cosine over its vectors REPLACES the lexical score — the
    AI-Researcher fidelity path, still deterministic given a deterministic embedder;
  - merge bookkeeping is PROVENANCE, not deletion: every merged idea's id is recorded against
    the representative it merged into (no idea silently vanishes — novelty-paradox guard kin);
  - representative choice is deterministic: ideas are processed sorted by idea_id; the first
    member of a duplicate cluster (lowest idea_id) represents it.

Pure functions: no I/O, no network, no LLM, no clock.
"""
from __future__ import annotations

import math
import re
from difflib import SequenceMatcher
from typing import Callable, List, Optional, Sequence

DEFAULT_THRESHOLD = 0.8
_WORD_RE = re.compile(r"[a-z0-9]+")

EmbedFn = Callable[[str], Sequence[float]]


def _norm_tokens(text: str) -> List[str]:
    return _WORD_RE.findall((text or "").lower())


def lexical_similarity(a: str, b: str) -> float:
    """max(token-Jaccard, SequenceMatcher ratio) in [0,1]; empty text NEVER matches anything
    (two ideas with no summary must not auto-merge on vacuous equality)."""
    ta, tb = _norm_tokens(a), _norm_tokens(b)
    if not ta or not tb:
        return 0.0
    jacc = len(set(ta) & set(tb)) / len(set(ta) | set(tb))
    seq = SequenceMatcher(None, " ".join(ta), " ".join(tb)).ratio()
    return max(jacc, seq)


def _cosine(va: Sequence[float], vb: Sequence[float]) -> float:
    dot = sum(x * y for x, y in zip(va, vb))
    na = math.sqrt(sum(x * x for x in va))
    nb = math.sqrt(sum(y * y for y in vb))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


def similarity(a: str, b: str, embed_fn: Optional[EmbedFn] = None) -> float:
    """Embedding cosine when an embedder is supplied (AI-Researcher fidelity), lexical otherwise."""
    if embed_fn is not None:
        if not (a or "").strip() or not (b or "").strip():
            return 0.0
        return _cosine(embed_fn(a), embed_fn(b))
    return lexical_similarity(a, b)


def dedupe_ideas(ideas: List[dict], threshold: float = DEFAULT_THRESHOLD,
                 text_key: str = "summary", embed_fn: Optional[EmbedFn] = None) -> dict:
    """Cluster near-duplicate ideas; return {kept, merged, threshold}.

    kept   — the representative ideas (deterministic: lowest idea_id of each cluster), in
             idea_id order, each dict passed through unchanged (immutability: copies).
    merged — provenance entries {kept_id, merged_ids, max_similarity} for every cluster that
             absorbed at least one duplicate. No idea is silently dropped — every input id
             appears either in kept or in exactly one merged_ids list.
    """
    if not (0.0 < threshold <= 1.0):
        raise ValueError(f"threshold must be in (0, 1], got {threshold}")
    ids = [i.get("idea_id") for i in ideas]
    if any(not isinstance(x, str) or not x.strip() for x in ids):
        raise ValueError(f"every idea must carry a non-empty string idea_id (got {ids})")
    if len(set(ids)) != len(ids):
        dupes = sorted({x for x in ids if ids.count(x) > 1})
        raise ValueError(f"duplicate idea_id (none may vanish): {dupes}")

    ordered = sorted((dict(i) for i in ideas), key=lambda i: i["idea_id"])
    kept: List[dict] = []
    merged_map = {}
    for idea in ordered:
        text = str(idea.get(text_key) or "")
        target = None
        best = 0.0
        for rep in kept:
            sim = similarity(text, str(rep.get(text_key) or ""), embed_fn=embed_fn)
            if sim >= threshold and sim > best:
                target, best = rep, sim
        if target is None:
            kept.append(idea)
        else:
            entry = merged_map.setdefault(target["idea_id"],
                                          {"kept_id": target["idea_id"], "merged_ids": [],
                                           "max_similarity": 0.0})
            entry["merged_ids"].append(idea["idea_id"])
            entry["max_similarity"] = round(max(entry["max_similarity"], best), 4)
    return {"kept": kept,
            "merged": [merged_map[k] for k in sorted(merged_map)],
            "threshold": threshold}
