"""Run research on desktop, without Kivy, network, or trade credentials."""
import argparse
import csv
import json
import os
from datetime import datetime, timezone
from .sources import (synthetic_scenario, load_candles_csv, save_candles_csv,
                      load_clusters_csv, fetch_coinglass_snapshot)
from .backtest import simulate
from .detection import describe


def main():
    parser = argparse.ArgumentParser(description='Liquidation Lab (offline research, no orders)')
    parser.add_argument('--scenario', choices=['up', 'down', 'sideways'], default='up')
    parser.add_argument('--csv', help='Optional historical OHLC CSV')
    parser.add_argument('--levels-csv', help='Optional supplied price,intensity CSV')
    parser.add_argument('--export-csv', help='Save demo OHLC as CSV')
    parser.add_argument('--backtest', action='store_true')
    parser.add_argument('--coinglass-export', help='Fetch current CoinGlass map into CSV (not historical)')
    parser.add_argument('--coinglass-range', choices=['1d','7d','30d','180d','365d'], default='1d')
    args = parser.parse_args()
    candles, clusters = synthetic_scenario(args.scenario)
    source = 'ARTIFICIAL DEMO'
    if args.csv:
        candles = load_candles_csv(args.csv)
        clusters = []
        source = 'HISTORICAL CSV: ' + args.csv
    if args.levels_csv:
        clusters = load_clusters_csv(args.levels_csv)
    if args.coinglass_export:
        clusters = fetch_coinglass_snapshot(os.getenv('COINGLASS_API_KEY',''),
                                           period=args.coinglass_range)
        with open(args.coinglass_export, 'w', encoding='utf8', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(('price','intensity'))
            writer.writerows((c.price, c.intensity) for c in clusters)
        metadata = {'retrieved_at_utc': datetime.now(timezone.utc).isoformat(),
                    'provider': 'CoinGlass', 'exchange': 'Bybit',
                    'symbol': 'BTCUSDT', 'range': args.coinglass_range,
                    'meaning': 'CURRENT SNAPSHOT, NOT HISTORICALLY OBSERVED'}
        with open(args.coinglass_export + '.metadata.json', 'w', encoding='utf8') as f:
            json.dump(metadata, f, ensure_ascii=False, indent=2)
        source += ' + COINGLASS CURRENT SNAPSHOT (never used by backtest)'
    if args.export_csv:
        save_candles_csv(args.export_csv, candles)
    d = describe(candles)
    print(f'Source: {source}; candles: {len(candles)}; clusters: {len(clusters)}')
    print(f'Last price: {d["price"]}; RSI: {d["rsi"]}; range setup: {d["setup"]}')
    if args.backtest:
        out = simulate(candles)
        summary = {k: v for k, v in out.items() if k not in ('trades','equity_curve')}
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        for t in out['trades']:
            print(f"{t['side']:5} {t['opened']:3}->{t['closed']:3} PnL={t['pnl']:+.2f} ({t['reason']})")


if __name__ == '__main__':
    main()
