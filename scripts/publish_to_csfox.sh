#!/bin/sh
set -eu

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
PROJECT_DIR="${SECTORS_PROJECT_DIR:-$(dirname -- "$SCRIPT_DIR")}"
PYTHON_BIN="${SECTORS_PYTHON:-python3}"

cd "$PROJECT_DIR"
exec "$PYTHON_BIN" scripts/publish_to_csfox_gh.py
