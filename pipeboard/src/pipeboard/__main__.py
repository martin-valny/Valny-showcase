"""pipeboard [--port 8080] [--host 127.0.0.1] [--root .]"""

from __future__ import annotations

import argparse
import sys


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="pipeboard", description="Local web UI for a small public-data scRNA-seq pipeline.")
    ap.add_argument("--port", type=int, default=8080)
    ap.add_argument("--host", default="127.0.0.1", help="bind address (default: localhost only)")
    ap.add_argument("--root", default=".", help="project root containing schema/, data/ and runs/")
    args = ap.parse_args(argv)

    import uvicorn

    from .server import create_app

    print(f"pipeboard: http://{args.host}:{args.port}")
    uvicorn.run(create_app(args.root), host=args.host, port=args.port, log_level="warning")
    return 0


if __name__ == "__main__":
    sys.exit(main())
