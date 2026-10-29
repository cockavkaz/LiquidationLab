"""Backtests and replay use one causal execution engine."""
from .detection import Parameters
from .replay import ReplaySession


def simulate(candles, params=Parameters(), initial_equity=10000., risk_fraction=.005,
             max_notional_mult=1., fee_rate=.0006, slippage=.0002):
    if not candles:
        return dict(initial_equity=initial_equity, final_equity=initial_equity,
                    return_pct=0., trade_count=0, win_rate_pct=0.,
                    max_drawdown_pct=0., profit_factor=0., trades=[],
                    open_position=None, notes='Нет свечей')
    return ReplaySession(candles, params, initial_equity, risk_fraction,
                         max_notional_mult, fee_rate, slippage).summary()
