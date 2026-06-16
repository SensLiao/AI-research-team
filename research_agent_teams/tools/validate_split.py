"""Deterministic validator for split_manifest artifacts.

Raises ValueError when the declared split_unit appears in the profile's
``split_policy.forbidden_split_units`` list (e.g. slice/patch for medical volumes,
token for text corpora). This is a hard pre-condition for dataset-split-planner:
a forbidden split unit causes leakage and must be caught before the plan is accepted.

Profile-driven: the forbidden units come from the domain profile, nothing is hardcoded.
Always-on checks (structural) still run even when no profile is supplied.
"""
from __future__ import annotations

from typing import Optional


def check_split_unit(split_manifest: dict, profile: Optional[dict] = None) -> None:
    """Raise ValueError if split_unit is forbidden by the profile.

    Args:
        split_manifest: A dict conforming to split_manifest.schema.json.
        profile: Optional domain profile dict. When provided, its
                 ``split_policy.forbidden_split_units`` is consulted.

    Raises:
        ValueError: If ``split_unit`` is in the profile's forbidden list,
                    or if ``split_unit`` is missing/empty.
    """
    split_unit = split_manifest.get("split_unit")
    if not split_unit or not isinstance(split_unit, str) or not split_unit.strip():
        raise ValueError(
            "split_manifest.split_unit is missing or empty — a split unit must be declared"
        )

    if profile is None:
        return

    split_policy = (profile.get("split_policy") or {})
    forbidden: list = split_policy.get("forbidden_split_units") or []

    if split_unit in forbidden:
        allowed: list = split_policy.get("allowed_split_units") or []
        raise ValueError(
            f"split_unit={split_unit!r} is forbidden by profile "
            f"{profile.get('profile_id', '<unknown>')!r}: "
            f"forbidden_split_units={forbidden}. "
            f"Use one of the allowed units: {allowed}"
        )


def validate_split(split_manifest: dict, profile: Optional[dict] = None) -> None:
    """Full validation of a split_manifest against a domain profile.

    Validates structural completeness and then checks the split_unit
    against profile constraints. Raises ValueError on any violation.

    Args:
        split_manifest: A dict conforming to split_manifest.schema.json.
        profile: Optional domain profile dict.

    Raises:
        ValueError: On any structural or profile-policy violation.
    """
    # Structural checks (always-on, no profile required)
    if not isinstance(split_manifest, dict):
        raise ValueError("split_manifest must be a dict")

    splits = split_manifest.get("splits")
    if not splits or not isinstance(splits, list) or len(splits) < 2:
        raise ValueError(
            "split_manifest.splits must contain at least 2 splits (e.g. train and test)"
        )

    for i, s in enumerate(splits):
        name = s.get("name")
        fraction = s.get("fraction")
        if not name:
            raise ValueError(f"split[{i}].name is missing or empty")
        if fraction is None or not isinstance(fraction, (int, float)) or isinstance(fraction, bool):
            raise ValueError(f"split[{i}].fraction is missing or non-numeric")
        if not (0 < fraction <= 1):
            raise ValueError(
                f"split[{i}].fraction={fraction!r} is out of range (0, 1]"
            )

    leakage_decl = split_manifest.get("leakage_declaration")
    if not leakage_decl or not isinstance(leakage_decl, str) or not leakage_decl.strip():
        raise ValueError(
            "split_manifest.leakage_declaration is missing or empty — "
            "a written leakage declaration is required"
        )

    # Profile-driven check
    check_split_unit(split_manifest, profile)
