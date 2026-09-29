"""The runner: executes jobs and writes job records.

To the runner, the scRNA pipeline is a black box it invokes. The runner knows
nothing about agents. It accepts config patches and relaunch requests through
its API (`api.JobAPI`), just as it would from a human operator.
"""

from __future__ import annotations

from pathlib import Path

from .api import Rejected
from .config import AGENT_EDITABLE, STEPS, RunConfig
from .faults import SCENARIOS, materialize
from .jobs import JobRecord, JobStore
from .pipeline import Pipeline


class Runner:
    def __init__(self, store: JobStore, workdir: Path | str, max_attempts: int = 3):
        self.store = store
        self.max_attempts = max_attempts
        self.workdir = Path(workdir)
        self._pipes: dict[str, Pipeline] = {}  # per-job step cache; lost on restart, which is fine

    # ------------------------------------------------------------ lifecycle

    def submit(self, scenario_name: str, clean_path: Path | str) -> str:
        s = SCENARIOS[scenario_name]
        job_id = self.store.new_id()
        input_path = materialize(s, Path(clean_path), self.workdir / job_id)
        job = JobRecord(id=job_id, job_type=s.job_type, scenario=s.name, input_uri=str(input_path), config=s.config.to_dict())
        job.events.append({"kind": "submitted", "scenario": s.name})
        self.store.put(job)
        self._execute(job_id, "load")
        return job_id

    def apply_patch(self, job_id: str, patch: dict) -> JobRecord:
        """Apply an already-validated patch and note which steps it invalidates."""
        job = self.store.get(job_id)
        old = {k: job.config[k] for k in patch}
        job.config.update(patch)
        for key in patch:
            first = AGENT_EDITABLE[key][1]
            if job.pending_from is None or STEPS.index(first) < STEPS.index(job.pending_from):
                job.pending_from = first
        job.events.append({"kind": "config_patch", "old": old, "new": dict(patch)})
        return self.store.put(job)

    def relaunch(self, job_id: str) -> JobRecord:
        job = self.store.get(job_id)
        if job.status != "failed":
            raise Rejected(f"job is {job.status}; only failed jobs can be relaunched")
        if job.pending_from is None:
            raise Rejected("no config change since the last run; relaunching would reproduce the same failure")
        if job.attempts >= self.max_attempts:
            raise Rejected(f"relaunch budget exhausted ({self.max_attempts}); escalate")
        job.attempts += 1
        self.store.put(job)
        return self._execute(job_id, job.pending_from)

    # ------------------------------------------------------------ execution

    def _execute(self, job_id: str, from_step: str) -> JobRecord:
        job = self.store.get(job_id)
        job.status = "running"
        self.store.put(job)

        cfg = RunConfig(**job.config)
        pipe = self._pipes.get(job_id)
        if pipe is None:
            pipe = self._pipes[job_id] = Pipeline(job.input_uri, cfg)
        pipe.cfg = cfg
        idx = STEPS.index(from_step)
        if idx > 0 and STEPS[idx - 1] not in pipe.cache:
            from_step = "load"  # no cached upstream output (e.g. runner restarted)
        result = pipe.run(from_step)

        job = self.store.get(job_id)
        failed = [c.to_dict() for c in result.failed_checks]
        job.status = "succeeded" if result.status == "passed" else "failed"
        job.failed_checks = failed
        job.error = f"{failed[0]['step']}.{failed[0]['name']}: {failed[0]['message']}" if failed else None
        job.pending_from = None
        job.events.append(
            {"kind": "run", "from_step": from_step, "status": job.status, "failed_checks": [f"{c['step']}.{c['name']}" for c in failed]}
        )
        return self.store.put(job)

    def reference_agreement(self, job_id: str) -> float | None:
        pipe = self._pipes.get(job_id)
        return pipe.reference_agreement() if pipe else None
