"""Shared delivery statuses for researcher-facing outputs.

Daily delivery and vault admission are deliberately different boundaries.  A
researcher may read and continue from an incomplete report; promotion still
requires the strict evidence and provenance gates.
"""
from __future__ import annotations


USABLE = "USABLE"
USABLE_WITH_CAVEATS = "USABLE_WITH_CAVEATS"
NEEDS_SUPPLEMENT = "NEEDS_SUPPLEMENT"
BLOCK = "BLOCK"

DELIVERY_STATUSES = {
    USABLE,
    USABLE_WITH_CAVEATS,
    NEEDS_SUPPLEMENT,
    BLOCK,
}


def delivery_status(*, hard_block: bool = False, supplements: bool = False,
                    advisories: bool = False) -> str:
    """Return the strongest applicable delivery status."""
    if hard_block:
        return BLOCK
    if supplements:
        return NEEDS_SUPPLEMENT
    if advisories:
        return USABLE_WITH_CAVEATS
    return USABLE


__all__ = [
    "BLOCK",
    "DELIVERY_STATUSES",
    "NEEDS_SUPPLEMENT",
    "USABLE",
    "USABLE_WITH_CAVEATS",
    "delivery_status",
]
