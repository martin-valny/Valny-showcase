"""Background jobs: one runner subprocess per job, with state kept on disk under runs/<job_id>/.

    runs/<job_id>/job.json     parameters the job was started with
    runs/<job_id>/state.json   id, status, pid, started_at, ended_at, error
    runs/<job_id>/run.log      append-only stdout/stderr of the runner
    runs/<job_id>/report.html  written by the runner on success *and* failure

The job list is simply a scan of runs/*/state.json, with no database.
"""

from __future__ import annotations

import json
import os
import secrets
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import yaml

TERMINAL = {"succeeded", "failed", "cancelled"}
LOG_CHUNK = 64 * 1024


class JobError(Exception):
    """Bad request for a job operation. `status` maps to an HTTP code."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


# ------------------------------------------------------------------ schema


def load_schema(path: Path | str) -> dict:
    schema = yaml.safe_load(Path(path).read_text())
    if not isinstance(schema, dict) or not isinstance(schema.get("parameters"), list):
        raise ValueError(f"{path}: expected a top-level 'parameters' list")
    for p in schema["parameters"]:
        missing = {"name", "type", "default"} - set(p)
        if missing:
            raise ValueError(f"{path}: parameter {p.get('name', '?')!r} is missing {sorted(missing)}")
    return schema


def validate_params(schema: dict, values: dict) -> dict:
    """Fill defaults, coerce types, and check bounds. Raises JobError(422) listing every problem."""
    specs = {p["name"]: p for p in schema["parameters"]}
    errors = [f"unknown parameter {k!r}" for k in values if k not in specs]
    out = {}
    for name, p in specs.items():
        v = values.get(name, p["default"])
        try:
            if p["type"] == "int":
                if isinstance(v, bool) or float(v) != int(float(v)):
                    raise ValueError
                v = int(float(v))
            elif p["type"] == "float":
                v = float(v)
            elif p["type"] == "bool":
                if not isinstance(v, bool):
                    raise ValueError
            elif p["type"] == "choice":
                if v not in p.get("options", []):
                    raise ValueError
        except (TypeError, ValueError):
            errors.append(f"{name}: {v!r} is not a valid {p['type']}")
            continue
        if "min" in p and v < p["min"]:
            errors.append(f"{name}: {v} is below the minimum {p['min']}")
        if "max" in p and v > p["max"]:
            errors.append(f"{name}: {v} is above the maximum {p['max']}")
        out[name] = v
    if errors:
        raise JobError("; ".join(errors), 422)
    return out


# ------------------------------------------------------------------ state


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def read_state(job_dir: Path) -> dict:
    return json.loads((job_dir / "state.json").read_text())


def write_state(job_dir: Path, **fields) -> dict:
    """Merge `fields` into state.json atomically."""
    path = job_dir / "state.json"
    state = json.loads(path.read_text()) if path.exists() else {}
    state.update(fields)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2))
    os.replace(tmp, path)
    return state


def _alive(pid: int | None) -> bool:
    if not pid:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    # A zombie child still "exists"; reap it if it is ours.
    try:
        done, _ = os.waitpid(pid, os.WNOHANG)
        return done == 0
    except ChildProcessError:
        return True


# ------------------------------------------------------------------ manager


class JobManager:
    def __init__(self, runs_dir: Path | str, data_path: Path | str, schema_path: Path | str, command: list[str] | None = None):
        self.runs_dir = Path(runs_dir)
        self.data_path = Path(data_path)
        self.schema_path = Path(schema_path)
        # Tests pass a fake command. The default is the real runner.
        self.command = command or [sys.executable, "-m", "pipeboard.runner"]

    def _dir(self, job_id: str) -> Path:
        d = self.runs_dir / job_id
        if "/" in job_id or ".." in job_id or not (d / "state.json").exists():
            raise JobError(f"job {job_id!r} not found", 404)
        return d

    def create(self, params: dict, sample_col: str | None = None) -> dict:
        if not self.data_path.exists():
            raise JobError(f"{self.data_path} not found. Run: python scripts/fetch_data.py", 409)
        clean = validate_params(load_schema(self.schema_path), params or {})
        job_id = f"{datetime.now():%Y%m%d-%H%M%S}-{secrets.token_hex(2)}"
        job_dir = self.runs_dir / job_id
        job_dir.mkdir(parents=True)
        (job_dir / "job.json").write_text(
            json.dumps({"id": job_id, "params": clean, "sample_col": sample_col or None, "data_path": str(self.data_path.resolve())}, indent=2)
        )
        write_state(job_dir, id=job_id, status="queued", pid=None, created_at=now(), started_at=None, ended_at=None, error=None)
        with open(job_dir / "run.log", "ab") as log:
            proc = subprocess.Popen(
                [*self.command, "--job-dir", str(job_dir)],
                stdout=log,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                start_new_session=True,  # own process group: survives the browser/server, cancellable as a group
                env={**os.environ, "PYTHONUNBUFFERED": "1"},
            )
        return write_state(job_dir, pid=proc.pid)

    def get(self, job_id: str) -> dict:
        job_dir = self._dir(job_id)
        state = read_state(job_dir)
        if state["status"] in ("queued", "running") and state.get("pid") and not _alive(state["pid"]):
            time.sleep(0.2)  # the runner may be writing its final state right now
            state = read_state(job_dir)
            if state["status"] in ("queued", "running"):
                state = write_state(job_dir, status="failed", ended_at=now(), error="runner exited unexpectedly (see run.log)")
        job = json.loads((job_dir / "job.json").read_text())
        return {**state, "params": job["params"], "sample_col": job.get("sample_col"), "has_report": (job_dir / "report.html").exists()}

    def list(self) -> list[dict]:
        if not self.runs_dir.exists():
            return []
        ids = sorted((p.parent.name for p in self.runs_dir.glob("*/state.json")), reverse=True)
        return [self.get(i) for i in ids]

    def cancel(self, job_id: str) -> dict:
        state = self.get(job_id)
        if state["status"] in TERMINAL:
            raise JobError(f"job is already {state['status']}", 409)
        pid = state.get("pid")
        job_dir = self._dir(job_id)
        write_state(job_dir, status="cancelled", ended_at=now(), error="cancelled by user")
        if pid:
            try:
                os.killpg(pid, signal.SIGTERM)  # pid == pgid because of start_new_session
                for _ in range(50):
                    if not _alive(pid):
                        break
                    time.sleep(0.1)
                else:
                    os.killpg(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        with open(job_dir / "run.log", "a") as f:
            f.write("[pipeboard] job cancelled by user\n")
        return self.get(job_id)

    def read_log(self, job_id: str, offset: int = 0) -> dict:
        job_dir = self._dir(job_id)
        path = job_dir / "run.log"
        size = path.stat().st_size if path.exists() else 0
        offset = max(0, min(offset, size))
        with open(path, "rb") as f:
            f.seek(offset)
            chunk = f.read(LOG_CHUNK)
        new_offset = offset + len(chunk)
        done = read_state(job_dir)["status"] in TERMINAL and new_offset >= size
        return {"text": chunk.decode("utf-8", errors="replace"), "offset": new_offset, "done": done}

    def report_path(self, job_id: str) -> Path:
        path = self._dir(job_id) / "report.html"
        if not path.exists():
            raise JobError("report not available yet", 404)
        return path
