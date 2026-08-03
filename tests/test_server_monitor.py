"""server-query tests — offline plan, the read-only command guard, the live gate, and a full
injected-executor live_status run (no network). Plus parser units for the vendored train_progress."""
from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

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
    marker = "\n__RAT_PROBE_EXIT__=0\n" if "__RAT_PROBE_EXIT__" in c else ""
    if c.strip() == "hostname":
        return "lab-a6000\n"
    if c.startswith("date -u"):
        return "2026-07-31T12:00:00Z\n"
    if c.strip() == "id -un":
        return "user01\n"
    if c.strip() == "uname -sr":
        return "Linux 5.15.0\n"
    if c.strip() == "tmux ls":
        return SESSIONS
    if "list-panes -t train1" in c:
        return "12345"
    if "list-panes -t honor_cron" in c:
        return "999"
    if "query-compute-apps" in c:
        return "23456, GPU-uuid-1, 40000" + marker
    if "query-gpu=index,uuid,name" in c:
        return "0, GPU-uuid-1, NVIDIA RTX A6000, 85, 40000, 49140, 70, 535.1" + marker
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
    if "ps -o user=,pid=,etime=,comm= -p 23456" in c:
        return "user01 23456 01:20:00 python"
    if "ls -la /data/runs/exp-A/train.log" in c:
        return "-rw-r--r-- 1 u u 5000 Jun 16 10:00 /data/runs/exp-A/train.log"
    if "grep -aE" in c:                       # the summary-include fetch
        return ("Epoch 8/80: loss=0.40 dice=0.60 frames=1 lr=9.9e-05 time=3600.0s\n"
                "Epoch 9/80: loss=0.31 dice=0.70 frames=1 lr=9.8e-05 time=3500.0s\n"
                "New best val_dice=0.71")
    if 'grep -av "^$"' in c:                  # the tail fallback
        return "Epoch 9/80: loss=0.31 dice=0.70 frames=1 lr=9.8e-05 time=3500.0s"
    if "df -B1" in c:
        return "/dev/sda1 1000000000000 500000000000 500000000000 50% /data"
    if "df -Pi" in c:
        return "/dev/sda1 1000000 250000 750000 25% /data"
    if "python3 --version" in c:
        return "Python 3.11.9\n__RAT_PROBE_EXIT__=0\n"
    if "/opt/petct/bin/python --version" in c:
        return "Python 3.10.14\n__RAT_PROBE_EXIT__=0\n"
    if "command -v conda" in c:
        return "/opt/conda/bin/conda\n"
    if "conda --version" in c:
        return "conda 24.5.0\n__RAT_PROBE_EXIT__=0\n"
    if "conda env list --json" in c:
        return '{"envs":["/opt/conda","/opt/conda/envs/petct"]}\n__RAT_PROBE_EXIT__=0\n'
    if "tmux -V" in c:
        return "tmux 3.4\n__RAT_PROBE_EXIT__=0\n"
    if "command -v sinfo" in c:
        return ""
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
    mon.assert_read_only(mon.GPU_PROCESS_QUERY)
    mon.assert_read_only("ps -o user=,pid=,etime=,comm= -p 23456 2>/dev/null")
    mon.assert_read_only("df -B1 -P -- /data | tail -1")
    mon.assert_read_only("df -Pi -P -- /data | tail -1")
    mon.assert_read_only("timeout 5s python3 --version 2>&1")


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
    assert any("query-compute-apps=pid,gpu_uuid,used_memory" in c
               for c in p["read_only_commands"])
    assert mon.PS_GPU_PROCESS_QUERY in p["read_only_commands"]
    assert any("df -B1" in c for c in p["read_only_commands"])
    assert any("df -Pi" in c for c in p["read_only_commands"])
    assert any("conda --version" in c for c in p["read_only_commands"])
    assert any("sinfo --noheader" in c for c in p["read_only_commands"])
    assert "SENTINEL-SECRET-NO-LEAK" not in str(p)


def test_plan_lists_configured_execution_python_without_duplicate_system_probe():
    commands = mon._planned_commands("/data", "/opt/petct/bin/python")
    assert sum("python3 --version" in command for command in commands) == 1
    assert any("/opt/petct/bin/python --version" in command for command in commands)


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
    assert st["gpu_inventory_status"] == "PASS"
    assert "/data" in st["disk"]
    assert st["storage"]["bytes"]["available_bytes"] == 500000000000
    assert st["storage"]["inodes"]["available_inodes"] == 750000
    assert st["runtime"]["python3"]["version"] == "Python 3.11.9"
    assert st["runtime"]["conda"]["status"] == "AVAILABLE"
    assert st["scheduler"]["tmux"]["status"] == "HEALTHY"
    assert len(st["runs"]) == 1
    run = st["runs"][0]
    assert run.session == "train1"
    assert run.best_val_dice == pytest.approx(0.71)
    assert run.gpu is not None and run.gpu.util_pct == 85
    assert st["workload"]["state"] == "MONITORED_PROJECT_RUNS_ACTIVE"
    assert st["workload"]["matched_run_gpu_process_count"] == 1
    assert st["workload"]["monitored_run_visibility"] == "PASS"
    assert st["gpu_processes"] == [{
        "pid": 23456,
        "gpu_uuid": "GPU-uuid-1",
        "used_memory_mb": 40000,
        "inspection_status": "PASS",
        "owner": "user01",
        "elapsed": "01:20:00",
        "comm": "python",
        "gpu_idx": 0,
        "matches_monitored_run": True,
        "workload_class": "monitored_project_run",
    }]
    # secret never present; SFTP never opened
    assert "SENTINEL-SECRET-NO-LEAK" not in str(st)
    # the markdown render works and stays secret-free
    md = mon.format_status(st)
    assert "Server status — LIVE" in md and "SENTINEL-SECRET-NO-LEAK" not in md
    assert "MONITORED_PROJECT_RUNS_ACTIVE" in md and "comm=python" in md
    assert "host=lab-a6000" in md and "driver=535.1" in md
    assert "monitored_runs=1 gpu_processes=1" in md
    # The workload inventory deliberately never requests or prints a full process command line.
    assert not any("user=,pid=,etime=,cmd=" in cmd for cmd in fake.commands)


def test_live_status_with_project_leases_and_audits(tmp_path, monkeypatch, resource_projects_root):
    monkeypatch.delenv("RAT_RESOURCES_ROOT", raising=False)
    from research_agent_teams.tools.resource_resolver import ResourceResolver
    resolver = ResourceResolver(workspace_root=str(tmp_path / "ws"))
    st = mon.live_status(executor=FakeSSH(), cfg=_cfg(), project="iac-cbct-seg", run_id="r1",
                         resolver=resolver)
    assert st["lease"]["lease_id"] == "lease-r1-001"
    assert st["lease"]["resource_id"] == "server.honor.gpu"
    assert st["lease"]["requires_human_approval"] is True
    audit = (tmp_path / "ws" / "audit_log.jsonl").read_text(encoding="utf-8")
    assert '"capability": "query_status"' in audit and '"decision": "granted"' in audit


def test_live_status_can_select_secondary_resource_alias():
    class CapturingResolver:
        def __init__(self):
            self.kwargs = None

        def resolve(self, **kwargs):
            self.kwargs = kwargs
            return SimpleNamespace(
                lease_id="lease-secondary-001",
                resource_id="server.second.gpu",
                requires_human_approval=True,
                env_refs={"host": "RAT_SECOND_HOST", "password": "RAT_SECOND_PASSWORD"},
            )

    resolver = CapturingResolver()
    st = mon.live_status(
        executor=FakeSSH(), cfg=_cfg(), project="iac-cbct-seg", run_id="r-secondary",
        resource_alias="secondary_gpu", resolver=resolver)

    assert resolver.kwargs["alias_or_resource"] == "secondary_gpu"
    assert st["lease"]["resource_id"] == "server.second.gpu"


def test_cli_routes_explicit_secondary_alias(monkeypatch, capsys):
    from research_agent_teams.server_monitor import __main__ as cli

    seen = {}

    def fake_live_status(**kwargs):
        seen.update(kwargs)
        return {
            "mode": "live", "server": {}, "sessions": [], "gpus": [], "disk": "",
            "runs": [], "lease": {
                "lease_id": "lease-test-001",
                "resource_id": "server.usyd.bdav_z390_3090",
                "requires_human_approval": True,
            },
        }

    monkeypatch.setattr(cli.monitor, "live_status", fake_live_status)
    rc = cli.main([
        "--live", "--project", "petct-textual-intent", "--run-id", "audit-1",
        "--resource", "secondary_gpu", "--json",
    ])
    assert rc == 0
    assert seen["project"] == "petct-textual-intent"
    assert seen["run_id"] == "audit-1"
    assert seen["resource_alias"] == "secondary_gpu"
    assert "server.usyd.bdav_z390_3090" in capsys.readouterr().out


# --------------------------------------------------------------------------- parser units

def test_parse_tmux_sessions_handles_no_server():
    assert mon.parse_tmux_sessions("no server running on /tmp/tmux-1000/default") == []
    assert mon.parse_tmux_sessions("a: 1 windows\nb: 2 windows") == ["a", "b"]


def test_parse_gpu_table():
    g = mon.parse_gpu_table("0, 12, 100, 49140, 55\n1, 0, 0, 49140, 40")
    assert len(g) == 2 and g[0]["util"] == 12 and g[1]["idx"] == 1


def test_parse_extended_gpu_and_compute_process_tables():
    g = mon.parse_gpu_table(
        "0, GPU-a, NVIDIA RTX A6000, 91, 42000, 49140, 72, 535.1"
    )
    assert g == [{
        "idx": 0, "uuid": "GPU-a", "name": "NVIDIA RTX A6000", "util": 91,
        "mem_used": 42000, "mem_total": 49140, "temp": 72, "driver_version": "535.1",
    }]
    p = mon.parse_gpu_process_table("321, GPU-a, 2048 MiB\nnot-a-pid, GPU-a, 1")
    assert p == [{"pid": 321, "gpu_uuid": "GPU-a", "used_memory_mb": 2048}]


def test_host_gpu_workload_is_not_hidden_when_tmux_and_project_runs_are_empty():
    class HostBusySSH(FakeSSH):
        def exec_command(self, cmd, timeout=30):
            self.commands.append(cmd)
            if cmd.strip() == "tmux ls":
                response = "no server running on /tmp/tmux-1000/default"
            elif "query-compute-apps" in cmd:
                response = "777, GPU-uuid-1, 12000\n__RAT_PROBE_EXIT__=0\n"
            elif "ps -o user=,pid=,etime=,comm= -p 777" in cmd:
                response = "another_user 777 05:10:00 python3"
            else:
                response = _responder(cmd)
            return None, _Stream(response), None

    st = mon.live_status(executor=HostBusySSH(), cfg=_cfg())
    assert st["sessions"] == [] and st["runs"] == []
    assert st["workload"]["state"] == "NO_MONITORED_PROJECT_RUNS_HOST_GPU_BUSY"
    assert st["workload"]["gpu_process_count"] == 1
    assert st["workload"]["other_owner_gpu_process_count"] == 1
    assert st["gpu_processes"][0]["workload_class"] == "host_other_or_unattributed"
    rendered = mon.format_status(st)
    assert "NO_MONITORED_PROJECT_RUNS_HOST_GPU_BUSY" in rendered
    assert "owner=another_user" in rendered
    assert "train.py" not in rendered  # no argument leakage from host-level inventory


def test_compute_process_probe_failure_is_unknown_not_idle():
    class ComputeProbeFailure(FakeSSH):
        def __init__(self):
            super().__init__()
            self.compute_calls = 0

        def exec_command(self, cmd, timeout=30):
            if "query-compute-apps" in cmd:
                self.compute_calls += 1
                if self.compute_calls == 1:  # host inventory fails; per-project parser may continue
                    raise TimeoutError("simulated")
            return super().exec_command(cmd, timeout=timeout)

    st = mon.live_status(executor=ComputeProbeFailure(), cfg=_cfg())
    assert st["gpu_processes"] == []
    assert st["workload"]["state"] == "GPU_WORKLOAD_VISIBILITY_UNKNOWN"
    assert st["workload"]["host_has_gpu_workload"] is None
    assert "do not infer that the host is idle" in mon.format_status(st)


def test_project_run_probe_failure_does_not_claim_runs_are_absent():
    class RunProbeFailure(FakeSSH):
        def exec_command(self, cmd, timeout=30):
            if "query-compute-apps" in cmd and "__RAT_PROBE_EXIT__" not in cmd:
                raise TimeoutError("simulated project parser failure")
            return super().exec_command(cmd, timeout=timeout)

    st = mon.live_status(executor=RunProbeFailure(), cfg=_cfg())
    assert st["gpu_processes"]
    assert st["runs"] == []
    assert st["workload"]["monitored_run_visibility"] == "UNKNOWN"
    assert st["workload"]["state"] == "MONITORED_RUN_VISIBILITY_UNKNOWN_HOST_GPU_BUSY"
    assert st["workload"]["project_monitor_has_active_runs"] is None
    assert "runs=0 is not evidence of absence" in mon.format_status(st)


def test_broken_slurm_client_is_unusable_and_overall_scheduler_is_not_pass():
    class BrokenSlurm(FakeSSH):
        def exec_command(self, cmd, timeout=30):
            self.commands.append(cmd)
            if "command -v sinfo" in cmd:
                response = "/usr/bin/sinfo\n"
            elif "sinfo --noheader" in cmd:
                response = "fatal: missing slurm.conf\n__RAT_PROBE_EXIT__=1\n"
            else:
                response = _responder(cmd)
            return None, _Stream(response), None

    st = mon.live_status(executor=BrokenSlurm(), cfg=_cfg())
    assert st["scheduler"]["slurm"] == {"status": "UNUSABLE", "partitions": []}
    assert st["scheduler"]["status"] == "DEGRADED"


def test_configured_execution_python_and_conda_environment_are_verified():
    cfg = replace(_cfg(), python="/opt/petct/bin/python", conda_env="petct")
    st = mon.live_status(executor=FakeSSH(), cfg=cfg)
    assert st["runtime"]["configured_python"] == {
        "status": "AVAILABLE", "name": "python", "version": "Python 3.10.14",
    }
    assert st["runtime"]["conda"]["configured_env_status"] == "PRESENT"
    assert st["runtime"]["status"] == "PASS"


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
