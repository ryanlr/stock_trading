#!/usr/bin/env python3
"""
Market Risk Playbook (Chinese) generator.

Re-implements the method behind https://balder-ai.com/playbook from public data:
  * index daily closes (^GSPC by default)      -> drawdown state, comparable positions, 20-session outcomes
  * volatility index daily closes (^VIX)       -> next-session range, variance-risk-premium signal
  * index option chain open interest (^SPX)    -> call wall / put wall / gamma flip (optional)

Usage:
  python build_playbook.py --out prediction.html --cache-dir ../data
  python build_playbook.py --offline --cache-dir ../data          # use cached CSV only
  python build_playbook.py --asof 2026-10-16                       # rebuild as of a past session

Only numpy + pandas are required for the analysis; yfinance (or plain HTTPS to Yahoo's
chart API as a fallback) is used to download data.
"""
from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import math
import os
import sys
import urllib.request
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

ET = ZoneInfo("America/New_York")

# --------------------------------------------------------------------------------------
# Parameters (documented in SKILL.md / references/methodology.md)
# --------------------------------------------------------------------------------------
HORIZON = 20                 # sessions ahead for every probability
HIGH_WINDOW = 252            # "recent high" = highest close of the last 252 sessions
STAT_START = "2005-01-01"    # comparable positions are drawn from this date onward
DD_BANDS = [0.0, 0.02, 0.05, 0.10, 0.20, 1.0]   # drawdown bands used to define "comparable"
KEY_LEVELS = [0.02, 0.05, 0.10, 0.20, 0.30]      # candidate key supports (below the high)
NOTCHES = [0.05, 0.10, 0.20, 0.30, 0.40]         # "one notch lower" boundaries for the four paths
BAND_LOOKBACK = 252          # sessions used to calibrate the realised/implied ratio
EDGE_PP = 0.05               # a probability must differ from its base rate by >= 5pp to be shown
MIN_N = 100                  # minimum comparable positions to publish a probability


# --------------------------------------------------------------------------------------
# Data
# --------------------------------------------------------------------------------------
def _yahoo_chart(symbol: str, start: str) -> pd.Series:
    """Fallback downloader: Yahoo chart API over plain HTTPS."""
    p1 = int(pd.Timestamp(start, tz="UTC").timestamp())
    p2 = int(dt.datetime.now(dt.timezone.utc).timestamp()) + 86400
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.request.quote(symbol)}"
           f"?period1={p1}&period2={p2}&interval=1d&includeAdjustedClose=false")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        js = json.load(r)
    res = js["chart"]["result"][0]
    tz = res["meta"].get("exchangeTimezoneName", "America/New_York")
    idx = pd.to_datetime(res["timestamp"], unit="s", utc=True).tz_convert(tz).normalize().tz_localize(None)
    close = res["indicators"]["quote"][0]["close"]
    return pd.Series(close, index=idx, dtype="float64").dropna()


def download(symbol: str, start: str = "1990-01-01") -> pd.Series:
    try:
        import yfinance as yf  # noqa: WPS433
        h = yf.Ticker(symbol).history(start=start, auto_adjust=False, actions=False)
        if h.empty:
            raise RuntimeError("empty")
        s = h["Close"].copy()
        s.index = pd.to_datetime(s.index).tz_localize(None).normalize()
        return s.dropna()
    except Exception as e:  # pragma: no cover - network dependent
        print(f"[warn] yfinance failed for {symbol}: {e}; trying chart API", file=sys.stderr)
        return _yahoo_chart(symbol, start)


def load_prices(index_sym: str, vol_sym: str, cache_dir: str, offline: bool) -> pd.DataFrame:
    os.makedirs(cache_dir, exist_ok=True)
    path = os.path.join(cache_dir, f"{index_sym.strip('^').lower()}_{vol_sym.strip('^').lower()}_daily.csv")
    df = None
    if not offline:
        try:
            px = download(index_sym)
            vx = download(vol_sym)
            df = pd.DataFrame({"close": px, "vix": vx}).dropna()
            df.index.name = "date"
            df.round(4).to_csv(path)
        except Exception as e:  # pragma: no cover
            print(f"[warn] download failed: {e}", file=sys.stderr)
    if df is None:
        if not os.path.exists(path):
            sys.exit(f"no data: download failed and no cache at {path}")
        df = pd.read_csv(path, parse_dates=["date"], index_col="date")
    return df.sort_index()


def option_structure(spot: float, symbol: str = "^SPX", max_days: int = 35, flat_iv: float = 0.18,
                     proxy: str = "SPY") -> dict | None:
    """Option structure from `symbol`; if its chain is thin, from `proxy` scaled to the index."""
    res = _option_structure(spot, symbol, 1.0, max_days, flat_iv)
    if res and res["rows"] >= 200 and res["call_wall"] and res["put_wall"]:
        res["source"] = symbol
        return res
    if not proxy:
        return res
    try:
        import yfinance as yf  # noqa: WPS433
        px = float(yf.Ticker(proxy).history(period="5d")["Close"].dropna().iloc[-1])
        scale = spot / px
    except Exception as e:  # pragma: no cover
        print(f"[warn] proxy price unavailable: {e}", file=sys.stderr)
        return res
    alt = _option_structure(spot, proxy, scale, max_days, flat_iv)
    if alt:
        alt["source"] = proxy
        alt["scale"] = scale
    return alt or res


def _option_structure(spot: float, symbol: str, scale: float, max_days: int, flat_iv: float) -> dict | None:
    """Call wall, put wall and gamma flip from a listed option chain (open interest).
    Strikes are multiplied by `scale` (1 for the index itself, index/ETF price for a proxy)."""
    try:
        import yfinance as yf  # noqa: WPS433
        tk = yf.Ticker(symbol)
        today = dt.datetime.now(ET).date()
        rows = []
        for exp in tk.options:
            d = (dt.date.fromisoformat(exp) - today).days
            if d < 0 or d > max_days:
                continue
            ch = tk.option_chain(exp)
            for kind, tab in (("C", ch.calls), ("P", ch.puts)):
                t = tab[["strike", "openInterest", "impliedVolatility"]].copy()
                t["kind"], t["days"] = kind, max(d, 0.5)
                rows.append(t)
        if not rows:
            return None
        oc = pd.concat(rows)
        oc["strike"] = oc["strike"] * scale
        oc = oc[oc.openInterest.fillna(0) > 0]
        oc = oc[oc.strike.between(spot * 0.85, spot * 1.15)].copy()
        if oc.empty:
            return None
        # Yahoo's IVs for index options are often junk outside market hours (~0 or blank).
        # Keep every row with open interest; replace an unusable IV with the vol-index level.
        bad = ~oc.impliedVolatility.between(0.05, 2.0)
        oc.loc[bad, "impliedVolatility"] = flat_iv
        iv_fallback_share = float(bad.mean())

        def gex(s: float) -> float:
            t = oc.days.values / 365.0
            iv = oc.impliedVolatility.values
            k = oc.strike.values
            d1 = (np.log(s / k) + 0.5 * iv ** 2 * t) / (iv * np.sqrt(t))
            g = np.exp(-0.5 * d1 ** 2) / np.sqrt(2 * np.pi) / (s * iv * np.sqrt(t))
            sign = np.where(oc.kind.values == "C", 1.0, -1.0)
            return float(np.sum(sign * g * oc.openInterest.values) * 100 * s * s * 0.01)

        grid = np.linspace(spot * 0.92, spot * 1.08, 161)
        vals = np.array([gex(s) for s in grid])
        flip = None
        cross = np.where(np.sign(vals[:-1]) != np.sign(vals[1:]))[0]
        if len(cross):
            i = cross[np.argmin(np.abs(grid[cross] - spot))]
            x0, x1, y0, y1 = grid[i], grid[i + 1], vals[i], vals[i + 1]
            flip = float(x0 - y0 * (x1 - x0) / (y1 - y0))
        by = oc.groupby(["kind", "strike"]).openInterest.sum()
        calls = by.loc["C"]
        puts = by.loc["P"]
        # walls = the largest open interest *near* price (within 4%), not the far round-number strikes
        cw = calls[(calls.index >= spot) & (calls.index <= spot * 1.04)]
        pw = puts[(puts.index <= spot) & (puts.index >= spot * 0.96)]
        call_wall = float(cw.idxmax()) if len(cw) else None
        put_wall = float(pw.idxmax()) if len(pw) else None
        return {"call_wall": call_wall, "put_wall": put_wall, "flip": flip,
                "gex_spot": gex(spot), "expiries": int(oc.days.nunique()), "rows": int(len(oc)),
                "iv_fallback_share": iv_fallback_share}
    except Exception as e:  # pragma: no cover
        print(f"[warn] option chain unavailable: {e}", file=sys.stderr)
        return None


# --------------------------------------------------------------------------------------
# Analysis
# --------------------------------------------------------------------------------------
def band_of(dd: float) -> int:
    for i in range(len(DD_BANDS) - 1):
        if DD_BANDS[i] <= dd < DD_BANDS[i + 1]:
            return i
    return len(DD_BANDS) - 2


def next_below(dd: float, levels: list[float]) -> float:
    for lv in levels:
        if lv > dd + 1e-9:
            return lv
    return levels[-1]


def compute(df: pd.DataFrame) -> dict:
    c = df["close"].values
    n = len(c)
    high = df["close"].rolling(HIGH_WINDOW, min_periods=60).max().values
    dd = 1 - c / high                                  # drawdown from recent high, >= 0

    # forward-window outcomes (NaN where the window is incomplete)
    fmin = np.full(n, np.nan)
    fmax = np.full(n, np.nan)
    for i in range(n - HORIZON):
        w = c[i + 1:i + 1 + HORIZON]
        fmin[i], fmax[i] = w.min(), w.max()
    deepest = 1 - np.minimum(fmin, c) / high           # deepest drawdown incl. today, vs today's high
    regain = fmax >= high
    up2 = fmax >= c * 1.02
    dn2 = fmin <= c * 0.98
    fwd_ret = np.full(n, np.nan)
    fwd_ret[:n - HORIZON] = c[HORIZON:] / c[:n - HORIZON] - 1

    dates = df.index
    valid = (dates >= pd.Timestamp(STAT_START)) & ~np.isnan(fmin) & ~np.isnan(high)

    # ---------------- today ----------------
    t = n - 1
    P, H, D = c[t], high[t], dd[t]
    b = band_of(D)
    key = next_below(D, KEY_LEVELS)
    notch = next_below(D, NOTCHES)
    notch2 = NOTCHES[min(NOTCHES.index(notch) + 1, len(NOTCHES) - 1)]

    bands = np.array([band_of(x) if not np.isnan(x) else -1 for x in dd])
    comp = valid & (bands == b)
    m = int(comp.sum())

    def p(mask_outcome, base_mask=comp):
        sel = base_mask & ~np.isnan(fmin)
        return float(np.mean(mask_outcome[sel])) if sel.any() else float("nan")

    hold_key = p(deepest < key)
    no_deeper = p(deepest < notch)
    p_regain = p(regain)
    p_up2, base_up2 = p(up2), p(up2, valid)
    p_dn2, base_dn2 = p(dn2), p(dn2, valid)
    base_regain = p(regain, valid)

    pathA = comp & regain & (deepest < notch)
    pathB = comp & ~regain & (deepest < notch)
    pathC = comp & (deepest >= notch) & (deepest < notch2)
    pathD = comp & (deepest >= notch2)
    paths = []
    for name, mk, depth in (
        (f"回到高点，且不跌破 −{notch:.0%}", pathA, True),
        (f"横盘震荡，不跌破 −{notch:.0%}、也回不到高点", pathB, False),
        (f"再下一个台阶（−{notch:.0%} 至 −{notch2:.0%}）", pathC, True),
        (f"更深（跌破 −{notch2:.0%}）", pathD, True),
    ):
        k = int(mk.sum())
        paths.append({"name": name, "prob": k / m if m else float("nan"), "n": k,
                      "deepest": float(np.median(deepest[mk])) if (k and depth) else None})

    # fan of forward paths applied to today's price
    idx = np.where(comp)[0]
    rel = np.stack([c[i:i + HORIZON + 1] / c[i] for i in idx]) if len(idx) else np.ones((1, HORIZON + 1))
    fan = {q: (np.percentile(rel, q, axis=0) * P).tolist() for q in (5, 25, 50, 75, 95)}

    # ---------------- next-session range (implied vol x realised/implied ratio) ----------------
    vix = df["vix"].values
    r = np.r_[np.nan, np.log(c[1:] / c[:-1])]
    sig = np.r_[np.nan, vix[:-1] / 100 / math.sqrt(252)]   # implied 1-day sigma known the night before
    ratio = pd.Series(np.abs(r) / sig)
    k50 = ratio.rolling(BAND_LOOKBACK, min_periods=200).median().shift(1).values   # strictly prior
    k80 = ratio.rolling(BAND_LOOKBACK, min_periods=200).quantile(0.8).shift(1).values
    inside50 = np.abs(r) <= k50 * sig
    inside80 = np.abs(r) <= k80 * sig
    oos = ~np.isnan(k50) & (dates >= pd.Timestamp("2006-01-01"))
    cov50, cov80 = float(np.mean(inside50[oos])), float(np.mean(inside80[oos]))
    full_ratio_median = float(np.nanmedian(ratio[dates >= pd.Timestamp(STAT_START)]))

    k50_next = float(ratio.iloc[-BAND_LOOKBACK:].median())
    k80_next = float(ratio.iloc[-BAND_LOOKBACK:].quantile(0.8))
    sig_next = vix[t] / 100 / math.sqrt(252)
    rng50 = (P * math.exp(-k50_next * sig_next), P * math.exp(k50_next * sig_next))
    rng80 = (P * math.exp(-k80_next * sig_next), P * math.exp(k80_next * sig_next))

    ledger = []
    for i in range(n - 1, max(n - 21, 0), -1):
        if np.isnan(k50[i]):
            continue
        lo50, hi50 = c[i - 1] * math.exp(-k50[i] * sig[i]), c[i - 1] * math.exp(k50[i] * sig[i])
        lo80, hi80 = c[i - 1] * math.exp(-k80[i] * sig[i]), c[i - 1] * math.exp(k80[i] * sig[i])
        ledger.append({"date": dates[i].strftime("%Y-%m-%d"), "lo50": lo50, "hi50": hi50,
                       "lo80": lo80, "hi80": hi80, "close": c[i],
                       "in50": bool(inside50[i]), "in80": bool(inside80[i])})
    led_cov50 = float(np.mean([x["in50"] for x in ledger])) if ledger else float("nan")

    # ---------------- drawdown recovery table (evidence #5) ----------------
    recov = []
    for i in range(len(DD_BANDS) - 1):
        mk = valid & (bands == i)
        if mk.sum() == 0:
            continue
        recov.append({"band": (DD_BANDS[i], DD_BANDS[i + 1]), "n": int(mk.sum()),
                      "regain": float(np.mean(regain[mk])), "current": i == b})

    # ---------------- variance risk premium (evidence #6) ----------------
    rv20 = pd.Series(r).rolling(20).std().values * math.sqrt(252)
    vrp = (vix / 100) ** 2 - rv20 ** 2
    nonov = np.where(valid & ~np.isnan(vrp) & ~np.isnan(fwd_ret))[0][::HORIZON]
    vv, rr = vrp[nonov], fwd_ret[nonov]
    qs = np.quantile(vv, [0.2, 0.4, 0.6, 0.8])
    quint = np.searchsorted(qs, vv)
    q_means = [float(np.mean(rr[quint == q])) for q in range(5)]
    top, rest = rr[quint == 4], rr[quint != 4]
    t_top = float((top.mean() - rest.mean()) / math.sqrt(top.var(ddof=1) / len(top) + rest.var(ddof=1) / len(rest)))
    today_q = int(np.searchsorted(qs, vrp[t])) if not np.isnan(vrp[t]) else None

    # overlap illustration (evidence #3)
    n_daily = int(valid.sum())

    # ---------------- what we leave out ----------------
    left_out, shown = [], {}
    for label, pv, bv in (("再涨 2%", p_up2, base_up2), ("再跌 2%", p_dn2, base_dn2)):
        if m < MIN_N:
            left_out.append(f"“{label}”的概率：可比样本只有 {m} 个，低于 {MIN_N} 的发布门槛")
        elif abs(pv - bv) < EDGE_PP:
            left_out.append(f"“20 个交易日内{label}”的概率（{pv:.0%}，常态 {bv:.0%}）：与基准差距不足 5 个百分点，"
                            f"不足以据此行动")
        else:
            shown[label] = (pv, bv)

    return dict(
        date=dates[t], P=P, H=H, D=D, band=(DD_BANDS[b], DD_BANDS[b + 1]), key=key, notch=notch, notch2=notch2,
        m=m, hold_key=hold_key, no_deeper=no_deeper, p_regain=p_regain, base_regain=base_regain,
        p_up2=p_up2, base_up2=base_up2, p_dn2=p_dn2, base_dn2=base_dn2, shown=shown, left_out=left_out,
        paths=paths, fan=fan, vix=vix[t], rng50=rng50, rng80=rng80, k50=k50_next, k80=k80_next,
        cov50=cov50, cov80=cov80, full_ratio_median=full_ratio_median, ledger=ledger, led_cov50=led_cov50,
        recov=recov, vrp_q_means=q_means, vrp_top=float(top.mean()), vrp_base=float(rr.mean()),
        vrp_t=t_top, vrp_n_top=int(len(top)), vrp_n=int(len(rr)), vrp_today_q=today_q,
        vrp_today=float(vrp[t]) if not np.isnan(vrp[t]) else None,
        n_daily=n_daily, n_indep=n_daily // HORIZON, n_obs_total=len(df), first_date=dates[0],
    )


# --------------------------------------------------------------------------------------
# Rendering
# --------------------------------------------------------------------------------------
def f0(x):
    return f"{x:,.0f}"


def pct(x, d=0):
    return f"{x * 100:.{d}f}%"


def fan_svg(res: dict) -> str:
    W, Hh, L, R, T, B = 720, 300, 58, 92, 16, 34
    fan = res["fan"]
    lines = {"高点": res["H"], f"关键支撑 −{res['key']:.0%}": res["H"] * (1 - res["key"]),
             f"−{res['notch']:.0%}": res["H"] * (1 - res["notch"])}
    if res["notch2"] != res["notch"]:
        lines[f"−{res['notch2']:.0%}"] = res["H"] * (1 - res["notch2"])
    lo = min(min(fan[5]), res["H"] * (1 - res["notch"])) * 0.995
    hi = max(max(fan[95]), res["H"]) * 1.005
    X = lambda i: L + (W - L - R) * i / HORIZON  # noqa: E731
    Y = lambda v: T + (Hh - T - B) * (hi - v) / (hi - lo)  # noqa: E731

    def area(a, b_):
        pts = [f"{X(i):.1f},{Y(v):.1f}" for i, v in enumerate(fan[a])]
        pts += [f"{X(i):.1f},{Y(v):.1f}" for i, v in reversed(list(enumerate(fan[b_])))]
        return " ".join(pts)

    out = [f'<svg viewBox="0 0 {W} {Hh}" role="img" aria-label="未来20个交易日的历史路径分布" '
           f'style="width:100%;height:auto;display:block">']
    for gv in np.linspace(lo, hi, 5):
        out.append(f'<line x1="{L}" x2="{W - R}" y1="{Y(gv):.1f}" y2="{Y(gv):.1f}" stroke="var(--grid)"/>'
                   f'<text x="{L - 6}" y="{Y(gv) + 4:.1f}" text-anchor="end" class="ax">{gv:,.0f}</text>')
    out.append(f'<polygon points="{area(5, 95)}" fill="var(--blue)" fill-opacity=".12"/>')
    out.append(f'<polygon points="{area(25, 75)}" fill="var(--blue)" fill-opacity=".22"/>')
    med = " ".join(f"{X(i):.1f},{Y(v):.1f}" for i, v in enumerate(fan[50]))
    out.append(f'<polyline points="{med}" fill="none" stroke="var(--blue)" stroke-width="2.2"/>')
    for name, v in lines.items():
        if lo <= v <= hi:
            col = "var(--ink)" if name == "高点" else ("var(--amber)" if "关键" in name else "var(--red)")
            out.append(f'<line x1="{L}" x2="{W - R}" y1="{Y(v):.1f}" y2="{Y(v):.1f}" stroke="{col}" '
                       f'stroke-dasharray="5 4" stroke-width="1.2"/>'
                       f'<text x="{W - R + 6}" y="{Y(v) + 4:.1f}" class="lb" fill="{col}">{html.escape(name)}</text>')
    out.append(f'<circle cx="{X(0):.1f}" cy="{Y(res["P"]):.1f}" r="4" fill="var(--ink)"/>')
    for i in (0, 5, 10, 15, 20):
        out.append(f'<text x="{X(i):.1f}" y="{Hh - 12}" text-anchor="middle" class="ax">'
                   f'{"今日" if i == 0 else f"+{i}"}</text>')
    out.append("</svg>")
    return "".join(out)


CSS = """
:root{--paper:#F5F7FA;--sheet:#FFFFFF;--ink:#0F2240;--text:#1C2B3D;--muted:#5B6875;--rule:#D9E0E7;--grid:#EBEFF4;
--blue:#1B86B8;--amber:#D9840F;--red:#C0392B;--green:#1E8449;--link:#1E3A5F;
--display:"Noto Serif SC","Songti SC",serif;--body:"Noto Sans SC","PingFang SC","Microsoft YaHei",system-ui,sans-serif;
--mono:"JetBrains Mono",ui-monospace,Menlo,monospace;color-scheme:light}
*,*::before,*::after{box-sizing:border-box}
body{margin:0;background:var(--paper);color:var(--text);font-family:var(--body);font-size:15.5px;line-height:1.7}
a{color:var(--link)}
.wrap{max-width:980px;margin:0 auto;padding-inline:16px}
.bar{border-bottom:1px solid var(--rule);background:var(--sheet)}
.bar .wrap{display:flex;justify-content:space-between;align-items:center;gap:12px;padding-block:12px;font-size:14px}
.bar a{text-decoration:none;color:var(--muted)}.bar a.home{color:var(--ink);font-weight:700}
header.hero{padding-block:32px 8px}
.kicker{font-family:var(--mono);font-size:12px;letter-spacing:.08em;color:var(--blue)}
h1{font-family:var(--display);font-weight:900;color:var(--ink);font-size:clamp(28px,4.4vw,42px);line-height:1.2;margin:.25em 0 .4em}
h2{font-family:var(--display);font-weight:600;font-size:23px;color:var(--ink);margin:0 0 10px;border-bottom:2px solid var(--ink);padding-bottom:6px}
h3{font-size:16.5px;color:var(--ink);margin:18px 0 4px}
.lede{font-size:17px;max-width:70ch;margin:0}
.lede b{color:var(--ink)}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:1px;background:var(--rule);border:1px solid var(--rule);margin:22px 0 6px}
.tiles div{background:var(--sheet);padding:12px 14px;display:flex;flex-direction:column;gap:2px;min-width:0}
.tiles b{font-family:var(--mono);font-size:22px;font-weight:600;color:var(--ink);font-variant-numeric:tabular-nums}
.tiles span{font-size:12.5px;color:var(--muted)}
section{background:var(--sheet);border:1px solid var(--rule);padding:20px 20px 16px;margin:18px 0}
.note{font-size:13px;color:var(--muted)}
.tbl{width:100%;overflow-x:auto}
table{width:100%;border-collapse:collapse;font-size:14.5px}
th,td{padding:7px 8px;border-bottom:1px solid var(--grid);text-align:left;vertical-align:top}
th{font-size:12.5px;color:var(--muted);font-weight:500}
td.n{font-family:var(--mono);text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
tr.cur td{background:#FFF7E8}
.ok{color:var(--green)}.mid{color:var(--amber)}.miss{color:var(--red)}
.ax{font:11px var(--mono);fill:var(--muted)}.lb{font:11.5px var(--body)}
.legend{display:flex;flex-wrap:wrap;gap:4px 16px;font-size:12.5px;color:var(--muted);margin-top:4px}
.legend i{display:inline-block;width:14px;height:8px;margin-right:5px;vertical-align:middle}
ol.ev{padding-left:1.3em;margin:0}ol.ev li{margin-bottom:14px}
.ev .so{display:block;font-size:14px;color:var(--ink);background:#F2F7FB;border-left:3px solid var(--blue);padding:4px 10px;margin-top:4px}
.tag{font-size:11.5px;border-radius:3px;padding:1px 6px;margin-left:6px;vertical-align:2px}
.tag.own{background:#E6F2F8;color:#14608A}.tag.cite{background:#F3ECE0;color:#7A5410}
footer{padding-block:18px 40px;font-size:12.5px;color:var(--muted)}
@media (max-width:560px){section{padding:16px 14px}th,td{padding:6px 5px}}
"""


def render(res: dict, opt: dict | None, intraday: bool, index_name: str, ga: str | None) -> str:
    e = html.escape
    d = res["date"].strftime("%Y-%m-%d")
    P, H = res["P"], res["H"]
    keylv = H * (1 - res["key"])
    notchlv = H * (1 - res["notch"])
    notch2lv = H * (1 - res["notch2"])
    lo50, hi50 = res["rng50"]
    lo80, hi80 = res["rng80"]

    # headline sentence
    comp_word = ""
    up_lo = res["p_up2"] < res["base_up2"]
    dn_lo = res["p_dn2"] < res["base_dn2"]
    if up_lo and dn_lo:
        comp_word = "上下两个方向的空间都比平常小——典型的“双向收窄”。"
    elif up_lo and not dn_lo:
        comp_word = "上行空间比平常小、下行风险比平常大——偏向防守。"
    elif not up_lo and dn_lo:
        comp_word = "上行空间比平常大、下行风险比平常小——偏向进攻。"
    else:
        comp_word = "上下两个方向的波动都比平常大——风险与机会同时放大。"
    lede = (f"标普500 现报 <b>{f0(P)}</b>，比近一年高点 {f0(H)} 低 <b>{res['D']:.2%}</b>。"
            f"历史上处在同一回撤区间（{res['band'][0]:.0%}–{res['band'][1]:.0%}）的 {res['m']:,} 个交易日里，"
            f"未来 20 个交易日有 <b>{pct(res['no_deeper'])}</b> 没有跌破 −{res['notch']:.0%}，"
            f"<b>{pct(res['p_regain'])}</b> 重新站上高点（全部交易日的常态是 {pct(res['base_regain'])}）；"
            f"再涨 2% 的概率 {pct(res['p_up2'])}（常态 {pct(res['base_up2'])}），"
            f"再跌 2% 的概率 {pct(res['p_dn2'])}（常态 {pct(res['base_dn2'])}）。{comp_word}"
            f"所有概率都来自历史条件频率，而不是观点。")

    paths_rows = "".join(
        f"<tr><td>{e(pth['name'])}</td><td class='n'><b>{pct(pth['prob'])}</b></td>"
        f"<td class='n'>{('−' + pct(pth['deepest'], 1)) if pth['deepest'] is not None else '—'}</td>"
        f"<td class='n'>{pth['n']:,}</td></tr>" for pth in res["paths"])

    if opt:
        positive = (P > opt["flip"]) if opt["flip"] else (opt["gex_spot"] > 0)
        regime = "正 gamma：做市商对冲会抑制波动" if positive else "负 gamma：做市商对冲会放大波动"
        src = ("SPX 期权链" if opt.get("source", "^SPX") == "^SPX" else
               f"{opt['source']} 期权链（SPX 期权链数据不足，按 SPX/{opt['source']} 价格比 {opt.get('scale', 1):.2f} 折算成 SPX 点位）")
        opt_html = f"""
<section aria-labelledby="s-opt"><h2 id="s-opt">今日期权结构（第二个视角）</h2>
<p>前面问的是“未来 20 个交易日会怎样”；这里看的是期权未平仓量把哪些价位压在当前价格附近。
状态：<b>{e(regime)}</b>。</p>
<div class="tbl"><table>
<tr><td>看涨墙（现价上方看涨期权未平仓量最大的行权价，常起阻力作用）</td><td class="n"><b>{f0(opt['call_wall']) if opt['call_wall'] else '—'}</b></td></tr>
<tr><td>Gamma 翻转点（高于此做市商抑制波动，低于此放大波动）</td><td class="n"><b>{f0(opt['flip']) if opt['flip'] else '—'}</b></td></tr>
<tr><td>看跌墙（现价下方看跌期权未平仓量最大的行权价，常起支撑作用）</td><td class="n"><b>{f0(opt['put_wall']) if opt['put_wall'] else '—'}</b></td></tr>
</table></div>
<p class="note">数据：{e(src)}（Yahoo Finance），35 天内的 {opt['expiries']} 个到期日，未平仓量为交易所上一交易日公布值；
gamma 用 Black-Scholes 由隐含波动率估算（{opt['iv_fallback_share']:.0%} 的合约因报价隐含波动率不可用而改用 VIX 水平），并假设做市商持有看涨多头、看跌空头的常用惯例——这是近似，不是做市商真实持仓。</p>
</section>"""
    else:
        opt_html = """
<section aria-labelledby="s-opt"><h2 id="s-opt">今日期权结构</h2>
<p class="note">本次运行没有取到可用的 SPX 期权链，期权墙与 gamma 翻转点暂缺。宁可空着，也不填一个估出来的数。</p></section>"""

    led_rows = "".join(
        f"<tr><td>{x['date']}</td><td class='n'>{f0(x['lo50'])} – {f0(x['hi50'])}</td>"
        f"<td class='n'>{f0(x['lo80'])} – {f0(x['hi80'])}</td><td class='n'><b>{x['close']:,.2f}</b></td>"
        f"<td class='{'ok' if x['in50'] else ('mid' if x['in80'] else 'miss')}'>{'50%区间内' if x['in50'] else ('仅80%区间内' if x['in80'] else '两个区间外')}</td></tr>"
        for x in res["ledger"])

    recov_rows = "".join(
        f"<tr class='{'cur' if r_['current'] else ''}'><td>距高点 {r_['band'][0]:.0%} – "
        f"{'以上' if r_['band'][1] >= 1 else format(r_['band'][1], '.0%')}{'（当前）' if r_['current'] else ''}</td>"
        f"<td class='n'>{r_['n']:,}</td><td class='n'><b>{pct(r_['regain'])}</b></td></tr>" for r_ in res["recov"])

    vq = res["vrp_today_q"]
    vrp_line = (f"今天的方差风险溢价落在第 <b>{vq + 1}</b> 档（1 最低、5 最高）。"
                + ("<b>处于最高一档——按原研究，这是唯一会说“可以加仓”的条件。</b>" if vq == 4
                   else "不在最高一档，所以今天没有“加仓”信号。")
                + (f"需要说明：本站复算的 t = {res['vrp_t']:.2f}，弱于原研究的 2.70，未达常用的 2 的门槛——方向一致，但证据只能算倾向，不是定论。"
                   if res["vrp_t"] < 2 else "")) if vq is not None else ""

    left = "".join(f"<li>{e(x)}</li>" for x in res["left_out"]) or "<li>今天所有计算出的概率都通过了自身门槛。</li>"
    state = "盘中（今日收盘未定）" if intraday else "收盘后"
    ga_tag = (f'<script async src="https://www.googletagmanager.com/gtag/js?id={ga}"></script>'
              f"<script>window.dataLayer=window.dataLayer||[];function gtag(){{dataLayer.push(arguments);}}"
              f"gtag('js',new Date());gtag('config','{ga}');</script>") if ga else ""

    return f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
{ga_tag}
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>标普500 风险手册 · 老王看美股</title>
<meta name="description" content="每日更新：标普500 下一交易日的可能区间、关键支撑，以及历史上类似位置之后 20 个交易日的四种走法。概率来自历史，不是观点。">
<meta property="og:title" content="标普500 风险手册：还能继续持有吗？">
<meta property="og:description" content="{e(d)}：现报 {f0(P)}，距近一年高点 {res['D']:.2%}；不跌破 −{res['notch']:.0%} 的历史概率 {pct(res['no_deeper'])}。">
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Noto+Serif+SC:wght@600;900&family=Noto+Sans+SC:wght@400;500;700&family=JetBrains+Mono:wght@400;600&display=swap">
<style>{CSS}</style></head>
<body>
<div class="bar"><div class="wrap"><a class="home" href="./">← 老王看美股</a><a href="https://heylaowang.com/ai/">老王看AI</a></div></div>
<main class="wrap">
<header class="hero">
<div class="kicker">每日 · {e(d)} · {state} · {e(index_name)}</div>
<h1>还能继续持有，还是该离场？</h1>
<p class="lede">{lede}</p>
<div class="tiles">
<div><b>{f0(P)}</b><span>标普500 · {e(d)} {"现价" if intraday else "收盘"}</span></div>
<div><b>{f0(lo50)}–{f0(hi50)}</b><span>下一交易日 50% 区间（±{(hi50 / P - 1):.2%}）</span></div>
<div><b>{f0(keylv)}</b><span>关键支撑（高点下方 {res['key']:.0%}）· 守住概率 {pct(res['hold_key'])}</span></div>
<div><b>{pct(res['no_deeper'])}</b><span>20 日内不跌破 −{res['notch']:.0%}（{f0(notchlv)}）</span></div>
</div>
</header>

<section aria-labelledby="s-paths"><h2 id="s-paths">未来 20 个交易日的四种走法</h2>
<div class="tbl"><table><tr><th>走法</th><th style="text-align:right">概率</th><th style="text-align:right">期间最深回撤（中位）</th><th style="text-align:right">样本</th></tr>
{paths_rows}</table></div>
<h3>历史路径套用到今天的价格</h3>
{fan_svg(res)}
<div class="legend"><span><i style="background:var(--blue);opacity:.25"></i>25%–75% 的路径</span><span><i style="background:var(--blue);opacity:.12"></i>5%–95%</span><span><i style="background:var(--blue);height:3px"></i>中位路径</span><span>虚线：高点、关键支撑、下一台阶</span></div>
<p class="note">把 {res['m']:,} 个可比交易日之后 20 天的涨跌幅，原样乘到今天的 {f0(P)} 上。这不是预测某一条路，而是“像今天这样的位置，过去都走成了什么样”。</p>
</section>

<section aria-labelledby="s-lv"><h2 id="s-lv">要盯的价位</h2>
<div class="tbl"><table>
<tr><td>近一年高点（只有回到这里，才算转势）</td><td class="n"><b>{f0(H)}</b></td></tr>
<tr><td>关键支撑（跌破就掉一个台阶）· 20 日内守住的历史概率 {pct(res['hold_key'])}</td><td class="n"><b>{f0(keylv)}</b></td></tr>
<tr><td>下一台阶 −{res['notch']:.0%}</td><td class="n">{f0(notchlv)}</td></tr>
<tr><td>再下一台阶 −{res['notch2']:.0%}</td><td class="n">{f0(notch2lv)}</td></tr>
<tr><td>下一交易日 80% 区间（更宽、更保守）</td><td class="n">{f0(lo80)} – {f0(hi80)}</td></tr>
</table></div>
<p class="note">VIX 收于 {res['vix']:.2f}。区间 = 前收盘 × exp(± k × VIX 隐含的单日波动)，k 取过去 252 个交易日“实际波动 / 隐含波动”的中位数（今天 k = {res['k50']:.2f}），80% 区间用 80 分位（{res['k80']:.2f}）。</p>
</section>
{opt_html}
<section aria-labelledby="s-led"><h2 id="s-led">区间账本：每天都记，错了也记</h2>
<p>2006 年以来逐日样本外检验：50% 区间实际覆盖 <b>{pct(res['cov50'], 1)}</b>，80% 区间覆盖 <b>{pct(res['cov80'], 1)}</b>。
最近 {len(res['ledger'])} 个交易日 50% 区间命中 {pct(res['led_cov50'])}。一个从不出错的区间不是本事，只是废话。</p>
<div class="tbl"><table><tr><th>交易日</th><th style="text-align:right">50% 区间</th><th style="text-align:right">80% 区间</th><th style="text-align:right">收盘</th><th>结果</th></tr>
{led_rows}</table></div>
<p class="note">每一行的区间只用到前一天收盘为止的数据。</p>
</section>

<section aria-labelledby="s-ev"><h2 id="s-ev">方法与证据</h2>
<p class="note">标 <span class="tag own">本站复算</span> 的数字由本页脚本用 Yahoo Finance 日线重新计算；标 <span class="tag cite">引用</span> 的结论来自 Balder 的研究（需要分钟级数据，本站未复算），用自己的话转述。</p>
<ol class="ev">
<li><b>不预测具体点位：价格近似鞅</b><span class="tag cite">引用</span><br>
Balder 用十种平滑方法（各种均线、VWAP、开盘价、昨收）去猜当日收盘，越平滑越差，最好的估计就是当前价格本身——这与 Samuelson（1965）的结论一致。
<span class="so">对你意味着：给你一个精确收盘点位的人，要么在猜，要么在卖东西。我们只给区间。</span></li>
<li><b>区间为什么只有约 0.6 个“隐含标准差”，而不是教科书的 1.96</b><span class="tag own">本站复算</span><br>
隐含波动率系统性高于实际波动（方差风险溢价，相当于市场为保险付的钱）。{STAT_START[:4]} 年以来，标普500 单日实际涨跌幅（绝对值）的中位数只有 VIX 隐含单日波动的 <b>{res['full_ratio_median']:.2f} 倍</b>。按 ±1.96 画区间几乎永远不会错，所以也不含信息；这个比例随波动环境漂移，因此每天用最近 252 天重新校准，样本外覆盖率 {pct(res['cov50'], 1)}——一半对、一半错，这正是 50% 区间该有的样子。
<span class="so">对你意味着：问一个区间“它错过没有”。</span></li>
<li><b>只看 20 天，不报 60 天</b><span class="tag own">本站复算</span><br>
用日线算 60 天远期收益，相邻两个样本共享 59 天。{STAT_START[:4]} 年以来 {res['n_daily']:,} 个“样本”，在 20 天视野下真正独立的只有约 <b>{res['n_indep']:,}</b> 个；拉到 60 天只剩约 {res['n_daily'] // 60:,} 个，t 值会被放大约 √60 ≈ 7.7 倍。这就是 Hansen-Hodrick 与 Newey-West 要处理的重叠样本问题。
<span class="so">对你意味着：看到漂亮的长周期 t 值，先问重叠怎么处理的。</span></li>
<li><b>扔掉的比留下的多</b><span class="tag cite">引用</span><br>
扫一批指标、报告最好的那个，搜索本身就会制造赢家。Balder 的做法是把收益序列分块打乱、重跑整个搜索，看纯噪声能把最优 t 值推多高；他们测试的波动率指标族，真实最优 t = 5.67，噪声中位数也是 5.67，整族被删掉。本页的“今日略去”就是同一原则。
<span class="so">对你意味着：“测了 50 个指标，这个最好”本身就是警示标签。</span></li>
<li><b>回撤不会很快均值回归</b><span class="tag own">本站复算</span><br>
{STAT_START[:4]} 年以来，按距近一年高点的回撤分组，20 个交易日内重新站上高点的比例：
<div class="tbl"><table><tr><th>回撤区间</th><th style="text-align:right">交易日数</th><th style="text-align:right">20 日内回到高点</th></tr>{recov_rows}</table></div>
<span class="so">对你意味着：回撤越深，越难在一个月内收复。深度带有惯性，不是弹簧；−5% 是减仓的位置，不是抄底的位置。</span></li>
<li><b>唯一让我们说“加仓”的信号：方差风险溢价</b><span class="tag own">本站复算</span><br>
Bollerslev、Tauchen 与 Zhou（Review of Financial Studies, 2009）发现，隐含方差减实际方差能预测未来股票收益，而且胜过市盈率、股息率和期限利差。本站用 VIX² 减 20 日实际方差，在不重叠的 20 日窗口上（{res['vrp_n']} 个样本）分五档：最高一档之后 20 日平均涨 <b>{pct(res['vrp_top'], 2)}</b>，全部窗口平均 {pct(res['vrp_base'], 2)}；最高档对其余四档的 t = {res['vrp_t']:.2f}（最高档 {res['vrp_n_top']} 个独立样本）。五档依次为 {" / ".join(pct(x, 2) for x in res['vrp_q_means'])}。{vrp_line}
<span class="so">对你意味着：市场越愿意为保险付钱，之后的收益往往越好。恐惧是燃料。</span></li>
<li><b>最后：能预测的部分很少</b><span class="tag cite">引用</span><br>
Balder 把能拿到的输入（隐含波动、多周期实际波动、早盘波动、平值跨式价格）全部放进去，对当日剩余时段的解释力 R² 只有约 0.11，近九成不可预测。
<span class="so">对你意味着：所以这里只谈概率和价位，不谈目标价和方向。</span></li>
</ol></section>

<section aria-labelledby="s-left"><h2 id="s-left">今日略去</h2>
<p>每天算出来的东西里，有些没过自己的门槛——太宽没有信息量、离基准太近不值得行动、或者样本太少。它们被删掉，并列在这里。只展示命中的产品，你无从判断它什么时候在凑数。</p>
<ul>{left}</ul></section>

<footer>
<p><b>数据</b>：标普500（^GSPC）与 VIX（^VIX）日收盘，Yahoo Finance，{res['first_date']:%Y} 年起，共 {res['n_obs_total']:,} 个交易日；可比样本取 {STAT_START[:4]} 年之后。“近一年高点”= 过去 252 个交易日最高收盘价。每个交易日美东收盘后自动更新。</p>
<p><b>方法来源</b>：本页复刻自 <a href="https://balder-ai.com/playbook" rel="noopener">Balder 的 Market Risk Playbook</a> 的思路，用公开数据独立实现，数值与原页不会完全一致。生成脚本与说明见 <a href="https://github.com/ryanlr/stock_trading/tree/main/skills/market-risk-playbook">GitHub</a>。</p>
<p>研究记录，不构成投资建议。概率是历史上可比位置的条件频率，不是对未来的保证。</p>
</footer>
</main></body></html>
"""


def main() -> None:
    here = os.path.dirname(os.path.abspath(__file__))
    ap = argparse.ArgumentParser()
    ap.add_argument("--index", default="^GSPC")
    ap.add_argument("--vol", default="^VIX")
    ap.add_argument("--options", default="^SPX", help="option-chain symbol; '' to skip")
    ap.add_argument("--name", default="S&P 500")
    ap.add_argument("--out", default="prediction.html")
    ap.add_argument("--cache-dir", default=os.path.join(here, "..", "data"))
    ap.add_argument("--offline", action="store_true")
    ap.add_argument("--asof", default=None, help="YYYY-MM-DD: truncate data to this session")
    ap.add_argument("--ga", default="G-2G0J05CN16", help="Google Analytics id ('' to omit)")
    ap.add_argument("--json", default=None, help="also dump the computed numbers here")
    a = ap.parse_args()

    df = load_prices(a.index, a.vol, a.cache_dir, a.offline)
    if a.asof:
        df = df[df.index <= pd.Timestamp(a.asof)]
    now = dt.datetime.now(ET)
    intraday = (a.asof is None and df.index[-1].date() == now.date()
                and now.weekday() < 5 and (now.hour, now.minute) < (16, 15))
    res = compute(df)
    opt = option_structure(res["P"], a.options, flat_iv=float(res["vix"]) / 100) if (a.options and not a.asof and not a.offline) else None
    page = render(res, opt, intraday, a.name, a.ga or None)
    with open(a.out, "w", encoding="utf-8") as fh:
        fh.write(page)
    if a.json:
        dump = {k: v for k, v in res.items() if k not in ("fan",)}
        dump["date"] = str(res["date"].date())
        dump["first_date"] = str(res["first_date"].date())
        dump["options"] = opt
        with open(a.json, "w", encoding="utf-8") as fh:
            json.dump(dump, fh, ensure_ascii=False, indent=1, default=float)
    print(f"wrote {a.out}: {res['date'].date()} close {res['P']:.2f}, dd {res['D']:.2%}, "
          f"comparable n={res['m']}, no-deeper {res['no_deeper']:.0%}, regain {res['p_regain']:.0%}, "
          f"range50 {res['rng50'][0]:.0f}-{res['rng50'][1]:.0f}, options={'yes' if opt else 'no'}")


if __name__ == "__main__":
    main()
