#!/usr/bin/env sh
set -eu
cd "$(dirname "$0")"

if ! command -v python3 >/dev/null 2>&1; then
  echo "Job Finder needs Python 3.11 or newer."
  echo "Install Python from https://www.python.org/downloads/ and try again."
  exit 1
fi

exec python3 scripts/bootstrap.py --launch
