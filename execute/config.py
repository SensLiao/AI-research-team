"""Server-access config for the GPU EXECUTE layer.

Loads `RAT_SERVER_* / RAT_REMOTE_*` from the gitignored `.env` (environment variables only;
CLAUDE.md §6). **Secret values (password / key) are NEVER stored on the dataclass, returned, logged,
or echoed** — only booleans (`has_password` / `has_ssh_key`) are exposed; auth material is read
directly from `os.environ` at connect time and used only there.
"""
from __future__ import annotations

import ipaddress
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Optional


_ENV_NAME_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")

_LEGACY_ENV_REFS = {
    "host": "RAT_SERVER_HOST",
    "endpoint": "RAT_SERVER_HOST",
    "port": "RAT_SERVER_PORT",
    "user": "RAT_SERVER_USER",
    "password": "RAT_SERVER_PASSWORD",
    "ssh_key": "RAT_SERVER_SSH_KEY",
    "remote_workdir": "RAT_REMOTE_WORKDIR",
    "python": "RAT_REMOTE_PYTHON",
    "conda_env": "RAT_REMOTE_CONDA_ENV",
    "conda_sh": "RAT_REMOTE_CONDA_SH",
    "scheduler": "RAT_SCHEDULER",
    "results_pull_dir": "RAT_RESULTS_PULL_DIR",
    "known_hosts": "RAT_SERVER_KNOWN_HOSTS",
    "connect_host": "RAT_SERVER_CONNECT_HOST",
}


@dataclass(frozen=True, repr=False)
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
    # Env-var NAMES only. Values remain outside the object and are fetched at connect time.
    password_env: str = "RAT_SERVER_PASSWORD"
    ssh_key_env: str = "RAT_SERVER_SSH_KEY"
    # Optional TCP endpoint used when local DNS is overridden.  Host-key verification still uses
    # ``host`` (the canonical DNS identity); this IP is deliberately omitted from repr/summary.
    connect_host: str = ""

    def __repr__(self) -> str:
        """Custom repr (dataclass default disabled) so a stray repr()/log line / traceback NEVER spills
        operational identifiers. The default dataclass repr exposes user / workdir / known_hosts; those
        are not secrets, but they are unnecessary in a debug print and tighten the blast radius if a
        config object lands in a log. Only host / port / the resolved auth MODE are shown — the
        password/key values are never on the object in the first place (read from os.environ at connect)."""
        auth = "password" if self.has_password else ("ssh_key" if self.has_ssh_key else "none")
        return f"ServerConfig(host={self.host!r}, port={self.port}, auth={auth})"


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


def _normalise_env_refs(env_refs: Optional[Mapping[str, str]]) -> dict[str, str]:
    """Return role -> env-var NAME without ever resolving a value.

    ``None`` preserves the original single-server RAT_SERVER_* contract. Supplying a mapping is an
    explicit multi-resource path: server-specific roles do not silently fall back to the primary
    server, which prevents credentials or endpoints from being mixed across resources.
    """
    if env_refs is None:
        return dict(_LEGACY_ENV_REFS)
    refs = dict(env_refs)
    for role, name in refs.items():
        if not isinstance(role, str) or not isinstance(name, str) or not _ENV_NAME_RE.fullmatch(name):
            raise ValueError(
                f"invalid environment reference for {role!r}: expected a bare UPPER_SNAKE name")
    if "host" not in refs and "endpoint" in refs:
        refs["host"] = refs["endpoint"]
    return refs


def load_config(env_path: str = "research_agent_teams/.env", *,
                env_refs: Optional[Mapping[str, str]] = None) -> ServerConfig:
    _load_dotenv(env_path)

    refs = _normalise_env_refs(env_refs)

    def ref(role: str) -> str:
        return refs.get(role, "")

    def g(role: str, default: str = "") -> str:
        name = ref(role)
        if not name:
            return default
        return (os.environ.get(name, default) or default).strip()

    host = g("host")
    if not host:
        raise RuntimeError(
            "server host is not set through the selected resource's env references — wire "
            "research_agent_teams/.env first (CLAUDE.md §6). "
            "Until the server is wired, the no-GPU operate flows still run; only GPU EXECUTE is gated.")
    try:
        port = int(g("port", "22") or "22")
    except ValueError:
        port = 22
    connect_host = g("connect_host")
    if connect_host:
        try:
            ipaddress.ip_address(connect_host)
        except ValueError as exc:
            raise RuntimeError(
                "RAT_SERVER_CONNECT_HOST must be an IP literal. Keep RAT_SERVER_HOST as the "
                "canonical hostname used for pinned host-key verification."
            ) from exc
    return ServerConfig(
        host=host,
        port=port,
        user=g("user"),
        workdir=g("remote_workdir"),
        python=g("python", "python3") or "python3",
        conda_env=g("conda_env"),
        conda_sh=g("conda_sh"),
        scheduler=g("scheduler"),
        results_pull_dir=g("results_pull_dir", "runs") or "runs",
        known_hosts=g("known_hosts"),
        has_password=bool(g("password")),
        has_ssh_key=bool(g("ssh_key")),
        password_env=ref("password"),
        ssh_key_env=ref("ssh_key"),
        connect_host=connect_host,
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
        "connection_route": (
            "direct-ip/canonical-host-key" if cfg.connect_host else "canonical-host"
        ),
    }
