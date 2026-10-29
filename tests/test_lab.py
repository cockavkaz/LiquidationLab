import io
import json
import tempfile
import unittest
from pathlib import Path

from lab.models import Candle
from lab.indicators import ema, rsi, atr, confirmed_pivots
from lab.detection import Parameters, find_setup, research_hypothesis
from lab.sources import (synthetic_scenario, save_candles_csv, load_candles_csv,
                         load_clusters_csv, aggregate_historical_events, fetch_bybit_candles, fetch_coinglass_snapshot)
from lab.backtest import simulate


class LabTests(unittest.TestCase):
    def setUp(self):
        self.data, self.clusters = synthetic_scenario('up')

    def test_reproducible_demo(self):
        again, clusters = synthetic_scenario('up')
        self.assertEqual(self.data, again)
        self.assertEqual(self.clusters, clusters)
        self.assertTrue(all(c.source == 'demo' for c in self.clusters))
        for c in self.data:
            c.validate()

    def test_ema_and_rsi(self):
        self.assertEqual(ema([1, 2, 3, 4], 2)[:2], [None, 1.5])
        self.assertEqual(rsi([100]*17, 14)[-1], 50)
        self.assertEqual(rsi(list(range(30)), 14)[-1], 100)
        self.assertIsNone(atr(self.data[:5], 14)[-1])
        self.assertGreater(atr(self.data, 14)[-1], 0)

    def test_time_prefix_invariance(self):
        # Future prices cannot alter indicators computed at historic indices.
        prices = [c.close for c in self.data]
        for n in (50, 110, 200):
            self.assertEqual(ema(prices[:n], 20)[-1], ema(prices, 20)[n-1])
            self.assertEqual(rsi(prices[:n], 14)[-1], rsi(prices, 14)[n-1])
            self.assertEqual(atr(self.data[:n], 14)[-1], atr(self.data, 14)[n-1])
            self.assertEqual(find_setup(self.data[:n]), find_setup(self.data, as_of=n-1))

    def test_impulse_before_range_and_spans(self):
        setups = [find_setup(self.data[:n]) for n in range(85, len(self.data))]
        actual = [s for s in setups if s is not None]
        self.assertGreater(len(actual), 0)
        for s in actual:
            self.assertLess(s.impulse_end, s.range_start)
            self.assertEqual(s.range_end - s.range_start + 1, Parameters().range_bars)
            self.assertLess(s.width_pct, Parameters().max_range_pct + 1e-12)

    def test_false_impulse_inside_range_not_accepted(self):
        prefix = self.data[:80]
        base = prefix[-1].close
        noisy = []
        for i in range(34):
            op = base + (0 if i % 2 == 0 else 3)
            close = base + (3 if i % 2 == 0 else 0)
            noisy.append(Candle(prefix[-1].timestamp + (i+1)*900_000,
                                op, max(op, close)+.1, min(op,close)-.1, close))
        self.assertIsNone(find_setup(prefix+noisy))

    def test_hypotheses_use_prior_range_only(self):
        ideas = []
        for n in range(90, len(self.data)):
            idea = research_hypothesis(self.data[:n])
            if idea:
                ideas.append(idea)
                self.assertEqual(idea['observation_time'], self.data[n - 1].timestamp)
                self.assertLessEqual(idea['setup'].range_end, n - 2)
        self.assertTrue(ideas)

    def test_backtest_deterministic_and_costly(self):
        out = simulate(self.data)
        again = simulate(self.data)
        self.assertEqual(out['trades'], again['trades'])
        self.assertGreater(out['trade_count'], 0)
        zero_costs = simulate(self.data, fee_rate=0, slippage=0)
        self.assertLessEqual(out['final_equity'], zero_costs['final_equity'])
        self.assertTrue(all(t["opened"] > 0 for t in out['trades']))
        self.assertTrue(all(t["opened"] <= t["closed"] for t in out['trades']))

    def test_csv(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'candles.csv'
            save_candles_csv(path, self.data[:50])
            self.assertEqual(load_candles_csv(path), self.data[:50])
            levels = Path(d) / 'levels.csv'
            levels.write_text('price,intensity\n100,12\n105,55\n', encoding='utf8')
            self.assertEqual([c.source for c in load_clusters_csv(levels)], ['imported','imported'])
            levels.write_text('price,intensity\n-1,20\n', encoding='utf8')
            with self.assertRaises(ValueError):
                load_clusters_csv(levels)

    def test_historical_liquidations_stable_binning(self):
        events = [{'price': 99, 'quantity': 5}, {'price': 99.10, 'quantity': 4},
                  {'price': 100, 'quantity': 2}]
        out = aggregate_historical_events(events, reference_price=100, bucket_pct=.005)
        self.assertAlmostEqual(sum(c.intensity for c in out), 11)
        self.assertTrue(all(c.source == 'executed-history' for c in out))

    def test_bybit_mock_excludes_unfinished_and_sorts(self):
        data = {'retCode': 0, 'result': {'list': [
            ['1740000900000','101','102','100','101','25'],
            ['1740000000000','100','101','99','100','20']]}}
        class Fake(io.BytesIO):
            def __enter__(self): return self
            def __exit__(self, *args): self.close()
        def opener(request, timeout):
            self.assertIn('api.bybit.com/v5/market/kline', request.full_url)
            return Fake(json.dumps(data).encode())
        out = fetch_bybit_candles(opener=opener, now_ms=1_740_001_000_000)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0].close, 100)

    def test_coinglass_mock_map_and_plan_requirements(self):
        class Fake(io.BytesIO):
            def __enter__(self): return self
            def __exit__(self, *args): self.close()
        def opener(request, timeout):
            self.assertIn('open-api-v4.coinglass.com', request.full_url)
            self.assertEqual(request.headers.get('Cg-api-key'), 'secret')
            return Fake(json.dumps({'code':'0','data':{'data':{
                '101.0':[[101,100,10,None],[101,50,25,None]],
                '102.0':[[102,20,50,None]]}}}).encode())
        out = fetch_coinglass_snapshot('secret', opener=opener)
        self.assertEqual([(c.price,c.intensity) for c in out], [(101.,150.),(102.,20.)])
        self.assertTrue(all(c.source == 'coinglass-snapshot' for c in out))
        with self.assertRaises(ValueError):
            fetch_coinglass_snapshot('')

    def test_invalid_ohlc(self):
        with self.assertRaises(ValueError):
            Candle(0, 10, 9, 8, 10).validate()
        self.assertIsInstance(confirmed_pivots(self.data), list)


if __name__ == '__main__':
    unittest.main()
