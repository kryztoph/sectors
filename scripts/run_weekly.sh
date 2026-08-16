#!/bin/sh
set -eu

PROJECT_DIR="/Users/fox/Private/Projects/sectors"
PROVIDER="${COTPY_PROVIDER:-yfinance}"
PERIOD="${COTPY_PERIOD:-2y}"
LOOKBACK="${COTPY_LOOKBACK:-104}"
PYTHON_BIN="${COTPY_PYTHON:-/usr/local/bin/python3}"
PUBLISH_REPORTS="${COTPY_PUBLISH_REPORTS:-1}"

cd "$PROJECT_DIR"
mkdir -p logs reports/cotpy/charts

echo "[$(date -u '+%Y-%m-%dT%H:%M:%SZ')] starting weekly cotpy capture"
echo "provider=$PROVIDER period=$PERIOD lookback=$LOOKBACK python=$PYTHON_BIN"

"$PYTHON_BIN" -m sectors cotpy --provider "$PROVIDER" --period "$PERIOD" --lookback "$LOOKBACK" --no-publish

if [ "$PUBLISH_REPORTS" = "1" ]; then
  ./scripts/publish_to_reports_repo.sh
fi

echo "[$(date -u '+%Y-%m-%dT%H:%M:%SZ')] weekly cotpy capture complete"
