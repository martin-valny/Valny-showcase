import time

from fastapi.testclient import TestClient

from conftest import TINY_PARAMS
from pipeboard.server import create_app


def test_ui_is_served(project):
    r = TestClient(create_app(project)).get("/")
    assert r.status_code == 200 and "pipeboard" in r.text


def test_missing_data_is_reported_and_blocks_jobs(project):
    (project / "data" / "pbmc3k_counts.h5ad").unlink()
    c = TestClient(create_app(project))
    status = c.get("/api/data/status").json()
    assert status["exists"] is False and status["hint"] == "python scripts/fetch_data.py"
    r = c.post("/api/jobs", json={"params": TINY_PARAMS})
    assert r.status_code == 409 and "fetch_data.py" in r.json()["detail"]


def test_data_status_lists_sample_columns(project):
    s = TestClient(create_app(project)).get("/api/data/status").json()
    assert s["exists"] and s["n_obs"] == 50 and s["size_bytes"] > 0
    assert s["sample_columns"] == [{"name": "batch", "n_values": 2}]


def test_invalid_params_are_422(project):
    r = TestClient(create_app(project)).post("/api/jobs", json={"params": {"min_genes": -5}})
    assert r.status_code == 422 and "below the minimum" in r.json()["detail"]


def test_unknown_sample_col_is_422(project):
    r = TestClient(create_app(project)).post("/api/jobs", json={"params": TINY_PARAMS, "sample_col": "../../etc"})
    assert r.status_code == 422 and "not one of ['batch']" in r.json()["detail"]
    assert not list((project / "runs").glob("*"))  # rejected before any job dir is made


def test_job_lifecycle_over_http(project, slow_command):
    c = TestClient(create_app(project, command=slow_command))
    r = c.post("/api/jobs", json={"params": TINY_PARAMS, "sample_col": None})
    assert r.status_code == 201
    job_id = r.json()["id"]

    assert [j["id"] for j in c.get("/api/jobs").json()] == [job_id]
    assert c.get(f"/api/jobs/{job_id}").json()["params"]["min_genes"] == TINY_PARAMS["min_genes"]
    assert c.get(f"/api/jobs/{job_id}/report").status_code == 404  # not finished yet

    time.sleep(0.6)
    logs = c.get(f"/api/jobs/{job_id}/logs", params={"offset": 0}).json()
    assert "tick" in logs["text"] and logs["offset"] > 0

    assert c.delete(f"/api/jobs/{job_id}").json()["status"] == "cancelled"
    assert c.delete(f"/api/jobs/{job_id}").status_code == 409
    assert c.get("/api/jobs/nope").status_code == 404


def test_report_is_served_and_downloadable(project):
    c = TestClient(create_app(project))
    job_id = c.post("/api/jobs", json={"params": {**TINY_PARAMS, "min_genes": 5000}}).json()["id"]
    for _ in range(300):
        if c.get(f"/api/jobs/{job_id}").json()["status"] == "failed":
            break
        time.sleep(0.2)
    r = c.get(f"/api/jobs/{job_id}/report")
    assert r.status_code == 200 and "QC removed all" in r.text
    d = c.get(f"/api/jobs/{job_id}/report", params={"download": 1})
    assert "attachment" in d.headers["content-disposition"]
