/* Home: the league banner, the latest champion, the all-time leaderboard and the page cards.
   Reads config.json and data/v1/index.json (schema "index"). */

import { config, load, show } from '../core/data.js';
import { managers } from '../core/managers.js';
import { fixed, signed, count, seasonRange } from '../core/format.js';
import { drawNav, drawFooter } from '../core/nav.js';
import { url, esc } from '../core/site.js';
import { sortTable } from '../components/sort-table.js';

/* The page cards: template text per page id; a card shows only when the league has that page. */
var CARDS = [
  { id: 'weekly-rankings', cls: 'card-rankings', icon: '&#128197;', title: 'Weekly Rankings',
    text: 'Power rankings, previews, and recaps filterable by season and week.', cta: 'View rankings' },
  { id: 'managers', cls: 'card-managers', icon: '&#128100;', title: 'Manager Profiles',
    text: 'Individual dashboards with season history, scoring trends, rivalry breakdowns, draft fingerprint radars, and personal draft board heatmaps.',
    cta: 'Browse managers' },
  { id: 'champions', cls: 'card-champions', icon: '&#127942;', title: 'Champions',
    text: "Hall of champions from every season since the league's founding.", cta: 'View champions' },
  { id: 'matchups', cls: 'card-matchups', icon: '&#9878;', title: 'Matchup Explorer',
    text: 'Explore every regular season and playoff matchup in league history, sortable by year, managers, and margin of victory.',
    cta: 'Explore matchups' },
  { id: 'draft-analysis', cls: 'card-draft', icon: '&#128200;', title: 'Draft Analysis',
    text: 'Hit rates by round and position, late-round steals, and archetype clustering across every season.',
    cta: 'View analysis', subs: true },
  { id: 'transaction-analysis', cls: 'card-transactions', icon: '&#128257;', title: 'Transaction Analysis',
    text: 'In-season activity: lineup efficiency, waiver wire value, and trade breakdowns across every season.',
    cta: 'View analysis', subs: true },
  { id: 'extra-analytics', cls: 'card-analytics', icon: '&#128300;', title: 'Extra Analytics',
    text: 'Schedule luck, seasonal trends, head-to-head records, conference rivalries, the closest games ever, and the championship gauntlet.',
    cta: 'Explore' },
];

/* the leaderboard's color tiers: top 30% of the visible managers good, next 30% middle, rest bad */
function tier(rank, total) {
  var n = total > 1 ? (rank - 1) / (total - 1) : 0;
  return n <= 0.3 ? 'cell-good val-bold' : n <= 0.6 ? 'cell-mid' : 'cell-bad';
}

function pageHref(cfg, id) {
  var p = cfg.pages.find(function (x) { return x.id === id; });
  return p ? url(p.href || p.path) : null;
}

function drawHero(cfg) {
  // a league without a logo shows its name alone (no request for a missing image)
  var logo = cfg.league.logo ? url(cfg.league.logo) : null;
  document.getElementById('hero').innerHTML =
    (logo ? '<img src="' + esc(logo) + '" alt="" class="hero-logo" onerror="this.remove()">' : '') +
    '<h1>' + esc(cfg.league.name) + '</h1><p class="hero-est">Est. ' + esc(cfg.league.first_season) + '</p>';
}

function drawChampion(cfg, mgr, champ) {
  var el = document.getElementById('champion');
  if (!champ) { el.remove(); return; }
  var href = pageHref(cfg, 'champions');
  if (href) el.setAttribute('href', href); else el.removeAttribute('href');
  el.innerHTML = '<div class="champ-trophy-badge"><div class="champ-trophy">&#127942;</div></div>' +
    '<div class="champ-info"><div class="champ-eyebrow">' + esc(champ.season) + ' Champion</div>' +
    '<h3>' + esc(mgr.name(champ.manager_key)) + '</h3><p>' + esc(champ.team_name || '') + '</p></div>' +
    (href ? '<span class="champ-arrow">&#8594;</span>' : '');
  el.hidden = false;
}

function drawLeaderboard(cfg, mgr, index) {
  var rows = index.leaderboard || [];
  var seasons = (cfg.seasons || []).length;
  document.getElementById('leaderboard-note').innerHTML = 'Click any column to sort &bull; ' +
    esc(count(seasons, 'season')) + ', ' + esc(seasonRange(cfg));
  var total = index.visible_managers || rows.length;
  var managersHref = pageHref(cfg, 'managers');
  var season = function (s) { return s.wins + '-' + s.losses + (s.ties ? '-' + s.ties : '') + ' (' + s.season + ')'; };
  var seasonPct = function (s) { var n = s.wins + s.losses + s.ties; return n ? (s.wins + s.ties / 2) / n : 0; };
  var table = document.getElementById('leaderboardTable');
  if (!rows.length) { show(table.querySelector('tbody'), 'empty'); return; }
  sortTable(table, rows, [
    { label: 'Manager', text: true, value: function (r) { return mgr.name(r.manager_key); } },
    { label: 'W', value: function (r) { return r.wins; } },
    { label: 'L', value: function (r) { return r.losses; } },
    { label: 'Win %', value: function (r) { return r.win_pct; } },
    { label: 'Playoffs', value: function (r) { return r.playoffs; } },
    { label: 'Champs', value: function (r) { return r.championships; } },
    { label: 'PF/G', value: function (r) { return r.avg_pf_per_game; } },
    // luck: points against z-score, negated so lucky (fewer points allowed than expected) is positive
    { label: 'Avg Luck', value: function (r) { return -r.avg_pa_z; } },
    { label: 'Best', value: function (r) { return seasonPct(r.best_season); } },
    { label: 'Worst', value: function (r) { return seasonPct(r.worst_season); } },
  ], function (r) {
    var k = r.ranks || {};
    var name = esc(mgr.name(r.manager_key));
    var link = managersHref ? '<a href="' + esc(managersHref) + '?manager=' + encodeURIComponent(mgr.name(r.manager_key)) +
      '" class="manager-link">' + name + '</a>' : name;
    var champs = r.championships > 0 ? '<span class="champ-badge">' + r.championships + ' &#127942;</span>'
      : '<span style="color:var(--muted);">0</span>';
    return '<td>' + link + '</td>' +
      '<td class="' + tier(k.wins, total) + '">' + r.wins + '</td>' +
      '<td class="' + tier(k.losses, total) + '">' + r.losses + '</td>' +
      '<td class="' + tier(k.win_pct, total) + '">' + fixed(r.win_pct, 3) + '</td>' +
      '<td class="' + tier(k.playoffs, total) + '">' + r.playoffs + '</td>' +
      '<td>' + champs + '</td>' +
      '<td class="' + tier(k.avg_pf_per_game, total) + '">' + fixed(r.avg_pf_per_game, 1) + '</td>' +
      '<td class="' + tier(k.avg_pa_z, total) + '">' + signed(-r.avg_pa_z, 2) + '</td>' +
      '<td class="val-small">' + season(r.best_season) + '</td>' +
      '<td class="val-small">' + season(r.worst_season) + '</td>';
    }, { col: 3, asc: false });
}

function drawCards(cfg) {
  var have = new Set(cfg.pages.map(function (p) { return p.id; }));
  document.getElementById('cards').innerHTML = CARDS.filter(function (c) { return have.has(c.id); }).map(function (c) {
    var subs = c.subs ? cfg.pages.filter(function (p) { return p.parent === c.id && p.nav; }) : [];
    return '<a href="' + esc(pageHref(cfg, c.id)) + '" class="nav-card ' + c.cls + ' glass">' +
      '<h3><span class="icon">' + c.icon + '</span> ' + esc(c.title) + '</h3><p>' + esc(c.text) + '</p>' +
      (subs.length ? '<div class="card-subpages">' + subs.map(function (p) {
        return '<span class="card-subpage-pill">' + esc(p.title) + '</span>';
      }).join('') + '</div>' : '') +
      '<span class="card-arrow">' + esc(c.cta) + ' &#8594;</span></a>';
  }).join('');
}

config().then(function (cfg) {
  var mgr = managers(cfg);
  drawNav(cfg, 'home');
  drawFooter(cfg);
  drawHero(cfg);
  drawCards(cfg);
  return load('data/v1/index.json').then(function (index) {
    drawChampion(cfg, mgr, index.champion);
    drawLeaderboard(cfg, mgr, index);
  }).catch(function (err) {
    console.error(err);
    show(document.querySelector('#leaderboardTable tbody'), 'error');
  });
}).catch(function (err) {
  console.error(err);
  show(document.getElementById('hero'), 'error', 'The site configuration could not be loaded.');
});
