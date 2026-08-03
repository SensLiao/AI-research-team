from __future__ import annotations

import json
from pathlib import Path

from research_agent_teams.operate import spine
from research_agent_teams.operate.artifacts import write_artifact
from research_agent_teams.operate.modes import venue_readiness as vr
from research_agent_teams.tests.test_operate_venue_readiness import (
    _profile,
    _reviews_with_fired_trigger,
    _stage_bundles,
)
from research_agent_teams.tools.director_packet import lint_packet, packet_path, write_packet
from research_agent_teams.tools.venue_readiness_markdown import venue_readiness_path


TS = "2026-07-10T00:00:00Z"
HEX = "a" * 64


def _write_manuscript_report(run_dir: Path, name: str, text: str) -> Path:
    path = run_dir / "director-review" / "manuscript" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _write_review_verdict(
    run_dir: Path,
    *,
    review_run_id: str,
    manuscript_ref: str = "runs/paper-001/manuscript/main.tex",
    manuscript_sha256: str = HEX,
    independent: bool = True,
) -> Path:
    path = run_dir / "evidence" / "VERIFY" / "manuscript-review-verdict.artifact.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "artifact_type": "manuscript_review_verdict",
                "payload": {
                    "review_run_id": review_run_id,
                    "reviewer_identity": {"independent_from_authoring": independent},
                    "blind_read_receipt": {"scheduler_authorization_sha256": "c" * 64},
                    "frozen_inputs": {
                        "manuscript_ref": manuscript_ref,
                        "manuscript_sha256": manuscript_sha256,
                    },
                    "verdict_sha256": "b" * 64,
                },
            }
        ),
        encoding="utf-8",
    )
    return path


def test_director_packet_renders_markdown_and_blocks_json_in_review_dir(tmp_path):
    runs = tmp_path / "runs"
    plan = spine.begin(str(runs), "pkt1", "read a paper deeply", "read_paper_deep", TS)
    rd = Path(plan["run_dir"])
    write_artifact(
        rd,
        "REPORT",
        "report-note.artifact.json",
        "report_note",
        "test",
        {"summary": "paper read complete", "references": [], "open_questions": []},
        TS,
    )
    write_artifact(
        rd,
        "DISCOVER",
        "paper-note.artifact.json",
        "paper_note",
        "test",
        {
            "title": "A useful paper",
            "source_ref": "doi:10.0000/example",
            "summary": "Detailed paper note for director review.",
            "claims": ["The paper supports the test packet."],
        },
        TS,
    )

    out = write_packet(rd, generated_at=TS)
    assert out == packet_path(rd)
    text = out.read_text(encoding="utf-8")
    assert "Director Review Packet - read_paper_deep - pkt1" in text
    assert "## Evidence Index" in text
    assert "paper-note.artifact.json" in text

    bad = rd / "director-review" / "bad.json"
    bad.write_text(json.dumps({"not": "allowed"}), encoding="utf-8")
    assert any("JSON is not allowed" in err for err in lint_packet(rd))


def test_report_commit_generates_director_packet(tmp_path):
    runs = tmp_path / "runs"
    plan = spine.begin(str(runs), "pkt2", "read a paper deeply", "read_paper_deep", TS)
    rd = Path(plan["run_dir"])
    report_path = write_artifact(
        rd,
        "REPORT",
        "report-note.artifact.json",
        "report_note",
        "test",
        {"summary": "paper read complete", "references": [], "open_questions": []},
        TS,
    )

    res = spine.commit_stage(rd, "REPORT", [report_path], TS)
    assert res["director_review_packet"].replace("\\", "/").endswith("director-review/00-REVIEW-PACKET.md")
    assert (rd / "director-review" / "00-REVIEW-PACKET.md").is_file()
    status = spine.status(rd)
    assert status["director_review_packet"].replace("\\", "/").endswith("director-review/00-REVIEW-PACKET.md")


def test_pending_packet_does_not_claim_completed_report(tmp_path):
    runs = tmp_path / "runs"
    plan = spine.begin(str(runs), "pkt-pending", "research a field", "deep_research", TS)
    rd = Path(plan["run_dir"])

    text = write_packet(rd, generated_at=TS).read_text(encoding="utf-8")

    assert "has not completed REPORT" in text
    assert "completed REPORT evidence" not in text


def test_pending_paper_card_does_not_use_completed_paper_packet(tmp_path):
    runs = tmp_path / "runs"
    plan = spine.begin(str(runs), "pkt-paper-pending", "read a paper", "read_paper_deep", TS)
    rd = Path(plan["run_dir"])
    card = rd / "director-review" / "papers" / "pending-paper.md"
    card.parent.mkdir(parents=True)
    card.write_text("# Pending Paper\n\nThis card is not yet committed.", encoding="utf-8")

    text = write_packet(rd, generated_at=TS).read_text(encoding="utf-8")

    assert "# Director Review Packet" in text
    assert "# Pending Paper" not in text


def test_pending_paper_card_artifact_keeps_packet_truthful(tmp_path):
    """A pre-REPORT card artifact must not make the director packet look complete."""
    runs = tmp_path / "runs"
    plan = spine.begin(str(runs), "pkt-paper-artifact-pending", "read a paper", "read_paper_deep", TS)
    rd = Path(plan["run_dir"])
    card = rd / "director-review" / "papers" / "pending-paper.md"
    card.parent.mkdir(parents=True)
    card.write_text("# Pending Paper\n\nThis card is not yet committed.", encoding="utf-8")
    write_artifact(
        rd,
        "DISCOVER",
        "paper-markdown-card.artifact.json",
        "paper_markdown_card",
        "paper-markdown-writer",
        {
            "source_ref": "doi:10.0000/pending",
            "title": "Pending Paper",
            "markdown": "Draft evidence. " * 50,
            "evidence_refs": [],
            "covered_claim_ids": [],
            "covered_figure_refs": [],
            "covered_sections": ["next-actions"],
            "quality_verdict": None,
        },
        TS,
    )

    text = write_packet(rd, generated_at=TS).read_text(encoding="utf-8")

    assert "Paper Markdown card artifact exists" in text
    assert "Director-facing paper card:" not in text


def test_director_packet_surfaces_evidence_deep_markdown_brief(tmp_path):
    runs = tmp_path / "runs"
    plan = spine.begin(str(runs), "pkt3", "review evidence deeply", "evidence_deep", TS)
    rd = Path(plan["run_dir"])
    brief = rd / "director-review" / "evidence" / "evidence-deep-brief.md"
    brief.parent.mkdir(parents=True)
    brief.write_text("# Evidence Deep Brief\n\nHuman-readable evidence synthesis.", encoding="utf-8")
    write_artifact(
        rd,
        "REPORT",
        "report-note.artifact.json",
        "report_note",
        "test",
        {"summary": "evidence deep complete", "references": [], "open_questions": []},
        TS,
    )
    write_artifact(
        rd,
        "DISCOVER",
        "claim-list.artifact.json",
        "claim_list",
        "claim-extractor",
        {"source_scope": "q", "claims": [
            {"claim_id": "c1", "text": "claim", "source_ref": "[[page-a]]"}]},
        TS,
    )
    write_artifact(
        rd,
        "DISCOVER",
        "contradiction-report.artifact.json",
        "contradiction_report",
        "contradiction-miner",
        {"n_claims_checked": 1, "conflicts": [], "summary": "none"},
        TS,
    )

    out = write_packet(rd, generated_at=TS)
    text = out.read_text(encoding="utf-8")
    assert "Director-facing evidence brief" in text
    assert "director-review/evidence/evidence-deep-brief.md" in text
    assert "Evidence panel extracted 1 anchored claims." in text


def test_director_packet_surfaces_gap_breadth_markdown_scan(tmp_path):
    runs = tmp_path / "runs"
    plan = spine.begin(str(runs), "pkt-gap", "scan gaps", "gap_breadth", TS)
    rd = Path(plan["run_dir"])
    scan = rd / "director-review" / "gaps" / "gap-scan.md"
    scan.parent.mkdir(parents=True)
    scan.write_text("# Gap Scan\n\n## Bottom Line\n\nHuman-readable gap scan.", encoding="utf-8")
    write_artifact(
        rd,
        "REPORT",
        "report-note.artifact.json",
        "report_note",
        "test",
        {
            "summary": "gap breadth complete",
            "references": ["director-review/gaps/gap-scan.md"],
            "open_questions": [],
        },
        TS,
    )
    write_artifact(
        rd,
        "DISCOVER",
        "gap-classification.artifact.json",
        "gap_classification",
        "gap-classifier",
        {
            "gaps": [
                {
                    "gap_id": "WK-1",
                    "gap_type": "methodological_gap",
                    "reason_code": "WEAK_LOCUS",
                    "evidence_ref": ["[[p1]]"],
                }
            ]
        },
        TS,
    )
    write_artifact(
        rd,
        "DISCOVER",
        "novelty-score.artifact.json",
        "novelty_score",
        "novelty-scorer",
        {
            "scores": [
                {
                    "gap_id": "WK-1",
                    "novelty": 0.25,
                    "feasibility_signal": 0.7,
                    "derived_from": ["weakness_opportunity"],
                    "evidence_ref": ["[[p1]]"],
                }
            ]
        },
        TS,
    )

    out = write_packet(rd, generated_at=TS)
    text = out.read_text(encoding="utf-8")
    assert "Director-facing gap scan" in text
    assert "director-review/gaps/gap-scan.md" in text
    assert "Gap scan classified 1 research gap(s)." in text
    assert "Novelty scoring retained 1 gap(s); scores are advisory only." in text
    assert "start new_direction only if the director wants to bet" in text


def test_director_packet_surfaces_deep_research_markdown_brief(tmp_path):
    runs = tmp_path / "runs"
    plan = spine.begin(str(runs), "pkt4", "research a field deeply", "deep_research", TS)
    rd = Path(plan["run_dir"])
    brief = rd / "director-review" / "research" / "research-brief.md"
    brief.parent.mkdir(parents=True)
    brief.write_text("# Research Brief\n\nHuman-readable research synthesis.", encoding="utf-8")
    write_artifact(
        rd,
        "REPORT",
        "report-note.artifact.json",
        "report_note",
        "test",
        {"summary": "deep research complete", "references": [], "open_questions": []},
        TS,
    )
    write_artifact(
        rd,
        "DISCOVER",
        "research-brief.artifact.json",
        "research_brief",
        "landscape-mapper",
        {
            "topic": "field",
            "perspectives": [
                {"perspective_id": "P1", "angle": "a", "questions": ["q"]},
                {"perspective_id": "P2", "angle": "b", "questions": ["q"]},
                {"perspective_id": "P3", "angle": "c", "questions": ["q"]},
            ],
            "findings": [
                {"perspective_id": "P1", "summary": "s", "source_refs": ["x"]},
                {"perspective_id": "P2", "summary": "s", "source_refs": ["x"]},
                {"perspective_id": "P3", "summary": "s", "source_refs": ["x"]},
            ],
            "bottom_line": "promising but needs robustness evidence",
            "consensus": ["one consensus"],
            "live_disagreements": [],
            "evidence_gaps": ["one gap"],
            "actionable_next_questions": ["run next experiment"],
            "iterations_used": 1,
            "saturation_reached": True,
            "evidence_ref": ["x"],
        },
        TS,
    )
    write_artifact(
        rd,
        "DISCOVER",
        "research-markdown-brief.artifact.json",
        "research_markdown_brief",
        "landscape-mapper",
        {
            "topic": "field",
            "markdown": "x" * 700,
            "evidence_refs": ["x"],
            "perspective_ids": ["P1", "P2", "P3"],
            "quality_caveats": [],
        },
        TS,
    )

    out = write_packet(rd, generated_at=TS)
    text = out.read_text(encoding="utf-8")
    assert "Research bottom line: promising but needs robustness evidence" in text
    assert "Director-facing research brief" in text
    assert "director-review/research/research-brief.md" in text


def test_director_packet_surfaces_idea_bet_markdown_menu(tmp_path):
    runs = tmp_path / "runs"
    plan = spine.begin(str(runs), "pkt5", "find a direction", "new_direction", TS)
    rd = Path(plan["run_dir"])
    write_artifact(
        rd,
        "IDEATE",
        "idea-backlog.artifact.json",
        "idea_backlog",
        "test",
        {
            "ranked_ideas": [
                {
                    "idea_id": "IDEA-1",
                    "rank": 1,
                    "summary": "Testable residual-intent parser experiment.",
                    "feasibility": {"score": 0.8, "compute": "low", "data": "available", "time": "short"},
                    "evidence_ref": ["IH1", "GAP-1"],
                }
            ]
        },
        TS,
    )
    write_artifact(
        rd,
        "REPORT",
        "report-note.artifact.json",
        "report_note",
        "test",
        {"summary": "new direction complete", "references": [], "open_questions": []},
        TS,
    )

    out = write_packet(rd, generated_at=TS)
    text = out.read_text(encoding="utf-8")
    menu = rd / "director-review" / "ideas" / "idea-bet-menu.md"
    assert menu.is_file()
    assert "Director-facing idea bet menu" in text
    assert "director-review/ideas/idea-bet-menu.md" in text
    menu_text = menu.read_text(encoding="utf-8")
    assert "IDEA-1" in menu_text
    assert "PIVOT" in menu_text


def test_director_packet_backfills_and_links_venue_readiness_markdown(tmp_path):
    runs = tmp_path / "runs"
    plan = spine.begin(
        str(runs),
        "pkt6",
        "assess venue readiness for NeurIPS",
        "venue_readiness",
        TS,
        north_star={"statement": "judge NeurIPS readiness", "in_scope": ["NeurIPS"], "out_of_scope": []},
    )
    rd = Path(plan["run_dir"])
    _stage_bundles(rd, _profile(), _reviews_with_fired_trigger())
    spine.open_stage(rd, "VERIFY", TS)
    paths, rep = vr.run_dets(rd, "VERIFY", TS)
    assert rep["verdict"] == "NOT-YET"
    assert rep["director_venue_readiness"].replace("\\", "/").endswith(
        "director-review/venue/venue-readiness.md"
    )
    assert venue_readiness_path(rd).is_file()

    venue_readiness_path(rd).unlink()
    assert not venue_readiness_path(rd).exists()

    out = write_packet(rd, generated_at=TS)
    assert venue_readiness_path(rd).is_file()
    text = out.read_text(encoding="utf-8")
    assert "Director-facing venue readiness packet" in text
    assert "director-review/venue/venue-readiness.md" in text
    assert "Venue readiness summary: verdict `NOT-YET`, venue `NeurIPS-2025`, unresolved triggers 1." in text
    assert "Unresolved trigger ids: `RT-D4-BASELINE`" in text
    assert not any("director-review/venue/venue-readiness.md" in p.replace("\\", "/") for p in paths)


def test_manuscript_authoring_packet_links_the_primary_overview_not_an_internal_review(tmp_path):
    runs = tmp_path / "runs"
    plan = spine.begin(str(runs), "paper-001", "author a paper", "manuscript_authoring", TS)
    rd = Path(plan["run_dir"])
    _write_manuscript_report(rd, "00-OVERVIEW.md", "# Manuscript overview\n\nReadable source product.")
    _write_manuscript_report(rd, "reviewer-report.md", "# Internal audit\n\nNot independent review.")

    text = write_packet(rd, generated_at=TS).read_text(encoding="utf-8")

    assert "[00-OVERVIEW.md](./manuscript/00-OVERVIEW.md)" in text
    assert "No independently operated `manuscript_review` product is linked" in text
    assert "./manuscript/reviewer-report.md" not in text


def test_manuscript_review_packet_requires_distinct_verified_verdict_before_linking_report(tmp_path):
    runs = tmp_path / "runs"
    plan = spine.begin(str(runs), "review-001", "review a paper", "manuscript_review", TS)
    rd = Path(plan["run_dir"])
    _write_manuscript_report(rd, "reviewer-report.md", "# Independent review\n\nReadable findings.")
    _write_review_verdict(rd, review_run_id="review-001")

    text = write_packet(rd, generated_at=TS).read_text(encoding="utf-8")

    assert "[reviewer-report.md](./manuscript/reviewer-report.md)" in text
    assert "review run `review-001`" in text
    assert "runs/paper-001/manuscript/main.tex" in text
    assert "`" + ("b" * 64) + "`" in text


def test_manuscript_review_packet_fails_closed_on_cross_run_hash_and_unsafe_input(tmp_path):
    runs = tmp_path / "runs"
    plan = spine.begin(str(runs), "review-002", "review a paper", "manuscript_review", TS)
    rd = Path(plan["run_dir"])
    _write_manuscript_report(rd, "reviewer-report.md", "# Independent review\n\nReadable findings.")
    _write_review_verdict(
        rd,
        review_run_id="paper-001",
        manuscript_ref="../outside/main.tex",
        manuscript_sha256="not-a-hash",
    )

    text = write_packet(rd, generated_at=TS).read_text(encoding="utf-8")

    assert "./manuscript/reviewer-report.md" not in text
    assert "no verified independent manuscript-review verdict" in text.lower()
    assert "../outside/main.tex" not in text


def test_manuscript_packet_rejects_secret_bearing_review_reference_without_hiding_packet(tmp_path):
    runs = tmp_path / "runs"
    plan = spine.begin(str(runs), "review-secret", "review a paper", "manuscript_review", TS)
    rd = Path(plan["run_dir"])
    _write_manuscript_report(rd, "reviewer-report.md", "# Independent review\n\nReadable findings.")
    _write_review_verdict(
        rd,
        review_run_id="review-secret",
        manuscript_ref="runs/paper-001/main.tex?api_key=super-secret",
    )

    text = write_packet(rd, generated_at=TS).read_text(encoding="utf-8")

    assert "# Director Review Packet" in text
    assert "./manuscript/reviewer-report.md" not in text
    assert "super-secret" not in text
