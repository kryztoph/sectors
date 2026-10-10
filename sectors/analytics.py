from __future__ import annotations

import math
from statistics import mean, stdev

from .model import Instrument, PriceBar, SectorMetric, utc_timestamp
from .market_data import serialize_history


WINDOWS = {"5d": 5, "21d": 21, "63d": 63}


def build_snapshot(
    benchmark: Instrument,
    sectors: list[Instrument],
    history: dict[str, list[PriceBar]],
    provider: str,
    references: list[Instrument] | None = None,
    created_at: str | None = None,
    as_of: str | None = None,
    assets: list[Instrument] | None = None,
    sector_weights: dict[str, object] | None = None,
) -> dict[str, object]:
    benchmark_bars = history.get(benchmark.symbol, [])
    if len(benchmark_bars) < 64:
        raise ValueError(f"{benchmark.symbol} needs at least 64 price bars")

    metrics = calculate_sector_metrics(benchmark, sectors, history)
    snapshot_as_of = as_of or benchmark_bars[-1].date
    asset_symbols = {item.symbol for item in (assets or [])}
    snapshot_history = {
        symbol: [bar for bar in bars if bar.date <= snapshot_as_of]
        if symbol in asset_symbols else bars
        for symbol, bars in history.items()
    }
    return {
        "created_at": created_at or utc_timestamp(),
        "as_of": snapshot_as_of,
        "provider": provider,
        "benchmark": {"symbol": benchmark.symbol, "name": benchmark.name},
        "references": [
            {"symbol": reference.symbol, "name": reference.name}
            for reference in (references or [])
        ],
        "sectors": [{"symbol": sector.symbol, "name": sector.name} for sector in sectors],
        "metrics": [_metric_to_dict(metric) for metric in metrics],
        "assets": [{"symbol": item.symbol, "name": item.name} for item in (assets or [])],
        "asset_metrics": calculate_asset_metrics(benchmark, assets or [], history, snapshot_as_of),
        "sector_weights": sector_weights or {"status": "unavailable"},
        "market": serialize_history(snapshot_history),
    }


def calculate_asset_metrics(
    benchmark: Instrument,
    assets: list[Instrument],
    history: dict[str, list[PriceBar]],
    as_of: str,
) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    benchmark_by_date = {bar.date: bar for bar in history[benchmark.symbol] if bar.date <= as_of}
    for asset in assets:
        by_date = {bar.date: bar for bar in history.get(asset.symbol, []) if bar.date <= as_of}
        dates = sorted(set(by_date) & set(benchmark_by_date))
        row: dict[str, object] = {"symbol": asset.symbol, "name": asset.name, "status": "unavailable"}
        if dates:
            bars = [by_date[day] for day in dates]
            spy = [benchmark_by_date[day] for day in dates]
            returns = _window_returns(bars)
            benchmark_returns = _window_returns(spy)
            relative = {label: _subtract(returns[label], benchmark_returns[label]) for label in WINDOWS}
            row.update(
                status="available", as_of=dates[-1], close=bars[-1].close,
                returns=_rounded_dict(returns), relative_returns=_rounded_dict(relative),
            )
        result.append(row)
    return result


def calculate_sector_metrics(
    benchmark: Instrument,
    sectors: list[Instrument],
    history: dict[str, list[PriceBar]],
) -> list[SectorMetric]:
    benchmark_returns = _window_returns(history[benchmark.symbol])
    interim: list[dict[str, object]] = []
    for sector in sectors:
        bars = history.get(sector.symbol, [])
        if len(bars) < 64:
            raise ValueError(f"{sector.symbol} needs at least 64 price bars")
        returns = _window_returns(bars)
        relative = {
            label: _subtract(returns[label], benchmark_returns[label])
            for label in WINDOWS
        }
        ma10 = _moving_average(bars, 10)
        ma50 = _moving_average(bars, 50)
        ma150 = _moving_average(bars, 150)
        close = bars[-1].close
        trend_score = _trend_score(close, ma10, ma50)
        trend = _trend_label(trend_score)
        vol = _realized_volatility(bars, 21)
        interim.append(
            {
                "symbol": sector.symbol,
                "name": sector.name,
                "close": close,
                "returns": returns,
                "relative_returns": relative,
                "moving_averages": {"10d": ma10, "50d": ma50, "150d": ma150},
                "trend": trend,
                "trend_score": trend_score,
                "volatility_21d": vol,
            }
        )

    scores = _score_metrics(interim)
    ranked: list[SectorMetric] = []
    for rank, item in enumerate(sorted(interim, key=lambda row: scores[str(row["symbol"])], reverse=True), start=1):
        score = scores[str(item["symbol"])]
        relative_21d = item["relative_returns"]["21d"]  # type: ignore[index]
        trend_score = item["trend_score"]
        signal = _signal(score, relative_21d, trend_score)  # type: ignore[arg-type]
        ranked.append(
            SectorMetric(
                symbol=str(item["symbol"]),
                name=str(item["name"]),
                rank=rank,
                score=round(score, 2),
                signal=signal,
                close=round(float(item["close"]), 4),
                returns=_rounded_dict(item["returns"]),  # type: ignore[arg-type]
                relative_returns=_rounded_dict(item["relative_returns"]),  # type: ignore[arg-type]
                moving_averages=_rounded_dict(item["moving_averages"]),  # type: ignore[arg-type]
                trend=str(item["trend"]),
                volatility_21d=_round_or_none(item["volatility_21d"]),  # type: ignore[arg-type]
            )
        )
    return ranked


def _score_metrics(rows: list[dict[str, object]]) -> dict[str, float]:
    score: dict[str, float] = {str(row["symbol"]): 0.0 for row in rows}
    for label, weight in [("5d", 20.0), ("21d", 35.0), ("63d", 25.0)]:
        values = {
            str(row["symbol"]): row["relative_returns"][label]  # type: ignore[index]
            for row in rows
        }
        for symbol, points in _rank_points(values).items():
            score[symbol] += points * weight

    trend_values = {str(row["symbol"]): row["trend_score"] for row in rows}
    for symbol, points in _rank_points(trend_values).items():
        score[symbol] += points * 10.0

    volatility_values = {
        str(row["symbol"]): -float(row["volatility_21d"] or 0.0)
        for row in rows
    }
    for symbol, points in _rank_points(volatility_values).items():
        score[symbol] += points * 10.0

    return {symbol: (value - 50.0) * 2.0 for symbol, value in score.items()}


def _rank_points(values: dict[str, object]) -> dict[str, float]:
    clean = [(symbol, float(value)) for symbol, value in values.items() if value is not None]
    clean.sort(key=lambda item: item[1])
    if len(clean) == 1:
        return {clean[0][0]: 0.5}
    points: dict[str, float] = {}
    for index, (symbol, _) in enumerate(clean):
        points[symbol] = index / (len(clean) - 1)
    return points


def _window_returns(bars: list[PriceBar]) -> dict[str, float | None]:
    return {label: _return_over_window(bars, window) for label, window in WINDOWS.items()}


def _return_over_window(bars: list[PriceBar], window: int) -> float | None:
    if len(bars) <= window:
        return None
    start = bars[-window - 1].close
    end = bars[-1].close
    if start == 0:
        return None
    return (end / start) - 1


def _moving_average(bars: list[PriceBar], window: int) -> float | None:
    if len(bars) < window:
        return None
    return mean(bar.close for bar in bars[-window:])


def _realized_volatility(bars: list[PriceBar], window: int) -> float | None:
    if len(bars) <= window:
        return None
    daily_returns = []
    for prev, current in zip(bars[-window - 1 : -1], bars[-window:]):
        if prev.close <= 0:
            continue
        daily_returns.append((current.close / prev.close) - 1)
    if len(daily_returns) < 2:
        return None
    return stdev(daily_returns) * math.sqrt(252)


def _trend_score(close: float, ma10: float | None, ma50: float | None) -> float:
    score = 0.0
    if ma10 and close > ma10:
        score += 0.5
    if ma50 and close > ma50:
        score += 0.5
    if ma10 and ma50 and ma10 > ma50:
        score += 0.5
    return score


def _trend_label(score: float) -> str:
    if score >= 1.5:
        return "bullish"
    if score >= 1.0:
        return "constructive"
    if score >= 0.5:
        return "mixed"
    return "weak"


def _signal(score: float, relative_21d: float | None, trend_score: float) -> str:
    rel = relative_21d or 0.0
    if score > 20 and rel > 0 and trend_score >= 1.0:
        return "LEADING"
    if score > 0:
        return "IMPROVING"
    if score < -20 and rel < 0 and trend_score < 1.0:
        return "LAGGING"
    return "WEAKENING"


def _subtract(left: float | None, right: float | None) -> float | None:
    if left is None or right is None:
        return None
    return left - right


def _rounded_dict(values: dict[str, float | None]) -> dict[str, float | None]:
    return {key: _round_or_none(value) for key, value in values.items()}


def _round_or_none(value: float | None) -> float | None:
    if value is None:
        return None
    return round(float(value), 6)


def _metric_to_dict(metric: SectorMetric) -> dict[str, object]:
    return {
        "symbol": metric.symbol,
        "name": metric.name,
        "rank": metric.rank,
        "score": metric.score,
        "signal": metric.signal,
        "close": metric.close,
        "returns": metric.returns,
        "relative_returns": metric.relative_returns,
        "moving_averages": metric.moving_averages,
        "trend": metric.trend,
        "volatility_21d": metric.volatility_21d,
    }
