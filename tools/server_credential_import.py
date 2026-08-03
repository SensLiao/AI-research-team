"""Secret-safe import of the director's out-of-repo BDAV server handoff into ``.env``.

The importer is intentionally narrow: it recognises the four labelled fields in the university
handoff, validates their shape, and atomically upserts only ``RAT_BDAV_Z390_*`` keys. It never returns
or prints a credential value. Resource metadata continues to store env-var NAMES only.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Mapping


_FIELD_PATTERNS = {
    "user": re.compile(r"^Account/Server Host Name/Unikey:\s*(\S+)\s*$", re.MULTILINE),
    "password": re.compile(r"^Initial Password:\s*(\S+)\s*$", re.MULTILINE),
    "host": re.compile(r"^Server IP Address:\s*(\S+)\s*$", re.MULTILINE),
    "workdir": re.compile(r"^Where to store all your files:\s*(/\S+)", re.MULTILINE),
}

_PROFILE_KEYS = {
    "host": "RAT_BDAV_Z390_HOST",
    "user": "RAT_BDAV_Z390_USER",
    "password": "RAT_BDAV_Z390_PASSWORD",
    "workdir": "RAT_BDAV_Z390_REMOTE_WORKDIR",
}

_DEFAULTS = {
    "RAT_BDAV_Z390_CONNECT_HOST": "",
    "RAT_BDAV_Z390_PORT": "22",
    "RAT_BDAV_Z390_SSH_KEY": "",
    "RAT_BDAV_Z390_KNOWN_HOSTS": "",
    "RAT_BDAV_Z390_REMOTE_PYTHON": "python3",
    "RAT_BDAV_Z390_REMOTE_CONDA_ENV": "",
    "RAT_BDAV_Z390_REMOTE_CONDA_SH": "",
    "RAT_BDAV_Z390_SCHEDULER": "",
    "RAT_BDAV_Z390_RESULTS_PULL_DIR": "runs",
}


def parse_bdav_handoff(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for field, pattern in _FIELD_PATTERNS.items():
        matches = pattern.findall(text)
        if len(matches) != 1:
            raise ValueError(f"handoff must contain exactly one labelled {field} field")
        values[field] = matches[0].strip()
    if not re.fullmatch(r"[A-Za-z0-9._-]+", values["user"]):
        raise ValueError("handoff user field has an invalid shape")
    if not re.fullmatch(r"[A-Za-z0-9.-]+", values["host"]):
        raise ValueError("handoff host field has an invalid shape")
    if not values["workdir"].startswith("/mnt/HDD4"):
        raise ValueError("BDAV workdir must stay on /mnt/HDD4")
    if not values["password"]:
        raise ValueError("handoff password is empty")
    return values


def _upsert_env(path: Path, updates: Mapping[str, str]) -> list[str]:
    existing = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    remaining = dict(updates)
    output: list[str] = []
    for line in existing:
        if "=" in line and not line.lstrip().startswith("#"):
            key = line.split("=", 1)[0].strip()
            if key in remaining:
                output.append(f"{key}={remaining.pop(key)}")
                continue
        output.append(line)
    if remaining:
        if output and output[-1] != "":
            output.append("")
        output.append("# Secondary USyd BDAV Z390-3090 server (secret values; never commit)")
        output.extend(f"{key}={value}" for key, value in remaining.items())

    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent), text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write("\n".join(output).rstrip("\n") + "\n")
        try:
            os.chmod(tmp_name, 0o600)
        except OSError:
            pass
        os.replace(tmp_name, path)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)
    return sorted(updates)


def import_bdav_handoff(source: Path, env_path: Path) -> dict[str, object]:
    values = parse_bdav_handoff(source.read_text(encoding="utf-8"))
    updates = {env_name: values[field] for field, env_name in _PROFILE_KEYS.items()}
    # Preserve any already-pinned optional value; defaults are added only when absent.
    current_keys = set()
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                current_keys.add(line.split("=", 1)[0].strip())
    updates.update({key: value for key, value in _DEFAULTS.items() if key not in current_keys})
    updated_keys = _upsert_env(env_path, updates)
    return {
        "profile": "server.usyd.bdav_z390_3090",
        "env_path": str(env_path),
        "updated_keys": updated_keys,
        "secret_values_emitted": False,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Import a BDAV server handoff without printing secrets")
    parser.add_argument("--source", required=True)
    parser.add_argument("--env", default="research_agent_teams/.env")
    args = parser.parse_args(argv)
    result = import_bdav_handoff(Path(args.source), Path(args.env))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
