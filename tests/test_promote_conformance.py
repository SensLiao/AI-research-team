"""S④ — drift/conformance tests pinning the machine's vault-write seam to the DB contract.

(1) the promote gate writes ONLY `result` pages — a non-result vault_type fail-closes, so no malformed,
    mislabeled page (e.g. a `method` carrying result-status) ever reaches the crown jewels;
(2) a promoted `result` page is UNIVERSAL-frontmatter-conformant per vault_page_contract (drift tripwire:
    if render_vault_page ever drops a universal field or emits a bad status/confidence, this goes red);
(3) the validator's `check_type_specific` switch behaves (full vs universal-only).

HONEST, DEFERRED: the DB `result` template also requires 10 DATA fields (model/dataset/metric/value/...).
Those come from a REAL experiment run (EXECUTE pipeline, server-gated), not from the current candidate, so
promote writes them into the body and frontmatter conformance is enforced at the universal layer for now.
Full result-data frontmatter conformance is a wired-pipeline change tracked in the upgrade ledger.
"""
from __future__ import annotations

from pathlib import Path

from research_agent_teams.tools import promote
from research_agent_teams.tools import vault_page_contract as vpc

_REPO_ROOT = Path(__file__).resolve().parents[2]
_VAULT = _REPO_ROOT / "AI agent database" / "PhD-Research-OS"


def _parse_fm(page: str) -> dict:
    lines = page.splitlines()
    assert lines and lines[0] == "---"
    fm: dict = {}
    for ln in lines[1:]:
        if ln == "---":
            break
        k, sep, v = ln.partition(":")
        if sep:
            fm[k.strip()] = v.strip().strip('"')
    return fm


def test_promote_rejects_non_result_vault_type(tmp_path):
    # bare vault (no 05-registry) so the project-discipline check is skipped — isolate the renderer guard.
    candidate = {
        "slug": "adapter-card", "vault_type": "method", "project": "iac-cbct-seg",
        "title": "Adapter", "body": "x", "source_result_status": "frozen",
    }
    rec = promote.promote_to_vault(
        candidate,
        signals={"leakage_pass": True, "fairness_pass": True, "reviewer_approves_freeze": True},
        human_freeze=True, vault_root=tmp_path, decided_by="director",
        decided_at="2026-06-16T00:00:00Z",
    )
    assert rec["admissible"] is False
    assert any("result" in r and "renderer" in r for r in rec["reasons"])
    assert rec["vault_path"] is None          # nothing written


def test_promoted_result_page_is_universal_conformant():
    page = promote.render_vault_page(
        slug="medsam3-lora-dice", vault_type="result", project="iac-cbct-seg",
        title="MedSAM3 LoRA Dice", created="2026-06-16",
        decision={"rederived_result_status": "frozen", "rederived_can_cite_thesis": True},
        candidate={"body": "Dice=0.79 on the frozen external test split."},
    )
    fm = _parse_fm(page)
    contract = vpc.load_contract(_VAULT) if _VAULT.exists() else {"result": []}
    v = vpc.validate_page(fm, contract=contract, check_type_specific=False)
    assert v["ok"] is True, v["violations"]


def test_check_type_specific_switch():
    contract = {"result": ["model", "dataset", "metric", "value"]}
    minimal = {
        "title": "r", "type": "result", "status": "completed", "confidence": "high",
        "created": "2026-06-16", "updated": "2026-06-16", "project": "iac-cbct-seg",
    }
    assert vpc.validate_page(minimal, contract=contract, check_type_specific=False)["ok"] is True
    full = vpc.validate_page(minimal, contract=contract, check_type_specific=True)
    assert full["ok"] is False
    assert any(x["code"] == "MISSING_TYPE_SPECIFIC" for x in full["violations"])
