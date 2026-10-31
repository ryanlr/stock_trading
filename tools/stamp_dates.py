#!/usr/bin/env python3
"""
Stamp "最近更新" (last-updated) dates onto the site.

* Every tracked page gets a small strip at the top: 最近更新：YYYY-MM-DD
* index.html gets the site-wide latest date in the top-right of its header bar,
  and each report card shows its own page's date next to the file name.

A page's date is the date of the last commit that changed its *content*. Everything this
script writes sits between <!--upd--> and <!--/upd--> markers and is stripped before comparing,
so stamping never counts as an update (the script is idempotent and safe to run on every push).
Uncommitted changes in the working tree count as today. Dates are US Pacific (site owner's time).

Run from the repo root:  python tools/stamp_dates.py
Needs full git history (actions/checkout with fetch-depth: 0).
"""
from __future__ import annotations

import datetime as dt
import os
import re
import subprocess
import sys
from zoneinfo import ZoneInfo

TZ = ZoneInfo("America/Los_Angeles")
MARK = re.compile(r"<!--upd-->.*?<!--/upd-->", re.S)
STRIP_STYLE = ("display:block;text-align:right;font:12px/1.6 system-ui,-apple-system,'PingFang SC',"
               "'Microsoft YaHei',sans-serif;color:#5B6875;background:#F5F7FA;padding:4px 16px;"
               "border-bottom:1px solid #E3E8EE;margin:0")


def git(*args: str) -> str:
    return subprocess.run(["git", *args], capture_output=True, text=True, check=False).stdout


def strip(text: str) -> str:
    return MARK.sub("", text)


def content_date(path: str) -> dt.date:
    today = dt.datetime.now(TZ).date()
    head = git("show", f"HEAD:{path}")
    if not head:                                   # new, uncommitted file
        return today
    with open(path, encoding="utf-8") as fh:
        if strip(fh.read()) != strip(head):        # edited in the working tree
            return today
    for line in git("log", "--format=%H %cI", "--", path).splitlines():
        sha, when = line.split(" ", 1)
        cur = git("show", f"{sha}:{path}")
        prev = git("show", f"{sha}^:{path}")
        if not prev or strip(cur) != strip(prev):
            return dt.datetime.fromisoformat(when).astimezone(TZ).date()
    return today


def stamp_page(text: str, d: dt.date) -> str:
    text = MARK.sub("", text)
    badge = f'<!--upd--><div class="upd-strip" style="{STRIP_STYLE}">最近更新：{d:%Y-%m-%d}</div><!--/upd-->'
    m = re.search(r"<body[^>]*>", text, re.I)
    if m:
        return text[:m.end()] + badge + text[m.end():]
    m = re.search(r"<main[\s>]", text, re.I)
    if m:
        return text[:m.start()] + badge + text[m.start():]
    sys.exit("no <body> or <main> to anchor the date strip")


def stamp_index(text: str, dates: dict[str, dt.date], latest: dt.date) -> str:
    text = MARK.sub("", text)
    # top-right of the header bar, after the existing nav links
    badge = (f'<!--upd--><style>.bar nav{{align-items:center}}.bar nav a{{white-space:nowrap}}'
             f'.upd-top{{font-size:12.5px;color:var(--muted);white-space:nowrap}}'
             f'.upd-top b{{color:var(--ink);font-family:var(--mono);font-weight:600}}'
             f'.upd-card{{margin-top:auto;padding-top:8px;font-family:var(--mono);font-size:11.5px;color:var(--muted)}}'
             f'a.card .upd-card+.f{{margin-top:0;padding-top:2px}}'
             f'@media (max-width:560px){{.upd-top .lbl{{display:none}}}}</style>'
             f'<span class="upd-top"><span class="lbl">最近更新 </span><b>{latest:%Y-%m-%d}</b></span><!--/upd-->')
    text, n = re.subn(r'(<nav aria-label="站点">.*?)(</nav>)', lambda m: m.group(1) + badge + m.group(2), text, count=1, flags=re.S)
    if not n:
        sys.exit("index.html: header nav not found")
    # each card: a date line just above its footer (<span class="f">)
    def card(m: re.Match) -> str:
        d = dates.get(os.path.normpath(m.group(1)))
        if not d:
            return m.group(0)
        return m.group(0) + f'<!--upd--><span class="upd-card">更新于 {d:%Y-%m-%d}</span><!--/upd-->'
    text = re.sub(r'<a class="card" href="([^"]+)"[^>]*>(?:(?!</a>).)*?(?=<span class="f">)', card, text, flags=re.S)
    return text


def main() -> None:
    pages = [p for p in git("ls-files", "*.html").split() if os.path.exists(p)]
    dates = {p: content_date(p) for p in pages}
    latest = max(dates.values())
    changed = []
    for p in pages:
        with open(p, encoding="utf-8") as fh:
            old = fh.read()
        new = stamp_index(old, dates, latest) if p == "index.html" else stamp_page(old, dates[p])
        if new != old:
            with open(p, "w", encoding="utf-8") as fh:
                fh.write(new)
            changed.append(p)
    for p in pages:
        print(f"{dates[p]}  {p}{'  (stamped)' if p in changed else ''}")
    print(f"site latest: {latest}")


if __name__ == "__main__":
    main()
