"""Per-mode operate recipes.

A recipe declares, for each stage of a mode: the LLM worker(s) to dispatch (the reading / reasoning
WORK that only a sub-agent can do, with a ready-to-use prompt) and the deterministic producers/gates
to run as plain Python (scoring, classification, hard gates). The spine drives the boundaries; the
recipe fills the WORK slot. `new_direction` is the first wired mode (the one walked in the first-run
demo); add a module here to wire another mode without touching the spine.
"""
from . import new_direction

REGISTRY = {
    "new_direction": new_direction,
}

__all__ = ["REGISTRY", "new_direction"]
