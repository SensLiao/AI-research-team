"""研究链条图 —— 「哪个点子还没有对应实验」.

The property that matters: a "断了" row must mean *no wikilink was found*, and the tool must say so
rather than implying the work does not exist. Every coverage test below is paired with its inverse.
"""
from __future__ import annotations

from research_agent_teams.tools import research_map as rm


def _page(wiki, kind, slug, *, project="p", body="", **front):
    folder = wiki / (kind + "s")
    folder.mkdir(parents=True, exist_ok=True)
    lines = ["---", f"title: {slug} title", f"type: {kind}", f"project: {project}"]
    lines += [f"{key.replace('_', '-')}: {value}" for key, value in front.items()]
    lines += ["---", "", body]
    (folder / f"{slug}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _vault(tmp_path):
    wiki = tmp_path / "02-wiki"
    wiki.mkdir(parents=True)
    return wiki


def test_an_idea_with_no_experiment_is_reported_as_broken(tmp_path):
    wiki = _vault(tmp_path)
    _page(wiki, "idea", "lonely-idea", idea_status="in-consideration")
    step = next(s for s in rm.build_map("p", vault_root=tmp_path)["steps"] if s["kind"] == "idea")
    assert step["total"] == 1 and step["broken"] == 1 and step["covered"] == 0
    assert step["broken_pages"][0]["slug"] == "lonely-idea"


def test_an_experiment_linking_the_idea_makes_it_covered(tmp_path):
    """The inverse of the test above — same idea page, one wikilink away from covered."""
    wiki = _vault(tmp_path)
    _page(wiki, "idea", "lonely-idea", idea_status="in-consideration")
    _page(wiki, "experiment", "exp-1", body="tests [[lonely-idea]] end to end")
    steps = {s["kind"]: s for s in rm.build_map("p", vault_root=tmp_path)["steps"]}
    assert steps["idea"]["covered"] == 1 and steps["idea"]["broken"] == 0
    # …and the experiment itself is now the broken link, because nothing produced a result for it.
    assert steps["experiment"]["broken"] == 1


def test_a_link_from_the_wrong_type_does_not_count_as_downstream(tmp_path):
    """A synthesis mentioning an idea is not an experiment for it — otherwise every discussed idea
    would silently read as 'covered', which is the exact false comfort this view exists to prevent."""
    wiki = _vault(tmp_path)
    _page(wiki, "idea", "chatted-about", idea_status="in-consideration")
    _page(wiki, "synthesis", "lit-review", body="we discuss [[chatted-about]] at length")
    step = next(s for s in rm.build_map("p", vault_root=tmp_path)["steps"] if s["kind"] == "idea")
    assert step["broken"] == 1


def test_only_a_frozen_result_counts_as_citable(tmp_path):
    wiki = _vault(tmp_path)
    _page(wiki, "result", "prov", result_status="provisional")
    _page(wiki, "result", "froz", result_status="frozen")
    step = next(s for s in rm.build_map("p", vault_root=tmp_path)["steps"] if s["kind"] == "result")
    assert step["covered"] == 1 and step["broken"] == 1
    assert step["broken_pages"][0]["slug"] == "prov"


def test_a_referrer_outside_the_project_still_counts(tmp_path):
    """Scoping the REFERRERS as well as the pages would invent broken links: an in-project idea taken
    up by a page that forgot its project binding has still been taken up."""
    wiki = _vault(tmp_path)
    _page(wiki, "idea", "shared-idea", project="p", idea_status="in-consideration")
    _page(wiki, "experiment", "exp-x", project="other", body="based on [[shared-idea]]")
    step = next(s for s in rm.build_map("p", vault_root=tmp_path)["steps"] if s["kind"] == "idea")
    assert step["covered"] == 1, "a cross-project referrer is still a referrer"


def test_project_scoping_excludes_other_projects_pages(tmp_path):
    wiki = _vault(tmp_path)
    _page(wiki, "idea", "mine", project="p", idea_status="in-consideration")
    _page(wiki, "idea", "theirs", project="q", idea_status="in-consideration")
    data = rm.build_map("p", vault_root=tmp_path)
    assert data["pages_in_scope"] == 1 and data["pages_in_vault"] == 2


def test_the_blind_spot_is_always_stated(tmp_path):
    wiki = _vault(tmp_path)
    _page(wiki, "idea", "x", idea_status="in-consideration")
    data = rm.build_map("p", vault_root=tmp_path)
    assert "wikilink" in data["blind_spot"]
    rendered = rm.render_map(data)
    assert "诚实边界" in rendered and "不等于这件事没做过" in rendered


def test_a_missing_or_empty_vault_renders_instead_of_crashing(tmp_path):
    data = rm.build_map("p", vault_root=tmp_path / "nope")
    assert data["pages_in_vault"] == 0
    assert "研究链条" in rm.render_map(data)


def test_the_map_never_writes(tmp_path):
    source = open(rm.__file__, encoding="utf-8").read()
    for forbidden in (".write_text(", ".write_bytes(", ".unlink(", "rmtree(", ".mkdir(",
                      "os.remove(", "os.replace("):
        assert forbidden not in source, f"the map must stay read-only; found {forbidden!r}"
