"""All market values here are synthetic test fixtures, never observations."""
from __future__ import annotations

import copy
from contextlib import closing
import json
import math
import sqlite3
import unittest
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from sectors import cli
from sectors.candidates import (READY, REJECTED, WATCH, analyze_candidate, hypothetical_outcome,
                                indicators, position_size, review_packet, update_outcomes)
from sectors.cotpy import write_cotpy_charts

NOW = datetime(2026, 6, 18, 21, tzinfo=UTC)


def fixture_candidate():
    days = []
    day = NOW.date()
    while len(days) < 80:
        if day.weekday() < 5:
            days.append(day.isoformat())
        day -= timedelta(days=1)
    days.reverse()
    rows = []
    for i, day in enumerate(days):
        close = 96 + i * .05 + .3 * math.sin(i)
        rows.append(dict(date=day, open=round(close-.1, 4), high=round(96+i*.05+.9, 4),
                         low=round(close-.6, 4), close=round(close, 4), volume=200_000))
    # Explicit confirmed chart pivots in a synthetic daily series.
    rows[-10]["high"] = 104.2
    rows[-5]["low"] = 98.5
    rows[-1].update(open=99.8, close=100, high=100.6, low=99.4)
    return {"symbol": "TEST", "asset_type": "stock", "side": "long", "setup_date": NOW.date().isoformat(),
            "entry": "100", "stop": "98", "target": "104", "history": {
                "symbol": "TEST", "source": "synthetic-test-fixture", "verified": True,
                "retrieved_at": NOW.isoformat(), "price_basis": "raw", "currency": "USD", "interval": "1d", "bars": rows},
            "quote": {"symbol": "TEST", "source": "synthetic-test-fixture", "verified": True,
                      "as_of": NOW.isoformat(), "price": "100", "price_basis": "raw", "currency": "USD"},
            "events": {"symbol": "TEST", "source": "synthetic-test-fixture", "verified": True,
                       "checked_at": NOW.isoformat(), "status": "clear", "coverage_days": 7, "next_event": None}}


def outcome_bar(day, o=99, h=101, l=99, c=100):
    return dict(date=day, open=o, high=h, low=l, close=c, volume=200_000)


class CandidateTests(unittest.TestCase):
    def test_exact_math_boundaries(self):
        for entry, stop, target, shares in [(100, 97, 106, 20), (125, 122, 131, 16),
                                            ("33.33", "32.3301", "35.3298", 60),
                                            (2000, 1940, 2120, 1)]:
            size = position_size(entry, stop, target)
            self.assertEqual(size["shares"], shares)
            self.assertLessEqual(Decimal(size["capital"]), 2000)
            self.assertLessEqual(Decimal(size["planned_loss"]), 60)
            self.assertGreaterEqual(Decimal(size["reward_risk"]), 2)
        for values in [(100, "96.999999", 107), (100, 97, "105.99999"), (2001, 1990, 2023),
                       (0, 0, 0), (100, 100, 110), (100, 101, 110), (100, 99, 99),
                       ("NaN", 99, 102), (100, "Infinity", 102), (True, .99, 2)]:
            with self.subTest(values=values), self.assertRaises(ValueError):
                position_size(*values)

    def test_ready_watch_and_stable_identity(self):
        candidate = fixture_candidate()
        ready = analyze_candidate(candidate, NOW)
        self.assertEqual(ready["classification"], READY, ready)
        self.assertEqual(ready["position"]["shares"], 20)
        self.assertTrue({"ma20", "ma50", "rsi14", "atr14", "support", "resistance"} <= ready["technicals"].keys())
        candidate["quote"]["price"] = "99.90"
        candidate["entry"] = "100.0"
        watch = analyze_candidate(candidate, NOW)
        self.assertEqual(watch["classification"], WATCH)
        self.assertEqual(ready["setup_id"], watch["setup_id"])
        candidate["target"] = "104.1"
        self.assertNotEqual(ready["setup_id"], analyze_candidate(candidate, NOW)["setup_id"])

    def test_evidence_hard_gates(self):
        mutations = [
            lambda c: c.pop("quote"), lambda c: c["quote"].update(price=None),
            lambda c: c["quote"].update(as_of="2026-06-17T20:59:59+00:00"),
            lambda c: c["quote"].update(as_of="2026-06-18T16:00:00+00:00"),
            lambda c: c["history"].update(retrieved_at="2026-06-19T21:00:00+00:00"),
            lambda c: c["quote"].update(verified=False), lambda c: c["quote"].update(symbol="OTHER"),
            lambda c: c["quote"].update(currency="EUR"), lambda c: c["history"].update(price_basis="adjusted"),
            lambda c: c["history"].update(bars=c["history"]["bars"][:-5]),
            lambda c: c["history"].update(bars=[]), lambda c: c["history"]["bars"][-1].update(volume=None),
            lambda c: c["history"]["bars"][-1].update(high=1),
            lambda c: c["history"]["bars"][-1].update(close=float("inf")),
            lambda c: c["history"]["bars"][-1].update(date="2026-06-19"),
            lambda c: c["history"]["bars"][-1].update(date=c["history"]["bars"][-2]["date"]),
            lambda c: c["history"]["bars"].pop(-2),
            lambda c: c["history"]["bars"].pop(),
            lambda c: c["history"]["bars"].__setitem__(-1, None),
            lambda c: c["history"].update(currency="EUR"),
            lambda c: c["events"].update(status="clear", risks=["earnings"]),
            lambda c: c["events"].update(status="unknown"), lambda c: c["events"].update(coverage_days=6),
            lambda c: c["events"].update(next_event="2026-06-25"), lambda c: c.pop("events"),
            lambda c: c.update(asset_type="future"), lambda c: c.update(side="short"),
            lambda c: c.update(stop="99.0"), lambda c: c.update(target="105"),
            lambda c: [b.update(volume=100) for b in c["history"]["bars"]],
        ]
        for mutate in mutations:
            candidate = fixture_candidate()
            mutate(candidate)
            with self.subTest(mutation=mutate):
                self.assertEqual(analyze_candidate(candidate, NOW)["classification"], REJECTED)

    def test_rsi_atr_are_wilder_indicators(self):
        result = analyze_candidate(fixture_candidate(), NOW)
        self.assertGreater(result["technicals"]["rsi14"], 50)
        self.assertLessEqual(result["technicals"]["rsi14"], 70)
        self.assertGreater(result["technicals"]["atr14"], 1)
        self.assertLess(result["technicals"]["atr14"], 2)

    def test_indicators_known_constant_and_rising_series(self):
        rows = [dict(date=f"bar-{i}", close=i, high=i+1, low=i-1, volume=200_000) for i in range(2, 66)]
        metrics = indicators(rows, Decimal(100))
        self.assertEqual(metrics["ma20"], 55.5)
        self.assertEqual(metrics["ma50"], 40.5)
        self.assertEqual(metrics["rsi14"], 100)
        self.assertEqual(metrics["atr14"], 2)
        flat = [dict(date="constant", close=100, high=101, low=99, volume=200_000)] * 64
        self.assertEqual(indicators(flat, Decimal(100))["rsi14"], 50)

    def test_incomplete_session_rejected_and_volume_trigger_watches(self):
        candidate = fixture_candidate()
        intraday = NOW.replace(hour=18)
        candidate["quote"]["as_of"] = intraday.isoformat()
        candidate["history"]["retrieved_at"] = intraday.isoformat()
        candidate["events"]["checked_at"] = intraday.isoformat()
        result = analyze_candidate(candidate, intraday)
        self.assertEqual(result["classification"], REJECTED)
        self.assertIn("not yet complete", result["reasons"][0])
        candidate = fixture_candidate()
        candidate["history"]["bars"][-1]["volume"] = 100_000
        self.assertEqual(analyze_candidate(candidate, NOW)["classification"], WATCH)
        candidate = fixture_candidate()
        candidate["quote"]["price"] = "100.51"
        self.assertEqual(analyze_candidate(candidate, NOW)["classification"], WATCH)

    def test_replay_ledger_and_reports_are_separate(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            packet = {"candidates": [fixture_candidate()]}
            current = review_packet(root, packet, NOW)
            replay = review_packet(root, packet, NOW, replay=True)
            self.assertEqual(replay["evaluation_mode"], "historical replay")
            self.assertEqual(current["evaluation_mode"], "current review")
            self.assertTrue((root / "reports/candidates/replay/latest.json").exists())
            with closing(sqlite3.connect(root / "state/candidates-replay.sqlite3")) as db:
                self.assertEqual(db.execute("SELECT count(*) FROM setups").fetchone()[0], 1)
            with self.assertRaisesRegex(ValueError, "duplicate"):
                review_packet(root, {"candidates": [fixture_candidate(), fixture_candidate()]}, NOW)

    def test_review_idempotent_and_watch_never_becomes_a_fill(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            packet = {"candidates": [fixture_candidate()]}
            first = review_packet(root, packet, NOW)
            content = (root / "reports/candidates/latest.json").read_bytes()
            self.assertEqual(review_packet(root, packet, NOW), first)
            self.assertEqual((root / "reports/candidates/latest.json").read_bytes(), content)
            with closing(sqlite3.connect(root / "state/candidates.sqlite3")) as db:
                self.assertEqual(db.execute("SELECT count(*) FROM setups").fetchone()[0], 1)
            self.assertEqual(len(list((root / "state/snapshots/candidates").glob("*.json"))), 1)
            packet["candidates"][0]["quote"]["price"] = 90
            packet["candidates"][0]["setup_date"] = "2026-06-17"
            review_packet(root, packet, NOW)
            with closing(sqlite3.connect(root / "state/candidates.sqlite3")) as db:
                self.assertEqual(db.execute("SELECT count(*) FROM setups").fetchone()[0], 1)

    def test_hypothetical_outcomes_never_claim_ambiguous_fills(self):
        setup = analyze_candidate(fixture_candidate(), NOW)
        first = outcome_bar("2026-06-19")
        def evaluate(rows):
            return hypothetical_outcome(setup, NOW.isoformat(), rows)
        self.assertEqual(evaluate([])["status"], "AWAITING ENTRY")
        self.assertEqual(evaluate([outcome_bar("2026-06-18", h=110, l=90)])["status"], "AWAITING ENTRY")
        self.assertEqual(evaluate([first])["status"], "OPEN")
        self.assertEqual(evaluate([first, outcome_bar("2026-06-23", o=100, h=104)])["status"], "UNRESOLVED")
        for bar in [outcome_bar("2026-06-22", o=100, h=105, l=97),
                    outcome_bar("2026-06-22", o=97, h=100, l=96, c=98),
                    outcome_bar("2026-06-22", o=105, h=106, l=100),
                    outcome_bar("2026-06-29")]:
            result = evaluate([first, bar])
            self.assertEqual(result["status"], "UNRESOLVED")
            self.assertIsNone(result["r_multiple"])
            self.assertFalse(result["broker_fill"])
        self.assertEqual(evaluate([outcome_bar("2026-06-19", o=101)])["status"], "UNRESOLVED")
        self.assertEqual(evaluate([outcome_bar("2026-06-19", h=105)])["status"], "UNRESOLVED")
        self.assertEqual(evaluate([first, outcome_bar("2026-06-22", o=100, l=98)])["r_multiple"], "-1")
        self.assertEqual(evaluate([first, outcome_bar("2026-06-22", o=100, h=104)])["r_multiple"], "2")

    def test_outcome_uses_eastern_activation_date_and_explicit_holidays(self):
        setup = analyze_candidate(fixture_candidate(), NOW)
        winter_activation = "2026-11-06T00:45:00+00:00"  # Thursday 7:45 PM ET.
        result = hypothetical_outcome(setup, winter_activation, [outcome_bar("2026-11-06")])
        self.assertEqual(result["status"], "OPEN")
        monday_only = [outcome_bar("2026-06-22")]
        self.assertEqual(hypothetical_outcome(setup, NOW.isoformat(), monday_only)["status"], "UNRESOLVED")
        self.assertEqual(hypothetical_outcome(setup, NOW.isoformat(), monday_only, ["2026-06-19"])["status"], "OPEN")

    def test_outcome_update_merges_idempotently_and_rejects_corrections(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            review_packet(root, {"candidates": [fixture_candidate()]}, NOW)
            later = NOW + timedelta(days=4)
            history = copy.deepcopy(fixture_candidate()["history"])
            history.update(retrieved_at=later.isoformat(), bars=[outcome_bar("2026-06-19"), outcome_bar("2026-06-22", o=100, h=104)])
            packet = {"histories": {"TEST": history}}
            result = update_outcomes(root, packet, later)
            self.assertEqual(result, update_outcomes(root, packet, later))
            self.assertEqual(result["outcomes"][0]["status"], "TARGET")
            self.assertEqual(result["outcomes"][0]["symbol"], "TEST")
            self.assertEqual(result["outcomes"][0]["evidence_inputs"][0]["source"], "synthetic-test-fixture")
            history["bars"][0]["close"] = 100.5
            with self.assertRaisesRegex(ValueError, "correction"):
                update_outcomes(root, packet, later)
            with closing(sqlite3.connect(root / "state/candidates.sqlite3")) as db:
                self.assertEqual(db.execute("SELECT count(*) FROM bars").fetchone()[0], 2)
            report = json.loads((root / "reports/candidates/latest.json").read_text())
            self.assertEqual(report["outcomes"][0]["status"], "TARGET")

    def test_cli_is_local_and_rejects_bad_packet(self):
        with TemporaryDirectory() as tmp, patch.object(cli, "ROOT", Path(tmp)), patch.object(cli, "_publish_to_reports_repo") as publish:
            packet = Path(tmp) / "input.json"
            packet.write_text(json.dumps({"candidates": [fixture_candidate()]}))
            with patch("builtins.print"):
                self.assertEqual(cli.main(["candidates", "--input", str(packet), "--as-of", NOW.isoformat()]), 0)
                packet.write_text('{"candidates": []}')
                self.assertEqual(cli.main(["candidates", "--input", str(packet)]), 1)
            publish.assert_not_called()

    def test_empty_cot_fails_without_output_or_publish(self):
        with TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, "no cotpy charts"):
                write_cotpy_charts(Path(tmp), history={})
            self.assertFalse((Path(tmp) / "reports/cotpy/index.html").exists())

    def test_partial_cot_preserves_existing_reports(self):
        from sectors.cotpy import COTPY_UNIVERSE
        from sectors.model import PriceBar
        rows = [PriceBar(date=(date(2026, 1, 5) + timedelta(weeks=i)).isoformat(), close=100) for i in range(12)]
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            index = root / "reports/cotpy/index.html"
            index.parent.mkdir(parents=True)
            index.write_text("previous complete report")
            with self.assertRaisesRegex(ValueError, "insufficient history"):
                write_cotpy_charts(root, history={COTPY_UNIVERSE[0].ticker: rows})
            self.assertEqual(index.read_text(), "previous complete report")
            self.assertFalse((index.parent / "charts").exists())


if __name__ == "__main__":
    unittest.main()
