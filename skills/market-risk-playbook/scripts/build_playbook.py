#!/usr/bin/env python3
"""
QQQ 买点雷达 (prediction.html) — render the QQQ buy-point report from cached data.

  python fetch_data.py                       # Yahoo: QQQ OHLCV, VXN/VIX, QQQ option chain
  python build_playbook.py --out prediction.html

All analysis lives in analysis.py; this file only lays out the page and the charts.
"""
from __future__ import annotations

import argparse
import html
import json
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import analysis as A  # noqa: E402

UP, DN = "#D64545", "#1E9E6A"          # 红涨绿跌
GOLD, BLUE, AMBER, PURPLE, GREY = "#C98A0B", "#1B86B8", "#D9840F", "#7B4FB5", "#8A96A3"
F = 24                                    # future sessions drawn on the chart (through the monthly expiry)
WEEK = "一二三四五六日"


def esc(x) -> str:
    return html.escape(str(x))


def pct(x, d=1, sign=False) -> str:
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return "—"
    return f"{x * 100:+.{d}f}%" if sign else f"{x * 100:.{d}f}%"


def num(x, d=2) -> str:
    return "—" if x is None else f"{x:,.{d}f}"


def md(ts) -> str:
    ts = pd.Timestamp(ts)
    return f"{ts.month}月{ts.day}日"


# ------------------------------------------------------------------------------------------
# Main chart
# ------------------------------------------------------------------------------------------
def main_chart(win: pd.DataFrame, fut: list, bt: dict, opt: dict | None, marks: list, misses: list,
               anchor: pd.Timestamp | None) -> str:
    W, L, R = 1000, 58, 104
    panels = [("price", 340), ("vol", 86), ("rsi", 86), ("macd", 86), ("score", 70)]
    gap, top = 16, 12
    ys, y = {}, top
    for name, h in panels:
        ys[name] = (y, y + h)
        y += h + gap
    H = y + 18
    n_w = len(win)
    N = n_w + F
    slot = (W - L - R) / N
    X = lambda i: L + slot * (i + 0.5)  # noqa: E731
    dates = list(win.index) + list(fut)
    pos = {d: i for i, d in enumerate(dates)}
    last_i = n_w - 1
    P = float(win["close"].iloc[-1])

    fan = None
    if anchor is not None and anchor in pos and len(bt["paths"]):
        a_i = pos[anchor]
        a_px = float(win.loc[anchor, "close"])
        q = {p: np.percentile(bt["paths"], p, axis=0) * a_px for p in (10, 25, 50, 75, 90)}
        null_med = np.median(bt["pull_paths"], axis=0) * a_px
        fan = (a_i, q, null_med)
        fan_end = dates[min(a_i + len(q[50]) - 1, len(dates) - 1)]
    cone = []
    if opt:
        for t in opt["term"]:
            d = pd.Timestamp(t["expiry"])
            if d in pos and pos[d] > last_i:
                cone.append((pos[d], t["sigma_move"]))
    lo = float(win["low"].min())
    hi = float(win["high"].max())
    if fan:
        lo, hi = min(lo, fan[1][10].min()), max(hi, fan[1][90].max())
    for i, s in cone:
        lo, hi = min(lo, P - s), max(hi, P + s)
    if opt and opt["monthly"]["call_wall"]:
        hi = max(hi, opt["monthly"]["call_wall"])
    pad = (hi - lo) * 0.04
    lo, hi = lo - pad, hi + pad
    py0, py1 = ys["price"]
    Y = lambda v: py1 - (py1 - py0) * (v - lo) / (hi - lo)  # noqa: E731

    o = [f'<svg viewBox="0 0 {W} {H}" class="chart big" role="img" aria-label="QQQ 近五个月日线、成交量、RSI、MACD 与买点标注，以及未来走势投影">']
    o.append(f'<defs><clipPath id="pc"><rect x="{L}" y="{py0}" width="{W - R - L}" height="{py1 - py0}"/></clipPath></defs>')
    o.append(f'<rect x="{X(last_i) + slot / 2:.1f}" y="{py0}" width="{W - R - X(last_i) - slot / 2:.1f}" '
             f'height="{ys["score"][1] - py0}" fill="#F3F6FA"/>')
    o.append(f'<text x="{X(last_i) + slot:.1f}" y="{py1 - 6}" class="tag">投影 →</text>')
    prev_m = None
    for i, d in enumerate(dates):
        if d.month != prev_m:
            o.append(f'<line x1="{X(i) - slot / 2:.1f}" x2="{X(i) - slot / 2:.1f}" y1="{py0}" y2="{ys["score"][1]}" stroke="var(--grid)"/>'
                     f'<text x="{X(i) - slot / 2 + 3:.1f}" y="{H - 4}" class="ax">{d.month}月</text>')
            prev_m = d.month
    for v in np.linspace(lo + pad, hi - pad, 6):
        o.append(f'<line x1="{L}" x2="{W - R}" y1="{Y(v):.1f}" y2="{Y(v):.1f}" stroke="var(--grid)" stroke-dasharray="2 3"/>'
                 f'<text x="{L - 6}" y="{Y(v) + 4:.1f}" text-anchor="end" class="ax">{v:.0f}</text>')
    for col, colr, lab in (("ma50", "#6C7A89", "50日均线"), ("ma200", "#2E3E50", "200日均线")):
        pts = " ".join(f"{X(i):.1f},{Y(v):.1f}" for i, v in enumerate(win[col].values) if not np.isnan(v))
        o.append(f'<polyline clip-path="url(#pc)" points="{pts}" fill="none" stroke="{colr}" stroke-width="1.1" stroke-dasharray="{"4 3" if col == "ma200" else "none"}" opacity=".75"/>')
        v_end = float(win[col].iloc[-1])
        if v_end < lo:
            o.append(f'<text x="{X(last_i) - 4:.1f}" y="{py1 - 6}" text-anchor="end" class="lb" fill="{colr}">{lab} {v_end:.0f}（在图下方）↓</text>')
        else:
            o.append(f'<text x="{X(last_i) - 70:.1f}" y="{Y(v_end) + 14:.1f}" class="lb" fill="{colr}">{lab}</text>')
    if cone:
        cone = sorted(cone)
        up1 = [(last_i, P)] + [(i, P + s) for i, s in cone]
        dn1 = [(last_i, P)] + [(i, P - s) for i, s in cone]
        up5 = [(last_i, P)] + [(i, P + 0.674 * s) for i, s in cone]
        dn5 = [(last_i, P)] + [(i, P - 0.674 * s) for i, s in cone]
        poly = " ".join(f"{X(i):.1f},{Y(v):.1f}" for i, v in up5 + dn5[::-1])
        o.append(f'<polygon clip-path="url(#pc)" points="{poly}" fill="{AMBER}" fill-opacity=".13"/>')
        for seq in (up1, dn1):
            o.append(f'<polyline points="{" ".join(f"{X(i):.1f},{Y(v):.1f}" for i, v in seq)}" fill="none" stroke="{AMBER}" stroke-width="1.4" stroke-dasharray="5 3"/>')
        i_end, s_end = cone[-1]
        o.append(f'<text x="{X(i_end) + 4:.1f}" y="{Y(P + s_end) + 4:.1f}" class="lb" fill="{AMBER}">+1σ {P + s_end:.0f}</text>'
                 f'<text x="{X(i_end) + 4:.1f}" y="{Y(P - s_end) + 4:.1f}" class="lb" fill="{AMBER}">−1σ {P - s_end:.0f}</text>')
    if fan:
        a_i, q, null_med = fan
        xs = [X(a_i + k) for k in range(len(q[50]))]
        poly = " ".join(f"{x:.1f},{Y(v):.1f}" for x, v in zip(xs, q[90])) + " " + \
               " ".join(f"{x:.1f},{Y(v):.1f}" for x, v in zip(xs[::-1], q[10][::-1]))
        o.append(f'<polygon points="{poly}" fill="{BLUE}" fill-opacity=".10"/>')
        poly = " ".join(f"{x:.1f},{Y(v):.1f}" for x, v in zip(xs, q[75])) + " " + \
               " ".join(f"{x:.1f},{Y(v):.1f}" for x, v in zip(xs[::-1], q[25][::-1]))
        o.append(f'<polygon points="{poly}" fill="{BLUE}" fill-opacity=".18"/>')
        o.append(f'<polyline points="{" ".join(f"{x:.1f},{Y(v):.1f}" for x, v in zip(xs, q[50]))}" fill="none" stroke="{BLUE}" stroke-width="2"/>')
        o.append(f'<polyline points="{" ".join(f"{x:.1f},{Y(v):.1f}" for x, v in zip(xs, null_med))}" fill="none" stroke="{GREY}" stroke-width="1.3" stroke-dasharray="2 3"/>')
        o.append(f'<text x="{xs[-1]:.1f}" y="{Y(q[50][-1]) - 9:.1f}" text-anchor="end" class="lb" fill="{BLUE}">历史中位 {q[50][-1]:.0f}（{fan_end:%m-%d}）</text>')
    if opt:
        x0, x1 = X(last_i) + slot / 2, W - R
        lv = []
        if opt["monthly"]["call_wall"]:
            lv.append((opt["monthly"]["call_wall"], f"看涨墙 {opt['monthly']['call_wall']:.0f}", UP, "6 3"))
        if opt["flip"]:
            lv.append((opt["flip"], f"Gamma翻转 {opt['flip']:.0f}", PURPLE, "2 3"))
        if opt["monthly"]["put_wall"]:
            lv.append((opt["monthly"]["put_wall"], f"看跌墙 {opt['monthly']['put_wall']:.0f}", DN, "6 3"))
        for v, lab, colr, da in lv:
            if lo < v < hi:
                o.append(f'<line x1="{x0:.1f}" x2="{x1:.1f}" y1="{Y(v):.1f}" y2="{Y(v):.1f}" stroke="{colr}" stroke-dasharray="{da}" stroke-width="1.1"/>'
                         f'<text x="{x1 + 4:.1f}" y="{Y(v) + 4:.1f}" class="lb" fill="{colr}">{esc(lab)}</text>')
    if anchor is not None and anchor in pos:
        lowv = float(win.loc[anchor, "low"])
        o.append(f'<line x1="{X(pos[anchor]):.1f}" x2="{W - R:.1f}" y1="{Y(lowv):.1f}" y2="{Y(lowv):.1f}" stroke="#B03A2E" stroke-width="1" stroke-dasharray="1 2"/>'
                 f'<text x="{X(pos[anchor]) + 30:.1f}" y="{Y(lowv) + 13:.1f}" class="lb" fill="#B03A2E">失效参考 {lowv:.2f}</text>')
    for i, (d, r) in enumerate(win.iterrows()):
        colr = UP if r["close"] >= r["open"] else DN
        x = X(i)
        tip = (f"{d:%Y-%m-%d} 周{WEEK[d.weekday()]}\n开 {r['open']:.2f} 高 {r['high']:.2f} 低 {r['low']:.2f} 收 {r['close']:.2f}"
               f"（{r['ret1'] * 100:+.2f}%）\n成交量 {r['volume'] / 1e6:.1f}M（{r['vrel']:.2f}× 常态）\n"
               f"RSI2 {r['rsi2']:.1f} · RSI14 {r['rsi14']:.1f} · VXN {r['vxn']:.2f} · 出清分 {r['score']:.0f}")
        bt_, bb = Y(max(r["open"], r["close"])), Y(min(r["open"], r["close"]))
        o.append(f'<g><title>{esc(tip)}</title><rect x="{x - slot / 2:.1f}" y="{py0}" width="{slot:.1f}" height="{py1 - py0}" fill="transparent"/>'
                 f'<line x1="{x:.1f}" x2="{x:.1f}" y1="{Y(r["high"]):.1f}" y2="{Y(r["low"]):.1f}" stroke="{colr}"/>'
                 f'<rect x="{x - slot * 0.32:.1f}" y="{bt_:.1f}" width="{slot * 0.64:.1f}" height="{max(bb - bt_, 0.8):.1f}" fill="{colr}"/></g>')
    for k, m in enumerate(marks, 1):
        i = pos[m["date"]]
        yv = Y(win.loc[m["date"], "low"]) + 8
        o.append(f'<path d="M{X(i):.1f},{yv:.1f} l-7,13 h14 z" fill="{GOLD}" stroke="#fff" stroke-width="1"/>'
                 f'<text x="{X(i):.1f}" y="{yv + 26:.1f}" text-anchor="middle" class="mk">{k}</text>')
    for k, m in enumerate(misses):
        i = pos[m["date"]]
        yv = Y(win.loc[m["date"], "high"]) - 10
        o.append(f'<circle cx="{X(i):.1f}" cy="{yv:.1f}" r="4.5" fill="#fff" stroke="{GREY}" stroke-width="1.6"/>'
                 f'<text x="{X(i):.1f}" y="{yv - 8:.1f}" text-anchor="middle" class="ms">{chr(97 + k)}</text>')
    o.append(f'<circle cx="{X(last_i):.1f}" cy="{Y(P):.1f}" r="3.5" fill="var(--ink)"/>'
             f'<text x="{X(last_i) + 6:.1f}" y="{Y(P) + 4:.1f}" class="lb" fill="var(--ink)" font-weight="700">{P:.2f}</text>')

    v0, v1 = ys["vol"]
    vmax = float(win["volume"].max()) * 1.12
    VY = lambda v: v1 - (v1 - v0) * v / vmax  # noqa: E731
    o.append(f'<text x="{L}" y="{v0 - 3}" class="pt">成交量（百万股）· 虚线 = 20 日中位数的 1.5 倍 · 金色数字 = 扣除期权到期效应后的放量倍数</text>')
    for i, (d, r) in enumerate(win.iterrows()):
        colr = UP if r["close"] >= r["open"] else DN
        o.append(f'<rect x="{X(i) - slot * 0.34:.1f}" y="{VY(r["volume"]):.1f}" width="{slot * 0.68:.1f}" height="{v1 - VY(r["volume"]):.1f}" fill="{colr}" opacity=".55"/>')
        if r["opex"]:
            o.append(f'<text x="{X(i):.1f}" y="{v1 + 10:.1f}" text-anchor="middle" class="ox">OPEX</text>')
    med = win["volume"].rolling(20).median().shift(1) * 1.5
    pts = " ".join(f"{X(i):.1f},{VY(v):.1f}" for i, v in enumerate(med.values) if not np.isnan(v))
    o.append(f'<polyline points="{pts}" fill="none" stroke="{GOLD}" stroke-width="1" stroke-dasharray="3 2"/>')
    for m in marks:
        i = pos[m["date"]]
        o.append(f'<text x="{X(i):.1f}" y="{VY(win.loc[m["date"], "volume"]) - 3:.1f}" text-anchor="middle" class="vk">{win.loc[m["date"], "vrel"]:.2f}×</text>')
    o.append(f'<text x="{L - 6}" y="{v0 + 8}" text-anchor="end" class="ax">{vmax / 1e6:.0f}</text>')

    r0, r1 = ys["rsi"]
    RY = lambda v: r1 - (r1 - r0) * v / 100  # noqa: E731
    o.append(f'<text x="{L}" y="{r0 - 3}" class="pt">RSI(14) 蓝线 · RSI(2) 灰线（红色虚线 5 = 极度超卖）</text>')
    for lv in (70, 30, 5):
        o.append(f'<line x1="{L}" x2="{X(last_i) + slot / 2:.1f}" y1="{RY(lv):.1f}" y2="{RY(lv):.1f}" stroke="{UP if lv == 5 else GREY}" stroke-dasharray="{"1 2" if lv == 5 else "3 3"}"/>'
                 f'<text x="{L - 6}" y="{RY(lv) + 4:.1f}" text-anchor="end" class="ax">{lv}</text>')
    for col, colr, wd in (("rsi2", "#A9B4BF", 1), ("rsi14", BLUE, 1.6)):
        o.append(f'<polyline points="{" ".join(f"{X(i):.1f},{RY(v):.1f}" for i, v in enumerate(win[col].values))}" fill="none" stroke="{colr}" stroke-width="{wd}"/>')
    for m in marks:
        i = pos[m["date"]]
        o.append(f'<circle cx="{X(i):.1f}" cy="{RY(win.loc[m["date"], "rsi2"]):.1f}" r="3" fill="{GOLD}"/>')

    m0, m1 = ys["macd"]
    mm = float(np.nanmax(np.abs(win[["macd", "macd_sig", "macd_hist"]].values))) * 1.1
    MY = lambda v: (m0 + m1) / 2 - (m1 - m0) / 2 * v / mm  # noqa: E731
    o.append(f'<text x="{L}" y="{m0 - 3}" class="pt">MACD(12,26,9) · 黑线 MACD · 橙线 信号线 · 柱 = 两者之差</text>')
    o.append(f'<line x1="{L}" x2="{X(last_i) + slot / 2:.1f}" y1="{MY(0):.1f}" y2="{MY(0):.1f}" stroke="var(--rule)"/>')
    for i, v in enumerate(win["macd_hist"].values):
        o.append(f'<rect x="{X(i) - slot * 0.3:.1f}" y="{min(MY(v), MY(0)):.1f}" width="{slot * 0.6:.1f}" height="{abs(MY(v) - MY(0)):.1f}" fill="{UP if v >= 0 else DN}" opacity=".6"/>')
    for col, colr in (("macd", "var(--ink)"), ("macd_sig", AMBER)):
        o.append(f'<polyline points="{" ".join(f"{X(i):.1f},{MY(v):.1f}" for i, v in enumerate(win[col].values))}" fill="none" stroke="{colr}" stroke-width="1.2"/>')

    s0, s1 = ys["score"]
    SY = lambda v: s1 - (s1 - s0) * v / 100  # noqa: E731
    o.append(f'<text x="{L}" y="{s0 - 3}" class="pt">恐慌出清分（0–100：超卖、放量、VXN、回调四项的五年分位均值）</text>')
    o.append(f'<line x1="{L}" x2="{X(last_i) + slot / 2:.1f}" y1="{SY(80):.1f}" y2="{SY(80):.1f}" stroke="{GOLD}" stroke-dasharray="3 2"/>'
             f'<text x="{L - 6}" y="{SY(80) + 4:.1f}" text-anchor="end" class="ax">80</text>')
    o.append(f'<polyline points="{" ".join(f"{X(i):.1f},{SY(v):.1f}" for i, v in enumerate(win["score"].values) if not np.isnan(v))}" fill="none" stroke="{GOLD}" stroke-width="1.5"/>')
    for m in marks:
        i = pos[m["date"]]
        o.append(f'<circle cx="{X(i):.1f}" cy="{SY(win.loc[m["date"], "score"]):.1f}" r="3" fill="{GOLD}"/>')
    o.append("</svg>")
    return "".join(o)


def path_svg(bt: dict, anchor_px: float, realized: list) -> str:
    W, H, L, R, T, B = 680, 250, 50, 130, 14, 30
    q = {p: (np.percentile(bt["paths"], p, axis=0) - 1) * 100 for p in (10, 25, 50, 75, 90)}
    nm = (np.median(bt["pull_paths"], axis=0) - 1) * 100
    lo, hi = min(q[10].min(), -6), max(q[90].max(), 6)
    X = lambda k: L + (W - L - R) * k / 20  # noqa: E731
    Y = lambda v: T + (H - T - B) * (hi - v) / (hi - lo)  # noqa: E731
    o = [f'<svg viewBox="0 0 {W} {H}" class="chart" role="img" aria-label="历史信号之后20个交易日的路径分布">']
    for v in range(int(np.floor(lo / 2) * 2), int(hi) + 1, 2):
        o.append(f'<line x1="{L}" x2="{W - R}" y1="{Y(v):.1f}" y2="{Y(v):.1f}" stroke="{"var(--rule)" if v == 0 else "var(--grid)"}"/>'
                 f'<text x="{L - 6}" y="{Y(v) + 4:.1f}" text-anchor="end" class="ax">{v:+d}%</text>')

    def band(a, b):
        return " ".join(f"{X(k):.1f},{Y(v):.1f}" for k, v in enumerate(q[a])) + " " + \
            " ".join(f"{X(k):.1f},{Y(v):.1f}" for k, v in reversed(list(enumerate(q[b]))))
    o.append(f'<polygon points="{band(90, 10)}" fill="{BLUE}" fill-opacity=".10"/>')
    o.append(f'<polygon points="{band(75, 25)}" fill="{BLUE}" fill-opacity=".2"/>')
    o.append(f'<polyline points="{" ".join(f"{X(k):.1f},{Y(v):.1f}" for k, v in enumerate(q[50]))}" fill="none" stroke="{BLUE}" stroke-width="2.2"/>')
    o.append(f'<polyline points="{" ".join(f"{X(k):.1f},{Y(v):.1f}" for k, v in enumerate(nm))}" fill="none" stroke="{GREY}" stroke-width="1.5" stroke-dasharray="3 3"/>')
    o.append(f'<text x="{X(20) + 5:.1f}" y="{Y(q[50][-1]) - 2:.1f}" class="lb" fill="{BLUE}">信号后中位 {q[50][-1]:+.1f}%</text>'
             f'<text x="{X(20) + 5:.1f}" y="{Y(nm[-1]) + 14:.1f}" class="lb" fill="{GREY}">普通回调中位 {nm[-1]:+.1f}%</text>')
    k5 = 5
    o.append(f'<line x1="{X(k5):.1f}" x2="{X(k5):.1f}" y1="{T}" y2="{H - B}" stroke="var(--gold)" stroke-dasharray="2 3"/>'
             f'<text x="{X(k5) + 4:.1f}" y="{T + 10}" class="lb" fill="var(--gold)">第5日：信号 {q[50][k5]:+.1f}% vs 回调 {nm[k5]:+.1f}%</text>')
    if realized:
        pts = " ".join(f"{X(k):.1f},{Y((v / anchor_px - 1) * 100):.1f}" for k, v in enumerate(realized))
        o.append(f'<polyline points="{pts}" fill="none" stroke="var(--ink)" stroke-width="2"/>')
        k, v = len(realized) - 1, realized[-1]
        o.append(f'<circle cx="{X(k):.1f}" cy="{Y((v / anchor_px - 1) * 100):.1f}" r="3.5" fill="var(--ink)"/>'
                 f'<text x="{X(k) + 6:.1f}" y="{Y((v / anchor_px - 1) * 100) + 16:.1f}" class="lb" fill="var(--ink)">本次 {((v / anchor_px - 1) * 100):+.1f}%</text>')
    for k in (0, 5, 10, 15, 20):
        o.append(f'<text x="{X(k):.1f}" y="{H - 10}" text-anchor="middle" class="ax">{"信号日" if k == 0 else f"+{k}"}</text>')
    o.append("</svg>")
    return "".join(o)


CSS = """
:root{--paper:#F5F7FA;--sheet:#FFFFFF;--ink:#0F2240;--text:#1C2B3D;--muted:#5B6875;--rule:#D9E0E7;--grid:#EDF1F5;
--blue:#1B86B8;--amber:#D9840F;--gold:#C98A0B;--link:#1E3A5F;--up:#D64545;--dn:#1E9E6A;
--display:"Noto Serif SC","Songti SC",serif;--body:"Noto Sans SC","PingFang SC","Microsoft YaHei",system-ui,sans-serif;
--mono:"JetBrains Mono",ui-monospace,Menlo,monospace;color-scheme:light}
*,*::before,*::after{box-sizing:border-box}
body{margin:0;background:var(--paper);color:var(--text);font-family:var(--body);font-size:15.5px;line-height:1.7}
a{color:var(--link)}
.wrap{max-width:1040px;margin:0 auto;padding-inline:16px}
.bar{border-bottom:1px solid var(--rule);background:var(--sheet)}
.bar .wrap{display:flex;justify-content:space-between;align-items:center;gap:12px;padding-block:12px;font-size:14px}
.bar a{text-decoration:none;color:var(--muted)}.bar a.home{color:var(--ink);font-weight:700}
header.hero{padding-block:30px 6px}
.kicker{font-family:var(--mono);font-size:12px;letter-spacing:.08em;color:var(--blue)}
h1{font-family:var(--display);font-weight:900;color:var(--ink);font-size:clamp(28px,4.4vw,42px);line-height:1.2;margin:.25em 0 .4em}
h2{font-family:var(--display);font-weight:600;font-size:23px;color:var(--ink);margin:0 0 10px;border-bottom:2px solid var(--ink);padding-bottom:6px}
h3{font-size:16.5px;color:var(--ink);margin:18px 0 6px}
.lede{font-size:17px;max-width:78ch;margin:0}.lede b{color:var(--ink)}
.verdict{display:inline-block;background:#FFF3DC;color:#7A4E00;border:1px solid #F0D49B;border-radius:4px;padding:1px 10px;font-weight:700;margin-right:6px}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:1px;background:var(--rule);border:1px solid var(--rule);margin:20px 0 6px}
.tiles div{background:var(--sheet);padding:12px 14px;display:flex;flex-direction:column;gap:2px;min-width:0}
.tiles b{font-family:var(--mono);font-size:21px;font-weight:600;color:var(--ink);font-variant-numeric:tabular-nums}
.tiles span{font-size:12.5px;color:var(--muted)}
section{background:var(--sheet);border:1px solid var(--rule);padding:20px 20px 16px;margin:18px 0}
.note{font-size:13px;color:var(--muted)}
.scroll{overflow-x:auto;-webkit-overflow-scrolling:touch}
.chart{width:100%;height:auto;display:block}
.chart.big{min-width:760px}
.ax{font:10.5px var(--mono);fill:var(--muted)}.lb{font:11px var(--body);paint-order:stroke;stroke:#fff;stroke-width:3px;stroke-linejoin:round}.pt{font:11.5px var(--body);fill:var(--muted)}
.tag{font:11px var(--body);fill:var(--muted)}.mk{font:700 12px var(--mono);fill:var(--gold)}.ms{font:11px var(--mono);fill:#8A96A3}
.vk{font:600 10px var(--mono);fill:var(--gold)}.ox{font:8.5px var(--mono);fill:#8A96A3}
.legend{display:flex;flex-wrap:wrap;gap:4px 16px;font-size:12.5px;color:var(--muted);margin:6px 0 0}
.legend i{display:inline-block;width:14px;height:8px;margin-right:5px;vertical-align:middle}
table{width:100%;border-collapse:collapse;font-size:14px}
th,td{padding:6px 8px;border-bottom:1px solid var(--grid);text-align:left;vertical-align:top}
th{font-size:12.5px;color:var(--muted);font-weight:500}
td.n,th.n{font-family:var(--mono);text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
.pos{color:var(--up)}.neg{color:var(--dn)}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:14px}
.card{border:1px solid var(--rule);border-top:3px solid var(--gold);padding:14px 16px;background:#FFFDF8}
.card h3{margin:0 0 6px;display:flex;justify-content:space-between;gap:8px;align-items:baseline}
.card h3 span{font-family:var(--mono);font-size:13px;color:var(--muted);font-weight:400}
.card ul{margin:6px 0 8px;padding-left:1.1em;font-size:14px}.card li{margin:2px 0}
.card .out{font-size:13.5px;background:#F4F7FA;padding:6px 10px;border-radius:3px}
.ok{color:#1E8449;font-weight:700}.no{color:#B03A2E;font-weight:700}
details{margin-top:10px}summary{cursor:pointer;color:var(--link);font-size:14px}
.callout{border-left:4px solid var(--amber);background:#FFF8EC;padding:10px 14px;margin:12px 0;font-size:14.5px}
footer{padding-block:18px 40px;font-size:12.5px;color:var(--muted)}
@media (max-width:560px){section{padding:16px 13px}th,td{padding:5px 5px}table{font-size:13px}}
"""


def cond_rows(r: pd.Series) -> list[tuple[str, bool, str]]:
    R = A.RULE
    return [
        ("长期趋势向上", bool(r["up"]), f"收盘高于 200 日均线 {r['above_ma200'] * 100:+.1f}%"),
        (f"回调 ≥ {R['dd_min']:.0%}", bool(r["dd"] >= R["dd_min"]), f"距 63 日高点 −{r['dd'] * 100:.1f}%"),
        (f"RSI(2) ≤ {R['rsi2_max']:.0f}", bool(r["rsi2"] <= R["rsi2_max"]), f"RSI(2) = {r['rsi2']:.2f}"),
        (f"放量 ≥ {R['vrel_min']}×", bool(r["vrel"] >= R["vrel_min"]),
         f"{r['vrel']:.2f}× 常态" + (f"（原始 {r['vrel_raw']:.2f}×，已扣除月度期权到期放量）" if r["opex"] else "")),
        (f"VXN 高于 20 日均值 ≥ {R['vxn_rel_min']:.0%}", bool(r["vxn_rel"] >= R["vxn_rel_min"]),
         f"VXN {r['vxn']:.2f}，{r['vxn_rel'] * 100:+.0f}%（当日 {r['vxn_chg'] * 100:+.1f}%）"),
    ]


def render(df: pd.DataFrame, bt: dict, opt: dict | None, vxn_stale: bool, ga: str | None) -> tuple[str, dict]:
    last = df.index[-1]
    start = last - pd.DateOffset(months=5)
    win = df[df.index >= start]
    fut = A.next_sessions(last, F)
    P = float(win["close"].iloc[-1])
    ev_in = [d for d in bt["event_dates"] if d >= win.index[0]]
    live = ev_in[-1] if ev_in and (df.index.get_loc(last) - df.index.get_loc(ev_in[-1])) < 20 else None

    misses = []
    for d, r in win.iterrows():
        if d in ev_in or not r["up"] or not (r["score"] >= 80):
            continue
        if any(0 < df.index.get_loc(d) - df.index.get_loc(e) <= A.RULE["cooldown"] for e in ev_in):
            continue
        failed = [c[0] for c in cond_rows(r) if not c[1]]
        misses.append({"date": d, "failed": failed, "score": float(r["score"])})
    marks = [{"date": d} for d in ev_in]

    cards = []
    for k, d in enumerate(ev_in, 1):
        r = df.loc[d]
        i = df.index.get_loc(d)
        rows = "".join(f"<li>{'<span class=ok>✓</span>' if ok else '<span class=no>✗</span>'} {esc(name)}：{esc(val)}</li>"
                       for name, ok, val in cond_rows(r))
        extra = (f"<li>当日 {r['ret1'] * 100:+.2f}%，收在当日振幅的 {((r['close'] - r['low']) / (r['high'] - r['low'])) * 100:.0f}% 位置；"
                 f"RSI(14) {r['rsi14']:.1f}；MACD 柱 {r['macd_hist']:+.2f}（{'零轴下方' if r['macd_hist'] < 0 else '零轴上方'}）；"
                 f"出清分 {r['score']:.0f}</li>")
        outs = []
        for h in (5, 10, 20):
            j = i + h
            if j < len(df):
                rr = df["adj_close"].iloc[j] / df["adj_close"].iloc[i] - 1
                outs.append(f"{h} 日后 <b class='{'pos' if rr >= 0 else 'neg'}'>{rr * 100:+.1f}%</b>")
        realized = len(df) - 1 - i
        if realized < 20:
            rr = df["adj_close"].iloc[-1] / df["adj_close"].iloc[i] - 1
            outs.append(f"至今 {realized} 个交易日 <b class='{'pos' if rr >= 0 else 'neg'}'>{rr * 100:+.1f}%</b>")
        fw = df["adj_close"].iloc[i + 1:i + 21]
        if len(fw) >= 5:
            mae = fw.min() / df["adj_close"].iloc[i] - 1
            outs.append(f"{len(fw)} 日内最大浮亏 {mae * 100:+.1f}%" if mae < 0
                        else f"{len(fw)} 日内从未跌破买入价")
        cards.append(f"""<div class="card"><h3>{k}. {d:%Y-%m-%d} 周{WEEK[d.weekday()]}<span>收 {r['close']:.2f}</span></h3>
<ul>{rows}{extra}</ul><div class="out">{' · '.join(outs)}</div></div>""")
    miss_rows = "".join(
        f"<tr><td>{chr(97 + k)}</td><td>{m['date']:%Y-%m-%d}</td><td class='n'>{df.loc[m['date'], 'close']:.2f}</td>"
        f"<td class='n'>{m['score']:.0f}</td><td>{esc('、'.join(m['failed']) or '—')}</td>"
        f"<td class='n'>{pct(df.loc[m['date'], 'f5'], 1, True)}</td></tr>" for k, m in enumerate(misses))

    proj = {}
    if live is not None:
        a_px = float(df.loc[live, "close"])
        after = list(df.index[df.index > live]) + fut
        for h in (5, 10, 20):
            proj[h] = {p: float(np.percentile(bt["paths"][:, h], p) * a_px) for p in (10, 25, 50, 75, 90)}
            proj[h]["date"] = after[h - 1]
    realized_path = list(df.loc[live:, "adj_close"].values / df.loc[live, "adj_close"] * df.loc[live, "close"]) if live is not None else []

    if opt:
        term_rows = "".join(
            f"<tr><td>{t['expiry']}{'（月度）' if A.is_monthly_opex(pd.Timestamp(t['expiry'])) else ('（周五）' if pd.Timestamp(t['expiry']).weekday() == 4 else '')}</td>"
            f"<td class='n'>{t['days']}</td>"
            f"<td class='n'>±{t['straddle']:.2f}（±{t['move_pct'] * 100:.1f}%）</td><td class='n'>{t['atm_iv'] * 100:.1f}%</td>"
            f"<td class='n'>{P - t['sigma_move']:.0f} – {P + t['sigma_move']:.0f}</td><td class='n'>{t['oi']:,}</td></tr>"
            for t in opt["term"] if pd.Timestamp(t["expiry"]).weekday() == 4 or t["days"] <= 3)
        pb = opt["prob_below"]
        hi63 = float(df["close"].iloc[-63:].max())
        anchor_close = float(df.loc[live, "close"]) if live is not None else P
        anchor_low = float(df.loc[live, "low"]) if live is not None else P

        def above(k):
            v = pb(k)
            return None if v is None else 1 - v
        probs = [(f"回到 3 个月高点 {hi63:.2f} 之上", above(hi63))]
        if opt["flip"]:
            probs.append((f"站上 Gamma 翻转点 {opt['flip']:.0f}", above(opt["flip"])))
        probs += [(f"低于信号日收盘 {anchor_close:.2f}", pb(anchor_close)),
                  (f"低于失效参考 {anchor_low:.2f}", pb(anchor_low))]
        if opt["monthly"]["put_wall"]:
            probs.append((f"低于月度看跌墙 {opt['monthly']['put_wall']:.0f}", pb(opt["monthly"]["put_wall"])))
        prob_rows = "".join(f"<tr><td>{esc(a)}</td><td class='n'><b>{pct(b, 0)}</b></td></tr>" for a, b in probs)
        front = opt["term"][0]
        neg = (opt["flip"] and P < opt["flip"]) or (not opt["flip"] and opt["gex_spot"] < 0)
        regime = "负 gamma（做市商对冲会放大波动）" if neg else "正 gamma（做市商对冲会抑制波动）"
        wk, mo = opt["weekly"], opt["monthly"]
        lows = [x for x in (wk["put_wall"], mo["put_wall"]) if x]
        near_low = (f"，与信号日最低 {anchor_low:.2f} 相距不到 1.5%" if live is not None and lows
                    and min(abs(x / anchor_low - 1) for x in lows) < 0.015 else "")
        near_high = ("，几乎就是 3 个月高点" if mo["call_wall"] and abs(mo["call_wall"] / hi63 - 1) < 0.01 else "")
        hedge_note = ("：避险需求仍在，市场并没有转向乐观。" if opt["pc_oi"] > 1.2 and opt["put25_iv"] - opt["call25_iv"] > 0.04
                      else "。")
        fri = [t for t in opt["term"] if pd.Timestamp(t["expiry"]).weekday() == 4]
        term_note = ""
        if len(fri) >= 2:
            term_note = (f"期限结构：{fri[0]['expiry'][5:]} 到期的平值 IV {fri[0]['atm_iv'] * 100:.1f}%，{fri[1]['expiry'][5:]} 为 {fri[1]['atm_iv'] * 100:.1f}%"
                         + ("——近端更贵，市场在为眼前的事件（财报、议息等）额外付费。" if fri[0]["atm_iv"] > fri[1]["atm_iv"] + 0.01 else "。"))
        upcoming = [(d, n_) for d, n_ in A.EVENTS if pd.Timestamp(opt["asof"]) < pd.Timestamp(d) <= pd.Timestamp(opt["asof"]) + pd.Timedelta(days=45)]
        if upcoming:
            term_note += " 未来 45 天的已知事件：" + "；".join(f"{d[5:]} {n_}" for d, n_ in upcoming) + "（日程来源：<a href='https://balder-ai.com/research/midterms-2026' rel='noopener'>Balder 事件日程</a>）。"
        opt_html = f"""
<section aria-labelledby="s-opt"><h2 id="s-opt">期权市场在说什么（{esc(opt['asof'])} 收盘后快照）</h2>
<div class="callout"><b>结论</b>：现价 {P:.2f} 在 Gamma 翻转点 <b>{num(opt['flip'], 0)}</b> 之下，属于<b>{regime}</b>——重新站上 {num(opt['flip'], 0)} 之前，涨跌都容易被放大。
看跌期权最集中在 <b>{num(wk['put_wall'], 0)}</b>（{wk['expiry'][5:]} 到期，{wk['put_wall_oi']:,} 张）和 <b>{num(mo['put_wall'], 0)}</b>（{mo['expiry'][5:]} 月度，{mo['put_wall_oi']:,} 张）{near_low}；
看涨期权最集中在 <b>{num(wk['call_wall'], 0)}</b>（{wk['expiry'][5:]}）与 <b>{num(mo['call_wall'], 0)}</b>（月度{near_high}）。
同等虚值的保护性看跌比看涨贵 <b>{(opt['put25_iv'] - opt['call25_iv']) * 100:.1f}</b> 个波动率点，看跌/看涨未平仓量比 {opt['pc_oi']:.2f}{hedge_note}</div>
<div class="scroll"><table>
<tr><th>指标</th><th class="n">数值</th><th>怎么读</th></tr>
<tr><td>Gamma 翻转点（35 天内到期合计）</td><td class="n">{num(opt['flip'], 1)}</td><td>高于此，做市商对冲抑制波动；低于此，放大波动</td></tr>
<tr><td>本周（{wk['expiry']}）看涨墙 / 看跌墙 / 最大痛点</td><td class="n">{num(wk['call_wall'], 0)} / {num(wk['put_wall'], 0)} / {num(wk['max_pain'], 0)}</td><td>现价 ±6% 内未平仓量最多的行权价；最大痛点 = 期权买方整体亏损最大的结算价</td></tr>
<tr><td>月度（{mo['expiry']}）看涨墙 / 看跌墙 / 最大痛点</td><td class="n">{num(mo['call_wall'], 0)} / {num(mo['put_wall'], 0)} / {num(mo['max_pain'], 0)}</td><td>月度合约持仓最大，影响更持久</td></tr>
<tr><td>看跌/看涨 未平仓量比</td><td class="n">{opt['pc_oi']:.2f}</td><td>看跌 {opt['oi_p']:,} 张 vs 看涨 {opt['oi_c']:,} 张</td></tr>
<tr><td>看跌/看涨 当日成交量比</td><td class="n">{opt['pc_vol']:.2f}</td><td>大于 1 = 当天买保护的多于买进攻的</td></tr>
<tr><td>{opt['skew_expiry']} 到期 25Δ 看跌 / 看涨 隐含波动率</td><td class="n">{opt['put25_iv'] * 100:.1f}% / {opt['call25_iv'] * 100:.1f}%</td><td>对应行权价约 {opt['put25_k']:.0f} / {opt['call25_k']:.0f}；差值就是“偏斜”</td></tr>
<tr><td>最近到期（{front['expiry']}）隐含的单日波动</td><td class="n">±{front['move_pct'] * 100:.2f}%</td><td>平值跨式价格 ÷ 现价，近似市场对下一个交易日的定价</td></tr>
</table></div>
<h3>各到期日的期权定价区间</h3>
<div class="scroll"><table><tr><th>到期日</th><th class="n">天数</th><th class="n">平值跨式（预期波动）</th><th class="n">平值 IV</th><th class="n">±1σ 价格区间</th><th class="n">未平仓量</th></tr>{term_rows}</table></div>
<p class="note">{term_note}</p>
<h3>期权隐含概率（到 {esc(opt['monthly_expiry'])} 月度到期）</h3>
<div class="scroll"><table><tr><th>事件</th><th class="n">概率</th></tr>{prob_rows}</table></div>
<p class="note">由期权价格对行权价求导（Breeden–Litzenberger）得到的风险中性概率。它包含保险溢价：下跌一侧通常被高估、上涨一侧被低估，不能直接当作真实概率。</p>
<p class="note">数据说明：QQQ 期权链 {opt['n_contracts']:,} 个合约、{opt['n_expiries']} 个到期日；隐含波动率由本站用买卖中间价反推，未平仓量为交易所上一交易日公布值，成交量为当日。Yahoo 只提供期权的当下快照，没有历史，所以买点规则里的“期权恐慌”用的是 VXN（由纳指100 期权计算的隐含波动率指数）。从今天起每个交易日自动存档完整期权链，积累后即可直接回测看跌/看涨比、偏斜和 Gamma 信号。</p>
</section>"""
    else:
        opt_html = '<section><h2>期权市场</h2><p class="note">本次没有取到 QQQ 期权链。</p></section>'

    s, b, pl = bt["signal"], bt["base"], bt["pullback"]
    nl = bt["nulls"]
    sum_rows = ""
    for lab, frame, n_ in (("恐慌出清信号", s, f"{bt['n_done']} 次"),
                           ("上升趋势中任意 ≥5% 回调日", pl, f"{bt['n_pullback_days']:,} 天"),
                           ("全部交易日", b, f"{bt['n_days']:,} 天")):
        sum_rows += (f"<tr><td>{lab}</td><td class='n'>{n_}</td>"
                     + "".join(f"<td class='n'>{pct(frame[h]['mean'], 2, True)}<br><span class='note'>胜率 {pct(frame[h]['hit'], 0)}</span></td>" for h in ("f5", "f10", "f20"))
                     + "</tr>")
    p_rows = "".join(f"<tr><td>{lab}</td>" + "".join(f"<td class='n'>{nl[k][h]:.3f}</td>" for h in ("f5", "f10", "f20")) + "</tr>"
                     for lab, k in (("从全部交易日随机抽", "all"), ("只在上升趋势中随机抽", "uptrend"),
                                    ("只在上升趋势的 ≥5% 回调日中随机抽", "pullback")))
    ev_rows = "".join(
        f"<tr><td>{t['date']}</td><td class='n'>{t['close']:.2f}</td><td class='n'>−{t['dd'] * 100:.1f}%</td><td class='n'>{t['rsi2']:.1f}</td>"
        f"<td class='n'>{t['vrel']:.2f}×</td><td class='n'>{t['vxn']:.1f}（{t['vxn_rel'] * 100:+.0f}%）</td>"
        + "".join(f"<td class='n {'pos' if (t[h] or 0) >= 0 else 'neg'}'>{pct(t[h], 1, True)}</td>" for h in ("f5", "f10", "f20"))
        + f"<td class='n'>{pct(t['mae20'], 1, True)}</td></tr>" for t in reversed(bt["table"]))
    w = bt["worst"]

    lr = df.loc[live] if live is not None else None
    if lr is not None:
        since = df["adj_close"].iloc[-1] / df.loc[live, "adj_close"] - 1
        verdict = (f"<span class='verdict'>是，按规则成立</span>{md(live)}（周{WEEK[live.weekday()]}）QQQ 收 <b>{lr['close']:.2f}</b>，"
                   f"预先写定的「上升趋势中的恐慌出清」规则<b>四个条件全部满足</b>：仍在 200 日均线上方 {lr['above_ma200'] * 100:.1f}%；"
                   f"距 3 个月高点回调 {lr['dd'] * 100:.1f}%；RSI(2) 跌到 {lr['rsi2']:.2f}；扣除月度期权到期的放量后，成交量仍是常态的 {lr['vrel']:.2f} 倍；"
                   f"VXN 单日跳升 {lr['vxn_chg'] * 100:.0f}% 至 {lr['vxn']:.2f}。2001 年以来同样的信号出现 {bt['n_done']} 次，"
                   f"之后 5 个交易日平均 <b>{pct(s['f5']['mean'], 1, True)}</b>、上涨概率 <b>{pct(s['f5']['hit'], 0)}</b>（全部交易日为 {pct(b['f5']['mean'], 1, True)}、{pct(b['f5']['hit'], 0)}）。"
                   f"但边界要看清：优势<b>集中在一周之内</b>，放到 10–20 天，并不比“上升趋势里任意一次 5% 回调”更好。"
                   f"截至 {md(last)} 收盘，{'已反弹' if since >= 0 else '仍下跌'} {pct(since, 1, True)}。")
    else:
        verdict = "最近 20 个交易日没有触发「恐慌出清」买点。"

    tiles = ""
    if lr is not None:
        tiles = f"""<div class="tiles">
<div><b>{md(live)} ✓</b><span>触发买点 · 收 {lr['close']:.2f} · 出清分 {lr['score']:.0f}{'（五个月最高）' if lr['score'] >= win['score'].max() - 1e-9 else ''}</span></div>
<div><b>{pct(s['f5']['hit'], 0)} / {pct(s['f5']['mean'], 1, True)}</b><span>历史 {bt['n_done']} 次：5 日上涨概率 / 平均涨幅</span></div>
<div><b>{P:.2f}</b><span>{md(last)} 收盘 · 较信号日 {pct(df['adj_close'].iloc[-1] / df.loc[live, 'adj_close'] - 1, 1, True)}</span></div>
<div><b>{lr['low']:.2f}</b><span>失效参考：5 日内收盘跌破信号日最低</span></div>
<div><b>{num(opt['flip'], 0) if opt else '—'}</b><span>Gamma 翻转点 · 站上之前处于负 gamma</span></div>
</div>"""

    proj_rows = ""
    for h, v in proj.items():
        proj_rows += (f"<tr><td>信号后第 {h} 个交易日（{v['date']:%m-%d}）</td><td class='n'>{v[10]:.0f}</td><td class='n'>{v[25]:.0f}</td>"
                      f"<td class='n'><b>{v[50]:.0f}</b></td><td class='n'>{v[75]:.0f}</td><td class='n'>{v[90]:.0f}</td></tr>")

    ga_tag = (f'<script async src="https://www.googletagmanager.com/gtag/js?id={ga}"></script>'
              f"<script>window.dataLayer=window.dataLayer||[];function gtag(){{dataLayer.push(arguments);}}"
              f"gtag('js',new Date());gtag('config','{ga}');</script>") if ga else ""
    R_ = A.RULE
    if live is not None:
        lag = df.index.get_loc(last) - df.index.get_loc(live)
        h1 = ("QQQ 买点雷达：上周五是买点吗？" if live.weekday() == 4 and 0 < lag <= 5 and last.isocalendar()[1] != live.isocalendar()[1]
              else f"QQQ 买点雷达：{md(live)}是买点吗？")
    else:
        h1 = "QQQ 买点雷达：今天有买点吗？"
    chart = main_chart(win, fut, bt, opt, marks, misses, live)
    pathc = path_svg(bt, float(df.loc[live, "close"]), realized_path) if live is not None else ""
    og = (md(live) + "触发恐慌出清买点") if live is not None else "暂无买点"

    page = f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
{ga_tag}
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>QQQ 买点雷达 · 老王看美股</title>
<meta name="description" content="QQQ 每日买点雷达：上升趋势中的恐慌出清信号（价格、成交量、RSI、VXN），2001 年以来回测验证；期权链解读与未来走势投影。">
<meta property="og:title" content="{esc(h1)}">
<meta property="og:description" content="{esc(og)}；历史 {bt['n_done']} 次，5 日上涨概率 {pct(s['f5']['hit'], 0)}。">
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Noto+Serif+SC:wght@600;900&family=Noto+Sans+SC:wght@400;500;700&family=JetBrains+Mono:wght@400;600&display=swap">
<style>{CSS}</style></head>
<body>
<div class="bar"><div class="wrap"><a class="home" href="./">← 老王看美股</a><a href="https://heylaowang.com/ai/">老王看AI</a></div></div>
<main class="wrap">
<header class="hero">
<div class="kicker">QQQ · 每个交易日收盘后更新 · 数据截至 {last:%Y-%m-%d}</div>
<h1>{h1}</h1>
<p class="lede">{verdict}</p>
{tiles}
</header>

<section aria-labelledby="s-chart"><h2 id="s-chart">近五个月：买点标注与未来投影</h2>
<div class="scroll">{chart}</div>
<div class="legend"><span><i style="background:var(--up)"></i>红涨</span><span><i style="background:var(--dn)"></i>绿跌</span>
<span>▲ 金色编号 = 触发买点（见下方卡片）</span><span>○ 字母 = 接近但未触发</span>
<span><i style="background:var(--blue);opacity:.3"></i>历史信号之后的走势分布（10–90%，中线为中位数）</span>
<span><i style="background:var(--amber);opacity:.3"></i>期权定价区间（虚线 ±1σ，色带约 50%）</span>
<span><i style="background:#8A96A3;height:2px"></i>普通回调之后的中位走势</span></div>
<p class="note">鼠标悬停在 K 线上可看当日开高低收、成交量倍数、RSI、VXN 与出清分；手机上可左右滑动图表。</p>
</section>

<section aria-labelledby="s-cards"><h2 id="s-cards">近五个月的买点，以及为什么</h2>
<div class="cards">{''.join(cards)}</div>
<h3>接近但没有触发的日子</h3>
<div class="scroll"><table><tr><th>标注</th><th>日期</th><th class="n">收盘</th><th class="n">出清分</th><th>没满足的条件</th><th class="n">之后 5 日</th></tr>{miss_rows or '<tr><td colspan=6>无</td></tr>'}</table></div>
<p class="note">这些日子出清分也很高，但缺一个条件。规则要求四条同时满足，是因为单看平均分，回测里的区分度很弱（见下方“验证”）。</p>
</section>

<section aria-labelledby="s-proj"><h2 id="s-proj">接下来几天：两种投影</h2>
<p>一是<b>历史</b>：把 {bt['n_done']} 次信号之后的走势，按比例套到{md(live) if live is not None else '信号日'}收盘价上；二是<b>期权</b>：今天的期权价格隐含的区间（上方大图中的橙色锥形）。</p>
<div class="scroll">{pathc}</div>
<div class="legend"><span><i style="background:var(--blue)"></i>信号之后（深色 25–75%，浅色 10–90%）</span><span><i style="background:#8A96A3;height:2px"></i>上升趋势中普通 ≥5% 回调之后</span><span><i style="background:var(--ink);height:2px"></i>本次实际</span></div>
<div class="scroll"><table><tr><th>历史投影（QQQ 价格）</th><th class="n">10%</th><th class="n">25%</th><th class="n">中位</th><th class="n">75%</th><th class="n">90%</th></tr>{proj_rows}</table></div>
<p class="note">图里能看到这项研究最重要的结论：信号之后的中位走势在头 5 天明显高于普通回调，之后两条线靠拢。所以这是一个“一周左右的反弹”信号，不是一个月以上的择时信号。</p>
</section>

{opt_html}

<section aria-labelledby="s-bt"><h2 id="s-bt">买点规则与回测验证</h2>
<h3>假设（先写下，再回测）</h3>
<p>在长期上升趋势里，一次短促的抛售如果同时出现<b>价格极度超卖、成交量放大、隐含波动率飙升</b>，说明被迫卖出和恐慌买保险的人已经付出了过高代价；趋势没坏，价格倾向于很快反弹。这对应两条已有研究：指数的短期反转效应，以及“隐含波动率越高于实际波动，之后收益越好”（Bollerslev、Tauchen、Zhou，2009）。</p>
<h3>规则（收盘时判断，四条同时满足）</h3>
<ol>
<li><b>趋势</b>：复权收盘价高于 {R_['trend_ma']} 日均线。</li>
<li><b>回调</b>：距 {R_['high_win']} 个交易日高点至少 {R_['dd_min']:.0%}。</li>
<li><b>超卖</b>：RSI(2) ≤ {R_['rsi2_max']:.0f}。</li>
<li><b>恐慌</b>：成交量 ≥ 过去 20 日中位数的 {R_['vrel_min']} 倍（月度期权到期日先除以历史上到期日的典型放量倍数），且 VXN 高于过去 20 日均值 {R_['vxn_rel_min']:.0%} 以上。</li>
</ol>
<p class="note">5 个交易日内的重复信号算同一次。样本从 {bt['sample_from']} 开始（VXN 自 2001 年发布）。</p>
<h3>结果</h3>
<div class="scroll"><table><tr><th></th><th class="n">样本</th><th class="n">之后 5 日</th><th class="n">10 日</th><th class="n">20 日</th></tr>{sum_rows}</table></div>
<h3>验证：会不会只是运气？</h3>
<p><b>随机对照</b>：从对照池里随机抽 {bt['n_done']} 天、重复数千次，看有多大比例能达到信号的平均收益（p 值越小，越不像运气）：</p>
<div class="scroll"><table><tr><th>对照池</th><th class="n">5 日</th><th class="n">10 日</th><th class="n">20 日</th></tr>{p_rows}</table></div>
<p><b>参数稳健性</b>：把四个阈值各换几档（回调 3–7%、RSI(2) 3/5/10、放量 1.25/1.5/2 倍、VXN 5/10/20%），共 {bt['grid_cells']} 组，其中 {bt['grid_usable']} 组样本够用。<b>{pct(bt['grid_pos_share'], 0)}</b> 的组合 5 日收益都高于全部交易日，中位数多出 {pct(bt['grid_median_excess'], 2, True)}。把收益序列整体错位后重跑同样的搜索作为“纯噪声”基准：真实结果的中位 t 值 {bt['grid_median_t']:.2f} 远高于噪声（p = {bt['family_p_median']:.3f}），最好的一组也胜过噪声中最好的一组（p = {bt['family_p_max']:.3f}）。</p>
<div class="callout"><b>必须说清的几点</b><br>
① 预先写定的这组阈值，恰好是 {bt['grid_cells']} 组里 5 日 t 值最高的（t = {bt['rule_cell_t']:.2f}）。这是巧合，也意味着 {pct(s['f5']['mean'], 1, True)} 偏乐观；更合理的预期是参数网格的中位数，即比平常多 {pct(bt['grid_median_excess'], 1, True)} 左右。<br>
② 10 日、20 日的超额不显著：和“上升趋势里任意 5% 回调”比，p ≈ {nl['pullback']['f10']:.2f}。买在回调本身就不错（20 日平均 {pct(pl['f20']['mean'], 1, True)}，全部交易日为 {pct(b['f20']['mean'], 1, True)}），恐慌出清只是把<b>时点</b>选得更好。<br>
③ 样本只有 {bt['n_done']} 次。最差的一次是 {w['date']}{'（新冠暴跌开端）' if w['date'] == '2020-02-24' else ''}，之后 20 日 {pct(w['f20'], 1, True)}。<br>
④ 失效参考：{bt['n_done']} 次里有 {bt['broke_n']} 次在 5 日内收盘跌破信号日最低价，这些之后 20 日平均 {pct(bt['broke_f20'], 1, True)}、期间浮亏中位 {pct(bt['broke_mae'], 1, True)}；守住的 {bt['held_n']} 次平均 {pct(bt['held_f20'], 1, True)}。这是同一批样本里的观察，不是独立验证过的止损规则。<br>
⑤ MACD 测过但没有放进规则：用“MACD 柱创 60 日新低”替代 RSI(2)，5 日结果几乎一样；两者叠加只减少样本、不提高收益——MACD 滞后，它确认的是下跌，不是低点。RSI(14) ≤ 35 替代 RSI(2) 效果相近{f'（本次 RSI(14) 为 {lr["rsi14"]:.1f}）' if lr is not None else ''}。<br>
⑥ 把四个要素平均成“出清分”做十分位检验，分数与后续收益的关系很弱；优势只出现在四个要素<b>同时</b>极端的时候。所以图中的出清分只用来看强度，买点以规则为准。</div>
<details><summary>展开：2001 年以来全部 {bt['n_events']} 次信号</summary>
<div class="scroll"><table><tr><th>日期</th><th class="n">收盘</th><th class="n">回调</th><th class="n">RSI2</th><th class="n">放量</th><th class="n">VXN</th><th class="n">5日</th><th class="n">10日</th><th class="n">20日</th><th class="n">20日内最大浮亏</th></tr>{ev_rows}</table></div>
<p class="note">价格为拆股调整后的 QQQ 价格；收益用含分红的复权价计算。</p></details>
</section>

<footer>
<p><b>数据</b>：QQQ 日线开高低收与成交量、VXN、VIX（Yahoo Finance，1999 年起）；QQQ 期权链为每个交易日收盘后的快照（Yahoo Finance）。{'VXN 当日数据尚未发布，沿用前一交易日数值。' if vxn_stale else ''}每个交易日美东收盘后自动更新。</p>
<p><b>方法</b>：规则、回测与验证代码见 <a href="https://github.com/ryanlr/stock_trading/tree/main/skills/market-risk-playbook">GitHub</a>。“只报告通过检验的结果、失败的也写出来”的做法借鉴自 <a href="https://balder-ai.com/playbook" rel="noopener">Balder 的 Market Risk Playbook</a>。</p>
<p>研究记录，不构成投资建议。历史统计不代表未来，回测样本有限。</p>
</footer>
</main></body></html>
"""
    out = {"date": str(last.date()), "close": P, "live_signal": str(live.date()) if live is not None else None,
           "events_5m": [str(d.date()) for d in ev_in], "near_misses": [str(m["date"].date()) for m in misses],
           "backtest": {k: v for k, v in bt.items() if k not in ("paths", "pull_paths", "event_dates", "table", "worst")},
           "projection": {h: {str(p): v[p] for p in (10, 25, 50, 75, 90)} for h, v in proj.items()},
           "options": {k: v for k, v in (opt or {}).items() if k != "prob_below"}}
    return page, out


def main() -> None:
    here = os.path.dirname(os.path.abspath(__file__))
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default=os.path.join(here, "..", "data"))
    ap.add_argument("--out", default="prediction.html")
    ap.add_argument("--json", default=None)
    ap.add_argument("--ga", default="G-2G0J05CN16")
    ap.add_argument("--null-reps", type=int, default=5000)
    ap.add_argument("--family-reps", type=int, default=500)
    a = ap.parse_args()
    raw, stale = A.load(a.data_dir)
    df = A.features(raw)
    bt = A.backtest(df, null_reps=a.null_reps, family_reps=a.family_reps)
    opt = A.options_read(os.path.join(a.data_dir, "options", "qqq_chain_latest.csv.gz"))
    if opt and opt["asof"] != str(df.index[-1].date()):
        print(f"[warn] option snapshot {opt['asof']} != last session {df.index[-1].date()}", file=sys.stderr)
    page, out = render(df, bt, opt, stale, a.ga or None)
    with open(a.out, "w", encoding="utf-8") as fh:
        fh.write(page)
    if a.json:
        with open(a.json, "w", encoding="utf-8") as fh:
            json.dump(out, fh, ensure_ascii=False, indent=1,
                      default=lambda x: float(x) if isinstance(x, (np.floating, np.integer)) else str(x))
    print(f"wrote {a.out}: {out['date']} close {out['close']:.2f}; live signal {out['live_signal']}; "
          f"5m events {out['events_5m']}; near misses {out['near_misses']}")


if __name__ == "__main__":
    main()
