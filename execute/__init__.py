"""GPU EXECUTE layer — the gated runner that takes a design-stage script and runs it on the
director's lab GPU server (the now-wired research_agent_teams/.env).

HARD SAFETY MODEL (CLAUDE.md §6 + shared-University-server etiquette):
  - DEFAULT is `plan` — build + show the EXACT remote job (offline, NO connection). Always safe.
  - LIVE connection / submit is **director-gated**: refused unless `RAT_EXECUTE_AUTHORIZED == <run_id>`
    is set in the environment by the DIRECTOR, who is present. The model must NEVER self-authorize,
    never set that variable, never run a live submit on a shared machine unsupervised.
  - The job builder encodes the lab runbook's footguns/etiquette (python3 not python; conda activate
    wrapped in set +u/-u; caches redirected off the root partition; LF line endings; tmux for long
    jobs; work only inside the workdir). See job.py.

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
