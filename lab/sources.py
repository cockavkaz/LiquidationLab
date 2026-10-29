"""Data origins are explicitly marked; no real orders, wallets or secrets."""
import math,random,csv,json,time
from urllib.parse import urlencode
from urllib.request import Request,urlopen
from .models import Candle,Cluster

def synthetic_scenario(name="up",seed=19,cycles=7):
    if name not in ("up","down","sideways"):raise ValueError("Unknown scenario")
    rng=random.Random(seed+{"up":0,"down":101,"sideways":202}[name]);candles=[];price=100.
    def emit(p):
        nonlocal price
        hi=max(price,p)+rng.uniform(.07,.2);lo=min(price,p)-rng.uniform(.07,.2)
        candles.append(Candle(1725000000000+len(candles)*900000,price,hi,max(.01,lo),p,rng.uniform(400,1800)));price=p
    for i in range(80):emit(max(1,price+.12*math.sin(i*.24)+rng.uniform(-.1,.1)))
    for block in range(cycles):
        sign=(1 if block%2==0 else -1) if name=="sideways" else (1 if name=="up" else -1)
        for j in range(10):emit(max(1,price+sign*(.54+rng.uniform(-.12,.12))))
        center=price
        for j in range(32):emit(max(1,center+1.05*math.sin(j*math.pi/5+.8)+rng.uniform(-.07,.07)))
    baseline=price
    clusters=[Cluster(baseline*(1+d),v,"demo") for d,v in [(-.029,30),(-.021,67),(-.013,92),(-.006,44),(.005,72),(.012,100),(.02,55),(.029,25)]]
    return candles,clusters

def fetch_bybit_candles(symbol="BTCUSDT",interval="15",limit=500,timeout=12,opener=urlopen,now_ms=None):
    minutes={"1":1,"3":3,"5":5,"15":15,"30":30,"60":60,"120":120,"240":240,"360":360,"720":720,"D":1440}
    if interval not in minutes or not 50<=limit<=1000 or not symbol.isalnum() or not symbol.isupper():raise ValueError("Invalid request")
    url="https://api.bybit.com/v5/market/kline?"+urlencode(dict(category="linear",symbol=symbol,interval=interval,limit=limit))
    with opener(Request(url,headers={"User-Agent":"LiquidationLab-Educational/0.2"}),timeout=timeout) as r:
        payload=json.loads(r.read().decode())
    if payload.get("retCode")!=0:raise ValueError("Bybit API error")
    now_ms=int(time.time()*1000) if now_ms is None else now_ms
    out=[]
    for row in payload["result"]["list"]:
        c=Candle(int(row[0]),*map(float,row[1:6]));c.validate()
        if c.timestamp+minutes[interval]*60000<=now_ms:out.append(c)
    return sorted(set(out),key=lambda x:x.timestamp)

def save_candles_csv(path,candles):
    with open(path,"w",newline="",encoding="utf8") as f:
        w=csv.writer(f);w.writerow(("timestamp","open","high","low","close","volume"))
        w.writerows((c.timestamp,c.open,c.high,c.low,c.close,c.volume) for c in candles)

def load_candles_csv(path):
    out=[]
    with open(path,encoding="utf-8-sig",newline="") as f:
        for row in csv.DictReader(f):
            c=Candle(int(row["timestamp"]),float(row["open"]),float(row["high"]),float(row["low"]),float(row["close"]),float(row.get("volume") or 0))
            c.validate()
            if out and c.timestamp<=out[-1].timestamp:raise ValueError("Timestamps must ascend")
            out.append(c)
    return out

def load_clusters_csv(path):
    out=[]
    with open(path,encoding="utf-8-sig",newline="") as f:
        for row in csv.DictReader(f):
            p=float(row["price"]);intensity=float(row["intensity"])
            if p<=0 or intensity<0 or not math.isfinite(p+intensity):raise ValueError("Bad level")
            out.append(Cluster(p,intensity,"imported"))
    return out

def fetch_coinglass_snapshot(api_key,period="1d",opener=urlopen,timeout=15):
    if not api_key:raise ValueError("CoinGlass API key required")
    if period not in ("1d","7d","30d","180d","365d"):raise ValueError("Invalid period")
    url="https://open-api-v4.coinglass.com/api/futures/liquidation/map?"+urlencode(dict(exchange="Bybit",symbol="BTCUSDT",range=period))
    req=Request(url,headers={"accept":"application/json","CG-API-KEY":api_key,"User-Agent":"LiquidationLab-Educational/0.2"})
    with opener(req,timeout=timeout) as r:payload=json.loads(r.read().decode())
    if str(payload.get("code"))!="0":raise ValueError("CoinGlass error: verify plan/symbol/key")
    raw=(payload.get("data") or {}).get("data")
    if not isinstance(raw,dict):raise ValueError("Unexpected CoinGlass format")
    bins={}
    for rows in raw.values():
        if isinstance(rows,list):
            for row in rows:
                if isinstance(row,list) and len(row)>=2:
                    p,v=float(row[0]),float(row[1])
                    if p>0 and v>=0 and math.isfinite(p+v):bins[p]=bins.get(p,0)+v
    return [Cluster(p,v,"coinglass-snapshot") for p,v in sorted(bins.items())]
