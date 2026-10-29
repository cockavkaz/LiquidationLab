"""Detect a strong impulse that ENDS BEFORE a subsequent long consolidation."""
from dataclasses import dataclass
from typing import Optional, Sequence
from .models import Candle, Setup
from .indicators import atr, ema, rsi


@dataclass(frozen=True)
class Parameters:
    impulse_bars: int = 10
    range_bars: int = 24
    impulse_atr_multiple: float = 2.4
    max_range_pct: float = 0.035
    max_range_to_impulse: float = 0.80
    min_impulse_body_ratio: float = .45
    ema_fast: int = 20
    ema_slow: int = 50
    rsi_period: int = 14
    use_rsi_filter: bool = True
    edge_zone: float = .25


def find_setup(candles: Sequence[Candle], p: Parameters = Parameters(),
               as_of: Optional[int] = None, atr_values=None) -> Optional[Setup]:
    """A setup at index `as_of` uses ONLY closed candles at/before that index.

    The range occupies [as_of-range_bars+1, as_of] inclusive.
    The impulse occupies an immediately preceding, disjoint window.
    No overlap and no use of future prices/volatility.
    """
    end = len(candles) - 1 if as_of is None else as_of
    if end >= len(candles) or end < 0:
        return None
    rstart = end - p.range_bars + 1
    iend = rstart - 1
    istart = iend - p.impulse_bars + 1
    if p.impulse_bars < 2 or p.range_bars < 3 or istart < p.rsi_period + 2:
        return None
    segment = candles[istart:iend + 1]
    width_candles = candles[rstart:end + 1]
    move = segment[-1].close - segment[0].open
    reference_atr = (atr_values[iend] if atr_values is not None
                     else atr(candles[:iend + 1], p.rsi_period)[-1])
    if reference_atr is None or reference_atr <= 0:
        return None
    if abs(move) < p.impulse_atr_multiple * reference_atr:
        return None
    # Require directional body to exceed a share of the total high-low excursion.
    excursion = max(c.high for c in segment) - min(c.low for c in segment)
    if excursion <= 0 or abs(move) / excursion < p.min_impulse_body_ratio:
        return None
    top = max(c.high for c in width_candles)
    bottom = min(c.low for c in width_candles)
    midpoint = (top + bottom) / 2
    if midpoint <= 0:
        return None
    width = top - bottom
    if width / midpoint > p.max_range_pct:
        return None
    if width > abs(move) * p.max_range_to_impulse:
        return None
    return Setup('up' if move > 0 else 'down', abs(move), bottom, top,
                 midpoint, width / midpoint, istart, iend, rstart, end)


def describe(candles: Sequence[Candle], p: Parameters = Parameters()) -> dict:
    if not candles:
        return {'setup': None, 'rsi': None, 'ema_fast': None, 'ema_slow': None,
                'atr': None, 'price': None}
    closes = [c.close for c in candles]
    return {'setup': find_setup(candles, p), 'rsi': rsi(closes, p.rsi_period)[-1],
            'ema_fast': ema(closes, p.ema_fast)[-1],
            'ema_slow': ema(closes, p.ema_slow)[-1],
            'atr': atr(candles, p.rsi_period)[-1], 'price': closes[-1]}


def research_hypothesis(candles: Sequence[Candle], p: Parameters = Parameters(),
                        as_of: Optional[int] = None, atr_values=None,
                        rsi_values=None, ema_fast_values=None,
                        ema_slow_values=None) -> Optional[dict]:
    """Research-only hypothesis, decided at a completed candle's CLOSE.

    Caller may pass precalculated CAUSAL indicators, never future prices.
    The reference consolidation ends before the observed boundary touch.
    A hypothetical entry can only occur on the NEXT candle open.
    """
    end = len(candles)-1 if as_of is None else as_of
    if end < p.impulse_bars+p.range_bars+p.rsi_period+3 or end >= len(candles):
        return None
    reference = find_setup(candles, p, as_of=end-1, atr_values=atr_values)
    if reference is None:
        return None
    c = candles[end]
    price = c.close
    a = (atr_values[end] if atr_values is not None
         else atr(candles[:end+1], p.rsi_period)[-1])
    rr = (rsi_values[end] if rsi_values is not None
          else rsi([x.close for x in candles[:end+1]], p.rsi_period)[-1])
    if a is None or a <= 0 or rr is None:
        return None
    span = reference.top-reference.bottom
    if span <= 0 or not reference.bottom <= price <= reference.top:
        return None
    relative = (price-reference.bottom)/span
    if relative <= p.edge_zone:
        if p.use_rsi_filter and rr > 47:
            return None
        side='long'
        stop=reference.bottom-a*.25
        target=reference.top-.10*span
    elif relative >= 1-p.edge_zone:
        if p.use_rsi_filter and rr < 53:
            return None
        side='short'
        stop=reference.top+a*.25
        target=reference.bottom+.10*span
    else:
        return None
    fast = (ema_fast_values[end] if ema_fast_values is not None
            else ema([x.close for x in candles[:end+1]],p.ema_fast)[-1])
    slow = (ema_slow_values[end] if ema_slow_values is not None
            else ema([x.close for x in candles[:end+1]],p.ema_slow)[-1])
    return {'side':side,'stop':stop,'target':target,'setup':reference,
            'rsi':rr,'ema_fast':fast,'ema_slow':slow,
            'observation_time':c.timestamp}
