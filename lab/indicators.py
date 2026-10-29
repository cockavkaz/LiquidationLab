"""Causal indicators: each value uses historical candles only."""
from .models import Candle

def ema(values, period):
    if period < 1:
        raise ValueError("period must be positive")
    output = [None] * len(values)
    if len(values) < period:
        return output
    value = sum(values[:period])/period
    output[period-1] = value
    a = 2/(period+1)
    for i in range(period,len(values)):
        value += a*(values[i]-value)
        output[i] = value
    return output

def rsi(values, period=14):
    if period < 1:
        raise ValueError("period must be positive")
    out = [None]*len(values)
    if len(values) <= period:
        return out
    diffs=[values[i]-values[i-1] for i in range(1,period+1)]
    gain=sum(max(d,0) for d in diffs)/period
    loss=sum(max(-d,0) for d in diffs)/period
    for i in range(period,len(values)):
        if i>period:
            d=values[i]-values[i-1]
            gain=(gain*(period-1)+max(d,0))/period
            loss=(loss*(period-1)+max(-d,0))/period
        out[i] = 50.0 if gain==0 and loss==0 else (100.0 if loss==0 else 100-100/(1+gain/loss))
    return out

def atr(candles,period=14):
    if period < 1:
        raise ValueError("period must be positive")
    out=[None]*len(candles)
    if len(candles)<=period:
        return out
    tr=[max(c.high-c.low,abs(c.high-candles[i-1].close),abs(c.low-candles[i-1].close))
        for i,c in enumerate(candles) if i>0]
    value=sum(tr[:period])/period
    out[period]=value
    for i in range(period+1,len(candles)):
        value=(value*(period-1)+tr[i-1])/period
        out[i]=value
    return out

def confirmed_pivots(candles, reversal_pct=.012):
    """Confirmed ZigZag pivots; not an objectively proven Elliott labeling."""
    if len(candles)<3 or reversal_pct<=0:
        return []
    pivots=[]
    hi=lo=candles[0].close
    hi_i=lo_i=0
    direction=0
    for i,c in enumerate(candles[1:],1):
        if direction==0:
            if c.high>hi: hi,hi_i=c.high,i
            if c.low<lo: lo,lo_i=c.low,i
            if hi/lo-1 >= reversal_pct:
                if hi_i>lo_i: direction=1; pivots.append((lo_i,lo,"L"))
                else: direction=-1; pivots.append((hi_i,hi,"H"))
        elif direction==1:
            if c.high>hi: hi,hi_i=c.high,i
            if c.low<=hi*(1-reversal_pct):
                pivots.append((hi_i,hi,"H"));direction=-1;lo,lo_i=c.low,i
        else:
            if c.low<lo: lo,lo_i=c.low,i
            if c.high>=lo*(1+reversal_pct):
                pivots.append((lo_i,lo,"L"));direction=1;hi,hi_i=c.high,i
    return pivots
