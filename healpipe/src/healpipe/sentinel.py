"""The sentinel: polls the runner for failed jobs and investigates each one once.

The sentinel sees jobs, not the DAG. It only talks to `JobAPI`, never imports
the pipeline, and keeps two small state files:

* state/cursor.json:    the last job revision it has seen
* state/processed.json: job ids that reached a terminal outcome (dedup)
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from .planners import Outcome
from .toolkits import Investigation
from .trace import Trace

TERMINAL = {"fixed", "escalated"}


@dataclass
class PollReport:
    cursor_before: int
    cursor_after: int
    handled: dict[str, Outcome] = field(default_factory=dict)
    skipped: list[str] = field(default_factory=list)  # already processed


class Sentinel:
    def __init__(self, api, planner, state_dir: Path | str, traces_dir: Path | str | None = None, shadow: bool = False):
        self.api, self.planner, self.shadow = api, planner, shadow
        self.state_dir = Path(state_dir)
        self.traces_dir = Path(traces_dir) if traces_dir else None
        self.traces: dict[str, Trace] = {}

    # ------------------------------------------------------------ state

    def _read(self, name: str, default):
        p = self.state_dir / name
        return json.loads(p.read_text()) if p.exists() else default

    def _write(self, name: str, value) -> None:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        (self.state_dir / name).write_text(json.dumps(value, indent=2))

    @property
    def processed(self) -> list[str]:
        return self._read("processed.json", [])

    # ------------------------------------------------------------ poll

    def poll(self) -> PollReport:
        cursor = self._read("cursor.json", {"rev": 0})["rev"]
        jobs, next_cursor = self.api.list_failed_jobs(cursor)
        report = PollReport(cursor, next_cursor)

        for job in jobs:
            if job["id"] in self.processed:
                report.skipped.append(job["id"])
                continue
            report.handled[job["id"]] = self._investigate(job)

        # Jobs touched during this poll (e.g. relaunched) have newer revs; that is fine,
        # the processed set covers them.
        self._write("cursor.json", {"rev": max(next_cursor, report.cursor_before)})
        return report

    def _investigate(self, job: dict) -> Outcome:
        trace = Trace(job_id=job["id"], scenario=job["scenario"], job_type=job["job_type"], planner=self.planner.name)
        trace.add("job_failed", rev=job["rev"], error=job["error"], failed_checks=job["failed_checks"])
        inv = Investigation(job["id"], self.api, trace, traces_dir=self.traces_dir, shadow=self.shadow)
        outcome = self.planner.investigate(inv)

        first = job["failed_checks"][0] if job["failed_checks"] else {}
        trace.summary = {
            "symptom": job["error"],
            "check": f"{first.get('step')}.{first.get('name')}" if first else None,
            "outcome": outcome.outcome,
            "changes": outcome.applied or outcome.proposed,
            "escalation_reason": inv.escalation["reason"] if inv.escalation else None,
        }
        if self.traces_dir:
            trace.write(self.traces_dir)
        self.traces[job["id"]] = trace

        if outcome.outcome in TERMINAL:
            self._write("processed.json", self.processed + [job["id"]])
        return outcome
