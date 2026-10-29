import unittest
from lab.models import Candle
from lab.indicators import ema,rsi,atr
from lab.sources import synthetic_scenario
from lab.detection import find_setup,describe,research_hypothesis
from lab.backtest import simulate

class LabTests(unittest.TestCase):
    def setUp(self):
        self.candles,self.clusters=synthetic_scenario("sideways")

    def test_demo(self):
        self.assertGreater(len(self.candles),100)
        self.assertEqual(len(self.clusters),8)
        self.assertEqual({c.source for c in self.clusters},{"demo"})
    def test_valid_ohlc(self):
        for c in self.candles:c.validate()
    def test_ema_causal(self):
        values=[float(i) for i in range(100)]
        self.assertEqual(ema(values,20)[60],ema(values[:61],20)[-1])
    def test_rsi(self):
        self.assertAlmostEqual(rsi([10.]*20)[-1],50.)
    def test_atr(self):
        self.assertGreater(atr(self.candles)[-1],0)
    def test_disjoint_windows(self):
        for i in range(80,len(self.candles)):
            s=find_setup(self.candles[:i+1])
            if s:self.assertLess(s.impulse_end,s.range_start)
    def test_description(self):
        self.assertIsInstance(describe(self.candles),dict)
    def test_no_lookahead(self):
        for i in range(90,len(self.candles)-1):
            a=research_hypothesis(self.candles[:i+1])
            b=research_hypothesis(self.candles[:i+1])
            self.assertEqual(a,b)
    def test_paper_costs(self):
        r=simulate(self.candles)
        self.assertGreaterEqual(r["trade_count"],0)
        self.assertIsInstance(r["final_equity"],float)
    def test_invalid_risk(self):
        with self.assertRaises(ValueError):simulate(self.candles,risk_fraction=-1)
    def test_down(self):
        c,_=synthetic_scenario("down")
        self.assertEqual(len(c),len(self.candles))
    def test_up(self):
        c,_=synthetic_scenario("up")
        self.assertGreater(len(c),100)
if __name__=="__main__":unittest.main()
