"""Download public 10x PBMC3k and write raw integer counts to data/pbmc3k_counts.h5ad.

`pipeboard` also does this automatically on first start if the file is missing.
The download and conversion live in src/pipeboard/data.py (source URL documented there).

Usage:  python scripts/fetch_data.py [--out data/pbmc3k_counts.h5ad]
"""

from pipeboard.data import main

if __name__ == "__main__":
    main()
