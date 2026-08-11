/* ============================================================
   OpenCode Token Tracker — Dashboard v3 (Full Analytics)

   Chart.js-powered analytics dashboard with 10 sections:
   stat cards, token usage, cost over time, composition,
   cache efficiency, cost/tokens by model, project/agent
   breakdowns, session activity, and 4 detailed data tables.
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

  /* ── Chart color palette ───────────────────────────────── */
  function cssVar(n) {
    return getComputedStyle(document.documentElement).getPropertyValue(n).trim();
  }

  var TOKEN_COLORS = {
    input:      '#22c55e',
    output:     '#a855f7',
    reasoning:  '#3b82f6',
    cache_read: '#06b6d4',
    cache_write:'#f97316'
  };
  var TOKEN_BG = {
    input:      'rgba(34,197,94,0.65)',
    output:     'rgba(168,85,247,0.65)',
    reasoning:  'rgba(59,130,246,0.65)',
    cache_read: 'rgba(6,182,212,0.65)',
    cache_write:'rgba(249,115,22,0.65)'
  };
  var TOKEN_LABELS = {
    input:'Input', output:'Output', reasoning:'Reasoning',
    cache_read:'Cache Read', cache_write:'Cache Write'
  };
  var TOKEN_KEYS = ['input','output','reasoning','cache_read','cache_write'];

  var MODEL_COLORS = [
    '#22c55e','#3b82f6','#a855f7','#f59e0b','#06b6d4',
    '#f97316','#ec4899','#8b5cf6','#14b8a6','#eab308'
  ];
  var PROJECT_COLORS = ['#22c55e','#3b82f6','#a855f7','#f59e0b','#06b6d4','#f97316'];
  var AGENT_COLORS  = ['#a855f7','#3b82f6','#22c55e','#f59e0b','#f97316','#06b6d4'];

  /* ── State ─────────────────────────────────────────────── */
  var RANGES = {
    daily:   { groupBy:'day',   days:29 },
    weekly:  { groupBy:'week',  weeks:11 },
    monthly: { groupBy:'month', months:11 },
    all:     { groupBy:'month', allTime:true }
  };
  var currentRange = 'monthly';
  var refreshSeconds = 30;
  var timer = null;
  var inFlight = false;
  var seq = 0;
  var lastSuccessAt = null;
  var lastSummary = null;
  var lastTimeRows = null;
  var charts = {};

  /* ── Helpers ───────────────────────────────────────────── */
  function pad2(n) { return n < 10 ? '0' + n : String(n); }
  function timeStr(d) { return pad2(d.getHours())+':'+pad2(d.getMinutes())+':'+pad2(d.getSeconds()); }
  function formatTokens(n) {
    n = Math.max(0, Math.round(n || 0));
    if (n >= 1e9) return (n/1e9).toFixed(1).replace(/\.0$/,'') + 'B';
    if (n >= 1e6) return (n/1e6).toFixed(1).replace(/\.0$/,'') + 'M';
    if (n >= 1e4) return (n/1e3).toFixed(1).replace(/\.0$/,'') + 'K';
    return n.toLocaleString('en-US');
  }
  function formatCost(x) {
    if (x === 0) return '$0.00';
    if (x < 0.01) return '<$0.01';
    return '$' + x.toFixed(2);
  }
  function fmtPct(x) { return x.toFixed(1) + '%'; }
  function totalTokens(t) {
    return TOKEN_KEYS.reduce(function(s,k){ return s + (t[k]||0); }, 0);
  }
  function rangeBounds(range) {
    var now = new Date(), from;
    if (range.allTime) { from = 0; }
    else {
      var d = new Date(now);
      if (range.days) d.setDate(d.getDate()-range.days);
      else if (range.weeks) d.setDate(d.getDate()-range.weeks*7);
      else if (range.months) { d.setDate(1); d.setMonth(d.getMonth()-range.months); }
      from = d.getTime();
    }
    return { from:from, to:now.getTime() };
  }
  function fetchJSON(url) {
    return fetch(url,{headers:{Accept:'application/json'}}).then(function(r){
      if (!r.ok) { var e=new Error('HTTP '+r.status+' '+url); e.status=r.status; return r.json().catch(function(){return{}}).then(function(b){e.body=b;throw e}); }
      return r.json();
    });
  }
  function sorted(rows) { return (rows||[]).slice().sort(function(a,b){ return a.key<b.key?-1:a.key>b.key?1:0; }); }
  function byTokens(rows) { return (rows||[]).slice().sort(function(a,b){ return totalTokens(b.tokens)-totalTokens(a.tokens); }); }
  function byCost(rows) { return (rows||[]).slice().sort(function(a,b){ return (b.cost||0)-(a.cost||0); }); }

  /* ── Sync status ───────────────────────────────────────── */
  function setLive() { syncDot.className='sync-dot live'; syncText.textContent='Live · '+timeStr(lastSuccessAt); }
  function setOffline() { syncDot.className='sync-dot off'; syncText.textContent=lastSuccessAt?'Offline · '+timeStr(lastSuccessAt):'Offline'; }
  function showError(m) { errorMsg.textContent=m; errorBanner.classList.add('show'); }
  function hideError() { errorBanner.classList.remove('show'); }

  /* ── Chart.js defaults ─────────────────────────────────── */
  function applyDefaults() {
    var t3=cssVar('--text-3')||'#63636e';
    var brd=cssVar('--border')||'rgba(255,255,255,0.06)';
    Chart.defaults.font.family="'Rubik',system-ui,sans-serif";
    Chart.defaults.font.size=11;
    Chart.defaults.color=t3;
    Chart.defaults.plugins.legend.display=false;
    Chart.defaults.plugins.tooltip.backgroundColor=cssVar('--surface-2')||'#1e1e23';
    Chart.defaults.plugins.tooltip.titleColor=cssVar('--text')||'#f0f0f2';
    Chart.defaults.plugins.tooltip.bodyColor=cssVar('--text-2')||'#a0a0ab';
    Chart.defaults.plugins.tooltip.borderColor=cssVar('--border-strong')||'rgba(255,255,255,0.12)';
    Chart.defaults.plugins.tooltip.borderWidth=1;
    Chart.defaults.plugins.tooltip.padding=10;
    Chart.defaults.plugins.tooltip.cornerRadius=8;
    Chart.defaults.plugins.tooltip.boxPadding=4;
    Object.assign(Chart.defaults.scale.grid,{color:brd,drawBorder:false});
    Object.assign(Chart.defaults.scale.ticks,{color:t3,font:{size:10}});
  }

  function destroyAll() { Object.keys(charts).forEach(function(k){ if(charts[k]){charts[k].destroy();charts[k]=null;} }); }

  function showEmpty(id,v) { $(id).style.display=v?'none':'flex'; }

  /* ══════════════════════════════════════════════════════════
     SECTION 1 — STAT CARDS
     ══════════════════════════════════════════════════════════ */
  function renderStats(s) {
    if (!s) return;
    var t=s.totals, b=s.budget, tt=totalTokens(t.tokens);
    $('statTokens').textContent=formatTokens(tt);
    $('statTokensSub').textContent='input '+formatTokens(t.tokens.input)+' · output '+formatTokens(t.tokens.output)+' · reasoning '+formatTokens(t.tokens.reasoning);
    $('statCost').textContent=formatCost(t.cost);
    $('statCostSub').textContent=t.cost===0&&tt>0?'All free models':(t.sessions>0?formatCost(t.cost/t.sessions)+' avg/session':'');
    $('statSessions').textContent=t.sessions.toLocaleString('en-US');
    $('statSessionsSub').textContent=t.unpriced_sessions>0?t.unpriced_sessions+' unpriced':'avg '+formatCost(t.avg_cost);
    if (b.monthly>0) {
      var pct=Math.min(b.percent,100);
      $('statBudget').textContent=formatCost(b.spent)+' / '+formatCost(b.monthly);
      $('budgetFill').style.width=pct+'%';
      $('statBudgetSub').textContent=formatCost(b.remaining)+' left · projected '+formatCost(b.projected);
      statBudgetCard.className='stat-card stat-card--budget'+(b.alert==='warn'?' warn':b.alert==='exceeded'?' exceeded':'');
    } else {
      $('statBudget').textContent='No budget';
      $('budgetFill').style.width='0%';
      $('statBudgetSub').textContent='Set budget.monthly in config';
      statBudgetCard.className='stat-card stat-card--budget';
    }
  }
  var statBudgetCard = null; // resolved at init

  /* ══════════════════════════════════════════════════════════
     SECTION 2 — TOKEN USAGE OVER TIME (stacked bar)
     ══════════════════════════════════════════════════════════ */
  function renderTimeSeries(rows) {
    var canvas=$('chartTimeSeries');
    if(!rows||!rows.length){showEmpty('emptyTimeSeries',false);if(charts.timeSeries){charts.timeSeries.destroy();charts.timeSeries=null;}return;}
    showEmpty('emptyTimeSeries',true);
    var labels=rows.map(function(r){return r.label;});
    var datasets=TOKEN_KEYS.map(function(k){
      return{label:TOKEN_LABELS[k],data:rows.map(function(r){return r.tokens[k]||0;}),
        backgroundColor:TOKEN_BG[k],borderColor:TOKEN_COLORS[k],borderWidth:1,borderRadius:2,borderSkipped:false};
    });
    if(charts.timeSeries)charts.timeSeries.destroy();
    charts.timeSeries=new Chart(canvas,{
      type:'bar',data:{labels:labels,datasets:datasets},
      options:{responsive:true,maintainAspectRatio:false,interaction:{mode:'index',intersect:false},
        scales:{x:{stacked:true,grid:{display:false},ticks:{maxRotation:0,autoSkipPadding:20}},
          y:{stacked:true,beginAtZero:true,ticks:{callback:function(v){return formatTokens(v);}}}},
        plugins:{tooltip:{callbacks:{
          label:function(c){return c.dataset.label+': '+formatTokens(c.raw);},
          footer:function(items){return 'Total: '+formatTokens(items.reduce(function(s,i){return s+i.raw;},0));}
        }}}}
    });
    $('legendTimeSeries').innerHTML=datasets.map(function(d){
      return '<span class="legend-item"><span class="legend-dot" style="background:'+d.borderColor+'"></span>'+d.label+'</span>';
    }).join('');
  }

  /* ══════════════════════════════════════════════════════════
     SECTION 3 — COST OVER TIME (line)
     ══════════════════════════════════════════════════════════ */
  function renderCostTime(rows) {
    var canvas=$('chartCostTime');
    if(!rows||!rows.length||rows.every(function(r){return(r.cost||0)<=0;})){showEmpty('emptyCostTime',false);if(charts.costTime){charts.costTime.destroy();charts.costTime=null;}return;}
    showEmpty('emptyCostTime',true);
    var labels=rows.map(function(r){return r.label;});
    var data=rows.map(function(r){return r.cost||0;});
    if(charts.costTime)charts.costTime.destroy();
    charts.costTime=new Chart(canvas,{
      type:'line',data:{labels:labels,datasets:[{
        label:'Cost',data:data,
        borderColor:cssVar('--accent')||'#22c55e',
        backgroundColor:(cssVar('--accent-dim')||'rgba(34,197,94,0.1)'),
        fill:true,tension:0.3,pointRadius:3,pointHoverRadius:5,borderWidth:2
      }]},
      options:{responsive:true,maintainAspectRatio:false,
        scales:{x:{grid:{display:false},ticks:{maxRotation:0,autoSkipPadding:20}},
          y:{beginAtZero:true,ticks:{callback:function(v){return formatCost(v);}}}},
        plugins:{tooltip:{callbacks:{label:function(c){return formatCost(c.raw);}}}}}
    });
  }

  /* ══════════════════════════════════════════════════════════
     SECTION 4 — TOKEN COMPOSITION (doughnut)
     ══════════════════════════════════════════════════════════ */
  function renderComposition(s) {
    var canvas=$('chartComposition');
    if(!s){showEmpty('emptyComposition',false);if(charts.comp){charts.comp.destroy();charts.comp=null;}return;}
    var t=s.totals.tokens, tt=totalTokens(t);
    if(tt<=0){showEmpty('emptyComposition',false);if(charts.comp){charts.comp.destroy();charts.comp=null;}return;}
    showEmpty('emptyComposition',true);
    var values=TOKEN_KEYS.map(function(k){return t[k]||0;});
    var colors=TOKEN_KEYS.map(function(k){return TOKEN_COLORS[k];});
    var labels=TOKEN_KEYS.map(function(k){return TOKEN_LABELS[k];});
    if(charts.comp)charts.comp.destroy();
    charts.comp=new Chart(canvas,{
      type:'doughnut',data:{labels:labels,datasets:[{
        data:values,backgroundColor:colors,
        borderColor:cssVar('--surface')||'#141416',borderWidth:3,hoverOffset:6
      }]},
      options:{responsive:true,maintainAspectRatio:false,cutout:'58%',
        plugins:{legend:{display:true,position:'bottom',
          labels:{boxWidth:10,padding:12,font:{size:11},color:cssVar('--text-2')||'#a0a0ab'}},
          tooltip:{callbacks:{label:function(c){
            var pct=(c.raw/tt*100).toFixed(1);
            return c.label+': '+formatTokens(c.raw)+' ('+pct+'%)';
          }}}}}
    });
  }

  /* ══════════════════════════════════════════════════════════
     SECTION 5 — CACHE EFFICIENCY
     ══════════════════════════════════════════════════════════ */
  function renderEfficiency(s) {
    if(!s){showEmpty('emptyEfficiency',false);return;}
    var t=s.totals.tokens, tt=totalTokens(t);
    if(tt<=0){showEmpty('emptyEfficiency',false);return;}
    showEmpty('emptyEfficiency',true);
    var cacheHit=t.cache_read/(t.input+t.cache_read)*100||0;
    var outRatio=t.output/(t.input+t.output)*100||0;
    var reasonPct=t.reasoning/tt*100||0;
    var cacheWritePct=t.cache_write/tt*100||0;
    $('effCacheHit').textContent=fmtPct(cacheHit);
    $('effCacheFill').style.width=Math.min(cacheHit,100)+'%';
    $('effOutputRatio').textContent=fmtPct(outRatio);
    $('effOutputFill').style.width=Math.min(outRatio,100)+'%';
    $('effReasoning').textContent=fmtPct(reasonPct);
    $('effReasoningFill').style.width=Math.min(reasonPct,100)+'%';
    $('effCacheWrite').textContent=fmtPct(cacheWritePct);
    $('effCacheWriteFill').style.width=Math.min(cacheWritePct,100)+'%';
  }

  /* ══════════════════════════════════════════════════════════
     GENERIC HORIZONTAL BAR CHART
     ══════════════════════════════════════════════════════════ */
  function renderHBar(canvasId,emptyId,rows,valueKey,tipFn,colors) {
    var canvas=$(canvasId);
    var filtered=(rows||[]).filter(function(r){return(r[valueKey]||0)>0;});
    if(!filtered.length){showEmpty(emptyId,false);if(charts[canvasId]){charts[canvasId].destroy();charts[canvasId]=null;}return;}
    showEmpty(emptyId,true);
    var top=byCost(filtered).slice(0,10);
    var isMobile=window.innerWidth<600;
    var maxLabelLen=isMobile?20:35;
    var labels=top.map(function(r){var lbl=r.label||r.key;return lbl.length>maxLabelLen?lbl.substring(0,maxLabelLen)+'…':lbl;});
    var values=top.map(function(r){return r[valueKey]||0;});
    var cls=top.map(function(_,i){return colors[i%colors.length];});
    if(charts[canvasId])charts[canvasId].destroy();
    charts[canvasId]=new Chart(canvas,{
      type:'bar',data:{labels:labels,datasets:[{
        data:values,
        backgroundColor:cls.map(function(c){return c+'bb';}),
        borderColor:cls,borderWidth:1,borderRadius:4,borderSkipped:false
      }]},
      options:{indexAxis:'y',responsive:true,maintainAspectRatio:false,
        layout:{padding:{left:4}},
        scales:{x:{beginAtZero:true,ticks:{callback:tipFn.tick||function(v){return v;}}},
          y:{grid:{display:false},ticks:{font:{size:11,weight:'500'},autoSkipPadding:12}}},
        plugins:{tooltip:{callbacks:{label:function(c){return tipFn.tip(c.raw,top[c.dataIndex]);}}}}}
    });
  }

  function renderCostModel(rows) {
    renderHBar('chartCostModel','emptyCostModel',byCost(rows),'cost',
      {tick:function(v){return formatCost(v);},tip:function(v,r){return(r.label||r.key)+': '+formatCost(v);}},
      MODEL_COLORS);
  }
  function renderTokensModel(rows) {
    var enriched=byTokens(rows).map(function(r){r._tt=totalTokens(r.tokens);return r;});
    renderHBar('chartTokensModel','emptyTokensModel',enriched,'_tt',
      {tick:function(v){return formatTokens(v);},tip:function(v,r){return(r.label||r.key)+': '+formatTokens(v);}},
      MODEL_COLORS);
  }
  function renderProject(rows) {
    var enriched=byTokens(rows).map(function(r){r._tt=totalTokens(r.tokens);return r;});
    renderHBar('chartProject','emptyProject',enriched,'_tt',
      {tick:function(v){return formatTokens(v);},tip:function(v,r){return(r.label||r.key)+': '+formatTokens(r._tt)+' tokens';}},
      PROJECT_COLORS);
  }
  function renderAgent(rows) {
    var enriched=byTokens(rows).map(function(r){r._tt=totalTokens(r.tokens);return r;});
    renderHBar('chartAgent','emptyAgent',enriched,'_tt',
      {tick:function(v){return formatTokens(v);},tip:function(v,r){return(r.label||r.key)+': '+formatTokens(r._tt)+' tokens';}},
      AGENT_COLORS);
  }

  /* ══════════════════════════════════════════════════════════
     SECTION 6 — SESSION ACTIVITY (bar chart)
     ══════════════════════════════════════════════════════════ */
  function renderActivity(rows) {
    var canvas=$('chartActivity');
    if(!rows||!rows.length){showEmpty('emptyActivity',false);if(charts.activity){charts.activity.destroy();charts.activity=null;}return;}
    showEmpty('emptyActivity',true);
    var labels=rows.map(function(r){return r.label;});
    var counts=rows.map(function(r){return r.sessions||0;});
    if(charts.activity)charts.activity.destroy();
    charts.activity=new Chart(canvas,{
      type:'bar',data:{labels:labels,datasets:[{
        label:'Sessions',data:counts,
        backgroundColor:(cssVar('--blue-dim')||'rgba(59,130,246,0.2)'),
        borderColor:cssVar('--blue')||'#3b82f6',
        borderWidth:1,borderRadius:3,borderSkipped:false
      }]},
      options:{responsive:true,maintainAspectRatio:false,
        scales:{x:{grid:{display:false},ticks:{maxRotation:0,autoSkipPadding:20}},
          y:{beginAtZero:true,ticks:{stepSize:1}}},
        plugins:{tooltip:{callbacks:{label:function(c){return c.raw+' sessions';}}}}}
    });
  }

  /* ══════════════════════════════════════════════════════════
     DATA TABLES — MODEL, PROJECT, AGENT
     ══════════════════════════════════════════════════════════ */
  function renderBreakdownTable(tbodyId,emptyId,countId,rows,valueKey) {
    var tbody=$(tbodyId);
    var filtered=byCost(rows||[]).filter(function(r){return totalTokens(r.tokens)>0||(valueKey==='cost'&&(r.cost||0)>0);});
    if(!filtered.length){showEmpty(emptyId,false);tbody.innerHTML='';$(countId).textContent='';return;}
    showEmpty(emptyId,true);
    var grand=filtered.reduce(function(s,r){return s+(valueKey==='cost'?(r.cost||0):totalTokens(r.tokens));},0);
    var grandTokens=filtered.reduce(function(s,r){return s+totalTokens(r.tokens);},0);
    var useTokenPct=valueKey==='cost'&&grand<=0;
    $(countId).textContent=filtered.length+' models';
    if(tbodyId==='tbodyProjects')$(countId).textContent=filtered.length+' projects';
    if(tbodyId==='tbodyAgents')$(countId).textContent=filtered.length+' agents';
    var html='';
    filtered.forEach(function(r){
      var tt=totalTokens(r.tokens);
      var pct=useTokenPct?(grandTokens>0?tt/grandTokens*100:0):(grand>0?(valueKey==='cost'?(r.cost||0)/grand*100:tt/grand*100):0);
      var isFree=(r.key||'').indexOf('-free')>-1;
      html+='<tr>'
        +'<td class="model-name" title="'+esc(r.label||r.key)+'">'+esc(r.label||r.key)+'</td>'
        +'<td class="num">'+r.sessions+'</td>'
        +'<td class="num">'+formatTokens(r.tokens.input)+'</td>'
        +'<td class="num">'+formatTokens(r.tokens.output)+'</td>'
        +'<td class="num">'+formatTokens(r.tokens.reasoning)+'</td>'
        +'<td class="num">'+formatTokens(r.tokens.cache_read)+'</td>'
        +'<td class="num">'+formatTokens(r.tokens.cache_write)+'</td>'
        +'<td class="num" style="color:var(--text);font-weight:600">'+formatTokens(tt)+'</td>'
        +'<td class="num cost">'+formatCost(r.cost||0)+'</td>'
        +'<td class="pct-bar-cell"><div style="display:flex;align-items:center;gap:6px"><div class="pct-bar" style="flex:1"><div class="pct-bar-fill" style="width:'+pct+'%"></div></div><span style="font-size:11px;color:var(--text-3);min-width:36px;text-align:right">'+fmtPct(pct)+'</span></div></td>'
        +'</tr>';
    });
    tbody.innerHTML=html;
  }

  /* ══════════════════════════════════════════════════════════
     RECENT SESSIONS TABLE
     ══════════════════════════════════════════════════════════ */
  function cleanTitle(title, createdDate) {
    if (!title) return '(untitled)';
    if (/^New session - \d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}/.test(title)) {
      return 'Session · ' + createdDate.toLocaleDateString('en-US',{month:'short',day:'numeric'}) + ' ' + createdDate.toLocaleTimeString('en-US',{hour:'2-digit',minute:'2-digit'});
    }
    return title;
  }

  function renderSessions() {
    var range=RANGES[currentRange];
    var bounds=rangeBounds(range);
    fetchJSON('/api/sessions?limit=20&sort=updated&from='+bounds.from+'&to='+bounds.to)
      .then(function(data){
        var items=data.items||[];
        var tbody=$('tbodySessions');
        if(!items.length){showEmpty('emptyTableSessions',false);tbody.innerHTML='';$('sessionCount').textContent='';return;}
        showEmpty('emptyTableSessions',true);
        $('sessionCount').textContent=data.total+' total';
        var html='';
        items.forEach(function(s){
          var tt=totalTokens(s.tokens);
          var isFree=(s.model||'').indexOf('-free')>-1;
          var created=new Date(s.created_at);
          var dateStr=created.toLocaleDateString('en-US',{month:'short',day:'numeric'})+' '+created.toLocaleTimeString('en-US',{hour:'2-digit',minute:'2-digit'});
          html+='<tr>'
            +'<td class="session-title" title="'+esc(s.title||'')+'">'+esc(cleanTitle(s.title, created))+'</td>'
            +'<td><span class="tag '+(isFree?'tag--free':'tag--paid')+'">'+esc(shortModel(s.model))+'</span></td>'
            +'<td style="font-size:12px;color:var(--text-3)">'+esc(s.agent||'—')+'</td>'
            +'<td class="num">'+formatTokens(s.tokens.input)+'</td>'
            +'<td class="num">'+formatTokens(s.tokens.output)+'</td>'
            +'<td class="num" style="color:var(--text);font-weight:600">'+formatTokens(tt)+'</td>'
            +'<td class="num cost">'+formatCost(s.cost)+'</td>'
            +'<td class="session-date">'+dateStr+'</td>'
            +'</tr>';
        });
        tbody.innerHTML=html;
      })
      .catch(function(){});
  }

  function shortModel(m) {
    if (!m) return '—';
    var parts = m.split('/');
    return parts[parts.length - 1];
  }
  function esc(s) {
    var d = document.createElement('div');
    d.textContent = s;
    return d.innerHTML;
  }

  /* ══════════════════════════════════════════════════════════
     MAIN FETCH + RENDER CYCLE
     ══════════════════════════════════════════════════════════ */
  function refresh() {
    if (inFlight) return;
    inFlight = true;
    var mySeq = ++seq;
    var range = RANGES[currentRange];
    var bounds = rangeBounds(range);
    var q = 'from=' + bounds.from + '&to=' + bounds.to;

    fetchJSON('/api/config')
      .then(function(cfg) {
        var secs = Number(cfg.refresh_seconds);
        if (secs > 0 && secs !== refreshSeconds) { refreshSeconds = secs; startPolling(); }
        return fetchJSON('/api/summary?' + q);
      })
      .then(function(summary) {
        if (mySeq !== seq) return;
        lastSummary = summary;
        renderStats(summary);
        /* Hide cost-only sections when all models are free */
        var costSections=document.querySelectorAll('[data-cost-section]');
        var hasCost=summary.totals.cost>0;
        costSections.forEach(function(el){el.style.display=hasCost?'':'none';});
        renderComposition(summary);
        renderEfficiency(summary);
        renderCostModel(summary.by_model);
        renderTokensModel(summary.by_model);
        renderProject(summary.by_project);
        renderAgent(summary.by_agent);
        renderBreakdownTable('tbodyModels','emptyTableModels','modelCount',summary.by_model,'cost');
        renderBreakdownTable('tbodyProjects','emptyTableProjects','projectCount',summary.by_project,'cost');
        renderBreakdownTable('tbodyAgents','emptyTableAgents','agentCount',summary.by_agent,'cost');
        renderSessions();
        return fetchJSON('/api/breakdown?group_by=' + range.groupBy + '&' + q);
      })
      .then(function(data) {
        if (mySeq !== seq) return;
        lastTimeRows = sorted(data.rows);
        renderTimeSeries(lastTimeRows);
        renderCostTime(lastTimeRows);
        renderActivity(lastTimeRows);
        lastSuccessAt = new Date();
        setLive();
        hideError();
      })
      .catch(function(err) {
        if (mySeq !== seq) return;
        setOffline();
        showError(err.status === 503 ? 'Database unavailable' : 'Server unreachable — retrying…');
      })
      .then(function() {
        if (mySeq !== seq) return;
        inFlight = false;
        if (themeChangePending) { themeChangePending = false; destroyAll(); refresh(); }
      });
  }

  function startPolling() {
    if (timer) clearInterval(timer);
    timer = setInterval(refresh, refreshSeconds * 1000);
  }

  /* ══════════════════════════════════════════════════════════
     THEME CHANGE → re-render everything
     ══════════════════════════════════════════════════════════ */
  var themeChangePending = false;
  function onThemeChange() {
    applyDefaults();
    /* If a refresh is in flight, defer the re-render to avoid
       destroying charts that the in-flight refresh is about to create. */
    if (inFlight) { themeChangePending = true; return; }
    destroyAll();
    refresh();
  }

  /* ══════════════════════════════════════════════════════════
     INIT
     ══════════════════════════════════════════════════════════ */
  applyDefaults();
  statBudgetCard = $('statBudget').closest('.stat-card');

  var activeTab = rangeTabs.querySelector('.range-tab[aria-pressed="true"]');
  if (activeTab) currentRange = activeTab.dataset.range;

  rangeTabs.addEventListener('click', function(e) {
    var btn = e.target.closest('.range-tab');
    if (!btn || btn.dataset.range === currentRange) return;
    currentRange = btn.dataset.range;
    rangeTabs.querySelectorAll('.range-tab').forEach(function(b) {
      b.setAttribute('aria-pressed', String(b === btn));
    });
    refresh();
  });

  if (window.MutationObserver) {
    new MutationObserver(onThemeChange).observe(document.documentElement, {
      attributes: true, attributeFilter: ['data-theme']
    });
  }

  refresh();
  startPolling();
})();
