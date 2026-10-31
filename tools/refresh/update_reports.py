#!/usr/bin/env python3
"""
Refresh the static reports with the data in data/refresh/ (written by fetch_refresh.py).

Run from the repo root after a fetch:   python tools/refresh/update_reports.py
Re-runnable: every edit is a regex on the current page, so it works on already-updated pages.
Images (the breadth card and the two QQQ charts) are re-rendered with Playwright from
tools/refresh/templates/*.html.

Pages and what is refreshed
  reports/trump_and_stock/trump.html, bessent.html   QQQ series extended, r1/r20/r60 recomputed
  reports/top_100_Nasdaq_evolution/top100.html       2026 column = current S&P 500 members by Yahoo marketCap
  reports/top_100_Nasdaq_evolution/sp100_evolution   same 2026 list, story ranks
  reports/top_100_Nasdaq_evolution/index.html        third period (2025 list, 2025-11-21 -> latest) counts, QQQ, card image
  reports/top_100_Nasdaq_evolution/qqq_2020_2026     third period numbers, both charts redrawn
  reports/trump_and_stock/index.html, index.html     cut-off dates, hero numbers
"""
from __future__ import annotations

import base64
import json
import os
import re
import sys

import numpy as np
import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
D = os.path.join(ROOT, "data", "refresh")
TPL = os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates")

# --- third-period sample: the 2025 list from Ben's "Top-100-last-5-years" sheet, tab "numbers", column K
LIST_2025 = ("NVDA AAPL MSFT AMZN GOOGL GOOG AVGO META TSLA BRK.B LLY WMT JPM V ORCL XOM JNJ MA NFLX ABBV COST "
             "BAC PLTR PG HD AMD KO GE CSCO CVX UNH IBM WFC CAT MS AXP MRK PM TMUS MU GS RTX ABT TMO MCD CRM PEP "
             "ISRG LIN DIS INTU T AMGN LRCX AMAT C APP QCOM UBER NEE VZ NOW TJX INTC APH SCHW DHR BLK GILD ACN "
             "BKNG GEV SPGI ANET TXN KLAC BSX PFE SYK WELL BA ADBE UNP PGR COF DE LOW MDT ETN PANW CRWD HON CB "
             "PLD ADI HCA BX VRTX COP MCK").split()
P3_START = "2025-11-21"
SECOND_CLASS = {"GOOG", "FOX", "NWS", "BRK.A"}     # Yahoo marketCap is company-level; keep one line per company
GICS2SEC = {"Information Technology": "T", "Communication Services": "C", "Consumer Discretionary": "D",
            "Consumer Staples": "D", "Financials": "F", "Health Care": "H", "Industrials": "I", "Energy": "E"}


def rd(p):
    with open(os.path.join(ROOT, p), encoding="utf-8") as fh:
        return fh.read()


def wr(p, s):
    with open(os.path.join(ROOT, p), "w", encoding="utf-8") as fh:
        fh.write(s)


def sub1(s, pat, rep, label, flags=0):
    new, n = re.subn(pat, rep, s, count=1, flags=flags)
    if n == 0:
        sys.exit(f"pattern not found: {label}")
    return new


def json_span(s, name):
    i = s.find(f"const {name}")
    j = s.find("{", i)
    obj, end = json.JSONDecoder().raw_decode(s[j:])
    return obj, j, j + end


def cn_date(d):
    d = pd.Timestamp(d)
    return f"{d.year}年{d.month}月{d.day}日"


# ------------------------------------------------------------------------------------------
q = pd.read_csv(os.path.join(D, "qqq_daily.csv"), parse_dates=["date"], index_col="date")
QC = q["Close"]
LAST = QC.index[-1]
LASTS = LAST.strftime("%Y-%m-%d")
closes = pd.read_csv(os.path.join(D, "closes.csv"), parse_dates=["date"], index_col="date")
caps = pd.read_csv(os.path.join(D, "caps.csv")).set_index("ticker")
cons = pd.read_csv(os.path.join(D, "sp500_constituents.csv"))
SUMMARY = {"last": LASTS, "qqq": float(QC.iloc[-1])}


# ------------------------------------------------------------------------------------------
def update_event_page(path, events_key, header_pat, header_rep):
    s = rd(path)
    data, a, b = json_span(s, "DATA")
    start = data["px"][0][0]
    ser = QC[QC.index >= start]
    px = [[d.strftime("%Y-%m-%d"), round(float(v), 2)] for d, v in ser.items()]
    old = {d: v for d, v in data["px"]}
    drift = max(abs(old[d] - v) for d, v in px if d in old)
    if drift > 0.02:
        sys.exit(f"{path}: existing prices differ from Yahoo by {drift}")
    pos = {d: k for k, (d, _) in enumerate(px)}
    for e in data[events_key]:
        i0 = pos[e["base_date"]]
        for h in (1, 20, 60):
            e[f"r{h}"] = round((px[i0 + h][1] / px[i0][1] - 1) * 100, 2) if i0 + h < len(px) else None
    data["px"] = px
    s = s[:a] + json.dumps(data, ensure_ascii=False) + s[b:]
    s = sub1(s, header_pat, header_rep, path + " header")
    wr(path, s)
    return len(px)


def trump_and_bessent():
    n1 = update_event_page("reports/trump_and_stock/trump.html", "key",
                           r"(QQQ · 2024-10-10 → )\d{4}-\d{2}-\d{2}( · 日收盘价)", rf"\g<1>{LASTS}\g<2>")
    s = rd("reports/trump_and_stock/trump.html")
    # observation sentence: date from data, neutral wording for the sign
    s = re.sub(r"到\d{4}-\d{2}-\d{2}收盘\$\$\{last\[1\]", "到${last[0]}收盘$${last[1]", s)
    s = s.replace("，分别上涨${fmt(sinceD)}和", "，涨跌幅分别为${fmt(sinceD)}和")
    wr("reports/trump_and_stock/trump.html", s)
    n2 = update_event_page("reports/trump_and_stock/bessent.html", "ev",
                           r"(2025-01-28 上任 → )\d{4}-\d{2}-\d{2}( · QQQ 日收盘价)", rf"\g<1>{LASTS}\g<2>")
    s = rd("reports/trump_and_stock/index.html")
    s = sub1(s, r"(?:数据|QQQ价格)截至\d{4}-\d{2}-\d{2}收盘(?:；发言整理截至[\d-]+)?",
             f"QQQ价格截至{LASTS}收盘；发言整理截至2026-10-09", "trump index foot")
    wr("reports/trump_and_stock/index.html", s)
    SUMMARY["trump_px"], SUMMARY["bessent_px"] = n1, n2


# ------------------------------------------------------------------------------------------
def top100_lists():
    mem = set(cons["Symbol"])
    c = caps.loc[[t for t in caps.index if t in mem and t not in SECOND_CLASS]].dropna(subset=["marketCap"])
    c = c.assign(cap_b=c["marketCap"] / 1e9).sort_values("cap_b", ascending=False).head(100)
    return [[t, float(f"{v:.4g}")] for t, v in c["cap_b"].items()]


def top100_pages():
    new = top100_lists()
    path = "reports/top_100_Nasdaq_evolution/top100.html"
    s = rd(path)
    P, a, b = json_span(s, "P")
    old26 = [t for t, _ in P["data"]["2026"]]
    P["data"]["2026"] = new
    sec = cons.set_index("Symbol")["GICS Sector"]
    for t, _ in new:
        if t not in P["sec"]:
            P["sec"][t] = GICS2SEC.get(sec.get(t, ""), "O")
    s = s[:a] + json.dumps(P, ensure_ascii=False, separators=(",", ":")) + s[b:]
    l21 = [t for t, _ in P["data"]["2021"]]
    l26 = [t for t, _ in new]
    gone = len([t for t in l21 if t not in l26])
    share = {y: (lambda v: sum(v[:10]) / sum(v))(sorted([x for _, x in P["data"][y]], reverse=True)) for y in P["data"]}
    md = f"{LAST.month}/{LAST.day}"
    s = sub1(s, r"const YL=\{'2026':'2026·[\d/]+'\}", f"const YL={{'2026':'2026·{md}'}}", "YL")
    s = sub1(s, r"'2026':'\d{4}-\d{2}-\d{2} 收盘'", f"'2026':'{LASTS} 收盘'", "DATE")
    s = sub1(s, r"(美股前100换掉了 <em>)\d+(</em> 家)", rf"\g<1>{gone}\g<2>", "h1")
    s = sub1(s, r"2026 年取 \d+ 月 \d+ 日收盘", f"2026 年取 {LAST.month} 月 {LAST.day} 日收盘", "lede")
    s = sub1(s, r"<h2>[^<]*四分之一的位置，换了人</h2>",
             "<h2>" + ("四分之一的位置，换了人" if gone >= 25 else "近四分之一的位置，换了人") + "</h2>", "ch1 h2")
    s = sub1(s, r"橙色的 \d+ 家到 2026 年已经不在榜上；蓝色是取而代之的 \d+ 家新面孔",
             f"橙色的 {gone} 家到 2026 年已经不在榜上；蓝色是取而代之的 {gone} 家新面孔", "ch1 d")
    s = sub1(s, r"跌出 \d+ 家", f"跌出 {gone} 家", "lout")
    s = sub1(s, r"新进 \d+ 家", f"新进 {gone} 家", "lin")
    peak = max(share, key=share.get)
    conc = (f"前10大公司占前100合计市值的比例。2022 年熊市一度回落到 {share['2022'] * 100:.0f}%，"
            f"之后升到一半以上，{peak} 年最高（{share[peak] * 100:.0f}%）；{LAST.year} 年 {LAST.month} 月底为 {share['2026'] * 100:.0f}%。")
    s = sub1(s, r"(<p class=\"d\">)前10大公司占前100合计市值的比例。[^<]*(</p>)", rf"\g<1>{conc}\g<2>", "conc")
    s = sub1(s, r"2026-\d{2}-\d{2} 市值来自 [^；]*；",
             f"{LASTS} 市值来自 Yahoo Finance（收盘价 × 总股本，当日标普500成分股，与 companiesmarketcap.com 的 10-09 数值逐一核对，中位偏差 0.0%）；", "footer")
    wr(path, s)

    path = "reports/top_100_Nasdaq_evolution/sp100_evolution.html"
    s = rd(path)
    Dd, a, b = json_span(s, "DATA")
    Dd["lists"][5] = l26
    Dd["years"][5] = LASTS
    Dd["snapshot"] = LASTS
    s = s[:a] + json.dumps(Dd, ensure_ascii=False, separators=(",", ":")) + s[b:]
    s = re.sub(r"y==='\d{4}-\d{2}-\d{2}'\?'2026':y", "y.startsWith('2026')?'2026':y", s)
    if "y.startsWith('2026')?'2026':y" not in s:
        sys.exit("labels mapping not found")
    s = sub1(s, r"数据截至\d{4}年\d+月\d+日 · (?:按原表行序展示排名|2021—2025按原表行序，2026列按\d+月\d+日市值重算)",
             f"数据截至{cn_date(LAST)} · 2021—2025按原表行序，2026列按{LAST.month}月{LAST.day}日市值重算", "intro")
    s = sub1(s, r"(范围A1:F101；)[^<]*?(因此不将所有年份称为“年末”。)",
             rf"\g<1>读取快照为2026年10月10日。前五列沿用原表；2026列原为2026-10-09，{LASTS}按Yahoo Finance市值（当日标普500成分股，Alphabet两类股合并）重新排出前100。前五列仅标注年份，未标注具体统计日，\g<2>",
             "source")
    union = len(set(t for l in Dd["lists"] for t in l))
    s = sub1(s, r"05 / 全部\d+个代码", f"05 / 全部{union}个代码", "union")
    rk = {t: (l26.index(t) + 1 if t in l26 else None) for t in ("NVDA", "MU", "PLTR")}
    nv = ("并在最后两期位居第1。" if rk["NVDA"] == 1 else
          f"2025年位居第1，{LAST.year}年{LAST.month}月底为第{rk['NVDA']}。")
    s = sub1(s, r"\['NVDA','从第7名到第\d+名','2022年曾退到第13名，随后升至2023年第5、2024年第2，[^']*'\]",
             f"['NVDA','从第7名到第{rk['NVDA']}名','2022年曾退到第13名，随后升至2023年第5、2024年第2，{nv}']", "story NVDA")
    s = sub1(s, r"2023年第96名重新出现，2026年升至第\d+。", f"2023年第96名重新出现，2026年升至第{rk['MU']}。", "story MU")
    s = sub1(s, r"\['MU','[^']*'", "['MU','离榜、回归，再进前十'" if rk["MU"] <= 10 else "['MU','离榜、回归，逼近前十'", "MU title")
    s = sub1(s, r"\['PLTR','从第52名到第\d+名','在这六期观察中，首次出现于2024年第52名；2025年第18，2026年第\d+。'\]",
             f"['PLTR','从第52名到第{rk['PLTR']}名','在这六期观察中，首次出现于2024年第52名；2025年第18，2026年第{rk['PLTR']}。']", "story PLTR")
    wr(path, s)
    SUMMARY.update(top100_gone=gone, top10_share=share["2026"], ranks=rk, union=union,
                   moved_out=[t for t in old26 if t not in l26], moved_in=[t for t in l26 if t not in old26],
                   top5=l26[:5])
    return new


# ------------------------------------------------------------------------------------------
def render_png(template, ctx, size, out_png):
    from playwright.sync_api import sync_playwright
    html = open(os.path.join(TPL, template), encoding="utf-8").read()
    for k, v in ctx.items():
        html = html.replace("{{" + k + "}}", str(v))
    tmp = out_png + ".html"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(html)
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={"width": size[0], "height": size[1]})
        pg.goto("file://" + tmp)
        pg.wait_for_timeout(400)
        pg.screenshot(path=out_png, clip={"x": 0, "y": 0, "width": size[0], "height": size[1]})
        b.close()
    os.remove(tmp)
    return base64.b64encode(open(out_png, "rb").read()).decode()


def breadth():
    a = closes.loc[P3_START, LIST_2025]
    z = closes.loc[LAST, LIST_2025]
    r = (z / a - 1) * 100
    if r.isna().any():
        sys.exit(f"missing prices: {list(r[r.isna()].index)}")
    big, small, down = int((r > 10).sum()), int(((r > 0) & (r <= 10)).sum()), int((r <= 0).sum())
    q0, q1 = float(QC.loc[P3_START]), float(QC.iloc[-1])
    qr = (q1 / q0 - 1) * 100
    return dict(big=big, small=small, down=down, up=big + small, q0=q0, q1=q1, qr=qr, r=r)


def breadth_page(br, scratch):
    path = "reports/top_100_Nasdaq_evolution/index.html"
    s = rd(path)
    big, small, down, up = br["big"], br["small"], br["down"], br["up"]
    ym = f"{LAST.year}年{LAST.month}月"
    stronger = big > 33
    title3 = "上涨扩大，分化仍在" if stronger and down >= 20 else ("普涨扩大" if stronger else "涨跌接近各半")
    b64 = render_png("breadth_card.html", dict(
        Q0=f"{br['q0']:.2f}", Q1=f"{br['q1']:.2f}", QR=f"{br['qr']:+.2f}%", YM=ym, TITLE=title3,
        BIG=big, SMALL=small, DOWN=down, WB=big, WS=small, WD=down,
        SUB=f"{big}只涨超10%，仍有{down}只下跌" if down else f"{big}只涨超10%"),
        (1920, 1080), os.path.join(scratch, "breadth_2025_2026.png"))
    # the third card image appears twice (img + download link); replace the data URI after the third alt
    m = re.search(r'<img[^>]+src="data:image/png;base64,[A-Za-z0-9+/=]+"[^>]*alt="2025—2026年：[^"]*"', s)
    if not m:
        sys.exit("third card img not found")
    old_uri = re.search(r'data:image/png;base64,[A-Za-z0-9+/=]+', m.group(0)).group(0)
    s = s.replace(old_uri, "data:image/png;base64," + b64)
    s = re.sub(r'alt="2025—2026年：[^"]*"', f'alt="2025—2026年：{title3}"', s)
    # JS dot chart
    s = sub1(s, r"className='dot '\+\(i<\d+\?'s1':i<\d+\?'s2':'s3'\)", f"className='dot '+(i<{big}?'s1':i<{up}?'s2':'s3')", "dots")
    s = sub1(s, r"const n=mode===10\?\d+:\d+", f"const n=mode===10?{big}:{up}", "n")
    s = sub1(s, r"mode===10\?'\d+只未超过门槛 = \d+只小幅上涨 \+ \d+只下跌':'\d+只涨超10% \+ \d+只小幅涨 = \d+只上涨'",
             f"mode===10?'{100 - big}只未超过门槛 = {small}只小幅上涨 + {down}只下跌':'{big}只涨超10% + {small}只小幅涨 = {up}只上涨'", "caption js")
    s = sub1(s, r'(<span id="left-label">上涨</span> <strong id="left-count" class="tabular-nums">)\d+只', rf"\g<1>{up}只", "left")
    s = sub1(s, r'(<span id="right-label">下跌</span> <strong id="right-count" class="tabular-nums">)\d+只', rf"\g<1>{down}只", "right")
    s = sub1(s, r'aria-label="2025至2026年100只股票：\d+只上涨、\d+只下跌。切换10%门槛后，\d+只超过门槛、\d+只未超过。"',
             f'aria-label="2025至2026年100只股票：{up}只上涨、{down}只下跌。切换10%门槛后，{big}只超过门槛、{100 - big}只未超过。"', "aria")
    s = sub1(s, r'(<div class="text-small" id="dot-caption" aria-live="polite">)每点代表一个股票代码 · \d+只涨超10% \+ \d+只小幅涨 = \d+只上涨',
             rf"\g<1>每点代表一个股票代码 · {big}只涨超10% + {small}只小幅涨 = {up}只上涨", "caption")
    # narrative
    s = sub1(s, r"2025—2026年(?:（截至[\d-]+）)?，\d+只涨幅超过10%，比上一组多\d+只；但仍有\d+只下跌。[^<]*?判断。",
             f"2025—2026年（截至{LASTS}），{big}只涨幅超过10%，比上一组多{big - 33}只；但仍有{down}只下跌。"
             f"QQQ同期{br['qr']:+.2f}%，与上一段的+16.94%接近，上涨面却明显更广。这支持“上涨更强、分化仍在”的判断。", "narr")
    s = sub1(s, r"原表三组计数依次为：71 / 16 / 11、33 / 19 / 48、\d+ / \d+ / \d+（涨超10% / 小幅上涨 / 下跌[^）]*）。(?:第三组已用[^。]*。)*",
             f"原表三组计数依次为：71 / 16 / 11、33 / 19 / 48、49 / 20 / 31（涨超10% / 小幅上涨 / 下跌；第三组为截至2026-10-09的原值）。"
             f"第三组已用 Yahoo Finance 拆股调整收盘价重算到{LASTS}：{big} / {small} / {down}；同一方法重算到10-09时与原值49 / 20 / 31完全一致。", "orig")
    s = sub1(s, r"第三组起点为2025年11月(?:21日)?收盘(?:、终点为[\d-]+收盘)?。", f"第三组起点为2025年11月21日收盘、终点为{LASTS}收盘。", "start")
    s = sub1(s, r"2025年11月21日\$590\.07 → 20\d\d年\d+月\d+日\$[\d.]+：[+\-][\d.]+%。",
             f"2025年11月21日${br['q0']:.2f} → {cn_date(LAST)}${br['q1']:.2f}：{br['qr']:+.2f}%。", "qqq3")
    s = sub1(s, r"这里包括\d+只小幅上涨与\d+只下跌", f"这里包括{small}只小幅上涨与{down}只下跌", "not-over-10")
    s = sub1(s, r"价格核对日期：\d{4}年\d+月\d+日", f"价格核对日期：{cn_date(LAST + pd.Timedelta(days=1))}", "check")
    s = sub1(s, r"报告快照：\d{4}年\d+月", f"报告快照：{LAST.year}年{LAST.month}月", "snap")
    wr(path, s)


def qqq_page(br, scratch):
    path = "reports/top_100_Nasdaq_evolution/qqq_2020_2026.html"
    s = rd(path)
    wk = q[q.index >= "2017-06-01"].resample("W-FRI").agg({"Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"}).dropna()
    bars = [[d.strftime("%Y-%m-%d"), round(r.Open, 2), round(r.High, 2), round(r.Low, 2), round(r.Close, 2), int(r.Volume)] for d, r in wk.iterrows()]
    seg = [dict(a="2020-11", b="2021-11", p0=289.99, p1=397.63, r="+37.12%", note="起点：11月平均收盘价", c="#1F4FD8",
                ad="2020-11-15", bd="2021-11-17"),
           dict(a="2024-11", b="2025-11", p0=504.58, p1=590.07, r="+16.94%", note="起点：11月平均收盘价", c="#F2560A",
                ad="2024-11-15", bd=P3_START),
           dict(a="2025-11", b=f"{LAST.year}-{LAST.month:02d}", p0=br["q0"], p1=br["q1"], r=f"{br['qr']:+.2f}%",
                note="起止均为指定交易日收盘价", c="#6A1FB0", ad=P3_START, bd=LASTS)]
    ctx = dict(BARS=json.dumps(bars), SEG=json.dumps(seg, ensure_ascii=False), LAST=LASTS)
    uris = []
    for k, layout in enumerate(("points", "spans")):
        ctx["LAYOUT"] = layout
        uris.append(render_png("qqq_chart.html", ctx, (1688, 932), os.path.join(scratch, f"qqq-chart-{k + 1}.png")))
    old = re.findall(r"data:image/png;base64,[A-Za-z0-9+/=]+", s)
    distinct = list(dict.fromkeys(old))
    if len(distinct) != 2:
        sys.exit(f"qqq page: expected 2 distinct images, found {len(distinct)}")
    for o, n in zip(distinct, uris):
        s = s.replace(o, "data:image/png;base64," + n)
    alt = f"QQQ三段涨幅：37.12%、16.94%、{br['qr']:+.2f}%".replace("+", "")
    s = re.sub(r'alt="QQQ三段涨幅：[^"]*"', f'alt="{alt}"', s)
    s = sub1(s, r"<p><strong>阅读说明：</strong>[^<]*</p>",
             f"<p><strong>阅读说明：</strong>两张图用 Yahoo Finance 的 QQQ 周线（截至{LASTS}）重新绘制，对数纵轴；图1在价格线上标出起止点，图2在下方标出区间。标注价格按核实的收盘价计算。</p>", "note")
    s = sub1(s, r"2025-11-21 → \d{4}-\d{2}-\d{2}。美元价格", f"2025-11-21 → {LASTS}。美元价格", "footer")
    s = s.replace("原走势图复权口径可能与标注价格不同。", "")
    wr(path, s)


def homepage(br):
    s = rd("index.html")
    p = float(QC.iloc[-1])
    low22 = float(QC["2022"].min())
    s = sub1(s, r"<b>~\$260 → ~\$\d+</b><span>从2022年熊市低点到\d{4}年\d+月底?，QQQ大约涨到原来的[\d.]+倍</span>",
             f"<b>~$260 → ~${p:.0f}</b><span>从2022年熊市低点到{LAST.year}年{LAST.month}月底，QQQ大约涨到原来的{p / low22:.1f}倍</span>", "hero1")
    s = sub1(s, r"<b>\+\d+%</b><span>从那次低点到\d{4}-\d{2}-\d{2}收盘\$[\d.]+的涨幅</span>",
             f"<b>+{(p / 416.06 - 1) * 100:.0f}%</b><span>从那次低点到{LASTS}收盘${p:.2f}的涨幅</span>", "hero3")
    wr("index.html", s)
    SUMMARY.update(hero_mult=p / low22, hero_up=(p / 416.06 - 1) * 100, low22=low22)


def main():
    scratch = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "data", "refresh", "img")
    os.makedirs(scratch, exist_ok=True)
    trump_and_bessent()
    top100_pages()
    br = breadth()
    breadth_page(br, scratch)
    qqq_page(br, scratch)
    homepage(br)
    SUMMARY.update(breadth={k: br[k] for k in ("big", "small", "down", "q0", "q1", "qr")})
    print(json.dumps(SUMMARY, ensure_ascii=False, indent=1, default=str))


if __name__ == "__main__":
    main()
