/* Life Without Defense: every matchup re-scored with each team's started D/ST points removed
   (league-wide flips, position comparison, D/ST performance vs winning, margins, flip rate by
   season, the playoff field, net impact per manager, draft round and capital, predictability,
   and a per-manager panel).

   Reads config.json and data/v1/dst-impact.json (schema "dst-impact"); impact-data.js renames its
   manager keys to names, which gives the Stage A file exactly. The script itself is the Stage A
   page's, run once the data is in (decision 7.14: same look first; its inline handlers stay on
   window until the design pass). What was typed into the page now comes from the league: manager
   chip colors (config.json, light shade), the excluded managers, and from the data the seasons,
   games, sample sizes, the playoff field size and which seasons' real fields differed from it
   (config.json seasons[].playoff_team_count), the rounds a D/ST was drafted in, the thin rounds
   (under THIN_WEEKS weeks) and the correlation summary. */

import { config, load } from '../core/data.js';
import { managers } from '../core/managers.js';
import { drawNav, drawFooter, drawSubnav } from '../core/nav.js';
import { count } from '../core/format.js';
import { byName, ordinal } from './impact-data.js';
import { andList, seasonRanges } from './transaction-notes.js';

var Chart = window.Chart;
var DST_DATA = null, POSITIONS = [], MIN_ROUND = 8, MAX_ROUND = 16;
var POS_COLORS = { 'QB':'#983a3a', 'RB':'#4a7a4a', 'WR':'#3a6f98', 'TE':'#a07010', 'K':'#6a6460', 'D/ST':'#504840' };
var THIN_WEEKS = 10;

function capital(word) { return word.charAt(0).toUpperCase() + word.slice(1); }

/* the notes the Stage A page typed, from the data */
function notes(cfg, mgr) {
  var L = DST_DATA.league;
  var seasons = Array.from(new Set(L.all_games.map(function (g) { return g.season; }))).sort();
  document.getElementById('seasons-rescored').textContent = capital(count(seasons.length, 'season')) + ', re-scored.';
  document.getElementById('mini-seasons').textContent = seasons.length;
  document.querySelectorAll('[data-first-season]').forEach(function (el) { el.textContent = seasons[0]; });
  document.querySelectorAll('[data-total-games]').forEach(function (el) { el.textContent = L.total_games; });

  var hidden = mgr.all.filter(function (m) { return m.hidden; });
  var their = Array.from(new Set([].concat.apply([], hidden.map(function (m) { return m.seasons || []; })))).sort();
  document.getElementById('excluded-note').textContent = hidden.length ? ' ' + andList(hidden.map(function (m) { return m.name; }))
    + (their.length === 1 ? ' (' + their[0] + '-only participant' + (hidden.length > 1 ? 's' : '') + ')' : '')
    + (hidden.length > 1 ? ' are' : ' is') + ' excluded, matching the rest of the site.' : '';

  var P = DST_DATA.dst_performance;
  if (P) {
    document.getElementById('ppg-n').textContent = P.ppg_vs_winpct.n;
    document.getElementById('round-n').textContent = P.round_vs_winpct.n;
    var pr = P.ppg_vs_winpct.r, rr = P.round_vs_winpct.r;
    document.getElementById('corr-note').textContent = pr > 0.1 && Math.abs(rr) < 0.15
      ? 'A better-performing defense does correlate with winning a bit more -- not surprising, since D/ST points are literally part '
        + 'of your score. But when you drafted it barely matters: the round-to-round difference is close to noise.'
      : 'D/ST PPG correlates with win% at r = ' + pr.toFixed(2) + '; the round it was drafted, at r = ' + rr.toFixed(2) + '.';
  }

  // the playoff field the comparison uses, and the seasons whose real field was a different size
  var SP = DST_DATA.season_playoffs, sizes = {};
  Object.keys(SP).forEach(function (s) { var n = SP[s].actual_top8.length; sizes[n] = (sizes[n] || 0) + 1; });
  var field = Number(Object.keys(sizes).sort(function (a, b) { return sizes[b] - sizes[a]; })[0] || 0);
  document.getElementById('field-size').textContent = field;
  var info = function (s) { return (cfg.seasons || []).find(function (x) { return x.season === Number(s); }) || {}; };
  var odd = Object.keys(SP).filter(function (s) { return info(s).playoff_team_count && info(s).playoff_team_count !== field; }).sort();
  var rest = Object.keys(SP).filter(function (s) { return odd.indexOf(s) === -1; }).map(Number);
  document.getElementById('format-note').textContent = !odd.length ? '' : ' ' + andList(odd) + ' had non-standard playoff formats ('
    + odd.map(function (s) {
      var i = info(s);
      return s + ': ' + i.playoff_team_count + (i.team_count === i.playoff_team_count ? ' of ' + i.team_count : '') + ' teams made the playoffs';
    }).join('; ') + '), so treat ' + (odd.length === 1 ? 'that year’s' : 'those ' + count(odd.length, 'year').split(' ')[0] + ' years’')
    + ' playoff-field comparison as a looser approximation' + (rest.length ? ' than ' + seasonRanges(rest) : '') + '.';

  var dv = DST_DATA.draft_vs_waiver || {}, w = dv.by_round_weeks || {};
  var rounds = Object.keys(w).map(Number).sort(function (a, b) { return a - b; });
  if (rounds.length) { MIN_ROUND = rounds[0]; MAX_ROUND = rounds[rounds.length - 1]; }
  document.getElementById('dst-rounds').textContent = rounds.length ? MIN_ROUND + '-' + MAX_ROUND : '';
  var thin = rounds.filter(function (r) { return w[r] < THIN_WEEKS; });
  document.getElementById('thin-rounds').textContent = !thin.length ? '' : ' ' + (thin.length === 1 ? 'Round ' : 'Rounds ')
    + andList(thin.map(String)) + (thin.length === 1 ? ' has' : ' have') + ' very small samples (under ' + THIN_WEEKS + ' weeks) -- read '
    + (thin.length === 1 ? 'that bar' : thin.length === 2 ? 'those two bars' : 'those bars') + ' cautiously.';
}

var CURRENT_MANAGER = null;
var acqChart = null;
var mgrScatterChart = null;

var MANAGER_COLOR_HEX = {};   // name -> light color, from config.json
function hexToRgb(hex) {
  var r = parseInt(hex.slice(1,3),16), g = parseInt(hex.slice(3,5),16), b = parseInt(hex.slice(5,7),16);
  return r+','+g+','+b;
}

function shortName(name) {
  var parts = name.split(' ');
  return parts.length < 2 ? name : parts[0] + ' ' + parts[parts.length-1][0] + '.';
}

function renderHeadline() {
  var league = DST_DATA.league;
  var pct = (league.total_flips / league.total_games * 100).toFixed(1);
  document.getElementById('headline-pct').textContent = pct + '%';
  document.getElementById('mini-total-games').textContent = league.total_games;
  document.getElementById('mini-total-flips').textContent = league.total_flips;
}

var marginScatterPlugin = {
  id: 'marginScatterZones',
  beforeDatasetsDraw: function(chart) {
    var xScale = chart.scales.x, yScale = chart.scales.y;
    var area = chart.chartArea;
    var ctx = chart.ctx;
    ctx.save();

    // Shade the y < 0 region (flipped-outcome zone)
    var yZeroPx = yScale.getPixelForValue(0);
    if (yZeroPx < area.bottom) {
      ctx.fillStyle = 'rgba(192,74,74,0.08)';
      ctx.fillRect(area.left, yZeroPx, area.right - area.left, area.bottom - yZeroPx);
      ctx.font = "600 10px 'Outfit', sans-serif";
      ctx.fillStyle = 'rgba(192,74,74,0.7)';
      ctx.textAlign = 'left';
      ctx.textBaseline = 'top';
      ctx.fillText('Defensive-Flipped Matchups', area.left + 6, yZeroPx + 6);
    }

    // Y = X reference diagonal (no net effect on margin)
    var xMin = xScale.min, xMax = xScale.max;
    var p1x = xScale.getPixelForValue(xMin), p1y = yScale.getPixelForValue(xMin);
    var p2x = xScale.getPixelForValue(xMax), p2y = yScale.getPixelForValue(xMax);
    ctx.beginPath();
    ctx.setLineDash([4, 4]);
    ctx.moveTo(p1x, p1y);
    ctx.lineTo(p2x, p2y);
    ctx.lineWidth = 1;
    ctx.strokeStyle = 'rgba(90,85,80,0.4)';
    ctx.stroke();
    ctx.setLineDash([]);

    ctx.restore();
  }
};

function renderMarginScatter() {
  var games = DST_DATA.league.all_games;
  var points = games.map(function(g) {
    var winnerIsA = g.actual_winner === g.team_a;
    var winnerScore = winnerIsA ? g.score_a : g.score_b;
    var loserScore  = winnerIsA ? g.score_b : g.score_a;
    var winnerAdj   = winnerIsA ? g.adj_a : g.adj_b;
    var loserAdj    = winnerIsA ? g.adj_b : g.adj_a;
    return {
      x: winnerScore - loserScore,
      y: winnerAdj - loserAdj,
      g: g
    };
  });

  var flips = points.filter(function(p){ return p.g.flipped; });
  var nonFlips = points.filter(function(p){ return !p.g.flipped; });

  var ctx = document.getElementById('margin-scatter-chart').getContext('2d');
  new Chart(ctx, {
    type: 'scatter',
    data: {
      datasets: [
        {
          label: 'No flip',
          data: nonFlips,
          backgroundColor: 'rgba(156,148,156,0.45)',
          radius: 3.5,
        },
        {
          label: 'Outcome flipped',
          data: flips,
          backgroundColor: 'rgba(192,74,74,0.85)',
          radius: 4.5,
        },
      ]
    },
    plugins: [marginScatterPlugin],
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            title: function(items) {
              var g = items[0].raw.g;
              return '\'' + String(g.season).slice(2) + ' ' + g.label;
            },
            label: function(item) {
              var g = item.raw.g;
              var newWinner = g.adj_winner === 'TIE' ? 'Tie' : g.adj_winner;
              return [
                g.team_a + ' ' + g.score_a.toFixed(1) + ' - ' + g.score_b.toFixed(1) + ' ' + g.team_b,
                'Without D/ST: ' + g.adj_a.toFixed(1) + ' - ' + g.adj_b.toFixed(1) + ' (' + newWinner + ')'
              ];
            }
          }
        }
      },
      scales: {
        x: { title: { display: true, text: 'Actual margin of victory' }, beginAtZero: true },
        y: { title: { display: true, text: 'Margin without defense' } }
      }
    }
  });
}

var mgrScatterPlugin = {
  id: 'mgrScatterZones',
  beforeDatasetsDraw: function(chart) {
    var xScale = chart.scales.x, yScale = chart.scales.y;
    var area = chart.chartArea;
    var ctx = chart.ctx;
    ctx.save();

    var x0 = xScale.getPixelForValue(0);
    var y0 = yScale.getPixelForValue(0);

    // Won but would've lost (x > 0, y < 0) -- defense secured this win; removing it would hurt
    ctx.fillStyle = 'rgba(192,74,74,0.08)';
    if (x0 < area.right && y0 < area.bottom) {
      var xStart = Math.max(x0, area.left);
      ctx.fillRect(xStart, y0, area.right - xStart, area.bottom - y0);
    }
    // Lost but would've won (x < 0, y > 0) -- defense cost this win; removing it would help
    ctx.fillStyle = 'rgba(74,138,90,0.08)';
    if (x0 > area.left && y0 > area.top) {
      var yEnd = Math.min(y0, area.bottom);
      ctx.fillRect(area.left, area.top, x0 - area.left, yEnd - area.top);
    }

    // Zero reference lines
    ctx.strokeStyle = 'rgba(90,85,80,0.25)';
    ctx.lineWidth = 1;
    ctx.beginPath(); ctx.moveTo(x0, area.top); ctx.lineTo(x0, area.bottom); ctx.stroke();
    ctx.beginPath(); ctx.moveTo(area.left, y0); ctx.lineTo(area.right, y0); ctx.stroke();

    // Y = X diagonal (no net effect on their margin)
    var lo = Math.min(xScale.min, yScale.min);
    var hi = Math.max(xScale.max, yScale.max);
    var p1x = xScale.getPixelForValue(lo), p1y = yScale.getPixelForValue(lo);
    var p2x = xScale.getPixelForValue(hi), p2y = yScale.getPixelForValue(hi);
    ctx.beginPath();
    ctx.setLineDash([4, 4]);
    ctx.moveTo(p1x, p1y);
    ctx.lineTo(p2x, p2y);
    ctx.strokeStyle = 'rgba(90,85,80,0.4)';
    ctx.stroke();
    ctx.setLineDash([]);

    ctx.restore();
  }
};

function renderMgrScatter(name) {
  var games = DST_DATA.league.all_games.filter(function(g) {
    return g.team_a === name || g.team_b === name;
  });
  var points = games.map(function(g) {
    var isA = g.team_a === name;
    var myScore = isA ? g.score_a : g.score_b;
    var oppScore = isA ? g.score_b : g.score_a;
    var myAdj = isA ? g.adj_a : g.adj_b;
    var oppAdj = isA ? g.adj_b : g.adj_a;
    return { x: myScore - oppScore, y: myAdj - oppAdj, g: g, opponent: isA ? g.team_b : g.team_a };
  });

  var gained = points.filter(function(p) { return p.x < 0 && p.y >= 0; });   // lost, would've won -- defense cost them
  var lost   = points.filter(function(p) { return p.x >= 0 && p.y < 0; });   // won, would've lost -- defense secured it
  var noFlip = points.filter(function(p) { return (p.x >= 0) === (p.y >= 0); });

  if (mgrScatterChart) mgrScatterChart.destroy();
  var ctx = document.getElementById('mgr-scatter-chart').getContext('2d');
  mgrScatterChart = new Chart(ctx, {
    type: 'scatter',
    data: {
      datasets: [
        { label: 'No flip', data: noFlip, backgroundColor: 'rgba(156,148,156,0.5)', radius: 4 },
        { label: 'Defense cost them a win', data: gained, backgroundColor: 'rgba(74,138,90,0.85)', radius: 5 },
        { label: 'Defense secured a win', data: lost, backgroundColor: 'rgba(192,74,74,0.85)', radius: 5 },
      ]
    },
    plugins: [mgrScatterPlugin],
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            title: function(items) {
              var g = items[0].raw.g;
              return '\'' + String(g.season).slice(2) + ' ' + g.label + ' vs ' + items[0].raw.opponent;
            },
            label: function(item) {
              var p = item.raw;
              return ['Actual margin: ' + (p.x >= 0 ? '+' : '') + p.x.toFixed(1),
                      'Without D/ST: ' + (p.y >= 0 ? '+' : '') + p.y.toFixed(1)];
            }
          }
        }
      },
      scales: {
        x: { title: { display: true, text: 'Their actual margin' } },
        y: { title: { display: true, text: 'Margin without defense' } }
      }
    }
  });
}

function renderSeasonPlayoffList() {
  var sp = DST_DATA.season_playoffs;
  var seasons = Object.keys(sp).sort();
  var el = document.getElementById('season-playoff-list');

  el.innerHTML = seasons.map(function(season) {
    var s = sp[season];
    var champBadge = s.champion_changed
      ? '<span class="season-badge changed">Title Doesn\'t Hold Up</span>'
      : '<span class="season-badge same">Same Champion</span>';
    var champNote = s.champion_changed
      ? '<div class="season-flip-note"><strong>' + shortName(s.actual_champion) + '</strong> actually won it, '
        + 'but would have been eliminated in the ' + s.champion_eliminated_round + ' without defense -- so a '
        + 'different champion would have won in ' + season + '. (Exactly who can\'t be determined beyond that '
        + 'point without simulating hypothetical matchups that never really happened.)</div>'
      : '';

    var fieldHtml;
    if (s.gained.length === 0 && s.lost.length === 0) {
      fieldHtml = '<div class="season-none">No change to the playoff field.</div>';
    } else {
      var tags = s.gained.map(function(m) {
        return '<span class="season-tag gained">+ ' + shortName(m) + '</span>';
      }).concat(s.lost.map(function(m) {
        return '<span class="season-tag lost">&minus; ' + shortName(m) + '</span>';
      }));
      fieldHtml = '<div class="season-field-row">' + tags.join('') + '</div>';
    }

    var flipNotes = s.playoff_flips.map(function(f) {
      var newWinner = f.adj_winner === 'TIE' ? 'a tie' : f.adj_winner;
      return '<div class="season-flip-note">' + f.label + ': ' + f.team_a + ' ' + f.score_a.toFixed(1)
        + ' &ndash; ' + f.score_b.toFixed(1) + ' ' + f.team_b + ' (actual: ' + f.actual_winner
        + ') would have gone to ' + newWinner + ' without defense (' + f.adj_a.toFixed(1) + '-' + f.adj_b.toFixed(1) + ').</div>';
    }).join('');

    return '<div class="season-card">'
      + '<div class="season-card-header"><span class="season-year">' + season + '</span>' + champBadge + '</div>'
      + champNote
      + fieldHtml
      + flipNotes
      + '</div>';
  }).join('');
}

var trendLinePlugin = {
  id: 'trendLine',
  afterDatasetsDraw: function(chart) {
    var xScale = chart.scales.x, yScale = chart.scales.y;
    var area = chart.chartArea;
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

function renderDraftCapitalTable() {
  var dc = DST_DATA.draft_capital;
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

  function roundColor(rnd) {
    if (rnd === null) return '';
    var t = Math.max(0, Math.min(1, (rnd - MIN_ROUND) / Math.max(1, MAX_ROUND - MIN_ROUND)));
    var opacity = 1 - t * 0.75; // earliest round -> 1.0, latest -> 0.25
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
        html += '<td class="dcap-round-cell" style="' + roundColor(rnd) + '">Rd ' + rnd + '</td>';
      }
    });
    var avgTxt = d.career_avg_round !== null ? 'Rd ' + d.career_avg_round.toFixed(1) : '&ndash;';
    html += '<td class="dcap-avg-cell">' + avgTxt + '</td></tr>';
  });

  html += '</tbody>';
  document.getElementById('dcap-table').innerHTML = html;
}

function renderPpgCorrChart() {
  var dp = DST_DATA.dst_performance;
  var stat = dp.ppg_vs_winpct;
  var points = dp.points.map(function(p){ return { x: p.ppg, y: p.win_pct * 100, season: p.season, manager: p.manager }; });

  var ctx = document.getElementById('ppg-corr-chart').getContext('2d');
  var chart = new Chart(ctx, {
    type: 'scatter',
    data: { datasets: [{ data: points, backgroundColor: 'rgba(80,72,64,0.6)', radius: 4 }] },
    plugins: [trendLinePlugin],
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            title: function(items) { var p = items[0].raw; return p.manager + ' \u2019' + String(p.season).slice(2); },
            label: function(item) { return item.raw.x.toFixed(1) + ' PPG, ' + item.raw.y.toFixed(0) + '% win rate'; }
          }
        }
      },
      scales: {
        x: { title: { display: true, text: 'D/ST PPG' } },
        y: { title: { display: true, text: 'Win %' } }
      }
    }
  });
  chart.$trend = { slope: stat.slope * 100, intercept: stat.intercept * 100 };
  chart.update();
  document.getElementById('ppg-corr-readout').textContent =
    'r = ' + stat.r.toFixed(3) + '  (R\u00B2 = ' + (stat.r2*100).toFixed(1) + '%,  n = ' + stat.n + ')';
}

function renderRoundCorrChart() {
  var dp = DST_DATA.dst_performance;
  var stat = dp.round_vs_winpct;
  var points = dp.points.filter(function(p){ return p.drafted_round !== null; })
    .map(function(p){ return { x: p.drafted_round, y: p.win_pct * 100, season: p.season, manager: p.manager }; });

  var ctx = document.getElementById('round-corr-chart').getContext('2d');
  var chart = new Chart(ctx, {
    type: 'scatter',
    data: { datasets: [{ data: points, backgroundColor: 'rgba(80,72,64,0.6)', radius: 4 }] },
    plugins: [trendLinePlugin],
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            title: function(items) { var p = items[0].raw; return p.manager + ' \u2019' + String(p.season).slice(2); },
            label: function(item) { return 'Drafted round ' + item.raw.x + ', ' + item.raw.y.toFixed(0) + '% win rate'; }
          }
        }
      },
      scales: {
        x: { title: { display: true, text: 'D/ST Draft Round' } },
        y: { title: { display: true, text: 'Win %' } }
      }
    }
  });
  chart.$trend = { slope: stat.slope * 100, intercept: stat.intercept * 100 };
  chart.update();
  document.getElementById('round-corr-readout').textContent =
    'r = ' + stat.r.toFixed(3) + '  (R\u00B2 = ' + (stat.r2*100).toFixed(1) + '%,  n = ' + stat.n + ')';
}

function renderPositionFlipChart() {
  var rates = DST_DATA.position_flip_rates;
  var order = POSITIONS;
  var colors = POS_COLORS;

  var ctx = document.getElementById('position-flip-chart').getContext('2d');
  new Chart(ctx, {
    type: 'bar',
    data: {
      labels: order,
      datasets: [{
        data: order.map(function(p){ return rates[p].pct; }),
        backgroundColor: order.map(function(p){ return colors[p]; }),
        borderRadius: 4,
      }]
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            label: function(item) {
              var p = order[item.dataIndex];
              return rates[p].flips + ' of ' + rates[p].total + ' games flip (' + rates[p].pct + '%)';
            }
          }
        }
      },
      scales: {
        y: { title: { display: true, text: '% of games that flip' }, beginAtZero: true }
      }
    }
  });
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

function renderDraftVsWaiverChart() {
  var dv = DST_DATA.draft_vs_waiver;
  var rounds = Object.keys(dv.by_round_ppg).map(Number).sort(function(a,b){ return a-b; });

  var ctx = document.getElementById('draft-waiver-chart').getContext('2d');
  var chart = new Chart(ctx, {
    type: 'bar',
    data: {
      labels: rounds.map(function(r){ return 'Rd ' + r; }),
      datasets: [{
        data: rounds.map(function(r){ return dv.by_round_ppg[r]; }),
        backgroundColor: 'rgba(80,72,64,0.75)',
        borderRadius: 4,
      }]
    },
    plugins: [draftWaiverLinePlugin],
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            label: function(item) {
              var r = rounds[item.dataIndex];
              return item.parsed.y.toFixed(2) + ' PPG (' + dv.by_round_weeks[r] + ' real-game weeks)';
            }
          }
        }
      },
      scales: {
        y: { title: { display: true, text: 'PPG' }, beginAtZero: true }
      }
    }
  });
  chart.$waiverPPG = dv.waiver_ppg;
  chart.update();
}

var barValueLabelPlugin = {
  id: 'barValueLabel',
  afterDatasetsDraw: function(chart) {
    var ctx = chart.ctx;
    var meta = chart.getDatasetMeta(0);
    ctx.save();
    ctx.font = "700 11px 'Outfit', sans-serif";
    ctx.fillStyle = '#3d3a38';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'bottom';
    meta.data.forEach(function(bar, i) {
      var val = chart.data.datasets[0].data[i];
      ctx.fillText(val.toFixed(2), bar.x, bar.y - 4);
    });
    ctx.restore();
  }
};

function renderPositionConsistencyChart() {
  var cv = DST_DATA.position_consistency;
  var order = POSITIONS;
  var colors = POS_COLORS;

  var ctx = document.getElementById('position-consistency-chart').getContext('2d');
  new Chart(ctx, {
    type: 'bar',
    data: {
      labels: order,
      datasets: [{
        data: order.map(function(p){ return cv[p].avg_cv; }),
        backgroundColor: order.map(function(p){ return colors[p]; }),
        borderRadius: 4,
      }]
    },
    plugins: [barValueLabelPlugin],
    options: {
      responsive: true, maintainAspectRatio: false,
      layout: { padding: { top: 20 } },
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            label: function(item) {
              var p = order[item.dataIndex];
              return 'Based on ' + cv[p].sample + ' player-seasons';
            }
          }
        }
      },
      scales: {
        y: { title: { display: true, text: 'Week-to-week unpredictability' }, beginAtZero: true }
      }
    }
  });

  var dstCv = cv['D/ST'].avg_cv;
  var others = order.filter(function(p){ return p !== 'D/ST'; }).map(function(p){ return cv[p].avg_cv; });
  var nextHighest = Math.max.apply(null, others);
  var ratio = (dstCv / nextHighest).toFixed(1);
  var place = others.filter(function(v){ return v > dstCv; }).length + 1;
  document.getElementById('consistency-callout').textContent = !others.length ? '' : dstCv > nextHighest
    ? 'Defense is about ' + ratio + 'x more unpredictable, week to week, than any other position.'
    : 'Defense is the ' + ordinal(place) + ' most unpredictable position, week to week.';
}

function renderChips() {
  var grid = document.getElementById('mgr-chip-grid');
  var names = Object.keys(DST_DATA.managers).sort();
  grid.innerHTML = names.map(function(m) {
    var rgb = hexToRgb(MANAGER_COLOR_HEX[m] || '#9c949c');
    return '<div class="mgr-chip" style="--chip-rgb:' + rgb + ';" onclick="selectManager(\'' + m + '\')">' + shortName(m) + '</div>';
  }).join('');
}

function selectManager(name) {
  CURRENT_MANAGER = name;
  document.querySelectorAll('.mgr-chip').forEach(function(c) {
    c.classList.toggle('active', c.textContent.trim() === shortName(name));
  });
  var d = DST_DATA.managers[name];
  document.getElementById('mgr-panel-name').textContent = name;
  document.getElementById('mgr-actual-record').textContent = d.actual_record[0] + '-' + d.actual_record[1];
  document.getElementById('mgr-adj-record').textContent = d.adj_record[0] + '-' + d.adj_record[1];
  document.getElementById('mgr-dst-ppg-note').textContent = 'Averages ' + d.dst_ppg.toFixed(1) + ' PPG from D/ST across ' + d.games + ' games';

  renderFlipList(d);
  renderMgrScatter(name);
  renderAcqPie(d);
}

function renderFlipList(d) {
  var el = document.getElementById('mgr-flip-list');
  if (!d.flipped_games.length) {
    el.innerHTML = '<p class="metric-note">No games would have flipped for this manager.</p>';
    return;
  }
  var games = d.flipped_games.slice().sort(function(a,b){ return a.season - b.season; });
  el.innerHTML = games.map(function(g) {
    var gained = g.direction === 'gained_win';
    var tagClass = gained ? 'gained' : 'lost';
    var tagText = gained ? 'GAINED WIN' : 'LOST WIN';
    return '<div class="mgr-flip-row">'
      + '<div class="flip-row-top">'
      +   '<span class="flip-tag ' + tagClass + '">' + tagText + '</span>'
      +   '<span class="flip-meta">\'' + String(g.season).slice(2) + ' ' + g.label + '</span>'
      + '</div>'
      + '<div class="flip-detail">vs ' + g.opponent + ' - ' + g.my_score.toFixed(1) + '-' + g.opp_score.toFixed(1)
      +   ' &rarr; ' + g.my_adj.toFixed(1) + '-' + g.opp_adj.toFixed(1) + '</div>'
      + '</div>';
  }).join('');
}

function renderAcqPie(d) {
  var acq = d.acquisition;
  var vals = [acq.drafted, acq.waiver, acq.traded];
  var labels = ['Drafted', 'Waiver / FA', 'Traded'];
  var colors = ['#4a7fa8', '#c0623a', '#d4af37'];
  var total = vals.reduce(function(a,b){ return a+b; }, 0);

  var legendEl = document.getElementById('acq-legend');
  legendEl.innerHTML = labels.map(function(lab, i) {
    var pct = total !== 0 ? (vals[i] / total * 100).toFixed(0) : 0;
    return '<div class="pie-legend-row"><span class="pie-swatch" style="background:' + colors[i] + ';"></span>'
      + lab + '<span class="pie-legend-val">' + vals[i].toFixed(0) + ' pts (' + pct + '%)</span></div>';
  }).join('');

  if (acqChart) acqChart.destroy();
  var ctx = document.getElementById('acq-pie-chart').getContext('2d');
  acqChart = new Chart(ctx, {
    type: 'doughnut',
    data: { labels: labels, datasets: [{ data: vals.map(function(v){ return Math.max(v, 0); }), backgroundColor: colors, borderWidth: 0 }] },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: { legend: { display: false } },
      cutout: '62%'
    }
  });
}

function renderNetImpactChart() {
  var names = Object.keys(DST_DATA.managers);
  var rows = names.map(function(m) {
    var games = DST_DATA.managers[m].flipped_games;
    var gained = games.filter(function(g){ return g.direction === 'gained_win'; }).length;
    var lost = games.filter(function(g){ return g.direction === 'lost_win'; }).length;
    return { name: m, net: gained - lost };
  });
  rows.sort(function(a,b){ return b.net - a.net; });

  var ctx = document.getElementById('net-impact-chart').getContext('2d');
  new Chart(ctx, {
    type: 'bar',
    data: {
      labels: rows.map(function(r){ return shortName(r.name); }),
      datasets: [{
        data: rows.map(function(r){ return r.net; }),
        backgroundColor: rows.map(function(r){ return r.net >= 0 ? 'rgba(74,138,90,0.75)' : 'rgba(192,74,74,0.75)'; }),
        borderRadius: 3,
      }]
    },
    options: {
      indexAxis: 'y',
      responsive: true, maintainAspectRatio: false,
      plugins: { legend: { display: false } },
      scales: {
        x: { title: { display: true, text: 'Net games (gained - lost)' }, ticks: { stepSize: 1 } },
        y: { ticks: { font: { size: 10 } } }
      }
    }
  });
}

function renderSeasonFlipChart() {
  var seasons = Array.from(new Set(DST_DATA.league.all_games.map(function(g){ return g.season; }))).sort();
  var counts = seasons.map(function(s) {
    var games = DST_DATA.league.all_games.filter(function(g){ return g.season === s; });
    var flips = games.filter(function(g){ return g.flipped; }).length;
    return games.length ? (flips / games.length * 100) : 0;
  });

  var ctx = document.getElementById('season-flip-chart').getContext('2d');
  new Chart(ctx, {
    type: 'bar',
    data: {
      labels: seasons,
      datasets: [{
        data: counts,
        backgroundColor: 'rgba(212,175,55,0.7)',
        borderRadius: 4,
      }]
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: { callbacks: { label: function(ctx){ return ctx.parsed.y.toFixed(1) + '% of games flipped'; } } }
      },
      scales: {
        y: { title: { display: true, text: '% flipped' }, beginAtZero: true }
      }
    }
  });
}


// the handlers the page's markup names (inline onclick, as on the Stage A page)
window.selectManager = selectManager;

config().then(function (cfg) {
  var mgr = managers(cfg);
  drawNav(cfg, 'dst-impact');
  drawSubnav(cfg, 'dst-impact');
  drawFooter(cfg);
  return load('data/v1/dst-impact.json').then(function (M) {
    DST_DATA = byName(M, mgr.name);
    mgr.all.forEach(function (m) { if (m.colors) MANAGER_COLOR_HEX[m.name] = m.colors.light || m.colors.dark; });
    POSITIONS = Object.keys(DST_DATA.position_flip_rates);
    POSITIONS.forEach(function (p) { if (!POS_COLORS[p]) POS_COLORS[p] = '#8a8480'; });
    notes(cfg, mgr);
    renderHeadline();
    renderPositionFlipChart();
    if (DST_DATA.dst_performance) { renderPpgCorrChart(); renderRoundCorrChart(); }
    renderMarginScatter();
    renderSeasonFlipChart();
    renderSeasonPlayoffList();
    renderNetImpactChart();
    if (DST_DATA.draft_vs_waiver && DST_DATA.draft_vs_waiver.by_round_ppg) renderDraftVsWaiverChart();
    renderDraftCapitalTable();
    renderPositionConsistencyChart();
    renderChips();
    var first = Object.keys(DST_DATA.managers).sort()[0];
    if (first) selectManager(first);
  });
}).catch(function (err) {
  console.error(err);
  var el = document.getElementById('headline-sub');
  if (el) el.innerHTML = '<div class="data-state data-state-error">This page could not be loaded.</div>';
});
