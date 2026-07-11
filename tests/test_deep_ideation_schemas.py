"""Unit tests for the three RAT-2 Wave-3 payload schemas.

Covers: mechanism_graph, experiment_sketch, idea_lineage.

For each schema:
  1. Minimal valid payload validates clean.
  2. Missing a required field produces errors.
  3. Bad enum value produces errors.
  4. Anti-slop / real-ref guard violations produce errors.
  5. GOVERNANCE (additionalProperties:false): injecting a self-bet field at top-level
     AND on a nested item is schema-rejected (mirrors test_idea_backlog_schema_rejects_a_self_bet_field).
"""
from __future__ import annotations

import pytest

from research_agent_teams.tools.validate_artifact import validate_against, validate_payload

# ---------------------------------------------------------------------------
# Minimal valid payloads
# ---------------------------------------------------------------------------

_MG_GOOD = {
    "graph_id": "MG-001",
    "problem_ref": "PA-001",
    "nodes": [
        {"node_id": "N1", "label": "sparse prompt signal", "kind": "variable",
         "evidence_ref": ["[[slug-a]]"]},
        {"node_id": "N2", "label": "boundary under-seg", "kind": "outcome",
         "evidence_ref": ["[[slug-b]]"]},
    ],
    "edges": [
        {"edge_id": "E1", "from_node": "N1", "to_node": "N2", "relation": "causes",
         "evidence_ref": ["[[slug-a]]"]},
    ],
}

_ES_GOOD = {
    "sketch_id": "ES-001",
    "idea_ref": "IDEA-1",
    "experiment": "Train LoRA vs full-ft at matched GPU-hours",
    "controls": ["same backbone, frozen vs adapted encoder"],
    "metrics": ["Dice on held-out canal set"],
    "observable_signals": ["Dice gap within 1% -> LoRA competitive"],
    "falsifier": "LoRA trails full-ft by >1% Dice at matched compute",
}

_IL_GOOD = {
    "lineages": [
        {"idea_id": "IDEA-1", "disposition": "candidate", "evidence_ref": ["IH1"]},
    ],
}


# ===========================================================================
# mechanism_graph
# ===========================================================================

class TestMechanismGraphSchema:

    # 1. minimal valid payload
    def test_valid_minimal_payload(self):
        assert validate_payload("mechanism_graph", _MG_GOOD) == []

    # 2. missing required field
    def test_missing_graph_id_is_rejected(self):
        bad = {k: v for k, v in _MG_GOOD.items() if k != "graph_id"}
        assert validate_payload("mechanism_graph", bad) != []

    def test_missing_problem_ref_is_rejected(self):
        bad = {k: v for k, v in _MG_GOOD.items() if k != "problem_ref"}
        assert validate_payload("mechanism_graph", bad) != []

    def test_missing_nodes_is_rejected(self):
        bad = {k: v for k, v in _MG_GOOD.items() if k != "nodes"}
        assert validate_payload("mechanism_graph", bad) != []

    def test_missing_edges_is_rejected(self):
        bad = {k: v for k, v in _MG_GOOD.items() if k != "edges"}
        assert validate_payload("mechanism_graph", bad) != []

    # 3. bad enum values
    def test_bad_node_kind_is_rejected(self):
        import copy
        bad = copy.deepcopy(_MG_GOOD)
        bad["nodes"][0]["kind"] = "garbage_kind"
        assert validate_payload("mechanism_graph", bad) != []

    def test_bad_edge_relation_is_rejected(self):
        import copy
        bad = copy.deepcopy(_MG_GOOD)
        bad["edges"][0]["relation"] = "destroys"  # not in enum
        assert validate_payload("mechanism_graph", bad) != []

    # 4. anti-slop / real-ref guard violations
    def test_fewer_than_2_nodes_is_rejected(self):
        import copy
        bad = copy.deepcopy(_MG_GOOD)
        bad["nodes"] = bad["nodes"][:1]  # only 1 node -> minItems:2 violated
        assert validate_payload("mechanism_graph", bad) != []

    def test_zero_edges_is_rejected(self):
        import copy
        bad = copy.deepcopy(_MG_GOOD)
        bad["edges"] = []  # minItems:1 violated
        assert validate_payload("mechanism_graph", bad) != []

    def test_problem_ref_without_digit_is_rejected(self):
        import copy
        bad = copy.deepcopy(_MG_GOOD)
        bad["problem_ref"] = "PA-without-digit"  # pattern: [0-9] requires at least one digit
        assert validate_payload("mechanism_graph", bad) != []

    def test_node_empty_evidence_ref_is_rejected(self):
        import copy
        bad = copy.deepcopy(_MG_GOOD)
        bad["nodes"][0]["evidence_ref"] = []  # minItems:1 violated
        assert validate_payload("mechanism_graph", bad) != []

    def test_edge_empty_evidence_ref_is_rejected(self):
        import copy
        bad = copy.deepcopy(_MG_GOOD)
        bad["edges"][0]["evidence_ref"] = []  # minItems:1 violated
        assert validate_payload("mechanism_graph", bad) != []

    # 5. GOVERNANCE — additionalProperties:false -> self-bet field is schema-rejected
    def test_top_level_selected_field_is_rejected(self):
        """additionalProperties:false: any top-level self-bet field must be rejected."""
        assert validate_against("mechanism_graph.schema.json", {**_MG_GOOD, "selected": "N1"}) != []

    def test_top_level_chosen_field_is_rejected(self):
        assert validate_against("mechanism_graph.schema.json", {**_MG_GOOD, "chosen": "N1"}) != []

    def test_top_level_bet_field_is_rejected(self):
        assert validate_against("mechanism_graph.schema.json", {**_MG_GOOD, "bet": "N1"}) != []

    def test_top_level_winner_field_is_rejected(self):
        assert validate_against("mechanism_graph.schema.json", {**_MG_GOOD, "winner": "N1"}) != []

    def test_nested_node_selected_field_is_rejected(self):
        """additionalProperties:false on node items: self-bet on a node is rejected."""
        import copy
        bad = copy.deepcopy(_MG_GOOD)
        bad["nodes"][0]["selected"] = True
        assert validate_against("mechanism_graph.schema.json", bad) != []

    def test_nested_edge_winner_field_is_rejected(self):
        """additionalProperties:false on edge items: self-bet on an edge is rejected."""
        import copy
        bad = copy.deepcopy(_MG_GOOD)
        bad["edges"][0]["winner"] = "E1"
        assert validate_against("mechanism_graph.schema.json", bad) != []


# ===========================================================================
# experiment_sketch
# ===========================================================================

class TestExperimentSketchSchema:

    # 1. minimal valid payload
    def test_valid_minimal_payload(self):
        assert validate_payload("experiment_sketch", _ES_GOOD) == []

    # 2. missing required fields
    def test_missing_sketch_id_is_rejected(self):
        bad = {k: v for k, v in _ES_GOOD.items() if k != "sketch_id"}
        assert validate_payload("experiment_sketch", bad) != []

    def test_missing_idea_ref_is_rejected(self):
        bad = {k: v for k, v in _ES_GOOD.items() if k != "idea_ref"}
        assert validate_payload("experiment_sketch", bad) != []

    def test_missing_experiment_is_rejected(self):
        bad = {k: v for k, v in _ES_GOOD.items() if k != "experiment"}
        assert validate_payload("experiment_sketch", bad) != []

    def test_missing_falsifier_is_rejected(self):
        bad = {k: v for k, v in _ES_GOOD.items() if k != "falsifier"}
        assert validate_payload("experiment_sketch", bad) != []

    def test_missing_controls_is_rejected(self):
        bad = {k: v for k, v in _ES_GOOD.items() if k != "controls"}
        assert validate_payload("experiment_sketch", bad) != []

    def test_missing_metrics_is_rejected(self):
        bad = {k: v for k, v in _ES_GOOD.items() if k != "metrics"}
        assert validate_payload("experiment_sketch", bad) != []

    def test_missing_observable_signals_is_rejected(self):
        bad = {k: v for k, v in _ES_GOOD.items() if k != "observable_signals"}
        assert validate_payload("experiment_sketch", bad) != []

    # 3. bad enum value — experiment_sketch has no explicit enum field, so we test
    #    an additionalProperties violation which is the closest structural guard
    def test_extra_top_level_field_is_rejected(self):
        """additionalProperties:false rejects any unknown field."""
        bad = {**_ES_GOOD, "rank": 1}  # not in schema properties
        assert validate_against("experiment_sketch.schema.json", bad) != []

    # 4. anti-slop / real-ref guard violations
    def test_idea_ref_without_digit_is_rejected(self):
        """idea_ref must contain a digit (real-ref guard pattern [0-9])."""
        bad = {**_ES_GOOD, "idea_ref": "IDEA-no-digit"}
        assert validate_payload("experiment_sketch", bad) != []

    def test_blank_falsifier_is_rejected(self):
        """falsifier is non-blank (pattern \\S)."""
        bad = {**_ES_GOOD, "falsifier": "   "}  # only whitespace -> fails \\S pattern
        assert validate_payload("experiment_sketch", bad) != []

    def test_empty_controls_list_is_rejected(self):
        bad = {**_ES_GOOD, "controls": []}
        assert validate_payload("experiment_sketch", bad) != []

    def test_empty_metrics_list_is_rejected(self):
        bad = {**_ES_GOOD, "metrics": []}
        assert validate_payload("experiment_sketch", bad) != []

    def test_empty_observable_signals_is_rejected(self):
        bad = {**_ES_GOOD, "observable_signals": []}
        assert validate_payload("experiment_sketch", bad) != []

    # 5. GOVERNANCE — additionalProperties:false -> self-bet field is schema-rejected
    def test_top_level_selected_field_is_rejected(self):
        assert validate_against("experiment_sketch.schema.json", {**_ES_GOOD, "selected": "ES-001"}) != []

    def test_top_level_chosen_field_is_rejected(self):
        assert validate_against("experiment_sketch.schema.json", {**_ES_GOOD, "chosen": "ES-001"}) != []

    def test_top_level_bet_field_is_rejected(self):
        assert validate_against("experiment_sketch.schema.json", {**_ES_GOOD, "bet": "ES-001"}) != []

    def test_top_level_winner_field_is_rejected(self):
        assert validate_against("experiment_sketch.schema.json", {**_ES_GOOD, "winner": "ES-001"}) != []


# ===========================================================================
# idea_lineage
# ===========================================================================

class TestIdeaLineageSchema:

    # 1. minimal valid payload
    def test_valid_minimal_payload(self):
        assert validate_payload("idea_lineage", _IL_GOOD) == []

    def test_valid_multi_entry_payload(self):
        good = {
            "lineages": [
                {"idea_id": "IDEA-1", "disposition": "candidate", "evidence_ref": ["IH1"]},
                {"idea_id": "IDEA-2", "disposition": "cut_prior_art", "evidence_ref": ["IH2", "[[slug-x]]"]},
                {"idea_id": "EV-1", "disposition": "evolved", "evidence_ref": ["IDEA-1"],
                 "parent_ids": ["IDEA-1"]},
            ],
        }
        assert validate_payload("idea_lineage", good) == []

    # 2. missing required fields
    def test_missing_lineages_is_rejected(self):
        assert validate_payload("idea_lineage", {}) != []

    def test_lineage_entry_missing_idea_id_is_rejected(self):
        bad = {"lineages": [{"disposition": "candidate", "evidence_ref": ["IH1"]}]}
        assert validate_payload("idea_lineage", bad) != []

    def test_lineage_entry_missing_disposition_is_rejected(self):
        bad = {"lineages": [{"idea_id": "IDEA-1", "evidence_ref": ["IH1"]}]}
        assert validate_payload("idea_lineage", bad) != []

    def test_lineage_entry_missing_evidence_ref_is_rejected(self):
        bad = {"lineages": [{"idea_id": "IDEA-1", "disposition": "candidate"}]}
        assert validate_payload("idea_lineage", bad) != []

    # 3. bad enum value for disposition
    def test_bad_disposition_value_is_rejected(self):
        bad = {"lineages": [{"idea_id": "IDEA-1", "disposition": "recommended",
                              "evidence_ref": ["IH1"]}]}
        assert validate_payload("idea_lineage", bad) != []

    def test_disposition_selected_is_rejected(self):
        """'selected' is explicitly NOT in the disposition enum."""
        bad = {"lineages": [{"idea_id": "IDEA-1", "disposition": "selected",
                              "evidence_ref": ["IH1"]}]}
        assert validate_payload("idea_lineage", bad) != []

    def test_disposition_chosen_is_rejected(self):
        """'chosen' is explicitly NOT in the disposition enum — key governance assertion."""
        bad = {"lineages": [{"idea_id": "IDEA-1", "disposition": "chosen",
                              "evidence_ref": ["IH1"]}]}
        assert validate_payload("idea_lineage", bad) != []

    def test_disposition_winner_is_rejected(self):
        bad = {"lineages": [{"idea_id": "IDEA-1", "disposition": "winner",
                              "evidence_ref": ["IH1"]}]}
        assert validate_payload("idea_lineage", bad) != []

    # 4. anti-slop / real-ref guard violations
    def test_empty_evidence_ref_is_rejected(self):
        """evidence_ref must have minItems:1."""
        bad = {"lineages": [{"idea_id": "IDEA-1", "disposition": "candidate",
                              "evidence_ref": []}]}
        assert validate_payload("idea_lineage", bad) != []

    def test_empty_lineages_array_is_rejected(self):
        """lineages must have minItems:1."""
        assert validate_payload("idea_lineage", {"lineages": []}) != []

    def test_problem_ref_without_digit_is_rejected(self):
        """Optional problem_ref, when present, has the digit real-ref guard."""
        bad = {"lineages": [{"idea_id": "IDEA-1", "disposition": "candidate",
                              "evidence_ref": ["IH1"],
                              "problem_ref": "PA-no-digit"}]}
        assert validate_payload("idea_lineage", bad) != []

    # 5. GOVERNANCE — additionalProperties:false -> self-bet field is schema-rejected at both levels
    def test_top_level_selected_field_is_rejected(self):
        assert validate_against("idea_lineage.schema.json", {**_IL_GOOD, "selected": "IDEA-1"}) != []

    def test_top_level_chosen_field_is_rejected(self):
        assert validate_against("idea_lineage.schema.json", {**_IL_GOOD, "chosen": "IDEA-1"}) != []

    def test_top_level_bet_field_is_rejected(self):
        assert validate_against("idea_lineage.schema.json", {**_IL_GOOD, "bet": "IDEA-1"}) != []

    def test_top_level_winner_field_is_rejected(self):
        assert validate_against("idea_lineage.schema.json", {**_IL_GOOD, "winner": "IDEA-1"}) != []

    def test_nested_lineage_entry_selected_field_is_rejected(self):
        """additionalProperties:false on lineage items: self-bet injected per-item is rejected."""
        import copy
        bad = copy.deepcopy(_IL_GOOD)
        bad["lineages"][0]["selected"] = True
        assert validate_against("idea_lineage.schema.json", bad) != []

    def test_nested_lineage_entry_chosen_field_is_rejected(self):
        import copy
        bad = copy.deepcopy(_IL_GOOD)
        bad["lineages"][0]["chosen"] = True
        assert validate_against("idea_lineage.schema.json", bad) != []

    def test_nested_lineage_entry_bet_field_is_rejected(self):
        import copy
        bad = copy.deepcopy(_IL_GOOD)
        bad["lineages"][0]["bet"] = "IDEA-1"
        assert validate_against("idea_lineage.schema.json", bad) != []

    def test_nested_lineage_entry_winner_field_is_rejected(self):
        import copy
        bad = copy.deepcopy(_IL_GOOD)
        bad["lineages"][0]["winner"] = "IDEA-1"
        assert validate_against("idea_lineage.schema.json", bad) != []
