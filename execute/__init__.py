"""GPU EXECUTE layer — the gated runner that takes a design-stage script and runs it on the
director's lab GPU server (the now-wired research_agent_teams/.env).

HARD SAFETY MODEL (CLAUDE.md §6 + shared-University-server etiquette):
  - DEFAULT is `plan` — build + show the EXACT remote job (offline, NO connection). Always safe.
  - LIVE connection / submit is **director-gated**: the primary assistant first shows the exact remote
    write/command plan and asks the DIRECTOR in chat. A fresh top-level confirmation is carried through
    a library-only parameter and recorded in the receipt; the director does not set PowerShell state.
    The ordinary CLI retains `RAT_EXECUTE_AUTHORIZED == <run_id>` only as a legacy unattended capability
    and exposes no flag for impersonating the chat confirmation. Workers/modes never self-authorize.
  - The job builder encodes the lab runbook's footguns/etiquette (python3 not python; conda activate
    wrapped in set +u/-u; caches redirected off the root partition; LF line endings; tmux for long
    jobs; work only inside the workdir). See job.py.
  - When local DNS is overridden, `RAT_SERVER_CONNECT_HOST=<literal IP>` controls only the TCP endpoint;
    `RAT_SERVER_HOST` remains the canonical host-key identity. Direct IP never disables RejectPolicy.

`paramiko` is imported lazily (only inside `connect`), so `plan` and the test-suite never need it
nor a live connection. This layer is BUILT + mock-tested; its first LIVE run is director-supervised.
"""
from .config import ServerConfig, load_config, redacted_summary
from .job import JobSpec, build_job_script, remote_run_dir, tmux_submit_command, tmux_status_command
from .runner import LiveConnectionRefused, plan

__all__ = [
    "ServerConfig", "load_config", "redacted_summary",
    "JobSpec", "build_job_script", "remote_run_dir", "tmux_submit_command", "tmux_status_command",
    "LiveConnectionRefused", "plan",
]
