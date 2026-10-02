"""COG BTC study. Standard library only. Run --download once, then without flags.
Research rules, not an exact replication of discretionary author strategies.
"""
import csv, io, json, math, statistics, hashlib, zipfile, urllib.request
from pathlib import Path
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor
import sys

ROOT = Path(__file__).resolve().parent
def download():
    cache = ROOT / "archives"
    cache.mkdir(exist_ok=True)
    def one(ym):
        name = f"BTCUSDT-1d-{ym}.zip"
        url = "https://data.binance.vision/data/spot/monthly/klines/BTCUSDT/1d/" + name
        dest = cache / name
        data = dest.read_bytes() if dest.exists() else urllib.request.urlopen(url, timeout=30).read()
        check = urllib.request.urlopen(url + ".CHECKSUM", timeout=30).read().decode().split()[0]
        assert hashlib.sha256(data).hexdigest() == check, name
        dest.write_bytes(data)
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            rows = list(csv.reader(io.TextIOWrapper(z.open(z.namelist()[0]))))
        return rows, {"url": url, "sha256": check}
    months = [f"{y}-{m:02}" for y in range(2018, 2026) for m in range(1, 13)]
    with ThreadPoolExecutor(max_workers=6) as pool:
        batches = list(pool.map(one, months))
    rows = []
    for batch, _ in batches:
        for r in batch:
            ts = int(r[0])
            ts //= 1000 if ts > 10**14 else 1
            rows.append([datetime.fromtimestamp(ts/1000, timezone.utc).date().isoformat()] + r[1:6])
    rows.sort()
    assert len({r[0] for r in rows}) == len(rows)
    for a,b in zip(rows,rows[1:]):
        assert (datetime.fromisoformat(b[0])-datetime.fromisoformat(a[0])).days == 1
    for r in rows:
        o,h,l,c,v = map(float,r[1:])
        assert 0 < l <= min(o,c) <= max(o,c) <= h and v >= 0
    with (ROOT/"BTCUSDT-1d.csv").open("w",newline="") as f:
        w=csv.writer(f); w.writerow(["date","open","high","low","close","volume"]); w.writerows(rows)
    (ROOT/"sources.json").write_text(json.dumps([x[1] for x in batches],indent=2))
    print("Downloaded and SHA256 checked:",len(rows),"daily bars",flush=True)

def cog(x,n):
    out=[None]*len(x)
    for i in range(n-1,len(x)):
        a=x[i-n+1:i+1]
        out[i]=-sum(v*(n-j) for j,v in enumerate(a))/sum(a)
    return out

def ma(x,n,alpha=None):
    out=[None]*len(x); state=None
    for i in range(n-1,len(x)):
        a=x[i-n+1:i+1]
        if any(v is None for v in a): continue
        if alpha is None or state is None: state=sum(a)/n
        else: state=alpha*x[i]+(1-alpha)*state
        out[i]=state
    return out

def alma(x,n,offset=.85,sigma=6):
    weights=[math.exp(-((j-offset*(n-1))**2)/(2*(n/sigma)**2)) for j in range(n)]
    out=[None]*len(x)
    for i in range(n-1,len(x)):
        a=x[i-n+1:i+1]
        if all(v is not None for v in a): out[i]=sum(v*w for v,w in zip(a,weights))/sum(weights)
    return out

def linreg(x,n):
    out=[None]*len(x); mid=(n-1)/2; den=sum((j-mid)**2 for j in range(n))
    for i in range(n-1,len(x)):
        a=x[i-n+1:i+1]
        if all(v is not None for v in a):
            mean=sum(a)/n
            slope=sum((j-mid)*v for j,v in enumerate(a))/den
            out[i]=mean+slope*mid
    return out

def cross(a,b,i,up=True):
    if i < 1 or any(v is None for v in [a[i],b[i],a[i-1],b[i-1]]): return False
    return (a[i]>b[i] and a[i-1]<=b[i-1]) if up else (a[i]<b[i] and a[i-1]>=b[i-1])

def signals(close):
    c9=cog(close,9); c21=cog(close,21); r2=ma(c9,2,1/2)
    ema=ma(close,200,2/201)
    regime=[False if i==0 or ema[i] is None or ema[i-1] is None else close[i]>ema[i] and ema[i]>=ema[i-1] for i in range(len(close))]
    a3=alma(c9,3); a5=alma(c9,5)
    defs=[
        ("A_COG9_virada",c9,[None]+c9[:-1],False,1),
        ("B_COG9_ALMA3",c9,a3,False,1),
        ("C_COG9_RMA2_ALMA3",r2,alma(r2,3),False,1),
        ("D_COG21_ALMA3",c21,alma(c21,3),False,1),
        ("E_COG9_ALMA5",c9,a5,False,1),
        ("F_COG9_ALMA3_EMA200",c9,a3,True,1),
        ("G_COG9_LSMA200_EMA200",c9,linreg(c9,200),True,1),
        ("H_COG9_ALMA3_confirma2",c9,a3,False,2),
    ]
    result={}
    for name,a,b,filt,confirm in defs:
        buy=[False]*len(close); sell=buy.copy()
        for i in range(1,len(close)):
            if confirm==1:
                buy[i]=cross(a,b,i)
            else:
                buy[i]=i>=2 and cross(a,b,i-1) and a[i] is not None and b[i] is not None and a[i]>b[i]
            sell[i]=cross(a,b,i,False)
            if filt:
                buy[i]=buy[i] and regime[i]
                sell[i]=sell[i] or not regime[i]
        result[name]=(buy,sell)
    return result

def wilson(w,n):
    if not n:return [None,None]
    z=1.96; p=w/n; d=1+z*z/n
    center=(p+z*z/(2*n))/d
    half=z*math.sqrt(p*(1-p)/n+z*z/(4*n*n))/d
    return [100*(center-half),100*(center+half)]

def simulate(rows,buy,sell,start,end,cost=.0015,hold=False):
    ids=[i for i,r in enumerate(rows) if start<=r["date"]<=end]
    cash=10000.; qty=0.; trades=[]; curve=[]; entry=None; invested=0
    for i in ids:
        r=rows[i]; o=r["open"]; c=r["close"]
        if qty and sell[i-1] and not hold:
            proceeds=qty*o*(1-cost)
            trades.append(dict(entry=entry[0],exit=r["date"],net_pct=(proceeds/entry[1]-1)*100,pnl=proceeds-entry[1],forced=False))
            cash=proceeds; qty=0
        elif not qty and (buy[i-1] or hold):
            entry=(r["date"],cash)
            qty=cash/(o*(1+cost)); cash=0
        if qty:invested+=1
        equity=cash+qty*c
        if i==ids[-1] and qty:
            cash=qty*c*(1-cost)
            trades.append(dict(entry=entry[0],exit=r["date"],net_pct=(cash/entry[1]-1)*100,pnl=cash-entry[1],forced=True))
            qty=0; equity=cash
        curve.append((r["date"],equity))
    peak=10000.; dd=0
    for _,eq in curve:
        peak=max(peak,eq); dd=max(dd,1-eq/peak)
    wins=sum(t["pnl"]>0 for t in trades); n=len(trades)
    gain=sum(max(t["pnl"],0) for t in trades); loss=-sum(min(t["pnl"],0) for t in trades)
    endval=curve[-1][1]; days=len(ids)
    stats=dict(trades=n,wins=wins,win_rate=100*wins/n if n else None,ci95=wilson(wins,n),
        return_pct=100*(endval/10000-1),cagr_pct=100*((endval/10000)**(365.25/days)-1),
        max_dd_pct=dd*100,pf=gain/loss if loss else None,
        avg_trade_pct=statistics.mean(t["net_pct"] for t in trades) if trades else None,
        exposure_pct=invested/days*100,forced_exits=sum(t["forced"] for t in trades))
    return stats,trades,curve

def main():
    assert cog([1.]*10,9)[-1] == -5
    assert cog(list(range(1,11)),9)[-1] > -5
    assert abs(alma([7.]*10,3)[-1]-7)<1e-10
    with (ROOT/"BTCUSDT-1d.csv").open() as f:
        rows=[{k:(v if k=="date" else float(v)) for k,v in r.items()} for r in csv.DictReader(f)]
    sig=signals([r["close"] for r in rows])
    results={}; trade_rows=[]; curves={}
    for period,start,end in [("development","2019-01-01","2022-12-31"),("validation","2023-01-01","2025-12-31")]:
        results[period]={}
        for name,(buy,sell) in sig.items():
            st,tr,curve=simulate(rows,buy,sell,start,end)
            st["stress_cost"]=simulate(rows,buy,sell,start,end,.003)[0]
            results[period][name]=st
            trade_rows.extend(dict(period=period,strategy=name,**t) for t in tr)
            if period=="validation":curves[name]=curve
        st,_,curve=simulate(rows,[False]*len(rows),[False]*len(rows),start,end,hold=True)
        results[period]["Buy_and_hold"]=st
        if period=="validation":curves["Buy_and_hold"]=curve
    results["annual"]={}
    for y in range(2023,2026):
        results["annual"][str(y)]={name:simulate(rows,*ss,f"{y}-01-01",f"{y}-12-31")[0] for name,ss in sig.items()}
    results["metadata"]={"symbol":"BTCUSDT spot","timeframe":"1d UTC","data_start":rows[0]["date"],"data_end":rows[-1]["date"],"bars":len(rows),"cost_per_side":.0015,"stress_per_side":.003,"long_only":True,"initial_capital":10000,"execution":"signal at close, next open; last day liquidated at close"}
    (ROOT/"results.json").write_text(json.dumps(results,indent=2))
    with (ROOT/"trades.csv").open("w",newline="") as f:
        w=csv.DictWriter(f,fieldnames=trade_rows[0].keys());w.writeheader();w.writerows(trade_rows)
    with (ROOT/"equity-validation.csv").open("w",newline="") as f:
        w=csv.writer(f); names=list(curves);w.writerow(["date"]+names)
        for i in range(len(curves[names[0]])):
            w.writerow([curves[names[0]][i][0]]+[curves[n][i][1] for n in names])
    print(json.dumps(results,indent=2))

if __name__=="__main__":
    if "--download" in sys.argv:download()
    else:main()
