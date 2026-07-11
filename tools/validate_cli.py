"""CLI wrapper for the artifact contract enforcer (so the JS hook can shell out to it).

Usage:
    python -m research_agent_teams.tools.validate_cli <artifact.json>
    <json on stdin> | python -m research_agent_teams.tools.validate_cli --stdin

Exit 0 = valid (prints OK). Exit 2 = invalid/unreadable (prints errors to stderr).
"""
from __future__ import annotations

import json
import sys

from research_agent_teams.tools.validate_artifact import validate_artifact


def _load(argv):
    if len(argv) >= 2 and argv[1] == "--stdin":
        return json.loads(sys.stdin.read())
    if len(argv) >= 2:
        with open(argv[1], encoding="utf-8") as fh:
            return json.load(fh)
    raise ValueError("usage: validate_cli <artifact.json> | --stdin")


def main(argv) -> int:
    try:
        artifact = _load(argv)
    except Exception as exc:  # unreadable / unparsable -> fail closed
        print(f"contract-enforcer: cannot read artifact: {exc}", file=sys.stderr)
        return 2
    errors = validate_artifact(artifact)
    if errors:
        for e in errors:
            print(f"contract-enforcer: {e}", file=sys.stderr)
        return 2
    print("OK")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
