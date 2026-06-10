"""experiment_feedback — RD-Agent attribution routing + schema conformance (wave 1)."""
from __future__ import annotations

import pytest

from research_agent_teams.operate.artifacts import envelope
from research_agent_teams.tools.experiment_feedback import (
    build_experiment_feedback,
    suggest_next_action,
)
from research_agent_teams.tools.validate_artifact import validate_artifact

TS = "2026-06-10T12:00:00Z"


def test_routing_rule():
    assert suggest_next_action("improved", "hypothesis") == "stop"
    assert suggest_next_action("regressed", "hypothesis") == "revise_hypothesis"
    assert suggest_next_action("failed", "implementation") == "fix_implementation"
    assert suggest_next_action("inconclusive", "environment") == "fix_environment"
    assert suggest_next_action("failed", "unknown") == "escalate"
    with pytest.raises(ValueError):
        suggest_next_action("exploded", "hypothesis")
    with pytest.raises(ValueError):
        suggest_next_action("failed", "gremlins")


def test_builder_validates_and_passes_schema():
    fb = build_experiment_feedback(
        "runs/r1/evidence/ANALYZE/result-summary.artifact.json", "regressed", "implementation",
        "Loss spiked after epoch 3; gradient clipping missing vs the protocol.",
        ["result-summary.artifact.json", "journal-entry-3.artifact.json"],
        hypothesis_ref="IH2",
        metrics_delta=[{"name": "dice", "before": 0.81, "after": 0.74}])
    assert fb["next_action_hint"] == "fix_implementation"      # derived from attribution
    art = envelope("experiment_feedback", "result-analyzer", fb, TS)
    assert validate_artifact(art) == []


def test_builder_fail_loud():
    with pytest.raises(ValueError):
        build_experiment_feedback("", "failed", "unknown", "s", ["e"])
    with pytest.raises(ValueError):
        build_experiment_feedback("r", "failed", "unknown", "  ", ["e"])
    with pytest.raises(ValueError):
        build_experiment_feedback("r", "failed", "unknown", "s", [])
    with pytest.raises(ValueError):
        build_experiment_feedback("r", "failed", "unknown", "s", ["e"], next_action_hint="reboot")
    with pytest.raises(ValueError):
        build_experiment_feedback("r", "failed", "unknown", "s", ["e"],
                                  metrics_delta=[{"before": 1}])


def test_override_hint_is_allowed_but_enum_checked():
    fb = build_experiment_feedback("r", "failed", "implementation", "s", ["e"],
                                   next_action_hint="escalate")
    assert fb["next_action_hint"] == "escalate"
