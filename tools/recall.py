"""Recall core — the M⇐D seam, read side (machine reads System D BY REFERENCE).

The machine never inlines System-D content into its run-store (blueprint §5). `/recall` resolves a
topic to [[slug]] + content-sha + section citations and emits a `recall_note`. The note carries
POINTERS, never the DB page body — so the run-store stays free of copied knowledge, and every cited
fact is traceable back to a live, hashed DB page (evidence-contract: never invent a slug).

Absorption wave 1 — TEMPR-style fused retrieval (Hindsight pattern, re-scoped to the vault):
the old single-channel whole-token slug match is now ONE of FOUR channels fused with Reciprocal
Rank Fusion (RRF, k=60, tie-aware competition ranks):

  1. slug-token   — whole-token match between query and slug (the original channel, kept).
  2. bm25         — BM25-lite full-text relevance over the page text (finds pages whose BODY
                    matches even when the slug does not; stdlib-only implementation).
  3. wikilink     — 1-hop graph expansion: pages linked from / linking to the top direct hits
                    (the vault's own [[wikilink]] graph as the relation channel).
  4. temporal     — recency (frontmatter year/date) as a RANKING channel over the candidate
                    pool only. It can re-order candidates; it can NEVER introduce a page by
                    itself — an unrelated query stays vault_silent no matter how new a page is.

A 5th embedding channel is deliberately NOT enabled (no hard deps; can be added later behind a
guarded import as another ranked list into the same RRF).

By-reference guarantees preserved: citations carry slug + content-sha + first-heading section +
a `supports` note built ONLY from query tokens / channel names / years — never page text.
Pure ranking helpers are I/O-free; I/O stays isolated in recall().
"""
from __future__ import annotations

import hashlib
import math
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

_SLUG_IN_INDEX = re.compile(r"\[\[([a-z0-9]+(?:-[a-z0-9]+)*)")
_HEADING = re.compile(r"^#{1,3}\s+(.*\S)", re.MULTILINE)
_WIKILINK = re.compile(r"\[\[([a-z0-9]+(?:-[a-z0-9]+)*)")
_YEAR_KEY = re.compile(r"(?im)^(?:year|date|published|review-date)\s*:\s*\"?(\d{4})")
_WORD = re.compile(r"[a-z0-9]+")
_FM_BLOCK = re.compile(r"^---\s*\n(.*?)\n---", re.DOTALL)
_PROJECT_LINE = re.compile(r"(?m)^project[ \t]*:[ \t]*(.*)$")  # [ \t] not \s: must not cross the newline into a block list

RRF_K = 60
TOP_K = 6
_BM25_K1 = 1.5
_BM25_B = 0.75

# Stopwords are filtered from the QUERY before any channel runs. Without this, the BM25 channel's
# idf floor (log(x)+1 is always positive) lets a ubiquitous filler word ("the"/"how"/"with"/"for",
# all >=3 chars so _WORD keeps them) match a page BODY and defeat vault_silent — the recall_note's
# redundant anti-fabrication promise (evidence-contract: "recall must say so explicitly, never
# fabricate"). Domain-general: English function words, not topic terms.
_STOPWORDS = frozenset({
    "the", "and", "for", "are", "but", "not", "you", "all", "any", "can", "has", "had", "her",
    "was", "one", "our", "out", "his", "how", "man", "new", "now", "old", "see", "two", "way",
    "who", "did", "yes", "his", "been", "have", "this", "that", "with", "they", "from", "what",
    "your", "when", "make", "like", "time", "just", "know", "into", "than", "them", "then",
    "does", "did", "will", "would", "could", "should", "about", "there", "their", "which",
    "where", "while", "these", "those", "being", "over", "such", "some", "more", "most", "very",
})


def _sha256_text(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def _index_slugs(vault_root: Path) -> List[str]:
    idx = vault_root / "00-system" / "index.md"
    if not idx.exists():
        return []
    return sorted(set(_SLUG_IN_INDEX.findall(idx.read_text(encoding="utf-8"))))


def _resolve_page(vault_root: Path, slug: str) -> Optional[Path]:
    hits = list((vault_root / "02-wiki").glob(f"**/{slug}.md"))
    return hits[0] if hits else None


def _tokens(query: str) -> List[str]:
    return [t for t in re.split(r"[^a-z0-9]+", (query or "").lower())
            if len(t) >= 3 and t not in _STOPWORDS]


def _doc_tokens(text: str) -> List[str]:
    return [t for t in _WORD.findall((text or "").lower()) if len(t) >= 3]


# ---------- pure: channels ----------

def _ranks(scored: List[Tuple[str, float]]) -> Dict[str, int]:
    """Tie-aware competition ranks (1,1,3,...) from (slug, score) pairs, score DESC / slug ASC.
    Tie-awareness matters: RRF must let a later channel (e.g. temporal) re-order genuine ties
    instead of laundering them through an arbitrary slug-order rank difference."""
    ordered = sorted(scored, key=lambda x: (-x[1], x[0]))
    out: Dict[str, int] = {}
    prev_score: Optional[float] = None
    prev_rank = 0
    for pos, (slug, score) in enumerate(ordered, start=1):
        rank = prev_rank if prev_score is not None and score == prev_score else pos
        out[slug] = rank
        prev_score, prev_rank = score, rank
    return out


def channel_slug_token(query_tokens: List[str], pages: List[dict]) -> Dict[str, int]:
    scored = []
    for p in pages:
        shared = [t for t in query_tokens if t in set(p["slug"].split("-"))]
        if shared:
            scored.append((p["slug"], float(len(shared))))
    return _ranks(scored)


def channel_bm25(query_tokens: List[str], pages: List[dict]) -> Dict[str, int]:
    """BM25-lite over page text. Only pages containing >=1 query token score (score>0)."""
    if not pages:
        return {}
    n = len(pages)
    avgdl = sum(len(p["tokens"]) for p in pages) / max(1, n)
    df: Dict[str, int] = {}
    for t in set(query_tokens):
        df[t] = sum(1 for p in pages if t in p["token_set"])
    scored = []
    for p in pages:
        dl = len(p["tokens"]) or 1
        s = 0.0
        for t in query_tokens:
            tf = p["tf"].get(t, 0)
            if tf == 0:
                continue
            idf = math.log((n - df[t] + 0.5) / (df[t] + 0.5) + 1.0)
            s += idf * (tf * (_BM25_K1 + 1)) / (tf + _BM25_K1 * (1 - _BM25_B + _BM25_B * dl / avgdl))
        if s > 0.0:
            scored.append((p["slug"], s))
    return _ranks(scored)


def channel_wikilink(seed_slugs: List[str], pages: List[dict]) -> Dict[str, int]:
    """1-hop expansion: pages connected to the seeds via [[wikilinks]] (either direction),
    excluding the seeds themselves; scored by number of seed connections."""
    seeds = set(seed_slugs)
    if not seeds:
        return {}
    by_slug = {p["slug"]: p for p in pages}
    scored = []
    for p in pages:
        if p["slug"] in seeds:
            continue
        out_links = p["links"] & seeds
        in_links = {s for s in seeds if p["slug"] in by_slug[s]["links"]} if p["slug"] else set()
        conn = len(out_links | in_links)
        if conn:
            scored.append((p["slug"], float(conn)))
    return _ranks(scored)


def channel_temporal(pool: List[str], pages: List[dict]) -> Dict[str, int]:
    """Recency rank over the CANDIDATE POOL only — never introduces a page by itself."""
    by_slug = {p["slug"]: p for p in pages}
    scored = [(s, float(by_slug[s]["year"])) for s in pool
              if s in by_slug and by_slug[s]["year"] is not None]
    return _ranks(scored)


def fuse_rrf(channel_ranks: Dict[str, Dict[str, int]], k: int = RRF_K) -> List[Tuple[str, float]]:
    """Reciprocal Rank Fusion across named channels -> (slug, fused_score) DESC, slug ASC."""
    fused: Dict[str, float] = {}
    for ranks in channel_ranks.values():
        for slug, r in ranks.items():
            fused[slug] = fused.get(slug, 0.0) + 1.0 / (k + r)
    return sorted(fused.items(), key=lambda x: (-x[1], x[0]))


# ---------- pure: note assembly (contract unchanged) ----------

def build_recall_note(query: str, citations: List[dict], *,
                      closest: Optional[dict] = None) -> dict:
    """Assemble a recall_note. citations is a list of {slug, sha256, section?, supports?} — pointers
    only, never DB body. vault_silent is derived from whether any citation was found."""
    silent = len(citations) == 0
    confidence = "high" if len(citations) >= 2 else ("medium" if citations else "low")
    note = {
        "query": query,
        "citations": citations,
        "confidence": confidence,
        "vault_silent": silent,
    }
    if silent and closest is not None:
        note["closest"] = closest
    return note


def _supports_note(slug: str, query_tokens: List[str], channel_ranks: Dict[str, Dict[str, int]],
                   year: Optional[int]) -> str:
    """The supports pointer, built ONLY from query tokens / channel names / year — never page text."""
    parts = []
    st = channel_ranks.get("slug-token", {})
    if slug in st:
        shared = [t for t in query_tokens if t in set(slug.split("-"))]
        parts.append("slug-token(" + ", ".join(shared) + ")" if shared else "slug-token")
    if slug in channel_ranks.get("bm25", {}):
        parts.append(f"bm25#{channel_ranks['bm25'][slug]}")
    if slug in channel_ranks.get("wikilink", {}):
        parts.append("wikilink-neighbor")
    if slug in channel_ranks.get("temporal", {}) and year is not None:
        parts.append(f"recency({year})")
    return "channels: " + "; ".join(parts) if parts else "fused match"


# ---------- pure: per-page parse (cacheable) ----------

def _page_projects(text: str) -> frozenset:
    """The `project:` facet(s) of a page (schema-contract §9.6 many-to-many): scalar, inline `[a, b]`,
    or block (`- a`) list — all normalise to a frozenset. Empty when the page declares no project.
    Project-isolated RECALL keeps a page iff this set intersects {active_project, 'meta'}."""
    fm = _FM_BLOCK.match(text)
    block = fm.group(1) if fm else ""
    pm = _PROJECT_LINE.search(block)
    if not pm:
        return frozenset()
    val = pm.group(1).strip()
    if val and val != "[]":
        if val.startswith("["):
            return frozenset(x.strip().strip("'\"") for x in val.strip("[]").split(",") if x.strip())
        return frozenset({val.strip("'\"")})
    out = []
    for line in block[pm.end():].splitlines():
        s = line.strip()
        if s.startswith("- "):
            out.append(s[2:].strip().strip("'\""))
        elif s:
            break
    return frozenset(i for i in out if i)


def _parse_page(slug: str, text: str) -> dict:
    """Build the immutable-by-convention page record from a slug + its raw text. Pure: same
    (slug, text) -> equal dict. The returned sets/dicts are only ever READ downstream (channel
    helpers build fresh sets for intersections), so the cached object is safe to share across calls."""
    toks = _doc_tokens(text)
    tf: Dict[str, int] = {}
    for t in toks:
        tf[t] = tf.get(t, 0) + 1
    ym = _YEAR_KEY.search(text)
    heading = _HEADING.search(text)
    return {"slug": slug, "text": text, "tokens": toks, "token_set": set(toks),
            "tf": tf, "links": set(_WIKILINK.findall(text)) - {slug},
            "year": int(ym.group(1)) if ym else None,
            "heading": heading.group(1) if heading else "",
            "projects": _page_projects(text),
            "sha": _sha256_text(text)}


# ---------- I/O ----------

# Module-level page cache (M11): resolved-path-str -> (mtime_ns, size, parsed page dict). A page is
# re-parsed ONLY when its (mtime_ns, size) changes; an unchanged page is served from the cache without
# touching the disk. The parse is pure and the cached dict is read-only downstream, so caching is
# byte-transparent — recall()'s output is identical with or without a cache hit. `clear_page_cache()`
# resets it (tests / a forced cold read). Keyed by the resolved absolute path so two vaults never collide.
_PAGE_CACHE: Dict[str, Tuple[int, int, dict]] = {}


def clear_page_cache() -> None:
    """Drop every cached page (test hook / force a cold re-read)."""
    _PAGE_CACHE.clear()


def _load_page_cached(path: Path, slug: str) -> dict:
    """Return the parsed page for `path`, reading+parsing only on a cold/stale cache entry.
    Cache validity key is (mtime_ns, size); a content edit changes both (size) or at least mtime."""
    key = str(path.resolve())
    st = path.stat()
    sig = (st.st_mtime_ns, st.st_size)
    hit = _PAGE_CACHE.get(key)
    if hit is not None and (hit[0], hit[1]) == sig:
        return hit[2]
    page = _parse_page(slug, path.read_text(encoding="utf-8"))
    _PAGE_CACHE[key] = (sig[0], sig[1], page)
    return page


def _load_pages(vault_root: Path) -> List[dict]:
    pages = []
    for slug in _index_slugs(vault_root):
        path = _resolve_page(vault_root, slug)
        if path is None:
            continue
        pages.append(_load_page_cached(path, slug))
    return pages


def recall(query: str, *, vault_root, project: Optional[str] = None, top_k: int = TOP_K) -> dict:
    """Resolve `query` against System D BY REFERENCE and return a recall_note.

    Four-channel TEMPR-style retrieval fused with RRF (module docstring); citations stay
    slug + content-sha + section pointers — the DB page body is hashed and pointed at,
    NEVER copied into the returned note."""
    vault_root = Path(vault_root)
    toks = _tokens(query)
    pages = _load_pages(vault_root)
    # PROJECT ISOLATION (no cross-project contamination): a scoped recall keeps only pages whose
    # `project:` facet set intersects {project, 'meta'} — project B never sees project A's pages,
    # while genuinely cross-project knowledge (`project: meta`) stays visible to all. project=None
    # keeps the legacy whole-vault behaviour, so existing callers/tests are byte-unaffected.
    if project is not None:
        allowed = {project, "meta"}
        pages = [p for p in pages if p["projects"] & allowed]
    slugs = [p["slug"] for p in pages]

    ch: Dict[str, Dict[str, int]] = {}
    ch["slug-token"] = channel_slug_token(toks, pages)
    ch["bm25"] = channel_bm25(toks, pages)
    direct = fuse_rrf({k: ch[k] for k in ("slug-token", "bm25")})
    seeds = [s for s, _ in direct[:3]]
    ch["wikilink"] = channel_wikilink(seeds, pages)
    pool = sorted(set(ch["slug-token"]) | set(ch["bm25"]) | set(ch["wikilink"]))
    ch["temporal"] = channel_temporal(pool, pages)

    fused = fuse_rrf(ch)
    by_slug = {p["slug"]: p for p in pages}
    citations: List[dict] = []
    for slug, _score in fused[:max(1, int(top_k))]:
        p = by_slug[slug]
        citations.append({
            "slug": slug,
            "sha256": p["sha"],
            "section": p["heading"],
            "supports": _supports_note(slug, toks, ch, p["year"]),
        })

    closest: Optional[dict] = None
    if not citations and slugs:
        closest = {"slug": slugs[0], "differs": "no shared topic token with the query"}
    return build_recall_note(query, citations, closest=closest)
