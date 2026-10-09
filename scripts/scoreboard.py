#!/usr/bin/env python3
"""Model scoreboard for Kalshi 15-min crypto markets — DEMONSTRATION ONLY.

Every run, for each open 15-min window, this script records the fair-value
model's "lean":
    model favors Over  if P(up) > yes_ask + FEE_EDGE
    model favors Under if P(up) < yes_bid - FEE_EDGE
    otherwise "no lean"

FEE_EDGE = 0.04 (4 cents). This is a rough half-spread + taker-fee estimate:
a lean is only logged when the model's view beats the market price by more
than it would plausibly cost to act on it. It is NOT a profitability claim.

On later runs, settled windows are graded: win = the favored side won.
P&L is simulated for ONE contract per lean, after the Kalshi taker fee.
Nothing here is a recommendation. The model FAILED its pre-registered
profitability test (270 trades, -$1.44, t=-0.21); this board exists so you
can WATCH the model, not to find an edge. No money is involved anywhere.

Outputs:
    data/scoreboard.jsonl  — one row per window observed (deduped by ticker)
    data/scoreboard.json   — running tally + honesty note (consumed by site)

Usage:
    python3 scoreboard.py                 # update both files, print summary
Designed for GitHub Actions (every 5 min) and cron. Exit 0 unless a crash.
"""
import sys, os, json, time, datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from kalshi_lib import (SERIES, open_markets, settled_markets, market_mid,
                        coinbase_spot, fair_value, taker_fee)

FEE_EDGE = 0.04  # 4c half-spread + fee estimate; documented above

HONESTY_NOTE = (
    "DEMONSTRATION, not a signal. No money is involved. "
    "Small samples are noise. The 946-window backtest is the real grade: "
    "the fair-value model lost -$1.44 over 270 trades (t=-0.21). "
    "This board exists so you can watch the model, not to find an edge."
)

BASE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data')
JSONL_PATH = os.path.join(BASE_DIR, 'scoreboard.jsonl')
JSON_PATH = os.path.join(BASE_DIR, 'scoreboard.json')


def utcnow():
    return datetime.datetime.now(datetime.timezone.utc)


def iso_to_dt(s):
    return datetime.datetime.fromisoformat(s.replace('Z', '+00:00'))


def load_log():
    rows = []
    if os.path.exists(JSONL_PATH):
        with open(JSONL_PATH) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except Exception:
                    pass
    return rows


def save_log(rows):
    os.makedirs(BASE_DIR, exist_ok=True)
    with open(JSONL_PATH, 'w') as f:
        for r in rows:
            f.write(json.dumps(r) + '\n')


def record_leans(rows, now):
    """Append one row per open window not already logged. Returns new rows."""
    seen = {r.get('window_ticker') for r in rows}
    new_rows = []
    for series, meta in SERIES.items():
        try:
            markets = open_markets(series)
        except Exception as e:
            print(f'WARN open_markets {series}: {e}', file=sys.stderr)
            continue
        spot = coinbase_spot(meta['product'])
        for m in markets:
            ticker = m.get('ticker')
            if not ticker or ticker in seen:
                continue
            try:
                close_dt = iso_to_dt(m['close_time'])
            except Exception:
                continue
            secs_left = (close_dt - now).total_seconds()
            if secs_left <= 0:
                continue
            try:
                target = float(m['floor_strike']) if m.get('floor_strike') is not None else None
                yes_bid = float(m['yes_bid_dollars'])
                yes_ask = float(m['yes_ask_dollars'])
                no_ask = float(m['no_ask_dollars'])
            except Exception:
                continue
            model = fair_value(spot, target, meta['sigma_15m'], secs_left)
            if model is None:
                continue  # model unavailable for this coin (e.g. NEAR/HYPE) — skip honestly
            if model > yes_ask + FEE_EDGE:
                lean = 'over'
                entry_cents = round(yes_ask * 100, 1)
            elif model < yes_bid - FEE_EDGE:
                lean = 'under'
                entry_cents = round(no_ask * 100, 1)
            else:
                lean = 'no_lean'
                entry_cents = None
            row = {
                'window_ticker': ticker,
                'series': series,
                'coin': meta['coin'],
                'recorded_at': now.strftime('%Y-%m-%dT%H:%M:%SZ'),
                'lean': lean,
                'model_p': round(model, 4),
                'market_mid_cents': round(((yes_bid + yes_ask) / 2) * 100, 1),
                'entry_price_cents': entry_cents,
                'outcome': None,   # filled when the window settles
                'pnl_cents': None,  # simulated 1-contract P&L after taker fee
            }
            rows.append(row)
            new_rows.append(row)
            seen.add(ticker)
        time.sleep(0.2)
    return new_rows


def grade_rows(rows):
    """Fill outcome + pnl_cents for settled windows missing them."""
    by_series = {}
    for r in rows:
        if r.get('outcome') is not None:
            continue
        by_series.setdefault(r['series'], []).append(r)
    graded = 0
    for series, pending in by_series.items():
        try:
            settled = settled_markets(series, limit=100)
        except Exception as e:
            print(f'WARN settled_markets {series}: {e}', file=sys.stderr)
            continue
        res_map = {s['ticker']: s['result'] for s in settled}
        for r in pending:
            res = res_map.get(r['window_ticker'])
            if res not in ('yes', 'no'):
                continue
            lean = r['lean']
            if lean not in ('over', 'under'):
                r['outcome'] = 'na'
                continue
            win = (res == 'yes') == (lean == 'over')
            r['outcome'] = 'win' if win else 'loss'
            entry = (r['entry_price_cents'] or 0) / 100.0
            fee = taker_fee(entry)
            cost = entry + fee
            r['pnl_cents'] = round((1.0 - cost) * 100, 1) if win else round(-cost * 100, 1)
            graded += 1
    return graded


def tally(rows):
    picks = [r for r in rows if r['lean'] in ('over', 'under')]
    settled = [r for r in picks if r.get('outcome') in ('win', 'loss')]
    wins = sum(1 for r in settled if r['outcome'] == 'win')
    pnl = round(sum(r['pnl_cents'] for r in settled if r.get('pnl_cents') is not None), 1)
    return {
        'n_picks': len(picks),
        'n_settled': len(settled),
        'wins': wins,
        'win_rate': round(wins / len(settled), 4) if settled else None,
        'pnl_cents': pnl,
    }


def main():
    now = utcnow()
    rows = load_log()
    new_rows = record_leans(rows, now)
    graded = grade_rows(rows)
    save_log(rows)

    t = tally(rows)
    recent = []
    for r in rows[-20:][::-1]:
        recent.append({
            'coin': r['coin'],
            'ticker': r['window_ticker'],
            'lean': r['lean'],
            'model_p': r['model_p'],
            'market_mid_cents': r['market_mid_cents'],
            'outcome': r.get('outcome'),
            'pnl_cents': r.get('pnl_cents'),
            'recorded_at': r['recorded_at'],
        })

    out = {
        'updated_at': now.strftime('%Y-%m-%dT%H:%M:%SZ'),
        'fee_edge_cents': int(FEE_EDGE * 100),
        'note': HONESTY_NOTE,
        'n_picks': t['n_picks'],
        'n_settled': t['n_settled'],
        'wins': t['wins'],
        'win_rate': t['win_rate'],
        'pnl_cents': t['pnl_cents'],
        'recent': recent,
    }
    os.makedirs(BASE_DIR, exist_ok=True)
    with open(JSON_PATH, 'w') as f:
        json.dump(out, f, indent=2)

    wr = f"{t['win_rate']*100:.1f}%" if t['win_rate'] is not None else 'n/a'
    print(f'scoreboard: {len(new_rows)} new rows, {graded} graded, '
          f'picks={t["n_picks"]} settled={t["n_settled"]} wins={t["wins"]} '
          f'win_rate={wr} pnl_cents={t["pnl_cents"]}')


if __name__ == '__main__':
    main()
