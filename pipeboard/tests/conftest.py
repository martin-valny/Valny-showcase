from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

from fixtures.synthetic import write_tiny_h5ad

REPO = Path(__file__).resolve().parents[1]

# Small params that suit the 50-cell fixture.
TINY_PARAMS = {"min_genes": 10, "max_mito_pct": 50, "n_hvgs": 100, "n_neighbors": 5}


@pytest.fixture
def project(tmp_path):
    """A project root with the real schema and the tiny dataset at data/pbmc3k_counts.h5ad."""
    (tmp_path / "schema").mkdir()
    shutil.copy(REPO / "schema" / "pipeline.yaml", tmp_path / "schema" / "pipeline.yaml")
    write_tiny_h5ad(tmp_path / "data" / "pbmc3k_counts.h5ad")
    return tmp_path


@pytest.fixture
def slow_command(tmp_path):
    """A stand-in runner that marks itself running, then sleeps (to test cancel and streaming logs)."""
    script = tmp_path / "slow_runner.py"
    script.write_text(
        "import sys, time\n"
        "from pathlib import Path\n"
        f"sys.path.insert(0, {str(REPO / 'src')!r})\n"
        "from pipeboard.jobs import write_state, now\n"
        "job_dir = Path(sys.argv[sys.argv.index('--job-dir') + 1])\n"
        "write_state(job_dir, status='running', started_at=now())\n"
        "for i in range(600):\n"
        "    print(f'tick {i}', flush=True); time.sleep(0.1)\n"
    )
    return [sys.executable, str(script)]
