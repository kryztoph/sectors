from __future__ import annotations

import html
from .context import context_html, pct
from pathlib import Path
from typing import Any


def build_brief(snapshot: dict[str, Any]) -> str:
    metrics = list(snapshot.get("metrics", []))
    leaders = metrics[:3]
    laggards = metrics[-3:]
    lines = [
        "# Sector Rotation Brief",
        "",
        f"Created: {snapshot.get('created_at', 'unknown')}",
        f"As of: {snapshot.get('as_of', 'unknown')}",
        f"Provider: {snapshot.get('provider', 'unknown')}",
        "",
        "## Summary",
        "",
    ]
    if leaders:
        lines.append("- Leaders: " + ", ".join(_label(row) for row in leaders))
    if laggards:
        lines.append("- Laggards: " + ", ".join(_label(row) for row in laggards))
    lines.extend(["", "## Rankings", ""])
    lines.append("| Rank | Sector | Symbol | Signal | Score | Rel 5d | Rel 21d | Rel 63d | Trend |")
    lines.append("| ---: | --- | --- | --- | ---: | ---: | ---: | ---: | --- |")
    for row in metrics:
        rel = row.get("relative_returns") or {}
        lines.append(
            "| {rank} | {name} | {symbol} | {signal} | {score:.2f} | {rel5} | {rel21} | {rel63} | {trend} |".format(
                rank=row.get("rank", ""),
                name=row.get("name", ""),
                symbol=row.get("symbol", ""),
                signal=row.get("signal", ""),
                score=float(row.get("score") or 0.0),
                rel5=_pct(rel.get("5d")),
                rel21=_pct(rel.get("21d")),
                rel63=_pct(rel.get("63d")),
                trend=row.get("trend", ""),
            )
        )
    allocation = snapshot.get("sector_weights") or {}
    lines.extend(["", "## S&P 500 sector weights", "", f"Allocation as of: {allocation.get('as_of', 'unavailable')}", f"Source: {allocation.get('source', 'unavailable')}", "", "| Sector | Index weight |", "| --- | ---: |"])
    for item in snapshot.get("sectors", []):
        lines.append(f"| {item['name']} | {pct((allocation.get('weights') or {}).get(item['symbol']))} |")
    lines.extend(["", "## Oil, 10-year notes and Bitcoin", "", "| Asset | Symbol | As of | 21 sessions | vs SPY |", "| --- | --- | --- | ---: | ---: |"])
    for item in snapshot.get("asset_metrics", []):
        lines.append(f"| {item['name']} | {item['symbol']} | {item.get('as_of', 'unavailable')} | {pct((item.get('returns') or {}).get('21d'))} | {pct((item.get('relative_returns') or {}).get('21d'))} |")
    lines.extend(["", "Assets use common SPY trading dates and are outside the sector ranks. Continuous futures rolls affect returns; ZN=F is a note price, not a yield."])
    lines.extend(["", "## Notes", ""])
    lines.append("- Relative returns are sector ETF returns minus SPY returns over the same window.")
    lines.append("- Scores are cross-sectional ranks; they are useful for rotation monitoring, not trade execution.")
    return "\n".join(lines) + "\n"


def build_brief_html(snapshot: dict[str, Any]) -> str:
    metrics = [row for row in snapshot.get("metrics", []) if isinstance(row, dict)]
    leaders = metrics[:3]
    laggards = metrics[-3:]
    rows = "\n".join(_metric_row_html(row) for row in metrics)
    leaders_html = ", ".join(_label(row) for row in leaders) or "N/A"
    laggards_html = ", ".join(_label(row) for row in laggards) or "N/A"
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Sector Rotation Brief</title>
  <style>{_brief_css()}</style>
</head>
<body>
  <main>
    <header>
      <div>
        {_brand_html("../../assets/logo.png", "../../index.html")}
        <p class="eyebrow">Sector rotation research</p>
        <h1>Sector Rotation Brief</h1>
        <p class="meta">Created {_escape(snapshot.get('created_at', 'unknown'))} · As of {_escape(snapshot.get('as_of', 'unknown'))} · Provider {_escape(snapshot.get('provider', 'unknown'))}</p>
      </div>
      <nav class="actions" aria-label="Report links">
        <a href="sector_rotation_tracker.html">Rotation tracker</a>
        <a href="sector_charts.html">Sector charts</a>
        <a href="latest-brief.md">Markdown brief</a>
      </nav>
    </header>
    <section class="summary" aria-label="Summary">
      <article><span>Leaders</span><strong>{_escape(leaders_html)}</strong></article>
      <article><span>Laggards</span><strong>{_escape(laggards_html)}</strong></article>
    </section>
    <section class="panel" aria-label="Sector rankings">
      <h2>Rankings</h2>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th class="num">Rank</th>
              <th>Sector</th>
              <th>Symbol</th>
              <th>Signal</th>
              <th class="num">Score</th>
              <th class="num">Rel 5d</th>
              <th class="num">Rel 21d</th>
              <th class="num">Rel 63d</th>
              <th>Trend</th>
            </tr>
          </thead>
          <tbody>{rows}</tbody>
        </table>
      </div>
    </section>
    {context_html(snapshot)}
    <section class="notes" aria-label="Notes">
      <h2>Notes</h2>
      <ul>
        <li>Relative returns are sector ETF returns minus SPY returns over the same window.</li>
        <li>Scores are cross-sectional ranks; they are useful for rotation monitoring, not trade execution.</li>
      </ul>
    </section>
    <footer class="report-footer">Copyright &copy; 2026 csfox.com. All rights reserved.</footer>
  </main>
</body>
</html>
"""


def write_brief(path: Path, snapshot: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(build_brief(snapshot), encoding="utf-8")


def write_brief_html(path: Path, snapshot: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(build_brief_html(snapshot), encoding="utf-8")


def _metric_row_html(row: dict[str, Any]) -> str:
    rel = row.get("relative_returns") if isinstance(row.get("relative_returns"), dict) else {}
    symbol = str(row.get("symbol", ""))
    chart_href = f"charts/{_escape(symbol)}.html"
    signal = str(row.get("signal", ""))
    return """
            <tr>
              <td class="num">{rank}</td>
              <td>{name}</td>
              <td><a href="{chart_href}">{symbol}</a></td>
              <td><span class="signal signal-{signal_class}">{signal}</span></td>
              <td class="num">{score}</td>
              <td class="num">{rel5}</td>
              <td class="num">{rel21}</td>
              <td class="num">{rel63}</td>
              <td>{trend}</td>
            </tr>""".format(
        rank=_escape(row.get("rank", "")),
        name=_escape(row.get("name", "")),
        chart_href=chart_href,
        symbol=_escape(symbol),
        signal=_escape(signal),
        signal_class=_escape(signal.lower()),
        score=_escape(_number(row.get("score"))),
        rel5=_escape(_pct(rel.get("5d") if isinstance(rel, dict) else None)),
        rel21=_escape(_pct(rel.get("21d") if isinstance(rel, dict) else None)),
        rel63=_escape(_pct(rel.get("63d") if isinstance(rel, dict) else None)),
        trend=_escape(row.get("trend", "")),
    )


def _label(row: dict[str, Any]) -> str:
    return f"{row.get('symbol', '')} {row.get('signal', '')}".strip()


def _pct(value: Any) -> str:
    if value is None:
        return "N/A"
    try:
        return f"{float(value) * 100:.2f}%"
    except (TypeError, ValueError):
        return "N/A"


def _number(value: Any) -> str:
    try:
        return f"{float(value):.2f}"
    except (TypeError, ValueError):
        return "N/A"


def _escape(value: object) -> str:
    return html.escape(str(value))


def _brand_html(logo_path: str, home_path: str) -> str:
    return f"""<a class="brand" href="{_escape(home_path)}" aria-label="CSFox home">
          <img class="brand-logo" src="{_escape(logo_path)}" alt="">
          <span class="brand-text">CSFox.com</span>
        </a>"""


def _brief_css() -> str:
    return """
    :root {
      color-scheme: light;
      --bg: #f6f7f9;
      --text: #17202a;
      --muted: #687485;
      --line: #d8dee7;
      --panel: #ffffff;
      --leading: #1f8f5f;
      --weakening: #c47b20;
      --lagging: #b64747;
      --improving: #3478b8;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font-family: ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      line-height: 1.45;
    }
    main {
      width: min(1180px, calc(100vw - 32px));
      margin: 0 auto;
      padding: 24px 0 36px;
    }
    header {
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      gap: 18px;
      margin-bottom: 18px;
    }
    .brand {
      display: inline-flex;
      align-items: center;
      gap: 10px;
      color: var(--text);
      text-decoration: none;
      margin-bottom: 12px;
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
    h1 { margin: 0; font-size: 32px; letter-spacing: -.02em; }
    h2 { margin: 0 0 12px; font-size: 18px; }
    .meta { color: var(--muted); margin: 8px 0 0; font-size: 14px; }
    .actions { display: flex; gap: 8px; flex-wrap: wrap; justify-content: flex-end; }
    .actions a, table a {
      color: #245fa8;
      text-decoration: none;
      font-weight: 650;
    }
    .actions a {
      border: 1px solid var(--line);
      background: var(--panel);
      border-radius: 999px;
      padding: 8px 12px;
      font-size: 14px;
    }
    .actions a:hover, table a:hover { text-decoration: underline; }
    .summary {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 12px;
      margin-bottom: 14px;
    }
    .summary article, .panel, .notes {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 10px;
    }
    .summary article { padding: 14px 16px; }
    .summary span { display: block; color: var(--muted); font-size: 13px; margin-bottom: 4px; }
    .summary strong { font-size: 18px; }
    .panel, .notes { padding: 16px; margin-top: 14px; }
    .table-wrap { overflow-x: auto; }
    table { width: 100%; border-collapse: collapse; font-size: 14px; }
    th, td { border-bottom: 1px solid #edf0f4; padding: 10px 9px; text-align: left; white-space: nowrap; }
    th { color: var(--muted); font-size: 12px; letter-spacing: .02em; text-transform: uppercase; }
    .num { text-align: right; font-variant-numeric: tabular-nums; }
    .signal { border-radius: 999px; color: #ffffff; display: inline-block; font-size: 12px; font-weight: 750; padding: 4px 8px; }
    .signal-leading { background: var(--leading); }
    .signal-weakening { background: var(--weakening); }
    .signal-lagging { background: var(--lagging); }
    .signal-improving { background: var(--improving); }
    .notes ul { margin: 0; padding-left: 20px; color: var(--muted); }
    .report-footer { margin-top: 18px; padding-top: 14px; border-top: 1px solid var(--line); color: var(--muted); font-size: 13px; text-align: center; }
    @media (max-width: 760px) {
      header { flex-direction: column; }
      .actions { justify-content: flex-start; }
      .summary { grid-template-columns: 1fr; }
    }
    """
