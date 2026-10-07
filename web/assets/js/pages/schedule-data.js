/* Schedule Release data: data/v1/schedule.json (schema "schedule") in the shapes the page's script
   reads, as the Stage A build wrote them (engine/publish/pages/schedule.py, schedule_views):
     MANAGERS_DATA     name -> that manager's schedule, one entry per week: opponent, all-time record,
                       most recent / closest / blowout meeting, game log, every meeting with its MVP,
                       and the themed extras (rematch, trade count) on weeks whose theme asks for them
     LEAGUE_SCHEDULE   the weeks with their theme ("Standard" without one) and matchups
     CONF              name -> conference label, empty when the league has no conferences
   Pure: no DOM, so it can be checked on its own against the Stage A files. name(key) gives a
   manager's display name. Ties pick the earliest meeting, as the build did. */

import { pyRound } from '../core/format.js';

var STANDARD = 'Standard';
var ROUND_DEPTH = { 'Championship': 0, 'Semifinal': 1, 'Quarterfinal': 2, 'First Round': 3 };
var r = function (v, d) { return v === null || v === undefined ? null : pyRound(v, d); };
var margin = function (g) { return Math.abs(g.points - g.opponent_points); };

/* the pair's biggest playoff meeting: the deepest round, the most recent on ties */
function rematch(games) {
  var po = games.filter(function (g) { return g.is_playoff; });
  if (!po.length) return null;
  var depth = function (g) { return g.label in ROUND_DEPTH ? ROUND_DEPTH[g.label] : 4; };
  var best = po[0];
  po.forEach(function (g) {
    if (depth(g) < depth(best) || (depth(g) === depth(best) && g.season > best.season)) best = g;
  });
  return { season: String(best.season), round: best.label };
}

export function scheduleData(M, name) {
  var highlights = M.theme_highlights || {};
  var hist = {}, trades = {};
  var pairKey = function (a, b) { return a < b ? a + '|' + b : b + '|' + a; };
  M.rivalries.forEach(function (rv) {
    trades[pairKey(rv.manager_key, rv.opponent_key)] = rv.trades;
    hist[rv.manager_key + '>' + rv.opponent_key] = rv.games;
    hist[rv.opponent_key + '>' + rv.manager_key] = rv.games.map(function (g) {
      return Object.assign({}, g, { points: g.opponent_points, opponent_points: g.points });
    });
  });

  var gameView = function (g, me, opp) {
    var winner = g.points > g.opponent_points ? me : g.points < g.opponent_points ? opp : null;
    return { season: String(g.season), week: g.week_label, score_a: r(g.points, 2), score_b: r(g.opponent_points, 2),
             winner: winner ? name(winner) : 'Tie', margin: r(margin(g), 2) };
  };
  var first = function (gs, better) { return gs.reduce(function (a, g) { return better(g, a) ? g : a; }, gs[0]); };

  var LEAGUE_SCHEDULE = [], per = {}, order = [];
  M.weeks.forEach(function (w) {
    var theme = w.theme || STANDARD;
    LEAGUE_SCHEDULE.push({ week: w.week, week_type: theme, matchups: w.matchups.map(function (m) {
      return { team_a: name(m.manager_key), team_b: name(m.opponent_key), interconference: m.interconference };
    }) });
    w.matchups.forEach(function (m) {
      [[m.manager_key, m.opponent_key], [m.opponent_key, m.manager_key]].forEach(function (pair) {
        var me = pair[0], opp = pair[1], games = hist[me + '>' + opp] || [];
        var res = games.map(function (g) { return g.points > g.opponent_points ? 'win' : g.points < g.opponent_points ? 'loss' : 'tie'; });
        var pick = function (g) { return games.length ? gameView(g, me, opp) : null; };
        if (!per[me]) { per[me] = []; order.push(me); }
        per[me].push({
          week: w.week, week_type: theme, opponent: name(opp), interconference: m.interconference,
          my_wins: res.filter(function (x) { return x === 'win'; }).length,
          opp_wins: res.filter(function (x) { return x === 'loss'; }).length,
          total_games: games.length,
          most_recent: pick(games[games.length - 1]),
          closest: pick(games.length ? first(games, function (g, a) { return margin(g) < margin(a); }) : null),
          blowout: pick(games.length ? first(games, function (g, a) { return margin(g) > margin(a); }) : null),
          game_log: res,
          rematch: highlights[theme] === 'rematch' ? rematch(games) : null,
          trade_count: highlights[theme] === 'trades' ? (trades[pairKey(me, opp)] || 0) : null,
          games: games.map(function (g) {
            var v = gameView(g, me, opp);
            return { season: g.season, score_a: v.score_a, score_b: v.score_b, winner: v.winner, label: g.label,
                     mvp_name: g.mvp ? g.mvp.name : null, mvp_pos: g.mvp ? g.mvp.position : null,
                     mvp_pts: g.mvp ? r(g.mvp.points, 1) : null };
          })
        });
      });
    });
  });

  var MANAGERS_DATA = {};
  order.forEach(function (k) {
    MANAGERS_DATA[name(k)] = per[k].map(function (e, i) { return { e: e, i: i }; })
      .sort(function (a, b) { return (a.e.week - b.e.week) || (a.i - b.i); })
      .map(function (x) { return x.e; });
  });
  var CONF = {};
  Object.keys(M.conferences || {}).forEach(function (k) { if (M.conferences[k]) CONF[name(k)] = M.conferences[k]; });
  return { SEASON: M.season, MANAGERS_DATA: MANAGERS_DATA, LEAGUE_SCHEDULE: LEAGUE_SCHEDULE, CONF: CONF };
}
