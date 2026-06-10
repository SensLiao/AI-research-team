"""Build the REMOTE job for a GPU run — pure, testable, and encoding the lab runbook's footguns &
etiquette so a 'correct' script does not silently break or violate shared-machine rules. NO connection.

Runbook footguns encoded (from the director's server handoff):
  #1 default `python` is wrong          -> use cfg.python (python3 / the conda env's python)
  #2 root `/` partition fills up         -> redirect TMPDIR/PIP_CACHE_DIR/HF_HOME/XDG_CACHE_HOME onto
                                            the project partition (under the run's own dir)
  #3 Windows-edited `.sh` -> CRLF breaks -> the run.sh is written with LF (build_job_script returns \n-only)
  #4 `conda activate` + `set -u` clash   -> wrap activate in `set +u` / `set -u`
  #5 long jobs die on disconnect         -> launch detached in tmux
Etiquette: work ONLY inside the workdir (assert_in_workdir); the builder never emits sudo / rm -rf /
/ kill of other sessions.
"""
from __future__ import annotations

import re
import shlex
from dataclasses import dataclass
from typing import Optional

# Injection defense: every model-/caller-controllable JobSpec field that flows into a remote shell or
# tmux command is validated at construction (fail-closed). run_id is also a path segment AND a tmux
# session name, so it must carry no dots/colons/metacharacters; gpus is a CUDA_VISIBLE_DEVICES list; the
# script is a relative filename (no '..', no leading '/'). `args` is parsed with shlex (and re-quoted per
# token in build_job_script), so a value like "; rm -rf ~" becomes inert literal argv, never shell syntax.
_RUN_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")
_SCRIPT_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_./-]*$")
_GPUS_RE = re.compile(r"^[0-9]+(,[0-9]+)*$")


@dataclass(frozen=True)
class JobSpec:
    run_id: str
    script: str                 # script filename to run inside the run's remote dir, e.g. "train.py"
    args: str = ""              # extra CLI args appended to the python invocation
    gpus: str = ""              # CUDA_VISIBLE_DEVICES value (e.g. "0"); empty = inherit
    local_script: Optional[str] = None  # local path to upload as `script` (set at submit time)

    def __post_init__(self):
        if not _RUN_ID_RE.match(self.run_id or ""):
            raise ValueError(
                f"unsafe run_id {self.run_id!r}: must match {_RUN_ID_RE.pattern} — no spaces, shell "
                "metacharacters, or path/tmux separators (run_id is a remote path segment AND a tmux name)")
        if (not _SCRIPT_RE.match(self.script or "")) or (".." in self.script) or self.script.startswith("/"):
            raise ValueError(
                f"unsafe script {self.script!r}: must be a relative filename (no '..', no leading '/', "
                "no shell metacharacters)")
        if self.gpus and not _GPUS_RE.match(self.gpus):
            raise ValueError(f"unsafe gpus {self.gpus!r}: digits and commas only (CUDA_VISIBLE_DEVICES list)")
        try:
            shlex.split(self.args or "")
        except ValueError as exc:
            raise ValueError(f"unparseable args {self.args!r} (unbalanced quotes?): {exc}")


def remote_run_dir(cfg, job: JobSpec) -> str:
    """The run's own directory on the server, under the workdir (etiquette: never outside workdir)."""
    return f"{cfg.workdir.rstrip('/')}/{job.run_id}"


def assert_in_workdir(cfg, remote_path: str) -> None:
    """Etiquette guard: refuse any remote path that is not inside the configured workdir."""
    wd = cfg.workdir.rstrip("/")
    if not wd:
        raise ValueError("workdir (RAT_REMOTE_WORKDIR) is unset — cannot bound writes to a safe area")
    norm = remote_path.rstrip("/")
    if not (norm == wd or norm.startswith(wd + "/")):
        raise PermissionError(f"refused: remote path {remote_path!r} is outside the workdir {wd!r}")


def _cache_env_exports(run_dir: str) -> str:
    # footgun #2: keep caches/temp off the small root partition — put them under the run dir.
    return (
        f'export TMPDIR="{run_dir}/.tmp" PIP_CACHE_DIR="{run_dir}/.pipcache" '
        f'HF_HOME="{run_dir}/.hf" XDG_CACHE_HOME="{run_dir}/.xdgcache"\n'
        f'mkdir -p "$TMPDIR" "$PIP_CACHE_DIR" "$HF_HOME" "$XDG_CACHE_HOME"'
    )


def build_job_script(cfg, job: JobSpec) -> str:
    """The bash the server runs inside tmux. Returned with LF-only newlines (footgun #3).

    Encodes: conda activate wrapped in set +u/-u (#4), python3 not python (#1), caches off root (#2),
    cd into the run's own dir, GPU pinning if requested, all stdout/stderr to a per-run log.
    Where conda_sh / conda_env are unset, emits a clearly-marked placeholder for the director to fill.
    """
    rdir = remote_run_dir(cfg, job)
    conda_sh = cfg.conda_sh or "<RAT_REMOTE_CONDA_SH: /path/.../etc/profile.d/conda.sh>"
    conda_env = cfg.conda_env or "<RAT_REMOTE_CONDA_ENV: full-path env for this model family>"
    gpus = f"CUDA_VISIBLE_DEVICES={job.gpus} " if job.gpus else ""
    # args are re-emitted as individually shell-quoted tokens so injection payloads are inert literal argv.
    arg_str = " ".join(shlex.quote(tok) for tok in shlex.split(job.args)) if job.args else ""
    script_q = shlex.quote(job.script)   # validated already; quoted as defense-in-depth (safe names unchanged)
    invocation = f"{gpus}{cfg.python} {script_q}{(' ' + arg_str) if arg_str else ''}".rstrip()
    lines = [
        "#!/usr/bin/env bash",
        "set -e",
        "# --- conda (footgun #4: activate clashes with set -u) ---",
        "set +u",
        f"source {conda_sh}",
        f"conda activate {conda_env}",
        "set -u",
        "# --- caches off the root partition (footgun #2) ---",
        _cache_env_exports(rdir),
        "# --- run inside this run's own dir; log everything ---",
        f'cd "{rdir}"',
        f'{invocation} > "{rdir}/{job.run_id}.log" 2>&1',
    ]
    return "\n".join(lines) + "\n"


def tmux_submit_command(cfg, job: JobSpec) -> str:
    """The single SSH command that launches run.sh detached in tmux (footgun #5: survive disconnect)."""
    rdir = remote_run_dir(cfg, job)
    return f"tmux new-session -d -s rat-{job.run_id} 'bash \"{rdir}/run.sh\"'"


def tmux_status_command(job: JobSpec) -> str:
    """Read the tail of the running tmux pane (non-destructive; never attaches/kills)."""
    return (f"tmux capture-pane -pt rat-{job.run_id} 2>/dev/null | tail -40 "
            f"|| echo '[no tmux session rat-{job.run_id} — job finished or not started]'")
