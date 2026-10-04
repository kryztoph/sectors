from __future__ import annotations

import math
from collections.abc import Iterable

from .model import PriceBar


class MarketDataProvider:
    name = "base"

    def fetch_history(self, symbols: list[str], period: str = "1y") -> dict[str, list[PriceBar]]:
        raise NotImplementedError


class YFinanceMarketDataProvider(MarketDataProvider):
    name = "yfinance"

    def fetch_history(self, symbols: list[str], period: str = "1y") -> dict[str, list[PriceBar]]:
        try:
            import yfinance as yf
        except ImportError as exc:
            raise RuntimeError("yfinance is not installed; run: python3 -m pip install -e '.[live]'") from exc

        data: dict[str, list[PriceBar]] = {}
        for symbol in symbols:
            ticker = yf.Ticker(symbol)
            history = ticker.history(period=period, auto_adjust=False)
            bars: list[PriceBar] = []
            if not history.empty:
                clean = history.dropna(subset=["Close"])
                for idx, row in clean.iterrows():
                    bars.append(
                        PriceBar(
                            date=idx.date().isoformat(),
                            close=float(row["Close"]),
                            open=_float_or_none(row.get("Open")),
                            high=_float_or_none(row.get("High")),
                            low=_float_or_none(row.get("Low")),
                            volume=_int_or_none(row.get("Volume")),
                        )
                    )
            data[symbol] = bars
        return data


def fetch_optional_history(provider: MarketDataProvider, symbols: list[str], period: str) -> dict[str, list[PriceBar]]:
    result = {}
    for symbol in symbols:
        try:
            result[symbol] = provider.fetch_history([symbol], period=period).get(symbol, [])
        except Exception:
            # An unavailable context asset must not block the sector snapshot.
            result[symbol] = []
    return result


def provider_names() -> list[str]:
    return ["yfinance"]


def get_market_data_provider(name: str) -> MarketDataProvider:
    if name == "yfinance":
        return YFinanceMarketDataProvider()
    raise ValueError(f"Unsupported market data provider: {name}")


def serialize_history(history: dict[str, Iterable[PriceBar]]) -> dict[str, list[dict[str, object]]]:
    return {
        symbol: [
            _bar_to_dict(bar)
            for bar in bars
        ]
        for symbol, bars in history.items()
    }


def _bar_to_dict(bar: PriceBar) -> dict[str, object]:
    return {
        "date": bar.date,
        "open": bar.open,
        "high": bar.high,
        "low": bar.low,
        "close": bar.close,
        "volume": bar.volume,
    }


def _float_or_none(value: object) -> float | None:
    if value is None:
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(result):
        return None
    return result


def _int_or_none(value: object) -> int | None:
    parsed = _float_or_none(value)
    if parsed is None:
        return None
    return int(parsed)
