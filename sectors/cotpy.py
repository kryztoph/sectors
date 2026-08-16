from __future__ import annotations

import html
import json
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from statistics import mean
from typing import Any

from .market_data import get_market_data_provider
from .model import PriceBar


DEFAULT_INDEX = Path("reports") / "cotpy" / "index.html"
DEFAULT_CHART_DIR = Path("reports") / "cotpy" / "charts"
DEFAULT_LOOKBACK = 104


@dataclass(frozen=True)
class CotpyInstrument:
    symbol: str
    name: str
    ticker: str


COTPY_UNIVERSE: list[CotpyInstrument] = [
    CotpyInstrument("GOLD", "Gold", "GC=F"),
    CotpyInstrument("SILVER", "Silver", "SI=F"),
    CotpyInstrument("COPPER", "Copper", "HG=F"),
    CotpyInstrument("CRUDE_OIL", "Crude Oil", "CL=F"),
    CotpyInstrument("NATURAL_GAS", "Natural Gas", "NG=F"),
    CotpyInstrument("PLATINUM", "Platinum", "PL=F"),
    CotpyInstrument("CORN", "Corn", "ZC=F"),
    CotpyInstrument("WHEAT", "Wheat", "ZW=F"),
    CotpyInstrument("SOYBEANS", "Soybeans", "ZS=F"),
    CotpyInstrument("COFFEE", "Coffee", "KC=F"),
    CotpyInstrument("SUGAR", "Sugar", "SB=F"),
    CotpyInstrument("COTTON", "Cotton", "CT=F"),
]


def write_cotpy_charts(
    root: Path,
    history: dict[str, list[PriceBar]] | None = None,
    provider_name: str = "yfinance",
    period: str = "2y",
    output: Path | None = None,
    chart_dir: Path | None = None,
    lookback: int = DEFAULT_LOOKBACK,
) -> list[Path]:
    if history is None:
        provider = get_market_data_provider(provider_name)
        history = provider.fetch_history([item.ticker for item in COTPY_UNIVERSE], period=period)
    if lookback <= 0:
        raise ValueError("lookback must be greater than zero")

    target_index = output or root / DEFAULT_INDEX
    target_dir = chart_dir or root / DEFAULT_CHART_DIR
    target_dir.mkdir(parents=True, exist_ok=True)

    pages: list[dict[str, Any]] = []
    written: list[Path] = []
    missing: list[str] = []

    for item in COTPY_UNIVERSE:
        bars = _weekly_bars(history.get(item.ticker, []))
        if len(bars) < 8:
            missing.append(item.symbol)
            continue
        window = bars[-lookback:]
        latest = window[-1]
        page_path = target_dir / f"{item.symbol}_interactive.html"
        page_path.write_text(
            build_cotpy_chart_html(item=item, bars=window),
            encoding="utf-8",
        )
        pages.append(
            {
                "symbol": item.symbol,
                "name": item.name,
                "ticker": item.ticker,
                "href": f"charts/{item.symbol}_interactive.html",
                "latest_close": latest.close,
                "latest_date": latest.date,
                "return_13w": _return_over_window(window, 13),
                "return_26w": _return_over_window(window, 26),
                "return_52w": _return_over_window(window, 52),
                "trend": _trend_label(window),
            }
        )
        written.append(page_path)

    if not pages:
        raise ValueError("no cotpy charts could be generated")
    if missing:
        raise ValueError("insufficient history for cotpy symbols: " + ", ".join(sorted(missing)))

    target_index.parent.mkdir(parents=True, exist_ok=True)
    target_index.write_text(build_cotpy_index_html(pages), encoding="utf-8")
    return [target_index, *written]


def build_cotpy_chart_html(item: CotpyInstrument, bars: list[PriceBar]) -> str:
    closes = [bar.close for bar in bars]
    plot_data = {
        "dates": [bar.date for bar in bars],
        "opens": [bar.open if bar.open is not None else bar.close for bar in bars],
        "highs": [bar.high if bar.high is not None else max(bar.open or bar.close, bar.close) for bar in bars],
        "lows": [bar.low if bar.low is not None else min(bar.open or bar.close, bar.close) for bar in bars],
        "closes": closes,
        "volumes": [bar.volume or 0 for bar in bars],
        "ma10": _moving_average(closes, 10),
        "ma26": _moving_average(closes, 26),
    }
    stats = [
        ("Source", item.ticker),
        ("Last Close", _number(closes[-1])),
        ("13W Return", _pct(_return_over_window(bars, 13))),
        ("26W Return", _pct(_return_over_window(bars, 26))),
        ("Trend", _trend_label(bars)),
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
  <title>{html.escape(item.symbol)} Interactive</title>
  <style>{_css()}</style>
  <script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
</head>
<body>
  <main>
    <header>
      <div>
        {_brand_html("../../../assets/logo.png", "../index.html")}
        <p class="eyebrow">Weekly COTPY commodity chart</p>
        <h1>{html.escape(item.name)} <span class="ticker">{html.escape(item.symbol)}</span></h1>
        <p class="meta">Source ticker {html.escape(item.ticker)} · Last weekly bar {html.escape(bars[-1].date)}</p>
      </div>
    </header>

    <section class="stats" aria-label="Commodity stats">
      {stats_html}
    </section>

    <section class="chart-card" aria-label="{html.escape(item.name)} weekly interactive chart">
      <div id="chart" role="img" aria-label="{html.escape(item.symbol)} interactive chart"></div>
    </section>

    {_footer_html()}
  </main>
  <script>
    const data = {json.dumps(plot_data, ensure_ascii=False)};
    const traces = [
      {{
        type: "candlestick",
        name: "{html.escape(item.name)}",
        x: data.dates,
        open: data.opens,
        high: data.highs,
        low: data.lows,
        close: data.closes,
        increasing: {{line: {{color: "#1f8f5f"}}}},
        decreasing: {{line: {{color: "#b94a48"}}}},
        xaxis: "x",
        yaxis: "y",
      }},
      {{
        type: "bar",
        name: "Volume",
        x: data.dates,
        y: data.volumes,
        marker: {{color: "rgba(79, 110, 149, 0.34)"}},
        xaxis: "x",
        yaxis: "y2",
        hovertemplate: "%{{x}}<br>Volume: %{{y:,}}<extra></extra>",
      }},
      {{
        type: "scatter",
        mode: "lines",
        name: "10W MA",
        x: data.dates,
        y: data.ma10,
        line: {{color: "#2f6fb2", width: 2}},
        connectgaps: false,
        xaxis: "x",
        yaxis: "y",
      }},
      {{
        type: "scatter",
        mode: "lines",
        name: "26W MA",
        x: data.dates,
        y: data.ma26,
        line: {{color: "#6f4aa8", width: 2}},
        connectgaps: false,
        xaxis: "x",
        yaxis: "y",
      }},
    ];
    const layout = {{
      template: "plotly_white",
      hovermode: "x unified",
      margin: {{t: 16, l: 56, r: 56, b: 40}},
      legend: {{orientation: "h", y: 1.08}},
      xaxis: {{rangeslider: {{visible: false}}, showgrid: true}},
      yaxis: {{title: "Price", domain: [0.34, 1], fixedrange: false}},
      yaxis2: {{title: "Volume", domain: [0, 0.24], fixedrange: false, showgrid: false, anchor: "x"}},
    }};
    Plotly.newPlot("chart", traces, layout, {{responsive: true, displaylogo: false}});
  </script>
</body>
</html>
"""


def build_cotpy_index_html(pages: list[dict[str, Any]]) -> str:
    rows = "\n".join(_index_row_html(page) for page in pages)
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>COTPY Charts</title>
  <style>{_index_css()}</style>
</head>
<body>
  <main>
    <header>
      <div>
        {_brand_html("../../assets/logo.png", "../../index.html")}
        <p class="eyebrow">Weekly commodity chart set</p>
        <h1>COTPY Charts</h1>
        <p class="meta">Interactive weekly commodity charts generated from the current key commodities universe.</p>
      </div>
    </header>

    <section class="panel" aria-label="Commodity chart index">
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Commodity</th>
              <th>Source</th>
              <th>Last Date</th>
              <th class="num">Last Close</th>
              <th class="num">13W Return</th>
              <th class="num">26W Return</th>
              <th class="num">52W Return</th>
              <th>Trend</th>
            </tr>
          </thead>
          <tbody>{rows}</tbody>
        </table>
      </div>
    </section>

    {_footer_html()}
  </main>
</body>
</html>
"""


def _index_row_html(page: dict[str, Any]) -> str:
    return """
            <tr>
              <td><a href="{href}">{symbol}</a></td>
              <td>{name}</td>
              <td>{latest_date}</td>
              <td class="num">{latest_close}</td>
              <td class="num">{ret13}</td>
              <td class="num">{ret26}</td>
              <td class="num">{ret52}</td>
              <td>{trend}</td>
            </tr>""".format(
        href=_escape(page["href"]),
        symbol=_escape(page["symbol"]),
        name=_escape(page["name"]),
        latest_date=_escape(page["latest_date"]),
        latest_close=_escape(_number(page["latest_close"])),
        ret13=_escape(_pct(page["return_13w"])),
        ret26=_escape(_pct(page["return_26w"])),
        ret52=_escape(_pct(page["return_52w"])),
        trend=_escape(str(page["trend"])),
    )


def _weekly_bars(rows: object) -> list[PriceBar]:
    bars = _parse_bars(rows)
    if not bars:
        return []
    weekly: dict[str, list[PriceBar]] = {}
    order: list[str] = []
    for bar in sorted(bars, key=lambda item: item.date):
        week_start = (date.fromisoformat(bar.date) - timedelta(days=date.fromisoformat(bar.date).weekday())).isoformat()
        if week_start not in weekly:
            weekly[week_start] = []
            order.append(week_start)
        weekly[week_start].append(bar)

    aggregated: list[PriceBar] = []
    for key in order:
        group = weekly[key]
        first = group[0]
        last = group[-1]
        open_price = first.open if first.open is not None else first.close
        high = max(bar.high if bar.high is not None else max(bar.open or bar.close, bar.close) for bar in group)
        low = min(bar.low if bar.low is not None else min(bar.open or bar.close, bar.close) for bar in group)
        volume = sum(bar.volume or 0 for bar in group) or None
        aggregated.append(
            PriceBar(
                date=last.date,
                open=open_price,
                high=high,
                low=low,
                close=last.close,
                volume=volume,
            )
        )
    return aggregated


def _parse_bars(rows: object) -> list[PriceBar]:
    bars: list[PriceBar] = []
    if not isinstance(rows, list):
        return bars
    for row in rows:
        if isinstance(row, PriceBar):
            bars.append(row)
            continue
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
            PriceBar(
                date=str(row.get("date") or ""),
                open=open_price,
                high=max(high, open_price, close),
                low=min(low, open_price, close),
                close=close,
                volume=int(volume) if isinstance(volume, int | float) else None,
            )
        )
    return bars


def _moving_average(values: list[float], window: int) -> list[float | None]:
    output: list[float | None] = []
    for index in range(len(values)):
        if index + 1 < window:
            output.append(None)
        else:
            output.append(mean(values[index + 1 - window : index + 1]))
    return output


def _return_over_window(bars: list[PriceBar], window: int) -> float | None:
    if len(bars) <= window:
        return None
    start = bars[-window - 1].close
    end = bars[-1].close
    if start == 0:
        return None
    return (end / start) - 1


def _trend_label(bars: list[PriceBar]) -> str:
    closes = [bar.close for bar in bars]
    ma10 = _moving_average(closes, 10)
    ma26 = _moving_average(closes, 26)
    latest = closes[-1]
    latest_ma10 = ma10[-1] if ma10 else None
    latest_ma26 = ma26[-1] if ma26 else None
    if latest_ma10 is None or latest_ma26 is None:
        return "forming"
    if latest > latest_ma10 and latest_ma10 > latest_ma26:
        return "bullish"
    if latest > latest_ma10:
        return "constructive"
    if latest < latest_ma26:
        return "weak"
    return "mixed"


def _float(value: object) -> float | None:
    try:
        parsed = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if parsed != parsed:
        return None
    return parsed


def _number(value: object) -> str:
    parsed = _float(value)
    return "N/A" if parsed is None else f"{parsed:.2f}"


def _pct(value: object) -> str:
    parsed = _float(value)
    return "N/A" if parsed is None else f"{parsed * 100:.2f}%"


def _brand_html(logo_path: str, home_path: str) -> str:
    return f"""<a class="brand" href="{_escape(home_path)}" aria-label="CSFox home">
          <img class="brand-logo" src="{_escape(logo_path)}" alt="">
          <span class="brand-text">CSFox.com</span>
        </a>"""


def _footer_html() -> str:
    return '<footer class="report-footer">Copyright &copy; 2026 csfox.com. All rights reserved.</footer>'


def _escape(value: object) -> str:
    return html.escape(str(value))


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
      --ma10: #2f6fb2;
      --ma26: #6f4aa8;
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
    .brand-logo { width: 46px; height: auto; display: block; }
    .brand-text { font-size: 18px; font-weight: 750; }
    .eyebrow {
      margin: 0 0 4px;
      color: var(--muted);
      font-size: 13px;
      letter-spacing: .08em;
      text-transform: uppercase;
    }
    h1 { margin: 0; font-size: 30px; }
    h1 .ticker { font-size: 18px; color: var(--muted); font-weight: 600; margin-left: 8px; }
    .meta { color: var(--muted); margin: 8px 0 0; font-size: 14px; }
    .stats, .panel, .chart-card {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
    }
    .stats {
      display: grid;
      grid-template-columns: repeat(5, minmax(82px, 1fr));
      overflow: hidden;
      margin-bottom: 16px;
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
    .chart-card { padding: 12px; overflow-x: auto; }
    #chart { width: 100%; min-width: 860px; height: 760px; }
    .panel { padding: 12px; }
    .table-wrap { overflow-x: auto; }
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
    .num { text-align: right; }
    table a {
      color: #245fa8;
      text-decoration: none;
      font-weight: 650;
    }
    table a:hover { text-decoration: underline; }
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
      }
      #chart { min-width: 0; height: 640px; }
    }
    """


def _index_css() -> str:
    return _css()
