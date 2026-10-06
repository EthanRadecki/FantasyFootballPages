/* Manager Profiles: one pill per visible manager, and a career dashboard for the one selected
   (?manager=<name or slug> selects one on load).

   Reads config.json, data/v1/index.json (the pills' records and the career ranks),
   data/v1/managers/<key>.json (everything on the dashboard), data/v1/weekly-rankings/ (the power
   ranking trajectory, when the league has weekly rankings) and data/v1/headshots.json (desktop only).
   Ported from the Stage A page with the same layout, charts and colors (decision 7.14); the numbers
   are the engine's. */

import { config, load, show } from '../core/data.js';
import { managers } from '../core/managers.js';
import { fixed } from '../core/format.js';
import { drawNav, drawFooter } from '../core/nav.js';
import { url, esc, params } from '../core/site.js';
import { seasonColor, seasonLabel, seasons as leagueSeasons, seasonInfo, rgb, rgba, posBadge, orderPositions,
         POSITION_SWATCH, POSITION_FILL } from '../core/theme.js';

var Chart = window.Chart;

// palette (matches site.css)
var C_ACCENT = '#9c949c';
var C_MUTED = '#8a8480';
var C_TEXT_MID = '#5a5550';

// Headshots (scatter bubbles, best-week podium) are desktop only, as on the Stage A page.
var IS_MOBILE = window.matchMedia('(max-width: 768px)').matches;

var S = {
  cfg: null, mgr: null, index: null, board: {}, headshots: null, models: {}, rankings: null,
  key: null, model: null, charts: {},
  fp: 'career',
  bsw: { pos: 'ALL', year: 'career' },
  fl: { pos: 'ALL', year: 'career', sort: 'total_points', dir: 'desc', page: 1 },
};
var FL_PAGE_SIZE = 20, FL_SCATTER_TOP_N = 50, FL_TIMELINE_TOP_N = 20, BSW_TABLE_ROWS = 10;

if (Chart) {
  Chart.defaults.font.family = "'Outfit', sans-serif";
  Chart.defaults.font.size = 12;
  Chart.defaults.color = C_TEXT_MID;
}

function destroyChart(id) {
  if (S.charts[id]) { S.charts[id].destroy(); delete S.charts[id]; }
}
function gridStyle() { return { color: 'rgba(156,148,156,0.15)', drawBorder: false }; }
function tickStyle() { return { color: C_MUTED }; }
function teams() { return S.index.visible_managers || S.mgr.visible.length; }

/* rank tiers: top 5 of 14 green, next 5 gold, the rest red (scaled to the league's size) */
function rankTier(rank, n) {
  n = n || teams();
  if (rank <= Math.round(n * 5 / 14)) return 'good';
  if (rank <= Math.round(n * 10 / 14)) return 'mid';
  return 'bad';
}
function tierColor(tier, alpha) {
  return { good: 'rgba(90,138,90,', mid: 'rgba(212,175,55,', bad: 'rgba(168,90,90,' }[tier] + alpha + ')';
}
function getRankColor(rank, total) {
  var norm = total > 1 ? (rank - 1) / (total - 1) : 0;
  if (norm <= 0.35) return 'background:rgba(90,138,90,0.15);color:#5a8a5a;';
  if (norm <= 0.65) return 'background:rgba(212,175,55,0.12);color:#a89030;';
  return 'background:rgba(168,90,90,0.15);color:#a85a5a;';
}
function pct(w, l, t) { var n = w + l + (t || 0); return n ? (w + (t || 0) / 2) / n : 0; }
function record(w, l, t) { return w + '-' + l + (t ? '-' + t : ''); }
function seasonPill(season) {
  var c = seasonColor(S.cfg, season) || 'var(--muted)';
  return '<span class="season-pill" style="background:' + c + ';">' + season + '</span>';
}
function headshot(playerId) {
  return S.headshots && playerId != null ? S.headshots[String(playerId)] || null : null;
}
function pageHref(id) {
  var p = S.cfg.pages.find(function (x) { return x.id === id; });
  return p ? url(p.href || p.path) : null;
}

// ---------------------------------------------------------------- pills and header

function drawPills() {
  var grid = document.getElementById('mgr-grid');
  var rows = {};
  (S.index.leaderboard || []).forEach(function (r) { rows[r.manager_key] = r; });
  var list = S.mgr.visible.slice().sort(function (a, b) { return a.short.localeCompare(b.short); });
  grid.innerHTML = list.map(function (m) {
    var accent = (m.colors && m.colors.light) || C_ACCENT, text = (m.colors && m.colors.dark) || accent;
    var r = rows[m.key];
    return '<div class="mgr-pill glass" data-key="' + esc(m.key) + '" style="--mgr-accent:' + accent +
      ';--mgr-accent-rgb:' + rgb(accent) + ';--mgr-accent-text:' + text + ';">' +
      (m.logo ? '<img class="mgr-logo" src="' + esc(url(m.logo)) + '" alt="" onerror="this.remove()">' : '') +
      '<div class="mgr-name">' + esc(m.name) + '</div>' +
      '<div class="mgr-quick">' + (r ? record(r.wins, r.losses, r.ties) + ' · ' + fixed(r.win_pct, 3) : '--') + '</div></div>';
  }).join('');
  grid.querySelectorAll('.mgr-pill').forEach(function (el) {
    el.addEventListener('click', function () { select(el.dataset.key, true); });
  });
}

function drawHeader(m) {
  var key = m.manager_key, c = m.career, row = S.board[key] || {}, ranks = row.ranks || {}, n = teams();
  document.getElementById('profile-name').textContent = S.mgr.name(key);
  document.getElementById('profile-subtitle').textContent = c.seasons + ' seasons (' + c.first_season + '-' + c.last_season + ')';
  var logo = document.getElementById('profile-logo');
  logo.src = S.mgr.logo(key) || '';
  logo.style.visibility = S.mgr.logo(key) ? '' : 'hidden';
  document.getElementById('profile-badges').innerHTML = (c.champion_seasons || []).map(function (y) {
    return '<span class="champ-badge">&#127942; ' + y + '</span>';
  }).join(' ');
  var set = function (id, v) { document.getElementById(id).textContent = v; };
  set('stat-wins', c.wins); set('stat-losses', c.losses); set('stat-winpct', fixed(c.win_pct, 3));
  set('stat-playoffs', c.playoffs); set('stat-champs', c.championships); set('stat-pfg', fixed(c.avg_pf_per_game, 1));
  [['rank-wins', ranks.wins], ['rank-losses', ranks.losses], ['rank-winpct', ranks.win_pct],
   ['rank-playoffs', ranks.playoffs], ['rank-pfg', ranks.avg_pf_per_game]].forEach(function (x) {
    var el = document.getElementById(x[0]);
    el.textContent = x[1] ? '#' + x[1] : '';
    el.style.cssText = x[1] ? getRankColor(x[1], n) : '';
  });
  ['best', 'worst'].forEach(function (side) {
    var r = m.rivals && m.rivals[side];
    document.getElementById('rival-' + side + '-name').textContent = r ? S.mgr.name(r.opponent_key) : 'N/A';
    document.getElementById('rival-' + side + '-record').textContent = r ?
      record(r.wins, r.losses, r.ties) + ' (' + (r.win_pct * 100).toFixed(1) + '%)' : '';
    var img = document.getElementById('rival-' + side + '-logo');
    var src = r ? S.mgr.logo(r.opponent_key) : null;
    img.src = src || '';
    img.style.visibility = src ? '' : 'hidden';
  });
  var tbody = document.querySelector('#season-table tbody');
  tbody.innerHTML = m.seasons.slice().sort(function (a, b) { return b.season - a.season; }).map(function (s) {
    var diff = s.point_diff_per_game || 0;
    var made = s.made_playoffs === true || s.made_playoffs === 1;
    var tier = s.pf_rank ? rankTier(s.pf_rank, (seasonInfo(S.cfg, s.season) || {}).team_count) : '';
    return '<tr><td class="val-bold">' + s.season + '</td><td>' + esc(s.team_name || '') + '</td>' +
      '<td>' + record(s.wins, s.losses, s.ties) + '</td>' +
      '<td class="val-bold">' + fixed(pct(s.wins, s.losses, s.ties), 3) + '</td>' +
      '<td class="' + (tier ? 'cell-' + tier : '') + '">' + fixed(s.pf_per_game, 1) + '</td>' +
      '<td>' + fixed(s.pa_per_game, 1) + '</td>' +
      '<td class="' + (diff >= 0 ? 'val-green' : 'val-red') + '">' + (diff >= 0 ? '+' : '') + diff.toFixed(1) + '</td>' +
      '<td>' + (s.draft_slot != null ? s.draft_slot : '') + '</td>' +
      '<td>' + (made ? '<span class="playoff-yes">&#10003;</span>' : '<span class="playoff-no">&#10007;</span>') + '</td></tr>';
  }).join('');
}

// ---------------------------------------------------------------- charts

function renderPerfChart(m) {
  destroyChart('perf');
  var seasons = m.seasons.slice().sort(function (a, b) { return a.season - b.season; });
  var avg = m.league_pf_per_game || {};
  var labels = seasons.map(function (s) { return s.season; });
  var pfg = seasons.map(function (s) { return +s.pf_per_game.toFixed(1); });
  var winPcts = seasons.map(function (s) { return +(pct(s.wins, s.losses, s.ties) * 100).toFixed(1); });
  var leagueAvg = seasons.map(function (s) { return avg[s.season] != null ? +avg[s.season].toFixed(1) : null; });
  var tiers = seasons.map(function (s) { return rankTier(s.pf_rank, (seasonInfo(S.cfg, s.season) || {}).team_count); });
  var yVals = pfg.concat(leagueAvg.filter(function (v) { return v !== null; }));
  var yMin = Math.max(0, Math.floor((Math.min.apply(null, yVals) - 10) / 10) * 10);
  S.charts.perf = new Chart(document.getElementById('chart-perf').getContext('2d'), {
    data: {
      labels: labels,
      datasets: [
        { type: 'bar', label: 'PF/G', data: pfg, yAxisID: 'yRight', order: 2, borderWidth: 1.5,
          backgroundColor: tiers.map(function (t) { return tierColor(t, 0.72); }),
          borderColor: tiers.map(function (t) { return tierColor(t, 1.0); }) },
        { type: 'line', label: 'Win %', data: winPcts, borderColor: C_ACCENT, backgroundColor: 'rgba(156,148,156,0.08)',
          borderWidth: 2.5, pointRadius: 5, pointBackgroundColor: C_ACCENT, pointBorderColor: '#fff',
          pointBorderWidth: 1.5, tension: 0.35, fill: false, yAxisID: 'yLeft', order: 1 },
        { type: 'line', label: 'League Avg PF/G', data: leagueAvg, borderColor: C_MUTED, borderWidth: 1.5,
          borderDash: [5, 4], pointRadius: 0, fill: false, yAxisID: 'yRight', order: 3 },
      ],
    },
    options: {
      responsive: true, maintainAspectRatio: false, interaction: { mode: 'index', intersect: false },
      plugins: {
        legend: { position: 'top', align: 'end', labels: { boxWidth: 12, padding: 16, color: C_TEXT_MID } },
        tooltip: { callbacks: { label: function (ctx) {
          return ctx.dataset.label === 'Win %' ? 'Win %: ' + ctx.parsed.y + '%' : ctx.dataset.label + ': ' + ctx.parsed.y;
        } } },
      },
      scales: {
        x: { grid: gridStyle(), ticks: tickStyle() },
        yLeft: { type: 'linear', position: 'left', min: 0, max: 100, grid: gridStyle(),
                 title: { display: true, text: 'Win %', color: C_MUTED, font: { size: 11 } },
                 ticks: Object.assign(tickStyle(), { callback: function (v) { return v + '%'; } }) },
        yRight: { type: 'linear', position: 'right', min: yMin, ticks: tickStyle(), grid: { drawOnChartArea: false },
                  title: { display: true, text: 'PF/G', color: C_MUTED, font: { size: 11 } } },
      },
    },
  });
}

/* schedule luck: actual wins vs expected wins (engine: a win above the week's median, half for a tie) */
function renderLuckChart(m) {
  destroyChart('luck');
  var rows = (m.schedule_luck || []).slice().sort(function (a, b) { return a.season - b.season; });
  if (!rows.length) return;
  var luck = rows.map(function (r) { return +(r.actual_wins - r.expected_wins).toFixed(1); });
  S.charts.luck = new Chart(document.getElementById('chart-luck').getContext('2d'), {
    type: 'bar',
    data: {
      labels: rows.map(function (r) { return r.season; }),
      datasets: [
        { label: 'Actual Wins', data: rows.map(function (r) { return r.actual_wins; }), borderWidth: 1.5, order: 1,
          backgroundColor: luck.map(function (v) { return v >= 0 ? 'rgba(90,138,90,0.72)' : 'rgba(168,90,90,0.72)'; }),
          borderColor: luck.map(function (v) { return v >= 0 ? 'rgba(90,138,90,1)' : 'rgba(168,90,90,1)'; }) },
        { label: 'Expected Wins', data: rows.map(function (r) { return +r.expected_wins.toFixed(1); }), order: 2,
          backgroundColor: 'rgba(156,148,156,0.18)', borderColor: 'rgba(156,148,156,0.6)', borderWidth: 1.5 },
      ],
    },
    options: {
      responsive: true, maintainAspectRatio: false, interaction: { mode: 'index', intersect: false },
      plugins: {
        legend: { position: 'top', align: 'end', labels: { boxWidth: 12, padding: 16, color: C_TEXT_MID } },
        tooltip: { callbacks: { afterBody: function (items) {
          var v = luck[items[0].dataIndex];
          return ['Luck: ' + (v > 0 ? '+' : '') + v + ' wins vs expected'];
        } } },
      },
      scales: {
        x: { grid: gridStyle(), ticks: tickStyle() },
        y: { grid: gridStyle(), ticks: Object.assign(tickStyle(), { stepSize: 1 }), min: 0,
             title: { display: true, text: 'Wins', color: C_MUTED, font: { size: 11 } } },
      },
    },
  });
}

function h2hColor(p, alpha) {
  if (p >= 0.6) return 'rgba(90,138,90,' + alpha + ')';
  if (p >= 0.4) return 'rgba(212,175,55,' + alpha + ')';
  return 'rgba(168,90,90,' + alpha + ')';
}

function renderH2HChart(m) {
  destroyChart('h2h');
  var rows = (m.head_to_head || []).filter(function (r) {
    var o = S.mgr.get(r.opponent_key);
    return !(o && o.hidden) && r.wins + r.losses + (r.ties || 0) > 0;
  }).map(function (r) { return Object.assign({ pct: pct(r.wins, r.losses, r.ties) }, r); });
  rows.sort(function (a, b) { return b.pct - a.pct; });
  var label = function (k) {
    var parts = S.mgr.name(k).replace(/ (Jr\.?|Sr\.?|II|III|IV)$/, '').split(' ');
    return parts[0] + ' ' + parts[parts.length - 1][0] + '.';
  };
  var pcts = rows.map(function (r) { return +(r.pct * 100).toFixed(1); });
  S.charts.h2h = new Chart(document.getElementById('chart-h2h').getContext('2d'), {
    type: 'bar',
    data: {
      labels: rows.map(function (r) { return label(r.opponent_key); }),
      datasets: [{ label: 'Win %', data: pcts, borderWidth: 1.5, borderRadius: 3,
                   backgroundColor: pcts.map(function (p) { return h2hColor(p / 100, 0.7); }),
                   borderColor: pcts.map(function (p) { return h2hColor(p / 100, 1.0); }) }],
    },
    options: {
      indexAxis: 'y', responsive: true, maintainAspectRatio: false,
      plugins: { legend: { display: false }, tooltip: { callbacks: { label: function (ctx) {
        var r = rows[ctx.dataIndex];
        return record(r.wins, r.losses, r.ties) + '  (' + pcts[ctx.dataIndex] + '%)';
      } } } },
      scales: {
        x: { grid: gridStyle(), min: 0, max: 100, ticks: Object.assign(tickStyle(), { callback: function (v) { return v + '%'; } }) },
        y: { grid: { display: false }, ticks: Object.assign(tickStyle(), { font: { size: 11 } }) },
      },
    },
  });
}

function percentile(sorted, p) {
  var idx = (p / 100) * (sorted.length - 1), lo = Math.floor(idx), hi = Math.ceil(idx);
  return lo === hi ? sorted[lo] : sorted[lo] + (sorted[hi] - sorted[lo]) * (idx - lo);
}

function renderDistChart(m) {
  destroyChart('dist');
  var scores = (m.weeks || []).filter(function (w) { return !w.excluded_from_ppg; }).map(function (w) { return w.points; });
  var range = S.index.score_range || { min: 50, max: 250 };
  var gMin = Math.floor(range.min / 5) * 5, gMax = Math.ceil(range.max / 5) * 5;
  var sorted = scores.slice().sort(function (a, b) { return a - b; });
  var p25 = sorted.length ? +percentile(sorted, 25).toFixed(1) : null;
  var p75 = sorted.length ? +percentile(sorted, 75).toFixed(1) : null;
  var avg = sorted.length ? +(sorted.reduce(function (s, v) { return s + v; }, 0) / sorted.length).toFixed(1) : null;
  var bins = [], labels = [];
  for (var b = gMin; b < gMax; b += 5) { bins.push(0); labels.push(b + '-' + (b + 5)); }
  scores.forEach(function (s) { var i = Math.floor((s - gMin) / 5); if (i >= 0 && i < bins.length) bins[i]++; });
  var at = function (score) { return (score - gMin) / 5; };
  var overlay = {
    id: 'distOverlay',
    beforeDatasetsDraw: function (chart) {
      if (p25 === null) return;
      var c = chart.ctx, x = chart.scales.x, y = chart.scales.y;
      var x25 = x.getPixelForValue(at(p25)), x75 = x.getPixelForValue(at(p75));
      c.save();
      c.fillStyle = 'rgba(168,90,90,0.10)'; c.fillRect(x.left, y.top, x25 - x.left, y.bottom - y.top);
      c.fillStyle = 'rgba(212,175,55,0.10)'; c.fillRect(x25, y.top, x75 - x25, y.bottom - y.top);
      c.fillStyle = 'rgba(90,138,90,0.10)'; c.fillRect(x75, y.top, x.right - x75, y.bottom - y.top);
      c.restore();
    },
    afterDatasetsDraw: function (chart) {
      if (avg === null) return;
      var c = chart.ctx, x = chart.scales.x.getPixelForValue(at(avg)), y = chart.scales.y;
      c.save(); c.strokeStyle = 'rgba(44,42,40,0.85)'; c.lineWidth = 2;
      c.beginPath(); c.moveTo(x, y.top); c.lineTo(x, y.bottom); c.stroke(); c.restore();
    },
  };
  var legend = [
    { label: 'Bottom 25%', data: [], backgroundColor: 'rgba(168,90,90,0.30)', borderColor: 'rgba(168,90,90,0)', borderWidth: 0 },
    { label: 'Middle 50%', data: [], backgroundColor: 'rgba(212,175,55,0.35)', borderColor: 'rgba(212,175,55,0)', borderWidth: 0 },
    { label: 'Top 25%', data: [], backgroundColor: 'rgba(90,138,90,0.30)', borderColor: 'rgba(90,138,90,0)', borderWidth: 0 },
    { label: 'Avg ' + avg, data: [], backgroundColor: 'rgba(44,42,40,0)', borderColor: 'rgba(44,42,40,0.85)', borderWidth: 2, type: 'line' },
  ];
  S.charts.dist = new Chart(document.getElementById('chart-dist').getContext('2d'), {
    type: 'bar',
    data: { labels: labels, datasets: [{ label: 'Games', data: bins, backgroundColor: 'rgba(156,148,156,0.5)',
      borderColor: 'rgba(156,148,156,0.85)', borderWidth: 1, borderRadius: 2 }].concat(legend) },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: {
        legend: { display: true, position: 'top', align: 'end', labels: { color: C_TEXT_MID, boxWidth: 12, padding: 14,
          font: { size: 11 }, filter: function (item) { return item.datasetIndex > 0; } } },
        tooltip: { callbacks: {
          title: function (items) { return items[0].label + ' pts'; },
          label: function (ctx) { return ctx.datasetIndex !== 0 ? null : ctx.parsed.y + ' game' + (ctx.parsed.y !== 1 ? 's' : ''); },
        } },
      },
      scales: {
        x: { grid: { display: false }, ticks: Object.assign(tickStyle(), { maxRotation: 45, font: { size: 10 },
          callback: function (val, idx) { return idx % 2 === 0 ? this.getLabelForValue(val) : ''; } }) },
        y: { grid: gridStyle(), ticks: Object.assign(tickStyle(), { stepSize: 1 }), min: 0,
             title: { display: true, text: 'Games', color: C_MUTED, font: { size: 11 } } },
      },
    },
    plugins: [overlay],
  });
}

/* one line per season, x = week: the regular season and the playoff games that count (winners bracket,
   no consolation games); filled marker = win, hollow = loss. The league average covers regular-season weeks;
   the team average is this manager's mean score per week over the seasons it played that week. */
function renderTrendsChart(m) {
  destroyChart('trends');
  var weeks = (m.weeks || []).filter(function (w) { return w.points > 0; });
  var playoffs = m.playoff_weeks || [];
  var last = playoffs.length ? 'final_week' : 'regular_season_weeks';
  var maxWeek = Math.max.apply(null, (S.cfg.seasons || []).map(function (s) { return s[last] || s.regular_season_weeks || 0; }).concat([1]));
  var bySeason = {}, leagueByWeek = {};
  weeks.forEach(function (w) {
    (bySeason[w.season] = bySeason[w.season] || {})[w.week] = { score: w.points, win: w.result === 'W' };
    if (w.league_avg != null) (leagueByWeek[w.week] = leagueByWeek[w.week] || []).push(w.league_avg);
  });
  playoffs.forEach(function (w) {
    (bySeason[w.season] = bySeason[w.season] || {})[w.week] = { score: w.points, win: w.result === 'W', round: w.round };
  });
  var labels = [];
  for (var i = 1; i <= maxWeek; i++) labels.push('Wk ' + i);
  var datasets = Object.keys(bySeason).map(Number).sort().map(function (yr) {
    var color = seasonColor(S.cfg, yr) || C_ACCENT;
    var data = [], bg = [], radius = [], border = [];
    for (var w = 1; w <= maxWeek; w++) {
      var e = bySeason[yr][w];
      if (e) { data.push(+e.score.toFixed(1)); bg.push(e.win ? color : '#d5cfc8'); radius.push(5); border.push(e.win ? 1.5 : 2); }
      else { data.push(null); bg.push(color); radius.push(4); border.push(1.5); }
    }
    return { label: String(yr), data: data, borderColor: color, backgroundColor: 'transparent', borderWidth: 2,
             pointRadius: radius, pointBackgroundColor: bg, pointBorderColor: color, pointBorderWidth: border,
             pointHoverRadius: 7, tension: 0.3, spanGaps: false, _outcomes: bySeason[yr] };
  });
  var avgLine = [];
  for (var wk = 1; wk <= maxWeek; wk++) {
    var a = leagueByWeek[wk];
    avgLine.push(a ? +(a.reduce(function (s, v) { return s + v; }, 0) / a.length).toFixed(1) : null);
  }
  datasets.push({ label: 'League Avg', data: avgLine, borderColor: 'rgba(138,132,128,0.55)', borderWidth: 1.5,
                  borderDash: [5, 4], backgroundColor: 'transparent', pointRadius: 0, pointHoverRadius: 0,
                  tension: 0.3, spanGaps: true, order: 99 });
  // the team's own average per week, over every season it played that week (playoff games that count included)
  var teamLine = [];
  for (var tw = 1; tw <= maxWeek; tw++) {
    var vals = Object.keys(bySeason).map(function (yr) { return bySeason[yr][tw]; }).filter(Boolean)
      .map(function (e) { return e.score; });
    teamLine.push(vals.length ? +(vals.reduce(function (a, v) { return a + v; }, 0) / vals.length).toFixed(1) : null);
  }
  var teamColor = S.mgr.color(m.manager_key, 'dark') || C_TEXT_MID;
  datasets.push({ label: 'Team Avg', data: teamLine, borderColor: rgba(teamColor, 0.85), borderWidth: 2.5,
                  borderDash: [2, 3], backgroundColor: 'transparent', pointRadius: 0, pointHoverRadius: 0,
                  tension: 0.3, spanGaps: true, order: 98 });
  S.charts.trends = new Chart(document.getElementById('chart-trends').getContext('2d'), {
    type: 'line',
    data: { labels: labels, datasets: datasets },
    options: {
      responsive: true, maintainAspectRatio: false, interaction: { mode: 'index', intersect: false },
      plugins: {
        legend: { position: 'top', align: 'end', labels: { boxWidth: 12, padding: 14, color: C_TEXT_MID,
          generateLabels: function (chart) {
            var items = Chart.defaults.plugins.legend.labels.generateLabels(chart);
            items.push({ text: 'Win', fillStyle: 'rgba(61,58,56,0.7)', strokeStyle: 'rgba(61,58,56,0.7)', lineWidth: 0,
                         pointStyle: 'circle', hidden: false, datasetIndex: -1 });
            items.push({ text: 'Loss', fillStyle: '#d5cfc8', strokeStyle: 'rgba(61,58,56,0.7)', lineWidth: 2,
                         pointStyle: 'circle', hidden: false, datasetIndex: -1 });
            return items;
          } } },
        tooltip: { callbacks: { label: function (ctx) {
          if (ctx.parsed.y === null) return null;
          if (ctx.dataset.label === 'League Avg' || ctx.dataset.label === 'Team Avg') return ctx.dataset.label + ': ' + ctx.parsed.y + ' pts';
          var e = ctx.dataset._outcomes && ctx.dataset._outcomes[ctx.dataIndex + 1];
          return ctx.dataset.label + ': ' + ctx.parsed.y + ' pts' + (e ? ' (' + (e.win ? 'W' : 'L') + (e.round ? ', ' + e.round : '') + ')' : '');
        } } },
      },
      scales: {
        x: { grid: gridStyle(), ticks: tickStyle() },
        y: { grid: gridStyle(), ticks: tickStyle(), title: { display: true, text: 'Points', color: C_MUTED, font: { size: 11 } } },
      },
    },
  });
}

/* every published weekly ranking: {manager key: {season: {week: rank}}}, loaded once */
function rankings() {
  if (S.rankings) return S.rankings;
  if (!S.cfg.pages.some(function (p) { return p.id === 'weekly-rankings'; })) return (S.rankings = Promise.resolve({}));
  S.rankings = load('data/v1/weekly-rankings/index.json').then(function (idx) {
    var files = [];
    (idx.seasons || []).forEach(function (s) { (s.weeks || []).forEach(function (w) { files.push(w.file); }); });
    return Promise.all(files.map(function (f) { return load('data/v1/weekly-rankings/' + f).catch(function () { return null; }); }));
  }).then(function (weeks) {
    var out = {};
    weeks.forEach(function (w) {
      if (!w) return;
      (w.teams || []).forEach(function (t) {
        ((out[t.manager_key] = out[t.manager_key] || {})[w.season] = out[t.manager_key][w.season] || {})[w.week] = t.rank;
      });
    });
    return out;
  }).catch(function (err) { console.error(err); return {}; });
  return S.rankings;
}

function renderRankChart(key, all) {
  destroyChart('rank');
  var bySeason = all[key];
  if (!bySeason || !Object.keys(bySeason).length) return;
  var seasons = Object.keys(bySeason).map(Number).sort();
  var maxWeek = 0, maxRank = 1;
  seasons.forEach(function (yr) { Object.keys(bySeason[yr]).forEach(function (wk) {
    maxWeek = Math.max(maxWeek, Number(wk)); maxRank = Math.max(maxRank, bySeason[yr][wk]);
  }); });
  var labels = [];
  for (var w = 1; w <= maxWeek; w++) labels.push('Wk ' + w);
  S.charts.rank = new Chart(document.getElementById('chart-rank').getContext('2d'), {
    type: 'line',
    data: { labels: labels, datasets: seasons.map(function (yr) {
      var color = seasonColor(S.cfg, yr) || C_ACCENT, data = [];
      for (var w = 1; w <= maxWeek; w++) data.push(bySeason[yr][w] !== undefined ? bySeason[yr][w] : null);
      return { label: String(yr), data: data, borderColor: color, backgroundColor: 'transparent', borderWidth: 2,
               pointRadius: 4, pointBackgroundColor: color, pointBorderColor: '#fff', pointBorderWidth: 1.5,
               pointHoverRadius: 7, tension: 0.3, spanGaps: false };
    }) },
    options: {
      responsive: true, maintainAspectRatio: false, interaction: { mode: 'index', intersect: false },
      plugins: {
        legend: { position: 'top', align: 'end', labels: { boxWidth: 12, padding: 14, color: C_TEXT_MID } },
        tooltip: { callbacks: { label: function (ctx) { return ctx.parsed.y === null ? null : ctx.dataset.label + ': #' + ctx.parsed.y; } } },
      },
      scales: {
        x: { grid: gridStyle(), ticks: tickStyle() },
        y: { grid: gridStyle(), reverse: true, min: 1, max: Math.max(maxRank, teams()),
             ticks: Object.assign(tickStyle(), { stepSize: 1, callback: function (v) { return '#' + v; } }),
             title: { display: true, text: 'Rank', color: C_MUTED, font: { size: 11 } } },
      },
    },
  });
}

// ---------------------------------------------------------------- draft fingerprint (10 measures)

var FP_META = {
  early_rb_pct: ['Early RB%', 'pct1'], early_wr_pct: ['Early WR%', 'pct1'], rb_wr_balance: ['RB/WR Balance', 'num1'],
  positional_diversity: ['Positional Diversity', 'num1'], same_position_run_rate: ['Run Rate', 'num1'],
  draft_conviction: ['Draft Conviction', 'num1'], qb_patience: ['QB Patience', 'num1'], te_patience: ['TE Patience', 'num1'],
  k_patience: ['K Patience', 'num1'], dst_patience: ['DST Patience', 'num1'],
};
function fpValue(dim, v) {
  if (v === null || v === undefined || isNaN(v)) return 'N/A';
  return (FP_META[dim] || [dim, 'num1'])[1] === 'pct1' ? v.toFixed(1) + '%' : v.toFixed(1);
}

function drawFingerprintFilters(m) {
  var row = document.getElementById('fp-filter-row');
  var dp = m.draft_profile;
  var years = dp ? (dp.seasons || []).map(function (s) { return s.season; }) : [];
  if (S.fp !== 'career' && years.indexOf(S.fp) === -1) S.fp = 'career';
  var link = pageHref('draft-fingerprints');
  row.innerHTML = '<span class="fp-filter-label">Season:</span>' +
    '<button class="fp-btn' + (S.fp === 'career' ? ' active' : '') + '" data-fp="career">Career</button>' +
    years.map(function (y) {
      return '<button class="fp-btn year-swatch-btn' + (S.fp === y ? ' active' : '') + '" data-fp="' + y +
        '" style="--swatch-color:' + (seasonColor(S.cfg, y) || 'var(--muted)') + ';">' + esc(seasonLabel(S.cfg, y)) + '</button>';
    }).join('') + (link ? '<a href="' + esc(link) + '" class="fp-link">Full Comparison &#8594;</a>' : '');
  row.querySelectorAll('[data-fp]').forEach(function (b) {
    b.addEventListener('click', function () {
      S.fp = b.dataset.fp === 'career' ? 'career' : Number(b.dataset.fp);
      row.querySelectorAll('[data-fp]').forEach(function (x) { x.classList.toggle('active', x === b); });
      renderFingerprintChart(S.model);
    });
  });
}

function renderFingerprintChart(m) {
  destroyChart('fingerprint');
  var dp = m.draft_profile;
  if (!dp) return;
  var period = S.fp === 'career' ? dp.career : (dp.seasons || []).find(function (s) { return s.season === S.fp; });
  if (!period) return;
  var dims = dp.dims || Object.keys(FP_META);
  var data = dims.map(function (d) { var v = (period.normalized || {})[d]; return v == null ? 50 : v; });
  var raw = dims.map(function (d) { var v = (period.raw || {})[d]; return v == null ? null : v; });
  var color = S.mgr.color(m.manager_key, 'light') || C_ACCENT;
  var labels = dims.map(function (d) { return (FP_META[d] || [d])[0]; });
  S.charts.fingerprint = new Chart(document.getElementById('chart-fingerprint').getContext('2d'), {
    type: 'radar',
    data: { labels: labels, datasets: [{ label: S.mgr.name(m.manager_key), data: data,
      backgroundColor: rgba(color, 0.18), borderColor: rgba(color, 0.95), borderWidth: 2.5,
      pointBackgroundColor: rgba(color, 0.95), pointBorderColor: '#fff', pointBorderWidth: 1.5, pointRadius: 5, pointHoverRadius: 7 }] },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: { legend: { display: false }, tooltip: { callbacks: {
        title: function (items) { return labels[items[0].dataIndex]; },
        label: function (ctx) { return fpValue(dims[ctx.dataIndex], raw[ctx.dataIndex]); },
      } } },
      scales: { r: { min: 0, max: 100, ticks: { stepSize: 25, display: false },
        grid: { color: 'rgba(156,148,156,0.18)' }, angleLines: { color: 'rgba(156,148,156,0.18)' },
        pointLabels: { color: '#6b5f50', font: { size: 11, family: "'Outfit', sans-serif", weight: '600' } } } },
    },
  });
}

// ---------------------------------------------------------------- draft board map

var HM_POS_COLORS = { RB: '#5a8a5a', WR: '#4a7fa8', QB: '#c08a3a', TE: '#9f8bc2' };

function surplusToColor(val, maxAbs) {
  if (maxAbs === 0) return 'rgba(156,148,156,0.25)';
  var p = Math.max(-1, Math.min(1, val / maxAbs)), r, g, b, t;
  if (p < 0) { t = -p; r = Math.round(245 + (192 - 245) * t); g = Math.round(240 + (58 - 240) * t); b = Math.round(232 + (58 - 232) * t); }
  else { t = p; r = Math.round(245 - (245 - 90) * t); g = Math.round(240 - (240 - 138) * t); b = Math.round(232 - (232 - 74) * t); }
  return 'rgba(' + r + ',' + g + ',' + b + ',0.85)';
}

function renderHeatmap(m) {
  var grid = document.getElementById('heatmap-grid');
  grid.innerHTML = '';
  var data = m.draft_board;
  if (!data || !data.board) return;
  var board = data.board, keys = Object.keys(board);
  var rounds = Math.max.apply(null, keys.map(function (k) { return Number(k.split('_')[0]); }).concat([1]));
  var slots = Math.max.apply(null, (S.cfg.seasons || []).map(function (s) { return s.team_count || 0; })
    .concat(keys.map(function (k) { return Number(k.split('_')[1]); })));
  grid.style.gridTemplateColumns = '36px repeat(' + slots + ', 1fr)';
  var maxAbs = Math.max(3, Math.max.apply(null, keys.map(function (k) { return Math.abs(board[k].avg_surplus); }).concat([0])));
  var html = '<div class="hm-header"></div>';
  for (var s = 1; s <= slots; s++) html += '<div class="hm-header">' + s + '</div>';
  for (var rd = 1; rd <= rounds; rd++) {
    html += '<div class="hm-row-label">' + rd + '</div>';
    for (var sl = 1; sl <= slots; sl++) {
      var c = board[rd + '_' + sl];
      if (!c) { html += '<div class="hm-cell empty"></div>'; continue; }
      var counts = {};
      c.picks.forEach(function (p) { counts[p.pos] = (counts[p.pos] || 0) + 1; });
      var top = Object.keys(counts).sort(function (a, b) { return counts[b] - counts[a]; })[0];
      html += '<div class="hm-cell" data-cell="' + rd + '_' + sl + '" style="background:' + surplusToColor(c.avg_surplus, maxAbs) +
        ';border-bottom:2px solid ' + (HM_POS_COLORS[top] || 'transparent') + ';">' + (c.n_seasons > 1 ? c.n_seasons : '') + '</div>';
    }
  }
  grid.innerHTML = html;
  var tt = document.getElementById('hm-tooltip');
  grid.querySelectorAll('[data-cell]').forEach(function (el) {
    var c = board[el.dataset.cell], rs = el.dataset.cell.split('_');
    el.addEventListener('mouseenter', function (e) {
      document.getElementById('hm-tt-title').textContent = 'Round ' + rs[0] + ', Slot ' + rs[1] + ' (' + c.n_seasons +
        ' season' + (c.n_seasons > 1 ? 's' : '') + '), avg: ' + (c.avg_surplus >= 0 ? '+' : '') + c.avg_surplus.toFixed(2);
      document.getElementById('hm-tt-picks').innerHTML = c.picks.map(function (p) {
        return '<div class="hm-tooltip-row"><span style="color:' + (HM_POS_COLORS[p.pos] || '#888') + ';font-weight:700">' + esc(p.pos) +
          '</span> ' + esc(p.player) + ' \'' + String(p.season).slice(2) + ' <span style="color:' + (p.surplus >= 0 ? '#5a8a5a' : '#c0623a') +
          ';font-weight:700">' + (p.surplus >= 0 ? '+' : '') + p.surplus.toFixed(2) + '</span></div>';
      }).join('');
      tt.classList.add('visible');
      place(e);
    });
    el.addEventListener('mousemove', place);
    el.addEventListener('mouseleave', function () { tt.classList.remove('visible'); });
  });
  function place(e) {
    var x = e.clientX + 12, y = e.clientY + 12;
    if (x + 230 > window.innerWidth) x = e.clientX - 240;
    if (y + 160 > window.innerHeight) y = e.clientY - 170;
    tt.style.left = x + 'px'; tt.style.top = y + 'px';
  }
}

// ---------------------------------------------------------------- filters (best weeks, franchise sections)

function drawFilterRows(selector, cls, state, positions, onChange) {
  document.querySelectorAll(selector).forEach(function (row) {
    var pos = row.dataset.filter === 'pos';
    var items = pos ? ['ALL'].concat(positions) : ['career'].concat(leagueSeasons(S.cfg));
    row.innerHTML = '<span class="fp-filter-label">' + (pos ? 'Position:' : 'Season:') + '</span>' + items.map(function (v) {
      var on = String(pos ? state.pos : state.year) === String(v);
      var sw = pos ? POSITION_SWATCH[v] : seasonColor(S.cfg, v);
      var label = pos ? (v === 'ALL' ? 'All' : v) : (v === 'career' ? 'Career' : seasonLabel(S.cfg, v));
      return '<button class="fp-btn ' + cls + '-' + (pos ? 'pos' : 'year') + '-btn' + (on ? ' active' : '') +
        (sw ? (pos ? ' pos-swatch-btn' : ' year-swatch-btn') + '" style="--swatch-color:' + sw + ';' : '') +
        '" data-v="' + esc(v) + '">' + esc(label) + '</button>';
    }).join('');
  });
  document.querySelectorAll(selector + ' button').forEach(function (b) {
    b.addEventListener('click', function () {
      var pos = b.closest('[data-filter]').dataset.filter === 'pos';
      var v = b.dataset.v;
      if (pos) state.pos = v; else state.year = v === 'career' ? 'career' : Number(v);
      document.querySelectorAll('.' + cls + '-' + (pos ? 'pos' : 'year') + '-btn').forEach(function (x) {
        x.classList.toggle('active', x.dataset.v === v);
      });
      onChange();
    });
  });
}

function renderBswTable() {
  var podium = document.getElementById('bsw-podium'), tbody = document.querySelector('#bsw-table tbody');
  var rows = (S.model.best_weeks || []).filter(function (r) {
    return (S.bsw.year === 'career' || r.season === S.bsw.year) && (S.bsw.pos === 'ALL' || r.position === S.bsw.pos);
  }).sort(function (a, b) { return b.points - a.points; }).slice(0, BSW_TABLE_ROWS);
  if (!rows.length) {
    podium.innerHTML = '';
    tbody.innerHTML = '<tr class="fl-empty-row"><td colspan="6">No players match this filter.</td></tr>';
    return;
  }
  podium.innerHTML = rows.slice(0, 3).map(function (p, i) {
    var img = '';
    if (!IS_MOBILE) {
      var src = headshot(p.player_id), colors = POSITION_FILL[p.position] || POSITION_FILL.K;
      img = src ? '<img class="bsw-podium-headshot" src="' + esc(src) + '" alt="' + esc(p.name) + '" style="border-color:' +
        colors.border + ';" loading="lazy" onerror="this.outerHTML=\'<div class=&quot;bsw-podium-placeholder&quot;></div>\';">'
        : '<div class="bsw-podium-placeholder"></div>';
    }
    return '<div class="bsw-podium-card rank-' + (i + 1) + '"><div class="bsw-podium-rank">#' + (i + 1) + '</div>' + img +
      '<div class="bsw-podium-player">' + esc(p.name) + '</div>' + posBadge(p.position) +
      '<div class="bsw-podium-points">' + p.points.toFixed(1) + '</div>' +
      '<div class="bsw-podium-meta"><span>Week ' + p.week + '</span>' + seasonPill(p.season) + '</div></div>';
  }).join('');
  tbody.innerHTML = rows.slice(3).map(function (p, i) {
    return '<tr><td>' + (i + 4) + '</td><td style="font-weight:700;color:var(--palm);">' + esc(p.name) + '</td><td>' +
      posBadge(p.position) + '</td><td>' + p.points.toFixed(1) + '</td><td>Week ' + p.week + '</td><td>' + seasonPill(p.season) + '</td></tr>';
  }).join('');
}

function flColorGradient(value, min, max) {
  if (max === min) return 'transparent';
  var mid = (min + max) / 2, r, g, b, t;
  if (value <= mid) {
    t = Math.max(0, Math.min(1, (mid - value) / ((mid - min) || 1)));
    r = Math.round(245 + (192 - 245) * t); g = Math.round(240 + (98 - 240) * t); b = Math.round(232 + (58 - 232) * t);
  } else {
    t = Math.max(0, Math.min(1, (value - mid) / ((max - mid) || 1)));
    r = Math.round(245 + (90 - 245) * t); g = Math.round(240 + (138 - 240) * t); b = Math.round(232 + (90 - 232) * t);
  }
  return 'rgba(' + r + ',' + g + ',' + b + ',0.32)';
}

/* franchise leaders: player totals over the filtered seasons (started weeks' points; weeks rostered counts all) */
function leaders() {
  var by = {};
  (S.model.franchise_leaders || []).forEach(function (r) {
    if (S.fl.year !== 'career' && r.season !== S.fl.year) return;
    if (S.fl.pos !== 'ALL' && r.position !== S.fl.pos) return;
    var k = r.player_id != null ? r.player_id : r.name;
    var p = by[k] = by[k] || { player: r.name, player_id: r.player_id, position: r.position, weeks_rostered: 0, games_played: 0, total_points: 0 };
    p.weeks_rostered += r.weeks_rostered; p.games_played += r.games_played; p.total_points += r.total_points;
  });
  return Object.keys(by).map(function (k) {
    var p = by[k]; p.ppg = p.games_played > 0 ? p.total_points / p.games_played : 0; return p;
  });
}

function renderFranchise() {
  var list = leaders();
  list.sort(function (a, b) { return S.fl.dir === 'desc' ? b[S.fl.sort] - a[S.fl.sort] : a[S.fl.sort] - b[S.fl.sort]; });
  var byPoints = list.slice().sort(function (a, b) { return b.total_points - a.total_points; });
  renderScatter(byPoints.slice(0, FL_SCATTER_TOP_N));
  renderTimeline(byPoints.slice(0, FL_TIMELINE_TOP_N));
  var tbody = document.querySelector('#franchise-leaders-table tbody'), pag = document.getElementById('fl-pagination');
  if (!list.length) {
    tbody.innerHTML = '<tr class="fl-empty-row"><td colspan="7">No players match this filter.</td></tr>';
    pag.style.display = 'none';
    return;
  }
  var pages = Math.max(1, Math.ceil(list.length / FL_PAGE_SIZE));
  S.fl.page = Math.min(Math.max(1, S.fl.page), pages);
  var start = (S.fl.page - 1) * FL_PAGE_SIZE;
  var range = function (k) { var v = list.map(function (p) { return p[k]; }); return [Math.min.apply(null, v), Math.max.apply(null, v)]; };
  var rT = range('total_points'), rP = range('ppg'), rG = range('games_played'), rW = range('weeks_rostered');
  tbody.innerHTML = list.slice(start, start + FL_PAGE_SIZE).map(function (p, i) {
    var cell = function (v, r, text) { return '<td class="fl-grad-cell" style="background:' + flColorGradient(v, r[0], r[1]) + ';">' + text + '</td>'; };
    return '<tr><td>' + (start + i + 1) + '</td><td style="font-weight:700;color:var(--palm);">' + esc(p.player) + '</td><td>' +
      posBadge(p.position) + '</td>' + cell(p.total_points, rT, p.total_points.toFixed(1)) + cell(p.ppg, rP, p.ppg.toFixed(1)) +
      cell(p.games_played, rG, p.games_played) + cell(p.weeks_rostered, rW, p.weeks_rostered) + '</tr>';
  }).join('');
  pag.style.display = 'flex';
  document.getElementById('fl-page-info').textContent = 'Page ' + S.fl.page + ' of ' + pages + ' (' + list.length + ' players)';
  document.getElementById('fl-prev-btn').disabled = S.fl.page <= 1;
  document.getElementById('fl-next-btn').disabled = S.fl.page >= pages;
}

var IMG_CACHE = {};
function headshotImg(src) {
  if (!src) return null;
  var c = IMG_CACHE[src];
  if (c) return c.complete && c.naturalWidth > 0 ? c : null;
  var img = new Image();
  img.onload = function () {
    var chart = S.charts.flScatter;
    if (chart && chart.canvas && chart.canvas.isConnected) { try { chart.draw(); } catch (e) { /* replaced chart */ } }
  };
  img.src = src;
  IMG_CACHE[src] = img;
  return null;
}

function renderScatter(items) {
  destroyChart('flScatter');
  if (!items.length) return;
  var maxPts = Math.max.apply(null, items.map(function (p) { return p.total_points; }));
  var radius = function (pts) { return 4 + (maxPts > 0 ? (pts / maxPts) * 22 : 0); };
  var datasets = orderPositions(items.map(function (p) { return p.position; })).map(function (pos) {
    var colors = POSITION_FILL[pos] || POSITION_FILL.K;
    return { label: pos, borderWidth: 1.5, backgroundColor: colors.fill, borderColor: colors.border,
      data: items.filter(function (p) { return p.position === pos; }).map(function (p) {
        return { x: p.games_played, y: p.ppg, r: radius(p.total_points), player: p.player, pts: p.total_points, img: headshot(p.player_id) };
      }) };
  });
  var faces = {
    id: 'flHeadshots',
    afterDatasetsDraw: function (chart) {
      var ctx = chart.ctx;
      chart.data.datasets.forEach(function (ds, di) {
        var meta = chart.getDatasetMeta(di);
        if (!meta || meta.hidden) return;
        meta.data.forEach(function (pt, i) {
          var raw = ds.data[i], img = raw && headshotImg(raw.img);
          if (!img) return;
          var x = pt.x, y = pt.y, r = raw.r;
          ctx.save(); ctx.beginPath(); ctx.arc(x, y, Math.max(r - 1, 0), 0, Math.PI * 2); ctx.closePath(); ctx.clip();
          ctx.drawImage(img, x - r, y - r, r * 2, r * 2); ctx.restore();
          ctx.save(); ctx.beginPath(); ctx.arc(x, y, Math.max(r - 0.75, 0), 0, Math.PI * 2);
          ctx.lineWidth = 1.5; ctx.strokeStyle = ds.borderColor; ctx.stroke(); ctx.restore();
        });
      });
    },
  };
  S.charts.flScatter = new Chart(document.getElementById('fl-scatter-chart').getContext('2d'), {
    type: 'bubble',
    data: { datasets: datasets },
    plugins: IS_MOBILE ? [] : [faces],
    options: {
      responsive: true, maintainAspectRatio: false, resizeDelay: 200, animation: false, layout: { padding: 20 },
      scales: {
        x: { title: { display: true, text: 'Games started', color: C_MUTED }, grid: gridStyle(), ticks: tickStyle() },
        y: { title: { display: true, text: 'Points per game', color: C_MUTED }, grid: gridStyle(), ticks: tickStyle() },
      },
      plugins: { legend: { display: false }, tooltip: { callbacks: { label: function (ctx) {
        var d = ctx.raw;
        return d.player + ' - ' + d.pts.toFixed(1) + ' pts, ' + d.y.toFixed(1) + ' ppg, ' + d.x + ' games started';
      } } } },
    },
  });
}

var TL_TICKS = [1, 5, 9, 13, 17];

function renderTimeline(items) {
  var wrap = document.getElementById('fl-timeline-wrap');
  wrap.innerHTML = '';
  if (!items.length) return;
  var stints = {};
  (S.model.roster_stints || []).forEach(function (s) {
    var k = s.player_id != null ? s.player_id : s.name;
    (stints[k] = stints[k] || []).push(s);
  });
  var seasons = S.fl.year === 'career' ? leagueSeasons(S.cfg) : [S.fl.year];
  var span = Math.max.apply(null, (S.cfg.seasons || []).map(function (s) { return s.final_week || 17; }).concat([17]));
  var cols = '130px repeat(' + seasons.length + ', 1fr)';
  var at = function (w) { return ((w - 1) / span) * 100; };
  var html = '<div class="fl-tl-scroll"><div style="min-width:' + (130 + seasons.length * 80) + 'px">' +
    '<div class="fl-tl-header" style="grid-template-columns:' + cols + '"><div class="fl-tl-label"></div>' +
    seasons.map(function (s) {
      return '<div><div style="text-align:center;">' + seasonPill(s) + '</div><div class="fl-tl-ticks">' +
        TL_TICKS.filter(function (w) { return w <= span; }).map(function (w, i, a) {
          return '<span class="fl-tl-tick' + (i === 0 ? ' fl-tl-tick-first' : i === a.length - 1 ? ' fl-tl-tick-last' : '') +
            '" style="left:' + at(w) + '%;">' + w + '</span>';
        }).join('') + '</div></div>';
    }).join('') + '</div>';
  items.forEach(function (item, idx) {
    var colors = POSITION_FILL[item.position] || POSITION_FILL.K;
    var mine = (stints[item.player_id != null ? item.player_id : item.player] || []);
    html += '<div class="fl-tl-row' + (idx % 2 === 1 ? ' fl-tl-alt' : '') + '" style="grid-template-columns:' + cols + '">' +
      '<div class="fl-tl-label">' + posBadge(item.position) + '<span>' + esc(item.player) + '</span></div>' +
      seasons.map(function (s) {
        var info = seasonInfo(S.cfg, s) || {};
        var cell = TL_TICKS.filter(function (w) { return w > 1 && w <= span; }).map(function (w) {
          return '<div class="fl-tl-gridline" style="left:' + at(w) + '%"></div>';
        }).join('') + '<div class="fl-tl-playoff-line" style="left:' + at((info.regular_season_weeks || 14) + 1) + '%"></div>';
        mine.filter(function (st) { return st.season === s; }).forEach(function (st) {
          cell += '<div class="fl-tl-bar" style="left:' + at(st.start) + '%;width:' + ((st.end - st.start + 1) / span) * 100 +
            '%;background:' + colors.fill.replace(/[\d.]+\)$/, '0.25)') + '"></div>';
          var started = (st.started || []).slice().sort(function (a, b) { return a - b; });
          var runStart = null, prev = null;
          started.concat([null]).forEach(function (w) {
            if (w !== null && (prev === null || w === prev + 1)) { if (runStart === null) runStart = w; }
            else {
              if (runStart !== null) {
                cell += '<div class="fl-tl-bar" style="left:' + at(runStart) + '%;width:' + ((prev - runStart + 1) / span) * 100 +
                  '%;background:' + colors.border + '"></div>';
              }
              runStart = w;
            }
            prev = w;
          });
        });
        return '<div class="fl-tl-track">' + cell + '</div>';
      }).join('') + '</div>';
  });
  wrap.innerHTML = html + '</div></div>';
}

// ---------------------------------------------------------------- selection

function renderAll(m) {
  drawHeader(m);
  renderPerfChart(m);
  renderLuckChart(m);
  renderH2HChart(m);
  renderDistChart(m);
  renderTrendsChart(m);
  destroyChart('rank');
  rankings().then(function (all) { if (S.key === m.manager_key) renderRankChart(m.manager_key, all); });
  drawFingerprintFilters(m);
  renderFingerprintChart(m);
  renderHeatmap(m);
  var positions = orderPositions((m.franchise_leaders || []).map(function (r) { return r.position; })
    .concat((m.best_weeks || []).map(function (r) { return r.position; })));
  if (S.bsw.pos !== 'ALL' && positions.indexOf(S.bsw.pos) === -1) S.bsw.pos = 'ALL';
  if (S.fl.pos !== 'ALL' && positions.indexOf(S.fl.pos) === -1) S.fl.pos = 'ALL';
  drawFilterRows('.bsw-filter-row', 'bsw', S.bsw, positions, renderBswTable);
  drawFilterRows('.fl-filter-row', 'fl', S.fl, positions, function () { S.fl.page = 1; renderFranchise(); });
  renderBswTable();
  S.fl.page = 1;
  renderFranchise();
}

function select(key, scroll) {
  S.key = key;
  document.querySelectorAll('.mgr-pill').forEach(function (p) { p.classList.toggle('active', p.dataset.key === key); });
  document.getElementById('select-prompt').style.display = 'none';
  var profile = document.getElementById('manager-profile');
  profile.classList.add('visible');
  var m = S.mgr.get(key) || {};
  var accent = (m.colors && m.colors.light) || C_ACCENT;
  profile.style.setProperty('--mgr-accent', accent);
  profile.style.setProperty('--mgr-accent-rgb', rgb(accent));
  profile.style.setProperty('--mgr-accent-text', (m.colors && m.colors.dark) || accent);
  if (scroll) profile.scrollIntoView({ behavior: 'smooth', block: 'start' });
  var model = S.models[key] || (S.models[key] = load('data/v1/managers/' + key + '.json'));
  model.then(function (data) {
    if (S.key !== key) return;
    S.model = data;
    // the profile was just made visible: let layout settle before Chart.js measures the canvases
    requestAnimationFrame(function () { requestAnimationFrame(function () { renderAll(data); }); });
  }).catch(function (err) {
    console.error(err);
    show(document.getElementById('profile-subtitle'), 'error', 'This manager could not be loaded.');
  });
}

function wire() {
  document.getElementById('fl-prev-btn').addEventListener('click', function () { S.fl.page--; renderFranchise(); });
  document.getElementById('fl-next-btn').addEventListener('click', function () { S.fl.page++; renderFranchise(); });
  document.querySelectorAll('.fl-sortable').forEach(function (th) {
    th.addEventListener('click', function () {
      var k = th.dataset.sortKey;
      if (S.fl.sort === k) S.fl.dir = S.fl.dir === 'desc' ? 'asc' : 'desc';
      else { S.fl.sort = k; S.fl.dir = 'desc'; }
      S.fl.page = 1;
      document.querySelectorAll('.fl-sortable').forEach(function (x) {
        x.classList.remove('sort-asc', 'sort-desc');
        if (x.dataset.sortKey === S.fl.sort) x.classList.add(S.fl.dir === 'asc' ? 'sort-asc' : 'sort-desc');
      });
      if (S.model) renderFranchise();
    });
  });
}

config().then(function (cfg) {
  S.cfg = cfg;
  S.mgr = managers(cfg);
  drawNav(cfg, 'managers');
  drawFooter(cfg);
  wire();
  if (!IS_MOBILE) {
    load('data/v1/headshots.json').then(function (h) {
      S.headshots = h.players || {};
      if (S.model) { renderBswTable(); renderFranchise(); }
    }).catch(function () { S.headshots = {}; });
  }
  return load('data/v1/index.json').then(function (index) {
    S.index = index;
    (index.leaderboard || []).forEach(function (r) { S.board[r.manager_key] = r; });
    drawPills();
    var wanted = params().manager;
    var m = wanted && S.mgr.find(wanted);
    if (m && !m.hidden) select(m.key, true);
  });
}).catch(function (err) {
  console.error(err);
  show(document.getElementById('mgr-grid'), 'error', 'The managers could not be loaded.');
});
