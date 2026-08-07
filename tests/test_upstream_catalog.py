"""上游原文目录 —— findable, and unmistakably NOT capability.

The load-bearing property is the disclaimer, not the listing: a director who reads this catalogue must
not come away thinking the machine can run 358 upstream skills. Every render path is asserted to carry
the boundary, and the module is asserted to have no execution or fetch path at all.
"""
from __future__ import annotations

from research_agent_teams.tools import upstream_catalog as uc


def test_bundles_are_derived_from_real_skill_md_locations_not_a_written_list():
    data = uc.catalog()
    if not data["present"]:
        import pytest
        pytest.skip("no vendored upstream tree on this checkout")
    assert data["sources"], "the manifest lists no sources at all"
    for source in data["sources"]:
        assert source["bundles_found"] == len(source["bundles"])
        # Cross-check: what we DERIVED must match what upstream itself declared. A mismatch means the
        # snapshot drifted, and is worth failing on rather than quietly reporting a smaller number.
        if source["declared_skills"]:
            assert source["bundles_found"] == source["declared_skills"], (
                f"{source['source_id']}: derived {source['bundles_found']} bundles but upstream "
                f"declares {source['declared_skills']}")


def test_every_hit_resolves_to_a_file_that_exists_on_disk():
    result = uc.find("", limit=40)
    if not result["matched"]:
        import pytest
        pytest.skip("no vendored upstream tree on this checkout")
    missing = [hit["handle"] for hit in result["hits"] if not hit["on_disk"]]
    assert not missing, f"catalogued but absent from disk: {missing[:5]}"


def test_a_query_that_matches_nothing_returns_nothing_rather_than_everything():
    result = uc.find("definitely-not-a-real-skill-name-xyzzy")
    assert result["matched"] == 0 and result["hits"] == []


def test_the_not_capability_boundary_is_on_every_rendered_surface():
    catalogue = uc.render_catalog(uc.catalog())
    hits = uc.render_hits(uc.find("", limit=3))
    for rendered in (catalogue, hits):
        assert "不是这台机器的能力" in rendered
        assert "跑不起来" in rendered


def test_the_excluded_source_stays_excluded_and_is_disclosed():
    data = uc.catalog()
    if not data["present"]:
        import pytest
        pytest.skip("no vendored upstream tree on this checkout")
    ids = {source["source_id"] for source in data["sources"]}
    for excluded in data["excluded_source_ids"]:
        assert excluded not in ids, f"{excluded} was excluded on safety grounds but is being listed"
    assert data["excluded_source_ids"], "the exclusion must be disclosed, not silently absent"
    assert any(x in uc.render_catalog(data) for x in data["excluded_source_ids"])


def test_the_module_has_no_execution_or_fetch_path():
    """The director's 2026-08-04 decision was 只挂原文，不跑任何东西 — enforced here, not just promised."""
    source = open(uc.__file__, encoding="utf-8").read()
    for forbidden in ("subprocess", "os.system", "urllib", "requests", "socket", "importlib",
                      "exec(", "eval(", ".write_text(", ".mkdir("):
        assert forbidden not in source, f"the upstream catalogue must never {forbidden!r}"


def test_a_missing_manifest_degrades_honestly(monkeypatch, tmp_path):
    monkeypatch.setattr(uc, "MANIFEST", tmp_path / "nope.json")
    data = uc.catalog()
    assert data["present"] is False and data["sources"] == []
    assert "没找到" in uc.render_catalog(data)
