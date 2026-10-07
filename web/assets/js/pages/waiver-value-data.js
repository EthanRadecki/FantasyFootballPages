/* Waiver Value data: data/v1/waiver-value.json (schema "waiver-value") in the shapes the page's script
   reads, as the Stage A build wrote them inline (engine/publish/pages/waivers.py, waiver_view). Pure:
   no DOM, so it can be checked on its own against the Stage A blocks.

   name(key) gives a manager's display name. The model keys and orders by manager key; where the
   page's lists follow names (pickups in file order: season, manager, player), they are re-sorted here. */

import { pyRound } from '../core/format.js';

var TYPE_CODE = { FREEAGENT: 'F', WAIVER: 'W' };
var byName = function (name) { return function (a, b) { var x = name(a), y = name(b); return x < y ? -1 : x > y ? 1 : 0; }; };

export function waiverData(M, name) {
  var mapScopes = function (obj, fn) {
    var out = {};
    Object.keys(obj).forEach(function (scope) {
      out[scope] = {};
      Object.keys(obj[scope]).forEach(function (pos) { out[scope][pos] = fn(obj[scope][pos]); });
    });
    return out;
  };
  var LEADERBOARD_FULL = mapScopes(M.leaderboard, function (rows) {
    return rows.map(function (r) { return { m: name(r.manager_key), ppw: r.ppw, z: r.z_per_week, n: r.pickups }; });
  });
  var BEST_BY_MANAGER = mapScopes(M.best_by_manager, function (byKey) {
    var out = {};
    Object.keys(byKey).sort(byName(name)).forEach(function (k) {
      var r = byKey[k];
      out[name(k)] = { p: r.player_name, tz: r.total_z, wk: r.weeks };
    });
    return out;
  });
  var BEST_PICKUPS_BY_FILTER = mapScopes(M.best_pickups, function (rows) {
    return rows.map(function (r) {
      return { s: r.season, m: name(r.manager_key), p: r.player_name, pos: r.position, wk: r.weeks, ppw: r.ppw,
               totalz: r.total_z, avgz: r.avg_z, type: r.type };
    });
  });
  var CONTESTED_SPLIT = M.free_agent_vs_claim.map(function (r) {
    return { m: name(r.manager_key), faPpw: r.free_agent.ppw, faZ: r.free_agent.z_per_week, faN: r.free_agent.pickups,
             wvPpw: r.waiver.ppw, wvZ: r.waiver.z_per_week, wvN: r.waiver.pickups,
             careerPpw: r.career.ppw, careerZ: r.career.z_per_week };
  });
  // visible pickups in the file's order: season, manager name, player id (stable)
  var visible = M.pickups.map(function (p, i) { return { p: p, i: i }; }).filter(function (x) { return !x.p.hidden; });
  visible.sort(function (a, b) {
    if (a.p.season !== b.p.season) return a.p.season - b.p.season;
    var x = name(a.p.manager_key), y = name(b.p.manager_key);
    if (x !== y) return x < y ? -1 : 1;
    if (a.p.player_id !== b.p.player_id) return a.p.player_id - b.p.player_id;
    return a.i - b.i;
  });
  var WAIVER_STINTS = visible.map(function (x) {
    var p = x.p;
    return { s: p.season, m: name(p.manager_key), t: TYPE_CODE[p.type] || String(p.type).charAt(0), sw: p.start_week,
             wk: p.weeks, z: pyRound(p.total_z, 3), ppw: pyRound(p.ppw, 2), p: p.player_name, pos: p.position };
  });
  var sc = M.scales;
  return {
    PAGE_SEASONS: M.seasons.slice(),
    LEADERBOARD_FULL: LEADERBOARD_FULL, POSITION_SCALE: sc.position, BEST_BY_MANAGER: BEST_BY_MANAGER,
    WAIVER_Z_GLOBAL_MIN: sc.pickup_z[0], WAIVER_Z_GLOBAL_MAX: sc.pickup_z[1], WAIVER_STINTS: WAIVER_STINTS,
    CONTESTED_SPLIT: CONTESTED_SPLIT, UPSIDE_MIN: sc.upside[0], UPSIDE_MAX: sc.upside[1],
    BEST_PICKUPS_BY_FILTER: BEST_PICKUPS_BY_FILTER,
    BEST_TOTALZ_MIN: sc.best_total_z[0], BEST_TOTALZ_MAX: sc.best_total_z[1],
    BEST_AVGZ_MIN: sc.best_avg_z[0], BEST_AVGZ_MAX: sc.best_avg_z[1]
  };
}
