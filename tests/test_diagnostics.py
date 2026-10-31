"""Offline regression tests for diagnostic-only version 0.5."""
import csv
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from lab.detection import Parameters, research_hypothesis
from lab.diagnostics import explain_at, diagnose_session, diagnostic_summary, REASONS
from lab.models import Candle
from lab.replay import ReplaySession
from lab.sources import synthetic_scenario
from lab.validation import validate_history, export_validation, short_summary


class DiagnosticsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.candles, _ = synthetic_scenario('down', cycles=10)

    def test_complete_causal_reasoning(self):
        session=ReplaySession(self.candles)
        result=diagnose_session(session)
        self.assertEqual(result['sample_candles'],len(self.candles))
        self.assertEqual(len(result['candle_diagnostics']),len(self.candles))
        self.assertEqual(sum(result['actual_gate_counts'].values()),result['eligible_candles'])
        self.assertEqual(result['queued_signals'],len([f for f in session.frames if 'SIGNAL' in f.action]))
        self.assertGreater(result['eligible_candles'],0)
        self.assertIn('ATR',diagnostic_summary(result))

    def test_no_future_candles_affect_reason(self):
        shorter=ReplaySession(self.candles[:170])
        full=ReplaySession(self.candles)
        for i in (65,91,128,169):
            x=explain_at(shorter.candles,i,shorter.params,
                         atr_values=shorter._atr,rsi_values=shorter._rsi,
                         ema_fast_values=shorter._ema_fast,ema_slow_values=shorter._ema_slow)
            y=explain_at(full.candles,i,full.params,
                         atr_values=full._atr,rsi_values=full._rsi,
                         ema_fast_values=full._ema_fast,ema_slow_values=full._ema_slow)
            self.assertEqual(x,y)

    def test_ready_only_when_production_accepts(self):
        s=ReplaySession(self.candles)
        for i in range(s.warmup,len(self.candles)):
            x=explain_at(s.candles,i,s.params,
                         atr_values=s._atr,rsi_values=s._rsi,
                         ema_fast_values=s._ema_fast,ema_slow_values=s._ema_slow)
            accepted=research_hypothesis(s.candles,s.params,as_of=i,
                     atr_values=s._atr,rsi_values=s._rsi,
                     ema_fast_values=s._ema_fast,ema_slow_values=s._ema_slow)
            self.assertEqual(x['reason_code'] in ('READY_LONG','READY_SHORT'),accepted is not None)

    def test_session_mutation_absent(self):
        s=ReplaySession(self.candles)
        before=s.summary()
        diag=diagnose_session(s)
        after=s.summary()
        self.assertEqual(before['trades'],after['trades'])
        self.assertEqual(before['final_equity'],after['final_equity'])
        self.assertEqual(before['max_drawdown_pct'],after['max_drawdown_pct'])
        self.assertEqual(diag['trade_risk']['trades'],before['trade_count'])

    def test_risk_ratios_are_from_actual_fills(self):
        s=ReplaySession(self.candles)
        d=diagnose_session(s)
        self.assertGreater(len(d['trades']),0)
        for t in d['trades']:
            self.assertAlmostEqual(t['risk_usdt'],abs(t['entry']-t['stop'])*t['size'])
            self.assertAlmostEqual(t['total_fee_usdt'],t['entry_fee']+t['exit_fee'])
            self.assertGreater(t['stop_distance_atr'],0)
            self.assertGreater(t['fee_to_risk_pct'],0)
            self.assertEqual(t['net_r_multiple'],t['pnl']/t['risk_usdt'])
            self.assertIn(t['reason'],('TP','SL','SL (обе границы)'))
            self.assertTrue(t['closed']>=t['opened'])

    def test_flat_history_rejected_as_weak_impulse(self):
        candles=[Candle(i*3600000,100,101,99,100,10) for i in range(230)]
        s=ReplaySession(candles)
        info=explain_at(s.candles,160,s.params,
                        atr_values=s._atr,rsi_values=s._rsi,
                        ema_fast_values=s._ema_fast,ema_slow_values=s._ema_slow)
        self.assertEqual(info['reason_code'],'IMPULSE_WEAK')

    def test_rsi_filter_disabled_has_no_rsi_rejections(self):
        p=Parameters(use_rsi_filter=False)
        s=ReplaySession(self.candles,params=p)
        d=diagnose_session(s)
        self.assertEqual(d['rsi_rejections'],0)
        self.assertNotIn('RSI_BLOCK_LONG',d['market_filter_counts'])
        self.assertNotIn('RSI_BLOCK_SHORT',d['market_filter_counts'])

    def test_no_signal_when_last_bar_missing_next_open(self):
        s=ReplaySession(self.candles)
        d=diagnose_session(s)
        self.assertEqual(d['candle_diagnostics'][-1]['operation_code'],'LAST_BAR')
        self.assertNotIn('LAST_BAR',d['actual_gate_counts'])

    def test_chronological_export_contains_diagnostics(self):
        report=validate_history(self.candles,source='ARTIFICIAL TEST',tune=False)
        self.assertEqual(report['version'],'0.5')
        self.assertIn('\nФИЛЬТРЫ HOLDOUT: ', short_summary(report))
        for k in ('training','holdout','baseline_holdout'):
            part=report[k]
            self.assertEqual(len(part['diagnostics']['candle_diagnostics']),part['metrics']['candles'])
            self.assertEqual(part['metrics']['trade_count'],len(part['diagnostics']['trades']))
        with tempfile.TemporaryDirectory() as tmp:
            export_validation(report,tmp)
            folder=Path(tmp)
            for k in ('training','holdout','baseline_holdout'):
                with open(folder/(k+'_diagnostic_gates.csv'),encoding='utf-8-sig',newline='') as f:
                    rows=list(csv.DictReader(f))
                    self.assertEqual(len(rows),report[k]['metrics']['candles'])
                    self.assertIn('reason_code',rows[0])
                with open(folder/(k+'_trade_risk.csv'),encoding='utf-8-sig',newline='') as f:
                    self.assertIn('fee_to_risk_pct',csv.DictReader(f).fieldnames)
            self.assertEqual(json.loads((folder/'validation.json').read_text(encoding='utf8'))['version'],'0.5')

    def test_research_cli_prints_in_legacy_console_encoding(self):
        env=os.environ.copy()
        env['PYTHONIOENCODING']='cp1252'
        completed=subprocess.run(
            [sys.executable,'-m','lab.cli','--scenario','down','--backtest'],
            cwd=Path(__file__).resolve().parents[1],
            env=env,capture_output=True,check=False)
        self.assertEqual(completed.returncode,0,completed.stderr.decode('utf-8','replace'))
        self.assertIn('Виртуальный тест:',completed.stdout.decode('utf-8'))


if __name__=='__main__':
    unittest.main()
