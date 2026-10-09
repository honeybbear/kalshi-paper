# Kalshi Paper — 15-min crypto simulator (FAKE MONEY)

Live: **https://honeybbear.github.io/kalshi-paper/**

An honest instrument panel + paper-trading simulator for Kalshi 15-minute
crypto prediction markets (the same contracts inside Coinbase Predict).

## What this is

- **Live board**: current 15-min windows for 9 coins (BTC, ETH, SOL, XRP, DOGE,
  BNB, ZEC, NEAR, HYPE) from Kalshi's public API — countdown, target price,
  Over/Under prices, and a fair-value model estimate with a dislocation meter.
  (SHIB has no 15-min series on Kalshi's public API — shown honestly as unavailable.)
- **Paper trading**: $1,000 **fake** bankroll in your browser (localStorage).
  Tap Over/Under to place paper trades at live asks, graded automatically at
  settlement. Full stats: P&L, win rate, ROI, per-coin breakdown. Kalshi taker
  fees are accounted on every trade.
- **Dislocation detector**: scans for contracts trading far from the model in
  the final 3 minutes or moving fast. **Detection only — not recommendations.**
- **Truth panel**: the research verdict, always one tap away.

## What this is NOT

A money machine. On 2026-10-07 we ran pre-registered signal tests on
946 real settled windows: the fair-value model went **−$1.44 (t = −0.21, FAIL)**
and 5-min momentum went **−$2.28 (t = −0.53, FAIL)**. The market is well
calibrated; no edge was found. Nothing on this site is a recommendation,
and the word "edge" appears here only to deny it.

## Data & refresh

- `scripts/refresh.py` → `data/live.json` (open windows + recent settlements)
- `scripts/dislocation_check.py` → `data/flags.json` (detection flags, stdout JSON)
- Shared: `scripts/kalshi_lib.py` (API helpers, frozen per-token volatilities
  from the Oct-2026 research, Kalshi taker-fee formula)
- `.github/workflows/refresh.yml` runs both every 5 minutes and commits the JSON.
- The site reads the static JSON (Kalshi's CDN blocks browser `Origin`
  headers, so client-side API calls are not possible — verified 2026-10-09).

Prices can be up to ~5 minutes stale; countdowns tick client-side.
Settlement rule: 60-sec avg of CF Benchmarks RTI at close ≥ open ⇒ YES (ties go YES).

## Run locally

```bash
python3 scripts/refresh.py
python3 scripts/dislocation_check.py --write data/flags.json
python3 -m http.server 8000   # then open http://localhost:8000
```
