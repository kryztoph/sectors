#!/bin/sh
set -eu

PROJECT_DIR="${SECTORS_PROJECT_DIR:-/Users/fox/Private/Projects/sectors}"
PYTHON_BIN="${SECTORS_PYTHON:-python3}"

cd "$PROJECT_DIR"
exec "$PYTHON_BIN" scripts/publish_to_csfox_gh.py
