from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime


@dataclass(frozen=True)
class Instrument:
    symbol: str
    name: str


@dataclass(frozen=True)
class PriceBar:
    date: str
    close: float
    open: float | None = None
    high: float | None = None
    low: float | None = None
    volume: int | None = None


@dataclass(frozen=True)
class SectorMetric:
    symbol: str
    name: str
    rank: int
    score: float
    signal: str
    close: float
    returns: dict[str, float | None]
    relative_returns: dict[str, float | None]
    moving_averages: dict[str, float | None]
    trend: str
    volatility_21d: float | None


def utc_timestamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
