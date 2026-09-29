"""Job records and a small JSON-file job store (state/jobs.json)."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

STATUSES = ("queued", "running", "failed", "succeeded")


@dataclass
class JobRecord:
    id: str
    job_type: str
    scenario: str
    input_uri: str
    config: dict
    status: str = "queued"
    error: str | None = None  # symptom text of the first failed check
    failed_checks: list[dict] = field(default_factory=list)
    events: list[dict] = field(default_factory=list)
    attempts: int = 0  # relaunches so far
    pending_from: str | None = None  # earliest step invalidated by config patches since the last run
    updated_at: str = ""
    rev: int = 0  # store-wide, monotonically increasing; the sentinel's cursor

    def to_dict(self) -> dict:
        return asdict(self)


class JobStore:
    """Every write bumps a global revision, so readers can ask "what changed since rev N"."""

    def __init__(self, path: Path | str):
        self.path = Path(path)
        self._rev = 0
        self._jobs: dict[str, JobRecord] = {}
        if self.path.exists():
            data = json.loads(self.path.read_text())
            self._rev = data["rev"]
            self._jobs = {k: JobRecord(**v) for k, v in data["jobs"].items()}

    def put(self, job: JobRecord) -> JobRecord:
        assert job.status in STATUSES, job.status
        self._rev += 1
        job.rev = self._rev
        job.updated_at = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
        self._jobs[job.id] = JobRecord(**json.loads(json.dumps(job.to_dict())))
        self._save()
        return self.get(job.id)

    def get(self, job_id: str) -> JobRecord:
        if job_id not in self._jobs:
            raise KeyError(f"unknown job {job_id!r}")
        return JobRecord(**json.loads(json.dumps(self._jobs[job_id].to_dict())))

    def all(self) -> list[JobRecord]:
        return [self.get(k) for k in self._jobs]

    def new_id(self) -> str:
        return f"job-{len(self._jobs) + 1:04d}"

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"rev": self._rev, "jobs": {k: v.to_dict() for k, v in self._jobs.items()}}, indent=2))
        os.replace(tmp, self.path)
