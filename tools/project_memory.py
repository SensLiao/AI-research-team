"""Cross-run research memory (audit C1 — cures the 'amnesiac genius').

Every project's durable workspace (``projects/<slug>/notes/``) carries a machine-readable
``gap-inventory.jsonl``: one line per gap any run of this project ever classified. At the next
run's DISCOVER, the recipe loads the inventory and lexically matches the new gaps against it —
"this one you already explored in run X" becomes a visible advisory line instead of silent
re-mining. The inventory is MACHINE-side scratch (never the vault); deleting the project deletes it.

Determinism: caller supplies ts; matching is the same lexical similarity the idea-dedup tool uses;
appends are idempotent per (run_id, gap_id) so a repair-loop re-run never duplicates lines.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional

from research_agent_teams.tools.idea_dedup import lexical_similarity
from research_agent_teams.tools.projects import PROJECT_SLUG_RE

PRIOR_OVERLAP_THRESHOLD = 0.6  # lexical similarity at/above which a gap counts as 'seen before'
PRIOR_ART_MATCH_THRESHOLD = 0.6  # lexical similarity at/above which a new idea counts as 'already dead'


def workspace_for_run(run_dir) -> Optional[Path]:
    """The project workspace for a run in the project-grouped layout, else None (legacy flat).

    runs/<project>/<run_id>/  ->  <machine-root>/projects/<project>/   (sibling of runs/)
    """
    rd = Path(run_dir).resolve()
    project_dir = rd.parent
    runs_dir = project_dir.parent
    if runs_dir.name != "runs" or not PROJECT_SLUG_RE.match(project_dir.name):
        return None
    ws = runs_dir.parent / "projects" / project_dir.name
    return ws if ws.is_dir() else None


def _inventory_path(workspace: Path) -> Path:
    return Path(workspace) / "notes" / "gap-inventory.jsonl"


def load_gap_inventory(workspace) -> List[dict]:
    p = _inventory_path(Path(workspace))
    if not p.exists():
        return []
    rows: List[dict] = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except ValueError:
            continue  # a corrupt line never breaks recall of the rest
    return rows


def append_gap_inventory(workspace, run_id: str, ts: str, gaps: List[dict]) -> int:
    """Append this run's classified gaps (idempotent per (run_id, gap_id)). Returns lines added."""
    ws = Path(workspace)
    p = _inventory_path(ws)
    if "phd-research-os" in str(p.resolve()).replace("\\", "/").lower():
        raise ValueError(f"gap inventory must never live in the vault: {p}")
    existing = {(r.get("run_id"), r.get("gap_id")) for r in load_gap_inventory(ws)}
    p.parent.mkdir(parents=True, exist_ok=True)
    added = 0
    with open(p, "a", encoding="utf-8") as fh:
        for g in gaps:
            gap_id = str(g.get("gap_id") or "")
            if not gap_id or (run_id, gap_id) in existing:
                continue
            row = {"run_id": run_id, "ts": ts, "gap_id": gap_id,
                   "statement": str(g.get("statement") or ""),
                   "gap_type": str(g.get("gap_type") or "")}
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
            added += 1
    return added


def prior_overlaps(gaps: List[dict], inventory: List[dict], *, run_id: str,
                   threshold: float = PRIOR_OVERLAP_THRESHOLD) -> List[dict]:
    """Match new gaps against the project's prior inventory (other runs only).

    Returns [{gap_id, prior_run_id, prior_gap_id, similarity}] for every new gap whose statement
    lexically matches a prior gap at/above threshold — 'this one you already explored'."""
    out: List[dict] = []
    prior = [r for r in inventory if r.get("run_id") != run_id and r.get("statement")]
    for g in gaps:
        stmt = str(g.get("statement") or "")
        if not stmt:
            continue
        best, best_row = 0.0, None
        for r in prior:
            sim = lexical_similarity(stmt, str(r["statement"]))
            if sim > best:
                best, best_row = sim, r
        if best_row is not None and best >= threshold:
            out.append({"gap_id": str(g.get("gap_id") or ""),
                        "prior_run_id": str(best_row.get("run_id") or ""),
                        "prior_gap_id": str(best_row.get("gap_id") or ""),
                        "similarity": round(best, 4)})
    return out


def _prior_art_path(workspace: Path) -> Path:
    return Path(workspace) / "notes" / "known-prior-art.jsonl"


def load_prior_art(workspace) -> List[dict]:
    p = _prior_art_path(Path(workspace))
    if not p.exists():
        return []
    rows: List[dict] = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except ValueError:
            continue  # a corrupt line never breaks recall of the rest
    return rows


def append_prior_art(workspace, run_id: str, ts: str, dead_rows: List[dict]) -> int:
    """Append this run's DEAD ideas as future full-paper retrieval leads.

    Idempotent per (run_id, fingerprint). Returns lines added. Each dead_row supplies a fingerprint
    (normalized "method | application | domain"); when absent it falls back to the row's summary, and a
    row with neither is skipped (never write an empty key)."""
    ws = Path(workspace)
    p = _prior_art_path(ws)
    if "phd-research-os" in str(p.resolve()).replace("\\", "/").lower():
        raise ValueError(f"known-prior-art ledger must never live in the vault: {p}")
    existing = {(r.get("run_id"), r.get("fingerprint")) for r in load_prior_art(ws)}
    p.parent.mkdir(parents=True, exist_ok=True)
    added = 0
    with open(p, "a", encoding="utf-8") as fh:
        for d in dead_rows:
            summary = str(d.get("summary") or "")
            fingerprint = str(d.get("fingerprint") or "") or summary
            if not fingerprint or (run_id, fingerprint) in existing:
                continue
            row = {"run_id": run_id, "ts": ts,
                   "idea_id": str(d.get("idea_id") or ""),
                   "fingerprint": fingerprint,
                   "summary": summary,
                   "colliding_refs": list(d.get("colliding_refs") or []),
                   "experimentally_validated": bool(d.get("experimentally_validated")),
                   "verdict": "DEAD"}
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
            added += 1
    return added


def prior_art_matches(ideas: List[dict], inventory: List[dict], *,
                      threshold: float = PRIOR_ART_MATCH_THRESHOLD) -> Dict[str, dict]:
    """Match new ideas against the project's known-prior-art ledger.

    Returns lexical leads for the collision checker. A match is not a novelty
    verdict and never proves that an improved current claim is already done.
    Picks the best-scoring ledger row per idea."""
    out: Dict[str, dict] = {}
    rows = [r for r in inventory if r.get("fingerprint") or r.get("summary")]
    for idea in ideas:
        idea_id = str(idea.get("idea_id") or "")
        if not idea_id:
            continue
        probes = [str(idea.get("summary") or "")]
        fp = str(idea.get("fingerprint") or "")
        if fp:
            probes.append(fp)
        probes = [t for t in probes if t]
        if not probes:
            continue
        best, best_row = 0.0, None
        for r in rows:
            targets = [str(r.get("fingerprint") or ""), str(r.get("summary") or "")]
            for probe in probes:
                for target in targets:
                    if not target:
                        continue
                    sim = lexical_similarity(probe, target)
                    if sim > best:
                        best, best_row = sim, r
        if best_row is not None and best >= threshold:
            out[idea_id] = best_row
    return out
