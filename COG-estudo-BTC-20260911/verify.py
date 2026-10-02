"""Checks of causal signals and next-open execution; not Pine compiler parity."""
import study, csv

with (study.ROOT/"BTCUSDT-1d.csv").open() as f:
    close=[float(r["close"]) for r in csv.DictReader(f)]
full=study.signals(close)
for cut in [400,1100,1900,2500]:
    partial=study.signals(close[:cut])
    for name in full:
        assert full[name][0][:cut]==partial[name][0],name
        assert full[name][1][:cut]==partial[name][1],name

# Signal on day 1 buys day 2 at 100, signal on day 2 exits day 3 at 120.
rows=[dict(date=f"2024-01-0{i+1}",open=o,close=c) for i,(o,c) in enumerate([(1,10),(100,110),(120,125),(130,130)])]
stats,trades,_=study.simulate(rows,[True,False,False,False],[False,True,False,False],"2024-01-02","2024-01-04",cost=.0015)
assert trades[0]["entry"]=="2024-01-02"
assert trades[0]["exit"]=="2024-01-03"
assert abs(stats["return_pct"]-100*(120*.9985/(100*1.0015)-1))<1e-9
assert len(trades)==1 and not trades[0]["forced"]
_,trades,_=study.simulate(rows,[True,False,False,False],[False]*4,"2024-01-02","2024-01-04")
assert trades[-1]["forced"]
print("PASS: 8 strategies x 4 truncation checks; next-open fills; costs; forced liquidation.")
