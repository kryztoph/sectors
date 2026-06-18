from __future__ import annotations

from collections.abc import Iterable
from datetime import date, timedelta

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
                    volume = row.get("Volume")
                    bars.append(
                        PriceBar(
                            date=idx.date().isoformat(),
                            close=float(row["Close"]),
                            volume=None if volume is None else int(volume),
                        )
                    )
            data[symbol] = bars
        return data


class SampleMarketDataProvider(MarketDataProvider):
    name = "sample"

    def fetch_history(self, symbols: list[str], period: str = "1y") -> dict[str, list[PriceBar]]:
        end = date(2026, 6, 17)
        start = end - timedelta(days=220)
        profiles = {
            "SPY": (500.0, 0.0018),
            "XLK": (225.0, 0.0032),
            "XLI": (128.0, 0.0024),
            "XLF": (45.0, 0.0021),
            "XLE": (92.0, 0.0017),
            "XLY": (185.0, 0.0014),
            "XLV": (145.0, 0.0007),
            "XLC": (88.0, 0.0028),
            "XLB": (91.0, 0.0005),
            "XLRE": (41.0, -0.0002),
            "XLP": (78.0, -0.0001),
            "XLU": (73.0, 0.0002),
        }
        result: dict[str, list[PriceBar]] = {}
        for symbol in symbols:
            base, drift = profiles.get(symbol, (100.0, 0.001))
            result[symbol] = _sample_bars(start, end, base, drift, symbol)
        return result


def provider_names() -> list[str]:
    return ["yfinance", "sample"]


def get_market_data_provider(name: str) -> MarketDataProvider:
    if name == "yfinance":
        return YFinanceMarketDataProvider()
    if name == "sample":
        return SampleMarketDataProvider()
    raise ValueError(f"Unsupported market data provider: {name}")


def _sample_bars(start: date, end: date, base: float, drift: float, symbol: str) -> list[PriceBar]:
    bars: list[PriceBar] = []
    current = start
    index = 0
    symbol_noise = (sum(ord(char) for char in symbol) % 9) / 1000
    while current <= end:
        if current.weekday() < 5:
            cycle = ((index % 13) - 6) / 1000
            close = base * (1 + drift * index + symbol_noise + cycle)
            bars.append(
                PriceBar(
                    date=current.isoformat(),
                    close=round(close, 2),
                    volume=20_000_000 + index * 100_000,
                )
            )
            index += 1
        current += timedelta(days=1)
    return bars


def serialize_history(history: dict[str, Iterable[PriceBar]]) -> dict[str, list[dict[str, object]]]:
    return {
        symbol: [
            {"date": bar.date, "close": bar.close, "volume": bar.volume}
            for bar in bars
        ]
        for symbol, bars in history.items()
    }
