#!/usr/bin/env python3
"""Shared helpers for the kalshi-paper project.
Public Kalshi API only, no auth. Polite rate limiting (~2 req/s max).
"""
import urllib.request, urllib.parse, json, time, sys, math

BASE = 'https://api.elections.kalshi.com/trade-api/v2'
CB = 'https://api.exchange.coinbase.com'
UA = {'User-Agent': 'kalshi-paper-simulator/1.0 (+research instrument panel)'}

# Per-token realized 15-min volatility (sigma_15m), FROZEN from the Oct 7 2026
# research: ~/workspace/kalshi-15min/reports/test_results.json
# (TRAIN-calibrated, never refit). NEAR had too few windows ("no vol"),
# HYPE 15M postdates the study -> None = model unavailable, shown honestly.
SERIES = {
    'KXBTC15M':  {'coin': 'BTC',  'product': 'BTC-USD',  'sigma_15m': 0.0018},
    'KXETH15M':  {'coin': 'ETH',  'product': 'ETH-USD',  'sigma_15m': 0.0022},
    'KXSOL15M':  {'coin': 'SOL',  'product': 'SOL-USD',  'sigma_15m': 0.0028},
    'KXXRP15M':  {'coin': 'XRP',  'product': 'XRP-USD',  'sigma_15m': 0.0035},
    'KXDOGE15M': {'coin': 'DOGE', 'product': 'DOGE-USD', 'sigma_15m': 0.0038},
    'KXBNB15M':  {'coin': 'BNB',  'product': 'BNB-USD',  'sigma_15m': 0.0027},
    'KXZEC15M':  {'coin': 'ZEC',  'product': 'ZEC-USD',  'sigma_15m': 0.0046},
    'KXNEAR15M': {'coin': 'NEAR', 'product': 'NEAR-USD', 'sigma_15m': None},
    'KXHYPE15M': {'coin': 'HYPE', 'product': 'HYPE-USD', 'sigma_15m': None},
}
# SHIB: shown in the Coinbase app's 15m list, but Kalshi's public API exposes
# NO 15-minute SHIB series (verified 2026-10-09 via /series). Board card is
# rendered as unavailable rather than faked.

WINDOW_SECONDS = 900  # 15-minute windows

MODEL_NOTE = (
    "Fair-value model P(up)=Phi(ln(S/target)/(sigma*sqrt(tau))), zero drift; "
    "sigma frozen from Oct-2026 research. That model LOST money in testing "
    "(270 trades, -$1.44, t=-0.21). Shown for observation only, not a recommendation."
)


def get_json(url, tries=3):
    req = urllib.request.Request(url, headers=UA)
    for a in range(tries):
        try:
            with urllib.request.urlopen(req, timeout=25) as r:
                return json.load(r)
        except Exception as e:
            if a == tries - 1:
                print(f'WARN get_json failed {url}: {e}', file=sys.stderr)
                return None
            time.sleep(1.0 * (a + 1))
    return None


def norm_cdf(x):
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def taker_fee(p_dollars):
    """Kalshi taker fee per contract, rounded UP to nearest cent.
    fee = ceil(0.07 * P * (1-P) * 100) / 100, P in dollars.
    Verified against Kalshi fee schedule (Feb 2026, updated Jul 2026)."""
    p = max(0.0, min(1.0, float(p_dollars)))
    return math.ceil(0.07 * p * (1.0 - p) * 100) / 100.0


def fair_value(spot, target, sigma_15m, seconds_remaining):
    """Model P(yes) for an open 15-min window. None if not computable."""
    try:
        if sigma_15m is None or spot is None or target is None:
            return None
        if spot <= 0 or target <= 0 or sigma_15m <= 0:
            return None
        tau = seconds_remaining / WINDOW_SECONDS
        if tau <= 0:
            return None
        z = math.log(spot / target) / (sigma_15m * math.sqrt(tau))
        return norm_cdf(z)
    except Exception:
        return None


def coinbase_spot(product):
    """Current spot price via Coinbase Exchange public ticker. None on failure."""
    d = get_json(f'{CB}/products/{product}/ticker')
    if not d:
        return None
    try:
        return float(d['price'])
    except Exception:
        return None


def open_markets(series_ticker):
    """Currently open markets for a series (usually 1; 2 during rollover)."""
    d = get_json(BASE + '/markets?' + urllib.parse.urlencode(
        {'series_ticker': series_ticker, 'status': 'open', 'limit': 10}))
    if not d:
        return []
    time.sleep(0.3)
    return d.get('markets', [])


def settled_markets(series_ticker, limit=12):
    """Most recent settled markets (for grading paper trades)."""
    d = get_json(BASE + '/markets?' + urllib.parse.urlencode(
        {'series_ticker': series_ticker, 'status': 'settled', 'limit': limit}))
    if not d:
        return []
    time.sleep(0.3)
    out = []
    for m in d.get('markets', []):
        out.append({'ticker': m.get('ticker'), 'result': m.get('result'),
                    'close_time': m.get('close_time')})
    return out


def market_mid(m):
    """Mid of yes bid/ask in dollars. None if missing."""
    try:
        bid = float(m['yes_bid_dollars'])
        ask = float(m['yes_ask_dollars'])
        return (bid + ask) / 2.0
    except Exception:
        return None


def minute_candles(series_ticker, ticker, start_ts, end_ts):
    """1-min yes bid/ask candlesticks for a market. Returns list or []."""
    d = get_json(BASE + f'/series/{series_ticker}/markets/{ticker}/candlesticks?' +
                 urllib.parse.urlencode(
                     {'start_ts': int(start_ts), 'end_ts': int(end_ts),
                      'period_interval': 1}))
    time.sleep(0.3)
    if not d:
        return []
    return d.get('candlesticks', [])


def candle_mid_close(c):
    try:
        bid = float(c['yes_bid']['close_dollars'])
        ask = float(c['yes_ask']['close_dollars'])
        return (bid + ask) / 2.0
    except Exception:
        return None
