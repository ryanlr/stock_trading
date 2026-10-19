#!/usr/bin/env python3
"""
Download everything the QQQ playbook needs from Yahoo Finance and cache it in the repo.

  data/qqq_daily.csv         QQQ daily OHLCV (split-adjusted Close + dividend-adjusted Adj Close), 1999→
  data/vol_daily.csv         ^VXN (Nasdaq-100 implied vol), ^VIX, ^NDX daily closes
  data/options/qqq_chain_YYYY-MM-DD.csv.gz
                             full QQQ option-chain snapshot (expiries <= 70 days) taken after the close;
                             one file per session, kept so option signals can be backtested later
  data/options/qqq_chain_latest.csv.gz   copy of the newest snapshot

Run after the US close. Requires yfinance, pandas.
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import shutil
import sys
import time
from zoneinfo import ZoneInfo

import pandas as pd
import yfinance as yf

ET = ZoneInfo("America/New_York")


def daily(symbol: str, start: str) -> pd.DataFrame:
    h = yf.Ticker(symbol).history(start=start, auto_adjust=False, actions=False)
    if h.empty:
        raise RuntimeError(f"no data for {symbol}")
    h.index = pd.to_datetime(h.index).tz_localize(None).normalize()
    h.index.name = "date"
    return h


def chain(symbol: str, max_days: int) -> pd.DataFrame:
    tk = yf.Ticker(symbol)
    today = dt.datetime.now(ET).date()
    out = []
    for exp in tk.options:
        d = (dt.date.fromisoformat(exp) - today).days
        if d < 0 or d > max_days:
            continue
        for attempt in range(3):
            try:
                ch = tk.option_chain(exp)
                break
            except Exception as e:  # pragma: no cover
                print(f"[warn] {exp}: {e}", file=sys.stderr)
                time.sleep(2)
        else:
            continue
        for kind, tab in (("C", ch.calls), ("P", ch.puts)):
            t = tab[["contractSymbol", "strike", "lastPrice", "bid", "ask", "volume",
                     "openInterest", "impliedVolatility", "lastTradeDate"]].copy()
            t.insert(0, "kind", kind)
            t.insert(0, "expiry", exp)
            out.append(t)
        time.sleep(0.3)
    if not out:
        raise RuntimeError("empty option chain")
    df = pd.concat(out, ignore_index=True)
    df["volume"] = df["volume"].fillna(0).astype(int)
    df["openInterest"] = df["openInterest"].fillna(0).astype(int)
    return df


def main() -> None:
    here = os.path.dirname(os.path.abspath(__file__))
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default=os.path.join(here, "..", "data"))
    ap.add_argument("--symbol", default="QQQ")
    ap.add_argument("--max-days", type=int, default=70)
    a = ap.parse_args()
    os.makedirs(os.path.join(a.data_dir, "options"), exist_ok=True)

    q = daily(a.symbol, "1999-03-01")
    q = q[["Open", "High", "Low", "Close", "Adj Close", "Volume"]].round(4)
    q.columns = ["open", "high", "low", "close", "adj_close", "volume"]
    q.to_csv(os.path.join(a.data_dir, f"{a.symbol.lower()}_daily.csv"))

    vols = {}
    for sym, col in (("^VXN", "vxn"), ("^VIX", "vix"), ("^NDX", "ndx")):
        try:
            vols[col] = daily(sym, "1999-01-01")["Close"]
        except Exception as e:  # pragma: no cover
            print(f"[warn] {sym}: {e}", file=sys.stderr)
    pd.DataFrame(vols).round(4).rename_axis("date").to_csv(os.path.join(a.data_dir, "vol_daily.csv"))

    last = q.index[-1].date()
    try:
        oc = chain(a.symbol, a.max_days)
        oc.insert(0, "spot", float(q["close"].iloc[-1]))
        oc.insert(0, "asof", str(last))
        p = os.path.join(a.data_dir, "options", f"{a.symbol.lower()}_chain_{last}.csv.gz")
        oc.to_csv(p, index=False, compression="gzip")
        shutil.copyfile(p, os.path.join(a.data_dir, "options", f"{a.symbol.lower()}_chain_latest.csv.gz"))
        print(f"chain: {len(oc)} contracts, {oc.expiry.nunique()} expiries")
    except Exception as e:  # pragma: no cover
        print(f"[warn] option chain failed: {e}", file=sys.stderr)
    print(f"{a.symbol}: {len(q)} sessions through {last}; vol cols {list(vols)}")


if __name__ == "__main__":
    main()
