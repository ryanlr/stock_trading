---
name: market-risk-playbook
description: Build a daily "Market Risk Playbook" page (Chinese) for an index — next-session range, key support, and the four 20-session paths from comparable historical drawdowns — modelled on balder-ai.com/playbook. Use when asked to generate, update, explain or adapt the playbook / prediction.html.
---

# Market Risk Playbook (市场风险手册)

A daily page that answers one question — **"can I stay long, or should I get out?"** — with
conditional frequencies from history instead of opinion. It reproduces the method of
[Balder's Market Risk Playbook](https://balder-ai.com/playbook) from public data and renders it in
Chinese for 老王看美股 (`prediction.html` at the repo root).

How the original page was reverse-engineered, with the arithmetic that confirms each definition,
is in `references/balder-analysis.md`. Read it before changing a definition.

## Data required

| Input | Symbol (Yahoo) | Used for | Required |
|---|---|---|---|
| Index daily close, 1990→today | `^GSPC` (NDX: `^NDX`) | recent high, drawdown state, comparable positions, 20-session outcomes, ledger | yes |
| Volatility index daily close | `^VIX` (NDX: `^VXN`) | next-session range (implied 1-day σ), variance risk premium | yes |
| Listed option chain, ≤35 days | `^SPX`, falling back to `SPY` scaled by SPX/SPY when Yahoo's SPX chain is thin (it usually is) | call wall, put wall, gamma flip, gamma regime | optional — section is shown as "unavailable" if missing |
| Intraday bars | — | Balder's evidence #1 (martingale) and #7 (R² ≈ 0.11) | not used; those two are cited, not recomputed |

Daily data is cached to `data/gspc_vix_daily.csv` so the script can run `--offline`.

## Analysis (what each number on the page is)

All windows are **20 sessions** (`HORIZON`). Comparable positions are drawn from 2005 onward.

1. **Recent high `H`** = highest close of the last 252 sessions. **Drawdown `D` = 1 − P/H.**
2. **Comparable positions** = every session since 2005 whose drawdown sits in the same band as today:
   `0–2%, 2–5%, 5–10%, 10–20%, >20%`. `m` = their count (Balder quotes "2,794 comparable positions").
3. **Key support** = the first level below today from `H×(1−{2,5,10,20,30}%)`. "Hold" = no close below it in the next 20 sessions.
4. **Four paths** classify each comparable session by its deepest drawdown (vs that session's own `H`) over the next 20 sessions, with `notch` = the first of `{5,10,20,30}%` below today and `notch2` the next one:
   - A: regains `H` and never breaks `notch` · B: never breaks `notch`, does not regain `H` (chop)
   - C: deepest between `notch` and `notch2` · D: deeper than `notch2`
   - "No deeper break" = A + B. "Deepest drawdown" column = median deepest drawdown within the path.
5. **+2% / −2% probabilities** = max (min) close in the next 20 sessions ≥ +2% (≤ −2%) from today, versus the same frequency over all sessions since 2005 (base rate). Both below base → "双向收窄 / compressed both ways".
6. **Next-session range** = `close × exp(± k × VIX/100/√252)`, `k` = median of `|log return| / implied 1-day σ` over the last 252 sessions (50% band); 80th percentile for the 80% band. This is why the band is ~0.6σ rather than 1.96σ: implied vol overstates realised vol (variance risk premium). The ledger scores every past band out of sample (target coverage ≈ 50%).
7. **Option structure**: call wall = max call OI strike above spot; put wall = max put OI strike below spot; gamma flip = spot where Σ(call Γ·OI) − Σ(put Γ·OI) crosses zero (Black-Scholes Γ from Yahoo IVs, dealer long calls / short puts convention). Above the flip → positive gamma (damped moves), below → negative gamma (amplified).
8. **Evidence section**: #2 band ratio, #3 overlap count, #5 drawdown-recovery table, #6 VRP quintiles (VIX² − 20-day realised variance, non-overlapping 20-day windows, top quintile vs rest Welch t) are recomputed every run. #1, #4, #7 are Balder's findings, cited and paraphrased.
9. **"What we left out" (今日略去)**: a probability is dropped and listed if it differs from its base rate by < 5pp or rests on < 100 comparable positions.

## Running it

```bash
pip install yfinance pandas numpy
python skills/market-risk-playbook/scripts/build_playbook.py --out prediction.html \
       --cache-dir skills/market-risk-playbook/data --json /tmp/playbook.json
```

Options: `--offline` (cache only), `--asof YYYY-MM-DD` (rebuild a past session; skips options),
`--index ^NDX --vol ^VXN --options ^NDX --name "Nasdaq 100"` (tech version), `--ga ''` (no analytics).

In this repo it runs automatically: `.github/workflows/playbook.yml` builds after each US close
(Mon–Fri 22:17 UTC), and on any push touching `skills/market-risk-playbook/**`, then commits
`prediction.html` and the CSV cache. Pages redeploys from `main`.

## Checks before publishing a change

- Open the page: hero sentence, four path probabilities summing to 100%, fan chart with high/key/notch lines.
- Ledger 50% coverage over the full sample should land near 50% (45–55%). Far off → the `k` calibration broke.
- Path probabilities and recovery table should be monotone in depth (deeper band → lower regain rate).
- Never publish a probability that failed its own threshold; it belongs in 今日略去.
- Keep it light-themed and in Chinese; numbers in the evidence section must be the script's, not copied from Balder.
