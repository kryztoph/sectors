from __future__ import annotations

import html
import json
import math
from dataclasses import dataclass
from pathlib import Path
from statistics import mean
from typing import Any


DEFAULT_INDEX = Path("reports") / "sector_charts.html"
DEFAULT_CHART_DIR = Path("reports") / "charts"


@dataclass(frozen=True)
class ChartBar:
    date: str
    open: float
    high: float
    low: float
    close: float
    volume: int | None


def write_sector_charts(
    root: Path,
    snapshot_path: Path | None = None,
    output: Path | None = None,
    chart_dir: Path | None = None,
    lookback: int = 126,
) -> list[Path]:
    snapshot = _load_snapshot(snapshot_path or _latest_snapshot(root))
    benchmark_symbol = str(snapshot.get("benchmark", {}).get("symbol") or "SPY")
    sectors = [item for item in snapshot.get("sectors", []) if isinstance(item, dict)]
    market = snapshot.get("market")
    if not isinstance(market, dict):
        raise ValueError("snapshot has no market history")

    target_index = output or root / DEFAULT_INDEX
    target_dir = chart_dir or root / DEFAULT_CHART_DIR
    target_dir.mkdir(parents=True, exist_ok=True)

    benchmark = _parse_bars(market.get(benchmark_symbol, []))
    if not benchmark:
        raise ValueError(f"snapshot has no benchmark history for {benchmark_symbol}")

    pages: list[dict[str, str]] = []
    written: list[Path] = []
    metrics = {
        str(item.get("symbol")): item
        for item in snapshot.get("metrics", [])
        if isinstance(item, dict) and item.get("symbol")
    }
    for sector in sectors:
        symbol = str(sector.get("symbol") or "")
        if not symbol:
            continue
        bars = _parse_bars(market.get(symbol, []))
        if not bars:
            continue
        path = target_dir / f"{symbol}.html"
        name = str(sector.get("name") or symbol)
        path.write_text(
            build_sector_chart_html(
                symbol=symbol,
                name=name,
                benchmark_symbol=benchmark_symbol,
                bars=bars[-lookback:],
                benchmark=benchmark,
                snapshot=snapshot,
                metric=metrics.get(symbol, {}),
            ),
            encoding="utf-8",
        )
        pages.append({"symbol": symbol, "name": name, "href": f"charts/{symbol}.html"})
        written.append(path)

    target_index.parent.mkdir(parents=True, exist_ok=True)
    target_index.write_text(build_index_html(snapshot, pages), encoding="utf-8")
    return [target_index, *written]


def build_sector_chart_html(
    symbol: str,
    name: str,
    benchmark_symbol: str,
    bars: list[ChartBar],
    benchmark: list[ChartBar],
    snapshot: dict[str, Any],
    metric: dict[str, Any] | None = None,
) -> str:
    metric = metric or {}
    svg = _build_svg(symbol, benchmark_symbol, bars, benchmark)
    title = f"{symbol} Sector Chart"
    rel = metric.get("relative_returns") if isinstance(metric.get("relative_returns"), dict) else {}
    stats = [
        ("Signal", str(metric.get("signal", "N/A"))),
        ("Rank", str(metric.get("rank", "N/A"))),
        ("Score", _number(metric.get("score"))),
        ("Rel 21d", _pct(rel.get("21d") if isinstance(rel, dict) else None)),
        ("Trend", str(metric.get("trend", "N/A"))),
    ]
    stats_html = "\n".join(
        f"<div><span>{html.escape(label)}</span><strong>{html.escape(value)}</strong></div>"
        for label, value in stats
    )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(title)}</title>
  <style>{_css()}</style>
</head>
<body>
  <main>
    <header>
      <div>
        {_brand_html("../../../assets/logo.png", "../../../index.html")}
        <a href="../sector_rotation_tracker.html">Sector rotation tracker</a>
        <h1>{html.escape(symbol)} - {html.escape(name)}</h1>
        <p>As of {html.escape(str(snapshot.get("as_of", "unknown")))} from {html.escape(str(snapshot.get("provider", "unknown")))}.</p>
      </div>
      <section class="stats" aria-label="Sector metrics">
        {stats_html}
      </section>
    </header>
    <section class="chart" aria-label="{html.escape(symbol)} candlestick chart">
      {svg}
    </section>
    {_footer_html()}
  </main>
</body>
</html>
"""


def build_index_html(snapshot: dict[str, Any], pages: list[dict[str, str]]) -> str:
    rows = "\n".join(
        f"""<tr><td><a href="{html.escape(page["href"])}">{html.escape(page["symbol"])}</a></td><td>{html.escape(page["name"])}</td></tr>"""
        for page in pages
    )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Sector Charts</title>
  <style>{_css()}</style>
</head>
<body>
  <main>
    <header>
      <div>
        {_brand_html("../../assets/logo.png", "../../index.html")}
        <h1>Sector Charts</h1>
        <p>Daily candlestick charts with volume, moving averages, relative strength, and trendlines. As of {html.escape(str(snapshot.get("as_of", "unknown")))}.</p>
      </div>
    </header>
    <table>
      <thead><tr><th>Symbol</th><th>Sector</th></tr></thead>
      <tbody>{rows}</tbody>
    </table>
    {_footer_html()}
  </main>
</body>
</html>
"""


def _brand_html(logo_path: str, home_path: str) -> str:
    return f"""<a class="brand" href="{html.escape(home_path)}" aria-label="CSFox home">
          <img class="brand-logo" src="{html.escape(logo_path)}" alt="">
          <span class="brand-text">CSFox.com</span>
        </a>"""


def _footer_html() -> str:
    return '<footer class="report-footer">Copyright &copy; 2026 csfox.com. All rights reserved.</footer>'


def _build_svg(symbol: str, benchmark_symbol: str, bars: list[ChartBar], benchmark: list[ChartBar]) -> str:
    if len(bars) < 2:
        raise ValueError(f"{symbol} needs at least 2 bars for charting")
    benchmark_by_date = {bar.date: bar for bar in benchmark}
    rs = _relative_strength(bars, benchmark_by_date)
    ma20 = _moving_average([bar.close for bar in bars], 20)
    ma50 = _moving_average([bar.close for bar in bars], 50)
    volume_ma = _moving_average([float(bar.volume or 0) for bar in bars], 20)

    width = 1120
    height = 760
    left = 66
    right = 42
    top = 36
    price_top = top
    price_height = 390
    volume_top = price_top + price_height + 32
    volume_height = 104
    rs_top = volume_top + volume_height + 42
    rs_height = 130
    plot_width = width - left - right

    lows = [bar.low for bar in bars]
    highs = [bar.high for bar in bars]
    price_min, price_max = _pad_range(min(lows), max(highs))
    volume_max = max([float(bar.volume or 0) for bar in bars] or [1.0])
    rs_values = [value for value in rs if value is not None]
    rs_min, rs_max = _pad_range(min(rs_values), max(rs_values)) if rs_values else (0.0, 1.0)

    def x(index: int) -> float:
        if len(bars) == 1:
            return left + plot_width / 2
        return left + index * plot_width / (len(bars) - 1)

    def y_price(value: float) -> float:
        return price_top + (price_max - value) * price_height / (price_max - price_min)

    def y_volume(value: float) -> float:
        return volume_top + volume_height - value * volume_height / max(volume_max, 1.0)

    def y_rs(value: float) -> float:
        return rs_top + (rs_max - value) * rs_height / (rs_max - rs_min)

    candle_width = max(3.0, min(9.0, plot_width / len(bars) * 0.58))
    parts = [
        f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="{html.escape(symbol)} candlestick chart with volume moving average, relative strength, and trendlines">',
        '<rect class="svg-bg" x="0" y="0" width="1120" height="760"/>',
        _panel(left, price_top, plot_width, price_height, f"{symbol} candlestick with 20d and 50d moving averages"),
        _panel(left, volume_top, plot_width, volume_height, "Volume and 20d volume MA"),
        _panel(left, rs_top, plot_width, rs_height, f"Relative strength versus {benchmark_symbol}"),
        _axis_labels(left, plot_width, price_top, price_height, price_min, price_max),
        _axis_labels(left, plot_width, rs_top, rs_height, rs_min, rs_max),
    ]
    for index, bar in enumerate(bars):
        cx = x(index)
        up = bar.close >= bar.open
        klass = "up" if up else "down"
        parts.append(f'<line class="wick {klass}" x1="{cx:.2f}" x2="{cx:.2f}" y1="{y_price(bar.high):.2f}" y2="{y_price(bar.low):.2f}"/>')
        y1 = y_price(max(bar.open, bar.close))
        y2 = y_price(min(bar.open, bar.close))
        body_height = max(1.0, y2 - y1)
        parts.append(f'<rect class="candle {klass}" x="{cx - candle_width / 2:.2f}" y="{y1:.2f}" width="{candle_width:.2f}" height="{body_height:.2f}"/>')
        if bar.volume:
            vheight = volume_top + volume_height - y_volume(float(bar.volume))
            parts.append(f'<rect class="volume {klass}" x="{cx - candle_width / 2:.2f}" y="{y_volume(float(bar.volume)):.2f}" width="{candle_width:.2f}" height="{max(1.0, vheight):.2f}"/>')

    parts.append(_polyline(ma20, x, y_price, "ma20"))
    parts.append(_polyline(ma50, x, y_price, "ma50"))
    parts.append(_polyline(volume_ma, x, y_volume, "volume-ma"))
    parts.append(_polyline(rs, x, y_rs, "rs-line"))
    parts.append(_trendline([bar.close for bar in bars], x, y_price, "price-trend"))
    parts.append(_trendline(rs, x, y_rs, "rs-trend"))
    parts.extend(
        [
            f'<text class="panel-title" x="{left}" y="{price_top - 12}">{html.escape(symbol)} price</text>',
            f'<text class="panel-title" x="{left}" y="{volume_top - 10}">Volume moving average</text>',
            f'<text class="panel-title" x="{left}" y="{rs_top - 10}">Relative strength vs {html.escape(benchmark_symbol)}</text>',
            _legend(width - 380, 24),
            f'<text class="date start" x="{left}" y="{height - 18}">{html.escape(bars[0].date)}</text>',
            f'<text class="date end" x="{left + plot_width}" y="{height - 18}">{html.escape(bars[-1].date)}</text>',
            "</svg>",
        ]
    )
    return "\n".join(part for part in parts if part)


def _parse_bars(rows: object) -> list[ChartBar]:
    bars: list[ChartBar] = []
    if not isinstance(rows, list):
        return bars
    for row in rows:
        if not isinstance(row, dict):
            continue
        close = _float(row.get("close"))
        if close is None:
            continue
        open_price = _float(row.get("open")) or close
        high = _float(row.get("high")) or max(open_price, close)
        low = _float(row.get("low")) or min(open_price, close)
        volume = row.get("volume")
        bars.append(
            ChartBar(
                date=str(row.get("date") or ""),
                open=open_price,
                high=max(high, open_price, close),
                low=min(low, open_price, close),
                close=close,
                volume=int(volume) if isinstance(volume, int | float) else None,
            )
        )
    return bars


def _relative_strength(bars: list[ChartBar], benchmark_by_date: dict[str, ChartBar]) -> list[float | None]:
    raw: list[float | None] = []
    first: float | None = None
    for bar in bars:
        bench = benchmark_by_date.get(bar.date)
        if not bench or bench.close <= 0:
            raw.append(None)
            continue
        value = bar.close / bench.close
        if first is None:
            first = value
        raw.append((value / first) * 100 if first else None)
    return raw


def _moving_average(values: list[float], window: int) -> list[float | None]:
    output: list[float | None] = []
    for index in range(len(values)):
        if index + 1 < window:
            output.append(None)
        else:
            output.append(mean(values[index + 1 - window : index + 1]))
    return output


def _trendline(values: list[float | None], x_fn: Any, y_fn: Any, klass: str) -> str:
    points = [(index, value) for index, value in enumerate(values) if value is not None]
    if len(points) < 2:
        return ""
    xs = [float(index) for index, _ in points]
    ys = [float(value) for _, value in points]
    x_mean = mean(xs)
    y_mean = mean(ys)
    denom = sum((item - x_mean) ** 2 for item in xs)
    if denom == 0:
        return ""
    slope = sum((xv - x_mean) * (yv - y_mean) for xv, yv in zip(xs, ys)) / denom
    intercept = y_mean - slope * x_mean
    first = points[0][0]
    last = points[-1][0]
    y_first = intercept + slope * first
    y_last = intercept + slope * last
    return f'<line class="trendline {klass}" x1="{x_fn(first):.2f}" y1="{y_fn(y_first):.2f}" x2="{x_fn(last):.2f}" y2="{y_fn(y_last):.2f}"/>'


def _polyline(values: list[float | None], x_fn: Any, y_fn: Any, klass: str) -> str:
    points = [
        f"{x_fn(index):.2f},{y_fn(float(value)):.2f}"
        for index, value in enumerate(values)
        if value is not None
    ]
    if len(points) < 2:
        return ""
    return f'<polyline class="{klass}" points="{" ".join(points)}"/>'


def _panel(left: int, top: int, width: int, height: int, label: str) -> str:
    return f'<rect class="panel" x="{left}" y="{top}" width="{width}" height="{height}" aria-label="{html.escape(label)}"/>'


def _axis_labels(left: int, width: int, top: int, height: int, minimum: float, maximum: float) -> str:
    return "\n".join(
        [
            f'<text class="axis" x="{left - 12}" y="{top + 5}" text-anchor="end">{maximum:.2f}</text>',
            f'<text class="axis" x="{left - 12}" y="{top + height + 4}" text-anchor="end">{minimum:.2f}</text>',
            f'<line class="grid" x1="{left}" x2="{left + width}" y1="{top + height / 2:.2f}" y2="{top + height / 2:.2f}"/>',
        ]
    )


def _legend(x: int, y: int) -> str:
    items = [
        ("ma20", "20d MA"),
        ("ma50", "50d MA"),
        ("price-trend", "Trendline"),
        ("rs-line", "Relative strength"),
    ]
    parts = []
    for index, (klass, label) in enumerate(items):
        item_x = x + (index % 2) * 180
        item_y = y + (index // 2) * 22
        parts.append(f'<line class="{klass}" x1="{item_x}" x2="{item_x + 28}" y1="{item_y}" y2="{item_y}"/>')
        parts.append(f'<text class="legend" x="{item_x + 36}" y="{item_y + 4}">{label}</text>')
    return "\n".join(parts)


def _pad_range(minimum: float, maximum: float) -> tuple[float, float]:
    if minimum == maximum:
        pad = abs(minimum) * 0.05 or 1.0
    else:
        pad = (maximum - minimum) * 0.06
    return minimum - pad, maximum + pad


def _load_snapshot(path: Path | None) -> dict[str, Any]:
    if path is None:
        raise ValueError("no snapshot found; run snapshot first")
    with path.open("r", encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return data


def _latest_snapshot(root: Path) -> Path | None:
    latest = root / "state" / "snapshots" / "latest.json"
    if latest.exists():
        return latest
    snapshots = sorted(path for path in (root / "state" / "snapshots").glob("*.json") if path.name != "latest.json")
    return snapshots[-1] if snapshots else None


def _float(value: object) -> float | None:
    try:
        result = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if math.isnan(result):
        return None
    return result


def _number(value: object) -> str:
    parsed = _float(value)
    return "N/A" if parsed is None else f"{parsed:.2f}"


def _pct(value: object) -> str:
    parsed = _float(value)
    return "N/A" if parsed is None else f"{parsed * 100:.2f}%"


def _css() -> str:
    return """
    :root {
      color-scheme: light;
      --bg: #f6f7f9;
      --text: #17202a;
      --muted: #687485;
      --line: #d8dee7;
      --panel: #ffffff;
      --up: #1f8f5f;
      --down: #b94a48;
      --ma20: #2f6fb2;
      --ma50: #6f4aa8;
      --rs: #bf7b22;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font-family: ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      line-height: 1.4;
    }
    main {
      width: min(1240px, calc(100vw - 32px));
      margin: 0 auto;
      padding: 24px 0 36px;
    }
    header {
      display: flex;
      justify-content: space-between;
      gap: 18px;
      align-items: center;
      margin-bottom: 18px;
    }
    .brand {
      display: inline-flex;
      align-items: center;
      gap: 10px;
      color: var(--text);
      text-decoration: none;
      margin-bottom: 8px;
    }
    .brand-logo {
      width: 46px;
      height: auto;
      display: block;
    }
    .brand-text {
      font-size: 18px;
      font-weight: 750;
    }
    h1 {
      margin: 4px 0 4px;
      font-size: 28px;
      letter-spacing: 0;
    }
    p, a {
      color: var(--muted);
      margin: 0;
      font-size: 14px;
    }
    a:hover { color: var(--text); }
    .chart, table, .stats {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
    }
    .chart {
      padding: 12px;
      overflow-x: auto;
    }
    svg {
      display: block;
      width: 100%;
      min-width: 820px;
      height: auto;
    }
    .stats {
      display: grid;
      grid-template-columns: repeat(5, minmax(82px, 1fr));
      min-width: 520px;
      overflow: hidden;
    }
    .stats div {
      padding: 10px 12px;
      border-left: 1px solid #edf0f4;
    }
    .stats div:first-child { border-left: 0; }
    .stats span {
      display: block;
      color: var(--muted);
      font-size: 12px;
    }
    .stats strong {
      display: block;
      font-size: 15px;
      margin-top: 2px;
    }
    table {
      width: 100%;
      border-collapse: collapse;
      overflow: hidden;
    }
    th, td {
      border-bottom: 1px solid #edf0f4;
      padding: 10px 12px;
      text-align: left;
      white-space: nowrap;
    }
    th {
      color: var(--muted);
      font-size: 13px;
    }
    .svg-bg { fill: #ffffff; }
    .panel {
      fill: #fbfcfd;
      stroke: #dce2ea;
    }
    .grid {
      stroke: #e9edf2;
      stroke-width: 1;
    }
    .wick.up, .candle.up { stroke: var(--up); fill: var(--up); }
    .wick.down, .candle.down { stroke: var(--down); fill: var(--down); }
    .wick { stroke-width: 1.5; }
    .volume.up { fill: rgba(31, 143, 95, 0.34); }
    .volume.down { fill: rgba(185, 74, 72, 0.34); }
    .ma20 {
      fill: none;
      stroke: var(--ma20);
      stroke-width: 2;
    }
    .ma50 {
      fill: none;
      stroke: var(--ma50);
      stroke-width: 2;
    }
    .volume-ma {
      fill: none;
      stroke: #45515f;
      stroke-width: 1.6;
    }
    .rs-line {
      fill: none;
      stroke: var(--rs);
      stroke-width: 2;
    }
    .trendline {
      fill: none;
      stroke: #111827;
      stroke-width: 1.7;
      stroke-dasharray: 7 5;
    }
    .rs-trend { stroke: #8c5a16; }
    .panel-title, .axis, .date, .legend {
      fill: #5f6b7a;
      font-size: 13px;
    }
    .panel-title { font-weight: 700; }
    .date.end { text-anchor: end; }
    .report-footer {
      margin-top: 18px;
      padding-top: 14px;
      border-top: 1px solid var(--line);
      color: var(--muted);
      font-size: 13px;
      text-align: center;
    }
    @media (max-width: 760px) {
      header { display: block; }
      .stats {
        grid-template-columns: repeat(2, minmax(0, 1fr));
        min-width: 0;
        margin-top: 14px;
      }
    }
    """
