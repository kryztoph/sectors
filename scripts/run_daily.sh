#!/bin/sh
set -eu

PROJECT_DIR="/Users/fox/Private/Projects/sectors"
PROVIDER="${SECTORS_PROVIDER:-yfinance}"
PERIOD="${SECTORS_PERIOD:-1y}"
PYTHON_BIN="${SECTORS_PYTHON:-/usr/local/bin/python3}"

cd "$PROJECT_DIR"
mkdir -p logs state/snapshots reports

echo "[$(date -u '+%Y-%m-%dT%H:%M:%SZ')] starting sector rotation capture"
echo "provider=$PROVIDER period=$PERIOD python=$PYTHON_BIN"

"$PYTHON_BIN" -m sectors validate
"$PYTHON_BIN" -m sectors snapshot --provider "$PROVIDER" --period "$PERIOD"
"$PYTHON_BIN" -m sectors brief

echo "[$(date -u '+%Y-%m-%dT%H:%M:%SZ')] sector rotation capture complete"
