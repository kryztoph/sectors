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

Reference ETFs: SPY, RSP, QQQ

## Quick Start

```sh
python3 -m sectors init
python3 -m sectors validate
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
- `python3 -m sectors charts`
  - Writes a standalone chart index plus one HTML candlestick chart per sector
    from the latest snapshot.
- `python3 -m sectors backfill-weekly --weeks 8`
  - Writes historical weekly-close snapshots for the prior complete weeks and
    refreshes the tracker.
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
- `reports/<timestamp>-brief.html`
- `reports/latest-brief.md`
- `reports/latest-brief.html`
- `reports/sector_rotation_tracker.html`
- `reports/sector_charts.html`
- `reports/charts/<symbol>.html`
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
- `SECTORS_PUBLISH_REPORTS`: defaults to `1`; set to `0` to skip publishing
  generated sector reports to GitHub
- `SECTORS_PUBLISH_REPO`: defaults to `kryztoph/csfox`
- `SECTORS_PUBLISH_REPO_URL`: optional GitHub URL fallback
- `SECTORS_PUBLISH_BRANCH`: defaults to `master`

## Weekly Cotpy Collection

The weekly runner generates the cotpy commodity chart set, writes one
interactive HTML page per key commodity, and publishes the refreshed
`reports/cotpy` tree to the `csfox` GitHub repo:

```sh
./scripts/run_weekly.sh
```

Install the Friday after-hours LaunchAgent:

```sh
./scripts/install_weekly_launchagent.sh
```

The weekly job runs Fridays at 5:45 PM local time. Each run writes:

- `reports/cotpy/index.html`
- `reports/cotpy/charts/<symbol>_interactive.html`
- `logs/cotpy-weekly.out`
- `logs/cotpy-weekly.err`

Environment overrides supported by `scripts/run_weekly.sh`:

- `COTPY_PROVIDER`: defaults to `yfinance`
- `COTPY_PERIOD`: defaults to `2y`
- `COTPY_LOOKBACK`: defaults to `104` weekly bars
- `COTPY_PYTHON`: defaults to `/usr/local/bin/python3`
- `COTPY_PUBLISH_REPORTS`: defaults to `1`; set to `0` to skip publishing
- `SECTORS_PUBLISH_REPO`: defaults to `kryztoph/csfox`
- `SECTORS_PUBLISH_REPO_URL`: optional GitHub URL fallback
- `SECTORS_PUBLISH_BRANCH`: defaults to `master`

Uninstall:

```sh
./scripts/uninstall_weekly_launchagent.sh
```

## Rotation Model

The ranking score is intentionally simple and inspectable:

- 5-day relative return rank
- 21-day relative return rank
- 63-day relative return rank
- Price trend versus 10-day and 50-day moving averages, with a 150-day reference average
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

By default, the tracker command also publishes the refreshed default tracker
directly to the `csfox` GitHub repo. To generate only the local file:

```sh
python3 -m sectors tracker --no-publish
```

Open `reports/sector_rotation_tracker.html` in a browser. The chart uses:

- X-axis: relative strength score from the snapshot
- Y-axis: score momentum versus the prior snapshot
- Quadrants: `Leading`, `Weakening`, `Lagging`, and `Improving`

The slider steps through snapshots in time order. `Play` animates the sequence,
and each sector keeps a short trail so rotation paths are visible.

## Sector Charts

Generate candlestick charts from the latest snapshot:

```sh
python3 -m sectors charts
```

Open `reports/sector_charts.html` in a browser. The index links to one chart per
sector under `reports/charts/`. Each chart includes price candles, volume,
20-day volume moving average, 10-day, 50-day, and 150-day price moving averages,
relative strength versus SPY, and linear trendlines for price and relative strength.

## Publishing Reports

Publish regenerated static sector outputs directly to the `csfox` GitHub repo
without touching the local `csfox` working tree:

```sh
./scripts/publish_to_reports_repo.sh
```

This copies:

- `reports/sector_rotation_tracker.html` to `reports/sectors/`
- `reports/sector_charts.html` to `reports/sectors/`
- `reports/charts/*.html` to `reports/sectors/charts/`
- the newest `reports/*-brief.html` to `reports/sectors/latest-brief.html`
- the newest `reports/*-brief.md` to `reports/sectors/latest-brief.md`
- `reports/cotpy/index.html` to `reports/cotpy/index.html`
- `reports/cotpy/charts/*_interactive.html` to `reports/cotpy/charts/`
- `~/Desktop/logo.png` to `assets/logo.png`

The publisher uses `gh api` to create Git blobs, a tree, and one commit touching
whichever report trees were regenerated, then advances `master`. It does not
clone or modify the local `csfox` checkout.

The daily runner publishes to the reports repo by default after charts are
regenerated.
It runs the tracker step with `--no-publish` and then publishes once at the end
so the tracker, chart index, sector chart pages, and latest brief move together.
To run the daily flow without publishing:

```sh
SECTORS_PUBLISH_REPORTS=0 ./scripts/run_daily.sh
```

The default repository is `kryztoph/csfox`. The publisher uses `gh api` to
create Git blobs, a tree, and one commit touching only `assets/logo.png` and
`reports/sectors`, then advances `master`. It does not clone or modify the local
`csfox` checkout.
The public tracker URL remains:

```text
https://csfox.com/reports/sectors/sector_rotation_tracker.html
```

## Weekly Cotpy Charts

Generate the weekly commodity chart set locally:

```sh
python3 -m sectors cotpy --no-publish
```

Open `reports/cotpy/index.html` in a browser. The index links to one
interactive page per key commodity under `reports/cotpy/charts/`. Each chart
shows weekly candlesticks, volume, 10-week and 26-week moving averages, and a
small stat panel.
