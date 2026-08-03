"""Director reporting — the universal "plan first, report after" layer.

Director lock (2026-08-01): every task gets TWO plain-Chinese products, and the
director never has to read JSON, hashes, or acronyms to know what happened.

- BEFORE the work: :func:`brief` scans the knowledge base, the registered
  projects, the recent runs and the available compute, then renders the plan
  card the director approves.
- AFTER the work: :func:`report` reads the finished run and renders the
  progress report — what came out, how far it got, what can and cannot be
  claimed, and which decision is the director's.

Both halves are deterministic and read-only.  They propose and describe; they
never start a run, never write the knowledge base, and never decide anything
that belongs to a human gate.
"""
from __future__ import annotations

from .briefing import brief, build_briefing, render_briefing
from .plain_words import explain, gate_label, say
from .progress import build_progress, render_progress, report
from .scan import scan_all

__all__ = [
    "brief",
    "build_briefing",
    "build_progress",
    "explain",
    "gate_label",
    "render_briefing",
    "render_progress",
    "report",
    "say",
    "scan_all",
]
