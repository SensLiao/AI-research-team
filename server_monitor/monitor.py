"""Read-only GPU-server monitor — the `server-query` capability of System M.

Mirrors execute/runner's plan-vs-live split:

  plan()        offline, ALWAYS safe — redacted server summary + the exact read-only commands it WOULD
                run. No connection, no paramiko.
  live_status() LIVE SSH (READ-ONLY). Refused unless the director set RAT_SERVER_QUERY_AUTHORIZED
                (default OFF -> tested-not-operated). paramiko is imported lazily; an `executor` can be
                injected (tests). Credentials are read from .env at connect time only, never stored or
                echoed; the server summary is redacted (host / user / auth-MODE).

Every command is forced through `ReadOnlyExecutor`, which REJECTS any mutating verb / output-redirect /
SFTP — so neither a bug nor a future edit can make server-query write, kill, or transfer files on the
shared lab machine. Optional resource-plane integration: pass project+run_id to lease `query_status` on
the project's `primary_gpu` binding (ResourceResolver), leaving a redacted audit line per live check.
"""
from __future__ import annotations

import os
import re
from typing import List, Optional

from research_agent_teams.execute import config as ec
from research_agent_teams.execute import runner as ex_runner
from research_agent_teams.server_monitor import train_progress as tp

AUTH_ENV = "RAT_SERVER_QUERY_AUTHORIZED"

GPU_QUERY = ("nvidia-smi --query-gpu=index,utilization.gpu,memory.used,memory.total,"
             "temperature.gpu --format=csv,noheader,nounits")

# A command is allowed only if it is provably READ-ONLY. This guard rejects any mutating verb or a
# real-file output redirect, so server-query can never write/kill/transfer on the server
# (defence-in-depth: it guards both this module's own commands AND the vendored train_progress parser's
# commands). `2>/dev/null`, `>/dev/null`, `2>&1` etc. are stderr/stream redirects (safe) and are
# stripped before the remaining-`>` (real-file write) check.
_FORBIDDEN = re.compile(
    r"(^|[|;&]|\s)(rm|kill|pkill|mv|cp|dd|sudo|chmod|chown|chgrp|shutdown|reboot|mkfs|truncate|"
    r"tee|scp|rsync|wget|curl|systemctl|crontab)\b")
_SAFE_REDIRECT = re.compile(r"(\d?>{1,2}\s*/dev/null|&>{1,2}\s*/dev/null|\d?>&[\d-]+)")


class ServerQueryRefused(RuntimeError):
    """A live server query was attempted without the director's RAT_SERVER_QUERY_AUTHORIZED."""


class UnsafeServerCommand(RuntimeError):
    """A command that is not provably read-only was about to run on the server."""


def assert_read_only(cmd: str) -> None:
    # strip the safe stderr/stream redirects first, so only a REAL-file write `>` trips the guard
    if ">" in _SAFE_REDIRECT.sub("", cmd) or _FORBIDDEN.search(cmd):
        raise UnsafeServerCommand(f"refused non-read-only server command: {cmd!r}")


class ReadOnlyExecutor:
    """Wraps an SSH-like client and asserts every command is read-only before delegating. SFTP blocked."""

    def __init__(self, client):
        self._c = client

    def exec_command(self, cmd: str, timeout: int = 30):
        assert_read_only(cmd)
        return self._c.exec_command(cmd, timeout=timeout)

    def open_sftp(self):
        raise UnsafeServerCommand("server-query is read-only: SFTP/file transfer is not allowed")

    def close(self):
        try:
            self._c.close()
        except Exception:
            pass


def _run(executor, cmd: str, timeout: int = 30) -> str:
    _, out, _ = executor.exec_command(cmd, timeout=timeout)
    return out.read().decode("utf-8", errors="replace")


# --------------------------------------------------------------------------- parsing

def parse_tmux_sessions(out: str) -> List[str]:
    """`tmux ls` -> session names (text before the first ':'). Robust to 'no server running'."""
    sessions: List[str] = []
    for line in (out or "").splitlines():
        line = line.strip()
        if not line or "no server running" in line.lower() or "error connecting" in line.lower():
            continue
        name = line.split(":", 1)[0].strip()
        if name:
            sessions.append(name)
    return sessions


def parse_gpu_table(csv: str) -> List[dict]:
    """Parse the 5-field nvidia-smi GPU table (index,util,mem.used,mem.total,temp)."""
    gpus: List[dict] = []
    for line in (csv or "").splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 5:
            continue
        try:
            gpus.append({"idx": int(parts[0]), "util": int(parts[1]), "mem_used": int(parts[2]),
                         "mem_total": int(parts[3]), "temp": int(parts[4])})
        except ValueError:
            continue
    return gpus


# --------------------------------------------------------------------------- plan / gate / connect

def _planned_commands(workdir: str = "$RAT_REMOTE_WORKDIR") -> List[str]:
    return [
        "tmux ls",
        GPU_QUERY,
        f"df -h {workdir} | tail -1",
        "# per training session (read-only, via train_progress): tmux list-panes / ps / nvidia-smi / "
        "tail log",
    ]


def plan(env_path: str = "research_agent_teams/.env") -> dict:
    """Offline preview: redacted server summary + the read-only commands server-query WOULD run.
    No connection is opened. This is the safe default the director reviews before authorizing."""
    try:
        cfg = ec.load_config(env_path)
        server = ec.redacted_summary(cfg)
        workdir = cfg.workdir or "$RAT_REMOTE_WORKDIR"
    except Exception as e:                       # .env not wired / no host -> still show the plan
        server = {"status": f"offline ({type(e).__name__}) — set RAT_SERVER_HOST in .env to enable"}
        workdir = "$RAT_REMOTE_WORKDIR"
    return {
        "mode": "plan",
        "server": server,
        "read_only_commands": _planned_commands(workdir),
        "connection": "NOT CONNECTED (plan only).",
        "live_gate": (f"set {AUTH_ENV}=1 (director) to allow a READ-ONLY live status check; "
                      "the model must not self-authorize."),
    }


def is_authorized() -> bool:
    """True only if the director enabled live read-only queries via the environment. Model never sets it."""
    return bool(os.environ.get(AUTH_ENV, "").strip())


def connect(env_path: str = "research_agent_teams/.env"):
    """Open a LIVE read-only SSH connection — refused unless RAT_SERVER_QUERY_AUTHORIZED is set.
    Returns (ReadOnlyExecutor, ServerConfig). paramiko is imported lazily here only."""
    if not is_authorized():
        raise ServerQueryRefused(
            f"LIVE server query refused. The director must set {AUTH_ENV}=1 to allow a READ-ONLY status "
            "check over SSH to the shared lab GPU server (CLAUDE.md §6 + shared-machine etiquette). The "
            "model must NOT self-authorize. Run `plan` to preview the read-only commands offline.")
    cfg = ec.load_config(env_path)
    if not (cfg.has_password or cfg.has_ssh_key):
        raise RuntimeError("no auth in .env (RAT_SERVER_PASSWORD / RAT_SERVER_SSH_KEY both empty).")
    import paramiko  # lazy: only a live query needs it

    client = paramiko.SSHClient()
    ex_runner._harden_host_key_verification(client, cfg)   # reuse the MITM guard (reject unknown host)
    client.connect(
        hostname=cfg.host, port=cfg.port, username=cfg.user,
        password=(os.environ.get("RAT_SERVER_PASSWORD") or None),
        key_filename=(os.environ.get("RAT_SERVER_SSH_KEY") or None),
        timeout=30, look_for_keys=False, allow_agent=False,
    )
    return ReadOnlyExecutor(client), cfg


# --------------------------------------------------------------------------- live status

def live_status(*, executor=None, cfg=None, env_path: str = "research_agent_teams/.env",
                project: Optional[str] = None, run_id: Optional[str] = None,
                exclude: Optional[set] = None, resolver=None) -> dict:
    """LIVE read-only status. Gated by RAT_SERVER_QUERY_AUTHORIZED unless an `executor` is injected
    (tests). When project+run_id are given, leases `query_status` on the project's `primary_gpu`
    binding (ResourceResolver) — leaving a redacted audit line."""
    own = executor is None
    if own:
        executor, cfg = connect(env_path)        # raises ServerQueryRefused if not authorized
    elif not isinstance(executor, ReadOnlyExecutor):
        executor = ReadOnlyExecutor(executor)    # force every injected client through the guard too

    lease_info = None
    if project and run_id:
        from research_agent_teams.tools.resource_resolver import ResourceResolver
        resolver = resolver or ResourceResolver()
        resolved = resolver.resolve(project=project, run_id=run_id, alias_or_resource="primary_gpu",
                                    capability="query_status", skill="server-query")
        lease_info = {"lease_id": resolved.lease_id, "resource_id": resolved.resource_id,
                      "requires_human_approval": resolved.requires_human_approval}

    try:
        sessions = parse_tmux_sessions(_run(executor, "tmux ls"))
        gpus = parse_gpu_table(_run(executor, GPU_QUERY))
        workdir = (cfg.workdir if cfg else "") or "/"
        disk = _run(executor, f"df -h {workdir} | tail -1").strip()
        runs = tp.summarize(executor, sessions, exclude=exclude)
        return {
            "mode": "live",
            "server": ec.redacted_summary(cfg) if cfg else {},
            "sessions": sessions,
            "gpus": gpus,
            "disk": disk,
            "runs": runs,
            "lease": lease_info,
        }
    finally:
        if own:
            executor.close()


def query(*, env_path: str = "research_agent_teams/.env", project: Optional[str] = None,
          run_id: Optional[str] = None) -> dict:
    """Convenience entry: live status when the director authorized it, else the offline plan."""
    if is_authorized():
        return live_status(env_path=env_path, project=project, run_id=run_id)
    return plan(env_path)


# --------------------------------------------------------------------------- rendering

def format_status(status: dict) -> str:
    """Render a markdown report from a plan() or live_status() result."""
    if status.get("mode") == "plan":
        lines = ["# Server status — PLAN (offline, not connected)", "",
                 f"server: {status['server']}", f"live gate: {status['live_gate']}",
                 "read-only commands that WOULD run:"]
        lines += [f"  $ {c}" for c in status["read_only_commands"]]
        return "\n".join(lines)

    lines = ["# Server status — LIVE (read-only)", "", f"server: {status['server']}"]
    if status.get("lease"):
        lines.append(f"lease: {status['lease']['lease_id']} on {status['lease']['resource_id']}")
    lines += ["", "## tmux sessions"]
    lines += [f"  - {s}" for s in status["sessions"]] or ["  (none)"]
    lines += ["", "## GPUs"]
    if status["gpus"]:
        for g in status["gpus"]:
            lines.append(f"  GPU{g['idx']}: util={g['util']}% "
                         f"mem={g['mem_used']}/{g['mem_total']}MiB temp={g['temp']}°C")
    else:
        lines.append("  (nvidia-smi returned no GPUs)")
    lines.append(f"\ndisk: {status['disk']}")
    lines.append(tp.format_report(status["runs"]))
    return "\n".join(lines)
