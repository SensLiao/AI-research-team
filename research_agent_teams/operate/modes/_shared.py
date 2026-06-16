"""Shared deterministic helpers for operate recipes (audit waves A-B, 2026-06-13).

One implementation of the cross-mode gates so six recipes cannot drift apart:

  - north-star plumbing (audit H2): read the run's immutable direction contract from the
    task_frame, render the standard worker-prompt block, and run the per-stage drift gate
    (tools/drift_gate) — provable drift (out-of-scope topic / zero anchor coverage) BLOCKs.
  - bundle precheck (audit H3/W4): a worker bundle missing a required top-level key raises a
    readable GateBlock instead of a bare KeyError.
  - referential integrity (audit H3): downstream ids must resolve to real upstream ids; vault
    ``[[slug]]`` refs must name a page that actually exists; internal-shaped ids not produced by
    any upstream stage are fabricated references and BLOCK.
  - live existence gate (audit H4): external refs (DOI / arXiv / title) go through
    tools/citation_existence — confirmed-nonexistent BLOCKs, offline degrades to warnings.
  - pre-search (audit H5/M1): the sanctioned live-retrieval pre-step, generalized from
    deep_research so every DISCOVER-entry mode can ground novelty in real literature.
  - negative-result memory (audit C2): ideas are lexically matched against the vault's
    negative-results cluster (read-only) — "you already falsified this" becomes a visible caveat.

All helpers are deterministic given their inputs; ``EXISTENCE_TRANSPORT`` is the single
test-injection point for the network-facing gate (run_dets signatures stay CLI-fixed).
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set, Tuple

import yaml

from ..artifacts import GateBlock, write_artifact
from ...tools.citation_existence import ExistenceCache, build_existence_verdict
from ...tools.drift_gate import build_verdict as _build_drift_verdict
from ...tools.idea_dedup import lexical_similarity
from ...tools.paper_search import no_semantic_neighbor_found, search, write_search_bundle
from ...tools.scope_guard import discover_vault_root
from ...tools.validate_artifact import PROFILE_DIR

# Test-injection point for the live existence checker. Production leaves it None (real network;
# a dead network degrades to lookup_error WARNINGS — never a false BLOCK, never silently verified).
EXISTENCE_TRANSPORT = None

# Test-injection point for the vault used by slug-integrity / negative-result checks.
# None (production) -> discover the real two-repo layout; a path -> force that vault;
# False -> force 'no vault reachable' (slug checks degrade to warnings — the offline-safe state).
VAULT_ROOT_OVERRIDE = None


def resolve_vault_root(default_vault=None):
    """The vault root the deterministic checks read (READ-ONLY), honoring the test override."""
    if VAULT_ROOT_OVERRIDE is False:
        return None
    if VAULT_ROOT_OVERRIDE:
        return VAULT_ROOT_OVERRIDE
    root = discover_vault_root()
    if root:
        return root
    if default_vault and Path(default_vault).is_dir():
        return default_vault
    return None

_SLUG_REF_RE = re.compile(r"^\[\[([a-z0-9]+(?:-[a-z0-9]+)*)\]\]$")
# Internal artifact ids (GAP-1, IH2, IDEA-003, EV-1, FW-2, conf1, c1) — anchored tightly, same
# discipline as tools/idea_grounding._INTERNAL_RE: a fabricated internal-shaped id must BLOCK.
_INTERNAL_ID_RE = re.compile(r"^(GAP|IH|IDEA|EV|FW|conf|c)[-_]?\d+$")

NEGATIVE_RESULT_SIM_THRESHOLD = 0.45


# --------------------------------------------------------------------------- task_frame / north star

def task_frame(run_dir) -> dict:
    return json.loads((Path(run_dir) / "task_frame.artifact.json").read_text(encoding="utf-8"))


def budget(run_dir) -> dict:
    return dict(task_frame(run_dir)["payload"].get("budget") or {})


def north_star(run_dir) -> dict:
    """The run's direction contract; legacy frames (no north_star) fall back to request_text."""
    p = task_frame(run_dir)["payload"]
    ns = p.get("north_star") or {}
    return {"statement": str(ns.get("statement") or p.get("request_text") or ""),
            "in_scope": list(ns.get("in_scope") or []),
            "out_of_scope": list(ns.get("out_of_scope") or [])}


def north_star_block(run_dir) -> str:
    """The standard NORTH STAR section every worker prompt carries (audit A2 — injection 100%)."""
    ns = north_star(run_dir)
    in_s = ", ".join(ns["in_scope"]) if ns["in_scope"] else "(none declared)"
    out_s = ", ".join(ns["out_of_scope"]) if ns["out_of_scope"] else "(none declared)"
    return (
        "NORTH STAR (the run's ONLY direction — a deterministic drift gate checks every stage's "
        "output against it; producing an out-of-scope topic is a hard BLOCK):\n"
        f"    {ns['statement']}\n"
        f"  in_scope: {in_s}\n"
        f"  out_of_scope: {out_s}\n"
        "Serve this direction only. If your inputs pull elsewhere, SAY SO in your output instead "
        "of silently following them; you never re-scope the run — only the director may."
    )


def domain_profile(run_dir) -> Optional[dict]:
    """The active domain-profile BODY (profiles/<ref>.profile.yaml), or None when unset/missing."""
    ref = task_frame(run_dir)["payload"].get("domain_profile_ref")
    if not ref:
        return None
    p = Path(PROFILE_DIR) / f"{ref}.profile.yaml"
    if not p.is_file():
        return None
    return yaml.safe_load(p.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------- bundle precheck (W4)

def require_bundle_keys(bundle: dict, keys: Iterable[str], *, stage: str, mode: str) -> None:
    """A worker bundle missing required top-level keys is a readable gate failure, not a KeyError."""
    if not isinstance(bundle, dict):
        raise GateBlock(f"{mode} {stage} worker bundle is not a JSON object")
    missing = [k for k in keys if k not in bundle]
    if missing:
        raise GateBlock(
            f"{mode} {stage} worker bundle is missing required key(s) {missing} — re-dispatch the "
            f"{stage} worker; it must emit the COMPLETE bundle shape its prompt specifies")


# --------------------------------------------------------------------------- drift gate (H2)

def run_drift_gate(run_dir, stage: str, ts: str, texts: Iterable[str]) -> Tuple[str, dict]:
    """Write the stage's drift verdict (analysis_check_verdict / goal_alignment); BLOCK on drift."""
    payload, facts = _build_drift_verdict(north_star(run_dir), texts, stage)
    path = write_artifact(run_dir, stage, "drift-verdict.artifact.json",
                          "analysis_check_verdict", "goal-alignment-checker", payload, ts,
                          "blocked" if not payload["pass"] else "approved")
    if not payload["pass"]:
        raise GateBlock(f"north-star drift gate BLOCK at {stage}: {payload['violations']}")
    return path, facts


# --------------------------------------------------------------------------- citation gates (H3/H4)

def resolvable_refs(evidence_table: dict) -> Set[str]:
    """The known-good ref set for citation_checker.build_report (audit W2 — the half-gate fix)."""
    return {str(s.get("ref")) for s in (evidence_table.get("sources") or []) if s.get("ref")}


def external_refs(evidence_table: dict, claim_evidence_map: Optional[dict] = None) -> List[str]:
    """Every non-slug ref a worker cited (sources + loci) — the existence gate's input."""
    refs: Dict[str, None] = {}
    for s in (evidence_table.get("sources") or []):
        r = str(s.get("ref") or "").strip()
        if r and not _SLUG_REF_RE.match(r):
            refs.setdefault(r)
    for m in ((claim_evidence_map or {}).get("mappings") or []):
        for locus in (m.get("loci") or []):
            r = str(locus.get("source_ref") or "").strip()
            if r and not _SLUG_REF_RE.match(r):
                refs.setdefault(r)
    return list(refs)


def run_existence_gate(run_dir, stage: str, ts: str, refs: List[str]) -> Tuple[str, dict]:
    """Live three-state existence check over external refs (audit H4 — the unplugged weapon, plugged).

    BLOCK iff a ref is CONFIRMED not to exist (the fabrication signal); lookup_error -> warning
    (offline-safe). The per-run sqlite cache makes re-checks free and the verdict reproducible."""
    clean = [r for r in dict.fromkeys(str(r).strip() for r in refs) if r]
    cache = ExistenceCache(str(Path(run_dir) / "inbox" / "citation-cache.sqlite"))
    try:
        verdict = build_existence_verdict(clean, ts, transport=EXISTENCE_TRANSPORT, cache=cache)
    finally:
        cache.close()
    path = write_artifact(run_dir, stage, "citation-existence-verdict.artifact.json",
                          "citation_existence_verdict", "citation-integrity-auditor", verdict, ts,
                          "blocked" if verdict["verdict"] == "BLOCK" else "approved")
    if verdict["verdict"] == "BLOCK":
        raise GateBlock(f"citation existence gate BLOCK at {stage}: {verdict['violations']}")
    return path, verdict


def vault_slugs(vault_root) -> Optional[Set[str]]:
    """Every real page slug in the vault's 02-wiki (read-only), or None when no vault is reachable."""
    if not vault_root:
        return None
    wiki = Path(vault_root) / "02-wiki"
    if not wiki.is_dir():
        return None
    return {p.stem.lower() for p in wiki.rglob("*.md")}


def check_referential_integrity(refs: Iterable[str], known_ids: Set[str],
                                vault_slug_set: Optional[Set[str]] = None) -> Tuple[List[str], List[str]]:
    """(violations, warnings) for downstream refs (audit H3 — the broken-chain fix).

    A ref must be: a known upstream id, a vault slug that EXISTS, or an external ref (owned by
    the existence gate). An internal-shaped id nobody upstream produced is a fabricated reference."""
    violations: List[str] = []
    warnings: List[str] = []
    for ref in refs:
        r = str(ref).strip()
        if not r:
            violations.append("empty evidence_ref entry (a reference must point at something)")
            continue
        if r in known_ids:
            continue
        m = _SLUG_REF_RE.match(r)
        if m:
            if vault_slug_set is None:
                warnings.append(f"{r}: vault unreachable — slug existence unverified")
            elif m.group(1) not in vault_slug_set:
                violations.append(f"{r}: no such page in the vault (never invent a slug)")
            continue
        if _INTERNAL_ID_RE.match(r):
            violations.append(
                f"{r}: internal-shaped id that no upstream stage produced "
                f"(known ids: {sorted(known_ids)[:10]}…) — fabricated reference")
            continue
        # external ref (doi/arXiv/title/url): the existence gate owns it
    return violations, warnings


# --------------------------------------------------------------------------- pre-search (H5/M1)

def pre_search(run_dir, request: str, ts: str, transport=None,
               sources=("arxiv", "openalex", "crossref", "s2"), limit_per_source: int = 8) -> str:
    """Deterministic live-retrieval pre-step: drop inbox/search-results.json for the worker AND
    the novelty grounding signal. A dead network degrades to an empty-records bundle with
    source_errors recorded — the run proceeds vault-only and the report says so; nothing is
    fabricated. (Generalized from deep_research; every DISCOVER-entry recipe shares it.)"""
    try:
        res = search(request, sources=sources, limit_per_source=limit_per_source, transport=transport)
    except Exception as e:  # total failure (e.g. bad query) -> recorded, never invented
        res = {"query": request, "records": [], "source_errors": {"all": str(e)}}
    return write_search_bundle(run_dir, request, res, ts)


def search_records(run_dir) -> List[dict]:
    """The live-retrieval records dropped by pre_search ([] when the pre-step did not run)."""
    p = Path(run_dir) / "inbox" / "search-results.json"
    if not p.exists():
        return []
    try:
        return list(json.loads(p.read_text(encoding="utf-8")).get("records") or [])
    except (OSError, ValueError):
        return []


def novelty_signals_from_search(gaps: List[dict], records: List[dict]) -> Dict[str, List[str]]:
    """Per-gap retrieval-grounded novelty signals for aggregate_novelty(signals=...) (audit H5).

    A gap whose statement surfaces NO semantically-near retrieved title earns the positive
    'no_semantic_neighbor_found' signal. Empty records -> {} (novelty stays in-vault counting,
    and the recipe's report says so honestly)."""
    if not records:
        return {}
    out: Dict[str, List[str]] = {}
    for g in gaps:
        stmt = str(g.get("statement") or "")
        gid = str(g.get("gap_id") or "")
        if not stmt or not gid:
            continue
        sig = no_semantic_neighbor_found(stmt, records)
        if sig["no_semantic_neighbor_found"]:
            out[gid] = ["no_semantic_neighbor_found"]
    return out


# --------------------------------------------------------------------------- negative-result memory (C2)

def negative_result_caveats(vault_root, ideas: List[dict],
                            threshold: float = NEGATIVE_RESULT_SIM_THRESHOLD) -> Dict[str, List[str]]:
    """Match idea summaries against the vault's negative-results cluster (READ-ONLY).

    Returns {idea_id: [caveat, ...]} for ideas lexically close to a recorded negative result —
    'this one was already tried and falsified' becomes a visible menu caveat, never a cut."""
    out: Dict[str, List[str]] = {}
    if not vault_root:
        return out
    nr_dir = Path(vault_root) / "02-wiki" / "negative-results"
    if not nr_dir.is_dir():
        return out
    pages: List[Tuple[str, List[str]]] = []
    for p in sorted(nr_dir.rglob("*.md")):
        try:
            head = p.read_text(encoding="utf-8", errors="ignore").splitlines()[:50]
        except OSError:
            continue
        candidates = [p.stem.replace("-", " ")]
        candidates += [ln.lstrip("# ").strip() for ln in head if ln.startswith("#")]
        pages.append((p.stem, [c for c in candidates if c]))
    for idea in ideas:
        summary = str(idea.get("summary") or "")
        iid = str(idea.get("idea_id") or "")
        if not summary or not iid:
            continue
        for slug, candidates in pages:
            best = max((lexical_similarity(summary, c) for c in candidates), default=0.0)
            if best >= threshold:
                out.setdefault(iid, []).append(
                    f"possible prior NEGATIVE result: [[{slug}]] (lexical similarity "
                    f"{round(best, 2)}) — check it before betting on this idea")
    return out
