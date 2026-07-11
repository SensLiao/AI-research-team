"""M3-a acceptance — the new-direction spine: the FREEDOM layer's smallest end-to-end slice.

A `new_direction` run drives DISCOVER -> IDEATE -> REPORT on fixtures through the real engine:
  DISCOVER  evidence-verifier + citation-integrity-auditor (the two real DISCOVER hard gates) ground
            the run in VERIFIED evidence, then gap-hunting (future_work_items -> gap_classification ->
            novelty_score);
  IDEATE    ideate (hypothesis_set -> idea_backlog, the ranked MENU);
  REPORT    presents the menu; then the run STOPS.

This proves the freedom-layer architecture + the director-in-the-loop model on the smallest build,
before the gap-hunting breadth / VR-1 venue investment. It drives the REAL deterministic cores
(evidence_checker / citation_checker / classify_gap / novelty_aggregate / feasibility_score) through
the proven control-plane engine.

The M3-a guarantees, all STRUCTURAL / demonstrable (not prose):
  1. EVIDENCE-GROUNDED: a new direction is high-stakes (it commits GPU + writing time), so the run is
     `director_signoff` and the DISCOVER hard gates FIRE — thin evidence or a contradicted citation
     BLOCKs before any ideation happens (no ideating on unverified evidence).
  2. NOVELTY IS SCORE-ONLY, NEVER A CUT: a LOW-novelty gap (single signal -> 0.25) still flows all the
     way into the idea_backlog and can even rank #1 on feasibility (novelty-paradox guard).
  3. THE MODEL NEVER SELF-BETS: idea_backlog is the ranked MENU only; its schema has no selected/chosen/
     bet/winner field. The director gate fires at the IDEATE boundary (the /idea-bet review): a reject
     halts the run; an approve lets the menu stand. The chosen bet is recorded only by the human
     /idea-bet gate as a separate adr (which always carries a standing PIVOT option, so even a 1-idea
     backlog is decidable and the director is never forced to bet).

Anti-slop runs end-to-end here (every gap / hypothesis / idea carries a non-blank evidence_ref, enforced
by the schemas). Tested, NOT operated on real research (director discipline); downstream experiment
rigor (DESIGN..VERIFY hard gates) fires only AFTER a bet.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from research_agent_teams.orchestrator.engine import run_task
from research_agent_teams.tools.citation_checker import build_report as citation_report
from research_agent_teams.tools.classify_gap import build_classification
from research_agent_teams.tools.evidence_checker import build_verdict as evidence_verdict
from research_agent_teams.tools.feasibility_score import build_idea_backlog
from research_agent_teams.tools.ledger import read_events, verify_chain
from research_agent_teams.tools.novelty_aggregate import aggregate_novelty
from research_agent_teams.tools.runstore import classify_status
from research_agent_teams.tools.validate_artifact import validate_against, validate_artifact

TS = "2026-06-09T00:00:00Z"


class GateBlock(RuntimeError):
    """Raised by a stage producer when a hard gate refuses — halts the run at that stage."""


# --------------------------------------------------------------------------- DISCOVER-gate fixtures

# evidence_table fed to evidence-verifier (kept in-memory; the gate's job is to verify it).
_EVIDENCE_CLEAN = {
    "query": "gap scan for a new promptable-3D-segmentation direction",
    "sources": [
        {"id": "s1", "kind": "paper", "ref": "[[hu-2021-lora]]", "claim_support": "strong"},
        {"id": "s2", "kind": "paper", "ref": "[[toothfairy-2025]]", "claim_support": "moderate"},
        {"id": "s3", "kind": "paper", "ref": "[[hdilemma-2024]]", "claim_support": "moderate"},
    ],
    "saturation_reached": True,
}
_EVIDENCE_THIN = {**_EVIDENCE_CLEAN, "sources": _EVIDENCE_CLEAN["sources"][:1]}  # 1 source -> BLOCK

# claim_list + claim_evidence_map fed to citation-integrity-auditor.
_CLAIMS_CLEAN = (
    {"source_scope": "new-direction gap scan",
     "claims": [{"claim_id": "c1", "text": "Adapter tuning is underexplored for promptable 3D seg.",
                 "source_ref": "[[hu-2021-lora]]"}]},
    {"mappings": [{"claim_id": "c1", "overall_support": "supported",
                   "loci": [{"locus_id": "l1", "source_ref": "[[hu-2021-lora]]", "location": "Sec 5",
                             "kind": "text", "reported_result": "named as open future work",
                             "supports_claim": True}]}]},
)
_CLAIMS_CONTRADICTED = (
    _CLAIMS_CLEAN[0],
    {"mappings": [{"claim_id": "c1", "overall_support": "contradicted",
                   "loci": [{"locus_id": "l1", "source_ref": "[[hu-2021-lora]]", "location": "Sec 5",
                             "kind": "text", "reported_result": "claims it is already solved",
                             "supports_claim": False}]}]},  # locus contradicts the claim -> BLOCK
)

# --------------------------------------------------------------------------- gap / ideate fixtures

# Gap signals mined from real KB paper_notes. Each carries gap_id + evidence_ref (anti-slop) + the
# fields classify_gap keys off + (optionally) cross-hunter derived_from signals. GAP-2 has a SINGLE
# provenance signal (only the reason_code bridge -> novelty 0.25, LOW) to prove low novelty is never cut.
_SIGNALS = [
    {"gap_id": "GAP-1", "statement": "Adapter tuning underexplored for promptable 3D segmentation",
     "source_ref": "[[hu-2021-lora]]", "evidence_ref": ["[[hu-2021-lora]]"],
     "derived_from": ["white_space_present"]},                                       # +future_work -> 0.50
    {"gap_id": "GAP-2", "statement": "No public fair-budget benchmark for SAM medical adaptation",
     "source_ref": "[[toothfairy-2025]]", "evidence_ref": ["[[toothfairy-2025]]"]},  # reason only -> 0.25 LOW
    {"gap_id": "GAP-3", "locus": "baseline evaluation", "opportunity": "equal-budget comparison",
     "evidence_ref": ["[[hdilemma-2024]]"],
     "derived_from": ["contrarian_angle", "empirically_untested"]},                  # +weakness_opportunity -> 0.75
]

_HYPOTHESES = [
    {"hypothesis_id": "IH1", "statement": "A LoRA adapter matches full fine-tune for 3D prompts at equal budget.",
     "falsifiable_prediction": "Mean Dice(LoRA) >= Dice(full-ft) within 1% at equal GPU-hours on fold0.",
     "evidence_needed": ["equal-budget ablation"], "evidence_ref": ["GAP-1", "[[hu-2021-lora]]"]},
    {"hypothesis_id": "IH2", "statement": "A fair-budget benchmark reorders the SAM-medical leaderboard.",
     "falsifiable_prediction": "At equal GPU-hours, >=2 methods swap rank vs the published table.",
     "evidence_needed": ["re-run top-5 at equal budget"], "evidence_ref": ["GAP-2", "[[toothfairy-2025]]"]},
    {"hypothesis_id": "IH3", "statement": "Equal-budget baselining removes the reported SOTA gap.",
     "falsifiable_prediction": "The 3% SOTA margin shrinks below seed variance once budget is equalized.",
     "evidence_needed": ["variance study"], "evidence_ref": ["GAP-3", "[[hdilemma-2024]]"]},
]

# Feasibility is INDEPENDENT of novelty: IDEA-2 derives from the LOW-novelty GAP-2 yet is the MOST
# feasible -> it must rank #1, proving novelty never gated it.
_IDEAS = [
    {"idea_id": "IDEA-1", "summary": "LoRA-vs-full-ft equal-budget ablation for promptable 3D seg.",
     "evidence_ref": ["IH1", "GAP-1"], "from_hypothesis_ref": "IH1",
     "feasibility": {"compute": "medium", "data": "available", "time": "medium"}},          # ~0.733
    {"idea_id": "IDEA-2", "summary": "Build the fair-budget SAM-medical benchmark and re-rank the leaderboard.",
     "evidence_ref": ["IH2", "GAP-2"], "from_hypothesis_ref": "IH2", "novelty_ref": "GAP-2",
     "feasibility": {"compute": "low", "data": "available", "time": "short"}},               # 1.0 -> rank 1
    {"idea_id": "IDEA-3", "summary": "Variance-corrected equal-budget re-baselining of the SOTA claim.",
     "evidence_ref": ["IH3", "GAP-3"], "from_hypothesis_ref": "IH3",
     "feasibility": {"compute": "high", "data": "restricted", "time": "long"}},              # 0.3 -> rank 3
]

LOW_NOVELTY_GAP = "GAP-2"
LOW_NOVELTY_IDEA = "IDEA-2"


# --------------------------------------------------------------------------- producer helpers

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


def make_new_direction_agent(evidence: str = "clean", citation: str = "clean"):
    """A single producer driving all 3 stages of new_direction through the REAL deterministic cores.
    `evidence`/`citation` ∈ {clean, thin/contradicted} drive the DISCOVER hard gates to PASS or BLOCK."""

    def produce(stage, tf, run_dir, ts):
        d = _stage_dir(run_dir, stage)

        if stage == "DISCOVER":
            # --- DISCOVER hard gate 1: evidence-verifier (ground ideation in verified evidence) ---
            table = _EVIDENCE_THIN if evidence == "thin" else _EVIDENCE_CLEAN
            ev = evidence_verdict(table)
            _write(d / "evidence-verdict.artifact.json",
                   _env("evidence_verdict", "evidence-verifier", ev,
                        "blocked" if ev["verdict"] == "BLOCK" else "approved"))
            if ev["verdict"] == "BLOCK":
                raise GateBlock(f"evidence BLOCK: {ev['reasons']}")

            # --- DISCOVER hard gate 2: citation-integrity-auditor ---
            cl, cem = _CLAIMS_CONTRADICTED if citation == "contradicted" else _CLAIMS_CLEAN
            cv = citation_report(cl, cem)
            _write(d / "citation-verdict.artifact.json",
                   _env("citation_integrity_verdict", "citation-integrity-auditor", cv,
                        "blocked" if cv["verdict"] == "BLOCK" else "approved"))
            if cv["verdict"] == "BLOCK":
                raise GateBlock(f"citation BLOCK: {cv['violations']}")

            # --- gap-hunting chain (REAL classify_gap + novelty_aggregate) ---
            fw = {"items": [{"item_id": f"FW-{i+1}", "statement": s["statement"], "source_ref": s["source_ref"]}
                            for i, s in enumerate(_SIGNALS) if "statement" in s]}
            _write(d / "future-work-items.artifact.json", _env("future_work_items", "future-work-miner", fw))

            gc = build_classification(_SIGNALS)
            assert len(gc["gaps"]) == len(_SIGNALS), "every signal must classify (no silent drop in this fixture)"
            _write(d / "gap-classification.artifact.json", _env("gap_classification", "gap-classifier", gc))

            # FIX: feed the gap_classification gaps DIRECTLY (they carry derived_from + a reason_code that
            # bridges to a provenance signal) — the true runtime path, no re-injection of upstream signals.
            ns = aggregate_novelty(gc["gaps"])
            return _write(d / "novelty-score.artifact.json", _env("novelty_score", "novelty-scorer", ns))

        if stage == "IDEATE":
            hs = {"hypotheses": _HYPOTHESES}
            _write(d / "hypothesis-set.artifact.json", _env("hypothesis_set", "hypothesis-generator", hs))
            backlog = build_idea_backlog(_IDEAS)
            return _write(d / "idea-backlog.artifact.json", _env("idea_backlog", "feasibility-reranker", backlog))

        if stage == "REPORT":
            note = {"summary": "new-direction menu: 3 evidence-bound ideas ranked by feasibility; awaiting /idea-bet",
                    "references": [], "produced_artifacts": [], "open_questions": []}
            return _write(d / "report-note.artifact.json", _env("report_note", "research-orchestrator", note))

        raise AssertionError(f"unexpected stage {stage}")

    return produce


def _approve(stage, tf):
    return "approved"


def _reject_at(stage_to_reject):
    def gate(stage, tf):
        return "reject" if stage == stage_to_reject else "approved"
    return gate


def _read_payload(run_dir, stage, name):
    p = Path(run_dir) / "evidence" / stage / name
    return json.loads(p.read_text(encoding="utf-8"))["payload"]


# --------------------------------------------------------------------------- 1. end-to-end happy path

def test_new_direction_runs_end_to_end_to_idea_backlog(tmp_path):
    runs = tmp_path / "runs"
    m = run_task(runs, "nd1", "find me a direction worth betting on", "new_direction", TS,
                 make_new_direction_agent(), _approve)
    assert m["status"] == "done"
    assert [c["stage"] for c in m["completed_work"]] == ["DISCOVER", "IDEATE", "REPORT"]
    run_dir = runs / "nd1"
    # the two DISCOVER hard gates FIRED and PASSED (ideation is grounded in verified evidence)
    assert _read_payload(run_dir, "DISCOVER", "evidence-verdict.artifact.json")["verdict"] == "PASS"
    assert _read_payload(run_dir, "DISCOVER", "citation-verdict.artifact.json")["verdict"] == "PASS"
    # the gap chain + the menu were produced and are contract-valid
    assert len(_read_payload(run_dir, "DISCOVER", "novelty-score.artifact.json")["scores"]) == 3
    assert len(_read_payload(run_dir, "IDEATE", "idea-backlog.artifact.json")["ranked_ideas"]) == 3
    # tamper-proof history intact + observable
    assert verify_chain(read_events(run_dir / "ledger.jsonl")) == []
    assert classify_status(run_dir) == "done"


# --------------------------------------------------------------------------- 2. DISCOVER gates are LIVE

def test_discover_evidence_gate_is_live_and_blocks_thin_evidence(tmp_path):
    runs = tmp_path / "runs"
    with pytest.raises(GateBlock):
        run_task(runs, "nd2", "ideate on thin evidence", "new_direction", TS,
                 make_new_direction_agent(evidence="thin"), _approve)
    run_dir = runs / "nd2"
    assert _read_payload(run_dir, "DISCOVER", "evidence-verdict.artifact.json")["verdict"] == "BLOCK"
    assert not (run_dir / "evidence" / "IDEATE").exists()  # never ideated on unverified evidence


def test_discover_citation_gate_is_live_and_blocks_a_contradicted_claim(tmp_path):
    runs = tmp_path / "runs"
    with pytest.raises(GateBlock):
        run_task(runs, "nd3", "ideate on a contradicted citation", "new_direction", TS,
                 make_new_direction_agent(citation="contradicted"), _approve)
    run_dir = runs / "nd3"
    assert _read_payload(run_dir, "DISCOVER", "citation-verdict.artifact.json")["verdict"] == "BLOCK"
    assert not (run_dir / "evidence" / "IDEATE").exists()


# --------------------------------------------------------------------------- 3. menu is ranked + evidence-bound

def test_idea_backlog_is_ranked_by_feasibility_and_every_idea_is_evidence_bound(tmp_path):
    runs = tmp_path / "runs"
    run_task(runs, "nd4", "rank directions", "new_direction", TS, make_new_direction_agent(), _approve)
    ideas = _read_payload(runs / "nd4", "IDEATE", "idea-backlog.artifact.json")["ranked_ideas"]
    assert [i["rank"] for i in ideas] == [1, 2, 3]                          # contiguous ranks
    scores = [i["feasibility"]["score"] for i in ideas]
    assert scores == sorted(scores, reverse=True)                          # ordered by feasibility DESC
    assert all(i["evidence_ref"] for i in ideas)                           # anti-slop end-to-end
    assert ideas[0]["idea_id"] == LOW_NOVELTY_IDEA                         # most feasible (from the LOW-novelty gap)


# --------------------------------------------------------------------------- 4. the model never self-bets

def test_idea_backlog_produced_by_the_run_carries_no_self_bet(tmp_path):
    runs = tmp_path / "runs"
    run_task(runs, "nd5", "produce a menu", "new_direction", TS, make_new_direction_agent(), _approve)
    backlog = _read_payload(runs / "nd5", "IDEATE", "idea-backlog.artifact.json")
    assert not (set(backlog) & {"selected", "chosen", "bet", "winner"})
    for idea in backlog["ranked_ideas"]:
        assert not (set(idea) & {"selected", "chosen", "bet", "winner"})


def test_idea_backlog_schema_rejects_a_self_bet_field():
    """Structural no-self-bet: a model that tries to inject a pick is schema-REJECTED."""
    good = {"ranked_ideas": [{"idea_id": "IDEA-1", "rank": 1, "summary": "x",
                              "feasibility": {"score": 0.7}, "evidence_ref": ["IH1"]}]}
    assert validate_against("idea_backlog.schema.json", good) == []
    assert validate_against("idea_backlog.schema.json", {**good, "selected": "IDEA-1"}) != []
    bad_item = {"ranked_ideas": [{**good["ranked_ideas"][0], "selected": True}]}
    assert validate_against("idea_backlog.schema.json", bad_item) != []


# --------------------------------------------------------------------------- 5. novelty is score-only, never a cut

def test_low_novelty_gap_survives_all_the_way_into_the_backlog(tmp_path):
    runs = tmp_path / "runs"
    run_task(runs, "nd6", "do not let novelty cut a direction", "new_direction", TS,
             make_new_direction_agent(), _approve)
    run_dir = runs / "nd6"
    ns = _read_payload(run_dir, "DISCOVER", "novelty-score.artifact.json")
    low = next(s for s in ns["scores"] if s["gap_id"] == LOW_NOVELTY_GAP)
    assert low["novelty"] == 0.25                                    # genuinely low (single-signal gap)
    backlog = _read_payload(run_dir, "IDEATE", "idea-backlog.artifact.json")
    assert LOW_NOVELTY_IDEA in [i["idea_id"] for i in backlog["ranked_ideas"]]  # ...yet survives to the menu
    assert all("novelty" not in i and "cut" not in i for i in backlog["ranked_ideas"])  # no cut vector


# --------------------------------------------------------------------------- 6. director gate halts; only /idea-bet bets

def test_director_gate_reject_at_ideate_halts_the_run(tmp_path):
    """The /idea-bet director review at the IDEATE boundary is a REAL gate: a reject ('none of these')
    halts the run before REPORT. The director saw the menu (idea_backlog) and rejected it."""
    runs = tmp_path / "runs"
    with pytest.raises(RuntimeError, match="director rejected"):
        run_task(runs, "nd7", "director rejects the whole menu", "new_direction", TS,
                 make_new_direction_agent(), _reject_at("IDEATE"))
    run_dir = runs / "nd7"
    assert (run_dir / "evidence" / "IDEATE" / "idea-backlog.artifact.json").exists()  # menu was produced
    assert not (run_dir / "evidence" / "REPORT").exists()                              # run halted before REPORT


def test_machine_only_produces_the_menu_the_bet_lives_only_in_an_idea_bet_adr(tmp_path):
    runs = tmp_path / "runs"
    m = run_task(runs, "nd8", "menu then human bet", "new_direction", TS, make_new_direction_agent(), _approve)
    run_dir = runs / "nd8"
    assert [c["stage"] for c in m["completed_work"]] == ["DISCOVER", "IDEATE", "REPORT"]
    assert not (run_dir / "evidence" / "DESIGN").exists()              # did not auto-advance to betting/DESIGN
    produced = [p.name for p in (run_dir / "evidence").rglob("*.json")]
    assert not any("idea-bet" in n or ".adr." in n for n in produced), f"machine must not self-bet: {produced}"

    # the /idea-bet HUMAN gate is the ONLY writer of the bet — recorded as an adr (with a standing PIVOT
    # option, so the menu is always decidable) that validates.
    backlog = _read_payload(run_dir, "IDEATE", "idea-backlog.artifact.json")
    options = [f"{i['idea_id']}: {i['summary']}" for i in backlog["ranked_ideas"]]
    options.append("PIVOT: do not bet on any listed idea — re-scope the direction")
    director_bet = {
        "decision_id": "ADR-0100",
        "question": "Which idea to bet on for run nd8?",
        "options": options,
        "chosen_option": options[0],
        "reason": "Lowest compute, public data, fastest to a result — best fit for the current GPU budget.",
        "status": "approved",
        "approved_by": "director",
        "approved_at": "2026-06-09T10:00:00Z",
    }
    assert validate_against("adr.schema.json", director_bet) == []
    assert "chosen_option" not in backlog          # the bet exists ONLY in the human adr
