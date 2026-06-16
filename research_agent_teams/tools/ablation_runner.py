"""Deterministic core of the ablation-runner (EXECUTE stage, producer).

Builds a run_record payload that captures one run's provenance (config hash,
data hash, git SHA, seed) and any provisional metrics.

Hard ceiling: a runner NEVER freezes a result.  Status may only be "planned"
or "provisional".  Raising ValueError on any other value is the mechanical
enforcement — the LLM agent calls this, the ceiling is not a vibe.
"""
from __future__ import annotations

from typing import Optional

_ALLOWED_STATUSES = {"planned", "provisional"}


def build_run_record(
    condition_id: str,
    config_hash: str,
    status: str = "planned",
    metrics: Optional[dict] = None,
    data_hash: Optional[str] = None,
    git_sha: Optional[str] = None,
    seed: Optional[int] = None,
    notes: Optional[str] = None,
) -> dict:
    """Build a run_record payload (validates against run_record.schema.json).

    Parameters
    ----------
    condition_id:
        Identifier for the ablation condition being run.
    config_hash:
        Hash of the config file / hyper-parameter snapshot used for this run.
        Required by the schema; must be a non-empty string.
    status:
        "planned" (queued, not yet executed) or "provisional" (executed but not
        yet frozen by an adversarial reviewer + human sign-off).
        Any other value raises ValueError — the runner ceiling is enforced here.
    metrics:
        Key/value pairs of metrics recorded during the run.  Defaults to {}.
    data_hash:
        Optional hash of the dataset version used (None when not yet known).
    git_sha:
        Optional Git commit SHA at run time (None when not captured).
    seed:
        Optional random seed used for reproducibility (None when not set).
    notes:
        Optional free-text note.  Key is OMITTED entirely when None to satisfy
        the schema's additionalProperties:false contract.

    Returns
    -------
    dict
        A run_record payload ready to be validated and written as an artifact.

    Raises
    ------
    ValueError
        When *status* is not in {"planned", "provisional"} — frozen / approved /
        etc. are forbidden at the runner stage.
    """
    if status not in _ALLOWED_STATUSES:
        raise ValueError(
            f"ablation-runner ceiling violated: status={status!r} is not allowed. "
            f"A runner may only emit {sorted(_ALLOWED_STATUSES)}. "
            "Freezing a result is the job of the adversarial-reviewer + human sign-off."
        )

    provenance: dict = {
        "config_hash": config_hash,
        "data_hash": data_hash,
        "git_sha": git_sha,
        "seed": seed,
    }

    payload: dict = {
        "condition_id": condition_id,
        "status": status,
        "provenance": provenance,
        "metrics": metrics if metrics is not None else {},
    }

    # Only include "notes" when provided — schema additionalProperties:false
    # means a null "notes" key would still pass (the field allows string), but
    # omitting it entirely is cleaner and consistent with the alignment_checker
    # paradigm of "emit exactly what the schema needs".
    if notes is not None:
        payload["notes"] = notes

    return payload
