/* Lineup Efficiency data: data/v1/lineup-efficiency.json (schema "lineup-efficiency") in the shapes the
   page's script reads, as the Stage A build wrote them inline (engine/publish/pages/lineup_efficiency.py,
   lineup_view). Pure: no DOM, so it can be checked on its own against the Stage A blocks.

   name(key) gives a manager's display name. The model keys managers by key and orders by key where
   the page orders by name, so those lists are re-sorted here: missed wins (rate, wins, name), depth
   vs wins (season, name), and the heatmap's managers (by name, with every cell re-indexed). */

var cmp = function (x, y) { return x < y ? -1 : x > y ? 1 : 0; };

export function lineupData(M, name) {
  var mapFilters = function (obj, fn) {
    var out = {};
    Object.keys(obj).forEach(function (f) { out[f] = fn(obj[f]); });
    return out;
  };
  var EFFICIENCY_BY_FILTER = mapFilters(M.efficiency, function (rows) {
    return rows.map(function (r) { return { m: name(r.m), g: r.g, w: r.w }; });
  });
  var MISSED_WINS_BY_FILTER = mapFilters(M.missed_wins, function (rows) {
    return rows.map(function (r) { return Object.assign({}, r, { manager: name(r.manager) }); })
      .sort(function (a, b) { return (b.rate - a.rate) || (b.n - a.n) || cmp(a.manager, b.manager); });
  });
  var BLUNDERS_BY_FILTER = mapFilters(M.blunders, function (rows) {
    return rows.map(function (b) {
      return { season: b.season, week: b.week, manager: name(b.manager), actual: b.actual, optimal: b.optimal, gap: b.gap,
               outcome: b.outcome, missed: b.missed };
    });
  });
  var ROSTERS_BY_FILTER = mapFilters(M.blunders, function (rows) {
    return rows.map(function (b) {
      return { season: b.roster.season, week: b.roster.week, manager: name(b.roster.manager), starters: b.roster.starters,
               bench: b.roster.bench };
    });
  });
  var DEPTH_BY_FILTER = mapFilters(M.depth, function (rows) {
    return rows.map(function (r) { return { m: name(r.m), d: r.d }; });
  });
  var DEPTH_ADJUSTED_BY_FILTER = mapFilters(M.depth_adjusted, function (rows) {
    return rows.map(function (r) { return { m: name(r.m), raw: r.raw, depth: r.depth, adj: r.adj }; });
  });
  var DEPTH_VS_WINS_DATA = M.depth_vs_wins.map(function (r) { return { m: name(r.m), s: r.s, d: r.d, wr: r.wr }; })
    .sort(function (a, b) { return (a.s - b.s) || cmp(a.m, b.m); });

  // the heatmap's managers by name; cells re-indexed to that order
  var keys = M.career_grid.managers;
  var order = keys.map(function (k, i) { return { i: i, n: name(k) }; }).sort(function (a, b) { return cmp(a.n, b.n); });
  var newIdx = {};
  order.forEach(function (o, j) { newIdx[o.i] = j; });
  var HEATMAP_MANAGERS = order.map(function (o) { return o.n; });
  var CAREER_AVG_DATA = M.career_grid.cells.map(function (c) { return [newIdx[c[0]], c[1], c[2], c[3]]; })
    .sort(function (a, b) { return (a[0] - b[0]) || (a[1] - b[1]); });
  var HEATMAP_DATA = (M.weekly_grid ? M.weekly_grid.cells : []).map(function (c) { return [c[0], c[1], newIdx[c[2]], c[3], c[4]]; })
    .map(function (c, i) { return { c: c, i: i }; })
    .sort(function (a, b) { return (a.c[0] - b.c[0]) || (a.c[1] - b.c[1]) || (a.c[2] - b.c[2]) || (a.i - b.i); })
    .map(function (x) { return x.c; });

  return {
    PAGE_SEASONS: M.seasons.slice(),
    EFFICIENCY_BY_FILTER: EFFICIENCY_BY_FILTER, EFFICIENCY_GLOBAL_MIN: M.scales.gap[0], EFFICIENCY_GLOBAL_MAX: M.scales.gap[1],
    MISSED_WINS_BY_FILTER: MISSED_WINS_BY_FILTER, BLUNDERS_BY_FILTER: BLUNDERS_BY_FILTER, ROSTERS_BY_FILTER: ROSTERS_BY_FILTER,
    DEPTH_BY_FILTER: DEPTH_BY_FILTER, DEPTH_ADJUSTED_BY_FILTER: DEPTH_ADJUSTED_BY_FILTER,
    SEASON_TREND_DATA: M.season_trend.slice(), DEPTH_VS_WINS_DATA: DEPTH_VS_WINS_DATA,
    HEATMAP_MANAGERS: HEATMAP_MANAGERS, HEATMAP_DATA: HEATMAP_DATA,
    HEATMAP_SEASONS: M.weekly_grid ? M.weekly_grid.seasons.slice() : M.seasons.slice(),
    CAREER_AVG_DATA: CAREER_AVG_DATA, HEATMAP_GAP_MIN: M.scales.heatmap_gap[0], HEATMAP_GAP_MAX: M.scales.heatmap_gap[1]
  };
}
