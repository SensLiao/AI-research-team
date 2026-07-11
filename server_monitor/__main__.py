"""CLI: ``python -m research_agent_teams.server_monitor [--live] [--project P --run-id R] [--json]``

Default = plan (offline, always safe). ``--live`` forces a live READ-ONLY query (still gated by
RAT_SERVER_QUERY_AUTHORIZED). Output is a markdown report unless ``--json``.
"""
from __future__ import annotations

import argparse
import json
import sys

from research_agent_teams.server_monitor import monitor


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="server_monitor",
                                 description="Read-only GPU-server status (plan / live).")
    ap.add_argument("--live", action="store_true", help="force a live read-only query (director-gated)")
    ap.add_argument("--project", default=None, help="lease query_status on this project's primary_gpu")
    ap.add_argument("--run-id", dest="run_id", default=None)
    ap.add_argument("--env", default="research_agent_teams/.env")
    ap.add_argument("--json", action="store_true", help="emit JSON (run details collapsed to a count)")
    args = ap.parse_args(argv)

    if args.live:
        try:
            status = monitor.live_status(env_path=args.env, project=args.project, run_id=args.run_id)
        except monitor.ServerQueryRefused as e:
            print(json.dumps({"error": str(e)}) if args.json else f"[refused] {e}")
            return 2
    else:
        status = monitor.query(env_path=args.env, project=args.project, run_id=args.run_id)

    if args.json:
        safe = {k: (len(v) if k == "runs" else v) for k, v in status.items()}
        print(json.dumps(safe, ensure_ascii=False, default=str, indent=2))
    else:
        print(monitor.format_status(status))
    return 0


if __name__ == "__main__":
    sys.exit(main())
