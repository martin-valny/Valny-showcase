"""The runner and the sentinel are separate: the sentinel only needs something shaped like JobAPI."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

from healpipe.api import Rejected, validate_patch
from healpipe.planners import finish
from healpipe.sentinel import Sentinel


class FakeJobAPI:
    """In-memory stand-in for the runner. No pipeline, no data files."""

    def __init__(self):
        self.calls = []
        self.jobs = {
            "j1": {
                "id": "j1", "job_type": "annotate", "scenario": "species_mislabel", "status": "failed", "rev": 3,
                "error": "qc.mito_genes_detected: 0 mitochondrial genes matched prefix 'mt-'",
                "failed_checks": [{"step": "qc", "name": "mito_genes_detected", "message": "0 matched", "metrics": {}}],
                "config": {"species": "mouse", "input_scale": "counts", "orientation": "cells_x_genes", "min_genes": 200},
                "events": [], "attempts": 0, "attempts_left": 3, "input_uri": "unused",
            }
        }

    def list_failed_jobs(self, since_cursor=0):
        jobs = [j for j in self.jobs.values() if j["status"] == "failed" and j["rev"] > since_cursor]
        return jobs, max([since_cursor] + [j["rev"] for j in jobs])

    def get_job(self, job_id):
        return dict(self.jobs[job_id])

    def set_job_config(self, job_id, patch, *, dry_run=False):
        self.calls.append(("set_job_config", patch, dry_run))
        validate_patch(self.jobs[job_id], patch)
        if dry_run:
            return {"status": "would_apply", "patch": patch}
        self.jobs[job_id]["config"].update(patch)
        return {"status": "applied", "patch": patch}

    def request_relaunch(self, job_id):
        self.calls.append(("request_relaunch", job_id))
        job = self.jobs[job_id]
        job["status"] = "succeeded" if job["config"]["species"] == "human" else "failed"
        job["rev"] += 1
        return {"status": job["status"], "from_step": "qc", "failed_checks": [], "job_error": None, "attempts_left": 2}


class Scripted:
    name = "scripted"

    def investigate(self, inv):
        inv.call("inspect_job", {"rationale": "x"})
        inv.call("set_job_config", {"rationale": "x", "key": "species", "value": "human", "dry_run": False})
        inv.call("request_relaunch", {"rationale": "x"})
        return finish(inv)


def test_sentinel_runs_against_fake_api(tmp_path):
    api = FakeJobAPI()
    report = Sentinel(api, Scripted(), tmp_path).poll()
    assert report.handled["j1"].outcome == "fixed"
    assert api.calls == [("set_job_config", {"species": "human"}, False), ("request_relaunch", "j1")]


def test_sentinel_side_does_not_import_pipeline():
    code = "import sys, healpipe.sentinel, healpipe.planners; print('healpipe.pipeline' in sys.modules, 'healpipe.runner' in sys.modules)"
    src = str(Path(__file__).resolve().parents[1] / "src")
    env = {**os.environ, "PYTHONPATH": src + os.pathsep + os.environ.get("PYTHONPATH", "")}
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True, env=env).stdout.split()
    assert out == ["False", "False"]


def test_runner_relaunches_from_the_dirty_step(make):
    env = make()
    job_id = env.runner.submit("species_mislabel", env.clean)
    env.api.set_job_config(job_id, {"species": "human"})
    out = env.api.request_relaunch(job_id)
    assert out["from_step"] == "qc" and out["status"] == "succeeded"


def test_runner_refuses_blind_retry_and_caps_attempts(make):
    env = make()
    env.runner.max_attempts = 1
    job_id = env.runner.submit("negative_values", env.clean)
    with pytest.raises(Rejected, match="no config change"):
        env.api.request_relaunch(job_id)
    env.api.set_job_config(job_id, {"input_scale": "log1p"})
    env.api.request_relaunch(job_id)
    env.api.set_job_config(job_id, {"input_scale": "counts"})
    with pytest.raises(Rejected, match="budget exhausted"):
        env.api.request_relaunch(job_id)
