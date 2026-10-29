"""Clearly labeled sources. No exchange credentials, order submission or scraping."""
import csv
import json
import math
import random
import time
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from .models import Candle, Cluster


def synthetic_scenario(name='up', seed=19, cycles=7) -> tuple[list[Candle], list[Cluster]]:
    """Deterministic *fabricated* OHLC and liquidation-like clusters for UI demos."""
    if name not in ('up', 'down', 'sideways'):
        raise ValueError('Unknown scenario')
    rng = random.Random(seed + {'up': 0, 'down': 101, 'sideways': 202}[name])
    candles = []
    price = 100.0
    initial = 1_725_000_000_000

    def candle(next_price, i):
        nonlocal price
        op = price
        close = max(1, next_price)
        hi = max(op, close) + rng.uniform(.07, .20)
        lo = min(op, close) - rng.uniform(.07, .20)
        candles.append(Candle(initial + i*900_000, op, hi, lo, close,
                              rng.uniform(400, 1800)))
        price = close

    for i in range(80):
        candle(price + .12*math.sin(i*.24) + rng.uniform(-.10, .10), i)
    for block in range(cycles):
        phase = len(candles)
        direction = (1 if block % 2 == 0 else -1) if name == 'sideways' else (1 if name == 'up' else -1)
        for j in range(10):
            candle(price + direction*(.54 + rng.uniform(-.12, .12)), phase + j)
        center = price
        for j in range(32):
            # Long range after the impulse; repeated lower/upper boundary visits.
            delta = 1.05*math.sin(j * math.pi / 5 + .8) + rng.uniform(-.07, .07)
            candle(center + delta, phase + 10 + j)
        price = candles[-1].close
    baseline = candles[-1].close
    clusters = [Cluster(baseline*(1 + dist), strength, 'demo') for dist, strength in
                [(-.029, 30), (-.021, 67), (-.013, 92), (-.006, 44),
                 (.005, 72), (.012, 100), (.020, 55), (.029, 25)]]
    return candles, clusters


def save_candles_csv(path, candles):
    with open(path, 'w', encoding='utf-8', newline='') as f:
        w = csv.writer(f)
        w.writerow(('timestamp', 'open', 'high', 'low', 'close', 'volume'))
        for c in candles:
            w.writerow((c.timestamp, c.open, c.high, c.low, c.close, c.volume))


def load_candles_csv(path) -> list[Candle]:
    """Data contract: timestamp in UTC milliseconds, ascending; OHLC numeric."""
    with open(path, 'r', encoding='utf-8-sig', newline='') as f:
        rows = csv.DictReader(f)
        if not rows.fieldnames or not {'timestamp', 'open', 'high', 'low', 'close'}.issubset(rows.fieldnames):
            raise ValueError('CSV requires timestamp,open,high,low,close')
        out = []
        for row in rows:
            c = Candle(int(row['timestamp']), float(row['open']), float(row['high']),
                       float(row['low']), float(row['close']), float(row.get('volume') or 0))
            c.validate()
            if out and c.timestamp <= out[-1].timestamp:
                raise ValueError('Timestamps must be strictly ascending')
            out.append(c)
    return out


def load_clusters_csv(path) -> list[Cluster]:
    """Generic user-supplied level export: price,intensity (NOT an automatic CoinGlass API)."""
    with open(path, 'r', encoding='utf-8-sig', newline='') as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames or not {'price','intensity'}.issubset(reader.fieldnames):
            raise ValueError('Level CSV requires price,intensity')
        clusters = []
        for r in reader:
            price, intensity = float(r['price']), float(r['intensity'])
            if not (math.isfinite(price) and math.isfinite(intensity)) or price <= 0 or intensity < 0:
                raise ValueError('Level and intensity must be nonnegative finite numbers')
            clusters.append(Cluster(price, intensity, 'imported'))
    return clusters


def aggregate_historical_events(events, reference_price: float, bucket_pct: float = .005):
    """Historic liquidation EXECUTIONS, not a map of future potential liquidations.

    events: iterable of dicts: price, quantity. Preserve a FIXED bin size over time.
    """
    if reference_price <= 0 or bucket_pct <= 0:
        raise ValueError('Reference price and width must be positive')
    step = reference_price * bucket_pct
    bins = {}
    for e in events:
        price = float(e['price'])
        qty = float(e['quantity'])
        if not (math.isfinite(price) and math.isfinite(qty)) or price <= 0 or qty < 0:
            raise ValueError('Invalid executed liquidation event')
        bucket = math.floor(price / step)
        bins[bucket] = bins.get(bucket, 0) + qty
    return [Cluster((b + .5) * step, vol, 'executed-history') for b, vol in sorted(bins.items())]


def fetch_bybit_candles(symbol='BTCUSDT', interval='15', limit=500,
                        *, timeout=12, opener=urlopen, now_ms=None):
    """Public REST candles, no API key; excludes the current UNFINISHED candle.

    This is BYBIT OHLC data, not a CoinGlass liquidation map.
    """
    allowed_intervals = {'1': 1, '3': 3, '5': 5, '15': 15, '30': 30,
                         '60': 60, '120': 120, '240': 240, '360': 360,
                         '720': 720, 'D': 1440}
    if interval not in allowed_intervals or not (50 <= limit <= 1000):
        raise ValueError('Unsupported timeframe or limit (50..1000)')
    if not (3 <= len(symbol) <= 20 and symbol.isalnum() and symbol.isupper()):
        raise ValueError('Invalid symbol')
    q = urlencode({'category': 'linear', 'symbol': symbol, 'interval': interval, 'limit': limit})
    url = 'https://api.bybit.com/v5/market/kline?' + q
    request = Request(url, headers={'User-Agent': 'LiquidationLab-Educational/0.2'})
    with opener(request, timeout=timeout) as f:
        payload = json.loads(f.read().decode('utf-8'))
    if payload.get('retCode') != 0:
        raise ValueError(f"Bybit response error: {payload.get('retMsg', 'unknown')}")
    now_ms = int(time.time() * 1000) if now_ms is None else now_ms
    candle_duration = allowed_intervals[interval] * 60_000
    out = []
    for raw in payload['result']['list']:
        timestamp, o, h, l, c, v = raw[:6]
        candle = Candle(int(timestamp), float(o), float(h), float(l), float(c), float(v))
        candle.validate()
        if candle.timestamp + candle_duration <= now_ms:
            out.append(candle)
    out.sort(key=lambda c: c.timestamp)
    return [c for i, c in enumerate(out) if i == 0 or c.timestamp > out[i-1].timestamp]


def fetch_coinglass_snapshot(api_key: str, exchange='Bybit', symbol='BTCUSDT',
                             period='1d', *, timeout=15, opener=urlopen) -> list[Cluster]:
    """Official CoinGlass v4 *CURRENT SNAPSHOT* (requires eligible paid API plan).

    Documentation: https://docs.coinglass.com/reference/liquidation-map
    No historical backfill here. Never feed current snapshots into historical trades.
    """
    if not api_key or not api_key.strip():
        raise ValueError('Set COINGLASS_API_KEY; endpoint requires an eligible API plan')
    if period not in ('1d', '7d', '30d', '180d', '365d'):
        raise ValueError('Unsupported map range')
    if not exchange or not symbol or not symbol.isalnum():
        raise ValueError('Exchange and symbol required')
    q = urlencode({'exchange': exchange, 'symbol': symbol, 'range': period})
    req = Request('https://open-api-v4.coinglass.com/api/futures/liquidation/map?' + q,
                  headers={'accept': 'application/json', 'CG-API-KEY': api_key.strip(),
                           'User-Agent': 'LiquidationLab-Educational/0.2'})
    with opener(req, timeout=timeout) as f:
        payload = json.loads(f.read().decode('utf-8'))
    if str(payload.get('code')) != '0':
        # Never include an API key in error logs or exception texts.
        raise ValueError('CoinGlass returned an error (check subscription, symbol and key)')
    raw = (payload.get('data') or {}).get('data')
    if not isinstance(raw, dict):
        raise ValueError('Unexpected CoinGlass liquidation map format')
    bins = {}
    for _, rows in raw.items():
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, list) or len(row) < 2:
                continue
            price, strength = float(row[0]), float(row[1])
            if (math.isfinite(price) and math.isfinite(strength)
                and price > 0 and strength >= 0):
                bins[price] = bins.get(price, 0) + strength
    return [Cluster(p, v, 'coinglass-snapshot') for p, v in sorted(bins.items())]
