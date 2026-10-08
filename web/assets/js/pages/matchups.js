/* Matchup Explorer: every game the league counts (regular season and winners bracket) with its box
   score; filters by season, phase, manager or team, head-to-head; superlatives; a game modal.

   Reads config.json and data/v1/matchups.json (schema "matchups"). Ported from the Stage A page with
   the same layout (decision 7.14). Round names come from league.yaml's playoff rounds; the game the
   league excludes from superlatives is flagged in the data (analysis.exclude_games). */

import { config, load, show } from '../core/data.js';
import { managers } from '../core/managers.js';
import { drawNav, drawFooter } from '../core/nav.js';
import { esc } from '../core/site.js';
import { seasonColor, seasonInfo, rgb, POSITION_SWATCH } from '../core/theme.js';

var FALLBACK_PALETTE = ['#6d6a5f', '#5c6b73', '#7a5c58', '#5f6e4c', '#6b5a75'];
var BATCH = 24;

var cfg, mgr, ALL = [], FILTERED = [], RENDERED = 0, NAMES = [];
var state = { season: 'all', phase: 'all', query: '', sort: 'recent', h2h: null };
var modalList = [], modalIndex = 0;
var grid = document.getElementById('matchupGrid');
var loadMoreBtn = document.getElementById('loadMoreBtn');
var resultsCount = document.getElementById('resultsCount');
var heroSub = document.getElementById('heroSub');

function hashStr(s) { var h = 0; for (var i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) >>> 0; return h; }
function managerColor(key) { return mgr.color(key, 'dark') || FALLBACK_PALETTE[hashStr(key) % FALLBACK_PALETTE.length]; }
function slotLabel(slot) { return slot && slot.indexOf('/') !== -1 && slot !== 'D/ST' ? 'FLEX' : slot; }

/* "The Round of 15" -> "Round of 15" on the cards; the full name in the game's modal */
function roundShort(name) { return String(name || '').replace(/^The /, ''); }

/* playoff tier for the card's frame: 4 for the final, 3 the round before, 2 the one before that, 1 earlier */
function playoffTier(g) {
  if (!g.isPlayoff) return 0;
  var info = seasonInfo(cfg, g.season) || {};
  // rounds counted back from the final by the weeks that hold a round (a two-week round is one)
  var weeks = Object.keys(info.rounds || {}).map(Number).sort(function (a, b) { return a - b; });
  var fromEnd = weeks.indexOf(g.week) !== -1 ? weeks.length - 1 - weeks.indexOf(g.week) : (info.final_week || g.week) - g.week;
  return Math.max(1, 4 - fromEnd);
}

/* "Semifinals", or "Semifinals · Wks 15-16" for a two-week round */
function roundLabel(g, short) {
  var name = short ? roundShort(g.round) : (g.round || 'Playoffs');
  return g.weeks > 1 ? name + ' \u00b7 Wks ' + g.firstWeek + '-' + g.week : name;
}

function side(t) {
  var m = mgr.get(t.manager_key) || {};
  return { key: t.manager_key, name: m.name || t.manager_key, short: m.short || m.name || '?', team: t.team_name || '',
           score: t.points, total: t.points_total, won: t.result === 'W', starters: t.starters || [], bench: t.bench || [] };
}

function adapt(g) {
  return { id: g.id, season: g.season, week: g.week, round: g.round, isPlayoff: !!g.is_playoff,
           weeks: g.weeks || 1, firstWeek: g.first_week || g.week,
           excluded: !!g.superlative_excluded, margin: g.margin, combined: g.combined,
           a: side(g.teams[0]), b: side(g.teams[1]) };
}

function init(data) {
  ALL = (data.games || []).map(adapt);
  var names = {};
  ALL.forEach(function (g) { names[g.a.name] = 1; names[g.b.name] = 1; });
  NAMES = Object.keys(names).sort();
  var seasons = Array.from(new Set(ALL.map(function (g) { return g.season; }))).sort();
  heroSub.innerHTML = '<strong>' + ALL.length + '</strong> matchups on record across <strong>' + seasons.length +
    '</strong> seasons (' + seasons[0] + '&ndash;' + seasons[seasons.length - 1] + '), every game with a full box score.';
  buildSeasonPills(seasons);
  buildManagerOptions();
  buildQuickJump();
  bindControls();
  applyFilters();
}

function buildSeasonPills(seasons) {
  var wrap = document.getElementById('seasonPills');
  wrap.innerHTML = '';
  var add = function (label, val, color) {
    var btn = document.createElement('button');
    btn.className = 'mx-pill' + (val === 'all' ? ' active' : '');
    btn.textContent = label;
    if (color) btn.style.setProperty('--pill-color', color);
    btn.onclick = function () {
      state.season = val;
      Array.from(wrap.children).forEach(function (c) { c.classList.remove('active'); });
      btn.classList.add('active');
      applyFilters();
    };
    wrap.appendChild(btn);
  };
  add('All Seasons', 'all');
  seasons.forEach(function (s) { add(String(s), s, seasonColor(cfg, s) || '#888'); });
}

function buildManagerOptions() {
  var list = document.getElementById('managerList'), a = document.getElementById('h2hA'), b = document.getElementById('h2hB');
  NAMES.forEach(function (n) {
    list.insertAdjacentHTML('beforeend', '<option value="' + esc(n) + '">');
    a.insertAdjacentHTML('beforeend', '<option value="' + esc(n) + '">' + esc(n) + '</option>');
    b.insertAdjacentHTML('beforeend', '<option value="' + esc(n) + '">' + esc(n) + '</option>');
  });
}

function buildQuickJump() {
  var wrap = document.getElementById('quickJump');
  var eligible = ALL.filter(function (g) { return !g.excluded; });
  if (!eligible.length) return;
  var closest = eligible.reduce(function (x, y) { return y.margin < x.margin ? y : x; });
  var blowout = eligible.reduce(function (x, y) { return y.margin > x.margin ? y : x; });
  var highest = eligible.reduce(function (x, y) { return y.combined > x.combined ? y : x; });
  var chips = [
    { icon: '&#128293;', label: 'Closest Game', game: closest, value: closest.margin.toFixed(2) + ' pt margin' },
    { icon: '&#128165;', label: 'Biggest Blowout', game: blowout, value: blowout.margin.toFixed(1) + ' pt margin' },
    { icon: '&#128200;', label: 'Highest Combined', game: highest, value: highest.combined.toFixed(1) + ' points' },
    { icon: '&#127922;', label: 'Feeling lucky', game: null, value: 'Random matchup' },
  ];
  chips.forEach(function (c) {
    var el = document.createElement('button');
    el.className = 'mx-chip glass';
    el.innerHTML = '<span class="mx-chip-icon">' + c.icon + '</span><span><span class="mx-chip-label">' + c.label +
      '</span><span class="mx-chip-value">' + c.value + '</span></span>';
    el.onclick = function () { jumpToGame(c.game || ALL[Math.floor(Math.random() * ALL.length)]); };
    wrap.appendChild(el);
  });
}

function jumpToGame(game) {
  resetFiltersUI();
  applyFilters();
  var idx = FILTERED.indexOf(game);
  if (idx === -1) { FILTERED = ALL.slice(); idx = FILTERED.indexOf(game); }
  openModal(FILTERED, idx);
}

function resetFiltersUI() {
  state = { season: 'all', phase: 'all', query: '', sort: 'recent', h2h: null };
  document.getElementById('searchInput').value = '';
  document.getElementById('sortSelect').value = 'recent';
  document.querySelectorAll('#seasonPills .mx-pill').forEach(function (p, i) { p.classList.toggle('active', i === 0); });
  document.querySelectorAll('#phaseToggle button').forEach(function (b) { b.classList.toggle('active', b.dataset.phase === 'all'); });
  clearH2H();
}

function bindControls() {
  document.getElementById('phaseToggle').addEventListener('click', function (e) {
    var btn = e.target.closest('button');
    if (!btn) return;
    state.phase = btn.dataset.phase;
    Array.from(btn.parentNode.children).forEach(function (b) { b.classList.remove('active'); });
    btn.classList.add('active');
    applyFilters();
  });
  var timer;
  document.getElementById('searchInput').addEventListener('input', function (e) {
    clearTimeout(timer);
    var v = e.target.value;
    timer = setTimeout(function () { state.query = v.trim().toLowerCase(); applyFilters(); }, 150);
  });
  document.getElementById('sortSelect').addEventListener('change', function (e) { state.sort = e.target.value; applyFilters(); });
  document.getElementById('h2hGo').addEventListener('click', function () {
    var a = document.getElementById('h2hA').value, b = document.getElementById('h2hB').value;
    if (!a || !b || a === b) return;
    state.h2h = [a, b];
    document.getElementById('h2hClear').hidden = false;
    applyFilters();
    renderH2HSummary(a, b);
  });
  document.getElementById('h2hClear').addEventListener('click', function () { clearH2H(); applyFilters(); });
  document.getElementById('randomBtn').addEventListener('click', function () {
    var pool = FILTERED.length ? FILTERED : ALL;
    openModal(pool, Math.floor(Math.random() * pool.length));
  });
  loadMoreBtn.addEventListener('click', renderNextBatch);
  new IntersectionObserver(function (entries) {
    entries.forEach(function (en) { if (en.isIntersecting && RENDERED < FILTERED.length) renderNextBatch(); });
  }, { rootMargin: '400px' }).observe(loadMoreBtn);
  document.getElementById('modalClose').addEventListener('click', closeModal);
  document.getElementById('modalOverlay').addEventListener('click', function (e) { if (e.target.id === 'modalOverlay') closeModal(); });
  document.getElementById('modalPrev').addEventListener('click', function () { navModal(-1); });
  document.getElementById('modalNext').addEventListener('click', function () { navModal(1); });
  document.addEventListener('keydown', function (e) {
    if (!document.getElementById('modalOverlay').classList.contains('open')) return;
    if (e.key === 'Escape') closeModal();
    if (e.key === 'ArrowLeft') navModal(-1);
    if (e.key === 'ArrowRight') navModal(1);
  });
}

function clearH2H() {
  state.h2h = null;
  document.getElementById('h2hA').value = '';
  document.getElementById('h2hB').value = '';
  document.getElementById('h2hClear').hidden = true;
  document.getElementById('h2hSummary').hidden = true;
}

function pairOf(g, a, b) { return (g.a.name === a && g.b.name === b) || (g.a.name === b && g.b.name === a); }

function renderH2HSummary(a, b) {
  var games = ALL.filter(function (g) { return pairOf(g, a, b); });
  var wins = {}; wins[a] = 0; wins[b] = 0;
  games.forEach(function (g) { var w = g.a.won ? g.a.name : g.b.won ? g.b.name : null; if (w) wins[w]++; });
  var box = document.getElementById('h2hSummary');
  if (!games.length) box.innerHTML = '<span>' + esc(a) + ' and ' + esc(b) + ' haven\'t played a recorded matchup.</span>';
  else {
    var avg = (games.reduce(function (s, g) { return s + g.margin; }, 0) / games.length).toFixed(1);
    box.innerHTML = '<span class="mx-h2h-record">' + esc(a) + ' ' + wins[a] + ' &ndash; ' + wins[b] + ' ' + esc(b) + '</span>' +
      '<span>across ' + games.length + ' game' + (games.length === 1 ? '' : 's') + ' &middot; avg margin ' + avg + ' pts</span>';
  }
  box.hidden = false;
}

function applyFilters() {
  var q = state.query;
  FILTERED = ALL.filter(function (g) {
    if (state.season !== 'all' && String(g.season) !== String(state.season)) return false;
    if (state.phase === 'regular' && g.isPlayoff) return false;
    if (state.phase === 'playoff' && !g.isPlayoff) return false;
    if (state.h2h && !pairOf(g, state.h2h[0], state.h2h[1])) return false;
    if (q && (g.a.name + ' ' + g.a.team + ' ' + g.b.name + ' ' + g.b.team).toLowerCase().indexOf(q) === -1) return false;
    return true;
  });
  FILTERED.sort(function (x, y) {
    switch (state.sort) {
      case 'oldest': return (x.season - y.season) || (x.week - y.week);
      case 'closest': return x.margin - y.margin;
      case 'blowout': return y.margin - x.margin;
      case 'highest': return y.combined - x.combined;
      case 'lowest': return x.combined - y.combined;
      default: return (y.season - x.season) || (y.week - x.week);
    }
  });
  RENDERED = 0;
  grid.innerHTML = '';
  resultsCount.textContent = FILTERED.length + ' matchup' + (FILTERED.length === 1 ? '' : 's') +
    (state.season !== 'all' || state.phase !== 'all' || q || state.h2h ? ' match your filters' : ' in league history');
  if (!FILTERED.length) {
    grid.innerHTML = '<div class="mx-empty">No matchups found. Try widening your filters.</div>';
    loadMoreBtn.style.display = 'none';
    return;
  }
  renderNextBatch();
}

function renderNextBatch() {
  FILTERED.slice(RENDERED, RENDERED + BATCH).forEach(function (g, i) { grid.appendChild(buildCard(g, RENDERED + i)); });
  RENDERED = Math.min(FILTERED.length, RENDERED + BATCH);
  loadMoreBtn.style.display = RENDERED >= FILTERED.length ? 'none' : 'inline-block';
}

function sideHtml(s, isModal) {
  var color = managerColor(s.key), prefix = isModal ? 'mx-modal-' : 'mx-';
  var logo = mgr.logo(s.key);
  var fallback = '<div class="' + (isModal ? 'mx-modal-logo-fallback' : 'mx-logo-fallback') + '" style="background:' + color +
    (logo ? '' : ';display:flex') + '">' + esc(s.short.charAt(0).toUpperCase()) + '</div>';
  var img = logo ? '<img class="' + (isModal ? 'mx-modal-logo' : 'mx-logo') + '" src="' + esc(logo) +
    '" alt="" onerror="this.style.display=\'none\';this.nextElementSibling.style.display=\'flex\';" style="background:' + color + '">' : '';
  return '<div class="' + prefix + 'side ' + (isModal ? 'mx-modal-team ' : '') + (s.won ? 'mx-win' : 'mx-lose') +
    '" style="--side-color:' + color + ';--side-rgb:' + rgb(color) + '">' +
    (isModal ? '' : '<div class="mx-logo-wrap">') + img + fallback + (isModal ? '' : '</div>') +
    '<div class="' + prefix + (isModal ? 'team-name' : 'side-name') + '">' + esc(s.short) + '</div>' +
    '<div class="' + prefix + (isModal ? 'team-sub' : 'side-team') + '">' + esc(s.team) + '</div>' +
    // a two-week round: ESPN's total, with the per-week score every comparison uses beneath it
    '<div class="' + prefix + (isModal ? 'team-score' : 'side-score') + '">' + (s.total != null ? s.total : s.score).toFixed(2) + '</div>' +
    (s.total != null ? '<div class="' + prefix + (isModal ? 'team-sub' : 'side-team') + '">' + s.score.toFixed(2) + ' per week</div>' : '') +
    (s.won ? '<div class="mx-win-badge" style="--side-color:' + color + '">Winner</div>' : '') + '</div>';
}

function buildCard(g, idx) {
  var el = document.createElement('div'), tier = playoffTier(g);
  el.className = 'mx-card glass' + (tier ? ' mx-po mx-po-' + tier : '');
  el.style.animationDelay = (Math.min(idx % BATCH, 11) * 0.03) + 's';
  el.innerHTML = '<div class="mx-card-tags"><span class="mx-tag" style="--tag-color:' + (seasonColor(cfg, g.season) || '#888') + '">' +
    g.season + '</span><span class="mx-tag mx-tag-week">' + esc(g.isPlayoff ? roundLabel(g, true) : 'Wk ' + g.week) + '</span>' +
    (g.isPlayoff ? '<span class="mx-tag mx-tag-playoff">&#127942;</span>' : '') + '</div>' +
    '<div class="mx-card-body">' + sideHtml(g.a, false) + '<div class="mx-center"><div class="mx-vs">VS</div><div class="mx-margin">' +
    g.margin.toFixed(1) + ' pt' + (g.margin === 1 ? '' : 's') + '</div></div>' + sideHtml(g.b, false) + '</div>';
  el.addEventListener('click', function () { openModal(FILTERED, idx); });
  return el;
}

function playerRow(p) {
  return '<div class="mx-player-row"><span class="mx-player-slot">' + esc(slotLabel(p.slot)) + '</span>' +
    '<span class="mx-pos-badge" style="--pos-color:' + (POSITION_SWATCH[p.pos] || '#666') + '">' + esc(p.pos) + '</span>' +
    '<span class="mx-player-name">' + esc(p.name) + '</span><span class="mx-player-pts">' + p.pts.toFixed(2) + '</span></div>';
}

function rosterColumn(s, uid) {
  return '<div><div class="mx-roster-section-label">Starting Lineup</div>' + s.starters.map(playerRow).join('') +
    (s.bench.length ? '<button class="mx-bench-toggle" data-target="bench-' + uid + '">Show bench (' + s.bench.length +
      ') &#9662;</button><div class="mx-bench-list" id="bench-' + uid + '">' + s.bench.map(playerRow).join('') + '</div>' : '') + '</div>';
}

function buildModalBody(g) {
  document.getElementById('modalBody').innerHTML =
    '<div class="mx-modal-header"><div class="mx-modal-tags"><span class="mx-tag" style="--tag-color:' +
    (seasonColor(cfg, g.season) || '#888') + '">' + g.season + '</span><span class="mx-tag mx-tag-week">' +
    esc(g.isPlayoff ? roundLabel(g, false) : 'Week ' + g.week) + '</span>' +
    (g.isPlayoff ? '<span class="mx-tag mx-tag-playoff">&#127942; Playoffs</span>' : '') + '</div>' +
    '<div class="mx-modal-vs">' + sideHtml(g.a, true) + '<div class="mx-modal-atsign">VS</div>' + sideHtml(g.b, true) + '</div></div>' +
    '<div class="mx-modal-columns">' + rosterColumn(g.a, 'a') + rosterColumn(g.b, 'b') + '</div>';
  document.querySelectorAll('.mx-bench-toggle').forEach(function (btn) {
    btn.addEventListener('click', function () {
      var t = document.getElementById(btn.dataset.target), open = t.classList.toggle('open');
      btn.innerHTML = open ? 'Hide bench &#9652;' : 'Show bench (' + t.children.length + ') &#9662;';
    });
  });
}

function openModal(list, idx) {
  modalList = list; modalIndex = idx;
  buildModalBody(list[idx]);
  document.getElementById('modalOverlay').classList.add('open');
  document.body.classList.add('mx-modal-lock');
}
function closeModal() {
  document.getElementById('modalOverlay').classList.remove('open');
  document.body.classList.remove('mx-modal-lock');
}
function navModal(dir) {
  if (!modalList.length) return;
  modalIndex = (modalIndex + dir + modalList.length) % modalList.length;
  buildModalBody(modalList[modalIndex]);
}

config().then(function (c) {
  cfg = c;
  mgr = managers(c);
  drawNav(c, 'matchups');
  drawFooter(c);
  return load('data/v1/matchups.json').then(init);
}).catch(function (err) {
  console.error(err);
  heroSub.textContent = 'The matchups could not be loaded.';
  show(grid, 'error');
});
