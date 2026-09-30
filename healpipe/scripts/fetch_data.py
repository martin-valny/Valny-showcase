"""Download the public PBMC3k dataset and rebuild its raw integer count matrix.

`healpipe run` / `healpipe eval` also do this automatically if the file is missing.
The download and conversion live in src/healpipe/data.py (source URL documented there).

Usage:  python scripts/fetch_data.py [--out data/pbmc3k_counts.h5ad]
"""

from healpipe.data import main

if __name__ == "__main__":
    main()
