"""pipeboard [--port 8080] [--host 127.0.0.1] [--root .] [--no-fetch]

On first start, downloads the public dataset if data/pbmc3k_counts.h5ad is missing.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="pipeboard", description="Local web UI for a small public-data scRNA-seq pipeline.")
    ap.add_argument("--port", type=int, default=8080)
    ap.add_argument("--host", default="127.0.0.1", help="bind address (default: localhost only)")
    ap.add_argument("--root", default=".", help="project root containing schema/, data/ and runs/")
    ap.add_argument("--no-fetch", action="store_true", help="don't download the public dataset if it is missing")
    args = ap.parse_args(argv)

    data_path = Path(args.root) / "data" / "pbmc3k_counts.h5ad"
    if not data_path.exists() and not args.no_fetch:
        print(f"{data_path} not found; downloading public PBMC3k (~25 MB download, one time)...")
        try:
            from .data import fetch

            fetch(data_path)
        except Exception as e:  # keep serving; the UI shows how to fetch manually
            print(f"download failed ({type(e).__name__}: {e}). Run: python scripts/fetch_data.py", file=sys.stderr)

    import uvicorn

    from .server import create_app

    print(f"pipeboard: http://{args.host}:{args.port}")
    uvicorn.run(create_app(args.root), host=args.host, port=args.port, log_level="warning")
    return 0


if __name__ == "__main__":
    sys.exit(main())
