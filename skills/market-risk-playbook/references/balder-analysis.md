# How balder-ai.com/playbook is built — reverse-engineering notes (2026-10-19)

Source page: <https://balder-ai.com/playbook> ("Market Risk Playbook — today's range and the four
paths"), a free daily page from Balder's 龙气榜 / Signal Desk. A sister page
(<https://balder-ai.com/playbook-ndx>) runs the same template on the Nasdaq 100 with VXN.

## Page anatomy (snapshot of 2026-10-19, intraday)

| Block | Shown | Inference |
|---|---|---|
| Header | "Daily · 2026-10-19 · Intraday — today's close is not known yet" | regenerated during the session from a live quote |
| Hero | SPX 7,690, −1.64% below recent high; 84% no deeper break, 87% regains high within 20 sessions, 53% add another 2% vs usual 65%; "2,794 comparable positions since 2005" | conditional frequencies over a filtered history |
| Tiles | Today's range 7,656–7,725 · Key level 7,663 · No deep break 84% | |
| Fan chart (PNG) | historical paths drawn forward | rendered image of comparable 20-session paths |
| Four paths | Back to high w/o deeper break 78% (−1.8%) · Chop 6% · One notch lower (−5% to −10%) 13% (−6.2%) · Deeper (< −10%) 3% (−12.0%) | classified by deepest drawdown over 20 sessions |
| Levels | Recent high 7,819 · Key support 7,663 | |
| Intraday structure | Call wall 7,750 · Gamma flip 7,721 · Put wall 7,650 · "negative gamma" | SPX option open interest |
| Method & evidence | 7 numbered research findings | static text with study numbers |
| What we left out | "a 2% drop probability that beat its base rate by too little to act on" | thresholded outputs are listed, not hidden |

## Definitions confirmed by arithmetic

- **Recent high = max close.** SPX closes in the same site's SPX ledger: 10-06 7,818.93 → "7,819". Drawdown 7,690 / 7,819 − 1 = −1.65% ✓ (page: −1.64%).
- **Key level = high × 0.98** (the next notch boundary below price): 7,819 × 0.98 = 7,662.6 → **7,663** ✓.
  NDX: headline key level 28,102 = 31,224 × 0.90 ✓ (price was −5.49%, so the next boundary is −10%).
  The NDX "levels" table still printed 31,224 × 0.98 = 30,600 — a template bug, which is why we use the next boundary consistently.
- **Four paths are absolute deepest-drawdown buckets** (>−5% split by regained/not, −5…−10, <−10): 78 + 6 + 13 + 3 = 100, and "no deep break" 84 = 78 + 6 ✓. NDX: 1 + 0 + 51 + 48 = 100, "no deep break" 1% ✓.
- **Today's range ≈ ±0.45%** = 7,690 × (1 ± 0.0045). Their method #2: implied 1-day σ from the vol index × the trailing-252-session median of realised/implied (≈ 0.54 long-run), targeting ~50% coverage (they report 50.4% out of sample over 5,189 days). With VIX near 20, 20/√252 × 0.54 × ~0.66 ≈ 0.45% ✓ order of magnitude; intraday they also scale for the remaining session.
- **Option block** uses the same OI-based call wall / put wall / gamma flip as their SPX probability cone page (same numbers: 7,750 / 7,650 / 7,720.65).

## Data sources implied

1. Index daily closes since at least 2005 (5,421 sessions quoted) — drawdowns and forward outcomes.
2. Volatility index (VIX / VXN) daily — implied σ for the range and the variance risk premium signal.
3. Live SPX option chain with open interest and IVs — walls, flip, gamma regime.
4. Intraday bars (5-min, morning session) — only for research findings #1 (smoothing loses to the current price) and #7 (R² 0.113 for the rest of the session).

## Analysis implied by the 7 findings

1. Don't forecast a point: price ≈ martingale (Samuelson 1965) → publish a range.
2. Range = ~0.65σ, not 1.96σ, because implied > realised vol; ratio recalibrated on a 252-session window.
3. Stop at 20 sessions: overlapping windows inflate t by √h (Hansen-Hodrick / Newey-West).
4. Charge every indicator family for its search with block-shuffled nulls; families that don't beat the noise are cut.
5. Drawdown regain rates within 20 sessions fall with depth (57% / 30% / 7% / 0%).
6. Only "add" signal: top quintile of the variance risk premium (Bollerslev-Tauchen-Zhou 2009): +1.65% vs 0.79% baseline, t = 2.70, 54 non-overlapping samples.
7. Very little is forecastable (R² 0.113 intraday).

## What is not disclosed (and what we chose)

- The exact "comparable position" filter. Their 2,794 positions (≈ half of all sessions since 2005) and an 87% regain rate (vs 57% for "just off the high" in finding #5) imply extra conditions beyond the drawdown band — possibly a narrower drawdown window or a volatility-regime filter. We use the drawdown band alone and say so; our probabilities will differ.
- The recent-high window. Finding #5's "529 samples below −10%" since 2005 is too few for an all-time-high drawdown (2008–2013 alone would exceed it), so it is a rolling high; we use 252 sessions.
- The base-rate threshold for "left out". We use 5 percentage points and n ≥ 100.

## Validation: our first build vs Balder, same session (2026-10-19)

| Metric | Balder (intraday 7,690) | This skill (close 7,690.73) |
|---|---|---|
| Recent high | 7,819 | 7,819 |
| Comparable positions since 2005 | 2,794 | 2,686 (0–2% band) |
| No deeper break (−5%) | 84% | 86% |
| Regains high within 20 sessions | 87% | 81% |
| Add another 2% (base) | 53% (65%) | 47% (60%) |
| Paths A / B / C / D | 78 / 6 / 13 / 3% | 76 / 11 / 12 / 2% |
| Deepest drawdown A / C / D | −1.8 / −6.2 / −12.0% | −1.5 / −6.1 / −12.4% |
| Next-session range | 7,656–7,725 | 7,651–7,731 |
| Realised/implied median | 0.54 | 0.47 (since 2005, VIX) |
| 50% band out-of-sample coverage | 50.4% | 50.2% |
| Regain by band 5–10% / >10% | 7% / 0% | 8% / 0% |
| VRP top quintile vs baseline | +1.65% vs 0.79%, t 2.70, n 54 | +1.58% vs 0.79%, t 1.42, n 55 |

Close enough to confirm the definitions; the residual gaps (regain rate, chop share) point to an
extra conditioning filter in the original that is not disclosed. The VRP effect has the same size
but weaker significance under our Welch test, and the page says so.
