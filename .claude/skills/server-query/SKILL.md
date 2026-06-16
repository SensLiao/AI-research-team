---
name: server-query
description: >
  Query the director's lab GPU server for a READ-ONLY status snapshot — tmux sessions, nvidia-smi
  (GPU util / memory / temperature), running training processes, per-session training progress
  (epochs / best val_dice / ETA / anomalies), and disk. Ports the Honor-degree `server-status` skill
  into System M: connect via SSH (password auth, paramiko) and READ — never write, never rm/kill/mv/
  sudo, never SFTP. Credentials come from the gitignored `.env` through the resource pool; they are
  read at connect time only and never echoed. Live SSH is director-gated (RAT_SERVER_QUERY_AUTHORIZED);
  the default is an offline `plan` that shows exactly what would run. Trigger phrases: 查服务器 /
  查看服务器状态 / 服务器任务 / GPU 状态 / 看下 run 进度 / 训练到第几个 epoch / server status /
  GPU usage / job status / training progress / check the server / 看服务器.
model: sonnet
---

# server-query — read-only GPU-server monitor

This skill answers "what's happening on the lab server right now?" without ever changing anything on
it. It is the System-M re-implementation of the Honor-degree `server-status` skill, wired into the
resource pool and the `.env` secret model (CLAUDE.md §6). **It is part of System M (the machine), not
the database.**

## What it reports (read-only)
- live tmux sessions + the scheduler session
- per-GPU utilization / memory / temperature (`nvidia-smi`)
- each training session's progress: latest epoch, loss/dice trajectory, best `val_dice`, ETA, and
  anomalies (val-dice stagnation, loss spikes, GPU hot ≥85 °C, GPU idle with a live python child)
- disk headroom on the work volume

## How to run

**Offline plan (always safe, default — no connection):**
```bash
python -m research_agent_teams.server_monitor
```
Prints the redacted server summary (host / user / auth-MODE — never the password) and the exact
read-only commands it WOULD run.

**Live read-only status (director-gated):**
```bash
# the DIRECTOR enables a live read-only check for this session:
export RAT_SERVER_QUERY_AUTHORIZED=1          # PowerShell: $env:RAT_SERVER_QUERY_AUTHORIZED = "1"
python -m research_agent_teams.server_monitor --live
```
Optionally tie the check to a project (leaves a redacted audit line + a lease on the project's
`primary_gpu` binding):
```bash
python -m research_agent_teams.server_monitor --live --project my-project --run-id <run_id>
```
`--json` emits machine-readable output (training runs collapsed to a count).

## Hard rules (do NOT cross)
- **Read-only.** Every command is forced through `ReadOnlyExecutor`, which rejects any mutating verb
  (`rm`/`kill`/`pkill`/`mv`/`cp`/`dd`/`sudo`/`chmod`/`tee`/`scp`/`rsync`/…), any real-file output
  redirect, and any SFTP/file transfer. `2>/dev/null` / `2>&1` are allowed (stream redirects).
- **Credentials never appear** in chat / logs / artifacts. They live only in `research_agent_teams/.env`
  (`RAT_SERVER_HOST` / `RAT_SERVER_USER` / `RAT_SERVER_PASSWORD`), are read at connect time, and the
  server summary is redacted (host / user / auth-MODE only). The skill NEVER hardcodes a credential.
- **Live SSH is gated.** No connection happens unless the director set `RAT_SERVER_QUERY_AUTHORIZED`.
  The model must NOT self-authorize. Until then the skill is `tested-not-operated` — `plan` works,
  `--live` is refused with an explanatory message.
- **Host-key verified** (no trust-on-first-use): reuses the execute layer's MITM guard
  (`RejectPolicy` + system/`RAT_SERVER_KNOWN_HOSTS`). First connect to a new server needs the key
  pinned out-of-band (`ssh-keyscan`), exactly like the execute layer.
- **System M only.** server-query never reads or writes the vault (System D). It is a workshop tool.

## Implementation
- `research_agent_teams/server_monitor/monitor.py` — `plan` / `is_authorized` / `connect` /
  `live_status` / `query` / `format_status` + the read-only guard.
- `research_agent_teams/server_monitor/train_progress.py` — the vendored, generic, read-only log/tmux/
  nvidia-smi parser (epoch-regex registry; add a script by adding one regex).
- Platform footguns for this specific server (CRLF, python3, full root partition, conda `set -u`, …):
  `research_agent_teams/server_monitor/PLATFORM-NOTES.md`.
- Resource binding: `projects/<slug>/resource_bindings.yaml` → alias `primary_gpu`
  (`server.honor.gpu`, capabilities `query_status` / `pull_logs`).
