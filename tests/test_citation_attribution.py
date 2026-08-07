import hashlib
import json

import pytest

from research_agent_teams.tools.citation_attribution import (
    build_attribution_report,
    build_run_attribution_report,
    write_fulltext_context_snapshot,
)
from research_agent_teams.tools.validate_artifact import validate_payload


QUOTE = "The endpoint rose by 3.2 points (95% CI 1.1 to 5.3)."


def test_local_pdf_snapshot_uses_complete_page_text_not_search_excerpts(tmp_path):
    fitz = pytest.importorskip("fitz")
    pdf = tmp_path / "paper.pdf"
    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 72), "Full page evidence absent from the search excerpt.")
    document.save(pdf)
    document.close()
    report = {
        "available": True,
        "contexts": [{"doc_ref": str(pdf), "page": 1, "excerpt": "search excerpt only"}],
    }
    manifest = write_fulltext_context_snapshot(tmp_path, report, [str(pdf)])
    snapshot = (tmp_path / manifest["snapshot_ref"]).read_text(encoding="utf-8")
    assert "Full page evidence" in snapshot
    assert manifest["coverage_boundary"].startswith("complete local PDF")
    assert manifest["parser_version"] == "pymupdf-page-text/v1"


def _inputs(tmp_path):
    snapshot = tmp_path / "snapshots" / "paper-x.txt"
    snapshot.parent.mkdir(parents=True)
    text = "x" * 120 + QUOTE + " trailing text"
    snapshot.write_text(text, encoding="utf-8")
    digest = hashlib.sha256(snapshot.read_bytes()).hexdigest()
    claims = {
        "source_scope": "two-paper synthesis",
        "claims": [{"claim_id": "C1", "text": "The intervention improved the endpoint.",
                    "source_ref": "doi:10.1/x"}],
    }
    claim_map = {
        "attribution_contract_version": "claim-span/v1",
        "mappings": [{
            "claim_id": "C1",
            "overall_support": "supported",
            "loci": [{
                "locus_id": "L1",
                "source_ref": "doi:10.1/x",
                "location": "Results paragraph 2",
                "kind": "text",
                "reported_result": QUOTE,
                "supports_claim": True,
                "support_relation": "entails",
                "directness": "direct",
                "span_id": "SPAN-1",
                "snapshot_ref": "snapshots/paper-x.txt",
                "document_hash": digest,
                "parser_version": "utf-8-char/v1",
                "char_start": 120,
                "char_end": 120 + len(QUOTE),
                "exact_quote": QUOTE,
            }],
        }],
    }
    audit = {
        "contract_version": "citation-attribution/v1",
        "independent_of_linker": True,
        "claim_results": [{
            "claim_id": "C1",
            "verdict": "entails",
            "locator_verified": True,
            "verified_locus_ids": ["L1"],
            "unsupported_locus_ids": [],
            "notes": "Independent reread confirmed the direction, magnitude, and interval.",
        }],
    }
    return claims, claim_map, audit


def test_independent_precise_span_attribution_passes_and_derives_metrics(tmp_path):
    report = build_attribution_report(*_inputs(tmp_path), run_dir=tmp_path)
    assert report["verdict"] == "PASS"
    assert report["citation_correctness"] == 1.0
    assert report["claim_completeness"] == 1.0
    assert report["citation_f1"] == 1.0
    assert report["mechanical_verification"]["n_verified"] == 1
    assert validate_payload("citation_attribution_report", report) == []


def test_linker_self_attestation_or_unverified_locator_blocks(tmp_path):
    claims, claim_map, audit = _inputs(tmp_path)
    audit["independent_of_linker"] = False
    audit["claim_results"][0]["locator_verified"] = False
    report = build_attribution_report(claims, claim_map, audit, run_dir=tmp_path)
    assert report["verdict"] == "BLOCK"
    assert any("independent_of_linker" in row for row in report["violations"])
    assert any("did not verify" in row for row in report["violations"])


def test_partial_support_cannot_masquerade_as_supported_claim(tmp_path):
    claims, claim_map, audit = _inputs(tmp_path)
    audit["claim_results"][0]["verdict"] = "partial"
    report = build_attribution_report(claims, claim_map, audit, run_dir=tmp_path)
    assert report["verdict"] == "BLOCK"
    assert report["claim_completeness"] == 0.0
    assert any("found partial support" in row for row in report["violations"])


def test_strict_paper_read_requires_complete_support_even_when_linker_agrees_partial(tmp_path):
    claims, claim_map, audit = _inputs(tmp_path)
    claim_map["mappings"][0]["overall_support"] = "partial"
    audit["claim_results"][0]["verdict"] = "partial"
    report = build_attribution_report(
        claims, claim_map, audit, run_dir=tmp_path, require_complete_claims=True,
    )
    assert report["verdict"] == "PASS_WITH_CAVEATS"
    assert report["claim_completeness"] == 0.0


def test_complete_document_coverage_can_caveat_an_absence_claim(tmp_path):
    claims, claim_map, audit = _inputs(tmp_path)
    claims["claims"][0]["kind"] = "limitation"
    claim_map["mappings"][0]["overall_support"] = "not-found"
    claim_map["mappings"][0]["loci"][0]["support_relation"] = "insufficient"
    claim_map["mappings"][0]["loci"][0]["supports_claim"] = False
    audit["claim_results"][0]["verdict"] = "insufficient"
    audit["claim_results"][0]["verified_locus_ids"] = []
    audit["claim_results"][0]["unsupported_locus_ids"] = ["L1"]
    report = build_attribution_report(
        claims, claim_map, audit, run_dir=tmp_path, require_complete_claims=True,
        coverage_based_absence_claim_ids={"C1"},
    )
    assert report["verdict"] == "PASS_WITH_CAVEATS"


def test_strict_map_without_exact_locator_blocks(tmp_path):
    claims, claim_map, audit = _inputs(tmp_path)
    claim_map["mappings"][0]["loci"][0].pop("char_end")
    report = build_attribution_report(claims, claim_map, audit, run_dir=tmp_path)
    assert report["verdict"] == "BLOCK"
    assert any("no exact char span" in row for row in report["violations"])


def test_document_hash_mismatch_alone_no_longer_blocks(tmp_path):
    """R3 A1/B1 (2026-08-07): document_hash re-verification is torn down — the field is still
    written but no longer compared against the snapshot's recomputed sha256. What still gates
    the locus is the actual content check: exact_quote must match the snapshot bytes (see
    test_recomputed_span_quote_mismatch_blocks, unaffected by this change)."""
    claims, claim_map, audit = _inputs(tmp_path)
    claim_map["mappings"][0]["loci"][0]["document_hash"] = "0" * 64
    report = build_attribution_report(claims, claim_map, audit, run_dir=tmp_path)
    assert report["verdict"] == "PASS"
    assert report["mechanical_verification"]["n_verified"] == 1


def test_recomputed_span_quote_mismatch_blocks(tmp_path):
    claims, claim_map, audit = _inputs(tmp_path)
    claim_map["mappings"][0]["loci"][0]["exact_quote"] = "A fabricated quote"
    report = build_attribution_report(claims, claim_map, audit, run_dir=tmp_path)
    assert report["verdict"] == "BLOCK"
    assert any("exact_quote mismatch" in row for row in report["violations"])


def test_missing_snapshot_is_unverified_never_pass(tmp_path):
    claims, claim_map, audit = _inputs(tmp_path)
    claim_map["mappings"][0]["loci"][0]["snapshot_ref"] = "snapshots/missing.txt"
    report = build_attribution_report(claims, claim_map, audit, run_dir=tmp_path)
    assert report["verdict"] == "UNVERIFIED"
    assert report["mechanical_verification"]["n_unverified"] == 1
    assert report["citation_correctness"] == 0.0
    assert report["claim_completeness"] == 0.0
    assert report["unverified_reasons"]


def test_absent_independent_auditor_blocks_current_run(tmp_path):
    claims, claim_map, _audit = _inputs(tmp_path)
    report = build_attribution_report(claims, claim_map, {}, run_dir=tmp_path)
    assert report["verdict"] == "BLOCK"
    assert any("independent citation audit missing" in row for row in report["violations"])


def test_explicit_legacy_replay_is_visible_and_can_never_pass(tmp_path):
    claims, claim_map, _audit = _inputs(tmp_path)
    claim_map.pop("attribution_contract_version")
    for locus in claim_map["mappings"][0]["loci"]:
        for key in ("support_relation", "span_id", "snapshot_ref", "document_hash",
                    "parser_version", "char_start", "char_end", "exact_quote"):
            locus.pop(key, None)
    marker = tmp_path / "inbox" / "citation-legacy-replay.json"
    marker.parent.mkdir(parents=True)
    marker.write_text(json.dumps({
        "contract_version": "citation-legacy-replay/v1",
        "legacy_replay": True,
        "reason": "historical fixture predates exact claim-span attribution",
        "source_run_ref": "old-run-1",
    }), encoding="utf-8")
    report = build_run_attribution_report(tmp_path, claims, claim_map, None)
    assert report["verdict"] == "UNVERIFIED"
    assert report["legacy_replay"] is True
    assert report["citation_f1"] == 0.0
    assert validate_payload("citation_attribution_report", report) == []


def test_machine_readable_json_table_cell_can_be_reopened_and_verified(tmp_path):
    claims, claim_map, audit = _inputs(tmp_path)
    table = tmp_path / "snapshots" / "table.json"
    table.write_text(json.dumps({"rows": [{"metric": "Dice", "value": "0.91"}]}), encoding="utf-8")
    locus = claim_map["mappings"][0]["loci"][0]
    locus.update({
        "kind": "table",
        "location": "Table 2, Dice cell",
        "reported_result": "0.91",
        "snapshot_ref": "snapshots/table.json",
        "document_hash": hashlib.sha256(table.read_bytes()).hexdigest(),
        "table_cell_ref": "json-pointer:/rows/0/value",
        "exact_quote": "0.91",
    })
    locus.pop("char_start")
    locus.pop("char_end")
    report = build_attribution_report(claims, claim_map, audit, run_dir=tmp_path)
    assert report["verdict"] == "PASS"
    assert report["mechanical_verification"]["locus_results"][0]["quote_verified"] is True


def test_snapshot_path_escape_is_a_hard_policy_block(tmp_path):
    claims, claim_map, audit = _inputs(tmp_path)
    outside = tmp_path.parent / f"{tmp_path.name}-outside.txt"
    outside.write_text(QUOTE, encoding="utf-8")
    locus = claim_map["mappings"][0]["loci"][0]
    locus.update({
        "snapshot_ref": f"../{outside.name}",
        "document_hash": hashlib.sha256(outside.read_bytes()).hexdigest(),
        "char_start": 0,
        "char_end": len(QUOTE),
    })
    report = build_attribution_report(claims, claim_map, audit, run_dir=tmp_path)
    assert report["verdict"] == "BLOCK"
    assert any("escapes the run directory" in row for row in report["violations"])
