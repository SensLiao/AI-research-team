"""Gated GPU-execution orchestrator.

DEFAULT = `plan` — build + return the EXACT remote job (offline, NO connection). Always safe; this is
what the model runs to show the director what WOULD execute.

LIVE (`connect` / `submit` / `status` / `pull`) = real SSH. **Refused** unless the DIRECTOR has set
`RAT_EXECUTE_AUTHORIZED == <run_id>` in the environment and is present. The model must NEVER set that
variable, never self-authorize, never run a live submit on the shared lab machine unsupervised
(CLAUDE.md §6 + shared-University-server etiquette). `paramiko` is imported lazily inside `connect`, so
`plan` and the tests never need it nor a live connection.
"""
from __future__ import annotations

import os
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
        "live_gate": ("LIVE submit is director-gated: set RAT_EXECUTE_AUTHORIZED=%s and be present. "
                      "The model must not self-authorize." % job.run_id),
    }


def is_authorized(job: JobSpec) -> bool:
    """True only if the DIRECTOR authorized THIS run_id via the environment. The model never sets this."""
    return os.environ.get("RAT_EXECUTE_AUTHORIZED", "") == job.run_id and bool(job.run_id)


def connect(job: JobSpec, env_path: str = "research_agent_teams/.env"):
    """Open a LIVE SSH connection — refused unless the director authorized this run + is present.
    Returns (paramiko.SSHClient, ServerConfig). paramiko is imported lazily here only."""
    if not is_authorized(job):
        raise LiveConnectionRefused(
            "LIVE execution refused. The director must set RAT_EXECUTE_AUTHORIZED=%s and be present for "
            "the first/any real connection to the shared lab GPU server (CLAUDE.md §6 + shared-machine "
            "etiquette). The model must NOT self-authorize. Run `plan` to preview the job offline." % job.run_id)
    cfg = load_config(env_path)
    if not (cfg.has_password or cfg.has_ssh_key):
        raise RuntimeError("no auth in .env (RAT_SERVER_PASSWORD / RAT_SERVER_SSH_KEY both empty).")
    import paramiko  # lazy: only a live run needs it

    client = paramiko.SSHClient()
    _harden_host_key_verification(client, cfg)   # ⑥ verify identity; reject unknown host (no auto-trust)
    try:
        client.connect(
            hostname=cfg.host, port=cfg.port, username=cfg.user,
            password=(os.environ.get("RAT_SERVER_PASSWORD") or None),
            key_filename=(os.environ.get("RAT_SERVER_SSH_KEY") or None),
            timeout=30, look_for_keys=False, allow_agent=False,
        )
    except paramiko.SSHException as exc:
        raise RuntimeError(
            f"SSH host-key verification failed for {cfg.host}: {exc}. The server's key is not in known_hosts — "
            "this is the MITM guard, NOT a bug. Pin the key out-of-band (e.g. "
            "`ssh-keyscan -p <port> <host> >> ~/.ssh/known_hosts`, or into a file you set as "
            "RAT_SERVER_KNOWN_HOSTS), verify the fingerprint with the lab, then retry. The connection is "
            "never auto-trusted.") from exc
    return client, cfg


def _put_text(sftp, remote_path: str, text: str) -> None:
    with sftp.file(remote_path, "w") as f:        # written with the text's own (LF) newlines
        f.write(text)


def submit(job: JobSpec, env_path: str = "research_agent_teams/.env") -> dict:
    """LIVE: upload the script + run.sh into the run's remote dir and launch it in tmux. Director-gated."""
    client, cfg = connect(job, env_path)
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
        return {"submitted": True, "session": f"rat-{job.run_id}", "remote_run_dir": rdir,
                "status_hint": "operate execute status --run-id %s" % job.run_id}
    finally:
        client.close()


def status(job: JobSpec, env_path: str = "research_agent_teams/.env") -> dict:
    """LIVE: read the tmux pane tail (non-destructive). Director-gated."""
    client, cfg = connect(job, env_path)
    try:
        _, out, _ = client.exec_command(tmux_status_command(job))
        return {"run_id": job.run_id, "tail": out.read().decode("utf-8", "replace")}
    finally:
        client.close()


def pull(job: JobSpec, env_path: str = "research_agent_teams/.env", into: str = None) -> dict:
    """LIVE: pull the per-run log + a `results/` dir back into the local run-store. Director-gated."""
    client, cfg = connect(job, env_path)
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
        return {"run_id": job.run_id, "pulled_to": str(local), "files": pulled}
    finally:
        client.close()
