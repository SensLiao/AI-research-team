"""Conformance tests for the agent spec upgrade (spec_version 1.1.0 baseline).

Checks every agents/*.md file (excluding agents/references/ subdirectory) for:
  - Parseable YAML frontmatter (model_policy._frontmatter + yaml.safe_load dual-rail)
  - model in {opus, sonnet, none}
  - spec_version present and matches semantic-version pattern
  - rq_exempt:true OR body contains "North-star discipline" (100% coverage)
  - synthesis-writer declared model == opus  (M7)
  - inline-twin name set files contain "Inline operate twin" (M5)

All assertions use plain pytest (no fixtures) so failures show clearly which file failed.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

import yaml

# Path to the agents directory (resolved relative to this test file)
AGENTS_DIR = Path(__file__).resolve().parent.parent / "agents"

SPEC_VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")
VALID_MODELS = {"opus", "sonnet", "none"}

# Agents whose spec duties are mirrored in operate/modes/*.py — must have "Inline operate twin"
INLINE_TWIN_AGENTS = {
    "lit-scout",
    "evidence-verifier",
    "citation-integrity-auditor",
    "hypothesis-generator",
    "feasibility-reranker",
    "gap-classifier",
    "novelty-scorer",
    "future-work-miner",
    "idea-tournament-ranker",
    "idea-evolver",
    "venue-reviewer-persona",
    "area-chair-synthesizer",
    "venue-selector",
    "venue-review-configurator",
    "scientific-critic",
    "experiment-planner",
    "protocol-compiler",
    "result-analyzer",
    "result-sanity-checker",
    "adversarial-reviewer",
    "trainset-builder",
    "testset-builder",
    "preflight-checker",
    "experiment-journaler",
    "train-test-parity-verifier",
    "variable-control-auditor",
    "train-test-alignment-auditor",
    "metric-implementation-auditor",
}


def _collect_agents() -> list[Path]:
    """Return all agents/*.md files, excluding the references/ subdirectory."""
    return sorted(
        p for p in AGENTS_DIR.glob("*.md")
        if p.is_file()
    )


def _frontmatter_model_policy(md_text: str) -> dict:
    """Parse frontmatter using model_policy's own _frontmatter function (authoritative path)."""
    from research_agent_teams.orchestrator.model_policy import _frontmatter  # type: ignore
    return _frontmatter(md_text)


def _frontmatter_yaml(md_text: str) -> dict:
    """Parse frontmatter via raw yaml.safe_load (dual-rail check)."""
    lines = md_text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    block: list[str] = []
    for line in lines[1:]:
        if line.strip() == "---":
            break
        block.append(line)
    else:
        return {}
    return yaml.safe_load("\n".join(block)) or {}


def _body(md_text: str) -> str:
    """Return the markdown body (everything after the closing ---)."""
    lines = md_text.splitlines()
    if not lines or lines[0].strip() != "---":
        return md_text
    end = None
    for i, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            end = i
            break
    if end is None:
        return md_text
    return "\n".join(lines[end + 1:])


# ──────────────────────────────────────────────────────────────────────────────
# Parametrized per-file tests
# ──────────────────────────────────────────────────────────────────────────────

AGENT_FILES = _collect_agents()
AGENT_IDS = [p.stem for p in AGENT_FILES]


def _read(p: Path) -> tuple[dict, dict, str]:
    """Return (fm_mp, fm_yaml, body) for a given agent path."""
    text = p.read_text(encoding="utf-8")
    return _frontmatter_model_policy(text), _frontmatter_yaml(text), _body(text)


class TestFrontmatterParseable:
    """Frontmatter must parse without error on both rails."""

    def test_all_agents_parseable(self):
        errors = []
        for p in AGENT_FILES:
            try:
                fm_mp, fm_yaml, _ = _read(p)
            except Exception as exc:
                errors.append(f"{p.name}: {exc}")
        assert not errors, "Frontmatter parse errors:\n" + "\n".join(errors)


class TestModelField:
    """model must be in {opus, sonnet, none} for every agent that declares one."""

    def test_all_models_valid(self):
        invalid = []
        for p in AGENT_FILES:
            fm_mp, fm_yaml, _ = _read(p)
            model_val: Optional[str] = fm_yaml.get("model")
            if model_val is None:
                continue  # no model key = not dispatchable, skip
            if str(model_val) not in VALID_MODELS:
                invalid.append(f"{p.name}: model={model_val!r}")
        assert not invalid, "Invalid model values:\n" + "\n".join(invalid)


class TestSpecVersion:
    """spec_version must be present and match semantic version pattern."""

    def test_all_agents_have_spec_version(self):
        missing = []
        for p in AGENT_FILES:
            _, fm_yaml, _ = _read(p)
            sv = fm_yaml.get("spec_version")
            if sv is None:
                missing.append(p.name)
            elif not SPEC_VERSION_RE.match(str(sv)):
                missing.append(f"{p.name} (bad format: {sv!r})")
        assert not missing, "Missing/invalid spec_version:\n" + "\n".join(missing)


class TestNorthStarCoverage:
    """Every agent must have EITHER rq_exempt:true in frontmatter OR 'North-star discipline' in body."""

    def test_north_star_100_percent(self):
        uncovered = []
        for p in AGENT_FILES:
            _, fm_yaml, body = _read(p)
            is_rq_exempt = fm_yaml.get("rq_exempt") is True
            has_north_star = "North-star discipline" in body
            if not is_rq_exempt and not has_north_star:
                uncovered.append(p.name)
        assert not uncovered, (
            "Agents missing north-star discipline (no rq_exempt:true and no north-star block):\n"
            + "\n".join(uncovered)
        )


class TestSynthesisWriterModelOpus:
    """synthesis-writer must declare model: opus (M7 upgrade)."""

    def test_synthesis_writer_is_opus(self):
        sw = AGENTS_DIR / "synthesis-writer.md"
        assert sw.exists(), "synthesis-writer.md not found"
        _, fm_yaml, _ = _read(sw)
        model = fm_yaml.get("model")
        assert model == "opus", (
            f"synthesis-writer.md declares model={model!r}, expected 'opus' (M7 requirement)"
        )


class TestInlineTwinAnnotations:
    """Agents in the inline-twin set must contain the 'Inline operate twin' annotation."""

    def test_inline_twin_agents_annotated(self):
        missing = []
        for p in AGENT_FILES:
            if p.stem not in INLINE_TWIN_AGENTS:
                continue
            _, _, body = _read(p)
            if "Inline operate twin" not in body:
                missing.append(p.name)
        assert not missing, (
            "Inline-twin agents missing 'Inline operate twin' annotation:\n"
            + "\n".join(missing)
        )
