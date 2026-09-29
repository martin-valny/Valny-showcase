import pytest

from conftest import TINY_PARAMS
from fixtures.synthetic import write_tiny_h5ad
from pipeboard import pipeline, report


@pytest.fixture
def tiny(tmp_path):
    return write_tiny_h5ad(tmp_path / "tiny.h5ad")


def test_happy_path_produces_embedding_and_report(tiny, tmp_path):
    lines = []
    m = pipeline.run(tiny, TINY_PARAMS, log=lines.append, out_dir=tmp_path, sample_col="batch")
    assert m["n_cells_before"] == 50 and 0 < m["n_cells_after_qc"] <= 50
    assert len(m["umap"]) == m["n_cells_after_qc"] and len(m["umap"][0]) == 2
    assert set(m["groups"]) == {"a", "b"}
    assert any(line.startswith("[embed] done") for line in lines)
    assert (tmp_path / "adata.h5ad").exists()

    html = report.render({"id": "t1", "status": "succeeded"}, TINY_PARAMS, m, sample_col="batch")
    out = tmp_path / "report.html"
    out.write_text(html)
    assert out.exists() and "data:image/png;base64," in html
    assert "batch = a" in html and "<script" not in html  # self-contained, static


def test_qc_removing_every_cell_is_a_readable_failure(tiny, tmp_path):
    params = {**TINY_PARAMS, "min_genes": 10_000}
    with pytest.raises(pipeline.PipelineError) as e:
        pipeline.run(tiny, params, log=lambda _: None)
    msg = str(e.value)
    assert "QC removed all 50 cells" in msg and "min_genes=10000: 0 pass" in msg

    html = report.render({"id": "t2", "status": "failed"}, params, None, error=msg)
    assert "No embedding (job failed)" in html and "QC removed all 50 cells" in html


def test_unknown_sample_column_fails_early(tiny):
    with pytest.raises(pipeline.PipelineError, match="not found in obs"):
        pipeline.run(tiny, TINY_PARAMS, log=lambda _: None, sample_col="donor")
