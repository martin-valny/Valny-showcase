"""Tiny synthetic count matrix (50 cells x 100 genes, 5 MT- genes, a 2-level batch column). No network."""

from __future__ import annotations

from pathlib import Path

import anndata as ad
import numpy as np
import pandas as pd
import scipy.sparse as sp


def write_tiny_h5ad(path: Path, n_cells: int = 50, n_genes: int = 100, seed: int = 0) -> Path:
    rng = np.random.default_rng(seed)
    genes = [f"MT-G{i}" for i in range(5)] + [f"GENE{i}" for i in range(n_genes - 5)]
    lam = np.full((n_cells, n_genes), 1.5)
    lam[:, :5] = 0.3
    lam[n_cells // 2 :, 5:30] = 6.0  # two crude "populations" so the UMAP has structure
    X = sp.csr_matrix(rng.poisson(lam).astype(np.float32))
    obs = pd.DataFrame({"batch": pd.Categorical(["a", "b"] * (n_cells // 2))}, index=[f"cell{i}" for i in range(n_cells)])
    path.parent.mkdir(parents=True, exist_ok=True)
    ad.AnnData(X=X, obs=obs, var=pd.DataFrame(index=genes)).write_h5ad(path)
    return path
