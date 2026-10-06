/* Hall of Champions: a timeline of every champion, the championship game scores, and one card per
   finished season (record, scoring, the finals margin, and the starters of each playoff round).

   Reads config.json, data/v1/champions.json (schema "champions") and data/v1/headshots.json
   (desktop only, as on the Stage A page). Ported from the Stage A page with the same layout
   (decision 7.14). What was written into the page now comes from the league:
     logos       a manager's championship logo for that season (league.yaml championship_logos),
                 else their logo, else the league's
     card tint   theme.champion_tints for the season, else the champion's color
     photos      the league's editorial champions.yaml, shown below the season they name */

import { config, load, show } from '../core/data.js';
import { managers } from '../core/managers.js';
import { drawNav, drawFooter } from '../core/nav.js';
import { url, esc } from '../core/site.js';
import { rgb, POSITION_SWATCH } from '../core/theme.js';

var Chart = window.Chart;
var IS_MOBILE_VIEWPORT = window.matchMedia('(max-width: 768px)').matches;
var DEFAULT_TINT = '156,148,156';
var KNOWN_BADGES = ['QB', 'RB', 'WR', 'TE', 'FLEX', 'K', 'D/ST'];

var cfg, mgr, HEADSHOTS = {};

/* ── names ── */
function fullName(key) { return mgr.name(key); }
function firstName(key) { return String(fullName(key)).split(' ')[0]; }
/* "Carmine P." for the timeline: first name and the last name's initial, suffixes dropped */
function timelineName(key) {
  var parts = String(fullName(key)).replace(/,?\s+(Jr\.?|Sr\.?|II|III|IV)$/i, '').split(' ');
  return parts.length > 1 ? parts[0] + ' ' + parts[parts.length - 1][0] + '.' : parts[0];
}

/* ── images and colors ── */
function logoFor(key, season) {
  var m = mgr.get(key) || {};
  var path = (m.championship_logos || {})[String(season)] || m.logo || cfg.league.logo;
  return path ? url(path) : '';
}
function initials(key) {
  var parts = String(fullName(key)).replace(/,?\s+(Jr\.?|Sr\.?|II|III|IV)$/i, '').split(' ').filter(Boolean);
  return ((parts[0] || '?')[0] + (parts.length > 1 ? parts[parts.length - 1][0] : '')).toUpperCase();
}
function logoColor(key) { return mgr.color(key, 'dark') || '#9c949c'; }
function seasonLogoFor(season) {
  var path = (cfg.league.logos_by_season || {})[String(season)];
  return path ? url(path) : '';
}
function tintRgb(c) {
  var hex = ((cfg.theme || {}).champion_tints || {})[String(c.season)] || mgr.color(c.manager_key, 'dark');
  return hex ? rgb(hex) : DEFAULT_TINT;
}
function headshot(p) {
  if (IS_MOBILE_VIEWPORT || p.player_id == null) return null;
  return HEADSHOTS[String(p.player_id)] || null;
}

/* ── formatting ── */
function recordText(c) {
  return c.wins + '-' + c.losses + (c.ties ? '-' + c.ties : '');
}
function recordHtml(record) {
  var parts = record.split('-');
  if (parts.length !== 2) return esc(record);
  return '<span style="color:#4a8a5a;">' + parts[0] + '</span>'
    + '<span style="color:var(--muted);">-</span>'
    + '<span style="color:#c04a4a;">' + parts[1] + '</span>';
}
function slotLabel(slot) { return slot && slot.indexOf('/') !== -1 && slot !== 'D/ST' ? 'FLEX' : slot; }
function finalRound(c) { return c.rounds.length ? c.rounds[c.rounds.length - 1] : null; }

/* ── card ── */
function renderTeamTotalSlot(seasonPpg, weekTotal) {
  var delta = weekTotal - seasonPpg;
  var wkClass = delta > 0.1 ? 'up' : (delta < -0.1 ? 'down' : '');
  var arrow = wkClass === 'up' ? '&#9650; ' : (wkClass === 'down' ? '&#9660; ' : '');
  var deltaTxt = wkClass ? ' (' + (delta > 0 ? '+' : '') + delta.toFixed(1) + ')' : '';

  return '<div class="roster-slot team-total-slot">'
    + '<div class="roster-slot-top">'
    +   '<span class="pos-badge pos-total">TEAM</span>'
    +   '<span class="roster-name">Total Score</span>'
    + '</div>'
    + '<div class="roster-ppg-row">'
    +   '<span>Season <span class="ppg-val">' + seasonPpg.toFixed(1) + '</span></span>'
    +   '<span>This week <span class="ppg-po ' + wkClass + '">' + arrow + weekTotal.toFixed(1) + deltaTxt + '</span></span>'
    + '</div>'
    + '</div>';
}

function renderRosterSlots(starters) {
  return starters.map(function (r) {
    var pos = slotLabel(r.slot);
    var posClass = KNOWN_BADGES.indexOf(pos) !== -1 ? 'pos-' + pos.replace('/', '').toLowerCase() : 'pos-flex';   // other slots (OP, ...) look like FLEX
    var hasPpg = r.ppg !== null && r.ppg !== undefined;
    var ppg = hasPpg ? +r.ppg.toFixed(1) : null;   // the change is measured from the average as shown
    var seasonTxt = hasPpg ? ppg.toFixed(1) : '&ndash;';
    var weekTxt = r.points.toFixed(1);
    var wkClass = '', deltaTxt = '';
    if (hasPpg) {
      var delta = r.points - ppg;
      if (delta > 0.1) { wkClass = 'up'; deltaTxt = ' (+' + delta.toFixed(1) + ')'; }
      else if (delta < -0.1) { wkClass = 'down'; deltaTxt = ' (' + delta.toFixed(1) + ')'; }
    }
    var arrow = wkClass === 'up' ? '&#9650; ' : (wkClass === 'down' ? '&#9660; ' : '');

    var headshotHtml = '';
    var src = headshot(r);
    if (src) {
      var ringColor = POSITION_SWATCH[r.position] || 'rgba(156,148,156,0.5)';
      headshotHtml = '<img class="roster-headshot" src="' + esc(src) + '" alt="' + esc(r.name)
        + '" style="border-color:' + ringColor + ';" loading="lazy" onerror="this.remove();">';
    }

    return '<div class="roster-slot">'
      + '<div class="roster-slot-top">'
      +   headshotHtml
      +   '<span class="pos-badge ' + posClass + '">' + esc(pos) + '</span>'
      +   '<span class="roster-name">' + esc(r.name) + '</span>'
      + '</div>'
      + '<div class="roster-ppg-row">'
      +   '<span>Season <span class="ppg-val">' + seasonTxt + '</span></span>'
      +   '<span>This week <span class="ppg-po ' + wkClass + '">' + arrow + weekTxt + deltaTxt + '</span></span>'
      + '</div>'
      + '</div>';
  }).join('');
}

function buildCard(c, all) {
  var lastIdx = c.rounds.length - 1; // the championship is shown first
  var toggleBtns = c.rounds.map(function (rd, idx) {
    return '<button class="roster-toggle-btn' + (idx === lastIdx ? ' active' : '') + '" data-year="' + c.season +
      '" data-idx="' + idx + '">' + esc(rd.label) + '</button>';
  }).join('');
  var roundDivs = c.rounds.map(function (rd, idx) {
    var displayStyle = idx === lastIdx ? '' : 'style="display:none;"';
    return '<div class="champ-roster" data-year="' + c.season + '" data-idx="' + idx + '" ' + displayStyle + '>'
      + renderRosterSlots(rd.starters || [])
      + renderTeamTotalSlot(c.pf_per_game, rd.points)
      + '</div>';
  }).join('');

  var ringCount = all.filter(function (x) { return x.manager_key === c.manager_key; }).length;
  var ringBadge = ringCount > 1 ? '<span class="ring-badge">&#127942; ' + ringCount + 'x Champion</span>' : '';

  var fin = finalRound(c);
  var marginHtml = '';
  if (fin && fin.opponent_points != null) {
    var total = fin.points + fin.opponent_points;
    var champPct = (fin.points / total * 100).toFixed(1);
    var runnerPct = (100 - champPct).toFixed(1);
    marginHtml = '<div class="champ-margin-wrap">'
      + '<div class="champ-margin-labels">'
      +   '<span class="lbl-champ">' + esc(firstName(c.manager_key)) + ' &middot; ' + fin.points.toFixed(1) + '</span>'
      +   '<span class="lbl-runner">' + esc(firstName(c.runner_up_key)) + ' &middot; ' + fin.opponent_points.toFixed(1) + '</span>'
      + '</div>'
      + '<div class="champ-margin-bar">'
      +   '<div class="seg-champ" style="width:' + champPct + '%;"></div>'
      +   '<div class="seg-runner" style="width:' + runnerPct + '%;"></div>'
      + '</div>'
      + '</div>';
  }

  var seasonLogo = seasonLogoFor(c.season);
  return '<div class="champ-card glass" id="champ-' + c.season + '" style="--tint:' + tintRgb(c) + ';">'
    + '<div class="champ-banner">'
    +   (seasonLogo ? '<div class="champ-season-logo-wrap"><img class="champ-season-logo" src="' + esc(seasonLogo) + '" alt="' +
          c.season + ' season logo" onerror="this.parentElement.remove()"></div>' : '')
    +   '<div class="champ-banner-flex">'
    +     '<div class="champ-logo-wrap">' + (logoFor(c.manager_key, c.season)
            ? '<img class="champ-logo" src="' + esc(logoFor(c.manager_key, c.season)) + '" alt="' + esc(fullName(c.manager_key)) + ' ' + c.season + ' logo">'
            : '<div class="champ-logo champ-logo-initials" style="background-color:' + logoColor(c.manager_key) + ';">' + esc(initials(c.manager_key)) + '</div>') + '</div>'
    +     '<div class="champ-banner-text">'
    +       '<div class="champ-year-badge">&#127942; ' + c.season + ' Champion</div>'
    +       '<div class="champ-title">' + esc(c.team_name || '') + '</div>'
    +       '<div class="champ-manager-line"><strong>' + esc(fullName(c.manager_key)) + '</strong>' + ringBadge + '</div>'
    +     '</div>'
    +   '</div>'
    + '</div>'
    + marginHtml
    + '<div class="champ-stats">'
    +   '<div class="champ-stat">'
    +     '<div class="champ-stat-value">' + recordHtml(recordText(c)) + '</div>'
    +     '<div class="champ-stat-label">Record</div>'
    +   '</div>'
    +   '<div class="champ-stat">'
    +     '<div class="champ-stat-value">' + c.pf_per_game.toFixed(1) + '</div>'
    +     '<div class="champ-stat-label">Reg Season PPG</div>'
    +   '</div>'
    +   '<div class="champ-stat">'
    +     '<div class="champ-stat-value">' + (c.playoff_ppg != null ? c.playoff_ppg.toFixed(1) : '--') + '</div>'
    +     '<div class="champ-stat-label">Playoff PPG</div>'
    +   '</div>'
    +   '<div class="champ-stat">'
    +     '<div class="champ-stat-value">' + (c.runner_up_key ? esc(firstName(c.runner_up_key)) : '--') + '</div>'
    +     '<div class="champ-stat-label">Runner-Up</div>'
    +   '</div>'
    + '</div>'
    + '<div class="roster-toggle-row">'
    +   '<div class="roster-toggle">' + toggleBtns + '</div>'
    + '</div>'
    + roundDivs
    + '</div>';
}

function photoHtml(p) {
  return '<div class="trophy-wrap glass">'
    + (p.label ? '<div class="trophy-label">&#128248; ' + esc(p.label) + '</div>' : '')
    + '<img src="' + esc(url(p.image)) + '" class="trophy-photo" alt="' + esc(p.alt || p.label || '') + '">'
    + '</div>';
}

function buildChampList(champs, photos) {
  var list = document.getElementById('champ-list');
  var html = '';
  champs.forEach(function (c) {
    html += buildCard(c, champs);
    photos.filter(function (p) { return p.after === c.season; }).forEach(function (p) { html += photoHtml(p); });
  });
  list.innerHTML = html;

  list.addEventListener('click', function (e) {
    var btn = e.target.closest('.roster-toggle-btn');
    if (btn) { toggleRound(btn); return; }
    var photo = e.target.closest('.trophy-photo');
    if (photo) openLightbox(photo.src, photo.alt);
  });

  var revealTargets = list.querySelectorAll('.champ-card, .trophy-wrap');
  var revealObserver = new IntersectionObserver(function (entries) {
    entries.forEach(function (entry) {
      if (entry.isIntersecting) {
        entry.target.classList.add('revealed');
        revealObserver.unobserve(entry.target);
      }
    });
  }, { threshold: 0.12 });
  revealTargets.forEach(function (el) { revealObserver.observe(el); });
}

function toggleRound(btn) {
  var year = btn.dataset.year, idx = btn.dataset.idx;
  document.querySelectorAll('.champ-roster[data-year="' + year + '"]').forEach(function (el) {
    el.style.display = el.dataset.idx === idx ? '' : 'none';
  });
  btn.parentElement.querySelectorAll('.roster-toggle-btn').forEach(function (b) { b.classList.remove('active'); });
  btn.classList.add('active');
}

/* ── lightbox ── */
var lightbox = document.getElementById('lightbox');
function openLightbox(src, alt) {
  var img = document.getElementById('lightbox-img');
  img.src = src;
  img.alt = alt || '';
  lightbox.classList.add('active');
  document.body.style.overflow = 'hidden';
}
function closeLightbox() {
  lightbox.classList.remove('active');
  document.body.style.overflow = '';
}
lightbox.addEventListener('click', closeLightbox);
document.addEventListener('keydown', function (e) { if (e.key === 'Escape') closeLightbox(); });

/* ── timeline ── */
function drawTimeline(finals) {
  var el = document.getElementById('timeline');
  var logoR = 24, ringR = logoR + 4, n = finals.length;
  var vbW = 1000, vbH = 105, padX = 80, lineY = 34;
  var x0 = padX, xN = vbW - padX;

  var svgParts = [];
  svgParts.push('<svg viewBox="0 0 ' + vbW + ' ' + vbH + '" xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" style="width:100%;display:block;">');
  if (n > 1) svgParts.push('<line x1="' + x0 + '" y1="' + lineY + '" x2="' + xN + '" y2="' + lineY + '" stroke="rgba(212,175,55,0.25)" stroke-width="3"/>');

  finals.forEach(function (f, i) {
    var cx = n > 1 ? Math.round(padX + (xN - x0) / (n - 1) * i) : vbW / 2;
    var cy = lineY;
    var clipId = 'timeline-clip-' + f.season;
    var logoUrl = esc(logoFor(f.champ, f.season));

    svgParts.push('<a data-year="' + f.season + '" style="cursor:pointer;">');
    svgParts.push('<circle cx="' + cx + '" cy="' + cy + '" r="' + ringR + '" fill="rgba(245,240,232,1)" stroke="rgba(212,175,55,0.9)" stroke-width="3"/>');
    svgParts.push('<clipPath id="' + clipId + '"><circle cx="' + cx + '" cy="' + cy + '" r="' + logoR + '"/></clipPath>');
    if (logoUrl) {
      svgParts.push('<image href="' + logoUrl + '" xlink:href="' + logoUrl + '" x="' + (cx - logoR) + '" y="' + (cy - logoR)
        + '" width="' + (logoR * 2) + '" height="' + (logoR * 2) + '" clip-path="url(#' + clipId + ')" preserveAspectRatio="xMidYMid slice"/>');
    } else {   // no logo: the champion's initials on their color
      svgParts.push('<circle cx="' + cx + '" cy="' + cy + '" r="' + logoR + '" fill="' + logoColor(f.champ) + '"/>');
      svgParts.push('<text x="' + cx + '" y="' + (cy + 5) + '" text-anchor="middle" font-family="Outfit,sans-serif" font-size="15" font-weight="800" fill="#fff">' + esc(initials(f.champ)) + '</text>');
    }
    var yearY = cy + logoR + 20;
    svgParts.push('<text x="' + cx + '" y="' + yearY + '" text-anchor="middle" font-family="Outfit,sans-serif" font-size="12" font-weight="800" fill="#3d3a38">' + f.season + '</text>');
    svgParts.push('<text x="' + cx + '" y="' + (yearY + 14) + '" text-anchor="middle" font-family="Outfit,sans-serif" font-size="11" font-weight="700" fill="#3d3a38">' + esc(timelineName(f.champ)) + '</text>');
    svgParts.push('</a>');
  });

  svgParts.push('</svg>');
  el.innerHTML = svgParts.join('');
  el.addEventListener('click', function (e) {
    var a = e.target.closest('a[data-year]');
    var card = a && document.getElementById('champ-' + a.dataset.year);
    if (card) card.scrollIntoView({ behavior: 'smooth', block: 'start' });
  });
}

/* ── championship game scores ── */
function drawFinalsChart(finals) {
  if (!Chart) return;
  Chart.defaults.font.family = "'Outfit', sans-serif";
  Chart.defaults.color = '#5a5550';

  var labels = finals.map(function (f) { return String(f.season); });
  var champScores = finals.map(function (f) { return f.champ_score; });
  var runnerScores = finals.map(function (f) { return f.runner_score; });
  var margins = finals.map(function (f) { return +(f.champ_score - f.runner_score).toFixed(2); });
  // the axis starts at 60 as on the Stage A page, lower when a league's finals scored less
  var low = Math.min.apply(null, champScores.concat(runnerScores));
  var yMin = Math.max(0, Math.min(60, Math.floor((low - 10) / 10) * 10));

  new Chart(document.getElementById('chart-finals').getContext('2d'), {
    type: 'bar',
    data: {
      labels: labels,
      datasets: [
        { label: 'Champion', data: champScores, backgroundColor: 'rgba(212,175,55,0.72)', borderColor: 'rgba(212,175,55,1)',
          borderWidth: 1.5, borderRadius: 3, order: 1 },
        { label: 'Runner-Up', data: runnerScores, backgroundColor: 'rgba(156,148,156,0.35)', borderColor: 'rgba(156,148,156,0.7)',
          borderWidth: 1.5, borderRadius: 3, order: 2 },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: { mode: 'index', intersect: false },
      plugins: {
        legend: { position: 'top', align: 'end', labels: { boxWidth: 12, padding: 16, color: '#5a5550' } },
        tooltip: {
          callbacks: {
            title: function (items) { return items[0].label + ' Championship'; },
            label: function (ctx) {
              var f = finals[ctx.dataIndex];
              if (ctx.datasetIndex === 0) return firstName(f.champ) + ': ' + f.champ_score;
              return firstName(f.runner) + ': ' + f.runner_score;
            },
            afterBody: function (items) { return ['Margin: +' + margins[items[0].dataIndex]]; },
          },
        },
      },
      scales: {
        x: { grid: { color: 'rgba(156,148,156,0.15)', drawBorder: false }, ticks: { color: '#8a8480' } },
        y: {
          grid: { color: 'rgba(156,148,156,0.15)', drawBorder: false },
          ticks: { color: '#8a8480' },
          title: { display: true, text: 'Points Scored', color: '#8a8480', font: { size: 11 } },
          min: yMin,
        },
      },
    },
  });
}

function init(data) {
  var seasons = data.seasons || [];
  if (!seasons.length) {
    show(document.getElementById('champ-list'), 'empty', 'No champions yet: the first one is crowned when a season finishes.');
    show(document.getElementById('timeline'), 'empty', 'No champions yet.');
    document.getElementById('finalsSection').hidden = true;
    return;
  }
  var champs = seasons.slice().sort(function (a, b) { return b.season - a.season; });   // newest first
  var finals = seasons.slice().sort(function (a, b) { return a.season - b.season; }).map(function (c) {
    var fin = finalRound(c) || {};
    return { season: c.season, champ: c.manager_key, champ_score: fin.points,
             runner: c.runner_up_key, runner_score: fin.opponent_points };
  }).filter(function (f) { return f.champ_score != null && f.runner_score != null; });

  drawTimeline(finals);
  drawFinalsChart(finals);
  buildChampList(champs, data.photos || []);
}

config().then(function (c) {
  cfg = c;
  mgr = managers(c);
  drawNav(c, 'champions');
  drawFooter(c);
  document.getElementById('pageSub').textContent = 'Every championship team since ' + c.league.name + "'s founding";
  var heads = IS_MOBILE_VIEWPORT ? Promise.resolve(null)
    : load('data/v1/headshots.json').catch(function () { return null; });
  return Promise.all([load('data/v1/champions.json'), heads]).then(function (res) {
    HEADSHOTS = (res[1] && res[1].players) || {};
    init(res[0]);
  });
}).catch(function (err) {
  console.error(err);
  show(document.getElementById('champ-list'), 'error', 'The champions could not be loaded.');
});
