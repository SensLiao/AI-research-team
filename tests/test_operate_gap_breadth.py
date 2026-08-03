"""operate/modes/gap_breadth — the 5-hunter panel, really parallel (audit B3/W4)."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from research_agent_teams.operate import spine
from research_agent_teams.operate.artifacts import GateBlock
from research_agent_teams.operate.modes import _shared, gap_breadth
from research_agent_teams.operate.output_versions import (
    finalize_output,
    physical_output,
    prepare_plan,
)
from research_agent_teams.tools.research_output_quality import audit_markdown_text

TS = "2026-06-13T00:00:00Z"
REQ = "scan for mandibular canal segmentation gaps"

BUNDLES = {
    "future-work-miner": [{"gap_id": "FW-1", "statement": "canal segmentation prompt budgets are an open problem",
                           "source_ref": "[[p1]]", "evidence_ref": ["[[p1]]"], "derived_from": ["future_work"]}],
    "weakness-spotter": [{"gap_id": "WK-1", "statement": "canal segmentation evals ignore scanner shift",
                          "locus": "[[p2]] §4", "opportunity": "add cross-scanner eval",
                          "source_ref": "[[p2]]", "evidence_ref": ["[[p2]]"],
                          "derived_from": ["weakness_opportunity"]}],
    "white-space-mapper": [{"gap_id": "WS-1", "statement": "no one studies canal segmentation with sparse clicks",
                            "white_space_present": True, "source_ref": "[[p3]]", "evidence_ref": ["[[p3]]"],
                            "derived_from": ["white_space_present"]}],
    "cross-domain-transfer-scout": [{"gap_id": "XF-1", "statement": "vessel tracking priors untried on canal segmentation",
                                     "source_domain": "vessel tracking", "target_hook": "tubular prior",
                                     "source_ref": "[[p4]]", "evidence_ref": ["[[p4]]"],
                                     "derived_from": ["transfer_potential"]}],
    "contrarian-angle-generator": [{"gap_id": "CA-1", "statement": "canal segmentation may not need 3D context",
                                    "challenged_assumption": "3D context is required",
                                    "source_ref": "[[p5]]", "evidence_ref": ["[[p5]]"],
                                    "derived_from": ["contrarian_angle"]}],
}

SIGNALS_BY_ID = {
    row["gap_id"]: row
    for rows in BUNDLES.values()
    for row in rows
}


def _prosecution(gap_id, status):
    ref = SIGNALS_BY_ID[gap_id]["source_ref"]
    row = {
        "gap_id": gap_id,
        "search_query": f"targeted method problem query for {gap_id}",
        "closure_status": status,
        "why_status": (
            "The cited limitation explicitly remains unresolved."
            if status == "OPEN" else
            "A completed method-problem experiment was located."
            if status == "CLOSED" else
            "Retrieval coverage is incomplete, so the status remains UNVERIFIED."
        ),
        "strongest_prior_art": [{
            "source_ref": ref,
            "title": f"Closest work for {gap_id}",
            "relationship": "adjacent" if status != "CLOSED" else "same",
            "result_locator": "section 4, table 2",
        }],
        "positive_open_evidence": [],
        "closure_evidence": [],
        "strongest_counterevidence": "The nearest paper may already cover part of the claimed scope.",
        "evidence_ref": [ref],
    }
    if status == "OPEN":
        row["positive_open_evidence"] = [{
            "source_ref": ref,
            "open_scope_or_limitation": "The source identifies this exact boundary as unresolved.",
            "locator": "limitations, paragraph 2",
        }]
    if status == "CLOSED":
        row["closure_evidence"] = [{
            "source_ref": ref,
            "title": f"Completed work for {gap_id}",
            "completed_scope": "The same intervention was run on the same task and evaluated.",
            "reported_result": "The intervention improved boundary F1 by 4.2 points against the baseline.",
            "result_locator": "results, table 3",
        }]
    return row


PROSECUTOR_BUNDLE = {
    "prosecutions": [
        _prosecution("FW-1", "OPEN"),
        _prosecution("WK-1", "UNVERIFIED"),
        _prosecution("WS-1", "CLOSED"),
        _prosecution("XF-1", "OPEN"),
        _prosecution("CA-1", "UNVERIFIED"),
    ]
}


def _dossier(gap_id, quadrant):
    ref = SIGNALS_BY_ID[gap_id]["source_ref"]
    status = next(
        row["closure_status"] for row in PROSECUTOR_BUNDLE["prosecutions"]
        if row["gap_id"] == gap_id
    )
    why_open = (
        "UNVERIFIED: current retrieval cannot establish whether the boundary remains open."
        if status == "UNVERIFIED" else
        "The closest study leaves the named mechanism and evaluation boundary unresolved."
    )
    return {
        "gap_id": gap_id,
        "related_gap_ids": [],
        "knowledge_quadrant": quadrant,
        "quadrant_basis": "The evidence state and field location match this quadrant.",
        "problem_statement": f"Does a mechanism-targeted intervention resolve {gap_id} under shift?",
        "evidence_refs": [ref],
        "why_open": why_open,
        "recent_prior_art": [{
            "source_ref": ref,
            "contribution": "The closest work establishes the baseline behavior.",
            "remaining_boundary": "It does not isolate the proposed mechanism under shift.",
        }],
        "mechanism_chain": [
            "A domain shift changes the local evidence distribution.",
            "The proposed mechanism should preserve the relevant structural signal.",
            "A paired stress test should change the error pattern if the mechanism is causal.",
        ],
        "cross_domain_bridge": {
            "source_domain": "robust signal processing",
            "transferable_mechanism": "structure-preserving filtering",
            "target_fit": "Both tasks must recover a weak structured signal under nuisance variation.",
            "boundary_conditions": "The transfer should fail when topology is not stable.",
        },
        "strongest_counterargument": "The observed gap may be a dataset artifact rather than a mechanism failure.",
        "counterevidence": ["A neighboring benchmark reports little degradation under one scanner shift."],
        "minimum_discriminating_experiment": {
            "hypothesis": "The intervention reduces paired shift error without changing in-domain performance.",
            "intervention": "Change only the mechanism and freeze data, split, seeds, and evaluation.",
            "baseline_controls": ["plain baseline", "parameter-matched placebo module"],
            "primary_outcome": "paired change in shift error with a confidence interval",
            "success_threshold": "the prespecified effect clears the minimum meaningful improvement",
            "failure_threshold": "the interval includes no meaningful improvement",
            "kill_criteria": "stop if the failure cannot be reproduced or the placebo explains the gain",
        },
        "resources": {
            "data": "one in-domain and one held-out scanner cohort",
            "compute": "three paired seeds on one available GPU",
            "implementation": "one isolated module plus frozen evaluation code",
            "estimated_effort": "two implementation days plus one audit day",
        },
        "next_step": "Verify the closest paper in full text, then preregister the paired pilot.",
    }


SYNTHESIZER_BUNDLE = {
    "dossiers": [
        _dossier("FW-1", "Known Unknown"),
        _dossier("WK-1", "Known Unknown"),
        _dossier("XF-1", "Unknown Known"),
        _dossier("CA-1", "Unknown Unknown"),
    ]
}


def _audit(gap_id, verdict, scores):
    return {
        "gap_id": gap_id,
        "verdict": verdict,
        "dimensions": {
            dimension: {"score": score, "rationale": f"Independent {dimension} rationale for {gap_id}."}
            for dimension, score in zip(gap_breadth.QUALITY_DIMENSIONS, scores)
        },
        "strongest_objection": "The closest prior art and dataset boundary could erase the contribution.",
        "required_repairs": [] if verdict == "PASS" else ["Resolve the named evidence defect."],
        "evidence_ref": [SIGNALS_BY_ID[gap_id]["source_ref"]],
    }


AUDITOR_BUNDLE = {
    "audits": [
        _audit("FW-1", "PASS", (4, 4, 4, 4, 4, 5)),
        _audit("WK-1", "REVISE", (5, 2, 5, 5, 5, 4)),
        # Low feasibility cannot bury a scientifically stronger opportunity.
        _audit("XF-1", "PASS", (5, 4, 5, 5, 5, 1)),
        _audit("CA-1", "BLOCK", (5, 2, 2, 4, 2, 5)),
    ]
}


def _begin(tmp_path, **kw):
    runs = tmp_path / "runs"
    runs.mkdir(exist_ok=True)
    plan = spine.begin(str(runs), "gb1", REQ, "gap_breadth", TS, **kw)
    return plan["run_dir"]


def _drop_bundles(rd, only=None, override=None):
    for hunter, signals in (override or BUNDLES).items():
        if only and hunter not in only:
            continue
        p = Path(rd) / "inbox" / f"DISCOVER.{hunter}.bundle.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({"signals": signals}), encoding="utf-8")


def test_gap_breadth_uses_hash_linked_supplement_bundle(tmp_path):
    """Hunter bundles repaired through the scheduler are the ones the gate reads."""
    rd = Path(_begin(tmp_path))
    _drop_bundles(rd)
    logical = rd / "inbox" / "DISCOVER.future-work-miner.bundle.json"
    original = json.loads(logical.read_text(encoding="utf-8"))
    original["signals"][0]["statement"] = "original wording"
    logical.write_text(json.dumps(original), encoding="utf-8")
    node = {
        "id": "future-work-miner",
        "label": "future-work-miner",
        "output_path": logical,
        "output_rel": "inbox/DISCOVER.future-work-miner.bundle.json",
    }
    plan = prepare_plan(
        rd, "DISCOVER", 1, [node], {"future-work-miner"},
        {"verdict": "NEEDS_SUPPLEMENT", "defects": []},
    )
    corrected_path = physical_output(rd, plan, "future-work-miner")
    corrected = json.loads(logical.read_text(encoding="utf-8"))
    corrected["signals"][0]["statement"] = "corrected wording"
    corrected_path.parent.mkdir(parents=True, exist_ok=True)
    corrected_path.write_text(json.dumps(corrected), encoding="utf-8")
    finalize_output(rd, "DISCOVER", 1, "future-work-miner", TS)

    bundles = gap_breadth._load_hunter_bundles(rd)
    assert bundles["future-work-miner"]["signals"][0]["statement"] == "corrected wording"


def _with_closure_snapshots(rd, prosecutor):
    payload = json.loads(json.dumps(prosecutor))
    for row in payload.get("prosecutions", []):
        if row.get("closure_status") != "CLOSED":
            continue
        for index, paper in enumerate(row.get("closure_evidence") or []):
            scope = paper["completed_scope"]
            result = paper["reported_result"]
            text = scope + "\n" + result
            rel = Path("inbox") / "closure-snapshots" / f"{row['gap_id']}-{index}.txt"
            path = Path(rd) / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(text.encode("utf-8"))
            result_start = len(scope) + 1
            paper["scope_verification"] = {
                "contract_version": gap_breadth.CLOSURE_SCOPE_CONTRACT,
                "verification_method": "fulltext_snapshot",
                "independent_of_hunter": True,
                "snapshot_ref": rel.as_posix(),
                "document_hash": "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest(),
                "parser_version": "unit-fulltext/v1",
                "scope_span": {
                    "start_char": 0,
                    "end_char": len(scope),
                    "exact_quote": scope,
                },
                "result_span": {
                    "start_char": result_start,
                    "end_char": result_start + len(result),
                    "exact_quote": result,
                },
                "scope_match_rationale": "The exact methods span names the same intervention and task.",
                "result_match_rationale": "The exact results span reports the measured comparison.",
            }
    return payload


def _drop_staged_bundles(rd, *, prosecutor=None, synthesizer=None, auditor=None,
                         bind_closure=True):
    prosecutor_payload = prosecutor if prosecutor is not None else PROSECUTOR_BUNDLE
    if bind_closure:
        prosecutor_payload = _with_closure_snapshots(rd, prosecutor_payload)
    payloads = {
        "gap-prosecutor": prosecutor_payload,
        "mechanism-synthesizer": synthesizer or SYNTHESIZER_BUNDLE,
        "gap-quality-auditor": auditor or AUDITOR_BUNDLE,
    }
    for agent, payload in payloads.items():
        p = Path(rd) / "inbox" / f"DISCOVER.{agent}.bundle.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(payload), encoding="utf-8")


def _drop_complete_panel(rd):
    _drop_bundles(rd)
    _drop_staged_bundles(rd)


def test_llm_step_returns_blind_hunters_then_three_ordered_workers(tmp_path):
    rd = _begin(tmp_path)
    panel = gap_breadth.llm_step(rd, "DISCOVER", REQ)
    assert len(panel["workers"]) == 8
    hunter_workers = panel["workers"][:5]
    assert {w["label"] for w in hunter_workers} == set(gap_breadth.HUNTERS)
    for w in hunter_workers:
        assert "NORTH STAR" in w["prompt"] and "ONLY this" in w["prompt"]
        assert "doi:..." in w["prompt"] and "search-results.json" in w["prompt"]
        assert "reference papers ONLY by their real" not in w["prompt"]
        assert "DISCOVER.gap-prosecutor.bundle.json" not in w["prompt"]
        assert w["depends_on"] == [] and w["execution_group"] == "blind-hunters"
    assert panel["worker_order"] == [*gap_breadth.HUNTERS, *gap_breadth.POST_HUNTER_AGENTS]
    assert panel["parallel_groups"] == [
        list(gap_breadth.HUNTERS),
        ["gap-prosecutor"],
        ["mechanism-synthesizer"],
        ["gap-quality-auditor"],
    ]
    by_label = {worker["label"]: worker for worker in panel["workers"]}
    for hunter in gap_breadth.HUNTERS:
        assert f"DISCOVER.{hunter}.bundle.json" in by_label["gap-prosecutor"]["prompt"]
    assert "DISCOVER.gap-prosecutor.bundle.json" in by_label["mechanism-synthesizer"]["prompt"]
    assert "DISCOVER.mechanism-synthesizer.bundle.json" in by_label["gap-quality-auditor"]["prompt"]
    assert by_label["gap-prosecutor"]["depends_on"] == list(gap_breadth.HUNTERS)
    assert by_label["mechanism-synthesizer"]["depends_on"] == ["gap-prosecutor"]
    assert by_label["gap-quality-auditor"]["depends_on"] == [
        "gap-prosecutor", "mechanism-synthesizer"
    ]
    assert gap_breadth.llm_step(rd, "REPORT", REQ) is None


def test_happy_path_merges_classifies_and_scores(tmp_path):
    rd = _begin(tmp_path)
    _drop_complete_panel(rd)
    paths, report = gap_breadth.run_dets(rd, "DISCOVER", TS)
    assert report["gaps_classified"] == 5
    assert report["signals_per_hunter"]["weakness-spotter"] == 1
    gc = json.loads(Path(rd, "evidence", "DISCOVER", "gap-classification.artifact.json").read_text(encoding="utf-8"))
    types = {g["gap_id"]: g["gap_type"] for g in gc["payload"]["gaps"]}
    assert types["XF-1"] == "transfer_gap" and types["CA-1"] == "assumption_gap"
    assert types["WK-1"] == "methodological_gap" and types["WS-1"] == "coverage_gap"
    nv = json.loads(Path(rd, "evidence", "DISCOVER", "novelty-score.artifact.json").read_text(encoding="utf-8"))
    assert len(nv["payload"]["scores"]) == 5                       # SCORE-ONLY: none dropped
    assert report["novelty_grounded"] is False                     # no pre-search bundle
    assert report["closure_statuses"]["WS-1"] == "CLOSED"
    assert report["closed_ids"] == ["WS-1"]
    assert report["dossiers_built"] == 4
    assert report["quality_verdicts"]["CA-1"] == "BLOCK"
    scan = Path(rd) / gap_breadth.GAP_SCAN_REL
    assert report["director_gap_scan"].replace("\\", "/").endswith("director-review/gaps/gap-scan.md")
    assert scan.is_file()
    text = scan.read_text(encoding="utf-8")
    assert not text.lstrip().startswith("{")
    for heading in (
        "## Bottom Line",
        "## Knowledge Quadrants",
        "## Ranked Scientific Opportunities",
        "## Why Worth Studying",
        "## Evidence Anchors",
        "## Gap Dossiers",
        "## Novelty Uncertainty",
        "## First Falsification Experiment",
        "## Kill Criteria",
        "## Closed By Prior Art",
        "## Decision Boundary",
        "## Next Action",
    ):
        assert heading in text
    for quadrant in gap_breadth.KNOWLEDGE_QUADRANTS:
        assert quadrant in text
    assert "Highest audit-admissible dossier for human review is `XF-1`" in text
    assert "feasibility 5%" in text
    assert "`WS-1` was cut only because" in text
    assert "full-text snapshot `inbox/closure-snapshots/WS-1-0.txt`" in text
    assert "exact scope/result spans" in text
    assert "No shared pre-search bundle was available" in text
    assert "does not self-bet" in text
    assert audit_markdown_text("gap_breadth", text)["status"] == "pass"
    rpaths, _ = gap_breadth.run_dets(rd, "REPORT", TS)
    assert rpaths
    note = json.loads(Path(rpaths[0]).read_text(encoding="utf-8"))["payload"]
    assert "director-review/gaps/gap-scan.md" in note["references"]


def test_missing_hunter_bundle_blocks_by_name(tmp_path):
    rd = _begin(tmp_path)
    _drop_bundles(rd, only={"future-work-miner", "weakness-spotter"})
    _drop_staged_bundles(rd)
    with pytest.raises(GateBlock, match="white-space-mapper"):
        gap_breadth.run_dets(rd, "DISCOVER", TS)


def test_missing_staged_bundle_blocks_in_predecessor_order(tmp_path):
    rd = _begin(tmp_path)
    _drop_bundles(rd)
    p = Path(rd) / "inbox" / "DISCOVER.gap-prosecutor.bundle.json"
    p.write_text(json.dumps(PROSECUTOR_BUNDLE), encoding="utf-8")
    with pytest.raises(GateBlock, match="mechanism-synthesizer"):
        gap_breadth.run_dets(rd, "DISCOVER", TS)


def test_closed_requires_completed_paper_scope_and_result_locator(tmp_path):
    rd = _begin(tmp_path)
    _drop_bundles(rd)
    bad = json.loads(json.dumps(PROSECUTOR_BUNDLE))
    closed = next(row for row in bad["prosecutions"] if row["gap_id"] == "WS-1")
    closed["closure_evidence"] = []
    _drop_staged_bundles(rd, prosecutor=bad)
    with pytest.raises(GateBlock, match="CLOSED requires exact completed-paper evidence"):
        gap_breadth.run_dets(rd, "DISCOVER", TS)


def test_source_existence_and_locator_alone_cannot_close_a_gap(tmp_path):
    rd = _begin(tmp_path)
    _drop_bundles(rd)
    # The legacy shape names a real-looking source and locator but has no independently re-opened
    # full-text snapshot. It must not be allowed to remove the opportunity.
    _drop_staged_bundles(rd, prosecutor=json.loads(json.dumps(PROSECUTOR_BUNDLE)),
                         bind_closure=False)
    with pytest.raises(GateBlock, match="scope_verification"):
        gap_breadth.run_dets(rd, "DISCOVER", TS)


def test_closed_snapshot_hash_mismatch_blocks_false_closure(tmp_path):
    rd = _begin(tmp_path)
    _drop_bundles(rd)
    bad = _with_closure_snapshots(rd, PROSECUTOR_BUNDLE)
    closed = next(row for row in bad["prosecutions"] if row["gap_id"] == "WS-1")
    closed["closure_evidence"][0]["scope_verification"]["document_hash"] = "sha256:" + "0" * 64
    _drop_staged_bundles(rd, prosecutor=bad, bind_closure=False)
    with pytest.raises(GateBlock, match="snapshot hash mismatch"):
        gap_breadth.run_dets(rd, "DISCOVER", TS)


def test_closed_scope_quote_must_match_declared_fulltext_span(tmp_path):
    rd = _begin(tmp_path)
    _drop_bundles(rd)
    bad = _with_closure_snapshots(rd, PROSECUTOR_BUNDLE)
    closed = next(row for row in bad["prosecutions"] if row["gap_id"] == "WS-1")
    closed["closure_evidence"][0]["scope_verification"]["scope_span"]["exact_quote"] += " tampered"
    _drop_staged_bundles(rd, prosecutor=bad, bind_closure=False)
    with pytest.raises(GateBlock, match="exact_quote does not match"):
        gap_breadth.run_dets(rd, "DISCOVER", TS)


def test_no_search_hit_cannot_be_promoted_to_open(tmp_path):
    rd = _begin(tmp_path)
    _drop_bundles(rd)
    bad = json.loads(json.dumps(PROSECUTOR_BUNDLE))
    row = next(item for item in bad["prosecutions"] if item["gap_id"] == "WK-1")
    row["closure_status"] = "OPEN"
    row["why_status"] = "No paper was found."
    row["positive_open_evidence"] = []
    _drop_staged_bundles(rd, prosecutor=bad)
    with pytest.raises(GateBlock, match="no search hit is only UNVERIFIED"):
        gap_breadth.run_dets(rd, "DISCOVER", TS)


def test_external_status_evidence_must_be_existence_verified(tmp_path, monkeypatch):
    rd = _begin(tmp_path)
    _drop_bundles(rd)
    bad = json.loads(json.dumps(PROSECUTOR_BUNDLE))
    row = next(item for item in bad["prosecutions"] if item["gap_id"] == "FW-1")
    row["positive_open_evidence"][0]["source_ref"] = "doi:10.9999/unreachable"
    _drop_staged_bundles(rd, prosecutor=bad)

    monkeypatch.setattr(
        _shared,
        "run_existence_gate",
        lambda *args, **kwargs: (
            str(Path(rd) / "evidence" / "DISCOVER" / "citation-existence-verdict.artifact.json"),
            {
                "checked": [{
                    "ref": "doi:10.9999/unreachable",
                    "state": "lookup_error",
                    "detail": "offline",
                }],
                "warnings": ["offline"],
            },
        ),
    )
    with pytest.raises(GateBlock, match="downgrade affected gaps to UNVERIFIED"):
        gap_breadth.run_dets(rd, "DISCOVER", TS)


def test_unverified_dossier_must_disclose_uncertainty(tmp_path):
    rd = _begin(tmp_path)
    _drop_bundles(rd)
    bad = json.loads(json.dumps(SYNTHESIZER_BUNDLE))
    row = next(item for item in bad["dossiers"] if item["gap_id"] == "WK-1")
    row["why_open"] = "This gap is definitely open because nothing was found."
    _drop_staged_bundles(rd, synthesizer=bad)
    with pytest.raises(GateBlock, match="why_open must say so"):
        gap_breadth.run_dets(rd, "DISCOVER", TS)


def test_quality_audit_requires_all_six_dimensions(tmp_path):
    rd = _begin(tmp_path)
    _drop_bundles(rd)
    bad = json.loads(json.dumps(AUDITOR_BUNDLE))
    del bad["audits"][0]["dimensions"]["information_gain"]
    _drop_staged_bundles(rd, auditor=bad)
    with pytest.raises(GateBlock, match="missing quality dimensions"):
        gap_breadth.run_dets(rd, "DISCOVER", TS)


def test_invented_slug_blocks_when_the_vault_is_reachable(tmp_path, monkeypatch):
    vault = tmp_path / "vault"
    (vault / "02-wiki").mkdir(parents=True)
    (vault / "02-wiki" / "p1.md").write_text("# p1", encoding="utf-8")
    monkeypatch.setattr(_shared, "VAULT_ROOT_OVERRIDE", str(vault))
    rd = _begin(tmp_path)
    _drop_bundles(rd, only={"future-work-miner"})
    _drop_bundles(rd, override={h: s for h, s in BUNDLES.items() if h != "future-work-miner"})
    _drop_staged_bundles(rd)
    with pytest.raises(GateBlock, match="vault-slug integrity BLOCK"):
        gap_breadth.run_dets(rd, "DISCOVER", TS)                   # [[p2]]..[[p5]] don't exist


def test_out_of_scope_drift_blocks_the_panel(tmp_path):
    rd_runs = tmp_path / "runs"
    rd_runs.mkdir()
    plan = spine.begin(str(rd_runs), "gb2", REQ, "gap_breadth", TS,
                       north_star={"statement": REQ, "in_scope": [], "out_of_scope": ["pricing"]})
    rd = plan["run_dir"]
    poisoned = {h: [dict(s[0], statement=s[0]["statement"] + " with a pricing angle")]
                for h, s in BUNDLES.items()}
    _drop_bundles(rd, override=poisoned)
    _drop_staged_bundles(rd)
    with pytest.raises(GateBlock, match="drift gate BLOCK"):
        gap_breadth.run_dets(rd, "DISCOVER", TS)
