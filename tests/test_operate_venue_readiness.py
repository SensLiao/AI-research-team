"""Operate acceptance — drive `venue_readiness` through the STEP-WISE spine (operate.spine +
modes.venue_readiness) the way the research-orchestrator skill does, with stub worker bundles in
place of live sub-agents. Proves the operated twin of the mode-registry venue chain:

  - the blind 3-persona panel produces contract-valid venue_profile + venue_review artifacts and a
    DERIVED venue_readiness_verdict (venue_score.py is the single source of truth — never self-set);
  - the deterministic independence check turns an echo-chamber panel into DEGRADED-REVIEW
    (information for the director, NOT a GateBlock);
  - the structural gates BLOCK: a missing adversarial seat, a venue_id mismatch;
  - a fired reject-trigger forces NOT-YET with a non-empty unresolved list (schema allOf holds);
  - the verdict's evidence_ref points at the REAL review artifact paths.

The ONLY difference from a live run is fixture bundles instead of real reviewing — the deterministic
governance + derivation are the real cores. Run ONLY this file + test_operate_full_rigor.py.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from research_agent_teams.operate import spine
from research_agent_teams.operate.artifacts import GateBlock
from research_agent_teams.operate.modes import venue_readiness as vr
from research_agent_teams.tools.ledger import read_events, verify_chain
from research_agent_teams.tools.validate_artifact import validate_artifact

TS = "2026-06-13T00:00:00Z"
VENUE = "NeurIPS-2025"
REQUEST = "assess venue readiness of the LoRA segmentation method manuscript for NeurIPS"
NORTH_STAR = {"statement": "judge whether the LoRA segmentation method is ready for NeurIPS",
              "in_scope": ["LoRA segmentation method", "venue readiness"],
              "out_of_scope": ["diffusion"]}


# --------------------------------------------------------------------------- fixtures

def _profile(personas=("methodology", "domain", "adversarial"), venue_id=VENUE):
    return {"venue_profile": {
        "venue_id": venue_id, "tier": "conf", "paper_type": "methodological",
        "dimension_weights": {"D1": {"weight": 1.0, "gating": True}, "D2": {"weight": 1.0},
                              "D3": {"weight": 1.0}, "D4": {"weight": 1.5, "gating": True},
                              "D5": {"weight": 1.0}, "D6": {"weight": 0.5}, "D7": {"weight": 0.0}},
        "reject_triggers": [{"trigger_id": "RT-D4-BASELINE", "dimension": "D4",
                             "description": "baseline is under-tuned or unfair",
                             "our_risk": "the equal-budget baseline must be verified"}],
        "accept_condition": "D1>=3 AND D4>=3 AND (D3>=3 OR D2>=3) AND no reject-trigger",
        "anti_bias_suppressors": ["hasn't beaten SOTA alone"],
        "personas": list(personas),
        "evidence_ref": ["agents/references/venue-rubrics/tier1-conf-ml.md", "manuscript.pdf"],
    }}


# Three DISTINCT reviews (deliberately divergent vocabulary -> low pairwise lexical similarity) that
# all clear the accept-condition with no fired trigger -> MEETS-BAR. Per-review anchor coverage is not
# needed for the drift gate: the combined drift text already carries the venue_id ('NeurIPS') anchor,
# so the notes are free to read very differently, keeping the independence check 'ok'.
def _accept_reviews(venue_id=VENUE):
    return {
        "methodology": {"venue_review": {
            "persona": "methodology", "venue_id": venue_id,
            "dimension_scores": {
                "D1": {"score": 3, "evidence_ref": ["Sec 3.2 proof"],
                       "notes": "lemma derivation holds; convergence assumptions enumerated upfront"},
                "D4": {"score": 4, "evidence_ref": ["Table 2 protocol"],
                       "notes": "matched-budget ablation grid spans both learning-rate regimes"},
                "D3": {"score": 3, "evidence_ref": ["Sec 2 related work"],
                       "notes": "low-rank reparameterization differs meaningfully from prior tuning"}},
            "reject_triggers_fired": [], "overall": "Weak Accept", "confidence": 4,
            "evidence_ref": ["Sec 3.2", "Table 2"]}},
        "domain": {"venue_review": {
            "persona": "domain", "venue_id": venue_id,
            "dimension_scores": {
                "D1": {"score": 3, "evidence_ref": ["Fig 4 qualitative"],
                       "notes": "vessel topology preserved; radiologist-plausible boundary contours"},
                "D4": {"score": 3, "evidence_ref": ["Sec 4.1 splits"],
                       "notes": "subject-disjoint folds eliminate inter-patient information bleed"},
                "D2": {"score": 3, "evidence_ref": ["Sec 5 discussion"],
                       "notes": "clinical value lands in scarce-annotation hospital deployment"}},
            "reject_triggers_fired": [], "overall": "Accept", "confidence": 4,
            "evidence_ref": ["Fig 4", "Sec 4.1"]}},
        "adversarial": {"venue_review": {
            "persona": "adversarial", "venue_id": venue_id,
            "dimension_scores": {
                "D1": {"score": 3, "evidence_ref": ["repo eval.py:120"],
                       "notes": "rebuilt the harness end to end; outputs replicate barring float jitter"},
                "D3": {"score": 3, "evidence_ref": ["repo model.py:42"],
                       "notes": "weight-delta trick is genuinely distinct, not a renamed wrapper"},
                "D4": {"score": 3, "evidence_ref": ["repo train.py:80"],
                       "notes": "traced dataloaders; nothing leaks, rivals receive identical sweeps"}},
            "reject_triggers_fired": [], "overall": "Borderline", "confidence": 5,
            "evidence_ref": ["repo eval.py:120", "repo train.py:80", "repo model.py:42"]}},
    }


def _echo_reviews(venue_id=VENUE):
    """Three near-identical reviews — an echo chamber the independence check must catch."""
    same_note = "the equal-budget baseline evaluation protocol is rigorous and the segmentation method is sound"
    base = {
        "dimension_scores": {
            "D1": {"score": 3, "evidence_ref": ["Sec 3"], "notes": same_note},
            "D4": {"score": 3, "evidence_ref": ["Table 2"], "notes": same_note},
            "D3": {"score": 3, "evidence_ref": ["Sec 2"], "notes": same_note}},
        "reject_triggers_fired": [], "overall": "Weak Accept", "confidence": 4,
        "evidence_ref": ["Sec 3", "Table 2"]}
    out = {}
    for persona in ("methodology", "domain", "adversarial"):
        out[persona] = {"venue_review": {**base, "persona": persona, "venue_id": venue_id}}
    return out


def _reviews_with_fired_trigger(venue_id=VENUE):
    """Accept-clearing scores BUT the adversarial reviewer fires a real reject-trigger -> NOT-YET."""
    reviews = _accept_reviews(venue_id)
    reviews["adversarial"]["venue_review"]["reject_triggers_fired"] = [
        {"trigger_id": "RT-D4-BASELINE", "dimension": "D4",
         "locus": "Table 2, baseline column",
         "required_fix": "tune the baseline to equal compute and re-report"}]
    return reviews


# --------------------------------------------------------------------------- drivers

def _bundle(run_dir, name, payload):
    inbox = Path(run_dir) / "inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    (inbox / name).write_text(json.dumps(payload), encoding="utf-8")


def _stage_bundles(run_dir, profile, reviews):
    _bundle(run_dir, "VERIFY.profile.bundle.json", profile)
    for persona, payload in reviews.items():
        _bundle(run_dir, f"VERIFY.review.{persona}.bundle.json", payload)


def _validate_written(paths):
    for p in paths:
        art = json.loads(Path(p).read_text(encoding="utf-8"))
        assert validate_artifact(art) == [], f"artifact failed contract: {p}"


def _begin(runs, run_id, north_star=NORTH_STAR):
    return spine.begin(str(runs), run_id, REQUEST, "venue_readiness", TS, north_star=north_star)


# --------------------------------------------------------------------------- 1. happy path -> MEETS-BAR

def test_venue_readiness_happy_path_meets_bar(tmp_path):
    runs = tmp_path / "runs"
    plan = _begin(runs, "vr1")
    rd = plan["run_dir"]
    assert plan["stages"] == ["VERIFY", "REPORT"]

    _stage_bundles(rd, _profile(), _accept_reviews())
    spine.open_stage(rd, "VERIFY", TS)
    paths, rep = vr.run_dets(rd, "VERIFY", TS)
    res = spine.commit_stage(rd, "VERIFY", paths, TS)

    assert rep["verdict"] == "MEETS-BAR"
    assert rep["unresolved_triggers"] == 0
    assert rep["independence_max_sim"] < vr.INDEPENDENCE_SIM_THRESHOLD
    assert rep["personas"] == ["adversarial", "domain", "methodology"]
    assert res["gate"] == "director_signoff"

    # all 4 artifacts (profile + 3 reviews) + verdict + drift are contract-valid
    _validate_written(paths)
    assert sum("review-" in p for p in paths) == 3
    assert any("venue-profile" in p for p in paths)

    # the verdict's evidence_ref points at the REAL review artifact paths (run-relative)
    verdict = json.loads((Path(rd) / "evidence" / "VERIFY" /
                          "venue-readiness-verdict.artifact.json").read_text())["payload"]
    assert verdict["verdict"] == "MEETS-BAR"
    assert len(verdict["evidence_ref"]) == 3
    for ref in verdict["evidence_ref"]:
        assert (Path(rd) / ref).is_file(), f"evidence_ref must be a real path: {ref}"
    assert verify_chain(read_events(Path(rd) / "ledger.jsonl")) == []


# --------------------------------------------------------------------------- 2. echo chamber -> DEGRADED-REVIEW

def test_venue_readiness_echo_chamber_is_degraded_not_blocked(tmp_path):
    runs = tmp_path / "runs"
    rd = _begin(runs, "vr2")["run_dir"]
    _stage_bundles(rd, _profile(), _echo_reviews())
    spine.open_stage(rd, "VERIFY", TS)
    # an echo chamber is INFORMATION (a degraded verdict), never a structural GateBlock
    paths, rep = vr.run_dets(rd, "VERIFY", TS)
    assert rep["independence_max_sim"] >= vr.INDEPENDENCE_SIM_THRESHOLD
    assert rep["verdict"] == "DEGRADED-REVIEW"
    _validate_written(paths)
    spine.commit_stage(rd, "VERIFY", paths, TS)  # commits fine — it is a real, valid verdict


# --------------------------------------------------------------------------- 3. missing adversarial -> BLOCK

def test_venue_readiness_blocks_missing_adversarial_persona(tmp_path):
    runs = tmp_path / "runs"
    rd = _begin(runs, "vr3")["run_dir"]
    reviews = _accept_reviews()
    del reviews["adversarial"]                                   # only 2 of 3 seats filled
    _stage_bundles(rd, _profile(), reviews)
    spine.open_stage(rd, "VERIFY", TS)
    with pytest.raises(GateBlock) as ei:
        vr.run_dets(rd, "VERIFY", TS)
    msg = str(ei.value).lower()
    assert "adversarial" in msg
    assert not (Path(rd) / "evidence" / "VERIFY" /
                "venue-readiness-verdict.artifact.json").exists()


# --------------------------------------------------------------------------- 4. venue_id mismatch -> BLOCK

def test_venue_readiness_blocks_venue_id_mismatch(tmp_path):
    runs = tmp_path / "runs"
    rd = _begin(runs, "vr4")["run_dir"]
    reviews = _accept_reviews()
    reviews["domain"]["venue_review"]["venue_id"] = "ICML-2025"   # calibrated to the wrong venue
    _stage_bundles(rd, _profile(), reviews)
    spine.open_stage(rd, "VERIFY", TS)
    with pytest.raises(GateBlock) as ei:
        vr.run_dets(rd, "VERIFY", TS)
    assert "venue_id" in str(ei.value)


# --------------------------------------------------------------------------- 5. fired trigger -> NOT-YET

def test_venue_readiness_fired_trigger_is_not_yet_with_unresolved(tmp_path):
    runs = tmp_path / "runs"
    rd = _begin(runs, "vr5")["run_dir"]
    _stage_bundles(rd, _profile(), _reviews_with_fired_trigger())
    spine.open_stage(rd, "VERIFY", TS)
    paths, rep = vr.run_dets(rd, "VERIFY", TS)
    assert rep["verdict"] == "NOT-YET"
    assert rep["unresolved_triggers"] >= 1
    verdict = json.loads((Path(rd) / "evidence" / "VERIFY" /
                          "venue-readiness-verdict.artifact.json").read_text())["payload"]
    # schema allOf: non-empty unresolved_reject_triggers forces a non-accept verdict
    assert verdict["unresolved_reject_triggers"] == ["RT-D4-BASELINE"]
    assert verdict["verdict"] in ("NOT-YET", "WRONG-PATH", "DEGRADED-REVIEW")
    assert verdict["gaps"]                                       # a NOT-YET populates gap-to-fix
    _validate_written(paths)


# --------------------------------------------------------------------------- 6. REPORT stage

def test_venue_readiness_report_stage_emits_note(tmp_path):
    runs = tmp_path / "runs"
    rd = _begin(runs, "vr6")["run_dir"]
    _stage_bundles(rd, _profile(), _accept_reviews())
    spine.open_stage(rd, "VERIFY", TS)
    paths, _ = vr.run_dets(rd, "VERIFY", TS)
    spine.commit_stage(rd, "VERIFY", paths, TS)

    spine.open_stage(rd, "REPORT", TS)
    rpaths, _ = vr.run_dets(rd, "REPORT", TS)
    res = spine.commit_stage(rd, "REPORT", rpaths, TS)
    assert res["done"] is True
    note = json.loads(Path(rpaths[0]).read_text())["payload"]
    assert "venue-pick" in note["summary"] and "venue-decide" in note["summary"]
    _validate_written(rpaths)


# --------------------------------------------------------------------------- 7. llm_step dispatch shape

def test_venue_readiness_llm_step_multi_worker_shape(tmp_path):
    runs = tmp_path / "runs"
    rd = _begin(runs, "vr7")["run_dir"]
    spec = vr.llm_step(rd, "VERIFY", REQUEST, model_policy="default")
    # the venue panel: profile worker FIRST, then the three personas (they read its bundle)
    assert spec["label"] == "venue-panel" and "FIRST" in spec["note"]
    labels = [w["label"] for w in spec["workers"]]
    assert labels == ["venue-selector", "venue-reviewer-methodology",
                      "venue-reviewer-domain", "venue-reviewer-adversarial"]
    # reviewing is judgment with asymmetric cost: opus in BOTH model policies
    assert {w["model"] for w in spec["workers"]} == {"opus"}
    assert vr.llm_step(rd, "VERIFY", REQUEST, model_policy="max_quality")["workers"][0]["model"] == "opus"
    # every prompt carries the north-star block + a REPAIR clause; only the adversarial seat opens code
    for w in spec["workers"]:
        assert "NORTH STAR" in w["prompt"]
    assert "REPAIR ATTEMPT" in spec["workers"][1]["prompt"]
    assert "OPEN THE EVAL CODE" in spec["workers"][3]["prompt"]      # adversarial obligation
    assert "OPEN THE EVAL CODE" not in spec["workers"][1]["prompt"]  # methodology stays in lens
    # distinct output bundles; the profile worker writes the profile bundle the personas read
    assert len({w["output"] for w in spec["workers"]}) == 4
    assert spec["workers"][0]["output"].endswith("inbox/VERIFY.profile.bundle.json")
    assert vr.llm_step(rd, "REPORT", REQUEST) is None
