from __future__ import annotations

import html
import json
import unittest
from datetime import date, timedelta
from unittest.mock import patch
from pathlib import Path
from tempfile import TemporaryDirectory
from sectors.backfill import backfill_weekly_snapshots
from sectors.config import write_json
from sectors.charts import write_sector_charts
from sectors.cli import main
from sectors.report import build_brief, build_brief_html
from tests.test_sectors import _fixture_history

from sectors.analytics import build_snapshot, calculate_asset_metrics
from sectors.config import DEFAULT_UNIVERSE, validate_universe
from sectors.context import context_html
from sectors.market_data import MarketDataProvider, fetch_optional_history
from sectors.model import Instrument, PriceBar
from sectors.tracker import build_rotation_series, build_tracker_html
from sectors.weights import NAMES, fetch_sector_weights, parse_sector_weights


def allocation_html(weights=None):
    # Synthetic allocation fixture, not live index data.
    values = weights or [10.0] * 10 + [0.0]
    data = {"asOfDateSimple": "Oct 01 2026", "attrArray": [{"name": {"value": name}, "weight": {"originalValue": str(value)}} for name, value in zip(NAMES.values(), values)]}
    return '<input id="index-sector-breakdown" value="' + html.escape(json.dumps(data), quote=True) + '">'


class MarketContextTests(unittest.TestCase):
    def test_official_index_payload_maps_technology_and_preserves_zero(self):
        result = parse_sector_weights(allocation_html())
        self.assertEqual(result['as_of'], '2026-10-01')
        self.assertEqual(result['weights']['XLK'], 0.1)
        self.assertEqual(result['weights']['XLU'], 0)
        self.assertEqual(result['basis'], 'S&P 500 index sector breakdown')

    def test_missing_nonfinite_or_incomplete_allocations_fail_closed(self):
        for document in ['<html></html>', allocation_html([float('nan')] * 11), allocation_html([1.0] * 11)]:
            with self.assertRaises(ValueError):
                parse_sector_weights(document)
        with patch('sectors.weights.urlopen', side_effect=OSError('offline')):
            self.assertEqual(fetch_sector_weights()['status'], 'unavailable')

    def test_malformed_source_response_does_not_abort_collection(self):
        for payload in [[], None, {'attrArray': None}, {'attrArray': [None], 'asOfDateSimple': 'Oct 01 2026'}]:
            document = '<input id="index-sector-breakdown" value="' + html.escape(json.dumps(payload), quote=True) + '">'
            with patch('sectors.weights.urlopen') as request:
                request.return_value.__enter__.return_value.read.return_value = document.encode()
                self.assertEqual(fetch_sector_weights()['status'], 'unavailable')
        payload = json.loads(html.unescape(allocation_html().split('value="', 1)[1].rsplit('"', 1)[0]))
        payload['attrArray'].append(payload['attrArray'][0])
        document = '<input id="index-sector-breakdown" value="' + html.escape(json.dumps(payload), quote=True) + '">'
        with self.assertRaises(ValueError):
            parse_sector_weights(document)

    def test_bitcoin_weekends_and_future_dates_do_not_distort_comparison(self):
        start = date(2026, 1, 1)
        btc = [PriceBar((start + timedelta(days=i)).isoformat(), 100 + i) for i in range(110)]
        spy = [bar for bar in btc[:100] if date.fromisoformat(bar.date).weekday() < 5]
        history = {'SPY': spy, 'BTC-USD': btc}
        rows = calculate_asset_metrics(Instrument('SPY', 'Benchmark'), [Instrument('BTC-USD', 'Bitcoin'), Instrument('CL=F', 'Oil')], history, spy[-1].date)
        self.assertEqual(rows[0]['as_of'], spy[-1].date)
        self.assertEqual(rows[0]['close'], spy[-1].close)
        self.assertEqual(rows[0]['relative_returns']['21d'], 0.0)
        self.assertEqual(rows[1]['status'], 'unavailable')

    def test_failed_optional_asset_does_not_abort_collection(self):
        class Provider(MarketDataProvider):
            def fetch_history(self, symbols, period='1y'):
                if symbols == ['CL=F']:
                    raise RuntimeError('unavailable')
                return {symbols[0]: [PriceBar('2026-10-01', 100)]}
        result = fetch_optional_history(Provider(), ['CL=F', 'BTC-USD'], '1y')
        self.assertEqual(result['CL=F'], [])
        self.assertEqual(len(result['BTC-USD']), 1)

    def test_assets_do_not_change_sector_rankings_and_render_in_tracker(self):
        sectors = [Instrument(**item) for item in DEFAULT_UNIVERSE['sectors']]
        benchmark = Instrument('SPY', 'Benchmark')
        assets = [Instrument(**item) for item in DEFAULT_UNIVERSE['assets']]
        days = [(date(2026, 1, 1) + timedelta(days=i)).isoformat() for i in range(70)]
        history = {item.symbol: [PriceBar(day, 100 + i * (j + 1)) for i, day in enumerate(days)] for j, item in enumerate([benchmark, *sectors, *assets])}
        original = build_snapshot(benchmark, sectors, history, 'fixture')
        augmented = build_snapshot(benchmark, sectors, history, 'fixture', assets=assets, sector_weights=parse_sector_weights(allocation_html()))
        self.assertEqual(original['metrics'], augmented['metrics'])
        self.assertEqual(len(augmented['metrics']), 11)
        rendered = context_html(augmented)
        self.assertIn('10-year Treasury', rendered)
        self.assertIn('Index weight', rendered)
        self.assertIn('10.00%', rendered)
        tracker = build_tracker_html(build_rotation_series([augmented]))
        self.assertIn('contextHtml', tracker)
        self.assertIn('marketContext', tracker)

    def test_backfill_preserves_references_without_current_weights(self):
        symbols = [item['symbol'] for key in ['references', 'sectors', 'assets'] for item in DEFAULT_UNIVERSE[key]]
        history = _fixture_history(symbols)
        history['CL=F'] = []
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_json(root / 'config' / 'universe.json', DEFAULT_UNIVERSE)
            with patch('sectors.backfill.get_market_data_provider') as get_provider:
                provider = get_provider.return_value
                provider.name = 'fixture'
                provider.fetch_history.side_effect = lambda symbols, period: {symbol: history[symbol] for symbol in symbols}
                paths = backfill_weekly_snapshots(root, weeks=2, refresh_tracker=False)
            for path in paths:
                snapshot = json.loads(path.read_text())
                self.assertTrue(snapshot['market']['RSP'])
                self.assertTrue(snapshot['market']['QQQ'])
                self.assertEqual(snapshot['sector_weights']['status'], 'unavailable')
                self.assertEqual(len(snapshot['asset_metrics']), 3)
                rendered = context_html(snapshot)
                self.assertNotIn('href="charts/CL=F.html"', rendered)
                self.assertIn('CL=F', rendered)

    def test_invalid_optional_configuration_reports_errors(self):
        for assets in [None, [{'symbol': [], 'name': 'Invalid'}], [{'symbol': 'SPY', 'name': 'Duplicate'}], [{'symbol': 'RSP', 'name': 'Duplicate reference'}]]:
            self.assertTrue(validate_universe({**DEFAULT_UNIVERSE, 'assets': assets}))

    def test_collection_and_reports_include_assets_and_dated_weights(self):
        symbols = [item['symbol'] for key in ['references', 'sectors', 'assets'] for item in DEFAULT_UNIVERSE[key]]
        history = _fixture_history(symbols)
        # An explicit extra Bitcoin day must not move the equity snapshot date.
        future_day = (date.fromisoformat(history['SPY'][-1].date) + timedelta(days=1)).isoformat()
        history['BTC-USD'].append(PriceBar(future_day, 123.0))
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_json(root / 'config' / 'universe.json', DEFAULT_UNIVERSE)
            with patch('sectors.cli.ROOT', root), patch('sectors.cli.get_market_data_provider') as get_provider, patch('sectors.cli.fetch_sector_weights', return_value=parse_sector_weights(allocation_html())):
                provider = get_provider.return_value
                provider.name = 'fixture'
                provider.fetch_history.side_effect = lambda symbols, period: {symbol: history[symbol] for symbol in symbols}
                self.assertEqual(main(['snapshot']), 0)
            snapshot = json.loads((root / 'state' / 'snapshots' / 'latest.json').read_text())
            self.assertEqual(snapshot['as_of'], history['SPY'][-1].date)
            self.assertLess(snapshot['market']['BTC-USD'][-1]['date'], future_day)
            self.assertEqual(len(snapshot['metrics']), 11)
            paths = write_sector_charts(root)
            self.assertEqual(len(paths), 15)  # index, eleven sectors, three markets
            for symbol in ['CL=F', 'ZN=F', 'BTC-USD']:
                self.assertTrue((root / 'reports' / 'charts' / f'{symbol}.html').exists())
                self.assertIn(symbol, build_brief(snapshot))
                self.assertIn(symbol, build_brief_html(snapshot))
            self.assertIn('10.00%', build_brief(snapshot))
            self.assertIn('2026-10-01', build_brief_html(snapshot))
            self.assertIn('BTC-USD Market Chart', (root / 'reports' / 'charts' / 'BTC-USD.html').read_text())

    def test_legacy_config_and_snapshots_remain_readable(self):
        config = {key: value for key, value in DEFAULT_UNIVERSE.items() if key != 'assets'}
        self.assertEqual(validate_universe(config), [])
        sectors = [Instrument(**item) for item in config['sectors']]
        benchmark = Instrument(**config['benchmark'])
        snapshot = build_snapshot(benchmark, sectors, _fixture_history([benchmark.symbol] + [item.symbol for item in sectors]), 'fixture')
        for key in ['assets', 'asset_metrics', 'sector_weights']:
            snapshot.pop(key)
        for render in [build_brief, build_brief_html, context_html]:
            self.assertIn('N/A', render(snapshot))
        self.assertEqual(build_rotation_series([snapshot])['sectorCount'], 11)

    def test_short_asset_history_does_not_break_charts_or_link_to_missing_page(self):
        sectors = [Instrument(**item) for item in DEFAULT_UNIVERSE['sectors']]
        benchmark = Instrument('SPY', 'Benchmark')
        history = _fixture_history([benchmark.symbol] + [item.symbol for item in sectors])
        history['CL=F'] = [history['SPY'][-1]]
        snapshot = build_snapshot(benchmark, sectors, history, 'fixture', assets=[Instrument('CL=F', 'Oil')])
        self.assertNotIn('href="charts/CL=F.html"', context_html(snapshot))
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_json(root / 'state' / 'snapshots' / 'latest.json', snapshot)
            self.assertEqual(len(write_sector_charts(root)), 12)

    def test_tracker_script_safely_embeds_context(self):
        snapshot = {'sectors': [{'symbol': 'XLK', 'name': '</script><script>alert(1)</script>'}], 'metrics': []}
        rendered = build_tracker_html(build_rotation_series([snapshot]))
        self.assertNotIn('</script><script>alert(1)', rendered)
        self.assertIn('\\u003c', rendered)


if __name__ == '__main__':
    unittest.main()
