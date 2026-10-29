"""Causal price indicators: values at t depend on candles up to t only."""
from typing import Optional, Sequence
from .models import Candle


def ema(values: Sequence[float], period: int) -> list[Optional[float]]:
    if period <= 0:
        raise ValueError('period must be positive')
    result: list[Optional[float]] = [None] * len(values)
    if len(values) < period:
        return result
    v = sum(values[:period]) / period
    result[period - 1] = v
    alpha = 2 / (period + 1)
    for i in range(period, len(values)):
        v += alpha * (values[i] - v)
        result[i] = v
    return result


def rsi(values: Sequence[float], period: int = 14) -> list[Optional[float]]:
    if period <= 0:
        raise ValueError('period must be positive')
    result: list[Optional[float]] = [None] * len(values)
    if len(values) <= period:
        return result
    gains, losses = [], []
    for a, b in zip(values[:period], values[1:period + 1]):
        gains.append(max(b - a, 0.0))
        losses.append(max(a - b, 0.0))
    gain = sum(gains) / period
    loss = sum(losses) / period
    for i in range(period, len(values)):
        if i > period:
            diff = values[i] - values[i - 1]
            gain = (gain * (period - 1) + max(diff, 0)) / period
            loss = (loss * (period - 1) + max(-diff, 0)) / period
        if gain == 0 and loss == 0:
            result[i] = 50.0
        elif loss == 0:
            result[i] = 100.0
        else:
            result[i] = 100 - 100 / (1 + gain / loss)
    return result


def atr(candles: Sequence[Candle], period: int = 14) -> list[Optional[float]]:
    if period <= 0:
        raise ValueError('period must be positive')
    result: list[Optional[float]] = [None] * len(candles)
    if len(candles) <= period:
        return result
    tr = [max(candles[i].high - candles[i].low,
              abs(candles[i].high - candles[i-1].close),
              abs(candles[i].low - candles[i-1].close))
          for i in range(1, len(candles))]
    v = sum(tr[:period]) / period
    result[period] = v
    for i in range(period + 1, len(candles)):
        v = (v * (period - 1) + tr[i-1]) / period
        result[i] = v
    return result


def confirmed_pivots(candles: Sequence[Candle], reversal_pct: float = .012) -> list[tuple[int, float, str]]:
    """ZigZag of CONFIRMED extrema only; final unconfirmed pivot is not included.

    This is exploratory price structure, not an objective Elliott-wave labeling.
    """
    if len(candles) < 3 or reversal_pct <= 0:
        return []
    pivots = []
    base = candles[0].close
    direction = 0
    peak = base
    trough = base
    peak_i = trough_i = 0
    for i in range(1, len(candles)):
        h, l = candles[i].high, candles[i].low
        if direction == 0:
            if h > peak:
                peak, peak_i = h, i
            if l < trough:
                trough, trough_i = l, i
            if peak / max(trough, 1e-12) - 1 >= reversal_pct:
                if peak_i > trough_i:
                    direction = 1
                    pivots.append((trough_i, trough, 'L'))
                else:
                    direction = -1
                    pivots.append((peak_i, peak, 'H'))
        elif direction == 1:
            if h > peak:
                peak, peak_i = h, i
            if l <= peak * (1 - reversal_pct):
                pivots.append((peak_i, peak, 'H'))
                direction = -1
                trough, trough_i = l, i
        else:
            if l < trough:
                trough, trough_i = l, i
            if h >= trough * (1 + reversal_pct):
                pivots.append((trough_i, trough, 'L'))
                direction = 1
                peak, peak_i = h, i
    return pivots
