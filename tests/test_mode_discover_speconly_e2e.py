"""Engine-level E2E for three DISCOVER-entry modes — honest reachable behaviour.

gap_scan + full_new_direction are registry-defined + engine-routable but NOT one-button operate
recipes (audit H8): both declare a DISCOVER entry with NO `stage_path`, so the engine's `_resolve_path`
drives the FULL tail DISCOVER->IDEATE->...->REPORT — yet each mode's agent_subset holds ONLY
DISCOVER-stage agents. That is a "dead tail": no agent does the work of any post-DISCOVER stage.
ingest_paper is now an OPERATED reading mode (paper-reading upgrade 2026-06-26 — the real one-button
ingest is its operate recipe), but its ENGINE-driven path is asserted here too: under the tight
max_agent_hops=1 budget the stop-controller BITES at the first hop, before any stage runs. This test
asserts the HONEST reachable behaviour of each, never a faked "done":

  - ingest_paper        (operated reading mode; record_only, max_agent_hops=1, agents=[literature-ingest])
        The 1-hop budget is so tight the stop-controller BITES on the very first stage — `usage`
        hits agent_hops=1 and `assert_within` raises BudgetExceeded BEFORE the DISCOVER producer
        even runs. The honest engine-level reachable behaviour: this budget cannot afford even one
        stage through the engine (the budget bites at hop 1 regardless of the now-declared stage_path).
        (The real one-button ingest is the `ingest_paper` OPERATE recipe / DB INGEST; this asserts the
        separate engine-driven path's budget bite — no longer a spec-only stub.)

  - gap_scan            (record_only, max_agent_hops=3, agents=[future-work-miner, weakness-spotter,
                         gap-classifier])
        All three DISCOVER hunters produce schema-valid artifacts and DISCOVER checkpoints cleanly;
        then the engine walks into the declared-but-dead IDEATE tail (no agent in the subset can
        author an IDEATE artifact). The producer refuses -> run halts crashed_mid_stage with the
        DISCOVER evidence present and IDEATE/REPORT absent. Honest: entry-stage work done, tail dead.

  - full_new_direction  (director_signoff, max_agent_hops=6, agents=[lit-scout, model-dataset-scout,
                         evidence-verifier, citation-integrity-auditor, gap-classifier])
        Both DISCOVER hard gates (evidence-verifier + citation-integrity-auditor) FIRE and PASS on a
        clean evidence base (router guardrail-1 makes them mandatory for a director_signoff DISCOVER
        entry); all five DISCOVER agents produce; DISCOVER checkpoints under the director gate's
        approve. Then the same dead IDEATE tail halts the run crashed_mid_stage. Honest: grounded
        DISCOVER done, no auto-advance into ungated betting/DESIGN.

Mirrors the helper/structure of test_m2_spine_slice.py + test_m3a_new_direction.py: the _env/_write/
_stage_dir helpers, run_task(...), validate_artifact==[] on every producer write, ledger verify_chain,
classify_status. Every artifact is attributed to an agent in the mode's own subset and produced by the
REAL deterministic tool-core where one exists (paper_ingest / evidence_scout / model_dataset_scout /
classify_gap / evidence_checker / citation_checker). READ-ONLY on all source; tested, NOT operated.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from research_agent_teams.orchestrator.engine import run_task
from research_agent_teams.tools.budget_tracker import BudgetExceeded
from research_agent_teams.tools.citation_checker import build_report as citation_report
from research_agent_teams.tools.classify_gap import build_classification
from research_agent_teams.tools.evidence_checker import build_verdict as evidence_verdict
from research_agent_teams.tools.evidence_scout import build_evidence_table
from research_agent_teams.tools.ledger import read_events, verify_chain
from research_agent_teams.tools.model_dataset_scout import build_candidates
from research_agent_teams.tools.paper_ingest import ingest_paper
from research_agent_teams.tools.runstore import classify_status
from research_agent_teams.tools.validate_artifact import validate_artifact

TS = "2026-06-09T00:00:00Z"
PROFILE = "cv-medical-segmentation"


class DeadTail(RuntimeError):
    """Raised by a producer when the engine drives a stage the mode has NO agent for.

    These three modes declare no stage_path, so the engine walks the full DISCOVER..REPORT tail,
    but every mode's subset is DISCOVER-only. Reaching any post-DISCOVER stage means there is no
    worker to honestly author its artifact — the producer refuses rather than fabricate one.
    """


# --------------------------------------------------------------------------- producer helpers
# (same shape as test_m2_spine_slice / test_m3a_new_direction)

def _env(atype, by, payload, status="approved"):
    return {"artifact_id": atype, "artifact_type": atype, "schema_version": "1.0.0",
            "created_by": by, "created_at": TS, "status": status, "payload": payload}


def _stage_dir(run_dir, stage) -> Path:
    d = Path(run_dir) / "evidence" / stage
    d.mkdir(parents=True, exist_ok=True)
    return d


def _write(path: Path, art: dict) -> Path:
    errs = validate_artifact(art)
    assert errs == [], f"producer wrote an invalid artifact: {errs}"
    path.write_text(json.dumps(art), encoding="utf-8")
    return path


def _approve(stage, tf):
    return "approved"


def _read_payload(run_dir, stage, name):
    p = Path(run_dir) / "evidence" / stage / name
    return json.loads(p.read_text(encoding="utf-8"))["payload"]


def _discover_artifact_files(run_dir, stage) -> list:
    d = Path(run_dir) / "evidence" / stage
    return sorted(p.name for p in d.glob("*.json")) if d.is_dir() else []


# --------------------------------------------------------------------------- shared DISCOVER fixtures

# Clean, saturated evidence base (>=3 sources, >=1 strong) — clears evidence-verifier's mechanical floor.
_SOURCES = [
    {"id": "s1", "kind": "paper", "ref": "[[hu-2021-lora]]", "claim_support": "strong"},
    {"id": "s2", "kind": "paper", "ref": "[[toothfairy-2025]]", "claim_support": "moderate"},
    {"id": "s3", "kind": "paper", "ref": "[[hdilemma-2024]]", "claim_support": "moderate"},
]
# A single anchored, supported claim — clears citation-integrity-auditor.
_CLAIM_LIST = {"source_scope": "new-direction gap scan",
               "claims": [{"claim_id": "c1", "text": "Adapter tuning is underexplored for promptable 3D seg.",
                           "source_ref": "[[hu-2021-lora]]"}]}
_CLAIM_EVIDENCE_MAP = {"mappings": [{"claim_id": "c1", "overall_support": "supported",
                                     "loci": [{"locus_id": "l1", "source_ref": "[[hu-2021-lora]]",
                                               "location": "Sec 5", "kind": "text",
                                               "reported_result": "named as open future work",
                                               "supports_claim": True}]}]}
# Gap signals carrying gap_id + evidence_ref + fields classify_gap keys off (anti-slop).
_GAP_SIGNALS = [
    {"gap_id": "GAP-1", "statement": "Adapter tuning underexplored for promptable 3D segmentation",
     "source_ref": "[[hu-2021-lora]]", "evidence_ref": ["[[hu-2021-lora]]"]},          # stated_open_problem
    {"gap_id": "GAP-2", "locus": "baseline evaluation", "opportunity": "equal-budget comparison",
     "evidence_ref": ["[[hdilemma-2024]]"]},                                            # methodological_gap
]


# =========================================================================== 1. ingest_paper
# record_only, max_agent_hops=1, agents=[literature-ingest]. The budget is the limiter.

def _make_ingest_producer(probe: dict):
    """A literature-ingest producer for ingest_paper. It is wired with a REAL paper_note built by
    tools.paper_ingest.ingest_paper, but it records whether it was ever CALLED — because the honest
    expectation is that the 1-hop budget bites before this producer runs at all."""

    def produce(stage, tf, run_dir, ts):
        probe["called"] = probe.get("called", 0) + 1
        d = _stage_dir(run_dir, stage)
        if stage == "DISCOVER":
            note = ingest_paper({
                "title": "LoRA: Low-Rank Adaptation of Large Language Models",
                "source_ref": "arxiv:2106.09685",
                "summary": "Freezes pretrained weights and learns rank-decomposition deltas.",
                "claims": ["LoRA matches full fine-tune on several tasks at a fraction of the parameters."],
            })
            return _write(d / "paper-note.artifact.json", _env("paper_note", "literature-ingest", note))
        raise DeadTail(f"ingest_paper has no agent for stage {stage} (DISCOVER-only subset)")

    return produce


def test_ingest_paper_budget_bites_before_its_single_stage(tmp_path):
    """ingest_paper's max_agent_hops=1 is so tight the stop-controller raises BudgetExceeded on the
    FIRST stage, before the literature-ingest producer ever runs — the honest reachable behaviour
    (a one-paper mode that cannot afford even its own single DISCOVER hop is NOT 'done')."""
    runs = tmp_path / "runs"
    probe: dict = {}
    with pytest.raises(BudgetExceeded, match=r"max_agent_hops reached: 1/1"):
        run_task(runs, "ip1", "把这篇论文收进库 / ingest this paper", "ingest_paper", TS,
                 _make_ingest_producer(probe), _approve, domain_profile_ref=PROFILE)
    run_dir = runs / "ip1"
    # the producer was NEVER called (budget bit first) and nothing was produced
    assert probe.get("called", 0) == 0
    assert not (run_dir / "evidence" / "DISCOVER").exists()
    assert run_dir.exists()                                   # the run dir/manifest were created at PARSE
    assert classify_status(run_dir) != "done"                # never reached done (honest)
    # the run never even opened its first stage -> no boundary -> not resumable-to-done either
    assert classify_status(run_dir) == "ready"


def test_ingest_paper_paper_note_core_builds_a_valid_artifact():
    """Honesty check that the literature-ingest agent's REAL tool-core is sound (the budget — not a
    broken producer — is why the mode can't run): tools.paper_ingest.ingest_paper builds a paper_note
    that passes the full artifact contract under the literature-ingest attribution."""
    note = ingest_paper({
        "title": "LoRA: Low-Rank Adaptation of Large Language Models",
        "source_ref": "arxiv:2106.09685",
        "summary": "Freezes pretrained weights and learns rank-decomposition deltas.",
        "claims": ["LoRA matches full fine-tune at a fraction of the parameters."],
    })
    assert validate_artifact(_env("paper_note", "literature-ingest", note)) == []


# =========================================================================== 2. gap_scan
# record_only, max_agent_hops=3, agents=[future-work-miner, weakness-spotter, gap-classifier].
# All three produce at DISCOVER; the dead IDEATE tail halts the run.

def _make_gap_scan_producer():
    """DISCOVER producer for gap_scan: emits one artifact per agent in the subset
    (future-work-miner -> future_work_items, weakness-spotter -> weakness_report,
    gap-classifier -> gap_classification via the REAL classify_gap core), then refuses the dead tail."""

    def produce(stage, tf, run_dir, ts):
        if stage != "DISCOVER":
            # NOTE: refuse BEFORE creating the stage dir, so the dead tail leaves no empty dir behind.
            raise DeadTail(f"gap_scan has no agent for stage {stage} (DISCOVER-only subset)")
        d = _stage_dir(run_dir, stage)
        # future-work-miner
        fw = {"items": [{"item_id": "FW-1",
                         "statement": "Adapter tuning underexplored for promptable 3D segmentation",
                         "source_ref": "[[hu-2021-lora]]"}]}
        _write(d / "future-work-items.artifact.json", _env("future_work_items", "future-work-miner", fw))
        # weakness-spotter (locus + opportunity -> a direct methodological_gap signal)
        wk = {"weaknesses": [{"gap_id": "WK-1", "locus": "baseline evaluation",
                              "opportunity": "equal-budget comparison removes the reported SOTA gap",
                              "evidence_ref": ["[[hdilemma-2024]]"]}]}
        _write(d / "weakness-report.artifact.json", _env("weakness_report", "weakness-spotter", wk))
        # gap-classifier (REAL classify_gap core over both hunters' signals)
        gc = build_classification(_GAP_SIGNALS)
        assert len(gc["gaps"]) == len(_GAP_SIGNALS)          # every identified gap classifies (no silent drop)
        return _write(d / "gap-classification.artifact.json", _env("gap_classification", "gap-classifier", gc))

    return produce


def test_gap_scan_completes_discover_then_halts_on_the_dead_ideate_tail(tmp_path):
    """gap_scan's 3 DISCOVER hunters all produce + DISCOVER checkpoints; then the engine drives the
    declared-but-dead IDEATE tail (no IDEATE agent in the subset) and the producer refuses -> the run
    halts crashed_mid_stage. Honest: entry-stage work done, the unreachable tail is not faked."""
    runs = tmp_path / "runs"
    with pytest.raises(DeadTail, match="no agent for stage IDEATE"):
        run_task(runs, "gs1", "扫一遍空白点 / gap scan", "gap_scan", TS,
                 _make_gap_scan_producer(), _approve, domain_profile_ref=PROFILE)
    run_dir = runs / "gs1"
    # DISCOVER fully produced (one artifact per agent in the subset) and checkpointed
    assert _discover_artifact_files(run_dir, "DISCOVER") == [
        "future-work-items.artifact.json", "gap-classification.artifact.json", "weakness-report.artifact.json"]
    assert classify_status(run_dir) == "crashed_mid_stage"   # died walking the dead tail, not done
    # the gap chain is contract-valid + the hunters are correctly attributed
    fw = json.loads((run_dir / "evidence" / "DISCOVER" / "future-work-items.artifact.json").read_text(encoding="utf-8"))
    wk = json.loads((run_dir / "evidence" / "DISCOVER" / "weakness-report.artifact.json").read_text(encoding="utf-8"))
    gc = json.loads((run_dir / "evidence" / "DISCOVER" / "gap-classification.artifact.json").read_text(encoding="utf-8"))
    assert fw["created_by"] == "future-work-miner"
    assert wk["created_by"] == "weakness-spotter"
    assert gc["created_by"] == "gap-classifier"
    assert {g["gap_type"] for g in gc["payload"]["gaps"]} == {"stated_open_problem", "methodological_gap"}
    # the dead tail produced NOTHING — no IDEATE/REPORT artifacts (a forward-skip would have needed stage_path)
    assert _discover_artifact_files(run_dir, "IDEATE") == []
    assert _discover_artifact_files(run_dir, "REPORT") == []
    # tamper-proof history is intact up to the crash boundary
    assert verify_chain(read_events(run_dir / "ledger.jsonl")) == []


def test_gap_scan_record_only_never_self_decides_a_gate(tmp_path):
    """gap_scan is record_only (a cheap scan, no commitment): the engine's director-gate branch never
    fires, so a gate_fn that would REJECT is never even consulted — the scan still runs DISCOVER and
    halts on the dead tail exactly as under approve. Proves record_only is gate-free here."""
    runs = tmp_path / "runs"

    def _explode_if_gated(stage, tf):
        raise AssertionError("record_only must NOT consult the director gate")

    with pytest.raises(DeadTail, match="no agent for stage IDEATE"):
        run_task(runs, "gs2", "gap scan, no gate", "gap_scan", TS,
                 _make_gap_scan_producer(), _explode_if_gated, domain_profile_ref=PROFILE)
    run_dir = runs / "gs2"
    assert _discover_artifact_files(run_dir, "DISCOVER") == [
        "future-work-items.artifact.json", "gap-classification.artifact.json", "weakness-report.artifact.json"]
    assert classify_status(run_dir) == "crashed_mid_stage"


# =========================================================================== 3. full_new_direction
# director_signoff, max_agent_hops=6, agents=[lit-scout, model-dataset-scout, evidence-verifier,
# citation-integrity-auditor, gap-classifier]. Both DISCOVER hard gates fire+pass; dead IDEATE tail halts.

def _make_full_new_direction_producer(evidence: str = "clean", citation: str = "clean"):
    """DISCOVER producer for full_new_direction: runs the two REAL DISCOVER hard gates first
    (evidence-verifier via evidence_checker, citation-integrity-auditor via citation_checker), then
    emits lit-scout (evidence_table), model-dataset-scout (candidates) and gap-classifier output.
    A gate BLOCK halts the run at DISCOVER; otherwise DISCOVER checkpoints and the dead tail halts it."""

    def produce(stage, tf, run_dir, ts):
        if stage != "DISCOVER":
            raise DeadTail(f"full_new_direction has no agent for stage {stage} (DISCOVER-only subset)")
        d = _stage_dir(run_dir, stage)
        # --- DISCOVER hard gate 1: evidence-verifier (ground the direction in verified evidence) ---
        sources = _SOURCES[:1] if evidence == "thin" else _SOURCES
        ev = evidence_verdict({"query": "gap scan for a new direction", "sources": sources,
                               "saturation_reached": True})
        _write(d / "evidence-verdict.artifact.json",
               _env("evidence_verdict", "evidence-verifier", ev, "blocked" if ev["verdict"] == "BLOCK" else "approved"))
        if ev["verdict"] == "BLOCK":
            raise DeadTail(f"evidence-verifier BLOCK: {ev['reasons']}")   # a hard-gate BLOCK halts DISCOVER
        # --- DISCOVER hard gate 2: citation-integrity-auditor ---
        cem = _CLAIM_EVIDENCE_MAP
        if citation == "contradicted":
            cem = {"mappings": [{"claim_id": "c1", "overall_support": "contradicted",
                                 "loci": [{"locus_id": "l1", "source_ref": "[[hu-2021-lora]]", "location": "Sec 5",
                                           "kind": "text", "reported_result": "claims it is already solved",
                                           "supports_claim": False}]}]}
        cv = citation_report(_CLAIM_LIST, cem)
        _write(d / "citation-verdict.artifact.json",
               _env("citation_integrity_verdict", "citation-integrity-auditor", cv,
                    "blocked" if cv["verdict"] == "BLOCK" else "approved"))
        if cv["verdict"] == "BLOCK":
            raise DeadTail(f"citation-integrity-auditor BLOCK: {cv['violations']}")
        # --- the rest of the DISCOVER subset (lit-scout + model-dataset-scout + gap-classifier) ---
        et = build_evidence_table("gap scan for a new direction", _SOURCES, saturation_reached=True)
        _write(d / "evidence-table.artifact.json", _env("evidence_table", "lit-scout", et))
        mc = build_candidates("promptable 3D medical segmentation",
                              [{"kind": "model", "name": "SAM-ViT-B", "ref": "[[sam-vit-b]]"},
                               {"kind": "dataset", "name": "ToothFairy3", "ref": "[[toothfairy-2025]]"}])
        _write(d / "model-dataset-candidates.artifact.json",
               _env("model_dataset_candidates", "model-dataset-scout", mc))
        gc = build_classification(_GAP_SIGNALS)
        return _write(d / "gap-classification.artifact.json", _env("gap_classification", "gap-classifier", gc))

    return produce


def test_full_new_direction_passes_both_discover_gates_then_halts_on_dead_tail(tmp_path):
    """full_new_direction (director_signoff) makes both DISCOVER hard gates mandatory; on a clean base
    they FIRE and PASS, all five DISCOVER agents produce, the director approves and DISCOVER checkpoints
    — then the dead IDEATE tail halts the run crashed_mid_stage. Honest: a grounded DISCOVER, with no
    auto-advance into ungated betting/DESIGN."""
    runs = tmp_path / "runs"
    with pytest.raises(DeadTail, match="no agent for stage IDEATE"):
        run_task(runs, "fnd1", "帮我找个研究方向 / find a direction", "full_new_direction", TS,
                 _make_full_new_direction_producer(), _approve, domain_profile_ref=PROFILE)
    run_dir = runs / "fnd1"
    # both DISCOVER hard gates fired and PASSED (the direction is grounded in verified evidence)
    assert _read_payload(run_dir, "DISCOVER", "evidence-verdict.artifact.json")["verdict"] == "PASS"
    assert _read_payload(run_dir, "DISCOVER", "citation-verdict.artifact.json")["verdict"] == "PASS"
    # all five DISCOVER agents produced, each attributed to a member of the mode's subset
    assert _discover_artifact_files(run_dir, "DISCOVER") == [
        "citation-verdict.artifact.json", "evidence-table.artifact.json", "evidence-verdict.artifact.json",
        "gap-classification.artifact.json", "model-dataset-candidates.artifact.json"]
    by = {json.loads((run_dir / "evidence" / "DISCOVER" / n).read_text(encoding="utf-8"))["created_by"]
          for n in _discover_artifact_files(run_dir, "DISCOVER")}
    assert by == {"evidence-verifier", "citation-integrity-auditor", "lit-scout",
                  "model-dataset-scout", "gap-classifier"}
    assert classify_status(run_dir) == "crashed_mid_stage"   # halted on the dead tail, not done
    # the dead tail produced NOTHING and the run did NOT auto-advance to betting/DESIGN
    assert not (run_dir / "evidence" / "IDEATE").exists()
    assert not (run_dir / "evidence" / "DESIGN").exists()
    assert not (run_dir / "evidence" / "REPORT").exists()
    assert verify_chain(read_events(run_dir / "ledger.jsonl")) == []


def test_full_new_direction_evidence_gate_is_live_and_blocks_thin_evidence(tmp_path):
    """Router guardrail-1 wires evidence-verifier as a mandatory DISCOVER hard gate for this mode:
    a too-thin evidence base BLOCKs at DISCOVER (before the run could even reach the dead tail),
    leaving the BLOCK verdict on the record and citation/lit-scout artifacts absent."""
    runs = tmp_path / "runs"
    with pytest.raises(DeadTail, match="evidence-verifier BLOCK"):
        run_task(runs, "fnd2", "ideate on thin evidence", "full_new_direction", TS,
                 _make_full_new_direction_producer(evidence="thin"), _approve, domain_profile_ref=PROFILE)
    run_dir = runs / "fnd2"
    assert _read_payload(run_dir, "DISCOVER", "evidence-verdict.artifact.json")["verdict"] == "BLOCK"
    # halted at the first hard gate: the later DISCOVER artifacts were never written
    assert "citation-verdict.artifact.json" not in _discover_artifact_files(run_dir, "DISCOVER")
    assert "evidence-table.artifact.json" not in _discover_artifact_files(run_dir, "DISCOVER")
    assert classify_status(run_dir) == "crashed_mid_stage"
    assert not (run_dir / "evidence" / "IDEATE").exists()


def test_full_new_direction_citation_gate_is_live_and_blocks_a_contradicted_claim(tmp_path):
    """The second DISCOVER hard gate (citation-integrity-auditor) is equally live: a contradicting
    locus BLOCKs at DISCOVER after the evidence gate passed, naming the contradicted claim."""
    runs = tmp_path / "runs"
    with pytest.raises(DeadTail, match="citation-integrity-auditor BLOCK"):
        run_task(runs, "fnd3", "ideate on a contradicted citation", "full_new_direction", TS,
                 _make_full_new_direction_producer(citation="contradicted"), _approve, domain_profile_ref=PROFILE)
    run_dir = runs / "fnd3"
    assert _read_payload(run_dir, "DISCOVER", "evidence-verdict.artifact.json")["verdict"] == "PASS"
    cv = _read_payload(run_dir, "DISCOVER", "citation-verdict.artifact.json")
    assert cv["verdict"] == "BLOCK"
    assert cv["contradicted_claims"] == ["c1"]               # the contradicted claim was named
    # lit-scout / model-dataset-scout never ran (halted at the citation gate)
    assert "evidence-table.artifact.json" not in _discover_artifact_files(run_dir, "DISCOVER")
    assert classify_status(run_dir) == "crashed_mid_stage"
    assert not (run_dir / "evidence" / "IDEATE").exists()
