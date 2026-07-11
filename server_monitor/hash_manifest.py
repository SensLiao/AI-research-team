"""Read-only remote sha256 manifest helper for execution preflight.

Default mode is an offline plan. Live mode reuses the same director gate as server-query:
``RAT_SERVER_QUERY_AUTHORIZED``. The helper never opens SFTP, never downloads files, never writes to
the remote server, and passes every command through the existing read-only guard.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shlex
import sys
from typing import Iterable, List, Optional

from research_agent_teams.execute import config as ec
from research_agent_teams.server_monitor import monitor


IAC_NNUNET_NOMIRROR_PATHS = [
    "nnUNet_results/predictions/nnunet_s1_fold5_test_nomirror",
    "nnUNet_results/evaluation/nnunet_s1_fold5_test_nomirror",
]


def _clean_paths(paths: Iterable[str]) -> List[str]:
    cleaned = [str(p).strip() for p in paths if str(p).strip()]
    if not cleaned:
        raise ValueError("at least one path is required")
    return cleaned


def build_command(paths: Iterable[str], *, workdir: Optional[str] = None) -> str:
    """Build a deterministic, read-only sha256 command for one or more remote paths."""
    cleaned = _clean_paths(paths)
    quoted_paths = " ".join(shlex.quote(p) for p in cleaned)
    body = (
        f"for p in {quoted_paths}; do "
        'if [ -e "$p" ]; then '
        'LC_ALL=C find "$p" -type f -print0 | LC_ALL=C sort -z | xargs -0 -r sha256sum; '
        'else echo "__MISSING__ $p"; fi; '
        "done"
    )
    cmd = f"cd {shlex.quote(workdir)} && {body}" if workdir else body
    monitor.assert_read_only(cmd)
    return cmd


def plan(paths: Iterable[str], *, workdir: Optional[str] = None) -> dict:
    """Offline preview of the exact read-only command. No SSH connection is opened."""
    cmd = build_command(paths, workdir=workdir)
    return {
        "mode": "plan",
        "connection": "NOT CONNECTED (plan only).",
        "read_only_command": cmd,
        "live_gate": (
            f"set {monitor.AUTH_ENV}=1 (director) to allow a READ-ONLY live hash manifest; "
            "the model must not self-authorize."
        ),
    }


def live_manifest(
    paths: Iterable[str],
    *,
    executor=None,
    cfg=None,
    env_path: str = "research_agent_teams/.env",
    project: Optional[str] = None,
    run_id: Optional[str] = None,
    workdir: Optional[str] = None,
    resolver=None,
) -> dict:
    """Run the read-only hash manifest live, gated unless an executor is injected for tests."""
    own = executor is None
    if own:
        executor, cfg = monitor.connect(env_path)
    elif not isinstance(executor, monitor.ReadOnlyExecutor):
        executor = monitor.ReadOnlyExecutor(executor)

    lease_info = None
    if project and run_id:
        from research_agent_teams.tools.resource_resolver import ResourceResolver

        resolver = resolver or ResourceResolver()
        resolved = resolver.resolve(
            project=project,
            run_id=run_id,
            alias_or_resource="primary_gpu",
            capability="pull_logs",
            stage="EXECUTE",
            skill="server-query",
        )
        lease_info = {
            "lease_id": resolved.lease_id,
            "resource_id": resolved.resource_id,
            "capability": resolved.capability,
            "requires_human_approval": resolved.requires_human_approval,
        }

    try:
        remote_workdir = workdir
        if remote_workdir is None and cfg is not None:
            remote_workdir = cfg.workdir or None
        cmd = build_command(paths, workdir=remote_workdir)
        stdout = monitor._run(executor, cmd, timeout=300)
        lines = [line for line in stdout.splitlines() if line.strip()]
        missing = [
            line.removeprefix("__MISSING__ ").strip()
            for line in lines
            if line.startswith("__MISSING__ ")
        ]
        return {
            "mode": "live",
            "server": ec.redacted_summary(cfg) if cfg else {},
            "command": cmd,
            "lines": lines,
            "line_count": len(lines),
            "missing": missing,
            "stdout_sha256": "sha256:" + hashlib.sha256(stdout.encode("utf-8")).hexdigest(),
            "lease": lease_info,
        }
    finally:
        if own:
            executor.close()


def _paths_from_args(args) -> List[str]:
    paths: List[str] = []
    if args.iac_nnunet_nomirror:
        paths.extend(IAC_NNUNET_NOMIRROR_PATHS)
    paths.extend(args.path or [])
    return _clean_paths(paths)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog="server_hash_manifest",
        description="Read-only remote sha256 manifest preflight (plan / live).",
    )
    ap.add_argument("--iac-nnunet-nomirror", action="store_true", help="use the IAC nnU-Net paths")
    ap.add_argument("--path", action="append", default=[], help="remote path to hash; repeatable")
    ap.add_argument("--workdir", default=None, help="remote workdir to cd into before hashing")
    ap.add_argument("--live", action="store_true", help="force a live read-only manifest")
    ap.add_argument("--project", default=None, help="lease pull_logs on this project's primary_gpu")
    ap.add_argument("--run-id", dest="run_id", default=None)
    ap.add_argument("--env", default="research_agent_teams/.env")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    try:
        paths = _paths_from_args(args)
        if args.live:
            result = live_manifest(
                paths,
                env_path=args.env,
                project=args.project,
                run_id=args.run_id,
                workdir=args.workdir,
            )
        else:
            result = plan(paths, workdir=args.workdir)
    except monitor.ServerQueryRefused as e:
        print(json.dumps({"error": str(e)}, ensure_ascii=False) if args.json else f"[refused] {e}")
        return 2
    except Exception as e:
        print(json.dumps({"error": str(e)}, ensure_ascii=False) if args.json else f"[error] {e}")
        return 1

    if args.json:
        print(json.dumps(result, ensure_ascii=False, default=str, indent=2))
    elif result["mode"] == "plan":
        print("# Hash manifest PLAN (offline, not connected)")
        print(result["connection"])
        print(result["live_gate"])
        print(result["read_only_command"])
    else:
        print("# Hash manifest LIVE (read-only)")
        print(f"server: {result['server']}")
        if result.get("lease"):
            print(f"lease: {result['lease']}")
        print(f"line_count: {result['line_count']}")
        print(f"stdout_sha256: {result['stdout_sha256']}")
        if result["missing"]:
            print(f"missing: {result['missing']}")
        for line in result["lines"]:
            print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
