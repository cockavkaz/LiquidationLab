"""Offline deterministic checks for causal replay and multi-page Bybit history."""
import io
import json
import unittest
from urllib.parse import urlparse,parse_qs
from unittest.mock import patch

from lab.detection import Parameters, find_setup, research_hypothesis
from lab.history import fetch_bybit_history
from lab.models import Candle
from lab.replay import ReplaySession
from lab.sources import synthetic_scenario
from lab.backtest import simulate


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self
    def __exit__(self, *_):
        self.close()


class ReplayTests(unittest.TestCase):
    def setUp(self):
        self.candles,_=synthetic_scenario('down')

    def test_replay_causality_with_future_removed(self):
        prefix=self.candles[:160]
        a=ReplaySession(prefix)
        b=ReplaySession(self.candles)
        for i in (80,95,130,159):
            x=a.seek(i)
            y=b.seek(i)
            self.assertEqual((x.price,x.phase,x.action,x.explanation,x.equity,x.setup),
                             (y.price,y.phase,y.action,y.explanation,y.equity,y.setup))

    def test_rewind_does_not_show_future_trades(self):
        s=ReplaySession(self.candles)
        final=s.finish()
        self.assertGreater(final.trade_count,0)
        s.seek(s.warmup)
        self.assertEqual(len(s.visible_trades()),s.frames[s.warmup].trade_count)
        self.assertLessEqual(len(s.visible_trades()),final.trade_count)
        self.assertEqual(s.next().index,s.warmup+1)
        self.assertEqual(s.previous().index,s.warmup)

    def test_replay_and_backtest_same_engine(self):
        r=ReplaySession(self.candles).summary()
        b=simulate(self.candles)
        self.assertEqual(b['trades'],r['trades'])
        self.assertEqual(b['max_drawdown_pct'],r['max_drawdown_pct'])
        self.assertGreaterEqual(b['max_drawdown_pct'],0)

    def test_fees_and_drawdown(self):
        fee=simulate(self.candles,fee_rate=.001,slippage=.0004)
        free=simulate(self.candles,fee_rate=0,slippage=0)
        self.assertLess(fee['final_equity'],free['final_equity'])
        self.assertGreater(fee['max_drawdown_pct'],0)

    def test_conservative_stop_when_both_boundaries_hit(self):
        p=Parameters(impulse_bars=2,range_bars=3,rsi_period=2,ema_slow=2,ema_fast=2)
        candles=[]
        for i in range(25):
            high,low=(103,97) if i==11 else (101,99)
            candles.append(Candle(i*60000,100,high,low,100,10))
        def signal(*args,**kwargs):
            if kwargs.get('as_of') == 10:
                return {'side':'long','stop':98,'target':102,'rsi':30}
            return None
        with patch('lab.replay.research_hypothesis',side_effect=signal):
            s=ReplaySession(candles,params=p,fee_rate=0,slippage=0)
            last=s.finish()
        self.assertEqual(s.trades[0]['reason'],'SL (обе границы)')
        self.assertAlmostEqual(s.trades[0]['exit'],98)
        self.assertLess(s.trades[0]['pnl'],0)

    def test_cached_indicators_equal_prefix(self):
        s=ReplaySession(self.candles)
        for i in range(60,len(self.candles),11):
            expected=find_setup(self.candles[:i+1])
            got=find_setup(self.candles,as_of=i,atr_values=s._atr)
            self.assertEqual(expected,got)
            idea_a=research_hypothesis(self.candles[:i+1])
            idea_b=research_hypothesis(self.candles,as_of=i,atr_values=s._atr,
                rsi_values=s._rsi,ema_fast_values=s._ema_fast,ema_slow_values=s._ema_slow)
            self.assertEqual(idea_a,idea_b)

    def test_history_two_pages_and_no_unclosed(self):
        now=1740000000000
        interval=60000
        # 1100 completed candles and one last unfinished live candle.
        first=now-1100*interval
        records=[]
        for i in range(1101):
            ts=first+i*interval
            records.append([str(ts),'100','101','99','100','123'])
        pages=[]
        def opener(request,timeout):
            query=parse_qs(urlparse(request.full_url).query)
            self.assertEqual(query['symbol'],['BTCUSDT'])
            end=int(query['end'][0])
            match=[r for r in records if int(r[0])<=end]
            result=match[::-1][:1000]
            pages.append(len(result))
            return FakeResponse(json.dumps({'retCode':0,'result':{'list':result}}).encode())
        candles=fetch_bybit_history(interval='1',days=2,now_ms=now,opener=opener)
        self.assertEqual(len(candles),1100)
        self.assertEqual(pages,[1000,101])
        self.assertEqual(candles[0].timestamp,first)
        self.assertEqual(candles[-1].timestamp,now-interval)
        self.assertEqual([c.timestamp for c in candles],sorted(set(c.timestamp for c in candles)))

    def test_history_invalid(self):
        with self.assertRaises(ValueError):fetch_bybit_history(interval='four')
        with self.assertRaises(ValueError):fetch_bybit_history(days=0)

if __name__=='__main__':
    unittest.main()
