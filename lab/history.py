"""Bybit V5 historical OHLC pagination (read-only, no API keys).

The API returns newest-first rows with at most 1000 candles per request.
Only closed candles are saved, sorted oldest-to-newest and deduplicated.
"""
import json
import time
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from .models import Candle

MINUTES = {'1': 1, '3': 3, '5': 5, '15': 15, '30': 30,
           '60': 60, '120': 120, '240': 240, '360': 360,
           '720': 720, 'D': 1440}


def fetch_bybit_history(symbol='BTCUSDT', interval='60', days=30,
                        opener=urlopen, timeout=15, now_ms=None, end_ms=None,
                        max_bars=12000, on_page=None):
    """Fetch up to 'days' before end_ms; 1..1000 bars per request.

    end_ms is the upper edge of the requested history; now_ms is used only
    to reject an unfinished live candle. Mockable opener aids offline tests.
    """
    if not symbol.isalnum() or not symbol.isupper() or not 1 <= len(symbol) <= 25:
        raise ValueError('Invalid symbol')
    if interval not in MINUTES or not (1 <= days <= 365) or max_bars < 10:
        raise ValueError('Invalid history range')
    now = int(time.time()*1000) if now_ms is None else int(now_ms)
    end = min(now, int(end_ms)) if end_ms is not None else now
    since = end - int(days*86400000)
    page_end = end
    step_ms = MINUTES[interval] * 60000
    by_start = {}
    for page in range(1 + max_bars//1000 + 1):
        params = {'category': 'linear', 'symbol': symbol, 'interval': interval,
                  'start': since, 'end': page_end, 'limit': min(1000, max_bars)}
        url = 'https://api.bybit.com/v5/market/kline?' + urlencode(params)
        req = Request(url, headers={'User-Agent': 'LiquidationLab-Educational/0.3'})
        try:
            with opener(req, timeout=timeout) as response:
                payload = json.loads(response.read().decode('utf-8'))
        except HTTPError as exc:
            if exc.code == 403:
                raise ConnectionError(
                    'Bybit returned HTTP 403: this network cannot access the public market API. '
                    'Run the Windows app where access is permitted or import completed OHLC CSV; '
                    'no historical result was generated.'
                ) from exc
            raise
        if payload.get('retCode') != 0:
            raise ValueError('Bybit returned error: '+str(payload.get('retMsg', 'unknown')))
        rows = payload.get('result', {}).get('list', [])
        if not rows:
            break
        starts = []
        for row in rows:
            candle = Candle(int(row[0]), *map(float, row[1:6]))
            candle.validate()
            starts.append(candle.timestamp)
            if since <= candle.timestamp <= end and candle.timestamp+step_ms <= now:
                by_start[candle.timestamp] = candle
        if on_page:
            on_page(page+1, len(by_start))
        oldest = min(starts)
        if oldest <= since or len(by_start) >= max_bars:
            break
        if oldest >= page_end:
            raise ValueError('Bybit pagination did not advance')
        page_end = oldest-1
        if len(rows) < min(1000, max_bars):
            break
    candles = [by_start[k] for k in sorted(by_start)]
    if len(candles) > max_bars:
        candles = candles[-max_bars:]
    if not candles:
        raise ValueError('Bybit returned no closed candles in this period')
    return candles
