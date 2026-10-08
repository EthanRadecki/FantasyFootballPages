/* Draft Analysis: results by draft slot, who drafted from each slot, hit rates by round, tier and
   position, the late-round steals, and a preview of the career surplus rankings.

   Reads config.json and data/v1/draft-analysis.json (schema "draft-analysis"). Ported from the Stage A
   page with the same layout (decision 7.14); the typed slot table and hit-rate cards are drawn from
   the data with the rules the Stage A build used for them (engine/publish/pages/draft_analysis.py):
     slot table   playoff %, champ % and PF/G to 1 place, dominance and expected to 2, over/under to
                  3 then 2 (half away from zero) with an arrow; playoff % and PF/G colored by z-score
                  among the slots shown (good above +0.2, bad below -1.0), champ % good above 0,
                  the rest by sign
   What was written into the page now comes from the league and the data:
     slots        the slots with results (2+ seasons, decision 7.4); the who-drafted grid lists every
                  slot used, slot 15 of 2020 included, and marks the live season
     tiers        the hit-rate tiers' rounds (labels, card titles, chart dividers)
     notes        hit thresholds, games floors, window and starter baselines from the model's
                  `method`; seasons and the position example from the data
     managers     names and colors from config.json (hidden managers in the muted color) */

import { config, load } from '../core/data.js';
import { managers } from '../core/managers.js';
import { drawNav, drawFooter, drawSubnav } from '../core/nav.js';
import { url, esc } from '../core/site.js';
import { seasonColor } from '../core/theme.js';
import { count } from '../core/format.js';
import { chapterRail } from '../components/chapter-rail.js';

var Chart = window.Chart;
var C_MUTED = '#8a8480';
var HIDDEN_COLOR = '#8a8480';
var GOOD_Z = 0.2, BAD_Z = -1.0;
var cfg, mgr, D;

/* ── colors ── */
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
function bone(p, alpha) {
  var r, g, b, t;
  if (p <= 0.5) { t = p / 0.5; r = Math.round(192 + (245 - 192) * t); g = Math.round(58 + (240 - 58) * t); b = Math.round(58 + (232 - 58) * t); }
  else { t = (p - 0.5) / 0.5; r = Math.round(245 + (74 - 245) * t); g = Math.round(240 + (168 - 240) * t); b = Math.round(232 + (58 - 232) * t); }
  return 'rgba(' + r + ',' + g + ',' + b + ',' + alpha + ')';
}
/* 0% red, 50% bone, 100% green */
function absoluteGradient(pct, alpha) { return bone(Math.max(0, Math.min(100, pct)) / 100, alpha !== undefined ? alpha : 0.72); }
/* relative to the series */
function gradientColor(val, min, max, alpha) { return bone(max !== min ? (val - min) / (max - min) : 0.5, alpha !== undefined ? alpha : 0.72); }

/* ── numbers as the page shows them ── */
function roundN(v, n) { return Number(Number(v).toFixed(n)); }
/* round to d+1 places, then half away from zero to d, signed ("+0.26", "-0.66") */
function signedStr(v, d) {
  var s = Math.abs(roundN(v, d + 1)).toFixed(d + 1).replace('.', '');
  var n = Math.floor(Number(s) / 10) + (Number(s.slice(-1)) >= 5 ? 1 : 0);
  var text = (n / Math.pow(10, d)).toFixed(d);
  return (v < 0 && n !== 0 ? '-' : '+') + text;
}
function band(values) {
  var mean = values.reduce(function (a, b) { return a + b; }, 0) / values.length;
  var sd = Math.sqrt(values.reduce(function (a, b) { return a + (b - mean) * (b - mean); }, 0) / values.length);
  return values.map(function (v) { var z = sd ? (v - mean) / sd : 0; return z > GOOD_Z ? 'good' : z < BAD_Z ? 'bad' : 'mid'; });
}
function rangeText(list) { return !list.length ? '' : list.length === 1 ? String(list[0]) : list[0] + '-' + list[list.length - 1]; }
function nameOf(key) { return mgr.name(key); }
function colorOf(key) { var m = mgr.get(key); return m && m.hidden ? HIDDEN_COLOR : (mgr.color(key) || 'var(--palm)'); }
function pageHref(id) {
  var p = cfg.pages.find(function (x) { return x.id === id; });
  return p ? url(p.href || p.path) : null;
}

/* ── tiers ── */
function tierLabel(t) {
  var hi = t.last_round == null ? '+' : '-' + t.last_round;
  return t.tier + ' Rounds (' + t.first_round + hi + ')';
}
function tierDividerPlugin(id) {
  var cuts = D.hit_rate_tiers.filter(function (t) { return t.last_round != null; }).map(function (t) { return t.last_round - 0.5; });
  return { id: id, afterDraw: function (chart) {
    var c = chart.ctx, x = chart.scales.x, y = chart.scales.y;
    cuts.forEach(function (idx) {
      var px = x.getPixelForValue(idx);
      c.save(); c.beginPath(); c.strokeStyle = 'rgba(138,132,128,0.4)'; c.lineWidth = 1; c.setLineDash([4, 3]);
      c.moveTo(px, y.top); c.lineTo(px, y.bottom); c.stroke(); c.restore();
    });
  } };
}

/* ── Draft Slot Analysis ── */
var SLOT_DATA = {};   // slot -> [[name, season]]

function slotCharts(rows) {
  var slots = rows.map(function (r) { return r.slot; });
  function chart(id, values, label, yScale, zero) {
    var min = Math.min.apply(null, values), max = Math.max.apply(null, values);
    new Chart(document.getElementById(id).getContext('2d'), {
      type: 'bar',
      data: { labels: slots, datasets: [{ data: values,
        backgroundColor: values.map(function (v) { return gradientColor(v, min, max, 0.72); }),
        borderColor: values.map(function (v) { return gradientColor(v, min, max, 1); }),
        borderWidth: 1.5, borderRadius: 3 }] },
      options: { responsive: true, plugins: { legend: { display: false }, tooltip: { callbacks: {
        title: function (i) { return 'Slot ' + i[0].label; },
        label: function (ctx) {
          var lines = [label(ctx), ''];
          (SLOT_DATA[slots[ctx.dataIndex]] || []).forEach(function (e) { lines.push(e[0] + ' (' + e[1] + ')'); });
          return lines;
        }
      } } }, scales: { x: { grid: gridStyle(), ticks: tickStyle(), title: { display: true, text: 'Draft Slot', color: C_MUTED, font: { size: 11 } } }, y: yScale } },
      plugins: zero ? [{ id: 'zeroLine', afterDraw: function (ch) {
        var c = ch.ctx, y = ch.scales.y, x = ch.scales.x, y0 = y.getPixelForValue(0);
        c.save(); c.beginPath(); c.strokeStyle = 'rgba(138,132,128,0.5)'; c.lineWidth = 1.5; c.setLineDash([5, 4]);
        c.moveTo(x.left, y0); c.lineTo(x.right, y0); c.stroke(); c.restore();
      } }] : []
    });
  }
  chart('chart-playoff-rate', rows.map(function (r) { return r.pp; }), function (ctx) { return 'Playoff Rate: ' + ctx.parsed.y + '%'; },
    { grid: gridStyle(), ticks: Object.assign(tickStyle(), { callback: function (v) { return v + '%'; } }), title: { display: true, text: 'Playoff Rate', color: C_MUTED, font: { size: 11 } }, min: 0, max: 110 });
  chart('chart-adj-perf', rows.map(function (r) { return r.ou3; }), function (ctx) {
    var val = ctx.parsed.y; return 'Over/Under: ' + (val >= 0 ? '+' : '') + val.toFixed(3);
  }, { grid: gridStyle(), ticks: tickStyle(), title: { display: true, text: 'Dominance Over/Under Expected', color: C_MUTED, font: { size: 11 } } }, true);
}

function slotTable(rows) {
  var pl = band(rows.map(function (r) { return r.pp; })), pf = band(rows.map(function (r) { return r.pf; }));
  document.getElementById('slot-tbody').innerHTML = rows.map(function (r, i) {
    var ou = Number(signedStr(r.ou3, 2));
    return '<tr><td class="val-bold">' + r.slot + '</td><td>' + r.seasons + '</td>'
      + '<td class="cell-' + pl[i] + ' val-bold">' + r.pp.toFixed(1) + '%</td>'
      + '<td class="cell-' + (r.cp > 0 ? 'good' : 'bad') + ' val-bold">' + r.cp.toFixed(1) + '%</td>'
      + '<td class="cell-' + pf[i] + '">' + r.pf.toFixed(1) + '</td>'
      + '<td class="' + (r.dom > 0 ? 'cell-good val-green' : 'cell-bad val-red') + '">' + signedStr(r.dom, 2) + '</td>'
      + '<td class="' + (r.exp > 0 ? 'val-green' : 'val-red') + '">' + signedStr(r.exp, 2) + '</td>'
      + '<td class="' + (ou > 0 ? 'cell-good val-green' : 'cell-bad val-red') + '">' + signedStr(ou, 2) + ' ' + (ou > 0 ? '&#9650;' : '&#9660;') + '</td></tr>';
  }).join('');
}

function slotGrid() {
  var years = Array.from(new Set(D.slot_managers.map(function (s) { return s.season; }))).sort(function (a, b) { return a - b; });
  var live = D.slot_managers.filter(function (s) { return s.live; }).map(function (s) { return s.season; });
  var maxSlot = Math.max.apply(null, D.slot_managers.map(function (s) { return s.draft_slot; }));
  var html = '<table class="slot-table"><thead><tr><th class="row-header">Slot</th>';
  years.forEach(function (yr) {
    var yc = seasonColor(cfg, yr) || 'var(--muted)', isLive = live.indexOf(yr) !== -1;
    html += '<th style="color:' + yc + ';border-bottom-color:' + yc + ';' + (isLive ? 'border-left:2px dashed rgba(var(--accent-rgb),0.3);' : '') + '">' + yr
      + (isLive ? '<div style="font-size:0.55rem;font-weight:700;letter-spacing:0.06em;color:var(--muted);margin-top:0.15rem;">LIVE</div>' : '')
      + '</th>';
  });
  html += '</tr></thead><tbody>';
  for (var slot = 1; slot <= maxSlot; slot++) {
    var entries = D.slot_managers.filter(function (s) { return s.draft_slot === slot; });
    var byYear = {}, counts = {};
    entries.forEach(function (e) { byYear[e.season] = e.manager_key; counts[e.manager_key] = (counts[e.manager_key] || 0) + 1; });
    html += '<tr><td class="row-header">Slot ' + slot + '</td>';
    years.forEach(function (yr) {
      var key = byYear[yr], isLive = live.indexOf(yr) !== -1;
      var border = isLive ? 'border-left:2px dashed rgba(var(--accent-rgb),0.3);' : '';
      if (!key) { html += '<td style="color:var(--muted);font-size:0.7rem;' + border + '">&ndash;</td>'; return; }
      var mc = colorOf(key), repeat = counts[key] > 1;
      var tag = repeat ? '<span class="slot-repeat-tag" style="background:' + mc + ';">&times;' + counts[key] + '</span>' : '';
      html += '<td class="' + (repeat ? 'is-repeat' : '') + '" style="' + border + '"><span style="color:' + mc + ';' + (isLive ? 'font-style:italic;' : '') + '">'
        + esc(nameOf(key)) + '</span>' + tag + '</td>';
    });
    html += '</tr>';
  }
  document.getElementById('slot-grid').innerHTML = html + '</tbody></table>';
}

/* ── Hit Rate ── */
function tierCards() {
  document.getElementById('tier-cards').innerHTML = D.hit_rate_tiers.map(function (t) {
    return '<div class="hr-stat-card glass">'
      + '<div class="hr-stat-tier">' + esc(tierLabel(t)) + '</div>'
      + '<div class="hr-stat-pct hr-' + esc(t.tier.toLowerCase()) + '">' + t.hit_rate.toFixed(1) + '%</div>'
      + '<div class="hr-stat-sub">' + t.hits + ' hits from ' + t.picks + ' picks</div>'
      + '</div>';
  }).join('');
}

var POS_COLS = [['rb', 'RB', 'rgba(90,138,90,0.8)', 'rgba(90,138,90,1)'], ['wr', 'WR', 'rgba(74,127,168,0.8)', 'rgba(74,127,168,1)'],
  ['qb', 'QB', 'rgba(168,90,90,0.8)', 'rgba(168,90,90,1)'], ['te', 'TE', 'rgba(212,175,55,0.8)', 'rgba(212,175,55,1)'],
  ['k', 'K', 'rgba(156,148,156,0.7)', 'rgba(156,148,156,1)'], ['dst', 'D/ST', 'rgba(100,90,80,0.7)', 'rgba(100,90,80,1)']];

function hitCharts() {
  var HR = D.hit_rate_by_round, games = D.method ? D.method.min_games : 8;
  var rates = HR.map(function (d) { return d.hit_rate; });
  new Chart(document.getElementById('chart-hit-rate-round').getContext('2d'), {
    type: 'bar',
    data: { labels: HR.map(function (d) { return 'Rd ' + d.round; }), datasets: [{ label: 'Hit Rate', data: rates,
      backgroundColor: rates.map(function (v) { return absoluteGradient(v, 0.72); }),
      borderColor: rates.map(function (v) { return absoluteGradient(v, 1); }), borderWidth: 1.5, borderRadius: 3 }] },
    options: { responsive: true, plugins: { legend: { display: false }, tooltip: { callbacks: {
      title: function (i) { var d = HR[i[0].dataIndex]; return 'Round ' + d.round + ' (' + d.tier + ')'; },
      label: function (ctx) { var d = HR[ctx.dataIndex]; return ['Hit Rate: ' + d.hit_rate + '%', d.hits + ' hits from ' + d.total_picks + ' picks (min. ' + games + ' games played)']; }
    } } }, scales: { x: { grid: gridStyle(), ticks: tickStyle() },
      y: { grid: gridStyle(), ticks: Object.assign(tickStyle(), { callback: function (v) { return v + '%'; } }), title: { display: true, text: 'Hit Rate', color: C_MUTED, font: { size: 11 } }, min: 0, max: 100 } } },
    plugins: [tierDividerPlugin('td1')]
  });

  // position share per round; positions the league never drafts are left out
  var cols = POS_COLS.filter(function (c) { return HR.some(function (d) { return d[c[0]] > 0; }); });
  var totals = HR.map(function (d) { return POS_COLS.reduce(function (a, c) { return a + (d[c[0]] || 0); }, 0); });
  new Chart(document.getElementById('chart-pos-concentration').getContext('2d'), {
    type: 'bar',
    data: { labels: HR.map(function (d) { return 'Rd ' + d.round; }), datasets: cols.map(function (c) {
      return { label: c[1], data: HR.map(function (d, i) { return Math.round((d[c[0]] || 0) / (totals[i] || 1) * 100); }),
               backgroundColor: c[2], borderColor: c[3], borderWidth: 1 };
    }) },
    options: { responsive: true, plugins: {
      legend: { display: true, position: 'top', labels: { color: C_MUTED, boxWidth: 12, font: { size: 11 } } },
      tooltip: { callbacks: {
        title: function (i) { var d = HR[i[0].dataIndex]; return 'Round ' + d.round + ' (' + d.tier + ')'; },
        label: function (ctx) {
          var d = HR[ctx.dataIndex], key = ctx.dataset.label === 'D/ST' ? 'dst' : ctx.dataset.label.toLowerCase();
          return ctx.dataset.label + ': ' + d[key] + ' picks (' + ctx.parsed.y + '%)';
        }
      } }
    }, scales: { x: { grid: gridStyle(), ticks: tickStyle(), stacked: true },
      y: { grid: gridStyle(), ticks: Object.assign(tickStyle(), { callback: function (v) { return v + '%'; } }), stacked: true, min: 0, max: 100, title: { display: true, text: '% of Picks', color: C_MUTED, font: { size: 11 } } } } },
    plugins: [tierDividerPlugin('td2')]
  });

  // "K and D/ST flood in from round N onward": the round from which every later round is at least 10% K and D/ST
  var share = HR.map(function (d, i) { return ((d.k || 0) + (d.dst || 0)) / (totals[i] || 1); });
  var from = null;
  for (var i = share.length - 1; i >= 0 && share[i] >= 0.1; i--) from = HR[i].round;
  var late = ['k', 'dst'].filter(function (c) { return HR.some(function (d) { return d[c] > 0; }); }).map(function (c) { return c === 'k' ? 'K' : 'D/ST'; });
  document.getElementById('flood-note').textContent = from != null && from !== HR[0].round && late.length
    ? ' ' + late.join(' and ') + ' flood' + (late.length === 1 ? 's' : '') + ' in from round ' + from + ' onward.' : '';

  var positions = ['RB', 'WR', 'QB', 'TE'].filter(function (p) { return D.hit_rate_by_position[p]; });
  D.hit_rate_tiers.forEach(function (t, ti) {
    var label = document.getElementById('pos-label-' + ti);
    if (label) label.textContent = 'Hit Rate by Position - ' + tierLabel(t);
  });
  ['chart-hit-pos-early', 'chart-hit-pos-mid', 'chart-hit-pos-late'].forEach(function (id, ti) {
    var data = positions.map(function (p) { return D.hit_rate_by_position[p][ti]; });
    new Chart(document.getElementById(id).getContext('2d'), {
      type: 'bar',
      data: { labels: positions, datasets: [{ data: data,
        backgroundColor: data.map(function (v) { return absoluteGradient(v, 0.72); }),
        borderColor: data.map(function (v) { return absoluteGradient(v, 1); }), borderWidth: 1.5, borderRadius: 3 }] },
      options: { responsive: true, plugins: { legend: { display: false }, tooltip: { callbacks: { label: function (ctx) { return ctx.parsed.y + '% hit rate (min. ' + games + ' games played)'; } } } },
        scales: { x: { grid: gridStyle(), ticks: tickStyle() }, y: { grid: gridStyle(), ticks: Object.assign(tickStyle(), { callback: function (v) { return v + '%'; } }), min: 0, max: 100 } } }
    });
  });
}

/* ── notes from the method and the data ── */
function shadeWord(pct) {
  return pct >= 75 ? 'medium-green' : pct >= 50 ? 'light-green' : pct > 25 ? 'light-red' : 'dark-red';
}
function notes() {
  var m = D.method, seasons = D.seasons;
  var last = seasons[seasons.length - 1];
  var teams = ((cfg.seasons || []).find(function (s) { return s.season === last; }) || {}).team_count;
  var provider = cfg.league.provider === 'espn' ? 'ESPN' : String(cfg.league.provider || '').toUpperCase();
  if (m) {
    var groups = {};
    ['WR', 'RB', 'QB', 'TE'].forEach(function (p) { if (m.hit_top_n[p] != null) (groups[m.hit_top_n[p]] = groups[m.hit_top_n[p]] || []).push(p); });
    var tops = Object.keys(groups).map(Number).sort(function (a, b) { return b - a; })
      .map(function (n) { return 'top ' + n + ' at ' + groups[n].join(' or '); }).join(', or ');
    document.getElementById('hit-note').innerHTML = 'A pick is a <strong>hit</strong> if the player finished ' + tops
      + ', in PPR points per game for that season.' + (m.lineup_scaled
        ? ' Cutoffs follow each season\u2019s starters at the position (' + m.season + ' shown): the teams times its lineup slots, FLEX slots split by who filled them.'
        : (teams && teams === m.starter_rank.QB ? ' Thresholds are calibrated to the ' + teams + '-team league size.' : ''))
      + ' Stats are sourced directly from ' + esc(provider) + ' fantasy scoring to match your exact league settings. Data covers all '
      + count(seasons.length, 'season') + ', ' + rangeText(seasons) + '. Players with fewer than ' + m.min_games
      + ' games are excluded from hit rate calculations, since small samples are not reliable indicators of talent.';
    document.getElementById('steals-note').innerHTML = 'Picks are ranked by <strong>points above position average</strong>, not raw PPR/game, so '
      + 'positions are comparable. A WR who scores 8 points above the average WR beats a QB who scores 5 points above the average QB, '
      + "even if the QB's raw number is higher. Minimum " + m.steal_min_games + ' games played to qualify. Rounds ' + m.steal_min_round + ' and later only.';
    var sr = {};
    ['QB', 'TE', 'RB', 'WR'].forEach(function (p) { if (m.starter_rank[p] != null) (sr[m.starter_rank[p]] = sr[m.starter_rank[p]] || []).push(p); });
    var base = Object.keys(sr).map(Number).sort(function (a, b) { return a - b; }).map(function (n) { return 'top ' + n + ' for ' + sr[n].join('/'); }).join(', ');
    document.getElementById('surplus-note').innerHTML = 'Every pick is scored using <strong>position-relative value (PRV)</strong> -- how a player '
      + 'performed versus the average starter at their position that season (' + base + (m.lineup_scaled ? ' in ' + m.season
        + ', from each season\u2019s lineup slots' : '') + '). That PRV is then compared against all skill position '
      + 'players taken within ' + m.window + ' picks of that slot, capturing <strong>opportunity cost</strong>. A TE who beats the TE baseline by 5 '
      + 'points earns the same credit as a WR who beats the WR baseline by 5 points. <strong>Round weights</strong> apply: full weight early, '
      + 'discounted late. Picks with fewer than ' + m.min_games + ' games played count as zero surplus.';
  }
  // the gradient example: the best early position against the worst late one
  var pos = Object.keys(D.hit_rate_by_position), lastTier = D.hit_rate_tiers.length - 1;
  if (pos.length && lastTier > 0) {
    var best = pos.reduce(function (a, p) { return D.hit_rate_by_position[p][0] > D.hit_rate_by_position[a][0] ? p : a; }, pos[0]);
    var worst = pos.reduce(function (a, p) { return D.hit_rate_by_position[p][lastTier] < D.hit_rate_by_position[a][lastTier] ? p : a; }, pos[0]);
    var b = D.hit_rate_by_position[best][0], w = D.hit_rate_by_position[worst][lastTier];
    document.getElementById('gradient-note').innerHTML = 'Bar colors use an absolute scale where 0% is always red and 100% is always green, with bone '
      + 'at 50%. This means you can compare across all ' + count(D.hit_rate_tiers.length, 'chart') + '. A ' + shadeWord(b) + ' early '
      + best + ' (' + b + '%) looks very different from a ' + shadeWord(w) + ' ' + D.hit_rate_tiers[lastTier].tier.toLowerCase() + ' ' + worst
      + ' (' + w + '%), even though both might look "good" or "bad" on a relative scale. The gradient reflects the actual hit rate, not just how '
      + 'each position compares within its tier.';
  }
}

/* ── Steals ── */
function renderSteals(rows) {
  document.getElementById('steals-tbody').innerHTML = (rows || []).map(function (s) {
    return '<tr>'
      + '<td class="steal-rank">' + s.rank + '</td>'
      + '<td style="font-weight:600;color:var(--palm)">' + esc(s.player_name) + '</td>'
      + '<td><span class="pos-badge pos-' + s.position.toLowerCase() + '">' + esc(s.position) + '</span></td>'
      + '<td>' + s.round + '</td><td>' + s.draft_slot + '</td>'
      + '<td><span class="season-pill" style="background:' + (seasonColor(cfg, s.season) || 'var(--muted)') + ';">' + s.season + '</span></td>'
      + '<td style="font-weight:600;color:var(--accent)">' + s.ppg.toFixed(1) + '</td>'
      + '<td>' + rggPill(s.above_average, 0, D.above_average_max, 2, true) + '</td>'
      + '<td>' + s.games + '</td><td>' + esc(nameOf(s.manager_key)) + '</td></tr>';
  }).join('');
}

function steals() {
  var row = document.getElementById('steals-filter');
  var seasons = Object.keys(D.season_steals).map(Number).sort(function (a, b) { return a - b; });
  row.insertAdjacentHTML('beforeend', seasons.map(function (s) {
    var c = seasonColor(cfg, s);
    return '<button class="season-btn year-swatch-btn"' + (c ? ' style="--swatch-color:' + esc(c) + ';"' : '') + ' data-season="' + s + '">' + s + '</button>';
  }).join(''));
  row.addEventListener('click', function (e) {
    var btn = e.target.closest('.season-btn');
    if (!btn) return;
    row.querySelectorAll('.season-btn').forEach(function (b) { b.classList.remove('active'); });
    btn.classList.add('active');
    renderSteals(btn.dataset.season === 'all' ? D.steals : D.season_steals[btn.dataset.season]);
  });
  renderSteals(D.steals);
}

/* ── Surplus preview ── */
function surplusPreview() {
  var href = pageHref('surplus-value');
  var vals = D.career_preview.map(function (d) { return d.avg_surplus; });
  var min = Math.min.apply(null, vals), max = Math.max.apply(null, vals);
  var tbody = document.getElementById('surplus-preview-tbody');
  tbody.innerHTML = D.career_preview.map(function (d) {
    return '<tr' + (href ? ' style="cursor:pointer"' : '') + '>'
      + '<td class="surplus-rank">' + d.rank + '</td>'
      + '<td style="font-weight:600;color:var(--palm)">' + esc(nameOf(d.manager_key)) + '</td>'
      + '<td>' + rggPill(d.avg_surplus, min, max, 3, true) + '</td>'
      + '<td style="color:var(--muted)">' + d.seasons + '</td></tr>';
  }).join('');
  var link = document.getElementById('explore-surplus');
  if (href) {
    link.href = href;
    tbody.addEventListener('click', function (e) { if (e.target.closest('tr')) window.location.href = href; });
  } else {
    link.remove();
  }
}

function draw() {
  Chart.defaults.font.family = "'Outfit', sans-serif";
  Chart.defaults.font.size = 12;
  Chart.defaults.color = '#5a5550';
  D.slot_managers.forEach(function (s) { (SLOT_DATA[s.draft_slot] = SLOT_DATA[s.draft_slot] || []).push([nameOf(s.manager_key), s.season]); });
  var rows = D.slot_results.map(function (r) {
    return { slot: r.draft_slot, seasons: r.seasons, pp: roundN(r.playoff_rate * 100, 1), cp: roundN(r.champion_rate * 100, 1),
             pf: roundN(r.pf_per_game, 1), dom: roundN(r.dominance, 2), exp: roundN(r.expected_dominance, 2), ou3: roundN(r.over_under, 3) };
  });
  document.querySelectorAll('.season-range').forEach(function (el) { el.textContent = rangeText(D.seasons); });
  slotCharts(rows);
  slotTable(rows);
  slotGrid();
  tierCards();
  hitCharts();
  notes();
  steals();
  surplusPreview();
}

config().then(function (c) {
  cfg = c;
  mgr = managers(cfg);
  drawNav(cfg, 'draft-analysis');
  drawSubnav(cfg, 'draft-analysis');
  drawFooter(cfg);
  chapterRail();
  return load('data/v1/draft-analysis.json');
}).then(function (d) {
  D = d;
  draw();
}).catch(function (err) {
  console.error(err);
  var el = document.getElementById('slot-tbody');
  if (el) el.innerHTML = '<tr><td colspan="8"><div class="data-state data-state-error">This section could not be loaded.</div></td></tr>';
});
