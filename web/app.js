/* ============================================================
   OpenCode Token Tracker — Dashboard v2

   Chart.js-powered analytics dashboard. Fetches from the
   tracker API, renders stat cards and five charts, auto-refreshes,
   handles dark/light themes, and degrades gracefully on error.
   ============================================================ */
(function () {
  'use strict';

  /* ── DOM refs ──────────────────────────────────────────── */
  var $ = function (id) { return document.getElementById(id); };
  var syncDot = $('syncDot');
  var syncText = $('syncText');
  var errorBanner = $('errorBanner');
  var errorMsg = $('errorBannerMsg');
  var rangeTabs = $('rangeTabs');

  /* stat cards */
  var statTokens = $('statTokens');
  var statTokensSub = $('statTokensSub');
  var statCost = $('statCost');
  var statCostSub = $('statCostSub');
  var statSessions = $('statSessions');
  var statSessionsSub = $('statSessionsSub');
  var statBudget = $('statBudget');
  var statBudgetSub = $('statBudgetSub');
  var budgetFill = $('budgetFill');
  var statBudgetCard = statBudget.closest('.stat-card');

  /* ── Chart color palette ───────────────────────────────── */
  function cssVar(name) {
    return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  }

  var COLORS = {
    input:     { bg: 'rgba(34,197,94,0.7)',  border: '#22c55e' },  /* green */
    output:    { bg: 'rgba(168,85,247,0.7)', border: '#a855f7' },  /* purple */
    reasoning: { bg: 'rgba(59,130,246,0.7)', border: '#3b82f6' },  /* blue */
    cacheRead: { bg: 'rgba(6,182,212,0.7)',  border: '#06b6d4' },  /* cyan */
    cacheWrite:{ bg: 'rgba(249,115,22,0.7)', border: '#f97316' },  /* coral */
  };

  var MODEL_COLORS = [
    '#22c55e', '#3b82f6', '#a855f7', '#f59e0b', '#06b6d4',
    '#f97316', '#ec4899', '#8b5cf6', '#14b8a6', '#eab308'
  ];

  var TOKEN_LABELS = {
    input: 'Input', output: 'Output', reasoning: 'Reasoning',
    cache_read: 'Cache Read', cache_write: 'Cache Write'
  };

  var TOKEN_KEYS = ['input', 'output', 'reasoning', 'cache_read', 'cache_write'];

  /* ── State ─────────────────────────────────────────────── */
  var RANGES = {
    daily:   { groupBy: 'day',   days: 29 },
    weekly:  { groupBy: 'week',  weeks: 11 },
    monthly: { groupBy: 'month', months: 11 },
    all:     { groupBy: 'month', allTime: true }
  };
  var currentRange = 'monthly';
  var refreshSeconds = 30;
  var timer = null;
  var inFlight = false;
  var seq = 0;
  var lastSuccessAt = null;
  var lastSummary = null;

  /* Chart instances — destroyed and re-created on theme change */
  var charts = {};

  /* ── Helpers ───────────────────────────────────────────── */
  function pad2(n) { return n < 10 ? '0' + n : String(n); }
  function timeStr(d) { return pad2(d.getHours()) + ':' + pad2(d.getMinutes()) + ':' + pad2(d.getSeconds()); }

  function formatTokens(n) {
    n = Math.max(0, Math.round(n || 0));
    if (n >= 1e9) return (n / 1e9).toFixed(1).replace(/\.0$/, '') + 'B';
    if (n >= 1e6) return (n / 1e6).toFixed(1).replace(/\.0$/, '') + 'M';
    if (n >= 1e4) return (n / 1e3).toFixed(1).replace(/\.0$/, '') + 'K';
    return n.toLocaleString('en-US');
  }

  function formatCost(x) {
    if (x === 0) return '$0.00';
    if (x < 0.01) return '<$0.01';
    return '$' + x.toFixed(2);
  }

  function formatPct(x) { return x.toFixed(1) + '%'; }

  function rangeBounds(range) {
    var now = new Date();
    var from;
    if (range.allTime) { from = 0; }
    else {
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
          err.body = body; throw err;
        });
      }
      return resp.json();
    });
  }

  /* ── Sync status ───────────────────────────────────────── */
  function setLive() {
    syncDot.className = 'sync-dot live';
    syncText.textContent = 'Live · ' + timeStr(lastSuccessAt);
  }
  function setOffline() {
    syncDot.className = 'sync-dot off';
    syncText.textContent = lastSuccessAt
      ? 'Offline · ' + timeStr(lastSuccessAt) : 'Offline';
  }
  function showError(msg) { errorMsg.textContent = msg; errorBanner.classList.add('show'); }
  function hideError() { errorBanner.classList.remove('show'); }

  /* ── Chart.js global defaults ──────────────────────────── */
  function applyChartDefaults() {
    var text2 = cssVar('--text-2') || '#a0a0ab';
    var text3 = cssVar('--text-3') || '#63636e';
    var border = cssVar('--border') || 'rgba(255,255,255,0.06)';
    Chart.defaults.font.family = "'Rubik', system-ui, sans-serif";
    Chart.defaults.font.size = 11;
    Chart.defaults.color = text3;
    Chart.defaults.plugins.legend.display = false;
    Chart.defaults.plugins.tooltip.backgroundColor = cssVar('--surface-2') || '#1e1e23';
    Chart.defaults.plugins.tooltip.titleColor = cssVar('--text') || '#f0f0f2';
    Chart.defaults.plugins.tooltip.bodyColor = text2;
    Chart.defaults.plugins.tooltip.borderColor = cssVar('--border-strong') || 'rgba(255,255,255,0.12)';
    Chart.defaults.plugins.tooltip.borderWidth = 1;
    Chart.defaults.plugins.tooltip.padding = 10;
    Chart.defaults.plugins.tooltip.cornerRadius = 8;
    Chart.defaults.plugins.tooltip.displayColors = true;
    Chart.defaults.plugins.tooltip.boxPadding = 4;
    Chart.defaults.scale.grid = { color: border, drawBorder: false };
    Chart.defaults.scale.ticks = { color: text3, font: { size: 10 } };
  }

  /* ── Destroy all charts (for theme re-render) ──────────── */
  function destroyCharts() {
    Object.keys(charts).forEach(function (k) {
      if (charts[k]) { charts[k].destroy(); charts[k] = null; }
    });
  }

  /* ── Render: stat cards ────────────────────────────────── */
  function renderStats(summary) {
    if (!summary) return;
    var t = summary.totals;
    var b = summary.budget;

    statTokens.textContent = formatTokens(t.tokens.input + t.tokens.output + t.tokens.reasoning + t.tokens.cache_read + t.tokens.cache_write);
    statTokensSub.textContent = 'input ' + formatTokens(t.tokens.input) + ' · output ' + formatTokens(t.tokens.output);

    var totalCost = t.cost || 0;
    statCost.textContent = formatCost(totalCost);
    statCostSub.textContent = totalCost === 0 && t.tokens.input > 0 ? 'All free models' : (t.sessions > 0 ? formatCost(totalCost / t.sessions) + ' avg/session' : '');

    statSessions.textContent = t.sessions.toLocaleString('en-US');
    statSessionsSub.textContent = t.unpriced_sessions > 0 ? t.unpriced_sessions + ' unpriced' : '';

    if (b.monthly > 0) {
      var pct = Math.min(b.percent, 100);
      statBudget.textContent = formatCost(b.spent) + ' / ' + formatCost(b.monthly);
      budgetFill.style.width = pct + '%';
      statBudgetSub.textContent = formatCost(b.remaining) + ' left · projected ' + formatCost(b.projected);
      statBudgetCard.className = 'stat-card stat-card--budget' + (b.alert === 'warn' ? ' warn' : b.alert === 'exceeded' ? ' exceeded' : '');
    } else {
      statBudget.textContent = 'No budget';
      budgetFill.style.width = '0%';
      statBudgetSub.textContent = 'Set budget.monthly in config';
      statBudgetCard.className = 'stat-card stat-card--budget';
    }
  }

  /* ── Render: token usage over time ─────────────────────── */
  function renderTokenChart(rows) {
    var canvas = $('chartTokenUsage');
    var empty = $('chartEmpty');
    if (!rows || !rows.length) { empty.style.display = 'flex'; if (charts.token) { charts.token.destroy(); charts.token = null; } return; }
    empty.style.display = 'none';

    var labels = rows.map(function (r) { return r.label; });
    var datasets = TOKEN_KEYS.map(function (key, i) {
      var c = COLORS[key === 'cache_read' ? 'cacheRead' : key === 'cache_write' ? 'cacheWrite' : key];
      return {
        label: TOKEN_LABELS[key],
        data: rows.map(function (r) { return r.tokens[key] || 0; }),
        backgroundColor: c.bg,
        borderColor: c.border,
        borderWidth: 1,
        borderRadius: 2,
        borderSkipped: false,
      };
    });

    if (charts.token) charts.token.destroy();
    charts.token = new Chart(canvas, {
      type: 'bar',
      data: { labels: labels, datasets: datasets },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: 'index', intersect: false },
        scales: {
          x: { stacked: true, grid: { display: false }, ticks: { maxRotation: 0, autoSkipPadding: 20 } },
          y: { stacked: true, beginAtZero: true, ticks: { callback: function (v) { return formatTokens(v); } } }
        },
        plugins: {
          tooltip: {
            callbacks: {
              label: function (ctx) { return ctx.dataset.label + ': ' + formatTokens(ctx.raw); },
              footer: function (items) { var sum = items.reduce(function (s, i) { return s + i.raw; }, 0); return 'Total: ' + formatTokens(sum); }
            }
          }
        }
      }
    });

    /* build legend */
    var legendEl = $('chartLegend');
    legendEl.innerHTML = datasets.map(function (d) {
      return '<span class="legend-item"><span class="legend-dot" style="background:' + d.borderColor + '"></span>' + d.label + '</span>';
    }).join('');
  }

  /* ── Render: token composition doughnut ────────────────── */
  function renderComposition(summary) {
    var canvas = $('chartComposition');
    var empty = $('compEmpty');
    if (!summary) { empty.style.display = 'flex'; if (charts.comp) { charts.comp.destroy(); charts.comp = null; } return; }
    var t = summary.totals.tokens;
    var total = TOKEN_KEYS.reduce(function (s, k) { return s + (t[k] || 0); }, 0);
    if (total <= 0) { empty.style.display = 'flex'; if (charts.comp) { charts.comp.destroy(); charts.comp = null; } return; }
    empty.style.display = 'none';

    var values = TOKEN_KEYS.map(function (k) { return t[k] || 0; });
    var colors = TOKEN_KEYS.map(function (k) { var ck = k === 'cache_read' ? 'cacheRead' : k === 'cache_write' ? 'cacheWrite' : k; return COLORS[ck].border; });
    var labels = TOKEN_KEYS.map(function (k) { return TOKEN_LABELS[k]; });

    if (charts.comp) charts.comp.destroy();
    charts.comp = new Chart(canvas, {
      type: 'doughnut',
      data: {
        labels: labels,
        datasets: [{ data: values, backgroundColor: colors, borderColor: cssVar('--surface') || '#141416', borderWidth: 3, hoverOffset: 6 }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        cutout: '60%',
        plugins: {
          legend: { display: true, position: 'bottom', labels: { boxWidth: 10, padding: 12, font: { size: 11 }, color: cssVar('--text-2') || '#a0a0ab' } },
          tooltip: {
            callbacks: {
              label: function (ctx) {
                var pct = (ctx.raw / total * 100).toFixed(1);
                return ctx.label + ': ' + formatTokens(ctx.raw) + ' (' + pct + '%)';
              }
            }
          }
        }
      }
    });
  }

  /* ── Render: horizontal bar chart (model cost / tokens / project) ── */
  function renderHBar(canvasId, emptyId, rows, valueKey, titleFn, colorList) {
    var canvas = $(canvasId);
    var empty = $(emptyId);
    var filtered = (rows || []).filter(function (r) { return (r[valueKey] || 0) > 0; });
    if (!filtered.length) { empty.style.display = 'flex'; if (charts[canvasId]) { charts[canvasId].destroy(); charts[canvasId] = null; } return; }
    empty.style.display = 'none';

    filtered.sort(function (a, b) { return (b[valueKey] || 0) - (a[valueKey] || 0); });
    var top = filtered.slice(0, 10);
    var labels = top.map(function (r) { return r.label || r.key; });
    var values = top.map(function (r) { return r[valueKey] || 0; });
    var colors = top.map(function (_, i) { return colorList[i % colorList.length]; });

    if (charts[canvasId]) charts[canvasId].destroy();
    charts[canvasId] = new Chart(canvas, {
      type: 'bar',
      data: {
        labels: labels,
        datasets: [{
          data: values,
          backgroundColor: colors.map(function (c) { return c + 'cc'; }),
          borderColor: colors,
          borderWidth: 1,
          borderRadius: 4,
          borderSkipped: false,
        }]
      },
      options: {
        indexAxis: 'y',
        responsive: true,
        maintainAspectRatio: false,
        scales: {
          x: { beginAtZero: true, ticks: { callback: titleFn.tick || function (v) { return v; } } },
          y: { grid: { display: false }, ticks: { font: { size: 11, weight: '500' } } }
        },
        plugins: {
          tooltip: {
            callbacks: {
              label: function (ctx) { return titleFn.tip(ctx.raw, top[ctx.dataIndex]); }
            }
          }
        }
      }
    });
  }

  /* ── Render: cost by model ─────────────────────────────── */
  function renderCostModel(rows) {
    renderHBar('chartCostModel', 'costModelEmpty', rows, 'cost',
      {
        tick: function (v) { return formatCost(v); },
        tip: function (v, row) { return (row.label || row.key) + ': ' + formatCost(v); }
      },
      MODEL_COLORS
    );
  }

  /* ── Render: tokens by model ───────────────────────────── */
  function renderModelTokens(rows) {
    renderHBar('chartModelTokens', 'modelTokensEmpty', rows, '_totalTokens',
      {
        tick: function (v) { return formatTokens(v); },
        tip: function (v, row) { return (row.label || row.key) + ': ' + formatTokens(v); }
      },
      MODEL_COLORS
    );
  }

  /* ── Render: usage by project ──────────────────────────── */
  function renderProject(rows) {
    renderHBar('chartProject', 'projectEmpty', rows, 'cost',
      {
        tick: function (v) { return formatCost(v); },
        tip: function (v, row) { return (row.label || row.key) + ': ' + formatCost(v) + ' · ' + formatTokens(row._totalTokens || 0) + ' tokens'; }
      },
      ['#22c55e', '#3b82f6', '#a855f7', '#f59e0b', '#06b6d4', '#f97316']
    );
  }

  /* ── Data fetch + render cycle ─────────────────────────── */
  function refresh() {
    if (inFlight) return;
    inFlight = true;
    var mySeq = ++seq;
    var range = RANGES[currentRange];
    var bounds = rangeBounds(range);
    var q = 'from=' + bounds.from + '&to=' + bounds.to;

    fetchJSON('/api/config')
      .then(function (cfg) {
        var secs = Number(cfg.refresh_seconds);
        if (secs > 0 && secs !== refreshSeconds) { refreshSeconds = secs; startPolling(); }
        return fetchJSON('/api/summary?' + q);
      })
      .then(function (summary) {
        if (mySeq !== seq) return;
        lastSummary = summary;
        renderStats(summary);

        /* compute _totalTokens on each model/project row for the token charts */
        function addTotal(rows) {
          (rows || []).forEach(function (r) {
            r._totalTokens = TOKEN_KEYS.reduce(function (s, k) { return s + (r.tokens[k] || 0); }, 0);
          });
        }
        addTotal(summary.by_model);
        addTotal(summary.by_project);

        renderComposition(summary);
        renderModelTokens(summary.by_model);
        renderCostModel(summary.by_model);
        renderProject(summary.by_project);

        /* fetch time series */
        return fetchJSON('/api/breakdown?group_by=' + range.groupBy + '&' + q);
      })
      .then(function (data) {
        if (mySeq !== seq) return;
        var rows = (data.rows || []).slice().sort(function (a, b) { return a.key < b.key ? -1 : a.key > b.key ? 1 : 0; });
        renderTokenChart(rows);
        lastSuccessAt = new Date();
        setLive();
        hideError();
      })
      .catch(function (err) {
        if (mySeq !== seq) return;
        setOffline();
        showError(err.status === 503 ? 'Database unavailable' : 'Server unreachable — retrying…');
      })
      .then(function () {
        if (mySeq === seq) inFlight = false;
      });
  }

  function startPolling() {
    if (timer) clearInterval(timer);
    timer = setInterval(refresh, refreshSeconds * 1000);
  }

  /* ── Theme change → re-render charts with new colors ───── */
  function onThemeChange() {
    destroyCharts();
    applyChartDefaults();
    if (lastSummary) {
      /* re-render composition, model tokens, cost model, project from cached summary */
      renderComposition(lastSummary);
      var addTotal = function (rows) {
        (rows || []).forEach(function (r) {
          r._totalTokens = TOKEN_KEYS.reduce(function (s, k) { return s + (r.tokens[k] || 0); }, 0);
        });
      };
      addTotal(lastSummary.by_model);
      addTotal(lastSummary.by_project);
      renderModelTokens(lastSummary.by_model);
      renderCostModel(lastSummary.by_model);
      renderProject(lastSummary.by_project);
    }
    /* refetch time series with new colors */
    var range = RANGES[currentRange];
    var bounds = rangeBounds(range);
    fetchJSON('/api/breakdown?group_by=' + range.groupBy + '&from=' + bounds.from + '&to=' + bounds.to)
      .then(function (data) {
        var rows = (data.rows || []).slice().sort(function (a, b) { return a.key < b.key ? -1 : a.key > b.key ? 1 : 0; });
        renderTokenChart(rows);
      })
      .catch(function () {});
  }

  /* ── Wiring ────────────────────────────────────────────── */
  applyChartDefaults();

  /* Range tabs */
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

  /* Theme observer */
  if (window.MutationObserver) {
    new MutationObserver(onThemeChange).observe(document.documentElement, {
      attributes: true, attributeFilter: ['data-theme']
    });
  }

  /* Start */
  refresh();
  startPolling();
})();
