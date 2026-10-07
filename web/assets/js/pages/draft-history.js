/* Draft History: every pick of every season as a board, one row per round and one column per
   manager in draft-slot order. Tap a pick for its stats.

   Reads config.json and data/v1/draft-history.json (schema "draft-history"). Ported from the Stage A
   page with the same layout (decision 7.14). What was written into the page now comes from the
   league:
     seasons      the drafted seasons, newest first, the live one selected; swatches from
                  theme.season_colors
     managers     names, short names, colors and logos from config.json; the filter lists the
                  visible managers, the board every manager who drafted (decision 7.3)
     rounds       each season's own round count; the position legend shows the positions drafted
     placement    each pick sits in the column of the manager who made it, so a pick traded during
                  the draft is under its new owner (the page placed it by the pick's slot) */

import { config, load } from '../core/data.js';
import { managers } from '../core/managers.js';
import { drawNav, drawFooter, drawSubnav } from '../core/nav.js';
import { esc } from '../core/site.js';
import { seasonColor } from '../core/theme.js';

var cfg, mgr, DATA;
var byPick = {};          // "season|round|slot" -> pick
var currentYear = null;
var currentManagerFilter = 'all';
var tooltip = document.getElementById('pick-tooltip');
var activeCell = null;

function posClass(pos) {
  return { RB: 'rb', WR: 'wr', QB: 'qb', TE: 'te', K: 'k', 'D/ST': 'dst' }[pos] || 'wr';
}

function seasonInfo(year) {
  return DATA.seasons.find(function (s) { return s.season === year; }) || null;
}

function buildBoard(year) {
  var slotOrder = DATA.slot_order[String(year)];
  var info = seasonInfo(year);
  if (!slotOrder || !info) return;

  var head = '<tr><th style="width:48px;min-width:48px;"></th>';
  slotOrder.forEach(function (key) {
    var logo = mgr.logo(key);
    head += '<th data-manager="' + esc(key) + '">'
      + (logo ? '<img src="' + esc(logo) + '" alt="' + esc(mgr.name(key)) + '" class="manager-logo" onerror="this.style.display=\'none\'">' : '')
      + '<span class="manager-name-header">' + esc(mgr.short(key)) + '</span>'
      + '</th>';
  });
  document.getElementById('board-head').innerHTML = head + '</tr>';

  var body = '';
  for (var round = 1; round <= info.rounds; round++) {
    body += '<tr><td class="round-cell">Rd ' + round + '</td>';
    slotOrder.forEach(function (key, slotIdx) {
      var pick = byPick[year + '|' + round + '|' + (slotIdx + 1)];
      if (!pick) { body += '<td data-manager="' + esc(key) + '"></td>'; return; }
      var pc = posClass(pick.position);
      body += '<td class="cell-' + pc + '" data-manager="' + esc(key) + '" data-pick="' + esc(year + '|' + round + '|' + (slotIdx + 1)) + '">'
        + '<div class="pick-cell">'
        + '<span class="pick-name">' + esc(pick.name) + '</span>'
        + '<span class="pos-badge pos-' + pc + '">' + esc(pick.position) + '</span>'
        + '</div></td>';
    });
    body += '</tr>';
  }
  document.getElementById('board-body').innerHTML = body;
  applyManagerFilter();
}

function showTip(event, cell) {
  event.stopPropagation();
  if (activeCell === cell) { hideTip(); return; }
  activeCell = cell;
  var pick = byPick[cell.dataset.pick];
  var html = '<div class="tip-name">' + esc(pick.name) + '</div>';
  html += '<div class="tip-stat">Position: <span class="pos-badge pos-' + posClass(pick.position) + '">' + esc(pick.position) + '</span></div>';
  html += '<div class="tip-stat">Manager: <span>' + esc(mgr.name(pick.manager_key)) + '</span></div>';
  html += '<div class="tip-stat">Round: <span>' + pick.round + '</span></div>';
  if (pick.ppg !== null && pick.ppg !== undefined) {
    html += '<div class="tip-stat">PPR/G: <span>' + pick.ppg.toFixed(1) + '</span></div>';
    html += '<div class="tip-stat">Games: <span>' + pick.games + '</span></div>';
  } else {
    html += '<div class="tip-stat" style="opacity:0.5">Stats not available</div>';
  }
  tooltip.innerHTML = html;
  var rect = cell.getBoundingClientRect();
  tooltip.style.left = Math.min(rect.left + rect.width / 2, window.innerWidth - 230) + 'px';
  tooltip.style.top = (rect.top - 10) + 'px';
  tooltip.style.transform = 'translate(-50%, -100%)';
  tooltip.classList.add('visible');
}

function hideTip() {
  tooltip.classList.remove('visible');
  activeCell = null;
}

function applyManagerFilter() {
  document.querySelectorAll('#draft-board th[data-manager], #draft-board td[data-manager]').forEach(function (c) {
    c.classList.toggle('mgr-dim', currentManagerFilter !== 'all' && c.getAttribute('data-manager') !== currentManagerFilter);
  });
}

function drawFilters() {
  var seasons = DATA.seasons.map(function (s) { return s.season; }).sort(function (a, b) { return b - a; });
  document.getElementById('season-row').insertAdjacentHTML('beforeend', seasons.map(function (y) {
    var c = seasonColor(cfg, y);
    return '<button class="season-btn year-swatch-btn' + (y === currentYear ? ' active' : '') + '"'
      + (c ? ' style="--swatch-color:' + esc(c) + ';"' : '') + ' data-year="' + y + '">' + y + '</button>';
  }).join(''));
  var list = mgr.visible.slice().sort(function (a, b) { return a.name < b.name ? -1 : a.name > b.name ? 1 : 0; });
  document.getElementById('manager-row').insertAdjacentHTML('beforeend',
    '<button class="mgr-btn mgr-all active" data-manager="all">All Managers</button>' +
    list.map(function (m) {
      return '<button class="mgr-btn" style="--mgr-color:' + esc(mgr.color(m.key) || '#9c949c') + ';" data-manager="' + esc(m.key) + '">'
        + '<span class="mgr-dot"></span>' + esc(m.name) + '</button>';
    }).join(''));
  // the legend lists the positions this league drafted
  var drafted = new Set(DATA.picks.map(function (p) { return p.position; }));
  document.querySelectorAll('.pos-legend .legend-item[data-pos]').forEach(function (el) {
    if (!drafted.has(el.dataset.pos)) el.remove();
  });
}

function bind() {
  document.getElementById('season-row').addEventListener('click', function (e) {
    var btn = e.target.closest('.season-btn');
    if (!btn) return;
    document.querySelectorAll('.season-btn').forEach(function (b) { b.classList.remove('active'); });
    btn.classList.add('active');
    currentYear = Number(btn.dataset.year);
    buildBoard(currentYear);
  });
  document.getElementById('manager-row').addEventListener('click', function (e) {
    var btn = e.target.closest('.mgr-btn');
    if (!btn) return;
    document.querySelectorAll('.mgr-btn').forEach(function (b) { b.classList.remove('active'); });
    btn.classList.add('active');
    currentManagerFilter = btn.dataset.manager;
    applyManagerFilter();
  });
  document.getElementById('board-body').addEventListener('click', function (e) {
    var cell = e.target.closest('td[data-pick]');
    if (cell) showTip(e, cell);
  });
  document.addEventListener('click', hideTip);
}

config().then(function (c) {
  cfg = c;
  mgr = managers(cfg);
  drawNav(cfg, 'draft-history');
  drawSubnav(cfg, 'draft-history');
  drawFooter(cfg);
  return load('data/v1/draft-history.json');
}).then(function (d) {
  DATA = d;
  // each pick under its drafter's slot; a drafter with two picks in one round keeps the second in the
  // column the pick came from (its position in the round: snake order)
  d.picks.forEach(function (p) {
    var key = p.season + '|' + p.round + '|' + p.draft_slot;
    if (byPick[key]) {
      var n = (d.slot_order[String(p.season)] || []).length;
      var idx = (p.overall_pick - 1) % n;
      key = p.season + '|' + p.round + '|' + (p.round % 2 === 1 ? idx + 1 : n - idx);
    }
    if (!byPick[key]) byPick[key] = p;
  });
  var seasons = d.seasons.map(function (s) { return s.season; });
  if (!seasons.length) {
    document.getElementById('board-body').innerHTML = '<tr><td><div class="data-state data-state-empty">No drafts yet.</div></td></tr>';
    return;
  }
  currentYear = Math.max.apply(null, seasons);
  drawFilters();
  bind();
  buildBoard(currentYear);
}).catch(function (err) {
  console.error(err);
  document.getElementById('board-body').innerHTML = '<tr><td><div class="data-state data-state-error">This section could not be loaded.</div></td></tr>';
});
