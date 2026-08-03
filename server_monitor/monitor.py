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

import json
import os
import re
import shlex
from typing import List, Mapping, Optional

from research_agent_teams.execute import config as ec
from research_agent_teams.execute import runner as ex_runner
from research_agent_teams.server_monitor import train_progress as tp

AUTH_ENV = "RAT_SERVER_QUERY_AUTHORIZED"

GPU_QUERY = (
    "nvidia-smi --query-gpu=index,uuid,name,utilization.gpu,memory.used,memory.total,"
    "temperature.gpu,driver_version --format=csv,noheader,nounits"
)
GPU_PROCESS_QUERY = (
    "nvidia-smi --query-compute-apps=pid,gpu_uuid,used_memory "
    "--format=csv,noheader,nounits 2>/dev/null"
)
PS_GPU_PROCESS_QUERY = "ps -o user=,pid=,etime=,comm= -p <GPU_PID> 2>/dev/null"

_PROBE_TIMEOUT_S = 8
_REMOTE_HEALTH_TIMEOUT_S = 5

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


def _probe(executor, cmd: str, *, timeout: int = _PROBE_TIMEOUT_S) -> dict:
    """Run one bounded read-only probe without turning absence into a healthy result.

    Only an exception *type* is retained. Remote command text, stderr, credentials and full process
    arguments are never copied into the returned status object.
    """
    try:
        return {"status": "PASS", "output": _run(executor, cmd, timeout=timeout)}
    except Exception as exc:  # SSH timeout/transport failures must fail closed
        return {"status": "UNKNOWN", "output": "", "error_type": type(exc).__name__}


def _with_exit_marker(cmd: str) -> str:
    return f"{cmd}; printf '\\n__RAT_PROBE_EXIT__=%s\\n' \"$?\""


def _run_with_exit(executor, cmd: str, *, timeout: int = _PROBE_TIMEOUT_S) -> dict:
    """Run a short remote probe and recover its exit status from stdout.

    ``timeout`` bounds the command on the host; the SSH timeout is a second independent bound.
    """
    marker = "__RAT_PROBE_EXIT__="
    wrapped = _with_exit_marker(cmd)
    probed = _probe(executor, wrapped, timeout=timeout)
    if probed["status"] != "PASS":
        return probed
    output = probed["output"]
    match = re.search(rf"(?:^|\n){re.escape(marker)}(\d+)\s*$", output)
    if not match:
        return {"status": "UNKNOWN", "output": "", "error_type": "MissingExitMarker"}
    return {
        "status": "PASS" if int(match.group(1)) == 0 else "FAIL",
        "exit_code": int(match.group(1)),
        "output": output[:match.start()].rstrip(),
    }


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
    """Parse the resource table; retain backward compatibility with the old five-field format."""
    gpus: List[dict] = []
    for line in (csv or "").splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 5:
            continue
        try:
            if len(parts) >= 8:
                gpus.append({
                    "idx": int(parts[0]), "uuid": parts[1], "name": parts[2],
                    "util": int(parts[3]), "mem_used": int(parts[4]),
                    "mem_total": int(parts[5]), "temp": int(parts[6]),
                    "driver_version": parts[7],
                })
            else:
                gpus.append({
                    "idx": int(parts[0]), "util": int(parts[1]), "mem_used": int(parts[2]),
                    "mem_total": int(parts[3]), "temp": int(parts[4]),
                })
        except ValueError:
            continue
    return gpus


def parse_gpu_process_table(csv: str) -> List[dict]:
    """Parse compute-app rows without ever requesting or retaining a full command line."""
    processes: List[dict] = []
    for line in (csv or "").splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 3 or not parts[0].isdigit():
            continue
        try:
            memory = int(re.sub(r"\s*MiB$", "", parts[2], flags=re.IGNORECASE))
        except ValueError:
            memory = None
        processes.append({
            "pid": int(parts[0]),
            "gpu_uuid": parts[1],
            "used_memory_mb": memory,
        })
    return processes


def _parse_ps_gpu_process(out: str, expected_pid: int) -> dict:
    """Parse only owner/pid/elapsed/comm; arguments are deliberately not queried."""
    line = (out or "").strip().splitlines()
    if not line:
        return {"inspection_status": "UNKNOWN", "owner": None, "elapsed": None, "comm": None}
    parts = line[0].split(None, 3)
    if len(parts) != 4 or not parts[1].isdigit() or int(parts[1]) != expected_pid:
        return {"inspection_status": "UNKNOWN", "owner": None, "elapsed": None, "comm": None}
    return {
        "inspection_status": "PASS",
        "owner": parts[0],
        "elapsed": parts[2],
        "comm": parts[3],
    }


def _collect_gpu_processes(executor, gpus: List[dict]) -> tuple[List[dict], str]:
    compute = _run_with_exit(executor, GPU_PROCESS_QUERY)
    if compute["status"] != "PASS":
        return [], "UNKNOWN"
    uuid_to_idx = {g.get("uuid"): g["idx"] for g in gpus if g.get("uuid")}
    processes = parse_gpu_process_table(compute["output"])
    for process in processes:
        pid = process["pid"]
        # PID is parsed as an integer above, so it cannot inject shell syntax.
        ps = _probe(executor, f"ps -o user=,pid=,etime=,comm= -p {pid} 2>/dev/null")
        details = (_parse_ps_gpu_process(ps["output"], pid) if ps["status"] == "PASS"
                   else {"inspection_status": "UNKNOWN", "owner": None,
                         "elapsed": None, "comm": None})
        process.update(details)
        process["gpu_idx"] = uuid_to_idx.get(process["gpu_uuid"])
    return processes, "PASS"


def _parse_df_line(out: str, *, kind: str) -> dict:
    line = (out or "").strip().splitlines()
    if not line:
        return {"status": "UNKNOWN"}
    parts = line[-1].split(None, 5)
    if len(parts) != 6:
        return {"status": "UNKNOWN"}
    try:
        total, used, available = (int(parts[1]), int(parts[2]), int(parts[3]))
    except ValueError:
        return {"status": "UNKNOWN"}
    names = (("total_bytes", "used_bytes", "available_bytes") if kind == "bytes"
             else ("total_inodes", "used_inodes", "available_inodes"))
    return {
        "status": "PASS", "filesystem": parts[0], names[0]: total, names[1]: used,
        names[2]: available, "used_percent": parts[4], "mountpoint": parts[5],
        "raw": line[-1],
    }


def _collect_storage(executor, workdir: str) -> dict:
    quoted = shlex.quote(workdir)
    bytes_probe = _probe(executor, f"df -B1 -P -- {quoted} | tail -1")
    inode_probe = _probe(executor, f"df -Pi -P -- {quoted} | tail -1")
    bytes_info = (_parse_df_line(bytes_probe["output"], kind="bytes")
                  if bytes_probe["status"] == "PASS" else {"status": "UNKNOWN"})
    inode_info = (_parse_df_line(inode_probe["output"], kind="inodes")
                  if inode_probe["status"] == "PASS" else {"status": "UNKNOWN"})
    return {
        "status": "PASS" if bytes_info["status"] == inode_info["status"] == "PASS" else "UNKNOWN",
        "path": workdir,
        "bytes": bytes_info,
        "inodes": inode_info,
    }


def _collect_identity(executor) -> dict:
    commands = {
        "hostname": "hostname",
        "utc_time": "date -u +%Y-%m-%dT%H:%M:%SZ",
        "user": "id -un",
        "kernel": "uname -sr",
    }
    result = {key: _probe(executor, cmd, timeout=5) for key, cmd in commands.items()}
    return {
        "status": "PASS" if all(
            v["status"] == "PASS" and v["output"].strip() for v in result.values()
        ) else "UNKNOWN",
        **{key: (value["output"].strip() or None) for key, value in result.items()},
    }


def _collect_runtime(executor, cfg=None) -> dict:
    py = _run_with_exit(executor, f"timeout {_REMOTE_HEALTH_TIMEOUT_S}s python3 --version 2>&1")
    configured_python_raw = str(getattr(cfg, "python", "") or "python3")
    configured_python_name = os.path.basename(configured_python_raw.rstrip("/")) or "python3"
    if configured_python_raw == "python3":
        configured_python = py
    else:
        configured_python = _run_with_exit(
            executor,
            f"timeout {_REMOTE_HEALTH_TIMEOUT_S}s {shlex.quote(configured_python_raw)} --version 2>&1",
        )
    conda_path = _probe(executor, "command -v conda 2>/dev/null", timeout=5)
    conda_available = conda_path["status"] == "PASS" and bool(conda_path["output"].strip())
    conda_version = ({"status": "UNAVAILABLE", "output": ""} if not conda_available else
                     _run_with_exit(
                         executor,
                         f"timeout {_REMOTE_HEALTH_TIMEOUT_S}s conda --version 2>&1",
                     ))

    configured_env = os.path.basename(str(getattr(cfg, "conda_env", "") or "").rstrip("/")) or None
    env_status = "NOT_CONFIGURED" if configured_env is None else "UNKNOWN"
    if configured_env and conda_available:
        envs = _run_with_exit(
            executor,
            f"timeout {_REMOTE_HEALTH_TIMEOUT_S}s conda env list --json 2>/dev/null",
        )
        if envs["status"] == "PASS":
            try:
                paths = json.loads(envs["output"]).get("envs", [])
                env_status = ("PRESENT" if any(
                    os.path.basename(str(path).rstrip("/")) == configured_env for path in paths
                ) else "ABSENT")
            except (TypeError, ValueError, json.JSONDecodeError):
                env_status = "UNKNOWN"

    python_status = "AVAILABLE" if py["status"] == "PASS" and py["output"].strip() else "UNKNOWN"
    configured_python_status = ("AVAILABLE" if configured_python["status"] == "PASS" and
                                configured_python["output"].strip() else "UNKNOWN")
    conda_status = ("AVAILABLE" if conda_version.get("status") == "PASS" and
                    conda_version.get("output", "").strip() else
                    ("UNAVAILABLE" if not conda_available else "UNKNOWN"))
    if configured_python_status != "AVAILABLE":
        overall = "BLOCKED"
    elif configured_env is not None and not (
        conda_status == "AVAILABLE" and env_status == "PRESENT"
    ):
        overall = "BLOCKED" if env_status in {"ABSENT", "NOT_CONFIGURED"} else "DEGRADED"
    else:
        overall = "PASS"
    return {
        "status": overall,
        "python3": {"status": python_status, "version": py.get("output", "").strip() or None},
        "configured_python": {
            "status": configured_python_status,
            "name": configured_python_name,
            "version": configured_python.get("output", "").strip() or None,
        },
        "conda": {
            "status": conda_status,
            "version": conda_version.get("output", "").strip() or None,
            "configured_env": configured_env,
            "configured_env_status": env_status,
        },
    }


def _collect_scheduler(executor, cfg=None) -> dict:
    tmux = _run_with_exit(executor, f"timeout {_REMOTE_HEALTH_TIMEOUT_S}s tmux -V 2>&1")
    sinfo_path = _probe(executor, "command -v sinfo 2>/dev/null", timeout=5)
    slurm_installed = sinfo_path["status"] == "PASS" and bool(sinfo_path["output"].strip())
    if slurm_installed:
        slurm = _run_with_exit(
            executor,
            f"timeout {_REMOTE_HEALTH_TIMEOUT_S}s sinfo --noheader "
            "--format='%P|%a|%l|%D' 2>&1",
        )
        slurm_status = "HEALTHY" if slurm["status"] == "PASS" else "UNUSABLE"
        slurm_summary = (slurm.get("output", "").splitlines()[:20]
                         if slurm_status == "HEALTHY" else [])
    else:
        slurm_status = "NOT_INSTALLED" if sinfo_path["status"] == "PASS" else "UNKNOWN"
        slurm_summary = []

    configured = os.path.basename(str(getattr(cfg, "scheduler", "") or "").rstrip("/")) or None
    tmux_status = "HEALTHY" if tmux["status"] == "PASS" and tmux["output"].strip() else "UNKNOWN"
    configured_low = (configured or "").lower()
    if configured_low in {"slurm", "srun", "sinfo", "sbatch", "squeue"}:
        overall = "PASS" if slurm_status == "HEALTHY" else "BLOCKED"
    elif configured and "tmux" in configured_low:
        overall = "PASS" if tmux_status == "HEALTHY" else "BLOCKED"
    elif slurm_status == "UNUSABLE":
        # Do not silently treat a broken Slurm client as healthy merely because tmux exists too.
        overall = "DEGRADED" if tmux_status == "HEALTHY" else "BLOCKED"
    else:
        overall = "PASS" if tmux_status == "HEALTHY" else "UNKNOWN"
    return {
        "status": overall,
        "configured_scheduler": configured,
        "tmux": {"status": tmux_status, "version": tmux.get("output", "").strip() or None},
        "slurm": {"status": slurm_status, "partitions": slurm_summary},
    }


def _workload_summary(sessions: List[str], runs, gpu_processes: List[dict],
                      process_visibility: str, run_visibility: str,
                      server_user: Optional[str]) -> dict:
    run_pids = {int(run.python_pid) for run in runs if run.python_pid and str(run.python_pid).isdigit()}
    for process in gpu_processes:
        matched = process["pid"] in run_pids
        process["matches_monitored_run"] = matched
        process["workload_class"] = ("monitored_project_run" if matched
                                     else "host_other_or_unattributed")
    matched_count = sum(bool(p["matches_monitored_run"]) for p in gpu_processes)
    unmatched_count = len(gpu_processes) - matched_count
    other_owner_count = sum(
        bool(server_user and p.get("owner") and p["owner"] != server_user) for p in gpu_processes
    )

    if process_visibility != "PASS":
        state = "GPU_WORKLOAD_VISIBILITY_UNKNOWN"
    elif run_visibility != "PASS":
        state = ("MONITORED_RUN_VISIBILITY_UNKNOWN_HOST_GPU_BUSY" if gpu_processes
                 else "MONITORED_RUN_VISIBILITY_UNKNOWN_HOST_GPU_IDLE")
    elif not runs and gpu_processes:
        state = "NO_MONITORED_PROJECT_RUNS_HOST_GPU_BUSY"
    elif not runs:
        state = "NO_MONITORED_PROJECT_RUNS_HOST_GPU_IDLE"
    elif not gpu_processes:
        state = "MONITORED_RUNS_WITHOUT_GPU_PROCESS"
    elif unmatched_count:
        state = "MONITORED_PROJECT_RUNS_AND_OTHER_HOST_GPU_WORKLOAD"
    else:
        state = "MONITORED_PROJECT_RUNS_ACTIVE"
    return {
        "state": state,
        "gpu_process_visibility": process_visibility,
        "monitored_run_visibility": run_visibility,
        "tmux_session_count": len(sessions),
        "monitored_run_count": len(runs),
        "gpu_process_count": len(gpu_processes),
        "matched_run_gpu_process_count": matched_count,
        "unattributed_host_gpu_process_count": unmatched_count,
        "other_owner_gpu_process_count": other_owner_count,
        "host_has_gpu_workload": bool(gpu_processes) if process_visibility == "PASS" else None,
        "project_monitor_has_active_runs": bool(runs) if run_visibility == "PASS" else None,
    }


# --------------------------------------------------------------------------- plan / gate / connect

def _planned_commands(workdir: str = "$RAT_REMOTE_WORKDIR",
                      python_cmd: str = "$RAT_REMOTE_PYTHON") -> List[str]:
    commands = [
        "hostname",
        "date -u +%Y-%m-%dT%H:%M:%SZ",
        "id -un",
        "uname -sr",
        "tmux ls",
        _with_exit_marker(GPU_QUERY),
        _with_exit_marker(GPU_PROCESS_QUERY),
        PS_GPU_PROCESS_QUERY,
        f"df -B1 -P -- {workdir} | tail -1",
        f"df -Pi -P -- {workdir} | tail -1",
        _with_exit_marker(f"timeout {_REMOTE_HEALTH_TIMEOUT_S}s python3 --version 2>&1"),
    ]
    if python_cmd != "python3":
        rendered_python = python_cmd if python_cmd.startswith("$") else shlex.quote(python_cmd)
        commands.append(_with_exit_marker(
            f"timeout {_REMOTE_HEALTH_TIMEOUT_S}s {rendered_python} --version 2>&1"
        ) + "  # configured execution Python")
    commands += [
        "command -v conda 2>/dev/null",
        _with_exit_marker(f"timeout {_REMOTE_HEALTH_TIMEOUT_S}s conda --version 2>&1")
        + "  # conditional",
        _with_exit_marker(f"timeout {_REMOTE_HEALTH_TIMEOUT_S}s conda env list --json 2>/dev/null")
        + "  # conditional",
        _with_exit_marker(f"timeout {_REMOTE_HEALTH_TIMEOUT_S}s tmux -V 2>&1"),
        "command -v sinfo 2>/dev/null",
        _with_exit_marker(
            f"timeout {_REMOTE_HEALTH_TIMEOUT_S}s sinfo --noheader "
            "--format='%P|%a|%l|%D' 2>&1"
        ) + "  # conditional; output retained to 20 lines",
        "# per training session (read-only, via train_progress): tmux list-panes / ps / nvidia-smi / "
        "tail log",
    ]
    return commands


def plan(env_path: str = "research_agent_teams/.env", *,
         env_refs: Optional[Mapping[str, str]] = None) -> dict:
    """Offline preview: redacted server summary + the read-only commands server-query WOULD run.
    No connection is opened. This is the safe default the director reviews before authorizing."""
    try:
        cfg = ec.load_config(env_path, env_refs=env_refs)
        server = ec.redacted_summary(cfg)
        workdir = cfg.workdir or "$RAT_REMOTE_WORKDIR"
        python_cmd = cfg.python or "$RAT_REMOTE_PYTHON"
    except Exception as e:                       # .env not wired / no host -> still show the plan
        server = {"status": f"offline ({type(e).__name__}) — set RAT_SERVER_HOST in .env to enable"}
        workdir = "$RAT_REMOTE_WORKDIR"
        python_cmd = "$RAT_REMOTE_PYTHON"
    return {
        "mode": "plan",
        "server": server,
        "read_only_commands": _planned_commands(workdir, python_cmd),
        "connection": "NOT CONNECTED (plan only).",
        "live_gate": (f"set {AUTH_ENV}=1 (director) to allow a READ-ONLY live status check; "
                      "the model must not self-authorize."),
    }


def is_authorized() -> bool:
    """True only if the director enabled live read-only queries via the environment. Model never sets it."""
    return bool(os.environ.get(AUTH_ENV, "").strip())


def connect(env_path: str = "research_agent_teams/.env", *,
            env_refs: Optional[Mapping[str, str]] = None):
    """Open a LIVE read-only SSH connection — refused unless RAT_SERVER_QUERY_AUTHORIZED is set.
    Returns (ReadOnlyExecutor, ServerConfig). paramiko is imported lazily here only."""
    if not is_authorized():
        raise ServerQueryRefused(
            f"LIVE server query refused. The director must set {AUTH_ENV}=1 to allow a READ-ONLY status "
            "check over SSH to the shared lab GPU server (CLAUDE.md §6 + shared-machine etiquette). The "
            "model must NOT self-authorize. Run `plan` to preview the read-only commands offline.")
    cfg = ec.load_config(env_path, env_refs=env_refs)
    if not (cfg.has_password or cfg.has_ssh_key):
        raise RuntimeError("no auth in .env for the selected server resource.")
    import paramiko  # lazy: only a live query needs it

    client = paramiko.SSHClient()
    ex_runner._harden_host_key_verification(client, cfg)   # reuse the MITM guard (reject unknown host)
    ex_runner._connect_verified_transport(client, cfg)
    return ReadOnlyExecutor(client), cfg


# --------------------------------------------------------------------------- live status

def live_status(*, executor=None, cfg=None, env_path: str = "research_agent_teams/.env",
                project: Optional[str] = None, run_id: Optional[str] = None,
                resource_alias: str = "primary_gpu", exclude: Optional[set] = None,
                resolver=None) -> dict:
    """LIVE read-only status. Gated by RAT_SERVER_QUERY_AUTHORIZED unless an `executor` is injected
    (tests). When project+run_id are given, leases `query_status` on the project's `primary_gpu`
    binding (ResourceResolver) — leaving a redacted audit line."""
    lease_info = None
    resolved = None
    if project and run_id:
        from research_agent_teams.tools.resource_resolver import ResourceResolver
        resolver = resolver or ResourceResolver()
        resolved = resolver.resolve(project=project, run_id=run_id,
                                    alias_or_resource=resource_alias,
                                    capability="query_status", skill="server-query")
        lease_info = {"lease_id": resolved.lease_id, "resource_id": resolved.resource_id,
                      "requires_human_approval": resolved.requires_human_approval}

    own = executor is None
    if own:
        executor, cfg = connect(
            env_path, env_refs=(resolved.env_refs if resolved is not None else None))
    elif not isinstance(executor, ReadOnlyExecutor):
        executor = ReadOnlyExecutor(executor)    # force every injected client through the guard too

    try:
        identity = _collect_identity(executor)
        sessions = parse_tmux_sessions(_run(executor, "tmux ls"))
        gpu_inventory = _run_with_exit(executor, GPU_QUERY)
        gpus = (parse_gpu_table(gpu_inventory["output"])
                if gpu_inventory["status"] == "PASS" else [])
        gpu_processes, gpu_process_visibility = _collect_gpu_processes(executor, gpus)
        workdir = (cfg.workdir if cfg else "") or "/"
        storage = _collect_storage(executor, workdir)
        runtime = _collect_runtime(executor, cfg)
        scheduler = _collect_scheduler(executor, cfg)
        try:
            runs = tp.summarize(executor, sessions, exclude=exclude)
            run_visibility = "PASS"
        except Exception:
            # Host-level process inventory remains useful, but project-run absence is now UNKNOWN.
            runs = []
            run_visibility = "UNKNOWN"
        workload = _workload_summary(
            sessions, runs, gpu_processes, gpu_process_visibility, run_visibility,
            getattr(cfg, "user", None) if cfg else None,
        )
        return {
            "mode": "live",
            "server": ec.redacted_summary(cfg) if cfg else {},
            "identity": identity,
            "sessions": sessions,
            "gpus": gpus,
            "gpu_inventory_status": gpu_inventory["status"],
            "gpu_processes": gpu_processes,
            "workload": workload,
            "storage": storage,
            # Compatibility for existing readers; this is now the exact-byte df row, not df -h.
            "disk": storage.get("bytes", {}).get("raw", ""),
            "runtime": runtime,
            "scheduler": scheduler,
            "runs": runs,
            "lease": lease_info,
        }
    finally:
        if own:
            executor.close()


def query(*, env_path: str = "research_agent_teams/.env", project: Optional[str] = None,
          run_id: Optional[str] = None, resource_alias: str = "primary_gpu") -> dict:
    """Convenience entry: live status when the director authorized it, else the offline plan."""
    if is_authorized():
        return live_status(env_path=env_path, project=project, run_id=run_id,
                           resource_alias=resource_alias)
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
    identity = status.get("identity", {})
    lines += ["", "## Host identity",
              f"  host={identity.get('hostname') or '?'} utc={identity.get('utc_time') or '?'} "
              f"user={identity.get('user') or '?'} kernel={identity.get('kernel') or '?'} "
              f"status={identity.get('status', 'UNKNOWN')}"]
    lines += ["", "## tmux sessions"]
    lines += [f"  - {s}" for s in status["sessions"]] or ["  (none)"]
    lines += ["", "## GPUs"]
    if status["gpus"]:
        for g in status["gpus"]:
            name = f" {g.get('name')}" if g.get("name") else ""
            lines.append(f"  GPU{g['idx']}{name}: util={g['util']}% "
                         f"mem={g['mem_used']}/{g['mem_total']}MiB temp={g['temp']}°C "
                         f"driver={g.get('driver_version') or '?'}")
    else:
        lines.append("  (nvidia-smi returned no GPUs)")
    if status.get("gpu_inventory_status", "UNKNOWN") != "PASS":
        lines.append("  [!] GPU inventory visibility UNKNOWN")

    workload = status.get("workload", {})
    lines += ["", "## GPU workloads", f"  state: {workload.get('state', 'UNKNOWN')}"]
    lines.append(
        f"  counts: tmux_sessions={workload.get('tmux_session_count', '?')} "
        f"monitored_runs={workload.get('monitored_run_count', '?')} "
        f"gpu_processes={workload.get('gpu_process_count', '?')} "
        f"unattributed={workload.get('unattributed_host_gpu_process_count', '?')} "
        f"other_owner={workload.get('other_owner_gpu_process_count', '?')}"
    )
    visibility = workload.get("gpu_process_visibility", "UNKNOWN")
    if visibility != "PASS":
        lines.append("  [!] GPU process visibility UNKNOWN; do not infer that the host is idle")
    elif status.get("gpu_processes"):
        for process in status["gpu_processes"]:
            gpu = f"GPU{process['gpu_idx']}" if process.get("gpu_idx") is not None else process["gpu_uuid"]
            lines.append(
                f"  - {gpu} pid={process['pid']} owner={process.get('owner') or '?'} "
                f"elapsed={process.get('elapsed') or '?'} comm={process.get('comm') or '?'} "
                f"mem={process.get('used_memory_mb')}MiB class={process['workload_class']}"
            )
    else:
        lines.append("  (no compute-app process reported; visibility PASS)")
    if workload.get("monitored_run_visibility", "UNKNOWN") != "PASS":
        lines.append("  [!] monitored project-run visibility UNKNOWN; runs=0 is not evidence of absence")

    storage = status.get("storage", {})
    lines += ["", "## Storage"]
    for label in ("bytes", "inodes"):
        item = storage.get(label, {})
        if item.get("status") == "PASS":
            lines.append(f"  {label}: {item.get('used_percent')} used; "
                         f"available={item.get('available_' + label)}; mount={item.get('mountpoint')}")
        else:
            lines.append(f"  {label}: UNKNOWN")

    runtime = status.get("runtime", {})
    scheduler = status.get("scheduler", {})
    configured_python = runtime.get("configured_python", {})
    conda = runtime.get("conda", {})
    lines += ["", "## Runtime / scheduler",
              f"  runtime: {runtime.get('status', 'UNKNOWN')} "
              f"python3={runtime.get('python3', {}).get('version') or '?'} "
              f"configured_python={configured_python.get('name') or '?'}:"
              f"{configured_python.get('status', 'UNKNOWN')} "
              f"conda={conda.get('status', 'UNKNOWN')} "
              f"env={conda.get('configured_env') or '(not configured)'}:"
              f"{conda.get('configured_env_status', 'UNKNOWN')}",
              f"  scheduler: {scheduler.get('status', 'UNKNOWN')} "
              f"tmux={scheduler.get('tmux', {}).get('version') or '?'} "
              f"slurm={scheduler.get('slurm', {}).get('status', 'UNKNOWN')}"]
    lines.append(tp.format_report(status["runs"]))
    return "\n".join(lines)
