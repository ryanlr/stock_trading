---
name: market-risk-playbook
description: Build or update the daily QQQ buy-point radar (prediction.html, Chinese) — "washout in uptrend" signal from price, volume, RSI and VXN with a validated backtest, a 5-month annotated chart, the QQQ option-chain read, and a forward projection. Use when asked to generate, update, explain or extend the playbook / prediction.html / QQQ buy points.
---

# QQQ 买点雷达 (QQQ buy-point radar)

A daily page for 老王看美股 (`prediction.html` at the repo root) that answers: **is this a buying
point for QQQ, why (in numbers), did that kind of point work before, and what do options and history
say about the next few weeks?**

It began as a Chinese re-implementation of Balder's Market Risk Playbook (how that page works is in
`references/balder-analysis.md`); the current version keeps Balder's discipline — pre-register,
test against nulls, publish failures — but is built around a QQQ buy signal. The full research
record (hypothesis, every test, what failed) is in `references/signal-research.md`. Read it before
changing the rule.

## Data (all from Yahoo Finance, via `scripts/fetch_data.py`)

| Input | Symbol | Used for |
|---|---|---|
| Daily OHLC + volume, 1999→ | `QQQ` (split-adjusted Close and dividend-adjusted Adj Close) | trend, pullback, RSI, MACD, volume, forward returns, chart |
| Nasdaq-100 implied-vol index | `^VXN` (2001→) | the option-market "fear" leg of the signal (historical option chains are not available on Yahoo) |
| VIX, NDX | `^VIX`, `^NDX` | reference only |
| Full option chain, expiries ≤ 70 days | `QQQ` | today's read: walls, gamma flip, max pain, put/call, skew, term structure, risk-neutral probabilities, option-implied cone |

Every run archives the chain as `data/options/qqq_chain_YYYY-MM-DD.csv.gz` so option signals can be
backtested once enough history accumulates.

## The signal: 上升趋势中的恐慌出清 (washout in uptrend)

Judged at the close; all four must hold; repeats within 5 sessions are one event (`analysis.RULE`):

1. **Trend** — adjusted close > 200-day average.
2. **Pullback** — ≥ 5% below the 63-session high.
3. **Oversold** — RSI(2) ≤ 5.
4. **Fear** — volume ≥ 1.5× trailing 20-day median (on monthly-opex Fridays divided first by the historical median opex volume ratio, ≈1.13×), **and** VXN ≥ 10% above its trailing 20-day mean.

Rationale: short-term reversal in index ETFs plus the variance-risk-premium effect (Bollerslev–Tauchen–Zhou 2009) — forced selling and overpaid hedging inside an intact uptrend tend to reverse.

## What the backtest says (2001-03 → 2026-10, 25 completed events)

- 5-day: +1.80% mean, 84% up (all days +0.28%, 58%); excess t = 3.13; random-entry nulls p = 0.001–0.025.
- Robust: all 129 usable cells of a 135-cell threshold grid beat the base rate at 5 days; median excess +1.03%; family-wise null p ≈ 0.006 for the grid's median t; the single best cell is not significant on its own (max-t p ≈ 0.06) — the evidence is breadth, not one strong cell.
- The pre-registered cell happens to be the grid's best → expect ~+1% excess, not +1.5%.
- 10/20-day: no edge over "any ≥5% pullback in an uptrend" (p ≈ 0.48). It is a ~1-week bounce signal.
- Invalidation (in-sample): close below the signal-day low within 5 sessions → 10/25 cases, 20-day mean −1.0% vs +4.4% for the rest.
- MACD and an averaged washout score were tested and did not improve the rule (see research record).

## Page sections (`scripts/build_playbook.py`)

Hero verdict on the latest signal → 5-month chart (candles 红涨绿跌, MA50/MA200, volume with opex-adjusted multiples, RSI(14)/RSI(2), MACD, washout score; numbered buy points, lettered near-misses; projection area with the historical post-signal fan anchored on the signal day, the option-implied ±1σ/50% cone from today, walls, gamma flip and the invalidation line) → one card per buy point with every condition's number and the realised outcome → near-miss table → projection (event-study chart vs pullback baseline, percentile table) → option section → rule, results, nulls, robustness, caveats, all historical events.

## Running

```bash
pip install yfinance pandas numpy
python skills/market-risk-playbook/scripts/fetch_data.py
python skills/market-risk-playbook/scripts/build_playbook.py --out prediction.html \
       --json skills/market-risk-playbook/data/latest.json
```

`.github/workflows/playbook.yml` does both after every US close (Mon–Fri 22:17 UTC) and on pushes
touching `skills/market-risk-playbook/scripts/**`, then commits the page and data. This sandbox
cannot reach Yahoo, so the workflow is also how fresh data gets into the repo.

## Rules for changes

- Never tune thresholds until a chosen date fires — that is curve-fitting. Change the rule only with a stated reason, then re-run the grid and family-wise null and report both.
- Every number on the page must come from the script; text that states a finding must be conditional on the computed value if the finding could flip.
- Keep it light-themed, Chinese, and honest about where the edge stops (5 days) and about small n.
- Check the page visually (desktop and 390px) after layout changes: labels inside the chart, no horizontal page scroll (the big chart scrolls inside its own box).
