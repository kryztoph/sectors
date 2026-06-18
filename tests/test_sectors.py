from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from sectors.analytics import build_snapshot
from sectors.backfill import _latest_complete_weekly_closes, _truncate_history
from sectors.config import DEFAULT_UNIVERSE, load_universe, write_json
from sectors.market_data import SampleMarketDataProvider
from sectors.report import build_brief
from sectors.tracker import build_rotation_series, build_tracker_html, load_snapshots


class SectorMonitorTests(unittest.TestCase):
    def test_sample_snapshot_ranks_all_11_sectors(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_json(root / "config" / "universe.json", DEFAULT_UNIVERSE)
            benchmark, sectors = load_universe(root)
            symbols = [benchmark.symbol] + [sector.symbol for sector in sectors]
            provider = SampleMarketDataProvider()

            snapshot = build_snapshot(
                benchmark,
                sectors,
                provider.fetch_history(symbols),
                provider=provider.name,
            )

        metrics = snapshot["metrics"]
        self.assertEqual(len(metrics), 11)
        self.assertEqual([row["rank"] for row in metrics], list(range(1, 12)))
        self.assertEqual(metrics[0]["signal"], "LEADING")

    def test_brief_contains_rankings_table(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_json(root / "config" / "universe.json", DEFAULT_UNIVERSE)
            benchmark, sectors = load_universe(root)
            symbols = [benchmark.symbol] + [sector.symbol for sector in sectors]
            provider = SampleMarketDataProvider()
            snapshot = build_snapshot(
                benchmark,
                sectors,
                provider.fetch_history(symbols),
                provider=provider.name,
            )

        brief = build_brief(snapshot)

        self.assertIn("# Sector Rotation Brief", brief)
        self.assertIn("| Rank | Sector | Symbol |", brief)
        self.assertIn("Relative returns are sector ETF returns minus SPY", brief)

    def test_tracker_builds_frames_and_html(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_json(root / "config" / "universe.json", DEFAULT_UNIVERSE)
            benchmark, sectors = load_universe(root)
            symbols = [benchmark.symbol] + [sector.symbol for sector in sectors]
            provider = SampleMarketDataProvider()
            first = build_snapshot(
                benchmark,
                sectors,
                provider.fetch_history(symbols),
                provider=provider.name,
            )
            second = build_snapshot(
                benchmark,
                sectors,
                provider.fetch_history(symbols),
                provider=provider.name,
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

    def test_weekly_backfill_helpers_select_prior_complete_weeks(self) -> None:
        provider = SampleMarketDataProvider()
        symbols = ["SPY", "XLK", "XLF"]
        history = provider.fetch_history(symbols)

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


if __name__ == "__main__":
    unittest.main()
