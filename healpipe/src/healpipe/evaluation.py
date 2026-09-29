"""Scenario driver and scorecard: runner submits, sentinel polls, the outcome is graded."""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from .api import JobAPI
from .faults import SCENARIOS
from .jobs import JobStore
from .planners import Outcome
from .runner import Runner
from .sentinel import PollReport, Sentinel


@dataclass
class Row:
    job_id: str
    scenario: str
    job_type: str
    expected: str
    outcome: Outcome
    correct: bool
    note: str
    agreement: float | None


def grade(scenario: str, outcome: Outcome, job: dict) -> tuple[bool, str]:
    s = SCENARIOS[scenario]
    if outcome.detail.startswith("replay diverged"):
        return False, f"stale recording: {outcome.detail}"
    # Consistency: a write that was applied and then followed by an escalation means the
    # planner changed production config and still handed the job to a human.
    if outcome.outcome == "escalated" and outcome.applied:
        return False, f"inconsistent: applied {outcome.applied} and then escalated"
    if outcome.outcome != s.expected:
        return False, f"expected {s.expected}, got {outcome.outcome}"
    wrong = {k: job["config"][k] for k, v in s.expected_fix.items() if job["config"][k] != v}
    if wrong:
        return False, f"wrong fix: {wrong}"
    return True, ""


@dataclass
class Environment:
    store: JobStore
    runner: Runner
    api: JobAPI
    sentinel: Sentinel


def make_env(state_dir: Path, runs_dir: Path, planner, fresh: bool = False, shadow: bool = False) -> Environment:
    """state_dir holds jobs.json / cursor.json / processed.json; runs_dir holds job inputs and traces."""
    state_dir, runs_dir = Path(state_dir), Path(runs_dir)
    if fresh and state_dir.exists():
        shutil.rmtree(state_dir)
    store = JobStore(state_dir / "jobs.json")
    runner = Runner(store, runs_dir / "inputs")
    api = JobAPI(runner)
    return Environment(store, runner, api, Sentinel(api, planner, state_dir, runs_dir / "traces", shadow=shadow))


def run_scenarios(env: Environment, names: list[str], clean_path: Path) -> tuple[list[Row], PollReport, PollReport]:
    job_ids = {env.runner.submit(n, clean_path): n for n in names}
    first = env.sentinel.poll()
    second = env.sentinel.poll()  # nothing new: the dedup / cursor check
    rows = []
    for job_id, name in job_ids.items():
        job = env.api.get_job(job_id)
        outcome = first.handled.get(job_id) or Outcome("clean", detail="never failed; sentinel not involved")
        ok, note = grade(name, outcome, job)
        rows.append(Row(job_id, name, job["job_type"], SCENARIOS[name].expected, outcome, ok, note, env.runner.reference_agreement(job_id)))
    return rows, first, second


def scorecard(rows: list[Row], planner_name: str) -> str:
    lines = [
        "| job | scenario | type | expected | outcome | correct | writes | tool calls | label agreement |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        a = f"{r.agreement:.0%}" if r.agreement is not None else "-"
        writes = ", ".join(f"{c['key']}={c['new']}" for c in (r.outcome.applied or r.outcome.proposed)) or "-"
        ok = "yes" if r.correct else f"**no** ({r.note})"
        lines.append(f"| {r.job_id} | {r.scenario} | {r.job_type} | {r.expected} | {r.outcome.outcome} | {ok} | {writes} | {r.outcome.tool_calls} | {a} |")
    n_ok = sum(r.correct for r in rows)
    lines.append(f"\n**{n_ok}/{len(rows)} correct** (planner: {planner_name})")
    return "\n".join(lines)
