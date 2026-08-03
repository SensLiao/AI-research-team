"""Gated GPU-execution orchestrator.

DEFAULT = `plan` — build + return the EXACT remote job (offline, NO connection). Always safe; this is
what the model runs to show the director what WOULD execute.

LIVE (`connect` / `submit` / `status` / `pull`) = real SSH. **Refused** unless the primary assistant has
just received an explicit top-level confirmation from the DIRECTOR for this operation, or the legacy
exact `RAT_EXECUTE_AUTHORIZED == <run_id>` capability is present. The ordinary CLI cannot assert the
top-level confirmation flag. Workers, modes and scheduled jobs must never self-authorize or run a live
submit on the shared lab machine unsupervised (CLAUDE.md §6 + shared-University-server etiquette).
`paramiko` is imported lazily inside `connect`, so `plan` and the tests never need it nor a live connection.
"""
from __future__ import annotations

import os
import socket
from pathlib import Path
from typing import Optional

from ..tools.scope_guard import discover_vault_root
from .config import load_config, redacted_summary
from .job import (
    JobSpec,
    assert_in_workdir,
    build_job_script,
    remote_run_dir,
    tmux_status_command,
    tmux_submit_command,
)


class LiveConnectionRefused(RuntimeError):
    """A live connection/submit was attempted without the director's explicit authorization."""


def _harden_host_key_verification(client, cfg) -> None:
    """⑥ Verify the server's identity — NO trust-on-first-use. Load the system known_hosts plus any
    director-pinned RAT_SERVER_KNOWN_HOSTS, then REJECT an unknown host (MITM defense). Extracted so the
    policy is unit-testable without a live connection. Replaces the old AutoAddPolicy (auto-trust)."""
    import paramiko
    try:
        client.load_system_host_keys()
    except Exception:
        pass
    if cfg.known_hosts and Path(cfg.known_hosts).exists():
        client.load_host_keys(cfg.known_hosts)
    client.set_missing_host_key_policy(paramiko.RejectPolicy())


def _connect_verified_transport(client, cfg, *, socket_factory=socket.create_connection) -> None:
    """Connect over an optional direct IP while verifying the canonical SSH host identity.

    Local DNS interception must not force either a failed connection or a weaker host-key policy.
    When ``connect_host`` is set, a TCP socket is opened to that IP, then handed to Paramiko while
    ``hostname`` remains the canonical name. Paramiko therefore looks up the pinned canonical
    known-hosts entry, not an untrusted IP alias.
    """
    direct_socket = None
    if cfg.connect_host:
        direct_socket = socket_factory((cfg.connect_host, cfg.port), timeout=30)
    try:
        client.connect(
            hostname=cfg.host,
            port=cfg.port,
            username=cfg.user,
            password=(os.environ.get(cfg.password_env) or None) if cfg.password_env else None,
            key_filename=(os.environ.get(cfg.ssh_key_env) or None) if cfg.ssh_key_env else None,
            timeout=30,
            look_for_keys=False,
            allow_agent=False,
            sock=direct_socket,
        )
    except Exception:
        if direct_socket is not None:
            direct_socket.close()
        raise


def _safe_pull_dest(results_pull_dir: str, run_id: str, into: Optional[str],
                    vault_root: Optional[str] = None, project: str = "") -> Path:
    """⑤ Resolve + FENCE the local landing dir for pulled results: it MUST stay inside results_pull_dir and
    MUST NEVER be inside the vault. A crafted `into` / run_id cannot redirect remote results into the crown
    jewels (or anywhere outside the run-store). With a project, the default landing dir mirrors the
    run-store grouping: <results_pull_dir>/<project>/<run_id>/pulled. Pure + testable; no connection."""
    base = Path(results_pull_dir).resolve()
    if into is not None:
        dest = Path(into).resolve()
    elif project:
        dest = (base / project / run_id / "pulled").resolve()
    else:
        dest = (base / run_id / "pulled").resolve()
    bs, ds = str(base), str(dest)
    if not (ds == bs or ds.startswith(bs + os.sep)):
        raise PermissionError(f"refused: pull destination {dest} escapes the results dir {base}")
    vr = vault_root or discover_vault_root()
    if vr:
        vs = str(Path(vr).resolve())
        if ds == vs or ds.startswith(vs + os.sep):
            raise PermissionError(
                f"refused: pull destination {dest} is inside the vault — knowledge enters System D only via "
                "the /promote-to-vault gate, never by pulling remote results")
    return dest


def plan(job: JobSpec, env_path: str = "research_agent_teams/.env") -> dict:
    """Offline preview: the exact run.sh + tmux submit + status commands + a NO-secret server summary.
    No connection is opened. This is the model-safe default the director reviews before authorizing."""
    cfg = load_config(env_path)
    rdir = remote_run_dir(cfg, job)
    assert_in_workdir(cfg, rdir)
    return {
        "run_id": job.run_id,
        "project": job.project or None,
        "server": redacted_summary(cfg),
        "remote_run_dir": rdir,
        "run_sh": build_job_script(cfg, job),
        "submit_cmd": tmux_submit_command(cfg, job),
        "status_cmd": tmux_status_command(job),
        "connection": "NOT CONNECTED (plan only).",
        "live_gate": (
            "LIVE operation is director-gated for run %s: the primary assistant must show the exact "
            "remote write/command plan and ask for an in-chat confirmation immediately before acting. "
            "RAT_EXECUTE_AUTHORIZED remains a legacy unattended-CLI capability; the director does not "
            "need to set it for an assistant-mediated operation." % job.run_id
        ),
    }


def is_authorized(job: JobSpec, *, explicit_director_command: bool = False) -> bool:
    """Accept a fresh top-level director confirmation or the legacy exact-run capability.

    ``explicit_director_command`` is intentionally a library-only parameter. The primary assistant may
    pass it only after presenting the exact remote mutation and receiving the director's confirmation in
    chat. The public execution CLI does not expose a matching flag, so workers, modes and schedules retain
    the default-deny path.
    """
    return bool(job.run_id) and (
        bool(explicit_director_command)
        or os.environ.get("RAT_EXECUTE_AUTHORIZED", "") == job.run_id
    )


def authorization_basis(job: JobSpec, *, explicit_director_command: bool = False) -> Optional[str]:
    """Return the non-secret authorization provenance recorded in live-operation receipts."""
    if explicit_director_command and job.run_id:
        return "explicit-director-command"
    if os.environ.get("RAT_EXECUTE_AUTHORIZED", "") == job.run_id and bool(job.run_id):
        return "legacy-exact-environment"
    return None


def connect(job: JobSpec, env_path: str = "research_agent_teams/.env", *,
            explicit_director_command: bool = False):
    """Open a LIVE SSH connection — refused unless the director authorized this run + is present.
    Returns (paramiko.SSHClient, ServerConfig). paramiko is imported lazily here only."""
    if not is_authorized(job, explicit_director_command=explicit_director_command):
        raise LiveConnectionRefused(
            "LIVE execution refused for run %s. The primary assistant must first show the exact remote "
            "write/command plan and receive the director's explicit in-chat confirmation. The director "
            "does not need to set a PowerShell variable for an assistant-mediated operation. The legacy "
            "unattended CLI remains scoped by RAT_EXECUTE_AUTHORIZED=<run-id>. Run `plan` to preview the "
            "job offline." % job.run_id)
    cfg = load_config(env_path)
    if not (cfg.has_password or cfg.has_ssh_key):
        raise RuntimeError("no auth in .env (RAT_SERVER_PASSWORD / RAT_SERVER_SSH_KEY both empty).")
    import paramiko  # lazy: only a live run needs it

    client = paramiko.SSHClient()
    _harden_host_key_verification(client, cfg)   # ⑥ verify identity; reject unknown host (no auto-trust)
    try:
        _connect_verified_transport(client, cfg)
    except (paramiko.SSHException, OSError) as exc:
        raise RuntimeError(
            f"SSH connection or host-key verification failed for {cfg.host}: {exc}. When a direct "
            "IP route is configured, TCP uses that endpoint but identity verification still uses this "
            "canonical hostname. The server's key must be in known_hosts — this is the MITM guard, "
            "NOT a bug. Pin the key out-of-band (e.g. "
            "`ssh-keyscan -p <port> <host> >> ~/.ssh/known_hosts`, or into a file you set as "
            "RAT_SERVER_KNOWN_HOSTS), verify the fingerprint with the lab, then retry. The connection is "
            "never auto-trusted.") from exc
    return client, cfg


def _put_text(sftp, remote_path: str, text: str) -> None:
    with sftp.file(remote_path, "w") as f:        # written with the text's own (LF) newlines
        f.write(text)


def submit(job: JobSpec, env_path: str = "research_agent_teams/.env", *,
           explicit_director_command: bool = False) -> dict:
    """LIVE: upload the script + run.sh into the run's remote dir and launch it in tmux. Director-gated."""
    client, cfg = connect(
        job, env_path, explicit_director_command=explicit_director_command
    )
    try:
        rdir = remote_run_dir(cfg, job)
        assert_in_workdir(cfg, rdir)
        client.exec_command(f'mkdir -p "{rdir}"')
        sftp = client.open_sftp()
        try:
            if job.local_script:
                sftp.put(job.local_script, f"{rdir}/{job.script}")
            _put_text(sftp, f"{rdir}/run.sh", build_job_script(cfg, job))
        finally:
            sftp.close()
        client.exec_command(tmux_submit_command(cfg, job))
        return {
            "submitted": True,
            "session": f"rat-{job.run_id}",
            "remote_run_dir": rdir,
            "status_hint": "operate execute status --run-id %s" % job.run_id,
            "authorization_basis": authorization_basis(
                job, explicit_director_command=explicit_director_command
            ),
        }
    finally:
        client.close()


def status(job: JobSpec, env_path: str = "research_agent_teams/.env", *,
           explicit_director_command: bool = False) -> dict:
    """LIVE: read the tmux pane tail (non-destructive). Director-gated."""
    client, cfg = connect(
        job, env_path, explicit_director_command=explicit_director_command
    )
    try:
        _, out, _ = client.exec_command(tmux_status_command(job))
        return {
            "run_id": job.run_id,
            "tail": out.read().decode("utf-8", "replace"),
            "authorization_basis": authorization_basis(
                job, explicit_director_command=explicit_director_command
            ),
        }
    finally:
        client.close()


def pull(job: JobSpec, env_path: str = "research_agent_teams/.env", into: str = None, *,
         explicit_director_command: bool = False) -> dict:
    """LIVE: pull the per-run log + a `results/` dir back into the local run-store. Director-gated."""
    client, cfg = connect(
        job, env_path, explicit_director_command=explicit_director_command
    )
    try:
        rdir = remote_run_dir(cfg, job)
        # ⑤ fence the landing dir before any local write: a crafted `into`/run_id can never write the vault
        # or escape the run-store. (Raises PermissionError on violation — nothing is pulled.)
        local = _safe_pull_dest(cfg.results_pull_dir, job.run_id, into, project=job.project)
        local.mkdir(parents=True, exist_ok=True)
        sftp = client.open_sftp()
        pulled = []
        try:
            for remote_name in (f"{job.run_id}.log",):
                # strip any path components a (future) server-named file might carry — stays inside `local`.
                dest_file = local / Path(remote_name).name
                try:
                    sftp.get(f"{rdir}/{remote_name}", str(dest_file))
                    pulled.append(remote_name)
                except IOError:
                    pass
        finally:
            sftp.close()
        return {
            "run_id": job.run_id,
            "pulled_to": str(local),
            "files": pulled,
            "authorization_basis": authorization_basis(
                job, explicit_director_command=explicit_director_command
            ),
        }
    finally:
        client.close()
