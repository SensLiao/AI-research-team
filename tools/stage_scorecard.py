"""Deterministic CROSS-STAGE quality-scorecard aggregator for the quality-controller agent.

This is the genuinely-new AGGREGATION layer. Per-stage gate verdicts ALREADY exist elsewhere
(``schemas/analysis_check_verdict.schema.json``, the ``blocking_gates`` in ``orchestrator/graph.yaml``,
``tools/drift_gate.py``). What was missing — and what this module supplies — is the CROSS-STAGE
view that rolls those EXISTING per-stage verdicts up into one scorecard and derives a deterministic
``can_finish``.

Hard boundary (mirrored in agents/quality-controller.md):
  * This is an AGGREGATOR. It READS verdict ``pass`` bits in the existing analysis_check_verdict
    shape ``{"panel_role", "pass", "violations", ...}``. It does NOT invent a new verdict format,
    does NOT re-implement any gate, and does NOT re-run any check.
  * ``can_finish`` is the machine's internal completeness signal — it NEVER overrides the director's
    human gates (``/promote-to-vault``, ``/idea-bet``). Those remain the sole deciders to bet,
    publish, or write the DB.

Determinism: pure functions only — no network, no clock, no randomness, no I/O. The same inputs
always produce byte-identical outputs (sorted, stable ordering throughout).

The three public functions:
  * ``build_stage_scorecard(stage, verdicts)`` — roll a list of per-stage verdicts into one
    stage_scorecard (one dimension_result per verdict; ``stage_pass`` = AND over them).
  * ``build_global_scorecard(run_id, stage_cards)`` — roll the stage cards into the global
    scorecard: map each stage card onto the global quality dimensions, derive each dimension's
    pass bit (AND over the stage cards that bear on it), then derive ``can_finish`` + reasons.
  * ``can_finish_run(global_scorecard)`` — AND over the required dimensions' pass bits.
"""
from __future__ import annotations

from typing import Dict, List, Tuple

# ---------------------------------------------------------------------------
# The six required global quality dimensions (must match
# global_quality_scorecard.schema.json properties.dimensions.required).
# ---------------------------------------------------------------------------
REQUIRED_DIMENSIONS: Tuple[str, ...] = (
    "grounding",
    "novelty",
    "method_completeness",
    "analysis_validity",
    "integrity",
    "review",
)

# Which FSM stages roll up into which global quality dimension. A dimension passes iff EVERY
# mapped stage card that is present passes (AND). A dimension with no present stage cards is
# treated as not-yet-satisfied (pass=False) — you cannot "finish" a dimension nothing has
# established. This map is the only place stage→dimension wiring lives.
_DIMENSION_STAGE_MAP: Dict[str, Tuple[str, ...]] = {
    "grounding": ("DISCOVER",),
    "novelty": ("DISCOVER", "IDEATE"),
    "method_completeness": ("DESIGN", "EXECUTE"),
    "analysis_validity": ("ANALYZE",),
    "integrity": ("EXECUTE", "ANALYZE"),
    "review": ("VERIFY",),
}

_VALID_STAGES: Tuple[str, ...] = (
    "DISCOVER", "IDEATE", "DESIGN", "EXECUTE", "ANALYZE", "VERIFY", "REPORT",
)


def build_stage_scorecard(stage: str, verdicts: List[dict]) -> dict:
    """Roll a list of EXISTING per-stage verdicts into one stage_scorecard.

    Each verdict is read in the existing ``analysis_check_verdict`` shape: its ``pass`` bit is taken
    as-is (it is already derived from ``violations`` by that schema's allOf — we never recompute it),
    and a short dimension name is taken from ``panel_role`` (falling back to ``dimension`` then a
    positional label) so the rolled-up card traces back to the source verdict.

    Args:
        stage: One of the real FSM stages (see graph.yaml). ValueError if unknown.
        verdicts: List of per-stage verdict dicts in the analysis_check_verdict shape. Each must
                  carry a boolean ``pass``. An ``evidence_ref`` is used if present, else a stable
                  pointer is synthesised from the stage + dimension so the anti-slop field is filled.

    Returns:
        A dict conforming to stage_scorecard.schema.json:
        ``{"stage", "dimension_results": [{dimension, pass, evidence_ref}], "stage_pass"}``.
        ``stage_pass`` is the AND over every dimension_result.pass (vacuously True for an empty list).

    Raises:
        ValueError: stage is not a real FSM stage, a verdict is not a dict, or a verdict lacks a
                    boolean ``pass`` (we never guess a pass/fail).
    """
    if stage not in _VALID_STAGES:
        raise ValueError(
            f"build_stage_scorecard: unknown stage {stage!r}; expected one of {list(_VALID_STAGES)}"
        )

    dimension_results: List[dict] = []
    for index, verdict in enumerate(verdicts):
        if not isinstance(verdict, dict):
            raise ValueError(
                f"build_stage_scorecard: verdict at index {index} must be a dict, "
                f"got {type(verdict).__name__!r}"
            )
        if "pass" not in verdict or not isinstance(verdict["pass"], bool):
            raise ValueError(
                f"build_stage_scorecard: verdict at index {index} must carry a boolean 'pass' "
                f"(read from the existing analysis_check_verdict shape — never guessed); "
                f"keys present: {sorted(verdict.keys())}"
            )

        dimension = _verdict_dimension(verdict, stage, index)
        evidence_ref = _verdict_evidence_ref(verdict, stage, dimension)
        dimension_results.append({
            "dimension": dimension,
            "pass": bool(verdict["pass"]),
            "evidence_ref": evidence_ref,
        })

    stage_pass = all(d["pass"] for d in dimension_results)
    return {
        "stage": stage,
        "dimension_results": dimension_results,
        "stage_pass": stage_pass,
    }


def build_global_scorecard(run_id: str, stage_cards: List[dict]) -> dict:
    """Roll a list of stage_scorecards up into the global_quality_scorecard.

    For each of the six REQUIRED_DIMENSIONS, gather the stage cards mapped to it (``_DIMENSION_STAGE_MAP``)
    that are actually present, and derive the dimension's pass bit as the AND over their ``stage_pass``.
    A dimension with NO present stage card is pass=False (nothing has established it yet) and names
    that in its blocking_reasons. ``can_finish`` is then the AND over the six dimension pass bits, and
    the top-level ``blocking_reasons`` names every failing required dimension.

    Args:
        run_id: The run being aggregated (non-empty).
        stage_cards: List of stage_scorecard dicts (each ``{"stage", "dimension_results", "stage_pass"}``).

    Returns:
        A dict conforming to global_quality_scorecard.schema.json.

    Raises:
        ValueError: run_id empty, a stage card is malformed, or a stage card names an unknown stage.
    """
    if not isinstance(run_id, str) or not run_id.strip():
        raise ValueError("build_global_scorecard: run_id must be a non-empty string")

    # Index the present stage cards by stage name; validate shape as we go.
    cards_by_stage: Dict[str, dict] = {}
    normalized_cards: List[dict] = []
    for index, card in enumerate(stage_cards):
        if not isinstance(card, dict):
            raise ValueError(
                f"build_global_scorecard: stage_card at index {index} must be a dict, "
                f"got {type(card).__name__!r}"
            )
        card_stage = card.get("stage")
        if card_stage not in _VALID_STAGES:
            raise ValueError(
                f"build_global_scorecard: stage_card at index {index} names unknown stage "
                f"{card_stage!r}; expected one of {list(_VALID_STAGES)}"
            )
        if not isinstance(card.get("stage_pass"), bool):
            raise ValueError(
                f"build_global_scorecard: stage_card for {card_stage!r} must carry a boolean "
                f"'stage_pass'; keys present: {sorted(card.keys())}"
            )
        # Keep a normalized copy (stable shape) so the embedded array is schema-clean.
        normalized = {
            "stage": card_stage,
            "dimension_results": list(card.get("dimension_results", [])),
            "stage_pass": bool(card["stage_pass"]),
        }
        if "notes" in card:
            normalized["notes"] = card["notes"]
        cards_by_stage[card_stage] = normalized
        normalized_cards.append(normalized)

    dimensions: Dict[str, dict] = {}
    blocking_reasons: List[str] = []

    for dim in REQUIRED_DIMENSIONS:
        mapped_stages = _DIMENSION_STAGE_MAP[dim]
        present = [cards_by_stage[s] for s in mapped_stages if s in cards_by_stage]
        missing = [s for s in mapped_stages if s not in cards_by_stage]

        dim_reasons: List[str] = []
        if not present:
            # No stage card bears on this dimension yet — cannot be satisfied.
            dim_pass = False
            dim_reasons.append(
                f"{dim}: no stage scorecard present for required stage(s) {sorted(mapped_stages)}"
            )
        else:
            dim_pass = all(c["stage_pass"] for c in present)
            if not dim_pass:
                failed = sorted(c["stage"] for c in present if not c["stage_pass"])
                dim_reasons.append(f"{dim}: failing stage(s) {failed}")
            for m in missing:
                dim_reasons.append(f"{dim}: missing stage scorecard for {m}")

        evidence_ref = sorted(c["stage"] for c in present)
        dimensions[dim] = {
            "pass": dim_pass,
            "evidence_ref": evidence_ref,
            "blocking_reasons": dim_reasons,
        }
        if not dim_pass:
            blocking_reasons.append(f"{dim} did not pass")

    can_finish = all(dimensions[d]["pass"] for d in REQUIRED_DIMENSIONS)

    return {
        "run_id": run_id,
        "stage_scorecards": normalized_cards,
        "dimensions": dimensions,
        "can_finish": can_finish,
        "blocking_reasons": blocking_reasons,
    }


def can_finish_run(global_scorecard: dict) -> bool:
    """Return the deterministic AND over the required dimensions' pass bits.

    This is the single source of truth for the boolean: ``can_finish`` is True iff EVERY required
    dimension's ``pass`` is True. It is computed directly from the dimensions (not by trusting the
    stored ``can_finish`` field), so this function can independently re-derive / verify the verdict.

    Args:
        global_scorecard: A global_quality_scorecard dict (must carry a ``dimensions`` object).

    Returns:
        True iff all six required dimensions pass.

    Raises:
        ValueError: the scorecard lacks a ``dimensions`` object, or a required dimension is absent
                    or lacks a boolean ``pass`` (we never assume a missing dimension passed).
    """
    if not isinstance(global_scorecard, dict):
        raise ValueError(
            f"can_finish_run: global_scorecard must be a dict, got {type(global_scorecard).__name__!r}"
        )
    dims = global_scorecard.get("dimensions")
    if not isinstance(dims, dict):
        raise ValueError("can_finish_run: global_scorecard must carry a 'dimensions' object")

    for dim in REQUIRED_DIMENSIONS:
        entry = dims.get(dim)
        if not isinstance(entry, dict) or not isinstance(entry.get("pass"), bool):
            raise ValueError(
                f"can_finish_run: required dimension {dim!r} is absent or lacks a boolean 'pass' "
                f"(a missing required dimension is never assumed to pass)"
            )

    return all(bool(dims[dim]["pass"]) for dim in REQUIRED_DIMENSIONS)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _verdict_dimension(verdict: dict, stage: str, index: int) -> str:
    """Pick a stable dimension name for a per-stage verdict.

    Preference order: explicit ``dimension`` → ``panel_role`` (the analysis_check_verdict
    discriminator) → a positional ``<stage>_check_<index>`` label. Always a non-empty string.
    """
    for key in ("dimension", "panel_role"):
        value = verdict.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return f"{stage.lower()}_check_{index}"


def _verdict_evidence_ref(verdict: dict, stage: str, dimension: str) -> str:
    """Pick a non-empty evidence_ref for a dimension result.

    Uses an explicit ``evidence_ref`` (string, or first element if a list) when present; otherwise
    synthesises a stable pointer from the stage + dimension so the anti-slop field is always filled
    and deterministic.
    """
    ref = verdict.get("evidence_ref")
    if isinstance(ref, str) and ref.strip():
        return ref.strip()
    if isinstance(ref, list):
        for item in ref:
            if isinstance(item, str) and item.strip():
                return item.strip()
    return f"{stage}:{dimension}"
