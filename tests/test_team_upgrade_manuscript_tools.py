"""Real tests for the 2026-08-20 team-upgrade manuscript/verification tools.

Covers the four modules ported from the proven run-local implementations:
  tools/bib_audit.py         (catalog D4 — bibliography metadata defects)
  tools/dual_read.py         (catalog C1/C2 — extraction reliability + vocabulary pinning)
  tools/latex_gen_lint.py    (catalog D6/D2 — generation hygiene + adjudicative language)
  tools/deposit_manifest.py  (catalog E1/TU-2 — release-moment deposit receipt)

No network anywhere: bib_audit receives a fake transport with canned authority
records. All fixtures are domain-neutral by construction.
"""
from __future__ import annotations

import json
import os
import textwrap
import time
import urllib.parse

import pytest

from research_agent_teams.tools import bib_audit
from research_agent_teams.tools.bib_audit import (
    DEFECT_LEAKED_WORKNOTE,
    DEFECT_MISSING_DOI,
    DEFECT_PREPRINT_SUPERSEDED,
    DEFECT_SUFFIX_RENDER_HAZARD,
    DEFECT_UNRESOLVED,
    DEFECT_VENUE_MISMATCH,
    apply_fixes,
    audit,
    clean,
    fix_author,
    parse_bib,
)
from research_agent_teams.tools.deposit_manifest import build_manifest, verify_receipt
from research_agent_teams.tools.dual_read import compare, draw_sample
from research_agent_teams.tools.latex_gen_lint import lint_tex_tree


# ===================================================================== bib_audit
FIXTURE_BIB = textwrap.dedent(
    """\
    % neutral fixture bibliography (team-upgrade tests)

    @misc{alpha2015refine,
      title        = {Neutral Widget Networks for Signal Refinement},
      author       = {Alice Author and Bob Builder},
      year         = {2015},
      eprint       = {1505.00001},
      archiveprefix = {arXiv},
    }

    @article{beta2019survey,
      title   = {A Survey of Modular Widget Pipelines},
      author  = {Given M. Surname III},
      journal = {Journal of Widget Studies},
      year    = {2019},
    }

    @article{gamma2020tools,
      title   = {Tooling for Reproducible Widget Analysis},
      author  = {Carol Coder},
      journal = {Journal of Alpha Studies},
      year    = {2020},
      doi     = {10.1000/gamma},
      note    = {Not stated in the retrieved artefact},
    }

    @misc{delta2016stream,
      title        = {Streaming Widget Calibration at Scale},
      author       = {Dan Dev},
      year         = {2016},
      eprint       = {1606.00002},
      archiveprefix = {arXiv},
    }

    @article{epsilon2018graphs,
      title   = {Widget Provenance Graphs},
      author  = {Eve Eng},
      journal = {Workshop on Widget Provenance},
      year    = {2018},
    }
    """
)


def _search_body(items):
    return json.dumps({"message": {"items": items}}).encode("utf-8")


def _work_body(msg):
    return json.dumps({"message": msg}).encode("utf-8")


def fake_transport(url, headers):
    """Canned Crossref: DOI lookups by path, title searches by query substring."""
    parsed = urllib.parse.urlparse(url)
    if parsed.path.startswith("/works/"):
        doi = urllib.parse.unquote(parsed.path[len("/works/"):])
        if doi == "10.1000/gamma":
            return _work_body(
                {
                    "DOI": "10.1000/gamma",
                    "title": ["Tooling for Reproducible Widget Analysis"],
                    "container-title": ["Quarterly Review of Gadget Methods"],
                    "issued": {"date-parts": [[2020]]},
                    "type": "journal-article",
                }
            )
        if doi == "10.5000/alpha-canonical":
            return _work_body(
                {
                    "DOI": "10.5000/alpha-canonical",
                    "title": ["Neutral Widget Networks for Signal Refinement"],
                    "container-title": ["Symposium on Neutral Widgets"],
                    "issued": {"date-parts": [[2015]]},
                    "type": "proceedings-article",
                    "page": "234-241",
                }
            )
        raise bib_audit.BibAuditLookupError(f"HTTP 404 for {url}", status=404)

    query = urllib.parse.parse_qs(parsed.query).get("query.bibliographic", [""])[0].lower()
    if "neutral widget networks" in query:
        # The reprint trap: containment-only match, two years later. Must be refused.
        return _search_body(
            [
                {
                    "DOI": "10.9000/reprint",
                    "title": ["Invited Talk: Neutral Widget Networks for Signal Refinement"],
                    "container-title": ["Reprint Digest"],
                    "issued": {"date-parts": [[2017]]},
                    "type": "proceedings-article",
                }
            ]
        )
    if "survey of modular widget pipelines" in query:
        return _search_body(
            [
                {
                    "DOI": "10.2000/beta",
                    "title": ["A Survey of Modular Widget Pipelines"],
                    "container-title": ["Journal of Widget Studies"],
                    "issued": {"date-parts": [[2019]]},
                    "type": "journal-article",
                }
            ]
        )
    if "streaming widget calibration" in query:
        # Authority metadata arrives XML-escaped — exactly the build-killer input.
        return _search_body(
            [
                {
                    "DOI": "10.3000/delta_1",
                    "title": ["Streaming Widget Calibration at Scale"],
                    "container-title": ["Conference on Widgets &amp; Gadgets"],
                    "issued": {"date-parts": [[2016]]},
                    "type": "proceedings-article",
                    "volume": "12",
                    "page": "34-41",
                }
            ]
        )
    if "widget provenance graphs" in query:
        # Containment match with year agreement within 1 — acceptable.
        return _search_body(
            [
                {
                    "DOI": "10.4000/epsilon",
                    "title": ["Widget Provenance Graphs: Extended Report"],
                    "container-title": ["Workshop on Widget Provenance"],
                    "issued": {"date-parts": [[2019]]},
                    "type": "journal-article",
                }
            ]
        )
    return _search_body([])


@pytest.fixture()
def fixture_bib(tmp_path):
    path = tmp_path / "refs.bib"
    path.write_text(FIXTURE_BIB, encoding="utf-8")
    return path


@pytest.fixture()
def fixture_report(fixture_bib):
    return audit(fixture_bib, mailto="test@example.org", transport=fake_transport)


def _classes(report, key):
    for finding in report.findings:
        if finding["key"] == key:
            return {d["class"] for d in finding["defects"]}
    return set()


def test_clean_unescapes_before_latex_escape():
    # html.unescape FIRST, then escape — or "&amp;" would become "\&amp;".
    assert clean("A &amp; B") == r"A \& B"
    assert clean("A & B") == r"A \& B"
    assert clean("50%_of_#1 ~x^ y") == r"50\%\_of\_\#1 \textasciitilde{}x\textasciicircum{} y"


def test_fix_author_suffix_renders_comma_form():
    assert fix_author("Given M. Surname III") == "Surname, III, Given M."
    # already-safe forms are untouched
    assert fix_author("Surname, III, Given M.") == "Surname, III, Given M."
    assert fix_author("Given Surname") == "Given Surname"


def test_strict_matcher_refuses_containment_with_year_mismatch(fixture_report):
    # The reprint case: containment-only candidate two years off is refused,
    # and the entry is UNRESOLVED — reported, never guessed.
    assert DEFECT_UNRESOLVED in _classes(fixture_report, "alpha2015refine")
    assert "alpha2015refine" not in fixture_report.resolved
    # ...while containment WITH year agreement within +/-1 is accepted.
    assert "epsilon2018graphs" in fixture_report.resolved
    assert DEFECT_MISSING_DOI in _classes(fixture_report, "epsilon2018graphs")


def test_audit_reports_all_defect_classes(fixture_report):
    assert {DEFECT_SUFFIX_RENDER_HAZARD, DEFECT_MISSING_DOI} <= _classes(
        fixture_report, "beta2019survey"
    )
    assert {DEFECT_VENUE_MISMATCH, DEFECT_LEAKED_WORKNOTE} <= _classes(
        fixture_report, "gamma2020tools"
    )
    assert DEFECT_PREPRINT_SUPERSEDED in _classes(fixture_report, "delta2016stream")
    assert fixture_report.n_entries == 5
    assert fixture_report.lookup_errors == []


def test_doi_override_pins_the_authority(fixture_bib):
    report = audit(
        fixture_bib,
        mailto="test@example.org",
        transport=fake_transport,
        overrides={"alpha2015refine": "10.5000/alpha-canonical"},
    )
    assert DEFECT_UNRESOLVED not in _classes(report, "alpha2015refine")
    assert report.resolved["alpha2015refine"]["doi"] == "10.5000/alpha-canonical"
    assert DEFECT_PREPRINT_SUPERSEDED in _classes(report, "alpha2015refine")


def test_lookup_failure_is_named_not_unresolved(tmp_path):
    def dead_transport(url, headers):
        raise bib_audit.BibAuditLookupError("network down (test)")

    path = tmp_path / "one.bib"
    path.write_text(
        "@article{omega2021,\n  title = {Widget Base Rates},\n  author = {Ann A},\n"
        "  journal = {Widget Letters},\n  year = {2021},\n}\n",
        encoding="utf-8",
    )
    report = audit(path, mailto="test@example.org", transport=dead_transport)
    assert [row["key"] for row in report.lookup_errors] == ["omega2021"]
    assert report.findings == []  # absence was never confirmable, so nothing is UNRESOLVED


def test_apply_fixes_applies_only_authority_supported_classes(fixture_bib, fixture_report):
    fix = apply_fixes(fixture_bib, fixture_report)
    entries = {e["key"]: e for e in parse_bib(
        (fixture_bib.parent / "refs.v2.bib").read_text(encoding="utf-8")
    )}
    assert fix.output_path.endswith("refs.v2.bib")

    # suffix hazard repaired to the BibTeX comma form; resolved DOI added
    beta = entries["beta2019survey"]
    assert beta["fields"]["author"] == "Surname, III, Given M."
    assert beta["fields"]["doi"] == "10.2000/beta"

    # preprint promoted to the published record, escaper applied, arXiv id kept
    delta = entries["delta2016stream"]
    assert delta["type"] == "inproceedings"
    assert delta["fields"]["booktitle"] == r"Conference on Widgets \& Gadgets"
    assert delta["fields"]["doi"] == "10.3000/delta_1"
    assert "arXiv:1606.00002" in delta["fields"]["note"]
    assert "eprint" not in delta["fields"]

    # VENUE_MISMATCH is NEVER auto-rewritten: journal untouched, key deferred;
    # the leaked worknote in the same entry IS dropped (authority-independent).
    gamma = entries["gamma2020tools"]
    assert gamma["fields"]["journal"] == "Journal of Alpha Studies"
    assert "note" not in gamma["fields"]
    assert "gamma2020tools" in fix.deferred

    # UNRESOLVED entry is left alone entirely
    alpha = entries["alpha2015refine"]
    assert alpha["type"] == "misc"
    assert alpha["fields"]["eprint"] == "1505.00001"
    assert "alpha2015refine" in fix.deferred

    assert fix.changes_by_class["preprint->published"] == 1
    assert fix.changes_by_class["add-doi"] >= 1
    assert fix.changes_by_class["author-suffix"] == 1
    assert fix.changes_by_class["drop-note"] == 1


# ===================================================================== dual_read
def test_draw_sample_is_deterministic_and_order_independent():
    ids = [f"unit-{i:02d}" for i in range(10)]
    first = draw_sample(ids, seed=20260820, fraction=0.3, minimum=2)
    second = draw_sample(ids, seed=20260820, fraction=0.3, minimum=2)
    shuffled = draw_sample(list(reversed(ids)), seed=20260820, fraction=0.3, minimum=2)
    assert first == second == shuffled
    assert len(first) == 3
    assert first == sorted(first)


def test_draw_sample_minimum_floor_and_bounds():
    ids = [f"u{i}" for i in range(6)]
    assert len(draw_sample(ids, seed=1, fraction=0.0, minimum=4)) == 4
    assert sorted(draw_sample(ids, seed=1, fraction=0.0, minimum=99)) == sorted(ids)
    assert draw_sample(ids, seed=1, fraction=0.0, minimum=0) == []
    with pytest.raises(ValueError):
        draw_sample(ids, seed=1, fraction=1.5, minimum=0)


def test_compare_pins_hyphen_underscore_and_reads_flat_keys():
    primary = {
        "u1": {"decision": "include", "meta": {"status": "not-assessable"}, "signals": ["alpha", "beta"]},
        "u2": {"decision": "exclude", "meta": {"status": "assessed"}, "signals": ["alpha"]},
    }
    secondary = {
        "u1": {"decision": "Include", "meta__status": "not_assessable", "signals": ["beta", "alpha"]},
        "u2": {"decision": "exclude", "meta__status": "assessed", "signals": ["alpha", "gamma"]},
    }
    report = compare(primary, secondary, ["decision", "meta.status", "signals"])
    # one vocabulary with two spellings is agreement, not disagreement (C2)
    assert report.by_field["meta.status"]["agree"] == 2
    assert report.by_field["decision"]["agree"] == 2
    # set-valued field: strict verdict AND Jaccard partial credit both reported
    assert report.by_field["signals"]["agree"] == 1
    assert report.by_field["signals"]["disagree"] == 1
    assert report.by_field["signals"]["mean_jaccard"] == 0.75
    assert report.n_field_comparisons == 6


def test_compare_surfaces_undeclared_alias_and_honors_declared_one():
    primary = {"u1": {"grade": "not assessable"}}
    secondary = {"u1": {"grade": "not_assessable"}}

    undeclared = compare(primary, secondary, ["grade"])
    assert undeclared.by_field["grade"]["disagree"] == 1
    assert len(undeclared.undeclared_alias_findings) == 1
    finding = undeclared.undeclared_alias_findings[0]
    assert finding["field"] == "grade"
    assert "alias" in finding["hint"]

    declared = compare(
        primary, secondary, ["grade"], aliases={"not assessable": "not_assessable"}
    )
    assert declared.by_field["grade"]["agree"] == 1
    assert declared.undeclared_alias_findings == []


def test_compare_report_always_carries_per_field_table_and_caveat():
    primary = {"u1": {"a": "x"}, "u2": {"a": "y"}}
    secondary = {"u1": {"a": "x"}, "u3": {"a": "y"}}
    report = compare(primary, secondary, ["a", "b"])
    # the overall number is structurally inseparable from the per-field table
    assert set(report.by_field) == {"a", "b"}
    assert report.overall_agreement_pct is not None
    assert report.by_field["b"]["not_attempted"] == 1
    assert report.n_units_primary_only == 1
    assert report.n_units_secondary_only == 1
    assert "reproducibility" in report.caveat and "correctness" in report.caveat
    payload = report.to_payload()
    assert "by_field" in payload and "overall_agreement_pct" in payload and "caveat" in payload


# ===================================================================== latex_gen_lint
def test_latex_lint_bell_control_char_is_hard_fail(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "main.tex").write_text(
        "line one\nline two\nbad \x07 cell\n", encoding="utf-8"
    )
    report = lint_tex_tree(src)
    hits = [e for e in report.errors if e["check"] == "control_character"]
    assert len(hits) == 1
    assert hits[0]["file"] == "main.tex"
    assert hits[0]["line"] == 3
    assert hits[0]["codepoint"] == "U+0007"
    assert "main.tex:3" in hits[0]["detail"]
    assert not report.ok


def test_latex_lint_residual_entity_hard_fail_outside_verbatim_only(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "body.tex").write_text(
        "before &amp; after\n"
        "\\begin{verbatim}\n"
        "inside &amp; verbatim is fine\n"
        "\\end{verbatim}\n"
        "% a comment mentioning &amp; is fine\n",
        encoding="utf-8",
    )
    report = lint_tex_tree(src)
    hits = [e for e in report.errors if e["check"] == "xml_entity"]
    assert [(h["file"], h["line"]) for h in hits] == [("body.tex", 1)]
    assert not report.ok


def test_latex_lint_ban_phrase_is_report_level_never_hard_fail(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "prose.tex").write_text(
        "The question is settled, and the apparatus largely exists.\n", encoding="utf-8"
    )
    report = lint_tex_tree(src)
    phrases = {r["phrase"] for r in report.reports}
    assert {"settled", "the apparatus largely exists"} <= phrases
    for row in report.reports:
        assert row["file"] == "prose.tex" and row["line"] == 1
        assert row["suggestion"]
    assert report.errors == []
    assert report.ok  # adjudicative findings alone never fail the lint


def test_latex_lint_skips_generated_files_for_ban_phrases(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "gen.tex").write_text(
        "%% AUTO-GENERATED by tools/mk_gen.py -- do not hand-edit.\n"
        "settled\n",
        encoding="utf-8",
    )
    report = lint_tex_tree(src)
    assert report.reports == []


def test_latex_lint_auto_generated_staleness_against_generator_mtime(tmp_path):
    src = tmp_path / "src"
    (src / "tab").mkdir(parents=True)
    generated = src / "tab" / "numbers.tex"
    generated.write_text(
        "%% AUTO-GENERATED by tools/mk_numbers.py -- do not hand-edit.\n"
        + r"\newcommand{\nFilesTotal}{3}" + "\n",
        encoding="utf-8",
    )
    generator = tmp_path / "mk_numbers.py"
    generator.write_text("print('generator')\n", encoding="utf-8")

    now = time.time()
    os.utime(generated, (now - 500, now - 500))
    os.utime(generator, (now, now))
    stale = lint_tex_tree(src, generators={"tab/numbers.tex": generator})
    checks = [w["check"] for w in stale.warnings]
    assert "auto_generated_stale" in checks
    assert stale.ok  # a staleness tripwire is a warning, not a hard fail

    os.utime(generated, (now + 500, now + 500))
    fresh = lint_tex_tree(src, generators={"tab/numbers.tex": generator})
    assert all(w["check"] != "auto_generated_stale" for w in fresh.warnings)


def test_latex_lint_reads_real_source_for_citation_terms_and_denominators(tmp_path):
    src = tmp_path / "source"
    src.mkdir()
    (src / "main.tex").write_text(
        "The SAMMed2D result was 100/111 \\cite{a,b,c,d}.\n"
        "A later caption incorrectly states 100/112.\n",
        encoding="utf-8",
    )

    report = lint_tex_tree(src, canonical_terms={"SAM-Med2D": ["SAMMed2D"]})
    checks = {row["check"] for row in report.reports}

    assert {"citation_stack", "terminology_alias", "denominator_conflict_candidate"} <= checks


# ===================================================================== deposit_manifest
def _deposit_tree(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    (data / "a.json").write_text('{"a": 1}', encoding="utf-8")
    (data / "b.json").write_text('{"b": 2}', encoding="utf-8")
    single = tmp_path / "notes.txt"
    single.write_text("standalone item", encoding="utf-8")
    return data, single


def test_deposit_root_hash_stable_across_group_dict_ordering(tmp_path):
    data, single = _deposit_tree(tmp_path)
    stamp = "2026-08-20T00:00:00Z"
    m1 = build_manifest(
        {"records": [data], "extras": [single]},
        tmp_path / "m1.json", author="A. Author", title="Fixture Deposit", created_utc=stamp,
    )
    m2 = build_manifest(
        {"extras": [single], "records": [data]},
        tmp_path / "m2.json", author="A. Author", title="Fixture Deposit", created_utc=stamp,
    )
    assert m1.root_sha256 == m2.root_sha256
    assert m1.n_files == m2.n_files == 3
    assert m1.by_group == {"records": 2, "extras": 1}
    assert m1.missing_declared_items == []


def test_deposit_receipt_flags_changed_missing_and_added(tmp_path):
    data, single = _deposit_tree(tmp_path)
    out = tmp_path / "deposit" / "MANIFEST.json"
    macros = tmp_path / "deposit" / "deposit_numbers.tex"
    manifest = build_manifest(
        {"records": [data], "extras": [single]},
        out, author="A. Author", title="Fixture Deposit", macros_path=macros,
    )
    # the document quotes the root from the same code path that computed it
    macros_text = macros.read_text(encoding="utf-8")
    assert macros_text.startswith("%% AUTO-GENERATED")
    assert manifest.root_sha256 in macros_text

    clean_check = verify_receipt(out)
    assert clean_check.ok and clean_check.root_matches

    (data / "a.json").write_text('{"a": 999}', encoding="utf-8")   # mutate
    single.unlink()                                                # remove
    (data / "new.json").write_text("{}", encoding="utf-8")         # add inside declared dir

    check = verify_receipt(out)
    assert not check.ok
    assert [c["path"] for c in check.changed] and check.changed[0]["path"].endswith("a.json")
    assert len(check.missing) == 1 and check.missing[0].endswith("notes.txt")
    assert len(check.added) == 1 and check.added[0].endswith("new.json")


def test_deposit_missing_declared_item_is_visible_not_silent(tmp_path):
    data, single = _deposit_tree(tmp_path)
    manifest = build_manifest(
        {"records": [data], "extras": [single, tmp_path / "never-written.csv"]},
        tmp_path / "m.json", author="A. Author", title="Fixture Deposit",
    )
    assert manifest.missing_declared_items == [str(tmp_path / "never-written.csv")]
    assert manifest.n_files == 3
