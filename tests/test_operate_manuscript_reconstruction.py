from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from research_agent_teams.operate.artifacts import TargetedGateBlock
from research_agent_teams.operate.modes import manuscript_reconstruction as reconstruction


def _write_docx(path: Path) -> None:
    document = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>
<w:p><w:r><w:t>Fix the title.</w:t></w:r></w:p></w:body></w:document>"""
    comments = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:comments xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
<w:comment w:id="0" w:author="Reviewer"><w:p><w:r><w:t>Check the denominator.</w:t></w:r></w:p></w:comment>
</w:comments>"""
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("word/document.xml", document)
        archive.writestr("word/comments.xml", comments)


def test_docx_body_and_word_comments_enter_the_same_review_surface(tmp_path):
    path = tmp_path / "review.docx"
    _write_docx(path)

    text = reconstruction._read_review_path(path)
    segments = reconstruction._review_segments(text)

    assert "Fix the title." in text
    assert "[WORD COMMENT — Reviewer] Check the denominator." in text
    assert [row["segment_id"] for row in segments] == ["S0001", "S0002"]


def _run_with_decomposition(tmp_path: Path, monkeypatch, decomposition: dict):
    input_path = tmp_path / reconstruction.INPUT_REL
    input_path.parent.mkdir(parents=True, exist_ok=True)
    input_path.write_text(json.dumps({"review_text": "Fix the title.\nLooks good."}), encoding="utf-8")
    monkeypatch.setattr(
        reconstruction._panel_recipe,
        "load_seat_bundles",
        lambda *_args, **_kwargs: {"decomposition": decomposition},
    )
    monkeypatch.setattr(
        reconstruction._panel_recipe,
        "common_gates",
        lambda *_args, **_kwargs: ([], {}),
    )
    return reconstruction._discover_dets(tmp_path, "2026-08-23T00:00:00Z")


def test_reconstruction_hard_gates_segment_coverage_and_current_draft_crosswalk(tmp_path, monkeypatch):
    decomposition = {
        "frozen_inputs": {},
        "points": [{
            "id": "R1",
            "quote": "Fix the title.",
            "claim_check": "unverifiable-here",
            "lane": "prose_repair",
            "owner": "title",
            "source_segment_ids": ["S0001"],
            "current_status": "OPEN",
            "current_loci": ["source/main.tex:1"],
            "required_change": "Use the reviewed title.",
            "acceptance_criterion": "Title and PDF metadata match.",
            "target_refs": ["source/main.tex"],
        }],
        "non_actionable_segment_ids": ["S0002"],
        "lane_totals": {"prose_repair": 1},
    }

    _paths, report = _run_with_decomposition(tmp_path, monkeypatch, decomposition)
    assert report["coverage"] == 1.0

    decomposition["non_actionable_segment_ids"] = ["S0001", "S0002"]
    with pytest.raises(TargetedGateBlock, match="decomposition"):
        _run_with_decomposition(tmp_path / "bad", monkeypatch, decomposition)
