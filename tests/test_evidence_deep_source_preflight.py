"""Regression coverage for evidence_deep's source-first operating contract."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from research_agent_teams.operate import spine
from research_agent_teams.operate.artifacts import GateBlock, TargetedGateBlock
from research_agent_teams.operate.cli import cmd_commit, cmd_run_dets, cmd_worker
from research_agent_teams.operate.modes import evidence_deep, evidence_review
from research_agent_teams.operate.panel_scheduler import PanelContractError
from research_agent_teams.tools.citation_attribution import (
    prepare_fulltext_citation_inputs,
)
from research_agent_teams.tools.ledger import read_events
from research_agent_teams.tools.runstore import classify_status, read_manifest


TS = "2026-07-13T00:00:00Z"


def test_mixed_pdf_markdown_html_and_python_sources_can_be_frozen(tmp_path):
    run_dir = tmp_path / "run"
    docs_dir = run_dir / "inbox" / "fulltext-docs"
    docs_dir.mkdir(parents=True)
    protocol = docs_dir / "autopet-v-protocol.md"
    protocol.write_text("# Protocol\nAUC-Dice is the primary metric.", encoding="utf-8")
    repository = docs_dir / "interactive_loop.py"
    repository.write_text("def simulate_click():\n    return 'GT-derived'\n", encoding="utf-8")
    webpage = docs_dir / "task.html"
    webpage.write_text(
        "<html><body><h1>autoPET V</h1><script>ignore()</script><p>Multi-round correction task.</p></body></html>",
        encoding="utf-8",
    )
    fitz = pytest.importorskip("fitz")
    paper = docs_dir / "paper.pdf"
    pdf = fitz.open()
    page = pdf.new_page()
    page.insert_text((72, 72), "PET CT residual correction reference paper")
    pdf.save(str(paper))
    pdf.close()

    report_path = prepare_fulltext_citation_inputs(
        run_dir, "verify autoPET V protocol", [str(paper), str(protocol), str(repository), str(webpage)]
    )
    report = json.loads(Path(report_path).read_text(encoding="utf-8"))
    manifest = json.loads((run_dir / "inbox" / "citation-snapshots" / "fulltext-contexts.manifest.json").read_text(
        encoding="utf-8"
    ))

    assert manifest is not None
    assert manifest["parser_version"] == "mixed-local-source/v1"
    assert report["available"] is True
    assert {
        str(paper.resolve()), str(protocol.resolve()), str(repository.resolve()), str(webpage.resolve())
    } <= {str(row["doc_ref"]) for row in report["contexts"]}
    snapshot = (run_dir / manifest["snapshot_ref"]).read_text(encoding="utf-8")
    assert "AUC-Dice" in snapshot and "simulate_click" in snapshot
    assert "Multi-round correction task." in snapshot and "ignore()" not in snapshot

    preflight_path = evidence_deep.register_source_preflight(
        str(run_dir),
        ["PETCT-paper", "autoPET-V-protocol", "autoPET-V-interactive-loop", "autoPET-V-task"],
        [str(paper), str(protocol), str(repository), str(webpage)],
        TS,
    )
    result = evidence_deep.source_preflight(str(run_dir))
    payload = json.loads(Path(preflight_path).read_text(encoding="utf-8"))
    assert result["source_preflight"] == "PASS"
    assert payload["document_hash"] == manifest["document_hash"]
    assert payload["sources"][0]["parser_version"] == "pymupdf-page-text/v1"
    assert payload["sources"][2]["parser_version"] == "utf8-source-text/v1"
    assert payload["sources"][3]["parser_version"] == "html-body-text/v1"


def test_source_preflight_rejects_unavailable_or_incomplete_fulltext_qa_contexts(tmp_path):
    run_dir = tmp_path / "run"
    docs_dir = run_dir / "inbox" / "fulltext-docs"
    docs_dir.mkdir(parents=True)
    a = docs_dir / "a.md"
    b = docs_dir / "b.py"
    a.write_text("# A\nProtocol detail", encoding="utf-8")
    b.write_text("VALUE = 'B'", encoding="utf-8")
    prepare_fulltext_citation_inputs(run_dir, "verify sources", [str(a), str(b)])
    report_path = run_dir / "inbox" / "fulltext-qa.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    report["available"] = False
    report["reason"] = "engine unavailable"
    report_path.write_text(json.dumps(report), encoding="utf-8")

    with pytest.raises(ValueError, match="rejects unavailable fulltext QA"):
        evidence_deep.register_source_preflight(str(run_dir), ["A", "B"], [str(a), str(b)], TS)

    report["available"] = True
    report["reason"] = ""
    report["contexts"] = [report["contexts"][0]]
    report_path.write_text(json.dumps(report), encoding="utf-8")
    with pytest.raises(ValueError, match="did not yield fulltext QA contexts"):
        evidence_deep.register_source_preflight(str(run_dir), ["A", "B"], [str(a), str(b)], TS)


def test_missing_frozen_sources_fail_before_any_evidence_deep_worker(tmp_path, capsys):
    runs = tmp_path / "runs"
    plan = spine.begin(str(runs), "preflight-block", "verify novelty", "evidence_deep", TS)

    class Args:
        runs_dir = str(runs)
        run_id = "preflight-block"
        stage = "DISCOVER"
        request = None
        vault = None
        ts = TS

    with pytest.raises(SystemExit) as exc:
        cmd_worker(Args())

    assert exc.value.code == 3
    output = json.loads(capsys.readouterr().out)
    assert output["gate"] == "BLOCK" and output["run_status"] == "failed"
    run_dir = Path(plan["run_dir"])
    manifest = read_manifest(run_dir)
    assert manifest["status"] == "failed"
    assert manifest["failure"]["stage"] == "DISCOVER"
    assert classify_status(run_dir) == "failed"
    assert not any(event["event_type"] == "stage_started" for event in read_events(run_dir / "ledger.jsonl"))


@pytest.mark.parametrize(
    ("exc", "expected_status"),
    [
        # R3 A4 (2026-08-07): terminal = isinstance(gb, TargetedGateBlock) and gb.verdict == "BLOCK"
        # (operate/cli.py:445-455) — a PLAIN GateBlock is never targeted, so it is never terminal
        # any more. It now takes the same "running" (halted, STAGE_HALTED, exit code still 3) path
        # as a repairable TargetedGateBlock, just for a different reason (untargeted, not
        # repairable-verdict).
        (GateBlock("citation gate BLOCK"), "running"),
        (TargetedGateBlock("hard targeted BLOCK", [], verdict="BLOCK"), "failed"),
        (TargetedGateBlock("repairable supplement", [], verdict="NEEDS_SUPPLEMENT"), "running"),
    ],
)
def test_cli_distinguishes_terminal_and_repairable_gateblocks(tmp_path, capsys, monkeypatch, exc, expected_status):
    runs = tmp_path / "runs"
    spine.begin(str(runs), "gate-kind", "review evidence", "evidence_review", TS)
    run_dir = runs / "gate-kind"

    monkeypatch.setattr(
        "research_agent_teams.operate.cli._schedule_or_exit",
        lambda *args, **kwargs: (None, {"status": "complete"}),
    )

    def raise_gate(*args, **kwargs):
        raise exc

    monkeypatch.setattr(evidence_review, "run_dets_with_repair", raise_gate)

    class Args:
        runs_dir = str(runs)
        run_id = "gate-kind"
        stage = "DISCOVER"
        ts = TS
        no_repair = False

    with pytest.raises(SystemExit) as exit_info:
        cmd_run_dets(Args())

    assert exit_info.value.code == 3
    output = json.loads(capsys.readouterr().out)
    assert output["run_status"] == expected_status
    manifest = read_manifest(run_dir)
    assert manifest["status"] == expected_status
    if expected_status == "failed":
        assert manifest["failure"]["stage"] == "DISCOVER"
        assert any(event["event_type"] == "run_failed" for event in read_events(run_dir / "ledger.jsonl"))
    else:
        assert not manifest.get("failure")


def test_cli_commit_cannot_leave_a_blocked_artifact_running(tmp_path, capsys):
    runs = tmp_path / "runs"
    plan = spine.begin(str(runs), "commit-block", "review evidence", "evidence_review", TS)
    run_dir = Path(plan["run_dir"])
    blocked = run_dir / "evidence" / "DISCOVER" / "evidence-verdict.artifact.json"
    blocked.parent.mkdir(parents=True)
    blocked.write_text(json.dumps({"status": "blocked"}), encoding="utf-8")

    class Args:
        runs_dir = str(runs)
        run_id = "commit-block"
        stage = "DISCOVER"
        ts = TS

    with pytest.raises(SystemExit) as exit_info:
        cmd_commit(Args())

    assert exit_info.value.code == 3
    output = json.loads(capsys.readouterr().out)
    assert output["run_status"] == "failed"
    assert read_manifest(run_dir)["failure"]["stage"] == "DISCOVER"


@pytest.mark.parametrize("command", [cmd_worker, cmd_run_dets])
def test_cli_terminalizes_unrecoverable_scheduler_contract_block(tmp_path, capsys, monkeypatch, command):
    """A bad predecessor contract is a hard refusal, never a still-running run."""
    runs = tmp_path / "runs"
    plan = spine.begin(str(runs), "scheduler-contract-block", "review evidence", "evidence_review", TS)
    run_dir = Path(plan["run_dir"])

    def refuse_contract(*args, **kwargs):
        raise PanelContractError(
            "evidence_deep claim-evidence-linker output contract BLOCK: legacy claims/evidence shape"
        )

    monkeypatch.setattr("research_agent_teams.operate.cli._schedule_stage_worker", refuse_contract)

    class Args:
        runs_dir = str(runs)
        run_id = "scheduler-contract-block"
        stage = "DISCOVER"
        request = None
        vault = None
        ts = TS
        no_repair = False

    with pytest.raises(SystemExit) as exit_info:
        command(Args())

    assert exit_info.value.code == 3
    output = json.loads(capsys.readouterr().out)
    assert output["scheduler_block"] is True
    assert output["run_status"] == "failed"
    assert output["gate"] == "BLOCK"
    assert Path(output["director_review_packet"]).is_file()
    manifest = read_manifest(run_dir)
    assert manifest["status"] == "failed"
    assert manifest["failure"]["stage"] == "DISCOVER"
    assert any(event["event_type"] == "run_failed" for event in read_events(run_dir / "ledger.jsonl"))
