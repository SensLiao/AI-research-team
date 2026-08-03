from __future__ import annotations

from pathlib import Path

import pytest

from research_agent_teams.tools.server_credential_import import (
    import_bdav_handoff,
    parse_bdav_handoff,
)


HANDOFF = """Account/Server Host Name/Unikey: test-user
Initial Password: TEST-SENTINEL-DO-NOT-LEAK
Server IP Address: second.lab.example.edu
Where to store all your files:/mnt/HDD4 (i.e. not /home/test-user)
"""


def test_parse_exact_fields():
    parsed = parse_bdav_handoff(HANDOFF)
    assert parsed["user"] == "test-user"
    assert parsed["host"] == "second.lab.example.edu"
    assert parsed["workdir"] == "/mnt/HDD4"


def test_import_preserves_unrelated_env_and_never_returns_secret(tmp_path: Path):
    source = tmp_path / "handoff.md"
    env = tmp_path / ".env"
    source.write_text(HANDOFF, encoding="utf-8")
    env.write_text("RAT_UNRELATED_SECRET=KEEP-ME\nRAT_BDAV_Z390_PORT=2202\n", encoding="utf-8")

    result = import_bdav_handoff(source, env)
    written = env.read_text(encoding="utf-8")

    assert "RAT_UNRELATED_SECRET=KEEP-ME" in written
    assert "RAT_BDAV_Z390_PORT=2202" in written
    assert "RAT_BDAV_Z390_HOST=second.lab.example.edu" in written
    assert "TEST-SENTINEL-DO-NOT-LEAK" not in repr(result)
    assert result["secret_values_emitted"] is False


def test_rejects_non_hdd4_workdir():
    with pytest.raises(ValueError, match="/mnt/HDD4"):
        parse_bdav_handoff(HANDOFF.replace("/mnt/HDD4", "/home/test-user"))
