#!/usr/bin/env python3
"""
One-shot data refresh for the static reports (runs in GitHub Actions; Yahoo via yfinance).

Writes to data/refresh/:
  qqq_daily.csv            QQQ daily OHLCV 2017-01-01 -> latest (Close = split-adjusted, not dividend-adjusted)
  sp500_constituents.csv   current S&P 500 members (Wikipedia)
  caps.csv                 for every current member + every ticker that appeared in the reports:
                           close on key dates, Yahoo marketCap / shares, latest close
  closes.csv               daily Close (split-adjusted) for those tickers, 2025-11-01 -> latest
"""
from __future__ import annotations

import io
import json
import os
import sys
import time
import urllib.request

import pandas as pd
import yfinance as yf

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "data", "refresh")
EXTRA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tickers_extra.txt")


def yahoo(t: str) -> str:
    return t.replace(".", "-")


def main() -> None:
    os.makedirs(OUT, exist_ok=True)
    q = yf.Ticker("QQQ").history(start="2017-01-01", auto_adjust=False, actions=False)
    q.index = pd.to_datetime(q.index).tz_localize(None).normalize()
    q = q[["Open", "High", "Low", "Close", "Adj Close", "Volume"]].round(4)
    q.index.name = "date"
    q.to_csv(os.path.join(OUT, "qqq_daily.csv"))
    print("QQQ", q.index[-1].date(), q["Close"].iloc[-1])

    req = urllib.request.Request("https://en.wikipedia.org/wiki/List_of_S%26P_500_companies",
                                 headers={"User-Agent": "Mozilla/5.0 (stock_trading refresh)"})
    html = urllib.request.urlopen(req, timeout=60).read().decode("utf-8")
    cons = pd.read_html(io.StringIO(html))[0]
    cons = cons[["Symbol", "Security", "GICS Sector", "GICS Sub-Industry", "Date added"]]
    cons.to_csv(os.path.join(OUT, "sp500_constituents.csv"), index=False)
    print("constituents", len(cons))

    extra = [x.strip() for x in open(EXTRA).read().split() if x.strip()] if os.path.exists(EXTRA) else []
    tickers = sorted(set(cons["Symbol"].tolist()) | set(extra))
    ysyms = [yahoo(t) for t in tickers]

    hist = yf.download(ysyms, start="2025-11-01", auto_adjust=False, actions=False, progress=False,
                       group_by="column", threads=True)
    closes = hist["Close"].copy()
    closes.index = pd.to_datetime(closes.index).tz_localize(None).normalize()
    closes.columns = [c.replace("-", ".") if c.replace("-", ".") in tickers else c for c in closes.columns]
    closes.round(4).to_csv(os.path.join(OUT, "closes.csv"), index_label="date")
    print("closes", closes.shape, closes.index[-1].date())

    rows = []
    for t in tickers:
        info = {}
        for attempt in range(3):
            try:
                info = yf.Ticker(yahoo(t)).info or {}
                break
            except Exception as e:  # pragma: no cover
                print(f"[warn] {t}: {e}", file=sys.stderr)
                time.sleep(2)
        rows.append({"ticker": t,
                     "marketCap": info.get("marketCap"),
                     "sharesOutstanding": info.get("sharesOutstanding"),
                     "impliedSharesOutstanding": info.get("impliedSharesOutstanding"),
                     "regularMarketPrice": info.get("regularMarketPrice"),
                     "previousClose": info.get("previousClose"),
                     "currency": info.get("currency"),
                     "quoteType": info.get("quoteType"),
                     "shortName": info.get("shortName")})
        time.sleep(0.15)
    caps = pd.DataFrame(rows)
    caps.to_csv(os.path.join(OUT, "caps.csv"), index=False)
    print("caps", len(caps), int(caps["marketCap"].notna().sum()), "with marketCap")
    json.dump({"qqq_last": str(q.index[-1].date()), "closes_last": str(closes.index[-1].date()),
               "n_constituents": int(len(cons)), "n_tickers": len(tickers)},
              open(os.path.join(OUT, "meta.json"), "w"), indent=1)


if __name__ == "__main__":
    main()
