"""Deterministic core of the protocol-compiler.

Given an experiment_matrix (the conditions x factors grid produced by experiment-planner)
plus an optional shared config dict, compile a concrete, runnable per-condition config list
so coders never have to guess from prose.

Design rules:
  - Pure functions over plain dicts; no I/O, no LLM.
  - Per-condition factors OVERRIDE shared on key collision — the divergence is explicit.
  - Input dicts are never mutated.
  - build_protocol is the thin builder that wraps compile_protocol with a named-arg envelope.
"""
from __future__ import annotations

from typing import Optional


def compile_protocol(
    matrix: dict,
    from_matrix_ref: str,
    shared: Optional[dict] = None,
    seed: Optional[int] = None,
) -> dict:
    """Compile an experiment_matrix into a protocol_spec payload.

    Args:
        matrix:          An experiment_matrix dict (must contain a "conditions" list).
        from_matrix_ref: Human-readable reference to the source matrix artifact
                         (e.g. a path or artifact ID).
        shared:          Canonical config shared across ALL conditions.  Defaults to {}.
                         Per-condition factors override these on key collision.
        seed:            Optional global seed carried into every per-condition config entry.

    Returns:
        A protocol_spec dict that satisfies protocol_spec.schema.json:
        {
            "from_matrix_ref": str,
            "shared": dict,
            "configs": [{"condition_id": str, "config": dict, "seed": int|None}, ...],
        }
    """
    resolved_shared: dict = dict(shared) if shared else {}

    configs = []
    for condition in matrix["conditions"]:
        # Merge: shared base, then condition factors overwrite (factors win — explicit divergence).
        merged_config: dict = {**resolved_shared, **condition["factors"]}
        configs.append(
            {
                "condition_id": condition["id"],
                "config": merged_config,
                "seed": seed,
            }
        )

    return {
        "from_matrix_ref": from_matrix_ref,
        "shared": resolved_shared,
        "configs": configs,
    }
