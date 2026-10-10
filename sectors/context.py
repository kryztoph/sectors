"""Shared market context rendered in briefs and tracker frames."""
from __future__ import annotations
import html
from typing import Any


def pct(value: Any) -> str:
    return "N/A" if value is None else f"{float(value) * 100:.2f}%"


def context_html(snapshot: dict[str, Any]) -> str:
    allocation = snapshot.get("sector_weights") or {}
    weights = allocation.get("weights") or {}
    date = html.escape(str(allocation.get("as_of", "unavailable")))
    source = allocation.get("source", "")
    attribution = f'<a href="{html.escape(source, quote=True)}">State Street index breakdown</a>' if source else "Allocations unavailable"
    names = {item["symbol"]: item["name"] for item in snapshot.get("sectors", [])}
    rows = "".join(f'<tr><td>{html.escape(name)}</td><td class="num">{pct(weights.get(symbol))}</td></tr>' for symbol, name in names.items())
    asset_rows = []
    for item in snapshot.get("asset_metrics", []):
        symbol = html.escape(str(item["symbol"]))
        name = html.escape(str(item["name"]))
        returns = item.get("returns") or {}
        relative = item.get("relative_returns") or {}
        close = "N/A" if item.get("close") is None else f'{float(item["close"]):,.2f}'
        has_chart = len((snapshot.get("market") or {}).get(item["symbol"], [])) >= 2
        symbol_html = f'<a href="charts/{symbol}.html">{symbol}</a>' if has_chart else symbol
        asset_rows.append(f'<tr><td>{symbol_html}</td><td>{name}</td><td>{html.escape(str(item.get("as_of", "unavailable")))}</td><td class="num">{close}</td><td class="num">{pct(returns.get("21d"))}</td><td class="num">{pct(relative.get("21d"))}</td></tr>')
    return f"""<section class="panel market-context" style="margin-top:16px;padding:16px;background:#fff;border:1px solid #d8dee7;border-radius:10px;overflow-x:auto">
<h2>S&amp;P 500 sector weights</h2><p>Allocation as of {date} · {attribution}. Missing allocations display N/A.</p>
<table><thead><tr><th>Sector</th><th class="num">Index weight</th></tr></thead><tbody>{rows}</tbody></table>
<h2>Oil, 10-year notes and Bitcoin</h2><table><thead><tr><th>Symbol</th><th>Asset</th><th>As of</th><th>Close</th><th>21 sessions</th><th>21 sessions vs SPY</th></tr></thead><tbody>{''.join(asset_rows)}</tbody></table>
<p>Assets are separate from the eleven sector ranks. Returns use common asset/SPY dates; Bitcoin weekends are excluded. CL=F and ZN=F are continuous futures prices; rolls affect returns. ZN=F is a note price, not a yield. Close units: oil USD/barrel, notes points per 100 face value, Bitcoin USD.</p></section>"""
