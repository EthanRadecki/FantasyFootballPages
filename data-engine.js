/* ══════════════════════════════════════
   Preach Fantasy - Data Engine
   Reads CSVs, computes stats, populates pages.
   ══════════════════════════════════════ */

// Excluded managers
var EXCLUDED = ['William Serafin', 'Thomas Sullivan'];

// Manager lastname map for logos
var LASTNAME_MAP = {
  'Aidan Quigley': 'Quigley',
  'Andrew Root': 'Root',
  'Anthony Kelly': 'Kelly',
  'Baylen Slansky': 'Slansky',
  'Ben Castaldo': 'Castaldo',
  'Brandon Hancock': 'Hancock',
  'Carmine Pittelli Jr.': 'Pittelli',
  'Charlie Gorman': 'Gorman',
  'Cole Maney': 'Maney',
  'Deniz Bileydi': 'Bileydi',
  'Ethan Radecki': 'Radecki',
  'Max Malich': 'Malich',
  'Quin Gegwich': 'Gegwich',
  'Ryan P McQuaid': 'McQuaid'
};

/* ── CSV PARSER ── */
function parseCSV(text) {
  var lines = text.replace(/\r/g, '').trim().split('\n');
  var headers = lines[0].split(',');
  var rows = [];
  for (var i = 1; i < lines.length; i++) {
    if (!lines[i].trim()) continue;
    var vals = lines[i].split(',');
    var obj = {};
    for (var j = 0; j < headers.length; j++) {
      obj[headers[j].trim()] = (vals[j] || '').trim();
    }
    rows.push(obj);
  }
  return rows;
}

/* ── FETCH HELPERS ── */
function loadCSV(path) {
  return fetch(path).then(function(r) { return r.text(); }).then(parseCSV);
}

/* ── LEADERBOARD ── */
function buildLeaderboard(statsData) {
  // Filter excluded
  var data = statsData.filter(function(r) { return EXCLUDED.indexOf(r.Manager) === -1; });

  // Group by manager
  var managers = {};
  data.forEach(function(r) {
    var name = r.Manager;
    if (!managers[name]) {
      managers[name] = { name: name, seasons: [], totalW: 0, totalL: 0, totalPlayoffs: 0, totalChamps: 0, pfgSum: 0, luckSum: 0, seasonCount: 0 };
    }
    var m = managers[name];
    var w = parseInt(r.W) || 0;
    var l = parseInt(r.L) || 0;
    m.totalW += w;
    m.totalL += l;
    m.totalPlayoffs += parseInt(r.Playoffs) || 0;
    m.totalChamps += parseInt(r.Champ_W) || 0;
    m.pfgSum += parseFloat(r['PF/G']) || 0;
    m.luckSum += parseFloat(r.LR_zscore) || 0;
    m.seasonCount++;
    var winPct = (w + l) > 0 ? w / (w + l) : 0;
    m.seasons.push({ year: parseInt(r.Year), w: w, l: l, winPct: winPct, team: r.Team });
  });

  // Convert to array and compute career stats
  var list = Object.values(managers).map(function(m) {
    m.winPct = (m.totalW + m.totalL) > 0 ? m.totalW / (m.totalW + m.totalL) : 0;
    m.avgPfg = m.seasonCount > 0 ? m.pfgSum / m.seasonCount : 0;
    m.avgLuck = m.seasonCount > 0 ? m.luckSum / m.seasonCount : 0;

    // Best and worst seasons by win %
    m.seasons.sort(function(a, b) { return b.winPct - a.winPct; });
    m.bestSeason = m.seasons[0];
    m.worstSeason = m.seasons[m.seasons.length - 1];

    return m;
  });

  // Sort by win % descending
  list.sort(function(a, b) { return b.winPct - a.winPct; });

  return list;
}

function renderLeaderboard(list) {
  var tbody = document.querySelector('#leaderboardTable tbody');
  if (!tbody) return;
  tbody.innerHTML = '';

  var total = list.length;

  // Pre-compute ranks for color coding
  function getRanks(arr, key, ascending) {
    var sorted = arr.slice().sort(function(a, b) {
      return ascending ? a[key] - b[key] : b[key] - a[key];
    });
    var ranks = {};
    sorted.forEach(function(item, i) { ranks[item.name] = i + 1; });
    return ranks;
  }

  var winRanks = getRanks(list, 'totalW', false);
  var lossRanks = getRanks(list, 'totalL', true); // fewer losses = better
  var winPctRanks = getRanks(list, 'winPct', false);
  var playoffRanks = getRanks(list, 'totalPlayoffs', false);
  var pfgRanks = getRanks(list, 'avgPfg', false);

  function cellColor(rank, total) {
    var norm = (rank - 1) / (total - 1);
    if (norm <= 0.3) return 'cell-good val-bold';
    if (norm <= 0.6) return 'cell-mid';
    return 'cell-bad';
  }

  list.forEach(function(m) {
    var tr = document.createElement('tr');
    var champCell = m.totalChamps > 0
      ? '<span class="champ-badge">' + m.totalChamps + ' &#127942;</span>'
      : '<span style="color:var(--muted);">0</span>';
    var bestRec = m.bestSeason.w + '-' + m.bestSeason.l + ' (' + m.bestSeason.year + ')';
    var worstRec = m.worstSeason.w + '-' + m.worstSeason.l + ' (' + m.worstSeason.year + ')';
    // LR_zscore is inverted: positive = unlucky, negative = lucky.
    // Negate for display so positive = lucky = green.
    var luckDisplay = -m.avgLuck;
    var luckClass = luckDisplay >= 0 ? 'val-green' : 'val-red';
    var luckPrefix = luckDisplay > 0 ? '+' : '';

    tr.innerHTML =
      '<td><a href="#" class="manager-link">' + m.name + '</a></td>' +
      '<td class="' + cellColor(winRanks[m.name], total) + '">' + m.totalW + '</td>' +
      '<td class="' + cellColor(lossRanks[m.name], total) + '">' + m.totalL + '</td>' +
      '<td class="' + cellColor(winPctRanks[m.name], total) + '">' + m.winPct.toFixed(3) + '</td>' +
      '<td class="' + cellColor(playoffRanks[m.name], total) + '">' + m.totalPlayoffs + '</td>' +
      '<td>' + champCell + '</td>' +
      '<td class="' + cellColor(pfgRanks[m.name], total) + '">' + m.avgPfg.toFixed(1) + '</td>' +
      '<td class="' + luckClass + '">' + luckPrefix + luckDisplay.toFixed(2) + '</td>' +
      '<td class="val-small">' + bestRec + '</td>' +
      '<td class="val-small">' + worstRec + '</td>';
    tbody.appendChild(tr);
  });
}

/* ── MANAGER PROFILES ── */
function buildManagerProfiles(statsData, matchupData) {
  var data = statsData.filter(function(r) { return EXCLUDED.indexOf(r.Manager) === -1; });
  var matchups = matchupData.filter(function(r) { return EXCLUDED.indexOf(r.Team_Name) === -1; });

  // Group stats by manager
  var profiles = {};
  data.forEach(function(r) {
    var name = r.Manager;
    if (!profiles[name]) {
      profiles[name] = { name: name, seasons: [], totalW: 0, totalL: 0, totalPlayoffs: 0, totalChamps: 0, pfgSum: 0, seasonCount: 0, champYears: [] };
    }
    var p = profiles[name];
    var w = parseInt(r.W) || 0;
    var l = parseInt(r.L) || 0;
    p.totalW += w;
    p.totalL += l;
    p.totalPlayoffs += parseInt(r.Playoffs) || 0;
    var champW = parseInt(r.Champ_W) || 0;
    p.totalChamps += champW;
    if (champW === 1) p.champYears.push(parseInt(r.Year));
    p.pfgSum += parseFloat(r['PF/G']) || 0;
    p.seasonCount++;
    p.seasons.push({
      year: parseInt(r.Year),
      team: r.Team,
      w: w,
      l: l,
      winPct: (w + l) > 0 ? w / (w + l) : 0,
      pfg: parseFloat(r['PF/G']) || 0,
      pag: parseFloat(r['PA/G']) || 0,
      diff: parseFloat(r.DIFF) || 0,
      draftSlot: parseInt(r.Draft_Slot) || 0,
      playoffs: parseInt(r.Playoffs) || 0,
      pfgRank: parseInt(r['PF/G_Rank_within_Year']) || 0,
      lrZscore: parseFloat(r.LR_zscore) || 0,
      dominance: parseFloat(r.Dominance_Score) || 0,
      luckRating: parseInt(r.Luck_Rating) || 0
    });
  });

  // Compute ranks across all managers
  var allManagers = Object.values(profiles);
  allManagers.forEach(function(p) {
    p.winPct = (p.totalW + p.totalL) > 0 ? p.totalW / (p.totalW + p.totalL) : 0;
    p.avgPfg = p.seasonCount > 0 ? p.pfgSum / p.seasonCount : 0;
    p.seasons.sort(function(a, b) { return b.year - a.year; });
  });

  // Rank functions
  function rankDesc(arr, key) {
    var sorted = arr.slice().sort(function(a, b) { return b[key] - a[key]; });
    sorted.forEach(function(item, i) { item[key + '_rank'] = i + 1; });
  }
  rankDesc(allManagers, 'totalW');
  rankDesc(allManagers, 'winPct');
  rankDesc(allManagers, 'totalPlayoffs');
  rankDesc(allManagers, 'avgPfg');
  // Losses: lower is better
  var lossSort = allManagers.slice().sort(function(a, b) { return a.totalL - b.totalL; });
  lossSort.forEach(function(item, i) { item.totalL_rank = i + 1; });

  // H2H from matchup data
  // Bracket-only: excludes non-elimination consolation games that occur during
  // playoff weeks (same convention as Closest Games / Championship Gauntlet).
  // A row counts if it's a regular-season week, OR it's a playoff week AND
  // Is_Playoff flags it as a real bracket game.
  function isRealGame(r) {
    var isPlayoffWeek = r.Week && r.Week.indexOf('Playoff') === 0;
    return !isPlayoffWeek || r.Is_Playoff === 'Yes';
  }

  allManagers.forEach(function(p) {
    var myMatchups = matchups.filter(function(r) { return r.Team_Name === p.name && isRealGame(r); });
    var h2h = {};
    myMatchups.forEach(function(r) {
      var opp = r.Opponent_Name;
      if (EXCLUDED.indexOf(opp) !== -1) return;
      if (!h2h[opp]) h2h[opp] = { w: 0, l: 0 };
      if (r.Outcome === 'Win') h2h[opp].w++;
      else h2h[opp].l++;
    });
    p.h2h = h2h;

    // Best and worst matchup
    var opponents = Object.keys(h2h);
    if (opponents.length > 0) {
      var best = null, worst = null, bestPct = -1, worstPct = 2;
      opponents.forEach(function(opp) {
        var total = h2h[opp].w + h2h[opp].l;
        if (total === 0) return;
        var pct = h2h[opp].w / total;
        if (pct > bestPct) { bestPct = pct; best = opp; }
        if (pct < worstPct) { worstPct = pct; worst = opp; }
      });
      p.bestRival = best;
      p.bestRivalRecord = best ? h2h[best].w + '-' + h2h[best].l : '';
      p.bestRivalPct = best ? (bestPct * 100).toFixed(1) + '%' : '';
      p.worstRival = worst;
      p.worstRivalRecord = worst ? h2h[worst].w + '-' + h2h[worst].l : '';
      p.worstRivalPct = worst ? (worstPct * 100).toFixed(1) + '%' : '';
    }

    // Weekly scores for scoring distribution
    p.weeklyScores = myMatchups
      .filter(function(r) { return r.Week && r.Week.indexOf('Week') === 0; })
      .map(function(r) { return parseFloat(r.Team_Score) || 0; });
  });

  // Store as lookup
  var lookup = {};
  allManagers.forEach(function(p) { lookup[p.name] = p; });
  return lookup;
}

function getRankColor(rank, total) {
  total = total || 14;
  var norm = (rank - 1) / (total - 1);
  if (norm <= 0.35) return 'background:rgba(90,138,90,0.15);color:#5a8a5a;';
  if (norm <= 0.65) return 'background:rgba(212,175,55,0.12);color:#a89030;';
  return 'background:rgba(168,90,90,0.15);color:#a85a5a;';
}

function renderManagerProfile(profile, totalManagers) {
  if (!profile) return;
  var n = totalManagers || 14;

  // Name and subtitle
  var el = document.getElementById;
  document.getElementById('profile-name').textContent = profile.name;
  var years = profile.seasons.map(function(s) { return s.year; });
  var minY = Math.min.apply(null, years);
  var maxY = Math.max.apply(null, years);
  document.getElementById('profile-subtitle').textContent = profile.seasonCount + ' seasons (' + minY + '-' + maxY + ')';

  // Logo
  var lastname = LASTNAME_MAP[profile.name] || '';
  document.getElementById('profile-logo').src = '../images/logos/' + lastname + '.png';

  // Championship badges
  var badgesEl = document.getElementById('profile-badges');
  if (profile.totalChamps > 0) {
    badgesEl.innerHTML = profile.champYears.map(function(y) {
      return '<span class="champ-badge">&#127942; ' + y + '</span>';
    }).join(' ');
  } else {
    badgesEl.innerHTML = '';
  }

  // Career stats
  document.getElementById('stat-wins').textContent = profile.totalW;
  document.getElementById('stat-losses').textContent = profile.totalL;
  document.getElementById('stat-winpct').textContent = profile.winPct.toFixed(3);
  document.getElementById('stat-playoffs').textContent = profile.totalPlayoffs;
  document.getElementById('stat-champs').textContent = profile.totalChamps;
  document.getElementById('stat-pfg').textContent = profile.avgPfg.toFixed(1);

  // Ranks
  document.getElementById('rank-wins').textContent = '#' + profile.totalW_rank;
  document.getElementById('rank-wins').style.cssText = getRankColor(profile.totalW_rank, n);
  document.getElementById('rank-losses').textContent = '#' + profile.totalL_rank;
  document.getElementById('rank-losses').style.cssText = getRankColor(profile.totalL_rank, n);
  document.getElementById('rank-winpct').textContent = '#' + profile.winPct_rank;
  document.getElementById('rank-winpct').style.cssText = getRankColor(profile.winPct_rank, n);
  document.getElementById('rank-playoffs').textContent = '#' + profile.totalPlayoffs_rank;
  document.getElementById('rank-playoffs').style.cssText = getRankColor(profile.totalPlayoffs_rank, n);
  document.getElementById('rank-pfg').textContent = '#' + profile.avgPfg_rank;
  document.getElementById('rank-pfg').style.cssText = getRankColor(profile.avgPfg_rank, n);

  // Rivalries
  document.getElementById('rival-best-name').textContent = profile.bestRival || 'N/A';
  document.getElementById('rival-best-record').textContent = profile.bestRivalRecord ? profile.bestRivalRecord + ' (' + profile.bestRivalPct + ')' : '';
  document.getElementById('rival-worst-name').textContent = profile.worstRival || 'N/A';
  document.getElementById('rival-worst-record').textContent = profile.worstRivalRecord ? profile.worstRivalRecord + ' (' + profile.worstRivalPct + ')' : '';

  // Rivalry logos
  var bestLn = LASTNAME_MAP[profile.bestRival] || '';
  var worstLn = LASTNAME_MAP[profile.worstRival] || '';
  document.getElementById('rival-best-logo').src = bestLn ? '../images/logos/' + bestLn + '.png' : '';
  document.getElementById('rival-worst-logo').src = worstLn ? '../images/logos/' + worstLn + '.png' : '';

  // Season table
  var tbody = document.querySelector('#season-table tbody');
  tbody.innerHTML = '';
  profile.seasons.forEach(function(s) {
    var tr = document.createElement('tr');
    var diffClass = s.diff >= 0 ? 'val-green' : 'val-red';
    var diffStr = s.diff >= 0 ? '+' + s.diff.toFixed(1) : s.diff.toFixed(1);
    var playoffStr = s.playoffs ? '<span class="playoff-yes">&#10003;</span>' : '<span class="playoff-no">&#10007;</span>';

    // PF/G cell coloring
    var pfgCellClass = '';
    if (s.pfgRank <= 5) pfgCellClass = 'cell-good';
    else if (s.pfgRank <= 10) pfgCellClass = 'cell-mid';
    else pfgCellClass = 'cell-bad';

    tr.innerHTML =
      '<td class="val-bold">' + s.year + '</td>' +
      '<td>' + s.team + '</td>' +
      '<td>' + s.w + '-' + s.l + '</td>' +
      '<td class="val-bold">' + s.winPct.toFixed(3) + '</td>' +
      '<td class="' + pfgCellClass + '">' + s.pfg.toFixed(1) + '</td>' +
      '<td>' + s.pag.toFixed(1) + '</td>' +
      '<td class="' + diffClass + '">' + diffStr + '</td>' +
      '<td>' + s.draftSlot + '</td>' +
      '<td>' + playoffStr + '</td>';
    tbody.appendChild(tr);
  });
}

/* ── UPDATE MANAGER PILLS WITH REAL DATA ── */
function updateManagerPills(profileLookup) {
  var pills = document.querySelectorAll('.mgr-pill');
  pills.forEach(function(pill) {
    var name = pill.getAttribute('data-manager');
    // Try exact match, then with period
    var profile = profileLookup[name] || profileLookup[name + '.'];
    if (!profile) return;
    var quickEl = pill.querySelector('.mgr-quick');
    if (quickEl) {
      quickEl.textContent = profile.totalW + '-' + profile.totalL + ' · ' + profile.winPct.toFixed(3);
    }
  });
}
