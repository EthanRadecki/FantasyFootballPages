/* Position Impact: every position's started points removed from both teams in every real matchup,
   side by side (flip rates, predictability, win% correlations, draft round and draft order,
   draft capital, where production comes from, and a deep dive per position).

   Reads config.json and data/v1/position-impact.json (schema "position-impact"); impact-data.js
   renames its manager keys to names, which gives the Stage A file exactly. The script itself is the
   Stage A page's, run once the data is in (decision 7.14: same look first; its inline handlers stay
   on window until the design pass). What was typed into the page now comes from the data: the
   positions (the league's started lineup slots), first season, games, manager-seasons, which pick
   each position's draft analysis uses, and the latest round anyone drafted. */

import { config, load } from '../core/data.js';
import { managers } from '../core/managers.js';
import { drawNav, drawFooter, drawSubnav } from '../core/nav.js';
import { byName, ordinal as ordinalOf, picksByNth } from './impact-data.js';

var Chart = window.Chart;
var PDATA = null, POS_ORDER = [], CURRENT_POS = null, BASE_POS = null, MAX_ROUND = 16;
// position colors (a position the list does not know is drawn grey)
var POS_COLORS = { 'QB':'#983a3a', 'RB':'#4a7a4a', 'WR':'#3a6f98', 'TE':'#a07010', 'K':'#6a6460', 'D/ST':'#504840' };
var ORDINAL_WORDS = { 1: 'first', 2: 'second', 3: 'third', 4: 'fourth' };

/* the notes the Stage A page typed, from the data */
function notes(cfg) {
  var seasons = Object.keys(PDATA.season_flip_rate[POS_ORDER[0]] || {}).map(Number).sort();
  document.querySelectorAll('[data-first-season]').forEach(function (el) { el.textContent = seasons[0] || cfg.league.first_season; });
  document.querySelectorAll('[data-total-games]').forEach(function (el) { el.textContent = PDATA.total_games; });
  var corr = PDATA.performance_correlation[POS_ORDER[0]];
  document.getElementById('ppg-n').textContent = corr ? corr.ppg_vs_winpct.n : '';
  var groups = picksByNth(PDATA.nth_pick, POS_ORDER);
  var word = function (n) { return ORDINAL_WORDS[n] || ordinalOf(n); };
  var text = 'For the draft-capital analysis, ' + groups.map(function (g, i) {
    return g[1].join('/').replace('D/ST', 'D-ST') + ' use' + (i === 0 ? ' the round each manager’s ' : ' the ')
      + '<strong>' + word(g[0]) + '</strong> pick' + (i === 0 ? ' at that position was taken' : '');
  }).join('; ');
  var later = groups.filter(function (g) { return g[0] > 1; });
  if (later.length) {
    text += ', since nearly everyone takes their ' + later.map(function (g) { return g[1].map(function (p) { return p + '1'; }).join('/'); }).join('/')
      + ' in the first couple rounds regardless of philosophy -- the ' + word(later[0][0]) + ' one is where actual draft strategy diverges.';
  } else text += '.';
  document.getElementById('nth-note').innerHTML = text;
  document.getElementById('dv-picks').textContent = groups.map(function (g) {
    return ordinalOf(g[0]) + ' pick for ' + g[1].join('/').replace('D/ST', 'D-ST');
  }).join(', ');
  // the round correlations: "close to zero" when every position is
  var r = POS_ORDER.map(function (p) { return { p: p, r: PDATA.performance_correlation[p].round_vs_winpct.r }; });
  var maxAbs = r.slice().sort(function (a, b) { return Math.abs(b.r) - Math.abs(a.r); })[0];
  document.getElementById('round-corr-note').textContent = Math.abs(maxAbs.r) < 0.15
    ? ' Every position lands close to zero -- position performance matters (see above), but when you draft it barely does, across the board.'
    : ' The strongest link is ' + maxAbs.p + ' (r = ' + maxAbs.r.toFixed(2) + ').';
}

var CURRENT_MGR = null;

var netImpactChart = null, ppgScatterChart = null, roundScatterChart = null;

function shortName(name) {
  var parts = name.split(' ');
  return parts.length < 2 ? name : parts[0] + ' ' + parts[parts.length-1][0] + '.';
}

var draftWaiverLinePlugin = {
  id: 'draftWaiverLine',
  afterDatasetsDraw: function(chart) {
    var yScale = chart.scales.y;
    var area = chart.chartArea;
    var ctx = chart.ctx;
    var yVal = chart.$waiverPPG;
    if (yVal === undefined) return;
    var yPx = yScale.getPixelForValue(yVal);
    ctx.save();
    ctx.beginPath();
    ctx.setLineDash([5, 4]);
    ctx.moveTo(area.left, yPx);
    ctx.lineTo(area.right, yPx);
    ctx.strokeStyle = 'rgba(168,90,90,0.7)';
    ctx.lineWidth = 1.5;
    ctx.stroke();
    ctx.setLineDash([]);
    ctx.font = "600 10px 'Outfit', sans-serif";
    ctx.fillStyle = 'rgba(168,90,90,0.9)';
    ctx.textAlign = 'right';
    ctx.textBaseline = 'bottom';
    ctx.fillText('Waiver baseline: ' + yVal.toFixed(2) + ' PPG', area.right - 4, yPx - 3);
    ctx.restore();
  }
};

function renderFlipRateChart() {
  var rates = PDATA.flip_rates;
  var ctx = document.getElementById('flip-rate-chart').getContext('2d');
  new Chart(ctx, {
    type: 'bar',
    data: {
      labels: POS_ORDER,
      datasets: [{ data: POS_ORDER.map(function(p){ return rates[p].pct; }),
        backgroundColor: POS_ORDER.map(function(p){ return POS_COLORS[p]; }), borderRadius: 4 }]
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: { legend: { display:false },
        tooltip: { callbacks: { label: function(item){
          var p = POS_ORDER[item.dataIndex];
          return rates[p].flips + ' of ' + rates[p].total + ' games flip (' + rates[p].pct + '%)';
        } } } },
      scales: { y: { title: { display:true, text:'% of games that flip' }, beginAtZero:true } }
    }
  });
}

function renderConsistencyChart() {
  var cv = PDATA.consistency;
  var ctx = document.getElementById('consistency-chart').getContext('2d');
  new Chart(ctx, {
    type: 'bar',
    data: {
      labels: POS_ORDER,
      datasets: [{ data: POS_ORDER.map(function(p){ return cv[p].avg_cv; }),
        backgroundColor: POS_ORDER.map(function(p){ return POS_COLORS[p]; }), borderRadius: 4 }]
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: { legend: { display:false },
        tooltip: { callbacks: { label: function(item){
          var p = POS_ORDER[item.dataIndex];
          return 'Based on ' + cv[p].sample + ' player-seasons';
        } } } },
      scales: { y: { title: { display:true, text:'Week-to-week unpredictability' }, beginAtZero:true } }
    }
  });
}

function renderCorrBarChart(canvasId, valueFn, axisLabel) {
  var ctx = document.getElementById(canvasId).getContext('2d');
  new Chart(ctx, {
    type: 'bar',
    data: {
      labels: POS_ORDER,
      datasets: [{ data: POS_ORDER.map(valueFn),
        backgroundColor: POS_ORDER.map(function(p){ return POS_COLORS[p]; }), borderRadius: 4 }]
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: { legend: { display:false } },
      scales: {
        y: { title: { display:true, text:axisLabel } },
        x: {}
      }
    }
  });
}

var ACQ_COLORS = ['#4a7fa8', '#c0623a', '#d4af37']; // Drafted, Waiver/FA, Traded
var ACQ_LABELS = ['Drafted', 'Waiver / FA', 'Traded'];
function renderLeagueAcqPies() {
  var grid = document.getElementById('league-pie-grid');
  grid.innerHTML = POS_ORDER.map(function(p) {
    return '<div class="league-pie-cell">'
      + '<div class="league-pie-label" style="background:' + POS_COLORS[p] + '22;color:' + POS_COLORS[p] + ';">' + p + '</div>'
      + '<div class="pie-canvas-wrap" style="margin:0 auto;"><canvas id="league-pie-' + p.replace('/','') + '"></canvas></div>'
      + '<div class="pie-legend" id="league-legend-' + p.replace('/','') + '" style="margin:0.5rem auto 0;"></div>'
      + '</div>';
  }).join('');

  POS_ORDER.forEach(function(p) {
    var lt = PDATA.acquisition_source[p].league_total;
    var vals = [lt.drafted, lt.waiver, lt.traded];
    var total = vals.reduce(function(a,b){ return a+b; }, 0);

    var legendEl = document.getElementById('league-legend-' + p.replace('/',''));
    legendEl.innerHTML = ACQ_LABELS.map(function(lab, i) {
      var pct = total !== 0 ? (vals[i] / total * 100).toFixed(0) : 0;
      return '<div class="pie-legend-row"><span class="pie-swatch" style="background:' + ACQ_COLORS[i] + ';"></span>'
        + lab + '<span class="pie-legend-val">' + pct + '%</span></div>';
    }).join('');

    var ctx = document.getElementById('league-pie-' + p.replace('/','')).getContext('2d');
    new Chart(ctx, {
      type: 'doughnut',
      data: { labels: ACQ_LABELS, datasets: [{ data: vals.map(function(v){ return Math.max(v,0); }), backgroundColor: ACQ_COLORS, borderWidth: 0 }] },
      options: { responsive:true, maintainAspectRatio:false, plugins:{ legend:{ display:false } }, cutout:'62%' }
    });
  });
}

function renderMgrSelector() {
  var managers = Object.keys(PDATA.acquisition_source[BASE_POS].per_manager).sort();
  if (!CURRENT_MGR || managers.indexOf(CURRENT_MGR) === -1) {
    CURRENT_MGR = managers[0];
  }
  var row = document.getElementById('mgr-select-row');
  row.innerHTML = managers.map(function(m) {
    var active = m === CURRENT_MGR ? ' active' : '';
    return '<div class="mgr-select-pill' + active + '" onclick="selectMgrForPie(\'' + m + '\')">' + shortName(m) + '</div>';
  }).join('');
}

function selectMgrForPie(m) {
  CURRENT_MGR = m;
  document.querySelectorAll('.mgr-select-pill').forEach(function(el) {
    el.classList.toggle('active', el.textContent.trim() === shortName(m));
  });
  renderMgrPieGrid();
}

function renderMgrPieGrid() {
  var grid = document.getElementById('mgr-pie-grid');
  grid.innerHTML = POS_ORDER.map(function(p) {
    return '<div class="league-pie-cell">'
      + '<div class="league-pie-label" style="background:' + POS_COLORS[p] + '22;color:' + POS_COLORS[p] + ';">' + p + '</div>'
      + '<div class="pie-canvas-wrap" style="margin:0 auto;"><canvas id="mgr-pie-' + p.replace('/','') + '"></canvas></div>'
      + '<div class="pie-legend" id="mgr-pie-legend-' + p.replace('/','') + '" style="margin:0.5rem auto 0;"></div>'
      + '</div>';
  }).join('');

  POS_ORDER.forEach(function(p) {
    var acq = PDATA.acquisition_source[p].per_manager[CURRENT_MGR];
    var vals = [acq.drafted, acq.waiver, acq.traded];
    var total = vals.reduce(function(a,b){ return a+b; }, 0);

    var legendEl = document.getElementById('mgr-pie-legend-' + p.replace('/',''));
    legendEl.innerHTML = ACQ_LABELS.map(function(lab, i) {
      var pct = total !== 0 ? (vals[i] / total * 100).toFixed(0) : 0;
      return '<div class="pie-legend-row"><span class="pie-swatch" style="background:' + ACQ_COLORS[i] + ';"></span>'
        + lab + '<span class="pie-legend-val">' + pct + '%</span></div>';
    }).join('');

    var ctx = document.getElementById('mgr-pie-' + p.replace('/','')).getContext('2d');
    new Chart(ctx, {
      type: 'doughnut',
      data: { labels: ACQ_LABELS, datasets: [{ data: vals.map(function(v){ return Math.max(v,0); }), backgroundColor: ACQ_COLORS, borderWidth: 0 }] },
      options: { responsive:true, maintainAspectRatio:false, plugins:{ legend:{ display:false } }, cutout:'62%' }
    });
  });
}

var dcapSort = { key: 'Manager', dir: 'asc' };

function setDcapSort(key) {
  if (dcapSort.key === key) {
    dcapSort.dir = dcapSort.dir === 'asc' ? 'desc' : 'asc';
  } else {
    dcapSort.key = key;
    dcapSort.dir = 'asc'; // ascending default: A-Z for manager, earliest-round-first for positions
  }
  renderDraftCapitalSummaryTable();
}

function renderDraftCapitalSummaryTable() {
  var allManagers = Object.keys(PDATA.draft_capital[BASE_POS] || {});
  var table = document.getElementById('dcap-summary-table');

  function roundColor(rnd, maxRound) {
    if (rnd === null) return '';
    var t = Math.max(0, Math.min(1, (rnd - 1) / (maxRound - 1)));
    var opacity = 1 - t * 0.75;
    return 'background:rgba(80,72,64,' + opacity.toFixed(2) + ');color:' + (t < 0.55 ? '#f5f0e8' : '#3d3a38') + ';';
  }

  function sortValue(m, key) {
    if (key === 'Manager') return m;
    var d = PDATA.draft_capital[key][m];
    return d ? d.career_avg_round : null;
  }

  var managers = allManagers.slice().sort(function(a, b) {
    var va = sortValue(a, dcapSort.key);
    var vb = sortValue(b, dcapSort.key);
    if (dcapSort.key === 'Manager') {
      return dcapSort.dir === 'asc' ? va.localeCompare(vb) : vb.localeCompare(va);
    }
    if (va === null && vb === null) return 0;
    if (va === null) return 1;  // no data always sorts last, regardless of direction
    if (vb === null) return -1;
    return dcapSort.dir === 'asc' ? va - vb : vb - va;
  });

  var headerCols = ['Manager'].concat(POS_ORDER);
  var html = '<thead><tr>' + headerCols.map(function(col) {
    var isManager = col === 'Manager';
    var arrow = dcapSort.key === col ? (dcapSort.dir === 'asc' ? ' \u25B2' : ' \u25BC') : '';
    var colorStyle = isManager ? '' : ('color:' + POS_COLORS[col] + ';');
    var cellClass = isManager ? 'dcap-mgr-cell dcap-sortable' : 'dcap-sortable';
    return '<th class="' + cellClass + '" style="' + colorStyle + 'cursor:pointer;" onclick="setDcapSort(\'' + col + '\')">' + col + arrow + '</th>';
  }).join('') + '</tr></thead><tbody>';

  managers.forEach(function(m) {
    html += '<tr><td class="dcap-mgr-cell">' + shortName(m) + '</td>';
    POS_ORDER.forEach(function(p) {
      var avg = PDATA.draft_capital[p][m] ? PDATA.draft_capital[p][m].career_avg_round : null;
      if (avg === null || avg === undefined) {
        html += '<td class="dcap-streamed">&ndash;</td>';
      } else {
        html += '<td style="' + roundColor(avg, MAX_ROUND) + 'font-weight:700;cursor:pointer;" onclick="selectPosition(\'' + p + '\', true)" title="Click to see ' + p + ' detail">' + avg.toFixed(1) + '</td>';
      }
    });
    html += '</tr>';
  });
  html += '</tbody>';
  table.innerHTML = html;
}

var scatterTrendPlugin = {
  id: 'scatterTrend',
  afterDatasetsDraw: function(chart) {
    var xScale = chart.scales.x, yScale = chart.scales.y;
    var ctx = chart.ctx;
    var trend = chart.$trend;
    if (!trend) return;
    var x1 = xScale.min, x2 = xScale.max;
    var y1 = trend.slope * x1 + trend.intercept;
    var y2 = trend.slope * x2 + trend.intercept;
    ctx.save();
    ctx.beginPath();
    ctx.setLineDash([5, 4]);
    ctx.moveTo(xScale.getPixelForValue(x1), yScale.getPixelForValue(y1));
    ctx.lineTo(xScale.getPixelForValue(x2), yScale.getPixelForValue(y2));
    ctx.strokeStyle = 'rgba(90,85,80,0.55)';
    ctx.lineWidth = 1.75;
    ctx.stroke();
    ctx.setLineDash([]);
    ctx.restore();
  }
};

function renderPpgScatterChart() {
  var perf = PDATA.performance_correlation[CURRENT_POS];
  var stat = perf.ppg_vs_winpct;
  var points = perf.points.map(function(p){ return { x: p.ppg, y: p.win_pct * 100, season: p.season, manager: p.manager }; });

  document.getElementById('ppg-scatter-title').textContent = CURRENT_POS + ' PPG vs. Win%';
  document.getElementById('ppg-scatter-note').textContent =
    'r = ' + stat.r.toFixed(3) + '  (R\u00B2 = ' + (stat.r2*100).toFixed(1) + '%,  n = ' + stat.n + ')';

  if (ppgScatterChart) ppgScatterChart.destroy();
  var ctx = document.getElementById('ppg-scatter-chart').getContext('2d');
  ppgScatterChart = new Chart(ctx, {
    type: 'scatter',
    data: { datasets: [{ data: points, backgroundColor: POS_COLORS[CURRENT_POS] + '99', radius: 4 }] },
    plugins: [scatterTrendPlugin],
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: { legend: { display:false },
        tooltip: { callbacks: {
          title: function(items){ var p = items[0].raw; return p.manager + ' \u2019' + String(p.season).slice(2); },
          label: function(item){ return item.raw.x.toFixed(1) + ' PPG, ' + item.raw.y.toFixed(0) + '% win rate'; }
        } } },
      scales: {
        x: { title: { display:true, text: CURRENT_POS + ' PPG' } },
        y: { title: { display:true, text:'Win %' } }
      }
    }
  });
  ppgScatterChart.$trend = { slope: stat.slope * 100, intercept: stat.intercept * 100 };
  ppgScatterChart.update();
}

function renderRoundScatterChart() {
  var perf = PDATA.performance_correlation[CURRENT_POS];
  var stat = perf.round_vs_winpct;
  var n = PDATA.nth_pick[CURRENT_POS];
  var ordinal = ordinalOf(n);
  var points = perf.points.filter(function(p){ return p.drafted_round !== null; })
    .map(function(p){ return { x: p.drafted_round, y: p.win_pct * 100, season: p.season, manager: p.manager }; });

  document.getElementById('round-scatter-title').textContent = ordinal + ' ' + CURRENT_POS + ' Draft Round vs. Win%';
  document.getElementById('round-scatter-note').textContent =
    'r = ' + stat.r.toFixed(3) + '  (R\u00B2 = ' + (stat.r2*100).toFixed(1) + '%,  n = ' + stat.n + ')';

  if (roundScatterChart) roundScatterChart.destroy();
  var ctx = document.getElementById('round-scatter-chart').getContext('2d');
  roundScatterChart = new Chart(ctx, {
    type: 'scatter',
    data: { datasets: [{ data: points, backgroundColor: POS_COLORS[CURRENT_POS] + '99', radius: 4 }] },
    plugins: [scatterTrendPlugin],
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: { legend: { display:false },
        tooltip: { callbacks: {
          title: function(items){ var p = items[0].raw; return p.manager + ' \u2019' + String(p.season).slice(2); },
          label: function(item){ return 'Drafted round ' + item.raw.x + ', ' + item.raw.y.toFixed(0) + '% win rate'; }
        } } },
      scales: {
        x: { title: { display:true, text: ordinal + ' ' + CURRENT_POS + ' draft round' } },
        y: { title: { display:true, text:'Win %' } }
      }
    }
  });
  roundScatterChart.$trend = { slope: stat.slope * 100, intercept: stat.intercept * 100 };
  roundScatterChart.update();
}

var boxplotChart = null;

var boxplotWhiskerPlugin = {
  id: 'boxplotWhisker',
  afterDatasetsDraw: function(chart) {
    var meta = chart.getDatasetMeta(0);
    var yScale = chart.scales.y;
    var ctx = chart.ctx;
    var stats = chart.$boxStats;
    if (!stats) return;
    ctx.save();
    meta.data.forEach(function(bar, i) {
      var s = stats[i];
      if (!s) return;
      var x = bar.x;
      var capW = Math.min(bar.width * 0.4, 14);
      var yMin = yScale.getPixelForValue(s.min);
      var yMax = yScale.getPixelForValue(s.max);
      var yQ1 = yScale.getPixelForValue(s.q1);
      var yQ3 = yScale.getPixelForValue(s.q3);
      var yMed = yScale.getPixelForValue(s.median);

      ctx.strokeStyle = 'rgba(80,72,64,0.85)';
      ctx.lineWidth = 1.5;
      // lower whisker: min to Q1
      ctx.beginPath(); ctx.moveTo(x, yMin); ctx.lineTo(x, yQ1); ctx.stroke();
      ctx.beginPath(); ctx.moveTo(x - capW/2, yMin); ctx.lineTo(x + capW/2, yMin); ctx.stroke();
      // upper whisker: Q3 to max
      ctx.beginPath(); ctx.moveTo(x, yMax); ctx.lineTo(x, yQ3); ctx.stroke();
      ctx.beginPath(); ctx.moveTo(x - capW/2, yMax); ctx.lineTo(x + capW/2, yMax); ctx.stroke();
      // median line inside the box
      ctx.strokeStyle = 'rgba(40,36,32,0.9)';
      ctx.lineWidth = 2;
      ctx.beginPath(); ctx.moveTo(bar.x - bar.width/2, yMed); ctx.lineTo(bar.x + bar.width/2, yMed); ctx.stroke();
    });
    ctx.restore();
  }
};

function renderBoxplotChart() {
  var bp = PDATA.draft_order[CURRENT_POS].by_order_boxplot;
  var orders = Object.keys(bp).map(Number).sort(function(a,b){ return a-b; });

  document.getElementById('boxplot-title').textContent = CURRENT_POS + ' Weekly Score Distribution By Draft Order';

  var stats = orders.map(function(o){ return bp[o]; });

  var trueMin = Math.min.apply(null, stats.map(function(s){ return s.min; }));
  var trueMax = Math.max.apply(null, stats.map(function(s){ return s.max; }));
  var pad = (trueMax - trueMin) * 0.08;

  if (boxplotChart) boxplotChart.destroy();
  var ctx = document.getElementById('boxplot-chart').getContext('2d');
  boxplotChart = new Chart(ctx, {
    type: 'bar',
    data: {
      labels: orders.map(function(o){ return '#' + o; }),
      datasets: [{
        data: stats.map(function(s){ return [s.q1, s.q3]; }),
        backgroundColor: POS_COLORS[CURRENT_POS] + '55',
        borderColor: POS_COLORS[CURRENT_POS],
        borderWidth: 1.5,
        borderSkipped: false,
      }]
    },
    plugins: [boxplotWhiskerPlugin],
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: { callbacks: {
          label: function(item) {
            var s = stats[item.dataIndex];
            return ['Median: ' + s.median, 'Q1-Q3: ' + s.q1 + ' to ' + s.q3, 'Min-Max: ' + s.min + ' to ' + s.max, 'n=' + s.n + ' weeks'];
          }
        } }
      },
      scales: {
        y: { title: { display:true, text:'Weekly points' }, min: Math.floor(trueMin - pad), max: Math.ceil(trueMax + pad) },
        x: { title: { display:true, text:'Draft order at this position' } }
      }
    }
  });
  boxplotChart.$boxStats = stats;
  boxplotChart.update();
}

function renderPosSelector() {
  var row = document.getElementById('pos-select-row');
  row.innerHTML = POS_ORDER.map(function(p) {
    var active = p === CURRENT_POS ? ' active' : '';
    return '<div class="pos-select-pill' + active + '" data-pos="' + p + '" onclick="selectPosition(\'' + p + '\')">' + p + '</div>';
  }).join('');
}

function selectPosition(pos, scrollToDetail) {
  CURRENT_POS = pos;
  document.querySelectorAll('.pos-select-pill').forEach(function(el) {
    el.classList.toggle('active', el.dataset.pos === pos);
  });
  renderNetImpactChart();
  renderPpgScatterChart();
  renderRoundScatterChart();
  renderBoxplotChart();
  renderDraftCapitalTable();
  if (scrollToDetail) {
    document.getElementById('pos-select-row').scrollIntoView({ behavior: 'smooth', block: 'start' });
  }
}

function renderNetImpactChart() {
  var ni = PDATA.net_impact[CURRENT_POS];
  var rows = Object.keys(ni).map(function(m){ return { name: m, net: ni[m] }; });
  rows.sort(function(a,b){ return b.net - a.net; });

  document.getElementById('net-impact-title').textContent = 'Who ' + CURRENT_POS + ' Has Helped Most (and Least)';

  if (netImpactChart) netImpactChart.destroy();
  var ctx = document.getElementById('net-impact-chart').getContext('2d');
  netImpactChart = new Chart(ctx, {
    type: 'bar',
    data: {
      labels: rows.map(function(r){ return shortName(r.name); }),
      datasets: [{ data: rows.map(function(r){ return r.net; }),
        backgroundColor: rows.map(function(r){ return r.net >= 0 ? 'rgba(74,138,90,0.75)' : 'rgba(192,74,74,0.75)'; }),
        borderRadius: 3 }]
    },
    options: {
      indexAxis: 'y', responsive: true, maintainAspectRatio: false,
      plugins: { legend: { display:false } },
      scales: {
        x: { title: { display:true, text:'Net games (gained - lost)' }, ticks:{ stepSize:1 } },
        y: { ticks: { font: { size:10 } } }
      }
    }
  });
}

function renderDraftWaiverGrid() {
  var grid = document.getElementById('draft-waiver-grid');
  grid.innerHTML = POS_ORDER.map(function(p) {
    var n = PDATA.nth_pick[p];
    var ordinal = ordinalOf(n);
    return '<div class="league-pie-cell">'
      + '<div class="league-pie-label" style="background:' + POS_COLORS[p] + '22;color:' + POS_COLORS[p] + ';">' + p + ' (' + ordinal + ' pick)</div>'
      + '<div class="league-chart-wrap" style="height:200px;"><canvas id="dv-grid-' + p.replace('/','') + '"></canvas></div>'
      + '</div>';
  }).join('');

  POS_ORDER.forEach(function(p) {
    var dv = PDATA.draft_vs_waiver[p];
    var rounds = Object.keys(dv.by_round_ppg).map(Number).sort(function(a,b){ return a-b; });
    var ctx = document.getElementById('dv-grid-' + p.replace('/','')).getContext('2d');
    var chart = new Chart(ctx, {
      type: 'bar',
      data: {
        labels: rounds.map(function(r){ return 'Rd ' + r; }),
        datasets: [{ data: rounds.map(function(r){ return dv.by_round_ppg[r]; }),
          backgroundColor: POS_COLORS[p], borderRadius: 3 }]
      },
      plugins: [draftWaiverLinePlugin],
      options: {
        responsive: true, maintainAspectRatio: false,
        plugins: { legend: { display:false },
          tooltip: { callbacks: { label: function(item){
            var r = rounds[item.dataIndex];
            return item.parsed.y.toFixed(2) + ' PPG (' + dv.by_round_weeks[r] + ' weeks)';
          } } } },
        scales: {
          y: { title: { display:true, text:'PPG', font:{size:10} }, beginAtZero:true, ticks:{ font:{size:9} } },
          x: { ticks: { font:{size:9} } }
        }
      }
    });
    chart.$waiverPPG = dv.waiver_ppg;
    chart.update();
  });
}

var hundredLinePlugin = {
  id: 'hundredLine',
  beforeDatasetsDraw: function(chart) {
    var yScale = chart.scales.y, area = chart.chartArea, ctx = chart.ctx;
    var yPx = yScale.getPixelForValue(100);
    ctx.save();
    ctx.beginPath();
    ctx.setLineDash([4, 4]);
    ctx.moveTo(area.left, yPx);
    ctx.lineTo(area.right, yPx);
    ctx.strokeStyle = 'rgba(90,85,80,0.5)';
    ctx.lineWidth = 1.25;
    ctx.stroke();
    ctx.setLineDash([]);
    ctx.restore();
  }
};

function renderDraftOrderIndexChart() {
  var maxOrder = 0;
  var datasets = POS_ORDER.map(function(p) {
    var doData = PDATA.draft_order[p];
    var orders = Object.keys(doData.by_order_ppg).map(Number).sort(function(a,b){ return a-b; });
    var wellSampled = orders.filter(function(o){ return doData.by_order_weeks[o] >= 20; });
    var base = doData.by_order_ppg[wellSampled[0]];
    maxOrder = Math.max(maxOrder, wellSampled[wellSampled.length - 1]);
    return {
      label: p,
      data: wellSampled.map(function(o){ return { x: o, y: Math.round(doData.by_order_ppg[o] / base * 100) }; }),
      borderColor: POS_COLORS[p],
      backgroundColor: POS_COLORS[p],
      borderWidth: 2.5,
      pointRadius: 3,
      tension: 0.15,
      fill: false,
    };
  });

  var ctx = document.getElementById('draft-order-index-chart').getContext('2d');
  new Chart(ctx, {
    type: 'line',
    data: { datasets: datasets },
    plugins: [hundredLinePlugin],
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: {
        legend: { display: true, position: 'bottom', labels: { boxWidth: 12, font: { size: 11 } } },
        tooltip: { callbacks: {
          title: function(items){ return items[0].dataset.label + ', order #' + items[0].raw.x; },
          label: function(item){ return item.raw.y + '% of their own 1st-pick average'; }
        } }
      },
      scales: {
        x: { type: 'linear', title: { display:true, text:'Draft order at that position' }, ticks: { stepSize: 1 }, min: 1, max: maxOrder },
        y: { title: { display:true, text:'% of that position\u2019s 1st-pick PPG' } }
      }
    }
  });
}

function renderDraftOrderGrid() {
  var grid = document.getElementById('draft-order-grid');
  grid.innerHTML = POS_ORDER.map(function(p) {
    return '<div class="league-pie-cell">'
      + '<div class="league-pie-label" style="background:' + POS_COLORS[p] + '22;color:' + POS_COLORS[p] + ';">' + p + '</div>'
      + '<div class="league-chart-wrap" style="height:200px;"><canvas id="do-grid-' + p.replace('/','') + '"></canvas></div>'
      + '</div>';
  }).join('');

  POS_ORDER.forEach(function(p) {
    var doData = PDATA.draft_order[p];
    var orders = Object.keys(doData.by_order_ppg).map(Number).sort(function(a,b){ return a-b; });
    var ctx = document.getElementById('do-grid-' + p.replace('/','')).getContext('2d');
    new Chart(ctx, {
      type: 'bar',
      data: {
        labels: orders.map(function(o){ return '#' + o; }),
        datasets: [{
          data: orders.map(function(o){ return doData.by_order_ppg[o]; }),
          backgroundColor: orders.map(function(o){
            return doData.by_order_weeks[o] < 20 ? POS_COLORS[p] + '55' : POS_COLORS[p];
          }),
          borderRadius: 3
        }]
      },
      options: {
        responsive: true, maintainAspectRatio: false,
        plugins: { legend: { display:false },
          tooltip: { callbacks: { label: function(item){
            var o = orders[item.dataIndex];
            var thin = doData.by_order_weeks[o] < 20 ? ' (thin sample)' : '';
            return item.parsed.y.toFixed(2) + ' PPG (' + doData.by_order_weeks[o] + ' weeks)' + thin;
          } } } },
        scales: {
          y: { title: { display:true, text:'PPG', font:{size:10} }, beginAtZero:true, ticks:{ font:{size:9} } },
          x: { ticks: { font:{size:9} } }
        }
      }
    });
  });
}

function renderDraftCapitalTable() {
  var dc = PDATA.draft_capital[CURRENT_POS];
  var n = PDATA.nth_pick[CURRENT_POS];
  var ordinal = ORDINAL_WORDS[n] || ordinalOf(n);
  document.getElementById('dcap-title').textContent = 'Who Spends Draft Capital On Their ' + ordinal + ' ' + CURRENT_POS + '?';

  // every season with a draft, from the data
  var years = Object.keys(Object.keys(dc).reduce(function(acc, m) {
    Object.keys(dc[m].by_year || {}).forEach(function(y) { acc[y] = 1; });
    return acc;
  }, {})).sort();
  var managers = Object.keys(dc).sort(function(a,b) {
    var aAvg = dc[a].career_avg_round, bAvg = dc[b].career_avg_round;
    if (aAvg === null) return 1;
    if (bAvg === null) return -1;
    return aAvg - bAvg;
  });

  var maxRound = MAX_ROUND;
  function roundColor(rnd) {
    var t = Math.max(0, Math.min(1, (rnd - 1) / (maxRound - 1)));
    var opacity = 1 - t * 0.75;
    return 'background:rgba(80,72,64,' + opacity.toFixed(2) + ');color:' + (t < 0.55 ? '#f5f0e8' : '#3d3a38') + ';';
  }

  var html = '<thead><tr><th class="dcap-mgr-cell">Manager</th>'
    + years.map(function(y){ return '<th>' + y + '</th>'; }).join('')
    + '<th>Career Avg</th></tr></thead><tbody>';

  managers.forEach(function(m) {
    var d = dc[m];
    html += '<tr><td class="dcap-mgr-cell">' + shortName(m) + '</td>';
    years.forEach(function(y) {
      var rnd = d.by_year[y];
      if (rnd === 'not_in_league') {
        html += '<td class="dcap-not-in-league">&ndash;</td>';
      } else if (rnd === null) {
        html += '<td class="dcap-streamed">streamed</td>';
      } else {
        html += '<td style="' + roundColor(rnd) + 'font-weight:700;">Rd ' + rnd + '</td>';
      }
    });
    var avgTxt = d.career_avg_round !== null ? 'Rd ' + d.career_avg_round.toFixed(1) : '&ndash;';
    html += '<td class="dcap-avg-cell">' + avgTxt + '</td></tr>';
  });

  html += '</tbody>';
  document.getElementById('dcap-table').innerHTML = html;
}


// the handlers the page's markup names (inline onclick, as on the Stage A page)
Object.assign(window, { selectMgrForPie: selectMgrForPie, setDcapSort: setDcapSort, selectPosition: selectPosition });

config().then(function (cfg) {
  var mgr = managers(cfg);
  drawNav(cfg, 'position-impact');
  drawSubnav(cfg, 'position-impact');
  drawFooter(cfg);
  return load('data/v1/position-impact.json').then(function (M) {
    PDATA = byName(M, mgr.name);
    POS_ORDER = PDATA.positions.slice();
    POS_ORDER.forEach(function (p) { if (!POS_COLORS[p]) POS_COLORS[p] = '#8a8480'; });
    BASE_POS = POS_ORDER.indexOf('D/ST') !== -1 ? 'D/ST' : POS_ORDER[POS_ORDER.length - 1];
    CURRENT_POS = BASE_POS;
    var rounds = [];
    POS_ORDER.forEach(function (p) {
      var dc = PDATA.draft_capital[p] || {};
      Object.keys(dc).forEach(function (m) {
        Object.keys(dc[m].by_year || {}).forEach(function (y) { if (typeof dc[m].by_year[y] === 'number') rounds.push(dc[m].by_year[y]); });
      });
    });
    MAX_ROUND = rounds.length ? Math.max(2, Math.max.apply(null, rounds)) : 16;
    notes(cfg);
    renderFlipRateChart();
    renderConsistencyChart();
    renderCorrBarChart('ppg-corr-chart', function(p){ return PDATA.performance_correlation[p].ppg_vs_winpct.r; }, 'Correlation (r) with win%');
    renderCorrBarChart('round-corr-chart', function(p){ return PDATA.performance_correlation[p].round_vs_winpct.r; }, 'Correlation (r) with win%');
    renderDraftWaiverGrid();
    renderDraftOrderIndexChart();
    renderDraftOrderGrid();
    renderDraftCapitalSummaryTable();
    renderLeagueAcqPies();
    renderMgrSelector();
    renderMgrPieGrid();
    renderPosSelector();
    renderNetImpactChart();
    renderPpgScatterChart();
    renderRoundScatterChart();
    renderBoxplotChart();
    renderDraftCapitalTable();
  });
}).catch(function (err) {
  console.error(err);
  var el = document.getElementById('flip-rate-chart');
  if (el) el.parentNode.innerHTML = '<div class="data-state data-state-error">This page could not be loaded.</div>';
});
