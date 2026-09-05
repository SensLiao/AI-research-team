"""Standalone generation-hygiene + adjudicative-language linter for LaTeX trees.

Closes failure-catalog items D6, D2 and the D3-adjacent hand-edit tripwire
(2026-08-20 team upgrade); the adjudicative scan implements Auditor C's Q3
missing-check #3 (03-verification-economics.md).

  D6 — LaTeX-from-heredoc escaping class. Three same-day incidents came from
       escape-significant text passing through an interpreting layer it was not
       written for: a "\\a" in a non-raw Python literal became U+0007 BELL in
       the .tex and stopped pdflatex; backslashes halved once per shell layer;
       XML-escaped authority metadata ("&amp;") survived into sources where the
       bare "&" is an alignment tab. The machine's build preflight
       (tools/latex_build.py) validates encoding, command policy, assets and
       labels but rejects neither C0 control characters (U+0007 is valid UTF-8)
       nor residual XML entities — this linter names both, pre-build, with
       file:line.

  D2 — adjudicative prose. Verdict vocabulary ("settled", "most accurate",
       "the apparatus largely exists", ...) shipped unlinted until an external
       review named it. The scan here reports every hit with the corpus-scoped
       replacement pattern the run's real repairs used (patch_overclaims.py).
       These are REPORT-level findings, never hard fails: a legitimate quote may
       contain a banned phrase — a human or a deterministic gate decides.

  D3-adjacent — files stamped ``%% AUTO-GENERATED`` are generator-owned; when a
       ``generators`` mapping is supplied, a stamped file older than its
       generator is reported (the generator changed and nobody re-ran it).
       A full regeneration check needs to execute the generator — out of scope
       for a linter; the mtime comparison is the cheap tripwire.

Deliberately NOT checked — unescaped bare "&" outside alignment contexts:
whether a "&" is an alignment tab or an error depends on the surrounding
environment (tabular/align/array, custom environments, and macros that expand
to alignment material), which cannot be identified without full macro
expansion. A lexical linter would either false-positive on every table row or
need a TeX engine; pdflatex itself is the reliable detector for that class.
The residual-entity check above still catches the observed generator bug
(the "&amp;" that PRODUCES a bare "&" when later unescaped or rendered).

Scan mechanics and their limits (documented, not hidden): scanning is
line-based, so a banned phrase wrapped across a source line break is not
matched; entity and phrase scans skip verbatim/lstlisting environments,
``\\verb`` spans and TeX comments, while the control-character scan covers
every byte of the file including comments — a control character anywhere is
evidence of the D6 generation bug even where TeX would ignore it.

This module is standalone: wiring it into latex_build._preflight is a separate,
separately-logged decision. Domain-general; stdlib only; writes nothing.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

AUTO_GENERATED_STAMP = "%% AUTO-GENERATED"

SEVERITY_ERROR = "error"      # hard fail: the build or the bibliography is broken
SEVERITY_WARNING = "warning"  # provenance tripwire: regeneration likely needed
SEVERITY_REPORT = "report"    # adjudicative language: a human / det gate decides

#: Verdict vocabulary actually repaired in the reference run (patch_overclaims.py),
#: mapped to the corpus-scoped replacement pattern those repairs used.
DEFAULT_BAN_PHRASES: Tuple[str, ...] = (
    "settled",
    "what displaced it",
    "the direction of the bias is knowable",
    "the apparatus largely exists",
    "most accurate",
    "most consistent",
    "never will",
    "established",
)

_REPLACEMENT_HINTS: Dict[str, str] = {
    "settled": 'scope the verdict to the evidence: "observed in this corpus", never "settled"',
    "what displaced it": "name the specific evidence that changed, scoped to the corpus reviewed",
    "the direction of the bias is knowable": (
        "state the direction observed in the matched comparisons and the conditions it held under"
    ),
    "the apparatus largely exists": (
        "\"components have been demonstrated in <setting>; whether they compose is untested\""
    ),
    "most accurate": (
        "\"strongest <quantity> in this corpus\" plus the unmatched-comparison caveat; "
        "never an unscoped superlative"
    ),
    "most consistent": (
        "\"most stable across the matched comparisons available in this corpus\" — "
        "one matched comparison is not a general ranking"
    ),
    "never will": (
        "\"unavailable at the moment of decision, and often never produced in routine practice\" — "
        "not an absolute about the future"
    ),
    "established": (
        "scope to the assembled corpus (e.g. \"recurs across the studies assembled here\"); "
        "certainty is not conferred by arithmetic over counts"
    ),
}
_GENERIC_HINT = "scope the claim to the corpus and the matched comparisons that support it"

_CONTROL_NAMES: Dict[int, str] = {
    0x00: "NUL", 0x01: "SOH", 0x02: "STX", 0x03: "ETX", 0x04: "EOT", 0x05: "ENQ",
    0x06: "ACK", 0x07: "BELL", 0x08: "BACKSPACE", 0x0B: "VERTICAL TAB",
    0x0C: "FORM FEED", 0x0E: "SO", 0x0F: "SI", 0x10: "DLE", 0x11: "DC1",
    0x12: "DC2", 0x13: "DC3", 0x14: "DC4", 0x15: "NAK", 0x16: "SYN", 0x17: "ETB",
    0x18: "CAN", 0x19: "EM", 0x1A: "SUB", 0x1B: "ESC", 0x1C: "FS", 0x1D: "GS",
    0x1E: "RS", 0x1F: "US",
}
_ALLOWED_CONTROL = {0x09, 0x0A, 0x0D}  # \t \n \r
_ENTITY_RE = re.compile(r"&(?:amp|lt|gt|quot);")
_VERBATIM_BEGIN_RE = re.compile(r"\\begin\{(?:verbatim|lstlisting)\*?\}")
_VERBATIM_END_RE = re.compile(r"\\end\{(?:verbatim|lstlisting)\*?\}")
_VERB_SPAN_RE = re.compile(r"\\verb\*?(.)(.*?)\1")
_CITATION_STACK_RE = re.compile(r"\\cite(?:p|t)?\s*\{([^{}]+)\}")
_FRACTION_RE = re.compile(r"(?<![A-Za-z0-9])([0-9]{1,7})\s*(?:/|\bof\b)\s*([0-9]{1,7})(?![A-Za-z0-9])", re.IGNORECASE)


@dataclass
class LintReport:
    """errors = hard fails; warnings = provenance tripwires; reports = adjudicative
    findings for a human or deterministic gate. ``ok`` is True iff no errors."""

    src_dir: str
    n_files_scanned: int
    errors: List[Dict[str, Any]] = field(default_factory=list)
    warnings: List[Dict[str, Any]] = field(default_factory=list)
    reports: List[Dict[str, Any]] = field(default_factory=list)
    ban_phrases: List[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    def to_payload(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload["ok"] = self.ok
        return payload


def _phrase_regex(phrase: str) -> "re.Pattern[str]":
    words = [re.escape(w) for w in phrase.split()]
    return re.compile(r"\b" + r"\s+".join(words) + r"\b", re.IGNORECASE)


def _strip_non_prose(line: str) -> str:
    """Remove \\verb spans and the TeX comment tail (a '%' not preceded by '\\')."""
    line = _VERB_SPAN_RE.sub("", line)
    return re.split(r"(?<!\\)%", line, 1)[0]


def _is_stamped(text: str) -> bool:
    first_line = text.split("\n", 1)[0]
    return first_line.lstrip().startswith(AUTO_GENERATED_STAMP)


def lint_tex_tree(
    src_dir: Path,
    *,
    ban_phrases: "Sequence[str] | None" = None,
    generators: "Dict[str, Path] | None" = None,
    canonical_terms: "Dict[str, Sequence[str]] | None" = None,
    max_citations_per_command: int = 3,
) -> LintReport:
    """Lint every .tex (and .bib) under ``src_dir``; see the module docstring.

    ``ban_phrases`` overrides the default adjudicative-vocabulary list (matches
    are word-bounded and case-insensitive). ``generators`` maps a generated
    file's path relative to ``src_dir`` (posix form) to its generator script;
    stamped files named there are age-checked against the generator's mtime.
    """
    src_dir = Path(src_dir)
    phrases = list(ban_phrases if ban_phrases is not None else DEFAULT_BAN_PHRASES)
    phrase_res = [(p, _phrase_regex(p)) for p in phrases]
    generator_map = {str(k).replace("\\", "/"): Path(v) for k, v in (generators or {}).items()}
    term_aliases = {
        str(canonical): tuple(str(alias) for alias in aliases)
        for canonical, aliases in (canonical_terms or {}).items()
    }

    report = LintReport(src_dir=str(src_dir), n_files_scanned=0, ban_phrases=phrases)
    files = sorted(
        p for p in src_dir.rglob("*")
        if p.is_file() and p.suffix.casefold() in {".tex", ".bib"}
        and "__pycache__" not in p.parts
    )
    for path in files:
        rel = path.relative_to(src_dir).as_posix()
        report.n_files_scanned += 1
        try:
            text = path.read_bytes().decode("utf-8")
        except UnicodeDecodeError as exc:
            report.errors.append(
                {
                    "check": "encoding",
                    "file": rel,
                    "line": None,
                    "detail": f"not valid UTF-8: {exc}",
                }
            )
            continue

        lines = text.split("\n")

        # (a) C0 control characters — hard fail, every byte of the file counts.
        for lineno, line in enumerate(lines, 1):
            for col, ch in enumerate(line, 1):
                cp = ord(ch)
                if cp < 0x20 and cp not in _ALLOWED_CONTROL:
                    name = _CONTROL_NAMES.get(cp, "C0 CONTROL")
                    report.errors.append(
                        {
                            "check": "control_character",
                            "file": rel,
                            "line": lineno,
                            "col": col,
                            "codepoint": f"U+{cp:04X}",
                            "detail": (
                                f"{rel}:{lineno}: {name} (U+{cp:04X}) — escape-significant text "
                                "passed through an interpreting layer it was not written for (D6); "
                                "regenerate from a file-based generator using raw strings"
                            ),
                        }
                    )

        # (b) residual XML entities — hard fail outside verbatim/comments.
        #     Applies to .bib too (the observed incident WAS a .bib venue field).
        is_bib = path.suffix.casefold() == ".bib"
        in_verbatim = False
        for lineno, line in enumerate(lines, 1):
            if not is_bib:
                if in_verbatim:
                    if _VERBATIM_END_RE.search(line):
                        in_verbatim = False
                    continue
                if _VERBATIM_BEGIN_RE.search(line):
                    in_verbatim = True
                    continue
                scan = _strip_non_prose(line)
            else:
                scan = line  # '%' is not a comment char in .bib; no verbatim either
            for m in _ENTITY_RE.finditer(scan):
                report.errors.append(
                    {
                        "check": "xml_entity",
                        "file": rel,
                        "line": lineno,
                        "entity": m.group(0),
                        "detail": (
                            f"{rel}:{lineno}: residual XML entity '{m.group(0)}' — authority "
                            "metadata must pass through the one unescape-then-LaTeX-escape "
                            "path (tools/bib_audit.clean) before it reaches a source file (D4/D6)"
                        ),
                    }
                )

        stamped = _is_stamped(text)

        # (d) AUTO-GENERATED staleness — provenance tripwire, needs the generator map.
        if stamped and rel in generator_map:
            generator = generator_map[rel]
            if not generator.exists():
                report.warnings.append(
                    {
                        "check": "generator_missing",
                        "file": rel,
                        "line": 1,
                        "detail": f"{rel}: declared generator {generator} does not exist",
                    }
                )
            elif path.stat().st_mtime < generator.stat().st_mtime:
                report.warnings.append(
                    {
                        "check": "auto_generated_stale",
                        "file": rel,
                        "line": 1,
                        "generator": str(generator),
                        "detail": (
                            f"{rel}: stamped {AUTO_GENERATED_STAMP} but older than its generator "
                            f"({generator.name}) — re-run the generator; hand-editing a stamped "
                            "file is forbidden"
                        ),
                    }
                )

        # (e) adjudicative language — REPORT level, prose (non-generated) .tex only.
        if not stamped and not is_bib:
            in_verbatim = False
            for lineno, line in enumerate(lines, 1):
                if in_verbatim:
                    if _VERBATIM_END_RE.search(line):
                        in_verbatim = False
                    continue
                if _VERBATIM_BEGIN_RE.search(line):
                    in_verbatim = True
                    continue
                scan = _strip_non_prose(line)
                for match in _CITATION_STACK_RE.finditer(scan):
                    keys = [key.strip() for key in match.group(1).split(",") if key.strip()]
                    if len(keys) > max_citations_per_command:
                        report.reports.append({
                            "check": "citation_stack",
                            "file": rel,
                            "line": lineno,
                            "count": len(keys),
                            "keys": keys,
                            "detail": (
                                f"{rel}:{lineno}: one citation command contains {len(keys)} entries; "
                                "split heterogeneous claims or justify an explicit exhaustive set"
                            ),
                        })
                for canonical, aliases in term_aliases.items():
                    for alias in aliases:
                        if alias and _phrase_regex(alias).search(scan):
                            report.reports.append({
                                "check": "terminology_alias",
                                "file": rel,
                                "line": lineno,
                                "canonical": canonical,
                                "alias": alias,
                                "detail": f"{rel}:{lineno}: use canonical term '{canonical}', not '{alias}'",
                            })
                for phrase, rx in phrase_res:
                    for m in rx.finditer(scan):
                        report.reports.append(
                            {
                                "check": "adjudicative_language",
                                "file": rel,
                                "line": lineno,
                                "phrase": phrase,
                                "match": m.group(0),
                                "suggestion": _REPLACEMENT_HINTS.get(phrase, _GENERIC_HINT),
                                "detail": (
                                    f"{rel}:{lineno}: adjudicative phrase '{m.group(0)}' — "
                                    "not a hard fail (a legitimate quote may contain it); "
                                    "a human or deterministic gate decides"
                                ),
                            }
                        )

    fractions: Dict[str, set[str]] = {}
    fraction_loci: Dict[Tuple[str, str], List[str]] = {}
    for path in files:
        if path.suffix.casefold() != ".tex":
            continue
        rel = path.relative_to(src_dir).as_posix()
        text_value = path.read_text(encoding="utf-8")
        for lineno, line in enumerate(text_value.splitlines(), 1):
            scan = _strip_non_prose(line)
            for numerator, denominator in _FRACTION_RE.findall(scan):
                fractions.setdefault(numerator, set()).add(denominator)
                fraction_loci.setdefault((numerator, denominator), []).append(f"{rel}:{lineno}")
    for numerator, denominators in sorted(fractions.items()):
        if len(denominators) > 1:
            report.reports.append({
                "check": "denominator_conflict_candidate",
                "numerator": numerator,
                "denominators": sorted(denominators),
                "loci": {
                    denominator: fraction_loci[(numerator, denominator)]
                    for denominator in sorted(denominators)
                },
                "detail": (
                    f"numerator {numerator} appears with multiple denominators "
                    f"{sorted(denominators)}; compare abstract, body, tables, and captions against "
                    "MANUSCRIPT-ONTOLOGY.md before adjudicating"
                ),
            })

    return report
