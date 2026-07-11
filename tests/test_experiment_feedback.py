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
VALIDITY = {
    "implementation_valid": True,
    "data_valid": True,
    "evaluation_valid": True,
    "protocol_valid": True,
    "statistics_valid": True,
}
HASH_A = "sha256:" + "a" * 64
HASH_B = "sha256:" + "b" * 64
DIAGNOSTIC = {"artifact_ref": "execution-results/diag/result.json", "sha256": HASH_A}
REPLICATION = {"artifact_ref": "execution-results/repl/result.json", "sha256": HASH_B}
VERIFIED_BINDINGS = {
    DIAGNOSTIC["artifact_ref"]: {
        "sha256": HASH_A,
        "role": "diagnostic_intervention",
        "job_id": "diag-job",
        "exit_status": 0,
    },
    REPLICATION["artifact_ref"]: {
        "sha256": HASH_B,
        "role": "replication_evidence",
        "job_id": "repl-job",
        "exit_status": 0,
    },
}


def test_routing_rule():
    assert suggest_next_action("improved", "hypothesis") == "stop"
    assert suggest_next_action("regressed", "hypothesis") == "revise_hypothesis"
    assert suggest_next_action("failed", "implementation") == "fix_implementation"
    assert suggest_next_action("inconclusive", "environment") == "fix_environment"
    assert suggest_next_action("failed", "data") == "fix_data"
    assert suggest_next_action("inconclusive", "statistics") == "increase_precision"
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
        metrics_delta=[{"name": "dice", "before": 0.81, "after": 0.74}],
        attribution_state="intervention_confirmed",
        validity=VALIDITY,
        counterfactual_check="supports",
        replication_status="reproduced_once",
        diagnostic_intervention=DIAGNOSTIC,
        replication_artifacts=[REPLICATION],
        verified_execution_bindings=VERIFIED_BINDINGS)
    assert fb["next_action_hint"] == "fix_implementation"      # derived from attribution
    art = envelope("experiment_feedback", "result-analyzer", fb, TS)
    assert validate_artifact(art) == []


def test_builder_fail_loud():
    with pytest.raises(ValueError):
        build_experiment_feedback("", "failed", "unknown", "s", ["e"],
                                  hypothesis_ref="H1", validity=VALIDITY)
    with pytest.raises(ValueError):
        build_experiment_feedback("r", "failed", "unknown", "  ", ["e"],
                                  hypothesis_ref="H1", validity=VALIDITY)
    with pytest.raises(ValueError):
        build_experiment_feedback("r", "failed", "unknown", "s", [],
                                  hypothesis_ref="H1", validity=VALIDITY)
    with pytest.raises(ValueError):
        build_experiment_feedback("r", "failed", "unknown", "s", ["e"],
                                  hypothesis_ref="H1", next_action_hint="reboot", validity=VALIDITY)
    with pytest.raises(ValueError):
        build_experiment_feedback("r", "failed", "unknown", "s", ["e"],
                                  hypothesis_ref="H1", metrics_delta=[{"before": 1}],
                                  validity=VALIDITY)


def test_hypothesis_attribution_requires_valid_pipeline_and_replication():
    with pytest.raises(ValueError, match="hypothesis attribution requires"):
        build_experiment_feedback(
            "r", "regressed", "hypothesis", "s", ["e"], validity=VALIDITY,
            hypothesis_ref="H1", replication_status="reproduced_once")
    invalid = {**VALIDITY, "evaluation_valid": False}
    with pytest.raises(ValueError, match="evaluation_valid"):
        build_experiment_feedback(
            "r", "regressed", "hypothesis", "s", ["e"], validity=invalid,
            hypothesis_ref="H1", replication_status="replicated")
    fb = build_experiment_feedback(
        "r", "regressed", "hypothesis", "replicated falsification", ["e"],
        hypothesis_ref="H1", validity=VALIDITY, replication_status="replicated",
        attribution_state="intervention_confirmed", diagnostic_intervention=DIAGNOSTIC,
        replication_artifacts=[REPLICATION],
        verified_execution_bindings=VERIFIED_BINDINGS)
    assert fb["attribution"] == "hypothesis"


def test_override_hint_is_allowed_but_enum_checked():
    fb = build_experiment_feedback("r", "failed", "implementation", "s", ["e"],
                                   hypothesis_ref="H1", next_action_hint="escalate",
                                   validity=VALIDITY)
    assert fb["next_action_hint"] == "escalate"


def test_self_reported_attribution_upgrade_requires_receipt_bound_artifacts():
    with pytest.raises(ValueError, match="verified diagnostic intervention"):
        build_experiment_feedback(
            "r", "failed", "implementation", "self-reported upgrade", ["e"],
            hypothesis_ref="H1", validity=VALIDITY,
            attribution_state="intervention_confirmed",
            replication_status="not_attempted",
        )
    with pytest.raises(ValueError, match="role"):
        build_experiment_feedback(
            "r", "failed", "implementation", "wrong evidence role", ["e"],
            hypothesis_ref="H1", validity=VALIDITY,
            attribution_state="intervention_confirmed",
            replication_status="replicated",
            diagnostic_intervention=DIAGNOSTIC,
            replication_artifacts=[REPLICATION],
            verified_execution_bindings={
                **VERIFIED_BINDINGS,
                DIAGNOSTIC["artifact_ref"]: {
                    **VERIFIED_BINDINGS[DIAGNOSTIC["artifact_ref"]],
                    "role": "raw_result_rows",
                },
            },
        )
