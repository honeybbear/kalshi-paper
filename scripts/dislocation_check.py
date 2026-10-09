#!/usr/bin/env python3
"""Dislocation detector for Kalshi 15-min crypto markets.

Polls the live public Kalshi API and emits JSON "flags" when a contract shows:
  A) final-3-minutes dislocation: in the last 180s of a window, the market mid
     differs from the fair-value model by more than 15 cents; or
  B) 2-sigma 60s move: the contract's mid price moved more than 2 one-minute
     sigmas (sigma_1min = sigma_15m / sqrt(15)) within the last 60 seconds.

This is PURE DETECTION. Flags describe what was observed. They are not
recommendations, not signals, and not "the edge": the fair-value model used
here was tested on 270 real trades and LOST money (-$1.44, t=-0.21), and the
momentum test lost too (-$2.28, t=-0.53). Every output carries that note.

Usage:
    python3 dislocation_check.py            # print flags JSON to stdout
    python3 dislocation_check.py --write data/flags.json

Exit 0 always (unless a crash); empty flags list is a normal result.
Designed to run clean from cron / GitHub Actions.
"""
import sys, os, json, time, math, datetime, argparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from kalshi_lib import (SERIES, WINDOW_SECONDS, MODEL_NOTE, open_markets,
                        market_mid, coinbase_spot, fair_value, minute_candles,
                        candle_mid_close)

FLAG_A_MIN_SECONDS = 180      # final 3 minutes of the window
FLAG_A_MIN_DISLOCATION = 0.15  # 15 cents
# Flag B uses empirical trailing sigma with a 2c floor (see check_market).


def utcnow():
    return datetime.datetime.now(datetime.timezone.utc)


def iso_to_dt(s):
    return datetime.datetime.fromisoformat(s.replace('Z', '+00:00'))


def check_market(series, m, now):
    """Return list of flag dicts for one open market (detection only)."""
    flags = []
    meta = SERIES[series]
    coin = meta['coin']
    ticker = m.get('ticker')
    try:
        close_dt = iso_to_dt(m['close_time'])
    except Exception:
        return flags
    secs_left = (close_dt - now).total_seconds()
    if secs_left < 0:
        return flags  # window over; nothing to detect

    mid = market_mid(m)
    target = m.get('floor_strike')
    try:
        target = float(target) if target is not None else None
    except Exception:
        target = None

    spot = coinbase_spot(meta['product'])
    model = fair_value(spot, target, meta['sigma_15m'], secs_left)
    dislocation = (mid - model) if (mid is not None and model is not None) else None

    base = {
        'ticker': ticker, 'series': series, 'coin': coin,
        'observed_at_utc': now.strftime('%Y-%m-%dT%H:%M:%SZ'),
        'seconds_remaining': round(secs_left),
        'target_price': target,
        'spot_ref': round(spot, 6) if spot else None,
        'market_mid_cents': round(mid * 100, 1) if mid is not None else None,
        'model_fair_cents': round(model * 100, 1) if model is not None else None,
    }

    # Flag A: final-3-minutes dislocation > 15c
    if (secs_left <= FLAG_A_MIN_SECONDS and dislocation is not None
            and abs(dislocation) > FLAG_A_MIN_DISLOCATION):
        f = dict(base)
        f.update({
            'type': 'final_minutes_dislocation',
            'dislocation_cents': round(dislocation * 100, 1),
            'observation': (
                f"Market mid differs from model by "
                f"{round(dislocation * 100, 1)}c in the final 3 minutes. "
                f"Detection only."),
        })
        flags.append(f)

    # Flag B: >2-sigma move in 60 seconds.
    # Sigma is EMPIRICAL: stdev of the market's own trailing 1-min mid changes
    # (model-implied per-minute sigma is far below the 1c price tick, so it
    # would flag on every tick — verified 2026-10-09). A 2c floor keeps the
    # threshold above tick noise + fees.
    if mid is not None:
        now_ts = int(now.timestamp())
        candles = minute_candles(series, ticker, now_ts - 1200, now_ts)
        mids = []
        for c in sorted(candles, key=lambda c: int(c.get('end_period_ts', 0) or 0)):
            try:
                if int(c.get('end_period_ts', 0) or 0) > now_ts:
                    continue  # incomplete current minute
            except Exception:
                pass
            mc = candle_mid_close(c)
            if mc is not None and mc > 0:
                mids.append(mc)
        if len(mids) >= 4:
            changes = [mids[i] - mids[i - 1] for i in range(1, len(mids))]
            mu = sum(changes) / len(changes)
            var = sum((x - mu) ** 2 for x in changes) / (len(changes) - 1)
            sigma = math.sqrt(var) if var > 0 else 0.0
            threshold = max(2.0 * sigma, 0.02)
            move = abs(mid - mids[-1])
            if move > threshold:
                f = dict(base)
                f.update({
                    'type': 'fast_price_move',
                    'move_cents': round(move * 100, 2),
                    'trailing_sigma_cents': round(sigma * 100, 2),
                    'threshold_cents': round(threshold * 100, 2),
                    'sigmas': round(move / sigma, 2) if sigma > 0 else None,
                    'observation': (
                        f"Contract mid moved {round(move * 100, 2)}c within "
                        f"~60 seconds vs a trailing 1-min sigma of "
                        f"{round(sigma * 100, 2)}c. Detection only."),
                })
                flags.append(f)

    return flags


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--write', default=None,
                    help='also write flags JSON to this path')
    args = ap.parse_args()

    now = utcnow()
    all_flags = []
    per_series = {}
    for series in SERIES:
        try:
            markets = open_markets(series)
        except Exception as e:
            per_series[series] = {'error': str(e)}
            continue
        per_series[series] = {'open_windows': len(markets)}
        for m in markets:
            try:
                all_flags.extend(check_market(series, m, now))
            except Exception as e:
                print(f'WARN check_market {series}: {e}', file=sys.stderr)
        time.sleep(0.2)

    out = {
        'generated_at_utc': now.strftime('%Y-%m-%dT%H:%M:%SZ'),
        'source': 'Kalshi public trade API (no auth), Coinbase Exchange spot (model input)',
        'model_note': MODEL_NOTE,
        'detection_note': (
            'Flags are observations only. The underlying model failed its '
            'pre-registered profitability test; flags are not recommendations '
            'and must not be presented as an edge.'),
        'series_checked': per_series,
        'flags': all_flags,
    }
    text = json.dumps(out, indent=2)
    print(text)
    if args.write:
        os.makedirs(os.path.dirname(os.path.abspath(args.write)), exist_ok=True)
        with open(args.write, 'w') as f:
            f.write(text)
        print(f'wrote {args.write} ({len(all_flags)} flags)', file=sys.stderr)


if __name__ == '__main__':
    main()
