/* OpenCode Token Tracker — dashboard data layer (T-012).
 *
 * Everything dynamic on top of the T-011 shell: the range selector, the
 * hand-rolled SVG stacked token chart, the per-model panel, and the
 * auto-refresh loop with live/offline sync status. No chart library, no
 * external requests — only the tracker's own API:
 *
 *   GET /api/config                       -> { ..., refresh_seconds }
 *   GET /api/breakdown?group_by=day|week|month|model&from=<ms>&to=<ms>
 *                                         -> { rows: [{key, label, sessions,
 *                                             tokens: {input, output, ...}, cost}] }
 *
 * The chart plots input + output per bucket (the two series the legend
 * names); the model panel uses the same definition so both panels always
 * reconcile. Rows arrive sorted by cost desc from the API, but a time
 * series must be chronological, so the chart re-sorts by key (all bucket
 * keys — YYYY-MM-DD, YYYY-Www, YYYY-MM — sort lexicographically in time
 * order).
 */
(function () {
  'use strict';

  /* ── DOM refs ──────────────────────────────────────────── */
  var chartEl = document.getElementById('chart');
  var chartEmpty = document.getElementById('chartEmpty');
  var modelSplit = document.getElementById('modelSplit');
  var modelEmpty = document.getElementById('modelEmpty');
  var errorBanner = document.getElementById('errorBanner');
  var errorMsg = document.getElementById('errorBannerMsg');
  var syncDot = document.getElementById('syncDot');
  var syncText = document.getElementById('syncText');
  var rangeTabs = document.getElementById('rangeTabs');

  /* ── state ─────────────────────────────────────────────── */
  var RANGES = {
    daily:   { groupBy: 'day',   days: 29 },   // now - 29 days
    weekly:  { groupBy: 'week',  weeks: 11 },  // now - 11 weeks
    monthly: { groupBy: 'month', months: 11 }, // now - 11 months
    all:     { groupBy: 'month', allTime: true }
  };
  var currentRange = 'all';
  var refreshSeconds = 30;
  var timer = null;
  var inFlight = false;
  var seq = 0;          // guards against out-of-order responses
  var lastSuccessAt = null;
  var lastData = null;  // { chartRows, modelRows } — kept across failures

  /* ── tiny style block for data-layer-only elements ────────
     (.model-pct and SVG text classes have no home in style.css,
     which is frozen; injecting keeps the data layer self-contained.) */
  var appStyle = document.createElement('style');
  appStyle.textContent = [
    '.model-pct { font-size: 12px; color: var(--text-3); font-variant-numeric: tabular-nums; min-width: 44px; text-align: right; white-space: nowrap; }',
    '.chart .tick-label { font-family: var(--font-mono); font-size: 10.5px; fill: var(--text-3); }',
    '.chart .x-label { font-size: 11px; fill: var(--text-3); }'
  ].join('\n');
  document.head.appendChild(appStyle);

  /* ── helpers ───────────────────────────────────────────── */
  function pad2(n) { return n < 10 ? '0' + n : String(n); }

  function timeStr(d) {
    return pad2(d.getHours()) + ':' + pad2(d.getMinutes()) + ':' + pad2(d.getSeconds());
  }

  function cssVar(name) {
    return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  }

  /* 1.2M / 585K / 1234 — one decimal, dropped when .0. */
  function formatTokens(n) {
    n = Math.max(0, Math.round(n || 0));
    if (n >= 1000000) return trimOne(n / 1000000) + 'M';
    if (n >= 10000) return trimOne(n / 1000) + 'K';
    return String(n);
  }

  function trimOne(v) {
    var s = v.toFixed(1);
    return s.slice(-2) === '.0' ? s.slice(0, -2) : s;
  }

  /* Exact counts for tooltips: 1,234,567. */
  function exact(n) {
    return Math.round(n || 0).toLocaleString('en-US');
  }

  /* Smallest "nice" axis ceiling: 1 / 2 / 5 × 10^k. */
  function niceCeil(v) {
    if (v <= 0) return 1;
    var mag = Math.pow(10, Math.floor(Math.log10(v)));
    var norm = v / mag;
    return (norm <= 1 ? 1 : norm <= 2 ? 2 : norm <= 5 ? 5 : 10) * mag;
  }

  function bucketTokens(row) {
    return (row.tokens.input || 0) + (row.tokens.output || 0);
  }

  function byKey(a, b) { return a.key < b.key ? -1 : a.key > b.key ? 1 : 0; }

  function rangeBounds(range) {
    var now = new Date();
    var from;
    if (range.allTime) {
      from = 0;
    } else {
      var d = new Date(now);
      if (range.days) d.setDate(d.getDate() - range.days);
      else if (range.weeks) d.setDate(d.getDate() - range.weeks * 7);
      else if (range.months) { d.setDate(1); d.setMonth(d.getMonth() - range.months); }
      from = d.getTime();
    }
    return { from: from, to: now.getTime() };
  }

  function fetchJSON(url) {
    return fetch(url, { headers: { Accept: 'application/json' } }).then(function (resp) {
      if (!resp.ok) {
        var err = new Error('HTTP ' + resp.status + ' ' + url);
        err.status = resp.status;
        return resp.json().catch(function () { return {}; }).then(function (body) {
          err.body = body;
          throw err;
        });
      }
      return resp.json();
    });
  }

  /* ── sync status ───────────────────────────────────────── */
  function setLive() {
    syncDot.classList.add('live');
    syncDot.classList.remove('off');
    syncText.textContent = 'Live · updated ' + timeStr(lastSuccessAt);
  }

  function setOffline() {
    syncDot.classList.remove('live');
    syncDot.classList.add('off');
    syncText.textContent = lastSuccessAt
      ? 'Offline · last update ' + timeStr(lastSuccessAt)
      : 'Offline · no data yet';
  }

  function showError(msg) {
    errorMsg.textContent = msg;
    errorBanner.classList.add('show');
  }

  function hideError() {
    errorBanner.classList.remove('show');
  }

  /* ── token usage chart (hand-rolled SVG) ───────────────── */
  function svgEl(tag, attrs) {
    var el = document.createElementNS('http://www.w3.org/2000/svg', tag);
    for (var k in attrs) {
      if (Object.prototype.hasOwnProperty.call(attrs, k)) el.setAttribute(k, attrs[k]);
    }
    return el;
  }

  function renderChart(rows) {
    var totals = rows.map(bucketTokens);
    var max = totals.length ? Math.max.apply(null, totals) : 0;
    if (!rows.length || max <= 0) {
      chartEl.textContent = '';
      chartEmpty.style.display = '';
      return;
    }
    chartEmpty.style.display = 'none';

    var W = chartEl.clientWidth || 800;
    var H = chartEl.clientHeight || 300;
    var padL = 46, padR = 8, padT = 10, padB = 24;
    var plotW = Math.max(10, W - padL - padR);
    var plotH = Math.max(10, H - padT - padB);
    var yMax = niceCeil(max);
    var y = function (v) { return padT + plotH - (v / yMax) * plotH; };
    var baseline = y(0);

    var n = rows.length;
    var slot = plotW / n;
    var barW = Math.min(slot * 0.62, 36);

    var inColor = cssVar('--accent') || '#c8f04e';
    var outColor = cssVar('--series-2') || '#8b7cf6';

    var inSum = 0, outSum = 0;
    rows.forEach(function (r) { inSum += r.tokens.input || 0; outSum += r.tokens.output || 0; });

    var svg = svgEl('svg', {
      viewBox: '0 0 ' + W + ' ' + H,
      role: 'img',
      'aria-label': 'Token usage, ' + n + ' buckets — input ' +
        formatTokens(inSum) + ', output ' + formatTokens(outSum)
    });

    /* gridlines + y-axis labels at 0 / 50% / max */
    [0, 0.5, 1].forEach(function (f) {
      var v = yMax * f;
      var gy = y(v);
      svg.appendChild(svgEl('line', {
        x1: padL, y1: gy, x2: W - padR, y2: gy,
        stroke: cssVar('--border') || 'rgba(255,255,255,0.08)', 'stroke-width': 1
      }));
      var label = svgEl('text', {
        x: padL - 6, y: gy + 3.5, 'text-anchor': 'end', 'class': 'tick-label'
      });
      label.textContent = formatTokens(v);
      svg.appendChild(label);
    });

    /* bars — input (accent) below, output (series-2) stacked above */
    rows.forEach(function (row, i) {
      var inT = row.tokens.input || 0;
      var outT = row.tokens.output || 0;
      var total = inT + outT;
      var x = padL + i * slot + (slot - barW) / 2;

      if (inT > 0) {
        var inRect = svgEl('rect', {
          x: x, y: y(inT), width: barW, height: Math.max(1, baseline - y(inT)),
          fill: inColor, rx: 2
        });
        var inTitle = svgEl('title');
        inTitle.textContent = row.label + ' — input ' + exact(inT);
        inRect.appendChild(inTitle);
        svg.appendChild(inRect);
      }
      if (outT > 0) {
        var outRect = svgEl('rect', {
          x: x, y: y(total), width: barW, height: Math.max(1, y(inT) - y(total)),
          fill: outColor, rx: 2
        });
        var outTitle = svgEl('title');
        outTitle.textContent = row.label + ' — output ' + exact(outT);
        outRect.appendChild(outTitle);
        svg.appendChild(outRect);
      }
      /* transparent hit rect spanning the whole bar: one tooltip per bucket */
      var hit = svgEl('rect', {
        x: x, y: y(total), width: barW, height: Math.max(1, baseline - y(total)),
        fill: 'transparent'
      });
      var hitTitle = svgEl('title');
      hitTitle.textContent = row.label + ' — input ' + exact(inT) +
        ' · output ' + exact(outT) + ' · total ' + exact(total);
      hit.appendChild(hitTitle);
      svg.appendChild(hit);

      if (shouldLabel(i, n, slot)) {
        var xl = svgEl('text', {
          x: x + barW / 2, y: H - 8, 'text-anchor': 'middle', 'class': 'x-label'
        });
        xl.textContent = row.label;
        svg.appendChild(xl);
      }
    });

    chartEl.textContent = '';
    chartEl.appendChild(svg);
  }

  /* Label every ceil(n/8)-th bucket; also the last one when it clears the
     previous label by more than one label width (~34px). */
  function shouldLabel(i, n, slot) {
    var step = Math.max(1, Math.ceil(n / 8));
    if (i % step === 0) return true;
    if (i === n - 1) {
      var lastLabeled = Math.floor((n - 1) / step) * step;
      return (i - lastLabeled) * slot > 34;
    }
    return false;
  }

  /* ── usage by model ────────────────────────────────────── */
  function renderModels(rows) {
    var withTokens = rows.filter(function (r) { return bucketTokens(r) > 0; });
    var grand = withTokens.reduce(function (sum, r) { return sum + bucketTokens(r); }, 0);
    if (!withTokens.length || grand <= 0) {
      modelSplit.textContent = '';
      modelEmpty.style.display = '';
      return;
    }
    modelEmpty.style.display = 'none';

    /* sorted desc by token count, key asc on ties */
    withTokens.sort(function (a, b) {
      var d = bucketTokens(b) - bucketTokens(a);
      return d !== 0 ? d : (a.key < b.key ? -1 : a.key > b.key ? 1 : 0);
    });

    var frag = document.createDocumentFragment();
    withTokens.forEach(function (row) {
      var total = bucketTokens(row);
      var pct = total / grand * 100;
      var pctText = trimOne(pct) + '%';

      var rowEl = document.createElement('div');
      rowEl.className = 'model-row';

      var name = document.createElement('span');
      name.className = 'model-name';
      name.textContent = row.label || row.key;
      name.title = row.label || row.key;

      var bar = document.createElement('div');
      bar.className = 'model-bar';
      var fill = document.createElement('i');
      fill.style.width = pct + '%';
      bar.appendChild(fill);

      var pctEl = document.createElement('span');
      pctEl.className = 'model-pct';
      pctEl.textContent = pctText;

      var val = document.createElement('span');
      val.className = 'model-val';
      val.textContent = formatTokens(total);

      rowEl.appendChild(name);
      rowEl.appendChild(bar);
      rowEl.appendChild(pctEl);
      rowEl.appendChild(val);
      frag.appendChild(rowEl);
    });

    modelSplit.textContent = '';
    modelSplit.appendChild(frag);
  }

  /* ── fetch + render cycle ────────────────────────────────
     Requests are sequential: an earlier thread-bound-sqlite race in the
     server was fixed in tracker/db.py (check_same_thread=False); the
     serial chain is kept as a harmless simplification. On localhost the
     extra round-trips cost milliseconds. */
  function refresh() {
    if (inFlight) return;
    inFlight = true;
    var mySeq = ++seq;
    var range = RANGES[currentRange];
    var bounds = rangeBounds(range);
    var q = 'from=' + bounds.from + '&to=' + bounds.to;
    var chartUrl = '/api/breakdown?group_by=' + range.groupBy + '&' + q;
    var modelUrl = '/api/breakdown?group_by=model&' + q;

    fetchJSON('/api/config')
      .then(function (cfg) {
        var secs = Number(cfg.refresh_seconds);
        if (secs > 0 && secs !== refreshSeconds) {
          refreshSeconds = secs;
          startPolling();
        }
        return fetchJSON(chartUrl);
      })
      .then(function (chartData) {
        if (mySeq !== seq) return;
        lastData = {
          chartRows: (chartData.rows || []).slice().sort(byKey),
          modelRows: lastData ? lastData.modelRows : []
        };
        renderChart(lastData.chartRows);
        return fetchJSON(modelUrl);
      })
      .then(function (modelData) {
        if (mySeq !== seq) return;
        lastData.modelRows = modelData.rows || [];
        renderModels(lastData.modelRows);
        lastSuccessAt = new Date();
        setLive();
        hideError();
      })
      .catch(function (err) {
        if (mySeq !== seq) return;
        /* keep last data on screen; only the status/banner change */
        setOffline();
        showError(err.status === 503
          ? 'Database temporarily unavailable'
          : 'Dashboard server unreachable — retrying…');
      })
      .then(function () {
        if (mySeq === seq) inFlight = false;
      });
  }

  function startPolling() {
    if (timer) clearInterval(timer);
    timer = setInterval(refresh, refreshSeconds * 1000);
  }

  /* ── wiring ────────────────────────────────────────────── */
  var activeTab = rangeTabs.querySelector('.range-tab[aria-pressed="true"]');
  if (activeTab) currentRange = activeTab.dataset.range;

  rangeTabs.addEventListener('click', function (e) {
    var btn = e.target.closest('.range-tab');
    if (!btn || btn.dataset.range === currentRange) return;
    currentRange = btn.dataset.range;
    rangeTabs.querySelectorAll('.range-tab').forEach(function (b) {
      b.setAttribute('aria-pressed', String(b === btn));
    });
    refresh();
  });

  /* Re-render on theme change: bar colors come from CSS variables. */
  if (window.MutationObserver) {
    new MutationObserver(function () {
      if (lastData) renderChart(lastData.chartRows);
    }).observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] });
  }

  var resizeTimer = null;
  window.addEventListener('resize', function () {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(function () {
      if (lastData) renderChart(lastData.chartRows);
    }, 150);
  });

  refresh();
  startPolling();
})();