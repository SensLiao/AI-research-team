"""Direct unit test for ``promote._path_within`` — the defence-in-depth net (``promote.py:33-38``)
that refuses to write when a resolved vault-page path escapes ``02-wiki/``. This last-line guard is
currently UNREACHABLE through the public API (upstream ``_candidate_violations`` rejects every
path-traversal vector first), so without this test its correctness is unverified independent of the
upstream guard. Reconciliation-audit Wave-0 item (2026-06-18): the existing promote tests prove the
*upstream* guard; this pins the *last-line* net itself.
"""
from research_agent_teams.tools import promote


def test_child_directly_inside_root_is_within(tmp_path):
    root = tmp_path / "02-wiki"
    root.mkdir()
    child = root / "results" / "x.md"
    assert promote._path_within(child, root) is True


def test_root_itself_is_within(tmp_path):
    root = tmp_path / "02-wiki"
    root.mkdir()
    assert promote._path_within(root, root) is True


def test_sibling_dir_is_not_within(tmp_path):
    root = tmp_path / "02-wiki"
    root.mkdir()
    escaped = tmp_path / "00-system" / "evil.md"  # sibling of root, outside it
    assert promote._path_within(escaped, root) is False


def test_dotdot_traversal_out_of_root_is_not_within(tmp_path):
    root = tmp_path / "02-wiki"
    root.mkdir()
    # …/02-wiki/results/../../00-system/evil.md  → normpath collapses to …/00-system/evil.md
    escaped = root / "results" / ".." / ".." / "00-system" / "evil.md"
    assert promote._path_within(escaped, root) is False


def test_dotdot_traversal_landing_back_inside_is_within(tmp_path):
    root = tmp_path / "02-wiki"
    root.mkdir()
    # …/02-wiki/sub/../x.md → normpath collapses to …/02-wiki/x.md (still inside)
    inside = root / "sub" / ".." / "x.md"
    assert promote._path_within(inside, root) is True


def test_prefix_string_sibling_is_not_within(tmp_path):
    # Guards the ``+ os.sep`` in the startswith check: a sibling whose name merely *starts with* the
    # root's name ("02-wiki-evil") must NOT be treated as inside "02-wiki".
    root = tmp_path / "02-wiki"
    root.mkdir()
    sibling = tmp_path / "02-wiki-evil" / "x.md"
    assert promote._path_within(sibling, root) is False
