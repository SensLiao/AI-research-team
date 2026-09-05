"""operate/modes/deep_ideation — the FULL deep-ideation chain end-to-end (RAT-2 Wave-3, 2026-06-19).

Drives DISCOVER -> IDEATE -> REPORT through the real deterministic producers offline (no vault, no
network), proving the deep chain wires the already-built RAT-2 tools into push-button artifacts:
  DISCOVER  new_direction's grounding base + problem_abstraction + mechanism_graph + mechanism_mapping
            + evidence_saturation_report + contradiction_report
  IDEATE    new_direction's hypotheses -> tournament -> novelty-collision gate -> /idea-bet MENU
            + experiment_sketch(es) + idea_lineage
  REPORT    new_direction's report-note + global_quality_scorecard + integrity_recommendation
            + idea_quality_eval (blind pairwise)

Every produced artifact is contract-validated (write_artifact validates; we re-assert here). The mode
COMPOSES new_direction's proven base (zero drift) and ADDS the deep producers from _deep_ideate.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from research_agent_teams.operate import spine
from research_agent_teams.operate.artifacts import GateBlock, TargetedGateBlock
from research_agent_teams.operate.modes import _deep_ideate, deep_ideation, new_direction
from research_agent_teams.tools.validate_artifact import validate_artifact

TS = "2026-06-19T00:00:00Z"
REQ = "find a promptable 3D segmentation direction worth betting on"

# --------------------------------------------------------------------------- worker-bundle fixtures (clean)

DISCOVER_BUNDLE = {
    "read_summary": "mined the vault for promptable-3D-seg gaps",
    "evidence_table": {"query": "promptable 3D segmentation gap scan",
                       "sources": [{"id": "s1", "kind": "paper", "ref": "[[a]]", "claim_support": "strong"},
                                   {"id": "s2", "kind": "paper", "ref": "[[b]]", "claim_support": "moderate"},
                                   {"id": "s3", "kind": "paper", "ref": "[[c]]", "claim_support": "moderate"}],
                       "saturation_reached": False},
    # Saturation is MEASURED from recorded retrieval rounds (2026-08-07), never self-declared. With no
    # rounds there is no saturation artifact at all — a measurement with no measurements behind it is
    # worse than a missing one — so the fixture records two real passes.
    "saturation_rounds": [
        {"round_index": 1, "queries_run": 3, "new_unique_sources": 3, "cumulative_unique_sources": 3},
        {"round_index": 2, "queries_run": 3, "new_unique_sources": 0, "cumulative_unique_sources": 3},
    ],
    "claim_list": {"source_scope": "gap scan",
                   "claims": [{"claim_id": "c1", "text": "Adapter tuning is underexplored for 3D prompts.",
                               "source_ref": "[[a]]"}]},
    "claim_evidence_map": {"mappings": [{"claim_id": "c1", "overall_support": "supported",
                                         "loci": [{"locus_id": "l1", "source_ref": "[[a]]", "location": "Sec 5",
                                                   "kind": "text", "reported_result": "named as open future work",
                                                   "supports_claim": True}]}]},
    "signals": [{"gap_id": "GAP-1", "statement": "Adapter tuning underexplored for promptable 3D seg",
                 "source_ref": "[[a]]", "evidence_ref": ["[[a]]"], "derived_from": ["white_space_present"]},
                {"gap_id": "GAP-2", "statement": "No fair-budget benchmark for SAM medical adaptation",
                 "source_ref": "[[b]]", "evidence_ref": ["[[b]]"], "derived_from": ["future_work"]}],
}

FORMALIZE_BUNDLE = {
    "problem_id": "PA-001",
    "problem": "segment thin tubular canal structures from volumetric scans with sparse prompts",
    "mechanism_primitives": ["thin_structure", "topology_preservation"],
    "failure_modes": ["breaks at low contrast boundaries"],
    "constraints": ["label scarcity"], "success_metrics": ["boundary fidelity"],
    "abstraction_confidence": 0.6,
}

MECHANISM_BUNDLE = {
    "graph_id": "MG-001", "problem_ref": "PA-001",
    "nodes": [{"node_id": "N1", "label": "sparse prompt signal", "kind": "variable", "evidence_ref": ["[[a]]"]},
              {"node_id": "N2", "label": "thin-structure feature drift", "kind": "mechanism", "evidence_ref": ["[[a]]"]},
              {"node_id": "N3", "label": "boundary under-segmentation", "kind": "outcome", "evidence_ref": ["[[b]]"]}],
    "edges": [{"edge_id": "E1", "from_node": "N1", "to_node": "N2", "relation": "enables", "evidence_ref": ["[[a]]"]},
              {"edge_id": "E2", "from_node": "N2", "to_node": "N3", "relation": "causes", "evidence_ref": ["[[b]]"]}],
    "intervention_points": [{"node_ref": "N2", "rationale": "stabilize thin-structure features"}],
    "failure_modes": ["loses topology at low contrast"],
}

ANALOGY_BUNDLE = {
    "mappings": [{"mapping_id": "AM-001", "source_domain": "vessel tracking", "target_problem_id": "PA-001",
                  "source_mechanisms": ["track thin tubular structure", "preserve connectivity"],
                  "target_mechanisms": ["track thin tubular structure", "preserve connectivity"],
                  "shared_mechanisms": [{"mechanism": "track thin tubular structure",
                                         "source_evidence_ref": ["[[a]]"]},
                                        {"mechanism": "preserve connectivity", "source_evidence_ref": ["[[c]]"]}],
                  "blocking_assumptions": [], "required_adaptations": []}],
}


def test_deep_ideation_declares_four_wave_sparse_discover_dag(tmp_path):
    runs = tmp_path / "runs"
    runs.mkdir()
    rd = spine.begin(str(runs), "dag", REQ, "deep_ideation", TS)["run_dir"]
    spec = deep_ideation.llm_step(rd, "DISCOVER", REQ)
    assert spec["parallel_groups"] == [
        ["direction-grounding-scout"],
        ["mathematical-formalizer", "contradiction-miner"],
        ["mathematical-formalizer"],
        ["analogy-mapper"],
    ]

CONTRADICTION_BUNDLE = {"conflicts": [], "n_claims_checked": 1}

# Multi-view panel contract fixture (2026-08-09): IDEATE.bundle.json is the MERGER's output — every
# idea carries the full thesis fields the idea-quality gate enforces (research_question,
# mechanism_hypothesis, causal_chain >=2, difference_from_prior_art, invention_claim for invention tier).
IDEATE_BUNDLE = {
    "hypotheses": [
        {"hypothesis_id": "IH1", "statement": "A LoRA adapter matches full fine-tune for 3D prompts at equal budget.",
         "falsifiable_prediction": "Dice(LoRA) >= Dice(full-ft) within 1% at equal GPU-hours on fold0.",
         "evidence_needed": ["equal-budget ablation"], "evidence_ref": ["GAP-1", "[[a]]"]},
        {"hypothesis_id": "IH2", "statement": "A fair-budget benchmark reorders the SAM-medical leaderboard.",
         "falsifiable_prediction": "At equal GPU-hours, >=2 methods swap rank vs the published table.",
         "evidence_needed": ["re-run top-5 at equal budget"], "evidence_ref": ["GAP-2", "[[b]]"]}],
    "ideas": [
        {"idea_id": "IDEA-1", "summary": "LoRA-vs-full-ft equal-budget ablation for promptable 3D seg.",
         "evidence_ref": ["IH1", "GAP-1"], "from_hypothesis_ref": "IH1",
         "research_question": "At equal GPU budget, does a LoRA adapter match full fine-tune on promptable 3D segmentation?",
         "mechanism_hypothesis": "Low-rank adaptation preserves the backbone's promptable priors while full fine-tune drifts them.",
         "causal_chain": ["LoRA constrains weight delta to low rank -> backbone priors preserved", "preserved priors -> equal-budget Dice parity"],
         "problem_evidence": ["[[a]]"], "independent_scientific_value": "Budget-equitable adapter comparison is a reusable protocol.",
         "contribution_tier": "method_invention",
         "invention_claim": "An equal-GPU-budget LoRA-vs-full-fine-tune protocol with matched compute accounting for promptable 3D segmentation.",
         "innovation_layers": ["evaluation", "feasibility"], "depth_target": "D2: parity reproduces on >=2 backbones",
         "conventional_base": "LoRA and full fine-tune are both established", "unusual_connection": "budget-equality as the comparison axis",
         "mechanism_graph_refs": ["N2"], "intervention_point": "N2 TUNES",
         "origin_operator": "enabler", "difference_from_prior_art": "adapter-vs-fullft at matched GPU-hours for 3D promptable models",
         "resource_envelope": "fits_single_a6000", "expected_contributions": ["fair-budget protocol"],
         "intended_contribution": "matched-compute adapter benchmark", "why_now": "LoRA is standard for 3D segmentation",
         "feasibility": {"compute": "medium", "data": "available", "time": "medium"}},
        {"idea_id": "IDEA-2", "summary": "Build the fair-budget SAM-medical benchmark and re-rank the leaderboard.",
         "evidence_ref": ["IH2", "GAP-2"], "from_hypothesis_ref": "IH2",
         "research_question": "Does equalizing GPU budget across SAM-medical methods reorder the published leaderboard?",
         "mechanism_hypothesis": "Unequal training budgets systematically favor heavier methods in published comparisons.",
         "causal_chain": ["budget equalization -> per-method capacity normalized", "normalized capacity -> rank swaps"],
         "problem_evidence": ["[[b]]"], "independent_scientific_value": "A budget-fair re-ranking is a measurement contribution.",
         "contribution_tier": "measurement", "invention_claim": None,
         "innovation_layers": ["evaluation"], "depth_target": "D2: >=2 rank swaps on equalized budget",
         "conventional_base": "SAM-medical benchmarks are established", "unusual_connection": "budget as a confound made explicit",
         "mechanism_graph_refs": ["N3"], "intervention_point": "N3 TUNES",
         "origin_operator": "constraint", "difference_from_prior_art": "budget-equalized re-ranking of the existing leaderboard",
         "resource_envelope": "fits_local_cpu", "expected_contributions": ["leaderboard re-ranking"],
         "intended_contribution": "budget-fair benchmark", "why_now": "published tables omit compute budgets",
         "feasibility": {"compute": "low", "data": "available", "time": "short"}}],
    "tournament": [{"round": 1, "pair_a": "IDEA-1", "pair_b": "IDEA-2", "winner": "IDEA-2",
                    "rationale": "IDEA-2 is lower compute and uses public data vs IDEA-1's ablation."}],
    "evolved": [],
}

COLLISION_BUNDLE = {
    "findings": [{"idea_id": "IDEA-1", "method_combination": "LoRA on promptable 3D seg",
                  "application": "canal segmentation", "domain": "medical imaging",
                  "queries": ["LoRA promptable 3D segmentation"], "verdict": "clear", "colliding_papers": [],
                  "confidence": "medium", "retrieval_status": "available",
                  "retrieval_note": "no collision found"},
                 {"idea_id": "IDEA-2", "method_combination": "fair-budget benchmark",
                  "application": "SAM medical", "domain": "medical imaging",
                  "queries": ["fair budget SAM medical benchmark"], "verdict": "clear", "colliding_papers": [],
                  "confidence": "medium", "retrieval_status": "available",
                  "retrieval_note": "no collision found"}],
    "evidence_ref": ["inbox/COLLISION.bundle.json"],
}

EXPERIMENT_BUNDLE = {
    "sketches": [
        {"sketch_id": "ES-1", "idea_ref": "IDEA-1", "experiment": "train LoRA vs full-ft at matched GPU-hours",
         "controls": ["same backbone, same data, equal GPU-hours"], "metrics": ["Dice", "boundary F1"],
         "observable_signals": ["Dice gap within 1% means LoRA competitive"],
         "falsifier": "LoRA trails full-ft by >1% Dice at matched compute",
         "feasibility": {"compute": "medium", "data": "available", "time": "medium"}},
        {"sketch_id": "ES-2", "idea_ref": "IDEA-2", "experiment": "re-run top-5 methods at equal budget",
         "controls": ["equal GPU-hours across methods"], "metrics": ["rank correlation vs published table"],
         "observable_signals": [">=2 rank swaps means budget confounds the leaderboard"],
         "falsifier": "no rank change after equalizing budget"}],
}


# --------------------------------------------------------------------------- helpers

def _begin(tmp_path, **kw):
    runs = tmp_path / "runs"
    runs.mkdir(exist_ok=True)
    return spine.begin(str(runs), "di1", REQ, "deep_ideation", TS, **kw)["run_dir"]


def _drop(rd, stem, payload):
    p = Path(rd) / "inbox" / f"{stem}.bundle.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(payload), encoding="utf-8")


def _drop_discover(rd):
    _drop(rd, "DISCOVER", DISCOVER_BUNDLE)
    _drop(rd, "FORMALIZE", FORMALIZE_BUNDLE)
    _drop(rd, "MECHANISM", MECHANISM_BUNDLE)
    _drop(rd, "ANALOGY", ANALOGY_BUNDLE)
    _drop(rd, "CONTRADICTION", CONTRADICTION_BUNDLE)


def _drop_ideate(rd):
    _drop(rd, "IDEATE", IDEATE_BUNDLE)
    _drop(rd, "COLLISION", COLLISION_BUNDLE)
    _drop(rd, "EXPERIMENT", EXPERIMENT_BUNDLE)
    new_direction.write_legacy_replay_receipt(
        rd, source_run_id="fixture-di1", reason="exercise frozen pre-panel compatibility")


def _payload(rd, stage, name):
    return json.loads(Path(rd, "evidence", stage, name).read_text(encoding="utf-8"))["payload"]


def _all_artifacts_valid(rd):
    bad = []
    for p in Path(rd, "evidence").rglob("*.artifact.json"):
        art = json.loads(p.read_text(encoding="utf-8"))
        errs = validate_artifact(art)
        if errs:
            bad.append((p.name, errs))
    return bad


# --------------------------------------------------------------------------- 1. full chain end-to-end

def test_deep_ideation_runs_discover_ideate_report_end_to_end(tmp_path):
    rd = _begin(tmp_path)
    _drop_discover(rd)
    dpaths, dreport = deep_ideation.run_dets(rd, "DISCOVER", TS)
    # the deep DISCOVER artifacts exist
    assert _payload(rd, "DISCOVER", "problem-abstraction.artifact.json")["problem_id"] == "PA-001"
    mg = _payload(rd, "DISCOVER", "mechanism-graph.artifact.json")
    assert len(mg["nodes"]) == 3 and len(mg["edges"]) == 2
    assert _payload(rd, "DISCOVER", "mechanism-mapping-AM-001.artifact.json")["overlap_score"] == 1.0
    assert _payload(rd, "DISCOVER", "mechanism-mapping-AM-001.artifact.json")["verdict"] == "PASS"
    assert _payload(rd, "DISCOVER", "evidence-saturation-report.artifact.json")["verdict"] in (
        "SATURATED", "NOT_SATURATED", "INSUFFICIENT_DATA")
    assert "n_claims_checked" in _payload(rd, "DISCOVER", "contradiction-report.artifact.json")
    assert dreport["deep_discover"]["mechanism_graph"] is True

    _drop_ideate(rd)
    ipaths, ireport = deep_ideation.run_dets(rd, "IDEATE", TS)
    # base menu still produced (zero drift on new_direction's contract) + the deep IDEATE artifacts
    assert len(_payload(rd, "IDEATE", "idea-backlog.artifact.json")["ranked_ideas"]) == 2
    assert _payload(rd, "IDEATE", "experiment-sketch-ES-1.artifact.json")["idea_ref"] == "IDEA-1"
    lineage = _payload(rd, "IDEATE", "idea-lineage.artifact.json")["lineages"]
    assert {ln["idea_id"] for ln in lineage} >= {"IDEA-1", "IDEA-2"}
    assert all(ln["disposition"] in ("candidate", "cut_prior_art", "evolved") for ln in lineage)
    menu = Path(rd, "director-review", "ideas", "idea-bet-menu.md")
    assert menu.is_file()
    menu_text = menu.read_text(encoding="utf-8")
    assert "Minimal experiment sketch" in menu_text
    assert "Falsifier:" in menu_text
    assert len(list(Path(rd, "director-review", "ideas", "cards").glob("direction-*.md"))) == 2

    rpaths, _ = deep_ideation.run_dets(rd, "REPORT", TS)
    gsc = _payload(rd, "REPORT", "global-quality-scorecard.artifact.json")
    assert gsc["run_id"] == "di1" and "can_finish" in gsc
    assert _payload(rd, "REPORT", "integrity-recommendation.artifact.json")["decision_authority"] == \
        "director-human-gate"
    qe = _payload(rd, "REPORT", "idea-quality-eval.artifact.json")
    assert {pi["idea_id"] for pi in qe["per_idea"]} == {"IDEA-1", "IDEA-2"}
    assert "depth" in qe["per_idea"][0]["scores"] and "novelty" in qe["per_idea"][0]["scores"]
    assert {pi["scores"]["grounding"] for pi in qe["per_idea"]} == {1.0}

    # EVERYTHING written across the whole run is contract-valid
    assert _all_artifacts_valid(rd) == []


# --------------------------------------------------------------------------- 2. menu has no self-bet (governance)

def test_deep_ideation_menu_and_lineage_carry_no_self_bet(tmp_path):
    rd = _begin(tmp_path)
    _drop_discover(rd)
    deep_ideation.run_dets(rd, "DISCOVER", TS)
    _drop_ideate(rd)
    deep_ideation.run_dets(rd, "IDEATE", TS)
    backlog = _payload(rd, "IDEATE", "idea-backlog.artifact.json")
    assert not (set(backlog) & {"selected", "chosen", "bet", "winner"})
    lineage = _payload(rd, "IDEATE", "idea-lineage.artifact.json")
    assert not (set(lineage) & {"selected", "chosen", "bet", "winner"})
    for ln in lineage["lineages"]:
        assert "disposition" in ln and ln["disposition"] != "chosen"


def test_deep_ideation_requires_sketch_for_every_surviving_menu_idea(tmp_path):
    rd = _begin(tmp_path)
    _drop_discover(rd)
    deep_ideation.run_dets(rd, "DISCOVER", TS)
    _drop_ideate(rd)
    broken = json.loads(json.dumps(EXPERIMENT_BUNDLE))
    broken["sketches"] = broken["sketches"][:1]
    _drop(rd, "EXPERIMENT", broken)
    with pytest.raises(GateBlock, match="experiment-sketch coverage"):
        deep_ideation.run_dets(rd, "IDEATE", TS)


# --------------------------------------------------------------------------- 3. mechanism-graph integrity is live

def test_mechanism_graph_dangling_edge_blocks(tmp_path):
    rd = _begin(tmp_path)
    _drop_discover(rd)
    broken = json.loads(json.dumps(MECHANISM_BUNDLE))
    broken["edges"][0]["to_node"] = "N9"          # points at a node that does not exist
    _drop(rd, "MECHANISM", broken)
    with pytest.raises(GateBlock, match="mechanism-graph integrity"):
        deep_ideation.run_dets(rd, "DISCOVER", TS)


def test_mechanism_graph_problem_ref_must_match_abstraction(tmp_path):
    rd = _begin(tmp_path)
    _drop_discover(rd)
    mism = json.loads(json.dumps(MECHANISM_BUNDLE))
    mism["problem_ref"] = "PA-999"                 # not the formalizer's PA-001
    _drop(rd, "MECHANISM", mism)
    with pytest.raises(GateBlock, match="problem_ref"):
        deep_ideation.run_dets(rd, "DISCOVER", TS)


def test_malformed_deep_artifact_repairs_actual_owner_not_terminal_worker(tmp_path):
    with pytest.raises(TargetedGateBlock) as caught:
        _deep_ideate._write_or_block(
            tmp_path,
            "DISCOVER",
            "mechanism-graph.artifact.json",
            "mechanism_graph",
            "mathematical-formalizer",
            {},
            TS,
        )

    assert caught.value.defects[0]["target_agents"] == ["mathematical-formalizer"]
    assert caught.value.defects[0]["refresh_agents"] == []


# --------------------------------------------------------------------------- 4. unknown stage raises (wiring)

def test_unknown_stage_raises(tmp_path):
    rd = _begin(tmp_path)
    with pytest.raises(ValueError):
        deep_ideation.run_dets(rd, "NO_SUCH_STAGE", TS)


# ------------------------------------------- 5. a worker packet may never ask for a key its schema bans
# Found live on 2026-08-04 by the first real `new_direction` run: the CONTRADICTION packet told the
# worker to emit `detail`, while `contradiction_report.schema.json` sets additionalProperties:false and
# names the field `description` — and `produce_contradiction` passes conflict dicts through VERBATIM, so
# a worker that obeyed its own packet produced an artifact the machine's own validator rejected, and the
# brief rendered a blank blocker line.  The class of bug (packet key vs schema key) is what is pinned
# here, not the one instance.
#
# R3 C4 (2026-08-07) generalizes this into a parametrized guard covering the two sources_read pairs
# C4 added — result_summary (the sanity worker) and failure_inventory (the failure-case-miner worker)
# — alongside the original conflicts case, so a future field gets the same protection for free.

def _schema_all_property_keys(schema_name: str) -> set[str]:
    """Every key declared under ANY 'properties' object anywhere in this schema — a conservative
    "does this key exist somewhere in the schema" superset. It does not enforce nesting level; it
    only catches a key invented out of thin air, the class of bug this guard exists for."""
    schema = json.loads(
        (Path(__file__).resolve().parents[2] / "research_agent_teams" / "schemas" / schema_name).read_text(encoding="utf-8"))

    def _walk(node) -> set[str]:
        found: set[str] = set()
        if isinstance(node, dict):
            props = node.get("properties")
            if isinstance(props, dict):
                found |= set(props)
            for value in node.values():
                found |= _walk(value)
        elif isinstance(node, list):
            for item in node:
                found |= _walk(item)
        return found

    return _walk(schema)


# (case id, wrapper key the packet's JSON example opens with, end-of-example marker or None to read
# to the end of the prompt, schema filename)
_PACKET_KEY_GUARD_CASES = [
    ("conflicts", '"conflicts"', "]", "contradiction_report.schema.json"),
    ("sources_read/result_summary", '"result_summary"', None, "result_summary.schema.json"),
    ("sources_read/failure_inventory", '"failure_inventory"', None, "failure_inventory.schema.json"),
]


def _packet_prompt(case_id: str) -> str:
    if case_id == "conflicts":
        return _deep_ideate.CONTRADICTION_WORKER_PROMPT
    from research_agent_teams.operate.modes import analysis_audit_panel as aap
    return aap._SANITY_PROMPT if "result_summary" in case_id else aap._FAILURE_PROMPT


@pytest.mark.parametrize(("case_id", "wrapper_key", "end_marker", "schema_name"), _PACKET_KEY_GUARD_CASES)
def test_worker_packet_asks_only_for_keys_its_own_schema_accepts(case_id, wrapper_key, end_marker, schema_name):
    prompt = _packet_prompt(case_id)
    allowed = _schema_all_property_keys(schema_name)
    # The packet embeds a literal JSON example; every quoted key inside it must be a key the
    # schema will accept, or an obedient worker is set up to fail validation. Slice past the
    # wrapper key first so the wrapper's OWN name (not itself a schema property) is never asked.
    example = prompt.split(wrapper_key, 1)[1]
    if end_marker is not None:
        example = example.split(end_marker, 1)[0]
    asked = set(re.findall(r'"([a-z_]+)"\s*:', example))
    assert asked <= allowed, (
        f"the {case_id!r} worker packet asks for {sorted(asked - allowed)}, which {schema_name} "
        f"forbids; allowed anywhere in the schema: {sorted(allowed)}")


def test_the_contradiction_conflict_key_survives_into_the_rendered_brief():
    """The renderer and the packet must name the same field, or the blocker line renders empty."""
    from research_agent_teams.tools import research_brief_markdown

    allowed = _schema_all_property_keys("contradiction_report.schema.json")
    source = Path(research_brief_markdown.__file__).read_text(encoding="utf-8")
    read_keys = set(re.findall(r"conflict\.get\(\"([a-z_]+)\"\)", source)) | \
        set(re.findall(r"conflict\.get\('([a-z_]+)'\)", source))
    assert read_keys, "expected the brief renderer to read at least one conflict field"
    assert read_keys <= allowed, (
        f"the brief reads conflict keys the schema does not allow: {sorted(read_keys - allowed)}")


def test_sources_read_key_survives_from_worker_packet_into_the_persisted_artifact():
    """R3 C4's other half of the same property: the field a worker's packet asks for must be the
    SAME field name the consumer actually reads back out, or the grounding the prompt promised is
    silently dropped — exactly what C4 fixed (sanity_checker.build_report and analysis_audit_panel's
    failure-inventory carry-through both now read 'sources_read', not something else)."""
    from research_agent_teams.tools import sanity_checker
    from research_agent_teams.operate.modes import analysis_audit_panel as aap

    assert "sources_read" in _schema_all_property_keys("result_summary.schema.json")
    assert "sources_read" in _schema_all_property_keys("failure_inventory.schema.json")

    sanity_source = Path(sanity_checker.__file__).read_text(encoding="utf-8")
    assert 'result_summary.get("sources_read")' in sanity_source

    panel_source = Path(aap.__file__).read_text(encoding="utf-8")
    assert 'failure_in.get("sources_read")' in panel_source
