/* Draft Fingerprints: every manager's draft profile (radar of ten traits, ADP deviation by position,
   the Metric Explorer), the draft archetypes, the archetype scatter and outcomes, and the method.

   Reads config.json and data/v1/draft-fingerprints.json (schema "draft-fingerprints"); the template
   metadata (labels, explorer groups, metric descriptions) is in fingerprint-meta.js. Ported from the
   Stage A page with the same layout (decision 7.14). buildData() turns the model into the page's
   former DATA with the rules the Stage A build used (engine/publish/pages/fingerprints.py,
   fingerprints_view), so every number shows as it did. What was written into the page now comes
   from the league and the data:
     managers       names, logos and colors (each manager's light color) from config.json; the chips
                    and explorer list the visible managers
     periods        Career and every profiled season, swatches from theme.season_colors
     method text    every number the engine computes (features, components, variance, p-values,
                    bootstrap runs and agreement, fill-ins, counts) from the model's stats; how k was
                    chosen in the original analysis, the silhouette sweep and the quoted composite
                    correlation from the league's editorial fingerprints.yaml (model `notes`), shown
                    as written (Ethan, 2026-10-07); without it the page states the engine's own
                    silhouette numbers and the correlation range from the data
     outcome axis   PPG 90-130, widened to the nearest ten when a league's archetypes fall outside */

import { config, load } from '../core/data.js';
import { managers } from '../core/managers.js';
import { drawNav, drawFooter, drawSubnav } from '../core/nav.js';
import { esc } from '../core/site.js';
import { seasonColor } from '../core/theme.js';
import { chapterRail } from '../components/chapter-rail.js';
import { RADAR_LABELS as RADAR_LABEL_BY_DIM, POSDEV_LABELS as POSDEV_LABEL_BY_DIM, EXPLORER_GROUPS as GROUPS_TEMPLATE,
         CAREER_EXTRAS_GROUP as CAREER_GROUP_TEMPLATE, METRIC_META as META_TEMPLATE } from './fingerprint-meta.js';

var Chart = window.Chart;
var cfg, mgr, M;

/* the Stage A builder's column lists (fingerprints.py) */
var SHAPE_DIMS = ['early_rb_pct', 'early_wr_pct', 'rb_wr_balance', 'positional_diversity', 'same_position_run_rate'];
var PATIENCE_DIMS = ['qb_patience', 'te_patience', 'k_patience', 'dst_patience'];
var ADP_SUMMARY = ['avg_adp_deviation', 'reach_tendency', 'value_hunting', 'draft_conviction', 'adp_independence'];
var CAREER_EXTRAS = ['draft_adaptability', 'first_qb_round', 'first_te_round', 'first_k_round', 'first_dst_round'];
var CAREER_SKIP = ['manager_key', 'hidden', 'n_seasons', 'win_pct', 'ppg', 'surplus'];
var COMPOSITES = ['reach_tendency', 'value_hunting', 'draft_conviction', 'adp_independence'];

/* ── rounding as the Stage A builder did it ── */
/* Python's round(): the float's exact decimal value, ties to even */
function pyRound(x, d) {
  if (x === null || x === undefined || !isFinite(x)) return x === undefined ? null : x;
  var neg = x < 0, parts = Math.abs(x).toFixed(100).split('.');
  var digits = parts[0] + parts[1].slice(0, d), rest = parts[1].slice(d);
  var up = rest[0] > '5' || (rest[0] === '5' && (/[1-9]/.test(rest.slice(1)) || Number(digits.slice(-1)) % 2 === 1));
  var n = (BigInt(digits) + (up ? 1n : 0n)).toString().padStart(d + 1, '0');
  var v = Number(d ? n.slice(0, n.length - d) + '.' + n.slice(n.length - d) : n);
  return neg ? -v : v;
}
/* the builder's round_half_up (numpy floor of x*10^d + 0.5) */
function halfUp(x, d) {
  if (x === null || x === undefined) return null;
  var f = Math.pow(10, d);
  return Math.floor(x * f + 0.5 + 1e-9) / f;
}
function num(v, d) { return v === null || v === undefined ? null : d === undefined ? v : pyRound(v, d); }

/* ── text helpers ── */
var WORDS = ['zero', 'one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight', 'nine', 'ten', 'eleven', 'twelve',
  'thirteen', 'fourteen', 'fifteen', 'sixteen', 'seventeen', 'eighteen', 'nineteen', 'twenty'];
function word(n) { return n < WORDS.length ? WORDS[n] : String(n); }
function cap(s) { return s.charAt(0).toUpperCase() + s.slice(1); }
function pearson(rows, a, b) {
  var xs = [], ys = [];
  rows.forEach(function (r) { if (r[a] != null && r[b] != null) { xs.push(r[a]); ys.push(r[b]); } });
  var n = xs.length;
  if (n < 3) return null;
  var mx = xs.reduce(function (s, v) { return s + v; }, 0) / n, my = ys.reduce(function (s, v) { return s + v; }, 0) / n;
  var sxy = 0, sxx = 0, syy = 0;
  for (var i = 0; i < n; i++) { sxy += (xs[i] - mx) * (ys[i] - my); sxx += (xs[i] - mx) * (xs[i] - mx); syy += (ys[i] - my) * (ys[i] - my); }
  return sxx && syy ? sxy / Math.sqrt(sxx * syy) : null;
}
function rText(r) { return r === null ? 'n/a' : (r < 0 ? '−' : '') + Math.abs(r).toFixed(2); }

/* ── DATA from the model ── */
var FINGERPRINTS, RADAR_DIMS, RADAR_LABELS, POSDEV_DIMS, POSDEV_LABELS, EXPLORER_GROUPS, CAREER_EXTRAS_GROUP, METRIC_META;
var GLOBAL_RANGES, CAREER_RANGES, ARCHETYPES, MANAGERS_ORDERED, PERIODS, FINISHED;
var CLUSTER_BY_ID = {};

function buildData() {
  var name = function (k) { return mgr.name(k); };
  RADAR_DIMS = M.radar_dims;
  POSDEV_DIMS = M.posdev_dims;
  RADAR_LABELS = RADAR_DIMS.map(function (d) { return RADAR_LABEL_BY_DIM[d] || d; });
  POSDEV_LABELS = POSDEV_DIMS.map(function (d) { return POSDEV_LABEL_BY_DIM[d] || d; });
  var have = function (rows, c) { return rows.some(function (r) { return c in r; }); };
  var metrics = SHAPE_DIMS.concat(PATIENCE_DIMS, ADP_SUMMARY).filter(function (c) { return have(M.seasons, c); }).concat(POSDEV_DIMS);
  var archName = {};
  M.archetypes.forEach(function (a) { archName[a.id] = a.name; });

  function entry(r, career) {
    var win = career ? num(r.win_pct, 3) : halfUp(r.win_pct, 3);
    var ppg = career ? num(r.ppg, 2) : halfUp(r.ppg, 2);
    var sur = career ? num(r.surplus, 4) : num(r.surplus);
    var all = {};
    metrics.forEach(function (m) { all[m] = num(r[m]); });
    all.Win_Pct = win; all.PPG = ppg; all.avg_surplus_per_pick = sur;
    if (career) {
      CAREER_EXTRAS.forEach(function (c) { if (c in r) all[c] = num(r[c]); });
      all.n_seasons = r.n_seasons;
    }
    var o = { raw: {}, normalized: {}, posdev: {}, all: all };
    RADAR_DIMS.forEach(function (d) { if (d in r) o.raw[d] = num(r[d]); if (('norm_' + d) in r) o.normalized[d] = num(r['norm_' + d], 1); });
    POSDEV_DIMS.forEach(function (d) { o.posdev[d] = num(r[d]); });
    var cl = career ? null : (r.cluster === undefined ? null : r.cluster);
    o.cluster = cl;
    o.archetype = cl === null ? null : (archName[cl] === undefined ? null : archName[cl]);
    o.outcomes = { win_pct: win, ppg: ppg, surplus: sur };
    return o;
  }

  // every manager with a profile, by name: finished seasons, career, then the live season
  FINGERPRINTS = {};
  var keys = Array.from(new Set(M.seasons.map(function (r) { return r.manager_key; }).concat(M.career.map(function (r) { return r.manager_key; }))))
    .sort(function (a, b) { return name(a) < name(b) ? -1 : name(a) > name(b) ? 1 : 0; });
  keys.forEach(function (k) {
    var per = {};
    var mine = M.seasons.filter(function (r) { return r.manager_key === k; }).sort(function (a, b) { return a.season - b.season; });
    mine.filter(function (r) { return !r.live; }).forEach(function (r) { per[String(r.season)] = entry(r, false); });
    var cr = M.career.find(function (r) { return r.manager_key === k; });
    if (cr) per.career = entry(cr, true);
    mine.filter(function (r) { return r.live; }).forEach(function (r) { per[String(r.season)] = entry(r, false); });
    FINGERPRINTS[name(k)] = per;
  });

  // scales: finished seasons, and the career averages
  FINISHED = M.seasons.filter(function (r) { return !r.live; });
  function ranges(rows, cols, outcome) {
    var out = {};
    cols.concat(['Win_Pct', 'PPG', 'avg_surplus_per_pick']).forEach(function (c) {
      var vals = rows.map(function (r) { return c === 'Win_Pct' || c === 'PPG' || c === 'avg_surplus_per_pick' ? outcome(r, c) : r[c]; })
        .filter(function (v) { return v !== null && v !== undefined; });
      if (vals.length) out[c] = [Math.min.apply(null, vals), Math.max.apply(null, vals)];
    });
    return out;
  }
  GLOBAL_RANGES = ranges(FINISHED, metrics, function (r, c) {
    return c === 'Win_Pct' ? halfUp(r.win_pct, 3) : c === 'PPG' ? halfUp(r.ppg, 2) : r.surplus;
  });
  var careerCols = M.career.length ? Object.keys(M.career[0]).filter(function (c) { return CAREER_SKIP.indexOf(c) === -1 && c.indexOf('norm_') !== 0; }) : [];
  CAREER_RANGES = ranges(M.career, careerCols, function (r, c) {
    return c === 'Win_Pct' ? num(r.win_pct, 3) : c === 'PPG' ? num(r.ppg, 2) : num(r.surplus, 4);
  });

  // archetypes: the summary cards and every clustered finished season
  var st = M.stats, r3 = function (k) { return st[k] === null || st[k] === undefined ? null : pyRound(st[k], 3); };
  ARCHETYPES = {
    cluster_summary: M.archetypes.map(function (a) {
      var center = {};
      RADAR_DIMS.forEach(function (d) { if (a.center[d] !== undefined) center[d] = pyRound(a.center[d], 2); });
      return { id: a.id, name: a.name, desc: a.description, n: a.n, color: a.color, center: center,
               outcomes: { win_pct: pyRound(a.win_pct, 2), ppg: pyRound(a.ppg, 2), avg_surplus_per_pick: pyRound(a.surplus, 2) } };
    }),
    assignments: FINISHED.filter(function (r) { return r.cluster !== null && r.cluster !== undefined; })
      .slice().sort(function (a, b) {
        var x = name(a.manager_key), y = name(b.manager_key);
        return x < y ? -1 : x > y ? 1 : a.season - b.season;
      }).map(function (r) {
        var e = entry(r, false);
        return { manager: name(r.manager_key), season: r.season, cluster: e.cluster, archetype: e.archetype, dims: e.raw,
                 posdev: e.posdev, outcomes: e.outcomes };
      }),
    k: st.k, n_observations: st.n_observations, n_managers: st.n_managers, n_multi_cluster: st.n_multi_cluster || 0,
    stats: { win_pct_p: r3('win_pct_p'), ppg_p: r3('ppg_p'), silhouette_pca_k4: r3('silhouette_pca'),
             silhouette_raw_k4: r3('silhouette_raw'), silhouette_k3_gmm: r3('silhouette_k3_gmm'),
             bootstrap_mean_ari: r3('bootstrap_mean_ari'), bootstrap_std_ari: r3('bootstrap_std_ari'),
             bootstrap_p5_p95: [r3('bootstrap_p5'), r3('bootstrap_p95')] }
  };
  ARCHETYPES.cluster_summary.forEach(function (c) { CLUSTER_BY_ID[c.id] = c; });

  // the visible managers with a profile, by name; each in their light color
  MANAGERS_ORDERED = mgr.visible.filter(function (m) { return FINGERPRINTS[m.name]; })
    .slice().sort(function (a, b) { return a.name < b.name ? -1 : a.name > b.name ? 1 : 0; })
    .map(function (m) { return { name: m.name, key: m.key, logo: mgr.logo(m.key), color: (m.colors && (m.colors.light || m.colors.dark)) || null }; });
  PERIODS = Array.from(new Set(M.seasons.map(function (r) { return r.season; }))).sort(function (a, b) { return a - b; });

  // the template with the numbers the descriptions quote
  EXPLORER_GROUPS = GROUPS_TEMPLATE.map(function (g) { return { id: g.id, label: g.label, cols: g.cols.filter(function (c) { return c in GLOBAL_RANGES || c in CAREER_RANGES || have(M.seasons, c); }) }; });
  CAREER_EXTRAS_GROUP = CAREER_GROUP_TEMPLATE;
  METRIC_META = {};
  Object.keys(META_TEMPLATE).forEach(function (k) {
    var m = Object.assign({}, META_TEMPLATE[k]);
    if (m.desc) m.desc = metaText(m.desc);
    if (m.missing_note) m.missing_note = metaText(m.missing_note);
    METRIC_META[k] = m;
  });
}

/* ── numbers for the text ── */
function convictionR(html) {
  var note = (M.notes || {}).conviction_r;
  if (note) return html ? note : note.replace(/&ndash;/g, '–');
  var rs = [];
  for (var i = 0; i < COMPOSITES.length; i++) for (var j = i + 1; j < COMPOSITES.length; j++) {
    var r = pearson(FINISHED, COMPOSITES[i], COMPOSITES[j]);
    if (r !== null) rs.push(r);
  }
  if (!rs.length) return 'n/a';
  return Math.min.apply(null, rs).toFixed(2) + (html ? '&ndash;' : '–') + Math.max.apply(null, rs).toFixed(2);
}
function fill(pos) { return (M.stats.fills || []).find(function (f) { return f.position === pos; }) || null; }
function fillSentence(pos) {
  var f = fill(pos);
  if (!f) return '';
  if (pos !== 'K' && fill('K')) return ' ' + f.filled + ' of ' + M.stats.n_observations + ' manager-seasons were imputed for the same reason as K.';
  return ' ' + f.filled + ' of ' + M.stats.n_observations + ' manager-seasons were imputed (late-round picks fell outside the tracked ADP universe).';
}
function hiddenProfiles() {
  var by = {};
  M.seasons.forEach(function (r) { var m = mgr.get(r.manager_key); if (m && m.hidden) (by[r.manager_key] = by[r.manager_key] || []).push(r.season); });
  return Object.keys(by).sort(function (a, b) { return mgr.name(a) < mgr.name(b) ? -1 : 1; }).map(function (k) { return { name: mgr.name(k), seasons: by[k] }; });
}
function andList(xs) { return xs.length < 2 ? xs.join('') : xs.slice(0, -1).join(', ') + ' and ' + xs[xs.length - 1]; }
function metaText(s) {
  return s.replace(/\{r:([a-z_]+):([a-z_]+)\}/g, function (_, a, b) { return rText(pearson(FINISHED, a, b)); })
    .replace(/\{r_conviction\}/g, function () { return convictionR(false); })
    .replace(/\{fill:([^}]+)\}/g, function (_, pos) { return fillSentence(pos); })
    .replace(/\{p_win\}/g, function () { return M.stats.win_pct_p == null ? 'n/a' : pyRound(M.stats.win_pct_p, 3).toFixed(3); })
    .replace(/\{p_ppg\}/g, function () { return M.stats.ppg_p == null ? 'n/a' : pyRound(M.stats.ppg_p, 3).toFixed(3); })
    .replace(/\{surplus_missing\}/g, function () {
      var h = hiddenProfiles();
      return h.length ? 'Missing for ' + andList(h.map(function (x) { return x.name + ' (' + x.seasons.join(', ') + ')'; })) + ', excluded from the surplus join.' : '';
    });
}

function writeText() {
  var st = M.stats, k = st.k, comps = st.pca_components;
  var fin = PERIODS.filter(function (p) { return FINISHED.some(function (r) { return r.season === p; }); });
  var range = function (dash) { return !fin.length ? '' : fin.length === 1 ? String(fin[0]) : fin[0] + dash + fin[fin.length - 1]; };
  var p3 = function (v) { return v == null ? 'n/a' : pyRound(v, 3).toFixed(3); };
  var set = function (id, html) { var el = document.getElementById(id); if (el) el.innerHTML = html; };
  set('header-sub', cap(word(st.n_features)) + ' signals, ' + word(k) + " fuzzy archetypes, and a season-by-season fingerprint for every manager who's ever sat at the draft board.");
  set('read-note', 'Every manager-season is scored on ' + st.n_features + ' drafting signals, distilled here into ' + RADAR_DIMS.length
    + " non-redundant traits. The radar below normalizes each trait against the field <em>for that season</em> (outer edge = that year's league max), "
    + 'so the shapes compare drafting style, not draft-year inflation. Toggle managers on and off, switch between seasons or career, and hover any point '
    + 'for the raw number behind it. All data covers ' + range('-') + ', ' + st.n_observations + ' manager-seasons across ' + st.n_managers + ' managers.');
  set('radar-note', "Outer edge = league max for that trait, <strong>within the selected period</strong> (each season is normalized against only that season's "
    + 'managers; Career is normalized against career averages). Early RB%, Early WR%, RB/WR Balance, and Positional Diversity describe draft shape. '
    + 'Draft Conviction stands in for four correlated "deviates from consensus" composites (Reach Tendency, Value Hunting, Draft Conviction, ADP '
    + "Independence, r=" + convictionR(true) + ") so the chart doesn't quadruple-count one signal.");
  set('explorer-title', 'All ' + st.n_features + ' drafting signals, grouped and sortable, for the period selected above.');
  set('explorer-note', 'Color intensity shows where a value sits within the full ' + range('&ndash;') + ' range for that column (career columns are scaled '
    + 'against the ' + M.career.length + ' career averages). Columns marked with a dotted underline belong to a correlated composite cluster; see the '
    + 'callout above the radar. Click a column header to sort.');
  set('archetype-title', 'K-means (k=' + k + ', on ' + comps + ' PCA components) groups manager-seasons into ' + word(k) + ' drafting styles.');
  var soft = (M.notes || {}).silhouette_sweep || ('the silhouette score was low (' + (st.silhouette_pca == null ? 'n/a' : st.silhouette_pca.toFixed(2)) + ' for k=' + k + ')');
  set('archetype-note', "This reflects <strong>draft-day decisions only</strong>, not waivers, trades, injuries, or lineup management. It's also a soft "
    + 'grouping: ' + soft + ', meaning this is a continuous behavioral space, not sharply separated tribes. A bootstrap resample ('
    + st.bootstrap_runs + ' iterations) put average agreement with the original clustering at ' + st.bootstrap_mean_ari.toFixed(2) + ' (ARI), ranging from '
    + st.bootstrap_p5.toFixed(2) + ' to ' + st.bootstrap_p95.toFixed(2) + ' across resamples: real signal, but plenty of manager-seasons sit near a boundary '
    + "rather than deep inside one archetype. And because " + (st.n_multi_cluster || 0) + " of the league's " + st.n_managers + ' managers show up in more '
    + 'than one archetype across their seasons, archetype behaves like a <strong>season-level style choice</strong>, not a fixed personal trait.');
  set('scatter-note', 'X axis: surplus per pick that season. Y axis: points per game, with the dashed line marking the league-wide average across all '
    + st.n_observations + ' manager-seasons. The four quadrants are purely descriptive: Kruskal-Wallis tests found no significant link between archetype '
    + 'and either Win% or PPG (see Archetype Outcomes below), so no quadrant should be read as "the draft caused the record."');
  set('outcomes-note', 'Kruskal-Wallis tests found no significant difference in Win% (p=' + p3(st.win_pct_p) + ') or PPG (p=' + p3(st.ppg_p) + ') across '
    + 'archetypes. Bars and line show the averages anyway for reference, though the differences you see here are not distinguishable from noise. '
    + 'Surplus/pick, plotted below, tells the same story: full overlap across all ' + word(k) + ' groups.');
  set('method-features', st.n_features + ' z-scored features per manager-season fed a PCA reduced to ' + comps + ' components ('
    + Math.round(st.pca_variance * 100) + '% variance retained) before clustering. PCA was chosen specifically to neutralize a real multicollinearity '
    + 'cluster: Reach Tendency, Value Hunting, Draft Conviction, and ADP Independence pairwise-correlate at r=' + convictionR(true)
    + ', likely one underlying ADP-deviation signal wearing four names.');
  set('k-heading', 'Choosing k=' + k);
  set('method-k', (M.notes || {}).k_choice || ('k=' + k + ' is the engine\'s fixed setting. On the ' + comps + ' PCA components the k-means fit\'s '
    + 'silhouette is ' + (st.silhouette_pca == null ? 'n/a' : st.silhouette_pca.toFixed(3))
    + (st.silhouette_k3_gmm == null ? '' : '; an independent 3-group Gaussian mixture on the same components scores ' + st.silhouette_k3_gmm.toFixed(3)) + '.'));
  set('method-impute', imputeText());
  var h = hiddenProfiles();
  var li = document.getElementById('method-hidden');
  if (!h.length) { if (li) li.remove(); } else {
    var seasons = Array.from(new Set([].concat.apply([], h.map(function (x) { return x.seasons; }))));
    var only = seasons.length === 1 ? (h.length === 2 ? 'both ' : h.length > 2 ? 'all ' : '') + seasons[0] + '-only' : seasons.join(', ');
    set('method-hidden', andList(h.map(function (x) { return esc(x.name); })) + ' (' + only + ') ' + (h.length === 1 ? 'is' : 'are') + ' excluded from surplus-based analysis; no surplus join '
      + 'is available for ' + (seasons.length === 1 ? 'that season' : 'those seasons') + '.');
  }
  set('method-multi', 'Managers are not independent across seasons: ' + (st.n_multi_cluster || 0) + ' of ' + st.n_managers + ' appear in more than one '
    + 'archetype. Cross-archetype performance comparisons should be read with that in mind.');
}

function imputeText() {
  var fills = M.stats.fills || [];
  if (!fills.length) return 'No ADP deviations needed imputing.';
  var label = function (p) { return p === 'D/ST' ? 'DST' : p; };
  var target = function (f) { return f.source.replace(/_patience$/, '') + '_adp_deviation'; };
  var many = fills.length > 1;
  var text = andList(fills.map(function (f) { return label(f.position); })) + ' ADP-deviation ' + (many ? 'were' : 'was') + ' missing for '
    + andList(fills.map(function (f) { return String(f.filled); })) + ' of ' + M.stats.n_observations + ' rows' + (many ? ' respectively' : '')
    + ', since those late-round picks fell outside the tracked ADP universe. ';
  var reg = fills.filter(function (f) { return f.method === 'regression'; }), mean = fills.filter(function (f) { return f.method === 'mean'; });
  if (reg.length) {
    text += (reg.length === fills.length ? (many ? 'Both were' : 'It was') : andList(reg.map(function (f) { return label(f.position); })) + (reg.length > 1 ? ' were' : ' was'))
      + ' imputed via linear regression on the corresponding patience score ('
      + reg.map(function (f) { return f.source + ' &rarr; ' + target(f) + ', r=' + f.r.toFixed(2); }).join('; ')
      + "), with every imputed value falling inside the column's observed range.";
  }
  if (mean.length) {
    text += (reg.length ? ' ' : '') + andList(mean.map(function (f) { return label(f.position); })) + (mean.length > 1 ? ' were' : ' was')
      + ' filled with the observed mean (too few rows to fit a regression).';
  }
  return text;
}

/* ══ the page (ported from the Stage A page) ══════════════════════════════════════════════════ */

var POSITION_COLOR_BY_LABEL = { QB: '#983a3a', RB: '#4a7a4a', WR: '#3a6f98', TE: '#a07010', K: '#6a6460', DST: '#504840' };
var FALLBACK_COLORS = ['#c9683f', '#4a7fa8', '#a85a5a', '#5a8a5a', '#8a6fa8', '#a8925a', '#5a8a8a', '#7a7a7a'];

var currentPeriod = 'career';
var activeManagers = {};
var radarChart = null;
var currentGroup = 'shape';
var sortCol = null, sortDir = 1;
var searchQuery = '';

function groupDescriptions() {
  return {
    shape: 'Where early draft capital goes: RB vs. WR investment in rounds 1–3, how balanced that split is, how many positions get touched overall, and how often a manager drafts the same position in bursts.',
    patience: 'How many rounds later than the field a manager waits to draft their first player at each non-RB/WR skill position. Higher = more patient.',
    conviction: 'How far off consensus ADP a manager drafts, expressed five different ways. These five metrics correlate heavily (r=' + convictionR(false) + '); read them as one signal from different angles, not five independent votes.',
    posdev: 'Average ADP deviation broken out by position. Positive means the manager reached (drafted ahead of consensus ADP); negative means the player fell to them (drafted later than ADP).',
    outcomes: 'Regular-season results. Not significantly associated with any drafting signal above (Kruskal-Wallis p=' + metaText('{p_win}') + ' for Win%, p=' + metaText('{p_ppg}') + ' for PPG).',
    career_extras: "Career-only figures not used in the season-level clustering: raw first-pick rounds by position, positional concentration (mirror image of diversity), and draft adaptability, i.e. how much a manager's approach varies year to year."
  };
}
var GROUP_DESCRIPTIONS;

function getColor(i) { return FALLBACK_COLORS[i % FALLBACK_COLORS.length]; }
function periodKey() { return currentPeriod === 'career' ? 'career' : String(currentPeriod); }
function getEntry(name, pk) { var e = FINGERPRINTS[name]; if (!e) return null; return e[pk] || null; }
function escapeHtml(s) { return String(s).replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;').replace(/>/g, '&gt;'); }

function fmtVal(key, v) {
  if (v === null || v === undefined || (typeof v === 'number' && isNaN(v))) return 'N/A';
  var fmt = (METRIC_META[key] || {}).fmt || 'num1';
  if (fmt === 'pct1') return v.toFixed(1) + '%';
  if (fmt === 'pct1raw') return (v * 100).toFixed(1) + '%';
  if (fmt === 'num1') return v.toFixed(1);
  if (fmt === 'signed1') return (v >= 0 ? '+' : '') + v.toFixed(1);
  if (fmt === 'signed3') return (v >= 0 ? '+' : '') + v.toFixed(3);
  return String(v);
}

/* ── period buttons and manager chips ── */
function buildPeriods() {
  var row = document.getElementById('period-row');
  row.insertAdjacentHTML('beforeend', '<button class="filter-btn active" data-period="career">Career</button>' + PERIODS.map(function (y) {
    var c = seasonColor(cfg, y);
    return '<button class="filter-btn year-swatch-btn"' + (c ? ' style="--swatch-color:' + esc(c) + ';"' : '') + ' data-period="' + y + '">' + y + '</button>';
  }).join(''));
  row.addEventListener('click', function (e) {
    var btn = e.target.closest('.filter-btn');
    if (btn) setPeriod(btn.dataset.period === 'career' ? 'career' : Number(btn.dataset.period), btn);
  });
}

function buildChips() {
  var g = document.getElementById('mgr-chips'); g.innerHTML = '';
  MANAGERS_ORDERED.forEach(function (m, i) {
    var c = m.color || getColor(i), chip = document.createElement('div');
    chip.className = 'mgr-chip'; chip.dataset.manager = m.name; chip.dataset.color = c;
    chip.style.borderColor = c;
    chip.innerHTML = (m.logo ? '<img src="' + esc(m.logo) + '" style="width:22px;height:22px;border-radius:50%;object-fit:cover;" onerror="this.remove()">' : '')
      + '<span class="chip-dot" style="background:' + c + '"></span>' + esc(m.name.split(' ').pop());
    chip.onclick = function () { toggleManager(m.name, chip, c); };
    g.appendChild(chip);
  });
}

function toggleManager(name, chip, color) {
  if (activeManagers[name]) {
    delete activeManagers[name]; chip.classList.remove('active');
    chip.style.background = 'rgba(var(--accent-rgb),0.06)'; chip.style.color = '';
  } else {
    activeManagers[name] = color; chip.classList.add('active');
    chip.style.background = color; chip.style.color = '#fff';
  }
  renderRadar(); renderActiveLegend(); renderPosdevStrip();
}

function setPeriod(period, btn) {
  document.querySelectorAll('.filter-btn').forEach(function (b) { b.classList.remove('active'); });
  btn.classList.add('active'); currentPeriod = period;
  renderRadar(); renderActiveLegend(); renderPosdevStrip();
  buildExplorerTabs(); buildExplorerTable();
}

/* ── radar ── */
function renderRadar() {
  if (radarChart) { radarChart.destroy(); radarChart = null; }
  var ctx = document.getElementById('chart-radar').getContext('2d');
  var datasets = [];
  var pk = periodKey();
  Object.keys(activeManagers).forEach(function (name) {
    var color = activeManagers[name], entry = getEntry(name, pk); if (!entry) return;
    var norm = entry.normalized, raw = entry.raw;
    datasets.push({ label: name, data: RADAR_DIMS.map(function (d) { return norm[d] !== undefined && norm[d] !== null ? norm[d] : 50; }),
      backgroundColor: color + '28', borderColor: color, borderWidth: 2.5,
      pointBackgroundColor: color, pointBorderColor: '#fff', pointBorderWidth: 1.5,
      pointRadius: 5, pointHoverRadius: 8, _rawVals: RADAR_DIMS.map(function (d) { return raw[d] !== undefined ? raw[d] : null; }) });
  });
  if (datasets.length === 0) {
    MANAGERS_ORDERED.forEach(function (m, i) {
      var entry = getEntry(m.name, pk); if (!entry) return;
      var color = m.color || getColor(i);
      datasets.push({ label: m.name, data: RADAR_DIMS.map(function (d) { return entry.normalized[d] !== undefined && entry.normalized[d] !== null ? entry.normalized[d] : 50; }),
        backgroundColor: color + '28', borderColor: color, borderWidth: 1.5, pointRadius: 3, pointBackgroundColor: color,
        pointBorderColor: '#fff', pointBorderWidth: 1,
        _rawVals: RADAR_DIMS.map(function (d) { return entry.raw[d] !== undefined ? entry.raw[d] : null; }) });
    });
  }
  radarChart = new Chart(ctx, {
    type: 'radar',
    data: { labels: RADAR_LABELS, datasets: datasets },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: {
        legend: { display: datasets.length > 0 && datasets.length <= 8, position: 'bottom', labels: { color: '#5a5550', boxWidth: 12, padding: 14, font: { size: 11 } } },
        tooltip: { callbacks: {
          title: function (items) { return RADAR_LABELS[items[0].dataIndex]; },
          label: function (c) { var rv = c.dataset._rawVals; if (!rv) return c.dataset.label; return c.dataset.label + ': ' + fmtVal(RADAR_DIMS[c.dataIndex], rv[c.dataIndex]); }
        } }
      },
      scales: { r: { min: 0, max: 100, ticks: { stepSize: 25, display: false }, grid: { color: 'rgba(156,148,156,0.18)' },
        angleLines: { color: 'rgba(156,148,156,0.18)' }, pointLabels: { color: '#6b5f50', font: { size: 11, family: "'Outfit', sans-serif", weight: '600' } } } }
    }
  });
}

function renderActiveLegend() {
  var el = document.getElementById('active-legend'); if (!el) return;
  var pk = periodKey(), names = Object.keys(activeManagers);
  if (names.length === 0) { el.innerHTML = ''; return; }
  el.innerHTML = names.map(function (name) {
    var color = activeManagers[name], entry = getEntry(name, pk), badge = '';
    if (entry && entry.archetype !== null && entry.archetype !== undefined) {
      var cl = CLUSTER_BY_ID[entry.cluster];
      badge = '<span class="active-legend-arch" style="background:' + (cl ? cl.color : '#8a8480') + '">' + esc(entry.archetype) + '</span>';
    }
    return '<span class="active-legend-item"><span class="active-legend-dot" style="background:' + color + '"></span>' + esc(name) + badge + '</span>';
  }).join('');
}

/* ── ADP deviation strip ── */
function renderPosdevStrip() {
  var el = document.getElementById('posdev-strip'); if (!el) return;
  var names = Object.keys(activeManagers);
  if (names.length === 0) {
    el.innerHTML = '<div class="posdev-empty">Select one or more managers above to see their ADP-deviation fingerprint.</div>';
    return;
  }
  var pk = periodKey(), ranges = pk === 'career' ? CAREER_RANGES : GLOBAL_RANGES;
  el.innerHTML = names.map(function (name) {
    var entry = getEntry(name, pk); if (!entry) return '';
    var color = activeManagers[name];
    var cells = POSDEV_DIMS.map(function (d, idx) {
      var v = entry.posdev[d], lbl = POSDEV_LABELS[idx], posColor = POSITION_COLOR_BY_LABEL[lbl] || color;
      var rng = ranges[d] || [-1, 1];
      var extent = Math.max(Math.abs(rng[0]), Math.abs(rng[1]), 0.001);
      var pct = (v === null || v === undefined) ? 0 : Math.max(-100, Math.min(100, (v / extent) * 100));
      var leftPct, widthPct;
      if (pct >= 0) { leftPct = 50; widthPct = pct / 2; } else { leftPct = 50 + pct / 2; widthPct = -pct / 2; }
      return '<div class="posdev-cell"><div class="posdev-cell-label" style="color:' + posColor + ';">' + esc(lbl) + '</div>'
        + '<div class="posdev-track"><div class="posdev-fill" style="left:' + leftPct + '%;width:' + widthPct + '%;background:' + posColor + ';"></div></div>'
        + '<div class="posdev-val">' + ((v === null || v === undefined) ? 'N/A' : fmtVal(d, v)) + '</div></div>';
    }).join('');
    return '<div class="posdev-row"><div class="posdev-name"><span class="posdev-name-dot" style="background:' + color + '"></span>' + esc(name) + '</div>'
      + '<div class="posdev-bars">' + cells + '</div></div>';
  }).join('');
}

/* ── Metric Explorer ── */
function activeGroups() {
  var groups = EXPLORER_GROUPS.slice();
  if (periodKey() === 'career') groups.push(CAREER_EXTRAS_GROUP);
  return groups;
}

function buildExplorerTabs() {
  var groups = activeGroups();
  if (!groups.some(function (g) { return g.id === currentGroup; })) currentGroup = 'shape';
  document.getElementById('explorer-tabs').innerHTML = groups.map(function (g) {
    return '<button class="tab-btn' + (g.id === currentGroup ? ' active' : '') + '" data-group="' + g.id + '">' + esc(g.label) + '</button>';
  }).join('');
}

function cellShadeNeutral(val, min, max) {
  if (min === max || val === null || val === undefined) return '';
  var p = Math.max(0, Math.min(1, (val - min) / (max - min)));
  return 'background:rgba(var(--accent-rgb),' + (0.05 + 0.32 * p).toFixed(2) + ');font-weight:' + (p > 0.6 ? '600' : '500') + ';';
}
function cellShadeOutcome(val, min, max) {
  if (min === max || val === null || val === undefined) return '';
  var p = Math.max(0, Math.min(1, (val - min) / (max - min)));
  var r, g, b, t;
  if (p <= 0.5) { t = p / 0.5; r = Math.round(192 + (245 - 192) * t); g = Math.round(58 + (240 - 58) * t); b = Math.round(58 + (232 - 58) * t); }
  else { t = (p - 0.5) / 0.5; r = Math.round(245 + (74 - 245) * t); g = Math.round(240 + (168 - 240) * t); b = Math.round(232 + (58 - 232) * t); }
  return 'background:rgba(' + r + ',' + g + ',' + b + ',0.45);color:' + (p > 0.65 ? '#1a3a1a' : p < 0.35 ? '#3a1a1a' : '#3d3a38') + ';font-weight:600;';
}

function buildExplorerTable() {
  var pk = periodKey(), groups = activeGroups();
  var group = groups.filter(function (g) { return g.id === currentGroup; })[0] || groups[0];
  document.getElementById('explorer-group-desc').textContent = GROUP_DESCRIPTIONS[group.id] || '';
  var cols = group.cols, ranges = pk === 'career' ? CAREER_RANGES : GLOBAL_RANGES, isOutcomeGroup = group.id === 'outcomes';
  var rows = MANAGERS_ORDERED
    .filter(function (m) { return m.name.toLowerCase().indexOf(searchQuery) !== -1; })
    .map(function (m) { return { name: m.name, entry: getEntry(m.name, pk) }; })
    .filter(function (r) { return r.entry; });
  if (sortCol) {
    rows.sort(function (a, b) {
      var av = a.entry.all[sortCol], bv = b.entry.all[sortCol];
      av = (av === null || av === undefined) ? -Infinity : av;
      bv = (bv === null || bv === undefined) ? -Infinity : bv;
      return (av - bv) * sortDir;
    });
  } else {
    rows.sort(function (a, b) { return a.name.localeCompare(b.name); });
  }
  var h = '<th data-sort="" style="cursor:default;">Manager</th>';
  cols.forEach(function (c) {
    var meta = METRIC_META[c] || {};
    var cls = (sortCol === c ? 'sorted' : '') + (meta.caution ? ' th-caution' : '');
    var arrow = sortCol === c ? (sortDir === 1 ? '▲' : '▼') : '↕';
    h += '<th class="' + cls + '" title="' + escapeHtml(meta.desc || '') + '" data-sort="' + c + '">' + (meta.short || c) + ' <span class="sort-arrow">' + arrow + '</span></th>';
  });
  document.getElementById('explorer-thead').innerHTML = h;
  var body = '';
  rows.forEach(function (r) {
    body += '<tr><td>' + esc(r.name) + '</td>';
    cols.forEach(function (c) {
      var v = r.entry.all[c], rng = ranges[c], style = '';
      if (rng && v !== null && v !== undefined) style = isOutcomeGroup ? cellShadeOutcome(v, rng[0], rng[1]) : cellShadeNeutral(v, rng[0], rng[1]);
      body += '<td style="' + style + '">' + fmtVal(c, v) + '</td>';
    });
    body += '</tr>';
  });
  document.getElementById('explorer-tbody').innerHTML = body || ('<tr><td colspan="' + (cols.length + 1) + '" style="text-align:center;color:var(--muted);padding:1.5rem;">No managers match "' + escapeHtml(searchQuery) + '".</td></tr>');
}

function bindExplorer() {
  document.getElementById('explorer-tabs').addEventListener('click', function (e) {
    var b = e.target.closest('.tab-btn');
    if (!b) return;
    currentGroup = b.dataset.group; sortCol = null; buildExplorerTabs(); buildExplorerTable();
  });
  document.getElementById('explorer-search').addEventListener('input', function (e) { searchQuery = e.target.value.toLowerCase(); buildExplorerTable(); });
  document.getElementById('explorer-thead').addEventListener('click', function (e) {
    var th = e.target.closest('th');
    if (!th) return;
    var col = th.dataset.sort || null;
    if (sortCol === col) { sortDir = -sortDir; } else { sortCol = col; sortDir = 1; }
    buildExplorerTable();
  });
}

/* ── archetypes ── */
function buildArchetypeCards() {
  var el = document.getElementById('archetype-cards'); if (!el) return;
  el.innerHTML = ARCHETYPES.cluster_summary.map(function (c) {
    var o = c.outcomes;
    return '<div class="archetype-card glass">'
      + '<div class="archetype-card-head"><span class="archetype-dot" style="background:' + c.color + '"></span>'
      + '<div class="archetype-name" style="color:' + c.color + '">' + esc(c.name) + '</div>'
      + '<div class="archetype-n">n=' + c.n + '</div></div>'
      + '<div class="archetype-desc">' + esc(c.desc) + '</div>'
      + '<div class="archetype-stats">'
      + '<div class="arch-stat"><div class="arch-stat-val" style="color:' + c.color + '">' + Math.round(o.win_pct * 100) + '%</div><div class="arch-stat-lbl">Avg Win%</div></div>'
      + '<div class="arch-stat"><div class="arch-stat-val" style="color:' + c.color + '">' + o.ppg.toFixed(1) + '</div><div class="arch-stat-lbl">Avg PPG</div></div>'
      + '<div class="arch-stat"><div class="arch-stat-val" style="color:' + c.color + '">' + (o.avg_surplus_per_pick >= 0 ? '+' : '') + o.avg_surplus_per_pick.toFixed(2) + '</div><div class="arch-stat-lbl">Surplus/Pick</div></div>'
      + '</div></div>';
  }).join('');
}

function buildClusterLegend() {
  document.getElementById('cluster-legend').innerHTML = ARCHETYPES.cluster_summary.map(function (c) {
    return '<div class="cluster-legend-item"><div class="cluster-dot" style="background:' + c.color + '"></div>' + esc(c.name) + ' <span style="color:var(--muted);font-weight:500;">(n=' + c.n + ')</span></div>';
  }).join('');
}

function buildOutcomeSurplusStrip() {
  document.getElementById('outcome-surplus-strip').innerHTML = ARCHETYPES.cluster_summary.map(function (c) {
    var v = c.outcomes.avg_surplus_per_pick;
    return '<div class="cluster-legend-item"><div class="cluster-dot" style="background:' + c.color + '"></div>' + esc(c.name) + ': <strong style="color:var(--palm)">' + (v >= 0 ? '+' : '') + v.toFixed(2) + '</strong>&nbsp;surplus/pick</div>';
  }).join('');
}

function buildScatterChart() {
  var ctx = document.getElementById('chart-scatter').getContext('2d');
  var allPpg = ARCHETYPES.assignments.map(function (a) { return a.outcomes.ppg; }).filter(function (v) { return v !== null && v !== undefined; });
  var meanPpg = allPpg.reduce(function (s, v) { return s + v; }, 0) / allPpg.length;
  var datasets = ARCHETYPES.cluster_summary.map(function (c) {
    var pts = ARCHETYPES.assignments.filter(function (a) { return a.cluster === c.id; }).map(function (a) {
      return { x: a.outcomes.surplus, y: a.outcomes.ppg, manager: a.manager, season: a.season,
               winPct: a.outcomes.win_pct !== null ? Math.round(a.outcomes.win_pct * 1000) / 10 : null, archetype: a.archetype };
    }).filter(function (p) { return p.y !== null && p.x !== null; });
    return { label: c.name, data: pts, backgroundColor: c.color + 'bb', borderColor: c.color, borderWidth: 1.5, pointRadius: 7, pointHoverRadius: 10 };
  });
  var quadrantPlugin = {
    id: 'quadrants',
    beforeDraw: function (chart) {
      var c2 = chart.ctx, xs = chart.scales.x, ys = chart.scales.y;
      var midX = xs.getPixelForValue(0), midY = ys.getPixelForValue(meanPpg);
      var left = xs.left, right = xs.right, top = ys.top, bottom = ys.bottom;
      c2.save();
      c2.fillStyle = 'rgba(90,138,90,0.06)'; c2.fillRect(midX, top, right - midX, midY - top);
      c2.fillStyle = 'rgba(168,90,90,0.06)'; c2.fillRect(left, midY, midX - left, bottom - midY);
      c2.fillStyle = 'rgba(150,130,80,0.06)'; c2.fillRect(left, top, midX - left, midY - top);
      c2.fillStyle = 'rgba(150,130,80,0.06)'; c2.fillRect(midX, midY, right - midX, bottom - midY);
      c2.strokeStyle = 'rgba(138,132,128,0.35)'; c2.lineWidth = 1.5; c2.setLineDash([5, 4]);
      c2.beginPath(); c2.moveTo(midX, top); c2.lineTo(midX, bottom); c2.stroke();
      c2.beginPath(); c2.moveTo(left, midY); c2.lineTo(right, midY); c2.stroke();
      c2.setLineDash([]);
      c2.font = '600 10px Outfit, sans-serif';
      c2.fillStyle = 'rgba(90,138,90,0.6)'; c2.fillText('High surplus, high PPG', midX + 8, top + 14);
      c2.fillStyle = 'rgba(168,90,90,0.6)'; c2.fillText('Low surplus, low PPG', left + 6, bottom - 6);
      c2.fillStyle = 'rgba(150,130,80,0.6)'; c2.fillText('Low surplus, high PPG', left + 6, top + 14);
      c2.fillText('High surplus, low PPG', midX + 8, bottom - 6);
      c2.restore();
    }
  };
  new Chart(ctx, {
    type: 'scatter',
    data: { datasets: datasets },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: {
        legend: { position: 'top', align: 'end', labels: { color: '#5a5550', boxWidth: 12, padding: 14, font: { size: 11 } } },
        tooltip: { callbacks: {
          title: function (items) { return items[0].raw.manager + ' ' + items[0].raw.season; },
          label: function (c) {
            var r = c.raw;
            return ['Archetype: ' + r.archetype, 'Surplus: ' + (r.x >= 0 ? '+' : '') + r.x.toFixed(3) + '/pick', 'PPG: ' + r.y.toFixed(1),
                    'Win%: ' + (r.winPct !== null ? r.winPct.toFixed(1) + '%' : 'N/A')];
          }
        } }
      },
      scales: {
        x: { grid: { color: 'rgba(156,148,156,0.12)', drawBorder: false }, ticks: { color: '#8a8480' }, title: { display: true, text: 'Surplus Per Pick', color: '#8a8480', font: { size: 11 } } },
        y: { grid: { color: 'rgba(156,148,156,0.12)', drawBorder: false }, ticks: { color: '#8a8480' }, title: { display: true, text: 'Points Per Game', color: '#8a8480', font: { size: 11 } }, grace: '10%' }
      }
    },
    plugins: [quadrantPlugin]
  });
}

function buildOutcomeChart() {
  var ctx = document.getElementById('chart-outcomes').getContext('2d');
  var cs = ARCHETYPES.cluster_summary;
  var colors = cs.map(function (c) { return c.color; });
  var ppgs = cs.map(function (c) { return c.outcomes.ppg; });
  var lo = Math.min.apply(null, ppgs.concat([90])), hi = Math.max.apply(null, ppgs.concat([130]));
  lo = lo < 90 ? Math.floor(lo / 10) * 10 : 90; hi = hi > 130 ? Math.ceil(hi / 10) * 10 : 130;
  new Chart(ctx, {
    type: 'bar',
    data: {
      labels: cs.map(function (c) { return c.name; }),
      datasets: [
        { label: 'Avg Win%', data: cs.map(function (c) { return Math.round(c.outcomes.win_pct * 1000) / 10; }),
          backgroundColor: colors.map(function (c) { return c + 'bb'; }), borderColor: colors, borderWidth: 1.5, borderRadius: 3, yAxisID: 'yPct' },
        { label: 'Avg PPG', type: 'line', data: ppgs, backgroundColor: 'rgba(156,148,156,0.15)', borderColor: 'rgba(156,148,156,0.7)',
          borderWidth: 1.5, borderRadius: 3, yAxisID: 'yPpg', pointRadius: 6, pointBackgroundColor: colors, pointBorderColor: '#fff', pointBorderWidth: 1.5, tension: 0.3 }
      ]
    },
    options: {
      responsive: true, maintainAspectRatio: false, interaction: { mode: 'index', intersect: false },
      plugins: {
        legend: { position: 'top', align: 'end', labels: { color: '#5a5550', boxWidth: 12, padding: 14, font: { size: 11 } } },
        tooltip: { callbacks: { label: function (c) {
          var arch = cs[c.dataIndex];
          if (c.dataset.label === 'Avg Win%') return 'Avg Win%: ' + c.parsed.y.toFixed(1) + '% (n=' + arch.n + ' seasons)';
          return 'Avg PPG: ' + c.parsed.y.toFixed(1);
        } } }
      },
      scales: {
        x: { grid: { color: 'rgba(156,148,156,0.15)', drawBorder: false }, ticks: { color: '#8a8480' } },
        yPct: { type: 'linear', position: 'left', grid: { color: 'rgba(156,148,156,0.15)', drawBorder: false }, ticks: { color: '#8a8480', callback: function (v) { return v + '%'; } },
                title: { display: true, text: 'Win %', color: '#8a8480', font: { size: 11 } }, min: 0, max: 100 },
        yPpg: { type: 'linear', position: 'right', grid: { drawOnChartArea: false }, ticks: { color: '#8a8480' },
                title: { display: true, text: 'PPG', color: '#8a8480', font: { size: 11 } }, min: lo, max: hi }
      }
    }
  });
}

config().then(function (c) {
  cfg = c;
  mgr = managers(cfg);
  drawNav(cfg, 'draft-fingerprints');
  drawSubnav(cfg, 'draft-fingerprints');
  drawFooter(cfg);
  chapterRail();
  return load('data/v1/draft-fingerprints.json');
}).then(function (m) {
  M = m;
  buildData();
  GROUP_DESCRIPTIONS = groupDescriptions();
  writeText();
  buildPeriods();
  buildChips();
  bindExplorer();
  renderRadar();
  renderActiveLegend();
  renderPosdevStrip();
  buildExplorerTabs();
  buildExplorerTable();
  buildArchetypeCards();
  buildClusterLegend();
  buildOutcomeSurplusStrip();
  buildScatterChart();
  buildOutcomeChart();
}).catch(function (err) {
  console.error(err);
  var el = document.getElementById('archetype-cards');
  if (el) el.innerHTML = '<div class="data-state data-state-error">This section could not be loaded.</div>';
});
