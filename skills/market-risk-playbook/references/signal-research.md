# QQQ "washout in uptrend" — research record (2026-10-19)

Question from the owner: *last Friday (2026-10-16) was a buying point — prove it with a hypothesis
and backtest, using price and volume (RSI/MACD allowed), find the other buying points in the past
5 months, and use option data.*

## 1. What the 5-month tape showed (before writing a rule)

Recurring lows: 06-05/06-10, 06-26, 07-17/07-29 (window bottom, 661.73, +9% in 4 days), 09-16, 10-16.
On 10-16: −2.5%, volume 2.1× (monthly opex), RSI(2) 0.65, RSI(14) 35, VXN 22.9 → 27.1 (+18.5%),
−6.6% from the 63-day high, +5.4% above the 200-day average.

Pitfall flagged up front: 10-16 was the October monthly option expiry, so its volume is partly
mechanical. Volume is normalised on opex Fridays by the trailing median opex volume ratio (≈1.13×):
2.10× raw → 1.85× adjusted.

## 2. Hypothesis and rule — fixed before testing

In an intact uptrend, a short selloff that combines extreme short-term oversold, a volume surge and
an implied-vol spike marks forced selling / overpaid hedging, and tends to reverse.

Rule: adj close > MA200; ≥5% below 63-day high; RSI(2) ≤ 5; opex-adjusted volume ≥ 1.5× 20-day
median AND VXN ≥ 10% above its 20-day mean. 5-session cooldown. Sample from 2001-03 (VXN start).

## 3. Results

| | n | 5d | 10d | 20d |
|---|---|---|---|---|
| Signal | 25 | +1.80% (84% up) | +1.11% (68%) | +2.24% (80%) |
| Any ≥5% pullback in uptrend | 719 days | +0.58% | +1.06% | +2.17% |
| All days | 6,427 | +0.28% (58%) | +0.55% | +1.12% |

In the 5-month window the rule fires on **2026-06-05, 2026-07-29 and 2026-10-16**.
06-05: +2.3% / +4.8% / +0.7% (5/10/20d). 07-29: +8.4% / +9.4% / +7.5%. 10-16: +1.2% after 1 day.
Near misses (washout score ≥ 80, one or two legs missing): 07-28, 10-14, 10-15.

## 4. Validation

- Excess vs all days: t = 3.13 (5d), 0.55 (10d), 0.87 (20d).
- Random-entry nulls (same n, 5,000 draws): 5d p = 0.01 (all days), 0.001 (uptrend days), 0.025 (uptrend ≥5% pullback days). 10d/20d p = 0.13–0.50.
- Grid: dd {3..7%} × RSI(2) {3,5,10} × volume {1.25,1.5,2.0} × VXN {5,10,20%} = 135 cells, 129 with ≥8 events. 100% positive 5-day excess; median +1.03%, median t 1.94, max t 3.13.
- Family-wise null (forward returns circularly shifted, whole grid re-run, 500 reps): median-t p ≈ 0.006; max-t p ≈ 0.06 (an exploratory 200-rep run gave 0.02). The best single cell is not significant on its own; the evidence is that nearly every cell works.
- **Caveat:** the pre-registered cell is the grid maximum. Use the grid median as the expectation.

## 5. Things tested that did not make the rule

- MACD histogram at a 60-day low instead of RSI(2): 5d +1.84% (n 28) — same, not better. Both together: n 16, no gain. MACD lags; it confirms the fall, not the low.
- RSI(14) ≤ 35 instead of RSI(2): similar (5d +1.62%, 20d +3.15%, n 27). 10-16 had RSI(14) 35.1.
- Averaged washout score (mean of 5-year percentile ranks of the four legs): weak, U-shaped deciles; top 2% only +0.92% at 5d. Weakest-link (min rank) score: no better. The edge is in the conjunction — kept on the chart as an intensity gauge only.
- Signal without the trend filter: similar 5d, worse hit rates and deeper drawdowns.

## 6. Risk notes

- Worst event 2020-02-24 (COVID): −22.8% over 20 days.
- Close below the signal-day low within 5 sessions: 10 of 25; their 20-day mean −1.0% (median MAE −3.7%) vs +4.4% for the 15 that held. In-sample observation, not an independently tested stop.

## 7. Options

Yahoo has no option history, so the backtest uses VXN. The live chain (archived daily from 2026-10-19)
gives on 10-19: gamma flip ≈ 733 (spot 718 → negative gamma), weekly walls 735/711, monthly (11-20)
walls 760/700, max pain 727/730, put/call OI 1.54, volume 1.17, 25Δ skew 25.4% vs 19.0%,
risk-neutral P(back above 759.66 by 11-20) ≈ 19%. Once ~1 year of snapshots exists, test put/call,
skew and gamma regime as additional legs with the same grid + family null procedure.
