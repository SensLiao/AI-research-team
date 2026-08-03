# Lab GPU servers — platform notes (read this before any EXECUTE on them)

> Vendored, **credential-free** summary of the Honor-degree server runbook (the original guide holds
> credentials and is NOT copied here). These are the footguns that bite real training/inference runs on
> these registered resources. server-query is read-only and unaffected, but the EXECUTE layer (and any
> future remote scripts) must respect every item below. Source server creds live ONLY in `.env`.

## Registered resources and status provenance

Hardware registration is not a live availability claim. The machine has two canonical resource aliases:

| Alias | Resource ID | Registered lower-level hardware | Status boundary |
| --- | --- | --- | --- |
| `primary_gpu` | `server.honor.gpu` | 2× NVIDIA RTX A6000, 48 GiB each | Primary execution resource; current workload and readiness still require a fresh live snapshot and gates |
| `secondary_gpu` | `server.usyd.bdav_z390_3090` | 1× NVIDIA GeForce RTX 3090 + 1× NVIDIA GeForce GTX 1080 Ti | **director reported resolved; live re-verification pending** |

Until a fresh live query or a validated job/scheduler receipt exists, `current_task=UNKNOWN` for both
resources. Registered hardware may be reused as inventory metadata; current task, busy/idle state, storage,
environment, scheduler health and execution readiness may not be inherited from an earlier report.

The normative machine-readable checklist is
`research_agent_teams/server_monitor/query_contract.json`
(contract `server-query-contract/v1`). Human notes and query implementations must not weaken its freshness,
UNKNOWN or operation-separation rules.

## Primary A6000 platform / OS
- Ubuntu 18.04, glibc 2.27 — old; some prebuilt wheels (newer manylinux) won't load. Prefer the
  project conda envs.
- 2× NVIDIA RTX A6000 (48 GB each), CUDA 12.1.
- Scheduler = a `honor_cron` **tmux** session (NOT Slurm/PBS). Jobs run under tmux/nohup.
- Multiple project conda environments exist (one per model family). Activate the right one per run.

## The 7 footguns (each has burned or can invalidate a real run)
1. **CRLF line endings.** Scripts uploaded from Windows get `\r\n`; bash then fails with cryptic
   `\r`-in-command errors. Normalize to LF before/after upload (`sed -i 's/\r$//' script.sh`), or write
   with LF newlines (the execute layer's `_put_text` already writes LF).
2. **`python` is Python 2.** Always call `python3` (and the env's python) explicitly; bare `python`
   silently runs the wrong interpreter.
3. **Root partition is ~100 % full.** Writing to default cache dirs fills `/` and crashes jobs.
   Redirect ALL caches to the data volume before running:
   `TMPDIR`, `PIP_CACHE_DIR`, `XDG_CACHE_HOME`, `HF_HOME` → a path under `$RAT_REMOTE_WORKDIR`.
4. **paramiko + `set -u` + `conda activate`.** Non-interactive SSH with `set -u` blows up inside
   `conda activate` (unbound vars). Wrap activation: `set +u; conda activate <env>; set -u`.
5. **SFTP is whole-file replace, not in-place patch.** Editing a remote file means re-uploading the
   whole file (the execute layer does this). Don't assume a partial/streamed patch landed.
6. **`BatchMode=yes` is not usable** on this host. Auth is interactive-password style (paramiko handles
   it from `.env`); don't rely on OpenSSH BatchMode for automation.
7. **Local DNS can be overridden.** Keep `RAT_SERVER_HOST` as the canonical SSH identity and put the
   literal TCP endpoint in `RAT_SERVER_CONNECT_HOST`. The runner opens a socket to the IP but passes the
   canonical hostname to Paramiko, so the pinned canonical `known_hosts` entry is still enforced. Do not
   solve DNS interception by changing the identity to an IP or enabling trust-on-first-use.

## Implications for server-query (read-only)
- None of the above can be triggered by server-query — it only runs read commands (`tmux ls`,
  `nvidia-smi`, `ps`, `tail`, `df`). But when reading logs it strips `\r` (tqdm) remotely, which is the
  same CRLF reality as footgun #1.
- Remote training logs are huge and tqdm-laden; the monitor fetches only the summary lines
  (`tr "\r" "\n" | grep …`) so the transfer stays small.

## Dual-server query runbook — `petct-textual-intent`

Do not invent hostname-specific aliases in experiment code. The resolver selects the resource from the
project binding and provides environment-variable **names** only; the connector reads values at connection
time. Candidate discovery is available through `ResourceResolver.candidates(...)`: both aliases must appear
for `query_status`. Discovery and a successful query never grant `submit_job`.

### Exact CLI

Offline plan (no SSH):

```powershell
python -m research_agent_teams.server_monitor --project petct-textual-intent --run-id <audit-id> --resource primary_gpu --json
python -m research_agent_teams.server_monitor --project petct-textual-intent --run-id <audit-id> --resource secondary_gpu --json
```

Fresh live read-only status, only while the director's `RAT_SERVER_QUERY_AUTHORIZED` gate is already active:

```powershell
python -m research_agent_teams.server_monitor --live --project petct-textual-intent --run-id <audit-id> --resource primary_gpu --json
python -m research_agent_teams.server_monitor --live --project petct-textual-intent --run-id <audit-id> --resource secondary_gpu --json
```

The model/operator must never set the authorization flag on its own. `--resource` changes the resolver alias;
it does not copy credentials between resources. The JSON response is redacted and contains the leased resource
ID, host identity/time, GPU inventory, host-wide compute processes, workload attribution, exact-byte and inode
storage headroom, runtime/Conda health, scheduler health, tmux sessions and detected project runs. `runs` is
collapsed to a count in CLI JSON; `gpu_processes` remains an explicit list because otherwise a host workload
could be hidden by `runs=0`.

An offline plan proves only which read commands would run. A live response is a point-in-time snapshot, not
permission to execute. If any required probe is missing, failed, timed out or stale, the affected field and
category are `UNKNOWN`. In particular, `runs=0`, an old dashboard, a director report or registered hardware
must never be converted into a current “no task”, “idle” or “execution ready” claim.

### Standard workload output: what is queried and how to read it

The standard call intentionally uses two independent evidence layers:

1. **Monitored project layer:** `tmux ls` plus the existing per-session, read-only progress parser. This can
   identify a known project run, its epoch/sweep progress and its matched Python PID.
2. **Host GPU layer:** `nvidia-smi --query-compute-apps=pid,gpu_uuid,used_memory ...` enumerates every visible
   compute application, even if it has no tmux session. Each numeric PID is then inspected with only
   `ps -o user=,pid=,etime=,comm= -p <PID>`.

The host inventory never requests `args` or a full `cmd`; JSON and Markdown therefore expose only owner, PID,
elapsed time, executable name, GPU UUID/index and process memory. A process is labelled
`monitored_project_run` only when its PID matches a detected project run. Everything else is conservatively
`host_other_or_unattributed`; it is not silently claimed to belong to this project.

`workload.state` has explicit fail-closed meanings:

| State | Meaning |
| --- | --- |
| `MONITORED_PROJECT_RUNS_ACTIVE` | Detected project run PIDs account for all visible GPU compute processes. |
| `MONITORED_PROJECT_RUNS_AND_OTHER_HOST_GPU_WORKLOAD` | Project run(s) and unmatched host workload coexist. |
| `MONITORED_RUNS_WITHOUT_GPU_PROCESS` | A monitored run exists but no compute-app PID is visible; inspect for startup/stall. |
| `NO_MONITORED_PROJECT_RUNS_HOST_GPU_BUSY` | Project/tmux run count is zero, but the host GPU is **not idle**. |
| `NO_MONITORED_PROJECT_RUNS_HOST_GPU_IDLE` | No monitored run and no compute process, with a successful process probe. |
| `GPU_WORKLOAD_VISIBILITY_UNKNOWN` | Compute-process query failed/timed out; never interpret this as idle. |
| `MONITORED_RUN_VISIBILITY_UNKNOWN_HOST_GPU_BUSY` | Host GPU work is visible, but project-session inspection failed; `runs=0` is not absence evidence. |
| `MONITORED_RUN_VISIBILITY_UNKNOWN_HOST_GPU_IDLE` | No GPU process is visible, but project-session inspection failed; do not claim no project run. |

The remaining fixed probes are also read-only and bounded:

```text
hostname
date -u +%Y-%m-%dT%H:%M:%SZ
id -un
uname -sr
nvidia-smi --query-gpu=index,uuid,name,utilization.gpu,memory.used,memory.total,temperature.gpu,driver_version --format=csv,noheader,nounits
nvidia-smi --query-compute-apps=pid,gpu_uuid,used_memory --format=csv,noheader,nounits
ps -o user=,pid=,etime=,comm= -p <GPU_PID>
df -B1 -P -- <workdir> | tail -1
df -Pi -P -- <workdir> | tail -1
timeout 5s python3 --version
timeout 5s <configured-execution-python> --version
command -v conda; timeout 5s conda --version; timeout 5s conda env list --json
timeout 5s tmux -V
command -v sinfo; timeout 5s sinfo --noheader --format='%P|%a|%l|%D'
```

The configured execution Python is checked separately from system `python3`; system Python being present does
not prove that the configured project interpreter works. Conda and Slurm detail probes run only when their
commands are present. A Slurm client that exists but returns
a non-zero/timeout health probe is `UNUSABLE`; a missing or malformed exit marker is `UNKNOWN`. Likewise, disk
bytes and inode probes must both pass before `storage.status=PASS`. These states are observation evidence only:
they never grant `submit_job`, choose a GPU, kill a process or mutate the server.

### Fixed read-only what/how checklist for every query

Every live response must include all eight categories below. Omission is not success: a missing, failed,
timed-out or stale probe produces `UNKNOWN` for that category. The complete field-level contract lives in
`server_monitor/query_contract.json`.

This checklist is an acceptance contract, not synthetic evidence. If the installed monitor has not yet wired
a category, the response must say `UNKNOWN (probe not implemented)` and disclose the gap; an operator must not
fill it from an older status, memory or an unrelated receipt.

1. **Identity**
   - **What:** resource alias/ID, hostname, UTC observation time, remote user, OS/kernel.
   - **How:** resolve the project binding, then bounded `hostname`, `date -u`, `id -un` and `uname -sr`.
2. **GPU**
   - **What:** index/UUID/model/memory/utilization/temperature plus every visible compute PID, owner,
     elapsed time and executable `comm`.
   - **How:** bounded `nvidia-smi` inventory and compute-app queries, then
     `ps -o user=,pid=,etime=,comm=` per numeric PID; never request full command arguments.
3. **tmux/process**
   - **What:** sessions, scheduler session, pane/child PIDs, bounded progress, and monitored versus
     unattributed host workload.
   - **How:** `tmux ls`, bounded `tmux list-panes`/child-process inspection, project-owned log summaries,
     and a PID join against the same GPU snapshot.
4. **Project/run/campaign**
   - **What:** requested IDs, canonical run roots, current stage/task, and live watcher/training/inference/
     evaluation membership.
   - **How:** bind the query to explicit IDs and cross-check canonical project status with the live
     process/session snapshot. Without live or validated receipt evidence, current stage/task is `UNKNOWN`.
5. **Receipts/gates**
   - **What:** canonical ready/execution/completion receipts, gate decisions, `FAILED` markers, timestamps,
     identities and SHA-256.
   - **How:** discover only canonical project-owned paths, exclude temporary/test fixtures, hash read-only,
     and verify that each receipt belongs to the requested run and campaign.
6. **Storage**
   - **What:** work-volume byte and inode headroom plus project workdir identity.
   - **How:** `df -B1 -P` and `df -Pi -P` on the configured workdir plus read-only metadata inspection.
     A write probe is never part of server-query.
7. **Environment marker**
   - **What:** system Python, configured execution Python, Conda/configured environment, and the configured
     project environment or bundle marker.
   - **How:** bounded version/env-list probes and a read-only hash of the configured project marker when
     one exists. System Python alone is not project-environment evidence.
8. **Failure/duplicate risk**
   - **What:** failed/interrupted/stale markers, duplicate live or receipted run/campaign identity,
     completed prerequisites that must not be repeated, and duplicate watcher/training/evaluation risk.
   - **How:** cross-check failure/completion markers, live processes and validated receipts. Conflicts or
     unavailable evidence remain `UNKNOWN`/blocked; they are never resolved by copying an older status.

For the current PET/CT campaign, always distinguish the committed scientific input from its failed wrapper:

- `nnunet/manifests/OOF_READY.json` is the canonical OOF gate and is independently hash-checked.
- `route_a/runs/PETCT-M0-OOF-METRICS-20260731T095340CST/state/FAILED` records the later deployed-script
  incompatibility. It does not invalidate OOF, and it does not authorize rerunning OOF.

### Secondary-server status boundary

The only admissible present-tense status before a new live query is:

> **director reported resolved; live re-verification pending**

That report is not a live snapshot and grants neither idle, busy nor execution-ready status. Current GPU
processes/tasks, project/run/campaign membership, storage, environment, scheduler, receipts and gates are all
`UNKNOWN` until re-observed. Do not inherit any task or blocker from an older snapshot, and do not invent a
replacement current task.

### `query_status` is not `submit_job`

`server-query` implements read-only `query_status` only. It may resolve a resource and lease the
`query_status` capability, read bounded status/receipt data and produce a timestamped redacted snapshot. It
must never submit/cancel work, signal a process, write/delete/transfer a remote file, install an environment,
change permissions or treat a query lease as execution authorization.

`submit_job` is a separate state-changing execute path. It requires an exact director-approved
project/run/campaign and resource binding, the durable recovery record required by the director safety rule,
and its own human gate. A PASS query, an idle GPU, a historical success or a director report alone never
authorizes submission.
