from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

from .analytics import build_snapshot
from .config import load_assets, load_references, load_universe, write_json
from .market_data import fetch_optional_history, get_market_data_provider
from .model import PriceBar
from .tracker import write_tracker


def backfill_weekly_snapshots(
    root: Path,
    weeks: int = 8,
    provider_name: str = "yfinance",
    period: str = "1y",
    overwrite: bool = False,
    refresh_tracker: bool = True,
) -> list[Path]:
    if weeks <= 0:
        raise ValueError("weeks must be greater than zero")

    benchmark, sectors = load_universe(root)
    assets = load_assets(root)
    references = load_references(root)
    asset_symbols = {item.symbol for item in assets}
    symbols = list(dict.fromkeys(reference.symbol for reference in [benchmark] + references + sectors))
    provider = get_market_data_provider(provider_name)
    history = provider.fetch_history(symbols, period=period)
    history.update(fetch_optional_history(provider, [item.symbol for item in assets], period))
    # Optional assets must not shorten the core sector backfill calendar.
    core_history = {item.symbol: history.get(item.symbol, []) for item in [benchmark, *sectors]}
    close_dates = _latest_complete_weekly_closes(core_history, weeks)
    written: list[Path] = []

    for close_date in close_dates:
        truncated = _truncate_history(
            {symbol: bars for symbol, bars in history.items() if symbol not in asset_symbols},
            close_date.isoformat(),
        )
        truncated.update({
            item.symbol: [bar for bar in history.get(item.symbol, []) if bar.date <= close_date.isoformat()]
            for item in assets
        })
        created_at = f"backfill-weekly-{close_date.isoformat()}"
        snapshot = build_snapshot(
            benchmark,
            sectors,
            truncated,
            provider=f"{provider.name}-weekly-backfill",
            created_at=created_at,
            as_of=close_date.isoformat(),
            references=references,
            assets=assets,
            # Current allocations cannot be assigned to historical dates.
            sector_weights={"status": "unavailable", "reason": "historical allocations not collected"},
        )
        path = root / "state" / "snapshots" / f"{created_at}.json"
        if path.exists() and not overwrite:
            continue
        write_json(path, snapshot)
        written.append(path)

    if refresh_tracker:
        write_tracker(root)
    return written


def _latest_complete_weekly_closes(history: dict[str, list[PriceBar]], weeks: int) -> list[date]:
    common_dates = _common_history_dates(history)
    if not common_dates:
        raise ValueError("no common history dates available across symbols")

    today = date.today()
    current_week_start = today - timedelta(days=today.weekday())
    weekly: dict[date, date] = {}
    for item in common_dates:
        parsed = date.fromisoformat(item)
        week_start = parsed - timedelta(days=parsed.weekday())
        if week_start >= current_week_start:
            continue
        weekly[week_start] = parsed

    closes = [weekly[key] for key in sorted(weekly)]
    if len(closes) < weeks:
        raise ValueError(f"only {len(closes)} complete weekly closes available; requested {weeks}")
    return closes[-weeks:]


def _common_history_dates(history: dict[str, list[PriceBar]]) -> list[str]:
    date_sets = [{bar.date for bar in bars} for bars in history.values() if bars]
    if not date_sets:
        return []
    common = set.intersection(*date_sets)
    return sorted(common)


def _truncate_history(history: dict[str, list[PriceBar]], as_of: str) -> dict[str, list[PriceBar]]:
    truncated = {
        symbol: [bar for bar in bars if bar.date <= as_of]
        for symbol, bars in history.items()
    }
    missing = [symbol for symbol, bars in truncated.items() if len(bars) < 64]
    if missing:
        raise ValueError(f"insufficient history through {as_of}: {', '.join(missing)}")
    return truncated
