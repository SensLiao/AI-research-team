from __future__ import annotations

import pytest

from research_agent_teams.operate.artifacts import envelope
from research_agent_teams.tools.research_delivery_boundary import (
    derive_research_delivery_boundary,
)
from research_agent_teams.tools.validate_artifact import validate_artifact


SHA_A = "sha256:" + "a" * 64
SHA_B = "sha256:" + "b" * 64
SHA_C = "sha256:" + "c" * 64


def _reviews(with_blocker: bool = False) -> list[dict]:
    blockers = []
    if with_blocker:
        blockers = [{
            "blocker_id": "closest-paper-fulltext",
            "kind": "MISSING_FULLTEXT",
            "description": "The closest prior paper is available as metadata only.",
            "evidence_refs": ["doi:10.1/closest"],
            "required_input": "Hash-pinned full text and method/result loci for the closest paper.",
        }]
    return [
        {"review_id": "method-review", "external_blockers": blockers},
        {"review_id": "implementation-review", "external_blockers": []},
        {"review_id": "evidence-review", "external_blockers": []},
    ]


def _chair(with_blocker: bool = False) -> dict:
    blockers = []
    if with_blocker:
        blockers = [{
            "blocker_id": "chair-closest-paper-fulltext",
            "kind": "MISSING_FULLTEXT",
            "description": "Closest-paper full text remains unavailable.",
            "source_blockers": [{
                "review_id": "method-review",
                "blocker_id": "closest-paper-fulltext",
            }],
            "required_input": "Hash-pinned full text and method/result loci for the closest paper.",
        }]
    return {
        "reviewed_artifact_ref": "inbox/DISCOVER.landscape-mapper.bundle.json",
        "reviewed_artifact_sha256": SHA_A,
        "disposition": (
            "CONTENT_CONVERGED_WITH_EXTERNAL_BLOCKERS" if blockers else "CONTENT_CONVERGED"
        ),
        "external_blockers": blockers,
    }


def _derive(**overrides) -> dict:
    inputs = {
        "reviewed_artifact_ref": "inbox/DISCOVER.landscape-mapper.bundle.json",
        "reviewed_artifact_sha256": SHA_A,
        "convergence_artifact_ref": "evidence/DISCOVER/research-convergence-verdict.artifact.json",
        "convergence_artifact_sha256": SHA_B,
        "convergence_verdict": _chair(),
        "source_reviews": _reviews(),
        "evidence_gate": "PASS",
        "citation_gate": "PASS",
        "citation_attribution_gate": "PASS",
        "existence_gate": "PASS",
    }
    inputs.update(overrides)
    return derive_research_delivery_boundary(**inputs)


def test_no_independent_hash_bound_novelty_gate_means_unverified():
    boundary = _derive()

    assert boundary["content_convergence"] == "CONTENT_CONVERGED"
    assert boundary["novelty"]["status"] == "UNVERIFIED"
    assert boundary["claim_boundaries"]["novelty_claim_allowed"] is False
    assert "NO_INDEPENDENT_HASH_BOUND_NOVELTY_GATE_PASS" in boundary["novelty"]["reasons"]
    assert validate_artifact(envelope(
        "research_delivery_boundary", "deterministic-research-delivery-boundary",
        boundary, "2026-08-13T00:00:00Z",
    )) == []


def test_exact_independent_hash_bound_gate_is_required_for_verified_pass():
    gate = {
        "gate": "PASS",
        "independent_of_author": True,
        "reviewed_artifact_ref": "inbox/DISCOVER.landscape-mapper.bundle.json",
        "reviewed_artifact_sha256": SHA_A,
    }
    boundary = _derive(
        novelty_gate=gate,
        novelty_gate_artifact_ref="evidence/DISCOVER/novelty-verification-gate.artifact.json",
        novelty_gate_artifact_sha256=SHA_C,
    )
    assert boundary["novelty"]["status"] == "VERIFIED_PASS"
    assert boundary["claim_boundaries"]["novelty_claim_allowed"] is True

    wrong_hash = _derive(
        novelty_gate={**gate, "reviewed_artifact_sha256": SHA_B},
        novelty_gate_artifact_ref="evidence/DISCOVER/novelty-verification-gate.artifact.json",
        novelty_gate_artifact_sha256=SHA_C,
    )
    assert wrong_hash["novelty"]["status"] == "UNVERIFIED"


def test_external_blocker_preserves_original_fields_and_overrides_novelty_pass():
    gate = {
        "gate": "PASS", "independent_of_author": True,
        "reviewed_artifact_ref": "inbox/DISCOVER.landscape-mapper.bundle.json",
        "reviewed_artifact_sha256": SHA_A,
    }
    boundary = _derive(
        convergence_verdict=_chair(True),
        source_reviews=_reviews(True),
        novelty_gate=gate,
        novelty_gate_artifact_ref="evidence/DISCOVER/novelty-verification-gate.artifact.json",
        novelty_gate_artifact_sha256=SHA_C,
    )

    assert boundary["novelty"]["independent_hash_bound_gate_pass"] is True
    assert boundary["novelty"]["status"] == "UNVERIFIED"
    assert boundary["delivery_status"] == "USABLE_WITH_CAVEATS"
    assert boundary["external_blockers"] == [{
        "blocker_id": "closest-paper-fulltext",
        "source_review_id": "method-review",
        "chair_blocker_id": "chair-closest-paper-fulltext",
        "kind": "MISSING_FULLTEXT",
        "description": "The closest prior paper is available as metadata only.",
        "required_input": "Hash-pinned full text and method/result loci for the closest paper.",
        "evidence_refs": ["doi:10.1/closest"],
    }]


@pytest.mark.parametrize("field,replacement", [
    ("kind", "OTHER"),
    ("required_input", "Rewrite the prose instead."),
])
def test_chair_cannot_rewrite_blocker_kind_or_required_input(field, replacement):
    chair = _chair(True)
    chair["external_blockers"][0][field] = replacement

    with pytest.raises(ValueError, match=f"changed {field}"):
        _derive(convergence_verdict=chair, source_reviews=_reviews(True))


def test_nonpassing_scientific_gate_overrides_otherwise_valid_novelty_pass():
    gate = {
        "gate": "PASS", "independent_of_author": True,
        "reviewed_artifact_ref": "inbox/DISCOVER.landscape-mapper.bundle.json",
        "reviewed_artifact_sha256": SHA_A,
    }
    boundary = _derive(
        evidence_gate="BLOCK",
        novelty_gate=gate,
        novelty_gate_artifact_ref="evidence/DISCOVER/novelty-verification-gate.artifact.json",
        novelty_gate_artifact_sha256=SHA_C,
    )
    assert boundary["novelty"]["status"] == "UNVERIFIED"
    assert "EVIDENCE_GATE_NOT_PASS" in boundary["novelty"]["reasons"]


def test_not_reviewed_content_is_never_plain_usable():
    chair = _chair()
    chair["disposition"] = "NOT_REVIEWED"
    boundary = _derive(convergence_verdict=chair)
    assert boundary["delivery_status"] == "USABLE_WITH_CAVEATS"


def test_delivery_boundary_must_bind_the_same_author_snapshot_as_chair():
    chair = _chair()
    chair["reviewed_artifact_sha256"] = SHA_B
    with pytest.raises(ValueError, match="exactly match the convergence chair binding"):
        _derive(convergence_verdict=chair)


def test_schema_rejects_claimed_verified_novelty_with_a_blocked_scientific_gate():
    boundary = _derive()
    boundary["novelty"] = {
        "status": "VERIFIED_PASS",
        "independent_hash_bound_gate_pass": True,
        "gate_artifact_ref": "evidence/DISCOVER/novelty-gate.artifact.json",
        "gate_artifact_sha256": SHA_C,
        "reasons": [],
    }
    boundary["claim_boundaries"]["novelty_claim_allowed"] = True
    boundary["scientific_gates"]["citation"] = "BLOCK"
    errors = validate_artifact(envelope(
        "research_delivery_boundary", "deterministic-research-delivery-boundary",
        boundary, "2026-08-13T00:00:00Z",
    ))
    assert any("citation" in error for error in errors)
