"""JobAPI: the runner's narrow interface, and the only thing the sentinel talks to.

    list_failed_jobs(since_cursor) -> (jobs, next_cursor)
    get_job(id)
    set_job_config(id, patch, *, dry_run=False)
    request_relaunch(id)

Writes are gated here. `validate_patch` is the single place that decides
whether a patch is allowed, and dry-run and apply both go through it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .config import AGENT_EDITABLE, JOB_TYPE_KEYS, RunConfig

if TYPE_CHECKING:  # keep the sentinel side free of pipeline imports
    from .runner import Runner

THRESHOLD_KEYS = {"min_genes", "max_pct_mito", "min_cells_per_gene", "target_sum"}


class Rejected(Exception):
    """A write or relaunch the API refused."""


def validate_patch(job: dict, patch: dict) -> None:
    if not isinstance(patch, dict) or not patch:
        raise Rejected("patch must be a non-empty object")
    owned = JOB_TYPE_KEYS[job["job_type"]]
    for key, value in patch.items():
        if key in THRESHOLD_KEYS:
            raise Rejected(f"'{key}' is a QC/analysis threshold owned by humans; not editable. If it looks wrong, escalate.")
        if key not in owned:
            where = [t for t, ks in JOB_TYPE_KEYS.items() if key in ks]
            hint = f" (owned by job type {where[0]!r})" if where else ""
            raise Rejected(f"'{key}' is not editable for job type {job['job_type']!r}{hint}; editable: {list(owned)}")
        allowed = AGENT_EDITABLE[key][0]
        if value not in allowed:
            raise Rejected(f"invalid value for {key}: {value!r}; allowed: {sorted(allowed)}")
        if job["config"].get(key) == value:
            raise Rejected(f"{key} is already {value!r}")


class JobAPI:
    def __init__(self, runner: "Runner"):
        self._runner = runner

    def list_failed_jobs(self, since_cursor: int = 0) -> tuple[list[dict], int]:
        jobs = [j.to_dict() for j in self._runner.store.all() if j.status == "failed" and j.rev > since_cursor]
        jobs.sort(key=lambda j: j["rev"])
        return jobs, max([since_cursor] + [j["rev"] for j in jobs])

    def get_job(self, job_id: str) -> dict:
        job = self._runner.store.get(job_id).to_dict()
        job["attempts_left"] = self._runner.max_attempts - job["attempts"]
        return job

    def set_job_config(self, job_id: str, patch: dict, *, dry_run: bool = False) -> dict:
        job = self.get_job(job_id)
        validate_patch(job, patch)
        RunConfig(**{**job["config"], **patch})  # must still build a valid config
        if dry_run:
            return {"status": "would_apply", "job_id": job_id, "patch": patch}
        updated = self._runner.apply_patch(job_id, patch)
        return {"status": "applied", "job_id": job_id, "patch": patch, "relaunch_from": updated.pending_from}

    def request_relaunch(self, job_id: str) -> dict:
        job = self._runner.relaunch(job_id)  # raises Rejected
        return {
            "job_id": job_id,
            "status": job.status,
            "from_step": job.events[-1]["from_step"],
            "error": job.error,
            "failed_checks": job.failed_checks,
            "attempts_left": self._runner.max_attempts - job.attempts,
        }
