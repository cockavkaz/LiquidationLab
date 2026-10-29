"""OHLC-only educational simulator, including fees/slippage. No real orders."""
from .detection import Parameters,research_hypothesis

def simulate(candles,params=Parameters(),initial_equity=10000.,risk_fraction=.005,
             max_notional_mult=1.,fee_rate=.0006,slippage=.0002):
    if initial_equity<=0 or not 0<risk_fraction<=.1 or max_notional_mult<=0 or fee_rate<0 or not 0<=slippage<.05:
        raise ValueError("Invalid simulation settings")
    equity=initial_equity;peak=equity;drawdown=0;trades=[];position=None
    warmup=max(params.ema_slow+2,params.rsi_period+params.range_bars+params.impulse_bars+3)
    for i in range(warmup,len(candles)-1):
        nxt=candles[i+1]
        if position is None:
            idea=research_hypothesis(candles[:i+1],params)
            if idea:
                sign=1 if idea["side"]=="long" else -1
                entry=nxt.open*(1+sign*slippage)
                stop=idea["stop"];target=idea["target"]
                valid=(stop<entry<target if sign==1 else target<entry<stop)
                if valid:
                    size=min(equity*risk_fraction/abs(entry-stop),equity*max_notional_mult/entry)
                    if size>0:
                        entry_fee=size*entry*fee_rate;equity-=entry_fee
                        position=dict(sign=sign,side=idea["side"],entry=entry,stop=stop,target=target,size=size,opened=i+1,entry_fee=entry_fee)
        if position:
            p=position;long=p["sign"]==1
            sl_hit=nxt.low<=p["stop"] if long else nxt.high>=p["stop"]
            tp_hit=nxt.high>=p["target"] if long else nxt.low<=p["target"]
            if sl_hit or tp_hit:
                raw=(min(nxt.open,p["stop"]) if long else max(nxt.open,p["stop"])) if sl_hit else p["target"]
                exit_price=raw*(1-slippage if long else 1+slippage)
                fee=p["size"]*exit_price*fee_rate
                pnl=(exit_price-p["entry"])*p["size"]*p["sign"]-fee-p["entry_fee"]
                equity+=pnl+p["entry_fee"]
                reason="SL" if sl_hit else "TP"
                if sl_hit and tp_hit:reason="SL (ambiguous candle)"
                trades.append(dict(side=p["side"],entry=p["entry"],exit=exit_price,pnl=pnl,opened=p["opened"],closed=i+1,reason=reason))
                position=None;peak=max(peak,equity);drawdown=max(drawdown,(peak-equity)/peak)
    if position and candles:
        p=position;long=p["sign"]==1
        ex=candles[-1].close*(1-slippage if long else 1+slippage)
        pnl=(ex-p["entry"])*p["size"]*p["sign"]-p["size"]*ex*fee_rate-p["entry_fee"]
        equity+=pnl+p["entry_fee"]
        trades.append(dict(side=p["side"],entry=p["entry"],exit=ex,pnl=pnl,opened=p["opened"],closed=len(candles)-1,reason="end"))
        peak=max(peak,equity);drawdown=max(drawdown,(peak-equity)/peak)
    profits=sum(t["pnl"] for t in trades if t["pnl"]>0);losses=-sum(t["pnl"] for t in trades if t["pnl"]<0)
    return dict(initial_equity=initial_equity,final_equity=equity,return_pct=(equity/initial_equity-1)*100,
                trade_count=len(trades),win_rate_pct=100*sum(t["pnl"]>0 for t in trades)/len(trades) if trades else 0,
                max_drawdown_pct=drawdown*100,profit_factor=profits/losses if losses else (float("inf") if profits else 0),
                trades=trades,notes="Paper-only OHLC simulation; not predictive.")
