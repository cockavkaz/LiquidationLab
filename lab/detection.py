"""Detect impulse BEFORE a subsequent non-overlapping range."""
from dataclasses import dataclass
from .models import Setup
from .indicators import atr,ema,rsi

@dataclass(frozen=True)
class Parameters:
    impulse_bars:int=10
    range_bars:int=24
    impulse_atr_multiple:float=2.4
    max_range_pct:float=.035
    max_range_to_impulse:float=.8
    min_impulse_body_ratio:float=.45
    ema_fast:int=20
    ema_slow:int=50
    rsi_period:int=14
    use_rsi_filter:bool=True
    edge_zone:float=.25

def find_setup(candles,p=Parameters(),as_of=None):
    end=len(candles)-1 if as_of is None else as_of
    if end>=len(candles) or end<0: return None
    rstart=end-p.range_bars+1
    iend=rstart-1
    istart=iend-p.impulse_bars+1
    if p.impulse_bars<2 or p.range_bars<3 or istart<p.rsi_period+2:return None
    impulse=candles[istart:iend+1]
    range_data=candles[rstart:end+1]
    move=impulse[-1].close-impulse[0].open
    reference_atr=atr(candles[:iend+1],p.rsi_period)[-1]
    if not reference_atr or abs(move)<p.impulse_atr_multiple*reference_atr:return None
    excursion=max(c.high for c in impulse)-min(c.low for c in impulse)
    if excursion<=0 or abs(move)/excursion<p.min_impulse_body_ratio:return None
    top=max(c.high for c in range_data);bottom=min(c.low for c in range_data)
    mid=(top+bottom)/2;width=top-bottom
    if mid<=0 or width/mid>p.max_range_pct or width>abs(move)*p.max_range_to_impulse:return None
    return Setup("up" if move>0 else "down",abs(move),bottom,top,mid,width/mid,istart,iend,rstart,end)

def describe(candles,p=Parameters()):
    if not candles:return dict(setup=None,rsi=None,ema_fast=None,ema_slow=None,atr=None,price=None)
    closes=[c.close for c in candles]
    return dict(setup=find_setup(candles,p),rsi=rsi(closes,p.rsi_period)[-1],
                ema_fast=ema(closes,p.ema_fast)[-1],ema_slow=ema(closes,p.ema_slow)[-1],
                atr=atr(candles,p.rsi_period)[-1],price=closes[-1])

def research_hypothesis(candles,p=Parameters()):
    """Hypothetical fill is next open; never place an actual order."""
    if len(candles)<p.impulse_bars+p.range_bars+p.rsi_period+4:return None
    ref=find_setup(candles,p,as_of=len(candles)-2)
    if not ref:return None
    d=describe(candles,p)
    price=candles[-1].close
    if not d["atr"] or d["rsi"] is None:return None
    span=ref.top-ref.bottom
    if span<=0 or not ref.bottom<=price<=ref.top:return None
    pos=(price-ref.bottom)/span
    if pos<=p.edge_zone:
        if p.use_rsi_filter and d["rsi"]>47:return None
        side="long";stop=ref.bottom-d["atr"]*.25;target=ref.top-span*.1
    elif pos>=1-p.edge_zone:
        if p.use_rsi_filter and d["rsi"]<53:return None
        side="short";stop=ref.top+d["atr"]*.25;target=ref.bottom+span*.1
    else:return None
    return dict(side=side,stop=stop,target=target,setup=ref,rsi=d["rsi"],
                ema_fast=d["ema_fast"],ema_slow=d["ema_slow"])
