"""
dashboard.py - one-glance terminal status of the research vault.

Run:  python 06-scripts/dashboard.py

Reuses lint_vault's frontmatter parser. Read-only; never writes.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import lint_vault as L  # parse_page / collect_pages / THREAD_LABELS

VAULT = L.VAULT_ROOT
W = 64


def bar(n: int, total: int, width: int = 22) -> str:
    if total <= 0:
        return ""
    filled = int(round(width * n / total))
    return "#" * filled + "." * (width - filled)


def git(*args: str) -> str:
    try:
        return subprocess.run(
            ["git", "-C", str(VAULT), *args],
            capture_output=True, text=True, timeout=5,
        ).stdout.strip()
    except Exception:
        return ""


def zoom_stage(statuses: list[str]) -> str:
    if any(s in ("deep-read", "cited") for s in statuses):
        return "implementation"
    if any(s == "read" for s in statuses):
        return "cluster"
    return "trend (scan)"


def main() -> None:
    pages = L.collect_pages()
    by_type: dict[str, int] = {}
    papers: list[dict] = []
    for p in pages:
        meta, _ = L.parse_page(p)
        t = str(meta.get("type", "?"))
        by_type[t] = by_type.get(t, 0) + 1
        if t == "paper":
            papers.append(meta)

    P = len(papers)
    rs_order = ["to-read", "skimmed", "read", "deep-read", "cited"]
    rs = {k: 0 for k in rs_order}
    rel = {"direct": 0, "adjacent": 0, "background": 0}
    for m in papers:
        k = str(m.get("reading-status", "to-read"))
        rs[k] = rs.get(k, 0) + 1
        r = str(m.get("relevance", "adjacent"))
        rel[r] = rel.get(r, 0) + 1

    threads: dict[str, list[str]] = {}
    for m in papers:
        th = next((t for t in (m.get("tags") or []) if t in L.THREAD_LABELS), "(unfiled)")
        threads.setdefault(th, []).append(str(m.get("reading-status", "to-read")))

    candidates = [m for m in papers
                  if m.get("relevance") == "direct" and m.get("reading-status") == "skimmed"]

    print()
    print("=" * W)
    print("  PhD-Research-OS  .  DASHBOARD")
    print("=" * W)

    print("\n## PIPELINE  (5-agent team, left-to-right execution order)")
    print("   literature-ingest  ->  experiment-planner  -> [DIRECTOR approves]")
    print("      search / read         design + variables")
    print("      ->  ablation-runner  ->  result-analyzer  ->  adversarial-reviewer")
    print("            run (GPU)            analyze              refute -> freeze")

    print("\n## KNOWLEDGE BASE  (notes by type)")
    interesting = ["paper", "experiment", "run", "result", "claim", "decision",
                   "synthesis", "idea", "negative-result"]
    for t in interesting:
        n = by_type.get(t, 0)
        flag = "" if n else "   <- empty (research not started here)"
        print(f"    {n:>3}  {t}{flag}")

    print(f"\n## READING FUNNEL  ({P} papers)")
    for k in rs_order:
        print(f"    {k:<10} {rs.get(k, 0):>3}  {bar(rs.get(k, 0), P)}")
    print(f"    relevance:  direct {rel['direct']}  .  adjacent {rel['adjacent']}  .  background {rel['background']}")

    print("\n## THREADS -> zoom stage  (derived from each thread's reading depth)")
    for th in sorted(threads):
        st = threads[th]
        print(f"    {th:<34} {len(st):>2}p   [{zoom_stage(st)}]")

    print("\n## NEXT ACTIONS")
    print(f"    {len(candidates)} deep-read candidates  (relevance:direct still at skimmed)")
    print("    -> Obsidian: 03-views/11-granularity-worklists.base  ('Depth worklist')")

    print("\n## VERSION CONTROL")
    n_commits = git("rev-list", "--count", "HEAD") or "0"
    last = git("log", "-1", "--format=%h  %s")
    print(f"    {n_commits} commits  .  last: {last[:48]}")

    print("\n" + "=" * W + "\n")


if __name__ == "__main__":
    main()
