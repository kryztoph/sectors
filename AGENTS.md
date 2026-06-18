# AGENTS.md

## Project Purpose

This project monitors the 11 S&P 500 sectors for sector rotation.

The initial workflow tracks the SPDR sector ETF proxies, compares them against
SPY, ranks relative strength, and writes local snapshots and Markdown briefs.
It is a market-monitoring and research tool, not a trade execution system.
The project also renders a four-quadrant HTML tracker from accumulated
time-ordered snapshots.

## Sector Universe

Use these sector proxies unless the user explicitly changes the universe:

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

Benchmark:

- SPY: S&P 500 ETF

## Data Integrity Rules

- Never fabricate prices, returns, rankings, or rotation signals.
- If live market data is unavailable, say so and use only explicit fixtures or
  existing snapshots.
- Store generated market snapshots under `state/snapshots/`.
- Store generated human reports under `reports/`.
- Store generated HTML trackers under `reports/`.
- Keep raw or derived data out of source control unless it is a small test
  fixture.

## Implementation Notes

- Prefer the local snapshot/report pattern from `../robinhood`.
- Reuse the simple yfinance provider idea from `../risk/market_data_provider.py`.
- Keep V1 standard-library-first; `yfinance` is an optional live-data dependency.
- Do not add execution, order review, or broker mutation workflows.
