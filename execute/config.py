"""Server-access config for the GPU EXECUTE layer.

Loads `RAT_SERVER_* / RAT_REMOTE_*` from the gitignored `.env` (environment variables only;
CLAUDE.md §6). **Secret values (password / key) are NEVER stored on the dataclass, returned, logged,
or echoed** — only booleans (`has_password` / `has_ssh_key`) are exposed; auth material is read
directly from `os.environ` at connect time and used only there.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass(frozen=True)
class ServerConfig:
    host: str
    port: int
    user: str
    workdir: str
    python: str
    conda_env: str
    conda_sh: str
    scheduler: str
    results_pull_dir: str
    known_hosts: str          # ⑥ path to a known_hosts file for SSH host-key verification (RAT_SERVER_KNOWN_HOSTS)
    has_password: bool        # booleans only — never the secret itself
    has_ssh_key: bool


def _load_dotenv(env_path) -> None:
    """Minimal KEY=VALUE loader (no external dep). Sets os.environ WITHOUT overriding already-set vars."""
    p = Path(env_path)
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, v = s.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())


def load_config(env_path: str = "research_agent_teams/.env") -> ServerConfig:
    _load_dotenv(env_path)

    def g(k: str, default: str = "") -> str:
        return (os.environ.get(k, default) or default).strip()

    host = g("RAT_SERVER_HOST")
    if not host:
        raise RuntimeError(
            "RAT_SERVER_HOST is not set — wire research_agent_teams/.env first (CLAUDE.md §6). "
            "Until the server is wired, the no-GPU operate flows still run; only GPU EXECUTE is gated.")
    try:
        port = int(g("RAT_SERVER_PORT", "22") or "22")
    except ValueError:
        port = 22
    return ServerConfig(
        host=host,
        port=port,
        user=g("RAT_SERVER_USER"),
        workdir=g("RAT_REMOTE_WORKDIR"),
        python=g("RAT_REMOTE_PYTHON", "python3") or "python3",
        conda_env=g("RAT_REMOTE_CONDA_ENV"),
        conda_sh=g("RAT_REMOTE_CONDA_SH"),
        scheduler=g("RAT_SCHEDULER"),
        results_pull_dir=g("RAT_RESULTS_PULL_DIR", "runs") or "runs",
        known_hosts=g("RAT_SERVER_KNOWN_HOSTS"),
        has_password=bool(g("RAT_SERVER_PASSWORD")),
        has_ssh_key=bool(g("RAT_SERVER_SSH_KEY")),
    )


def redacted_summary(cfg: ServerConfig) -> dict:
    """A connection summary with NO secret values. host/user/workdir are operational identifiers
    (not credentials); the password/key are shown only as the resolved auth MODE, never their value."""
    return {
        "host": cfg.host,
        "port": cfg.port,
        "user": cfg.user,
        "workdir": cfg.workdir or "(RAT_REMOTE_WORKDIR unset)",
        "python": cfg.python,
        "conda_env": cfg.conda_env or "(per-run — set RAT_REMOTE_CONDA_ENV)",
        "conda_sh": cfg.conda_sh or "(set RAT_REMOTE_CONDA_SH)",
        "scheduler": cfg.scheduler or "(none — tmux/nohup)",
        "auth": "password" if cfg.has_password else ("ssh-key" if cfg.has_ssh_key else "NONE-set"),
        "results_pull_dir": cfg.results_pull_dir,
    }
