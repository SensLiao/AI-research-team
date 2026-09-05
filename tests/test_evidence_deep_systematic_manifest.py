"""Publication-grade systematic-review manifest handoff from evidence_deep."""

from __future__ import annotations

import pytest

import json

from research_agent_teams.operate.modes import evidence_deep
from research_agent_teams.orchestrator.graph_spec import load_mode_registry
from research_agent_teams.tools.systematic_review_corpus import build_execution_manifest
from research_agent_teams.tools.validate_artifact import PAYLOAD_SCHEMAS


ROOT = __import__("pathlib").Path(__file__).resolve().parents[2]


def test_evidence_deep_persists_valid_systematic_review_manifest(tmp_path):
    run_dir = tmp_path / "run"
    source = run_dir / evidence_deep.SYSTEMATIC_REVIEW_MANIFEST_REL
    source.parent.mkdir(parents=True)
    manifest = build_execution_manifest(
        [],
        [
            {
                "source_id": "test-search",
                "source_type": "database",
                "query": "promptable medical image segmentation",
                "executed_at": "2026-08-17T04:00:00Z",
                "record_ids": [],
            }
        ],
        review_id="hidden-oracle-review",
        oracle_rulebook_version="oracle-ladder/2026-08-17",
    )
    source.write_text(json.dumps(manifest), encoding="utf-8")

    artifact = evidence_deep.persist_systematic_review_manifest(
        run_dir, "2026-08-17T05:00:00Z"
    )

    payload = json.loads((run_dir / artifact).read_text(encoding="utf-8"))["payload"]
    assert payload == manifest
    assert PAYLOAD_SCHEMAS["systematic_review_execution_manifest"] == (
        "systematic_review_execution_manifest.schema.json"
    )
    reusable = load_mode_registry()["modes"]["evidence_deep"]["handoff"][
        "reusable_artifacts"
    ]
    assert "systematic-review-execution-manifest.artifact.json" in reusable


def test_research_orchestrator_routes_publication_grade_reviews_through_full_evidence_chain():
    skill = ROOT / ".agents/skills/research-orchestrator/SKILL.md"
    if not skill.is_file():
        pytest.skip("workspace entry skill is not part of this checkout")
    text = skill.read_text(encoding="utf-8")
    for required in (
        "systematic-review-execution-manifest.artifact.json",
        "records → reports → studies",
        "citation adjacency",
        "original figures",
        "six-seat",
        "0 open BLOCKING/MAJOR",
    ):
        assert required in text


def test_evidence_deep_conservatively_normalizes_rich_source_quality_descriptions():
    payload = {
        "source_quality_report": {
            "ranked_sources": [
                {
                    "directness": "FULLTEXT_PRIMARY",
                    "methodology_review": {
                        "design_appropriateness": "Detailed benchmark design description",
                        "bias_control": "Bias control not established",
                        "measurement_validity": "adequate",
                        "statistical_validity": "Uncertainty not reported",
                        "reproducibility": "strong",
                    },
                    "sample_evaluation_review": {
                        "sample_adequacy": "Multi-dataset sample",
                        "evaluation_independence": "unclear",
                        "comparator_fairness": "Comparator parity not established",
                        "uncertainty_reporting": "Dose-response uncertainty not established.",
                    },
                    "limitations": ["Existing limitation"],
                }
            ]
        }
    }

    evidence_deep._normalize_source_quality_compat(payload)
    row = payload["source_quality_report"]["ranked_sources"][0]

    assert row["directness"] == "direct"
    assert row["methodology_review"] == {
        "design_appropriateness": "unclear",
        "bias_control": "unclear",
        "measurement_validity": "adequate",
        "statistical_validity": "unclear",
        "reproducibility": "strong",
    }
    assert row["sample_evaluation_review"]["uncertainty_reporting"] == "unclear"
    assert any("Detailed benchmark design description" in item for item in row["limitations"])
    assert any("Dose-response uncertainty not established." in item for item in row["limitations"])


def test_search_trace_separates_control_inputs_and_unfrozen_overlap_leads():
    payload = {
        "evidence_table": {"sources": [{"ref": "arXiv:2304.12306"}]},
        "evidence_search_trace": {
            "rounds": [
                {
                    "round_index": 0,
                    "source_hits": [
                        {"source_ref": "arXiv:2304.12306"},
                        {"source_ref": "inbox/DISCOVER.claim-extractor.bundle.json"},
                        {"source_ref": "doi:10.1016/j.compmedimag.2026.102789"},
                    ],
                    "claim_ids_addressed": ["c1"],
                    "findings": [],
                }
            ]
        },
    }

    evidence_deep._normalize_search_trace_compat(payload)
    row = payload["evidence_search_trace"]["rounds"][0]

    assert row["source_hits"] == [{"source_ref": "arXiv:2304.12306"}]
    assert row["findings"] == [
        {
            "finding_id": "unfrozen-search-lead-r0-1",
            "source_refs": ["doi:10.1016/j.compmedimag.2026.102789"],
            "claim_ids": ["c1"],
            "finding_kind": "boundary",
        }
    ]
