"""The collision worker prompt and raw schema must describe the same memo contract."""
from research_agent_teams.tools.validate_artifact import validate_payload


def test_collision_schema_accepts_current_investment_memo_fields():
    bundle = {
        "memo_contract_version": "idea-investment-memo/v2",
        "findings": [{
            "idea_id": "IDEA-1",
            "method_combination": "matched residual-action control assay",
            "application": "interactive whole-body PET/CT lesion correction",
            "domain": "medical image analysis",
            "queries": ["PET/CT residual action matched control assay"],
            "verdict": "adjacent",
            "colliding_papers": [],
            "closest_prior_art": [{
                "ref": "arXiv:2508.21680",
                "title": "Towards Interactive Lesion Segmentation in Whole-Body PET/CT with Promptable Models",
                "relationship": "partial_component_prior",
                "difference": "spatial-click interaction, not a matched action-content causal assay",
            }],
            "difference_from_prior_art": "The candidate holds spatial evidence and capacity fixed across action controls.",
            "visual_evidence": [],
            "confidence": "medium",
            "retrieval_status": "partial",
            "retrieval_note": "Scoped retrieval; this is not global novelty clearance.",
        }],
        "evidence_ref": ["inbox/COLLISION.bundle.json"],
    }
    assert validate_payload("collision_findings", bundle) == []
