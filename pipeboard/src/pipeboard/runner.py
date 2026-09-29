"""Runs one job to completion. Started by JobManager as its own process group.

    python -m pipeboard.runner --job-dir runs/<job_id>

stdout is run.log. The runner writes state.json transitions and always writes
report.html. It never overwrites a `cancelled` state set by the server.
"""

from __future__ import annotations

import argparse
import json
import signal
import sys
import traceback
from pathlib import Path

from .jobs import now, read_state, write_state


def _log(msg: str) -> None:
    print(f"{now()}  {msg}", flush=True)


def _finish(job_dir: Path, **fields) -> None:
    if read_state(job_dir)["status"] == "running":
        write_state(job_dir, ended_at=now(), **fields)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="pipeboard.runner")
    ap.add_argument("--job-dir", required=True)
    args = ap.parse_args(argv)
    job_dir = Path(args.job_dir)
    job = json.loads((job_dir / "job.json").read_text())

    # SIGTERM from cancel: exit quietly. The server has already recorded `cancelled`.
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))

    if read_state(job_dir)["status"] != "queued":
        return 0
    write_state(job_dir, status="running", started_at=now())
    _log(f"job {job['id']} started with {json.dumps(job['params'])}")

    # Heavy imports after the state flip, so the UI shows "running" right away.
    from . import pipeline, report

    state = read_state(job_dir)
    try:
        metrics = pipeline.run(job["data_path"], job["params"], log=_log, out_dir=job_dir, sample_col=job.get("sample_col"))
    except pipeline.PipelineError as e:
        _log(f"FAILED: {e}")
        (job_dir / "report.html").write_text(report.render({**state, "status": "failed", "ended_at": now()}, job["params"], None, str(e), job.get("sample_col")))
        _finish(job_dir, status="failed", error=str(e))
        return 1
    except Exception as e:  # unexpected: short error in state, full traceback in the log
        traceback.print_exc()
        msg = f"{type(e).__name__}: {e}"
        (job_dir / "report.html").write_text(report.render({**state, "status": "failed", "ended_at": now()}, job["params"], None, msg, job.get("sample_col")))
        _finish(job_dir, status="failed", error=msg[:300])
        return 1

    (job_dir / "report.html").write_text(report.render({**state, "status": "succeeded", "ended_at": now()}, job["params"], metrics, None, job.get("sample_col")))
    _log(f"report written: runs/{job_dir.name}/report.html")
    _finish(job_dir, status="succeeded", error=None)
    _log("job succeeded")
    return 0


if __name__ == "__main__":
    sys.exit(main())
