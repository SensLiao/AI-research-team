"""Stage-aware director-gate policy shared by the engine and operate spine.

``gate_level`` says whether a run needs human sign-off.  It does not by itself
say which checkpoint is the decision boundary.  Older frozen task frames
predate that distinction, so they retain the conservative legacy behaviour: a
sign-off at every driven stage.
"""
from __future__ import annotations

from typing import Mapping


def director_gate_required(payload: Mapping[str, object], stage: str) -> bool:
    """Return whether ``stage`` is the configured human decision boundary.

    A missing ``director_gate_stages`` field is intentionally fail-closed for
    legacy frames: historical high-stakes runs retain their former every-stage
    sign-off policy rather than being silently relaxed.
    """
    if payload.get("gate_level") != "director_signoff":
        return False
    configured = payload.get("director_gate_stages")
    if configured is None:
        return True
    return stage in configured
