#!/usr/bin/env bash
# Repo hygiene: no leftover branding or hiring wording, and the data path the notebook expects.
# The denylist is base64-encoded so this file does not match itself (base64 -d to review).
set -euo pipefail
cd "$(dirname "$0")/.."
pattern=$(echo 'bGF0Y2h8dGFrZS4/aG9tZXx0YWtlaG9tZXxpbnRlcnZpZXd8YXNzaWdubWVudHxjYW5kaWRhdGV8aGlyaW5nfHJlY3J1aXR8aW1tdW5haXxwYW5hY2VhfFxiYmxhZGVcYnxkYWdzdGVyfHdvcmtiZW5jaFwu' | base64 -d)
if git ls-files --cached --others --exclude-standard | grep -v '^tests/check_repo.sh$' | xargs grep -niE "$pattern" -- ; then
  echo "FAIL: denylisted terms found" >&2; exit 1
fi
grep -q 'H5_PATH <- "data/sample.h5ad"' ovary_analysis.Rmd || { echo "FAIL: H5_PATH changed" >&2; exit 1; }
if git ls-files | grep -E '\.h5ad$'; then echo "FAIL: data file committed" >&2; exit 1; fi
echo "repo checks passed"
