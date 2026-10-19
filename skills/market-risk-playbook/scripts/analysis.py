"""
QQQ buy-point analysis: features, the "washout in uptrend" signal, its backtest and validation,
the option-chain read, and the forward projection. Pure numpy/pandas; no network.

Inputs (written by fetch_data.py):
  data/qqq_daily.csv, data/vol_daily.csv, data/options/qqq_chain_latest.csv.gz
"""
from __future__ import annotations

import datetime as dt
import itertools
import math
import os

import numpy as np
import pandas as pd

# ------------------------------------------------------------------------------------------
# Pre-registered signal (written down before the backtest; see references/signal-research.md)
# ------------------------------------------------------------------------------------------
RULE = dict(
    trend_ma=200,        # C1  adjusted close above its 200-day average
    high_win=63,         # C2  drawdown measured from the 63-session (~3-month) high ...
    dd_min=0.05,         #     ... at least 5%
    rsi2_max=5.0,        # C3  RSI(2) <= 5
    vrel_min=1.5,        # C4a opex-adjusted volume >= 1.5x the trailing 20-day median
    vxn_rel_min=0.10,    # C4b VXN >= 10% above its trailing 20-day mean
    cooldown=5,          # signals within 5 sessions of the previous one are the same event
)
STUDY_START = "2001-03-01"   # VXN starts 2001-01-23; leave room for the 20-day mean
GRID = dict(dd_min=[0.03, 0.04, 0.05, 0.06, 0.07], rsi2_max=[3, 5, 10],
            vrel_min=[1.25, 1.5, 2.0], vxn_rel_min=[0.05, 0.10, 0.20])
# dated macro events shown in the option section when they fall within the next 45 days
EVENTS = [("2026-10-28", "FOMC 议息决议"), ("2026-11-03", "美国中期选举"), ("2026-11-06", "10 月非农就业"),
          ("2026-12-09", "FOMC 议息决议")]
NYSE_HOLIDAYS = {"2026-11-26", "2026-12-25", "2027-01-01", "2027-01-18", "2027-02-15", "2027-03-26",
                 "2027-05-31", "2027-06-18", "2027-07-05", "2027-09-06", "2027-11-25", "2027-12-24"}


# ------------------------------------------------------------------------------------------
# Data and features
# ------------------------------------------------------------------------------------------
def load(data_dir: str) -> tuple[pd.DataFrame, bool]:
    q = pd.read_csv(os.path.join(data_dir, "qqq_daily.csv"), parse_dates=["date"], index_col="date")
    v = pd.read_csv(os.path.join(data_dir, "vol_daily.csv"), parse_dates=["date"], index_col="date")
    df = q.join(v[["vxn", "vix"]], how="left")
    vxn_stale = bool(pd.isna(df["vxn"].iloc[-1]))
    df["vxn"] = df["vxn"].ffill()
    return df, vxn_stale


def rsi(c: pd.Series, n: int) -> pd.Series:
    d = c.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + up / dn)


def is_monthly_opex(d: pd.Timestamp) -> bool:
    return d.weekday() == 4 and 15 <= d.day <= 21


def features(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    c = df["adj_close"]                       # dividend-adjusted: for returns and indicators
    df["rsi2"], df["rsi14"] = rsi(c, 2), rsi(c, 14)
    e12, e26 = c.ewm(span=12, adjust=False).mean(), c.ewm(span=26, adjust=False).mean()
    scale = df["close"] / c                   # draw indicators in displayed (split-adjusted) units
    df["macd"] = (e12 - e26) * scale
    df["macd_sig"] = (e12 - e26).ewm(span=9, adjust=False).mean() * scale
    df["macd_hist"] = df["macd"] - df["macd_sig"]
    df["ma50"], df["ma200"] = df["close"].rolling(50).mean(), df["close"].rolling(200).mean()
    df["up"] = c > c.rolling(RULE["trend_ma"]).mean()
    df["above_ma200"] = c / c.rolling(RULE["trend_ma"]).mean() - 1
    df["hi63"] = df["close"].rolling(RULE["high_win"]).max()
    df["dd"] = 1 - c / c.rolling(RULE["high_win"]).max()
    df["opex"] = [is_monthly_opex(d) for d in df.index]
    vr = df["volume"] / df["volume"].rolling(20).median().shift(1)
    ox_med = vr.where(df["opex"]).expanding().median().shift(1).ffill()
    df["vrel_raw"] = vr
    df["vrel"] = np.where(df["opex"], vr / ox_med, vr)   # opex days carry mechanical volume
    df["opex_norm"] = ox_med
    df["vxn_chg"] = df["vxn"] / df["vxn"].shift(1) - 1
    df["vxn_rel"] = df["vxn"] / df["vxn"].rolling(20).mean().shift(1) - 1
    df["rv20"] = np.log(c).diff().rolling(20).std() * math.sqrt(252) * 100
    df["vrp"] = df["vxn"] ** 2 - df["rv20"] ** 2
    df["ret1"] = c.pct_change()
    for h in (1, 5, 10, 20):
        df[f"f{h}"] = c.shift(-h) / c - 1
    fwd = pd.concat([c.shift(-k) for k in range(1, 21)], axis=1)
    df["mae20"] = fwd.min(axis=1) / c - 1
    df["mfe20"] = fwd.max(axis=1) / c - 1
    df.loc[fwd.isna().any(axis=1), ["mae20", "mfe20"]] = np.nan
    # washout intensity 0-100: mean of rolling 5-year percentile ranks of the four ingredients
    ranks = {}
    for k, x in (("oversold", -df["rsi2"]), ("volume", df["vrel"]), ("fear", df["vxn_rel"]), ("pullback", df["dd"])):
        ranks[k] = x.rolling(1260, min_periods=500).apply(lambda a: (a[:-1] < a[-1]).mean(), raw=True)
    df["score"] = pd.DataFrame(ranks).mean(axis=1) * 100
    return df


def conditions(S: pd.DataFrame, dd_min, rsi2_max, vrel_min, vxn_rel_min) -> dict:
    return {"C1": S["up"].values,
            "C2": (S["dd"] >= dd_min).values,
            "C3": (S["rsi2"] <= rsi2_max).values,
            "C4a": (S["vrel"] >= vrel_min).values,
            "C4b": (S["vxn_rel"] >= vxn_rel_min).values}


def events(mask: np.ndarray, cooldown: int = RULE["cooldown"]) -> np.ndarray:
    keep, last = [], -10 ** 9
    for i in np.flatnonzero(mask):
        if i - last > cooldown:
            keep.append(i)
            last = i
        # a signal inside the cooldown neither creates an event nor extends it
    return np.array(keep, dtype=int)


# ------------------------------------------------------------------------------------------
# Backtest and validation
# ------------------------------------------------------------------------------------------
def _t(x: np.ndarray) -> float:
    x = x[~np.isnan(x)]
    return float(x.mean() / (x.std(ddof=1) / math.sqrt(len(x)))) if len(x) > 2 else float("nan")


def backtest(df: pd.DataFrame, seed: int = 7, null_reps: int = 5000, family_reps: int = 200) -> dict:
    S = df[df.index >= STUDY_START]
    cond = conditions(S, RULE["dd_min"], RULE["rsi2_max"], RULE["vrel_min"], RULE["vxn_rel_min"])
    sig = cond["C1"] & cond["C2"] & cond["C3"] & cond["C4a"] & cond["C4b"]
    ev = events(sig)
    E = S.iloc[ev]
    done = E["f20"].notna().values
    Ed = E[done]
    base = S[S["f20"].notna()]
    pull = S[S["up"] & (S["dd"] >= RULE["dd_min"]) & S["f20"].notna()]
    rng = np.random.default_rng(seed)
    n = len(Ed)

    def summary(frame):
        return {h: {"mean": float(frame[h].mean()), "hit": float((frame[h] > 0).mean()),
                    "median": float(frame[h].median())} for h in ("f5", "f10", "f20")}

    def pval(pool: pd.DataFrame, h: str) -> float:
        vals = pool[h].values
        sims = np.array([vals[rng.choice(len(vals), n, replace=False)].mean() for _ in range(null_reps)])
        return float(np.mean(sims >= Ed[h].mean()))

    nulls = {}
    for name, pool in (("all", base), ("uptrend", base[base["up"]]), ("pullback", pull)):
        nulls[name] = {h: pval(pool, h) for h in ("f5", "f10", "f20")}
    excess_t = {h: _t((Ed[h] - base[h].mean()).values) for h in ("f5", "f10", "f20")}

    # robustness grid + family-wise null (forward returns circularly shifted)
    f5 = S["f5"].values
    base_f5 = np.nanmean(f5)
    masks = []
    for g in itertools.product(*GRID.values()):
        c = conditions(S, *g)
        masks.append(events(c["C1"] & c["C2"] & c["C3"] & c["C4a"] & c["C4b"]))

    def grid_t(series: np.ndarray):
        ts, ex = [], []
        for idx in masks:
            x = series[idx]
            x = x[~np.isnan(x)]
            if len(x) < 8:
                ts.append(np.nan); ex.append(np.nan); continue
            d = x - np.nanmean(series)
            ts.append(d.mean() / (d.std(ddof=1) / math.sqrt(len(d)))); ex.append(d.mean())
        return np.array(ts), np.array(ex)

    ts, ex = grid_t(f5)
    ok = ~np.isnan(ts)
    max_null, med_null = [], []
    for _ in range(family_reps):
        sh = rng.integers(250, len(f5) - 250)
        tt, _ = grid_t(np.roll(f5, sh))
        max_null.append(np.nanmax(tt)); med_null.append(np.nanmedian(tt))
    rule_cell = list(itertools.product(*GRID.values())).index(
        (RULE["dd_min"], RULE["rsi2_max"], RULE["vrel_min"], RULE["vxn_rel_min"]))

    # invalidation: close below the signal-day low within 5 sessions
    broke = []
    for i in ev:
        if i + 21 >= len(S):
            continue
        broke.append(bool((S["close"].iloc[i + 1:i + 6] < S["low"].iloc[i]).any()))
    broke = np.array(broke)
    f20d = Ed["f20"].values[:len(broke)]
    mae = Ed["mae20"].values[:len(broke)]

    # forward paths for the projection fan (completed events only, 20 sessions)
    c = S["adj_close"].values
    paths = np.array([c[i:i + 21] / c[i] for i in ev if i + 20 < len(S)])
    pidx = np.flatnonzero(S["up"].values & (S["dd"] >= RULE["dd_min"]).values)
    pidx = pidx[pidx + 20 < len(S)]
    pull_paths = np.array([c[i:i + 21] / c[i] for i in pidx])

    table = []
    for i in ev:
        r = S.iloc[i]
        table.append({"date": S.index[i].strftime("%Y-%m-%d"), "close": float(r["close"]), "dd": float(r["dd"]),
                      "rsi2": float(r["rsi2"]), "rsi14": float(r["rsi14"]), "vrel": float(r["vrel"]),
                      "vxn": float(r["vxn"]), "vxn_rel": float(r["vxn_rel"]),
                      "f5": None if pd.isna(r["f5"]) else float(r["f5"]),
                      "f10": None if pd.isna(r["f10"]) else float(r["f10"]),
                      "f20": None if pd.isna(r["f20"]) else float(r["f20"]),
                      "mae20": None if pd.isna(r["mae20"]) else float(r["mae20"])})
    return dict(
        n_events=int(len(ev)), n_done=n, sample_from=str(S.index[0].date()), n_days=int(len(base)),
        signal=summary(Ed), base=summary(base), pullback=summary(pull), uptrend=summary(base[base["up"]]),
        n_pullback_days=int(len(pull)), nulls=nulls, excess_t=excess_t,
        grid_cells=int(len(masks)), grid_usable=int(ok.sum()), grid_pos_share=float(np.mean(ex[ok] > 0)),
        grid_median_excess=float(np.nanmedian(ex)), grid_median_t=float(np.nanmedian(ts)),
        grid_max_t=float(np.nanmax(ts)), rule_cell_t=float(ts[rule_cell]),
        rule_cell_rank=int((ts[ok] > ts[rule_cell]).sum()) + 1,
        family_p_max=float(np.mean(np.array(max_null) >= np.nanmax(ts))),
        family_p_median=float(np.mean(np.array(med_null) >= np.nanmedian(ts))),
        family_max_95=float(np.percentile(max_null, 95)),
        broke_n=int(broke.sum()), held_n=int((~broke).sum()),
        broke_f20=float(np.mean(f20d[broke])) if broke.any() else None,
        held_f20=float(np.mean(f20d[~broke])) if (~broke).any() else None,
        broke_mae=float(np.median(mae[broke])) if broke.any() else None,
        worst=table[int(np.nanargmin([t["f20"] if t["f20"] is not None else np.nan for t in table]))],
        table=table, paths=paths, pull_paths=pull_paths, base_f5=float(base_f5),
        event_dates=[S.index[i] for i in ev],
    )


# ------------------------------------------------------------------------------------------
# Option chain
# ------------------------------------------------------------------------------------------
def _ncdf(x):
    return 0.5 * (1 + np.vectorize(math.erf)(np.asarray(x) / math.sqrt(2)))


def bs_price(S, K, T, sig, r, q, kind):
    d1 = (np.log(S / K) + (r - q + 0.5 * sig ** 2) * T) / (sig * np.sqrt(T))
    d2 = d1 - sig * np.sqrt(T)
    if kind == "C":
        return S * np.exp(-q * T) * _ncdf(d1) - K * np.exp(-r * T) * _ncdf(d2)
    return K * np.exp(-r * T) * _ncdf(-d2) - S * np.exp(-q * T) * _ncdf(-d1)


def implied_vol(price, S, K, T, r, q, kind):
    lo, hi = 0.01, 3.0
    intrinsic = max(0.0, (S - K) if kind == "C" else (K - S))
    if not (price > intrinsic * 0.999 and price > 0):
        return np.nan
    for _ in range(60):
        mid = 0.5 * (lo + hi)
        if bs_price(S, K, T, mid, r, q, kind) > price:
            hi = mid
        else:
            lo = mid
    return 0.5 * (lo + hi)


def options_read(chain_path: str, r: float = 0.04, q: float = 0.006) -> dict | None:
    if not os.path.exists(chain_path):
        return None
    oc = pd.read_csv(chain_path)
    asof = pd.Timestamp(oc["asof"].iloc[0])
    S = float(oc["spot"].iloc[0])
    oc["exp"] = pd.to_datetime(oc["expiry"])
    oc["days"] = (oc["exp"] - asof).dt.days
    oc = oc[oc["days"] >= 1].copy()                       # drop the contract expiring today
    oc["T"] = oc["days"] / 365.0
    oc["mid"] = np.where((oc["bid"] > 0) & (oc["ask"] > 0), (oc["bid"] + oc["ask"]) / 2, np.nan)
    otm = ((oc["kind"] == "C") & (oc["strike"] >= S)) | ((oc["kind"] == "P") & (oc["strike"] <= S))
    near = oc["strike"].between(S * 0.8, S * 1.2)
    sel = otm & near & oc["mid"].notna()
    oc["iv"] = np.nan
    oc.loc[sel, "iv"] = [implied_vol(m, S, k, t, r, q, kd) for m, k, t, kd in
                         oc.loc[sel, ["mid", "strike", "T", "kind"]].itertuples(index=False)]

    exps = sorted(oc["expiry"].unique())
    term = []
    for e in exps:
        x = oc[oc["expiry"] == e]
        T = float(x["T"].iloc[0])
        ks = x["strike"].unique()
        k0 = ks[np.argmin(np.abs(ks - S))]
        c = x[(x["kind"] == "C") & (x["strike"] == k0)]["mid"]
        p = x[(x["kind"] == "P") & (x["strike"] == k0)]["mid"]
        if c.empty or p.empty or c.isna().all() or p.isna().all():
            continue
        straddle = float(c.iloc[0] + p.iloc[0])
        atm_iv = straddle / (0.7979 * S * math.sqrt(T))        # straddle ~ 0.798 * S * sigma * sqrt(T)
        term.append({"expiry": e, "days": int(x["days"].iloc[0]), "T": T, "straddle": straddle,
                     "move_pct": straddle / S, "atm_iv": atm_iv, "sigma_move": S * atm_iv * math.sqrt(T),
                     "oi": int(x["openInterest"].sum())})

    # skew: 25-delta put vs call IV at the expiry nearest 30 days
    def skew_at(e):
        x = oc[(oc["expiry"] == e) & oc["iv"].notna()].copy()
        T = float(x["T"].iloc[0])
        d1 = (np.log(S / x["strike"]) + (r - q + 0.5 * x["iv"] ** 2) * T) / (x["iv"] * math.sqrt(T))
        x["delta"] = np.where(x["kind"] == "C", _ncdf(d1), _ncdf(d1) - 1)
        put = x[x["kind"] == "P"].iloc[(x[x["kind"] == "P"]["delta"] + 0.25).abs().argsort()[:1]]
        call = x[x["kind"] == "C"].iloc[(x[x["kind"] == "C"]["delta"] - 0.25).abs().argsort()[:1]]
        return float(put["iv"].iloc[0]), float(call["iv"].iloc[0]), float(put["strike"].iloc[0]), float(call["strike"].iloc[0])

    e30 = min(exps, key=lambda e: abs((pd.Timestamp(e) - asof).days - 30))
    p25, c25, kp25, kc25 = skew_at(e30)

    # put/call
    vol_c = int(oc[oc["kind"] == "C"]["volume"].sum()); vol_p = int(oc[oc["kind"] == "P"]["volume"].sum())
    oi_c = int(oc[oc["kind"] == "C"]["openInterest"].sum()); oi_p = int(oc[oc["kind"] == "P"]["openInterest"].sum())

    # walls and max pain for the next weekly and the next monthly
    def walls(e, band=0.06):
        x = oc[oc["expiry"] == e]
        calls = x[(x["kind"] == "C") & x["strike"].between(S, S * (1 + band))]
        puts = x[(x["kind"] == "P") & x["strike"].between(S * (1 - band), S)]
        ks = np.sort(x["strike"].unique())
        ks = ks[(ks > S * 0.85) & (ks < S * 1.15)]
        pain = [(x[x["kind"] == "C"].eval("openInterest * (@k - strike).clip(0)").sum()
                 + x[x["kind"] == "P"].eval("openInterest * (strike - @k).clip(0)").sum()) for k in ks]
        return {"expiry": e,
                "call_wall": float(calls.loc[calls["openInterest"].idxmax(), "strike"]) if len(calls) else None,
                "call_wall_oi": int(calls["openInterest"].max()) if len(calls) else 0,
                "put_wall": float(puts.loc[puts["openInterest"].idxmax(), "strike"]) if len(puts) else None,
                "put_wall_oi": int(puts["openInterest"].max()) if len(puts) else 0,
                "max_pain": float(ks[int(np.argmin(pain))]) if len(ks) else None}

    weekly = next(e for e in exps if pd.Timestamp(e).weekday() == 4)
    monthly = next(e for e in exps if is_monthly_opex(pd.Timestamp(e)))

    # gamma exposure (dealer long calls / short puts convention), expiries <= 35 days
    g = oc[(oc["days"] <= 35) & (oc["openInterest"] > 0) & oc["strike"].between(S * 0.85, S * 1.15)].copy()
    # IV for every strike: OTM IV of the same strike/expiry, else the expiry's ATM IV
    ivmap = oc.dropna(subset=["iv"]).groupby(["expiry", "strike"])["iv"].mean()
    atm = {t["expiry"]: t["atm_iv"] for t in term}
    g["s"] = [ivmap.get((e, k), atm.get(e, 0.2)) for e, k in g[["expiry", "strike"]].itertuples(index=False)]

    def gex(spot):
        d1 = (np.log(spot / g["strike"]) + 0.5 * g["s"] ** 2 * g["T"]) / (g["s"] * np.sqrt(g["T"]))
        gamma = np.exp(-0.5 * d1 ** 2) / math.sqrt(2 * math.pi) / (spot * g["s"] * np.sqrt(g["T"]))
        sign = np.where(g["kind"] == "C", 1.0, -1.0)
        return float((sign * gamma * g["openInterest"]).sum() * 100 * spot * spot * 0.01)

    grid = np.linspace(S * 0.93, S * 1.07, 141)
    gv = np.array([gex(s) for s in grid])
    cross = np.flatnonzero(np.sign(gv[:-1]) != np.sign(gv[1:]))
    flip = None
    if len(cross):
        i = cross[np.argmin(np.abs(grid[cross] - S))]
        flip = float(grid[i] - gv[i] * (grid[i + 1] - grid[i]) / (gv[i + 1] - gv[i]))

    # risk-neutral probabilities at the monthly expiry from the OTM price curve
    def prob_below(e, K):
        x = oc[(oc["expiry"] == e) & oc["mid"].notna()]
        T = float(x["T"].iloc[0])
        kind = "P" if K <= S else "C"
        y = x[x["kind"] == kind].sort_values("strike")
        if len(y) < 5:
            return None
        ks, px = y["strike"].values, y["mid"].values
        a = 2.5
        p_hi, p_lo = np.interp(K + a, ks, px), np.interp(K - a, ks, px)
        dP = (p_hi - p_lo) / (2 * a) * math.exp(r * T)     # put: dP/dK = P(S<K); call: -dC/dK = P(S>K)
        return float(dP) if kind == "P" else float(1 + dP)

    return dict(asof=str(asof.date()), spot=S, n_contracts=int(len(oc)), n_expiries=len(exps), term=term,
                skew_expiry=e30, put25_iv=p25, call25_iv=c25, put25_k=kp25, call25_k=kc25,
                pc_vol=vol_p / vol_c if vol_c else None, pc_oi=oi_p / oi_c if oi_c else None,
                vol_c=vol_c, vol_p=vol_p, oi_c=oi_c, oi_p=oi_p,
                weekly=walls(weekly), monthly=walls(monthly), flip=flip, gex_spot=gex(S),
                prob_below=lambda K, e=monthly: prob_below(e, K), monthly_expiry=monthly)


# ------------------------------------------------------------------------------------------
# Calendar helper
# ------------------------------------------------------------------------------------------
def next_sessions(last: pd.Timestamp, n: int) -> list[pd.Timestamp]:
    out, d = [], last
    while len(out) < n:
        d += pd.Timedelta(days=1)
        if d.weekday() < 5 and d.strftime("%Y-%m-%d") not in NYSE_HOLIDAYS:
            out.append(d)
    return out
