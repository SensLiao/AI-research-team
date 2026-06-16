"""Observability log: one schema-validated line per agent invocation (append-only)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import List

from research_agent_teams.tools.hash_artifact import canonical_json
from research_agent_teams.tools.validate_artifact import validate_against

SCHEMA = "agent_run_log.schema.json"


def append_log(log_path, entry: dict) -> dict:
    errs = validate_against(SCHEMA, entry)
    if errs:
        raise ValueError(f"invalid agent_run_log: {errs}")
    with open(log_path, "a", encoding="utf-8") as fh:
        fh.write(canonical_json(entry) + "\n")
    return entry


def read_logs(log_path) -> List[dict]:
    p = Path(log_path)
    if not p.exists():
        return []
    return [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]
