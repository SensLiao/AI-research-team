"""Deterministic validator for unified_config artifacts.

Raises ValueError when a per-condition divergence has an empty or missing
justification. Config divergences without justifications are un-reviewable:
anyone reading the config cannot tell whether the difference was intentional
or an oversight.

Profile-driven where applicable; always-on structural checks run regardless.
"""
from __future__ import annotations

from typing import List, Optional, Tuple


def check_divergences(unified_config: dict) -> List[Tuple[str, str]]:
    """Return a list of (condition_id, key) pairs where justification is empty/missing.

    Args:
        unified_config: A dict conforming to unified_config.schema.json.

    Returns:
        List of (condition_id, divergence_key) tuples that violate the
        non-empty-justification requirement. Empty list = all clean.
    """
    bad: List[Tuple[str, str]] = []
    for condition in (unified_config.get("conditions") or []):
        cid = condition.get("condition_id") or "<unknown>"
        for div in (condition.get("divergences") or []):
            key = div.get("key") or "<unknown_key>"
            justification = div.get("justification")
            if not justification or not isinstance(justification, str) or not justification.strip():
                bad.append((cid, key))
    return bad


def validate_config(unified_config: dict, profile: Optional[dict] = None) -> None:
    """Full validation of a unified_config against its structural contract.

    Checks:
    1. Structural completeness (conditions array present, each has condition_id).
    2. Every divergence has a non-empty justification (the hard rule).

    Profile is accepted for future extensibility but is not currently required.

    Args:
        unified_config: A dict conforming to unified_config.schema.json.
        profile: Optional domain profile dict (reserved for future use).

    Raises:
        ValueError: If any structural or justification violation is found.
    """
    if not isinstance(unified_config, dict):
        raise ValueError("unified_config must be a dict")

    conditions = unified_config.get("conditions")
    if conditions is None:
        raise ValueError("unified_config.conditions is missing")
    if not isinstance(conditions, list):
        raise ValueError("unified_config.conditions must be a list")

    for i, c in enumerate(conditions):
        cid = c.get("condition_id")
        if not cid or not isinstance(cid, str) or not cid.strip():
            raise ValueError(f"unified_config.conditions[{i}].condition_id is missing or empty")

        for j, div in enumerate(c.get("divergences") or []):
            key = div.get("key")
            if not key or not isinstance(key, str) or not key.strip():
                raise ValueError(
                    f"conditions[{i}].divergences[{j}].key is missing or empty"
                )

    # Hard rule: every divergence needs a non-empty justification
    bad = check_divergences(unified_config)
    if bad:
        details = "; ".join(
            f"condition={cid!r} key={key!r}" for cid, key in bad
        )
        raise ValueError(
            f"unified_config has divergences with empty/missing justification: {details}. "
            "Every per-condition divergence from shared_config must be justified."
        )
