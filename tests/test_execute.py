"""GPU EXECUTE layer — mock tests. Exercise the offline core (config / job-command builder / plan) and
the SAFETY GATE without any real connection: monkeypatched FAKE env vars (never the real .env), no
paramiko (the live path is refused before paramiko would import), no shared-server contact.

What these lock:
  - secrets never leak into the config object / redacted summary / plan output;
  - the remote job encodes the lab runbook footguns (python3, conda set +u/-u, caches off root, LF, tmux);
  - workdir etiquette (no writes outside the workdir);
  - LIVE connect/submit is REFUSED unless the director set RAT_EXECUTE_AUTHORIZED == run_id (the model
    can never self-authorize), and authorization is per-run.
"""
from __future__ import annotations

import pytest

from research_agent_teams.execute import config
from research_agent_teams.execute.job import (
    JobSpec, assert_in_workdir, build_job_script, tmux_submit_command,
)
from research_agent_teams.execute.runner import LiveConnectionRefused, connect, is_authorized, plan, submit

FAKE_ENV = {
    "RAT_SERVER_HOST": "fake.lab.example.edu",
    "RAT_SERVER_PORT": "22",
    "RAT_SERVER_USER": "tester",
    "RAT_SERVER_PASSWORD": "SECRET-do-not-leak",
    "RAT_REMOTE_WORKDIR": "/mnt/HDD4/tester/research-runs",
    "RAT_REMOTE_PYTHON": "python3",
    "RAT_REMOTE_CONDA_ENV": "/mnt/HDD4/tester/envs/iac",
    "RAT_REMOTE_CONDA_SH": "/mnt/HDD3/conda/etc/profile.d/conda.sh",
    "RAT_RESULTS_PULL_DIR": "runs",
}

# a path that does NOT exist, so _load_dotenv no-ops and load_config reads the monkeypatched os.environ
# (never the real research_agent_teams/.env — tests must not touch real credentials)
NO_DOTENV = "research_agent_teams/.env.__nonexistent_for_tests__"


@pytest.fixture
def fake_env(monkeypatch):
    for k, v in FAKE_ENV.items():
        monkeypatch.setenv(k, v)
    monkeypatch.delenv("RAT_SERVER_SSH_KEY", raising=False)
    monkeypatch.delenv("RAT_EXECUTE_AUTHORIZED", raising=False)
    return NO_DOTENV


def test_config_holds_no_secret_and_summary_redacts(fake_env):
    cfg = config.load_config(fake_env)
    assert not hasattr(cfg, "password") and not hasattr(cfg, "ssh_key")   # dataclass stores no secret
    assert cfg.has_password is True
    summ = config.redacted_summary(cfg)
    assert "SECRET-do-not-leak" not in str(summ)
    assert summ["auth"] == "password"
    assert summ["host"] == "fake.lab.example.edu" and summ["user"] == "tester"


def test_config_can_select_an_isolated_second_server_by_env_reference(fake_env, monkeypatch):
    alt = {
        "host": "RAT_ALT_HOST",
        "port": "RAT_ALT_PORT",
        "user": "RAT_ALT_USER",
        "password": "RAT_ALT_PASSWORD",
        "remote_workdir": "RAT_ALT_WORKDIR",
        "known_hosts": "RAT_ALT_KNOWN_HOSTS",
    }
    monkeypatch.setenv("RAT_ALT_HOST", "second.lab.example.edu")
    monkeypatch.setenv("RAT_ALT_PORT", "2202")
    monkeypatch.setenv("RAT_ALT_USER", "second-user")
    monkeypatch.setenv("RAT_ALT_PASSWORD", "SECOND-SENTINEL-DO-NOT-LEAK")
    monkeypatch.setenv("RAT_ALT_WORKDIR", "/mnt/HDD4")
    monkeypatch.setenv("RAT_ALT_KNOWN_HOSTS", "/tmp/second-known-hosts")

    cfg = config.load_config(fake_env, env_refs=alt)

    assert cfg.host == "second.lab.example.edu"
    assert cfg.port == 2202 and cfg.user == "second-user" and cfg.workdir == "/mnt/HDD4"
    assert cfg.password_env == "RAT_ALT_PASSWORD"
    assert cfg.has_password is True
    assert "SECOND-SENTINEL-DO-NOT-LEAK" not in repr(cfg)


def test_transport_reads_selected_resource_credential_reference(fake_env, monkeypatch):
    from research_agent_teams.execute import runner

    monkeypatch.setenv("RAT_ALT_HOST", "second.lab.example.edu")
    monkeypatch.setenv("RAT_ALT_USER", "second-user")
    monkeypatch.setenv("RAT_ALT_PASSWORD", "SECOND-SENTINEL")
    cfg = config.load_config(fake_env, env_refs={
        "host": "RAT_ALT_HOST",
        "user": "RAT_ALT_USER",
        "password": "RAT_ALT_PASSWORD",
    })
    seen = {}

    class FakeClient:
        def connect(self, **kwargs):
            seen.update(kwargs)

    runner._connect_verified_transport(FakeClient(), cfg)
    assert seen["password"] == "SECOND-SENTINEL"
    assert seen["username"] == "second-user"


def test_repr_omits_operational_identifiers(fake_env, monkeypatch):
    """ServerConfig.__repr__ (L2 hygiene) shows only host/port/auth — never user / workdir / known_hosts
    values — so a stray repr / log line / traceback frame cannot spill them."""
    monkeypatch.setenv("RAT_SERVER_KNOWN_HOSTS", "/home/tester/.ssh/known_hosts")
    cfg = config.load_config(fake_env)
    r = repr(cfg)
    # the auth MODE is shown, host/port are shown
    assert r == "ServerConfig(host='fake.lab.example.edu', port=22, auth=password)"
    # the identifiers that the default dataclass repr WOULD have leaked are absent
    assert "tester" not in r                      # user value
    assert "/mnt/HDD4/tester/research-runs" not in r   # workdir value
    assert "known_hosts" not in r and "/home/tester/.ssh" not in r  # known_hosts value
    # and the secret was never on the object anyway
    assert "SECRET-do-not-leak" not in r


def test_repr_reflects_ssh_key_and_none_auth_modes(fake_env, monkeypatch):
    """The auth mode in repr tracks the resolved credential: ssh_key when only a key is set, none when
    neither — proving the mode is derived, not hardcoded."""
    monkeypatch.delenv("RAT_SERVER_PASSWORD", raising=False)
    monkeypatch.setenv("RAT_SERVER_SSH_KEY", "/home/tester/.ssh/id_ed25519")
    assert repr(config.load_config(fake_env)).endswith("auth=ssh_key)")

    monkeypatch.delenv("RAT_SERVER_SSH_KEY", raising=False)
    assert repr(config.load_config(fake_env)).endswith("auth=none)")


def test_direct_ip_endpoint_is_separate_from_canonical_host_identity(fake_env, monkeypatch):
    monkeypatch.setenv("RAT_SERVER_CONNECT_HOST", "192.0.2.25")
    cfg = config.load_config(fake_env)

    assert cfg.host == "fake.lab.example.edu"
    assert cfg.connect_host == "192.0.2.25"
    summary = config.redacted_summary(cfg)
    assert summary["connection_route"] == "direct-ip/canonical-host-key"
    assert "192.0.2.25" not in str(summary)
    assert "192.0.2.25" not in repr(cfg)


def test_direct_endpoint_opens_ip_socket_but_paramiko_verifies_canonical_name(
    fake_env, monkeypatch
):
    from research_agent_teams.execute import runner

    monkeypatch.setenv("RAT_SERVER_CONNECT_HOST", "192.0.2.25")
    cfg = config.load_config(fake_env)
    socket_token = object()
    seen = {}

    def socket_factory(address, timeout):
        seen["socket"] = {"address": address, "timeout": timeout}
        return socket_token

    class FakeClient:
        def connect(self, **kwargs):
            seen["connect"] = kwargs

    runner._connect_verified_transport(FakeClient(), cfg, socket_factory=socket_factory)

    assert seen["socket"] == {"address": ("192.0.2.25", 22), "timeout": 30}
    assert seen["connect"]["hostname"] == "fake.lab.example.edu"
    assert seen["connect"]["sock"] is socket_token


def test_direct_endpoint_must_be_an_ip_literal(fake_env, monkeypatch):
    monkeypatch.setenv("RAT_SERVER_CONNECT_HOST", "another.mutable.hostname.example")
    with pytest.raises(RuntimeError, match="IP literal"):
        config.load_config(fake_env)


def test_job_script_encodes_runbook_footguns(fake_env):
    cfg = config.load_config(fake_env)
    js = build_job_script(cfg, JobSpec(run_id="exp-1", script="train.py", args="--epochs 5", gpus="0"))
    assert "python3 train.py --epochs 5" in js                       # #1 python3, not python
    assert "set +u" in js and "set -u" in js                         # #4 conda activate wrapping
    assert "conda activate /mnt/HDD4/tester/envs/iac" in js
    assert 'export TMPDIR="' in js and "HF_HOME=" in js              # #2 caches off the root partition
    assert "CUDA_VISIBLE_DEVICES=0 " in js
    assert 'cd "/mnt/HDD4/tester/research-runs/exp-1"' in js
    assert "\r" not in js                                            # #3 LF only (no CRLF)


def test_submit_command_uses_tmux(fake_env):
    cfg = config.load_config(fake_env)
    cmd = tmux_submit_command(cfg, JobSpec(run_id="exp-1", script="train.py"))
    assert cmd.startswith("tmux new-session -d -s rat-exp-1")


def test_plan_is_offline_and_leaks_no_secret(fake_env):
    out = plan(JobSpec(run_id="exp-1", script="train.py"), env_path=fake_env)
    assert out["connection"].startswith("NOT CONNECTED")
    assert "run_sh" in out and "submit_cmd" in out and "status_cmd" in out
    assert "SECRET-do-not-leak" not in str(out)
    assert out["remote_run_dir"] == "/mnt/HDD4/tester/research-runs/exp-1"


def test_etiquette_refuses_paths_outside_workdir(fake_env):
    cfg = config.load_config(fake_env)
    assert_in_workdir(cfg, "/mnt/HDD4/tester/research-runs/exp-1")   # inside -> ok
    for bad in ("/etc/passwd", "/mnt/HDD3/shared/private", "/home/other/x"):
        with pytest.raises(PermissionError):
            assert_in_workdir(cfg, bad)


def test_live_connection_is_director_gated(fake_env):
    j = JobSpec(run_id="exp-1", script="train.py")
    assert is_authorized(j) is False                                 # RAT_EXECUTE_AUTHORIZED unset
    with pytest.raises(LiveConnectionRefused):                       # refused BEFORE any paramiko/connection
        connect(j, env_path=fake_env)
    with pytest.raises(LiveConnectionRefused):
        submit(j, env_path=fake_env)


def test_authorization_is_per_run(fake_env, monkeypatch):
    monkeypatch.setenv("RAT_EXECUTE_AUTHORIZED", "exp-1")
    assert is_authorized(JobSpec(run_id="exp-1", script="t.py")) is True
    assert is_authorized(JobSpec(run_id="OTHER-run", script="t.py")) is False   # scoped to the authorized run


def test_explicit_director_command_authorizes_without_environment(fake_env):
    """The primary assistant can carry the director's in-chat confirmation into one live call."""
    job = JobSpec(run_id="exp-1", script="t.py")
    assert is_authorized(job, explicit_director_command=True) is True


def test_connect_accepts_explicit_director_command_but_still_requires_credentials(
    fake_env, monkeypatch
):
    """An explicit command crosses only the human gate; it does not weaken SSH authentication."""
    monkeypatch.delenv("RAT_SERVER_PASSWORD", raising=False)
    monkeypatch.delenv("RAT_SERVER_SSH_KEY", raising=False)
    job = JobSpec(run_id="exp-1", script="t.py")

    with pytest.raises(RuntimeError, match="no auth"):
        connect(job, env_path=fake_env, explicit_director_command=True)


def test_live_cli_cannot_self_assert_director_invocation():
    """The ordinary CLI keeps the legacy env gate; no public bypass flag is exposed."""
    from research_agent_teams.execute.cli import build_parser

    with pytest.raises(SystemExit):
        build_parser().parse_args([
            "submit", "--run-id", "exp-1", "--script", "t.py", "--director-invoked"
        ])


def test_submit_threads_explicit_command_and_records_authorization_basis(fake_env, monkeypatch):
    """A live receipt must say whether approval came from the top-level director command."""
    from research_agent_teams.execute import runner

    class FakeSftp:
        def file(self, *_args, **_kwargs):
            class Sink:
                def __enter__(self):
                    return self

                def __exit__(self, *_exc):
                    return False

                def write(self, _text):
                    return None

            return Sink()

        def close(self):
            return None

    class FakeClient:
        def exec_command(self, _command):
            return None, None, None

        def open_sftp(self):
            return FakeSftp()

        def close(self):
            return None

    cfg = config.load_config(fake_env)
    seen = {}

    def fake_connect(job, env_path, *, explicit_director_command=False):
        seen["explicit"] = explicit_director_command
        return FakeClient(), cfg

    monkeypatch.setattr(runner, "connect", fake_connect)
    receipt = runner.submit(
        JobSpec(run_id="exp-1", script="t.py"),
        env_path=fake_env,
        explicit_director_command=True,
    )

    assert seen == {"explicit": True}
    assert receipt["authorization_basis"] == "explicit-director-command"


# ----------------------------- ④ remote command injection -----------------------------

def test_jobspec_rejects_injection_in_run_id():
    for bad in ("a; rm -rf ~", "a$(whoami)", "a`id`", "a b", "../x", "a|b", "a'b", "a.b", "a:b"):
        with pytest.raises(ValueError):
            JobSpec(run_id=bad, script="train.py")


def test_jobspec_rejects_unsafe_script_and_gpus():
    for bad in ("../etc/passwd", "/abs/train.py", "train.py; rm", "tr$(x).py", "-rf"):
        with pytest.raises(ValueError):
            JobSpec(run_id="exp-1", script=bad)
    for bad in ("0; rm", "0,$(x)", "all", "0 1"):
        with pytest.raises(ValueError):
            JobSpec(run_id="exp-1", script="t.py", gpus=bad)


def test_job_args_injection_is_neutralized_in_script(fake_env):
    cfg = config.load_config(fake_env)
    js = build_job_script(cfg, JobSpec(run_id="exp-1", script="train.py", args="--data x ; rm -rf ~"))
    assert "; rm -rf" not in js               # the bare command separator does not survive
    assert "';'" in js                        # the ';' became an inert, single-quoted literal arg
    # and the benign multi-arg case is unchanged (regression guard for the existing footgun test)
    js2 = build_job_script(cfg, JobSpec(run_id="exp-1", script="train.py", args="--epochs 5", gpus="0"))
    assert "python3 train.py --epochs 5" in js2


# ----------------------------- ⑤ pull landing-path fence -----------------------------

def test_pull_dest_fence_rejects_escape_and_vault(tmp_path, monkeypatch):
    from research_agent_teams.execute.runner import _safe_pull_dest
    runs = tmp_path / "runs"
    monkeypatch.setenv("RAT_VAULT_ROOT", str(tmp_path / "vault"))
    # default: inside the run-store -> ok
    dest = _safe_pull_dest(str(runs), "exp-1", None)
    assert str(dest).startswith(str(runs.resolve()))
    # `into` escaping the run-store -> refused
    with pytest.raises(PermissionError):
        _safe_pull_dest(str(runs), "exp-1", str(tmp_path / "elsewhere"))
    # `into` aimed at the vault -> refused
    with pytest.raises(PermissionError):
        _safe_pull_dest(str(runs), "exp-1", str(tmp_path / "vault" / "02-wiki" / "x"))


# ----------------------------- ⑥ SSH host-key verification -----------------------------

def test_connect_uses_reject_policy_not_autoadd(fake_env):
    paramiko = pytest.importorskip("paramiko")
    from research_agent_teams.execute.runner import _harden_host_key_verification
    cfg = config.load_config(fake_env)
    client = paramiko.SSHClient()
    _harden_host_key_verification(client, cfg)
    assert type(client._policy).__name__ == "RejectPolicy"   # NOT AutoAddPolicy (no trust-on-first-use)
