"""Chronological train/holdout validation using the SAME paper replay engine.

No accounts, orders, funding assumptions, or future liquidation information.
Selection uses training candles ONLY. Holdout starts with fresh capital and
indicators; warm-up candles inside the holdout do not create positions.
"""
from dataclasses import asdict, replace
from datetime import datetime, timezone
from pathlib import Path
import csv
import json
import math

from .detection import Parameters
from .replay import ReplaySession


def utc_label(milliseconds):
    return datetime.fromtimestamp(milliseconds / 1000, timezone.utc).strftime('%Y-%m-%d %H:%M UTC')


def verify_ohlc(candles, interval_minutes=None):
    """Fail closed on invalid/unsorted input. Gaps are diagnosed, not fabricated."""
    if not isinstance(candles, (list, tuple)) or not candles:
        raise ValueError('Нет исторических свечей')
    prev = None
    gap_count = 0
    for c in candles:
        if not isinstance(c.timestamp, int):
            raise ValueError('Timestamp должен быть UTC миллисекундами')
        values = (c.open, c.high, c.low, c.close, c.volume)
        if not all(math.isfinite(v) for v in values):
            raise ValueError('OHLC содержит NaN/Infinity')
        c.validate()
        if prev is not None:
            if c.timestamp <= prev:
                raise ValueError('Свечи должны идти по возрастающему времени без дубликатов')
            if interval_minutes and c.timestamp - prev > 1.5 * interval_minutes * 60000:
                gap_count += 1
        prev = c.timestamp
    return {'candles': len(candles), 'gaps': gap_count,
            'first_utc': utc_label(candles[0].timestamp),
            'last_utc': utc_label(candles[-1].timestamp)}


def _run_sample(candles, params, *, initial_equity, risk_fraction, fee_rate, slippage):
    session = ReplaySession(candles, params=params,
                            initial_equity=initial_equity,
                            risk_fraction=risk_fraction,
                            fee_rate=fee_rate, slippage=slippage)
    raw = session.summary()
    trades = []
    for t in raw['trades']:
        trade = dict(t)
        if t.get('signal_index') is not None:
            trade['signal_at_utc'] = utc_label(candles[t['signal_index']].timestamp)
        trade['opened_at_utc'] = utc_label(candles[t['opened']].timestamp)
        trade['closed_at_utc'] = utc_label(candles[t['closed']].timestamp)
        trades.append(trade)
    curve = [{'timestamp': frame.timestamp, 'utc': utc_label(frame.timestamp),
              'equity': round(frame.equity, 6),
              'max_drawdown_pct': round(frame.max_drawdown_pct, 6),
              'active': bool(frame.position)}
             for frame in session.frames]
    decisions = [
        {'bar_index': f.index, 'timestamp': f.timestamp,
         'utc': utc_label(f.timestamp), 'price': f.price,
         'action': f.action, 'phase': f.phase,
         'rsi': session._rsi[f.index],
         'ema_fast': session._ema_fast[f.index],
         'ema_slow': session._ema_slow[f.index],
         'atr': session._atr[f.index],
         'range_bottom': f.setup.bottom if f.setup else None,
         'range_top': f.setup.top if f.setup else None,
         'equity': f.equity, 'explanation': f.explanation}
        for f in session.frames]
    pnl = [t['pnl'] for t in trades]
    loss_runs, run = 0, 0
    for value in pnl:
        run = run + 1 if value < 0 else 0
        loss_runs = max(loss_runs, run)
    exposure = sum(1 for f in session.frames if f.position)
    initial = float(initial_equity)
    return {
        'metrics': {'candles': len(candles),
                    'start_utc': utc_label(candles[0].timestamp),
                    'end_utc': utc_label(candles[-1].timestamp),
                    'equity_start': initial,
                    'equity_end': raw['final_equity'],
                    'return_pct': raw['return_pct'],
                    'trade_count': raw['trade_count'],
                    'win_rate_pct': raw['win_rate_pct'],
                    'max_drawdown_pct': raw['max_drawdown_pct'],
                    'profit_factor': raw['profit_factor'],
                    'avg_net_pnl': (sum(pnl)/len(pnl) if pnl else 0.0),
                    'total_entry_fees': sum(t['entry_fee'] for t in trades),
                    'total_exit_fees': sum(t['exit_fee'] for t in trades),
                    'max_consecutive_losses': loss_runs,
                    'exposure_pct': exposure/len(session.frames)*100,
                    'has_open_position_at_end': bool(raw['open_position'])},
        'trades': trades, 'equity_curve': curve, 'decisions': decisions,
    }


def preset_parameters(base):
    """Small, predeclared grid; selected WITHOUT looking at holdout prices."""
    options = [
        ('Базовая', base),
        ('Узкий боковик', replace(base, max_range_pct=base.max_range_pct*.75)),
        ('Строгая граница', replace(base, edge_zone=max(.08, base.edge_zone*.70))),
        ('Без RSI-фильтра', replace(base, use_rsi_filter=False)),
    ]
    return options


def _train_score(metrics, min_trades=3):
    """Training-only utility. Insufficient trades get rejected for selection."""
    if metrics['trade_count'] < min_trades:
        return -1e12
    return (metrics['return_pct'] - 1.5*metrics['max_drawdown_pct']
            - .2*metrics['max_consecutive_losses'])


def validate_history(candles, *, source, interval_minutes=None, train_fraction=.70,
                     params=None, tune=True, risk_fraction=.005, fee_rate=.0006,
                     slippage=.0002, initial_equity=10000., min_segment=90):
    """Returns a portable report. No data from holdout is used for training.

    The two partitions DO NOT overlap; the first warm-up candles in the holdout
    are never used for a position. That deliberately sacrifices observations
    to avoid cross-boundary capital/indicator leakage.
    """
    quality = verify_ohlc(candles, interval_minutes)
    if not .5 <= train_fraction <= .85:
        raise ValueError('train_fraction должен быть в диапазоне 0.50–0.85')
    n = len(candles)
    split = int(n * train_fraction)
    if split < min_segment or n-split < min_segment:
        raise ValueError('Для независимого теста нужна более длинная история')
    base = params if params is not None else Parameters()
    train_data = candles[:split]
    test_data = candles[split:]
    kwargs = dict(initial_equity=initial_equity,
                  risk_fraction=risk_fraction,
                  fee_rate=fee_rate, slippage=slippage)
    presets = preset_parameters(base) if tune else [('Базовая', base)]
    candidates = []
    stored = {}
    for name, candidate in presets:
        result = _run_sample(train_data, candidate, **kwargs)
        score = _train_score(result['metrics'])
        stored[name] = result
        candidates.append({'name': name, 'parameters': asdict(candidate),
                           'train_score': score,
                           'training_metrics': result['metrics']})
    # If every candidate produced <3 trades, keep the baseline; never
    # choose a fake "winner" on the holdout.
    qualified = [c for c in candidates if c['train_score'] > -1e11]
    selected = max(qualified, key=lambda c: c['train_score']) if qualified else candidates[0]
    name = selected['name']
    selected_parameters = dict(presets)[name]
    held = _run_sample(test_data, selected_parameters, **kwargs)
    base_holdout = (held if name == 'Базовая'
                    else _run_sample(test_data, base, **kwargs))
    notes = [
        'Используются исключительно OHLC свечи: не исторические карты CoinGlass.',
        'Параметры выбираются только по TRAIN; контрольная выборка не участвует в выборе.',
        'TRAIN и HOLDOUT не перекрываются; капитал и индикаторы сбрасываются на границе.',
        'Начало HOLDOUT тратится на прогрев индикаторов (без переноса сделки из TRAIN).',
        'Маркировка капитала выполняется по закрытию каждой свечи, не по внутрисвечному минимуму.',
        'На OHLC нельзя восстановить точный порядок SL/TP: при конфликте выбирается SL.',
        'Открытая позиция в конце периода оценивается по последнему close; это НЕ исполненная сделка.',
        'Результаты не учитывают funding, рыночный импакт, точные ставки maker/taker и реальные задержки.',
        'Низкое число сделок не позволяет делать выводы о статистической значимости.',
    ]
    return {
        'version': '0.4',
        'source': str(source),
        'quality': quality,
        'split': {'train_count': split, 'holdout_count': n-split,
                  'train_last_utc': utc_label(train_data[-1].timestamp),
                  'holdout_first_utc': utc_label(test_data[0].timestamp),
                  'train_fraction': train_fraction},
        'assumptions': {'initial_equity_per_partition': initial_equity,
                        'risk_fraction': risk_fraction, 'fee_rate_per_side': fee_rate,
                        'slippage_per_side': slippage, 'min_selection_trades': 3,
                        'holdout_uses_own_warmup': True},
        'selected_preset': name,
        'selected_parameters': asdict(selected_parameters),
        'selection_explanation': ('Параметры выбранны по TRAIN'
                                  if qualified else
                                  'В TRAIN недостаточно сделок для выбора; сохранена базовая настройка'),
        'candidate_training_scores': candidates,
        'training': stored[name],
        'holdout': held,
        'baseline_holdout': base_holdout,
        'warnings': notes,
    }


def _write_csv(path, fields, rows):
    with open(path, 'w', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(rows)


def export_validation(report, directory):
    """Export auditable JSON + decision log, OHLC-independent CSV statistics."""
    folder = Path(directory)
    folder.mkdir(parents=True, exist_ok=True)
    # Avoid NaN/Infinity in the portable report.
    with open(folder/'validation.json','w',encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=2, allow_nan=False)
    for group in ('training', 'holdout', 'baseline_holdout'):
        out=report[group]
        _write_csv(folder/(group+'_trades.csv'),
                   ('side','signal_index','signal_at_utc','opened','closed','opened_at_utc','closed_at_utc',
                    'entry','exit','stop','target','size','pnl','reason','entry_fee','exit_fee'),
                   out['trades'])
        _write_csv(folder/(group+'_equity.csv'),
                   ('timestamp','utc','equity','max_drawdown_pct','active'),
                   out['equity_curve'])
        _write_csv(folder/(group+'_decisions.csv'),
                   ('bar_index','timestamp','utc','price','action','phase',
                    'rsi','ema_fast','ema_slow','atr','range_bottom','range_top',
                    'equity','explanation'),
                   out['decisions'])
    return folder


def short_summary(report):
    a=report['training']['metrics'];b=report['holdout']['metrics']
    c=report['baseline_holdout']['metrics']
    return (
        f"ИСТОРИЯ: {report['quality']['candles']} свечей, разрывов {report['quality']['gaps']}\n"
        f"TRAIN {report['split']['train_count']} | HOLDOUT {report['split']['holdout_count']}\n"
        f"TRAIN: {a['trade_count']} сделок, {a['return_pct']:+.2f}%, DD {a['max_drawdown_pct']:.2f}%\n"
        f"ВЫБОР ПО TRAIN: {report['selected_preset']}\n"
        f"HOLDOUT: {b['trade_count']} сделок, {b['return_pct']:+.2f}%, "
        f"DD {b['max_drawdown_pct']:.2f}%, PF {b['profit_factor']}\n"
        f"BASELINE HOLDOUT: {c['return_pct']:+.2f}% на {c['trade_count']} сделках\n"
        "ВНИМАНИЕ: это виртуальный тест на OHLC; карта ликвидаций не участвовала."
    )
