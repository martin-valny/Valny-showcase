"""Download one published mouse ovary Curio Seeker sample and write data/sample.h5ad.

Data source (public)
    Paper:  Mantri M, Zhang HH, Spanos E, Ren YA, De Vlaminck I.
            "A spatiotemporal molecular atlas of the ovulating mouse ovary."
            Proc Natl Acad Sci USA 121(5):e2317418121 (2024). doi:10.1073/pnas.2317418121
    GEO:    GSE240271  https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc=GSE240271
    Sample: GSM7689281 (1 h after hCG) by default. The file is
            GSM7689281_adata_ovary_1hr_spatial_raw_counts.h5ad.gz (~33 MB), from
            https://ftp.ncbi.nlm.nih.gov/geo/samples/GSM7689nnn/GSM7689281/suppl/
    Coordinates: the authors publish bead barcode -> x/y location files at
            https://github.com/madhavmantri/mouse_ovulation/tree/main/barcode_location_files
            Use one with --coords if the h5ad has no obsm['spatial'].

GEO supplementary files are public. Please cite the paper when you use them.
Do not commit the downloaded matrix to git; data/*.h5ad is gitignored.

What this script does
    1. Download the .h5ad.gz from GEO into data/raw/ (skipped if already there).
    2. Decompress it and open it with anndata.
    3. Check that X holds non-negative integer counts. Nothing is transformed.
    4. Make sure obsm['spatial'] exists. If it doesn't, join x/y from --coords
       (a CSV with a barcode column plus x/y columns) and fail if <90% of beads match.
    5. Write data/sample.h5ad in the layout the notebook reads:
       /X (CSR: data, indices, indptr), /obs/_index, /var/_index, /obsm/spatial.
    6. Print the file size and an HDF5 tree as a quick check.

Usage
    pip install -r scripts/requirements.txt
    python scripts/fetch_data.py                       # default sample
    python scripts/fetch_data.py --gsm GSM7689282 --file <name>.h5ad.gz
    python scripts/fetch_data.py --coords path/or/url/to/barcode_locations.csv
"""

from __future__ import annotations

import argparse
import gzip
import shutil
import sys
import urllib.request
from pathlib import Path

import anndata as ad
import h5py
import numpy as np
import pandas as pd
import scipy.sparse as sp

DEFAULT_GSM = "GSM7689281"
DEFAULT_FILE = "GSM7689281_adata_ovary_1hr_spatial_raw_counts.h5ad.gz"


def geo_url(gsm: str, filename: str) -> str:
    """GEO sample supplement URL: .../samples/GSM7689nnn/GSM7689281/suppl/<file>."""
    return f"https://ftp.ncbi.nlm.nih.gov/geo/samples/{gsm[:-3]}nnn/{gsm}/suppl/{filename}"


def download(url: str, dest: Path) -> Path:
    if dest.exists() and dest.stat().st_size > 0:
        print(f"already downloaded: {dest}")
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    print(f"downloading {url}")
    tmp = dest.with_suffix(dest.suffix + ".part")
    urllib.request.urlretrieve(url, tmp)
    tmp.rename(dest)
    return dest


def decompress(path: Path) -> Path:
    if path.suffix != ".gz":
        return path
    out = path.with_suffix("")
    if not out.exists():
        with gzip.open(path, "rb") as src, open(out, "wb") as dst:
            shutil.copyfileobj(src, dst)
    return out


def read_coords(source: str) -> pd.DataFrame:
    """CSV with one barcode column and two coordinate columns (x/y or xcoord/ycoord)."""
    df = pd.read_csv(source, sep=None, engine="python")
    cols = {c.lower(): c for c in df.columns}
    bc = next((cols[c] for c in ("barcode", "barcodes", "bead", "cell", "index") if c in cols), df.columns[0])
    x = next((cols[c] for c in ("x", "xcoord", "x_coord", "x_um") if c in cols), None)
    y = next((cols[c] for c in ("y", "ycoord", "y_coord", "y_um") if c in cols), None)
    if x is None or y is None:
        num = [c for c in df.columns if c != bc and pd.api.types.is_numeric_dtype(df[c])]
        if len(num) < 2:
            sys.exit(f"--coords: could not find x/y columns in {list(df.columns)}")
        x, y = num[:2]
    return df.set_index(df[bc].astype(str))[[x, y]].rename(columns={x: "x", y: "y"})


def ensure_spatial(adata: ad.AnnData, coords: str | None) -> ad.AnnData:
    if "spatial" in adata.obsm and np.asarray(adata.obsm["spatial"]).shape[1] >= 2:
        adata.obsm["spatial"] = np.asarray(adata.obsm["spatial"], dtype=np.float64)[:, :2]
        return adata
    if not coords:
        sys.exit(
            "The h5ad has no obsm['spatial']. Re-run with --coords pointing at the matching bead\n"
            "location file from https://github.com/madhavmantri/mouse_ovulation/tree/main/barcode_location_files"
        )
    loc = read_coords(coords)
    hit = adata.obs_names.isin(loc.index)
    if hit.mean() < 0.9:
        sys.exit(f"--coords matched only {hit.mean():.0%} of beads (need >= 90%). Wrong location file for this sample?")
    adata = adata[hit].copy()
    adata.obsm["spatial"] = loc.loc[adata.obs_names, ["x", "y"]].to_numpy(dtype=np.float64)
    print(f"joined coordinates for {adata.n_obs} beads from {coords}")
    return adata


def check_counts(adata: ad.AnnData) -> None:
    X = adata.X if sp.issparse(adata.X) else sp.csr_matrix(adata.X)
    vals = X.data
    if vals.size and (vals.min() < 0 or not np.allclose(vals, np.round(vals))):
        sys.exit("X does not look like raw counts (negative or non-integer values). Did you pick a processed file?")


def to_notebook_layout(adata: ad.AnnData) -> ad.AnnData:
    """Minimal AnnData: CSR counts, string obs/var indices, obsm['spatial']. Everything else is dropped."""
    X = sp.csr_matrix(adata.X, dtype=np.float32)
    out = ad.AnnData(
        X=X,
        obs=pd.DataFrame(index=adata.obs_names.astype(str)),
        var=pd.DataFrame(index=adata.var_names.astype(str)),
    )
    out.obsm["spatial"] = np.asarray(adata.obsm["spatial"], dtype=np.float64)
    out.var_names_make_unique()
    return out


def describe(path: Path) -> None:
    print(f"\n{path}  ({path.stat().st_size / 1e6:.1f} MB)")
    with h5py.File(path, "r") as f:
        for key in ("X/data", "X/indices", "X/indptr", "obs/_index", "var/_index", "obsm/spatial"):
            if key not in f:
                sys.exit(f"missing /{key} in output; the notebook expects it")
            print(f"  /{key:<12} shape={f[key].shape} dtype={f[key].dtype}")
        n_obs, n_var = len(f["obs/_index"]), len(f["var/_index"])
    a = ad.read_h5ad(path)
    umis = np.asarray(a.X.sum(axis=1)).ravel()
    print(f"  {n_obs} beads x {n_var} genes; UMI/bead median {np.median(umis):.0f}, "
          f"mito genes {int(a.var_names.str.startswith('mt-').sum())}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--gsm", default=DEFAULT_GSM, help=f"GEO sample (default {DEFAULT_GSM})")
    ap.add_argument("--file", default=DEFAULT_FILE, help="supplementary file name on the GSM page")
    ap.add_argument("--url", help="full URL to override the GEO path")
    ap.add_argument("--coords", help="bead location CSV (path or URL), only needed if obsm['spatial'] is missing")
    ap.add_argument("--out", default="data/sample.h5ad")
    args = ap.parse_args()

    out = Path(args.out)
    raw = download(args.url or geo_url(args.gsm, args.file), out.parent / "raw" / Path(args.url or args.file).name)
    adata = ad.read_h5ad(decompress(raw))
    print(f"read {adata.n_obs} beads x {adata.n_vars} genes; obsm keys: {list(adata.obsm.keys())}")

    check_counts(adata)
    adata = ensure_spatial(adata, args.coords)
    to_notebook_layout(adata).write_h5ad(out)
    describe(out)
    print("\nNext: knit ovary_analysis.Rmd (see README).")


if __name__ == "__main__":
    main()
