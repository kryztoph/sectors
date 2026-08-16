from __future__ import annotations

import unittest
from datetime import date, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import cast

from sectors.analytics import build_snapshot
from sectors.backfill import _latest_complete_weekly_closes, _truncate_history
from sectors.charts import write_sector_charts
from sectors.cotpy import COTPY_UNIVERSE, write_cotpy_charts
from sectors.config import DEFAULT_UNIVERSE, load_references, load_universe, write_json
from sectors.cli import build_parser
from sectors.model import PriceBar
from sectors.report import build_brief, build_brief_html
from sectors.tracker import build_rotation_series, build_tracker_html, load_snapshots


class SectorMonitorTests(unittest.TestCase):
    def test_snapshot_ranks_all_11_sectors(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_json(root / "config" / "universe.json", DEFAULT_UNIVERSE)
            benchmark, sectors = load_universe(root)
            references = load_references(root)
            symbols = list(dict.fromkeys(reference.symbol for reference in references + sectors))
            history = _fixture_history(symbols)

            snapshot = build_snapshot(
                benchmark,
                sectors,
                history,
                provider="test-fixture",
                references=references,
            )

        metrics = cast(list[dict[str, object]], snapshot["metrics"])
        self.assertEqual(len(metrics), 11)
        self.assertEqual([row["rank"] for row in metrics], list(range(1, 12)))
        self.assertEqual(metrics[0]["signal"], "LEADING")
        spy_bar = snapshot["market"]["SPY"][-1]
        self.assertIn("open", spy_bar)
        self.assertIn("high", spy_bar)
        self.assertIn("low", spy_bar)
        moving_averages = cast(dict[str, object], metrics[0]["moving_averages"])
        self.assertEqual(set(moving_averages), {"10d", "50d", "150d"})
        references = cast(list[dict[str, object]], snapshot["references"])
        market = cast(dict[str, object], snapshot["market"])
        self.assertEqual([item["symbol"] for item in references], ["SPY", "RSP", "QQQ"])
        self.assertEqual(len(market), 14)

    def test_brief_contains_rankings_table(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_json(root / "config" / "universe.json", DEFAULT_UNIVERSE)
            benchmark, sectors = load_universe(root)
            symbols = [benchmark.symbol] + [sector.symbol for sector in sectors]
            history = _fixture_history(symbols)
            snapshot = build_snapshot(
                benchmark,
                sectors,
                history,
                provider="test-fixture",
            )

        brief = build_brief(snapshot)
        brief_html = build_brief_html(snapshot)

        self.assertIn("# Sector Rotation Brief", brief)
        self.assertIn("| Rank | Sector | Symbol |", brief)
        self.assertIn("Relative returns are sector ETF returns minus SPY", brief)
        self.assertIn("<table>", brief_html)
        self.assertIn("../../assets/logo.png", brief_html)
        self.assertIn("latest-brief.md", brief_html)

    def test_tracker_builds_frames_and_html(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_json(root / "config" / "universe.json", DEFAULT_UNIVERSE)
            benchmark, sectors = load_universe(root)
            symbols = [benchmark.symbol] + [sector.symbol for sector in sectors]
            history = _fixture_history(symbols)
            first = build_snapshot(
                benchmark,
                sectors,
                history,
                provider="test-fixture",
            )
            second = build_snapshot(
                benchmark,
                sectors,
                history,
                provider="test-fixture",
            )
            first["created_at"] = "20260617T213000Z"
            second["created_at"] = "20260618T213000Z"
            second["metrics"][0]["score"] = second["metrics"][0]["score"] + 5

        series = build_rotation_series([first, second])
        html = build_tracker_html(series)

        self.assertEqual(series["frameCount"], 2)
        self.assertEqual(series["sectorCount"], 11)
        self.assertIn("Sector Rotation Tracker", html)
        self.assertIn("Relative strength", html)
        self.assertIn("Show All", html)
        self.assertIn("row-toggle", html)
        self.assertIn("name-cell", html)
        self.assertIn("visibleSymbols", html)
        self.assertIn("frame.asOf", html)
        self.assertIn('href="${href}"', html)
        self.assertIn("charts/${encodeURIComponent(point.symbol)}.html", html)
        self.assertIn("latest-brief.html", html)
        self.assertIn("../../assets/logo.png", html)
        self.assertIn("Copyright &copy; 2026 csfox.com", html)

    def test_weekly_backfill_helpers_select_prior_complete_weeks(self) -> None:
        symbols = ["SPY", "XLK", "XLF"]
        history = _fixture_history(symbols)

        closes = _latest_complete_weekly_closes(history, 8)
        truncated = _truncate_history(history, closes[-1].isoformat())

        self.assertEqual(len(closes), 8)
        self.assertTrue(all(close.weekday() <= 4 for close in closes))
        self.assertLessEqual(truncated["SPY"][-1].date, closes[-1].isoformat())

    def test_tracker_loads_snapshots_by_as_of_date(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            snapshot_dir = root / "state" / "snapshots"
            old = {"created_at": "backfill-weekly-2026-05-01", "as_of": "2026-05-01", "metrics": []}
            new = {"created_at": "20260618T213000Z", "as_of": "2026-06-18", "metrics": []}
            write_json(snapshot_dir / "20260618T213000Z.json", new)
            write_json(snapshot_dir / "backfill-weekly-2026-05-01.json", old)

            snapshots = load_snapshots(snapshot_dir)

        self.assertEqual([item["as_of"] for item in snapshots], ["2026-05-01", "2026-06-18"])

    def test_sector_charts_write_index_and_sector_pages(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_json(root / "config" / "universe.json", DEFAULT_UNIVERSE)
            benchmark, sectors = load_universe(root)
            symbols = [benchmark.symbol] + [sector.symbol for sector in sectors]
            history = _fixture_history(symbols)
            snapshot = build_snapshot(
                benchmark,
                sectors,
                history,
                provider="test-fixture",
            )
            write_json(root / "state" / "snapshots" / "latest.json", snapshot)

            written = write_sector_charts(root)
            index = written[0].read_text(encoding="utf-8")
            sector_page = (root / "reports" / "charts" / "XLK.html").read_text(encoding="utf-8")

        self.assertEqual(len(written), 12)
        self.assertIn("Sector Charts", index)
        self.assertIn("charts/XLK.html", index)
        self.assertIn("../../assets/logo.png", index)
        self.assertIn("Copyright &copy; 2026 csfox.com", index)
        self.assertIn("candlestick chart with volume moving average", sector_page)
        self.assertIn("../../../assets/logo.png", sector_page)
        self.assertIn("Copyright &copy; 2026 csfox.com", sector_page)
        self.assertIn("sector_rotation_tracker.html", sector_page)
        self.assertNotIn("sector_charts.html", sector_page)
        self.assertIn("Relative strength vs SPY", sector_page)
        self.assertIn("10d MA", sector_page)
        self.assertIn("50d MA", sector_page)
        self.assertIn("150d MA", sector_page)
        self.assertNotIn("ma20", sector_page)
        self.assertIn("trendline", sector_page)
        self.assertIn('class="crosshair-line crosshair-x"', sector_page)
        self.assertIn('class="crosshair-line crosshair-y"', sector_page)
        self.assertIn('class="crosshair-tooltip"', sector_page)
        self.assertIn('hitbox.addEventListener("pointermove"', sector_page)
        self.assertIn('crosshair.removeAttribute("hidden")', sector_page)

    def test_cotpy_charts_write_index_and_interactive_pages(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            history = _cotpy_fixture_history()

            written = write_cotpy_charts(root, history=history, lookback=12)
            index = written[0].read_text(encoding="utf-8")
            silver_page = (root / "reports" / "cotpy" / "charts" / "SILVER_interactive.html").read_text(encoding="utf-8")

        self.assertEqual(len(written), len(COTPY_UNIVERSE) + 1)
        self.assertIn("COTPY Charts", index)
        self.assertIn("SILVER_interactive.html", index)
        self.assertIn("charts/SILVER_interactive.html", index)
        self.assertIn("Plotly.newPlot", silver_page)
        self.assertIn("Source ticker SI=F", silver_page)
        self.assertIn("Copyright &copy; 2026 csfox.com", silver_page)

    def test_tracker_publish_flags_default_to_publish(self) -> None:
        parser = build_parser()

        tracker_default = parser.parse_args(["tracker"])
        tracker_local = parser.parse_args(["tracker", "--no-publish"])
        backfill_default = parser.parse_args(["backfill-weekly"])
        backfill_local = parser.parse_args(["backfill-weekly", "--no-publish"])
        cotpy_default = parser.parse_args(["cotpy"])
        cotpy_local = parser.parse_args(["cotpy", "--no-publish"])

        self.assertTrue(tracker_default.publish)
        self.assertFalse(tracker_local.publish)
        self.assertTrue(backfill_default.publish)
        self.assertFalse(backfill_local.publish)
        self.assertTrue(cotpy_default.publish)
        self.assertFalse(cotpy_local.publish)


def _fixture_history(symbols: list[str]) -> dict[str, list[PriceBar]]:
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
    return {
        symbol: _fixture_bars(start, end, *profiles.get(symbol, (100.0, 0.001)), symbol=symbol)
        for symbol in symbols
    }


def _cotpy_fixture_history() -> dict[str, list[PriceBar]]:
    end = date(2026, 6, 17)
    start = end - timedelta(days=260)
    profiles = {
        "GC=F": (1850.0, 0.0015),
        "SI=F": (22.0, 0.0022),
        "HG=F": (3.8, 0.0018),
        "CL=F": (72.0, 0.0011),
        "NG=F": (2.8, -0.0004),
        "PL=F": (950.0, 0.0010),
        "ZC=F": (5.2, 0.0006),
        "ZW=F": (6.4, 0.0005),
        "ZS=F": (13.0, 0.0007),
        "KC=F": (162.0, 0.0009),
        "SB=F": (18.0, 0.0004),
        "CT=F": (82.0, 0.0003),
    }
    return {
        item.ticker: _fixture_bars(start, end, *profiles[item.ticker], symbol=item.ticker)
        for item in COTPY_UNIVERSE
    }


def _fixture_bars(start: date, end: date, base: float, drift: float, symbol: str) -> list[PriceBar]:
    bars: list[PriceBar] = []
    current = start
    index = 0
    symbol_noise = (sum(ord(char) for char in symbol) % 9) / 1000
    while current <= end:
        if current.weekday() < 5:
            cycle = ((index % 13) - 6) / 1000
            close = base * (1 + drift * index + symbol_noise + cycle)
            open_price = close * (1 - 0.002 + (index % 5) / 5000)
            high = max(open_price, close) * (1 + 0.003)
            low = min(open_price, close) * (1 - 0.003)
            bars.append(
                PriceBar(
                    date=current.isoformat(),
                    close=round(close, 2),
                    open=round(open_price, 2),
                    high=round(high, 2),
                    low=round(low, 2),
                    volume=20_000_000 + index * 100_000,
                )
            )
            index += 1
        current += timedelta(days=1)
    return bars


if __name__ == "__main__":
    unittest.main()
