"""HTTP API and static UI.

    GET    /                       UI
    GET    /api/schema             form spec (schema/pipeline.yaml as JSON)
    GET    /api/data/status        does the input h5ad exist; size; eligible sample columns
    POST   /api/jobs               {"params": {...}, "sample_col": null} -> start a job
    GET    /api/jobs               list
    GET    /api/jobs/{id}          status
    GET    /api/jobs/{id}/logs     ?offset=<bytes> -> {text, offset, done}
    DELETE /api/jobs/{id}          cancel
    GET    /api/jobs/{id}/report   report.html (?download=1 to save)
"""

from __future__ import annotations

from pathlib import Path

import anndata as ad
from fastapi import Body, FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .jobs import JobError, JobManager, load_schema

STATIC = Path(__file__).parent / "static"


def _sample_columns(path: Path) -> tuple[int, int, list[dict]]:
    """Low-cardinality obs columns a user might pick as sample/group. Read in backed mode, so X is not loaded."""
    a = ad.read_h5ad(path, backed="r")
    try:
        cols = []
        for name in a.obs.columns:
            s = a.obs[name]
            if s.dtype.name in ("category", "object", "string", "bool"):
                n = s.nunique()
                if 2 <= n <= 50:
                    cols.append({"name": name, "n_values": int(n)})
        return a.n_obs, a.n_vars, cols
    finally:
        a.file.close()


def create_app(root: Path | str = ".", command: list[str] | None = None) -> FastAPI:
    root = Path(root).resolve()
    schema_path = root / "schema" / "pipeline.yaml"
    data_path = root / "data" / "pbmc3k_counts.h5ad"
    jobs = JobManager(root / "runs", data_path, schema_path, command=command)
    app = FastAPI(title="pipeboard")

    def _call(fn, *a, **kw):
        try:
            return fn(*a, **kw)
        except JobError as e:
            raise HTTPException(e.status, str(e)) from None

    @app.get("/api/schema")
    def schema():
        return load_schema(schema_path)  # re-read each time: edit the YAML, reload the page

    @app.get("/api/data/status")
    def data_status():
        if not data_path.exists():
            return {"exists": False, "path": str(data_path.relative_to(root)), "hint": "python scripts/fetch_data.py"}
        n_obs, n_vars, cols = _sample_columns(data_path)
        return {
            "exists": True,
            "path": str(data_path.relative_to(root)),
            "size_bytes": data_path.stat().st_size,
            "n_obs": n_obs,
            "n_vars": n_vars,
            "sample_columns": cols,
        }

    @app.post("/api/jobs", status_code=201)
    def start(body: dict = Body(default_factory=dict)):
        sample_col = body.get("sample_col") or None
        if sample_col is not None and data_path.exists():
            eligible = [c["name"] for c in _sample_columns(data_path)[2]]
            if sample_col not in eligible:
                raise HTTPException(422, f"sample_col {sample_col!r} is not one of {eligible}")
        return _call(jobs.create, body.get("params") or {}, sample_col)

    @app.get("/api/jobs")
    def list_jobs():
        return _call(jobs.list)

    @app.get("/api/jobs/{job_id}")
    def get_job(job_id: str):
        return _call(jobs.get, job_id)

    @app.get("/api/jobs/{job_id}/logs")
    def logs(job_id: str, offset: int = 0):
        return _call(jobs.read_log, job_id, offset)

    @app.delete("/api/jobs/{job_id}")
    def cancel(job_id: str):
        return _call(jobs.cancel, job_id)

    @app.get("/api/jobs/{job_id}/report")
    def job_report(job_id: str, download: bool = False):
        path = _call(jobs.report_path, job_id)
        headers = {"Content-Disposition": f'attachment; filename="pipeboard-{job_id}.html"'} if download else None
        return FileResponse(path, media_type="text/html", headers=headers)

    app.mount("/", StaticFiles(directory=STATIC, html=True), name="static")
    return app
