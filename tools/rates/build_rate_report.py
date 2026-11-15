#!/usr/bin/env python3
"""
Build reports/rate_hikes/index.html — "加息会让股市跌吗？用 QQQ 看五轮加息".

Data: QQQ daily adjusted close (skills/market-risk-playbook/data/qqq_daily.csv, Yahoo Finance, 1999-03 →)
and every FOMC target change since 1999 (tools/rates/fed_moves.py).
Run from the repo root:  python tools/rates/build_rate_report.py
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fed_moves import MOVES, START_RATE  # noqa: E402

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
q = pd.read_csv(os.path.join(ROOT, "skills/market-risk-playbook/data/qqq_daily.csv"), parse_dates=["date"], index_col="date")["adj_close"]
LAST = q.index[-1]
m = pd.DataFrame(MOVES, columns=["d", "r"])
m["d"] = pd.to_datetime(m["d"])
m["chg"] = m["r"].diff().fillna(m["r"].iloc[0] - START_RATE)
m["sgn"] = np.sign(m["chg"])
m["cyc"] = (m["sgn"] != m["sgn"].shift()).cumsum()
assert m["d"].isin(q.index).all()

ORANGE, BLUE, INK, GREY, UP, DN = "#D9840F", "#1B86B8", "#0F2240", "#8A96A3", "#D64545", "#1E9E6A"


def pct(x, d=1):
    return "—" if x is None or (isinstance(x, float) and np.isnan(x)) else f"{x * 100:+.{d}f}%"


def cls(x):
    return "" if x is None else ("pos" if x >= 0 else "neg")


cycles = []
for _, g in m.groupby("cyc"):
    a, b = g["d"].iloc[0], g["d"].iloc[-1]
    ongoing = g["sgn"].iloc[0] > 0 and b == m["d"].iloc[-1]
    end = LAST if ongoing else b
    seg = q[a:end]
    ia, ib = q.index.get_loc(a), q.index.get_loc(b)
    cycles.append(dict(
        hike=g["sgn"].iloc[0] > 0, a=a, b=b, end=end, n=len(g), bp=int(round(g["chg"].sum() * 100)),
        r0=float(g["r"].iloc[0] - g["chg"].iloc[0]), r1=float(g["r"].iloc[-1]), ongoing=ongoing,
        ret=float(seg.iloc[-1] / seg.iloc[0] - 1), dd=float((seg / seg.cummax() - 1).min()),
        pre=float(q.iloc[ia] / q.iloc[ia - 126] - 1) if ia >= 126 else None,
        after=float(q.iloc[ib + 252] / q.iloc[ib] - 1) if (ib + 252 < len(q) and not ongoing) else None))
H = [c for c in cycles if c["hike"]]
C = [c for c in cycles if not c["hike"]]
Hdone = [c for c in H if not c["ongoing"]]

ev = {}
for h in (1, 20, 60, 250):
    f = q.shift(-h) / q - 1
    row = {}
    for k, ds in (("hike", m[m["sgn"] > 0]["d"]), ("cut", m[m["sgn"] < 0]["d"])):
        x = f[ds].dropna()
        row[k] = (float(x.mean()), float((x > 0).mean()), int(len(x)))
    x = f.dropna()
    row["all"] = (float(x.mean()), float((x > 0).mean()), int(len(x)))
    ev[h] = row
r1 = q.pct_change()
day_h = r1[m[m["sgn"] > 0]["d"]]
day_c = r1[m[m["sgn"] < 0]["d"]]


# ---------------------------------------------------------------- charts
def main_chart():
    W, Hh, L, R = 1000, 520, 56, 20
    p0, p1, f0, f1 = 16, 360, 392, 490
    w = q.resample("W-FRI").last().dropna()
    t0, t1 = w.index[0], LAST
    X = lambda d: L + (W - L - R) * ((pd.Timestamp(d) - t0).days / (t1 - t0).days)  # noqa: E731
    lo, hi = np.log(w.min() * 0.9), np.log(w.max() * 2.6)
    Y = lambda v: p1 - (p1 - p0) * (np.log(v) - lo) / (hi - lo)  # noqa: E731
    FY = lambda v: f1 - (f1 - f0) * v / 7.0  # noqa: E731
    o = [f'<svg viewBox="0 0 {W} {Hh}" class="chart big" role="img" aria-label="QQQ 走势与美联储加息、降息周期">']
    for c in cycles:
        col = ORANGE if c["hike"] else BLUE
        x0, x1 = X(c["a"]), max(X(c["end"]), X(c["a"]) + 3)
        o.append(f'<rect x="{x0:.1f}" y="{p0}" width="{x1 - x0:.1f}" height="{f1 - p0}" fill="{col}" opacity=".13"/>')
        lab = f"{'加息' if c['hike'] else '降息'} {pct(c['ret'], 0)}" + ("（进行中）" if c["ongoing"] else "")
        anchor = "end" if c["ongoing"] else "middle"
        xx = x1 if c["ongoing"] else (x0 + x1) / 2
        o.append(f'<text x="{xx:.1f}" y="{p0 + (46 if c["ongoing"] else 14 if c["hike"] else 30)}" text-anchor="{anchor}" class="lb" fill="{col}" font-weight="700">{lab}</text>')
    for v in (20, 50, 100, 200, 400, 700):
        if w.min() * 0.9 < v < w.max() * 1.05:
            o.append(f'<line x1="{L}" x2="{W - R}" y1="{Y(v):.1f}" y2="{Y(v):.1f}" stroke="var(--grid)"/><text x="{L - 6}" y="{Y(v) + 4:.1f}" text-anchor="end" class="ax">{v}</text>')
    for y in range(2000, LAST.year + 1, 2):
        o.append(f'<text x="{X(f"{y}-01-01"):.1f}" y="{Hh - 8}" text-anchor="middle" class="ax">{y}</text>')
    o.append(f'<polyline points="{" ".join(f"{X(d):.1f},{Y(v):.1f}" for d, v in w.items())}" fill="none" stroke="{INK}" stroke-width="1.5"/>')
    o.append(f'<text x="{W - R - 4}" y="{p1 - 6}" text-anchor="end" class="pt">QQQ（含分红复权，对数坐标）</text>')
    # fed target step
    pts, rate = [(X(t0), FY(START_RATE))], START_RATE
    for d, r in zip(m["d"], m["r"]):
        pts += [(X(d), FY(rate)), (X(d), FY(r))]
        rate = r
    pts.append((X(t1), FY(rate)))
    for v in (0, 2, 4, 6):
        o.append(f'<line x1="{L}" x2="{W - R}" y1="{FY(v):.1f}" y2="{FY(v):.1f}" stroke="var(--grid)"/><text x="{L - 6}" y="{FY(v) + 4:.1f}" text-anchor="end" class="ax">{v}%</text>')
    o.append(f'<polyline points="{" ".join(f"{x:.1f},{y:.1f}" for x, y in pts)}" fill="none" stroke="{ORANGE}" stroke-width="1.8"/>')
    o.append(f'<text x="{L + 4}" y="{f0 - 4}" class="pt">联邦基金目标利率（区间上限）</text>')
    o.append("</svg>")
    return "".join(o)


def bar_chart():
    W, Hh, L, R, T, B = 1000, 300, 50, 16, 20, 70
    items = [(c, f"{c['a'].year}–{str(c['end'].year)[2:]}") for c in cycles]
    vals = [c["ret"] * 100 for c, _ in items]
    lo, hi = min(min(vals), 0) - 8, max(vals) + 10
    Y = lambda v: T + (Hh - T - B) * (hi - v) / (hi - lo)  # noqa: E731
    bw = (W - L - R) / len(items)
    o = [f'<svg viewBox="0 0 {W} {Hh}" class="chart big" role="img" aria-label="每一轮加息和降息期间 QQQ 的涨跌">']
    for v in range(int(lo // 20 * 20), int(hi) + 1, 20):
        o.append(f'<line x1="{L}" x2="{W - R}" y1="{Y(v):.1f}" y2="{Y(v):.1f}" stroke="{"var(--rule)" if v == 0 else "var(--grid)"}"/><text x="{L - 6}" y="{Y(v) + 4:.1f}" text-anchor="end" class="ax">{v:+d}%</text>')
    for i, (c, lab) in enumerate(items):
        col = ORANGE if c["hike"] else BLUE
        x = L + bw * i + bw * 0.18
        v = c["ret"] * 100
        o.append(f'<rect x="{x:.1f}" y="{min(Y(v), Y(0)):.1f}" width="{bw * 0.64:.1f}" height="{abs(Y(v) - Y(0)):.1f}" fill="{col}" opacity="{0.45 if c["ongoing"] else 0.9}"/>')
        o.append(f'<text x="{x + bw * 0.32:.1f}" y="{(Y(v) - 6) if v >= 0 else (Y(v) + 15):.1f}" text-anchor="middle" class="lb" font-weight="700" fill="{col}">{v:+.0f}%</text>')
        o.append(f'<text x="{x + bw * 0.32:.1f}" y="{Hh - B + 18}" text-anchor="middle" class="ax">{lab}</text>'
                 f'<text x="{x + bw * 0.32:.1f}" y="{Hh - B + 34}" text-anchor="middle" class="lb" fill="{col}">{"加息" if c["hike"] else "降息"}{c["bp"]:+d}bp</text>'
                 + (f'<text x="{x + bw * 0.32:.1f}" y="{Hh - B + 50}" text-anchor="middle" class="ax">进行中</text>' if c["ongoing"] else ""))
    o.append("</svg>")
    return "".join(o)


def cyc_rows(lst):
    out = ""
    for c in lst:
        out += (f"<tr><td>{c['a']:%Y-%m-%d} → {'至今' if c['ongoing'] else format(c['b'], '%Y-%m-%d')}</td>"
                f"<td class='n'>{c['n']} 次，{c['r0']:.2f}% → {c['r1']:.2f}%</td>"
                f"<td class='n {cls(c['pre'])}'>{pct(c['pre'])}</td>"
                f"<td class='n {cls(c['ret'])}'><b>{pct(c['ret'])}</b></td><td class='n neg'>{pct(c['dd'])}</td>"
                f"<td class='n {cls(c['after'])}'>{pct(c['after'])}</td></tr>")
    return out


ev_rows = ""
for h, name in ((1, "次日"), (20, "20 个交易日后"), (60, "60 个交易日后"), (250, "250 个交易日后（约一年）")):
    e = ev[h]
    ev_rows += (f"<tr><td>{name}</td>" + "".join(
        f"<td class='n {cls(e[k][0])}'>{pct(e[k][0], 2)}<br><span class='note'>上涨 {e[k][1] * 100:.0f}% · n={e[k][2]:,}</span></td>" for k in ("hike", "cut", "all")) + "</tr>")

h_up = sum(1 for c in Hdone if c["ret"] > 0)
c_dn = sum(1 for c in C if c["ret"] < 0)
cur = [c for c in H if c["ongoing"]]
cur_txt = ""
if cur:
    c = cur[0]
    cur_txt = (f"<p><b>眼下这一轮</b>：{c['a']:%Y年%-m月%-d日}美联储把利率上调到 {c['r1'] - 0.25:.2f}%–{c['r1']:.2f}%，是 2023 年 7 月以来第一次加息。"
               f"从那天到 {LAST:%Y-%m-%d}，QQQ {pct(c['ret'])}，期间最大回撤 {pct(c['dd'])}。时间太短，还不能算一轮完整的样本；"
               f"而且这段下跌里有中期选举后 AI 股的抛售和英伟达事件，不能都算到加息头上。</p>")
w22 = [c for c in H if c["a"].year == 2022][0]
w99 = [c for c in H if c["a"].year == 1999][0]
peak21 = float(q["2021-11-01":"2021-12-31"].max())
low22 = float(q["2022"].min())

CSS = """
:root{--paper:#F5F7FA;--sheet:#FFFFFF;--ink:#0F2240;--text:#1C2B3D;--muted:#5B6875;--rule:#D9E0E7;--grid:#EDF1F5;--link:#1E3A5F;--up:#D64545;--dn:#1E9E6A;
--display:"Noto Serif SC","Songti SC",serif;--body:"Noto Sans SC","PingFang SC","Microsoft YaHei",system-ui,sans-serif;--mono:"JetBrains Mono",ui-monospace,Menlo,monospace;color-scheme:light}
*,*::before,*::after{box-sizing:border-box}
body{margin:0;background:var(--paper);color:var(--text);font-family:var(--body);font-size:15.5px;line-height:1.75}
a{color:var(--link)}.wrap{max-width:1040px;margin:0 auto;padding-inline:16px}
.bar{border-bottom:1px solid var(--rule);background:var(--sheet)}.bar .wrap{display:flex;justify-content:space-between;gap:12px;padding-block:12px;font-size:14px}
.bar a{text-decoration:none;color:var(--muted)}.bar a.home{color:var(--ink);font-weight:700}
header.hero{padding-block:30px 6px}.kicker{font-family:var(--mono);font-size:12px;letter-spacing:.08em;color:#1B86B8}
h1{font-family:var(--display);font-weight:900;color:var(--ink);font-size:clamp(28px,4.4vw,42px);line-height:1.2;margin:.25em 0 .4em}
h2{font-family:var(--display);font-weight:600;font-size:23px;color:var(--ink);margin:0 0 10px;border-bottom:2px solid var(--ink);padding-bottom:6px}
.lede{font-size:17px;max-width:78ch;margin:0}.lede b{color:var(--ink)}
.verdict{display:inline-block;background:#FFF3DC;color:#7A4E00;border:1px solid #F0D49B;border-radius:4px;padding:1px 10px;font-weight:700;margin-right:6px}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:1px;background:var(--rule);border:1px solid var(--rule);margin:20px 0 6px}
.tiles div{background:var(--sheet);padding:12px 14px;display:flex;flex-direction:column;gap:2px}
.tiles b{font-family:var(--mono);font-size:21px;font-weight:600;color:var(--ink)}.tiles span{font-size:12.5px;color:var(--muted)}
section{background:var(--sheet);border:1px solid var(--rule);padding:20px 20px 16px;margin:18px 0}
.note{font-size:13px;color:var(--muted)}.scroll{overflow-x:auto;-webkit-overflow-scrolling:touch}
.chart{width:100%;height:auto;display:block}.chart.big{min-width:720px}
.ax{font:10.5px var(--mono);fill:var(--muted)}.lb{font:11.5px var(--body);paint-order:stroke;stroke:#fff;stroke-width:3px;stroke-linejoin:round}.pt{font:11.5px var(--body);fill:var(--muted)}
.legend{display:flex;flex-wrap:wrap;gap:4px 16px;font-size:12.5px;color:var(--muted);margin:6px 0 0}.legend i{display:inline-block;width:14px;height:8px;margin-right:5px;vertical-align:middle}
table{width:100%;border-collapse:collapse;font-size:14px}th,td{padding:6px 8px;border-bottom:1px solid var(--grid);text-align:left;vertical-align:top}
th{font-size:12.5px;color:var(--muted);font-weight:500}td.n,th.n{font-family:var(--mono);text-align:right;white-space:nowrap}
.pos{color:var(--up)}.neg{color:var(--dn)}
.callout{border-left:4px solid #D9840F;background:#FFF8EC;padding:10px 14px;margin:12px 0;font-size:14.5px}
footer{padding-block:18px 40px;font-size:12.5px;color:var(--muted)}
@media (max-width:560px){section{padding:16px 13px}th,td{padding:5px 5px}table{font-size:13px}}
"""

e60, e250 = ev[60], ev[250]
page = f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<script async src="https://www.googletagmanager.com/gtag/js?id=G-2G0J05CN16"></script><script>window.dataLayer=window.dataLayer||[];function gtag(){{dataLayer.push(arguments);}}gtag('js',new Date());gtag('config','G-2G0J05CN16');</script>
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>加息会让股市跌吗？用 QQQ 看五轮加息 · 老王看美股</title>
<meta name="description" content="1999 年以来美联储的每一次加息和降息，对照 QQQ 的走势：四轮完整加息期间 QQQ 全部上涨，降息期间反而多数下跌。">
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Noto+Serif+SC:wght@600;900&family=Noto+Sans+SC:wght@400;500;700&family=JetBrains+Mono:wght@400;600&display=swap">
<style>{CSS}</style></head><body>
<div class="bar"><div class="wrap"><a class="home" href="../../">← 老王看美股</a><a href="../">全部报告</a></div></div>
<main class="wrap">
<header class="hero">
<div class="kicker">QQQ · 1999-03 → {LAST:%Y-%m-%d} · 美联储 {int((m['sgn'] > 0).sum())} 次加息、{int((m['sgn'] < 0).sum())} 次降息</div>
<h1>加息会让股市跌吗？用 QQQ 看五轮加息</h1>
<p class="lede"><span class="verdict">历史上：加息本身没有压垮 QQQ</span>1999 年以来美联储有 {len(Hdone)} 轮完整的加息周期，从第一次加息到最后一次加息，QQQ <b>{h_up} 轮全部上涨</b>（{'、'.join(pct(c['ret'], 0) for c in Hdone)}）。
反过来，{len(C)} 轮降息周期里 QQQ 有 <b>{c_dn} 轮下跌</b>。单看每一次加息之后：60 个交易日平均 {pct(e60['hike'][0])}，和任意一天买入的 {pct(e60['all'][0])} 几乎一样；一年后 {pct(e250['hike'][0])} 对 {pct(e250['all'][0])}。
但“加息不影响股市”说得太满：<b>2022 年</b>那一轮中途最深回撤 {pct(w22['dd'], 0)}，而 <b>2000 年</b>加息结束后一年 QQQ 跌了 {pct(w99['after'], 0).lstrip('-')}。更准确的说法是：<b>加息不是卖出的理由，为什么加息才是。</b></p>
<div class="tiles">
<div><b>{h_up} / {len(Hdone)}</b><span>完整加息周期里 QQQ 上涨的轮数</span></div>
<div><b>{c_dn} / {len(C)}</b><span>降息周期里 QQQ 下跌的轮数</span></div>
<div><b>{pct(e250['hike'][0], 0)} vs {pct(e250['all'][0], 0)}</b><span>加息后一年 vs 任意一天买入后一年</span></div>
<div><b>{pct(float(day_h.mean()), 2)}</b><span>加息当天 QQQ 平均涨跌（{(day_h > 0).mean() * 100:.0f}% 上涨）</span></div>
</div>
</header>

<section><h2>一张图：QQQ 与每一轮加息、降息</h2>
<div class="scroll">{main_chart()}</div>
<div class="legend"><span><i style="background:{ORANGE};opacity:.4"></i>加息周期（第一次加息 → 最后一次加息）</span><span><i style="background:{BLUE};opacity:.4"></i>降息周期</span><span>标注的百分比 = 该周期内 QQQ 的涨跌</span></div>
<p class="note">橙色区域里价格线多数向上，蓝色区域里多数向下。原因不神秘：美联储在经济强、通胀高的时候加息，在经济出问题的时候降息。股市跟着的是经济和盈利，利率只是同一件事的另一面。</p>
</section>

<section><h2>每一轮的账</h2>
<div class="scroll">{bar_chart()}</div>
<h3 style="margin:18px 0 6px;font-size:16.5px;color:var(--ink)">加息周期</h3>
<div class="scroll"><table><tr><th>周期</th><th class="n">加息</th><th class="n">首次加息前半年</th><th class="n">周期内 QQQ</th><th class="n">期间最大回撤</th><th class="n">最后一次加息后一年</th></tr>{cyc_rows(H)}</table></div>
<h3 style="margin:18px 0 6px;font-size:16.5px;color:var(--ink)">降息周期</h3>
<div class="scroll"><table><tr><th>周期</th><th class="n">降息</th><th class="n">首次降息前半年</th><th class="n">周期内 QQQ</th><th class="n">期间最大回撤</th><th class="n">最后一次降息后一年</th></tr>{cyc_rows(C)}</table></div>
<p class="note">周期内涨跌 = 第一次利率变动当天收盘 → 最后一次变动当天收盘（进行中的周期算到 {LAST:%Y-%m-%d}）。收益用含分红的复权价。</p>
{cur_txt}
</section>

<section><h2>每一次加息之后</h2>
<p>把 {ev[1]['hike'][2]} 次加息、{ev[1]['cut'][2]} 次降息当作事件，看决议日收盘买入 QQQ 之后的表现，再和“任意一个交易日买入”比：</p>
<div class="scroll"><table><tr><th>持有到</th><th class="n">加息日买入</th><th class="n">降息日买入</th><th class="n">任意一天买入</th></tr>{ev_rows}</table></div>
<p class="note">加息当天 QQQ 平均 {pct(float(day_h.mean()), 2)}，降息当天平均 {pct(float(day_c.mean()), 2)}（全部交易日平均 {pct(float(r1.mean()), 2)}）。加息通常事先已被市场定价，“靴子落地”当天反而常常上涨。这些事件彼此靠得很近、收益窗口重叠，不能当作 {ev[1]['hike'][2]} 个独立样本，只适合看方向。</p>
</section>

<section><h2>必须说清的几点</h2>
<div class="callout">
① <b>样本只有 {len(Hdone)} 轮。</b>四轮都涨不等于下一轮也涨，这是描述历史，不是规律。<br>
② <b>2022 年是反例的一半。</b>那一轮从首次加息到最后一次加息 QQQ 是 {pct(w22['ret'], 0)}，但下跌发生得更早：QQQ 在 2021 年 11 月见顶（复权价约 ${peak21:.0f}），到 2022 年底的低点（约 ${low22:.0f}）跌了 {pct(low22 / peak21 - 1, 0)}，大半跌幅出现在市场“预期加息”和加息的前半程。市场交易的是预期，不是决议本身。<br>
③ <b>2000 年是另一种教训。</b>加息期间 QQQ 涨了 {pct(w99['ret'], 0)}，加息停下后的一年跌了 {pct(w99['after'], 0).lstrip('-')}。泡沫是在加息里吹大、在加息结束后破的。<br>
④ <b>因果是反的。</b>加息不“导致”上涨，降息也不“导致”下跌。美联储因为经济强才加息、因为经济坏才降息，QQQ 反映的是背后的经济和盈利。真正伤股市的是加息的原因和幅度：{w22['n']} 次、{w22['bp']}bp、为了压 9% 的通胀（2022），和 9 次、225bp、慢慢回到正常（2015–18）不是一回事。<br>
⑤ <b>只看了 QQQ。</b>QQQ 偏科技成长股，对利率（估值折现）理论上更敏感；连它都没有在加息里系统性下跌，但换成小盘股、地产或银行，结论可能不同。<br>
⑥ <b>“利率”这里指联邦基金目标利率。</b>长端利率（如 10 年期美债收益率）由市场决定，走势和政策利率不总是同步，本页没有检验它与 QQQ 的关系。
</div></section>

<footer>
<p><b>数据</b>：QQQ 日线复权收盘价（Yahoo Finance，1999-03-10 起，截至 {LAST:%Y-%m-%d}）；美联储历次利率决议（联邦公开市场委员会声明，1999 年 6 月至 2026 年 9 月共 {len(m)} 次变动，目标区间取上限）。</p>
<p><b>方法</b>：连续同方向的利率变动算一轮周期。代码见 <a href="https://github.com/ryanlr/stock_trading/tree/main/tools/rates">GitHub</a>。</p>
<p>研究记录，不构成投资建议。历史统计不代表未来。</p>
</footer>
</main></body></html>
"""
out = os.path.join(ROOT, "reports", "rate_hikes")
os.makedirs(out, exist_ok=True)
with open(os.path.join(out, "index.html"), "w", encoding="utf-8") as fh:
    fh.write(page)
print("wrote reports/rate_hikes/index.html", LAST.date(), [round(c["ret"], 3) for c in cycles], peak21, low22)
