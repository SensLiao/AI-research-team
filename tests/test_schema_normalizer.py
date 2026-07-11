from __future__ import annotations

from research_agent_teams.tools.schema_normalizer import normalize_payload
from research_agent_teams.tools.validate_artifact import validate_payload


def test_normalization_is_idempotent_and_preserves_richer_fields_in_sidecar():
    payload = {
        "source_ref": "doi:10.1/example",
        "verdict": "needs reread",
        "coverage": "partial",
        "single_paper_completeness": "partial",
        "source_fidelity": "mixed",
        "visual_coverage": "not applicable",
        "evidence_saturation": "not assessed single paper",
        "anchoring": "mixed",
        "method_depth": "mixed",
        "figure_table_coverage": "partial",
        "result_table_depth": "mixed",
        "algorithmic_depth": "not applicable",
        "reproducibility_depth": "mixed",
        "project_alignment": "mixed",
        "domain_transfer_honesty": "strong",
        "independent_critique_resolution": "resolved",
        "markdown_ready": False,
        "promotion_ready": False,
        "worker_extra_analysis": {"useful": "preserve me"},
    }
    normalized, report = normalize_payload("paper_reading_quality", payload)
    assert normalized["verdict"] == "NEEDS_SUPPLEMENT"
    assert normalized["visual_coverage"] == "not-applicable"
    assert "worker_extra_analysis" not in normalized
    assert report["preserved_extras"][0]["value"] == {"useful": "preserve me"}
    assert not validate_payload("paper_reading_quality", normalized)
    twice, second = normalize_payload("paper_reading_quality", normalized)
    assert twice == normalized
    assert second["changes"] == []


def test_normalizer_never_coerces_scientific_types_or_values():
    payload = {"source_ref": "x", "verdict": "PASS", "markdown_ready": "true"}
    normalized, _report = normalize_payload("paper_reading_quality", payload)
    assert normalized["markdown_ready"] == "true"
    assert validate_payload("paper_reading_quality", normalized)


def test_normalizer_losslessly_serializes_richer_structured_text_fields():
    payload = {
        "source_ref": "paper",
        "applicability": "applicable",
        "formal_objects": [{"object": "x", "definition": "y"}],
        "equations_or_rules": ["x=y"],
        "implementation_assumptions": [{"assumption": "closed set", "risk": "open set"}],
        "algorithm_flow": {"train": ["a", "b"], "infer": "c"},
        "equation_consistency": "internally mixed",
        "complexity_or_cost": None,
        "numerical_stability": "not reported",
        "edge_cases": ["empty target"],
        "red_flags": [{"severity": "high", "issue": "scope"}],
        "overall": "mixed",
    }
    normalized, report = normalize_payload("math_algorithm_audit", payload)
    assert not validate_payload("math_algorithm_audit", normalized)
    assert '"object":"x"' in normalized["formal_objects"][0]
    assert '"risk":"open set"' in normalized["implementation_assumptions"][0]
    assert '"train":["a","b"]' in normalized["algorithm_flow"]
    assert any(row["rule"] == "structured-value-to-canonical-json-text" for row in report["changes"])
