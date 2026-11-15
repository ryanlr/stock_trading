#!/usr/bin/env python3
"""Fetch Fed funds target (DFEDTAR to 2008, DFEDTARU upper bound after) and 10-year yield (DGS10) from FRED.
Writes data/rates/fed_target.csv and data/rates/dgs10.csv. Runs in GitHub Actions."""
import io, os, urllib.request
import pandas as pd
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "data", "rates")
def fred(sid):
    req = urllib.request.Request(f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}&cosd=1998-01-01",
                                 headers={"User-Agent": "Mozilla/5.0"})
    df = pd.read_csv(io.StringIO(urllib.request.urlopen(req, timeout=60).read().decode()))
    df.columns = ["date", "value"]
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    return df.dropna()
os.makedirs(OUT, exist_ok=True)
a, b = fred("DFEDTAR"), fred("DFEDTARU")
t = pd.concat([a, b[b["date"] > a["date"].max()]]).reset_index(drop=True)
t.to_csv(os.path.join(OUT, "fed_target.csv"), index=False)
fred("DGS10").to_csv(os.path.join(OUT, "dgs10.csv"), index=False)
print(t.tail(3))
