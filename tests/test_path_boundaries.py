from __future__ import annotations

import pytest

from research_agent_teams.tools.path_boundaries import (
    PathBoundaryError,
    assert_not_vault_path,
)


def test_assert_not_vault_path_blocks_vault_root_and_children(tmp_path):
    vault = tmp_path / "vault"
    with pytest.raises(PathBoundaryError, match="inside vault"):
        assert_not_vault_path(vault, vault_root=vault)
    with pytest.raises(PathBoundaryError, match="inside vault"):
        assert_not_vault_path(vault / "subdir" / "artifact.json", vault_root=vault)


def test_assert_not_vault_path_allows_siblings(tmp_path):
    vault = tmp_path / "vault"
    sibling = tmp_path / "scratch" / "artifact.json"
    assert assert_not_vault_path(sibling, vault_root=vault) == sibling.resolve(strict=False)
