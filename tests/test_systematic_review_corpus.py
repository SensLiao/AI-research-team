"""Deterministic corpus accounting for publication-grade systematic reviews."""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from research_agent_teams.tools.systematic_review_corpus import (
    build_execution_manifest,
    canonical_report_identity,
    main,
    validate_manifest,
    write_manifest,
)


SCHEMA_PATH = (
    Path(__file__).resolve().parents[2]
    / "research_agent_teams"
    / "schemas"
    / "systematic_review_execution_manifest.schema.json"
)
SHA_A = "sha256:" + "a" * 64
SHA_B = "sha256:" + "b" * 64


def _permission(*, figure_reuse: bool = False) -> dict:
    uses = ["text_mining", "quotation"]
    if figure_reuse:
        uses.append("figure_reuse")
    return {
        "status": "open_access",
        "basis": "publisher open-access licence recorded in the source snapshot",
        "allowed_uses": uses,
    }


def _decision(value: str) -> dict:
    return {"reviewer_1": value, "reviewer_2": value}


def _paper(
    record_id: str,
    *,
    title: str,
    doi: str | None = None,
    arxiv: str | None = None,
    pmid: str | None = None,
    study_key: str | None = None,
    source_tier: str = "tier_1",
    oracle_rung: str = "O2",
    fulltext_sha: str = SHA_A,
) -> dict:
    row = {
        "record_id": record_id,
        "title": title,
        "document_type": "journal_article",
        "study_key": study_key or record_id,
        "source_tier": source_tier,
        "oracle_rung": oracle_rung,
        "screening": {
            "title_abstract": _decision("include"),
            "fulltext": _decision("include"),
        },
        "fulltext": {
            "ref": f"inbox/fulltext-docs/{record_id}.pdf",
            "sha256": fulltext_sha,
            "content_type": "application/pdf",
            "permission": _permission(),
        },
        "extraction": {
            "oracle_access": {
                "status": "present",
                "value": "oracle labels are exposed during evaluation",
                "evidence_refs": [f"{record_id}:p5"],
            },
            "prompt_release": {"status": "absent", "evidence_refs": [f"{record_id}:p8"]},
            "seed_reporting": {"status": "unclear", "evidence_refs": [f"{record_id}:p9"]},
            "clinical_endpoint": {"status": "NA", "evidence_refs": [f"{record_id}:p2"]},
        },
    }
    if doi:
        row["doi"] = doi
    if arxiv:
        row["arxiv"] = arxiv
    if pmid:
        row["pmid"] = pmid
    return row


def _search_log(*record_ids: str, source_id: str = "crossref") -> dict:
    return {
        "source_id": source_id,
        "source_type": "database",
        "query": "hidden oracle AND prompt provenance",
        "executed_at": "2026-08-17T04:00:00Z",
        "record_ids": list(record_ids),
    }


def _manifest(records: list[dict], logs: list[dict], **kwargs) -> dict:
    return build_execution_manifest(
        records,
        logs,
        review_id="hidden-oracle-systematic-review",
        oracle_rulebook_version="oracle-ladder/2026-08-17",
        **kwargs,
    )


def test_identity_uses_doi_then_arxiv_then_pmid_then_normalized_title():
    assert canonical_report_identity(
        {"title": "Ignored", "doi": "https://doi.org/10.1000/ABC.1", "arxiv": "2401.00001"}
    ) == "doi:10.1000/abc.1"
    assert canonical_report_identity(
        {"title": "Ignored", "arxiv": "arXiv:2401.00001v3", "pmid": "1234"}
    ) == "arxiv:2401.00001"
    assert canonical_report_identity({"title": "Ignored", "pmid": "PMID: 1234"}) == "pmid:1234"
    assert canonical_report_identity({"title": "  A  Hidden-Oracle Study!  "}) == (
        "title:a hidden oracle study"
    )


def test_deduplicates_reports_groups_multiple_reports_into_study_and_recounts_tiers():
    journal = _paper(
        "r-journal",
        title="Complete study",
        doi="10.1000/complete",
        study_key="study-alpha",
        source_tier="tier_1",
    )
    duplicate = copy.deepcopy(journal)
    duplicate["record_id"] = "r-duplicate"
    duplicate["fulltext"]["ref"] = journal["fulltext"]["ref"]
    preprint = _paper(
        "r-preprint",
        title="Earlier report of the same experiment",
        arxiv="2401.00002v2",
        study_key="study-alpha",
        source_tier="tier_2",
        fulltext_sha=SHA_B,
    )

    result = _manifest(
        [preprint, duplicate, journal],
        [_search_log("r-journal", "r-duplicate", "r-preprint")],
        claimed_source_count=855,
    )

    assert result["deduplication"] == {
        "identified_occurrences": 3,
        "unique_reports": 2,
        "duplicates_removed": 1,
        "duplicate_groups": [
            {
                "identity": "doi:10.1000/complete",
                "record_ids": ["r-duplicate", "r-journal"],
                "kept_record_id": "r-duplicate",
            }
        ],
    }
    assert result["source_tier_counts"] == {
        "basis": "unique_paper_reports_after_deduplication",
        "total": 2,
        "by_tier": {"tier_1": 1, "tier_2": 1},
        "legacy_claimed_total": 855,
        "legacy_scalar_matches": False,
    }
    assert len(result["included_studies"]) == 1
    assert result["included_studies"][0]["report_identities"] == [
        "arxiv:2401.00002",
        "doi:10.1000/complete",
    ]


def test_double_screening_records_resolved_and_unresolved_conflicts():
    resolved = _paper("r1", title="Resolved", doi="10.1000/r1")
    resolved["screening"]["title_abstract"] = {
        "reviewer_1": "include",
        "reviewer_2": "exclude",
        "resolution": {
            "decision": "include",
            "resolver": "consensus",
            "reason": "full abstract clarified the population",
        },
    }
    unresolved = _paper("r2", title="Unresolved", doi="10.1000/r2")
    unresolved["screening"]["title_abstract"] = {
        "reviewer_1": "include",
        "reviewer_2": "exclude",
    }
    result = _manifest([unresolved, resolved], [_search_log("r1", "r2")])

    assert [(row["stage"], row["status"]) for row in result["screening"]["conflicts"]] == [
        ("title_abstract", "resolved"),
        ("title_abstract", "unresolved"),
    ]
    assert result["screening"]["has_unresolved_conflicts"] is True
    assert result["prisma"]["records_screened"] == 2
    assert result["prisma"]["reports_sought_for_retrieval"] == 1


def test_fulltext_exclusion_requires_specific_reason():
    excluded = _paper("r1", title="Wrong evaluation", doi="10.1000/excluded")
    excluded["screening"]["fulltext"] = _decision("exclude")
    with pytest.raises(ValueError, match="fulltext exclusion reason"):
        _manifest([excluded], [_search_log("r1")])

    excluded["fulltext_exclusion_reason"] = "No oracle-free comparator was evaluated"
    result = _manifest([excluded], [_search_log("r1")])
    assert result["screening"]["fulltext_exclusions"] == [
        {
            "identity": "doi:10.1000/excluded",
            "reason": "No oracle-free comparator was evaluated",
        }
    ]
    assert result["prisma"]["reports_excluded"] == 1
    assert result["prisma"]["studies_included"] == 0


def test_internal_documents_are_not_counted_as_papers_and_cards_cannot_masquerade_as_fulltext():
    paper = _paper("paper", title="Paper", doi="10.1000/paper")
    internal = {
        "record_id": "memo",
        "title": "Internal synthesis memo",
        "document_type": "internal_doc",
        "source_tier": "tier_4",
        "oracle_rung": "O0",
    }
    result = _manifest([internal, paper], [_search_log("memo", "paper")])
    assert result["source_tier_counts"]["total"] == 1
    assert result["prisma"]["records_removed_other_reasons"] == 1
    assert result["non_paper_records"] == [
        {
            "identity": "title:internal synthesis memo",
            "record_id": "memo",
            "document_type": "internal_doc",
            "reason": "non-paper record excluded before screening",
        }
    ]

    card = copy.deepcopy(paper)
    card["record_id"] = "card"
    card["title"] = "Database card"
    card["doi"] = "10.1000/card"
    card["document_type"] = "card"
    with pytest.raises(ValueError, match="cannot be treated as fulltext"):
        _manifest([card], [_search_log("card")])


def test_extraction_uses_exactly_four_states_and_present_requires_a_value():
    paper = _paper("r1", title="Extraction states", doi="10.1000/states")
    result = _manifest([paper], [_search_log("r1")])
    statuses = {
        row["field"]: row["status"] for row in result["included_studies"][0]["extractions"]
    }
    assert statuses == {
        "clinical_endpoint": "NA",
        "oracle_access": "present",
        "prompt_release": "absent",
        "seed_reporting": "unclear",
    }

    invalid = copy.deepcopy(paper)
    invalid["extraction"]["oracle_access"].pop("value")
    with pytest.raises(ValueError, match="present extraction.*value"):
        _manifest([invalid], [_search_log("r1")])

    invalid_status = copy.deepcopy(paper)
    invalid_status["extraction"]["oracle_access"]["status"] = "not reported"
    with pytest.raises(ValueError, match="extraction status"):
        _manifest([invalid_status], [_search_log("r1")])


def test_search_logs_permissions_prisma_and_manifest_schema_are_closed():
    a = _paper("a", title="A", doi="10.1000/a")
    b = _paper("b", title="B", arxiv="2401.00003")
    b["screening"]["title_abstract"] = _decision("exclude")
    log = _search_log("a", "b", source_id="openalex")
    result = _manifest([a, b], [log])

    assert result["search_sources"][0]["records_retrieved"] == 2
    assert result["search_sources"][0]["log_sha256"].startswith("sha256:")
    assert result["integrity"]["search_logs_sha256"].startswith("sha256:")
    assert result["permission_ledger"] == [
        {
            "identity": "doi:10.1000/a",
            "material_ref": "inbox/fulltext-docs/a.pdf",
            "material_sha256": SHA_A,
            "status": "open_access",
            "basis": "publisher open-access licence recorded in the source snapshot",
            "allowed_uses": ["quotation", "text_mining"],
            "figure_reuse_allowed": False,
        },
        {
            "identity": "arxiv:2401.00003",
            "material_ref": "inbox/fulltext-docs/b.pdf",
            "material_sha256": SHA_A,
            "status": "open_access",
            "basis": "publisher open-access licence recorded in the source snapshot",
            "allowed_uses": ["quotation", "text_mining"],
            "figure_reuse_allowed": False,
        },
    ]
    assert result["prisma"] == {
        "records_identified": 2,
        "duplicate_records_removed": 0,
        "records_removed_other_reasons": 0,
        "records_screened": 2,
        "records_excluded": 1,
        "reports_sought_for_retrieval": 1,
        "reports_not_retrieved": 0,
        "reports_assessed_for_eligibility": 1,
        "reports_excluded": 0,
        "reports_included": 1,
        "studies_included": 1,
    }
    Draft202012Validator.check_schema(json.loads(SCHEMA_PATH.read_text(encoding="utf-8")))
    errors = list(Draft202012Validator(json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))).iter_errors(result))
    assert errors == []


def test_manifest_is_deterministic_and_writer_validates_before_persisting(tmp_path):
    a = _paper("a", title="A", doi="10.1000/a")
    b = _paper("b", title="B", arxiv="2401.00003")
    logs = [_search_log("a", "b")]
    first = _manifest([a, b], logs)
    second = _manifest([b, a], logs)
    assert first == second

    destination = tmp_path / "manifest.json"
    write_manifest(destination, first)
    first_bytes = destination.read_bytes()
    write_manifest(destination, second)
    assert destination.read_bytes() == first_bytes

    tampered = copy.deepcopy(first)
    tampered["source_tier_counts"]["total"] = 999
    with pytest.raises(ValueError, match="source tier total"):
        validate_manifest(tampered)
    with pytest.raises(ValueError, match="source tier total"):
        write_manifest(destination, tampered)


def test_search_log_record_membership_and_prisma_arithmetic_fail_closed():
    paper = _paper("a", title="A", doi="10.1000/a")
    with pytest.raises(ValueError, match="unknown record_id"):
        _manifest([paper], [_search_log("a", "ghost")])

    result = _manifest([paper], [_search_log("a")])
    result["prisma"]["records_screened"] += 1
    with pytest.raises(ValueError, match="PRISMA arithmetic"):
        validate_manifest(result)


def test_oracle_rungs_and_rulebook_version_are_mandatory():
    paper = _paper("a", title="A", doi="10.1000/a")
    paper["oracle_rung"] = "O6"
    with pytest.raises(ValueError, match="oracle rung"):
        _manifest([paper], [_search_log("a")])
    with pytest.raises(ValueError, match="oracle_rulebook_version"):
        build_execution_manifest([_paper("a", title="A")], [_search_log("a")], review_id="r", oracle_rulebook_version="")


def test_one_report_can_preserve_multiple_protocol_level_oracle_rungs():
    paper = _paper(
        "r1", title="Mixed human and simulated protocols", doi="10.1000/mixed"
    )
    paper["oracle_rungs"] = ["O0", "O3", "O5"]

    result = _manifest([paper], [_search_log("r1")])

    assert result["reports"][0]["oracle_rungs"] == ["O0", "O3", "O5"]
    assert result["reports"][0]["oracle_rung"] == "O5"
    assert result["included_studies"][0]["oracle_rungs"] == ["O0", "O3", "O5"]


@pytest.mark.parametrize("exclusion_stage", ["title_abstract", "fulltext"])
def test_excluded_reports_may_remain_oracle_unclassified(exclusion_stage):
    paper = _paper("a", title="Excluded before oracle coding", doi="10.1000/excluded-unclassified")
    paper["oracle_rung"] = "UNCLASSIFIED"
    if exclusion_stage == "title_abstract":
        paper["screening"]["title_abstract"] = _decision("exclude")
    else:
        paper["screening"]["fulltext"] = _decision("exclude")
        paper["fulltext_exclusion_reason"] = "No hidden-oracle evaluation was reported"

    result = _manifest([paper], [_search_log("a")])

    assert result["reports"][0]["oracle_rung"] == "UNCLASSIFIED"
    assert result["included_studies"] == []


def test_included_report_must_have_a_classified_o0_to_o5_oracle_rung():
    paper = _paper("a", title="Included but uncoded", doi="10.1000/included-unclassified")
    paper["oracle_rung"] = "UNCLASSIFIED"

    with pytest.raises(ValueError, match=r"included report.*classified O0-O5"):
        _manifest([paper], [_search_log("a")])

    valid = _manifest(
        [_paper("a", title="Initially classified", doi="10.1000/included-classified")],
        [_search_log("a")],
    )
    valid["reports"][0]["oracle_rung"] = "UNCLASSIFIED"
    with pytest.raises(ValueError, match=r"included report.*classified O0-O5"):
        validate_manifest(valid)


def test_semantic_validation_rejects_inclusion_and_permission_mirrors_that_drift():
    paper = _paper("a", title="A", doi="10.1000/a")
    result = _manifest([paper], [_search_log("a")])

    bad_inclusion = copy.deepcopy(result)
    bad_inclusion["included_studies"][0]["report_identities"].append("doi:10.1000/ghost")
    with pytest.raises(ValueError, match="included report ledger"):
        validate_manifest(bad_inclusion)

    bad_primary = copy.deepcopy(result)
    bad_primary["included_studies"][0]["primary_report_identity"] = "doi:10.1000/ghost"
    with pytest.raises(ValueError, match="primary report"):
        validate_manifest(bad_primary)

    bad_permission = copy.deepcopy(result)
    bad_permission["permission_ledger"][0]["figure_reuse_allowed"] = True
    with pytest.raises(ValueError, match="figure_reuse_allowed"):
        validate_manifest(bad_permission)


def test_cli_writes_validated_manifest_and_prints_a_useful_count_summary(tmp_path, capsys):
    source = tmp_path / "corpus.json"
    destination = tmp_path / "execution-manifest.json"
    source.write_text(
        json.dumps(
            {
                "review_id": "hidden-oracle-systematic-review",
                "oracle_rulebook_version": "oracle-ladder/2026-08-17",
                "records": [_paper("a", title="A", doi="10.1000/a")],
                "search_logs": [_search_log("a")],
            }
        ),
        encoding="utf-8",
    )

    assert main(["--input", str(source), "--output", str(destination)]) == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["unique_reports"] == 1
    assert summary["included_studies"] == 1
    persisted = json.loads(destination.read_text(encoding="utf-8"))
    validate_manifest(persisted)
