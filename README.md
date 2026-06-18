# Sectors

Read-only sector rotation monitor for the 11 S&P 500 sectors.

V1 tracks the SPDR sector ETF proxies, compares each sector against SPY, ranks
relative strength, and writes local JSON snapshots plus Markdown briefs.

## Universe

- XLC: Communication Services
- XLY: Consumer Discretionary
- XLP: Consumer Staples
- XLE: Energy
- XLF: Financials
- XLV: Health Care
- XLI: Industrials
- XLB: Materials
- XLRE: Real Estate
- XLK: Technology
- XLU: Utilities

Benchmark: SPY

## Quick Start

```sh
python3 -m sectors init
python3 -m sectors validate
python3 -m sectors snapshot --provider sample
python3 -m sectors brief
```

For live market data, install the optional dependency and use `yfinance`:

```sh
python3 -m pip install -e '.[live]'
python3 -m sectors snapshot --provider yfinance --period 1y
python3 -m sectors brief
```

## Commands

- `python3 -m sectors init`
  - Creates `config/`, `state/raw/`, `state/snapshots/`, and `reports/`.
  - Writes `config/universe.json` if missing.
- `python3 -m sectors validate`
  - Validates the configured universe and benchmark.
- `python3 -m sectors snapshot`
  - Fetches market history, calculates rotation metrics, writes a snapshot, and
    updates `state/snapshots/latest.json`.
- `python3 -m sectors brief`
  - Writes a Markdown rotation brief from the latest snapshot.
- `python3 -m sectors tracker`
  - Writes a standalone HTML four-quadrant rotation tracker from all
    time-ordered snapshots.
- `python3 -m sectors status`
  - Prints latest snapshot and report paths.

## Daily Collection

Install live market dependencies first:

```sh
python3 -m pip install -e '.[live]'
```

Test one live run:

```sh
./scripts/run_daily.sh
```

Install the weekday after-hours LaunchAgent:

```sh
./scripts/install_daily_launchagent.sh
```

The job runs Monday through Friday at 5:30 PM local time. Each run writes:

- `state/snapshots/<timestamp>.json`
- `state/snapshots/latest.json`
- `reports/<timestamp>-brief.md`
- `reports/sector_rotation_tracker.html`
- `logs/daily.out`
- `logs/daily.err`

Run the scheduled job immediately:

```sh
launchctl kickstart -k "gui/$(id -u)/com.fox.sectors.daily"
```

Uninstall:

```sh
./scripts/uninstall_daily_launchagent.sh
```

Environment overrides supported by `scripts/run_daily.sh`:

- `SECTORS_PROVIDER`: defaults to `yfinance`
- `SECTORS_PERIOD`: defaults to `1y`
- `SECTORS_PYTHON`: defaults to `/usr/local/bin/python3`

## Rotation Model

The ranking score is intentionally simple and inspectable:

- 5-day relative return rank
- 21-day relative return rank
- 63-day relative return rank
- Price trend versus 20-day and 50-day moving averages
- 21-day realized volatility as a small penalty

Signals:

- `LEADING`: positive score, positive 21-day relative return, and bullish trend
- `IMPROVING`: positive score but incomplete confirmation
- `WEAKENING`: negative score but not yet broadly weak
- `LAGGING`: negative score, negative 21-day relative return, and weak trend

This is a research monitor, not a trading system.

## Four-Quadrant Tracker

Generate the visual tracker from the rolling snapshot history:

```sh
python3 -m sectors tracker
```

Open `reports/sector_rotation_tracker.html` in a browser. The chart uses:

- X-axis: relative strength score from the snapshot
- Y-axis: score momentum versus the prior snapshot
- Quadrants: `Leading`, `Weakening`, `Lagging`, and `Improving`

The slider steps through snapshots in time order. `Play` animates the sequence,
and each sector keeps a short trail so rotation paths are visible.
