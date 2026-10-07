/* Extra Analytics: head-to-head, closest games, championship gauntlet, conference analysis,
   schedule luck, schedule swap, the quarterly playoff model, positional production and win%
   attribution.

   Reads config.json and data/v1/extra-analytics.json (schema "extra-analytics");
   extra-analytics-data.js turns the model into the shapes the page's script reads, as the Stage A
   build wrote them inline. The script itself is the Stage A page's, run inside runPage() once the
   data is in (decision 7.14: same look first; its inline handlers stay on window until the design
   pass). What was typed into the page now comes from the league:
     managers, colors, logos  config.json; season pills and colors from its seasons and theme
     schedule luck            Career or one season (schedule_luck.seasons; Ethan, session 7)
     conference section       labels from league.conference_labels (colors by position, conf-0 and
                              conf-1), the teams, cards and tables from the data; hidden when the
                              league has no conferences
     notes                    every number in the notes, and the sentences that state them, from the
                              data: fits (n, R2, AUC), the strongest predictors, conference totals,
                              outliers and rivalries, stretch counts, the champions' spread and ranks
     editorial                the R2 chart's earlier model versions and the schedule swap caveats,
                              from the league's extra_analytics.yaml (model.attribution.history,
                              model.notes.swap_caveats) */

import { config, load } from '../core/data.js';
import { managers } from '../core/managers.js';
import { drawNav, drawFooter, drawSubnav } from '../core/nav.js';
import { esc } from '../core/site.js';
import { count } from '../core/format.js';
import { extraData, seasonLuck } from './extra-analytics-data.js';
import { andList } from './transaction-notes.js';

var Chart = window.Chart;
var cfg, mgr, MODEL, D, PAGE_LIVE_SEASON = null, SEASON_COLORS = {}, HARDEST_ALL = [], EASIEST_ALL = [];

/* "2026 (live)" for the live season, else the year (shared.js on the Stage A site) */
function seasonLabel(s) {
  return PAGE_LIVE_SEASON !== null && String(s) === String(PAGE_LIVE_SEASON) ? s + ' (live)' : String(s);
}

function pct3(v) { var t = v.toFixed(3); return v < 1 ? t.replace(/^0/, '') : t; }
function title(word) { return word.charAt(0).toUpperCase() + word.slice(1); }
function numberWord(n) { return count(n, 'x').split(' ')[0]; }

/* ---------------------------------------------------------------- notes from the data */

/* "All Five Significant, p < 0.05", or "3 of 5 Significant, p < 0.05" */
function significantTitle(coefs) {
  var sig = coefs.filter(function (c) { return c.p_value < 0.05; }).length;
  return (sig === coefs.length ? 'All ' + title(numberWord(coefs.length)) : sig + ' of ' + coefs.length) + ' Significant, p < 0.05';
}

function r2Title(vals) {
  if (vals.length < 2) return 'Model Fit';
  var rising = vals.every(function (v, i) { return i === 0 || v > vals[i - 1]; });
  return 'Model Refinement  |  ' + (rising ? 'Each Fix Improved Fit' : 'R² At Each Fix');
}

function fitText(fit) { return 'n=' + fit.n + ' manager-seasons, R&sup2;=' + fit.r2.toFixed(2); }

function quarterlyNotes() {
  var Q = MODEL.quarterly, fit = MODEL.quarterly_fit;
  var label = function (q) { return q.quarter + ' (Weeks ' + q.weeks + ')'; };
  var ranked = Q.slice().sort(function (a, b) { return b.coef - a.coef; });
  var top = ranked.slice(0, 2).sort(function (a, b) { return Q.indexOf(a) - Q.indexOf(b); });
  var html = 'A logistic regression tested which part of the season best predicts playoff qualification, using average '
    + 'points scored each quarter as independent variables. ';
  if (fit) {
    var word = fit.auc >= 0.8 ? 'strong' : fit.auc >= 0.7 ? 'fair' : 'weak';
    html += '<strong>The model achieved an AUC of ' + fit.auc.toFixed(2) + '</strong>, indicating ' + word + ' predictive accuracy. ';
  }
  html += esc(top.map(label).join(' and ')) + ' carry the largest coefficients, while ' + esc(label(ranked[ranked.length - 1]))
    + ' is the weakest predictor.';
  document.getElementById('q-method').innerHTML = html;
}

function positionalNotes() {
  var P = MODEL.positional;
  var fitEl = document.getElementById('pos-fit');
  if (P.fit) fitEl.innerHTML = fitText(P.fit); else fitEl.parentNode.removeChild(fitEl);
  document.getElementById('pos-head').innerHTML = '<th class="pos-sortable" data-key="manager">Manager</th>'
    + '<th class="pos-sortable sort-desc" data-key="winpct">Win%</th>'
    + P.positions.map(function (p) { return '<th class="pos-sortable" data-key="' + esc(p) + '">' + esc(p) + '</th>'; }).join('');
  var c = P.coefficients.slice().sort(function (a, b) { return b.std_coef - a.std_coef; });
  var sig = c.filter(function (x) { return x.p_value < 0.05; }), not = c.filter(function (x) { return x.p_value >= 0.05; });
  var w = function (x) { return esc(x.position) + ' (' + x.std_coef.toFixed(2) + ')'; };
  var html = '';
  if (sig.length) {
    html += '<strong>' + esc(andList(sig.slice(0, 2).map(function (x) { return x.position; }))) + ' '
      + (sig.length > 1 && sig.slice(0, 2).length > 1 ? 'are' : 'is') + ' the strongest predictor' + (sig.slice(0, 2).length > 1 ? 's' : '')
      + ' of winning</strong> once every position is controlled for (standardized weights '
      + sig.slice(0, 2).map(function (x) { return x.std_coef.toFixed(2); }).join(' and ') + ')';
    html += sig.length > 2 ? ', then ' + andList(sig.slice(2).map(w)) + '. ' : '. ';
  }
  if (not.length) {
    html += esc(andList(not.map(function (x) { return x.position; }))) + (not.length > 1 ? ' barely move' : ' barely moves')
      + ' the needle once the others are accounted for (not significant at p < 0.05).';
  }
  document.getElementById('pos-note').innerHTML = html;
}

var FACTOR_WORDS = { draft: 'draft skill', lineup: 'missed wins from lineup mistakes', waiver: 'waiver value',
                     trade: 'trade quality', luck: 'schedule luck' };
function attributionNotes() {
  var A = MODEL.attribution;
  document.getElementById('attr-fit').innerHTML = fitText(A.fit);
  var c = A.coefficients.slice().sort(function (a, b) { return b.std_coef - a.std_coef; });
  var word = function (x) { return FACTOR_WORDS[x.factor] || x.factor; };
  var rest = 1 - A.fit.r2;
  document.getElementById('attr-note').innerHTML = '<strong>' + esc(title(word(c[0]))) + ' is the single biggest lever</strong>'
    + (c.length > 1 ? ', then ' + esc(andList(c.slice(1).map(word))) + ', in that order' : '') + '. '
    + 'Waiver activity only shows up once it’s measured as pure upside, ignore the churn and the misses, and count only '
    + 'the real hits. Even together, these ' + numberWord(c.length) + ' ingredients explain <strong>'
    + Math.round(A.fit.r2 * 100) + '% of season-to-season win% variance</strong>, leaving '
    + (rest > 0.55 ? 'well over half' : rest > 0.45 ? 'about half' : 'less than half')
    + ' of what separates a good season from a bad one to real scoring production and variance the roster-building '
    + 'decisions above don’t capture.';
}

function swapNotes() {
  var hidden = mgr.all.filter(function (m) { return m.hidden; }).map(function (m) { return m.name; });
  var el = document.getElementById('ss-excluded');
  el.textContent = hidden.length ? 'Playoff games, consolation games, and anything involving ' + hidden.join(' or ')
    : 'Playoff games and consolation games';
}

function gauntletNotes() {
  var champs = MODEL.gauntlet.champions;
  document.getElementById('g-runs').textContent = numberWord(champs.length);
  var lengths = Array.from(new Set(champs.map(function (c) { return c.n; }))).sort();
  var three = champs.filter(function (c) { return c.n === 3; })[0];
  var total = three ? three.total : (MODEL.gauntlet.hardest[0] || {}).total;
  var skipped = (cfg.exclude_games || []).length;
  var other = lengths.filter(function (n) { return n !== 3; });
  document.getElementById('g-stretch-intro').innerHTML = 'A title run is really just a 3-game'
    + (other.length ? ' (or ' + other.join('-game, ') + '-game)' : '') + ' stretch of opponents. The same Gauntlet Score '
    + 'methodology applies to <strong>any manager’s any 3 consecutive real weeks</strong>, not just playoff runs. Applied to '
    + (total ? '<strong>all ' + total + ' such stretches</strong>' : 'every such stretch') + ' in league history'
    + (skipped ? ' (' + count(skipped, 'known forfeit week') + ' excluded)' : '')
    + ', deduplicated to one stretch per manager-season, it reveals the true scale: even the <strong>single hardest stretch '
    + 'ever only reaches ' + (HARDEST_ALL.length ? HARDEST_ALL[0].gs.toFixed(1) : '') + '</strong>, because averaging three '
    + 'games’ worth of opponent quality mechanically pulls the result toward the middle. That compression is what makes '
    + 'the scale honest, and it’s why a title run’s score can look modest in isolation while still ranking among the toughest ever.';
}

function gauntletCaption(champions, ranks) {
  var text = 'Every title run compared on the same fixed scale.';
  if (champions.length > 1) {
    var gs = champions.map(function (c) { return c.gs; });
    text += ' Relative to each other, the ' + numberWord(champions.length) + ' sit within '
      + (Math.max.apply(null, gs) - Math.min.apply(null, gs)).toFixed(1) + ' points of each other.';
  }
  var best = null;
  champions.forEach(function (c) {
    var rk = ranks[c.year + '_' + c.champion];
    if (rk && (!best || rk.rank / rk.total < best.rk.rank / best.rk.total)) best = { c: c, rk: rk };
  });
  if (best) {
    text += ' But as the full stretch-history comparison below shows, ' + best.c.champion.split(' ')[0] + '’s '
      + best.c.year + ' run ranks in the toughest ' + Math.ceil(best.rk.rank / best.rk.total * 100) + '% of any '
      + (best.rk.sameLength || 3) + '-week stretch anyone has faced.';
  }
  return text;
}

/* ---------------------------------------------------------------- conference section */

function conferenceSection() {
  var C = MODEL.conference, section = document.getElementById('conference-analysis');
  var labels = (cfg.league && cfg.league.conference_labels) || {};
  var index = {};
  Object.keys(labels).forEach(function (k) { index[labels[k]] = k; });
  var order = Array.from(new Set(C.managers.map(function (m) { return m.conference; }).filter(Boolean))).sort();
  if (order.length < 2) {                     // no conferences: the section keeps only the rivalries
    section.querySelector('.section-label').textContent = 'Rivalries';
    document.getElementById('conf-title').textContent = 'The longest-running rivalries in league history.';
    Array.from(section.children).forEach(function (el) {
      if (!el.querySelector('#rivalries') && el.id !== 'conf-rivalry-note' && !el.classList.contains('section-label')
          && el.id !== 'conf-title') el.style.display = 'none';
    });
    section.querySelectorAll('.rivalry-table th:last-child').forEach(function (th) { th.style.display = 'none'; });
    var pill = document.querySelector('.jump-nav-pill[data-target="conference-analysis"]');
    if (pill) pill.textContent = 'Rivalries';
    RIVALRIES = listedRivalries(C.rivalries);
    document.getElementById('rivalries').innerHTML = RIVALRIES.map(function (x) {
      var a = x.first_wins, b = x.second_wins;
      return '<tr><td>' + esc(mgr.name(x.first_key)) + ' vs ' + esc(mgr.name(x.second_key)) + '</td><td>'
        + esc(Math.max(a, b) + '-' + Math.min(a, b) + ' ' + (a === b ? 'Tied' : mgr.short(a > b ? x.first_key : x.second_key)))
        + '</td><td>' + x.games + '</td></tr>';
    }).join('');
    rivalryNote({});
    return;
  }
  var cls = function (c) { return 'conf-' + (index[c] !== undefined ? index[c] : order.indexOf(c)); };
  var badge = function (c) { return c ? '<span class="conf-badge ' + cls(c) + '">' + esc(c) + '</span>' : ''; };
  var first = order[0], last = order[order.length - 1];
  var firstSeason = MODEL.seasons[0];

  document.getElementById('conf-title').textContent = 'Does ' + order.join(' or ') + ' actually mean anything?';
  document.getElementById('conf-background').innerHTML = (C.moved && C.moved.length
    ? 'Every manager plays in a conference, ' + esc(order.join(' or ')) + ', since ' + firstSeason + '. Assignments changed for '
      + esc(andList(C.moved.map(mgr.name))) + '; each is shown in their latest conference.'
    : 'Every manager has been locked into a conference, ' + esc(order.join(' or ')) + ', since ' + firstSeason
      + '. It’s <strong>never reshuffled</strong> season to season.')
    + ' The question is whether it predicts anything about performance, or if it’s just a fun label.';

  var members = C.managers.slice().sort(function (a, b) {
    return (order.indexOf(a.conference) - order.indexOf(b.conference)) || (b.win_pct - a.win_pct)
      || (mgr.name(a.manager_key) < mgr.name(b.manager_key) ? -1 : 1);
  });
  document.getElementById('conf-teams').innerHTML = order.map(function (c) {
    var chips = members.filter(function (m) { return m.conference === c; })
      .sort(function (a, b) { return mgr.name(a.manager_key) < mgr.name(b.manager_key) ? -1 : 1; })
      .map(function (m) {
        var logo = mgr.logo(m.manager_key);
        return '<div class="conf-team-chip">' + (logo ? '<img src="' + esc(logo) + '" alt="" onerror="this.remove()">' : '')
          + '<span>' + esc(mgr.name(m.manager_key)) + '</span></div>';
      }).join('');
    return '<div class="conf-teams-col conf-col-' + cls(c).slice(5) + ' glass"><div class="conf-teams-header ' + cls(c) + '-text">'
      + esc(c) + '</div><div class="conf-teams-list">' + chips + '</div></div>';
  }).join('');

  var S = {};
  C.summary.forEach(function (row) { S[row.conference] = row; });
  var CARDS = [['Championships', 'titles', 0], ['Title Game Trips', 'title_games', 0], ['Playoff Trips', 'playoff_trips', 0],
               ['H2H Regular Season', 'wins_regular', 0], ['H2H Playoffs', 'wins_playoff', 0], ['Avg PF/Game', 'pf_per_game', 1]];
  var val = function (c, col, d) { var v = S[c] && S[c][col]; return v == null ? '-' : d ? Number(v).toFixed(d) : String(Math.round(v)); };
  document.getElementById('conf-cards').innerHTML = CARDS.map(function (card) {
    return '<div class="conf-stat-card glass"><div class="conf-stat-label">' + card[0] + '</div><div class="conf-stat-vals">'
      + order.map(function (c) {
        return '<div class="conf-stat-val"><div class="conf-stat-num ' + cls(c) + '-text">' + val(c, card[1], card[2])
          + '</div><div class="conf-stat-tag ' + cls(c) + '-text">' + esc(c) + '</div></div>';
      }).join('') + '</div></div>';
  }).join('');

  document.getElementById('conf-managers').innerHTML = members.map(function (m) {
    return '<tr><td class="conf-mgr-name">' + esc(mgr.name(m.manager_key)) + '</td><td>' + badge(m.conference) + '</td>'
      + '<td class="num">' + m.wins + '-' + m.losses + '</td><td class="num">' + pct3(m.win_pct) + '</td>'
      + '<td class="num">' + m.pf_per_game.toFixed(1) + '</td><td class="num">' + m.pa_per_game.toFixed(1) + '</td>'
      + '<td class="num attr-' + (m.margin >= 0 ? 'good' : 'bad') + '">' + (m.margin >= 0 ? '+' : '') + m.margin.toFixed(1) + '</td></tr>';
  }).join('');

  // the season table reads the record from the last conference's side, as the Stage A page did
  var seasons = C.seasons.filter(function (x) { return x.conference === last; }).sort(function (a, b) { return a.season - b.season; });
  document.getElementById('conf-seasons-hint').textContent = 'Interconference record by season, ' + last + '-' + first + '.';
  document.getElementById('conf-seasons-pct').textContent = last + ' Win%';
  document.getElementById('conf-seasons').innerHTML = seasons.map(function (x) {
    return '<tr><td><span class="season-pill" style="background:' + (SEASON_COLORS[x.season] || 'var(--muted)') + '">'
      + esc(seasonLabel(x.season)) + '</span></td><td class="num">' + x.wins + '-' + x.losses + '</td><td class="num">'
      + pct3(x.win_pct) + '</td><td class="num">' + x.games + '</td></tr>';
  }).join('');

  var confOf = {};
  C.managers.forEach(function (m) { confOf[m.manager_key] = m.conference; });
  RIVALRIES = listedRivalries(C.rivalries);
  document.getElementById('rivalries').innerHTML = RIVALRIES.map(function (x) {
    var a = x.first_wins, b = x.second_wins;
    var rec = Math.max(a, b) + '-' + Math.min(a, b) + ' ' + (a === b ? 'Tied' : mgr.short(a > b ? x.first_key : x.second_key));
    return '<tr><td>' + esc(mgr.name(x.first_key)) + ' vs ' + esc(mgr.name(x.second_key)) + '</td><td>' + esc(rec) + '</td><td>'
      + x.games + '</td><td>' + badge(confOf[x.first_key]) + ' ' + badge(confOf[x.second_key]) + '</td></tr>';
  }).join('');

  conferenceNotes(order, S, members, seasons, confOf);
}

/* The rivalry table: most meetings, then the closest record, then the pair by name, each pair
   written with the alphabetically first name first (matchup_history.order_rivalries); the first 8. */
var RIVALRIES_LISTED = 8, RIVALRIES = [];
function listedRivalries(all) {
  var cmp = function (x, y) { return x < y ? -1 : x > y ? 1 : 0; };
  return all.map(function (x) {
    var flip = mgr.name(x.first_key) > mgr.name(x.second_key);
    return flip ? { first_key: x.second_key, second_key: x.first_key, first_wins: x.second_wins, second_wins: x.first_wins, games: x.games } : x;
  }).sort(function (a, b) {
    return (b.games - a.games) || (Math.abs(a.first_wins - a.second_wins) - Math.abs(b.first_wins - b.second_wins))
      || cmp(mgr.name(a.first_key), mgr.name(b.first_key)) || cmp(mgr.name(a.second_key), mgr.name(b.second_key));
  }).slice(0, RIVALRIES_LISTED);
}

function conferenceNotes(order, S, members, seasons, confOf) {
  var first = order[0], last = order[order.length - 1];
  var n = function (c, col) { return S[c] ? Number(S[c][col]) : 0; };
  var rec = function (col) {
    var a = n(first, col), b = n(last, col);
    return '<strong>' + Math.max(a, b) + '-' + Math.min(a, b) + (a === b ? ', even' : ', ' + esc(a > b ? first : last)) + '</strong>';
  };
  var byTrips = order.slice().sort(function (a, b) { return (n(b, 'title_games') - n(a, 'title_games')) || (n(b, 'titles') - n(a, 'titles')); });
  var slots = order.reduce(function (t, c) { return t + n(c, 'title_games'); }, 0);
  var lead = byTrips[0], other = byTrips[1];
  document.getElementById('conf-summary-note').innerHTML = 'Playoff trips: ' + order.map(function (c) { return esc(c) + ' ' + n(c, 'playoff_trips'); }).join(', ')
    + '. Scoring: ' + order.map(function (c) { return esc(c) + ' ' + n(c, 'pf_per_game').toFixed(1); }).join(', ') + ' points per game. '
    + 'Head-to-head, the regular season stands at ' + rec('wins_regular') + ' and the playoffs at ' + rec('wins_playoff') + '. '
    + esc(lead) + ' has reached <strong>' + n(lead, 'title_games') + ' of ' + slots + ' possible championship games</strong> and won '
    + n(lead, 'titles') + ', while ' + esc(other) + ' has reached ' + n(other, 'title_games') + ' and won ' + n(other, 'titles') + '.';

  var losing = members.filter(function (m) { return m.win_pct < 0.5 && m.margin > 0; });
  var winning = members.filter(function (m) { return m.win_pct > 0.5 && m.margin < 0; });
  var odd = losing.map(function (m) { return '<strong>' + esc(mgr.name(m.manager_key)) + '</strong> has a losing record (' + pct3(m.win_pct) + ') despite a positive margin'; })
    .concat(winning.map(function (m) { return '<strong>' + esc(mgr.name(m.manager_key)) + '</strong> has a winning record (' + pct3(m.win_pct) + ') despite a negative one'; }));
  var outEl = document.getElementById('conf-outliers-note');
  if (odd.length) outEl.innerHTML = title(numberWord(odd.length)) + ' manager' + (odd.length > 1 ? 's stand' : ' stands') + ' out: ' + andList(odd) + '.';
  else outEl.remove();

  var best = function (side) {
    var rows = seasons.map(function (x) { return { s: x.season, p: side === last ? x.win_pct : 1 - x.win_pct }; })
      .filter(function (x) { return String(x.s) !== String(PAGE_LIVE_SEASON); })
      .sort(function (a, b) { return b.p - a.p; });
    return rows[0];
  };
  var bf = best(first), bl = best(last);
  var sEl = document.getElementById('conf-seasons-note');
  if (bf && bl) {
    sEl.innerHTML = '<strong>' + bf.s + ' was ' + esc(first) + '’s best season</strong> against ' + esc(last) + ' (' + pct3(bf.p)
      + '), and <strong>' + bl.s + ' was ' + esc(last) + '’s</strong> (' + pct3(bl.p) + ').';
  } else sEl.remove();

  rivalryNote(confOf);
}

function rivalryNote(confOf) {
  var riv = RIVALRIES, rEl = document.getElementById('conf-rivalry-note');
  if (!riv.length) { rEl.remove(); return; }
  var most = riv[0].games, top = riv.filter(function (x) { return x.games === most; });
  var pair = function (x) { return mgr.name(x.first_key) + ' vs ' + mgr.name(x.second_key); };
  var cross = function (x) { return confOf[x.first_key] !== confOf[x.second_key]; };
  var text = top.length === 1
    ? 'The longest feud in league history is <strong>' + esc(pair(top[0])) + ' at ' + most + ' meetings</strong>, '
      + (!confOf[top[0].first_key] ? 'and counting.' : cross(top[0]) ? 'crossing party lines.' : 'inside one conference.')
    : 'The longest feuds in league history run <strong>' + most + ' meetings</strong>: ' + esc(andList(top.map(pair))) + '.';
  var lop = riv.slice().sort(function (a, b) {
    return (Math.abs(b.first_wins - b.second_wins) / b.games - Math.abs(a.first_wins - a.second_wins) / a.games) || (b.games - a.games);
  })[0];
  if (lop.first_wins !== lop.second_wins) {
    var aw = lop.first_wins > lop.second_wins, wk = aw ? lop.first_key : lop.second_key, lk = aw ? lop.second_key : lop.first_key;
    text += ' The most one-sided of these: <strong>' + esc(mgr.name(wk).split(' ')[0]) + ' owns ' + esc(mgr.name(lk).split(' ')[0]) + ' '
      + Math.max(lop.first_wins, lop.second_wins) + '-' + Math.min(lop.first_wins, lop.second_wins) + '</strong>.';
  }
  rEl.innerHTML = text;
}

/* ---------------------------------------------------------------- the Stage A page script */

function runPage() {
/* ══════════════════════════════════════
   Extra Analytics - all four sections
   ══════════════════════════════════════ */

Chart.defaults.font.family = "'Outfit', sans-serif";
Chart.defaults.font.size   = 12;
Chart.defaults.color       = '#5a5550';

var C_TEXT_MID = '#5a5550';
var C_MUTED    = '#8a8480';
var C_GREEN    = '#5a8a5a';
var C_RED      = '#a85a5a';
var C_GOLD     = '#d4af37';
var C_ACCENT   = '#9c949c';

function gridStyle() { return { color:'rgba(156,148,156,0.15)', drawBorder:false }; }
function tickStyle() { return { color: C_MUTED }; }

function shortName(n) {
  var p = n.split(' ');
  return p.length < 2 ? n : p[0] + ' ' + p[p.length-1][0] + '.';
}

/* ── 1. SCHEDULE LUCK ─────────────────────────────────────────────────────── */
(function() {
  // Sorted unlucky → lucky (ascending luck delta); Career, or one season (schedule_luck.seasons)
  var luckChart = null;
  function renderLuck(season) {
  var luckData = season === 'career' ? D.luckData : seasonLuck(MODEL, season, mgr.name);

  var labels = luckData.map(function(d){ return shortName(d.name); });
  var deltas = luckData.map(function(d){ return d.luck; });
  var actual = luckData.map(function(d){ return d.actual; });
  var pred   = luckData.map(function(d){ return d.predicted; });

  var bgColors = deltas.map(function(v){
    return v > 0 ? 'rgba(90,138,90,0.72)' : v < 0 ? 'rgba(168,90,90,0.72)' : 'rgba(212,175,55,0.72)';
  });
  var bdColors = deltas.map(function(v){
    return v > 0 ? 'rgba(90,138,90,1)' : v < 0 ? 'rgba(168,90,90,1)' : 'rgba(212,175,55,1)';
  });

  // Zero-line plugin
  var zeroPlugin = {
    id: 'zeroLine',
    afterDraw: function(chart) {
      var ctx2  = chart.ctx;
      var xAxis = chart.scales.x;
      var yAxis = chart.scales.y;
      var x0 = xAxis.getPixelForValue(0);
      ctx2.save();
      ctx2.strokeStyle = 'rgba(138,132,128,0.45)';
      ctx2.lineWidth = 1.5;
      ctx2.setLineDash([4, 3]);
      ctx2.beginPath();
      ctx2.moveTo(x0, yAxis.top);
      ctx2.lineTo(x0, yAxis.bottom);
      ctx2.stroke();
      ctx2.restore();
    }
  };

  if (luckChart) luckChart.destroy();
  luckChart = new Chart(document.getElementById('chart-luck').getContext('2d'), {
    type: 'bar',
    data: {
      labels: labels,
      datasets: [{
        label: 'Gifted Wins',
        data: deltas,
        backgroundColor: bgColors,
        borderColor: bdColors,
        borderWidth: 1.5,
        borderRadius: 3,
      }]
    },
    options: {
      indexAxis: 'y',
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            title: function(items){ return luckData[items[0].dataIndex].name; },
            label: function(ctx) {
              var idx = ctx.dataIndex;
              var lv  = deltas[idx];
              var prefix = lv > 0 ? '+' : '';
              return [
                'Luck: ' + prefix + lv + ' wins vs expected',
                'Actual: ' + actual[idx] + 'W  |  Expected: ' + pred[idx] + 'W',
                season === 'career' ? 'Career' : seasonLabel(season),
              ];
            }
          }
        }
      },
      scales: {
        x: {
          grid: gridStyle(),
          ticks: Object.assign(tickStyle(), {
            stepSize: season === 'career' ? 2 : 1,
            callback: function(v){ return (v > 0 ? '+' : '') + v; }
          }),
          title: { display:true, text:'Gifted Wins (Actual minus Expected)', color:C_MUTED, font:{size:11} },
        },
        y: {
          grid: { display: false },
          ticks: Object.assign(tickStyle(), { font:{ size:12 } }),
        }
      }
    },
    plugins: [zeroPlugin]
  });
  }

  window.setLuckSeason = function(season, btn) {
    document.querySelectorAll('#luck-buttons .year-swatch-btn').forEach(function(b) { b.classList.remove('active'); });
    btn.classList.add('active');
    renderLuck(season);
  };
  var luckSeasons = Array.from(new Set(MODEL.schedule_luck.seasons.map(function(x) { return x.season; }))).sort();
  document.getElementById('luck-buttons').innerHTML =
    '<button class="fp-btn year-swatch-btn active" style="--swatch-color:var(--accent);" onclick="setLuckSeason(\'career\',this)">Career</button>' +
    luckSeasons.map(function(y) {
      return '<button class="fp-btn year-swatch-btn" style="--swatch-color:' + (SEASON_COLORS[y] || 'var(--muted)') +
        ';" data-year="' + y + '" onclick="setLuckSeason(' + y + ',this)">' + seasonLabel(y) + '</button>';
    }).join('');
  renderLuck('career');
})();

var SCHEDULE_SWAP_DATA = D.SCHEDULE_SWAP_DATA;
/* ── 4. SCHEDULE SWAP ─────────────────────────────────────────────────────── */
(function() {
  // Shown above the table only for seasons with a real data wrinkle worth flagging, from the league's
  // editorial file (notes.swap_caveats). No entry means no caveat that season.
  var SS_CAVEATS = (MODEL.notes && MODEL.notes.swap_caveats) || {};

  var SS_SEASON_LENGTH = Math.max.apply(null, (cfg.seasons || []).map(function(x) { return x.regular_season_weeks || 0; }).concat([1]));
  // regular-season games per season (the live season: the weeks played so far), written by the build
  var SS_SEASON_GAMES = D.SS_SEASON_GAMES;
  function ssLen(year) { return SS_SEASON_GAMES[String(year)] || SS_SEASON_LENGTH; }

  function ssCellClass(gain) {
    if (gain >= 2.5)  return 'win-high';
    if (gain >= 1.0)  return 'win-mid';
    if (gain > -1.0)  return 'even';
    if (gain > -2.5)  return 'loss-mid';
    return 'loss-high';
  }

  function renderScheduleSwap(year) {
    var seasonData = SCHEDULE_SWAP_DATA[String(year)];
    if (!seasonData) return;
    var managers = Object.keys(seasonData);

    var caveatEl = document.getElementById('ss-caveat');
    var caveatText = SS_CAVEATS[String(year)] || '';
    if (caveatText) {
      caveatEl.innerHTML = caveatText;
      caveatEl.classList.add('visible');
    } else {
      caveatEl.classList.remove('visible');
    }

    var table = document.getElementById('ss-table');
    table.innerHTML = '';

    // Header row
    var thead = document.createElement('thead');
    var hrow = document.createElement('tr');
    var th0 = document.createElement('th');
    th0.className = 'row-header';
    th0.textContent = 'Manager';
    hrow.appendChild(th0);
    managers.forEach(function(m) {
      var th = document.createElement('th');
      th.textContent = shortName(m);
      hrow.appendChild(th);
    });
    ['Actual','Avg (' + ssLen(year) + 'g)','Wins +/-'].forEach(function(label) {
      var th = document.createElement('th');
      th.className = 'ss-summary-head';
      th.textContent = label;
      hrow.appendChild(th);
    });
    thead.appendChild(hrow);
    table.appendChild(thead);

    // Body rows
    var tbody = document.createElement('tbody');
    managers.forEach(function(mgr) {
      var d = seasonData[mgr];
      var tr = document.createElement('tr');

      var nameTd = document.createElement('td');
      nameTd.textContent = shortName(mgr);
      tr.appendChild(nameTd);

      managers.forEach(function(col) {
        var td = document.createElement('td');
        if (col === mgr) {
          td.className = 'self';
          td.textContent = d.actual.w + '-' + d.actual.l;
          td.title = shortName(mgr) + '\u2019s actual record: ' + d.actual.w + '-' + d.actual.l;
        } else {
          var alt = d.alt[col];
          if (alt) {
            var gain = (alt.pct - d.actual.pct) * ssLen(year);
            td.className = ssCellClass(gain);
            td.textContent = alt.w + '-' + alt.l;
            td.title = shortName(mgr) + ' wearing ' + shortName(col) + '\u2019s schedule: ' +
              alt.w + '-' + alt.l + ' (' + alt.games + ' games, ' + Math.round(alt.pct * 100) + '%)';
          } else {
            td.textContent = '';
          }
        }
        tr.appendChild(td);
      });

      var actualTd = document.createElement('td');
      actualTd.className = 'ss-summary';
      actualTd.textContent = d.actual.w + '-' + d.actual.l;
      actualTd.title = 'Win% ' + d.actual.pct.toFixed(3);
      tr.appendChild(actualTd);

      var avgWins = d.avg_pct * ssLen(year);
      var avgTd = document.createElement('td');
      avgTd.className = 'ss-summary';
      avgTd.textContent = avgWins.toFixed(1);
      avgTd.title = 'Average win% across all other managers\u2019 schedules: ' + d.avg_pct.toFixed(3);
      tr.appendChild(avgTd);

      var diffTd = document.createElement('td');
      diffTd.className = 'ss-summary ' + (d.wins_gained >= 0 ? 'val-green' : 'val-red');
      diffTd.textContent = (d.wins_gained > 0 ? '+' : '') + d.wins_gained.toFixed(1);
      tr.appendChild(diffTd);

      tbody.appendChild(tr);
    });
    table.appendChild(tbody);
  }

  window.setSsYear = function(year, btn) {
    document.querySelectorAll('#schedule-swap .year-swatch-btn').forEach(function(b) {
      b.classList.remove('active');
    });
    btn.classList.add('active');
    renderScheduleSwap(year);
  };

  // one button per season in the data (the build writes SCHEDULE_SWAP_DATA)
  var ssYears = Object.keys(SCHEDULE_SWAP_DATA).sort();
  document.getElementById('ss-year-buttons').innerHTML = ssYears.map(function(y, i) {
    return '<button class="fp-btn year-swatch-btn' + (i === 0 ? ' active' : '') + '" style="--swatch-color:' +
      (SEASON_COLORS[y] || 'var(--muted)') + ';" data-year="' + y + '" onclick="setSsYear(' + y + ',this)">' + seasonLabel(y) + '</button>';
  }).join('');
  renderScheduleSwap(Number(ssYears[0]));
})();

/* ── 2. QUARTERLY REGRESSION ─────────────────────────────────────────────── */
if (D.labels) (function() {
  var labels = D.labels;
  var coefs  = D.coefs;
  var corrs  = D.corrs;
  var pvals  = D.pvals;

  function pLabel(p) { return p < 0.01 ? '***' : p < 0.05 ? '**' : p < 0.1 ? '*' : ''; }

  // Gradient green by value
  function greenScale(vals, alpha) {
    var mn = Math.min.apply(null, vals), mx = Math.max.apply(null, vals);
    return vals.map(function(v) {
      var t = mx !== mn ? (v - mn) / (mx - mn) : 0.5;
      var r = Math.round(180 + (40  - 180) * t);
      var g = Math.round(220 + (120 - 220) * t);
      var b = Math.round(180 + (70  - 180) * t);
      return 'rgba('+r+','+g+','+b+','+alpha+')';
    });
  }

  // Chart 1: Coefficients
  new Chart(document.getElementById('chart-q-coef').getContext('2d'), {
    type: 'bar',
    data: {
      labels: labels,
      datasets: [{
        label: 'Coefficient',
        data: coefs,
        backgroundColor: greenScale(coefs, 0.75),
        borderColor: greenScale(coefs, 1.0),
        borderWidth: 1.5,
        borderRadius: 3,
      }]
    },
    options: {
      responsive: true,
      plugins: {
        legend: { display:false },
        tooltip: {
          callbacks: {
            label: function(ctx) {
              var p = pvals[ctx.dataIndex];
              return 'Coef: +' + ctx.parsed.y.toFixed(3) + '  p=' + p.toFixed(3) + pLabel(p);
            }
          }
        },
        title: {
          display: true,
          text: 'Logistic Regression Coefficients' + (MODEL.quarterly_fit ? '  |  AUC ' + MODEL.quarterly_fit.auc.toFixed(2) : ''),
          color: C_TEXT_MID,
          font: { size:12, weight:'600' },
          padding: { bottom:12 }
        }
      },
      scales: {
        x: { grid:gridStyle(), ticks:Object.assign(tickStyle(), { font:{size:11} }) },
        y: {
          grid: gridStyle(), ticks: tickStyle(),
          title: { display:true, text:'Coefficient', color:C_MUTED, font:{size:11} },
          min: 0,
        }
      }
    }
  });

  // Chart 2: Correlations
  new Chart(document.getElementById('chart-q-corr').getContext('2d'), {
    type: 'bar',
    data: {
      labels: labels,
      datasets: [{
        label: 'Pearson r',
        data: corrs,
        backgroundColor: greenScale(corrs, 0.75),
        borderColor: greenScale(corrs, 1.0),
        borderWidth: 1.5,
        borderRadius: 3,
      }]
    },
    options: {
      responsive: true,
      plugins: {
        legend: { display:false },
        tooltip: {
          callbacks: {
            label: function(ctx) { return 'Pearson r: ' + ctx.parsed.y.toFixed(3); }
          }
        },
        title: {
          display: true,
          text: 'Pearson Correlation with Playoff Appearance',
          color: C_TEXT_MID,
          font: { size:12, weight:'600' },
          padding: { bottom:12 }
        }
      },
      scales: {
        x: { grid:gridStyle(), ticks:Object.assign(tickStyle(), { font:{size:11} }) },
        y: {
          grid: gridStyle(), ticks: tickStyle(),
          title: { display:true, text:'Pearson r', color:C_MUTED, font:{size:11} },
          min: 0,
        }
      }
    }
  });
})();

/* ── POSITIONAL PRODUCTION ────────────────────────────────────────────────── */
if (D.labels) (function() {
  var POSITIONS = D.POSITIONS;

  // Career averages and career std dev (week-to-week volatility) of started
  // points per position, real games only (consolation weeks excluded).
  var DATA = D.DATA;

  // Standardized regression coefficients (relative importance, Win% ~ position avgs, n=83)
  var STD_COEF = D.STD_COEF;
  var COEF_PVAL = D.COEF_PVAL;
  // Simple Pearson correlation of each position's season avg with that season's Win%
  var CORR_R = D.CORR_R;

  var posView = 'avg';          // 'avg' or 'std'
  var sortKey = 'winpct';
  var sortDir = 'desc';

  // Red (bad) -> gold (mid) -> green (good), using this page's own color
  // constants, scaled to the min/max of the column being displayed.
  function gradeColor(value, min, max, invert) {
    if (max === min) return 'transparent';
    var t = (value - min) / (max - min);
    if (invert) t = 1 - t;
    var stops = t <= 0.5
      ? [hexToRgb(C_RED), hexToRgb(C_GOLD), t * 2]
      : [hexToRgb(C_GOLD), hexToRgb(C_GREEN), (t - 0.5) * 2];
    var a = stops[0], b = stops[1], f = stops[2];
    var r = Math.round(a[0] + (b[0]-a[0])*f);
    var g = Math.round(a[1] + (b[1]-a[1])*f);
    var bl = Math.round(a[2] + (b[2]-a[2])*f);
    return 'rgba(' + r + ',' + g + ',' + bl + ',0.32)';
  }
  function hexToRgb(hex) {
    hex = hex.replace('#','');
    return [parseInt(hex.substr(0,2),16), parseInt(hex.substr(2,2),16), parseInt(hex.substr(4,2),16)];
  }

  function renderPosTable() {
    var tbody = document.getElementById('pos-tbody');
    var valField = posView === 'avg' ? 'avg' : 'std';

    // Column min/max for gradient scaling
    var ranges = {winpct:[Infinity,-Infinity]};
    POSITIONS.forEach(function(p){ ranges[p] = [Infinity,-Infinity]; });
    DATA.forEach(function(d) {
      ranges.winpct[0] = Math.min(ranges.winpct[0], d.winpct);
      ranges.winpct[1] = Math.max(ranges.winpct[1], d.winpct);
      POSITIONS.forEach(function(p) {
        var v = d[valField][p];
        ranges[p][0] = Math.min(ranges[p][0], v);
        ranges[p][1] = Math.max(ranges[p][1], v);
      });
    });

    var rows = DATA.slice();
    rows.sort(function(a, b) {
      var av = sortKey === 'manager' ? a.mgr : (sortKey === 'winpct' ? a.winpct : a[valField][sortKey]);
      var bv = sortKey === 'manager' ? b.mgr : (sortKey === 'winpct' ? b.winpct : b[valField][sortKey]);
      if (sortKey === 'manager') return sortDir === 'asc' ? av.localeCompare(bv) : bv.localeCompare(av);
      return sortDir === 'asc' ? av - bv : bv - av;
    });

    // For "Consistency" view, LOWER std dev is better (more consistent), so invert the color scale
    var invert = posView === 'std';

    tbody.innerHTML = rows.map(function(d) {
      var winBg = gradeColor(d.winpct, ranges.winpct[0], ranges.winpct[1], false);
      var cells = POSITIONS.map(function(p) {
        var v = d[valField][p];
        var bg = gradeColor(v, ranges[p][0], ranges[p][1], invert);
        return '<td class="pos-grad" style="background:' + bg + ';">' + v.toFixed(1) + '</td>';
      }).join('');
      return '<tr><td class="pos-mgr">' + d.mgr + '</td>'
        + '<td class="pos-grad" style="background:' + winBg + ';">' + d.winpct.toFixed(1) + '</td>'
        + cells + '</tr>';
    }).join('');
  }

  window.setPosView = function(view, btn) {
    posView = view;
    document.querySelectorAll('.season-filter-row .season-btn').forEach(function(b){
      if (b.closest('.season-filter-row') === btn.closest('.season-filter-row')) b.classList.remove('active');
    });
    btn.classList.add('active');
    document.getElementById('pos-table-hint').textContent = view === 'avg'
      ? 'Career average weekly points per position, started lineups only. Click any column to sort.'
      : 'Career week-to-week std dev per position (lower = more consistent). Click any column to sort.';
    renderPosTable();
  };

  document.querySelectorAll('#pos-table th.pos-sortable').forEach(function(th) {
    th.addEventListener('click', function() {
      var key = th.getAttribute('data-key');
      if (sortKey === key) {
        sortDir = sortDir === 'asc' ? 'desc' : 'asc';
      } else {
        sortKey = key;
        sortDir = key === 'manager' ? 'asc' : 'desc';
      }
      document.querySelectorAll('#pos-table th.pos-sortable').forEach(function(t) {
        t.classList.remove('sort-asc', 'sort-desc');
      });
      th.classList.add(sortDir === 'asc' ? 'sort-asc' : 'sort-desc');
      renderPosTable();
    });
  });

  renderPosTable();

  // Bar charts: standardized coefficients + simple correlations by position
  function posColors(vals, alpha) {
    var mn = Math.min.apply(null, vals), mx = Math.max.apply(null, vals);
    return vals.map(function(v) {
      var t = mx !== mn ? (v - mn) / (mx - mn) : 0.5;
      var r = Math.round(180 + (40  - 180) * t);
      var g = Math.round(220 + (120 - 220) * t);
      var b = Math.round(180 + (70  - 180) * t);
      return 'rgba('+r+','+g+','+b+','+alpha+')';
    });
  }

  var coefVals = POSITIONS.map(function(p){ return STD_COEF[p]; });
  var corrVals = POSITIONS.map(function(p){ return CORR_R[p]; });

  function pLabel(p) { return p < 0.01 ? '***' : p < 0.05 ? '**' : p < 0.1 ? '*' : ''; }

  new Chart(document.getElementById('chart-pos-coef').getContext('2d'), {
    type: 'bar',
    data: {
      labels: POSITIONS,
      datasets: [{
        label: 'Standardized coefficient',
        data: coefVals,
        backgroundColor: posColors(coefVals, 0.75),
        borderColor: posColors(coefVals, 1.0),
        borderWidth: 1.5,
        borderRadius: 3
      }]
    },
    options: {
      responsive: true,
      plugins: {
        legend: { display:false },
        tooltip: {
          callbacks: {
            label: function(ctx) {
              var pos = POSITIONS[ctx.dataIndex];
              var p = COEF_PVAL[pos];
              return 'Std coef: +' + ctx.parsed.y.toFixed(3) + '  p=' + p.toFixed(4) + pLabel(p);
            }
          }
        },
        title: {
          display: true,
          text: 'Standardized Coefficients  |  Win% ~ Position Avg' + (MODEL.positional.fit ? ', R\u00b2 ' + MODEL.positional.fit.r2.toFixed(2) : ''),
          color: C_TEXT_MID,
          font: { size:12, weight:'600' },
          padding: { bottom:12 }
        }
      },
      scales: {
        x: { grid:gridStyle(), ticks:Object.assign(tickStyle(), { font:{size:11} }) },
        y: {
          grid: gridStyle(), ticks: tickStyle(),
          title: { display:true, text:'Relative importance', color:C_MUTED, font:{size:11} },
          min: 0
        }
      }
    }
  });

  new Chart(document.getElementById('chart-pos-corr').getContext('2d'), {
    type: 'bar',
    data: {
      labels: POSITIONS,
      datasets: [{
        label: 'Pearson r',
        data: corrVals,
        backgroundColor: posColors(corrVals, 0.75),
        borderColor: posColors(corrVals, 1.0),
        borderWidth: 1.5,
        borderRadius: 3
      }]
    },
    options: {
      responsive: true,
      plugins: {
        legend: { display:false },
        tooltip: {
          callbacks: { label: function(ctx) { return 'Pearson r: ' + ctx.parsed.y.toFixed(3); } }
        },
        title: {
          display: true,
          text: 'Simple Correlation with Season Win%',
          color: C_TEXT_MID,
          font: { size:12, weight:'600' },
          padding: { bottom:12 }
        }
      },
      scales: {
        x: { grid:gridStyle(), ticks:Object.assign(tickStyle(), { font:{size:11} }) },
        y: {
          grid: gridStyle(), ticks: tickStyle(),
          title: { display:true, text:'Pearson r', color:C_MUTED, font:{size:11} },
          min: 0
        }
      }
    }
  });
})();

/* ── WIN% ATTRIBUTION ─────────────────────────────────────────────────────── */
if (D.labels) (function() {
  var DATA = D['DATA#1'];
  var LEAGUE_INTERCEPT = D.LEAGUE_INTERCEPT;
  var STEPS = ['draft','waiver','lineup','trade','luck'];
  var STEP_LABELS = {draft:'Draft', waiver:'Waiver', lineup:'Lineup', trade:'Trade', luck:'Luck'};

  var managers = Object.keys(DATA).sort();
  var currentMgr = managers[0];
  var waterfallChart = null;

  function renderPills() {
    var el = document.getElementById('attr-mgr-pills');
    el.innerHTML = managers.map(function(m) {
      var short = m;
      return '<button class="attr-mgr-pill' + (m===currentMgr?' active':'') + '" onclick="setAttrManager(\''+m+'\')">' + short + '</button>';
    }).join('');
  }

  window.setAttrManager = function(mgr) {
    currentMgr = mgr;
    document.querySelectorAll('.attr-mgr-pill').forEach(function(p, i) {
      p.classList.toggle('active', managers[i] === mgr);
    });
    renderWaterfall();
    renderSummary();
  };

  function renderSummary() {
    var d = DATA[currentMgr];
    document.getElementById('attr-actual').textContent = d.winpct.toFixed(1) + '%';
    document.getElementById('attr-predicted').textContent = d.predicted.toFixed(1) + '%';
    var resEl = document.getElementById('attr-residual');
    var sign = d.residual >= 0 ? '+' : '';
    resEl.textContent = sign + d.residual.toFixed(1) + 'pp';
    resEl.className = 'attr-stat-num ' + (d.residual >= 0 ? 'attr-good' : 'attr-bad');
  }

  function renderWaterfall() {
    var d = DATA[currentMgr];
    var labels = ['League avg'];
    STEPS.forEach(function(s){ labels.push(STEP_LABELS[s]); });
    labels.push('Predicted', 'Actual');

    var cum = LEAGUE_INTERCEPT;
    var bars = [[0, LEAGUE_INTERCEPT]];
    var colors = ['rgba(156,148,156,0.55)'];
    STEPS.forEach(function(s) {
      var v = d[s];
      var start = cum;
      cum += v;
      bars.push([Math.min(start,cum), Math.max(start,cum)]);
      colors.push(v >= 0 ? 'rgba(90,138,90,0.8)' : 'rgba(168,90,90,0.8)');
    });
    bars.push([0, d.predicted]);
    colors.push('rgba(156,132,156,0.75)');
    bars.push([0, d.winpct]);
    colors.push('rgba(212,175,55,0.85)');

    if (waterfallChart) { waterfallChart.destroy(); }
    var ctx = document.getElementById('chart-waterfall').getContext('2d');
    waterfallChart = new Chart(ctx, {
      type: 'bar',
      data: {
        labels: labels,
        datasets: [{
          data: bars,
          backgroundColor: colors,
          borderRadius: 4,
          borderSkipped: false
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { display: false },
          tooltip: {
            callbacks: {
              label: function(ctx) {
                var i = ctx.dataIndex;
                if (i === 0) return 'League average: ' + LEAGUE_INTERCEPT.toFixed(1) + '%';
                if (i === labels.length - 2) return 'Model predicts: ' + d.predicted.toFixed(1) + '%';
                if (i === labels.length - 1) return 'Actual win%: ' + d.winpct.toFixed(1) + '%';
                var stepKey = STEPS[i-1];
                var v = d[stepKey];
                return STEP_LABELS[stepKey] + ': ' + (v>=0?'+':'') + v.toFixed(2) + 'pp';
              }
            }
          },
          title: {
            display: true,
            text: currentMgr + '  |  win% built step by step',
            color: C_TEXT_MID,
            font: { size: 13, weight: '600' },
            padding: { bottom: 14 }
          }
        },
        scales: {
          x: { grid: gridStyle(), ticks: Object.assign(tickStyle(), { font: { size: 11 } }) },
          y: {
            grid: gridStyle(), ticks: Object.assign(tickStyle(), { callback: function(v){ return v+'%'; } }),
            title: { display: true, text: 'Win%', color: C_MUTED, font: { size: 11 } }
          }
        }
      }
    });
  }

  renderPills();
  renderWaterfall();
  renderSummary();

  // Final standardized coefficients across all five factors
  var COEF_LABELS = D.COEF_LABELS;
  var COEF_VALS   = D.COEF_VALS;
  function attrGreenScale(vals, alpha) {
    var mn = Math.min.apply(null, vals), mx = Math.max.apply(null, vals);
    return vals.map(function(v) {
      var t = mx !== mn ? (v - mn) / (mx - mn) : 0.5;
      var r = Math.round(180 + (40  - 180) * t);
      var g = Math.round(220 + (120 - 220) * t);
      var b = Math.round(180 + (70  - 180) * t);
      return 'rgba('+r+','+g+','+b+','+alpha+')';
    });
  }
  new Chart(document.getElementById('chart-attr-coef').getContext('2d'), {
    type: 'bar',
    data: {
      labels: COEF_LABELS,
      datasets: [{
        data: COEF_VALS,
        backgroundColor: attrGreenScale(COEF_VALS, 0.75),
        borderColor: attrGreenScale(COEF_VALS, 1.0),
        borderWidth: 1.5,
        borderRadius: 3
      }]
    },
    options: {
      responsive: true,
      plugins: {
        legend: { display: false },
        tooltip: { callbacks: { label: function(ctx){ return 'Standardized weight: +' + ctx.parsed.y.toFixed(3); } } },
        title: { display: true, text: 'Relative Importance  |  ' + significantTitle(MODEL.attribution.coefficients), color: C_TEXT_MID, font: { size: 12, weight: '600' }, padding: { bottom: 12 } }
      },
      scales: {
        x: { grid: gridStyle(), ticks: Object.assign(tickStyle(), { font: { size: 11 } }) },
        y: { grid: gridStyle(), ticks: tickStyle(), title: { display: true, text: 'Standardized coefficient', color: C_MUTED, font: { size: 11 } }, min: 0 }
      }
    }
  });

  // The model's own refinement history -- R^2 at each methodology fix, in the
  // actual order those fixes were made (the league's editorial file; the current fit last)
  var R2_LABELS = D.R2_LABELS;
  var R2_VALS   = D.R2_VALS;
  new Chart(document.getElementById('chart-attr-r2').getContext('2d'), {
    type: 'bar',
    data: {
      labels: R2_LABELS,
      datasets: [{
        data: R2_VALS,
        backgroundColor: attrGreenScale(R2_VALS, 0.75),
        borderColor: attrGreenScale(R2_VALS, 1.0),
        borderWidth: 1.5,
        borderRadius: 3
      }]
    },
    options: {
      responsive: true,
      plugins: {
        legend: { display: false },
        tooltip: { callbacks: { label: function(ctx){ return 'R\u00b2 = ' + ctx.parsed.y.toFixed(3); } } },
        title: { display: true, text: r2Title(R2_VALS), color: C_TEXT_MID, font: { size: 12, weight: '600' }, padding: { bottom: 12 } }
      },
      scales: {
        x: { grid: gridStyle(), ticks: Object.assign(tickStyle(), { font: { size: 10 } }) },
        y: { grid: gridStyle(), ticks: tickStyle(), title: { display: true, text: 'R\u00b2', color: C_MUTED, font: { size: 11 } }, min: 0, max: Math.max(0.5, Math.ceil(Math.max.apply(null, R2_VALS) * 10) / 10) }
      }
    }
  });
})();

/* ── 3. H2H MATRIX ────────────────────────────────────────────────────────── */
(function() {
  var managers = D.managers;

  var h2h = D.h2h;

  function cellClass(pct) {
    if (pct === null)  return 'self';
    if (pct >= 0.7)    return 'win-high';
    if (pct >= 0.55)   return 'win-mid';
    if (pct >= 0.45)   return 'even';
    if (pct >= 0.3)    return 'loss-mid';
    return 'loss-high';
  }

  var table = document.getElementById('h2h-table');
  var shortNames = managers.map(shortName);

  // Header row
  var thead = document.createElement('thead');
  var hrow  = document.createElement('tr');
  var th0   = document.createElement('th');
  th0.className = 'row-header';
  th0.textContent = '';
  hrow.appendChild(th0);
  shortNames.forEach(function(sn) {
    var th = document.createElement('th');
    th.textContent = sn;
    hrow.appendChild(th);
  });
  thead.appendChild(hrow);
  table.appendChild(thead);

  // Body rows
  var tbody = document.createElement('tbody');
  managers.forEach(function(mgr, ri) {
    var tr = document.createElement('tr');
    var th = document.createElement('td');
    th.textContent = shortName(mgr);
    th.style.cssText = 'font-weight:600;color:var(--palm);';
    tr.appendChild(th);

    managers.forEach(function(opp, ci) {
      var td = document.createElement('td');
      if (mgr === opp) {
        td.className = 'self';
        td.textContent = '\u2013';
      } else {
        var rec = h2h[mgr] && h2h[mgr][opp];
        if (rec) {
          td.className = cellClass(rec.pct);
          td.textContent = rec.w + '-' + rec.l;
          td.title = shortName(mgr) + ' vs ' + shortName(opp) + ': ' + rec.w + '-' + rec.l + ' (' + Math.round(rec.pct*100) + '%)';
        } else {
          td.textContent = '\u2013';
          td.style.color = 'var(--muted)';
        }
      }
      tr.appendChild(td);
    });
    tbody.appendChild(tr);
  });
  table.appendChild(tbody);
})();

/* ── 5. CHAMPIONSHIP GAUNTLET ─────────────────────────────────────────────── */
if (D.labels) (function() {
  // Each champion's rank among every stretch of the same length in league history, computed by
  // applying the exact same Gauntlet Score methodology to every stretch any manager has faced, not
  // just championship runs (sameLength names a run that was not 3 weeks).
  var CHAMPION_RANKS = D.CHAMPION_RANKS;

  var CHAMPIONS = D.CHAMPIONS;

  // six tiers from hardest to easiest; with more (or fewer) than six champions each takes its
  // share of the tiers in order
  var TIER_COLORS  = ['#a85a5a','#b87060','#9c849c','#7a90a0','#6a9a7a','#5a8a6a'];
  var TIER_VERDICTS = ['Pure Gauntlet','Battle-Tested','Earned It','Smooth Operator','Favorable Draw','Cakewalk'];
  var tier = function(i) { return Math.min(TIER_COLORS.length - 1, Math.floor(i * TIER_COLORS.length / CHAMPIONS.length)); };
  var COLORS = CHAMPIONS.map(function(c, i) { return TIER_COLORS[tier(i)]; });
  var VERDICTS = CHAMPIONS.map(function(c, i) { return TIER_VERDICTS[tier(i)]; });

  // Gauntlet Spectrum -- fixed axis 25-75 (roughly +/-1 std dev on the logistic curve),
  // independent of these six samples, so the window won't shift as new champions are added.
  var SPEC_MIN = 20, SPEC_MAX = 80;
  function specPct(v) { return Math.max(0, Math.min(100, (v - SPEC_MIN) / (SPEC_MAX - SPEC_MIN) * 100)); }

  var spectrum = document.getElementById('gauntletSpectrum');
  var axisLine = document.createElement('div');
  axisLine.className = 'gspectrum-line';
  spectrum.appendChild(axisLine);

  var band = document.createElement('div');
  band.className = 'gspectrum-band';
  band.style.left = specPct(40) + '%';
  band.style.width = (specPct(60) - specPct(40)) + '%';
  spectrum.appendChild(band);

  var centerLine = document.createElement('div');
  centerLine.className = 'gspectrum-center';
  spectrum.appendChild(centerLine);
  var centerLbl = document.createElement('div');
  centerLbl.className = 'gspectrum-center-lbl';
  centerLbl.textContent = 'League Avg';
  spectrum.appendChild(centerLbl);

  [30,40,50,60,70].forEach(function(t) {
    var tick = document.createElement('div');
    tick.className = 'gspectrum-tick';
    tick.style.left = specPct(t) + '%';
    spectrum.appendChild(tick);
    var lbl = document.createElement('div');
    lbl.className = 'gspectrum-tick-lbl';
    lbl.style.left = specPct(t) + '%';
    lbl.textContent = t;
    spectrum.appendChild(lbl);
  });

  // Reference lines for the hardest/easiest of every three-week
  // stretch ever recorded (see the stretch section below), so the six
  // champions' scores can be read against the true scale, not just each
  // other. Labels anchor to whichever edge they're nearest (both values
  // sit close to the ends of the axis already) rather than centering on
  // the exact value -- centered text near an edge clips on narrow
  // screens, edge-anchored text never does, regardless of viewport width.
  [
    { val: HARDEST_ALL.length ? HARDEST_ALL[0].gs : null, label: 'Hardest stretch ever', color: '#a85a5a', align: 'end' },
    { val: EASIEST_ALL.length ? EASIEST_ALL[0].gs : null, label: 'Easiest stretch ever', color: '#5a8a6a', align: 'start' },
  ].filter(function(ext) { return ext.val !== null; }).forEach(function(ext) {
    var line = document.createElement('div');
    line.className = 'gspectrum-extreme';
    line.style.left = specPct(ext.val) + '%';
    line.style.background = 'repeating-linear-gradient(180deg,' + ext.color + ' 0 3px,transparent 3px 6px)';
    spectrum.appendChild(line);
    var elbl = document.createElement('div');
    elbl.className = 'gspectrum-extreme-lbl align-' + ext.align;
    elbl.style.color = ext.color;
    elbl.textContent = ext.label;
    spectrum.appendChild(elbl);
  });

  var byPos = CHAMPIONS.map(function(c,i){ return {c:c, origIndex:i}; }).sort(function(a,b){ return a.c.gs - b.c.gs; });
  var pinEls = {}, legendEls = {};
  byPos.forEach(function(item) {
    var c = item.c, i = item.origIndex;
    var pin = document.createElement('div');
    pin.className = 'gspectrum-pin';
    pin.style.left = specPct(c.gs) + '%';
    pin.innerHTML = '<div class="gspectrum-pin-dot" style="background:' + COLORS[i] + '"></div>';
    pin.title = c.champion + ' (' + c.year + ') -- Gauntlet Score ' + c.gs;
    pin.addEventListener('click', function() {
      var card = document.getElementById('gc' + i);
      if (card) card.scrollIntoView({ behavior: 'smooth', block: 'center' });
    });
    pin.addEventListener('mouseenter', function() { if (legendEls[i]) legendEls[i].classList.add('active'); });
    pin.addEventListener('mouseleave', function() { if (legendEls[i]) legendEls[i].classList.remove('active'); });
    spectrum.appendChild(pin);
    pinEls[i] = pin;
  });

  var legend = document.getElementById('gauntletSpectrumLegend');
  byPos.forEach(function(item) {
    var c = item.c, i = item.origIndex;
    var entry = document.createElement('div');
    entry.className = 'gspectrum-legend-item';
    entry.innerHTML = '<div class="gspectrum-legend-dot" style="background:' + COLORS[i] + '"></div>'
      + '<span class="gspectrum-legend-name">' + c.champion.split(' ')[0] + '</span>'
      + '<span class="gspectrum-legend-year">' + c.year + '</span>'
      + '<span class="gspectrum-legend-score">' + c.gs + '</span>';
    entry.addEventListener('click', function() {
      var card = document.getElementById('gc' + i);
      if (card) card.scrollIntoView({ behavior: 'smooth', block: 'center' });
    });
    entry.addEventListener('mouseenter', function() { pinEls[i].classList.add('active'); });
    entry.addEventListener('mouseleave', function() { pinEls[i].classList.remove('active'); });
    legend.appendChild(entry);
    legendEls[i] = entry;
  });

  var caption = document.createElement('div');
  caption.className = 'gspectrum-caption';
  caption.textContent = gauntletCaption(CHAMPIONS, CHAMPION_RANKS);
  legend.parentElement.appendChild(caption);

  // Cards
  var grid = document.getElementById('gauntletGrid');
  CHAMPIONS.forEach(function(c, i) {
    var col = COLORS[i];
    var domStr = (c.raw_dom >= 0 ? '+' : '') + c.raw_dom.toFixed(2);

    var card = document.createElement('div');
    card.className = 'gauntlet-card';
    card.id = 'gc' + i;

    var rk = CHAMPION_RANKS[c.year + '_' + c.champion];
    var rankLine = '';
    if (rk) {
      var topPct = (rk.rank / rk.total * 100).toFixed(1);
      var lengthWord = rk.sameLength ? rk.sameLength : 3;
      rankLine = '<div class="gauntlet-rank-line">Ranks #' + rk.rank + ' of ' + rk.total + ' ' + lengthWord + '-week stretches ever, top ' + topPct + '%</div>';
    }

    var header = document.createElement('div');
    header.className = 'gauntlet-card-header';
    header.innerHTML = '<div class="gauntlet-rank-badge" style="background:' + col + '">' + (i+1) + '</div>'
      + '<div class="gauntlet-card-meta">'
      + '<div class="gcm-name">' + c.champion + '</div>'
      + (c.team ? '<div class="gcm-team">' + c.team + '</div>' : '')
      + '<div class="gcm-year">' + c.year + ' &nbsp;&bull;&nbsp; ' + c.games.length + ' playoff games</div>'
      + rankLine
      + '</div>'
      + '<div class="gauntlet-score-block">'
      + '<div class="gsb-num" style="color:' + col + '">' + c.gs + '</div>'
      + '<div class="gsb-lbl">Gauntlet Score</div>'
      + '<div class="gsb-verdict" style="color:' + col + '">' + VERDICTS[i] + '</div>'
      + '</div>';

    var bars = document.createElement('div');
    bars.className = 'gauntlet-bar-section';
    [{lbl:'Opp. Points Against',sub:'z ' + (c.raw_pts>=0?'+':'') + c.raw_pts.toFixed(2),val:c.s_pts,col:'#4a7fa8'},
     {lbl:'Opp. Dominance',sub:'z ' + domStr,val:c.s_dom,col:'#a85a5a'},
     {lbl:'Opp. Hot Streak',sub:'z ' + (c.raw_streak>=0?'+':'') + c.raw_streak.toFixed(2),val:c.s_streak,col:'#9c849c'}
    ].forEach(function(b) {
      var row = document.createElement('div');
      row.className = 'gauntlet-brow';
      var fillLeft = Math.min(b.val, 50);
      var fillWidth = Math.abs(b.val - 50);
      row.innerHTML = '<div class="gauntlet-brow-label">' + b.lbl + '<small>' + b.sub + '</small></div>'
        + '<div class="gdiv-track"><div class="gdiv-center"></div><div class="gdiv-fill" style="left:' + fillLeft + '%;width:' + fillWidth + '%;background:' + b.col + '"></div></div>'
        + '<div class="gauntlet-bval">' + b.val.toFixed(1) + '</div>';
      bars.appendChild(row);
    });

    var tog = document.createElement('div');
    tog.className = 'gauntlet-toggle';
    tog.innerHTML = 'Game-by-game breakdown <span class="gauntlet-toggle-arrow">&#9660;</span>';

    var gamesDiv = document.createElement('div');
    gamesDiv.className = 'gauntlet-games';
    var inner = document.createElement('div');
    inner.className = 'gauntlet-games-inner';
    inner.innerHTML = '<div class="gg-round-label">Playoff results</div>';
    c.games.forEach(function(g) {
      var ms = (g.m > 0 ? '+' : '') + g.m;
      var domG = (g.dom >= 0 ? '+' : '') + g.dom;
      var streakG = (g.streak >= 0 ? '+' : '') + g.streak;
      var row = document.createElement('div');
      row.className = 'gg-game-row';
      row.innerHTML = '<div><div class="gg-opp-name">vs. ' + g.opp + '</div>'
        + '<div class="gg-opp-team">' + (g.ot ? g.ot + ' &bull; ' : '') + g.r + '</div></div>'
        + '<div class="gg-score-bubble">' + g.cs + '&ndash;' + g.os
        + '<br><span style="font-size:0.68rem;font-weight:400">' + ms + '</span></div>'
        + '<div class="gg-opp-stats">'
        + (g.rppg !== null ? '<div class="gg-stat-row">Reg PPG <b>' + g.rppg + '</b></div>' : '')
        + '<div class="gg-stat-row">Streak <b>' + streakG + '</b></div>'
        + '<div class="gg-stat-row">Dom z <b>' + domG + '</b></div>'
        + '</div>';
      inner.appendChild(row);
    });
    gamesDiv.appendChild(inner);

    tog.addEventListener('click', function() {
      var open = gamesDiv.classList.toggle('open');
      tog.querySelector('.gauntlet-toggle-arrow').style.transform = open ? 'rotate(180deg)' : '';
    });

    card.appendChild(header);
    card.appendChild(bars);
    card.appendChild(tog);
    card.appendChild(gamesDiv);
    grid.appendChild(card);
  });
})();

/* ── HARDEST / EASIEST 3-WEEK STRETCHES EVER ────────────────────────────────
   Same Gauntlet Score methodology as above, generalized to every possible
   3-consecutive-real-week stretch any manager has faced, not just
   championship playoff runs. See generate_gauntlet_stretches.py. */
if (D.labels) (function() {
  var HARDEST = D.HARDEST;

  var EASIEST = D.EASIEST;

  function buildStretchCards(list, gridId, hardColor) {
    var grid = document.getElementById(gridId);
    list.forEach(function(s, i) {
      var card = document.createElement('div');
      card.className = 'gauntlet-card';

      var header = document.createElement('div');
      header.className = 'gauntlet-card-header';
      var weekLabel = s.games[0].week.replace('Playoff ', '') + '\u2013' + s.games[s.games.length - 1].week.replace('Playoff ', '');
      header.innerHTML = '<div class="gauntlet-rank-badge" style="background:' + hardColor + '">' + (i+1) + '</div>'
        + '<div class="gauntlet-card-meta">'
        + '<div class="gcm-name">' + s.manager + '</div>'
        + '<div class="gcm-team">' + s.season + ' &nbsp;&bull;&nbsp; ' + weekLabel + '</div>'
        + '</div>'
        + '<div class="gauntlet-score-block">'
        + '<div class="gsb-num" style="color:' + hardColor + '">' + s.gs.toFixed(1) + '</div>'
        + '<div class="gsb-lbl">Gauntlet Score</div>'
        + '</div>';

      var tog = document.createElement('div');
      tog.className = 'gauntlet-toggle';
      tog.innerHTML = 'Game-by-game breakdown <span class="gauntlet-toggle-arrow">&#9660;</span>';

      var gamesDiv = document.createElement('div');
      gamesDiv.className = 'gauntlet-games';
      var inner = document.createElement('div');
      inner.className = 'gauntlet-games-inner';
      inner.innerHTML = '<div class="gg-round-label">Opponents faced</div>';
      s.games.forEach(function(g) {
        var ms = (g.margin > 0 ? '+' : '') + g.margin;
        var domG = (g.opp_dom >= 0 ? '+' : '') + g.opp_dom;
        var surgeG = (g.opp_surge >= 0 ? '+' : '') + g.opp_surge;
        var row = document.createElement('div');
        row.className = 'gg-game-row';
        row.innerHTML = '<div><div class="gg-opp-name">vs. ' + g.opponent + '</div>'
          + '<div class="gg-opp-team">' + g.week + '</div></div>'
          + '<div class="gg-score-bubble">' + g.own_score + '&ndash;' + g.opp_score
          + '<br><span style="font-size:0.68rem;font-weight:400">' + ms + '</span></div>'
          + '<div class="gg-opp-stats">'
          + '<div class="gg-stat-row">Streak <b>' + surgeG + '</b></div>'
          + '<div class="gg-stat-row">Dom z <b>' + domG + '</b></div>'
          + '</div>';
        inner.appendChild(row);
      });
      gamesDiv.appendChild(inner);

      tog.addEventListener('click', function() {
        var open = gamesDiv.classList.toggle('open');
        tog.querySelector('.gauntlet-toggle-arrow').style.transform = open ? 'rotate(180deg)' : '';
      });

      card.appendChild(header);
      card.appendChild(tog);
      card.appendChild(gamesDiv);
      grid.appendChild(card);
    });
  }

  buildStretchCards(HARDEST, 'hardestStretchGrid', '#a85a5a');
  buildStretchCards(EASIEST, 'easiestStretchGrid', '#5a8a6a');
})();

/* ── CLOSEST GAMES EVER ───────────────────────────────────────────────────── */
(function() {
  var CLOSEST = D.CLOSEST;

  function renderClosest(list) {
    var tbody = document.getElementById('closest-tbody');
    tbody.innerHTML = list.map(function(g, i) {
      var whenHtml = (g.po ? '<span class="po-badge">PO</span>' : '') + g.when;
      return '<tr><td class="closest-rank">' + (i+1) + '</td><td>' + g.w + '</td><td>' + g.ws.toFixed(2)
        + '</td><td>' + g.l + '</td><td>' + g.ls.toFixed(2) + '</td><td class="margin-val">' + g.m.toFixed(2)
        + '</td><td>' + whenHtml + '</td></tr>';
    }).join('');
  }

  window.filterClosest = function(type, btn) {
    document.querySelectorAll('.season-btn').forEach(function(b){
      if (b.closest('.season-filter-row') === btn.closest('.season-filter-row')) b.classList.remove('active');
    });
    btn.classList.add('active');
    renderClosest(CLOSEST[type]);
  };

  renderClosest(CLOSEST.all);
})();

/* ── Jump-nav scroll-spy ── */
(function() {
  var pills = Array.from(document.querySelectorAll('.jump-nav-pill'));
  if (!pills.length) return;
  var nav = document.getElementById('jump-nav');
  var sections = pills.map(function(p) {
    return document.getElementById(p.dataset.target);
  }).filter(Boolean);

  function centerPillInStrip(pill) {
    // Scrolls only the horizontal pill strip itself - never the page.
    if (!nav || !window.matchMedia('(max-width:768px)').matches) return;
    var target = (pill.offsetLeft + pill.offsetWidth / 2) - (nav.clientWidth / 2);
    nav.scrollTo({ left: target, behavior: 'smooth' });
  }

  var observer = new IntersectionObserver(function(entries) {
    entries.forEach(function(entry) {
      var pill = pills.find(function(p) { return p.dataset.target === entry.target.id; });
      if (!pill) return;
      if (entry.isIntersecting) {
        pills.forEach(function(p) { p.classList.remove('active'); });
        pill.classList.add('active');
        centerPillInStrip(pill);
      }
    });
  }, { rootMargin: '-15% 0px -70% 0px', threshold: 0 });

  sections.forEach(function(s) { observer.observe(s); });
})();

  // the handlers the page's markup names (inline onclick, as on the Stage A page) are set on window above
}

config().then(function (c) {
  cfg = c;
  mgr = managers(cfg);
  drawNav(cfg, 'extra-analytics');
  drawSubnav(cfg, 'extra-analytics');
  drawFooter(cfg);
  return load('data/v1/extra-analytics.json');
}).then(function (M) {
  MODEL = M;
  D = extraData(M, mgr.name);
  PAGE_LIVE_SEASON = cfg.live_season != null && M.seasons.indexOf(cfg.live_season) !== -1 ? cfg.live_season : null;
  SEASON_COLORS = (cfg.theme && cfg.theme.season_colors) || {};
  HARDEST_ALL = D.HARDEST || [];
  EASIEST_ALL = D.EASIEST || [];
  conferenceSection();
  swapNotes();
  if (M.quarterly) {
    quarterlyNotes();
    positionalNotes();
    attributionNotes();
    gauntletNotes();
  } else {                                   // no fitted models yet (a league's first season): hide those sections
    ['championship-gauntlet', 'seasonal-analysis', 'positional-production', 'win-attribution'].forEach(function (id) {
      var el = document.getElementById(id);
      if (el) el.style.display = 'none';
      var pill = document.querySelector('.jump-nav-pill[data-target="' + id + '"]');
      if (pill) pill.remove();
    });
  }
  runPage();
}).catch(function (err) {
  console.error(err);
  var el = document.getElementById('h2h-table');
  if (el) el.innerHTML = '<tbody><tr><td><div class="data-state data-state-error">This page could not be loaded.</div></td></tr></tbody>';
});
