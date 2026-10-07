/* Trade Value data: data/v1/trade-value.json (schema "trade-value") in the shapes the page's script
   reads, as the Stage A build wrote them to data/*.js and inline (engine/publish/pages/trades.py,
   legacy_views). Pure: no DOM, so it can be checked on its own against the Stage A files.

   name(key) gives a manager's display name. The model keeps every trade side (hidden managers marked)
   and keys aggregates by manager key in key order, as the Stage A files did, so most blocks map
   straight across. Built here from the sides, as the build did:
     TRADES, BEST_WORST   visible managers' sides (2 and 3 places, best and worst by value, first wins)
     TRADE_NODES          every trade, all its sides, in trade order (the explorer shows hidden sides too)
     TRADE_WEEK_DATA      every side, 3 places
   The network is ordered by name on the page: nodes by name, each edge's pair in name order (its net
   difference flipped when the pair turns around). */

import { pyRound } from '../core/format.js';

var cmp = function (x, y) { return x < y ? -1 : x > y ? 1 : 0; };
var r = function (v, d) { return v === null || v === undefined ? null : pyRound(v, d); };
var names = function (ps) { return ps.map(function (p) { return p.name; }); };
var positions = function (ps) { return ps.map(function (p) { return p.position; }); };

function byManager(obj, name, fn) {
  var out = {};
  Object.keys(obj).forEach(function (k) { out[name(k)] = fn ? fn(obj[k]) : obj[k]; });
  return out;
}

export function tradeData(M, name) {
  var active = M.sides.filter(function (s) { return !s.hidden; });
  var filters = ['career'].concat(Array.from(new Set(active.map(function (s) { return s.season; }))).sort().map(String));
  var inFilter = function (f) { return f === 'career' ? active : active.filter(function (s) { return String(s.season) === f; }); };

  var LEADERBOARD = {};
  Object.keys(M.leaderboard).forEach(function (f) { LEADERBOARD[f] = byManager(M.leaderboard[f], name); });
  var LEADERBOARD_TOTALS = {};
  Object.keys(M.totals).forEach(function (f) { LEADERBOARD_TOTALS[f] = byManager(M.totals[f], name); });

  // best and worst trade per manager: the first side with the highest (lowest) value, managers in key order
  var BEST_WORST = {};
  filters.forEach(function (f) {
    var by = {};
    inFilter(f).forEach(function (s) { (by[s.manager_key] = by[s.manager_key] || []).push(s); });
    var out = {};
    Object.keys(by).sort().forEach(function (k) {
      var best = by[k][0], worst = by[k][0];
      by[k].forEach(function (s) { if (s.quad > best.quad) best = s; if (s.quad < worst.quad) worst = s; });
      var side = function (s) { return { got: names(s.got), gave: names(s.gave), quad: r(s.quad, 2) }; };
      out[name(k)] = { best: side(best), worst: side(worst) };
    });
    BEST_WORST[f] = out;
  });

  var scale = function (k) { return { min: r(M.scales[k].min, 3), max: r(M.scales[k].max, 3) }; };

  var TRADES = active.map(function (s) {
    return { s: s.season, m: name(s.manager_key), got: names(s.got), gave: names(s.gave),
             tg: r(s.trade_grade, 2), rg: r(s.realized_gains, 2), fit: r(s.fit_score, 3), nec: r(s.necessity_per_week, 3),
             quad: r(s.quad, 2), multi: s.multi, wk: s.week };
  });

  // network: nodes by name; each edge's pair in name order
  var nodes = M.network.nodes.map(function (n) { return { id: name(n.id), trades: n.trades }; })
    .sort(function (a, b) { return cmp(a.id, b.id); });
  var rank = {};
  nodes.forEach(function (n, i) { rank[n.id] = i; });
  var edges = M.network.edges.map(function (e) {
    var a = name(e.a), b = name(e.b), flip = rank[a] > rank[b];
    return { a: flip ? b : a, b: flip ? a : b, n: e.n, netDiff: flip ? -e.netDiff : e.netDiff,
             positions: e.positions, seasons: e.seasons };
  }).sort(function (x, y) { return (rank[x.a] - rank[y.a]) || (rank[x.b] - rank[y.b]); });

  var WINPCT_DATA = M.win_pct.map(function (w) { return Object.assign({}, w, { m: name(w.m) }); });

  // explorer: one node per trade, its sides in order
  var groups = [], byGroup = {};
  M.sides.forEach(function (s) {
    if (!byGroup[s.group_id]) { byGroup[s.group_id] = []; groups.push(s.group_id); }
    byGroup[s.group_id].push(s);
  });
  groups.sort(function (a, b) { return a - b; });
  var TRADE_NODES = groups.map(function (gid) {
    var g = byGroup[gid], first = g[0], pos = new Set();
    g.forEach(function (s) { positions(s.got).concat(positions(s.gave)).forEach(function (p) { pos.add(p); }); });
    return { gid: gid, season: first.season, sp: first.week, multi: first.multi,
             managers: g.map(function (s) {
               return { m: name(s.manager_key), got: names(s.got), gave: names(s.gave), tg: r(s.trade_grade, 2),
                        rg: r(s.realized_gains, 2), fit: r(s.fit_score, 3), nec: r(s.necessity_per_week, 3), quad: r(s.quad, 2) };
             }),
             positions: Array.from(pos).sort() };
  });

  var TRADE_WEEK_DATA = M.sides.map(function (s) {
    return { g: s.group_id, s: s.season, wk: s.week, m: name(s.manager_key), multi: s.multi, got: names(s.got), gave: names(s.gave),
             tg: r(s.trade_grade, 3), rg: r(s.realized_gains, 3), fit: r(s.fit_score, 3), nec: r(s.necessity_per_week, 3),
             quad: r(s.quad, 3) };
  });

  var MOST_TRADED = M.most_traded.map(function (p) {
    return { player: p.player, count: p.count, seasons: p.seasons, managers: p.managers.map(name), pos: p.pos };
  });

  return {
    PAGE_SEASONS: M.seasons.slice(),
    LEADERBOARD: LEADERBOARD, LEADERBOARD_TOTALS: LEADERBOARD_TOTALS, BEST_WORST: BEST_WORST, TRADES: TRADES,
    QUAD_SCALE: scale('quad'), TG_SCALE: scale('tg'), RG_SCALE: scale('rg'), FIT_SCALE: scale('fit'), NEC_SCALE: scale('nec'),
    NETWORK_DATA: { nodes: nodes, edges: edges }, WINPCT_DATA: WINPCT_DATA, TRADE_NODES: TRADE_NODES,
    TRADE_WEEK_DATA: TRADE_WEEK_DATA, MOST_TRADED: MOST_TRADED
  };
}
