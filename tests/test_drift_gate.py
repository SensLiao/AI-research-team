"""tools/drift_gate — the north-star per-stage drift gate (audit H2)."""
from __future__ import annotations

from research_agent_teams.tools.drift_gate import anchor_terms, build_verdict, check_drift
from research_agent_teams.tools.validate_artifact import validate_payload

NS = {"statement": "Improve interactive segmentation of mandibular canals in CBCT",
      "in_scope": ["prompt efficiency"], "out_of_scope": ["diffusion models", "pricing"]}


def test_anchor_terms_drop_stopwords_and_dedup():
    terms = anchor_terms("the the improve and improve of CBCT", ["CBCT prompts"])
    assert "the" not in terms and "and" not in terms
    assert terms.count("improve") == 1 and "cbct" in terms and "prompts" in terms


def test_clean_output_passes():
    r = check_drift(NS, ["a sharper interactive segmentation protocol for mandibular canals in CBCT"])
    assert r["violations"] == [] and r["coverage"] > 0.5 and r["out_of_scope_hits"] == []


def test_out_of_scope_phrase_is_a_hard_violation():
    r = check_drift(NS, ["we propose swapping the backbone for diffusion models on CBCT"])
    assert r["out_of_scope_hits"] == ["diffusion models"]
    assert any("out-of-scope" in v for v in r["violations"])


def test_single_token_out_of_scope_matches_tokens_not_substrings():
    ns = dict(NS, out_of_scope=["net"])
    ok = check_drift(ns, ["a magnetic resonance segmentation study of CBCT"])      # 'magnetic' != 'net'
    assert ok["out_of_scope_hits"] == []
    hit = check_drift(ns, ["we train a net on CBCT segmentation"])
    assert hit["out_of_scope_hits"] == ["net"]


def test_zero_anchor_coverage_is_a_hard_violation():
    r = check_drift(NS, ["a survey about restaurant recommendation engines"])
    assert any("zero north-star anchor coverage" in v for v in r["violations"])


def test_low_but_nonzero_coverage_is_advisory_only():
    r = check_drift(NS, ["CBCT something entirely unrelated otherwise"])
    assert r["violations"] == []                       # nonzero coverage never hard-blocks
    assert any("low north-star anchor coverage" in w for w in r["warnings"])


def test_empty_texts_do_not_false_block():
    r = check_drift(NS, [])
    assert r["violations"] == []


def test_build_verdict_is_schema_valid_and_derived():
    ok_payload, _ = build_verdict(NS, ["interactive segmentation of mandibular canals in CBCT"], "DISCOVER")
    assert validate_payload("analysis_check_verdict", ok_payload) == []
    assert ok_payload["panel_role"] == "goal_alignment" and ok_payload["pass"] is True

    bad_payload, facts = build_verdict(NS, ["pricing strategy for diffusion models"], "IDEATE")
    assert validate_payload("analysis_check_verdict", bad_payload) == []
    assert bad_payload["pass"] is False and bad_payload["violations"]
    assert facts["out_of_scope_hits"]
