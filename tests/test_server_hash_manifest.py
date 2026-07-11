"""Tests for the read-only remote hash manifest preflight helper."""
from __future__ import annotations

import hashlib
import json

import pytest

from research_agent_teams.execute.config import ServerConfig
from research_agent_teams.server_monitor import hash_manifest as hm
from research_agent_teams.server_monitor import monitor as mon


class _Stream:
    def __init__(self, data):
        self._d = data.encode("utf-8")

    def read(self):
        return self._d


class FakeSSH:
    def __init__(self, stdout):
        self.stdout = stdout
        self.commands = []
        self.closed = False

    def exec_command(self, cmd, timeout=30):
        self.commands.append(cmd)
        return None, _Stream(self.stdout), None

    def open_sftp(self):
        raise AssertionError("hash manifest must never open SFTP")

    def close(self):
        self.closed = True


def _cfg():
    return ServerConfig(
        host="lab.example.edu",
        port=22,
        user="user01",
        workdir="/data",
        python="python3",
        conda_env="",
        conda_sh="",
        scheduler="",
        results_pull_dir="runs",
        known_hosts="",
        has_password=True,
        has_ssh_key=False,
    )


def test_build_command_is_read_only_and_quotes_paths():
    cmd = hm.build_command(["a path", "b"], workdir="/data/project")
    assert "cd /data/project" in cmd
    assert "'a path'" in cmd
    assert "sha256sum" in cmd
    mon.assert_read_only(cmd)


def test_build_command_requires_paths():
    with pytest.raises(ValueError):
        hm.build_command([])


def test_plan_is_offline_and_secret_free(monkeypatch):
    monkeypatch.setenv("RAT_SERVER_PASSWORD", "SENTINEL-SECRET-NO-LEAK")
    p = hm.plan(hm.IAC_NNUNET_NOMIRROR_PATHS)
    assert p["mode"] == "plan"
    assert p["connection"].startswith("NOT CONNECTED")
    assert "sha256sum" in p["read_only_command"]
    assert "SENTINEL-SECRET-NO-LEAK" not in str(p)


def test_live_manifest_injected_executor_records_stdout_hash():
    stdout = (
        "abc123  nnUNet_results/predictions/nnunet_s1_fold5_test_nomirror/case001.nii.gz\n"
        "__MISSING__ nnUNet_results/evaluation/nnunet_s1_fold5_test_nomirror\n"
    )
    fake = FakeSSH(stdout)
    st = hm.live_manifest(hm.IAC_NNUNET_NOMIRROR_PATHS, executor=fake, cfg=_cfg())
    assert st["mode"] == "live"
    assert st["line_count"] == 2
    assert st["missing"] == ["nnUNet_results/evaluation/nnunet_s1_fold5_test_nomirror"]
    assert st["stdout_sha256"] == "sha256:" + hashlib.sha256(stdout.encode("utf-8")).hexdigest()
    assert fake.commands and "sha256sum" in fake.commands[0]


def test_live_manifest_refused_without_authorization(monkeypatch):
    monkeypatch.delenv("RAT_SERVER_QUERY_AUTHORIZED", raising=False)
    with pytest.raises(mon.ServerQueryRefused):
        hm.live_manifest(["x"])


def test_live_manifest_with_pull_logs_lease(tmp_path, monkeypatch):
    monkeypatch.delenv("RAT_RESOURCES_ROOT", raising=False)
    monkeypatch.delenv("RAT_PROJECTS_ROOT", raising=False)
    from research_agent_teams.tools.resource_resolver import ResourceResolver

    resolver = ResourceResolver(workspace_root=str(tmp_path / "ws"))
    st = hm.live_manifest(
        ["x"],
        executor=FakeSSH("abc  x\n"),
        cfg=_cfg(),
        project="iac-cbct-seg",
        run_id="hash-r1",
        resolver=resolver,
    )
    assert st["lease"]["lease_id"] == "lease-hash-r1-001"
    assert st["lease"]["resource_id"] == "server.honor.gpu"
    assert st["lease"]["capability"] == "pull_logs"
    audit = (tmp_path / "ws" / "audit_log.jsonl").read_text(encoding="utf-8")
    assert '"capability": "pull_logs"' in audit and '"decision": "granted"' in audit


def test_cli_plan_outputs_json(capsys):
    rc = hm.main(["--iac-nnunet-nomirror", "--json"])
    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert data["mode"] == "plan"
    assert "sha256sum" in data["read_only_command"]
