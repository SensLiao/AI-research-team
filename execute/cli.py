"""GPU EXECUTE CLI.

  plan   --run-id <id> --script train.py [--args "..."] [--gpus 0]   -> offline preview (NO connection)
  submit --run-id <id> --script train.py [--local-script path]       -> LIVE (director-gated)
  status --run-id <id>                                               -> LIVE (director-gated)
  pull   --run-id <id>                                               -> LIVE (director-gated)

`plan` is the model-safe default. This ordinary CLI deliberately has no flag that can impersonate an
in-chat director confirmation: submit/status/pull remain REFUSED unless the legacy exact
RAT_EXECUTE_AUTHORIZED=<run_id> capability is present. Assistant-mediated live operations use the
library-only explicit-director-command parameter after the primary assistant shows the exact mutation
plan and receives a fresh top-level confirmation (CLAUDE.md §6).
"""
from __future__ import annotations

import argparse
import json
import sys

from . import runner
from .job import JobSpec
from .runner import LiveConnectionRefused


def _emit(obj) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))


def _job(a) -> JobSpec:
    return JobSpec(run_id=a.run_id, script=getattr(a, "script", "") or "",
                   args=getattr(a, "args", "") or "", gpus=getattr(a, "gpus", "") or "",
                   local_script=getattr(a, "local_script", None),
                   project=getattr(a, "project", "") or "")


def cmd_plan(a) -> None:
    out = runner.plan(_job(a), env_path=a.env)
    _emit({k: v for k, v in out.items() if k != "run_sh"})
    print("\n=== run.sh (the bash that would run in tmux on the server) ===", file=sys.stderr)
    print(out["run_sh"], file=sys.stderr)


def _live(fn, a) -> None:
    try:
        _emit(fn(_job(a), env_path=a.env))
    except LiveConnectionRefused as e:
        _emit({"refused": True, "reason": str(e)})
        sys.exit(4)


def build_parser() -> argparse.ArgumentParser:
    import argparse as _a
    common = _a.ArgumentParser(add_help=False)
    common.add_argument("--run-id", required=True)
    common.add_argument("--project", default="",
                        help="the run's research project (lowercase-kebab); groups the remote dir as "
                             "<workdir>/<project>/<run_id> and the pulled results as "
                             "<results>/<project>/<run_id>/pulled")
    common.add_argument("--env", default="research_agent_teams/.env")

    p = argparse.ArgumentParser(prog="python -m research_agent_teams.execute", allow_abbrev=False,
                                description="Gated GPU execution on the lab server (plan offline; live director-gated).")
    sub = p.add_subparsers(dest="cmd", required=True)

    pl = sub.add_parser("plan", parents=[common], help="offline preview of the exact remote job (NO connection)")
    pl.add_argument("--script", required=True)
    pl.add_argument("--args", default="")
    pl.add_argument("--gpus", default="")
    pl.set_defaults(func=cmd_plan)

    sb = sub.add_parser("submit", parents=[common], help="LIVE submit (director-gated)")
    sb.add_argument("--script", required=True)
    sb.add_argument("--args", default="")
    sb.add_argument("--gpus", default="")
    sb.add_argument("--local-script", default=None)
    sb.set_defaults(func=lambda a: _live(runner.submit, a))

    st = sub.add_parser("status", parents=[common], help="LIVE status (director-gated)")
    st.set_defaults(func=lambda a: _live(runner.status, a))

    pu = sub.add_parser("pull", parents=[common], help="LIVE pull results (director-gated)")
    pu.set_defaults(func=lambda a: _live(runner.pull, a))
    return p


def main(argv=None) -> None:
    args = build_parser().parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
