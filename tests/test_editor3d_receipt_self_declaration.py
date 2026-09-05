"""训练回执自我声明必须从真实配置推导（3D editor fixed-state receipt guard）.

Guards the fix in the Honor-degree experiment repo
(`scripts/common/petct_editor3d_config.py` + `petct_editor3d_epoch.py`):
the fixed-state training receipt's ``execution_scope`` block
(``roll_in_enabled`` / ``simulation_mix_enabled`` /
``five_round_training_loss_enabled`` / ``inactive_config_sections``) used to be
hard-coded string constants.  It must now be derived from the live config
object, so flipping the config flips the receipt, and the audited
never-read loss keys (residual_bce_weight, residual_dice_weight,
monotonic_penalty_enabled, boundary_loss_enabled) enter the derived inactive
list instead of a hand-written one.

The derivation module is torch-free, so this test loads it standalone via
importlib and skips cleanly on machines without the experiment repo.
"""
from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path

import pytest

_HONOR_PROJECT = Path(
    r"C:\Users\廖神\Desktop\Honor degree\projects\petct_textual_intent"
)
_CONFIG_MODULE_PATH = _HONOR_PROJECT / "scripts" / "common" / "petct_editor3d_config.py"
_EPOCH_MODULE_PATH = _HONOR_PROJECT / "scripts" / "common" / "petct_editor3d_epoch.py"
_EFFECT_CONFIG_PATH = _HONOR_PROJECT / "configs" / "editor3d" / "a_plus_stunet_b_effect.json"

pytestmark = pytest.mark.skipif(
    not (_CONFIG_MODULE_PATH.is_file() and _EFFECT_CONFIG_PATH.is_file()),
    reason="Honor-degree petct_textual_intent repo is not present on this machine",
)

_AUDITED_NEVER_READ_LOSS_KEYS = (
    "loss.residual_bce_weight",
    "loss.residual_dice_weight",
    "loss.monotonic_penalty_enabled",
    "loss.boundary_loss_enabled",
)


def _load_derivation_module():
    spec = importlib.util.spec_from_file_location(
        "petct_editor3d_config_receipt_guard", _CONFIG_MODULE_PATH
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _production_config() -> dict:
    return json.loads(_EFFECT_CONFIG_PATH.read_text(encoding="utf-8"))


def test_baseline_scope_matches_run_and_derives_unread_keys():
    module = _load_derivation_module()
    scope = module.derive_fixed_state_execution_scope(_production_config())
    # The fixed-state Phase A run really does none of these; exact bools.
    assert scope["roll_in_enabled"] is False
    assert scope["simulation_mix_enabled"] is False
    assert scope["five_round_training_loss_enabled"] is False
    inactive = scope["inactive_config_sections"]
    # The previously hand-written three entries are still derived...
    assert "execution.roll_in" in inactive
    assert "execution.simulation_mix" in inactive
    assert "loss.round_weights" in inactive
    # ...and the audited never-read config keys join them mechanically.
    for key in _AUDITED_NEVER_READ_LOSS_KEYS:
        assert key in inactive
    # Consumed keys must never be reported inactive.
    assert "loss.lambda_full" not in inactive
    assert "loss.lambda_auth" not in inactive


def test_flipping_config_flips_derived_receipt_values():
    module = _load_derivation_module()
    base = _production_config()

    flipped = copy.deepcopy(base)
    flipped["execution"]["roll_in"]["enabled"] = True
    scope = module.derive_fixed_state_execution_scope(flipped)
    assert scope["roll_in_enabled"] is True
    assert "execution.roll_in" not in scope["inactive_config_sections"]
    # direct_loss_every_round is already true in the section, so enabling
    # roll-in also enables the five-round training loss and consumes
    # loss.round_weights.
    assert scope["five_round_training_loss_enabled"] is True
    assert "loss.round_weights" not in scope["inactive_config_sections"]

    flipped = copy.deepcopy(base)
    flipped["execution"]["simulation_mix"]["enabled"] = True
    scope = module.derive_fixed_state_execution_scope(flipped)
    assert scope["simulation_mix_enabled"] is True
    assert "execution.simulation_mix" not in scope["inactive_config_sections"]

    # Removing a declared-but-never-read key removes it from the derived list:
    # the list tracks the config instead of a constant.
    flipped = copy.deepcopy(base)
    del flipped["loss"]["residual_bce_weight"]
    scope = module.derive_fixed_state_execution_scope(flipped)
    assert "loss.residual_bce_weight" not in scope["inactive_config_sections"]

    # Dropping a deferred section drops its inactive entry too.
    flipped = copy.deepcopy(base)
    del flipped["execution"]["roll_in"]
    scope = module.derive_fixed_state_execution_scope(flipped)
    assert scope["roll_in_enabled"] is False
    assert "execution.roll_in" not in scope["inactive_config_sections"]


def test_epoch_receipt_wires_derivation_and_drops_hardcoded_constants():
    source = _EPOCH_MODULE_PATH.read_text(encoding="utf-8")
    assert "derive_fixed_state_execution_scope(config)" in source
    assert '"roll_in_enabled": False' not in source
    assert '"inactive_config_sections": ["execution.roll_in"' not in source
