"""Tests for validate_config.py — deterministic validator for unified_config artifacts.

Verifies:
- Valid configs with non-empty justifications pass without raising.
- Empty or missing justification in any divergence raises ValueError.
- Structural violations (missing conditions, empty condition_id) raise ValueError.
"""
from __future__ import annotations

import pytest

from research_agent_teams.tools.validate_config import check_divergences, validate_config


# ---- helpers ------------------------------------------------------------------

def _config(divergences_by_cond: dict | None = None) -> dict:
    """Build a minimal unified_config dict.

    Args:
        divergences_by_cond: {condition_id: [(key, value, justification), ...]}
    """
    conditions = []
    for cid, divs in (divergences_by_cond or {}).items():
        div_list = [
            {"key": k, "value": v, "justification": j}
            for k, v, j in divs
        ]
        conditions.append({"condition_id": cid, "divergences": div_list})

    if not conditions:
        conditions = [
            {"condition_id": "c0", "divergences": []},
            {"condition_id": "c1", "divergences": []},
        ]

    return {
        "shared_config": {"lr": 1e-4, "epochs": 50},
        "conditions": conditions,
    }


def _good_config() -> dict:
    return _config({
        "c0": [],
        "c1": [("adapter", "lora", "studying effect of LoRA adapter; this is the studied variable")],
    })


# ---- happy-path tests ---------------------------------------------------------

def test_clean_config_passes():
    """A config with all non-empty justifications should not raise."""
    validate_config(_good_config())


def test_no_divergences_passes():
    """A config where all conditions have empty divergences lists is fine."""
    validate_config(_config())


def test_multiple_conditions_all_justified_passes():
    """Multiple conditions each with justified divergences — should not raise."""
    c = _config({
        "c0": [],
        "c1": [("adapter", "lora", "studying LoRA")],
        "c2": [("epochs", 100, "double epochs to match param count")],
    })
    validate_config(c)


# ---- empty/missing justification raises ---------------------------------------

def test_empty_justification_raises():
    """An empty string justification must raise ValueError."""
    c = _config({"c1": [("adapter", "lora", "")]})
    with pytest.raises(ValueError, match="justification"):
        validate_config(c)


def test_whitespace_only_justification_raises():
    """A whitespace-only justification must raise ValueError."""
    c = _config({"c1": [("adapter", "lora", "   ")]})
    with pytest.raises(ValueError, match="justification"):
        validate_config(c)


def test_missing_justification_key_raises():
    """A divergence missing the justification key entirely must raise ValueError."""
    c = {
        "shared_config": {},
        "conditions": [
            {
                "condition_id": "c1",
                "divergences": [{"key": "adapter", "value": "lora"}],  # no justification key
            }
        ],
    }
    with pytest.raises(ValueError, match="justification"):
        validate_config(c)


def test_multiple_conditions_one_unjustified_raises():
    """Even one condition with an unjustified divergence must raise ValueError."""
    c = _config({
        "c0": [],
        "c1": [("adapter", "lora", "studying LoRA")],
        "c2": [("epochs", 100, "")],  # empty justification
    })
    with pytest.raises(ValueError, match="justification"):
        validate_config(c)


# ---- structural violation tests -----------------------------------------------

def test_missing_conditions_raises():
    """A config missing the conditions key must raise ValueError."""
    c = {"shared_config": {}}
    with pytest.raises(ValueError, match="conditions"):
        validate_config(c)


def test_none_conditions_raises():
    """conditions: null must raise ValueError (None is not a list)."""
    with pytest.raises(ValueError, match="conditions"):
        validate_config({"shared_config": {}, "conditions": None})


def test_empty_condition_id_raises():
    """An empty condition_id must raise ValueError."""
    c = {
        "shared_config": {},
        "conditions": [{"condition_id": "", "divergences": []}],
    }
    with pytest.raises(ValueError, match="condition_id"):
        validate_config(c)


def test_divergence_missing_key_field_raises():
    """A divergence without a key field must raise ValueError."""
    c = {
        "shared_config": {},
        "conditions": [
            {
                "condition_id": "c1",
                "divergences": [{"value": "lora", "justification": "reason"}],
            }
        ],
    }
    with pytest.raises(ValueError, match="key"):
        validate_config(c)


# ---- check_divergences unit tests ---------------------------------------------

def test_check_divergences_returns_empty_for_clean():
    """check_divergences returns [] for a config with all non-empty justifications."""
    assert check_divergences(_good_config()) == []


def test_check_divergences_returns_violations_for_empty_justification():
    """check_divergences returns [(cid, key)] for each empty justification."""
    c = _config({"c1": [("adapter", "lora", "")]})
    bad = check_divergences(c)
    assert len(bad) == 1
    assert bad[0] == ("c1", "adapter")


def test_check_divergences_catches_multiple_bad_entries():
    """Multiple empty justifications are all reported."""
    c = _config({
        "c1": [("adapter", "lora", ""), ("lr", 1e-3, "")],
        "c2": [("epochs", 100, "fine")],
    })
    bad = check_divergences(c)
    assert len(bad) == 2
    assert ("c1", "adapter") in bad
    assert ("c1", "lr") in bad
