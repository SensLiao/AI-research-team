"""Tests for the deterministic source→vault migration tool (`tools/migrate_source_vault.py`).

Covers the four contract guarantees on SYNTHETIC source pages (no real vault is read or written):
  - CONFORM   : a clean source page conforms to the DB universal schema (project injected,
                status/confidence coerced where a clear mapping exists).
  - DEDUP     : a source page whose slug (or normalized title) already lives in the TARGET vault
                is bucketed DEDUP (link, never double-write).
  - FLAG      : a source page that cannot cleanly conform records its contract violations.
  - RECONCILE : migrate + dedup + flag == total, exactly one bucket per page.
  - BODY-HASH : the body is preserved VERBATIM (sha256 of source body == sha256 of written body).

Everything runs against tmp_path fixtures — these tests never touch
`AI agent database/PhD-Research-OS/`.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from research_agent_teams.tools import migrate_source_vault as m


# --------------------------------------------------------------------------- #
# fixtures: a synthetic DB contract + synthetic source/target vaults
# --------------------------------------------------------------------------- #

# A trimmed type-registry.md good enough for load_contract(): concept (universal-only),
# paper (a few required type-specific fields), result (heavy required fields → easy to FLAG).
_REGISTRY_MD = """---
type: registry
---
# Type Registry

## Knowledge-note types

| type | Folder | Purpose | Required type-specific fields | Optional fields |
|------|--------|---------|------------------------------|-----------------|
| `concept` | `concepts/` | Idea | — (only universal) | `also-known-as` (list) |
| `paper` | `papers/` | External paper | `authors` (list), `year` (int), `venue` (str), `reading-status` (to-read\\|read), `relevance` (direct\\|adjacent) | `doi`, `url` |
| `method` | `methods/` | Technique | `category` (prompt\\|adaptation\\|loss) | `first-seen` |
| `result` | `results/` | Atomic row | `model`, `dataset`, `metric`, `value` (number), `result-status` (provisional\\|frozen), `leakage-audit` (pass\\|fail), `fairness-audit` (pass\\|fail) | `std` |

## Meta-doc types

| type | File(s) | Purpose |
|------|---------|---------|
| `readme` | `README.md` | Human-facing orientation docs |
| `registry` | `05-registry/*.md` | enums |
"""


def _make_contract_vault(tmp_path: Path) -> Path:
    """A tmp 'vault root' carrying only the registry file load_contract() parses."""
    reg = tmp_path / "contract-vault" / "05-registry"
    reg.mkdir(parents=True)
    (reg / "type-registry.md").write_text(_REGISTRY_MD, encoding="utf-8")
    return tmp_path / "contract-vault"


def _src_page(body: str = "Body line.\n\nSecond paragraph.\n", **fm) -> str:
    """Render a synthetic source page (YAML frontmatter + body)."""
    import yaml
    return "---\n" + yaml.safe_dump(fm, sort_keys=False, allow_unicode=True) + "---\n" + body


def _write_source_tree(root: Path, pages: dict[str, str]) -> None:
    for rel, text in pages.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")


def _write_target_tree(wiki: Path, slugs_to_titles: dict[str, str]) -> None:
    """Write minimal existing TARGET pages (nested dir to prove basename slug match)."""
    for slug, title in slugs_to_titles.items():
        p = wiki / "papers" / "some-cluster" / f"{slug}.md"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(f"---\ntitle: {title}\ntype: paper\n---\nexisting\n", encoding="utf-8")


# --------------------------------------------------------------------------- #
# CONFORM
# --------------------------------------------------------------------------- #

def test_conform_injects_project_and_keeps_clean_concept(tmp_path):
    contract_root = _make_contract_vault(tmp_path)
    contract = m.load_contract_for(contract_root)
    page = _src_page(
        title="Click Efficiency", type="concept", status="active",
        confidence="high", created="2026-04-19", updated="2026-04-20",
    )
    fm, body = m.parse_page(page)
    conformed = m.conform_frontmatter(fm, project="iac-cbct-seg")
    assert conformed["project"] == "iac-cbct-seg"
    res = m.classify_page(slug="click-efficiency", frontmatter=conformed,
                          body=body, contract=contract, target_slugs=set(),
                          target_titles=set())
    assert res["bucket"] == "MIGRATE", res


def test_conform_does_not_overwrite_existing_project(tmp_path):
    fm = {"project": "already-set", "type": "concept"}
    out = m.conform_frontmatter(fm, project="iac-cbct-seg")
    assert out["project"] == "already-set"


def test_status_coercion_superseded_to_deprecated(tmp_path):
    # `superseded` is not a universal status enum value; a clear mapping → deprecated.
    out = m.conform_frontmatter({"status": "superseded", "type": "concept"},
                                project="iac-cbct-seg")
    assert out["status"] == "deprecated"


def test_unmappable_status_left_for_flag(tmp_path):
    contract_root = _make_contract_vault(tmp_path)
    contract = m.load_contract_for(contract_root)
    out = m.conform_frontmatter(
        {"title": "X", "type": "concept", "status": "frobnicated", "confidence": "high",
         "created": "2026-01-01", "updated": "2026-01-01"},
        project="iac-cbct-seg")
    # left as-is (not silently coerced) → contract validation must catch it
    assert out["status"] == "frobnicated"
    res = m.classify_page(slug="x", frontmatter=out, body="b", contract=contract,
                          target_slugs=set(), target_titles=set())
    assert res["bucket"] == "FLAG"
    assert any(v["code"] == "UNREGISTERED_STATUS" for v in res["violations"])


def test_confidence_coercion_synonym(tmp_path):
    # a clear synonym maps; an unknown value is left for FLAG
    assert m.conform_frontmatter({"confidence": "hi", "type": "concept"},
                                 project="p")["confidence"] == "high"
    assert m.conform_frontmatter({"confidence": "weird", "type": "concept"},
                                 project="p")["confidence"] == "weird"


# --------------------------------------------------------------------------- #
# FLAG
# --------------------------------------------------------------------------- #

def test_flag_result_missing_required_audits(tmp_path):
    contract_root = _make_contract_vault(tmp_path)
    contract = m.load_contract_for(contract_root)
    # a result page with data fields but no validity audits → FLAG (full conformance)
    page = _src_page(
        title="medsam2 cldice", type="result", status="active", confidence="high",
        created="2026-04-26", updated="2026-04-28",
        model="[[medsam2]]", dataset="[[tf3]]", metric="cldice", value=0.431,
    )
    fm, body = m.parse_page(page)
    conformed = m.conform_frontmatter(fm, project="iac-cbct-seg")
    res = m.classify_page(slug="medsam2-cldice", frontmatter=conformed, body=body,
                          contract=contract, target_slugs=set(), target_titles=set())
    assert res["bucket"] == "FLAG"
    codes = {v["code"] for v in res["violations"]}
    assert "MISSING_TYPE_SPECIFIC" in codes
    # specifically the audit fields are flagged
    missing = {v.get("field") for v in res["violations"] if v["code"] == "MISSING_TYPE_SPECIFIC"}
    assert {"result-status", "leakage-audit", "fairness-audit"} <= missing


def test_flag_unknown_type(tmp_path):
    contract_root = _make_contract_vault(tmp_path)
    contract = m.load_contract_for(contract_root)
    page = _src_page(title="weird", type="readme", status="active", confidence="high",
                     created="2026-01-01", updated="2026-01-01")
    fm, body = m.parse_page(page)
    conformed = m.conform_frontmatter(fm, project="iac-cbct-seg")
    res = m.classify_page(slug="weird", frontmatter=conformed, body=body,
                          contract=contract, target_slugs=set(), target_titles=set())
    # readme is a meta type → not in the knowledge contract → UNKNOWN_TYPE → FLAG
    assert res["bucket"] == "FLAG"
    assert any(v["code"] == "UNKNOWN_TYPE" for v in res["violations"])


# --------------------------------------------------------------------------- #
# DEDUP
# --------------------------------------------------------------------------- #

def test_dedup_by_slug(tmp_path):
    contract_root = _make_contract_vault(tmp_path)
    contract = m.load_contract_for(contract_root)
    page = _src_page(title="CLIP", type="paper", status="active", confidence="high",
                     created="2026-01-01", updated="2026-01-01",
                     authors=["Radford"], year=2021, venue="ICML",
                     **{"reading-status": "read", "relevance": "direct"})
    fm, body = m.parse_page(page)
    conformed = m.conform_frontmatter(fm, project="iac-cbct-seg")
    res = m.classify_page(slug="radford-2021-clip", frontmatter=conformed, body=body,
                          contract=contract, target_slugs={"radford-2021-clip"},
                          target_titles=set())
    assert res["bucket"] == "DEDUP"


def test_dedup_by_normalized_title(tmp_path):
    contract_root = _make_contract_vault(tmp_path)
    contract = m.load_contract_for(contract_root)
    page = _src_page(title="Segment Anything", type="paper", status="active",
                     confidence="high", created="2026-01-01", updated="2026-01-01",
                     authors=["Kirillov"], year=2023, venue="ICCV",
                     **{"reading-status": "read", "relevance": "direct"})
    fm, body = m.parse_page(page)
    conformed = m.conform_frontmatter(fm, project="iac-cbct-seg")
    # slug differs but title normalizes to an existing target title
    res = m.classify_page(slug="kirillov-2023-sam", frontmatter=conformed, body=body,
                          contract=contract, target_slugs=set(),
                          target_titles={m.normalize_title("Segment Anything")})
    assert res["bucket"] == "DEDUP"


def test_dedup_takes_priority_over_flag(tmp_path):
    # even an unconformable page that is ALREADY in the vault is DEDUP, not FLAG (we link, not rewrite)
    contract_root = _make_contract_vault(tmp_path)
    contract = m.load_contract_for(contract_root)
    page = _src_page(title="X", type="result", status="active", confidence="high",
                     created="2026-01-01", updated="2026-01-01")  # missing audits
    fm, body = m.parse_page(page)
    conformed = m.conform_frontmatter(fm, project="iac-cbct-seg")
    res = m.classify_page(slug="x-existing", frontmatter=conformed, body=body,
                          contract=contract, target_slugs={"x-existing"}, target_titles=set())
    assert res["bucket"] == "DEDUP"


# --------------------------------------------------------------------------- #
# RECONCILE + BODY-HASH (end-to-end dry run on a synthetic source tree)
# --------------------------------------------------------------------------- #

def test_dry_run_reconciles_and_preserves_body_hash(tmp_path):
    contract_root = _make_contract_vault(tmp_path)

    # build a synthetic source tree: 1 clean concept (MIGRATE), 1 dup paper (DEDUP),
    # 1 broken result (FLAG), plus a README meta page that must be SKIPPED from scope.
    src = tmp_path / "src-wiki"
    clean_body = "# Click Efficiency\n\nNumber of clicks to reach target IoU.\n"
    dup_body = "# CLIP\n\nContrastive language image pretraining.\n"
    flag_body = "# Broken result\n\nNo audits here.\n"
    _write_source_tree(src, {
        "concepts/click-efficiency.md": _src_page(
            clean_body, title="Click Efficiency", type="concept", status="active",
            confidence="high", created="2026-04-19", updated="2026-04-20"),
        "papers/radford-2021-clip.md": _src_page(
            dup_body, title="CLIP", type="paper", status="active", confidence="high",
            created="2026-01-01", updated="2026-01-01", authors=["Radford"], year=2021,
            venue="ICML", **{"reading-status": "read", "relevance": "direct"}),
        "results/broken.md": _src_page(
            flag_body, title="Broken result", type="result", status="active",
            confidence="high", created="2026-01-01", updated="2026-01-01"),
        "datasets/README.md": "---\ntype: readme\nupdated: 2026-01-01\n---\nmeta orientation\n",
    })

    # TARGET vault: already has the CLIP paper (slug match)
    target_wiki = tmp_path / "target" / "02-wiki"
    _write_target_tree(target_wiki, {"radford-2021-clip": "CLIP"})

    out_dir = tmp_path / "out"
    report = m.run_migration(
        source_wiki=src, target_wiki=target_wiki, contract_vault_root=contract_root,
        project="iac-cbct-seg", out_dir=out_dir, dry_run=True,
    )

    # reconciliation: exactly one bucket per page; meta README excluded from total
    assert report["total"] == 3
    assert report["migrate"] == 1
    assert report["dedup"] == 1
    assert report["flag"] == 1
    assert report["migrate"] + report["dedup"] + report["flag"] == report["total"]
    assert report["body_hash_preserved"] is True

    # the MIGRATE page was written to the TEMP out dir, NOT the target vault
    written = list(out_dir.rglob("click-efficiency.md"))
    assert len(written) == 1
    # the target vault was not modified (still only the one existing CLIP file)
    assert not list(target_wiki.rglob("click-efficiency.md"))

    # BODY-HASH preserved verbatim through the write
    written_text = written[0].read_text(encoding="utf-8")
    _, written_body = m.parse_page(written_text)
    src_body = m.parse_page((src / "concepts/click-efficiency.md").read_text(encoding="utf-8"))[1]
    assert hashlib.sha256(written_body.encode("utf-8")).hexdigest() == \
           hashlib.sha256(src_body.encode("utf-8")).hexdigest()

    # a temp log/index copy was written into out_dir (never the real meta files)
    assert (out_dir / "_migration-log.md").exists()
    assert (out_dir / "_migration-index.md").exists()

    # flagged detail is structured
    assert report["flagged"] and report["flagged"][0]["slug"] == "broken"
    assert report["flagged"][0]["violations"]


def test_run_migration_refuses_real_write_without_confirm(tmp_path):
    """commit mode MUST require an explicit confirm token — a bare commit=True is rejected."""
    contract_root = _make_contract_vault(tmp_path)
    src = tmp_path / "src"
    src.mkdir()
    target = tmp_path / "t" / "02-wiki"
    target.mkdir(parents=True)
    with pytest.raises(m.CommitNotConfirmed):
        m.run_migration(source_wiki=src, target_wiki=target,
                        contract_vault_root=contract_root, project="p",
                        out_dir=None, dry_run=False, commit=True, confirm=False)


def test_body_hash_field_records_per_page(tmp_path):
    """Each MIGRATE entry carries its own source body sha256 (losslessness proof)."""
    contract_root = _make_contract_vault(tmp_path)
    src = tmp_path / "src"
    body = "# A\n\nverbatim body\n"
    _write_source_tree(src, {
        "concepts/a.md": _src_page(body, title="A", type="concept", status="active",
                                   confidence="high", created="2026-01-01", updated="2026-01-01"),
    })
    target = tmp_path / "t" / "02-wiki"
    target.mkdir(parents=True)
    out = tmp_path / "o"
    report = m.run_migration(source_wiki=src, target_wiki=target,
                             contract_vault_root=contract_root, project="p",
                             out_dir=out, dry_run=True)
    assert report["migrate"] == 1
    # the written page's body hashes to the source body hash
    written = list(out.rglob("a.md"))[0].read_text(encoding="utf-8")
    assert hashlib.sha256(m.parse_page(written)[1].encode("utf-8")).hexdigest() == \
           hashlib.sha256(body.encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------- #
# PARSE: tolerate markdown blockquote callouts embedded in frontmatter (bug fix 2026-06-16)
# --------------------------------------------------------------------------- #

def test_parse_page_tolerates_blockquote_callout_in_frontmatter():
    """A `>` callout line inside frontmatter must NOT silently nuke the whole page to {}.

    Real source `result` pages embed `> **⚠️ REFRESHED…**` / `> **SUPERSEDED…**` notices in their
    frontmatter; a bare `>` is invalid YAML ('while scanning a block scalar'). The fix strips those
    lines before parsing but PRESERVES their text as `provenance-note` (lossless: only-add)."""
    page = (
        "---\n"
        'title: "vista3d dice point-1"\n'
        "type: result\n"
        "status: active\n"
        "confidence: medium\n"
        'created: "2026-04-19"\n'
        'updated: "2026-06-03"\n'
        "\n"
        "# Result-specific (atomic row)\n"
        "\n"
        "> **⚠️ REFRESHED 2026-06-03 → frontmatter value is the canonical number.**\n"
        'model: "[[vista3d]]"\n'
        "result-status: frozen\n"
        "---\n"
        "# body heading\n\nverbatim body line.\n"
    )
    fm, body = m.parse_page(page)
    # the page is NOT lost: real typed fields survived the YAML break
    assert fm.get("type") == "result"
    assert fm.get("result-status") == "frozen"
    assert fm.get("model") == "[[vista3d]]"
    # the stripped callout text is preserved
    assert "provenance-note" in fm
    assert any("REFRESHED" in n for n in fm["provenance-note"])
    # body returned verbatim (losslessness)
    assert body == "# body heading\n\nverbatim body line.\n"


def test_parse_page_no_callout_adds_no_provenance_field():
    """A clean page (no `>` lines) is parsed exactly as before — no spurious provenance-note."""
    fm, _ = m.parse_page(_src_page(title="X", type="concept", status="active"))
    assert "provenance-note" not in fm


# --------------------------------------------------------------------------- #
# DROP: content-status policy (director 2026-06-16) — wrong/old pages never enter
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("rs", ["invalid", "superseded", "missing-audit"])
def test_drop_dirty_result_status(tmp_path, rs):
    contract_root = _make_contract_vault(tmp_path)
    contract = m.load_contract_for(contract_root)
    page = _src_page(title="R", type="result", status="active", confidence="high",
                     created="2026-01-01", updated="2026-01-01", model="[[m]]",
                     dataset="[[d]]", metric="dice", value=0.4, **{"result-status": rs})
    fm, body = m.parse_page(page)
    conformed = m.conform_frontmatter(fm, project="p")
    res = m.classify_page(slug="r", frontmatter=conformed, body=body, contract=contract,
                          target_slugs=set(), target_titles=set())
    assert res["bucket"] == "DROP"
    assert res["drop_reason"] == f"result-status:{rs}"


def test_drop_deprecated_status(tmp_path):
    contract_root = _make_contract_vault(tmp_path)
    contract = m.load_contract_for(contract_root)
    out = m.conform_frontmatter(
        {"title": "Old", "type": "concept", "status": "deprecated", "confidence": "high",
         "created": "2026-01-01", "updated": "2026-01-01"}, project="p")
    res = m.classify_page(slug="old", frontmatter=out, body="b", contract=contract,
                          target_slugs=set(), target_titles=set())
    assert res["bucket"] == "DROP"
    assert res["drop_reason"] == "status:deprecated"


def test_drop_superseded_status_is_coerced_then_dropped(tmp_path):
    contract_root = _make_contract_vault(tmp_path)
    contract = m.load_contract_for(contract_root)
    # universal status `superseded` → coerced to `deprecated` by conform → DROP
    out = m.conform_frontmatter(
        {"title": "Old", "type": "concept", "status": "superseded", "confidence": "high",
         "created": "2026-01-01", "updated": "2026-01-01"}, project="p")
    assert out["status"] == "deprecated"
    res = m.classify_page(slug="old", frontmatter=out, body="b", contract=contract,
                          target_slugs=set(), target_titles=set())
    assert res["bucket"] == "DROP"


def test_dedup_beats_drop(tmp_path):
    """A wrong page that ALREADY lives in the vault is DEDUP (already present), not DROP."""
    contract_root = _make_contract_vault(tmp_path)
    contract = m.load_contract_for(contract_root)
    page = _src_page(title="R", type="result", status="active", confidence="high",
                     created="2026-01-01", updated="2026-01-01", model="[[m]]",
                     dataset="[[d]]", metric="dice", value=0.4,
                     **{"result-status": "invalid"})
    fm, body = m.parse_page(page)
    conformed = m.conform_frontmatter(fm, project="p")
    res = m.classify_page(slug="r-existing", frontmatter=conformed, body=body, contract=contract,
                          target_slugs={"r-existing"}, target_titles=set())
    assert res["bucket"] == "DEDUP"


# --------------------------------------------------------------------------- #
# KEEP tiers: frozen → full migrate · provisional → reference (can-cite:false)
# --------------------------------------------------------------------------- #

def test_frozen_result_migrates_full(tmp_path):
    contract_root = _make_contract_vault(tmp_path)
    contract = m.load_contract_for(contract_root)
    page = _src_page(title="Frozen R", type="result", status="active", confidence="high",
                     created="2026-01-01", updated="2026-01-01", model="[[m]]", dataset="[[d]]",
                     metric="dice", value=0.7,
                     **{"result-status": "frozen", "leakage-audit": "pass", "fairness-audit": "pass"})
    fm, body = m.parse_page(page)
    conformed = m.conform_frontmatter(fm, project="p")
    res = m.classify_page(slug="frozen-r", frontmatter=conformed, body=body, contract=contract,
                          target_slugs=set(), target_titles=set())
    assert res["bucket"] == "MIGRATE"


def test_provisional_result_is_reference(tmp_path):
    """provisional result missing audit fields → MIGRATE_REF (not FLAG, not DROP)."""
    contract_root = _make_contract_vault(tmp_path)
    contract = m.load_contract_for(contract_root)
    page = _src_page(title="Prov R", type="result", status="active", confidence="medium",
                     created="2026-01-01", updated="2026-01-01", model="[[m]]", dataset="[[d]]",
                     metric="dice", value=0.5, **{"result-status": "provisional"})  # no audits
    fm, body = m.parse_page(page)
    conformed = m.conform_frontmatter(fm, project="p")
    res = m.classify_page(slug="prov-r", frontmatter=conformed, body=body, contract=contract,
                          target_slugs=set(), target_titles=set())
    assert res["bucket"] == "MIGRATE_REF"


def test_result_unknown_status_value_flags(tmp_path):
    """A result whose result-status is neither clean nor a known drop value → FLAG (manual)."""
    contract_root = _make_contract_vault(tmp_path)
    contract = m.load_contract_for(contract_root)
    page = _src_page(title="Weird R", type="result", status="active", confidence="low",
                     created="2026-01-01", updated="2026-01-01", model="[[m]]", dataset="[[d]]",
                     metric="dice", value=0.3, **{"result-status": "weird-value"})
    fm, body = m.parse_page(page)
    conformed = m.conform_frontmatter(fm, project="p")
    res = m.classify_page(slug="weird-r", frontmatter=conformed, body=body, contract=contract,
                          target_slugs=set(), target_titles=set())
    assert res["bucket"] == "FLAG"


def test_nonresult_partial_is_reference(tmp_path):
    """A non-result page that is universal-valid but missing type-specific fields → reference."""
    contract_root = _make_contract_vault(tmp_path)
    contract = m.load_contract_for(contract_root)
    # paper missing venue / reading-status / relevance, but universal fields present
    page = _src_page(title="Partial Paper", type="paper", status="active", confidence="high",
                     created="2026-01-01", updated="2026-01-01", authors=["X"], year=2024)
    fm, body = m.parse_page(page)
    conformed = m.conform_frontmatter(fm, project="p")
    res = m.classify_page(slug="partial-paper", frontmatter=conformed, body=body, contract=contract,
                          target_slugs=set(), target_titles=set())
    assert res["bucket"] == "MIGRATE_REF"


# --------------------------------------------------------------------------- #
# RECONCILE: full 5-bucket partition + can-cite forced false + callout page survives end-to-end
# --------------------------------------------------------------------------- #

def test_dry_run_five_bucket_partition_and_can_cite_forced_false(tmp_path):
    contract_root = _make_contract_vault(tmp_path)
    src = tmp_path / "src-wiki"
    _write_source_tree(src, {
        "concepts/clean.md": _src_page(
            "# Clean\n\nbody\n", title="Clean Concept", type="concept", status="active",
            confidence="high", created="2026-01-01", updated="2026-01-02"),
        "papers/dup-paper.md": _src_page(
            "# Dup\n\nbody\n", title="Dup Paper", type="paper", status="active", confidence="high",
            created="2026-01-01", updated="2026-01-01", authors=["X"], year=2024, venue="NeurIPS",
            **{"reading-status": "read", "relevance": "direct"}),
        "results/invalid-res.md": _src_page(
            "# Invalid\n\nbody\n", title="Invalid Res", type="result", status="active",
            confidence="high", created="2026-01-01", updated="2026-01-01", model="[[m]]",
            dataset="[[d]]", metric="dice", value=0.1,
            **{"result-status": "invalid", "leakage-audit": "fail", "fairness-audit": "missing"}),
        "results/prov-res.md": _src_page(
            "# Prov\n\nbody\n", title="Prov Res", type="result", status="active",
            confidence="medium", created="2026-01-01", updated="2026-01-01", model="[[m]]",
            dataset="[[d]]", metric="dice", value=0.5, **{"result-status": "provisional"}),
        "results/unknown-res.md": _src_page(
            "# Unknown\n\nbody\n", title="Unknown Res", type="result", status="active",
            confidence="low", created="2026-01-01", updated="2026-01-01", model="[[m]]",
            dataset="[[d]]", metric="dice", value=0.3),  # no result-status → FLAG
    })
    target_wiki = tmp_path / "target" / "02-wiki"
    _write_target_tree(target_wiki, {"dup-paper": "Dup Paper"})

    out_dir = tmp_path / "out"
    report = m.run_migration(
        source_wiki=src, target_wiki=target_wiki, contract_vault_root=contract_root,
        project="iac-cbct-seg", out_dir=out_dir, dry_run=True)

    assert report["total"] == 5
    assert report["migrate"] == 1        # clean concept
    assert report["dedup"] == 1          # dup paper
    assert report["drop"] == 1           # invalid result
    assert report["migrate_ref"] == 1    # provisional result
    assert report["flag"] == 1           # result with no result-status
    assert (report["migrate"] + report["migrate_ref"] + report["dedup"]
            + report["flag"] + report["drop"]) == report["total"]
    assert report["body_hash_preserved"] is True

    # dropped/ref reporting is structured
    assert report["dropped"] and report["dropped"][0]["slug"] == "invalid-res"
    assert report["dropped"][0]["reason"] == "result-status:invalid"
    assert any(r["slug"] == "prov-res" for r in report["ref"])

    # the provisional result was written with can-cite-thesis forced FALSE
    prov_written = list(out_dir.rglob("prov-res.md"))
    assert len(prov_written) == 1
    prov_fm, _ = m.parse_page(prov_written[0].read_text(encoding="utf-8"))
    assert prov_fm.get("can-cite-thesis") is False
    # the invalid result was NOT written anywhere
    assert not list(out_dir.rglob("invalid-res.md"))


def test_callout_frozen_result_migrates_end_to_end(tmp_path):
    """A frozen result whose frontmatter carries a `>` callout migrates (no longer wrongly FLAGged),
    keeps its provenance-note, and preserves its body hash through the dry-run write."""
    contract_root = _make_contract_vault(tmp_path)
    src = tmp_path / "src-wiki"
    callout_body = "# Frozen with callout\n\nverbatim.\n"
    page = (
        "---\n"
        'title: "Frozen Callout"\n'
        "type: result\n"
        "status: active\n"
        "confidence: high\n"
        'created: "2026-01-01"\n'
        'updated: "2026-06-03"\n'
        "\n"
        "> **⚠️ REFRESHED 2026-06-03 → value is canonical.**\n"
        'model: "[[m]]"\n'
        'dataset: "[[d]]"\n'
        "metric: dice\n"
        "value: 0.8\n"
        "result-status: frozen\n"
        "leakage-audit: pass\n"
        "fairness-audit: pass\n"
        "---\n"
    ) + callout_body
    _write_source_tree(src, {"results/frozen-callout.md": page})
    target_wiki = tmp_path / "target" / "02-wiki"
    target_wiki.mkdir(parents=True)
    out_dir = tmp_path / "out"
    report = m.run_migration(
        source_wiki=src, target_wiki=target_wiki, contract_vault_root=contract_root,
        project="iac-cbct-seg", out_dir=out_dir, dry_run=True)

    assert report["total"] == 1
    assert report["migrate"] == 1 and report["flag"] == 0
    written = list(out_dir.rglob("frozen-callout.md"))[0].read_text(encoding="utf-8")
    fm, body = m.parse_page(written)
    assert fm.get("result-status") == "frozen"
    assert "provenance-note" in fm
    assert hashlib.sha256(body.encode("utf-8")).hexdigest() == \
           hashlib.sha256(callout_body.encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------- #
# REAL COMMIT: page→page write into 02-wiki + index/log + crown-jewel safety
# --------------------------------------------------------------------------- #

def test_path_within_blocks_escape(tmp_path):
    wiki = tmp_path / "02-wiki"
    wiki.mkdir()
    assert m._path_within(wiki / "results" / "x.md", wiki)
    assert m._path_within(wiki / "x.md", wiki)
    assert not m._path_within(tmp_path / "05-registry" / "type-registry.md", wiki)
    assert not m._path_within(tmp_path / "00-system" / "index.md", wiki)


def test_real_commit_writes_pages_and_logs_and_spares_crown_jewels(tmp_path):
    vault_root = _make_contract_vault(tmp_path)   # carries 05-registry/type-registry.md
    (vault_root / "02-wiki").mkdir(parents=True, exist_ok=True)
    registry_before = (vault_root / "05-registry" / "type-registry.md").read_text(encoding="utf-8")

    src = tmp_path / "src"
    _write_source_tree(src, {
        "concepts/clean.md": _src_page("# Clean\n\nconcept body\n", title="Clean", type="concept",
            status="active", confidence="high", created="2026-01-01", updated="2026-01-02"),
        "results/invalid.md": _src_page("# Inv\n\nb\n", title="Inv", type="result", status="active",
            confidence="high", created="2026-01-01", updated="2026-01-01", model="[[m]]",
            dataset="[[d]]", metric="dice", value=0.1, **{"result-status": "invalid"}),
        "results/prov.md": _src_page("# Prov\n\nb\n", title="Prov", type="result", status="active",
            confidence="medium", created="2026-01-01", updated="2026-01-01", model="[[m]]",
            dataset="[[d]]", metric="dice", value=0.5, **{"result-status": "provisional"}),
    })

    report = m.run_migration(
        source_wiki=src, target_wiki=vault_root / "02-wiki", contract_vault_root=vault_root,
        project="iac-cbct-seg", out_dir=None, dry_run=False, commit=True, confirm=True)

    assert report["_committed"] is True
    assert report["migrate"] == 1 and report["migrate_ref"] == 1 and report["drop"] == 1
    # clean concept + provisional result written; invalid result NEVER written
    assert (vault_root / "02-wiki" / "concepts" / "clean.md").exists()
    assert (vault_root / "02-wiki" / "results" / "prov.md").exists()
    assert not list((vault_root / "02-wiki").rglob("invalid.md"))
    # provisional result entered with can-cite-thesis forced false
    prov_fm, _ = m.parse_page((vault_root / "02-wiki" / "results" / "prov.md").read_text(encoding="utf-8"))
    assert prov_fm.get("can-cite-thesis") is False
    # index + log appended (vault discipline)
    assert "migration" in (vault_root / "00-system" / "index.md").read_text(encoding="utf-8")
    assert "MIGRATE-BULK" in (vault_root / "07-logs" / "log.md").read_text(encoding="utf-8")
    # crown-jewel registry byte-identical (never touched)
    assert (vault_root / "05-registry" / "type-registry.md").read_text(encoding="utf-8") == registry_before
    # body preserved verbatim through the real write
    _, written_body = m.parse_page((vault_root / "02-wiki" / "concepts" / "clean.md").read_text(encoding="utf-8"))
    assert "concept body" in written_body


def test_load_type_folders_uses_registry_not_naive_plural(tmp_path):
    """Folders come from the registry's Folder column — `synthesis`→`syntheses` (NOT `synthesiss`),
    `entity`→`entities` (NOT `entitys`), `process-memory`→`process-memory`."""
    reg = tmp_path / "v" / "05-registry"
    reg.mkdir(parents=True)
    (reg / "type-registry.md").write_text(
        "## Knowledge-note types\n\n"
        "| type | Folder | Purpose | Required type-specific fields | Optional fields |\n"
        "|------|--------|---------|------------------------------|-----------------|\n"
        "| `synthesis` | `syntheses/` | x | — | — |\n"
        "| `entity` | `entities/` | x | `entity-type` (str) | — |\n"
        "| `process-memory` | `process-memory/` | x | `pm-id` (str) | — |\n"
        "| `result` | `results/` | x | `model` | — |\n",
        encoding="utf-8")
    folders = m.load_type_folders(tmp_path / "v")
    assert folders["synthesis"] == "syntheses"        # NOT synthesiss
    assert folders["entity"] == "entities"            # NOT entitys
    assert folders["process-memory"] == "process-memory"
    assert folders["result"] == "results"


def test_commit_writes_synthesis_to_syntheses_folder(tmp_path):
    """End-to-end: a `synthesis` page lands in `syntheses/`, never `synthesiss/`."""
    # registry with a synthesis row (universal-only required for simplicity)
    reg = tmp_path / "v" / "05-registry"
    reg.mkdir(parents=True)
    (reg / "type-registry.md").write_text(
        "## Knowledge-note types\n\n"
        "| type | Folder | Purpose | Required type-specific fields | Optional fields |\n"
        "|------|--------|---------|------------------------------|-----------------|\n"
        "| `synthesis` | `syntheses/` | x | — | — |\n",
        encoding="utf-8")
    vault_root = tmp_path / "v"
    (vault_root / "02-wiki").mkdir(parents=True, exist_ok=True)
    src = tmp_path / "src"
    _write_source_tree(src, {
        "syntheses/s1.md": _src_page("# S\n\nbody\n", title="Synth One", type="synthesis",
            status="active", confidence="high", created="2026-01-01", updated="2026-01-02"),
    })
    m.run_migration(source_wiki=src, target_wiki=vault_root / "02-wiki",
                    contract_vault_root=vault_root, project="p", out_dir=None,
                    dry_run=False, commit=True, confirm=True)
    assert (vault_root / "02-wiki" / "syntheses" / "s1.md").exists()
    assert not (vault_root / "02-wiki" / "synthesiss").exists()


def test_migrate_derives_can_cite_repairing_source_under_claim(tmp_path):
    """can-cite-thesis is DERIVED, never copied from the source self-claim: a fully-audited frozen
    result the source under-claimed `can-cite-thesis: false` is repaired to True (the vault's
    CITATION_GATE: derived = frozen ∧ leakage==pass ∧ fairness==pass)."""
    contract_root = _make_contract_vault(tmp_path)
    page = _src_page(title="Frozen Citable", type="result", status="active", confidence="high",
                     created="2026-01-01", updated="2026-01-01", model="[[m]]", dataset="[[d]]",
                     metric="dice", value=0.9, **{"result-status": "frozen", "leakage-audit": "pass",
                     "fairness-audit": "pass", "can-cite-thesis": False})
    src = tmp_path / "src"
    _write_source_tree(src, {"results/fc.md": page})
    out = tmp_path / "o"
    m.run_migration(source_wiki=src, target_wiki=tmp_path / "empty-wiki",
                    contract_vault_root=contract_root, project="p", out_dir=out, dry_run=True)
    fm, _ = m.parse_page((out / "results" / "fc.md").read_text(encoding="utf-8"))
    assert fm.get("can-cite-thesis") is True   # repaired: source said false, derived says true


def test_migrate_derives_can_cite_blocking_source_over_claim(tmp_path):
    """A frozen result whose audits are NOT pass cannot be citable even if the source claims true."""
    contract_root = _make_contract_vault(tmp_path)
    page = _src_page(title="Frozen NoAudit", type="result", status="active", confidence="high",
                     created="2026-01-01", updated="2026-01-01", model="[[m]]", dataset="[[d]]",
                     metric="dice", value=0.9, **{"result-status": "frozen", "leakage-audit": "missing",
                     "fairness-audit": "missing", "can-cite-thesis": True})
    src = tmp_path / "src"
    _write_source_tree(src, {"results/fn.md": page})
    out = tmp_path / "o"
    m.run_migration(source_wiki=src, target_wiki=tmp_path / "empty-wiki",
                    contract_vault_root=contract_root, project="p", out_dir=out, dry_run=True)
    fm, _ = m.parse_page((out / "results" / "fn.md").read_text(encoding="utf-8"))
    assert fm.get("can-cite-thesis") is False  # blocked: source over-claimed, audits not pass


# --------------------------------------------------------------------------- #
# LINK REBUILD — keep resolvable / redirect via superseded-by / de-link danglers / drop related
# --------------------------------------------------------------------------- #

def test_link_rebuild_keep_redirect_delink(tmp_path):
    contract_root = _make_contract_vault(tmp_path)
    body_a = "# A\n\nsee [[b-concept]] and [[gone]] and the old [[old-result|old run]].\n"
    src = tmp_path / "src"
    _write_source_tree(src, {
        "concepts/a.md": _src_page(body_a, title="A", type="concept", status="active",
            confidence="high", created="2026-01-01", updated="2026-01-02",
            related=["[[b-concept]]", "[[gone]]", "[[old-result]]"]),
        "concepts/b-concept.md": _src_page("# B\n\nbody\n", title="B Concept", type="concept",
            status="active", confidence="high", created="2026-01-01", updated="2026-01-02"),
        "results/old-result.md": _src_page("# Old\n\nb\n", title="Old", type="result", status="active",
            confidence="high", created="2026-01-01", updated="2026-01-01", model="[[m]]",
            dataset="[[d]]", metric="dice", value=0.1,
            **{"result-status": "invalid", "superseded-by": "[[new-result]]"}),
        "results/new-result.md": _src_page("# New\n\nb\n", title="New", type="result", status="active",
            confidence="high", created="2026-01-01", updated="2026-01-01", model="[[m]]",
            dataset="[[d]]", metric="dice", value=0.9,
            **{"result-status": "frozen", "leakage-audit": "pass", "fairness-audit": "pass"}),
    })
    out = tmp_path / "o"
    report = m.run_migration(source_wiki=src, target_wiki=tmp_path / "empty-wiki",
        contract_vault_root=contract_root, project="p", out_dir=out, dry_run=True)
    assert report["drop"] == 1
    fm_a, body = m.parse_page((out / "concepts" / "a.md").read_text(encoding="utf-8"))
    assert "[[b-concept]]" in body          # resolvable kept
    assert "[[gone]]" not in body and "gone" in body   # de-linked to text
    assert "[[new-result" in body and "[[old-result" not in body  # redirected via superseded-by
    rel_str = " ".join(str(r) for r in (fm_a.get("related") or []))
    assert "b-concept" in rel_str and "gone" not in rel_str and "new-result" in rel_str


def test_link_rebuild_applies_injected_reconnect(tmp_path):
    """A dangling [[sat-zhao-2025]] is smart-reconnected to an existing migrated paper via the
    injected link_redirects map (the agent-decided reconnect surface)."""
    contract_root = _make_contract_vault(tmp_path)
    src = tmp_path / "src"
    _write_source_tree(src, {
        "concepts/c.md": _src_page("# C\n\ncites [[sat-zhao-2025]] heavily.\n", title="C",
            type="concept", status="active", confidence="high", created="2026-01-01", updated="2026-01-02"),
        "papers/zhao-2025-sat.md": _src_page("# Zhao\n\nbody\n", title="Zhao 2025 SAT", type="paper",
            status="active", confidence="high", created="2026-01-01", updated="2026-01-01",
            authors=["Zhao"], year=2025, venue="MICCAI",
            **{"reading-status": "read", "relevance": "direct"}),
    })
    out = tmp_path / "o"
    m.run_migration(source_wiki=src, target_wiki=tmp_path / "empty-wiki",
        contract_vault_root=contract_root, project="p", out_dir=out, dry_run=True,
        link_redirects={"sat-zhao-2025": "zhao-2025-sat"})
    _, body = m.parse_page((out / "concepts" / "c.md").read_text(encoding="utf-8"))
    assert "[[zhao-2025-sat]]" in body and "[[sat-zhao-2025]]" not in body


def test_non_result_page_strips_result_gate_fields(tmp_path):
    """A non-result page carrying result-gate fields has them stripped (closes CITATION_GATE bypass)."""
    contract_root = _make_contract_vault(tmp_path)
    src = tmp_path / "src"
    _write_source_tree(src, {
        "concepts/e.md": _src_page("# E\n\nbody\n", title="ConceptE", type="concept", status="active",
            confidence="high", created="2026-01-01", updated="2026-01-01",
            **{"result-status": "frozen", "can-cite-thesis": True}),
    })
    out = tmp_path / "o"
    m.run_migration(source_wiki=src, target_wiki=tmp_path / "empty-wiki",
        contract_vault_root=contract_root, project="p", out_dir=out, dry_run=True)
    fm, _ = m.parse_page((out / "concepts" / "e.md").read_text(encoding="utf-8"))
    assert "result-status" not in fm and "can-cite-thesis" not in fm


def test_url_dedup_keeps_canonical_strips_rest(tmp_path):
    """A url shared by >1 migrated page is kept on the first slug, stripped from the rest
    (lint SOURCE_REF_DUPLICATE)."""
    contract_root = _make_contract_vault(tmp_path)
    src = tmp_path / "src"
    common = dict(type="paper", status="active", confidence="high", created="2026-01-01",
                  updated="2026-01-01", authors=["X"], year=2024, venue="V",
                  url="https://example.com/x", **{"reading-status": "read", "relevance": "direct"})
    _write_source_tree(src, {
        "papers/aaa-main.md": _src_page("# Main\n\nb\n", title="Main", **common),
        "papers/zzz-supp.md": _src_page("# Supp\n\nb\n", title="Supp", **common),
    })
    out = tmp_path / "o"
    m.run_migration(source_wiki=src, target_wiki=tmp_path / "empty-wiki",
        contract_vault_root=contract_root, project="p", out_dir=out, dry_run=True)
    fm_main, _ = m.parse_page((out / "papers" / "aaa-main.md").read_text(encoding="utf-8"))
    fm_supp, _ = m.parse_page((out / "papers" / "zzz-supp.md").read_text(encoding="utf-8"))
    assert fm_main.get("url") == "https://example.com/x"  # kept on first slug
    assert "url" not in fm_supp                            # stripped from the duplicate
