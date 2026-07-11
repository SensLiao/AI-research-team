"""server_monitor — System M's READ-ONLY GPU-server monitor (the `server-query` capability).

A faithful, parameterized port of the Honor-degree `server-status` skill into the research machine:
connect (paramiko, password auth) to the lab GPU server and READ tmux sessions / nvidia-smi / training
logs — never write, never rm/kill/mv/sudo, never SFTP. Credentials live only in the gitignored
`.env` (referenced through the resource pool) and are read at connect time, never stored or echoed.

- `train_progress` — vendored verbatim from the Honor-degree skill (pure stdlib parser, no creds,
  no hardcoded server paths). It turns remote tmux/log/nvidia-smi output into TrainRun records.
- `monitor` — plan-vs-live entry (mirrors execute/runner): `plan()` offline (always safe),
  `live_status()` gated by `RAT_SERVER_QUERY_AUTHORIZED`, optional ResourceResolver lease + audit.
"""
from research_agent_teams.server_monitor import monitor, train_progress  # noqa: F401

__all__ = ["monitor", "train_progress"]
