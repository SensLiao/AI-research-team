"""Full-text QA wrapper + deterministic retraction check (absorption wave 1; PaperQA2 pattern).

Two independent capabilities behind one artifact (``fulltext_qa_report``):

1. Page-anchored full-text QA — a thin wrapper around the OPTIONAL ``paper-qa`` package
   (PaperQA2). The engine is injectable: callers/tests pass ``engine`` (a callable
   ``(question, doc_paths, cache_dir) -> {"answer": str, "contexts": [...]}``); when omitted, the
   default engine imports paperqa lazily. HONESTY RULE: if the package is missing, no docs are
   given, or the engine errors, the report says ``available: false`` + reason — the machine never
   fabricates a full-text answer. Index/cache dirs are FENCED: anything inside the vault is
   rejected (two-repo seam; caches belong in ``runs/`` or machine-side dirs).

2. Deterministic retraction check — Crossref ``filter=updates:<DOI>`` notices (no LLM, no
   paperqa needed): retracted / concern / ok / unknown per ref. ContraCrow-style contradiction
   mining stays the contradiction-miner agent's judgment; this module only hands it page-anchored
   contexts and retraction flags as inputs.

The wrapper emits EVIDENCE for the DISCOVER workers (claim-evidence loci with page anchors);
PASS/BLOCK stays with the existing deterministic gates.
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable, Dict, List, Optional

from research_agent_teams.tools.scholar_clients import (
    ScholarLookupError,
    Transport,
    crossref_updates,
    normalize_doi,
)

_EXCERPT_MAX = 500

Engine = Callable[[str, List[str], Optional[str]], Dict]


def paperqa_available() -> bool:
    try:
        import paperqa  # noqa: F401
        return True
    except Exception:
        return False


def _in_vault(path: str) -> bool:
    return "phd-research-os" in str(Path(path).resolve()).replace("\\", "/").lower()


def _fence_cache_dir(cache_dir: Optional[str]) -> None:
    """Reject cache/index dirs inside the vault (the two-repo seam is non-negotiable)."""
    if cache_dir and _in_vault(cache_dir):
        raise ValueError(f"fulltext_qa cache_dir must never live in the vault: {cache_dir}")


def _fence_doc_paths(doc_paths: List[str]) -> None:
    """Reject source docs that live inside the vault. PaperQA contexts copy short excerpts of the
    consulted documents into the report; reading a vault page as a 'doc' would leak vault body text
    into a run artifact, breaking the by-reference seam. Full-text QA operates on scratch PDFs /
    external docs under runs/, never on the crown-jewels vault."""
    for d in doc_paths:
        if _in_vault(d):
            raise ValueError(
                f"fulltext_qa doc must never be a vault page (by-reference seam): {d}. "
                f"Full-text QA reads scratch PDFs / external docs, not the vault.")


def _default_engine(question: str, doc_paths: List[str], cache_dir: Optional[str]) -> Dict:
    """The real PaperQA2 engine (lazy import; only reached when the optional dep is installed)."""
    import paperqa  # local import — optional dependency

    settings = paperqa.Settings()
    if cache_dir:
        try:
            settings.agent.index.index_directory = cache_dir  # paperqa>=5 layout
        except Exception:
            pass
    docs = paperqa.Docs()
    for p in doc_paths:
        docs.add(p, settings=settings)
    answer = docs.query(question, settings=settings)
    contexts = []
    for c in getattr(answer, "contexts", []) or []:
        text_obj = getattr(c, "text", None)
        doc_obj = getattr(text_obj, "doc", None)
        contexts.append({
            "doc_ref": str(getattr(doc_obj, "docname", None) or getattr(doc_obj, "citation", "") or "doc"),
            "page": None,
            "excerpt": str(getattr(c, "context", ""))[:_EXCERPT_MAX],
            "relevance": float(getattr(c, "score", 0) or 0) / 10.0 if getattr(c, "score", None) is not None else None,
        })
    return {"answer": str(getattr(answer, "answer", "") or ""), "contexts": contexts}


def _normalize_contexts(raw_contexts: List[dict]) -> List[dict]:
    out: List[dict] = []
    for c in raw_contexts or []:
        excerpt = str(c.get("excerpt") or "")[:_EXCERPT_MAX]
        if not (c.get("doc_ref") and excerpt.strip()):
            continue
        ctx = {"doc_ref": str(c["doc_ref"]), "excerpt": excerpt}
        page = c.get("page")
        ctx["page"] = int(page) if isinstance(page, int) and page >= 1 else None
        rel = c.get("relevance")
        if isinstance(rel, (int, float)):
            ctx["relevance"] = max(0.0, min(1.0, float(rel)))
        else:
            ctx["relevance"] = None
        out.append(ctx)
    return out


def ask(question: str, doc_paths: List[str], cache_dir: Optional[str] = None,
        engine: Optional[Engine] = None,
        retraction_flags: Optional[List[dict]] = None) -> dict:
    """Run page-anchored full-text QA; return the ``fulltext_qa_report`` payload.

    Honest degradation order: no docs -> unavailable; engine missing (paperqa not installed and
    no injected engine) -> unavailable; engine raised -> unavailable with the error. The payload
    always validates against fulltext_qa_report.schema.json.
    """
    if not (question or "").strip():
        raise ValueError("ask requires a non-empty question")
    _fence_cache_dir(cache_dir)
    _fence_doc_paths(doc_paths or [])
    base = {"question": question, "retraction_flags": list(retraction_flags or [])}

    if not doc_paths:
        return dict(base, available=False, reason="no documents supplied (nothing to read)",
                    answer_summary="", contexts=[])
    if engine is None:
        if not paperqa_available():
            return dict(base, available=False,
                        reason="optional dependency 'paper-qa' is not installed — "
                               "pip install paper-qa to enable full-text QA",
                        answer_summary="", contexts=[])
        engine = _default_engine
    try:
        raw = engine(question, list(doc_paths), cache_dir)
    except Exception as e:  # honest: an engine crash is 'unavailable', never a fabricated answer
        return dict(base, available=False, reason=f"fulltext engine failed: {e}",
                    answer_summary="", contexts=[])
    return dict(base, available=True, reason="",
                answer_summary=str(raw.get("answer") or ""),
                contexts=_normalize_contexts(raw.get("contexts") or []))


# --------------------------------------------------------------------------- retraction check

def retraction_check(refs: List[str], transport: Optional[Transport] = None) -> List[dict]:
    """Deterministic Crossref retraction/concern flags for each ref (DOI-bearing refs only).

    Statuses: retracted (a retraction notice targets the DOI) / concern (an expression-of-concern
    notice targets it) / ok (lookup succeeded, no notice) / unknown (not a DOI, or lookup failed —
    absence of evidence is NOT evidence of absence offline).
    """
    out: List[dict] = []
    for ref in refs:
        raw = (ref or "").strip()
        doi = normalize_doi(raw.split("doi:")[-1] if raw.lower().startswith("doi:") else raw)
        if not doi:
            out.append({"ref": ref, "status": "unknown", "detail": "no DOI to check"})
            continue
        try:
            notices = crossref_updates(doi, transport=transport)
        except ScholarLookupError as e:
            out.append({"ref": ref, "status": "unknown", "detail": f"lookup failed: {e}"})
            continue
        kinds = " ".join(f"{n['type']} {n['label']}".lower() for n in notices)
        if "retraction" in kinds or "withdrawal" in kinds:
            out.append({"ref": ref, "status": "retracted",
                        "detail": f"notice(s): {', '.join(n['notice_doi'] for n in notices if n['notice_doi'])}"})
        elif "concern" in kinds:
            out.append({"ref": ref, "status": "concern",
                        "detail": f"expression of concern: {', '.join(n['notice_doi'] for n in notices if n['notice_doi'])}"})
        else:
            out.append({"ref": ref, "status": "ok", "detail": "no update notice registered"})
    return out
