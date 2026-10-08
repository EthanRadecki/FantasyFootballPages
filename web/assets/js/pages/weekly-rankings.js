/* Weekly Rankings: each ranked week's power rankings (a countdown of rank cards with the write-ups),
   the matchup of the week, draft and season insights, the season's ranking trajectory, playoff odds,
   King of the Hill, and the playoff previews.

   Reads config.json, data/v1/weekly-rankings/index.json (schema "weekly-rankings-index"), one
   data/v1/weekly-rankings/<season>-wNN.json per week ("weekly-rankings"), the playoff previews
   ("weekly-rankings-preview"), data/v1/playoff-odds.json and data/v1/headshots.json. Ported from the
   Stage A page with the same layout (decision 7.14). What was written into the page now comes from
   the league:
     names, colors, logos   config.json managers, by manager key
     season accent, logo    theme.season_accents and league.logos_by_season (none: the site's accent)
     playoff line, tiers    the season's odds cutoff (else its playoff team count); rank axis from its team count
     odds line              the odds cutoff over the season's team count; trials from the odds file
     bracket rounds         the season's playoff round names
     headshots              by player id
     projection axis        100-130 points, widened to the data when a league scores outside it */

import { config, load } from '../core/data.js';
import { managers } from '../core/managers.js';
import { drawNav, drawFooter } from '../core/nav.js';
import { url, esc } from '../core/site.js';
import { rgb, seasonInfo } from '../core/theme.js';
import { seasonRange } from '../core/format.js';

var Chart = window.Chart;
var DIR = 'data/v1/weekly-rankings/';

var cfg, mgr, INDEX = null;
var jsonCache = {};          // { file: data }
var trajectoryChart = null;
var playoffOddsChart = null;
var playoffOddsData = null;  // data/v1/playoff-odds.json
var headshots = null;        // player id -> image

/* ── league facts ── */
function nameOf(key, fallback) { var m = key && mgr.get(key); return m ? m.name : (fallback || key || ''); }
function colorOf(key) { return mgr.color(key, 'dark'); }
function logoOf(key) { return mgr.logo(key); }
function initials(name) {
  var parts = String(name || '').replace(/,?\s+(Jr\.?|Sr\.?|II|III|IV)$/i, '').replace(/[^A-Za-z' .]/g, '')
    .split(' ').filter(Boolean);
  return ((parts[0] || '?')[0] + (parts.length > 1 ? parts[parts.length - 1][0] : '')).toUpperCase();
}
/* a manager's logo, or their initials on their color when the league has no logo for them */
function logoHtml(key, cls, extra) {
  var src = logoOf(key);
  if (src) return '<img class="' + cls + '" src="' + esc(src) + '" alt=""' + (extra || '') + '>';
  return '<div class="' + cls + ' logo-initials" style="background:' + esc(colorOf(key) || '#9c949c') + ';">' +
    esc(initials(nameOf(key))) + '</div>';
}
function season(s) { return seasonInfo(cfg, s) || {}; }
/* the playoff line: the league's odds cutoff for the season (analysis.playoff_odds.cutoff), else ESPN's
   playoff team count */
function playoffCount(s) {
  var o = playoffOddsData && (playoffOddsData.seasons || []).find(function (x) { return x.season === Number(s); });
  return (o && o.cutoff) || season(s).playoff_team_count || null;
}
function teamCount(s, teams) { return season(s).team_count || (teams ? teams.length : null); }
function seasonManagers(s) {
  return mgr.visible.filter(function (m) { return !m.seasons || m.seasons.indexOf(Number(s)) !== -1; })
    .slice().sort(function (a, b) { return a.name < b.name ? -1 : a.name > b.name ? 1 : 0; });
}

/* ── season theme ──
   Retints the page to the selected season's accent by overriding the site's --accent variables,
   and shows that season's logo. A season without an accent keeps the site's default. */
function applySeasonTheme(s) {
  var root = document.documentElement;
  var color = ((cfg.theme || {}).season_accents || {})[String(s)];
  if (!color) {
    root.style.removeProperty('--accent');
    root.style.removeProperty('--accent-rgb');
    root.style.removeProperty('--accent-glow');
  } else {
    var c = rgb(color);
    root.style.setProperty('--accent', color);
    root.style.setProperty('--accent-rgb', c);
    root.style.setProperty('--accent-glow', 'rgba(' + c + ',0.18)');
  }
  var logo = document.getElementById('season-logo');
  var path = (cfg.league.logos_by_season || {})[String(s)];
  if (logo) {
    logo.onerror = function () { logo.style.display = 'none'; };
    logo.onload = function () { logo.style.display = 'inline-block'; };
    logo.alt = cfg.league.name + ' ' + s;
    if (path) logo.src = url(path);
    else { logo.removeAttribute('src'); logo.style.display = 'none'; }
  }
}

/* ── tier ── */
function getTierClass(rank, cutoff) {
  if (rank === 1) return 'tier-gold';
  if (rank === 2) return 'tier-silver';
  if (rank === 3) return 'tier-bronze';
  if (rank === 4) return 'tier-contender';
  if (rank <= (cutoff || 8)) return 'tier-mid';
  return 'tier-bottom';
}

/* ── Matchup of the Week ──
   Each side carries its own snapshot of rank, record and starting lineup, so the section is
   self-contained. */
function motwPosClass(pos) {
  if (pos === 'D/ST') return 'motw-pos-DST';
  if (pos === 'K') return 'motw-pos-K';
  return 'motw-pos-' + pos;
}

function renderMatchupOfWeek(data) {
  var wrap = document.getElementById('motw-wrap');
  var motw = data.matchup_of_the_week;
  if (!motw || !motw.team_a || !motw.team_b) { wrap.style.display = 'none'; return; }
  var a = motw.team_a, b = motw.team_b;
  var hide = ' onerror="this.style.display=\'none\'"';

  function side(t, cls) {
    return '<div class="motw-team ' + cls + '">'
      + '<div class="motw-team-top">'
      + logoHtml(t.manager_key, 'motw-logo', hide)
      + '<div><div class="motw-manager">' + esc(nameOf(t.manager_key, t.manager)) + '</div>'
      + (t.rank ? '<div class="motw-rank-badge">Week ' + data.week + ' Rank #' + t.rank + '</div>' : '')
      + '</div></div>'
      + (t.record ? '<div class="motw-record">' + esc(t.record) + '</div>' : '')
      + '</div>';
  }
  var html = '<div class="motw-header">' + side(a, 'away') + '<div class="motw-vs">vs</div>' + side(b, 'home') + '</div>';

  // slot by slot: the higher projection at each slot is bolded in the accent color
  html += '<div class="motw-slots">';
  (a.starters || []).forEach(function (aPlayer, i) {
    var bPlayer = (b.starters || [])[i];
    if (!bPlayer) return;
    var aProj = aPlayer.proj, bProj = bPlayer.proj;
    var aAdv = (aProj != null && bProj != null && aProj > bProj);
    var bAdv = (aProj != null && bProj != null && bProj > aProj);
    html += '<div class="motw-slot-row">'
      + '<div class="motw-player-cell">'
      + '<span class="motw-player-name">' + esc(aPlayer.player) + '</span>'
      + '<span class="motw-player-proj' + (aAdv ? ' adv' : '') + '">' + (aProj != null ? aProj.toFixed(1) : '--') + '</span>'
      + '</div>'
      + '<div class="motw-slot-label ' + motwPosClass(aPlayer.pos) + '">' + esc(aPlayer.slot || aPlayer.pos) + '</div>'
      + '<div class="motw-player-cell home">'
      + '<span class="motw-player-name">' + esc(bPlayer.player) + '</span>'
      + '<span class="motw-player-proj' + (bAdv ? ' adv' : '') + '">' + (bProj != null ? bProj.toFixed(1) : '--') + '</span>'
      + '</div>'
      + '</div>';
  });
  html += '</div>';

  var aTotal = a.proj_total, bTotal = b.proj_total;
  var aWins = (aTotal != null && bTotal != null && aTotal > bTotal);
  var bWins = (aTotal != null && bTotal != null && bTotal > aTotal);
  html += '<div class="motw-totals">'
    + '<div class="motw-total-val away' + (aWins ? ' win' : bWins ? ' lose' : '') + '">' + (aTotal != null ? aTotal.toFixed(1) : '--') + '</div>'
    + '<div class="motw-total-label">Projected<br>Total</div>'
    + '<div class="motw-total-val home' + (bWins ? ' win' : aWins ? ' lose' : '') + '">' + (bTotal != null ? bTotal.toFixed(1) : '--') + '</div>'
    + '</div>';
  if (motw.blurb) html += '<div class="motw-blurb"><p>' + motw.blurb + '</p></div>';   // editorial HTML

  document.getElementById('motw-content').innerHTML = html;
  wrap.style.display = 'block';
}

/* ── King of the Hill ──
   Top 20 players overall and by position (K and D/ST left out). Before any games, by draft order;
   once the week carries season totals, by points, drafted and free-agent players alike. A drafted
   player now on another roster (undrafted_players with a manager) is shown there instead. */
var kothPlayersByPos = null;
var KOTH_TIERS = [1, 2, 3, 4, 5, 5];
var KOTH_TABS = [['overall', 'Overall'], ['QB', 'QB'], ['RB', 'RB'], ['WR', 'WR'], ['TE', 'TE']];

function fetchHeadshots() {
  if (headshots) return Promise.resolve(headshots);
  return load('data/v1/headshots.json')
    .then(function (d) { headshots = d.players || {}; return headshots; })
    .catch(function () { headshots = {}; return headshots; });
}

function buildKothPools(data) {
  var totals = data.player_season_totals;
  var pointsMode = !!(totals && Object.keys(totals).length);
  var elsewhere = {};
  if (pointsMode && data.undrafted_players) {
    data.undrafted_players.forEach(function (p) {
      if (p.manager_key || p.manager) elsewhere[p.player + '|' + p.pos] = true;
    });
  }
  var all = [];
  (data.teams || []).forEach(function (t) {
    (t.draft_picks || []).forEach(function (p) {
      if (p.pos === 'K' || p.pos === 'D/ST') return;
      var key = p.player + '|' + p.pos;
      if (elsewhere[key]) return;
      var metric = pointsMode ? (totals[key] != null ? totals[key] : null) : p.overall;
      all.push({ player: p.player, nfl_team: p.nfl_team, pos: p.pos, manager: nameOf(t.manager_key, t.manager),
                 metric: metric, player_id: p.player_id });
    });
  });
  if (pointsMode && data.undrafted_players) {
    data.undrafted_players.forEach(function (p) {
      if (p.pos === 'K' || p.pos === 'D/ST') return;
      var metric = totals[p.player + '|' + p.pos] != null ? totals[p.player + '|' + p.pos] : null;
      if (metric == null) return;
      all.push({ player: p.player, nfl_team: p.nfl_team || '', pos: p.pos,
                 manager: p.manager_key || p.manager ? nameOf(p.manager_key, p.manager) : 'Free Agent',
                 metric: metric, player_id: p.player_id });
    });
  }
  all.sort(function (a, b) {
    if (a.metric == null) return 1;
    if (b.metric == null) return -1;
    return pointsMode ? (b.metric - a.metric) : (a.metric - b.metric);
  });
  var pools = { overall: all.slice(0, 20) };
  ['QB', 'RB', 'WR', 'TE'].forEach(function (pos) {
    pools[pos] = all.filter(function (p) { return p.pos === pos; }).slice(0, 20);
  });
  pools._pointsMode = pointsMode;
  return pools;
}

function renderKothPyramid(key) {
  var pool = kothPlayersByPos[key] || [];
  var pointsMode = kothPlayersByPos._pointsMode;
  var html = '';
  var idx = 0;
  KOTH_TIERS.forEach(function (size, tierIdx) {
    var tierPlayers = pool.slice(idx, idx + size);
    if (!tierPlayers.length) return;
    html += '<div class="koth-tier koth-tier-' + (tierIdx + 1) + '">';
    tierPlayers.forEach(function (p, i) {
      var rank = idx + i + 1;
      var shot = (headshots && p.player_id != null && headshots[String(p.player_id)]) || '';
      var metricLabel = p.metric == null ? '' : (pointsMode ? p.metric.toFixed(1) + ' pts' : 'Pick #' + p.metric);
      var fallback = '<div class="koth-headshot-fallback">' + esc(initials(p.player)) + '</div>';
      html += '<div class="koth-card">'
        + '<div class="koth-headshot-wrap">'
        + (shot
          ? '<img class="koth-headshot" src="' + esc(shot) + '" alt="' + esc(p.player) + '" data-initials="' + esc(initials(p.player)) + '">'
          : fallback)
        + '<span class="koth-rank-badge">' + rank + '</span>'
        + '</div>'
        + '<div class="koth-name">' + esc(p.player) + '<span class="koth-pos-chip koth-pos-' + esc(p.pos) + '">' + esc(p.pos) + '</span></div>'
        + '<div class="koth-meta">' + (p.nfl_team ? esc(p.nfl_team) + ' &middot; ' : '') + esc(p.manager) + '</div>'
        + (metricLabel ? '<div class="koth-metric">' + metricLabel + '</div>' : '')
        + '</div>';
    });
    html += '</div>';
    idx += size;
  });
  var el = document.getElementById('koth-pyramid');
  el.innerHTML = html;
  el.querySelectorAll('img.koth-headshot').forEach(function (img) {
    img.addEventListener('error', function () {
      img.outerHTML = '<div class="koth-headshot-fallback">' + esc(img.dataset.initials) + '</div>';
    });
  });
}

function selectKothTab(key) {
  document.querySelectorAll('#koth-tabs .draft-insights-tab').forEach(function (tab) {
    tab.classList.toggle('active', tab.dataset.key === key);
  });
  renderKothPyramid(key);
}

function renderTopPlayers(data) {
  var wrap = document.getElementById('koth-wrap');
  if (!data.teams || !data.teams.some(function (t) { return t.draft_picks && t.draft_picks.length; })) {
    wrap.style.display = 'none';
    return Promise.resolve();
  }
  return fetchHeadshots().then(function () {
    kothPlayersByPos = buildKothPools(data);
    document.getElementById('koth-desc').textContent = kothPlayersByPos._pointsMode
      ? 'Top 20 by cumulative fantasy points through ' + (data.label || ('Week ' + (data.week - 1))) + ', recomputed fresh each week. Drafted and free-agent players alike.'
      : 'No games played yet, so this ranks by where each player came off the board -- earliest pick first. Switches to real fantasy points once the season starts.';
    document.getElementById('koth-tabs').innerHTML = KOTH_TABS.map(function (pair, i) {
      return '<button class="draft-insights-tab' + (i === 0 ? ' active' : '') + '" data-key="' + pair[0] + '">' + pair[1] + '</button>';
    }).join('');
    renderKothPyramid('overall');
    wrap.style.display = 'block';
  });
}

/* ── rank cards ── */
function rankChangeHtml(change) {
  if (change === null || change === undefined) return '<span class="rank-change rank-same">NEW</span>';
  if (change > 0) return '<span class="rank-change rank-up">&#9650; ' + change + '</span>';
  if (change < 0) return '<span class="rank-change rank-down">&#9660; ' + Math.abs(change) + '</span>';
  return '<span class="rank-change rank-same">&ndash;</span>';
}

function streakHtml(streak) {
  if (!streak) return '';
  return '<span class="streak-badge ' + (streak[0] === 'W' ? 'streak-w' : 'streak-l') + '">' + esc(streak) + '</span>';
}

function renderRankings(data) {
  var container = document.getElementById('rankings-content');
  var isPreseason = !!data.is_preseason;
  var periodLabel = data.label ? data.label : (isPreseason ? 'Preseason' : ('Week ' + data.week));
  var headerVerb = isPreseason ? 'Preseason Power Rankings' : 'Power Rankings';
  var cutoff = playoffCount(data.season);
  var html = '<div class="rankings-label">&#128202; ' + headerVerb + ' - ' + data.season + ' ' + esc(periodLabel) + '</div>';
  html += '<div class="rankings-list">';

  // worst to best, for the countdown
  var teams = data.teams.slice().sort(function (a, b) { return b.rank - a.rank; });
  // write-ups are filed a week behind the week they sit in, so the toggle names the week they cover
  var blurbLabel = data.blurb_label ? data.blurb_label : (isPreseason ? 'Draft Recap' : ('Week ' + (data.week - 1)));

  var allSos = data.teams.map(function (tt) { return tt.sos_avg_opp_ppg; })
    .filter(function (v) { return v !== null && v !== undefined; });

  teams.forEach(function (t) {
    var key = t.manager_key;
    var name = nameOf(key, t.manager);
    var subParts = [];
    if (t.avg_rank !== null && t.avg_rank !== undefined) subParts.push('Avg rank #' + t.avg_rank.toFixed(1));
    if (t.streak) subParts.push(streakHtml(t.streak));
    var subHtml = subParts.join(' &middot; ');

    var statsHtml = '';
    if (isPreseason) {
      if (t.proj_ppg !== null && t.proj_ppg !== undefined) {
        statsHtml += '<div class="rank-record">' + t.proj_ppg.toFixed(1) + '</div><div class="rank-stat-line">Proj. PPG</div>';
      }
      if (t.adp_value !== null && t.adp_value !== undefined) {
        statsHtml += '<div class="rank-stat-line">ADP Value: <strong>' + (t.adp_value > 0 ? '+' : '') + t.adp_value.toFixed(1) + '</strong></div>';
      }
    } else {
      if (t.record_to_date) statsHtml += '<div class="rank-record">' + esc(t.record_to_date) + '</div>';
      if (t.ppg_to_date !== null && t.ppg_to_date !== undefined) {
        statsHtml += '<div class="rank-stat-line"><strong>' + t.ppg_to_date.toFixed(1) + '</strong> PF/G</div>';
      }
      if (t.last_score !== null && t.last_score !== undefined) {
        statsHtml += '<div class="rank-stat-line">Last: <strong>' + t.last_score + '</strong></div>';
      }
    }

    // SOS badge, colored against this week's spread of opponent PPG
    if (t.sos_avg_opp_ppg !== null && t.sos_avg_opp_ppg !== undefined) {
      var sosMin = Math.min.apply(null, allSos), sosMax = Math.max.apply(null, allSos);
      var sosT = 1 - (t.sos_avg_opp_ppg - sosMin) / Math.max(sosMax - sosMin, 0.1);
      var sosFg = gradientColor(sosT);
      var sosLabel = (t.sos_rank === 1) ? 'Hardest' : (t.sos_rank === allSos.length) ? 'Easiest' : ('#' + t.sos_rank + ' Hardest');
      statsHtml += '<div class="sos-badge" style="color:' + sosFg + ';background:' + rgbaFromRgbString(sosFg, 0.14) + ';" '
        + 'title="Projected Strength of Schedule: ' + t.sos_avg_opp_ppg.toFixed(1) + ' avg opponent PPG">'
        + 'SOS ' + t.sos_avg_opp_ppg.toFixed(1) + ' &middot; ' + sosLabel + '</div>';
    }

    html += '<div class="rank-card glass ' + getTierClass(t.rank, cutoff) + '">';
    html += '<div class="rank-num-wrap"><div class="rank-num">#' + t.rank + '</div>' + rankChangeHtml(t.rank_change) + '</div>';
    html += logoHtml(key, 'rank-logo');

    // the look-back write-up; [[img:id]] markers place its screenshots inline
    var blurbHtml = '';
    if (t.blurb) {
      blurbHtml = '<button class="rank-blurb-toggle" data-blurb="' + esc(key) + '" data-label="' + esc(blurbLabel) + '">'
        + '<span class="chevron">&#9656;</span>'
        + '<span class="toggle-label">Read the ' + esc(blurbLabel) + ' take</span>'
        + '</button>'
        + '<div class="rank-blurb" id="blurb-' + esc(key) + '">' + renderBlurbWithImages(t.blurb, t.screenshots, name) + '</div>';
    }

    // the draft archetype badge: this draft's nearest archetype and its closest past drafts
    var archetypeHtml = '';
    if (t.draft_archetype) {
      var arch = t.draft_archetype;
      var comps = (arch.comparisons || []).slice(0, 2).map(function (c) {
        var label = nameOf(c.manager_key, c.manager) + ' ’' + String(c.season).slice(2);
        return c.ppg != null ? label + ' (' + c.ppg.toFixed(0) + ' PPG)' : label;
      }).join(', ');
      var fp = cfg.pages.find(function (p) { return p.id === 'draft-fingerprints'; });
      archetypeHtml = '<div class="archetype-badge confidence-' + esc(arch.confidence) + '">'
        + '<span class="archetype-icon">&#129516;</span>'
        + '<span class="archetype-name">' + esc(arch.name) + '</span>'
        + (comps ? '<span class="archetype-comps">&middot; like ' + esc(comps) + '</span>' : '')
        + (data.hide_archetype_link || !fp ? '' : ' <a href="' + esc(url(fp.href || fp.path)) + '">see cluster &rarr;</a>')
        + '</div>';
    }

    html += '<div class="rank-info">'
      + '<div class="rank-manager">' + esc(name) + '</div>'
      + (subHtml ? '<div class="rank-sub">' + subHtml + '</div>' : '')
      + (t.synopsis ? '<div class="rank-synopsis">&ldquo;' + t.synopsis + '&rdquo;</div>' : '')
      + archetypeHtml
      + blurbHtml
      + '</div>';
    html += '<div class="rank-stats">' + statsHtml + '</div>';
    html += '</div>';
  });
  html += '</div>';
  container.innerHTML = html;
}

/* A write-up with each [[img:id]] marker replaced by its screenshot; a marker without a file is
   dropped, so a half-finished write-up still reads cleanly. */
function renderBlurbWithImages(text, screenshots, managerName) {
  if (!text) return '';
  var byId = {};
  (screenshots || []).forEach(function (s) { byId[s.id] = s; });
  var parts = text.split(/\[\[img:([\w-]+)\]\]/g);
  var html = '<p>';
  for (var i = 0; i < parts.length; i++) {
    if (i % 2 === 0) { html += parts[i]; continue; }
    var s = byId[parts[i]];
    if (s && s.file) {
      html += '</p>'
        + '<img class="rank-blurb-screenshot" src="' + esc(url(s.file)) + '" alt="' + esc(managerName) + ' stat screenshot">'
        + (s.caption ? '<div class="rank-blurb-caption">' + s.caption + '</div>' : '')
        + '<p>';
    }
  }
  return html + '</p>';
}

function toggleBlurb(btn) {
  var blurb = document.getElementById('blurb-' + btn.dataset.blurb);
  var isOpen = blurb.classList.toggle('open');
  btn.classList.toggle('open', isOpen);
  btn.querySelector('.toggle-label').textContent = (isOpen ? 'Hide the ' : 'Read the ') + btn.dataset.label + ' take';
}

/* ── chart overlays: a dashed line with a green wash above and a red wash below ── */
function thresholdPlugin(id, canvasId, value, label) {
  return {
    id: id,
    beforeDraw: function (chart) {
      if (chart.canvas.id !== canvasId || value() == null) return;
      var area = chart.chartArea, ctx = chart.ctx;
      var yPixel = chart.scales.y.getPixelForValue(value());
      ctx.save();
      var topGrad = ctx.createLinearGradient(0, area.top, 0, yPixel);
      topGrad.addColorStop(0, 'rgba(74,138,90,0.09)');
      topGrad.addColorStop(1, 'rgba(74,138,90,0.015)');
      ctx.fillStyle = topGrad;
      ctx.fillRect(area.left, area.top, area.right - area.left, yPixel - area.top);
      var botGrad = ctx.createLinearGradient(0, yPixel, 0, area.bottom);
      botGrad.addColorStop(0, 'rgba(192,74,74,0.015)');
      botGrad.addColorStop(1, 'rgba(192,74,74,0.09)');
      ctx.fillStyle = botGrad;
      ctx.fillRect(area.left, yPixel, area.right - area.left, area.bottom - yPixel);
      ctx.beginPath();
      ctx.setLineDash([6, 4]);
      ctx.moveTo(area.left, yPixel);
      ctx.lineTo(area.right, yPixel);
      ctx.lineWidth = 1.5;
      ctx.strokeStyle = 'rgba(90,85,80,0.5)';
      ctx.stroke();
      ctx.setLineDash([]);
      ctx.font = "600 10px 'Outfit', sans-serif";
      ctx.fillStyle = 'rgba(90,85,80,0.8)';
      ctx.textAlign = 'right';
      ctx.textBaseline = 'bottom';
      ctx.fillText(label(), area.right - 4, yPixel - 3);
      ctx.restore();
    }
  };
}

// the trajectory chart: the line between the last playoff rank and the first one out
var TRAJ_CUTOFF = null;
var playoffThresholdPlugin = thresholdPlugin('playoffThreshold', 'chart-trajectory',
  function () { return TRAJ_CUTOFF == null ? null : TRAJ_CUTOFF + 0.5; },
  function () { return 'Top ' + TRAJ_CUTOFF + ' · Playoffs'; });

// the odds chart: an average team's week-one odds (playoff spots / teams), "on pace" above it
var ODDS_THRESHOLD = null;
var playoffOddsThresholdPlugin = thresholdPlugin('playoffOddsThreshold', 'chart-playoff-odds',
  function () { return ODDS_THRESHOLD; },
  function () { return ODDS_THRESHOLD + '% · Playoff pace'; });

/* ── Draft / Season Insights ──
   A tab per metric the week's teams carry (ADP value, position spend, projected points, projected
   SOS, surplus value). */
var draftInsightsChart = null;
var draftInsightsTeams = null;
var draftProjSeasonStats = null;   // {manager key: {min, central, max}}, projected points tab only
var draftProjRows = null;
var CURRENT_DRAFT_METRIC_KEY = null;
var DRAFT_PROJ_CENTRAL_STAT = 'avg';   // 'avg' or 'median'
var PROJ_BAND = [100, 130];            // the projection axis and color band, widened to the data

function computeProjSeasonStats(weeksData) {
  var byManager = {};
  (weeksData || []).forEach(function (wk) {
    (wk.teams || []).forEach(function (t) {
      if (t.proj_ppg === null || t.proj_ppg === undefined) return;
      (byManager[t.manager_key] = byManager[t.manager_key] || []).push(t.proj_ppg);
    });
  });
  var stats = {};
  Object.keys(byManager).forEach(function (k) {
    var vals = byManager[k].slice().sort(function (a, b) { return a - b; });
    var central;
    if (DRAFT_PROJ_CENTRAL_STAT === 'median') {
      var mid = Math.floor(vals.length / 2);
      central = vals.length % 2 ? vals[mid] : (vals[mid - 1] + vals[mid]) / 2;
    } else {
      central = vals.reduce(function (a, b) { return a + b; }, 0) / vals.length;
    }
    stats[k] = { min: vals[0], max: vals[vals.length - 1], central: central };
  });
  return stats;
}

/* the projected points tab: faded ticks at each manager's season-to-date low, average and high */
var draftProjRangePlugin = {
  id: 'draftProjRange',
  afterDatasetsDraw: function (chart) {
    if (chart.canvas.id !== 'chart-draft-insights') return;
    if (CURRENT_DRAFT_METRIC_KEY !== 'proj_ppg') return;
    if (!draftProjSeasonStats || !draftProjRows) return;
    var meta = chart.getDatasetMeta(0), xScale = chart.scales.x, area = chart.chartArea, ctx = chart.ctx;
    ctx.save();
    meta.data.forEach(function (bar, i) {
      var row = draftProjRows[i];
      var stats = row && draftProjSeasonStats[row.key];
      if (!stats) return;
      var halfH = (bar.height || 18) / 2 + 4;
      [{ v: stats.min, bold: false }, { v: stats.central, bold: true }, { v: stats.max, bold: false }].forEach(function (m) {
        var x = Math.max(area.left, Math.min(area.right, xScale.getPixelForValue(m.v)));
        ctx.beginPath();
        ctx.setLineDash(m.bold ? [6, 3] : [4, 3]);
        ctx.strokeStyle = m.bold ? 'rgba(40,36,33,0.9)' : 'rgba(40,36,33,0.6)';
        ctx.lineWidth = m.bold ? 2.5 : 2;
        ctx.moveTo(x, bar.y - halfH);
        ctx.lineTo(x, bar.y + halfH);
        ctx.stroke();
        ctx.setLineDash([]);
      });
    });
    ctx.restore();
  }
};

var DRAFT_METRICS = {
  adp_value: {
    label: 'ADP Value',
    desc: 'How far each manager’s QB/RB/WR/TE picks ran from consensus ADP (K and D/ST excluded), positive means they reached, negative means they let a player fall to them.',
    getValue: function (t) { return t.adp_value; },
    format: function (v) { return (v > 0 ? '+' : '') + v.toFixed(1); },
    diverging: true
  },
  position_spend: {
    label: 'Position Spend',
    desc: 'Share of each manager’s draft capital spent at QB, RB, WR, and TE.',
    getValue: function (t) { return t.position_spend ? 1 : null; },
    format: function (v) { return v.toFixed(0) + '%'; },
    diverging: false,
    stacked: true
  },
  proj_ppg: {
    label: 'Projected Points',   // "Week N Projected Points", set per week
    desc: '',
    getValue: function (t) { return t.proj_ppg; },
    format: function (v) { return v.toFixed(1); },
    diverging: false
  },
  projected_sos: {
    label: 'Projected SOS',
    desc: 'Average projected points of each manager’s remaining opponents, from this week through the end of the regular season. Higher means a tougher slate of matchups.',
    getValue: function (t) { return t.sos_avg_opp_ppg; },
    format: function (v) { return v.toFixed(1) + ' PPG'; },
    diverging: false
  },
  draft_grade: {
    label: 'Surplus Value',
    desc: '',                    // names the league's seasons, set at start
    getValue: function (t) { return t.draft_grade; },
    format: function (v) { return (v > 0 ? '+' : '') + v.toFixed(1); },
    diverging: true
  }
};

var POSITION_COLORS = { QB: '#983a3a', RB: '#4a7a4a', WR: '#3a6f98', TE: '#a07010', K: '#6a6460', 'D/ST': '#504840' };
var SPEND_POSITIONS = ['QB', 'RB', 'WR', 'TE'];

// red -> gold -> green: t=0 worst, t=1 best
var GRADIENT_STOPS = [[168, 90, 90], [201, 162, 77], [90, 138, 90]];
function gradientColor(t) {
  t = Math.max(0, Math.min(1, t));
  var seg = t < 0.5 ? [GRADIENT_STOPS[0], GRADIENT_STOPS[1], t / 0.5] : [GRADIENT_STOPS[1], GRADIENT_STOPS[2], (t - 0.5) / 0.5];
  var a = seg[0], b = seg[1], k = seg[2];
  return 'rgb(' + Math.round(a[0] + (b[0] - a[0]) * k) + ',' + Math.round(a[1] + (b[1] - a[1]) * k) + ',' +
    Math.round(a[2] + (b[2] - a[2]) * k) + ')';
}
function rgbaFromRgbString(rgbStr, alpha) {
  var m = /rgb\((\d+),\s*(\d+),\s*(\d+)\)/.exec(rgbStr);
  return m ? 'rgba(' + m[1] + ',' + m[2] + ',' + m[3] + ',' + alpha + ')' : rgbStr;
}

function availableDraftMetrics(teams) {
  return Object.keys(DRAFT_METRICS).filter(function (key) {
    var m = DRAFT_METRICS[key];
    return teams.some(function (t) { return m.getValue(t) !== null && m.getValue(t) !== undefined; });
  });
}

/* 100-130, or the nearest tens around the week's values when any fall outside */
function projBand(values) {
  var lo = PROJ_BAND[0], hi = PROJ_BAND[1];
  values.forEach(function (v) {
    if (v < lo) lo = Math.floor(v / 10) * 10;
    if (v > hi) hi = Math.ceil(v / 10) * 10;
  });
  return [lo, hi];
}

function renderDraftInsights(data, weeksData) {
  var wrap = document.getElementById('draft-insights-wrap');
  draftInsightsTeams = data.teams;
  draftProjSeasonStats = computeProjSeasonStats(weeksData);
  document.getElementById('draft-insights-label').innerHTML = data.week <= 1 ? '&#127919; Draft Insights' : '&#127919; Season Insights';
  DRAFT_METRICS.proj_ppg.label = (data.label ? data.label : ('Week ' + data.week)) + ' Projected Points';
  DRAFT_METRICS.proj_ppg.desc = 'Projected starter total for each roster this week. Faded dashed ticks mark each '
    + 'manager’s season-to-date low, ' + (DRAFT_PROJ_CENTRAL_STAT === 'median' ? 'median' : 'average') + ', and high projection.';

  var keys = availableDraftMetrics(draftInsightsTeams);
  if (!keys.length) { wrap.style.display = 'none'; return; }
  document.getElementById('draft-insights-tabs').innerHTML = keys.map(function (key, i) {
    return '<button class="draft-insights-tab' + (i === 0 ? ' active' : '') + '" id="draft-insights-tab-' + key + '" data-key="' + key + '">'
      + esc(DRAFT_METRICS[key].label) + '</button>';
  }).join('');
  wrap.style.display = 'block';
  selectDraftMetric(keys[0]);
}

function selectDraftMetric(key) {
  availableDraftMetrics(draftInsightsTeams || []).forEach(function (k) {
    var tab = document.getElementById('draft-insights-tab-' + k);
    if (tab) tab.classList.toggle('active', k === key);
  });
  document.getElementById('draft-insights-desc').textContent = DRAFT_METRICS[key].desc;
  drawDraftChart(key);
}

function chartDefaults() {
  Chart.defaults.font.family = "'Outfit', sans-serif";
  Chart.defaults.color = '#5a5550';
}

function drawDraftChart(key) {
  var metric = DRAFT_METRICS[key];
  CURRENT_DRAFT_METRIC_KEY = key;
  if (draftInsightsChart) { draftInsightsChart.destroy(); draftInsightsChart = null; }
  closeDraftDetail();
  chartDefaults();
  var ctx = document.getElementById('chart-draft-insights').getContext('2d');
  var noDrilldown = (key === 'proj_ppg' || key === 'projected_sos');
  document.getElementById('draft-insights-hint').style.display = noDrilldown ? 'none' : 'block';

  if (metric.stacked) {
    // one stacked bar per manager, sorted by RB share
    var withSpend = draftInsightsTeams.filter(function (t) { return !!t.position_spend; });
    withSpend.sort(function (a, b) { return (b.position_spend.RB || 0) - (a.position_spend.RB || 0); });
    draftInsightsChart = new Chart(ctx, {
      type: 'bar',
      data: {
        labels: withSpend.map(function (t) { return nameOf(t.manager_key, t.manager); }),
        datasets: SPEND_POSITIONS.map(function (pos) {
          return { label: pos, data: withSpend.map(function (t) { return t.position_spend[pos] || 0; }),
                   backgroundColor: POSITION_COLORS[pos], borderRadius: 3, barThickness: 18 };
        })
      },
      options: {
        indexAxis: 'y', responsive: true, maintainAspectRatio: false,
        onClick: function (evt, elements) {
          if (!elements.length) return;
          showPositionSpendDetail(withSpend[elements[0].index], SPEND_POSITIONS[elements[0].datasetIndex]);
        },
        onHover: function (evt, elements) { evt.native.target.style.cursor = elements.length ? 'pointer' : 'default'; },
        plugins: {
          legend: { position: 'top', labels: { boxWidth: 10, color: '#5a5550', font: { size: 11 } } },
          tooltip: { callbacks: { label: function (c) { return c.dataset.label + ': ' + c.parsed.x.toFixed(0) + '%'; } } }
        },
        scales: {
          x: { stacked: true, min: 0, max: 100, grid: { color: 'rgba(156,148,156,0.15)', drawBorder: false },
               ticks: { color: '#8a8480', callback: function (v) { return v + '%'; } } },
          y: { stacked: true, grid: { display: false }, ticks: { color: '#5a5550', font: { size: 11, weight: '600' } } }
        }
      }
    });
    return;
  }

  var rows = draftInsightsTeams.map(function (t) {
    var v = metric.getValue(t);
    return (v === null || v === undefined) ? null : { key: t.manager_key, name: nameOf(t.manager_key, t.manager), value: v };
  }).filter(Boolean).sort(function (a, b) { return b.value - a.value; });
  var values = rows.map(function (r) { return r.value; });
  var labelColors = rows.map(function (r) { return colorOf(r.key) || '#5a5550'; });
  draftProjRows = rows;

  // bar colors carry meaning: red (bad) -> green (good), the good direction per metric
  var barColors, extent, band = null;
  if (key === 'proj_ppg') {
    band = projBand(values);
    barColors = values.map(function (v) { return gradientColor((v - band[0]) / (band[1] - band[0])); });
  } else if (key === 'adp_value') {
    extent = Math.max.apply(null, values.map(Math.abs).concat([5]));
    barColors = values.map(function (v) { return gradientColor((extent - v) / (2 * extent)); });
  } else if (key === 'projected_sos') {
    band = projBand(values);
    var minV = Math.min.apply(null, values), maxV = Math.max.apply(null, values);
    var range = Math.max(maxV - minV, 0.1);
    barColors = values.map(function (v) { return gradientColor(1 - (v - minV) / range); });
  } else if (key === 'draft_grade') {
    extent = Math.max.apply(null, values.map(Math.abs).concat([5]));
    barColors = values.map(function (v) { return gradientColor((v + extent) / (2 * extent)); });
  } else {
    barColors = values.map(function () { return '#9c949c'; });
  }

  draftInsightsChart = new Chart(ctx, {
    type: 'bar',
    data: { labels: rows.map(function (r) { return r.name; }),
            datasets: [{ data: values, backgroundColor: barColors, borderRadius: 4, barThickness: 18 }] },
    plugins: [draftProjRangePlugin],
    options: {
      indexAxis: 'y', responsive: true, maintainAspectRatio: false,
      onClick: function (evt, elements) {
        if (!elements.length || noDrilldown) return;
        var k = rows[elements[0].index].key;
        var team = draftInsightsTeams.filter(function (t) { return t.manager_key === k; })[0];
        if (key === 'adp_value') showAdpValueDetail(team);
        else if (key === 'draft_grade') showSurplusDetail(team);
      },
      onHover: function (evt, elements) {
        evt.native.target.style.cursor = (elements.length && !noDrilldown) ? 'pointer' : 'default';
      },
      plugins: {
        legend: { display: false },
        tooltip: { callbacks: { label: function (c) { return metric.format(c.parsed.x); } } }
      },
      scales: {
        x: Object.assign({
          grid: { color: 'rgba(156,148,156,0.15)', drawBorder: false },
          ticks: { color: '#8a8480', callback: function (v) { return metric.diverging && v > 0 ? '+' + v : v; } }
        }, band ? { min: band[0], max: band[1] } : {}),
        y: { grid: { display: false },
             ticks: { color: function (c) { return labelColors[c.index] || '#5a5550'; }, font: { size: 11, weight: '700' } } }
      }
    }
  });
}

/* ── Draft Insights detail cards (click a bar) ── */
function closeDraftDetail() { document.getElementById('draft-detail-card').classList.remove('open'); }
function draftDetailPosChip(pos) {
  return '<span class="draft-detail-pos-chip" style="background:' + (POSITION_COLORS[pos] || '#6a6460') + ';">' + esc(pos) + '</span>';
}
function draftDetailDevCell(dev) {
  if (dev === null || dev === undefined) return '<span style="color:var(--muted);">N/A</span>';
  return '<span class="' + (dev >= 0 ? 'draft-detail-dev-neg' : 'draft-detail-dev-pos') + '">' + (dev > 0 ? '+' : '') + dev.toFixed(1) + '</span>';
}
function draftDetailSurplusCell(sv) {
  if (sv === null || sv === undefined) return '<span style="color:var(--muted);">N/A</span>';
  return '<span class="' + (sv >= 0 ? 'draft-detail-dev-pos' : 'draft-detail-dev-neg') + '">' + (sv > 0 ? '+' : '') + sv.toFixed(1) + '</span>';
}
function detailTitle(color, text) {
  document.getElementById('draft-detail-title').innerHTML = '<span class="dot" style="background:' + color + ';"></span>' + esc(text);
}
function openDetail(body) {
  document.getElementById('draft-detail-body').innerHTML = body;
  document.getElementById('draft-detail-card').classList.add('open');
}
function teamLabel(p) { return esc(p.player) + ' <span style="color:var(--muted);font-size:0.75em;">' + esc(p.nfl_team) + '</span>'; }
function byPick(picks) { return (picks || []).slice().sort(function (a, b) { return a.overall - b.overall; }); }
function dimmed(p) { return ['QB', 'RB', 'WR', 'TE'].indexOf(p.pos) !== -1 ? '' : ' style="opacity:0.5;"'; }

function showAdpValueDetail(team) {
  detailTitle(colorOf(team.manager_key) || '#5a5550', nameOf(team.manager_key, team.manager) + '’s picks');
  var rowsHtml = byPick(team.draft_picks).map(function (p) {
    return '<tr' + dimmed(p) + '><td>' + draftDetailPosChip(p.pos) + '</td><td>' + teamLabel(p) + '</td>'
      + '<td>Rd ' + p.round + '.' + p.pick_in_round + ' (#' + p.overall + ')</td>'
      + '<td>' + (p.espn_adp !== null && p.espn_adp !== undefined ? p.espn_adp.toFixed(1) : 'N/A') + '</td>'
      + '<td>' + draftDetailDevCell(p.adp_deviation) + '</td></tr>';
  }).join('');
  openDetail('<table class="draft-detail-table"><thead><tr><th>Pos</th><th>Player</th><th>Pick</th><th>ESPN ADP</th><th>Deviation</th>'
    + '</tr></thead><tbody>' + rowsHtml + '</tbody></table>'
    + '<p class="draft-detail-hint">K and D/ST picks (dimmed) aren’t counted in the ADP Value average above.</p>');
}

function showPositionSpendDetail(team, pos) {
  detailTitle(POSITION_COLORS[pos] || '#5a5550', nameOf(team.manager_key, team.manager) + '’s ' + pos + 's');
  var picks = byPick((team.draft_picks || []).filter(function (p) { return p.pos === pos; }));
  if (!picks.length) { openDetail('<p class="draft-detail-hint">No ' + esc(pos) + ' picks this draft.</p>'); return; }
  var rowsHtml = picks.map(function (p) {
    return '<tr><td>' + teamLabel(p) + '</td><td>Round ' + p.round + ', Pick ' + p.pick_in_round + '</td>'
      + '<td>Overall #' + p.overall + '</td>'
      + '<td>' + (p.espn_adp !== null && p.espn_adp !== undefined ? p.espn_adp.toFixed(1) : 'N/A') + '</td></tr>';
  }).join('');
  openDetail('<table class="draft-detail-table"><thead><tr><th>Player</th><th>Draft Capital</th><th>Overall</th><th>ESPN ADP</th>'
    + '</tr></thead><tbody>' + rowsHtml + '</tbody></table>'
    + '<p class="draft-detail-hint">Position Spend weights early rounds exponentially heavier (halves every 3 rounds), not by a flat per-pick step.</p>');
}

function showSurplusDetail(team) {
  detailTitle(colorOf(team.manager_key) || '#5a5550', nameOf(team.manager_key, team.manager) + '’s picks');
  var rowsHtml = byPick(team.draft_picks).map(function (p) {
    return '<tr' + dimmed(p) + '><td>' + draftDetailPosChip(p.pos) + '</td><td>' + teamLabel(p) + '</td>'
      + '<td>Rd ' + p.round + '.' + p.pick_in_round + ' (#' + p.overall + ')</td>'
      + '<td>' + draftDetailSurplusCell(p.surplus_value) + '</td></tr>';
  }).join('');
  openDetail('<table class="draft-detail-table"><thead><tr><th>Pos</th><th>Player</th><th>Pick</th><th>Surplus</th>'
    + '</tr></thead><tbody>' + rowsHtml + '</tbody></table>'
    + '<p class="draft-detail-hint">K and D/ST picks (dimmed) aren’t graded -- surplus is skill positions only, and updates as more of the season plays out.</p>');
}

/* ── line charts: one line per manager of the season ── */
function lineDataset(m, data, radius, borderWidths) {
  var color = colorOf(m.key) || '#9c949c';
  return {
    label: m.name, data: data, borderColor: color, backgroundColor: 'transparent', borderWidth: 2,
    pointRadius: data.map(function (_, i) { return i === data.length - 1 ? 6 : radius; }),
    pointBackgroundColor: color, pointBorderColor: '#fff',
    pointBorderWidth: borderWidths ? data.map(function (_, i) { return i === data.length - 1 ? 2 : 1; }) : 1,
    pointHoverRadius: 8, tension: 0.3, spanGaps: false
  };
}
function lineOptions(yScale, tooltip) {
  return {
    responsive: true, maintainAspectRatio: false, interaction: { mode: 'index', intersect: false },
    plugins: {
      legend: { position: 'right', labels: { boxWidth: 10, padding: 10, color: '#5a5550', font: { size: 11 } } },
      tooltip: { callbacks: { label: function (c) { return c.parsed.y === null ? null : tooltip(c); } } }
    },
    scales: { x: { grid: { color: 'rgba(156,148,156,0.15)', drawBorder: false }, ticks: { color: '#8a8480' } }, y: yScale }
  };
}

function renderTrajectoryChart(s, upToWeek, weeksData) {
  var weeks = weeksData.map(function (d) { return d.week; });
  var datasets = seasonManagers(s).map(function (m) {
    var data = weeks.map(function (w) {
      var weekData = weeksData.find(function (d) { return d.week === w; });
      var team = weekData && weekData.teams.find(function (t) { return t.manager_key === m.key; });
      return team ? team.rank : null;
    });
    return lineDataset(m, data, 3, true);
  });
  if (trajectoryChart) { trajectoryChart.destroy(); trajectoryChart = null; }
  chartDefaults();
  TRAJ_CUTOFF = playoffCount(s);
  var last = weeksData[weeksData.length - 1];
  trajectoryChart = new Chart(document.getElementById('chart-trajectory').getContext('2d'), {
    type: 'line',
    data: { labels: weeks.map(function (w) { return 'Wk ' + w; }), datasets: datasets },
    plugins: [playoffThresholdPlugin],
    options: lineOptions({
      reverse: true, min: 1, max: teamCount(s, last && last.teams),
      grid: { color: 'rgba(156,148,156,0.15)', drawBorder: false },
      ticks: { color: '#8a8480', stepSize: 1, callback: function (v) { return '#' + v; } },
      title: { display: true, text: 'Rank', color: '#8a8480', font: { size: 11 } }
    }, function (c) { return c.dataset.label + ': #' + c.parsed.y; })
  });
  document.getElementById('trajectory-wrap').style.display = 'block';
}

function renderPlayoffOddsChart(s, upToWeek) {
  var wrap = document.getElementById('playoff-odds-wrap');
  var seasonData = playoffOddsData && (playoffOddsData.seasons || []).find(function (x) { return x.season === Number(s); });
  if (isNaN(upToWeek) || !seasonData) { wrap.style.display = 'none'; return; }
  var byWeek = {};
  seasonData.weeks.forEach(function (w) { byWeek[w.week] = w.odds; });
  var maxWeek = Math.min(upToWeek, seasonData.regular_season_weeks);
  var weeks = [];
  for (var w = 1; w <= maxWeek; w++) weeks.push(w);
  var datasets = seasonManagers(s).map(function (m) {
    return lineDataset(m, weeks.map(function (wk) {
      var odds = byWeek[wk];
      return odds && (m.key in odds) ? odds[m.key] : null;
    }), 2, false);
  });
  var teams = teamCount(s);
  ODDS_THRESHOLD = teams ? Math.round(seasonData.cutoff / teams * 100) : null;
  document.getElementById('playoff-odds-desc').textContent = 'Retrospective odds of finishing the regular season in the top '
    + seasonData.cutoff + '. At each week, real record and points to date are combined with '
    + (playoffOddsData.trials ? Number(playoffOddsData.trials).toLocaleString('en-US') + ' ' : '')
    + 'simulated playouts of the remaining schedule, using each manager\'s scoring average and volatility up to that point. '
    + 'Playoff-round games are never simulated or counted - this tracks regular season only.';
  if (playoffOddsChart) { playoffOddsChart.destroy(); playoffOddsChart = null; }
  chartDefaults();
  playoffOddsChart = new Chart(document.getElementById('chart-playoff-odds').getContext('2d'), {
    type: 'line',
    data: { labels: weeks.map(function (wk) { return 'Wk ' + wk; }), datasets: datasets },
    plugins: [playoffOddsThresholdPlugin],
    options: lineOptions({
      min: 0, max: 100, grid: { color: 'rgba(156,148,156,0.15)', drawBorder: false },
      ticks: { color: '#8a8480', stepSize: 20, callback: function (v) { return v + '%'; } },
      title: { display: true, text: 'Playoff odds', color: '#8a8480', font: { size: 11 } }
    }, function (c) { return c.dataset.label + ': ' + c.parsed.y.toFixed(1) + '%'; })
  });
  wrap.style.display = 'block';
}

/* ── playoff previews ──
   A bracket graphic (this round's matchups, then the picks carried forward) and one card per
   matchup. Pairing order (1v8 meets 4v5, 2v7 meets 3v6) follows the bracket's seeding. */
function statCompareClass(a, b) { return a > b ? 'stat-win' : a < b ? 'stat-loss' : 'stat-even'; }
function recordWins(rec) { return parseInt((rec || '0-0').split('-')[0], 10) || 0; }
function adjacentPairs(len) { var p = []; for (var i = 0; i < len; i += 2) p.push([i, i + 1]); return p; }

/* the rounds after this one, from the season's playoff round names */
function laterRounds(data, n) {
  var rounds = season(data.season).rounds || {};
  var names = Object.keys(rounds).sort(function (a, b) { return a - b; }).map(function (k) { return rounds[k]; });
  var at = names.map(function (x) { return String(x).toLowerCase(); })
    .indexOf(String(data.round_label || data.round || '').toLowerCase());
  if (at !== -1) return names.slice(at + 1);
  return { 4: ['Semifinals', 'Championship'], 2: ['Championship'], 1: [] }[n] || [];
}

function buildBracketHtml(data) {
  var matchups = data.matchups;
  var n = matchups.length;
  var pairOrder = { 4: [[0, 3], [1, 2]], 2: [[0, 1]], 1: [[0]] };
  if (!pairOrder[n]) return '';
  var order = [].concat.apply([], pairOrder[n]);
  var firstSlots = order.map(function (i) {
    var m = matchups[i];
    return { seedTop: m.higher_seed.seed, nameTop: m.higher_seed.team, seedBot: m.lower_seed.seed,
             nameBot: m.lower_seed.team, pickName: m.pick, known: true };
  });
  var columns = [{ label: data.round_label, slots: firstSlots, pairs: adjacentPairs(firstSlots.length) }];
  var names = laterRounds(data, n);
  var currentPicks = order.map(function (i) { return matchups[i].pick; });
  var ni = 0;
  while (currentPicks.length > 1) {
    var slots = [], nextPicks = [];
    for (var i = 0; i < currentPicks.length; i += 2) {
      slots.push({ nameTop: currentPicks[i], nameBot: currentPicks[i + 1], known: false });
      nextPicks.push(null);
    }
    columns.push({ label: names[ni] || 'Next Round', slots: slots, pairs: adjacentPairs(slots.length) });
    currentPicks = nextPicks;
    ni++;
  }
  return buildBracketHtmlActual(columns);
}

function bracketSlotHtml(slot) {
  if (slot.known) {
    return '<div class="bracket-slot">'
      + '<div class="bracket-slot-team' + (slot.pickName === slot.nameTop ? ' is-pick' : '') + '">'
      + '<span class="bracket-slot-seed">' + slot.seedTop + '</span><span class="bracket-slot-name">' + esc(slot.nameTop) + '</span></div>'
      + '<div class="bracket-slot-team' + (slot.pickName === slot.nameBot ? ' is-pick' : '') + '">'
      + '<span class="bracket-slot-seed">' + slot.seedBot + '</span><span class="bracket-slot-name">' + esc(slot.nameBot) + '</span></div>'
      + '</div>';
  }
  return '<div class="bracket-slot is-pending"><div class="bracket-pending-tag">Projected</div>'
    + '<div class="bracket-slot-team"><span class="bracket-slot-name">' + esc(slot.nameTop || 'TBD') + '</span></div>'
    + '<div class="bracket-slot-team"><span class="bracket-slot-name">' + esc(slot.nameBot || 'TBD') + '</span></div>'
    + '</div>';
}

function buildBracketHtmlActual(columns) {
  var html = '<div class="bracket-wrap"><div class="bracket">';
  columns.forEach(function (col, ci) {
    html += '<div class="bracket-col"><div class="bracket-col-label">' + esc(col.label) + '</div><div class="bracket-col-slots">';
    if (ci === columns.length - 1) {
      col.slots.forEach(function (s) { html += bracketSlotHtml(s); });
    } else {
      col.pairs.forEach(function (pair) {
        html += '<div class="bracket-pair">';
        pair.forEach(function (idx) { html += bracketSlotHtml(col.slots[idx]); });
        html += '</div>';
      });
    }
    html += '</div></div>';
  });
  return html + '</div></div>';
}

function renderPlayoffBracket(data) {
  var html = '<div class="playoff-banner"><span class="trophy">&#127942;</span><span>' + esc(data.round_label) + '</span>'
    + '<span class="trophy">&#127942;</span></div>';
  html += '<div class="playoff-subtitle">' + data.season + ' ' + esc(cfg.league.name) + ' Playoffs</div>';
  if (data.overview) html += '<div class="playoff-overview glass">' + data.overview + '</div>';
  html += buildBracketHtml(data);
  html += '<div class="playoff-matchups">';
  data.matchups.forEach(function (m) {
    var hi = m.higher_seed, lo = m.lower_seed;
    function side(t, cls) {
      return '<div class="matchup-side ' + cls + '"><div class="matchup-seed">' + t.seed + '</div>'
        + logoHtml(t.manager_key, 'matchup-team-logo')
        + '<div class="matchup-team-name">' + esc(t.team) + '</div>'
        + '<div class="matchup-manager">' + esc(nameOf(t.manager_key, t.manager)) + '</div></div>';
    }
    html += '<div class="matchup-card glass"><div class="matchup-label">' + esc(m.matchup_label) + '</div>';
    html += '<div class="matchup-sides">' + side(hi, 'side-left') + '<div class="matchup-vs">vs</div>' + side(lo, 'side-right') + '</div>';
    html += '<div class="matchup-stats">';
    [
      ['Projection', hi.projection, lo.projection, hi.projection.toFixed(1), lo.projection.toFixed(1)],
      ['Regular Season Avg', hi.regular_season_avg, lo.regular_season_avg, hi.regular_season_avg.toFixed(1), lo.regular_season_avg.toFixed(1)],
      ['Record', recordWins(hi.record), recordWins(lo.record), hi.record, lo.record]
    ].forEach(function (row) {
      html += '<div class="matchup-stat-row">'
        + '<div class="matchup-stat-value ' + statCompareClass(row[1], row[2]) + '">' + esc(row[3]) + '</div>'
        + '<div class="matchup-stat-label">' + row[0] + '</div>'
        + '<div class="matchup-stat-value ' + statCompareClass(row[2], row[1]) + '">' + esc(row[4]) + '</div>'
        + '</div>';
    });
    html += '</div>';
    if (m.blurb) {
      html += '<div class="matchup-pick"><div class="matchup-pick-label">My Pick</div><div class="matchup-pick-text">' + m.blurb + '</div></div>';
    }
    html += '</div>';
  });
  html += '</div>';
  document.getElementById('rankings-content').innerHTML = html;
}

/* ── loading ── */
function seasonEntry(s) { return (INDEX.seasons || []).find(function (x) { return x.season === s; }) || null; }
function fetchFile(file) {
  if (jsonCache[file]) return Promise.resolve(jsonCache[file]);
  return load(DIR + file).then(function (d) { jsonCache[file] = d; return d; });
}
function fetchWeek(s, week) {
  var e = seasonEntry(s);
  var w = e && e.weeks.find(function (x) { return x.week === week; });
  return w ? fetchFile(w.file) : Promise.reject(new Error('no week ' + s + ' ' + week));
}
function fetchPlayoffRound(s, slug) {
  var e = seasonEntry(s);
  var p = e && e.previews.find(function (x) { return x.round === slug; });
  return p ? fetchFile(p.file) : Promise.reject(new Error('no preview ' + s + ' ' + slug));
}

function emptyState(icon, text) {
  return '<div class="empty-state glass"><span class="empty-icon">' + icon + '</span><p>' + text + '</p></div>';
}

var loadSeq = 0;
function loadRankings() {
  var s = parseInt(document.getElementById('season-select').value, 10);
  var selected = document.getElementById('week-select').value;
  if (!s || !selected) return Promise.resolve();
  var seq = ++loadSeq;
  var container = document.getElementById('rankings-content');
  container.innerHTML = emptyState('&#9203;', 'Loading...');
  ['trajectory-wrap', 'playoff-odds-wrap', 'draft-insights-wrap', 'motw-wrap', 'koth-wrap'].forEach(function (id) {
    document.getElementById(id).style.display = 'none';
  });

  var week = parseInt(selected, 10);
  if (isNaN(week)) {   // a playoff preview
    return fetchPlayoffRound(s, selected).then(function (data) { if (seq === loadSeq) renderPlayoffBracket(data); })
      .catch(function (err) {
        console.error(err);
        if (seq === loadSeq) container.innerHTML = emptyState('&#127942;', 'No playoff data available for this round yet.');
      });
  }
  return fetchWeek(s, week).then(function (data) {
    if (seq !== loadSeq) return null;
    renderRankings(data);
    renderMatchupOfWeek(data);
    // every week up to this one: the trajectory, and the projected points tab's season range
    var e = seasonEntry(s);
    var upTo = e ? e.weeks.filter(function (w) { return w.week <= week; }) : [];
    return Promise.all(upTo.map(function (w) { return fetchFile(w.file); }))
      .then(function (weeksData) { return { data: data, weeksData: weeksData }; });
  }).then(function (result) {
    if (!result || seq !== loadSeq) return null;
    var sorted = result.weeksData.slice().sort(function (a, b) { return a.week - b.week; });
    renderDraftInsights(result.data, sorted);
    renderTrajectoryChart(s, week, sorted);
    renderPlayoffOddsChart(s, week);
    return renderTopPlayers(result.data);
  }).catch(function (err) {
    console.error(err);
    if (seq === loadSeq) container.innerHTML = emptyState('&#128203;', 'No rankings available for this week yet.');
  });
}

function onSeasonChange() {
  var s = parseInt(document.getElementById('season-select').value, 10);
  var weekSel = document.getElementById('week-select');
  var e = seasonEntry(s);
  weekSel.innerHTML = '';
  if (e) {
    // newest week first, the playoff previews above them
    e.weeks.slice().reverse().forEach(function (w) {
      var opt = document.createElement('option');
      opt.value = w.week;
      opt.textContent = w.label || ('Week ' + w.week);
      weekSel.appendChild(opt);
    });
    (e.previews || []).slice().reverse().forEach(function (p) {
      var opt = document.createElement('option');
      opt.value = p.round;
      opt.textContent = '🏆 ' + p.round.charAt(0).toUpperCase() + p.round.slice(1);
      weekSel.insertBefore(opt, weekSel.firstChild);
    });
  }
  applySeasonTheme(s);
  return loadRankings();
}

/* ── events ── */
function bind() {
  document.getElementById('season-select').addEventListener('change', onSeasonChange);
  document.getElementById('week-select').addEventListener('change', loadRankings);
  document.getElementById('rankings-content').addEventListener('click', function (e) {
    var btn = e.target.closest('.rank-blurb-toggle');
    if (btn) { toggleBlurb(btn); return; }
    var img = e.target.closest('.rank-blurb-screenshot');
    if (img) {
      e.stopPropagation();
      document.getElementById('screenshot-lightbox-img').src = img.src;
      document.getElementById('screenshot-lightbox').classList.add('open');
    }
  });
  document.getElementById('screenshot-lightbox').addEventListener('click', function () {
    this.classList.remove('open');
  });
  document.getElementById('draft-insights-tabs').addEventListener('click', function (e) {
    var tab = e.target.closest('.draft-insights-tab');
    if (tab) selectDraftMetric(tab.dataset.key);
  });
  document.getElementById('draft-detail-close').addEventListener('click', closeDraftDetail);
  document.getElementById('koth-tabs').addEventListener('click', function (e) {
    var tab = e.target.closest('.draft-insights-tab');
    if (tab) selectKothTab(tab.dataset.key);
  });
}

function start() {
  return config().then(function (c) {
    cfg = c;
    mgr = managers(cfg);
    drawNav(cfg, 'weekly-rankings');
    drawFooter(cfg);
    document.getElementById('page-sub').textContent = 'Power rankings across every season of ' + cfg.league.name;
    DRAFT_METRICS.draft_grade.desc = 'Weighted draft surplus so far this season -- actual production vs. expected for that '
      + 'draft slot, compared against every pick from ' + seasonRange(cfg) + ' taken within 3 spots of it. Positive means '
      + 'the pick is outperforming its slot.';
    bind();
    var odds = load('data/v1/playoff-odds.json').then(function (d) { playoffOddsData = d; })
      .catch(function (err) { console.error(err); playoffOddsData = null; });
    return Promise.all([load(DIR + 'index.json'), odds]);
  }).then(function (res) {
    INDEX = res[0];
    var seasonSel = document.getElementById('season-select');
    (INDEX.seasons || []).forEach(function (e) {
      var opt = document.createElement('option');
      opt.value = e.season;
      opt.textContent = e.season;
      seasonSel.appendChild(opt);
    });
    if (!(INDEX.seasons || []).length) {
      document.getElementById('rankings-content').innerHTML = emptyState('&#128203;', 'No rankings yet.');
      return null;
    }
    return onSeasonChange();
  }).catch(function (err) {
    console.error(err);
    document.getElementById('rankings-content').innerHTML = emptyState('&#128203;', 'Could not load rankings data.');
  });
}

start();
