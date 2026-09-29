"""healpipe CLI.

  healpipe scenarios                               list fault scenarios
  healpipe run --scenario species_mislabel [--planner claude] [--dry-run]
                                                   submit one job, poll once, print the trace
  healpipe eval [--planner claude]                 submit every scenario, poll, print a scorecard
  healpipe eval --planner claude --record DIR      ...and save each Claude investigation for replay
  healpipe eval --planner replay                   re-run recorded Claude decisions, no API key needed
  healpipe jobs                                    list jobs in state/jobs.json
  healpipe poll [--planner claude] [--dry-run]     run the sentinel once over existing state
  healpipe reset                                   delete state/
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

from .evaluation import make_env, run_scenarios, scorecard
from .faults import SCENARIOS
from .jobs import JobStore
from .planners import ClaudePlanner, RulePlanner
from .replay import ReplayPlanner


def _planner(args):
    if args.planner == "claude":
        try:
            return ClaudePlanner(model=args.model, effort=args.effort, record_dir=args.record)
        except TypeError as e:  # raised by the SDK when no credentials resolve
            sys.exit(f"Claude planner needs Anthropic credentials (e.g. export ANTHROPIC_API_KEY=...): {e}")
    if args.planner == "replay":
        if not any(Path(args.recordings).glob("*.json")):
            sys.exit(
                f"No Claude recordings in {args.recordings}/. Record once with a key:\n"
                f"  healpipe eval --planner claude --record {args.recordings}"
            )
        return ReplayPlanner(args.recordings)
    return RulePlanner()


def _print_poll(report) -> None:
    print(f"sentinel poll: cursor {report.cursor_before} -> {report.cursor_after}, "
          f"investigated {len(report.handled)}, skipped (already processed) {len(report.skipped)}")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="healpipe")
    p.add_argument("--state", default="state", help="sentinel/runner state directory")
    p.add_argument("--runs", default="runs", help="job inputs and traces")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("scenarios")
    sub.add_parser("jobs")
    sub.add_parser("reset")
    for name in ("run", "eval", "poll"):
        sp = sub.add_parser(name)
        sp.add_argument("--planner", choices=["rules", "claude", "replay"], default="rules")
        sp.add_argument("--record", metavar="DIR", help="with --planner claude: save each investigation for replay")
        sp.add_argument("--recordings", default="docs/claude_recordings", help="with --planner replay: where recordings live")
        sp.add_argument("--model", default="claude-opus-5-5")
        sp.add_argument("--effort", default="medium", choices=["low", "medium", "high", "xhigh", "max"])
        if name != "poll":
            sp.add_argument("--data", default="data/pbmc3k_counts.h5ad")
        if name != "eval":
            sp.add_argument("--dry-run", action="store_true", help="shadow mode: writes become would_apply, no relaunch")
        if name == "run":
            sp.add_argument("--scenario", required=True, choices=sorted(SCENARIOS))
    args = p.parse_args(argv)

    if args.cmd == "scenarios":
        for s in SCENARIOS.values():
            print(f"{s.name:<26} {s.job_type:<9} expect={s.expected:<9} {s.description}")
        return 0
    if args.cmd == "reset":
        shutil.rmtree(args.state, ignore_errors=True)
        print(f"removed {args.state}/")
        return 0
    if args.cmd == "jobs":
        path = Path(args.state) / "jobs.json"
        for j in JobStore(path).all() if path.exists() else []:
            print(f"{j.id}  rev={j.rev:<4} {j.job_type:<9} {j.status:<10} attempts={j.attempts}  {j.error or ''}")
        return 0

    planner = _planner(args)
    if args.cmd == "poll":
        env = make_env(args.state, args.runs, planner, shadow=args.dry_run)
        report = env.sentinel.poll()
        _print_poll(report)
        for job_id, o in report.handled.items():
            print(f"  {job_id}: {o.outcome}  {o.detail}")
        return 0

    data = Path(args.data)
    if not data.exists():
        print(f"{data} not found. Run: python scripts/fetch_data.py", file=sys.stderr)
        return 2

    if args.cmd == "run":
        env = make_env(args.state, args.runs, planner, shadow=args.dry_run)
        job_id = env.runner.submit(args.scenario, data)
        job = env.api.get_job(job_id)
        print(f"runner: {job_id} ({job['job_type']}) -> {job['status']}  {job['error'] or ''}")
        report = env.sentinel.poll()
        _print_poll(report)
        if job_id in env.sentinel.traces:
            print(env.sentinel.traces[job_id].to_markdown())
        return 0

    # eval: fresh, isolated state so the scorecard is reproducible
    eval_dir = Path(args.runs) / "eval"
    env = make_env(eval_dir / "state", eval_dir, planner, fresh=True)
    rows, first, second = run_scenarios(env, list(SCENARIOS), data)
    table = scorecard(rows, planner.name)
    print(table)
    _print_poll(first)
    _print_poll(second)
    (Path(args.runs) / f"eval.{planner.name}.md").write_text(table + "\n")
    return 0 if all(r.correct for r in rows) else 1


if __name__ == "__main__":
    sys.exit(main())
