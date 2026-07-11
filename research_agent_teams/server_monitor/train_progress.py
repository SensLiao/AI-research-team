#!/usr/bin/env python3
"""
train_progress.py — summarize live training progress from remote tmux sessions.

Given an open paramiko SSHClient and a list of tmux session names, this module:
  1. Resolves each non-scheduler session's bash pid and python command line
  2. Extracts the training log path from the command ("... | tee ... _train.log")
  3. Extracts the CUDA_VISIBLE_DEVICES index
  4. Remote-parses the log (stripping tqdm \r noise) and pulls out:
       - last completed epoch summary (loss, dice, lr, per-epoch seconds)
       - best val_dice + epoch
       - resume marker
       - recent non-tqdm log tail
  5. Cross-references nvidia-smi for GPU util / mem / temp for the same pid
  6. Returns a list of TrainRun records that daily_sync.py can format

Design: generic (not model-specific). The parser tries a small set of tolerant
epoch regexes in sequence; adding a new training script rarely needs code
changes. Reports identify runs by tmux session + run_name (derived from
--output_dir), not by model family.

Everything is read-only on the server. No files are written remotely.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

# Epoch summary regex registry ------------------------------------------------
#
# To support a new training script whose summary line doesn't fit any existing
# pattern, add one compiled regex to EPOCH_PATTERNS. Required named groups:
#   loss, lr, time        (always)
#   dice                  (optional — VISTA3D-style scripts that only log loss)
# Unnamed groups 1/2 must be current_epoch / total_epochs.

# A. colon-separated, no train_ prefix, explicit time=      (MedSAM2, MedSAM3)
#    Epoch 9/80: loss=0.3105 dice=0.6995 frames=11628 lr=9.96e-05 time=3618.3s
RE_EPOCH_COLON = re.compile(
    r"Epoch\s+(\d+)\s*/\s*(\d+)\s*:\s*"
    r"loss=(?P<loss>[\d.]+)\s+dice=(?P<dice>[\d.]+)"
    r".*?lr=(?P<lr>[\d.eE+\-]+)"
    r"\s+time=(?P<time>[\d.]+)s?"
)

# B. pipe-separated, train_ prefix, bare trailing time      (SAM-Med3D, SegVol)
#    Epoch 11/80 | train_loss=X train_dice=Y [| val_... ] | lr=E | 5667.2s
RE_EPOCH_PIPED = re.compile(
    r"Epoch\s+(\d+)\s*/\s*(\d+)\s*\|\s*"
    r"train_loss=(?P<loss>[\d.]+)\s+train_dice=(?P<dice>[\d.]+)"
    r".*?"                                                 # optional | val_loss/val_dice block
    r"\|\s*lr=(?P<lr>[\d.eE+\-]+)"
    r"\s*\|\s*(?P<time>[\d.]+)s"
)

# C. em-dash separated, comma-delimited, no train dice      (VISTA3D)
#    Epoch 1/80 — loss=0.4000, lr=9.50e-05, time=2500.0s, samples=384
RE_EPOCH_DASH = re.compile(
    r"Epoch\s+(\d+)\s*/\s*(\d+)\s*[—\-]\s*"
    r"loss=(?P<loss>[\d.]+)"
    r"(?:.*?dice=(?P<dice>[\d.]+))?"                       # dice optional
    r".*?lr=(?P<lr>[\d.eE+\-]+)"
    r".*?time=(?P<time>[\d.]+)s?"
)

EPOCH_PATTERNS: tuple[re.Pattern, ...] = (
    RE_EPOCH_COLON,
    RE_EPOCH_PIPED,
    RE_EPOCH_DASH,
)

# Best-val / resume markers (work across all current scripts) ----------------

# Standard "New best val_dice=..." (MedSAM2/MedSAM3, SAM-Med3D, SegVol)
RE_NEW_BEST = re.compile(r"New\s+best!?\s+val_dice\s*=\s*(?P<val>[\d.]+)")
# VISTA3D alternative: "Epoch 10 — val Dice=0.7400 (best=0.7400 at epoch 10)"
RE_VISTA_VAL_BEST = re.compile(
    r"Epoch\s+(?P<ep>\d+)\s*[—\-]\s*val\s+Dice\s*=\s*(?P<val>[\d.]+)"
    r".*?best\s*=\s*(?P<best>[\d.]+)\s+at\s+epoch\s+(?P<best_ep>\d+)"
)

RE_SAVED_LORA = re.compile(r"Saved\s+\d+\s+LoRA\s+tensors\s+to\s+(?P<path>\S+)")
RE_RESUMED = re.compile(r"Resumed:\s+start_epoch=(?P<ep>\d+),\s+best_val_dice=(?P<val>[\d.]+)")

# Inference-sweep markers (logs that have no epochs but multiple inference runs).
# Generic — matches any "[<Word>-<Word>]" tag prefix; no model name hardcoded.
# Examples covered:
#   --- [3/5] MedSAM3 + text ---
#   [MedSAM3-Point] Found 48 prompt files.
#   [SegVol-Box] Done. 48 cases processed.
RE_SWEEP_HEADER = re.compile(
    r"---\s+\[(\d+)\s*/\s*(\d+)\]\s+(.+?)\s+---"
)
RE_SWEEP_TAG_FOUND = re.compile(
    r"\[([\w][\w\-.]*-[\w][\w\-.]*)\]\s+Found\s+(\d+)\s+prompt\s+files"
)
RE_SWEEP_TAG_DONE = re.compile(
    r"\[([\w][\w\-.]*-[\w][\w\-.]*)\]\s+Done\.\s+(\d+)\s+cases\s+processed"
)

# Parse "... | tee [-a] <path>"  or  "... | tee [-a] '<path>'"
RE_TEE_PATH = re.compile(r"\|\s*tee(?:\s+-a)?\s+(\S+)")
RE_CUDA_DEV = re.compile(r"CUDA_VISIBLE_DEVICES=(\S+)")
RE_OUTPUT_DIR = re.compile(r"--output_dir\s+(\S+)")

# Matches shell-var assignments at start of a line: NAME=value (no leading whitespace)
RE_SHELL_ASSIGN = re.compile(r"^([A-Z_][A-Z0-9_]*)=(.+?)$", re.MULTILINE)
# Matches $VAR or ${VAR} references in a string
RE_SHELL_VAR_REF = re.compile(r"\$\{?([A-Z_][A-Z0-9_]*)\}?")


def _expand_shell_vars(text: str) -> str:
    """
    Lightweight shell-var expander. Scans `text` for `NAME=value` assignments,
    resolves any $VAR references within values (iteratively, capped at 5 passes
    to avoid infinite loops on circular refs), then substitutes them back into
    the whole text. Quotes are stripped from RHS values.

    This is NOT a real shell parser — it handles the common pattern of
    `HONOR=/path`, `OUT=$HONOR/sub`, `tee "$OUT/train.log"` seen in launchers.
    """
    env: dict[str, str] = {}
    for m in RE_SHELL_ASSIGN.finditer(text):
        name, value = m.group(1), m.group(2).strip()
        # strip surrounding single or double quotes
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        env[name] = value

    def _sub_once(s: str) -> str:
        return RE_SHELL_VAR_REF.sub(lambda m: env.get(m.group(1), m.group(0)), s)

    # resolve env values themselves (HONOR → OUT → tee target)
    for _ in range(5):
        changed = False
        for k, v in list(env.items()):
            nv = _sub_once(v)
            if nv != v:
                env[k] = nv
                changed = True
        if not changed:
            break

    return _sub_once(text)

# Remote-side grep filter: match anything that could be a summary line across
# ALL known script formats. Broad on purpose — the fine parse runs locally.
REMOTE_SUMMARY_PATTERNS = (
    r"Epoch [0-9]+(/|[ —-])|"     # any "Epoch N/M" or "Epoch N — ..." form
    r"New best|"
    r"Saved [0-9]+ LoRA|"
    r"Resumed:|"
    r"val_dice|val Dice|"
    r"^--- \[[0-9]+/[0-9]+\] |"   # sweep run header
    r"\] Done\. [0-9]+ cases processed|"  # sweep run completion
    r"\] Found [0-9]+ prompt files"       # sweep run starting
)

# Anything that looks like a tqdm progress bar line — filter out
REMOTE_TQDM_EXCLUDE = r"it/s\]|it\]|%\|"


# Data classes ----------------------------------------------------------------


@dataclass(frozen=True)
class EpochRecord:
    epoch: int
    total: int
    loss: float
    dice: float
    lr: str
    time_s: float


@dataclass(frozen=True)
class GpuSnapshot:
    gpu_idx: int
    util_pct: int
    mem_used_mb: int
    mem_total_mb: int
    temp_c: int


@dataclass(frozen=True)
class SweepRunRecord:
    """One inference run inside a multi-run sweep (e.g. cross-prompt or click-eff)."""
    tag: str               # generic "[Tag]" prefix (e.g. "MedSAM3-Point", "SegVol-Box")
    state: str             # "starting" | "done"
    n_cases: Optional[int] = None  # cases-found (starting) or cases-processed (done)


@dataclass
class TrainRun:
    session: str                           # tmux session name (primary identity)
    bash_pid: str                          # bash pid inside the tmux pane
    python_pid: Optional[str]              # python child pid (None if not found)
    run_name: str                          # run name derived from --output_dir
    log_path: str                          # remote log path
    cuda_visible: Optional[str]            # raw CUDA_VISIBLE_DEVICES value
    etime: str                             # elapsed wall time from ps (raw)
    family_hint: Optional[str] = None      # optional cosmetic model-family tag
    epochs: list[EpochRecord] = field(default_factory=list)
    best_val_dice: Optional[float] = None
    best_val_epoch: Optional[int] = None
    resumed_from_epoch: Optional[int] = None
    log_tail: list[str] = field(default_factory=list)
    gpu: Optional[GpuSnapshot] = None
    anomalies: list[str] = field(default_factory=list)
    parse_error: Optional[str] = None
    # Inference-sweep state (None for training runs).
    sweep_runs: list[SweepRunRecord] = field(default_factory=list)
    sweep_header: Optional[tuple[int, int, str]] = None  # (current_idx, total, label)


# Remote helpers --------------------------------------------------------------


def _run(ssh, cmd: str, timeout: int = 30) -> str:
    """Run a remote command and return stdout (stderr ignored unless parse_error)."""
    _, out, _ = ssh.exec_command(cmd, timeout=timeout)
    return out.read().decode("utf-8", errors="replace")


def _list_sessions_pids(ssh, sessions: list[str]) -> dict[str, list[str]]:
    """Map session_name -> list of pane pids (usually one pane => one bash pid)."""
    result: dict[str, list[str]] = {}
    for s in sessions:
        out = _run(ssh, f"tmux list-panes -t {s} -F '#{{pane_pid}}' 2>/dev/null")
        pids = [p.strip() for p in out.splitlines() if p.strip().isdigit()]
        if pids:
            result[s] = pids
    return result


def _ps_info(ssh, pid: str) -> tuple[str, str]:
    """Return (etime, full_cmd) for a pid. Empty strings if missing."""
    out = _run(ssh, f"ps -o etime=,cmd= -p {pid} 2>/dev/null")
    line = out.strip()
    if not line:
        return "", ""
    # ps output is space-separated: first token = etime, rest = cmd
    etime, _, cmd = line.partition(" ")
    return etime.strip(), cmd.strip()


def _find_python_child(ssh, bash_pid: str) -> Optional[str]:
    """Find the direct python child of a bash pid. Returns pid as str or None."""
    out = _run(ssh, f"ps --ppid {bash_pid} -o pid=,comm= 2>/dev/null")
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[1].startswith("python"):
            return parts[0]
    return None


def _query_gpu_for_pid(ssh, pid: str) -> Optional[GpuSnapshot]:
    """Cross-reference nvidia-smi compute apps with GPU index table for a pid."""
    compute = _run(
        ssh,
        "nvidia-smi --query-compute-apps=pid,gpu_uuid,used_memory "
        "--format=csv,noheader,nounits 2>/dev/null",
    )
    uuid_for_pid: Optional[str] = None
    for line in compute.splitlines():
        parts = [x.strip() for x in line.split(",")]
        if len(parts) >= 2 and parts[0] == str(pid):
            uuid_for_pid = parts[1]
            break
    if not uuid_for_pid:
        return None

    index_table = _run(
        ssh,
        "nvidia-smi --query-gpu=index,uuid,utilization.gpu,"
        "memory.used,memory.total,temperature.gpu "
        "--format=csv,noheader,nounits 2>/dev/null",
    )
    for line in index_table.splitlines():
        parts = [x.strip() for x in line.split(",")]
        if len(parts) >= 6 and parts[1] == uuid_for_pid:
            try:
                return GpuSnapshot(
                    gpu_idx=int(parts[0]),
                    util_pct=int(parts[2]),
                    mem_used_mb=int(parts[3]),
                    mem_total_mb=int(parts[4]),
                    temp_c=int(parts[5]),
                )
            except ValueError:
                return None
    return None


def _fetch_log_summary(ssh, log_path: str, tail_n: int = 60) -> str:
    """
    Remote-fetch only the summary-worthy lines from a huge \r-laden log.

    The pipeline strips tqdm progress bars and keeps epoch-summary / best / saved /
    resumed / val_dice lines, then tails the final N so output stays small.
    """
    cmd = (
        f'tr "\\r" "\\n" < {log_path} '
        f'| grep -avE "{REMOTE_TQDM_EXCLUDE}" '
        f'| grep -aE "{REMOTE_SUMMARY_PATTERNS}" '
        f'| tail -{tail_n}'
    )
    return _run(ssh, cmd, timeout=60)


def _fetch_log_tail_fallback(ssh, log_path: str, n: int = 5) -> list[str]:
    """Grab last N non-empty non-tqdm lines for unknown-format logs or tail display."""
    cmd = (
        f'tr "\\r" "\\n" < {log_path} '
        f'| grep -avE "{REMOTE_TQDM_EXCLUDE}" '
        f'| grep -av "^$" '
        f'| tail -{n}'
    )
    out = _run(ssh, cmd, timeout=60)
    return [ln for ln in out.splitlines() if ln.strip()]


# Command-line inspection -----------------------------------------------------


def _extract_run_name(cmd: str) -> str:
    """Derive a generic run_name from --output_dir (last path component)."""
    m = RE_OUTPUT_DIR.search(cmd)
    if not m:
        return "?"
    output_dir = m.group(1)
    return output_dir.rstrip("/").split("/")[-1] or "?"


# Optional: keep family tagging for users who want to visually group runs.
# Not used by format_report (report is family-agnostic by design) but exposed
# for callers that want to decorate or filter. Adding a new model here is
# purely cosmetic — parsing works regardless.
_FAMILY_HINTS: tuple[tuple[str, str], ...] = (
    ("medsam3", "MedSAM3"),
    ("train_lora_tracker", "MedSAM3"),
    ("sam_med3d", "SAM-Med3D"),
    ("sam-med3d", "SAM-Med3D"),
    ("sam3d_root", "SAM-Med3D"),
    ("segvol", "SegVol"),
    ("vista3d", "VISTA3D"),
    ("medsam2", "MedSAM2"),
    ("nnunet", "nnU-Net"),
    ("transunet", "TransUNet"),
    ("unetr", "UNETR"),
    ("sam_med2d", "SAM-Med2D"),
    ("sam-med2d", "SAM-Med2D"),
)


def guess_family(cmd: str) -> Optional[str]:
    """Optional cosmetic family tag. Returns None if unrecognized."""
    low = cmd.lower()
    for needle, label in _FAMILY_HINTS:
        if needle in low:
            return label
    return None


def _extract_log_path(cmd: str) -> Optional[str]:
    m = RE_TEE_PATH.search(cmd)
    if not m:
        return None
    path = m.group(1).strip("'\"")
    return path or None


def _extract_cuda(cmd: str) -> Optional[str]:
    m = RE_CUDA_DEV.search(cmd)
    return m.group(1) if m else None


# Log parsing -----------------------------------------------------------------


def _match_epoch(line: str) -> Optional[re.Match]:
    """Try each registered epoch pattern; return the first that matches."""
    for pat in EPOCH_PATTERNS:
        m = pat.search(line)
        if m:
            return m
    return None


def _parse_summary_block(text: str) -> tuple[list[EpochRecord], Optional[tuple[float, int]], Optional[int]]:
    """
    Parse the filtered summary block; return (epochs, (best_val, best_epoch)?, resumed_epoch?).

    Handles three distinct "best val" signals:
      - "New best val_dice=X"              (MedSAM2/3, SAM-Med3D, SegVol)
      - "Epoch N — val Dice=X (best=Y at epoch Z)"  (VISTA3D)
      - fallback: last preceding epoch number pairs with the New-best marker

    dice may be missing for scripts that only log train loss (e.g. VISTA3D).
    """
    epochs: list[EpochRecord] = []
    best_val: Optional[float] = None
    best_epoch: Optional[int] = None
    resumed: Optional[int] = None
    last_epoch_num: Optional[int] = None

    for line in text.splitlines():
        m = _match_epoch(line)
        if m:
            try:
                dice_raw = m.groupdict().get("dice")
                rec = EpochRecord(
                    epoch=int(m.group(1)),
                    total=int(m.group(2)),
                    loss=float(m.group("loss")),
                    dice=float(dice_raw) if dice_raw else 0.0,
                    lr=m.group("lr"),
                    time_s=float(m.group("time")),
                )
                epochs.append(rec)
                last_epoch_num = rec.epoch
            except (ValueError, IndexError):
                pass
            continue

        # VISTA3D val line carries best_val AND best_epoch explicitly
        mv = RE_VISTA_VAL_BEST.search(line)
        if mv:
            try:
                best_val = float(mv.group("best"))
                best_epoch = int(mv.group("best_ep"))
            except ValueError:
                pass
            continue

        m2 = RE_NEW_BEST.search(line)
        if m2:
            try:
                best_val = float(m2.group("val"))
                best_epoch = last_epoch_num
            except ValueError:
                pass
            continue

        m3 = RE_RESUMED.search(line)
        if m3:
            try:
                resumed = int(m3.group("ep"))
            except ValueError:
                pass

    pair = (best_val, best_epoch) if best_val is not None else None
    return epochs, pair, resumed


def _parse_sweep_block(text: str) -> tuple[Optional[tuple[int, int, str]], list[SweepRunRecord]]:
    """Parse inference-sweep markers from the same filtered summary block.

    Returns (latest_run_header, list_of_per_tag_records). Each tag (e.g.
    "MedSAM3-Point") collapses to one record reflecting its latest known
    state ("starting" -> "done"). Generic — never matches model names
    explicitly; works for any sweep that emits the standard tag format.
    """
    latest_header: Optional[tuple[int, int, str]] = None
    runs_by_tag: dict[str, SweepRunRecord] = {}

    for line in text.splitlines():
        m_h = RE_SWEEP_HEADER.search(line)
        if m_h:
            try:
                latest_header = (
                    int(m_h.group(1)), int(m_h.group(2)), m_h.group(3).strip()
                )
            except ValueError:
                pass
            continue

        m_d = RE_SWEEP_TAG_DONE.search(line)
        if m_d:
            tag = m_d.group(1)
            try:
                n = int(m_d.group(2))
            except ValueError:
                n = None
            runs_by_tag[tag] = SweepRunRecord(tag=tag, state="done", n_cases=n)
            continue

        m_f = RE_SWEEP_TAG_FOUND.search(line)
        if m_f:
            tag = m_f.group(1)
            try:
                n = int(m_f.group(2))
            except ValueError:
                n = None
            # don't downgrade an existing "done" record
            if runs_by_tag.get(tag, SweepRunRecord(tag=tag, state="?")).state != "done":
                runs_by_tag[tag] = SweepRunRecord(tag=tag, state="starting", n_cases=n)

    return latest_header, list(runs_by_tag.values())


# Anomaly detection -----------------------------------------------------------


def _detect_anomalies(run: TrainRun) -> list[str]:
    msgs: list[str] = []

    # Stagnation — no new best across last 5 completed epochs
    if run.best_val_epoch is not None and run.epochs:
        latest_epoch = run.epochs[-1].epoch
        if latest_epoch - run.best_val_epoch >= 5:
            msgs.append(
                f"val_dice stagnating: {latest_epoch - run.best_val_epoch} epochs since "
                f"last best (best={run.best_val_dice:.4f} @ epoch {run.best_val_epoch})"
            )

    # Loss spike — last epoch loss is >20% higher than the prior
    if len(run.epochs) >= 2:
        prev, curr = run.epochs[-2], run.epochs[-1]
        if prev.loss > 0 and (curr.loss - prev.loss) / prev.loss > 0.20:
            msgs.append(
                f"loss spiked: ep{prev.epoch} {prev.loss:.4f} -> ep{curr.epoch} {curr.loss:.4f}"
            )

    # GPU hot
    if run.gpu is not None and run.gpu.temp_c >= 85:
        msgs.append(f"GPU{run.gpu.gpu_idx} hot: {run.gpu.temp_c}°C (>=85)")

    # GPU idle while session appears to be training (and a python child exists)
    if run.gpu is not None and run.python_pid and run.gpu.util_pct == 0:
        msgs.append(
            f"GPU{run.gpu.gpu_idx} util 0% with live python pid — possibly stuck"
        )

    # Log has zero epochs and no resume marker — only flag if it's NOT a sweep
    if (not run.epochs and run.resumed_from_epoch is None and run.parse_error is None
            and not run.sweep_runs):
        msgs.append("no completed epoch parsed yet (fresh start or unrecognized format)")

    return msgs


# Formatting helpers ----------------------------------------------------------


def humanize_etime(etime: str) -> str:
    """
    Convert ps etime ("HH:MM:SS", "MM:SS", or "D-HH:MM:SS") to "~Xh Ym".
    Returns the raw value if not parseable.
    """
    if not etime:
        return "?"
    s = etime.strip()
    days = 0
    if "-" in s:
        d, _, s = s.partition("-")
        try:
            days = int(d)
        except ValueError:
            days = 0
    parts = s.split(":")
    try:
        ints = [int(p) for p in parts]
    except ValueError:
        return etime
    if len(ints) == 3:
        h, m, _ = ints
    elif len(ints) == 2:
        h, m = 0, ints[0]
    else:
        return etime
    total_h = days * 24 + h
    return f"~{total_h}h{m:02d}m"


def humanize_seconds(secs: float) -> str:
    s = int(secs)
    h, rem = divmod(s, 3600)
    m, ss = divmod(rem, 60)
    if h:
        return f"{h}h{m:02d}m"
    if m:
        return f"{m}m{ss:02d}s"
    return f"{ss}s"


def _eta_hours(run: TrainRun) -> Optional[float]:
    if not run.epochs:
        return None
    last = run.epochs[-1]
    avg = sum(e.time_s for e in run.epochs) / len(run.epochs)
    remaining = last.total - last.epoch
    if remaining <= 0:
        return 0.0
    return remaining * avg / 3600.0


def _delta_arrow(first: float, last: float, decimals: int = 4) -> str:
    delta = last - first
    sign = "↑" if delta > 0 else ("↓" if delta < 0 else "→")
    fmt = f"{{:.{decimals}f}}"
    return f"{fmt.format(first)} {sign} {fmt.format(last)} (Δ{delta:+.{decimals}f})"


# Public API ------------------------------------------------------------------


def summarize(
    ssh,
    sessions: list[str],
    exclude: Optional[set[str]] = None,
) -> list[TrainRun]:
    """
    Inspect each non-excluded tmux session and produce a TrainRun record.

    Parameters
    ----------
    ssh : paramiko SSHClient (already connected, read-only)
    sessions : list of tmux session names
    exclude : session names to skip (default: {"honor_cron"})
    """
    if exclude is None:
        exclude = {"honor_cron"}

    target_sessions = [s for s in sessions if s not in exclude]
    if not target_sessions:
        return []

    pane_map = _list_sessions_pids(ssh, target_sessions)
    runs: list[TrainRun] = []

    for session in target_sessions:
        bash_pids = pane_map.get(session, [])
        if not bash_pids:
            continue
        bash_pid = bash_pids[0]  # one pane per session in this workflow
        etime, cmd = _ps_info(ssh, bash_pid)
        if not cmd:
            continue

        python_pid = _find_python_child(ssh, bash_pid)

        # If the pane cmd is a bash launcher wrapper (common pattern), the
        # log path / cuda / output_dir live either in the inner python cmd
        # OR inside the launcher .sh file itself (shell-level `| tee`).
        # Build a single effective command string from all 3 sources so the
        # existing extractors still work.
        effective_cmd = cmd
        if python_pid:
            _, python_cmd = _ps_info(ssh, python_pid)
            if python_cmd:
                effective_cmd = effective_cmd + "\n" + python_cmd

        m_launcher = re.search(r"\bbash\s+(\S+\.sh)\b", cmd)
        if m_launcher:
            launcher_contents = _run(
                ssh, f"cat {m_launcher.group(1)} 2>/dev/null | head -60", timeout=10
            )
            if launcher_contents:
                effective_cmd = effective_cmd + "\n" + _expand_shell_vars(launcher_contents)

        log_path = _extract_log_path(effective_cmd)
        cuda = _extract_cuda(effective_cmd)
        run_name = _extract_run_name(effective_cmd)
        family_hint = guess_family(effective_cmd)
        gpu = _query_gpu_for_pid(ssh, python_pid) if python_pid else None

        if not log_path:
            runs.append(
                TrainRun(
                    session=session, bash_pid=bash_pid, python_pid=python_pid,
                    run_name=run_name, family_hint=family_hint,
                    log_path="(not found)",
                    cuda_visible=cuda, etime=etime, gpu=gpu,
                    parse_error="could not locate tee-target log path in cmd",
                )
            )
            continue

        # Check log exists + its size
        stat_out = _run(ssh, f"ls -la {log_path} 2>&1 | head -1")
        if "No such file" in stat_out or not stat_out.strip():
            runs.append(
                TrainRun(
                    session=session, bash_pid=bash_pid, python_pid=python_pid,
                    run_name=run_name, family_hint=family_hint,
                    log_path=log_path,
                    cuda_visible=cuda, etime=etime, gpu=gpu,
                    parse_error=f"log file not found: {log_path}",
                )
            )
            continue

        try:
            summary_block = _fetch_log_summary(ssh, log_path, tail_n=80)
            epochs, best_pair, resumed = _parse_summary_block(summary_block)
            sweep_header, sweep_runs = _parse_sweep_block(summary_block)
            tail_lines = _fetch_log_tail_fallback(ssh, log_path, n=3)
        except Exception as exc:  # broad on purpose — SSH / parse failure
            runs.append(
                TrainRun(
                    session=session, bash_pid=bash_pid, python_pid=python_pid,
                    run_name=run_name, family_hint=family_hint,
                    log_path=log_path,
                    cuda_visible=cuda, etime=etime, gpu=gpu,
                    parse_error=f"log parse error: {exc!r}",
                )
            )
            continue

        best_val = best_pair[0] if best_pair else None
        best_epoch = best_pair[1] if best_pair else None

        run = TrainRun(
            session=session,
            bash_pid=bash_pid,
            python_pid=python_pid,
            run_name=run_name,
            family_hint=family_hint,
            log_path=log_path,
            cuda_visible=cuda,
            etime=etime,
            epochs=epochs,
            best_val_dice=best_val,
            best_val_epoch=best_epoch,
            resumed_from_epoch=resumed,
            log_tail=tail_lines,
            gpu=gpu,
            sweep_runs=sweep_runs,
            sweep_header=sweep_header,
        )
        run.anomalies = _detect_anomalies(run)
        runs.append(run)

    return runs


def format_report(runs: list[TrainRun]) -> str:
    """Render a markdown section ('## Training progress') for all runs."""
    if not runs:
        return "\n## Training progress\n  (no active training sessions)\n"

    lines = ["", "## Training progress"]
    for run in runs:
        # Generic header: tmux session as primary identity, run_name as subtitle.
        # Optional family_hint shown as a small tag only if it was recognized.
        tag = f"  [{run.family_hint}]" if run.family_hint else ""
        header = f"\n### {run.session}  —  {run.run_name}{tag}"
        lines.append(header)

        gpu_part = (
            f"GPU{run.gpu.gpu_idx} util={run.gpu.util_pct}% "
            f"mem={run.gpu.mem_used_mb}/{run.gpu.mem_total_mb}MiB "
            f"temp={run.gpu.temp_c}°C"
            if run.gpu else f"CUDA_VISIBLE_DEVICES={run.cuda_visible or '?'} (no GPU proc match)"
        )
        lines.append(
            f"  session etime: {humanize_etime(run.etime)} "
            f"| bash_pid={run.bash_pid} python_pid={run.python_pid or '?'}"
        )
        lines.append(f"  {gpu_part}")
        lines.append(f"  log: {run.log_path}")

        if run.parse_error:
            lines.append(f"  [!] {run.parse_error}")
            if run.log_tail:
                lines.append("  recent tail:")
                for ln in run.log_tail:
                    lines.append(f"    {ln}")
            continue

        if run.resumed_from_epoch is not None:
            lines.append(f"  resumed from epoch {run.resumed_from_epoch}")

        if run.epochs:
            first = run.epochs[0]
            last = run.epochs[-1]
            avg_epoch = sum(e.time_s for e in run.epochs) / len(run.epochs)
            eta_h = _eta_hours(run)
            eta_str = f"{eta_h:.1f}h" if eta_h is not None else "?"

            lines.append(
                f"  progress: epoch {last.epoch}/{last.total} done "
                f"(avg {humanize_seconds(avg_epoch)}/ep, ETA ~{eta_str})"
            )
            lines.append(
                f"  latest epoch: loss={last.loss:.4f} dice={last.dice:.4f} "
                f"lr={last.lr}"
            )
            if len(run.epochs) >= 2:
                lines.append(
                    f"  loss trajectory: {_delta_arrow(first.loss, last.loss)}"
                )
                lines.append(
                    f"  dice trajectory: {_delta_arrow(first.dice, last.dice)}"
                )
            if run.best_val_dice is not None:
                ep = run.best_val_epoch if run.best_val_epoch is not None else "?"
                lines.append(
                    f"  best val_dice: {run.best_val_dice:.4f} @ epoch {ep}"
                )
            else:
                lines.append("  best val_dice: (no validation yet)")
        elif run.sweep_runs:
            done = sum(1 for r in run.sweep_runs if r.state == "done")
            started = len(run.sweep_runs)
            if run.sweep_header:
                i, n, label = run.sweep_header
                lines.append(
                    f"  inference sweep: run {i}/{n} ({label}); "
                    f"{done}/{started} tagged runs completed in this log"
                )
            else:
                lines.append(
                    f"  inference sweep: {done}/{started} tagged runs completed"
                )
            for sr in run.sweep_runs:
                cases = f" ({sr.n_cases} cases)" if sr.n_cases is not None else ""
                lines.append(f"    [{sr.tag}] {sr.state}{cases}")
        else:
            lines.append("  progress: no completed epoch / sweep run parsed yet")

        if run.anomalies:
            lines.append("  anomalies:")
            for a in run.anomalies:
                lines.append(f"    [!] {a}")

        if run.log_tail:
            lines.append("  recent log (non-tqdm):")
            for ln in run.log_tail:
                lines.append(f"    {ln}")

    lines.append("")
    return "\n".join(lines)
