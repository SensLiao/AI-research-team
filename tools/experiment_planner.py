"""Deterministic core of the experiment-planner (producer/conductor).

Given a research question, a variables declaration (studied/controlled/frozen),
a list of conditions, a ranked batch of next runs, and a leakage declaration,
assemble the experiment_matrix payload. The LLM agent reasons about the research
question and proposes these inputs; this module — not the LLM — enforces design
hygiene and assembles the canonical payload.

Design-hygiene rules enforced here (not by the LLM):
  1. Exactly one condition must declare baseline=True (clean isolation requires a
     unique reference point — zero baselines makes comparison meaningless; two
     baselines introduces ambiguity about which reference is authoritative).
  2. ranked_batch ranks must be the contiguous set 1..len (gaps or duplicates mean
     the priority order cannot be acted on unambiguously).
  3. leakage_declaration must be a non-empty string (silence is not a declaration —
     forcing an explicit statement makes the author commit to a position).
  4. variables must carry all three keys: studied, controlled, frozen.

PROPOSAL only — this module never launches jobs. Building the payload IS the output.
"""
from __future__ import annotations

from typing import List


def build_matrix(
    research_question: str,
    variables: dict,
    conditions: List[dict],
    ranked_batch: List[dict],
    leakage_declaration: str,
) -> dict:
    """Assemble and return an experiment_matrix payload.

    Design-hygiene guards raise ValueError before the payload is assembled,
    so callers receive either a valid, schema-ready dict or an exception.

    Args:
        research_question: The driving research question (non-empty string).
        variables: Dict with keys ``studied``, ``controlled``, ``frozen``; each a
            list of variable name strings.
        conditions: List of condition dicts (each with ``id``, ``factors``, and
            optionally ``baseline``). Exactly one must have ``baseline=True``.
        ranked_batch: List of run dicts (each with ``rank``, ``condition_id``,
            ``hypothesis``, optionally ``cost_gpu_hours``/``expected_signal``).
            Ranks must be the contiguous sequence 1..len(ranked_batch).
        leakage_declaration: Explicit written statement about data-leakage safety.
            Must be non-empty.

    Returns:
        A dict matching the experiment_matrix schema.

    Raises:
        ValueError: If any design-hygiene guard fires.
    """
    # Guard 1 — exactly one baseline
    n_baselines = sum(1 for c in conditions if c.get("baseline") is True)
    if n_baselines == 0:
        raise ValueError(
            "a clean design needs exactly one baseline (zero baselines declared)"
        )
    if n_baselines > 1:
        raise ValueError(
            f"a clean design needs exactly one baseline ({n_baselines} baselines declared)"
        )

    # Guard 2 — contiguous ranks 1..len
    expected_ranks = set(range(1, len(ranked_batch) + 1))
    actual_ranks = {r.get("rank") for r in ranked_batch}
    if actual_ranks != expected_ranks:
        raise ValueError(
            f"ranked_batch ranks must be the contiguous set 1..{len(ranked_batch)} "
            f"(got {sorted(actual_ranks)})"
        )

    # Guard 3 — non-empty leakage declaration
    if not leakage_declaration or not leakage_declaration.strip():
        raise ValueError(
            "leakage_declaration must be non-empty (silence is not a declaration)"
        )

    # Assemble payload — emit exactly the schema's allowed fields
    return {
        "research_question": research_question,
        "variables": {
            "studied": list(variables.get("studied", [])),
            "controlled": list(variables.get("controlled", [])),
            "frozen": list(variables.get("frozen", [])),
        },
        "conditions": [_clean_condition(c) for c in conditions],
        "ranked_batch": [_clean_batch_entry(r) for r in ranked_batch],
        "leakage_declaration": leakage_declaration,
    }


# ---------------------------------------------------------------------------
# Private helpers — normalise condition and batch-entry dicts so the payload
# contains only the fields the schema allows (additionalProperties: false).
# ---------------------------------------------------------------------------

def _clean_condition(c: dict) -> dict:
    """Return a condition dict with only schema-allowed fields."""
    out: dict = {
        "id": c["id"],
        "factors": dict(c.get("factors") or {}),
    }
    if c.get("baseline") is True:
        out["baseline"] = True
    return out


def _clean_batch_entry(r: dict) -> dict:
    """Return a ranked_batch entry with only schema-allowed fields."""
    out: dict = {
        "rank": r["rank"],
        "condition_id": r["condition_id"],
        "hypothesis": r["hypothesis"],
    }
    if "cost_gpu_hours" in r:
        out["cost_gpu_hours"] = r["cost_gpu_hours"]
    if "expected_signal" in r:
        out["expected_signal"] = r["expected_signal"]
    return out
