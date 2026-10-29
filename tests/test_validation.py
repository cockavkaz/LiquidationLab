"""No network needed: validates split, audit trail, causality and exports."""
import csv
import json
import tempfile
import unittest
from urllib.error import HTTPError
from pathlib import Path

from lab.detection import Parameters
from lab.history import fetch_bybit_history
from lab.models import Candle
from lab.sources import synthetic_scenario
from lab.validation import (validate_history, export_validation,
                            short_summary, verify_ohlc, preset_parameters)


class ValidationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.candles,_=synthetic_scenario('down', cycles=12)

    def test_chronological_no_overlap(self):
        a=validate_history(self.candles,source='DEMO',tune=False)
        self.assertEqual(a['split']['train_count']+a['split']['holdout_count'],len(self.candles))
        self.assertLess(a['split']['train_last_utc'],a['split']['holdout_first_utc'])
        self.assertNotEqual(a['training']['metrics']['start_utc'], a['holdout']['metrics']['start_utc'])
        self.assertEqual(a['selected_preset'],'Базовая')
        self.assertEqual(a['source'],'DEMO')

    def test_selection_uses_training_only(self):
        a=validate_history(self.candles,source='DEMO')
        split=a['split']['train_count']
        altered=list(self.candles)
        for i in range(split,len(altered)):
            c=altered[i]
            # Large but OHLC-valid change in the unseen test segment only.
            altered[i]=Candle(c.timestamp,c.open*1.3,c.high*1.3,c.low*1.3,
                              c.close*1.3,c.volume)
        b=validate_history(altered,source='DEMO')
        self.assertEqual(a['candidate_training_scores'],b['candidate_training_scores'])
        self.assertEqual(a['selected_preset'],b['selected_preset'])
        self.assertEqual(a['training']['metrics'],b['training']['metrics'])

    def test_trade_metadata_and_next_candle(self):
        a=validate_history(self.candles,source='DEMO',tune=False)
        for partition in ('training','holdout'):
            result=a[partition]
            self.assertEqual(result['metrics']['candles'],len(result['equity_curve']))
            self.assertEqual(result['metrics']['candles'],len(result['decisions']))
            self.assertGreaterEqual(result['metrics']['max_drawdown_pct'],0)
            for t in result['trades']:
                self.assertGreaterEqual(t['opened'],1)
                self.assertEqual(t['opened'],t['signal_index']+1)
                self.assertIn('UTC',t['signal_at_utc'])
                self.assertGreaterEqual(t['closed'],t['opened'])
                self.assertIn('UTC',t['opened_at_utc'])
                self.assertIn(t['reason'],('TP','SL','SL (обе границы)'))

    def test_invalid_input_duplicate_and_nan(self):
        candles=self.candles[:]
        candles[8]=candles[7]
        with self.assertRaisesRegex(ValueError,'возрастающему'):
            verify_ohlc(candles)
        c=self.candles[8]
        candles[8]=Candle(c.timestamp,float('nan'),c.high,c.low,c.close,c.volume)
        with self.assertRaisesRegex(ValueError,'NaN'):
            verify_ohlc(candles)

    def test_short_history_rejected(self):
        with self.assertRaises(ValueError):
            validate_history(self.candles[:120],source='DEMO')

    def test_invalid_fraction_rejected(self):
        with self.assertRaises(ValueError):
            validate_history(self.candles,source='DEMO',train_fraction=.95)

    def test_audit_export(self):
        a=validate_history(self.candles,source='DEMO',tune=False)
        with tempfile.TemporaryDirectory() as d:
            export_validation(a,d)
            folder=Path(d)
            self.assertTrue((folder/'validation.json').is_file())
            saved=json.loads((folder/'validation.json').read_text('utf8'))
            self.assertEqual(saved['split'],a['split'])
            for part in ('training','holdout','baseline_holdout'):
                for ext in ('_trades.csv','_equity.csv','_decisions.csv'):
                    self.assertTrue((folder/(part+ext)).is_file())
            with open(folder/'holdout_equity.csv',encoding='utf-8-sig',newline='') as f:
                self.assertEqual(len(list(csv.DictReader(f))),a['split']['holdout_count'])

    def test_honest_data_and_warning(self):
        a=validate_history(self.candles,source='DEMO',tune=False)
        self.assertIn('OHLC',short_summary(a))
        self.assertTrue(any('CoinGlass' in t for t in a['warnings']))
        self.assertTrue(a['assumptions']['holdout_uses_own_warmup'])

    def test_bybit_403_is_explicit_and_does_not_fabricate_history(self):
        def blocked(request,timeout):
            raise HTTPError(request.full_url,403,'Forbidden',None,None)
        with self.assertRaisesRegex(ConnectionError,'HTTP 403'):
            fetch_bybit_history(days=1,opener=blocked,now_ms=1740000000000)

    def test_parameter_presets_unchanged_input(self):
        p=Parameters()
        variants=preset_parameters(p)
        self.assertEqual(len(variants),4)
        self.assertEqual(variants[0][1],p)
        self.assertEqual(p.max_range_pct,Parameters().max_range_pct)


if __name__=='__main__':
    unittest.main()
