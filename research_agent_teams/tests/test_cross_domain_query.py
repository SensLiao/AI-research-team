"""Tests for the cross-domain query generator (a retrieval widener).

Reconciliation-audit Wave-0 hardening: the public API is
``abstract_problem(problem) -> str`` and ``cross_domain_queries(problem, *, k=6) -> list[str]``.

Behavior pinned here (confirmed against the real module — code is ground truth):
  * ``abstract_problem`` raises ValueError on empty/whitespace input, keeps <=2 mechanism
    terms + <=2 structure terms (mechanisms first), with two graceful fallbacks; hyphenated
    tokens (few-shot, low-rank) survive as single tokens.
  * ``cross_domain_queries`` takes a KEYWORD-ONLY ``k``; ``k < 1`` RAISES ValueError
    (it does NOT clamp up to 1); the upper clamp is ``len(_DISTANT_FIELDS) == 12``.
    Output is deterministic and de-duplicated, length ``min(k, 12)`` for k >= 1.
"""
import pytest

from research_agent_teams.tools.cross_domain_query import (
    abstract_problem,
    cross_domain_queries,
)


# --------------------------------------------------------------- abstract_problem


def test_abstract_problem_empty_raises():
    with pytest.raises(ValueError):
        abstract_problem("")


def test_abstract_problem_whitespace_raises():
    with pytest.raises(ValueError):
        abstract_problem("   ")


def test_abstract_problem_keeps_mechanism_then_structures_drops_domain_nouns():
    # mechanism `segmentation` + structures `thin`,`topology`; domain nouns
    # cbct/medical/mandibular/canal dropped; `broken` not in vocab dropped.
    assert (
        abstract_problem(
            "CBCT medical segmentation of very thin mandibular canal "
            "with broken topology"
        )
        == "segmentation thin topology"
    )


def test_abstract_problem_caps_two_mechanisms_two_structures():
    # segment + detect (<=2 mechanisms), thin + sparse (<=2 structures);
    # classify (3rd mechanism) and rare (3rd structure) dropped by the [:2] slice.
    assert (
        abstract_problem("segment detect classify thin sparse rare")
        == "segment detect thin sparse"
    )


def test_abstract_problem_dedup_first_seen_order():
    assert abstract_problem("segment segment thin thin") == "segment thin"


def test_abstract_problem_hyphenated_tokens_survive():
    # mechanism `adaptation`; structures few-shot,low-rank kept,
    # `frozen` is the 3rd structure dropped by [:2]; proves hyphenated tokens stay whole.
    assert (
        abstract_problem("few-shot low-rank adaptation of frozen text encoder")
        == "adaptation few-shot low-rank"
    )


def test_abstract_problem_fallback1_first_four_distinct_long_tokens():
    # No vocab match -> fallback#1: first 4 distinct non-domain tokens of len>3.
    # `qubits` is the 5th, dropped by [:4].
    assert (
        abstract_problem("quantum entanglement across distant qubits")
        == "quantum entanglement across distant"
    )


def test_abstract_problem_fallback2_ultra_degenerate_all_domain_nouns():
    # All domain nouns -> fallback#2: whole input lowercased + whitespace collapsed.
    assert abstract_problem("CT  MRI   canal") == "ct mri canal"


# --------------------------------------------------------------- cross_domain_queries


def test_cross_domain_queries_k_zero_raises():
    # THE key correction: k < 1 raises ValueError, NOT a length-1 list.
    with pytest.raises(ValueError):
        cross_domain_queries("thin topology", k=0)


def test_cross_domain_queries_k_negative_raises():
    with pytest.raises(ValueError):
        cross_domain_queries("thin topology", k=-3)


def test_cross_domain_queries_upper_clamp_is_twelve():
    assert len(cross_domain_queries("thin topology", k=999)) == 12


def test_cross_domain_queries_k_equals_ceiling():
    assert len(cross_domain_queries("thin topology", k=12)) == 12


def test_cross_domain_queries_default_k_is_six():
    assert len(cross_domain_queries("thin topology")) == 6


def test_cross_domain_queries_deterministic():
    problem = "thin object segmentation with topology breaks"
    assert cross_domain_queries(problem, k=6) == cross_domain_queries(problem, k=6)


def test_cross_domain_queries_deduped():
    q = cross_domain_queries("thin object segmentation with topology breaks", k=6)
    assert len(q) == len(set(q))


def test_cross_domain_queries_k_one_first_field_first_template():
    # _DISTANT_FIELDS[0] = "natural language processing", _TEMPLATES[0] = "{m} in {f}".
    assert cross_domain_queries("thin topology", k=1) == [
        "thin topology in natural language processing"
    ]


def test_cross_domain_queries_second_query_second_field_second_template():
    # _DISTANT_FIELDS[1] = "computer vision", _TEMPLATES[1] = "how does {f} solve {m}".
    assert (
        cross_domain_queries("thin topology", k=2)[1]
        == "how does computer vision solve thin topology"
    )


def test_cross_domain_queries_k_is_keyword_only():
    with pytest.raises(TypeError):
        cross_domain_queries("thin topology", 3)  # positional k -> TypeError
