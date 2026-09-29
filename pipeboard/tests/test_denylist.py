"""Hygiene gate: no employer, product, or infrastructure identifiers in pipeboard's files.

Patterns are base64-encoded so this file does not match itself (`base64 -d` to review).
"""

import base64
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_ENCODED = (
    "aW1tdW5haQpwYW5hY2VhClxiYmxhZGVcYgpibGFkZS11aQptaWdyYXRpb25fcHkKbWlncmF0aW9uLXB5CnBoYXNlID8xNAp3b3Jr"
    "YmVuY2hcLgpkYWdzdGVyCmNlbGxyYW5nZXIKb21pYy1kYXRhZ2VuCmdzOi8vClxicHJqXGQr"
)
PATTERNS = [re.compile(p, re.IGNORECASE) for p in base64.b64decode(_ENCODED).decode().splitlines()]
SKIP_SUFFIXES = {".h5ad", ".png", ".jpg", ".gif", ".pyc"}


def _files() -> list[Path]:
    try:
        out = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard"], cwd=ROOT, capture_output=True, text=True, check=True)
        return [ROOT / f for f in out.stdout.splitlines()]
    except (OSError, subprocess.CalledProcessError):
        return [p for p in ROOT.rglob("*") if p.is_file() and ".git" not in p.parts]


def test_no_denylisted_terms():
    hits = []
    for path in _files():
        if path.suffix in SKIP_SUFFIXES or not path.exists():
            continue
        text = path.read_text(errors="ignore")
        rel = path.relative_to(ROOT)
        hits += [f"{rel}: /{p.pattern}/" for p in PATTERNS if p.search(text) or p.search(str(rel))]
    assert not hits, "denylisted terms found:\n" + "\n".join(hits)
