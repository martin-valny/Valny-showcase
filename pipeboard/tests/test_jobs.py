import json
import os
import time

import pytest

from conftest import TINY_PARAMS
from pipeboard.jobs import JobError, JobManager, write_state


def _manager(project, command=None):
    return JobManager(project / "runs", project / "data" / "pbmc3k_counts.h5ad", project / "schema" / "pipeline.yaml", command=command)


def _wait(jobs, job_id, timeout=120):
    t0 = time.time()
    while time.time() - t0 < timeout:
        s = jobs.get(job_id)
        if s["status"] in ("succeeded", "failed", "cancelled"):
            return s
        time.sleep(0.2)
    raise AssertionError(f"job {job_id} did not finish: {jobs.get(job_id)}")


def test_real_runner_succeeds_and_writes_outputs(project):
    jobs = _manager(project)
    state = jobs.create(TINY_PARAMS, sample_col="batch")
    assert state["status"] in ("queued", "running") and state["pid"]
    final = _wait(jobs, state["id"])
    assert final["status"] == "succeeded", (project / "runs" / state["id"] / "run.log").read_text()
    job_dir = project / "runs" / state["id"]
    on_disk = json.loads((job_dir / "state.json").read_text())
    assert on_disk["status"] == "succeeded" and on_disk["started_at"] and on_disk["ended_at"]
    assert (job_dir / "report.html").exists() and "job succeeded" in (job_dir / "run.log").read_text()


def test_real_runner_failure_is_recorded_with_reason(project):
    jobs = _manager(project)
    state = jobs.create({**TINY_PARAMS, "min_genes": 5000})
    final = _wait(jobs, state["id"])
    assert final["status"] == "failed" and "QC removed all" in final["error"]
    assert "No embedding" in jobs.report_path(state["id"]).read_text()


def test_cancel_kills_process_group_and_marks_cancelled(project, slow_command):
    jobs = _manager(project, slow_command)
    state = jobs.create(TINY_PARAMS)
    time.sleep(0.5)
    out = jobs.cancel(state["id"])
    assert out["status"] == "cancelled"
    with pytest.raises(ProcessLookupError):
        os.killpg(state["pid"], 0)
    with pytest.raises(JobError) as e:
        jobs.cancel(state["id"])
    assert e.value.status == 409


def test_log_offsets_advance(project, slow_command):
    jobs = _manager(project, slow_command)
    job_id = jobs.create(TINY_PARAMS)["id"]
    time.sleep(0.6)
    first = jobs.read_log(job_id, 0)
    assert "tick 0" in first["text"] and not first["done"]
    time.sleep(0.4)
    second = jobs.read_log(job_id, first["offset"])
    assert second["offset"] > first["offset"] and "tick 0" not in second["text"]
    jobs.cancel(job_id)


def test_dead_runner_is_reconciled_to_failed(project, slow_command):
    jobs = _manager(project, slow_command)
    state = jobs.create(TINY_PARAMS)
    os.killpg(state["pid"], 9)  # simulate a crash, bypassing cancel()
    time.sleep(0.3)
    final = jobs.get(state["id"])
    assert final["status"] == "failed" and "exited unexpectedly" in final["error"]


def test_list_scans_state_files_and_rejects_bad_ids(project):
    jobs = _manager(project)
    (project / "runs" / "20990101-000000-abcd").mkdir(parents=True)
    write_state(project / "runs" / "20990101-000000-abcd", id="20990101-000000-abcd", status="succeeded", pid=None)
    (project / "runs" / "20990101-000000-abcd" / "job.json").write_text(json.dumps({"params": {}}))
    assert [j["id"] for j in jobs.list()] == ["20990101-000000-abcd"]
    with pytest.raises(JobError) as e:
        jobs.get("../etc")
    assert e.value.status == 404
