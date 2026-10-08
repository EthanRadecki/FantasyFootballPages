/* Surplus Value Index: career and season draft grades, every manager's best and worst pick, and the
   best and worst picks overall and by season.

   Reads config.json and data/v1/surplus-value.json (schema "surplus-value"). Ported from the Stage A
   page with the same layout (decision 7.14). What was written into the page now comes from the
   league and the data:
     seasons        the graded (finished) seasons, their ranges in the headings, season colors from
                    theme.season_colors
     managers       names from config.json
     method note    the baselines, games floor, window and round weights from the model's `method`
                    (the engine's constants)
     joined note    each manager with no grade in the first graded seasons, from the grades
   The numbers follow the page's rounding: grades and totals to 2 places, the color scale of single
   picks from the lowest and highest pick surplus to 2 places. */

import { config, load } from '../core/data.js';
import { managers } from '../core/managers.js';
import { drawNav, drawFooter, drawSubnav } from '../core/nav.js';
import { esc } from '../core/site.js';
import { seasonColor } from '../core/theme.js';
import { chapterRail } from '../components/chapter-rail.js';

var Chart = window.Chart;
var C_MUTED = '#8a8480';
var cfg, mgr, D;
var POP_SURPLUS_MIN, POP_SURPLUS_MAX;

/* red / gold / green pills */
var RGG_GOOD = [90, 138, 90], RGG_MID = [212, 175, 55], RGG_BAD = [168, 90, 90];
function rggLerp(a, b, t) { return Math.round(a + (b - a) * t); }
function rggColor(value, min, max, invert) {
  var p = max === min ? 0.5 : (value - min) / (max - min);
  if (invert) p = 1 - p;
  var c0 = p <= 0.5 ? RGG_GOOD : RGG_MID, c1 = p <= 0.5 ? RGG_MID : RGG_BAD;
  var t = p <= 0.5 ? p / 0.5 : (p - 0.5) / 0.5;
  return 'rgba(' + rggLerp(c0[0], c1[0], t) + ',' + rggLerp(c0[1], c1[1], t) + ',' + rggLerp(c0[2], c1[2], t) + ',0.85)';
}
function rggPill(value, min, max, decimals, signed) {
  return '<span style="background:' + rggColor(value, min, max, true) + ';color:#fff;padding:0.12rem 0.45rem;border-radius:4px;font-weight:700;">'
    + (signed && value >= 0 ? '+' : '') + value.toFixed(decimals) + '</span>';
}
function gridStyle() { return { color: 'rgba(156,148,156,0.15)', drawBorder: false }; }
function tickStyle() { return { color: C_MUTED }; }
/* bone -> red / green, for the career bars and the heatmap */
function gradientColor(val, min, max, alpha) {
  alpha = alpha !== undefined ? alpha : 0.72;
  var p = max !== min ? (val - min) / (max - min) : 0.5;
  var r, g, b, t;
  if (p <= 0.5) { t = p / 0.5; r = Math.round(192 + (245 - 192) * t); g = Math.round(58 + (240 - 58) * t); b = Math.round(58 + (232 - 58) * t); }
  else { t = (p - 0.5) / 0.5; r = Math.round(245 + (74 - 245) * t); g = Math.round(240 + (168 - 240) * t); b = Math.round(232 + (58 - 232) * t); }
  return 'rgba(' + r + ',' + g + ',' + b + ',' + alpha + ')';
}
function r2(x) { return Math.round(x * 100) / 100; }
function sColor(season) { return seasonColor(cfg, season) || 'var(--muted)'; }
function signed2(v) { return (v >= 0 ? '+' : '') + v.toFixed(2); }
function byName(a, b) { var x = mgr.name(a), y = mgr.name(b); return x < y ? -1 : x > y ? 1 : 0; }

/* "2020-2025" (or one season) */
function rangeText(list) {
  if (!list.length) return '';
  return list.length === 1 ? String(list[0]) : list[0] + '-' + list[list.length - 1];
}

/* ── text from the data ── */
function methodNote(m) {
  var groups = {};
  ['QB', 'TE', 'RB', 'WR'].forEach(function (p) {
    if (m.starter_rank[p] != null) (groups[m.starter_rank[p]] = groups[m.starter_rank[p]] || []).push(p);
  });
  var tops = Object.keys(groups).map(Number).sort(function (a, b) { return a - b; })
    .map(function (n) { return 'top ' + n + ' for ' + groups[n].join('/'); }).join(', ');
  // "in a 14-team league" when the baseline is one starter per team of the league's latest graded season
  var last = D.seasons[D.seasons.length - 1];
  var teams = ((cfg.seasons || []).find(function (s) { return s.season === last; }) || {}).team_count;
  if (m.lineup_scaled) tops += ' in ' + m.season + '; each season uses its own: the teams times the position\u2019s lineup slots, FLEX slots split by who filled them';
  else if (teams && teams === m.starter_rank.QB) tops += ' in a ' + teams + '-team league';
  var lo = 1;
  var weights = m.round_weights.map(function (w) {
    var hi = w.last_round != null ? w.last_round : m.rounds;
    var span = hi != null ? (lo === hi ? 'round ' + lo : 'rounds ' + lo + '-' + hi) : 'rounds ' + lo + '+';
    var text = (w.weight === 1 ? '1.0' : w.weight.toFixed(2)) + ' in ' + span;
    lo = (w.last_round || 0) + 1;
    return text;
  });
  return 'Each pick is scored using <strong>position-relative value (PRV)</strong> -- how a player performed versus the '
    + 'average starter at their position that season (' + tops + '). That PRV is then compared against the cross-position '
    + 'average at that draft slot, capturing opportunity cost. A TE who outperforms the TE baseline by 5 points gets the '
    + 'same credit as a WR who outperforms the WR baseline by 5 points. <strong>Round weights</strong> apply: '
    + weights.join(', ') + '. Picks with fewer than ' + m.min_games + ' games played are injury-neutralized to zero surplus.';
}

/* "X has no 2020 grade since joining in 2021." for each graded manager who joined later */
function joinedNote() {
  var first = {};
  D.season_grades.forEach(function (g) {
    if (first[g.manager_key] == null || g.season < first[g.manager_key]) first[g.manager_key] = g.season;
  });
  return Object.keys(first).sort(byName).filter(function (k) { return first[k] > D.seasons[0]; }).map(function (k) {
    var missing = D.seasons.filter(function (s) { return s < first[k]; });
    return ' ' + esc(mgr.name(k)) + ' has no ' + rangeText(missing) + ' grade since joining in ' + first[k] + '.';
  }).join('');
}

/* ── sections ── */
function careerChart() {
  var data = D.career_grades.slice().reverse();
  var values = data.map(function (d) { return d.avg_surplus; });
  var min = Math.min.apply(null, values), max = Math.max.apply(null, values);
  new Chart(document.getElementById('chart-career').getContext('2d'), {
    type: 'bar',
    data: { labels: data.map(function (d) { return mgr.name(d.manager_key); }), datasets: [{
      data: values,
      backgroundColor: values.map(function (v) { return gradientColor(v, min, max, 0.72); }),
      borderColor: values.map(function (v) { return gradientColor(v, min, max, 1); }),
      borderWidth: 1.5, borderRadius: 3, barThickness: 10
    }] },
    options: {
      indexAxis: 'y', responsive: true, maintainAspectRatio: false,
      plugins: { legend: { display: false }, tooltip: { callbacks: { label: function (ctx) {
        var d = data[ctx.dataIndex], tot = r2(d.weighted_total);
        return ['Avg surplus: ' + (d.avg_surplus >= 0 ? '+' : '') + d.avg_surplus.toFixed(3) + ' per pick',
                'Total: ' + (tot >= 0 ? '+' : '') + tot.toFixed(1), d.total_picks + ' picks, ' + d.seasons + ' seasons'];
      } } } },
      scales: {
        x: { grid: gridStyle(), ticks: tickStyle(), title: { display: true, text: 'Avg Surplus Per Pick', color: C_MUTED, font: { size: 11 } } },
        y: { grid: { display: false }, ticks: Object.assign(tickStyle(), { font: { size: 12 }, color: '#3d3a38' }) }
      }
    },
    plugins: [{ id: 'zeroLine', afterDraw: function (chart) {
      var c = chart.ctx, x = chart.scales.x, y = chart.scales.y, x0 = x.getPixelForValue(0);
      c.save(); c.beginPath(); c.strokeStyle = 'rgba(138,132,128,0.5)'; c.lineWidth = 1.5; c.setLineDash([5, 4]);
      c.moveTo(x0, y.top); c.lineTo(x0, y.bottom); c.stroke(); c.restore();
    } }]
  });
}

function careerTable() {
  var avg = D.career_grades.map(function (d) { return d.avg_surplus; });
  var tot = D.career_grades.map(function (d) { return r2(d.weighted_total); });
  var aMin = Math.min.apply(null, avg), aMax = Math.max.apply(null, avg);
  var tMin = Math.min.apply(null, tot), tMax = Math.max.apply(null, tot);
  document.getElementById('career-tbody').innerHTML = D.career_grades.map(function (d) {
    return '<tr><td class="manager-rank">' + d.rank + '</td>'
      + '<td style="font-weight:600;color:var(--palm)">' + esc(mgr.name(d.manager_key)) + '</td>'
      + '<td>' + rggPill(d.avg_surplus, aMin, aMax, 3, true) + '</td>'
      + '<td>' + rggPill(r2(d.weighted_total), tMin, tMax, 1, true) + '</td>'
      + '<td>' + d.total_picks + '</td><td>' + d.seasons + '</td></tr>';
  }).join('');
}

function heatmap() {
  var grade = {}, tips = {};
  D.season_grades.forEach(function (g) { grade[g.season + '|' + g.manager_key] = r2(g.grade); });
  D.extremes.forEach(function (e) {
    if (e.season == null) return;
    var tip = function (p) { return p.player_name + ' Rd' + p.round + ' (' + signed2(p.surplus_weighted) + ')'; };
    tips[e.season + '|' + e.manager_key] = 'Best: ' + tip(e.best) + '\nWorst: ' + tip(e.worst);
  });
  var order = D.career_grades.map(function (d) { return d.manager_key; });
  var smm = {};
  D.seasons.forEach(function (yr) {
    var vals = order.map(function (k) { return grade[yr + '|' + k]; }).filter(function (v) { return v !== undefined; });
    smm[yr] = { min: Math.min.apply(null, vals), max: Math.max.apply(null, vals) };
  });
  var html = '<table class="heatmap-table"><thead><tr><th class="row-header">Manager</th>';
  D.seasons.forEach(function (yr) {
    var yc = sColor(yr);
    html += '<th style="color:' + yc + ';border-bottom-color:' + yc + ';">' + yr + '</th>';
  });
  html += '<th>Career Avg</th></tr></thead><tbody>';
  var avg = D.career_grades.map(function (d) { return d.avg_surplus; });
  var aMin = Math.min.apply(null, avg), aMax = Math.max.apply(null, avg);
  D.career_grades.forEach(function (c) {
    var k = c.manager_key;
    html += '<tr><td>' + esc(mgr.name(k)) + '</td>';
    D.seasons.forEach(function (yr) {
      var val = grade[yr + '|' + k];
      if (val === undefined) { html += '<td style="color:var(--muted);font-size:0.7rem;">N/A</td>'; return; }
      html += '<td style="background:' + gradientColor(val, smm[yr].min, smm[yr].max, 0.55) + ';color:' + (val >= 0 ? '#2a4a2a' : '#4a1a1a')
        + '" data-tip="' + esc(tips[yr + '|' + k] || '') + '">' + (val >= 0 ? '+' : '') + val.toFixed(1) + '</td>';
    });
    html += '<td>' + rggPill(c.avg_surplus, aMin, aMax, 3, true) + '</td></tr>';
  });
  document.getElementById('heatmap-container').innerHTML = html + '</tbody></table>';
}

function seasonPill(season) {
  return '<span class="season-pill" style="background:' + sColor(season) + ';">' + season + '</span>';
}

function highsAndLows() {
  var rows = D.extremes.filter(function (e) { return e.season == null; })
    .sort(function (a, b) { return byName(a.manager_key, b.manager_key); });
  document.getElementById('manager-bw-tbody').innerHTML = rows.map(function (e) {
    var b = e.best, w = e.worst;
    return '<tr>'
      + '<td style="font-weight:600;color:var(--palm)">' + esc(mgr.name(e.manager_key)) + '</td>'
      + '<td style="color:var(--palm);font-weight:600">' + esc(b.player_name) + '</td>'
      + '<td><span class="pos-badge pos-' + b.position.toLowerCase() + '">' + esc(b.position) + '</span></td>'
      + '<td>' + seasonPill(b.season) + '</td><td>' + b.round + '</td>'
      + '<td>' + rggPill(r2(b.surplus_weighted), POP_SURPLUS_MIN, POP_SURPLUS_MAX, 2, true) + '</td>'
      + '<td style="border-left:1px solid rgba(var(--accent-rgb),0.15);color:var(--palm);font-weight:600">' + esc(w.player_name) + '</td>'
      + '<td><span class="pos-badge pos-' + w.position.toLowerCase() + '">' + esc(w.position) + '</span></td>'
      + '<td>' + seasonPill(w.season) + '</td><td>' + w.round + '</td>'
      + '<td>' + rggPill(r2(w.surplus_weighted), POP_SURPLUS_MIN, POP_SURPLUS_MAX, 2, true) + '</td>'
      + '</tr>';
  }).join('');
}

function renderPickTable(tbodyId, rows) {
  document.getElementById(tbodyId).innerHTML = (rows || []).map(function (d) {
    return '<tr><td class="pick-rank">' + d.rank + '</td>'
      + '<td style="font-weight:600;color:var(--palm)">' + esc(d.player_name) + '</td>'
      + '<td><span class="pos-badge pos-' + d.position.toLowerCase() + '">' + esc(d.position) + '</span></td>'
      + '<td>' + d.round + '</td><td>' + d.overall_pick + '</td><td>' + seasonPill(d.season) + '</td>'
      + '<td style="color:var(--text-mid)">' + d.prv.toFixed(1) + '</td>'
      + '<td style="color:var(--muted)">' + d.expected_prv.toFixed(1) + '</td>'
      + '<td>' + rggPill(d.surplus_weighted, POP_SURPLUS_MIN, POP_SURPLUS_MAX, 2, true) + '</td>'
      + '<td>' + esc(mgr.name(d.manager_key)) + '</td></tr>';
  }).join('');
}

function pickFilter(rowId, tbodyId, all, bySeason) {
  var row = document.getElementById(rowId);
  row.insertAdjacentHTML('beforeend', D.seasons.map(function (s) {
    var c = seasonColor(cfg, s);
    return '<button class="season-btn year-swatch-btn"' + (c ? ' style="--swatch-color:' + esc(c) + ';"' : '') + ' data-season="' + s + '">' + s + '</button>';
  }).join(''));
  row.addEventListener('click', function (e) {
    var btn = e.target.closest('.season-btn');
    if (!btn) return;
    row.querySelectorAll('.season-btn').forEach(function (b) { b.classList.remove('active'); });
    btn.classList.add('active');
    renderPickTable(tbodyId, btn.dataset.season === 'all' ? all : bySeason[btn.dataset.season]);
  });
  renderPickTable(tbodyId, all);
}

function draw() {
  Chart.defaults.font.family = "'Outfit', sans-serif";
  Chart.defaults.font.size = 12;
  Chart.defaults.color = '#5a5550';
  POP_SURPLUS_MIN = D.scale ? r2(D.scale.min) : -1;
  POP_SURPLUS_MAX = D.scale ? r2(D.scale.max) : 1;
  document.querySelectorAll('.season-range').forEach(function (el) { el.textContent = rangeText(D.seasons); });
  if (D.method) document.getElementById('method-note').innerHTML = methodNote(D.method);
  document.getElementById('joined-note').innerHTML = joinedNote();
  careerChart();
  careerTable();
  heatmap();
  highsAndLows();
  pickFilter('best-filter', 'best-tbody', D.best_picks, D.season_best);
  pickFilter('worst-filter', 'worst-tbody', D.worst_picks, D.season_worst);
}

config().then(function (c) {
  cfg = c;
  mgr = managers(cfg);
  drawNav(cfg, 'surplus-value');
  drawSubnav(cfg, 'surplus-value');
  drawFooter(cfg);
  chapterRail();
  return load('data/v1/surplus-value.json');
}).then(function (d) {
  D = d;
  draw();
}).catch(function (err) {
  console.error(err);
  var el = document.getElementById('career-tbody');
  if (el) el.innerHTML = '<tr><td colspan="6"><div class="data-state data-state-error">This section could not be loaded.</div></td></tr>';
});
