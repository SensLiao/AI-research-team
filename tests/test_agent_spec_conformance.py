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
AGENTS_DIR = Path(__file__).resolve().parents[2] / "research_agent_teams" / "agents"

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


class TestToolDeclarations:
    """Tool declarations must not advertise capabilities the runtime fence blocks."""

    def test_no_agent_declares_bash_tool(self):
        offenders = []
        for p in AGENT_FILES:
            _, fm_yaml, _ = _read(p)
            tools = fm_yaml.get("tools") or []
            if "Bash" in [str(t) for t in tools]:
                offenders.append(p.name)
        assert not offenders, "Bash is blocked for fenced agents; remove from tools:\n" + "\n".join(offenders)


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


class TestSynthesisWriterParked:
    """The unconsumed prose renderer is preserved but not an active seat."""

    def test_synthesis_writer_is_parked(self):
        sw = AGENTS_DIR / "_parked" / "synthesis-writer.md"
        assert sw.exists(), "parked synthesis-writer.md not found"
        _, fm_yaml, _ = _read(sw)
        assert fm_yaml.get("name") == "synthesis-writer"


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

    def test_inline_twin_named_modules_exist(self):
        """Each `Inline operate twin: ... operate/modes/<file>.py` annotation must name a
        REAL module under operate/modes/. The annotation may list several files in one line,
        written as `operate/modes/a.py / b.py / c.py` (the dir prefix appears once, then bare
        filenames separated by ` / `) — every named .py must exist. This catches a twin pointer
        rotting after a mode module is renamed/removed (the M5 mirror would then point at nothing).
        """
        modes_dir = AGENTS_DIR.parent / "operate" / "modes"
        # Capture the leading "operate/modes/<first>.py" plus the rest of the annotation line,
        # then pull every "<name>.py" token out of the whole matched span.
        line_re = re.compile(r"Inline operate twin:[^\n]*?operate/modes/[^\n]*?\.py")
        pyfile_re = re.compile(r"([A-Za-z0-9_]+\.py)")
        missing = []
        for p in AGENT_FILES:
            _, _, body = _read(p)
            for m in line_re.finditer(body):
                span = m.group(0)
                # Only the file tokens that follow the operate/modes/ marker are mode modules.
                after_marker = span[span.index("operate/modes/"):]
                for fname in pyfile_re.findall(after_marker):
                    if not (modes_dir / fname).is_file():
                        missing.append(f"{p.name}: names operate/modes/{fname} (does not exist)")
        assert not missing, (
            "Inline-twin annotations naming non-existent operate/modes modules:\n"
            + "\n".join(missing)
        )


# ──────────────────────────────────────────────────────────────────────────────
# Shared contract-fragment containment (Wave-0 reconciliation hardening)
# ──────────────────────────────────────────────────────────────────────────────
#
# WHY this test exists (and why it is a CONTAINMENT test, not a prompt-compiler):
# `agents/references/shared-definitions.md` is the *declared authoritative source* for
# cross-agent definitions that are deliberately TRIPLICATED — they live inline in the operate
# mode prompts (for prompt completeness) AND in the parallel hand-maintained agent .md specs.
# The inline prompts and spec bodies intentionally encode DIFFERENT labour splits, so neither can
# be compiled from the other (the whitepaper's heavy "prompt compiler" was deliberately rejected).
# The minimal, correct fix is to pin the small set of CONTRACT FRAGMENTS that genuinely MUST agree
# wherever they appear. The cleanest such fragment is the canonical 7-type gap taxonomy: a set of
# short, stable IDENTIFIER tokens (not prose), so matching is robust against wording drift.
#
# Existing `TestInlineTwinAnnotations` only proves an annotation STRING is present; it does NOT
# prove the inline prompt and the spec still carry the same taxonomy. This class closes that gap.

# The authoritative source-of-truth file for cross-agent definitions.
SHARED_DEFS = AGENTS_DIR / "references" / "shared-definitions.md"

# Fallback expected taxonomy (used only to assert the parse below stayed complete — never to mask
# a parse failure). Mirrors shared-definitions.md §2 "gap_type — 7-Taxonomy of Research Gaps".
_EXPECTED_GAP_TYPES = {
    "transfer_gap",
    "assumption_gap",
    "methodological_gap",
    "coverage_gap",
    "evidence_gap",
    "empirical_gap",
    "stated_open_problem",
}


def _canonical_gap_types() -> set[str]:
    """Parse the 7 gap-type NAME tokens out of shared-definitions.md §2 (the authoritative table).

    We read the canonical set from the source-of-truth file rather than hardcoding it, so the test
    stays anchored to the authority. A guard asserts exactly the expected 7 names were recovered —
    if the table is reshaped the guard fails loudly instead of silently checking an empty/partial set.
    """
    text = SHARED_DEFS.read_text(encoding="utf-8")
    # The §2 table renders each type as a backticked token in the `gap_type` column, e.g. `transfer_gap`.
    # Restrict to the §2 section so we don't pick up backticked tokens elsewhere in the file.
    sec = text.split("## 2.", 1)
    body = sec[1] if len(sec) == 2 else text
    body = body.split("\n## 3.", 1)[0]
    found = set(re.findall(r"`([a-z_]+_gap|stated_open_problem)`", body))
    found = {t for t in found if t in _EXPECTED_GAP_TYPES}
    return found


class TestSharedFragmentContainment:
    """Canonical contract fragments from the authoritative shared-definitions.md must be CONTAINED
    wherever a location genuinely MIRRORS that fragment — checked against BOTH an inline operate
    prompt module AND a twin agent spec.

    Fragment chosen: the 7-type gap-taxonomy NAME tokens (short, stable identifiers — robust against
    wording drift). Scoping note (this is the crux, and matches the deliberately-different labour
    splits the audit found):
      - The FULL 7-name taxonomy is enumerated in exactly the places that tabulate the complete
        taxonomy: shared-definitions.md §2 (authority) + new_direction.py DISCOVER worker legend
        (inline) + gap-classifier.md taxonomy table (twin spec). Those three MUST carry all 7.
      - gap_breadth.py is the 5-hunter panel: it deliberately enumerates only 5 of the 7 lenses
        (no evidence_gap / empirical_gap hunter). So its contract is the NARROWER one — its hunter
        type-names must each be a CANONICAL name (no hunter may invent a type) — asserted separately.
      - novelty-scorer.md carries NO type names by design (it consumes gap_type upstream and works
        on `derived_from` SIGNAL names, a different vocabulary), so it is correctly NOT a
        name-containment target. Asserting the full 7 there would be a false-strict choice, not a
        real drift — which is precisely the Step-5 loosening this comment records.
    """

    # Locations that enumerate the COMPLETE 7-type taxonomy (must contain every canonical name).
    GAP_TAXONOMY_INLINE_FULL = AGENTS_DIR.parent / "operate" / "modes" / "new_direction.py"
    GAP_TAXONOMY_SPEC_FULL = AGENTS_DIR / "gap-classifier.md"
    # The 5-hunter inline panel: a legitimately PARTIAL copy — its named types must be canonical.
    GAP_BREADTH_MODULE = AGENTS_DIR.parent / "operate" / "modes" / "gap_breadth.py"

    def test_authoritative_taxonomy_parses_to_seven(self):
        """The authoritative source must still define exactly the 7 canonical gap-type names —
        this guards the parser in _canonical_gap_types() against silently checking a partial set."""
        assert SHARED_DEFS.is_file(), f"authoritative source missing: {SHARED_DEFS}"
        got = _canonical_gap_types()
        assert got == _EXPECTED_GAP_TYPES, (
            "shared-definitions.md §2 no longer yields the expected 7 gap-type names.\n"
            f"  parsed:   {sorted(got)}\n  expected: {sorted(_EXPECTED_GAP_TYPES)}\n"
            "If the taxonomy genuinely changed, update _EXPECTED_GAP_TYPES (and every inline/spec copy)."
        )

    def _canonical(self) -> set[str]:
        """Canonical 7 names from the authority, with an explicit-set fallback so a parser regression
        cannot make the containment checks pass vacuously (the guard test above reports the regression)."""
        canon = _canonical_gap_types()
        return canon if canon == _EXPECTED_GAP_TYPES else _EXPECTED_GAP_TYPES

    def test_full_taxonomy_contained_in_inline_and_spec(self):
        """Every one of the 7 canonical gap-type names must appear in BOTH the inline prompt that
        enumerates the full taxonomy (new_direction.py DISCOVER legend) AND the twin spec that
        tabulates it (gap-classifier.md). On failure, name which location lacks which token."""
        canonical = self._canonical()
        targets: list[tuple[str, Path, str]] = [
            ("inline-prompt", self.GAP_TAXONOMY_INLINE_FULL,
             self.GAP_TAXONOMY_INLINE_FULL.read_text(encoding="utf-8")),
            # Full spec text (frontmatter + body): the taxonomy table is in the body, and reading the
            # whole file is the strict superset that avoids body-parse edge cases.
            ("twin-spec", self.GAP_TAXONOMY_SPEC_FULL,
             self.GAP_TAXONOMY_SPEC_FULL.read_text(encoding="utf-8")),
        ]
        missing: list[str] = []
        for kind, path, text in targets:
            for token in sorted(canonical):
                if token not in text:
                    missing.append(f"{kind} {path.name}: missing canonical gap-type token {token!r}")
        assert not missing, (
            "Shared gap-taxonomy fragment drift — a canonical type name is absent from a location "
            "that enumerates the FULL taxonomy and must mirror it "
            "(authoritative source: agents/references/shared-definitions.md §2):\n"
            + "\n".join(missing)
        )

    def test_gap_breadth_hunter_types_are_canonical(self):
        """gap_breadth.py's 5-hunter panel is a legitimately PARTIAL copy of the taxonomy. Every
        gap-type name it carries must be one of the 7 canonical names, and the set it carries must be
        a NON-EMPTY PROPER SUBSET of the 7 (the 5-hunter panel covers 5 of the 7 lenses). This is the
        narrower contract the 5-hunter labour split genuinely owns vs. the full-7 enumeration above.

        We test by exact containment of the KNOWN canonical tokens (not by scanning for arbitrary
        `*_gap`-looking identifiers — that false-matches tool/function names like `classify_gap`).
        """
        canonical = self._canonical()
        text = self.GAP_BREADTH_MODULE.read_text(encoding="utf-8")
        present = {t for t in canonical if t in text}
        assert present and present < canonical, (
            "gap_breadth.py is expected to carry a NON-EMPTY PROPER SUBSET of the 7 canonical "
            f"gap-type names (the 5-hunter panel); got {sorted(present)} "
            f"vs canonical {sorted(canonical)}. If the panel changed shape, update this expectation."
        )
