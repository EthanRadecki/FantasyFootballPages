/* Waiver Value: points per week rostered and position-adjusted value for every waiver and free agent
   pickup (career leaderboard, contested vs uncontested, total value, upside, value by week, best
   pickups).

   Reads config.json and data/v1/waiver-value.json (schema "waiver-value"); waiver-value-data.js turns
   the model into the shapes the page's script reads, as the Stage A build wrote them inline. The
   script itself is the Stage A page's, run inside runPage() once the data is in (decision 7.14: same
   look first; its inline handlers stay on window until the design pass). What was written into the
   page now comes from the league:
     seasons        the model's seasons, the live one labelled "(live)"; colors from theme.season_colors
     managers       names from config.json
     waiver system  each season's FAAB setting from ESPN (config.json seasons[].faab)
     excluded       the league's hidden managers */

import { config, load } from '../core/data.js';
import { managers } from '../core/managers.js';
import { drawNav, drawFooter, drawSubnav } from '../core/nav.js';
import { esc } from '../core/site.js';
import { waiverData } from './waiver-value-data.js';
import { methodNotes } from './transaction-notes.js';

var Chart = window.Chart;
var cfg, mgr;
// the page's data (waiver-value-data.js) and config
var PAGE_SEASONS, PAGE_LIVE_SEASON, SEASON_COLORS, LEADERBOARD_FULL, POSITION_SCALE, BEST_BY_MANAGER,
  WAIVER_Z_GLOBAL_MIN, WAIVER_Z_GLOBAL_MAX, WAIVER_STINTS, CONTESTED_SPLIT, UPSIDE_MIN, UPSIDE_MAX,
  BEST_PICKUPS_BY_FILTER, BEST_TOTALZ_MIN, BEST_TOTALZ_MAX, BEST_AVGZ_MIN, BEST_AVGZ_MAX;

/* "2026 (live)" for the live season, else the year (shared.js on the Stage A site) */
function seasonLabel(s) {
  return PAGE_LIVE_SEASON !== null && String(s) === String(PAGE_LIVE_SEASON) ? s + ' (live)' : String(s);
}

function runPage() {
  // The seasons this page shows, written by the build from the data (engine/publish).
  /* ── Shared red/gold/green gradient helper ── */
  var GOOD = [90,138,90];
  var MID  = [212,175,55];
  var BAD  = [168,90,90];
  function lerp(a,b,t){ return Math.round(a+(b-a)*t); }
  function gradientColor(value, min, max, invert) {
    var p = max===min ? 0.5 : (value - min) / (max - min);
    if (invert) p = 1 - p;
    var c0 = p<=0.5 ? GOOD : MID;
    var c1 = p<=0.5 ? MID : BAD;
    var t = p<=0.5 ? p/0.5 : (p-0.5)/0.5;
    var r = lerp(c0[0],c1[0],t), g = lerp(c0[1],c1[1],t), b = lerp(c0[2],c1[2],t);
    return 'rgba('+r+','+g+','+b+',0.85)';
  }

  // Season colors -- same palette used on managers.html.
  // Position colors -- same palette as the canonical .pos-badge system.
  var POSITION_COLORS = {
    QB: '#983a3a', RB: '#4a7a4a', WR: '#3a6f98',
    TE: '#a07010', K: '#6a6460', 'D/ST': '#504840'
  };
  function posBadgeClass(pos) {
    return 'pos-' + pos.replace('/', '').toLowerCase();
  }

  // Full grid: [season][position] -> [{m, ppw, z, n}]. Fixed global scales for both
  // PPW and Z so colors/axis stay consistent across every filter combination.
  // the positions the league's pickups cover (POSITION_SCALE has one entry per position with pickups)
  var POSITION_KEYS = ['ALL','QB','RB','WR','TE','K','D/ST'].filter(function(p){ return POSITION_SCALE[p]; });

  var currentFilter = 'career';
  var currentPosition = 'ALL';
  var waiverChart = null;

  function renderWaiverPills() {
    var el = document.getElementById('waiver-pills');
    var keys = ['career'].concat(PAGE_SEASONS.map(String));
    var html = '';
    keys.forEach(function(k) {
      var label = k === 'career' ? 'Career' : seasonLabel(k);
      var swatch = SEASON_COLORS[k] ? ' year-swatch-btn" style="--swatch-color:' + SEASON_COLORS[k] + ';' : '';
      html += '<button class="heatmap-season-pill'+(k==='career'?' active':'')+swatch+'" onclick="setFilter(\''+k+'\', this)">'+label+'</button>';
    });
    el.innerHTML = html;

    var elPos = document.getElementById('waiver-position-pills');
    var htmlPos = '';
    POSITION_KEYS.forEach(function(p) {
      var label = p === 'ALL' ? 'All Positions' : p;
      var swatch = POSITION_COLORS[p] ? ' pos-swatch-btn" style="--swatch-color:' + POSITION_COLORS[p] + ';' : '';
      htmlPos += '<button class="heatmap-season-pill'+(p==='ALL'?' active':'')+swatch+'" onclick="setWaiverPosition(\''+p+'\', this)">'+label+'</button>';
    });
    elPos.innerHTML = htmlPos;
  }

  function setFilter(filterKey, btn) {
    currentFilter = filterKey;
    btn.parentElement.querySelectorAll('.heatmap-season-pill').forEach(function(p){ p.classList.remove('active'); });
    btn.classList.add('active');
    renderWaiverChart();
  }

  function setWaiverPosition(posKey, btn) {
    currentPosition = posKey;
    btn.parentElement.querySelectorAll('.heatmap-season-pill').forEach(function(p){ p.classList.remove('active'); });
    btn.classList.add('active');
    renderWaiverChart();
  }

  function renderWaiverChart() {
    var pool = (LEADERBOARD_FULL[currentFilter] || {})[currentPosition] || [];
    var rows = pool.slice().sort(function(a,b){ return b.z-a.z; });
    var scale = POSITION_SCALE[currentPosition];
    var colors = rows.map(function(d){ return gradientColor(d.z, scale.zMin, scale.zMax, true); });
    var bestLookup = (BEST_BY_MANAGER[currentFilter] && BEST_BY_MANAGER[currentFilter][currentPosition]) || {};

    // Sample-size axis dynamically fits THIS view's own max n, not a fixed
    // global max, so a thin slice (a handful of pickups) still fills the row
    // visibly instead of looking like a sliver.
    var maxN = Math.max.apply(null, rows.map(function(d){return d.n;}));
    var nAxisMax = Math.ceil(maxN * 1.15) || 1;

    if (waiverChart) { waiverChart.destroy(); }
    var ctx = document.getElementById('chart-waiver-value').getContext('2d');
    waiverChart = new Chart(ctx, {
      type: 'bar',
      data: {
        labels: rows.map(function(d){return d.m;}),
        datasets: [
          {
            label: 'Pickups',
            data: rows.map(function(d){return d.n;}),
            backgroundColor: 'rgba(150,140,120,0.22)',
            borderRadius: 4,
            barPercentage: 0.9,
            categoryPercentage: 0.8,
            xAxisID: 'xN',
            order: 2,
          },
          {
            label: 'PPW',
            data: rows.map(function(d){return d.ppw;}),
            backgroundColor: colors,
            borderRadius: 4,
            barPercentage: 0.4,
            categoryPercentage: 0.8,
            xAxisID: 'x',
            order: 1,
          }
        ]
      },
      options: {
        indexAxis: 'y',
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: 'index', axis: 'y', intersect: false },
        plugins: {
          legend: { display:false },
          tooltip: {
            mode: 'index',
            axis: 'y',
            intersect: false,
            filter: function(item) { return item.datasetIndex === 1; },
            callbacks: {
              title: function(items) { return items[0].label; },
              label: function(ctx) {
                var d = rows[ctx.dataIndex];
                var lines = ['PPW: '+d.ppw.toFixed(2), 'Position-adjusted value: '+d.z.toFixed(3), 'Pickups: '+d.n];
                var best = bestLookup[d.m];
                if (best) {
                  var tzSign = best.tz >= 0 ? '+' : '';
                  lines.push('Best pickup: '+best.p+' ('+tzSign+best.tz.toFixed(2)+' over '+best.wk+' wk'+(best.wk===1?'':'s')+')');
                }
                return lines;
              }
            }
          }
        },
        scales: {
          x: { min:scale.ppwMin, max:scale.ppwMax, position:'bottom', title:{display:true,text:'Points per week rostered (PPW)'} },
          xN: {
            min:0, max:nAxisMax, position:'top', display:true,
            grid: { display:false },
            title: { display:true, text:'Number of pickups (sample size)', color:'#9a9078', font:{size:11} },
            ticks: { color:'#9a9078' }
          },
          y: { ticks:{ autoSkip:false, font:{size:12} } }
        }
      }
    });
  }

  /* ── Green-only sequential gradient: for "these are all winners" lists,
     where red would wrongly imply some picks were bad. Darkest green = best,
     lighter green/gold = still great, just relatively less so within the group. ── */
  function greenScale(value, min, max) {
    var p = max===min ? 1 : (value - min) / (max - min); // 1 = best, 0 = weakest of the group
    var LIGHT = [190,180,90];  // muted gold-green, weakest in a great group
    var DEEP  = [70,120,70];   // deep green, the best
    var r = lerp(LIGHT[0],DEEP[0],p), g = lerp(LIGHT[1],DEEP[1],p), b = lerp(LIGHT[2],DEEP[2],p);
    return 'rgba('+r+','+g+','+b+',0.9)';
  }

  /* ── Generic column sort helper ── */
  function sortRows(rows, key, type, dir) {
    var sorted = rows.slice().sort(function(a,b){
      var av = a[key], bv = b[key];
      if (type === 'text') { av = (av||'').toLowerCase(); bv = (bv||'').toLowerCase(); }
      if (av < bv) return dir === 'asc' ? -1 : 1;
      if (av > bv) return dir === 'asc' ? 1 : -1;
      return 0;
    });
    return sorted;
  }

  function wireSortableHeaders(tableId, renderFn, state) {
    document.querySelectorAll('#'+tableId+' th.sortable').forEach(function(th){
      th.addEventListener('click', function(){
        var key = th.getAttribute('data-key');
        var type = th.getAttribute('data-type') || 'number';
        if (state.key === key) {
          state.dir = state.dir === 'asc' ? 'desc' : 'asc';
        } else {
          state.key = key;
          state.type = type;
          state.dir = 'desc';
        }
        document.querySelectorAll('#'+tableId+' th.sortable').forEach(function(h){
          h.classList.remove('sorted-asc','sorted-desc');
        });
        th.classList.add(state.dir === 'asc' ? 'sorted-asc' : 'sorted-desc');
        renderFn();
      });
    });
  }

  // Per-stint waiver/FA data (Season, Manager, Type W/F, Start Week,
  // Weeks Rostered, Total Z, Player, Position) from waiver_stints_full.csv,
  // via generate_waiver_stint_data.py. Verified to reproduce CONTESTED_SPLIT's
  // wvZ/faZ (weeks-weighted mean of Avg_Z) to within rounding before being
  // trusted for the season toggle and weeks-rostered filter below.
  // Global range of individual stint Total_Z, computed directly from
  // WAIVER_STINTS below (min -10.223, max 11.233) -- used as fixed bounds
  // for the red-to-green gradient on individual pickups, same convention
  // as EFFICIENCY_GLOBAL_MIN/MAX and BEST_TOTALZ_MIN/MAX elsewhere on the
  // site, so a given shade always means the same magnitude everywhere.

  var splitSortState = { key: 'wvZ', type: 'number', dir: 'desc' };

  function renderSplitTable() {
    var tbody = document.querySelector('#split-table tbody');
    var zVals = [];
    CONTESTED_SPLIT.forEach(function(d){ if (d.faZ !== null) zVals.push(d.faZ); if (d.wvZ !== null) zVals.push(d.wvZ); });
    var minZ = Math.min.apply(null, zVals), maxZ = Math.max.apply(null, zVals);

    var rows = sortRows(CONTESTED_SPLIT, splitSortState.key, splitSortState.type, splitSortState.dir);
    var html = '';
    rows.forEach(function(d, i){
      // a manager with no pickups of one kind has no numbers for it (a dash)
      var none = '<td>&ndash;</td>';
      var zCell = function(z){ return z === null ? none : '<td><span style="background:'+gradientColor(z, minZ, maxZ, true)+';color:#fff;padding:0.15rem 0.5rem;border-radius:4px;font-weight:700;">'+z.toFixed(3)+'</span></td>'; };
      var ppwCell = function(v){ return v === null ? none : '<td class="val-bold">'+v.toFixed(2)+'</td>'; };
      html += '<tr>'
        +'<td class="wv-rank">'+(i+1)+'</td>'
        +'<td style="font-weight:600;color:var(--palm)">'+d.m+'</td>'
        +ppwCell(d.careerPpw)
        +zCell(d.wvZ)
        +ppwCell(d.wvPpw)
        +'<td>'+(d.wvN || 0)+'</td>'
        +zCell(d.faZ)
        +ppwCell(d.faPpw)
        +'<td>'+(d.faN || 0)+'</td>'
        +'</tr>';
    });
    tbody.innerHTML = html;
  }

  // Total PAV by manager: sum of Total_Z across every qualifying stint,
  // split waiver vs. FA, filterable by season, position, and by a minimum
  // weeks-rostered threshold. Uses WAIVER_STINTS (verified above).
  var totalValueChart = null;
  var totalValueChartRows = [];
  var totalValueLastClicked = null;
  var totalValueSeasonFilter = 'career';
  var totalValueMinWeeks = 0;
  var totalValuePosFilter = 'ALL';

  function renderTotalValueFilters() {
    var seasonEl = document.getElementById('total-value-season-pills');
    var seasons = PAGE_SEASONS.slice();
    var html = '<button class="heatmap-season-pill active" onclick="setTotalValueSeason(\'career\', this)">Career</button>';
    seasons.forEach(function(s){
      var swatch = SEASON_COLORS[s] ? ' year-swatch-btn" style="--swatch-color:' + SEASON_COLORS[s] + ';' : '';
      html += '<button class="heatmap-season-pill'+swatch+'" onclick="setTotalValueSeason('+s+', this)">'+seasonLabel(s)+'</button>';
    });
    seasonEl.innerHTML = html;

    var weeksEl = document.getElementById('total-value-weeks-pills');
    var buckets = [[0,'All Pickups'], [2,'2+ Weeks Rostered'], [4,'4+ Weeks Rostered'], [8,'8+ Weeks Rostered']];
    weeksEl.innerHTML = buckets.map(function(b){
      return '<button class="heatmap-season-pill'+(b[0]===0?' active':'')+'" onclick="setTotalValueMinWeeks('+b[0]+', this)">'+b[1]+'</button>';
    }).join('');

    var posEl = document.getElementById('total-value-pos-pills');
    posEl.innerHTML = POSITION_KEYS.map(function(p){
      var label = p === 'ALL' ? 'All Positions' : p;
      var swatch = POSITION_COLORS[p] ? ' pos-swatch-btn" style="--swatch-color:' + POSITION_COLORS[p] + ';' : '';
      return '<button class="heatmap-season-pill'+(p==='ALL'?' active':'')+swatch+'" onclick="setTotalValuePosition(\''+p+'\', this)">'+label+'</button>';
    }).join('');
  }

  function setTotalValueSeason(season, btn) {
    totalValueSeasonFilter = season;
    btn.parentElement.querySelectorAll('.heatmap-season-pill').forEach(function(p){ p.classList.remove('active'); });
    btn.classList.add('active');
    renderTotalValueChart();
    if (totalValueLastClicked !== null) renderTotalValueDetail(totalValueLastClicked);
  }

  function setTotalValueMinWeeks(minWeeks, btn) {
    totalValueMinWeeks = minWeeks;
    btn.parentElement.querySelectorAll('.heatmap-season-pill').forEach(function(p){ p.classList.remove('active'); });
    btn.classList.add('active');
    renderTotalValueChart();
    if (totalValueLastClicked !== null) renderTotalValueDetail(totalValueLastClicked);
  }

  function setTotalValuePosition(pos, btn) {
    totalValuePosFilter = pos;
    btn.parentElement.querySelectorAll('.heatmap-season-pill').forEach(function(p){ p.classList.remove('active'); });
    btn.classList.add('active');
    renderTotalValueChart();
    if (totalValueLastClicked !== null) renderTotalValueDetail(totalValueLastClicked);
  }

  // Same color/label conventions as the rest of the page's SEASON_COLORS
  // map, defined further up this file -- reused here rather than
  // redeclared.

  function renderTotalValueChart() {
    var pool = WAIVER_STINTS.filter(function(r){
      if (totalValueSeasonFilter !== 'career' && r.s !== totalValueSeasonFilter) return false;
      if (r.wk < totalValueMinWeeks) return false;
      if (totalValuePosFilter !== 'ALL' && r.pos !== totalValuePosFilter) return false;
      return true;
    });

    var byManager = {};
    pool.forEach(function(r){
      if (!byManager[r.m]) byManager[r.m] = { waiverTotal: 0, faTotal: 0 };
      if (r.t === 'W') byManager[r.m].waiverTotal += r.z;
      else byManager[r.m].faTotal += r.z;
    });

    var rows = Object.keys(byManager).map(function(m){
      return { m: m, waiverTotal: byManager[m].waiverTotal, faTotal: byManager[m].faTotal };
    });
    rows.sort(function(a,b){ return (b.waiverTotal + b.faTotal) - (a.waiverTotal + a.faTotal); });
    totalValueChartRows = rows; // so onClick can map a clicked index back to a manager name

    if (totalValueChart) { totalValueChart.destroy(); }
    var ctx = document.getElementById('chart-total-value').getContext('2d');
    totalValueChart = new Chart(ctx, {
      type: 'bar',
      data: {
        labels: rows.map(function(d){ return d.m; }),
        datasets: [
          {
            label: 'Waiver (contested)',
            data: rows.map(function(d){ return +d.waiverTotal.toFixed(2); }),
            backgroundColor: 'rgba(74,127,168,0.85)',
            borderRadius: 3,
          },
          {
            label: 'Free Agent (uncontested)',
            data: rows.map(function(d){ return +d.faTotal.toFixed(2); }),
            backgroundColor: 'rgba(154,144,128,0.85)',
            borderRadius: 3,
          }
        ]
      },
      options: {
        indexAxis: 'y',
        responsive: true,
        maintainAspectRatio: false,
        onHover: function(event, elements) {
          event.native.target.style.cursor = elements.length ? 'pointer' : 'default';
        },
        onClick: function(event, elements) {
          if (!elements.length) return;
          var mgrIndex = elements[0].index;
          totalValueLastClicked = totalValueChartRows[mgrIndex].m;
          renderTotalValueDetail(totalValueLastClicked);
        },
        plugins: {
          legend: { position: 'top', align: 'end', labels: { boxWidth: 12, padding: 14 } },
          tooltip: {
            callbacks: {
              footer: function(items) {
                var total = items.reduce(function(s, it){ return s + it.parsed.x; }, 0);
                return 'Combined total: ' + (total >= 0 ? '+' : '') + total.toFixed(2);
              }
            }
          }
        },
        scales: {
          x: { stacked: true, title: { display: true, text: 'Total position-adjusted value (sum of z-scores)' } },
          y: { stacked: true, ticks: { autoSkip: false, font: { size: 12 } } }
        }
      }
    });
  }

  // Detail panel for a clicked manager bar: their top pickups, respecting
  // the currently active season/weeks-rostered/position filters so it
  // always matches what the chart is actually showing.
  function renderTotalValueDetail(manager) {
    var panel = document.getElementById('total-value-detail');
    var pool = WAIVER_STINTS.filter(function(r){
      if (r.m !== manager) return false;
      if (totalValueSeasonFilter !== 'career' && r.s !== totalValueSeasonFilter) return false;
      if (r.wk < totalValueMinWeeks) return false;
      if (totalValuePosFilter !== 'ALL' && r.pos !== totalValuePosFilter) return false;
      return true;
    });
    pool.sort(function(a,b){ return b.z - a.z; });
    var top = pool.slice(0, 10);

    var seasonLabel = totalValueSeasonFilter === 'career'
      ? '<span style="color:var(--muted);font-weight:600;">Career</span>'
      : '<span class="season-pill" style="background:'+(SEASON_COLORS[totalValueSeasonFilter]||'var(--muted)')+';font-size:0.8rem;">'+totalValueSeasonFilter+'</span>';

    var rowsHtml = top.map(function(r, i){
      var typeClass = r.t === 'W' ? 'type-waiver' : 'type-freeagent';
      var typeLabel = r.t === 'W' ? 'Waiver' : 'Free Agent';
      var zBg = gradientColor(r.z, WAIVER_Z_GLOBAL_MIN, WAIVER_Z_GLOBAL_MAX, true);
      var seasonCell = totalValueSeasonFilter === 'career'
        ? '<td><span class="season-pill" style="background:'+(SEASON_COLORS[r.s]||'var(--muted)')+';">'+r.s+'</span></td>'
        : '';
      return '<tr>'
        + '<td class="wv-rank">'+(i+1)+'</td>'
        + seasonCell
        + '<td style="font-weight:600;color:var(--palm);">'+r.p+'</td>'
        + '<td><span class="pos-badge '+posBadgeClass(r.pos)+'">'+r.pos+'</span></td>'
        + '<td>Wk '+r.sw+'</td>'
        + '<td><span class="type-badge '+typeClass+'">'+typeLabel+'</span></td>'
        + '<td>'+r.wk+'</td>'
        + '<td>'+r.ppw.toFixed(2)+'</td>'
        + '<td><span style="background:'+zBg+';color:#fff;padding:0.12rem 0.45rem;border-radius:4px;font-weight:700;">'+(r.z>=0?'+':'')+r.z.toFixed(2)+'</span></td>'
        + '</tr>';
    }).join('');

    var seasonCol = totalValueSeasonFilter === 'career' ? '<th>Season</th>' : '';
    var countNote = pool.length > 10
      ? 'Showing the top 10 of ' + pool.length + ' pickups.'
      : 'All ' + pool.length + ' pickup' + (pool.length === 1 ? '' : 's') + ' from this manager' + (pool.length < 10 ? ' (fewer than 10 exist for this filter combination).' : '.');

    panel.innerHTML =
      '<div class="detail-panel-label">Manager Details</div>'
      + '<div style="display:flex;align-items:center;gap:0.5rem;margin-bottom:0.5rem;">'
        + '<span style="font-family:var(--font-display);font-weight:800;font-size:1.05rem;color:var(--palm);">'+manager+'</span>'
        + seasonLabel
      + '</div>'
      + (pool.length === 0
          ? '<p style="font-size:0.85rem;color:var(--muted);">No pickups match this filter combination for this manager.</p>'
          : '<div class="table-wrap" style="overflow-x:auto;padding:0;">'
            + '<table class="wv-table"><thead><tr><th>Rank</th>'+seasonCol+'<th>Player</th><th>Pos</th><th>Start Week</th><th>Type</th><th>Weeks Rostered</th><th>PPW</th><th>Total Value</th></tr></thead>'
            + '<tbody>'+rowsHtml+'</tbody></table></div>'
            + '<p class="metric-note" style="margin-top:0.6rem;">'+countNote+'</p>');
    panel.style.display = 'block';

    panel.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    panel.classList.remove('flash');
    void panel.offsetWidth;
    panel.classList.add('flash');
  }

  renderTotalValueFilters();

  // Waiver Upside (Positive-Only): same WAIVER_STINTS pool as the chart
  // above, but every stint with Total_Z <= 0 is dropped before summing by
  // manager instead of being netted in. Feeds the win attribution model on
  // extra-analytics.html, where only positive waiver value counts.
  var upsideChart = null;
  var upsideSeasonFilter = 'career';
  var upsidePosFilter = 'ALL';

  // Fixed across every season x position combination so a bar's color means
  // the same thing everywhere, whether it's Career/ALL or a thin slice like
  // 2021/K. Computed directly from WAIVER_STINTS, positive stints only.

  function renderUpsideFilters() {
    var seasonEl = document.getElementById('upside-season-pills');
    var seasons = PAGE_SEASONS.slice();
    var html = '<button class="heatmap-season-pill active" onclick="setUpsideSeason(\'career\', this)">Career</button>';
    seasons.forEach(function(s){
      var swatch = SEASON_COLORS[s] ? ' year-swatch-btn" style="--swatch-color:' + SEASON_COLORS[s] + ';' : '';
      html += '<button class="heatmap-season-pill'+swatch+'" onclick="setUpsideSeason('+s+', this)">'+seasonLabel(s)+'</button>';
    });
    seasonEl.innerHTML = html;

    var posEl = document.getElementById('upside-position-pills');
    posEl.innerHTML = POSITION_KEYS.map(function(p){
      var label = p === 'ALL' ? 'All Positions' : p;
      var swatch = POSITION_COLORS[p] ? ' pos-swatch-btn" style="--swatch-color:' + POSITION_COLORS[p] + ';' : '';
      return '<button class="heatmap-season-pill'+(p==='ALL'?' active':'')+swatch+'" onclick="setUpsidePosition(\''+p+'\', this)">'+label+'</button>';
    }).join('');
  }

  function setUpsideSeason(season, btn) {
    upsideSeasonFilter = season;
    btn.parentElement.querySelectorAll('.heatmap-season-pill').forEach(function(p){ p.classList.remove('active'); });
    btn.classList.add('active');
    renderUpsideChart();
    if (upsideLastClicked !== null) { upsidePage = 1; renderUpsideDetail(upsideLastClicked); }
  }

  function setUpsidePosition(pos, btn) {
    upsidePosFilter = pos;
    btn.parentElement.querySelectorAll('.heatmap-season-pill').forEach(function(p){ p.classList.remove('active'); });
    btn.classList.add('active');
    renderUpsideChart();
    if (upsideLastClicked !== null) { upsidePage = 1; renderUpsideDetail(upsideLastClicked); }
  }

  function renderUpsideChart() {
    var pool = WAIVER_STINTS.filter(function(r){
      if (upsideSeasonFilter !== 'career' && r.s !== upsideSeasonFilter) return false;
      if (upsidePosFilter !== 'ALL' && r.pos !== upsidePosFilter) return false;
      return r.z > 0;
    });

    var byManager = {};
    pool.forEach(function(r){
      byManager[r.m] = (byManager[r.m] || 0) + r.z;
    });

    var rows = Object.keys(byManager).map(function(m){ return { m: m, v: byManager[m] }; });
    rows.sort(function(a,b){ return b.v - a.v; });

    if (upsideChart) { upsideChart.destroy(); }
    var ctx = document.getElementById('chart-upside').getContext('2d');
    upsideChart = new Chart(ctx, {
      type: 'bar',
      data: {
        labels: rows.map(function(d){ return d.m; }),
        datasets: [{
          data: rows.map(function(d){ return +d.v.toFixed(2); }),
          backgroundColor: rows.map(function(d){ return greenScale(d.v, UPSIDE_MIN, UPSIDE_MAX); }),
          borderRadius: 3
        }]
      },
      options: {
        indexAxis: 'y',
        responsive: true,
        maintainAspectRatio: false,
        onHover: function(event, elements) {
          event.native.target.style.cursor = elements.length ? 'pointer' : 'default';
        },
        onClick: function(event, elements) {
          if (!elements.length) return;
          upsideLastClicked = rows[elements[0].index].m;
          upsidePage = 1;
          renderUpsideDetail(upsideLastClicked);
        },
        plugins: {
          legend: { display: false },
          tooltip: {
            callbacks: {
              label: function(item) { return 'Total value: +' + item.parsed.x.toFixed(2); }
            }
          }
        },
        scales: {
          x: { title: { display: true, text: 'Positive-only total value (sum of z-scores)' } },
          y: { ticks: { autoSkip: false, font: { size: 12 } } }
        }
      }
    });
  }

  // Detail panel for a clicked manager bar: every one of their positive-value
  // pickups within the current season/position filter, paginated 10 at a
  // time (rather than truncated to a top-N) so the list runs all the way
  // down to the weakest qualifying pickup instead of just the highlights.
  var upsideLastClicked = null;
  var upsidePage = 1;
  var UPSIDE_PAGE_SIZE = 10;

  function renderUpsideDetail(manager) {
    var panel = document.getElementById('upside-detail');
    var pool = WAIVER_STINTS.filter(function(r){
      if (r.m !== manager) return false;
      if (upsideSeasonFilter !== 'career' && r.s !== upsideSeasonFilter) return false;
      if (upsidePosFilter !== 'ALL' && r.pos !== upsidePosFilter) return false;
      return r.z > 0;
    });
    pool.sort(function(a,b){ return b.z - a.z; });

    var totalPages = Math.max(1, Math.ceil(pool.length / UPSIDE_PAGE_SIZE));
    if (upsidePage > totalPages) upsidePage = totalPages;
    if (upsidePage < 1) upsidePage = 1;
    var start = (upsidePage - 1) * UPSIDE_PAGE_SIZE;
    var page = pool.slice(start, start + UPSIDE_PAGE_SIZE);

    var seasonLabel = upsideSeasonFilter === 'career'
      ? '<span style="color:var(--muted);font-weight:600;">Career</span>'
      : '<span class="season-pill" style="background:'+(SEASON_COLORS[upsideSeasonFilter]||'var(--muted)')+';font-size:0.8rem;">'+upsideSeasonFilter+'</span>';

    var rowsHtml = page.map(function(r, i){
      var typeClass = r.t === 'W' ? 'type-waiver' : 'type-freeagent';
      var typeLabel = r.t === 'W' ? 'Waiver' : 'Free Agent';
      var zBg = greenScale(r.z, BEST_TOTALZ_MIN, BEST_TOTALZ_MAX);
      var seasonCell = upsideSeasonFilter === 'career'
        ? '<td><span class="season-pill" style="background:'+(SEASON_COLORS[r.s]||'var(--muted)')+';">'+r.s+'</span></td>'
        : '';
      return '<tr>'
        + '<td class="wv-rank">'+(start + i + 1)+'</td>'
        + seasonCell
        + '<td style="font-weight:600;color:var(--palm);">'+r.p+'</td>'
        + '<td><span class="pos-badge '+posBadgeClass(r.pos)+'">'+r.pos+'</span></td>'
        + '<td>Wk '+r.sw+'</td>'
        + '<td><span class="type-badge '+typeClass+'">'+typeLabel+'</span></td>'
        + '<td>'+r.wk+'</td>'
        + '<td>'+r.ppw.toFixed(2)+'</td>'
        + '<td><span style="background:'+zBg+';color:#fff;padding:0.12rem 0.45rem;border-radius:4px;font-weight:700;">+'+r.z.toFixed(2)+'</span></td>'
        + '</tr>';
    }).join('');

    var seasonCol = upsideSeasonFilter === 'career' ? '<th>Season</th>' : '';

    panel.innerHTML =
      '<div class="detail-panel-label">Manager Details</div>'
      + '<div style="display:flex;align-items:center;gap:0.5rem;margin-bottom:0.5rem;">'
        + '<span style="font-family:var(--font-display);font-weight:800;font-size:1.05rem;color:var(--palm);">'+manager+'</span>'
        + seasonLabel
      + '</div>'
      + (pool.length === 0
          ? '<p style="font-size:0.85rem;color:var(--muted);">No positive-value pickups match this filter combination for this manager.</p>'
          : '<div class="table-wrap" style="overflow-x:auto;padding:0;">'
            + '<table class="wv-table"><thead><tr><th>Rank</th>'+seasonCol+'<th>Player</th><th>Pos</th><th>Start Week</th><th>Type</th><th>Weeks Rostered</th><th>PPW</th><th>Total Value</th></tr></thead>'
            + '<tbody>'+rowsHtml+'</tbody></table></div>'
            + '<div class="upside-pagination">'
              + '<button class="upside-page-btn" onclick="upsidePrevPage()" '+(upsidePage<=1?'disabled':'')+'>&#8592; Prev</button>'
              + '<span class="upside-page-info">Page '+upsidePage+' of '+totalPages+' ('+pool.length+' pickup'+(pool.length===1?'':'s')+')</span>'
              + '<button class="upside-page-btn" onclick="upsideNextPage()" '+(upsidePage>=totalPages?'disabled':'')+'>Next &#8594;</button>'
            + '</div>');
    panel.style.display = 'block';

    panel.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    panel.classList.remove('flash');
    void panel.offsetWidth;
    panel.classList.add('flash');
  }

  function upsidePrevPage() {
    if (upsidePage <= 1 || !upsideLastClicked) return;
    upsidePage -= 1;
    renderUpsideDetail(upsideLastClicked);
  }

  function upsideNextPage() {
    if (!upsideLastClicked) return;
    upsidePage += 1;
    renderUpsideDetail(upsideLastClicked);
  }

  // Value by week of the season: volume (bars, split waiver/FA) and
  // average per-pickup value (line) for every pickup, grouped by the week
  // it was added (Start_Week). Season-filterable, all managers combined --
  // this is about league-wide timing patterns, not any one manager.
  var weekValueChart = null;
  var weekValueSeasonFilter = 'career';
  var weekValueMinWeeks = 0;
  var weekValuePosFilter = 'ALL';
  var weekValueLastClicked = null;

  function renderWeekValueFilters() {
    var el = document.getElementById('week-value-season-pills');
    var seasons = PAGE_SEASONS.slice();
    var html = '<button class="heatmap-season-pill active" onclick="setWeekValueSeason(\'career\', this)">Career</button>';
    seasons.forEach(function(s){
      var swatch = SEASON_COLORS[s] ? ' year-swatch-btn" style="--swatch-color:' + SEASON_COLORS[s] + ';' : '';
      html += '<button class="heatmap-season-pill'+swatch+'" onclick="setWeekValueSeason('+s+', this)">'+seasonLabel(s)+'</button>';
    });
    el.innerHTML = html;

    var weeksEl = document.getElementById('week-value-weeks-pills');
    var buckets = [[0,'All Pickups'], [2,'2+ Weeks Rostered'], [4,'4+ Weeks Rostered'], [8,'8+ Weeks Rostered']];
    weeksEl.innerHTML = buckets.map(function(b){
      return '<button class="heatmap-season-pill'+(b[0]===0?' active':'')+'" onclick="setWeekValueMinWeeks('+b[0]+', this)">'+b[1]+'</button>';
    }).join('');

    var posEl = document.getElementById('week-value-pos-pills');
    posEl.innerHTML = POSITION_KEYS.map(function(p){
      var label = p === 'ALL' ? 'All Positions' : p;
      var swatch = POSITION_COLORS[p] ? ' pos-swatch-btn" style="--swatch-color:' + POSITION_COLORS[p] + ';' : '';
      return '<button class="heatmap-season-pill'+(p==='ALL'?' active':'')+swatch+'" onclick="setWeekValuePosition(\''+p+'\', this)">'+label+'</button>';
    }).join('');
  }

  function setWeekValueSeason(season, btn) {
    weekValueSeasonFilter = season;
    btn.parentElement.querySelectorAll('.heatmap-season-pill').forEach(function(p){ p.classList.remove('active'); });
    btn.classList.add('active');
    renderWeekValueChart();
    if (weekValueLastClicked !== null) renderWeekValueDetail(weekValueLastClicked);
  }

  function setWeekValueMinWeeks(minWeeks, btn) {
    weekValueMinWeeks = minWeeks;
    btn.parentElement.querySelectorAll('.heatmap-season-pill').forEach(function(p){ p.classList.remove('active'); });
    btn.classList.add('active');
    renderWeekValueChart();
    if (weekValueLastClicked !== null) renderWeekValueDetail(weekValueLastClicked);
  }

  function setWeekValuePosition(pos, btn) {
    weekValuePosFilter = pos;
    btn.parentElement.querySelectorAll('.heatmap-season-pill').forEach(function(p){ p.classList.remove('active'); });
    btn.classList.add('active');
    renderWeekValueChart();
    if (weekValueLastClicked !== null) renderWeekValueDetail(weekValueLastClicked);
  }

  function renderWeekValueChart() {
    var pool = WAIVER_STINTS.filter(function(r){
      if (weekValueSeasonFilter !== 'career' && r.s !== weekValueSeasonFilter) return false;
      if (r.wk < weekValueMinWeeks) return false;
      if (weekValuePosFilter !== 'ALL' && r.pos !== weekValuePosFilter) return false;
      return true;
    });

    var maxWeek = 17;
    var byWeek = {};
    for (var w = 1; w <= maxWeek; w++) byWeek[w] = { waiverN: 0, faN: 0, zSum: 0, n: 0 };
    pool.forEach(function(r){
      var b = byWeek[r.sw];
      if (!b) return;
      if (r.t === 'W') b.waiverN++; else b.faN++;
      b.zSum += r.z;
      b.n++;
    });

    var labels = [], waiverCounts = [], faCounts = [], avgValues = [];
    for (var wk = 1; wk <= maxWeek; wk++) {
      var b = byWeek[wk];
      labels.push('Wk ' + wk);
      waiverCounts.push(b.waiverN);
      faCounts.push(b.faN);
      avgValues.push(b.n ? +(b.zSum / b.n).toFixed(3) : null);
    }

    if (weekValueChart) { weekValueChart.destroy(); }
    var ctx = document.getElementById('chart-week-value').getContext('2d');
    weekValueChart = new Chart(ctx, {
      data: {
        labels: labels,
        datasets: [
          {
            type: 'bar',
            label: 'Waiver adds',
            data: waiverCounts,
            backgroundColor: 'rgba(74,127,168,0.85)',
            yAxisID: 'yCount',
            stack: 'vol',
            order: 2,
          },
          {
            type: 'bar',
            label: 'FA adds',
            data: faCounts,
            backgroundColor: 'rgba(154,144,128,0.85)',
            yAxisID: 'yCount',
            stack: 'vol',
            order: 2,
          },
          {
            type: 'line',
            label: 'Avg value per pickup',
            data: avgValues,
            borderColor: '#c0623a',
            backgroundColor: 'rgba(192,98,58,0.1)',
            borderWidth: 2.5,
            pointRadius: 3,
            pointBackgroundColor: '#c0623a',
            tension: 0.3,
            spanGaps: true,
            yAxisID: 'yValue',
            order: 1,
          }
        ]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: 'index', intersect: false },
        onHover: function(event, elements) {
          event.native.target.style.cursor = elements.length ? 'pointer' : 'default';
        },
        onClick: function(event, elements) {
          if (!elements.length) return;
          var weekIndex = elements[0].index; // 0-based; week number is index+1
          weekValueLastClicked = weekIndex + 1;
          renderWeekValueDetail(weekValueLastClicked);
        },
        plugins: {
          legend: { position: 'top', align: 'end', labels: { boxWidth: 12, padding: 14 } }
        },
        scales: {
          x: { grid: { display: false } },
          yCount: {
            position: 'left', stacked: true,
            title: { display: true, text: weekValueMinWeeks > 0 ? 'Pickups added (' + weekValueMinWeeks + '+ weeks rostered)' : 'Pickups added' },
            ticks: { precision: 0 }
          },
          yValue: {
            position: 'right',
            title: { display: true, text: 'Avg position-adjusted value' },
            grid: { drawOnChartArea: false }
          }
        }
      }
    });
  }

  renderWeekValueFilters();

  // Detail panel for a clicked week bar: top pickups from that week,
  // respecting the currently active season and weeks-rostered filters so
  // it always matches what the chart is actually showing.
  function renderWeekValueDetail(week) {
    var panel = document.getElementById('week-value-detail');
    var pool = WAIVER_STINTS.filter(function(r){
      if (r.sw !== week) return false;
      if (weekValueSeasonFilter !== 'career' && r.s !== weekValueSeasonFilter) return false;
      if (r.wk < weekValueMinWeeks) return false;
      if (weekValuePosFilter !== 'ALL' && r.pos !== weekValuePosFilter) return false;
      return true;
    });
    pool.sort(function(a,b){ return b.z - a.z; });
    var top = pool.slice(0, 10);

    var seasonLabel = weekValueSeasonFilter === 'career'
      ? '<span style="color:var(--muted);font-weight:600;">Career</span>'
      : '<span class="season-pill" style="background:'+(SEASON_COLORS[weekValueSeasonFilter]||'var(--muted)')+';font-size:0.8rem;">'+weekValueSeasonFilter+'</span>';

    var rowsHtml = top.map(function(r, i){
      var typeClass = r.t === 'W' ? 'type-waiver' : 'type-freeagent';
      var typeLabel = r.t === 'W' ? 'Waiver' : 'Free Agent';
      var zBg = gradientColor(r.z, WAIVER_Z_GLOBAL_MIN, WAIVER_Z_GLOBAL_MAX, true);
      var seasonCell = weekValueSeasonFilter === 'career'
        ? '<span class="season-pill" style="background:'+(SEASON_COLORS[r.s]||'var(--muted)')+';">'+r.s+'</span>'
        : '';
      return '<tr>'
        + '<td class="wv-rank">'+(i+1)+'</td>'
        + (weekValueSeasonFilter === 'career' ? '<td>'+seasonCell+'</td>' : '')
        + '<td style="font-weight:600;color:var(--palm);">'+r.p+'</td>'
        + '<td><span class="pos-badge '+posBadgeClass(r.pos)+'">'+r.pos+'</span></td>'
        + '<td style="font-weight:600;color:var(--palm);">'+r.m+'</td>'
        + '<td><span class="type-badge '+typeClass+'">'+typeLabel+'</span></td>'
        + '<td>'+r.wk+'</td>'
        + '<td>'+r.ppw.toFixed(2)+'</td>'
        + '<td><span style="background:'+zBg+';color:#fff;padding:0.12rem 0.45rem;border-radius:4px;font-weight:700;">'+(r.z>=0?'+':'')+r.z.toFixed(2)+'</span></td>'
        + '</tr>';
    }).join('');

    var seasonCol = weekValueSeasonFilter === 'career' ? '<th>Season</th>' : '';
    var countNote = pool.length > 10
      ? 'Showing the top 10 of ' + pool.length + ' pickups.'
      : 'All ' + pool.length + ' pickup' + (pool.length === 1 ? '' : 's') + ' from this week' + (pool.length < 10 ? ' (fewer than 10 exist for this filter combination).' : '.');

    panel.innerHTML =
      '<div class="detail-panel-label">Week Details</div>'
      + '<div style="display:flex;align-items:center;gap:0.5rem;margin-bottom:0.5rem;">'
        + '<span style="font-family:var(--font-display);font-weight:800;font-size:1.05rem;color:var(--palm);">Week '+week+'</span>'
        + seasonLabel
      + '</div>'
      + (pool.length === 0
          ? '<p style="font-size:0.85rem;color:var(--muted);">No pickups match this filter combination for this week.</p>'
          : '<div class="table-wrap" style="overflow-x:auto;padding:0;">'
            + '<table class="wv-table"><thead><tr><th>Rank</th>'+seasonCol+'<th>Player</th><th>Pos</th><th>Manager</th><th>Type</th><th>Weeks Rostered</th><th>PPW</th><th>Total Value</th></tr></thead>'
            + '<tbody>'+rowsHtml+'</tbody></table></div>'
            + '<p class="metric-note" style="margin-top:0.6rem;">'+countNote+'</p>');
    panel.style.display = 'block';

    panel.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    panel.classList.remove('flash');
    void panel.offsetWidth;
    panel.classList.add('flash');
  }

  // Fixed across every season x position combination, so the same color always
  // means the same magnitude, whether you're looking at Career/ALL or a thin
  // slice like 2021/K. Only pickups with positive value over replacement are
  // shown at all, so this range is entirely non-negative.
  var bestFilter = 'career';
  var bestPosition = 'ALL';
  var bestSortState = { key: 'avgz', type: 'number', dir: 'desc' };

  function renderBestPills() {
    var el = document.getElementById('best-pills');
    var keys = ['career'].concat(PAGE_SEASONS.map(String));
    var html = '';
    keys.forEach(function(k) {
      var label = k === 'career' ? 'Career' : seasonLabel(k);
      var swatch = SEASON_COLORS[k] ? ' year-swatch-btn" style="--swatch-color:' + SEASON_COLORS[k] + ';' : '';
      html += '<button class="heatmap-season-pill'+(k==='career'?' active':'')+swatch+'" onclick="setBestFilter(\''+k+'\', this)">'+label+'</button>';
    });
    el.innerHTML = html;

    var elPos = document.getElementById('best-position-pills');
    var htmlPos = '';
    POSITION_KEYS.forEach(function(p) {
      var label = p === 'ALL' ? 'All Positions' : p;
      var swatch = POSITION_COLORS[p] ? ' pos-swatch-btn" style="--swatch-color:' + POSITION_COLORS[p] + ';' : '';
      htmlPos += '<button class="heatmap-season-pill'+(p==='ALL'?' active':'')+swatch+'" onclick="setBestPosition(\''+p+'\', this)">'+label+'</button>';
    });
    elPos.innerHTML = htmlPos;
  }

  function setBestFilter(filterKey, btn) {
    bestFilter = filterKey;
    btn.parentElement.querySelectorAll('.heatmap-season-pill').forEach(function(p){ p.classList.remove('active'); });
    btn.classList.add('active');
    renderBestTable();
  }

  function setBestPosition(posKey, btn) {
    bestPosition = posKey;
    btn.parentElement.querySelectorAll('.heatmap-season-pill').forEach(function(p){ p.classList.remove('active'); });
    btn.classList.add('active');
    renderBestTable();
  }

  function renderBestTable() {
    var tbody = document.querySelector('#best-table tbody');
    var data = (BEST_PICKUPS_BY_FILTER[bestFilter] || {})[bestPosition] || [];

    if (data.length === 0) {
      tbody.innerHTML = '<tr><td colspan="10" style="text-align:center;color:var(--muted);padding:1.5rem;">No qualifying pickups (minimum 3 weeks rostered, positive value over replacement) for this combination.</td></tr>';
      return;
    }

    var rows = sortRows(data, bestSortState.key, bestSortState.type, bestSortState.dir);
    var html = '';
    rows.forEach(function(d, i){
      var totalBg = greenScale(d.totalz, BEST_TOTALZ_MIN, BEST_TOTALZ_MAX);
      var avgBg = greenScale(d.avgz, BEST_AVGZ_MIN, BEST_AVGZ_MAX);
      var typeClass = d.type === 'WAIVER' ? 'type-waiver' : 'type-freeagent';
      var typeLabel = d.type === 'WAIVER' ? 'Waiver' : 'Free Agent';
      var seasonColor = SEASON_COLORS[d.s] || 'var(--muted)';
      html += '<tr>'
        +'<td class="wv-rank">'+(i+1)+'</td>'
        +'<td><span class="season-pill" style="background:'+seasonColor+';">'+d.s+'</span></td>'
        +'<td style="font-weight:600;color:var(--palm)">'+d.m+'</td>'
        +'<td>'+d.p+'</td>'
        +'<td><span class="pos-badge '+posBadgeClass(d.pos)+'">'+d.pos+'</span></td>'
        +'<td>'+d.wk+'</td>'
        +'<td class="val-bold">'+d.ppw.toFixed(2)+'</td>'
        +'<td><span style="background:'+totalBg+';color:#fff;padding:0.15rem 0.5rem;border-radius:4px;font-weight:700;">'+d.totalz.toFixed(2)+'</span></td>'
        +'<td><span style="background:'+avgBg+';color:#fff;padding:0.15rem 0.5rem;border-radius:4px;font-weight:700;">'+d.avgz.toFixed(3)+'</span></td>'
        +'<td><span class="type-badge '+typeClass+'">'+typeLabel+'</span></td>'
        +'</tr>';
    });
    tbody.innerHTML = html;
  }

  renderWaiverPills();
  renderWaiverChart();
  renderSplitTable();
  renderTotalValueChart();
  renderUpsideFilters();
  renderUpsideChart();
  renderWeekValueChart();
  wireSortableHeaders('split-table', renderSplitTable, splitSortState);
  renderBestPills();
  renderBestTable();
  wireSortableHeaders('best-table', renderBestTable, bestSortState);


  // the handlers the page's markup names (inline onclick, as on the Stage A page)
  Object.assign(window, { setBestFilter, setBestPosition, setFilter, setTotalValueMinWeeks, setTotalValuePosition, setTotalValueSeason, setUpsidePosition, setUpsideSeason, setWaiverPosition, setWeekValueMinWeeks, setWeekValuePosition, setWeekValueSeason, upsideNextPage, upsidePrevPage });
}

config().then(function (c) {
  cfg = c;
  mgr = managers(cfg);
  drawNav(cfg, 'waiver-value');
  drawSubnav(cfg, 'waiver-value');
  drawFooter(cfg);
  return load('data/v1/waiver-value.json');
}).then(function (M) {
  var D = waiverData(M, mgr.name);
  PAGE_SEASONS = D.PAGE_SEASONS; LEADERBOARD_FULL = D.LEADERBOARD_FULL; POSITION_SCALE = D.POSITION_SCALE;
  BEST_BY_MANAGER = D.BEST_BY_MANAGER; WAIVER_Z_GLOBAL_MIN = D.WAIVER_Z_GLOBAL_MIN; WAIVER_Z_GLOBAL_MAX = D.WAIVER_Z_GLOBAL_MAX;
  WAIVER_STINTS = D.WAIVER_STINTS; CONTESTED_SPLIT = D.CONTESTED_SPLIT; UPSIDE_MIN = D.UPSIDE_MIN; UPSIDE_MAX = D.UPSIDE_MAX;
  BEST_PICKUPS_BY_FILTER = D.BEST_PICKUPS_BY_FILTER; BEST_TOTALZ_MIN = D.BEST_TOTALZ_MIN; BEST_TOTALZ_MAX = D.BEST_TOTALZ_MAX;
  BEST_AVGZ_MIN = D.BEST_AVGZ_MIN; BEST_AVGZ_MAX = D.BEST_AVGZ_MAX;
  PAGE_LIVE_SEASON = cfg.live_season != null && PAGE_SEASONS.indexOf(cfg.live_season) !== -1 ? cfg.live_season : null;
  SEASON_COLORS = (cfg.theme && cfg.theme.season_colors) || {};
  methodNotes(cfg, mgr, PAGE_SEASONS);
  runPage();
}).catch(function (err) {
  console.error(err);
  var el = document.querySelector('#split-table tbody');
  if (el) el.innerHTML = '<tr><td colspan="9"><div class="data-state data-state-error">This page could not be loaded.</div></td></tr>';
});
