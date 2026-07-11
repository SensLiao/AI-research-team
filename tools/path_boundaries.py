"""Shared filesystem boundary checks for RAT tooling."""
from __future__ import annotations

from pathlib import Path

_PKG_ROOT = Path(__file__).resolve().parent.parent
_WORKSPACE_ROOT = _PKG_ROOT.parent
DEFAULT_VAULT_ROOT = _WORKSPACE_ROOT / "AI agent database" / "PhD-Research-OS"


class PathBoundaryError(ValueError):
    """Raised when a caller-provided path crosses a protected boundary."""


def _resolve(path: str | Path) -> Path:
    return Path(path).expanduser().resolve(strict=False)


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def default_vault_root() -> Path:
    """Return the expected PhD-Research-OS vault root for this workspace."""
    return _resolve(DEFAULT_VAULT_ROOT)


def assert_not_vault_path(
    path: str | Path,
    *,
    purpose: str = "write",
    vault_root: str | Path | None = None,
) -> Path:
    """Resolve and return ``path`` unless it is inside the research vault."""
    target = _resolve(path)
    protected_root = _resolve(vault_root) if vault_root is not None else default_vault_root()
    if target == protected_root or _is_relative_to(target, protected_root):
        raise PathBoundaryError(f"refusing to {purpose} inside vault: {target}")
    return target


__all__ = ["DEFAULT_VAULT_ROOT", "PathBoundaryError", "assert_not_vault_path", "default_vault_root"]
