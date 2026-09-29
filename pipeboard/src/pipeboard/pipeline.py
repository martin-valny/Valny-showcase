"""A deliberately small scRNA-seq pipeline: load -> qc -> normalize -> embed.

`run()` logs one line per step through the `log` callback, so the runner can
stream progress into run.log. A QC setting that removes every cell raises
PipelineError. That is an expected, readable failure, not a crash.
"""

from __future__ import annotations

import time
import warnings
from pathlib import Path
from typing import Callable

import anndata as ad
import numpy as np
import scanpy as sc
import scipy.sparse as sp

warnings.filterwarnings("ignore", category=FutureWarning)

STEPS = ["load", "qc", "normalize", "embed"]


class PipelineError(Exception):
    """An expected failure with a message meant for the user."""


def _step(log: Callable[[str], None], name: str):
    class _Timer:
        def __enter__(self):
            self.t0 = time.monotonic()
            log(f"[{name}] start")
            return self

        def __exit__(self, exc_type, *_):
            if exc_type is None:
                log(f"[{name}] done in {time.monotonic() - self.t0:.1f}s")

    return _Timer()


def run(
    input_path: Path | str,
    params: dict,
    log: Callable[[str], None] = print,
    out_dir: Path | str | None = None,
    sample_col: str | None = None,
) -> dict:
    metrics: dict = {}

    with _step(log, "load"):
        adata = ad.read_h5ad(input_path)
        if adata.X is None or adata.n_obs == 0 or adata.n_vars == 0:
            raise PipelineError(f"input has shape {adata.shape}; expected cells x genes")
        X = adata.X if sp.issparse(adata.X) else sp.csr_matrix(adata.X)
        if X.nnz and X.data.min() < 0:
            raise PipelineError("input contains negative values; expected raw counts")
        adata.X = X.astype(np.float32).tocsr()
        if sample_col and sample_col not in adata.obs:
            raise PipelineError(f"sample column {sample_col!r} not found in obs")
        metrics["n_cells_before"], metrics["n_genes"] = int(adata.n_obs), int(adata.n_vars)
        log(f"loaded {adata.n_obs} cells x {adata.n_vars} genes")

    with _step(log, "qc"):
        mito = adata.var_names.str.upper().str.startswith("MT-")
        total = np.asarray(adata.X.sum(axis=1)).ravel()
        n_genes = np.asarray((adata.X > 0).sum(axis=1)).ravel()
        pct_mito = 100 * np.asarray(adata.X[:, mito].sum(axis=1)).ravel() / np.maximum(total, 1)
        pass_genes = n_genes >= params["min_genes"]
        pass_mito = pct_mito <= params["max_mito_pct"]
        keep = pass_genes & pass_mito
        log(f"{int(mito.sum())} mito genes; {int(pass_genes.sum())} pass min_genes, {int(pass_mito.sum())} pass max_mito_pct")
        if not keep.any():
            raise PipelineError(
                f"QC removed all {adata.n_obs} cells "
                f"(min_genes={params['min_genes']}: {int(pass_genes.sum())} pass; "
                f"max_mito_pct={params['max_mito_pct']}: {int(pass_mito.sum())} pass)"
            )
        adata = adata[keep].copy()
        metrics.update(
            n_cells_after_qc=int(adata.n_obs),
            mean_genes_per_cell=round(float(n_genes[keep].mean()), 1),
            median_pct_mito=round(float(np.median(pct_mito[keep])), 2),
        )
        log(f"kept {adata.n_obs}/{metrics['n_cells_before']} cells")

    with _step(log, "normalize"):
        sc.pp.normalize_total(adata)
        sc.pp.log1p(adata)

    with _step(log, "embed"):
        if adata.n_obs < 3:
            raise PipelineError(f"only {adata.n_obs} cells left after QC; need at least 3 to embed")
        n_top = min(params["n_hvgs"], adata.n_vars)
        sc.pp.highly_variable_genes(adata, n_top_genes=n_top)
        adata = adata[:, adata.var["highly_variable"]].copy()
        n_comps = max(2, min(50, adata.n_obs - 1, adata.n_vars - 1))
        sc.pp.pca(adata, n_comps=n_comps)
        k = max(2, min(params["n_neighbors"], adata.n_obs - 1))
        sc.pp.neighbors(adata, n_neighbors=k)
        sc.tl.umap(adata, random_state=0)
        log(f"{n_top} HVGs, {n_comps} PCs, k={k}; UMAP done")
        metrics["umap"] = adata.obsm["X_umap"].tolist()
        if sample_col:
            metrics["groups"] = adata.obs[sample_col].astype(str).tolist()

    if out_dir is not None:
        adata.write_h5ad(Path(out_dir) / "adata.h5ad")
    return metrics
