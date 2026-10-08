/* Extra Analytics data: data/v1/extra-analytics.json (schema "extra-analytics") in the shapes the
   page's script reads, as the Stage A build wrote them inline (engine/publish/pages/extra_analytics.py:
   h2h_view, closest_view, luck_view, swap_view, quarterly_view, positional_view, attribution_view,
   gauntlet_view). Pure: no DOM, so it can be checked on its own against the Stage A blocks.

   name(key) gives a manager's display name. The model keys managers by key and orders by key where
   the page orders by name, so those lists are re-sorted here. Numbers are rounded as the Stage A
   build rounded them (Python's round, pyRound). */

import { pyRound } from '../core/format.js';

var cmp = function (x, y) { return x < y ? -1 : x > y ? 1 : 0; };
var r = pyRound;

function byName(obj) {
  var out = {};
  Object.keys(obj).sort(cmp).forEach(function (k) { out[k] = obj[k]; });
  return out;
}

/* schedule luck rows {name, actual, predicted, luck}, luck ascending then name (luck_view) */
export function luckRows(rows, name) {
  return rows.map(function (x) {
    return { name: name(x.manager_key || x.name), actual: x.actual !== undefined ? x.actual : x.actual_wins,
             predicted: x.predicted !== undefined ? x.predicted : x.expected_wins, luck: x.luck };
  }).sort(function (a, b) { return (a.luck - b.luck) || cmp(a.name, b.name); });
}

/* one season's schedule luck from schedule_luck.seasons */
export function seasonLuck(M, season, name) {
  return luckRows(M.schedule_luck.seasons.filter(function (x) { return x.season === Number(season); }), name);
}

export function extraData(M, name) {
  // head-to-head: managers by name, opponents by name
  var h2h = {};
  M.head_to_head.forEach(function (x) {
    var m = name(x.manager_key);
    (h2h[m] = h2h[m] || {})[name(x.opponent_key)] = { w: x.wins, l: x.losses, pct: r(x.win_pct, 3) };
  });
  var managers = Object.keys(h2h).sort(cmp);
  var H2H = {};
  managers.forEach(function (m) { H2H[m] = byName(h2h[m]); });

  var CLOSEST = {};
  Object.keys(M.closest).forEach(function (scope) {
    CLOSEST[scope] = M.closest[scope].map(function (g) {
      return { w: name(g.w), ws: g.ws, l: name(g.l), ls: g.ls, m: g.m, po: g.po, when: g.when };
    });
  });

  var luckData = luckRows(M.schedule_luck.career, name);

  var SCHEDULE_SWAP_DATA = {};
  Object.keys(M.schedule_swap).sort().forEach(function (s) {
    var season = {};
    Object.keys(M.schedule_swap[s]).forEach(function (k) {
      var d = M.schedule_swap[s][k], alt = {};
      Object.keys(d.alt).forEach(function (o) { alt[name(o)] = d.alt[o]; });
      season[name(k)] = { actual: d.actual, alt: byName(alt), avg_pct: d.avg_pct, wins_gained: d.wins_gained };
    });
    SCHEDULE_SWAP_DATA[s] = byName(season);
  });

  var out = { managers: managers, h2h: H2H, CLOSEST: CLOSEST, luckData: luckData, SCHEDULE_SWAP_DATA: SCHEDULE_SWAP_DATA,
              SS_SEASON_GAMES: Object.assign({}, M.season_games || {}) };
  // each model section only when the league's data fits it (the model leaves it out otherwise)
  if (M.quarterly) {
  // quarterly playoff model
  out.labels = M.quarterly.map(function (q) { return q.quarter + ' (Wks ' + q.weeks + ')'; });
  out.coefs = M.quarterly.map(function (q) { return r(q.coef, 3); });
  out.corrs = M.quarterly.map(function (q) { return r(q.corr, 3); });
  out.pvals = M.quarterly.map(function (q) { return r(q.p_value, 3); });

  }

  if (M.positional) {
  // positional production: win % descending (unrounded), then name
  var P = M.positional, positions = P.positions;
  out.POSITIONS = positions.slice();
  out.DATA = P.managers.map(function (d) {
    var avg = {}, std = {};
    positions.forEach(function (p) { avg[p] = r(d.avg[p], 2); std[p] = r(d.sd[p], 2); });
    return { _wp: d.win_pct * 100, mgr: name(d.manager_key), winpct: r(d.win_pct * 100, 1), avg: avg, std: std };
  }).sort(function (a, b) { return (b._wp - a._wp) || cmp(a.mgr, b.mgr); })
    .map(function (d) { return { mgr: d.mgr, winpct: d.winpct, avg: d.avg, std: d.std }; });
  var coef = {};
  P.coefficients.forEach(function (c) { coef[c.position] = c; });
  out.STD_COEF = {}; out.COEF_PVAL = {}; out.CORR_R = {};
  positions.forEach(function (p) {
    out.STD_COEF[p] = r(coef[p].std_coef, 3); out.COEF_PVAL[p] = r(coef[p].p_value, 4); out.CORR_R[p] = r(coef[p].corr, 3);
  });

  }

  if (M.attribution) {
  // win% attribution
  var A = M.attribution, attr = {};
  A.managers.forEach(function (d) {
    attr[name(d.manager_key)] = { winpct: r(d.win_pct, 1), draft: r(d.draft, 2), waiver: r(d.waiver, 2),
      lineup: r(d.lineup, 2), trade: r(d.trade, 2), luck: r(d.luck, 2), predicted: r(d.predicted, 2),
      residual: r(d.residual, 2) };
  });
  out['DATA#1'] = byName(attr);
  out.LEAGUE_INTERCEPT = r(A.fit.league_intercept, 2);
  var FACTOR = { draft: 'Draft', waiver: 'Waiver', lineup: 'Lineup', trade: 'Trade', luck: 'Luck' };
  var coefs = A.coefficients.map(function (c, i) { return { c: c, i: i }; })
    .sort(function (a, b) { return (b.c.std_coef - a.c.std_coef) || (a.i - b.i); }).map(function (x) { return x.c; });
  out.COEF_LABELS = coefs.map(function (c) { return FACTOR[c.factor] || c.factor.charAt(0).toUpperCase() + c.factor.slice(1); });
  out.COEF_VALS = coefs.map(function (c) { return r(c.std_coef, 3); });
  var hist = A.history || [{ label: 'Current model', r2: A.fit.r2 }];
  out.R2_LABELS = hist.map(function (h) { return h.label; });
  out.R2_VALS = hist.map(function (h) { return r(h.r2, 3); });

  }

  if (M.gauntlet) {
  // championship gauntlet
  var G = M.gauntlet;
  out.CHAMPION_RANKS = {};
  G.champions.slice().sort(function (a, b) { return a.rank - b.rank; }).forEach(function (c) {
    var v = { rank: c.rank, total: c.total };
    if (c.n !== 3) v.sameLength = c.n;
    out.CHAMPION_RANKS[c.season + '_' + name(c.manager_key)] = v;
  });
  out.CHAMPIONS = G.champions.slice().sort(function (a, b) { return b.gs - a.gs; }).map(function (c) {
    return { year: c.season, champion: name(c.manager_key), team: c.team === undefined ? null : c.team,
      gs: r(c.gs, 1), n: c.n, s_pts: r(c.s_pts, 1), s_dom: r(c.s_dom, 1), s_streak: r(c.s_streak, 1),
      raw_pts: r(c.raw_pts, 4), raw_dom: r(c.raw_dom, 4), raw_streak: r(c.raw_streak, 4),
      games: c.games.map(function (g) {
        return { r: g.week_label.replace('Playoff ', ''), opp: name(g.opponent_key),
          ot: g.opponent_team === undefined ? null : g.opponent_team, cs: r(g.own_score, 1), os: r(g.opp_score, 1),
          m: r(g.margin, 1), dom: r(g.opp_dom, 3), rppg: g.opponent_ppg == null ? null : r(g.opponent_ppg, 1),
          streak: r(g.opp_surge, 1) };
      }) };
  });
  var listed = function (list) {
    return list.map(function (w) {
      return { season: w.season, manager: name(w.manager_key), s_pts: r(w.s_pts, 1), s_dom: r(w.s_dom, 1),
        s_streak: r(w.s_streak, 1), gs: r(w.gs, 2),
        games: w.games.map(function (g) {
          return { week: g.week_label, opponent: name(g.opponent_key), own_score: r(g.own_score, 1),
            opp_score: r(g.opp_score, 1), margin: r(g.margin, 1), opp_dom: r(g.opp_dom, 3), opp_surge: r(g.opp_surge, 1) };
        }) };
    });
  };
  out.HARDEST = listed(G.hardest);
  out.EASIEST = listed(G.easiest);
  }
  return out;
}
