from __future__ import annotations

from research_agent_teams.tools.research_output_quality import (
    MODE_OUTPUT_CONTRACTS,
    audit_completed_runs,
    audit_markdown_text,
    audit_run_output,
)


def _good_markdown(mode: str) -> str:
    contract = MODE_OUTPUT_CONTRACTS[mode]
    lines = ["# Director Research Product", ""]
    for index, (concept, terms) in enumerate(contract.concepts.items(), start=1):
        lines.extend([f"## {index}. {concept}", "", terms[0], ""])
    lines.append("Evidence-backed detail. " * 180)
    return "\n".join(lines)


def test_all_operated_modes_have_business_output_contracts():
    """Every pressable mode declares what BUSINESS content its director Markdown must carry.

    Derived from REGISTRY rather than re-typed: this list was a second hand-maintained copy of the
    operated set, and wave 2 (2026-08-04) made it drift the moment nine modes were wired. The
    invariant that matters is the correspondence, not the names.
    """
    from research_agent_teams.operate.modes import REGISTRY

    assert set(MODE_OUTPUT_CONTRACTS) == set(REGISTRY)
    for mode, contract in MODE_OUTPUT_CONTRACTS.items():
        assert contract.primary_globs, mode
        assert contract.min_chars >= 600, mode
        assert len(contract.concepts) >= 6, mode

def test_good_director_markdown_passes_every_mode_contract():
    for mode in MODE_OUTPUT_CONTRACTS:
        result = audit_markdown_text(mode, _good_markdown(mode))
        assert result["status"] == "pass", (mode, result)
        assert result["score"] == 1.0


def test_idea_without_falsification_or_kill_criteria_is_advisory():
    text = "\n".join([
        "# Idea",
        "## Research question",
        "## Mechanism",
        "## Prior art and novelty",
        "## Feasibility and resources",
        "## Next actions and execution order",
        "Baseline and controls are defined. " * 120,
    ])
    result = audit_markdown_text("new_direction", text)
    assert result["status"] == "advisory"
    assert result["delivery_status"] == "USABLE_WITH_CAVEATS"
    assert "missing_business_concept:falsification" in result["failures"]
    assert "missing_business_concept:kill_criteria" in result["failures"]


def test_evidence_without_counterevidence_or_belief_update_fails():
    text = "\n".join([
        "# Evidence",
        "## Bottom line",
        "## Source quality",
        "## Claim evidence map and locus",
        "## Decision implication",
        "## Uncertainty and limitation",
        "## Next evidence to collect",
        "Source-backed detail. " * 120,
    ])
    result = audit_markdown_text("evidence_deep", text)
    assert "missing_business_concept:counterevidence" in result["failures"]
    assert "missing_business_concept:belief_update" in result["failures"]


def test_run_audit_fails_when_primary_markdown_is_missing(tmp_path):
    result = audit_run_output(tmp_path, "gap_breadth")
    assert result["status"] == "fail"
    assert result["failures"] == ["primary_director_markdown_missing"]


def test_completed_run_audit_reads_human_product(tmp_path):
    run = tmp_path / "runs" / "proj" / "r1"
    run.mkdir(parents=True)
    (run / "manifest.yaml").write_text(
        "schema_version: 1.0.0\nrun_id: r1\nproject: proj\nstatus: done\nmode: gap_breadth\n",
        encoding="utf-8",
    )
    out = run / "director-review" / "gaps" / "gap-scan.md"
    out.parent.mkdir(parents=True)
    out.write_text(_good_markdown("gap_breadth"), encoding="utf-8")
    report = audit_completed_runs(tmp_path / "runs")
    assert report["completed_run_count"] == 1
    assert report["pass"] == 1
    assert report["runs"][0]["paths"] == ["director-review/gaps/gap-scan.md"]


def test_completed_run_with_thin_markdown_is_advisory_not_failure(tmp_path):
    run = tmp_path / "runs" / "proj" / "r2"
    run.mkdir(parents=True)
    (run / "manifest.yaml").write_text(
        "schema_version: 1.0.0\nrun_id: r2\nproject: proj\nstatus: done\nmode: gap_breadth\n",
        encoding="utf-8",
    )
    out = run / "director-review" / "gaps" / "gap-scan.md"
    out.parent.mkdir(parents=True)
    out.write_text("# Gap scan\n\nUseful but incomplete working note.", encoding="utf-8")
    report = audit_completed_runs(tmp_path / "runs")
    assert report["advisory"] == 1
    assert report["fail"] == 0
    assert report["runs"][0]["delivery_status"] == "USABLE_WITH_CAVEATS"
