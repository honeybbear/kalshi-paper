/* kalshi-paper — live board + paper trading + detector. FAKE MONEY ONLY. */
(function () {
  'use strict';
  var LS_KEY = 'kalshi_paper_v1';
  var START_BANK = 1000;
  var TRADE_LOCK_SECS = 20;

  var COIN_COLORS = {
    BTC: '#f7931a', ETH: '#627eea', SOL: '#9945ff', XRP: '#25a4e8',
    DOGE: '#c2a633', BNB: '#f0b90b', SHIB: '#ff6b35', ZEC: '#e9b44c',
    NEAR: '#00ec97', HYPE: '#97fdd3'
  };

  var live = null, flags = null, scoreboard = null;
  var paper = loadPaper();
  var sheetState = null;

  function loadPaper() {
    try {
      var p = JSON.parse(localStorage.getItem(LS_KEY));
      if (p && typeof p.bankroll === 'number') return p;
    } catch (e) {}
    return { bankroll: START_BANK, positions: [], history: [] };
  }
  function savePaper() {
    try { localStorage.setItem(LS_KEY, JSON.stringify(paper)); } catch (e) {}
  }
  function takerFee(p) { // p in dollars; Kalshi taker fee, rounded UP to cent
    p = Math.max(0, Math.min(1, p));
    return Math.ceil(0.07 * p * (1 - p) * 100) / 100;
  }
  function fmt$ (x) {
    var s = (x < 0 ? '-$' : '$') + Math.abs(x).toFixed(2);
    return s;
  }
  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c];
    });
  }
  function secsLeft(closeIso) {
    return Math.floor((new Date(closeIso).getTime() - Date.now()) / 1000);
  }
  function fmtCd(s) {
    if (s < 0) return 'closed';
    var m = Math.floor(s / 60), r = s % 60;
    return m + ':' + (r < 10 ? '0' : '') + r;
  }
  function timeAgo(iso) {
    var s = Math.floor((Date.now() - new Date(iso).getTime()) / 1000);
    if (s < 0) s = 0;
    if (s < 60) return s + 's ago';
    var m = Math.floor(s / 60);
    if (m < 60) return m + 'm ago';
    return Math.floor(m / 60) + 'h ago';
  }

  /* ---------- data ---------- */
  function fetchAll() {
    fetch('data/live.json', { cache: 'no-store' }).then(function (r) {
      if (!r.ok) throw new Error('live.json HTTP ' + r.status);
      return r.json();
    }).then(function (d) {
      live = d;
      gradePositions();
      renderBoard(); renderPortfolio(); renderFresh();
    }).catch(function (e) {
      document.getElementById('fresh').textContent =
        'Market data unavailable right now (' + e.message + '). Simulator still works on last load.';
    });
    fetch('data/flags.json', { cache: 'no-store' }).then(function (r) {
      if (!r.ok) throw new Error('no flags yet');
      return r.json();
    }).then(function (d) {
      flags = d;
      renderDetector();
    }).catch(function () {
      flags = null; renderDetector();
    });
    fetch('data/scoreboard.json', { cache: 'no-store' }).then(function (r) {
      if (!r.ok) throw new Error('no scoreboard yet');
      return r.json();
    }).then(function (d) {
      scoreboard = d;
      renderScoreboard();
    }).catch(function () {
      scoreboard = null; renderScoreboard();
    });
  }

  /* ---------- board ---------- */
  function renderBoard() {
    var el = document.getElementById('board');
    if (!live || !live.coins) { el.innerHTML = '<div class="empty">Loading…</div>'; return; }
    var html = '';
    live.coins.forEach(function (c, i) {
      var col = COIN_COLORS[c.coin] || '#888';
      html += '<div class="card" data-coin="' + esc(c.coin) + '">';
      html += '<div class="row1"><div class="coinleft"><span class="coinbadge" style="background:' + col + '">' +
        esc(c.coin.slice(0, 4)) + '</span><span class="coinname">' + esc(c.coin) + ' <span class="muted">15m</span></span></div>';
      if (c.available) {
        html += '<span class="countdown" data-cd="' + esc(c.close_time_utc) + '">--:--</span>';
      }
      html += '</div>';
      if (!c.available) {
        html += '<div class="unavail">⚠ ' + esc(c.reason || 'Unavailable') + '</div>';
      } else {
        html += '<div class="target">Target price: <b>' +
          (c.target_price != null ? '$' + Number(c.target_price).toLocaleString(undefined, { maximumFractionDigits: 6 }) : '—') +
          '</b></div>';
        html += '<div class="sides">' +
          '<button class="sidebtn over" data-side="yes" data-i="' + i + '">Over <span class="p">' + c.yes_ask_cents + '¢</span><small>YES ask · pays $1 if up</small></button>' +
          '<button class="sidebtn under" data-side="no" data-i="' + i + '">Under <span class="p">' + c.no_ask_cents + '¢</span><small>NO ask · pays $1 if down/flat</small></button>' +
          '</div>';
        // dislocation meter
        var dis = c.dislocation_cents;
        if (dis != null) {
          var pos = Math.max(0, Math.min(100, 50 + (dis / 25) * 50));
          html += '<div class="meter"><div class="mlabel">Dislocation meter — market mid vs model</div>' +
            '<div class="meterbar"><div class="zero"></div><div class="dot" style="left:' + pos.toFixed(1) + '%"></div></div>' +
            '<div class="meternums"><span>-25¢</span><span>model ' + c.model_fair_cents + '¢ · market ' + c.mid_cents + '¢ · <b>' + (dis >= 0 ? '+' : '') + dis + '¢</b></span><span>+25¢</span></div>' +
            '<div class="meterwarn">Model estimate — tested flat on 270 real trades (−$1.44, t=−0.21). Not a recommendation.</div></div>';
        } else {
          html += '<div class="meterwarn">No calibrated model for ' + esc(c.coin) + ' (insufficient research history) — observation only.</div>';
        }
        if (c.spot_ref) {
          html += '<div class="muted" style="margin-top:6px;font-size:11.5px">Spot ref $' +
            Number(c.spot_ref).toLocaleString(undefined, { maximumFractionDigits: 4 }) + ' · vol ' +
            (c.volume != null ? Number(c.volume).toLocaleString() : '—') + '</div>';
        }
      }
      html += '</div>';
    });
    el.innerHTML = html;
    el.querySelectorAll('.sidebtn').forEach(function (b) {
      b.addEventListener('click', function () { openSheet(parseInt(b.dataset.i, 10), b.dataset.side); });
    });
    tick();
  }

  function tick() {
    document.querySelectorAll('[data-cd]').forEach(function (el) {
      var s = secsLeft(el.dataset.cd);
      el.textContent = fmtCd(s);
      el.classList.toggle('hot', s >= 0 && s < 60);
    });
    // lock trade buttons near close
    document.querySelectorAll('.sidebtn').forEach(function (b) {
      var card = b.closest('.card');
      var cd = card && card.querySelector('[data-cd]');
      if (cd) {
        var s = secsLeft(cd.dataset.cd);
        b.disabled = s < TRADE_LOCK_SECS;
        if (s < TRADE_LOCK_SECS) b.title = 'Window closing — paper trading locked';
      }
    });
    renderFresh();
  }

  function renderFresh() {
    var el = document.getElementById('fresh');
    if (live && live.generated_at_utc) {
      el.innerHTML = 'Prices updated <b>' + esc(timeAgo(live.generated_at_utc)) +
        '</b> · refreshes ~every 5 min · countdowns live';
    }
  }

  /* ---------- trade sheet ---------- */
  var sheetQty = 5;
  function openSheet(i, side) {
    var c = live.coins[i];
    if (!c || !c.available) return;
    var s = secsLeft(c.close_time_utc);
    sheetState = { card: c, side: side };
    sheetQty = 5;
    document.getElementById('sh-title').textContent =
      (side === 'yes' ? '▲ Over (YES)' : '▼ Under (NO)') + ' — ' + c.coin;
    document.getElementById('sh-tkr').textContent = c.ticker + ' · closes in ' + fmtCd(s);
    var block = document.getElementById('sh-block');
    if (s < TRADE_LOCK_SECS) {
      block.style.display = 'block';
      block.textContent = 'Window closes in under ' + TRADE_LOCK_SECS + 's — paper trading locked (data may be stale).';
    } else { block.style.display = 'none'; }
    var qbtns = document.getElementById('sh-qty').querySelectorAll('button');
    qbtns.forEach(function (b) {
      b.classList.toggle('sel', parseInt(b.dataset.q, 10) === sheetQty);
      b.onclick = function () {
        sheetQty = parseInt(b.dataset.q, 10);
        qbtns.forEach(function (x) { x.classList.toggle('sel', x === b); });
        updateSheet();
      };
    });
    updateSheet();
    document.getElementById('sheetbg').classList.add('open');
    document.getElementById('sheet').classList.add('open');
  }
  function closeSheet() {
    document.getElementById('sheetbg').classList.remove('open');
    document.getElementById('sheet').classList.remove('open');
    sheetState = null;
  }
  function updateSheet() {
    if (!sheetState) return;
    var c = sheetState.card;
    var priceC = sheetState.side === 'yes' ? c.yes_ask_cents : c.no_ask_cents;
    var price = priceC / 100;
    var fee = takerFee(price) * sheetQty;
    var cost = price * sheetQty + fee;
    var maxWin = sheetQty - cost, maxLoss = -cost;
    document.getElementById('sh-price').textContent = priceC + '¢/contract';
    document.getElementById('sh-fee').textContent = fmt$(fee) + ' (Kalshi taker fee)';
    document.getElementById('sh-cost').textContent = fmt$(cost);
    document.getElementById('sh-mm').textContent = '+' + fmt$(maxWin).slice(1) + ' / ' + fmt$(maxLoss);
    var ok = cost <= paper.bankroll + 1e-9 && secsLeft(c.close_time_utc) >= TRADE_LOCK_SECS;
    var btn = document.getElementById('sh-confirm');
    btn.disabled = !ok;
    btn.textContent = cost > paper.bankroll + 1e-9 ? 'Insufficient fake bankroll' : 'Place paper trade (fake)';
    sheetState.calc = { price: price, fee: fee, cost: cost, qty: sheetQty };
  }
  function confirmTrade() {
    if (!sheetState || !sheetState.calc) return;
    var c = sheetState.card, k = sheetState.calc;
    if (k.cost > paper.bankroll + 1e-9) return;
    if (secsLeft(c.close_time_utc) < TRADE_LOCK_SECS) return;
    paper.bankroll = Math.round((paper.bankroll - k.cost) * 100) / 100;
    paper.positions.push({
      id: 'p' + Date.now(),
      coin: c.coin, series: c.series, ticker: c.ticker,
      side: sheetState.side, qty: k.qty,
      entry_dollars: Math.round(k.price * 10000) / 10000,
      fee_dollars: Math.round(k.fee * 100) / 100,
      cost_dollars: Math.round(k.cost * 100) / 100,
      target: c.target_price,
      close_time_utc: c.close_time_utc,
      placed_at_utc: new Date().toISOString()
    });
    savePaper(); gradePositions(); renderPortfolio(); closeSheet();
  }

  /* ---------- grading + portfolio ---------- */
  function settledMap() {
    var m = {};
    if (live && live.settled) live.settled.forEach(function (s) { m[s.ticker] = s.result; });
    return m;
  }
  function liveMidByTicker() {
    var m = {};
    if (live && live.coins) live.coins.forEach(function (c) {
      if (c.available && c.ticker) m[c.ticker] = c.mid_cents / 100;
    });
    return m;
  }
  function gradePositions() {
    var sm = settledMap(), changed = false;
    paper.positions = paper.positions.filter(function (p) {
      var res = sm[p.ticker];
      if (res !== 'yes' && res !== 'no') return true;
      var win = (res === 'yes') === (p.side === 'yes');
      if (win) paper.bankroll = Math.round((paper.bankroll + p.qty) * 100) / 100;
      var realized = Math.round(((win ? p.qty : 0) - p.cost_dollars) * 100) / 100;
      paper.history.push({
        coin: p.coin, ticker: p.ticker, side: p.side, qty: p.qty,
        entry_cents: Math.round(p.entry_dollars * 100),
        fee_cents: Math.round(p.fee_dollars * 100),
        result: res, win: win,
        realized_dollars: realized,
        settled_at_utc: new Date().toISOString()
      });
      changed = true;
      return false;
    });
    if (changed) savePaper();
  }
  function unrealized(p, mids) {
    var mid = mids[p.ticker];
    if (mid == null) return 0; // window gone, awaiting settlement ref
    var cur = p.side === 'yes' ? mid : (1 - mid);
    return Math.round((cur - p.entry_dollars) * p.qty * 100) / 100;
  }
  function renderPortfolio() {
    var mids = liveMidByTicker();
    var realized = 0, wins = 0, staked = 0;
    var perCoin = {};
    paper.history.forEach(function (h) {
      realized += h.realized_dollars; staked += (h.entry_cents * h.qty + h.fee_cents) / 100;
      if (h.win) wins++;
      perCoin[h.coin] = (perCoin[h.coin] || 0) + h.realized_dollars;
    });
    var n = paper.history.length;
    var unreal = paper.positions.reduce(function (a, p) { return a + unrealized(p, mids); }, 0);
    var equity = paper.bankroll + unreal;

    document.getElementById('st-bank').textContent = fmt$(paper.bankroll);
    var eqEl = document.getElementById('st-equity');
    eqEl.textContent = fmt$(equity);
    eqEl.style.color = equity >= START_BANK ? 'var(--green)' : 'var(--red)';
    var pnlEl = document.getElementById('st-pnl');
    pnlEl.textContent = (realized >= 0 ? '+' : '') + fmt$(realized);
    pnlEl.style.color = realized >= 0 ? 'var(--green)' : 'var(--red)';
    document.getElementById('st-win').textContent = n ? Math.round(100 * wins / n) + '% (' + wins + '/' + n + ')' : '—';
    document.getElementById('st-roi').textContent = staked > 0 ? (realized / staked * 100).toFixed(1) + '%' : '—';
    document.getElementById('st-n').textContent = n;

    var pe = document.getElementById('positions');
    if (!paper.positions.length) {
      pe.innerHTML = '<div class="empty">No open paper positions.</div>';
    } else {
      pe.innerHTML = paper.positions.map(function (p) {
        var u = unrealized(p, mids);
        var s = secsLeft(p.close_time_utc);
        var uCls = u >= 0 ? 'win' : 'loss';
        return '<div class="pos"><div class="ph"><span>' + esc(p.coin) + ' ' +
          (p.side === 'yes' ? '▲ Over' : '▼ Under') + ' ×' + p.qty + '</span>' +
          '<span class="' + uCls + '">' + (u >= 0 ? '+' : '') + fmt$(u) + '</span></div>' +
          '<div class="pd">entry ' + Math.round(p.entry_dollars * 100) + '¢ · fee ' + fmt$(p.fee_dollars) +
          ' · mark-to-mid · closes in ' + fmtCd(s) + '<br>' + esc(p.ticker) + '</div></div>';
      }).join('');
    }

    var pc = document.getElementById('percoin');
    var coins = Object.keys(perCoin);
    if (!coins.length) { pc.innerHTML = '<div class="empty">Nothing settled yet.</div>'; }
    else {
      pc.innerHTML = '<table class="pct"><tr><th>Coin</th><th>Realized</th></tr>' +
        coins.sort().map(function (k) {
          var v = perCoin[k];
          return '<tr><td>' + esc(k) + '</td><td class="' + (v >= 0 ? 'win' : 'loss') + '">' +
            (v >= 0 ? '+' : '') + fmt$(v) + '</td></tr>';
        }).join('') + '</table>';
    }

    var he = document.getElementById('history');
    if (!paper.history.length) {
      he.innerHTML = '<div class="empty">No paper trades yet. Tap Over/Under on the board.</div>';
    } else {
      he.innerHTML = paper.history.slice().reverse().slice(0, 50).map(function (h) {
        var cls = h.win ? 'win' : 'loss';
        return '<div class="hist"><div class="ph"><span>' + esc(h.coin) + ' ' +
          (h.side === 'yes' ? '▲ Over' : '▼ Under') + ' ×' + h.qty + '</span>' +
          '<span class="' + cls + '">' + (h.realized_dollars >= 0 ? '+' : '') + fmt$(h.realized_dollars) + '</span></div>' +
          '<div class="pd">entry ' + h.entry_cents + '¢ · ' + (h.win ? 'WON' : 'LOST') +
          ' (' + h.result.toUpperCase() + ') · fee ' + fmt$(h.fee_cents / 100) + '</div></div>';
      }).join('');
    }
  }

  /* ---------- detector ---------- */
  function renderDetector() {
    var el = document.getElementById('flags');
    var ff = document.getElementById('flagfresh');
    if (!flags) {
      ff.textContent = '';
      el.innerHTML = '<div class="empty">No scan data yet — the detector runs every ~5 minutes.</div>';
      return;
    }
    ff.textContent = 'Last scan: ' + timeAgo(flags.generated_at_utc) + ' · ' +
      Object.keys(flags.series_checked || {}).length + ' series checked';
    if (!flags.flags.length) {
      el.innerHTML = '<div class="empty">✓ No dislocations detected in the latest scan.<br><span class="muted">Empty is the normal result — the market is usually calibrated.</span></div>';
      return;
    }
    el.innerHTML = flags.flags.map(function (f) {
      var label = f.type === 'final_minutes_dislocation' ? 'Final-minutes dislocation' :
        f.type === 'fast_price_move' ? 'Fast price move' : esc(f.type);
      return '<div class="flagcard"><div class="ft">🔎 ' + esc(f.coin) + ' — ' + esc(label) + '</div>' +
        '<div class="fo">' + esc(f.observation || '') + '</div>' +
        '<div class="fm">mid ' + f.market_mid_cents + '¢ · model ' + f.model_fair_cents + '¢ · ' +
        f.seconds_remaining + 's left · ' + esc(timeAgo(f.observed_at_utc)) + '<br>' + esc(f.ticker) + '</div></div>';
    }).join('');
  }

  /* ---------- scoreboard ---------- */
  function renderScoreboard() {
    var el = document.getElementById('sb-recent');
    var ff = document.getElementById('sb-fresh');
    if (!scoreboard) {
      ff.textContent = '';
      el.innerHTML = '<div class="empty">No scoreboard data yet — the scorer runs every ~5 minutes.</div>';
      document.getElementById('sb-picks').textContent = '—';
      document.getElementById('sb-settled').textContent = '—';
      document.getElementById('sb-wins').textContent = '—';
      document.getElementById('sb-winrate').textContent = '—';
      document.getElementById('sb-pnl').textContent = '—';
      return;
    }
    ff.textContent = 'Updated ' + timeAgo(scoreboard.updated_at) + ' · demonstration only, no money involved';
    document.getElementById('sb-picks').textContent = scoreboard.n_picks;
    document.getElementById('sb-settled').textContent = scoreboard.n_settled;
    document.getElementById('sb-wins').textContent = scoreboard.wins;
    document.getElementById('sb-winrate').textContent =
      scoreboard.win_rate != null ? (scoreboard.win_rate * 100).toFixed(1) + '%' : '—';
    var pnlEl = document.getElementById('sb-pnl');
    var pnlD = scoreboard.pnl_cents / 100;
    pnlEl.textContent = (pnlD >= 0 ? '+' : '') + fmt$(pnlD);
    pnlEl.style.color = pnlD >= 0 ? 'var(--green)' : 'var(--red)';

    var recent = scoreboard.recent || [];
    if (!recent.length) {
      el.innerHTML = '<div class="empty">No leans logged yet.</div>';
      return;
    }
    el.innerHTML = recent.map(function (r) {
      var leanTxt = r.lean === 'over' ? '▲ model favored Over' :
        r.lean === 'under' ? '▼ model favored Under' : '— no lean (within costs)';
      var outTxt, cls;
      if (r.outcome === 'win') { outTxt = 'WON +' + (r.pnl_cents / 100).toFixed(2); cls = 'win'; }
      else if (r.outcome === 'loss') { outTxt = 'LOST ' + (r.pnl_cents / 100).toFixed(2); cls = 'loss'; }
      else { outTxt = 'pending'; cls = ''; }
      return '<div class="hist"><div class="ph"><span>' + esc(r.coin) + ' · ' + leanTxt + '</span>' +
        '<span class="' + cls + '">' + esc(outTxt) + '</span></div>' +
        '<div class="pd">model ' + (r.model_p * 100).toFixed(1) + '¢ · market mid ' + r.market_mid_cents +
        '¢ · logged ' + esc(timeAgo(r.recorded_at)) + '<br>' + esc(r.ticker) + '</div></div>';
    }).join('');
  }

  /* ---------- tabs / wiring ---------- */
  document.querySelectorAll('.tabbar button').forEach(function (b) {
    b.addEventListener('click', function () {
      document.querySelectorAll('.tabbar button').forEach(function (x) { x.classList.remove('sel'); });
      b.classList.add('sel');
      document.querySelectorAll('.tabpage').forEach(function (p) { p.classList.remove('active'); });
      document.getElementById('tab-' + b.dataset.tab).classList.add('active');
      window.scrollTo(0, 0);
    });
  });
  document.getElementById('sh-confirm').addEventListener('click', confirmTrade);
  document.getElementById('sh-cancel').addEventListener('click', closeSheet);
  document.getElementById('sheetbg').addEventListener('click', closeSheet);
  document.getElementById('resetbtn').addEventListener('click', function () {
    if (confirm('Reset the paper simulator to $1,000 fake? Trade history will be cleared.')) {
      paper = { bankroll: START_BANK, positions: [], history: [] };
      savePaper(); renderPortfolio();
    }
  });

  fetchAll();
  setInterval(fetchAll, 60000);
  setInterval(tick, 1000);
})();
