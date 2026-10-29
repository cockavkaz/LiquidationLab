"""Causal candle-by-candle replay and paper fills. No exchange order methods.

Each candle is handled in this exact order:
1. Execute a signal decided at the PREVIOUS candle close at current open.
2. Evaluate stops/targets on the current candle; conservative stop-first policy.
3. Mark open position to market at current candle close (for drawdown).
4. Analyze ONLY candles through this close, optionally queue next-open action.

Stored frames never reveal later candles. A rewind changes only the visible cursor.
"""
from dataclasses import dataclass
from typing import Optional, Tuple

from .detection import Parameters, find_setup, research_hypothesis
from .indicators import atr, rsi, ema


@dataclass(frozen=True)
class ReplayFrame:
    index: int
    timestamp: int
    price: float
    phase: str
    explanation: str
    action: str
    equity: float
    max_drawdown_pct: float
    trade_count: int
    position: Optional[dict]
    setup: object
    pending: Optional[dict]
    markers: Tuple[dict, ...]


class ReplaySession:
    def __init__(self, candles, params=None, initial_equity=10000.0,
                 risk_fraction=0.005, max_notional_mult=1.0,
                 fee_rate=0.0006, slippage=0.0002):
        if not candles:
            raise ValueError('Нужны свечи для воспроизведения')
        if initial_equity <= 0 or not (0 < risk_fraction <= .1) or max_notional_mult <= 0:
            raise ValueError('Некорректные параметры риска')
        if fee_rate < 0 or not (0 <= slippage < .05):
            raise ValueError('Некорректные комиссии/проскальзывание')
        self.candles = tuple(candles)
        # Full arrays are safe to precompute: ATR/RSI/EMA are strictly causal
        # and any frame reads only its own or earlier indexed values.
        closes = [c.close for c in self.candles]
        p = params if params is not None else Parameters()
        self._atr = atr(self.candles, p.rsi_period)
        self._rsi = rsi(closes, p.rsi_period)
        self._ema_fast = ema(closes, p.ema_fast)
        self._ema_slow = ema(closes, p.ema_slow)
        self.params = params if params is not None else Parameters()
        self.initial_equity = float(initial_equity)
        self.cash = float(initial_equity)
        self.risk_fraction = risk_fraction
        self.max_notional_mult = max_notional_mult
        self.fee_rate = fee_rate
        self.slippage = slippage
        self.position = None
        self.pending = None
        self.peak_equity = float(initial_equity)
        self.max_drawdown = 0.0
        self.trades = []
        self.markers = []
        self.frames = []
        self.cursor = -1
        self.warmup = max(self.params.ema_slow + 2,
                          self.params.rsi_period + self.params.range_bars + self.params.impulse_bars + 3)

    def _close(self, candle, index, exit_raw, reason):
        p = self.position
        direction = p['sign']
        exit_price = exit_raw * (1 - direction * self.slippage)
        exit_fee = p['size'] * exit_price * self.fee_rate
        gross = (exit_price - p['entry']) * p['size'] * direction
        # Entry fee was already deducted from cash; do not deduct it twice.
        self.cash += gross - exit_fee
        pnl = gross - exit_fee - p['entry_fee']
        trade = {'side': p['side'], 'entry': p['entry'], 'exit': exit_price,
                 'stop': p['stop'], 'target': p['target'], 'pnl': pnl,
                 'opened': p['opened'], 'closed': index, 'reason': reason,
                 'size': p['size'], 'entry_fee': p['entry_fee'], 'exit_fee': exit_fee,
                 'signal_index': p.get('signal_decided_at')}
        self.trades.append(trade)
        self.markers.append({'index': index, 'type': 'exit', 'price': exit_price,
                             'side': p['side'], 'reason': reason})
        self.position = None
        return f"Закрытие {p['side']}: {reason}, P&L {pnl:+.2f}, с учётом комиссий."

    def _process_one(self, index):
        c = self.candles[index]
        actions = []
        explanations = []
        active_this_candle = False
        pending = self.pending
        self.pending = None
        if pending is not None and self.position is None:
            sign = 1 if pending['side'] == 'long' else -1
            entry = c.open * (1 + sign * self.slippage)
            stop, target = pending['stop'], pending['target']
            valid = (stop < entry < target if sign == 1 else target < entry < stop)
            if valid:
                size = min(self.cash * self.risk_fraction / abs(entry - stop),
                           self.cash * self.max_notional_mult / entry)
                if size > 0:
                    fee = size * entry * self.fee_rate
                    self.cash -= fee
                    self.position = {'side': pending['side'], 'sign': sign, 'entry': entry,
                                     'stop': stop, 'target': target, 'size': size,
                                     'opened': index, 'entry_fee': fee,
                                     'signal_decided_at': pending['decided_at']}
                    self.markers.append({'index': index, 'type': 'entry',
                                         'price': entry, 'side': pending['side']})
                    actions.append('ENTRY')
                    explanations.append(f"Виртуальный {pending['side']} по открытию новой свечи {entry:.2f}; SL {stop:.2f}, TP {target:.2f}.")
                    active_this_candle = True
            else:
                actions.append('CANCEL')
                explanations.append('Запланированный вход отменён: открытие новой свечи вне SL/TP.')

        if self.position is not None:
            p = self.position
            is_long = p['sign'] == 1
            stop_hit = c.low <= p['stop'] if is_long else c.high >= p['stop']
            target_hit = c.high >= p['target'] if is_long else c.low <= p['target']
            if stop_hit or target_hit:
                # If a candle crossed both boundaries, choose stop first.
                # Negative gap goes through stop at open, not the old stop price.
                if stop_hit:
                    raw = min(c.open, p['stop']) if is_long else max(c.open, p['stop'])
                    reason = 'SL (обе границы)' if target_hit else 'SL'
                else:
                    raw = p['target']
                    reason = 'TP'
                explanations.append(self._close(c, index, raw, reason))
                actions.append('EXIT')
                active_this_candle = True

        mtm = self.cash
        if self.position:
            p = self.position
            mtm += (c.close - p['entry']) * p['size'] * p['sign']
        self.peak_equity = max(self.peak_equity, mtm)
        if self.peak_equity > 0:
            self.max_drawdown = max(self.max_drawdown, (self.peak_equity - mtm)/self.peak_equity)

        setup = find_setup(self.candles, self.params, as_of=index, atr_values=self._atr)
        phase = 'Поиск структуры'
        if setup:
            phase = 'Консолидация'
            explanations.append(f"Импульс {setup.impulse_direction}, затем боковик {setup.bottom:.2f}–{setup.top:.2f}; окна не пересекаются.")
        elif index < self.warmup:
            phase = 'Накопление истории'

        if self.position:
            phase = 'Виртуальная позиция открыта'
            explanations.append('Отслеживаем SL/TP без новых входов.')
        elif not active_this_candle and index >= self.warmup and index + 1 < len(self.candles):
            # A signal is based ONLY on candles[:index+1]. It is filled at NEXT open.
            idea = research_hypothesis(
                self.candles, self.params, as_of=index, atr_values=self._atr,
                rsi_values=self._rsi, ema_fast_values=self._ema_fast,
                ema_slow_values=self._ema_slow)
            if idea:
                self.pending = {'side': idea['side'], 'stop': idea['stop'],
                                'target': idea['target'], 'decided_at': index}
                actions.append('SIGNAL')
                phase = 'Виртуальный сигнал'
                explanations.append(f"RSI {idea['rsi']:.1f}; решение на закрытии свечи, вход не раньше следующего открытия.")
            elif setup:
                explanations.append('У границы диапазона нет подтверждения фильтрами; остаёмся без позиции.')
        if not explanations:
            explanations.append('Данных для сигнала пока нет: исследуем движение цены.')
        frame = ReplayFrame(index=index, timestamp=c.timestamp, price=c.close,
                            phase=phase, explanation=' '.join(explanations),
                            action='+'.join(actions) if actions else 'OBSERVE',
                            equity=mtm, max_drawdown_pct=100*self.max_drawdown,
                            trade_count=len(self.trades),
                            position=dict(self.position) if self.position else None,
                            setup=setup, pending=dict(self.pending) if self.pending else None,
                            markers=tuple(m for m in self.markers if m['index'] >= max(0,index-100)))
        self.frames.append(frame)

    def seek(self, index):
        if not 0 <= index < len(self.candles):
            raise IndexError(index)
        while len(self.frames) <= index:
            self._process_one(len(self.frames))
        self.cursor = index
        return self.frames[index]

    def next(self):
        return self.seek(min(self.cursor + 1, len(self.candles) - 1))

    def previous(self):
        return self.seek(max(0, self.cursor - 1))

    def finish(self):
        frame = self.seek(len(self.candles) - 1)
        # Mark-to-market final equity is correct even if a position stays open.
        return frame

    def visible_trades(self):
        if self.cursor < 0:
            return []
        return self.trades[:self.frames[self.cursor].trade_count]

    def summary(self):
        frame = self.finish()
        pnl = [t['pnl'] for t in self.trades]
        wins = sum(x > 0 for x in pnl)
        gross_profit = sum(x for x in pnl if x > 0)
        gross_loss = -sum(x for x in pnl if x < 0)
        return {'initial_equity': self.initial_equity,
                'final_equity': frame.equity,
                'return_pct': 100*(frame.equity/self.initial_equity-1),
                'trade_count': len(self.trades),
                'win_rate_pct': (100*wins/len(pnl) if pnl else 0),
                'max_drawdown_pct': frame.max_drawdown_pct,
                'profit_factor': (gross_profit/gross_loss if gross_loss else (None if gross_profit else 0)),
                'open_position': frame.position,
                'trades': list(self.trades),
                'notes': 'Виртуальный тест: по закрытым свечам, без реальных ордеров. Открытые позиции отмечены по последней цене.'}
