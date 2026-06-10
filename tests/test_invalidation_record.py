"""invalidation_record — the contradiction-mining structured landing artifact (wave 1, Graphiti pattern)."""
from __future__ import annotations

from research_agent_teams.operate.artifacts import envelope
from research_agent_teams.tools.validate_artifact import validate_artifact

TS = "2026-06-10T12:00:00Z"

GOOD = {
    "claim_slug": "skeleton-recall-beats-cldice",
    "invalidated_by_slug": "u-mamba2-2025",
    "edge_type": "refutes",
    "invalid_at": "2025-11-01",
    "basis": "U-Mamba2 reports clDice 0.91 vs the claim's 0.88 ceiling under the same protocol.",
    "evidence_ref": ["contradiction-report.artifact.json", "[[u-mamba2-2025]]"],
}


def test_good_record_validates():
    art = envelope("invalidation_record", "contradiction-miner", GOOD, TS)
    assert validate_artifact(art) == []


def test_schema_rejects_invented_or_incomplete_records():
    # invented slug format (uppercase / spaces) is rejected — never invent a slug
    bad_slug = dict(GOOD, claim_slug="Not A Slug")
    assert validate_artifact(envelope("invalidation_record", "contradiction-miner", bad_slug, TS)) != []
    # unknown edge type rejected (refutes | supersedes only)
    bad_edge = dict(GOOD, edge_type="dislikes")
    assert validate_artifact(envelope("invalidation_record", "contradiction-miner", bad_edge, TS)) != []
    # missing basis rejected (an invalidation always carries its concrete contradiction evidence)
    no_basis = {k: v for k, v in GOOD.items() if k != "basis"}
    assert validate_artifact(envelope("invalidation_record", "contradiction-miner", no_basis, TS)) != []
    # empty evidence_ref rejected (anti-slop)
    no_ev = dict(GOOD, evidence_ref=[])
    assert validate_artifact(envelope("invalidation_record", "contradiction-miner", no_ev, TS)) != []
