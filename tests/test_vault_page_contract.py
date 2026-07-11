"""Tests for the DB-page conformance contract (tools/vault_page_contract).

Proves the machine binds to System D's OWN schema (type-registry.md parsed live), never a hardcoded
parallel copy. Hermetic parser tests use a synthetic registry; the binding test reads the real vault
registry read-only.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from research_agent_teams.tools import vault_page_contract as vpc

_REPO_ROOT = Path(__file__).resolve().parents[2]
_VAULT = _REPO_ROOT / "AI agent database" / "PhD-Research-OS"


def _conformant_method_page() -> dict:
    return {
        "title": "Adapter Modules", "type": "method", "status": "active",
        "confidence": "medium", "created": "2026-04-19", "updated": "2026-04-19",
        "project": "iac-cbct-seg", "category": "adaptation",
    }


def _write_mini_registry(tmp_path: Path) -> Path:
    reg = tmp_path / "05-registry"
    reg.mkdir(parents=True)
    (reg / "type-registry.md").write_text(
        "## Knowledge-note types\n\n"
        "| type | Folder | Purpose | Required type-specific fields | Optional fields |\n"
        "|------|--------|---------|------------------------------|-----------------|\n"
        "| `method` | `methods/` | Technique | `category` (prompt\\|adaptation\\|loss) | `first-seen` |\n"
        "| `result` | `results/` | Row (1 m × 1 metric) | `model`, `value` (number), `split` (val\\|test) | `std` |\n"
        "| `claim` | `claims/` | Prop | `claim-status` (draft), `audit` (object with `leakage`, `fairness` keys) | `chapter` |\n"
        "| `concept` | `concepts/` | Idea | — (only universal) | `also-known-as` |\n\n"
        "## Meta-doc types\n\n"
        "| type | File(s) | Purpose |\n"
        "|------|---------|---------|\n"
        "| `schema` | `00-system/CLAUDE.md` | Vault schema |\n",
        encoding="utf-8",
    )
    return tmp_path


# ---------- parser: synthetic registry (hermetic) ----------

def test_parser_handles_escaped_pipes_and_nested_backticks(tmp_path):
    contract = vpc.load_contract(_write_mini_registry(tmp_path))
    # an escaped-pipe enum must NOT split the row away:
    assert contract["result"] == ["model", "value", "split"]
    assert contract["method"] == ["category"]
    # nested sub-keys of `audit` are NOT pulled up as top-level required fields:
    assert contract["claim"] == ["claim-status", "audit"]
    # concept has only universal:
    assert contract["concept"] == []
    # meta-doc table (3-col) is ignored:
    assert "schema" not in contract


# ---------- binding: the REAL vault registry ----------

@pytest.mark.skipif(not _VAULT.exists(), reason="vault not present")
def test_load_contract_binds_to_real_registry():
    contract = vpc.load_contract(_VAULT)
    for f in ("model", "dataset", "metric", "value", "result-status",
              "can-cite-thesis", "leakage-audit", "fairness-audit", "evidence-artifact"):
        assert f in contract["result"], f
    # claim must NOT contain audit's nested sub-keys (parser guard, on real data):
    for nested in ("leakage", "fairness", "reproducibility"):
        assert nested not in contract["claim"], nested
    assert contract["method"] == ["category"]
    assert contract["concept"] == []
    assert "paper" in contract and {"authors", "year", "venue"} <= set(contract["paper"])
    # meta types never enter the contract:
    assert "schema" not in contract and "registry" not in contract


# ---------- validator ----------

def test_validate_accepts_conformant_page(tmp_path):
    contract = vpc.load_contract(_write_mini_registry(tmp_path))
    v = vpc.validate_page(_conformant_method_page(), contract=contract)
    assert v["ok"] is True and v["violations"] == []


def test_validate_rejects_missing_universal(tmp_path):
    contract = vpc.load_contract(_write_mini_registry(tmp_path))
    page = _conformant_method_page()
    del page["project"]
    v = vpc.validate_page(page, contract=contract)
    assert v["ok"] is False
    assert any(x["code"] == "MISSING_UNIVERSAL" and x["field"] == "project" for x in v["violations"])


def test_validate_rejects_unknown_type(tmp_path):
    contract = vpc.load_contract(_write_mini_registry(tmp_path))
    page = _conformant_method_page() | {"type": "banana"}
    v = vpc.validate_page(page, contract=contract)
    assert any(x["code"] == "UNKNOWN_TYPE" for x in v["violations"])


def test_validate_rejects_missing_type_specific(tmp_path):
    contract = vpc.load_contract(_write_mini_registry(tmp_path))
    page = {k: v for k, v in _conformant_method_page().items() if k != "category"}
    v = vpc.validate_page(page, contract=contract)
    assert any(x["code"] == "MISSING_TYPE_SPECIFIC" and x["field"] == "category"
               for x in v["violations"])


def test_validate_enforces_status_enum(tmp_path):
    contract = vpc.load_contract(_write_mini_registry(tmp_path))
    # 'frozen' is a result-status value, never a page-lifecycle status:
    page = _conformant_method_page() | {"status": "frozen"}
    v = vpc.validate_page(page, contract=contract)
    assert any(x["code"] == "UNREGISTERED_STATUS" for x in v["violations"])


def test_validate_enforces_bitemporal(tmp_path):
    contract = vpc.load_contract(_write_mini_registry(tmp_path))
    page = _conformant_method_page() | {
        "type": "claim", "claim-status": "draft", "audit": {"x": 1},
        "invalid-at": "2026-06-16",  # set without invalidated-by → must fail
    }
    v = vpc.validate_page(page, contract=contract)
    assert any(x["code"] == "BITEMPORAL" for x in v["violations"])
