"""Tier-S ingest panel tests: independent verification without becoming a deep read."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from research_agent_teams.operate.artifacts import GateBlock
from research_agent_teams.operate.modes import ingest_paper
from research_agent_teams.tools.research_output_quality import audit_markdown_text
from research_agent_teams.tools.validate_artifact import validate_artifact


TS = "2026-07-10T12:00:00Z"
SOURCE_REF = "inbox/source-paper.txt"
TITLE = "Residual Intent for Interactive Segmentation"


def _mk_run(tmp_path: Path) -> tuple[Path, str]:
    run_dir = tmp_path / "ingest-run"
    (run_dir / "inbox").mkdir(parents=True)
    source = run_dir / SOURCE_REF
    source.write_text(
        "Residual Intent for Interactive Segmentation\n"
        "Method: a structured residual-intent prompt augments spatial clicks.\n"
        "Result: the oracle-intent arm improved Dice on the held-out test split.\n",
        encoding="utf-8",
    )
    fingerprint = "sha256:" + hashlib.sha256(source.read_bytes()).hexdigest()
    task_frame = {
        "payload": {
            "task_id": "ingest-run",
            "mode": "ingest_paper",
            "north_star": {
                "statement": "residual intent for interactive segmentation",
                "in_scope": ["residual intent", "interactive segmentation", "oracle intent"],
                "out_of_scope": [],
            },
            "budget": {"max_agent_hops": 2, "max_debug_retries_per_run": 2},
        }
    }
    (run_dir / "task_frame.artifact.json").write_text(
        json.dumps(task_frame), encoding="utf-8")
    return run_dir, fingerprint


def _paper_note() -> dict:
    return {
        "title": TITLE,
        "source_ref": SOURCE_REF,
        "summary": (
            "The paper studies structured residual-intent prompts for interactive segmentation "
            "and reports an oracle-intent comparison."
        ),
        "claims": [
            "A structured residual-intent prompt augments spatial clicks.",
            "The oracle-intent arm improved Dice on the held-out test split.",
        ],
        "methods": ["structured residual-intent prompting"],
        "datasets": ["held-out test split"],
        "metrics": ["Dice"],
        "paper_type": "method",
        "read_purpose": "method",
        "relation_to_thesis": "A-core",
        "reading_objective": "Decide whether this paper needs a deep method read.",
        "reading_status": "skimmed",
        "paper_contract": {
            "category": "interactive segmentation method",
            "context": "spatial correction with structured text intent",
            "correctness_prior": "unverified skim",
            "contributions": ["structured residual-intent prompt"],
            "clarity": "main idea is identifiable from the skim",
            "contract_sentence": (
                "interactive correction -> structured intent -> click-only baseline -> "
                "oracle comparison -> held-out setting"
            ),
        },
    }


def _extractor(fingerprint: str) -> dict:
    note = _paper_note()
    return {
        "worker_contract": {"role": "paper-note-extractor", "source_read": True},
        "source_snapshot": {
            "source_ref": SOURCE_REF,
            "snapshot_ref": SOURCE_REF,
            "snapshot_fingerprint": fingerprint,
            "title": TITLE,
        },
        "paper_note": note,
        "claim_records": [
            {
                "claim_id": "C1",
                "claim": note["claims"][0],
                "source_section": "method",
                "source_location": "line 2",
                "evidence_excerpt": "structured residual-intent prompt augments spatial clicks",
            },
            {
                "claim_id": "C2",
                "claim": note["claims"][1],
                "source_section": "results",
                "source_location": "line 3",
                "evidence_excerpt": "oracle-intent arm improved Dice",
            },
        ],
    }


def _verifier(fingerprint: str, verdict: str = "PASS") -> dict:
    note = _paper_note()
    return {
        "worker_contract": {
            "role": "source-claim-verifier",
            "independent_of_extractor": True,
            "reopened_source_snapshot": True,
        },
        "verification": {
            "verdict": verdict,
            "source_identity": {
                "source_ref": SOURCE_REF,
                "snapshot_ref": SOURCE_REF,
                "snapshot_fingerprint": fingerprint,
                "verified_title": TITLE,
                "source_ref_match": True,
                "title_match": True,
            },
            "summary_result": {
                "verdict": "SUPPORTED",
                "reason": "Both the method and oracle comparison are stated in the snapshot.",
            },
            "claim_results": [
                {
                    "claim_id": "C1",
                    "claim": note["claims"][0],
                    "verdict": "SUPPORTED",
                    "reason": "The method line states this directly.",
                    "source_location": "line 2",
                    "section_confusion": False,
                },
                {
                    "claim_id": "C2",
                    "claim": note["claims"][1],
                    "verdict": "SUPPORTED",
                    "reason": "The result line states the held-out Dice improvement.",
                    "source_location": "line 3",
                    "section_confusion": False,
                },
            ],
            "field_results": [
                {
                    "field": "methods",
                    "item": note["methods"][0],
                    "verdict": "SUPPORTED",
                    "reason": "Named in the method line.",
                },
                {
                    "field": "datasets",
                    "item": note["datasets"][0],
                    "verdict": "SUPPORTED",
                    "reason": "The result identifies a held-out split.",
                },
                {
                    "field": "metrics",
                    "item": note["metrics"][0],
                    "verdict": "SUPPORTED",
                    "reason": "Dice is named in the result line.",
                },
            ],
            "section_confusion_check": {
                "abstract_or_method_presented_as_result": False,
                "reasons": [],
            },
            "deep_read_reasons": [],
        },
    }


def _write_panel(run_dir: Path, extractor: dict, verifier: dict) -> None:
    (run_dir / "inbox" / "DISCOVER.paper-note-extractor.bundle.json").write_text(
        json.dumps(extractor, ensure_ascii=False), encoding="utf-8")
    (run_dir / "inbox" / "DISCOVER.source-claim-verifier.bundle.json").write_text(
        json.dumps(verifier, ensure_ascii=False), encoding="utf-8")


def _artifact_payload(paths: list[str], stem: str) -> dict:
    path = next(Path(value) for value in paths if Path(value).stem == stem)
    artifact = json.loads(path.read_text(encoding="utf-8"))
    assert validate_artifact(artifact) == []
    return artifact["payload"]


def test_llm_step_is_ordered_two_worker_panel(tmp_path):
    run_dir, _ = _mk_run(tmp_path)
    spec = ingest_paper.llm_step(str(run_dir), "DISCOVER", "ingest this residual intent paper")

    assert spec["worker_order"] == ["paper-note-extractor", "source-claim-verifier"]
    assert [worker["label"] for worker in spec["workers"]] == spec["worker_order"]
    assert len({worker["output"] for worker in spec["workers"]}) == 2
    assert all("NORTH STAR" in worker["prompt"] for worker in spec["workers"])
    assert "independently\nreopen" in spec["workers"][1]["prompt"]
    assert "must not rewrite" in spec["workers"][1]["prompt"]
    assert "read_paper_deep" not in spec["workers"][0]["prompt"]


def test_panel_pass_writes_filtered_draft_and_quick_note(tmp_path):
    run_dir, fingerprint = _mk_run(tmp_path)
    _write_panel(run_dir, _extractor(fingerprint), _verifier(fingerprint))

    paths, report = ingest_paper.run_dets(run_dir, "DISCOVER", TS)
    note = _artifact_payload(paths, "paper-note.artifact")
    verification = _artifact_payload(paths, "paper-note-verification.artifact")

    assert report["verification_verdict"] == "PASS"
    assert report["legacy_unverified"] is False
    assert note["claims"] == _paper_note()["claims"]
    assert verification["independent_verifier"] is True
    assert verification["n_claims_retained"] == len(note["claims"])
    markdown = run_dir / report["director_markdown"]
    text = markdown.read_text(encoding="utf-8")
    assert "SKIMMED DRAFT / QUICK NOTE" in text
    assert "not a deep read" in text
    assert "NOT_PROMOTED" in text
    assert "Verifier Findings" in text
    assert len(text) >= 600
    assert audit_markdown_text("ingest_paper", text)["status"] == "pass"

    report_paths, report_body = ingest_paper.run_dets(run_dir, "REPORT", TS)
    _artifact_payload(report_paths, "report-note.artifact")
    assert report["director_markdown"] in report_body["director_markdown"]


def test_needs_deep_read_filters_unsupported_claim_and_field(tmp_path):
    run_dir, fingerprint = _mk_run(tmp_path)
    verifier = _verifier(fingerprint, verdict="NEEDS_DEEP_READ")
    verifier["verification"]["claim_results"][1].update({
        "verdict": "UNSUPPORTED",
        "reason": "The snapshot does not provide a numeric comparison or uncertainty.",
    })
    verifier["verification"]["field_results"][1].update({
        "verdict": "UNCLEAR",
        "reason": "A split is mentioned, but no named dataset is identifiable from the skim.",
    })
    verifier["verification"]["deep_read_reasons"] = [
        "Inspect the full result table and split protocol."
    ]
    _write_panel(run_dir, _extractor(fingerprint), verifier)

    paths, report = ingest_paper.run_dets(run_dir, "DISCOVER", TS)
    note = _artifact_payload(paths, "paper-note.artifact")

    assert report["verification_verdict"] == "NEEDS_DEEP_READ"
    assert note["claims"] == [_paper_note()["claims"][0]]
    assert note["datasets"] == []
    assert _paper_note()["claims"][1] not in note["claims"]
    text = (run_dir / report["director_markdown"]).read_text(encoding="utf-8")
    assert "NEEDS_DEEP_READ" in text
    assert "Dropped claims: `1`" in text
    assert "Run `read_paper_deep`" in text


def test_verifier_pass_cannot_hide_unsupported_claim(tmp_path):
    run_dir, fingerprint = _mk_run(tmp_path)
    verifier = _verifier(fingerprint, verdict="PASS")
    verifier["verification"]["claim_results"][1]["verdict"] = "UNSUPPORTED"
    _write_panel(run_dir, _extractor(fingerprint), verifier)

    with pytest.raises(GateBlock, match="verdict inconsistent"):
        ingest_paper.run_dets(run_dir, "DISCOVER", TS)


def test_missing_claim_coverage_blocks(tmp_path):
    run_dir, fingerprint = _mk_run(tmp_path)
    verifier = _verifier(fingerprint)
    verifier["verification"]["claim_results"].pop()
    _write_panel(run_dir, _extractor(fingerprint), verifier)

    with pytest.raises(GateBlock, match="completely cover"):
        ingest_paper.run_dets(run_dir, "DISCOVER", TS)


def test_partial_new_panel_blocks_instead_of_falling_back_to_legacy(tmp_path):
    run_dir, fingerprint = _mk_run(tmp_path)
    (run_dir / "inbox" / "DISCOVER.paper-note-extractor.bundle.json").write_text(
        json.dumps(_extractor(fingerprint), ensure_ascii=False), encoding="utf-8")
    (run_dir / "inbox" / "DISCOVER.bundle.json").write_text(
        json.dumps({"paper_note": _paper_note()}, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(GateBlock, match="panel missing bundle"):
        ingest_paper.run_dets(run_dir, "DISCOVER", TS)


def test_declared_block_never_produces_a_note(tmp_path):
    run_dir, fingerprint = _mk_run(tmp_path)
    verifier = _verifier(fingerprint, verdict="BLOCK")
    verifier["verification"]["deep_read_reasons"] = ["The source could not be verified honestly."]
    _write_panel(run_dir, _extractor(fingerprint), verifier)

    with pytest.raises(GateBlock, match="verifier BLOCK"):
        ingest_paper.run_dets(run_dir, "DISCOVER", TS)
    assert not (run_dir / "evidence" / "DISCOVER" / "paper-note.artifact.json").exists()


def test_source_identity_mismatch_blocks(tmp_path):
    run_dir, fingerprint = _mk_run(tmp_path)
    verifier = _verifier(fingerprint)
    verifier["verification"]["source_identity"]["verified_title"] = "A Different Paper"
    _write_panel(run_dir, _extractor(fingerprint), verifier)

    with pytest.raises(GateBlock, match="source identity BLOCK"):
        ingest_paper.run_dets(run_dir, "DISCOVER", TS)


def test_local_snapshot_hash_mismatch_blocks(tmp_path):
    run_dir, fingerprint = _mk_run(tmp_path)
    extractor = _extractor(fingerprint)
    extractor["source_snapshot"]["snapshot_fingerprint"] = "sha256:" + "0" * 64
    verifier = _verifier("sha256:" + "0" * 64)
    _write_panel(run_dir, extractor, verifier)

    with pytest.raises(GateBlock, match="hash does not match"):
        ingest_paper.run_dets(run_dir, "DISCOVER", TS)


def test_external_identifier_without_reopenable_bytes_cannot_pass(tmp_path):
    run_dir, fingerprint = _mk_run(tmp_path)
    extractor = _extractor(fingerprint)
    extractor["source_snapshot"].update({
        "snapshot_ref": "https://doi.org/10.0000/example",
        "snapshot_fingerprint": "sha256:" + "1" * 64,
    })
    verifier = _verifier("sha256:" + "1" * 64, verdict="PASS")
    verifier["verification"]["source_identity"]["snapshot_ref"] = (
        "https://doi.org/10.0000/example"
    )
    _write_panel(run_dir, extractor, verifier)

    with pytest.raises(GateBlock, match="verdict inconsistent"):
        ingest_paper.run_dets(run_dir, "DISCOVER", TS)


def test_external_identifier_is_explicit_needs_deep_read(tmp_path):
    run_dir, fingerprint = _mk_run(tmp_path)
    extractor = _extractor(fingerprint)
    extractor["source_snapshot"].update({
        "snapshot_ref": "https://arxiv.org/abs/0000.00000",
        "snapshot_fingerprint": "sha256:" + "2" * 64,
    })
    verifier = _verifier("sha256:" + "2" * 64, verdict="NEEDS_DEEP_READ")
    verifier["verification"]["source_identity"]["snapshot_ref"] = (
        "https://arxiv.org/abs/0000.00000"
    )
    verifier["verification"]["deep_read_reasons"] = [
        "Fetch an immutable fulltext snapshot."
    ]
    _write_panel(run_dir, extractor, verifier)

    paths, report = ingest_paper.run_dets(run_dir, "DISCOVER", TS)
    verification = _artifact_payload(paths, "paper-note-verification.artifact")
    assert report["verification_verdict"] == "NEEDS_DEEP_READ"
    assert verification["snapshot_locally_verified"] is False
    assert any("hash-verifiable" in reason for reason in verification["deep_read_reasons"])


def test_legacy_bundle_replays_but_is_visibly_unverified(tmp_path):
    run_dir, _ = _mk_run(tmp_path)
    (run_dir / "inbox" / "DISCOVER.bundle.json").write_text(
        json.dumps({"paper_note": copy.deepcopy(_paper_note())}, ensure_ascii=False),
        encoding="utf-8",
    )

    paths, report = ingest_paper.run_dets(run_dir, "DISCOVER", TS)
    note = _artifact_payload(paths, "paper-note.artifact")

    assert note["claims"] == _paper_note()["claims"]
    assert report["verification_verdict"] == "LEGACY_UNVERIFIED"
    assert report["legacy_unverified"] is True
    text = (run_dir / report["director_markdown"]).read_text(encoding="utf-8")
    assert "LEGACY UNVERIFIED" in text
    assert "No independent claim-level findings" in text
