"""Offline/reproducible CLI validation on real Bybit OHLC or exported CSV."""
import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path
from .history import MINUTES, fetch_bybit_history
from .sources import load_candles_csv, save_candles_csv, synthetic_scenario
from .validation import export_validation, short_summary, validate_history


def main(argv=None):
    # GitHub-hosted Windows runners and some classic terminals default to
    # CP1252/CP866. Print Russian diagnostics without UnicodeEncodeError.
    if hasattr(sys.stdout, 'reconfigure'):
        try:
            sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        except (ValueError, OSError):
            pass
    parser = argparse.ArgumentParser(description='Liquidation Lab 0.4: chronological OHLC-only validation')
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--bybit', action='store_true', help='Fetch public finished candles from Bybit')
    source.add_argument('--csv', help='Local timestamp/open/high/low/close/volume CSV')
    source.add_argument('--demo', choices=('up','down','sideways'), help='Artificial data for software testing ONLY')
    parser.add_argument('--symbol',default='BTCUSDT')
    parser.add_argument('--interval',choices=tuple(MINUTES),default='60')
    parser.add_argument('--days',type=int,default=90)
    parser.add_argument('--train-fraction',type=float,default=.7)
    parser.add_argument('--no-tune',action='store_true')
    parser.add_argument('--output',default='reports')
    parser.add_argument('--max-bars',type=int,default=12000)
    args=parser.parse_args(argv)
    if args.bybit:
        candles=fetch_bybit_history(symbol=args.symbol,interval=args.interval,
                                    days=args.days,max_bars=args.max_bars)
        label=f'BYBIT public OHLC {args.symbol} {args.interval} / {args.days} days'
    elif args.csv:
        candles=load_candles_csv(args.csv)
        label=f'IMPORTED CSV {args.csv}'
    else:
        candles,_=synthetic_scenario(args.demo,cycles=12)
        label='ARTIFICIAL '+args.demo
    result=validate_history(candles,source=label,
                            interval_minutes=MINUTES[args.interval] if args.bybit or args.demo else None,
                            train_fraction=args.train_fraction,tune=not args.no_tune)
    date=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    folder=Path(args.output)/('validation-'+date)
    folder.mkdir(parents=True,exist_ok=True)
    save_candles_csv(folder/'source_candles.csv',candles)
    export_validation(result,folder)
    print(short_summary(result))
    print('Отчёт: '+str(folder.absolute()))


if __name__=='__main__':
    main()
