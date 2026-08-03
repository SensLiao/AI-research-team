from __future__ import annotations

import copy

import pytest

from research_agent_teams.operate.artifacts import GateBlock
from research_agent_teams.operate.modes._shared import extract_worker_bundle_value


BASE = {"evidence_table": {"query": "q", "sources": []}}
KW = {"stage": "DISCOVER", "mode": "deep_research", "agent": "lit-scout"}


def test_canonical_worker_key_is_copied_without_mutating_bundle():
    bundle = copy.deepcopy(BASE)
    before = copy.deepcopy(bundle)

    value = extract_worker_bundle_value(bundle, "evidence_table", **KW)
    value["query"] = "changed downstream"

    assert bundle == before
    assert bundle["evidence_table"]["query"] == "q"


@pytest.mark.parametrize("wrapper", ["payload", "result", "data"])
def test_unique_single_level_wrapper_is_accepted(wrapper):
    bundle = {wrapper: copy.deepcopy(BASE)}

    value = extract_worker_bundle_value(bundle, "evidence_table", **KW)

    assert value == BASE["evidence_table"]


def test_direct_and_equal_wrapped_copy_are_accepted():
    bundle = {
        "evidence_table": copy.deepcopy(BASE["evidence_table"]),
        "payload": copy.deepcopy(BASE),
    }

    assert extract_worker_bundle_value(bundle, "evidence_table", **KW) == \
        BASE["evidence_table"]


def test_direct_and_conflicting_wrapped_copy_block():
    bundle = {
        "evidence_table": copy.deepcopy(BASE["evidence_table"]),
        "payload": {"evidence_table": {"query": "different", "sources": []}},
    }

    with pytest.raises(GateBlock, match="conflicting.*refusing to guess"):
        extract_worker_bundle_value(bundle, "evidence_table", **KW)


def test_multiple_wrapper_candidates_block_even_when_equal():
    bundle = {"payload": copy.deepcopy(BASE), "result": copy.deepcopy(BASE)}

    with pytest.raises(GateBlock, match="multiple wrapped candidates.*refusing to guess"):
        extract_worker_bundle_value(bundle, "evidence_table", **KW)


@pytest.mark.parametrize(
    "bundle",
    [
        {"error": "model timeout"},
        {"errors": ["invalid tool response"]},
        {"status": "failed", "reason": "tool read failed"},
        {"status": "blocked"},
        {"payload": {"success": False, "message": "worker aborted"}},
    ],
)
def test_worker_error_envelopes_are_never_treated_as_payload(bundle):
    with pytest.raises(GateBlock, match="worker failure envelope"):
        extract_worker_bundle_value(bundle, "evidence_table", **KW)


def test_optional_missing_key_returns_an_independent_default():
    default = []
    value = extract_worker_bundle_value(
        {"payload": {"other": {}}}, "invalidation_proposals",
        required=False, default=default, **KW,
    )
    value.append("changed")

    assert default == []


def test_wrapper_without_canonical_key_is_not_guessed_as_the_payload():
    with pytest.raises(GateBlock, match="missing required key"):
        extract_worker_bundle_value(
            {"payload": {"query": "q", "sources": []}},
            "evidence_table", **KW,
        )
