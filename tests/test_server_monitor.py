"""server-query tests — offline plan, the read-only command guard, the live gate, and a full
injected-executor live_status run (no network). Plus parser units for the vendored train_progress."""
from __future__ import annotations

import pytest

from research_agent_teams.execute.config import ServerConfig
from research_agent_teams.server_monitor import monitor as mon
from research_agent_teams.server_monitor import train_progress as tp


# --------------------------------------------------------------------------- fake SSH

class _Stream:
    def __init__(self, data):
        self._d = data.encode("utf-8")

    def read(self):
        return self._d


SESSIONS = "train1: 1 windows (created Mon)\nhonor_cron: 1 windows (created Mon)"


def _responder(cmd):
    c = cmd
    if c.strip() == "tmux ls":
        return SESSIONS
    if "list-panes -t train1" in c:
        return "12345"
    if "list-panes -t honor_cron" in c:
        return "999"
    if "query-compute-apps" in c:
        return "23456, GPU-uuid-1, 40000"
    if "query-gpu=index,uuid" in c or ("uuid" in c and "query-gpu" in c):
        return "0, GPU-uuid-1, 85, 40000, 49140, 70"
    if "query-gpu=index,utilization" in c:
        return "0, 85, 40000, 49140, 70"
    if "ps -o etime=,cmd= -p 12345" in c:
        return "01:23:45 CUDA_VISIBLE_DEVICES=0 python train.py --output_dir /data/runs/exp-A | tee /data/runs/exp-A/train.log"
    if "ps --ppid 12345" in c:
        return "23456 python"
    if "ps -o etime=,cmd= -p 23456" in c:
        return "01:20:00 python train.py --output_dir /data/runs/exp-A | tee /data/runs/exp-A/train.log"
    if "ls -la /data/runs/exp-A/train.log" in c:
        return "-rw-r--r-- 1 u u 5000 Jun 16 10:00 /data/runs/exp-A/train.log"
    if "grep -aE" in c:                       # the summary-include fetch
        return ("Epoch 8/80: loss=0.40 dice=0.60 frames=1 lr=9.9e-05 time=3600.0s\n"
                "Epoch 9/80: loss=0.31 dice=0.70 frames=1 lr=9.8e-05 time=3500.0s\n"
                "New best val_dice=0.71")
    if 'grep -av "^$"' in c:                  # the tail fallback
        return "Epoch 9/80: loss=0.31 dice=0.70 frames=1 lr=9.8e-05 time=3500.0s"
    if "df -h" in c:
        return "/dev/sda1 1.0T 500G 500G 50% /data"
    return ""


class FakeSSH:
    def __init__(self):
        self.commands = []
        self.closed = False

    def exec_command(self, cmd, timeout=30):
        self.commands.append(cmd)
        return None, _Stream(_responder(cmd)), None

    def open_sftp(self):
        raise AssertionError("server-query must never open SFTP")

    def close(self):
        self.closed = True


def _cfg():
    return ServerConfig(host="lab.example.edu", port=22, user="user01", workdir="/data",
                        python="python3", conda_env="", conda_sh="", scheduler="",
                        results_pull_dir="runs", known_hosts="", has_password=True, has_ssh_key=False)


# --------------------------------------------------------------------------- read-only guard

def test_assert_read_only_accepts_real_commands():
    mon.assert_read_only("tmux ls")
    mon.assert_read_only(mon.GPU_QUERY)
    mon.assert_read_only("df -h /data | tail -1")
    mon.assert_read_only('tr "\\r" "\\n" < /data/x.log | grep -avE "it/s" | grep -aE "Epoch" | tail -80')
    mon.assert_read_only("ps -eo pid,user,%cpu,%mem,etime,cmd --sort=-%mem | grep -E python | head -20")


@pytest.mark.parametrize("bad", [
    "rm -rf /data", "kill -9 123", "pkill python", "mv a b", "sudo reboot",
    "echo x > /tmp/y", "cat a >> b", "tee /tmp/z", "scp a b", "chmod 777 x",
])
def test_assert_read_only_rejects_mutations(bad):
    with pytest.raises(mon.UnsafeServerCommand):
        mon.assert_read_only(bad)


def test_readonly_executor_guards_and_blocks_sftp():
    ex = mon.ReadOnlyExecutor(FakeSSH())
    out = ex.exec_command("tmux ls")[1].read().decode()
    assert "train1" in out
    with pytest.raises(mon.UnsafeServerCommand):
        ex.exec_command("rm -rf /")
    with pytest.raises(mon.UnsafeServerCommand):
        ex.open_sftp()


# --------------------------------------------------------------------------- plan + gate

def test_plan_is_offline_and_lists_readonly_commands(monkeypatch):
    monkeypatch.setenv("RAT_SERVER_PASSWORD", "SENTINEL-SECRET-NO-LEAK")
    p = mon.plan()
    assert p["mode"] == "plan"
    assert p["connection"].startswith("NOT CONNECTED")
    assert any("tmux ls" in c for c in p["read_only_commands"])
    assert "SENTINEL-SECRET-NO-LEAK" not in str(p)


def test_connect_refused_without_authorization(monkeypatch):
    monkeypatch.delenv("RAT_SERVER_QUERY_AUTHORIZED", raising=False)
    assert mon.is_authorized() is False
    with pytest.raises(mon.ServerQueryRefused):
        mon.connect()                          # gate is checked BEFORE paramiko import


def test_is_authorized_true_when_env_set(monkeypatch):
    monkeypatch.setenv("RAT_SERVER_QUERY_AUTHORIZED", "1")
    assert mon.is_authorized() is True


# --------------------------------------------------------------------------- live_status (injected)

def test_live_status_full_run_injected_executor(monkeypatch):
    monkeypatch.setenv("RAT_SERVER_PASSWORD", "SENTINEL-SECRET-NO-LEAK")
    fake = FakeSSH()
    st = mon.live_status(executor=fake, cfg=_cfg())
    assert st["mode"] == "live"
    assert "train1" in st["sessions"] and "honor_cron" in st["sessions"]
    assert len(st["gpus"]) == 1 and st["gpus"][0]["util"] == 85 and st["gpus"][0]["temp"] == 70
    assert "/data" in st["disk"]
    assert len(st["runs"]) == 1
    run = st["runs"][0]
    assert run.session == "train1"
    assert run.best_val_dice == pytest.approx(0.71)
    assert run.gpu is not None and run.gpu.util_pct == 85
    # secret never present; SFTP never opened
    assert "SENTINEL-SECRET-NO-LEAK" not in str(st)
    # the markdown render works and stays secret-free
    md = mon.format_status(st)
    assert "Server status — LIVE" in md and "SENTINEL-SECRET-NO-LEAK" not in md


def test_live_status_with_project_leases_and_audits(tmp_path, monkeypatch):
    monkeypatch.delenv("RAT_RESOURCES_ROOT", raising=False)
    monkeypatch.delenv("RAT_PROJECTS_ROOT", raising=False)
    from research_agent_teams.tools.resource_resolver import ResourceResolver
    resolver = ResourceResolver(workspace_root=str(tmp_path / "ws"))
    st = mon.live_status(executor=FakeSSH(), cfg=_cfg(), project="iac-cbct-seg", run_id="r1",
                         resolver=resolver)
    assert st["lease"]["lease_id"] == "lease-r1-001"
    assert st["lease"]["resource_id"] == "server.honor.gpu"
    assert st["lease"]["requires_human_approval"] is True
    audit = (tmp_path / "ws" / "audit_log.jsonl").read_text(encoding="utf-8")
    assert '"capability": "query_status"' in audit and '"decision": "granted"' in audit


# --------------------------------------------------------------------------- parser units

def test_parse_tmux_sessions_handles_no_server():
    assert mon.parse_tmux_sessions("no server running on /tmp/tmux-1000/default") == []
    assert mon.parse_tmux_sessions("a: 1 windows\nb: 2 windows") == ["a", "b"]


def test_parse_gpu_table():
    g = mon.parse_gpu_table("0, 12, 100, 49140, 55\n1, 0, 0, 49140, 40")
    assert len(g) == 2 and g[0]["util"] == 12 and g[1]["idx"] == 1


def test_train_progress_parses_three_epoch_formats():
    colon = "Epoch 9/80: loss=0.31 dice=0.70 frames=1 lr=9.8e-05 time=3500.0s"
    piped = "Epoch 11/80 | train_loss=0.25 train_dice=0.75 | val_dice=0.7 | lr=1e-4 | 5667.2s"
    dash = "Epoch 1/80 — loss=0.40, lr=9.50e-05, time=2500.0s, samples=384"
    eps, best, resumed = tp._parse_summary_block("\n".join([colon, piped, dash]))
    assert [e.epoch for e in eps] == [9, 11, 1]
    assert eps[0].dice == pytest.approx(0.70)


def test_train_progress_best_and_resume():
    text = ("Resumed: start_epoch=5, best_val_dice=0.60\n"
            "Epoch 6/80: loss=0.3 dice=0.65 lr=1e-4 time=10s\n"
            "New best val_dice=0.66")
    eps, best, resumed = tp._parse_summary_block(text)
    assert resumed == 5
    assert best == (pytest.approx(0.66), 6)


def test_train_progress_detect_stagnation():
    run = tp.TrainRun(session="s", bash_pid="1", python_pid="2", run_name="r", log_path="l",
                      cuda_visible="0", etime="01:00:00",
                      epochs=[tp.EpochRecord(e, 80, 0.3, 0.7, "1e-4", 10.0) for e in range(1, 11)],
                      best_val_dice=0.7, best_val_epoch=3)
    anomalies = tp._detect_anomalies(run)
    assert any("stagnat" in a for a in anomalies)


def test_humanize_etime():
    assert tp.humanize_etime("01:23:45") == "~1h23m"
    assert tp.humanize_etime("2-03:04:05") == "~51h04m"
