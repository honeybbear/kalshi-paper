#!/usr/bin/env python3
"""Refresh the static data feed for the kalshi-paper site.

Pulls, via the public Kalshi API (no auth):
  - currently open 15-min markets for each series (prices, target, times)
  - recently settled markets (so the app can grade paper trades)
Enriches each open window with the fair-value model estimate and dislocation
vs the market mid, using Coinbase spot as the model input.

Writes data/live.json. Designed for GitHub Actions (every 5 min) and cron.

Usage: python3 refresh.py [--out data/live.json]
"""
import sys, os, json, time, datetime, argparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from kalshi_lib import (SERIES, MODEL_NOTE, open_markets, settled_markets,
                        market_mid, coinbase_spot, fair_value, taker_fee)


def utcnow():
    return datetime.datetime.now(datetime.timezone.utc)


def iso_to_dt(s):
    return datetime.datetime.fromisoformat(s.replace('Z', '+00:00'))


def build_coin_card(series, m, now):
    meta = SERIES[series]
    ticker = m.get('ticker')
    try:
        close_dt = iso_to_dt(m['close_time'])
        open_dt = iso_to_dt(m['open_time'])
    except Exception:
        return None
    secs_left = (close_dt - now).total_seconds()
    try:
        target = float(m.get('floor_strike')) if m.get('floor_strike') is not None else None
    except Exception:
        target = None
    try:
        yes_bid = float(m.get('yes_bid_dollars'))
        yes_ask = float(m.get('yes_ask_dollars'))
        no_bid = float(m.get('no_bid_dollars'))
        no_ask = float(m.get('no_ask_dollars'))
        last = float(m.get('last_price_dollars')) if m.get('last_price_dollars') is not None else None
    except Exception:
        return None
    mid = (yes_bid + yes_ask) / 2.0
    spot = coinbase_spot(meta['product'])
    model = fair_value(spot, target, meta['sigma_15m'], secs_left) if secs_left > 0 else None
    dislocation_c = round((mid - model) * 100, 1) if (model is not None) else None
    return {
        'coin': meta['coin'],
        'series': series,
        'ticker': ticker,
        'available': True,
        'target_price': target,
        'yes_bid_cents': round(yes_bid * 100, 1),
        'yes_ask_cents': round(yes_ask * 100, 1),
        'no_bid_cents': round(no_bid * 100, 1),
        'no_ask_cents': round(no_ask * 100, 1),
        'last_cents': round(last * 100, 1) if last is not None else None,
        'mid_cents': round(mid * 100, 1),
        'volume': m.get('volume_fp'),
        'open_time_utc': m.get('open_time'),
        'close_time_utc': m.get('close_time'),
        'spot_ref': round(spot, 6) if spot else None,
        'model_fair_cents': round(model * 100, 1) if model is not None else None,
        'model_sigma_15m': meta['sigma_15m'],
        'dislocation_cents': dislocation_c,
        'taker_fee_at_ask_cents': round(taker_fee(yes_ask) * 100, 1),
        'taker_fee_at_noask_cents': round(taker_fee(no_ask) * 100, 1),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', default=os.path.join(
        os.path.dirname(os.path.abspath(__file__)), '..', 'data', 'live.json'))
    args = ap.parse_args()

    now = utcnow()
    coins = []
    settled = []
    errors = {}
    for series, meta in SERIES.items():
        try:
            markets = open_markets(series)
        except Exception as e:
            errors[series] = str(e)
            continue
        if not markets:
            coins.append({'coin': meta['coin'], 'series': series,
                          'available': False,
                          'reason': 'no open 15-min window on Kalshi right now'})
        for m in markets:
            card = build_coin_card(series, m, now)
            if card:
                coins.append(card)
        try:
            for s in settled_markets(series, limit=12):
                settled.append({'series': series, 'ticker': s['ticker'],
                                'result': s['result'],
                                'close_time_utc': s['close_time']})
        except Exception as e:
            errors[series + ':settled'] = str(e)
        time.sleep(0.2)

    # SHIB: honest unavailable card (no Kalshi 15M series on the public API)
    coins.append({'coin': 'SHIB', 'series': 'KXSHIB15M', 'available': False,
                  'reason': 'No 15-minute SHIB series on Kalshi\u2019s public API '
                            '(verified 2026-10-09). Shown in the Coinbase app only.'})

    out = {
        'generated_at_utc': now.strftime('%Y-%m-%dT%H:%M:%SZ'),
        'refresh_cadence': 'GitHub Actions every 5 minutes; countdowns tick client-side',
        'caveat': ('Prices can be up to ~5 minutes stale. Paper trades execute at '
                   'the displayed ask; real markets move. FAKE MONEY ONLY.'),
        'model_note': MODEL_NOTE,
        'verdict': ('Research verdict (Oct 7 2026, 946 windows): fair-value model '
                    '-$1.44 (t=-0.21) FAIL; momentum -$2.28 (t=-0.53) FAIL. '
                    'Market is well calibrated. No edge found.'),
        'coins': coins,
        'settled': settled,
        'errors': errors,
    }
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, 'w') as f:
        json.dump(out, f, indent=2)
    n_ok = sum(1 for c in coins if c.get('available'))
    print(f'wrote {args.out}: {n_ok} live coin cards, {len(settled)} settled refs, '
          f'{len(errors)} errors')


if __name__ == '__main__':
    main()
