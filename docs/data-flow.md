# Data Flow

## Market Data Provider

Provider in `sectors/market_data.py`:

- **yfinance** — live market data via the yfinance library (requires `pip install -e '.[live]'`)

## Snapshot Pipeline

Triggered by `python3 -m sectors snapshot`:

1. Loads the 11 sectors plus the configured reference ETFs (SPY, RSP, and QQQ) from `config/universe.json`
2. Calls `provider.fetch_history(symbols, period)` — gets OHLCV bars for every symbol
3. `analytics.build_snapshot()` computes the rotation metrics:
   - 5d/21d/63d returns for each sector AND the benchmark
   - Relative return = sector return minus benchmark return (the core of the ranking)
   - 10d, 50d, and 150d moving averages; the 10d/50d pair drives the trend score (bullish/constructive/mixed/weak)
   - 21d realized volatility as a penalty
   - Final score = weighted rank of relative returns + trend rank + vol rank, normalized to roughly -100..+100
   - Signal: LEADING / IMPROVING / WEAKENING / LAGGING based on score + 21d rel return + trend
4. Stores all fetched OHLCV histories, including the reference ETFs, in `state/snapshots/<timestamp>.json` and updates `state/snapshots/latest.json`

## Daily Automation

`scripts/run_daily.sh` installed as a macOS LaunchAgent (`com.fox.sectors.daily`):

- Runs Mon-Fri at 5:30 PM local time
- Chains: validate → snapshot → brief → tracker → charts
- Each run produces a new timestamped snapshot, a Markdown brief, the HTML tracker, and per-sector candlestick charts

## Weekly Cotpy Automation

`scripts/run_weekly.sh` installed as a macOS LaunchAgent (`com.fox.sectors.cotpy.weekly`):

- Runs Fridays at 5:45 PM local time
- Generates the cotpy commodity chart index plus one interactive page per key commodity
- Publishes the refreshed `reports/cotpy` tree

## Weekly Backfill

`python3 -m sectors backfill-weekly --weeks 8`:

- Fetches 1y of history, then truncates it to each of the last 8 complete weekly closes
- Builds a snapshot as-of that historical date (so the tracker has a path before daily collection existed)
- Writes `state/snapshots/backfill-weekly-YYYY-MM-DD.json`
- Skips existing backfill files unless `--overwrite`
- Refreshes the tracker HTML afterward

## Derived Outputs

Consumers of snapshots (not data updates themselves):

- **brief** — Markdown report from latest snapshot
- **tracker** — Four-quadrant HTML (score x momentum) built from ALL time-ordered snapshots, with a time slider/play button
- **charts** — Per-sector candlestick HTML with volume, MAs, relative strength, trendlines

## Storage Design

- Snapshots are append-only JSON files
- The tracker and charts are regenerated from scratch each run by reading every snapshot in order
- No database — just files in `state/snapshots/`
