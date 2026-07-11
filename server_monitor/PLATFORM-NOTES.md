# Lab GPU server — platform notes (read this before any EXECUTE on it)

> Vendored, **credential-free** summary of the Honor-degree server runbook (the original guide holds
> credentials and is NOT copied here). These are the footguns that bite real training/inference runs on
> this specific server. server-query is read-only and unaffected, but the EXECUTE layer (and any
> future remote scripts) must respect every item below. Source server creds live ONLY in `.env`.

## Hardware / OS
- Ubuntu 18.04, glibc 2.27 — old; some prebuilt wheels (newer manylinux) won't load. Prefer the
  project conda envs.
- 2× NVIDIA RTX A6000 (48 GB each), CUDA 12.1.
- Scheduler = a `honor_cron` **tmux** session (NOT Slurm/PBS). Jobs run under tmux/nohup.
- Multiple project conda environments exist (one per model family). Activate the right one per run.

## The 6 footguns (each has burned a real run)
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

## Implications for server-query (read-only)
- None of the above can be triggered by server-query — it only runs read commands (`tmux ls`,
  `nvidia-smi`, `ps`, `tail`, `df`). But when reading logs it strips `\r` (tqdm) remotely, which is the
  same CRLF reality as footgun #1.
- Remote training logs are huge and tqdm-laden; the monitor fetches only the summary lines
  (`tr "\r" "\n" | grep …`) so the transfer stays small.
