"""
close_day.py — Refresh 00-system/hot.md from recent log entries.

Reads the most recent N days from 07-logs/log.md, extracts INGEST/SCHEMA/BACKFILL
entries, and prints a suggested replacement for hot.md.

This script does NOT auto-overwrite hot.md — it prints to stdout. The agent or human
reviews and applies. This is intentional: hot.md is a curated snapshot, not a dump.

Usage:
  python 06-scripts/close_day.py            # show suggested hot.md
  python 06-scripts/close_day.py --days 7   # consider last 7 days
"""
from __future__ import annotations
import argparse
import re
from datetime import date, timedelta
from pathlib import Path

VAULT_ROOT = Path(__file__).resolve().parent.parent
LOG_PATH = VAULT_ROOT / "07-logs" / "log.md"
HOT_PATH = VAULT_ROOT / "00-system" / "hot.md"

DATE_HEADER_RE = re.compile(r"^## (\d{4}-\d{2}-\d{2})\s*$", re.MULTILINE)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--days", type=int, default=7, help="how many days back to scan (default 7)")
    args = ap.parse_args()

    if not LOG_PATH.exists():
        print(f"No log at {LOG_PATH}; nothing to summarize.")
        return 1

    text = LOG_PATH.read_text(encoding="utf-8")
    cutoff = date.today() - timedelta(days=args.days)

    sections: list[tuple[str, str]] = []
    splits = list(DATE_HEADER_RE.finditer(text))
    for i, m in enumerate(splits):
        d = m.group(1)
        try:
            d_obj = date.fromisoformat(d)
        except ValueError:
            continue
        if d_obj < cutoff:
            continue
        start = m.end()
        end = splits[i + 1].start() if i + 1 < len(splits) else len(text)
        sections.append((d, text[start:end].strip()))

    if not sections:
        print(f"No log entries since {cutoff}.")
        return 0

    print(f"# Suggested hot.md refresh (covering {cutoff} to {date.today()})\n")
    print("## Recent activity\n")
    for d, body in sections:
        print(f"### {d}\n{body}\n")

    print("\n---\n")
    print(f"## Apply manually:\n")
    print(f"1. Open 00-system/hot.md")
    print(f"2. Replace the 'Project status' / 'Recently landed' / 'Open questions' sections with curated content from above")
    print(f"3. Bump `updated:` to {date.today()}")
    print(f"4. Append a CLOSE line to 07-logs/log.md")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
