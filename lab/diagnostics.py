"""Causal, non-trading diagnostics for Liquidation Lab 0.5.

Purpose: explain REJECTED virtual hypotheses and the economic risk of historic
paper fills. All gates inspect the completed prefix up to 'index' only.
The trading algorithm in detection.py remains unchanged.
"""
from collections import Counter
from datetime import datetime, timezone
import math
from statistics import median

from .detection import Parameters, find_setup, research_hypothesis

REASONS = {
    'WARMUP': 'Недостаточно закрытых свечей для импульса и боковика.',
    'ATR_UNAVAILABLE': 'ATR на момент предшествующего импульса недоступен.',
    'IMPULSE_WEAK': 'Предшествующий импульс не превышает требуемое число ATR.',
    'IMPULSE_BODY': 'Направленное движение недостаточно велико относительно экстремумов импульса.',
    'RANGE_PERCENT': 'Боковик слишком широкий относительно своей средней цены.',
    'RANGE_IMPULSE': 'Боковик слишком широкий относительно предыдущего импульса.',
    'SETUP_MISMATCH': 'Параметры модели не сформировали структуру; требуется диагностика.',
    'VOLATILITY_UNAVAILABLE': 'ATR на свече наблюдения отсутствует.',
    'RSI_UNAVAILABLE': 'RSI на свече наблюдения отсутствует.',
    'OUTSIDE_RANGE': 'Закрытие вышло за исторические границы боковика.',
    'MIDDLE_RANGE': 'Цена находится далеко от обеих исследуемых границ.',
    'RSI_BLOCK_LONG': 'У нижней границы RSI превышает установленный порог.',
    'RSI_BLOCK_SHORT': 'У верхней границы RSI ниже установленного порога.',
    'READY_LONG': 'У нижней границы выполнены условия виртуального гипотетического сигнала.',
    'READY_SHORT': 'У верхней границы выполнены условия виртуального гипотетического сигнала.',
    'POSITION_OPEN': 'Виртуальная позиция уже открыта: новый вход не рассматривается.',
    'ENTRY_OR_EXIT': 'На этой свече был вход или выход; новый сигнал не допускается.',
    'LAST_BAR': 'Для исполнения на следующей свече пока нет данных.',
    'OTHER_GUARD': 'Дополнительная проверка стратегии не позволила сформировать гипотезу.',
}


def utc_label(timestamp):
    return datetime.fromtimestamp(timestamp / 1000, timezone.utc).strftime('%Y-%m-%d %H:%M UTC')


def explain_at(candles, index, params=None, *, atr_values=None,
               rsi_values=None, ema_fast_values=None, ema_slow_values=None):
    """Explain one potential decision, without positions or future candles."""
    p = params if params is not None else Parameters()
    if index < 0 or index >= len(candles):
        raise IndexError(index)

    details = {
        'index': index, 'timestamp': candles[index].timestamp,
        'utc': utc_label(candles[index].timestamp),
        'price': candles[index].close,
        'reason_code': '', 'reason': '',
        'reference_bottom': None, 'reference_top': None,
        'atr': (atr_values[index] if atr_values is not None else None),
        'rsi': (rsi_values[index] if rsi_values is not None else None),
        'relative_in_range': None, 'impulse_atr_multiple': None,
        'range_width_pct': None,
        'actionable_hypothesis': False,
    }

    def reject(code):
        details['reason_code'] = code
        details['reason'] = REASONS[code]
        return details

    # Mirrors the historical reference ending one candle BEFORE the observed close.
    if index < p.impulse_bars + p.range_bars + p.rsi_period + 3:
        return reject('WARMUP')
    r_end = index - 1
    r_start = r_end - p.range_bars + 1
    impulse_end = r_start - 1
    impulse_start = impulse_end - p.impulse_bars + 1
    if p.impulse_bars < 2 or p.range_bars < 3 or impulse_start < p.rsi_period + 2:
        return reject('WARMUP')
    impulse = candles[impulse_start:impulse_end + 1]
    cand_range = candles[r_start:r_end + 1]
    move = impulse[-1].close - impulse[0].open
    if atr_values is None:
        from .indicators import atr
        reference_atr = atr(candles[:impulse_end + 1], p.rsi_period)[-1]
    else:
        reference_atr = atr_values[impulse_end]
    if reference_atr is None or reference_atr <= 0 or not math.isfinite(reference_atr):
        return reject('ATR_UNAVAILABLE')
    details['impulse_atr_multiple'] = abs(move) / reference_atr
    if abs(move) < p.impulse_atr_multiple * reference_atr:
        return reject('IMPULSE_WEAK')
    excursion = max(c.high for c in impulse) - min(c.low for c in impulse)
    if excursion <= 0 or abs(move) / excursion < p.min_impulse_body_ratio:
        return reject('IMPULSE_BODY')
    top = max(c.high for c in cand_range)
    bottom = min(c.low for c in cand_range)
    mid = (top + bottom) / 2
    width = top - bottom
    details['reference_bottom'] = bottom
    details['reference_top'] = top
    if mid <= 0:
        return reject('RANGE_PERCENT')
    details['range_width_pct'] = 100 * width / mid
    if width / mid > p.max_range_pct:
        return reject('RANGE_PERCENT')
    if width > abs(move) * p.max_range_to_impulse:
        return reject('RANGE_IMPULSE')

    # Use actual production detector for the final reference, fail closed on drift.
    reference = find_setup(candles, p, as_of=r_end, atr_values=atr_values)
    if reference is None:
        return reject('SETUP_MISMATCH')
    if atr_values is None or rsi_values is None:
        from .indicators import atr, rsi
        a = atr(candles[:index+1],p.rsi_period)[-1]
        rr = rsi([c.close for c in candles[:index+1]],p.rsi_period)[-1]
    else:
        a = atr_values[index]
        rr = rsi_values[index]
    details['atr'] = a
    details['rsi'] = rr
    if a is None or a <= 0:
        return reject('VOLATILITY_UNAVAILABLE')
    if rr is None:
        return reject('RSI_UNAVAILABLE')
    price = candles[index].close
    if price < bottom or price > top:
        return reject('OUTSIDE_RANGE')
    fraction = (price-bottom)/width if width>0 else .5
    details['relative_in_range'] = fraction
    if fraction <= p.edge_zone:
        if p.use_rsi_filter and rr > 47:
            return reject('RSI_BLOCK_LONG')
        code = 'READY_LONG'
    elif fraction >= 1-p.edge_zone:
        if p.use_rsi_filter and rr < 53:
            return reject('RSI_BLOCK_SHORT')
        code = 'READY_SHORT'
    else:
        return reject('MIDDLE_RANGE')

    # One shared source of truth for whether a hypothesis actually passes.
    production = research_hypothesis(
        candles, p, as_of=index, atr_values=atr_values, rsi_values=rsi_values,
        ema_fast_values=ema_fast_values, ema_slow_values=ema_slow_values)
    if production is None:
        return reject('OTHER_GUARD')
    details['actionable_hypothesis'] = True
    return reject(code)


def diagnose_trade(trade, session, previous_trade=None):
    """Risk and costs measured at the actual virtual fill, never hypothetical."""
    result = dict(trade)
    entry = float(trade['entry'])
    stop = float(trade['stop'])
    size = float(trade['size'])
    risk = abs(entry-stop)*size
    fees = float(trade['entry_fee']) + float(trade['exit_fee'])
    sig = trade.get('signal_index')
    a = (session._atr[sig] if isinstance(sig, int) and
         0 <= sig < len(session._atr) else None)
    result.update(
        price_stop_distance=abs(entry-stop),
        price_stop_distance_pct=100*abs(entry-stop)/entry if entry else None,
        risk_usdt=risk,
        total_fee_usdt=fees,
        fee_to_risk_pct=100*fees/risk if risk else None,
        stop_distance_atr=(abs(entry-stop)/a if a and a > 0 else None),
        net_r_multiple=(float(trade['pnl'])/risk if risk else None),
        duration_bars=trade['closed']-trade['opened'],
        same_bar_exit=(trade['closed']==trade['opened']),
        reentry_after_loss_24bars=bool(
            previous_trade and previous_trade['pnl']<0 and
            0 <= trade['opened']-previous_trade['closed'] <=24),
        same_direction_reentry_after_loss_24bars=bool(
            previous_trade and previous_trade['pnl']<0 and
            previous_trade['side']==trade['side'] and
            0 <= trade['opened']-previous_trade['closed'] <=24),
    )
    return result


def diagnose_session(session):
    """Full offline diagnostic. Does not mutate strategy parameters or fills."""
    session.finish()
    observed = []
    decision_codes = Counter()
    operational_codes = Counter()
    rsi_rejections = 0
    completed = 0
    candidates = 0
    for frame in session.frames:
        info = explain_at(
            session.candles, frame.index, session.params,
            atr_values=session._atr, rsi_values=session._rsi,
            ema_fast_values=session._ema_fast, ema_slow_values=session._ema_slow)
        market_code = info['reason_code']
        # Position gating reflects the actual replay machine. An otherwise
        # valid hypothetical decision is not executable while already in a trade.
        if frame.index == len(session.candles)-1:
            gate = 'LAST_BAR'
        elif 'SIGNAL' in frame.action:
            gate = market_code
        elif 'ENTRY' in frame.action or 'EXIT' in frame.action:
            gate = 'ENTRY_OR_EXIT'
        elif frame.position:
            gate = 'POSITION_OPEN'
        else:
            gate = market_code
        info.update(operation_code=gate, operation_reason=REASONS.get(gate,''),
                    replay_action=frame.action, phase=frame.phase)
        observed.append(info)
        if frame.index >= session.warmup and frame.index+1 < len(session.candles):
            decision_codes[market_code] += 1
            operational_codes[gate] += 1
            if info['reference_bottom'] is not None:
                completed += 1
            if info['actionable_hypothesis']:
                candidates += 1
            if market_code in ('RSI_BLOCK_LONG','RSI_BLOCK_SHORT'):
                rsi_rejections += 1
    trades = []
    for t in session.trades:
        trades.append(diagnose_trade(t,session,trades[-1] if trades else None))
    stops = [t for t in trades if t['reason'].startswith('SL')]
    distances = [t['stop_distance_atr'] for t in trades if t['stop_distance_atr'] is not None]
    fee_ratios = [t['fee_to_risk_pct'] for t in trades if t['fee_to_risk_pct'] is not None]
    result = {
        'sample_candles': len(session.candles),
        'eligible_candles': sum(operational_codes.values()),
        'market_filter_counts': dict(decision_codes),
        'actual_gate_counts': dict(operational_codes),
        'range_reached_filter_stage': completed,
        'raw_possible_hypotheses': candidates,
        'queued_signals': sum('SIGNAL' in f.action for f in session.frames),
        'rsi_rejections': rsi_rejections,
        'trades': trades,
        'trade_risk': {
            'trades': len(trades), 'stops': len(stops),
            'same_bar_exits': sum(t['same_bar_exit'] for t in trades),
            'reentries_after_loss_24bars': sum(t['reentry_after_loss_24bars'] for t in trades),
            'same_direction_reentries_after_loss_24bars':
                sum(t['same_direction_reentry_after_loss_24bars'] for t in trades),
            'median_stop_distance_atr': median(distances) if distances else None,
            'median_fee_to_risk_pct': median(fee_ratios) if fee_ratios else None,
            'fee_total_usdt': sum(t['total_fee_usdt'] for t in trades),
            'net_pnl_usdt': sum(t['pnl'] for t in trades),
        },
        'candle_diagnostics': observed,
        'limits': [
            'Диагноз описывает правила существующей стратегии; её параметры не менялись.',
            'ATR, RSI и диапазон рассчитываются только из завершённых свечей.',
            'Комиссии включают обе стороны, ATR определяется на свече сигнала.',
            'Экономика сделки зависит от предполагаемой модели исполнения.',
            'OHLC не определяет порядок внутрисвечных событий: SL имеет приоритет.',
            'Текущая карта CoinGlass не используется как историческая информация.',
        ],
    }
    return result


def diagnostic_summary(out, max_items=5):
    counts=sorted(out['actual_gate_counts'].items(),key=lambda kv:(-kv[1],kv[0]))
    reasons='; '.join(f"{k}={v}" for k,v in counts[:max_items])
    stats=out['trade_risk']
    f=lambda x:'—' if x is None else f'{x:.2f}'
    return (
        f"Свечей: {out['sample_candles']}, доступно после прогрева: {out['eligible_candles']}\n"
        f"Структуры после фильтра импульса: {out['range_reached_filter_stage']}\n"
        f"Сигналов: {out['queued_signals']}; закрытых виртуальных сделок: {stats['trades']}\n"
        f"Отклонения RSI: {out['rsi_rejections']}\n"
        f"Топ причин: {reasons}\n"
        f"Стопы (ATR): медиана {f(stats['median_stop_distance_atr'])}; "
        f"комиссии/риск: {f(stats['median_fee_to_risk_pct'])}%\n"
        f"Входы и выходы на одной свече: {stats['same_bar_exits']}; "
        f"входы после убытка ≤24 свечей: {stats['reentries_after_loss_24bars']}\n"
        f"Комиссии за период: {stats['fee_total_usdt']:.2f} USDT. "
        "Данные для исследования, не сигналы к реальным сделкам."
    )
