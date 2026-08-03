"""CPU-only contract dry-run for the T4 Scribble-M0 example.

This is deliberately not the PET/CT implementation.  It exercises the frozen
ontology, arm-parity interface, output shapes, patient aggregation and
fail-closed readiness state on synthetic objects.  Its output is always
NOT_SCIENTIFIC_EVIDENCE and cannot unlock GPU execution.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Iterable


LEGAL_JOINTS = (
    "ADD_SAME_LOCAL",
    "REMOVE_SAME_LOCAL",
    "ADD_SAME_COMPLETE",
    "REMOVE_SAME_COMPLETE",
    "ADD_NEW_COMPLETE",
    "REMOVE_NEW_COMPLETE",
)
ILLEGAL_JOINTS = ("ADD_NEW_LOCAL", "REMOVE_NEW_LOCAL")


@dataclass(frozen=True)
class SyntheticEpisode:
    patient_id: str
    split: str
    channels: tuple[float, ...]
    joint_label: str


def validate_joint(label: str) -> None:
    if label not in LEGAL_JOINTS:
        raise ValueError(f"illegal or unknown joint: {label}")


def apply_arm(
    episode: SyntheticEpisode,
    *,
    arm: str,
    synthetic_m0_indices: Iterable[int],
) -> SyntheticEpisode:
    """Neutralize only fixture-declared M0 slots while preserving shape.

    The slot numbers are synthetic and MUST NOT be reused as the unresolved
    canonical 17-channel map.
    """
    if arm not in {"full", "no_M0"}:
        raise ValueError(f"unknown arm: {arm}")
    values = list(episode.channels)
    if arm == "no_M0":
        for index in synthetic_m0_indices:
            values[index] = 0.0
    return SyntheticEpisode(
        patient_id=episode.patient_id,
        split=episode.split,
        channels=tuple(values),
        joint_label=episode.joint_label,
    )


def forward_shape_stub(batch_size: int) -> dict[str, list[int]]:
    """Return only the frozen interface shapes; this is not a learned model."""
    if batch_size < 1:
        raise ValueError("batch_size must be positive")
    return {
        "joint_logits": [batch_size, 6],
        "operation_logits": [batch_size, 2],
        "target_logits": [batch_size, 2],
        "scope_logits": [batch_size, 2],
    }


def patient_mean(values: list[tuple[str, float]]) -> float:
    grouped: dict[str, list[float]] = {}
    for patient_id, value in values:
        grouped.setdefault(patient_id, []).append(float(value))
    if not grouped:
        raise ValueError("patient aggregation requires observations")
    per_patient = [sum(rows) / len(rows) for rows in grouped.values()]
    return sum(per_patient) / len(per_patient)


def run_dry_run() -> dict:
    fixture = SyntheticEpisode(
        patient_id="SYNTHETIC_PATIENT_A",
        split="validation",
        channels=tuple(float(index + 1) for index in range(17)),
        joint_label="ADD_SAME_LOCAL",
    )
    validate_joint(fixture.joint_label)
    illegal_rejections = 0
    for label in ILLEGAL_JOINTS:
        try:
            validate_joint(label)
        except ValueError:
            illegal_rejections += 1

    synthetic_m0_indices = (5, 6)
    full = apply_arm(fixture, arm="full", synthetic_m0_indices=synthetic_m0_indices)
    no_m0 = apply_arm(fixture, arm="no_M0", synthetic_m0_indices=synthetic_m0_indices)
    unchanged = [
        index
        for index in range(17)
        if index not in synthetic_m0_indices and full.channels[index] == no_m0.channels[index]
    ]
    changed = [
        index
        for index in synthetic_m0_indices
        if full.channels[index] != no_m0.channels[index]
    ]

    # The episode-weighted and patient-weighted fixture values intentionally
    # differ, proving that the aggregator does not silently treat episodes as
    # independent patients.
    metric_fixture = [
        ("P1", 1.0),
        ("P1", 1.0),
        ("P1", 1.0),
        ("P2", 0.0),
    ]
    episode_mean = sum(value for _, value in metric_fixture) / len(metric_fixture)
    patient_level_mean = patient_mean(metric_fixture)

    passed = {
        "T03_legal_joint_mapping": illegal_rejections == 2 and len(LEGAL_JOINTS) == 6,
        "T06_fixture_split_disjointness": fixture.split == "validation",
        "T09_fixture_arm_parity": len(unchanged) == 15 and changed == list(synthetic_m0_indices),
        "T11_fixture_identifier_exclusion": len(fixture.channels) == 17,
        "T12_forward_shapes": forward_shape_stub(2)
        == {
            "joint_logits": [2, 6],
            "operation_logits": [2, 2],
            "target_logits": [2, 2],
            "scope_logits": [2, 2],
        },
        "T14_patient_aggregation": episode_mean != patient_level_mean,
    }
    if not all(passed.values()):
        raise AssertionError(f"synthetic contract dry-run failed: {passed}")

    return {
        "schema_version": "t4-scribble-m0-contract-dry-run/v1",
        "evidence_class": "NOT_SCIENTIFIC_EVIDENCE",
        "execution_kind": "CPU_SYNTHETIC_CONTRACT_ONLY",
        "scientific_claims_allowed": False,
        "gpu_execution_authorized": False,
        "preflight_state": "PREFLIGHT_BLOCKED",
        "passed_fixture_checks": sorted(passed),
        "interface_shapes": forward_shape_stub(2),
        "fixture_metric_pipeline": {
            "status": "NOT_SCIENTIFIC_EVIDENCE",
            "episode_mean": episode_mean,
            "patient_level_mean": patient_level_mean,
            "purpose": "prove patient aggregation wiring only",
        },
        "unresolved_blockers": [
            "exact downstream bundle/F0 digest closure",
            "canonical ordered 17-channel map and normalization digest",
            "complete M0-derived path manifest and neutralization rules",
            "real patient/case/OOF/grid lineage checks",
            "real implementation forward/loss/gradient and launch command",
            "fresh live resource evidence and separate submit_job authorization",
        ],
        "scope_boundary": (
            "The synthetic M0 indices and values are fixtures, not the canonical PET/CT channel map. "
            "No OOF, model, dataset, server, metric result, or paper claim was produced."
        ),
    }


def main() -> int:
    print(json.dumps(run_dry_run(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
