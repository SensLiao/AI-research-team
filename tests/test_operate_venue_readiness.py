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
from research_agent_teams.tools.venue_readiness_markdown import venue_readiness_path

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


def _review_config(run_ref="vr-run"):
    return {"review_config": {
        "run_ref": str(run_ref),
        "lenses": [
            {"lens": "methodology", "anchor": "D1 requires traceable soundness and D5 rerun evidence",
             "reviewer_agent": "venue-reviewer-methodology-blind"},
            {"lens": "domain", "anchor": "D2 requires consequential use and D6 precise communication",
             "reviewer_agent": "venue-reviewer-domain-blind"},
            {"lens": "adversarial", "anchor": "D3 requires a real delta and D4 equal-budget evaluation",
             "reviewer_agent": "venue-reviewer-adversarial-blind"},
        ],
        "synthesis_mandate": "Surface disagreements, classify fatal versus repairable gaps, and defer human gates.",
        "inputs_to_review": ["manuscript.pdf", "repo/eval.py", "repo/train.py"],
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


def _attestation(run_dir, persona, precommit):
    config = json.loads(
        (Path(run_dir) / vr.CONFIG_BUNDLE_REL).read_text(encoding="utf-8")
    )["review_config"]
    anchors = {row["lens"]: row["anchor"] for row in config["lenses"]}
    return {
        "protocol_version": vr.PROTOCOL_VERSION,
        "persona": persona,
        "reviewer_instance_id": f"venue-reviewer-{persona}-blind",
        "precommit_hash": precommit["precommit_hash"],
        "profile_ref": vr.PROFILE_REF,
        "config_ref": vr.CONFIG_REF,
        "precommit_ref": vr.PRECOMMIT_REF,
        "anchor_echo": anchors[persona],
        "input_refs": [
            "task_frame.artifact.json", vr.PROFILE_REF, vr.CONFIG_REF, vr.PRECOMMIT_REF,
            "manuscript.pdf",
        ],
        "other_review_refs_seen": [],
        "output_ref": vr._review_ref(persona),
    }


def _meta_review(reviews, panel_receipt):
    by_dim = {}
    for persona, bundle in reviews.items():
        for dim, row in bundle["venue_review"]["dimension_scores"].items():
            by_dim.setdefault(dim, []).append((persona, row["score"]))
    disagreements = []
    for dim, rows in sorted(by_dim.items()):
        scores = [score for _persona, score in rows]
        if len(scores) >= 2 and max(scores) != min(scores):
            disagreements.append({
                "dimension": dim,
                "personas": [persona for persona, _score in rows],
                "score_span": max(scores) - min(scores),
                "synthesis": "The stricter score is retained until the cited protocol evidence resolves the difference.",
                "evidence_ref": [vr._review_ref(persona) for persona, _score in rows],
            })
    fired = []
    for persona, bundle in reviews.items():
        for trigger in bundle["venue_review"].get("reject_triggers_fired") or []:
            fired.append((persona, trigger))
    if fired:
        persona, trigger = fired[0]
        strongest = {
            "status": "repairable",
            "reason": f"{trigger['trigger_id']} fires at {trigger['locus']} and blocks a positive submission screen.",
            "source_personas": [persona],
            "evidence_ref": [vr._review_ref(persona), trigger["locus"]],
        }
        repairable = [{
            "gap_id": "R1", "trigger_id": trigger["trigger_id"],
            "reason": trigger["required_fix"],
            "evidence_ref": [vr._review_ref(persona), trigger["locus"]],
            "responsible_stage": "EXECUTE",
        }]
    else:
        strongest = {
            "status": "repairable",
            "reason": "The D4 evaluation protocol is the strongest remaining challenge despite no fired trigger.",
            "source_personas": ["methodology", "adversarial"],
            "evidence_ref": [vr._review_ref("methodology"), vr._review_ref("adversarial")],
        }
        repairable = [{
            "gap_id": "R1",
            "reason": "Reconcile the D4 scoring difference with a documented equal-budget audit.",
            "evidence_ref": [vr._review_ref("methodology"), vr._review_ref("adversarial")],
            "responsible_stage": "VERIFY",
        }]
    return {"venue_meta_review": {
        "protocol_version": vr.PROTOCOL_VERSION,
        "precommit_hash": panel_receipt["precommit_hash"],
        "review_receipt_ref": vr.PANEL_RECEIPT_REF,
        "review_hashes": panel_receipt["review_hashes"],
        "reviewer_disagreements": disagreements,
        "strongest_reject_reason": strongest,
        "fatal_gaps": [],
        "repairable_gaps": repairable,
        "repair_sequence": [{
            "priority": 1, "gap_id": "R1",
            "action": repairable[0]["reason"],
            "responsible_stage": repairable[0]["responsible_stage"],
            "verification": "Repeat the blind D4 audit against the frozen rubric and compare evidence loci.",
        }],
        "human_gates": ["/venue-pick", "/venue-decide"],
        "advisory_only": True,
    }}


def _stage_bundles(run_dir, profile, reviews, *, finalize=True):
    _bundle(run_dir, "VERIFY.profile.bundle.json", profile)
    _bundle(run_dir, "VERIFY.review-config.bundle.json", _review_config(run_dir))
    precommit = vr.prepare_review_precommit(run_dir, TS)
    for persona, payload in reviews.items():
        strict_payload = dict(payload)
        strict_payload["blind_review_attestation"] = _attestation(run_dir, persona, precommit)
        _bundle(run_dir, f"VERIFY.review.{persona}.bundle.json", strict_payload)
    if finalize:
        panel_receipt = vr.prepare_review_panel_receipt(run_dir, TS)
        strict_reviews = {
            persona: json.loads(_review_path.read_text(encoding="utf-8"))
            for persona in reviews
            for _review_path in [Path(run_dir) / "inbox" / f"VERIFY.review.{persona}.bundle.json"]
        }
        _bundle(run_dir, "VERIFY.meta.bundle.json", _meta_review(strict_reviews, panel_receipt))


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
    assert rep["director_venue_readiness"].replace("\\", "/").endswith(
        "director-review/venue/venue-readiness.md"
    )
    venue_md = venue_readiness_path(rd)
    assert venue_md.is_file()
    venue_text = venue_md.read_text(encoding="utf-8")
    assert "Derived readiness verdict: `MEETS-BAR`" in venue_text
    assert VENUE in venue_text
    assert "## Blind Review Protocol" in venue_text
    assert "## Reviewer Disagreements" in venue_text
    assert "## Strongest Rejection Case" in venue_text
    assert "## Fatal Vs Repairable" in venue_text
    assert "## Repair Order" in venue_text
    assert "## Human Venue Gate" in venue_text
    assert "advisory_only: true" in venue_text
    assert "/venue-pick" in venue_text and "/venue-decide" in venue_text
    assert "not an acceptance fact" in venue_text
    assert not any("director-review/venue/venue-readiness.md" in p.replace("\\", "/") for p in paths)
    assert res["gate"] == "director_signoff"

    # frozen profile/config + 3 reviews + derived verdict + drift are contract-valid
    _validate_written(paths)
    assert sum(any(f"review-{persona}.artifact.json" in p for persona in vr.PERSONAS) for p in paths) == 3
    assert any("venue-profile" in p for p in paths)
    assert any("review-config" in p for p in paths)
    assert any("venue-meta-review.artifact.json" in p for p in paths)

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
    _stage_bundles(rd, _profile(), reviews, finalize=False)
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
    _stage_bundles(rd, _profile(), reviews, finalize=False)
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
    venue_text = venue_readiness_path(rd).read_text(encoding="utf-8")
    assert "Derived readiness verdict: `NOT-YET`" in venue_text
    assert "RT-D4-BASELINE" in venue_text
    assert "tune the baseline" in venue_text
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
    rpaths, rrep = vr.run_dets(rd, "REPORT", TS)
    res = spine.commit_stage(rd, "REPORT", rpaths, TS)
    assert res["done"] is True
    assert rrep["director_venue_readiness"].replace("\\", "/").endswith(
        "director-review/venue/venue-readiness.md"
    )
    note = json.loads(Path(rpaths[0]).read_text())["payload"]
    assert "venue-pick" in note["summary"] and "venue-decide" in note["summary"]
    assert "director-review/venue/venue-readiness.md" in note["references"]
    _validate_written(rpaths)


# --------------------------------------------------------------------------- 7. llm_step dispatch shape

def test_venue_readiness_llm_step_is_a_strict_staged_state_machine(tmp_path):
    runs = tmp_path / "runs"
    rd = _begin(runs, "vr7")["run_dir"]
    profile_step = vr.llm_step(rd, "VERIFY", REQUEST, model_policy="default")
    assert profile_step["label"] == "venue-selector"
    assert profile_step["output"].endswith("inbox/VERIFY.profile.bundle.json")
    assert "NORTH STAR" in profile_step["prompt"]

    _bundle(rd, "VERIFY.profile.bundle.json", _profile())
    config_step = vr.llm_step(rd, "VERIFY", REQUEST, model_policy="max_quality")
    assert config_step["label"] == "venue-review-configurator"
    assert config_step["output"].endswith("inbox/VERIFY.review-config.bundle.json")
    assert "Do not read the manuscript" in config_step["prompt"]

    _bundle(rd, "VERIFY.review-config.bundle.json", _review_config(rd))
    review_step = vr.llm_step(rd, "VERIFY", REQUEST)
    assert review_step["label"] == "venue-blind-review-panel"
    assert review_step["protocol_version"] == vr.PROTOCOL_VERSION
    assert (Path(rd) / vr.PRECOMMIT_RECEIPT_REL).is_file()
    labels = [worker["label"] for worker in review_step["workers"]]
    assert labels == ["venue-reviewer-methodology", "venue-reviewer-domain",
                      "venue-reviewer-adversarial"]
    assert len({worker["output"] for worker in review_step["workers"]}) == 3
    assert {worker["model"] for worker in review_step["workers"]} == {"opus"}
    for worker in review_step["workers"]:
        assert "NORTH STAR" in worker["prompt"]
        assert review_step["precommit_hash"] in worker["prompt"]
        assert vr.PROFILE_REF in worker["read_scope"]
        assert "inbox/VERIFY.review.*.bundle.json" in worker["forbidden_read_scope"]
        assert "another reviewer" in worker["prompt"]

    precommit = json.loads((Path(rd) / vr.PRECOMMIT_RECEIPT_REL).read_text(encoding="utf-8"))
    strict_reviews = {}
    for persona, payload in _accept_reviews().items():
        strict = {**payload, "blind_review_attestation": _attestation(rd, persona, precommit)}
        strict_reviews[persona] = strict
        _bundle(rd, f"VERIFY.review.{persona}.bundle.json", strict)
    meta_step = vr.llm_step(rd, "VERIFY", REQUEST)
    assert meta_step["label"] == "area-chair-synthesizer"
    assert meta_step["depends_on"] == ["freeze-blind-review-panel"]
    assert (Path(rd) / vr.PANEL_RECEIPT_REL).is_file()
    panel_receipt = json.loads((Path(rd) / vr.PANEL_RECEIPT_REL).read_text(encoding="utf-8"))
    _bundle(rd, "VERIFY.meta.bundle.json", _meta_review(strict_reviews, panel_receipt))
    assert vr.llm_step(rd, "VERIFY", REQUEST) is None
    assert vr.llm_step(rd, "REPORT", REQUEST) is None


def test_venue_precommit_blocks_any_reviewer_that_started_early(tmp_path):
    rd = _begin(tmp_path / "runs", "vr8")["run_dir"]
    _bundle(rd, "VERIFY.profile.bundle.json", _profile())
    _bundle(rd, "VERIFY.review-config.bundle.json", _review_config(rd))
    _bundle(rd, "VERIFY.review.methodology.bundle.json", _accept_reviews()["methodology"])
    with pytest.raises(GateBlock) as exc:
        vr.prepare_review_precommit(rd, TS)
    assert "before the venue profile/config precommit" in str(exc.value)


def test_venue_panel_blocks_reviewer_that_saw_another_review(tmp_path):
    rd = _begin(tmp_path / "runs", "vr9")["run_dir"]
    _bundle(rd, "VERIFY.profile.bundle.json", _profile())
    _bundle(rd, "VERIFY.review-config.bundle.json", _review_config(rd))
    precommit = vr.prepare_review_precommit(rd, TS)
    for persona, payload in _accept_reviews().items():
        attestation = _attestation(rd, persona, precommit)
        if persona == "domain":
            attestation["other_review_refs_seen"] = [vr._review_ref("methodology")]
        _bundle(rd, f"VERIFY.review.{persona}.bundle.json", {
            **payload, "blind_review_attestation": attestation,
        })
    with pytest.raises(GateBlock) as exc:
        vr.prepare_review_panel_receipt(rd, TS)
    assert "saw another review" in str(exc.value)


def test_venue_panel_blocks_reviewer_read_scope_escape(tmp_path):
    rd = _begin(tmp_path / "runs", "vr9b")["run_dir"]
    _bundle(rd, "VERIFY.profile.bundle.json", _profile())
    _bundle(rd, "VERIFY.review-config.bundle.json", _review_config(rd))
    precommit = vr.prepare_review_precommit(rd, TS)
    for persona, payload in _accept_reviews().items():
        attestation = _attestation(rd, persona, precommit)
        if persona == "domain":
            attestation["input_refs"].append("undeclared/private-review-draft.md")
        _bundle(rd, f"VERIFY.review.{persona}.bundle.json", {
            **payload, "blind_review_attestation": attestation,
        })
    with pytest.raises(GateBlock) as exc:
        vr.prepare_review_panel_receipt(rd, TS)
    assert "exceeded its blind read scope" in str(exc.value)


def test_venue_verify_blocks_frozen_profile_hash_tamper(tmp_path):
    rd = _begin(tmp_path / "runs", "vr10")["run_dir"]
    _stage_bundles(rd, _profile(), _accept_reviews())
    profile_path = Path(rd) / vr.PROFILE_ARTIFACT_REL
    artifact = json.loads(profile_path.read_text(encoding="utf-8"))
    artifact["payload"]["accept_condition"] = "D1>=1"
    profile_path.write_text(json.dumps(artifact), encoding="utf-8")
    spine.open_stage(rd, "VERIFY", TS)
    with pytest.raises(GateBlock) as exc:
        vr.run_dets(rd, "VERIFY", TS)
    assert "changed after freeze" in str(exc.value)


def test_venue_area_chair_cannot_start_before_panel_receipt(tmp_path):
    rd = _begin(tmp_path / "runs", "vr11")["run_dir"]
    _bundle(rd, "VERIFY.profile.bundle.json", _profile())
    _bundle(rd, "VERIFY.review-config.bundle.json", _review_config(rd))
    precommit = vr.prepare_review_precommit(rd, TS)
    _bundle(rd, "VERIFY.meta.bundle.json", {"venue_meta_review": {}})
    for persona, payload in _accept_reviews().items():
        _bundle(rd, f"VERIFY.review.{persona}.bundle.json", {
            **payload, "blind_review_attestation": _attestation(rd, persona, precommit),
        })
    with pytest.raises(GateBlock) as exc:
        vr.prepare_review_panel_receipt(rd, TS)
    assert "meta bundle exists before" in str(exc.value)
