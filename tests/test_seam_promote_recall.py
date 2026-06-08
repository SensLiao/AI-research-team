"""M3.5 — the M⇄D seam (recall read side + promote write side), proven through REGISTERED schemas.

The crown jewels of the seam:
  - the machine can NEVER self-promote: promotion is a human gate, and frozen/can-cite-thesis are
    RE-DERIVED from the ACTUAL audit artifacts, never from a self-claim (blueprint §0);
  - a `provisional` candidate is structurally non-promotable (DoD #6);
  - recall reads System D BY REFERENCE — the recall_note carries slug+sha pointers, never DB body.

Mirrors test_m3d_venue_readiness.py (derive-then-validate). No test writes the real PhD-Research-OS.
"""
from __future__ import annotations

import hashlib

from research_agent_teams.tools import promote, recall
from research_agent_teams.tools.validate_artifact import validate_payload


# ---------------- helpers ----------------

def _sig(leak=True, fair=True, freeze=True):
    return {"leakage_pass": leak, "fairness_pass": fair, "reviewer_approves_freeze": freeze}


def _candidate(slug="medsam3-lora-frozen-dice", status="provisional"):
    return {
        "slug": slug,
        "vault_type": "result",
        "project": "iac-cbct-seg",
        "title": "MedSAM3 LoRA frozen Dice",
        "source_result_status": status,
        "body": "Dice=0.79 on the frozen external test split.",
    }


# ---------------- re-derivation core (the safety center) ----------------

def test_promote_rejects_provisional():
    """DoD #6 core: no human freeze ⇒ ceiling holds ⇒ provisional ⇒ NOT admissible."""
    d = promote.rederive(leakage_pass=True, fairness_pass=True,
                         reviewer_approves_freeze=True, human_freeze=False)
    assert d["admissible"] is False
    assert d["rederived_result_status"] == "provisional"
    assert d["rederived_can_cite_thesis"] is False
    assert d["reasons"]  # non-empty derivation trace


def test_promote_admits_frozen_bundle():
    """All audits pass + reviewer approves freeze + human freeze ⇒ frozen + citable + admissible."""
    d = promote.rederive(leakage_pass=True, fairness_pass=True,
                         reviewer_approves_freeze=True, human_freeze=True)
    assert d["admissible"] is True
    assert d["rederived_result_status"] == "frozen"
    assert d["rederived_can_cite_thesis"] is True


def test_promote_blocks_on_reviewer_block():
    """adversarial-reviewer did not APPROVE-FREEZE ⇒ never frozen even with passing audits + freeze."""
    d = promote.rederive(leakage_pass=True, fairness_pass=True,
                         reviewer_approves_freeze=False, human_freeze=True)
    assert d["admissible"] is False
    assert d["rederived_result_status"] != "frozen"


def test_promote_blocks_on_failed_leakage_or_fairness():
    for leak, fair in ((False, True), (True, False)):
        d = promote.rederive(leakage_pass=leak, fairness_pass=fair,
                             reviewer_approves_freeze=True, human_freeze=True)
        assert d["admissible"] is False
        assert d["rederived_can_cite_thesis"] is False


def test_terminal_source_status_never_refreezes():
    """A source already invalid/superseded can never be re-frozen (status-registry terminal)."""
    for term in ("invalid", "superseded"):
        d = promote.rederive(leakage_pass=True, fairness_pass=True,
                             reviewer_approves_freeze=True, human_freeze=True,
                             source_result_status=term)
        assert d["admissible"] is False
        assert d["rederived_result_status"] == term


# ---------------- never trust a self-claim (extract from the REAL audits) ----------------

def test_extract_signals_reads_native_audit_vocab():
    sig = promote.extract_signals(
        {"verdict": "PASS", "violations": []},
        {"panel_role": "fairness", "pass": True, "violations": []},
        {"verdict": "APPROVE-FREEZE", "checks": []},
    )
    assert sig == {"leakage_pass": True, "fairness_pass": True,
                   "reviewer_approves_freeze": True, "reviewer_verdict": "APPROVE-FREEZE"}


def test_promote_ignores_forged_self_claim():
    """A candidate that SAYS it is frozen+citable, but whose REAL leakage audit is BLOCK, is rejected.
    Signals come from the actual audit artifact, not the candidate's self-claim."""
    forged = _candidate(status="frozen")           # self-claims frozen
    forged["can_cite_thesis"] = True               # self-claims citable (ignored by construction)
    signals = promote.extract_signals(
        {"verdict": "BLOCK", "violations": ["leakage smell on the test split"]},  # REAL audit: fail
        {"panel_role": "fairness", "pass": True, "violations": []},
        {"verdict": "APPROVE-FREEZE", "checks": []},
    )
    rec = promote.promote_to_vault(forged, signals=signals, human_freeze=True,
                                   vault_root="/nonexistent-never-written",
                                   decided_by="director", decided_at="2026-06-09T10:00:00Z")
    assert rec["admissible"] is False
    assert rec["vault_path"] is None
    assert validate_payload("promotion_record", rec) == []


# ---------------- schema integrity ----------------

def test_promotion_record_schema_validates_both_outcomes():
    reject = {
        "candidate_ref": {"path": "inbox/c.json", "sha256": "sha256:" + "a" * 64},
        "admissible": False, "rederived_result_status": "provisional",
        "rederived_can_cite_thesis": False, "reasons": ["no human_freeze"],
        "vault_path": None, "vault_slug": None,
        "decided_by": "director", "decided_at": "2026-06-09T10:00:00Z",
    }
    assert validate_payload("promotion_record", reject) == []
    admit = {
        "candidate_ref": {"path": "inbox/c.json", "sha256": "sha256:" + "b" * 64},
        "admissible": True, "rederived_result_status": "frozen",
        "rederived_can_cite_thesis": True, "reasons": ["admitted"],
        "vault_path": "/v/02-wiki/results/x.md", "vault_slug": "x",
        "decided_by": "director", "decided_at": "2026-06-09T10:00:00Z",
    }
    assert validate_payload("promotion_record", admit) == []


def test_promotion_record_schema_forbids_admissible_without_frozen():
    """Schema allOf safety net (independent of the tool): admissible=true with a non-frozen
    status is structurally REJECTED — a dead/forged 'admitted but provisional' record cannot exist."""
    bad = {
        "candidate_ref": {"path": "inbox/c.json", "sha256": "sha256:" + "c" * 64},
        "admissible": True, "rederived_result_status": "provisional",   # contradiction
        "rederived_can_cite_thesis": True,
        "reasons": ["forged"], "vault_path": "/v/x.md", "vault_slug": "x",
        "decided_by": "director", "decided_at": "2026-06-09T10:00:00Z",
    }
    assert validate_payload("promotion_record", bad) != []
    bad2 = dict(bad, rederived_result_status="frozen", rederived_can_cite_thesis=False)  # frozen but not citable
    assert validate_payload("promotion_record", bad2) != []


def test_recall_note_schema():
    good = {
        "query": "frozen dice results", "confidence": "high", "vault_silent": False,
        "citations": [{"slug": "medsam3-lora-ablation", "sha256": "sha256:" + "d" * 64,
                       "section": "Results", "supports": "dice row"}],
    }
    assert validate_payload("recall_note", good) == []
    # a citation missing sha is rejected
    bad = {"query": "x", "confidence": "low", "vault_silent": False,
           "citations": [{"slug": "medsam3-lora-ablation"}]}
    assert validate_payload("recall_note", bad) != []
    # a non-silent recall with zero citations is rejected (allOf)
    empty = {"query": "x", "confidence": "low", "vault_silent": False, "citations": []}
    assert validate_payload("recall_note", empty) != []
    # an invented (non-kebab) slug is rejected
    invented = {"query": "x", "confidence": "low", "vault_silent": False,
                "citations": [{"slug": "Not A Slug", "sha256": "sha256:" + "e" * 64}]}
    assert validate_payload("recall_note", invented) != []


# ---------------- recall by reference ----------------

def _seed_vault(root):
    """Build a throwaway test-vault with one indexed page. Returns the page body text."""
    (root / "00-system").mkdir(parents=True, exist_ok=True)
    (root / "02-wiki" / "results").mkdir(parents=True, exist_ok=True)
    (root / "07-logs").mkdir(parents=True, exist_ok=True)
    body = ("---\ntype: result\n---\n# MedSAM3 LoRA ablation\n\n"
            "SECRET_BODY_TOKEN dice=0.79 on the frozen split.\n")
    (root / "02-wiki" / "results" / "medsam3-lora-ablation.md").write_text(body, encoding="utf-8")
    (root / "00-system" / "index.md").write_text(
        "# Index\n- [[medsam3-lora-ablation]] — the ablation result\n", encoding="utf-8")
    return body


def test_recall_is_by_reference(tmp_path):
    """recall_note cites slug+sha, and the DB page body is NEVER copied into the note."""
    body = _seed_vault(tmp_path)
    note = recall.recall("medsam3 lora ablation dice", vault_root=tmp_path)
    assert validate_payload("recall_note", note) == []
    assert note["vault_silent"] is False
    assert note["citations"], "should cite the indexed page"
    cite = note["citations"][0]
    assert cite["slug"] == "medsam3-lora-ablation"
    assert cite["sha256"] == "sha256:" + hashlib.sha256(body.encode("utf-8")).hexdigest()
    # the by-reference guarantee: no DB body content leaked into the run-store artifact
    import json
    assert "SECRET_BODY_TOKEN" not in json.dumps(note)


def test_recall_no_invented_slug(tmp_path):
    """A topic the vault is silent on ⇒ vault_silent, no fabricated slug."""
    _seed_vault(tmp_path)
    note = recall.recall("quantum chromodynamics lattice", vault_root=tmp_path)
    assert validate_payload("recall_note", note) == []
    assert note["vault_silent"] is True
    assert note["citations"] == []


# ---------------- DoD #6 literal: promote into a throwaway test-vault ----------------

def test_promote_to_throwaway_test_vault(tmp_path):
    """The Definition-of-Done #6 acceptance, literally: a fixture artifact promotes into a throwaway
    test-vault when frozen, and is REJECTED when provisional — never touching the real DB."""
    _seed_vault(tmp_path)

    # (a) a provisional bundle (no human freeze) -> REJECTED, vault gains no new page
    before = set((tmp_path / "02-wiki" / "results").glob("*.md"))
    rej = promote.promote_to_vault(
        _candidate(slug="provisional-attempt"), signals=_sig(), human_freeze=False,
        vault_root=tmp_path, decided_by="director", decided_at="2026-06-09T10:00:00Z")
    assert rej["admissible"] is False
    assert rej["vault_path"] is None
    assert validate_payload("promotion_record", rej) == []
    assert set((tmp_path / "02-wiki" / "results").glob("*.md")) == before, "reject must not write the vault"

    # (b) a frozen bundle (all audits pass + reviewer approve-freeze + human freeze) -> ADMITTED
    adm = promote.promote_to_vault(
        _candidate(slug="frozen-dice-result"), signals=_sig(), human_freeze=True,
        vault_root=tmp_path, decided_by="director", decided_at="2026-06-09T10:00:00Z")
    assert adm["admissible"] is True
    assert validate_payload("promotion_record", adm) == []
    page = tmp_path / "02-wiki" / "results" / "frozen-dice-result.md"
    assert page.exists(), "admitted result must be written into the vault"
    text = page.read_text(encoding="utf-8")
    assert "can-cite-thesis: true" in text and "result-status: frozen" in text
    # vault write discipline: index.md + log.md both updated
    assert "frozen-dice-result" in (tmp_path / "00-system" / "index.md").read_text(encoding="utf-8")
    assert "PROMOTE" in (tmp_path / "07-logs" / "log.md").read_text(encoding="utf-8")
