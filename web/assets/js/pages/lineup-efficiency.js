/* Lineup Efficiency: points left on the bench against the best lineup each roster could have set
   (missed wins, career leaderboard, weekly calendar, league trend, bench depth, depth-adjusted
   efficiency, biggest blunders).

   Reads config.json and data/v1/lineup-efficiency.json (schema "lineup-efficiency");
   lineup-efficiency-data.js turns the model into the shapes the page's script reads, as the Stage A
   build wrote them inline. The script itself is the Stage A page's, run inside runPage() once the
   data is in (decision 7.14: same look first; its inline handlers stay on window until the design
   pass). What was written into the page now comes from the league:
     seasons          the model's seasons, the live one labelled "(live)"; colors from theme.season_colors
     managers         names and colors from config.json
     calendar labels  each season's regular-season weeks and playoff rounds (config.json seasons[]);
                      playoff columns read by role counted back from the final (Champ, Semi, Quarter, Rd1)
     notes            slot rules (the model's lineup slots), playoff games per manager, flagged weeks,
                      the two correlations, and which seasons had the extra first round, from the data;
                      the story behind those first rounds from the league's editorial (notes.first_round) */

import { config, load } from '../core/data.js';
import { managers } from '../core/managers.js';
import { drawNav, drawFooter, drawSubnav } from '../core/nav.js';
import { esc } from '../core/site.js';
import { chapterRail } from '../components/chapter-rail.js';
import { lineupData } from './lineup-efficiency-data.js';
import { methodNotes, andList, seasonRanges } from './transaction-notes.js';

var Chart = window.Chart;
var cfg, mgr;
// the page's data (lineup-efficiency-data.js) and config
var PAGE_SEASONS, PAGE_LIVE_SEASON, SEASON_COLORS, MANAGER_COLORS, EFFICIENCY_BY_FILTER, EFFICIENCY_GLOBAL_MIN,
  EFFICIENCY_GLOBAL_MAX, MISSED_WINS_BY_FILTER, BLUNDERS_BY_FILTER, ROSTERS_BY_FILTER, DEPTH_BY_FILTER,
  DEPTH_ADJUSTED_BY_FILTER, SEASON_TREND_DATA, DEPTH_VS_WINS_DATA, HEATMAP_MANAGERS, HEATMAP_DATA, HEATMAP_SEASONS,
  CAREER_AVG_DATA, HEATMAP_GAP_MIN, HEATMAP_GAP_MAX;
// the calendar's columns: the longest regular season, the most playoff rounds, the latest final week
var MAX_REG, MAX_ROUNDS, MAX_WEEK;

/* "2026 (live)" for the live season, else the year (shared.js on the Stage A site) */
function seasonLabel(s) {
  return PAGE_LIVE_SEASON !== null && String(s) === String(PAGE_LIVE_SEASON) ? s + ' (live)' : String(s);
}

function seasonInfo(s) {
  return (cfg.seasons || []).find(function (x) { return x.season === Number(s); }) || {};
}
function roundsOf(s) { var i = seasonInfo(s); return Math.max(0, (i.final_week || 0) - (i.regular_season_weeks || 0)); }

/* a playoff round by its distance from the final (1 = the final) */
function roleShort(distance, totalRounds) {
  var ROLE_SHORT = {1:'Champ', 2:'Semi', 3:'Quarter'};
  return ROLE_SHORT[distance] || ('Rd' + (totalRounds - distance + 1));
}

function pearson(xs, ys) {
  var n = xs.length;
  if (n < 2) return null;
  var mx = xs.reduce(function (a, b) { return a + b; }, 0) / n, my = ys.reduce(function (a, b) { return a + b; }, 0) / n;
  var sxy = 0, sxx = 0, syy = 0;
  for (var i = 0; i < n; i++) { sxy += (xs[i] - mx) * (ys[i] - my); sxx += (xs[i] - mx) * (xs[i] - mx); syy += (ys[i] - my) * (ys[i] - my); }
  return sxx && syy ? sxy / Math.sqrt(sxx * syy) : null;
}

/* "1 QB, 2 RB, 2 WR, 1 TE, 1 FLEX, 1 D/ST, 1 K" from a season's lineup slots */
var SLOT_ORDER = ['QB', 'RB', 'WR', 'TE', 'RB/WR/TE', 'D/ST', 'K'];
var SLOT_NAME = { 'RB/WR/TE': 'FLEX' };
function slotText(slots) {
  var n = {};
  slots.forEach(function (s) { n[s] = (n[s] || 0) + 1; });
  var order = SLOT_ORDER.filter(function (s) { return n[s]; })
    .concat(Object.keys(n).filter(function (s) { return SLOT_ORDER.indexOf(s) === -1; }).sort());
  return order.map(function (s) { return n[s] + ' ' + (SLOT_NAME[s] || s); }).join(', ');
}

/* the notes written from the data (see the header) */
function dataNotes(M) {
  // slot rules: one line, or per group of seasons when they changed
  var groups = [];
  Object.keys(M.slots || {}).sort().forEach(function (s) {
    var t = slotText(M.slots[s]), g = groups.find(function (x) { return x.text === t; });
    if (g) g.seasons.push(Number(s)); else groups.push({ text: t, seasons: [Number(s)] });
  });
  document.getElementById('slot-rules').textContent = groups.length === 1 ? groups[0].text
    : groups.map(function (g) { return g.text + ' in ' + seasonRanges(g.seasons); }).join('; ');

  var games = M.games.filter(function (g) { return !g.hidden; });
  var po = {};
  HEATMAP_MANAGERS.forEach(function (m) { po[m] = 0; });
  games.forEach(function (g) { if (g.playoff) po[mgr.name(g.manager_key)] = (po[mgr.name(g.manager_key)] || 0) + 1; });
  var pc = Object.keys(po).map(function (k) { return po[k]; });
  var lo = Math.min.apply(null, pc), hi = Math.max.apply(null, pc);
  document.getElementById('playoff-games').textContent = lo === hi ? lo + (lo === 1 ? ' game' : ' games') : lo + '-' + hi + ' games';

  var forfeits = games.filter(function (g) { return g.forfeited; }).length;
  var neglected = games.filter(function (g) { return g.neglected && !g.forfeited; }).length;
  var flagged = document.getElementById('flagged-note');
  if (forfeits + neglected) {
    var parts = [];
    if (forfeits) parts.push(forfeits + ' forfeit');
    if (neglected) parts.push(neglected + ' partial lineup neglect');
    flagged.textContent = 'Excludes ' + (forfeits + neglected) + ((forfeits + neglected) === 1 ? ' flagged week' : ' flagged weeks') + ' (' + parts.join(', ') + '). See methodology above.';
  } else flagged.remove();

  var r = pearson(DEPTH_VS_WINS_DATA.map(function (d) { return d.d; }), DEPTH_VS_WINS_DATA.map(function (d) { return d.wr; }));
  var a = r === null ? 0 : Math.abs(r);
  document.getElementById('depth-wins-note').innerHTML = r === null ? '' :
    'Correlation is ' + (a < 0.4 ? 'weak' : a < 0.7 ? 'moderate' : 'strong') + ' (r&asymp;' + r.toFixed(2) + ').'
    + (a < 0.4 ? ' Depth does not reliably predict win rate.' : '');

  var career = DEPTH_ADJUSTED_BY_FILTER.career || [];
  var rc = pearson(career.map(function (d) { return d.depth; }), career.map(function (d) { return d.raw; }));
  document.getElementById('depth-gap-r').textContent = rc === null ? '' : String(Math.round(rc * 100));

  // the calendar's extra first round: which seasons ran the most playoff rounds
  var note = document.getElementById('first-round-note');
  var most = HEATMAP_SEASONS.filter(function (s) { return roundsOf(s) === MAX_ROUNDS; });
  var others = HEATMAP_SEASONS.filter(function (s) { return roundsOf(s) !== MAX_ROUNDS; });
  if (!others.length || !MAX_ROUNDS) { note.remove(); return; }
  var label = roleShort(MAX_ROUNDS, MAX_ROUNDS);
  var list = function (ss) { return ss.length <= 2 ? andList(ss.map(String)) : seasonRanges(ss); };
  var fewer = Array.from(new Set(others.map(roundsOf)));
  var html = '<strong>' + esc(label) + ' only appears in ' + list(most) + '.</strong>';
  if (M.notes && M.notes.first_round) html += ' ' + esc(M.notes.first_round);
  html += ' ' + list(others) + ' only ran ' + (fewer.length === 1 ? fewer[0] : 'fewer') + ' playoff rounds, so '
    + esc(label) + ' is blank for those seasons.';
  note.innerHTML = html;
}

function runPage() {
  var SLOT_LABEL = { 'RB/WR/TE': 'FLEX', 'BE': 'BENCH', 'IR': 'IR' };
  function slotLabel(slot) { return SLOT_LABEL[slot] || slot; }

  function posBadgeClass(pos) { return 'pos-' + pos.replace('/', '').toLowerCase(); }
  function rosterRowHtml(p, isBenchTop) {
    return '<div class="roster-row' + (isBenchTop ? ' bench-top' : '') + '">'
      + '<div class="roster-row-left">'
      +   '<span class="roster-row-slot">' + slotLabel(p.slot) + '</span>'
      +   '<span class="roster-row-player">' + p.player + '</span>'
      +   '<span class="pos-badge ' + posBadgeClass(p.position) + '">' + p.position + '</span>'
      + '</div>'
      + '<span class="roster-row-points">' + p.points.toFixed(1) + '</span>'
      + '</div>';
  }

  function openRosterModal(i) {
    var d = BLUNDERS_BY_FILTER[blundersFilter][i];
    var roster = ROSTERS_BY_FILTER[blundersFilter][i];
    if (!roster) return;

    var SLOT_ORDER = ['QB','RB','WR','TE','RB/WR/TE','D/ST','K'];
    var starters = roster.starters.slice().sort(function(a,b){
      return SLOT_ORDER.indexOf(a.slot) - SLOT_ORDER.indexOf(b.slot);
    });
    var bench = roster.bench.slice().sort(function(a,b){ return b.points - a.points; });
    var benchTopPoints = bench.length ? bench[0].points : null;

    var seasonColor = SEASON_COLORS[d.season] || 'var(--muted)';
    var html = ''
      + '<div class="roster-modal-header">'
      +   '<div class="roster-modal-title">' + d.manager + '</div>'
      +   '<div class="roster-modal-meta">'
      +     '<span class="season-pill" style="background:' + seasonColor + ';">' + d.season + '</span> &nbsp;Week ' + d.week
      +   '</div>'
      +   '<div class="roster-modal-stats">'
      +     '<div><div class="roster-modal-stat-label">Actual</div><div class="roster-modal-stat-val">' + d.actual.toFixed(1) + '</div></div>'
      +     '<div><div class="roster-modal-stat-label">Optimal</div><div class="roster-modal-stat-val">' + d.optimal.toFixed(1) + '</div></div>'
      +     '<div><div class="roster-modal-stat-label">Gap</div><div class="roster-modal-stat-val" style="color:#c0623a;">+' + d.gap.toFixed(1) + '</div></div>'
      +   '</div>'
      + '</div>'
      + '<div class="roster-modal-section-label">Starting Lineup</div>'
      + starters.map(function(p){ return rosterRowHtml(p, false); }).join('')
      + '<div class="roster-modal-section-label">Bench</div>'
      + (bench.length
          ? bench.map(function(p){ return rosterRowHtml(p, p.points === benchTopPoints); }).join('')
          : '<p style="font-size:0.8rem;color:var(--muted);">No bench players recorded for this week.</p>');

    document.getElementById('roster-modal-body').innerHTML = html;
    document.getElementById('roster-modal').classList.add('active');
    document.body.style.overflow = 'hidden';
  }

  function closeRosterModal() {
    document.getElementById('roster-modal').classList.remove('active');
    document.body.style.overflow = '';
  }

  document.addEventListener('keydown', function(e) {
    if (e.key === 'Escape') closeRosterModal();
  });

  /* ── Shared red/gold/green gradient helper ── */
  var GOOD = [90,138,90];   // green = good
  var MID  = [212,175,55];  // gold = mid
  var BAD  = [168,90,90];   // red = bad
  function lerp(a,b,t){ return Math.round(a+(b-a)*t); }
  function gradientColor(value, min, max, invert) {
    var p = max===min ? 0.5 : (value - min) / (max - min);
    if (invert) p = 1 - p;
    var c0 = p<=0.5 ? GOOD : MID;
    var c1 = p<=0.5 ? MID : BAD;
    var t = p<=0.5 ? p/0.5 : (p-0.5)/0.5;
    var r = lerp(c0[0],c1[0],t), g = lerp(c0[1],c1[1],t), b = lerp(c0[2],c1[2],t);
    return 'rgba('+r+','+g+','+b+',0.85)';
  }

  /* ── Generic column sort helper ── */
  function sortRows(rows, key, type, dir) {
    var sorted = rows.slice().sort(function(a,b){
      var av = a[key], bv = b[key];
      if (av === null || av === undefined) av = type === 'text' ? '' : -999;
      if (bv === null || bv === undefined) bv = type === 'text' ? '' : -999;
      if (type === 'text') { av = (av||'').toLowerCase(); bv = (bv||'').toLowerCase(); }
      if (av < bv) return dir === 'asc' ? -1 : 1;
      if (av > bv) return dir === 'asc' ? 1 : -1;
      return 0;
    });
    return sorted;
  }

  function wireSortableHeaders(tableId, renderFn, state) {
    document.querySelectorAll('#'+tableId+' th.sortable').forEach(function(th){
      th.addEventListener('click', function(){
        var key = th.getAttribute('data-key');
        var type = th.getAttribute('data-type') || 'number';
        if (state.key === key) {
          state.dir = state.dir === 'asc' ? 'desc' : 'asc';
        } else {
          state.key = key;
          state.type = type;
          state.dir = 'desc';
        }
        document.querySelectorAll('#'+tableId+' th.sortable').forEach(function(h){
          h.classList.remove('sorted-asc','sorted-desc');
        });
        th.classList.add(state.dir === 'asc' ? 'sorted-asc' : 'sorted-desc');
        renderFn();
      });
    });
  }

  /* ── Career/season-filterable efficiency gap bar chart ── */
  var efficiencyChart = null;

  function renderEfficiencyPills() {
    var el = document.getElementById('efficiency-pills');
    var keys = ['career'].concat(PAGE_SEASONS.map(String));
    var html = '';
    keys.forEach(function(k) {
      var label = k === 'career' ? 'Career' : seasonLabel(k);
      var swatch = SEASON_COLORS[k] ? ' year-swatch-btn" style="--swatch-color:' + SEASON_COLORS[k] + ';' : '';
      html += '<button class="heatmap-season-pill'+(k==='career'?' active':'')+swatch+'" onclick="renderEfficiencyChart(\''+k+'\', this)">'+label+'</button>';
    });
    el.innerHTML = html;
  }

  function renderEfficiencyChart(filterKey, btn) {
    if (btn) {
      btn.parentElement.querySelectorAll('.heatmap-season-pill').forEach(function(p){ p.classList.remove('active'); });
      btn.classList.add('active');
    }
    var rows = EFFICIENCY_BY_FILTER[filterKey];
    var colors = rows.map(function(d){ return gradientColor(d.g, EFFICIENCY_GLOBAL_MIN, EFFICIENCY_GLOBAL_MAX); });

    if (efficiencyChart) { efficiencyChart.destroy(); }
    var ctx = document.getElementById('chart-efficiency-gap').getContext('2d');
    efficiencyChart = new Chart(ctx, {
      type: 'bar',
      data: {
        labels: rows.map(function(d){return d.m;}),
        datasets: [{
          data: rows.map(function(d){return d.g;}),
          backgroundColor: colors,
          borderRadius: 4,
          barPercentage: 0.7,
          categoryPercentage: 0.8,
        }]
      },
      options: {
        indexAxis: 'y',
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { display:false } },
        scales: {
          x: { min:0, max:25, title:{display:true,text:'Avg points left on bench per week'} },
          y: { ticks:{ autoSkip:false, font:{size:12}, color: function(ctx){ var mgr = rows[ctx.index] && rows[ctx.index].m; return MANAGER_COLORS[mgr] || '#1e1a14'; } } }
        }
      }
    });
  }

  renderEfficiencyPills();
  renderEfficiencyChart('career');

  /* ==== NEW: Depth, Trend, and Consistency data ==== */

  var DEPTH_ALL_VALUES = Object.keys(DEPTH_BY_FILTER).reduce(function(acc, key){
    return acc.concat(DEPTH_BY_FILTER[key].map(function(d){ return d.d; }));
  }, []);
  var DEPTH_GLOBAL_MIN = Math.min.apply(null, DEPTH_ALL_VALUES);
  var DEPTH_GLOBAL_MAX = Math.max.apply(null, DEPTH_ALL_VALUES);

  /* ---- Depth-Adjusted Efficiency (bar chart, career only) ---- */
  var depthAdjustedChart = null;
  var depthAdjustedFilter = 'career';
  function renderDepthAdjustedPills() {
    var el = document.getElementById('depth-adjusted-pills');
    if (!el) return;
    var keys = ['career'].concat(PAGE_SEASONS.map(String));
    var html = '';
    keys.forEach(function(k) {
      var label = k === 'career' ? 'Career' : seasonLabel(k);
      var swatch = SEASON_COLORS[k] ? ' year-swatch-btn" style="--swatch-color:' + SEASON_COLORS[k] + ';' : '';
      html += '<button class="heatmap-season-pill'+(k==='career'?' active':'')+swatch+'" onclick="setDepthAdjustedFilter(\''+k+'\', this)">'+label+'</button>';
    });
    el.innerHTML = html;
  }
  function setDepthAdjustedFilter(key, btn) {
    depthAdjustedFilter = key;
    if (btn) {
      btn.parentElement.querySelectorAll('.heatmap-season-pill').forEach(function(p){ p.classList.remove('active'); });
      btn.classList.add('active');
    }
    renderDepthAdjustedChart();
  }
  function renderDepthAdjustedChart() {
    var data = DEPTH_ADJUSTED_BY_FILTER[depthAdjustedFilter] || [];
    var rows = data.slice().sort(function(a,b){ return a.adj - b.adj; });
    var adjMin = Math.min.apply(null, rows.map(function(d){return d.adj;}));
    var adjMax = Math.max.apply(null, rows.map(function(d){return d.adj;}));
    var colors = rows.map(function(d){ return gradientColor(d.adj, adjMin, adjMax); });

    if (depthAdjustedChart) { depthAdjustedChart.destroy(); }
    var ctx = document.getElementById('chart-depth-adjusted').getContext('2d');
    depthAdjustedChart = new Chart(ctx, {
      type: 'bar',
      data: {
        labels: rows.map(function(d){return d.m;}),
        datasets: [{
          data: rows.map(function(d){return d.adj;}),
          backgroundColor: colors,
          borderRadius: 4,
          barPercentage: 0.7,
          categoryPercentage: 0.8,
        }]
      },
      options: {
        indexAxis: 'y',
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { display:false },
          tooltip: {
            callbacks: {
              label: function(ctx){
                var d = rows[ctx.dataIndex];
                return ['Raw efficiency gap: '+d.raw.toFixed(2), 'Bench depth score: '+d.depth.toFixed(2), 'Adjusted (this chart): '+(d.adj>=0?'+':'')+d.adj.toFixed(2)];
              }
            }
          }
        },
        scales: {
          x: { title:{display:true,text:'Adjusted gap (negative = better than depth predicts)'} },
          y: { ticks:{ autoSkip:false, font:{size:12}, color: function(ctx){ var mgr = rows[ctx.index] && rows[ctx.index].m; return MANAGER_COLORS[mgr] || '#1e1a14'; } } }
        }
      }
    });
  }
  renderDepthAdjustedPills();
  renderDepthAdjustedChart();

  /* ---- League Trend by Season (line chart) ---- */
  var seasonTrendChart = null;
  function renderSeasonTrendChart() {
    if (seasonTrendChart) { seasonTrendChart.destroy(); }
    var ctx = document.getElementById('chart-season-trend').getContext('2d');
    seasonTrendChart = new Chart(ctx, {
      type: 'line',
      data: {
        labels: SEASON_TREND_DATA.map(function(d){return d.s;}),
        datasets: [{
          data: SEASON_TREND_DATA.map(function(d){return d.g;}),
          borderColor: '#4a7fa8',
          backgroundColor: 'rgba(74,127,168,0.12)',
          borderWidth: 2.5,
          pointRadius: 4,
          pointBackgroundColor: '#4a7fa8',
          fill: true,
          tension: 0.25,
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { display:false } },
        scales: {
          y: { title:{display:true,text:'Avg points left on bench per week'} }
        }
      }
    });
  }
  renderSeasonTrendChart();

  /* ---- Bench Depth (bar chart, career + season toggle) ---- */
  var depthChart = null;
  function renderDepthPills() {
    var el = document.getElementById('depth-pills');
    var keys = ['career'].concat(PAGE_SEASONS.map(String));
    var html = '';
    keys.forEach(function(k) {
      var label = k === 'career' ? 'Career' : seasonLabel(k);
      var swatch = SEASON_COLORS[k] ? ' year-swatch-btn" style="--swatch-color:' + SEASON_COLORS[k] + ';' : '';
      html += '<button class="heatmap-season-pill'+(k==='career'?' active':'')+swatch+'" onclick="renderDepthChart(\''+k+'\', this)">'+label+'</button>';
    });
    el.innerHTML = html;
  }
  function renderDepthChart(filterKey, btn) {
    if (btn) {
      btn.parentElement.querySelectorAll('.heatmap-season-pill').forEach(function(p){ p.classList.remove('active'); });
      btn.classList.add('active');
    }
    var rows = DEPTH_BY_FILTER[filterKey].slice().sort(function(a,b){ return b.d - a.d; });
    var colors = rows.map(function(d){ return gradientColor(d.d, DEPTH_GLOBAL_MIN, DEPTH_GLOBAL_MAX, true); });

    if (depthChart) { depthChart.destroy(); }
    var ctx = document.getElementById('chart-depth').getContext('2d');
    depthChart = new Chart(ctx, {
      type: 'bar',
      data: {
        labels: rows.map(function(d){return d.m;}),
        datasets: [{
          data: rows.map(function(d){return d.d;}),
          backgroundColor: colors,
          borderRadius: 4,
          barPercentage: 0.7,
          categoryPercentage: 0.8,
        }]
      },
      options: {
        indexAxis: 'y',
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { display:false } },
        scales: {
          x: { title:{display:true,text:'Avg bench depth score (higher = deeper bench)'} },
          y: { ticks:{ autoSkip:false, font:{size:12}, color: function(ctx){ var mgr = rows[ctx.index] && rows[ctx.index].m; return MANAGER_COLORS[mgr] || '#1e1a14'; } } }
        }
      }
    });
  }
  renderDepthPills();
  renderDepthChart('career');

  /* ---- Depth vs. Wins (scatter) ---- */
  var depthWinsChart = null;
  function renderDepthWinsLegend() {
    var el = document.getElementById('depth-wins-legend');
    if (!el) return;
    var names = Object.keys(MANAGER_COLORS).sort();
    el.innerHTML = names.map(function(m){
      return '<span class="manager-color-legend-item"><span class="manager-color-legend-dot" style="background:'+MANAGER_COLORS[m]+';"></span>'+m+'</span>';
    }).join('');
  }
  renderDepthWinsLegend();

  // Shades the chart background green above 50% win rate and red below it,
  // with a dashed reference line at 50%. Runs on beforeDatasetsDraw so the
  // grid/axes render first, the bands render next, and the actual scatter
  // points render last on top -- points stay fully visible against the tint.
  var winRateBandsPlugin = {
    id: 'winRateBands',
    beforeDatasetsDraw: function(chart) {
      var yScale = chart.scales.y;
      var area = chart.chartArea;
      var ctx = chart.ctx;
      var y50 = Math.max(area.top, Math.min(area.bottom, yScale.getPixelForValue(50)));
      ctx.save();
      ctx.fillStyle = 'rgba(90,138,90,0.08)';
      ctx.fillRect(area.left, area.top, area.right - area.left, y50 - area.top);
      ctx.fillStyle = 'rgba(168,90,90,0.08)';
      ctx.fillRect(area.left, y50, area.right - area.left, area.bottom - y50);
      ctx.beginPath();
      ctx.setLineDash([5,4]);
      ctx.strokeStyle = 'rgba(30,26,20,0.35)';
      ctx.lineWidth = 1.5;
      ctx.moveTo(area.left, y50);
      ctx.lineTo(area.right, y50);
      ctx.stroke();
      ctx.restore();
    }
  };

  function renderDepthWinsChart() {
    if (depthWinsChart) { depthWinsChart.destroy(); }
    var ctx = document.getElementById('chart-depth-wins').getContext('2d');

    // Line of best fit across all manager-season points
    var xs = DEPTH_VS_WINS_DATA.map(function(d){return d.d;});
    var xMin = Math.min.apply(null, xs), xMax = Math.max.apply(null, xs);
    var fitSlope = 0.7455, fitIntercept = 49.3516;
    var fitLine = [
      {x: xMin, y: fitSlope*xMin + fitIntercept},
      {x: xMax, y: fitSlope*xMax + fitIntercept}
    ];

    depthWinsChart = new Chart(ctx, {
      type: 'scatter',
      data: {
        datasets: [
          {
            label: 'Manager-seasons',
            data: DEPTH_VS_WINS_DATA.map(function(d){ return {x:d.d, y:d.wr, m:d.m, s:d.s}; }),
            backgroundColor: DEPTH_VS_WINS_DATA.map(function(d){ return MANAGER_COLORS[d.m] || 'rgba(74,127,168,0.7)'; }),
            pointRadius: 6,
            pointHoverRadius: 8,
          },
          {
            type: 'line',
            label: 'Best fit',
            data: fitLine,
            borderColor: 'rgba(30,26,20,0.4)',
            borderWidth: 2,
            borderDash: [6,4],
            pointRadius: 0,
            fill: false,
          }
        ]
      },
      plugins: [winRateBandsPlugin],
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { display:false },
          tooltip: {
            callbacks: {
              label: function(ctx){
                if (ctx.dataset.label === 'Best fit') return null;
                var d = ctx.raw;
                return d.m+' ('+d.s+'): depth '+d.x.toFixed(2)+', win rate '+d.y.toFixed(1)+'%';
              }
            }
          }
        },
        scales: {
          x: { title:{display:true,text:'Bench depth score'} },
          y: { title:{display:true,text:'Win rate (%)'} }
        }
      }
    });
  }
  renderDepthWinsChart();


  var missedWinsSortState = { key:'rate', type:'number', dir:'desc' };
  var missedWinsFilter = 'career';
  function renderMissedWinsPills() {
    var el = document.getElementById('missed-wins-pills');
    if (!el) return;
    var keys = ['career'].concat(PAGE_SEASONS.map(String));
    var html = '';
    keys.forEach(function(k) {
      var label = k === 'career' ? 'Career' : seasonLabel(k);
      var swatch = SEASON_COLORS[k] ? ' year-swatch-btn" style="--swatch-color:' + SEASON_COLORS[k] + ';' : '';
      html += '<button class="heatmap-season-pill'+(k==='career'?' active':'')+swatch+'" onclick="setMissedWinsFilter(\''+k+'\', this)">'+label+'</button>';
    });
    el.innerHTML = html;
  }
  function setMissedWinsFilter(key, btn) {
    missedWinsFilter = key;
    if (btn) {
      btn.parentElement.querySelectorAll('.heatmap-season-pill').forEach(function(p){ p.classList.remove('active'); });
      btn.classList.add('active');
    }
    renderMissedWins();
  }
  function renderMissedWins() {
    var tbody = document.querySelector('#missed-wins-table tbody');
    var data = MISSED_WINS_BY_FILTER[missedWinsFilter] || [];
    var rows = sortRows(data, missedWinsSortState.key, missedWinsSortState.type, missedWinsSortState.dir);

    var minN = Math.min.apply(null, data.map(function(d){return d.n;}));
    var maxN = Math.max.apply(null, data.map(function(d){return d.n;}));
    var minL = Math.min.apply(null, data.map(function(d){return d.losses;}));
    var maxL = Math.max.apply(null, data.map(function(d){return d.losses;}));
    var minR = Math.min.apply(null, data.map(function(d){return d.rate;}));
    var maxR = Math.max.apply(null, data.map(function(d){return d.rate;}));
    var minReg = Math.min.apply(null, data.map(function(d){return d.reg;}));
    var maxReg = Math.max.apply(null, data.map(function(d){return d.reg;}));
    var minPo = Math.min.apply(null, data.map(function(d){return d.po;}));
    var maxPo = Math.max.apply(null, data.map(function(d){return d.po;}));
    var html = '';
    rows.forEach(function(d, i){
      var nBg = gradientColor(d.n, minN, maxN);
      var lBg = gradientColor(d.losses, minL, maxL);
      var bg = gradientColor(d.rate, minR, maxR);
      var regBg = gradientColor(d.reg, minReg, maxReg);
      var poBg = gradientColor(d.po, minPo, maxPo);
      html += '<tr>'
        +'<td class="le-rank">'+(i+1)+'</td>'
        +'<td style="font-weight:600;color:var(--palm)">'+d.manager+'</td>'
        +'<td>'+d.weeks+'</td>'
        +'<td><span style="background:'+lBg+';color:#fff;padding:0.15rem 0.5rem;border-radius:4px;font-weight:600;">'+d.losses+'</span></td>'
        +'<td><span style="background:'+nBg+';color:#fff;padding:0.15rem 0.5rem;border-radius:4px;font-weight:700;">'+d.n+'</span></td>'
        +'<td><span style="background:'+bg+';color:#fff;padding:0.2rem 0.55rem;border-radius:4px;font-weight:700;">'+d.rate.toFixed(1)+'%</span></td>'
        +'<td><span style="background:'+regBg+';color:#fff;padding:0.15rem 0.5rem;border-radius:4px;font-weight:600;">'+d.reg+'</span></td>'
        +'<td><span style="background:'+poBg+';color:#fff;padding:0.15rem 0.5rem;border-radius:4px;font-weight:600;">'+d.po+'</span></td>'
        +'</tr>';
    });
    tbody.innerHTML = html;
  }

  var blundersFilter = 'career';
  function renderBlundersPills() {
    var el = document.getElementById('blunders-pills');
    if (!el) return;
    var keys = ['career'].concat(PAGE_SEASONS.map(String));
    var html = '';
    keys.forEach(function(k) {
      var label = k === 'career' ? 'All-Time' : seasonLabel(k);
      var swatch = SEASON_COLORS[k] ? ' year-swatch-btn" style="--swatch-color:' + SEASON_COLORS[k] + ';' : '';
      html += '<button class="heatmap-season-pill'+(k==='career'?' active':'')+swatch+'" onclick="setBlundersFilter(\''+k+'\', this)">'+label+'</button>';
    });
    el.innerHTML = html;
  }
  function setBlundersFilter(key, btn) {
    blundersFilter = key;
    if (btn) {
      btn.parentElement.querySelectorAll('.heatmap-season-pill').forEach(function(p){ p.classList.remove('active'); });
      btn.classList.add('active');
    }
    renderBlunders();
  }
  function renderBlunders() {
    var tbody = document.querySelector('#blunders-table tbody');
    var data = BLUNDERS_BY_FILTER[blundersFilter] || [];
    var minA = Math.min.apply(null, data.map(function(d){return d.actual;}));
    var maxA = Math.max.apply(null, data.map(function(d){return d.actual;}));
    var minG = Math.min.apply(null, data.map(function(d){return d.gap;}));
    var maxG = Math.max.apply(null, data.map(function(d){return d.gap;}));
    var html = '';
    data.forEach(function(d, i){
      var badgeClass = d.outcome === 'Win' ? 'outcome-win' : 'outcome-loss';
      var missedStr = d.missed ? '<span class="missed-badge">Yes</span>' : '<span style="color:var(--muted);">No</span>';
      // More points scored = better = green. Fewer = worse = red.
      var actualBg = gradientColor(d.actual, minA, maxA, true);
      // Gap severity: gold (mildest, in this top-10) straight to red (worst). No white/light fade.
      var t = (d.gap - minG) / (maxG - minG);
      var gr = lerp(212,168,t), gg = lerp(175,90,t), gb = lerp(55,90,t);
      var gapBg = 'rgba('+gr+','+gg+','+gb+',0.85)';
      var seasonColor = SEASON_COLORS[d.season] || 'var(--muted)';
      html += '<tr class="blunder-row" onclick="openRosterModal('+i+')">'
        +'<td class="le-rank">'+(i+1)+'</td>'
        +'<td><span class="season-pill" style="background:'+seasonColor+';">'+d.season+'</span></td>'
        +'<td>'+d.week+'</td>'
        +'<td style="font-weight:600;color:var(--palm)">'+d.manager+'</td>'
        +'<td><span style="background:'+actualBg+';color:#fff;padding:0.15rem 0.5rem;border-radius:4px;font-weight:600;">'+d.actual.toFixed(1)+'</span></td>'
        +'<td>'+d.optimal.toFixed(1)+'</td>'
        +'<td><span style="background:'+gapBg+';color:#fff;padding:0.15rem 0.5rem;border-radius:4px;font-weight:700;">+'+d.gap.toFixed(1)+'</span></td>'
        +'<td><span class="outcome-badge '+badgeClass+'">'+d.outcome+'</span></td>'
        +'<td>'+missedStr+'</td>'
        +'</tr>';
    });
    tbody.innerHTML = html;
  }

  renderMissedWinsPills();
  renderMissedWins();
  wireSortableHeaders('missed-wins-table', renderMissedWins, missedWinsSortState);
  renderBlundersPills();
  renderBlunders();

  /* ── Weekly Efficiency Calendar heatmap ──
     Compact rows: [Season, WeekOrder, ManagerIndex, Gap, Forfeited(0/1)]
     WeekOrder 1-13/14 = regular season, remainder = playoff rounds. ── */
  // Career average: [ManagerIndex, ColumnIndex(1-14=Week1-14, 15-18=Playoff Rd 1-4), AvgGap, SeasonsCount]
  // Career average: [ManagerIndex, ColumnIndex(1-14=Week1-14, 15-18=First Round/Quarterfinal/Semifinal/Championship), AvgGap, SeasonsCount]
  // Columns 15-18 are grouped by PLAYOFF ROLE, not raw round number, since 2020/2021 ran 4 playoff
  // rounds and 2022-2025 ran 3. "Championship" always means the actual final, regardless of
  // whether it was that season's 3rd or 4th round.

  function weekLabelShort(season, w) {
    var info = seasonInfo(season);
    var regWeeks = info.regular_season_weeks;
    if (w <= regWeeks) return 'W' + w;
    var roundNum = w - regWeeks;
    var totalRounds = info.final_week - regWeeks;
    return roleShort(totalRounds - roundNum + 1, totalRounds);
  }

  function renderHeatmapSeasonPills() {
    var el = document.getElementById('season-pills');
    var html = '<button class="heatmap-season-pill active" data-season="career" onclick="renderCareerAvgGrid(this)">Career Avg</button>';
    HEATMAP_SEASONS.forEach(function(s) {
      var swatch = SEASON_COLORS[s] ? ' year-swatch-btn" style="--swatch-color:' + SEASON_COLORS[s] + ';' : '';
      html += '<button class="heatmap-season-pill'+swatch+'" data-season="'+s+'" onclick="renderHeatmapGrid('+s+', this)">'+s+'</button>';
    });
    el.innerHTML = html;
  }

  function renderHeatmapGrid(season, btn) {
    if (btn) {
      document.querySelectorAll('.heatmap-season-pill').forEach(function(p){ p.classList.remove('active'); });
      btn.classList.add('active');
    }
    var maxWeek = MAX_WEEK;
    var cols = '130px repeat('+maxWeek+', 1fr)';

    // Header row
    var headerHtml = '<div class="heatmap-header-cell"></div>';
    for (var w = 1; w <= maxWeek; w++) {
      headerHtml += '<div class="heatmap-header-cell">'+weekLabelShort(season, w)+'</div>';
    }

    // Lookup: for this season, map "managerIdx-week" -> {gap, forfeit}
    var lookup = {};
    HEATMAP_DATA.forEach(function(row) {
      if (row[0] !== season) return;
      lookup[row[2]+'-'+row[1]] = { gap: row[3], forfeit: row[4] === 1 };
    });

    var bodyHtml = '';
    HEATMAP_MANAGERS.forEach(function(mgr, mIdx) {
      var rowHtml = '<div class="heatmap-row-label">'+mgr+'</div>';
      for (var w = 1; w <= maxWeek; w++) {
        var entry = lookup[mIdx+'-'+w];
        var label = weekLabelShort(season, w);
        if (!entry) {
          rowHtml += '<div class="heatmap-cell empty" title="'+mgr+', '+label+': bye or not in bracket"></div>';
        } else if (entry.forfeit) {
          rowHtml += '<div class="heatmap-cell forfeit" title="'+mgr+', '+label+': excluded from average (forfeit or incomplete lineup)"></div>';
        } else {
          var bg = gradientColor(entry.gap, HEATMAP_GAP_MIN, HEATMAP_GAP_MAX);
          rowHtml += '<div class="heatmap-cell" style="background:'+bg+';" title="'+mgr+', '+label+': '+entry.gap.toFixed(1)+' pts left on bench"></div>';
        }
      }
      bodyHtml += '<div class="heatmap-row" style="grid-template-columns:'+cols+';">'+rowHtml+'</div>';
    });

    document.getElementById('heatmap-grid').innerHTML =
      '<div class="heatmap-header" style="grid-template-columns:'+cols+';">'+headerHtml+'</div>' + bodyHtml;
  }

  function careerColLabel(ci) {
    if (ci <= MAX_REG) return 'W'+ci;
    return roleShort(MAX_REG + MAX_ROUNDS - ci + 1, MAX_ROUNDS);
  }

  function renderCareerAvgGrid(btn) {
    if (btn) {
      document.querySelectorAll('.heatmap-season-pill').forEach(function(p){ p.classList.remove('active'); });
      btn.classList.add('active');
    }
    var maxCol = MAX_REG + MAX_ROUNDS; // regular-season weeks, then playoff rounds by role
    var cols = '130px repeat('+maxCol+', 1fr)';

    var headerHtml = '<div class="heatmap-header-cell"></div>';
    for (var c = 1; c <= maxCol; c++) {
      headerHtml += '<div class="heatmap-header-cell">'+careerColLabel(c)+'</div>';
    }

    // Lookup: "managerIdx-col" -> {gap, n}
    var lookup = {};
    CAREER_AVG_DATA.forEach(function(row) {
      lookup[row[0]+'-'+row[1]] = { gap: row[2], n: row[3] };
    });

    var bodyHtml = '';
    HEATMAP_MANAGERS.forEach(function(mgr, mIdx) {
      var rowHtml = '<div class="heatmap-row-label">'+mgr+'</div>';
      for (var c = 1; c <= maxCol; c++) {
        var entry = lookup[mIdx+'-'+c];
        var label = careerColLabel(c);
        if (!entry) {
          rowHtml += '<div class="heatmap-cell empty" title="'+mgr+', '+label+': no games in this slot"></div>';
        } else {
          var bg = gradientColor(entry.gap, HEATMAP_GAP_MIN, HEATMAP_GAP_MAX);
          var seasonWord = entry.n === 1 ? 'season' : 'seasons';
          rowHtml += '<div class="heatmap-cell" style="background:'+bg+';" title="'+mgr+', '+label+': '+entry.gap.toFixed(1)+' pts avg over '+entry.n+' '+seasonWord+'"></div>';
        }
      }
      bodyHtml += '<div class="heatmap-row" style="grid-template-columns:'+cols+';">'+rowHtml+'</div>';
    });

    document.getElementById('heatmap-grid').innerHTML =
      '<div class="heatmap-header" style="grid-template-columns:'+cols+';">'+headerHtml+'</div>' + bodyHtml;
  }

  renderHeatmapSeasonPills();
  renderCareerAvgGrid();


  // the handlers the page's markup names (inline onclick, as on the Stage A page)
  Object.assign(window, { closeRosterModal, openRosterModal, renderCareerAvgGrid, renderDepthChart, renderEfficiencyChart, renderHeatmapGrid, setBlundersFilter, setDepthAdjustedFilter, setMissedWinsFilter });
}

config().then(function (c) {
  cfg = c;
  mgr = managers(cfg);
  drawNav(cfg, 'lineup-efficiency');
  drawSubnav(cfg, 'lineup-efficiency');
  drawFooter(cfg);
  chapterRail();
  return load('data/v1/lineup-efficiency.json');
}).then(function (M) {
  var D = lineupData(M, mgr.name);
  PAGE_SEASONS = D.PAGE_SEASONS; EFFICIENCY_BY_FILTER = D.EFFICIENCY_BY_FILTER;
  EFFICIENCY_GLOBAL_MIN = D.EFFICIENCY_GLOBAL_MIN; EFFICIENCY_GLOBAL_MAX = D.EFFICIENCY_GLOBAL_MAX;
  MISSED_WINS_BY_FILTER = D.MISSED_WINS_BY_FILTER; BLUNDERS_BY_FILTER = D.BLUNDERS_BY_FILTER; ROSTERS_BY_FILTER = D.ROSTERS_BY_FILTER;
  DEPTH_BY_FILTER = D.DEPTH_BY_FILTER; DEPTH_ADJUSTED_BY_FILTER = D.DEPTH_ADJUSTED_BY_FILTER;
  SEASON_TREND_DATA = D.SEASON_TREND_DATA; DEPTH_VS_WINS_DATA = D.DEPTH_VS_WINS_DATA;
  HEATMAP_MANAGERS = D.HEATMAP_MANAGERS; HEATMAP_DATA = D.HEATMAP_DATA; HEATMAP_SEASONS = D.HEATMAP_SEASONS;
  CAREER_AVG_DATA = D.CAREER_AVG_DATA; HEATMAP_GAP_MIN = D.HEATMAP_GAP_MIN; HEATMAP_GAP_MAX = D.HEATMAP_GAP_MAX;
  PAGE_LIVE_SEASON = cfg.live_season != null && PAGE_SEASONS.indexOf(cfg.live_season) !== -1 ? cfg.live_season : null;
  SEASON_COLORS = (cfg.theme && cfg.theme.season_colors) || {};
  MANAGER_COLORS = {};
  mgr.visible.forEach(function (m) {
    if (HEATMAP_MANAGERS.indexOf(m.name) !== -1 && m.colors) MANAGER_COLORS[m.name] = m.colors.dark;
  });
  MAX_REG = Math.max.apply(null, HEATMAP_SEASONS.map(function (s) { return seasonInfo(s).regular_season_weeks || 0; }));
  MAX_ROUNDS = Math.max.apply(null, HEATMAP_SEASONS.map(roundsOf));
  MAX_WEEK = Math.max.apply(null, HEATMAP_SEASONS.map(function (s) { return seasonInfo(s).final_week || 0; }));
  methodNotes(cfg, mgr, PAGE_SEASONS);
  dataNotes(M);
  runPage();
}).catch(function (err) {
  console.error(err);
  var el = document.querySelector('#missed-wins-table tbody');
  if (el) el.innerHTML = '<tr><td colspan="8"><div class="data-state data-state-error">This page could not be loaded.</div></td></tr>';
});
