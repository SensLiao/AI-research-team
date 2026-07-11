"""M2 breadth acceptance — the two NEW hard gates are live and demonstrably BLOCK *through a real mode
in the engine* (not just at the checker unit level). This is the breadth analogue of the M2-a spine
acceptance, extending "every hard gate live and demonstrably blocking on injected violations" to the
two gates breadth adds:

  - metric-implementation-auditor ⛔ (DESIGN)   via the `m2_accept` mode
  - citation-integrity-auditor   ⛔ (DISCOVER)  via the `evidence_deep` mode

A gate BLOCK is enforced by the stage producer refusing to advance (raising), leaving the run halted at
that stage — the "dynamic agents cannot cross a hard gate" constitution rule. Each gate is shown to (a)
let a clean run proceed and (b) halt the pipeline at its own stage on an injected violation, with the
downstream stages never created. The real deterministic checkers decide the verdict.

Reuses the proven spine-slice producer (make_full_rigor_agent) for the metric-impl full-pipeline happy
path; the citation path (DISCOVER->REPORT) is self-contained.
"""
from __future__ import annotations

import json

import pytest

from research_agent_teams.orchestrator.engine import run_task
from research_agent_teams.tools.citation_checker import build_report as citation_build
from research_agent_teams.tools.compare_metric_impls import build_report as metric_build
from research_agent_teams.tools.ledger import read_events, verify_chain
from research_agent_teams.tools.runstore import classify_status
from research_agent_teams.tests.test_m2_spine_slice import (
    PROFILE,
    TS,
    GateBlock,
    _approve,
    _env,
    _fx,
    _stage_dir,
    _write,
    make_full_rigor_agent,
)

# metric profile: declares `dice`; no implementation_ref -> canonical check inactive, gate bites via
# cross-condition impl consistency (the realistic case for a profile that hasn't pinned a canonical impl).
_METRIC_PROFILE = {"metrics": [{"name": "dice", "higher_is_better": True}]}

_DICE_IMPL = {"impl_ref": "monai.metrics.DiceMetric", "spacing": [1, 1, 1], "postprocess": "argmax"}
_CONSISTENT = [
    {"condition_id": "c0", "metric_impls": {"dice": dict(_DICE_IMPL)}},
    {"condition_id": "c1", "metric_impls": {"dice": dict(_DICE_IMPL)}},
]
_DIVERGENT = [
    {"condition_id": "c0", "metric_impls": {"dice": dict(_DICE_IMPL)}},
    {"condition_id": "c1", "metric_impls": {"dice": {**_DICE_IMPL, "impl_ref": "custom.fast_dice"}}},
]


# --------------------------------------------------------------------------- metric-impl gate (DESIGN)

def _make_metric_impl_agent(conditions):
    """m2_accept producer: emits a real metric_impl_report at DESIGN (BLOCK halts), then delegates the
    rest of the spine to the proven full-rigor producer."""
    spine = make_full_rigor_agent(_fx())

    def produce(stage, tf, run_dir, ts):
        if stage == "DESIGN":
            d = _stage_dir(run_dir, "DESIGN")
            mr = metric_build(conditions, profile=_METRIC_PROFILE)
            _write(d / "metric-impl-report.artifact.json",
                   _env("metric_impl_report", "metric-implementation-auditor", mr,
                        "blocked" if mr["verdict"] == "BLOCK" else "approved"))
            if mr["verdict"] == "BLOCK":
                raise GateBlock(f"metric-impl BLOCK: {mr['violations']}")
            return spine(stage, tf, run_dir, ts)
        return spine(stage, tf, run_dir, ts)

    return produce


def test_metric_impl_gate_passes_clean_design_and_runs_full_pipeline(tmp_path):
    runs = tmp_path / "runs"
    m = run_task(runs, "mi1", "audit metric impls then run the ablation", "m2_accept", TS,
                 _make_metric_impl_agent(_CONSISTENT), _approve, domain_profile_ref=PROFILE)
    assert m["status"] == "done"
    assert [c["stage"] for c in m["completed_work"]] == ["DESIGN", "EXECUTE", "ANALYZE", "VERIFY", "REPORT"]
    run_dir = runs / "mi1"
    mr = json.loads((run_dir / "evidence" / "DESIGN" / "metric-impl-report.artifact.json").read_text(encoding="utf-8"))
    assert mr["payload"]["verdict"] == "PASS"
    assert verify_chain(read_events(run_dir / "ledger.jsonl")) == []


def test_metric_impl_gate_blocks_divergent_impl_and_halts_at_design(tmp_path):
    runs = tmp_path / "runs"
    with pytest.raises(GateBlock):
        run_task(runs, "mi2", "two conditions use a different dice implementation", "m2_accept", TS,
                 _make_metric_impl_agent(_DIVERGENT), _approve, domain_profile_ref=PROFILE)
    run_dir = runs / "mi2"
    assert classify_status(run_dir) == "crashed_mid_stage"
    mr = json.loads((run_dir / "evidence" / "DESIGN" / "metric-impl-report.artifact.json").read_text(encoding="utf-8"))
    assert mr["payload"]["verdict"] == "BLOCK" and mr["payload"]["violations"]
    assert mr["payload"]["impl_mismatches"]                       # the divergence was named
    assert not (run_dir / "evidence" / "EXECUTE").exists()        # never advanced past DESIGN
    assert not (run_dir / "evidence" / "ANALYZE").exists()


# --------------------------------------------------------------------------- citation-integrity gate (DISCOVER)

def _make_citation_agent(contradicted: bool):
    """evidence_deep producer (DISCOVER -> REPORT): emits claim_list + claim_evidence_map +
    citation_integrity_verdict at DISCOVER. A contradicting locus -> BLOCK halts before the reply."""

    def produce(stage, tf, run_dir, ts):
        d = _stage_dir(run_dir, stage)
        if stage == "DISCOVER":
            claim_list = {"source_scope": "SAM3 vs nnU-Net on vessel segmentation",
                          "claims": [{"claim_id": "c1", "text": "SAM3 beats nnU-Net on Dice",
                                      "source_ref": "arxiv:2401.00001", "kind": "comparison"}]}
            _write(d / "claim-list.artifact.json", _env("claim_list", "claim-extractor", claim_list))
            loci = [{"locus_id": "l1", "source_ref": "arxiv:2401.00001", "location": "Table 3 row 2",
                     "kind": "table",
                     "reported_result": "SAM3 Dice 0.61 vs nnU-Net 0.87" if contradicted else "SAM3 Dice 0.89 vs nnU-Net 0.87",
                     "supports_claim": not contradicted}]
            cem = {"mappings": [{"claim_id": "c1", "loci": loci,
                                 "overall_support": "contradicted" if contradicted else "supported"}]}
            _write(d / "claim-evidence-map.artifact.json", _env("claim_evidence_map", "claim-evidence-linker", cem))
            cv = citation_build(claim_list, cem)
            _write(d / "citation-integrity-verdict.artifact.json",
                   _env("citation_integrity_verdict", "citation-integrity-auditor", cv,
                        "blocked" if cv["verdict"] == "BLOCK" else "approved"))
            if cv["verdict"] == "BLOCK":
                raise GateBlock(f"citation BLOCK: {cv['violations']}")
            evtab = {"query": "SAM3 vs nnU-Net vessel segmentation",
                     "sources": [{"id": "s1", "kind": "paper", "ref": "arxiv:2401.00001"}],
                     "saturation_reached": True}
            return _write(d / "evidence-table.artifact.json", _env("evidence_table", "lit-scout", evtab))
        if stage == "REPORT":
            note = {"summary": "evidence-deep review complete", "references": [],
                    "produced_artifacts": [], "open_questions": []}
            return _write(d / "report-note.artifact.json", _env("report_note", "research-orchestrator", note))
        raise AssertionError(f"unexpected stage {stage}")

    return produce


def test_citation_gate_passes_clean_and_reaches_report(tmp_path):
    runs = tmp_path / "runs"
    m = run_task(runs, "ci1", "review the evidence with citation integrity", "evidence_deep", TS,
                 _make_citation_agent(contradicted=False), _approve, domain_profile_ref=PROFILE)
    assert m["status"] == "done"
    assert [c["stage"] for c in m["completed_work"]] == ["DISCOVER", "REPORT"]   # forward-skip to the reply
    run_dir = runs / "ci1"
    cv = json.loads((run_dir / "evidence" / "DISCOVER" / "citation-integrity-verdict.artifact.json").read_text(encoding="utf-8"))
    assert cv["payload"]["verdict"] == "PASS"
    assert verify_chain(read_events(run_dir / "ledger.jsonl")) == []


def test_citation_gate_blocks_contradicting_locus_and_halts_at_discover(tmp_path):
    runs = tmp_path / "runs"
    with pytest.raises(GateBlock):
        run_task(runs, "ci2", "a citation whose table reports the opposite result", "evidence_deep", TS,
                 _make_citation_agent(contradicted=True), _approve, domain_profile_ref=PROFILE)
    run_dir = runs / "ci2"
    assert classify_status(run_dir) == "crashed_mid_stage"
    cv = json.loads((run_dir / "evidence" / "DISCOVER" / "citation-integrity-verdict.artifact.json").read_text(encoding="utf-8"))
    assert cv["payload"]["verdict"] == "BLOCK"
    assert cv["payload"]["contradicted_claims"] == ["c1"]         # the contradicted claim was named
    assert not (run_dir / "evidence" / "REPORT").exists()         # never reached the reply
