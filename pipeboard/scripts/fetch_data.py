"""Download public 10x PBMC3k and write raw integer counts to data/pbmc3k_counts.h5ad.

Source (public, documented): the example dataset in CZI's cellxgene repository,
    https://raw.githubusercontent.com/chanzuckerberg/cellxgene/main/example-dataset/pbmc3k.h5ad
which is 10x Genomics PBMC3k processed as in the classic scanpy tutorial. Its
`.raw` layer holds per-cell normalized log1p values. Dividing each cell's
expm1 values by that cell's smallest non-zero value recovers the original UMI
counts exactly. The published clusters are kept as obs `published_cluster`, so
the UI's optional sample/group step has a column to offer.

Usage:  python scripts/fetch_data.py [--out data/pbmc3k_counts.h5ad]
"""

from __future__ import annotations

import argparse
import tempfile
import urllib.request
from pathlib import Path

import anndata as ad
import numpy as np
import scipy.sparse as sp

URL = "https://raw.githubusercontent.com/chanzuckerberg/cellxgene/main/example-dataset/pbmc3k.h5ad"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data/pbmc3k_counts.h5ad")
    out = Path(ap.parse_args().out)
    out.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "pbmc3k.h5ad"
        print(f"downloading {URL}")
        urllib.request.urlretrieve(URL, src)
        processed = ad.read_h5ad(src)

    raw = processed.raw.to_adata()
    X = raw.X.tocsr().astype(np.float64)
    X.data = np.expm1(X.data)
    unit = np.array([X.data[X.indptr[i] : X.indptr[i + 1]].min() for i in range(X.shape[0])])
    counts = sp.diags(1.0 / unit) @ X
    counts.data = np.round(counts.data)
    counts = sp.csr_matrix(counts, dtype=np.float32)

    assert counts.data.min() >= 0, "counts must be non-negative"
    assert np.allclose(np.asarray(counts.sum(axis=1)).ravel(), processed.obs["n_counts"].values), "totals do not match the published n_counts"

    adata = ad.AnnData(X=counts, obs=processed.obs[[]].copy(), var=raw.var[[]].copy())
    adata.obs["published_cluster"] = processed.obs["louvain"].astype(str).astype("category").values
    adata.uns["source"] = URL
    adata.write_h5ad(out, compression="gzip")
    print(f"wrote {out}: {adata.n_obs} cells x {adata.n_vars} genes, {out.stat().st_size / 1e6:.1f} MB")


if __name__ == "__main__":
    main()
