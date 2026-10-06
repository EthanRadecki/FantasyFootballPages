/* Season and position colors and labels. Season colors and the live season come from config.json;
   position colors are the template's palette (the same on every league). */

export function seasonColor(cfg, season) {
  var c = (cfg.theme && cfg.theme.season_colors) || {};
  return c[String(season)] || null;
}

/* "2026 (live)" for the live season, else the year */
export function seasonLabel(cfg, season) {
  return String(season) + (cfg.live_season != null && String(season) === String(cfg.live_season) ? ' (live)' : '');
}

/* The league's seasons, oldest first. */
export function seasons(cfg) {
  return (cfg.seasons || []).map(function (s) { return s.season; });
}

export function seasonInfo(cfg, season) {
  return (cfg.seasons || []).find(function (s) { return s.season === Number(season); }) || null;
}

/* "#rrggbb" -> "r,g,b" / rgba() */
export function rgb(hex) {
  var h = String(hex || '').replace('#', '');
  if (h.length === 3) h = h.split('').map(function (c) { return c + c; }).join('');
  return [0, 2, 4].map(function (i) { return parseInt(h.slice(i, i + 2), 16) || 0; }).join(',');
}
export function rgba(hex, alpha) {
  return 'rgba(' + rgb(hex) + ',' + alpha + ')';
}

export var POSITION_ORDER = ['QB', 'RB', 'WR', 'TE', 'FLEX', 'K', 'D/ST'];

/* filter button swatches */
export var POSITION_SWATCH = { QB: '#983a3a', RB: '#4a7a4a', WR: '#3a6f98', TE: '#a07010', K: '#6a6460', 'D/ST': '#504840' };

/* chart fills (bubbles, timeline bars) */
export var POSITION_FILL = {
  RB: { fill: 'rgba(90,138,90,0.65)', border: 'rgba(90,138,90,1)' },
  WR: { fill: 'rgba(74,127,168,0.65)', border: 'rgba(74,127,168,1)' },
  QB: { fill: 'rgba(168,90,90,0.65)', border: 'rgba(168,90,90,1)' },
  TE: { fill: 'rgba(212,175,55,0.65)', border: 'rgba(212,175,55,1)' },
  K: { fill: 'rgba(156,148,156,0.65)', border: 'rgba(156,148,156,1)' },
  'D/ST': { fill: 'rgba(100,90,80,0.65)', border: 'rgba(100,90,80,1)' },
};

var BADGE = { RB: 'rb', WR: 'wr', QB: 'qb', TE: 'te', K: 'k', 'D/ST': 'dst' };
export function posBadge(pos) {
  return '<span class="pos-badge pos-' + (BADGE[pos] || 'k') + '">' + pos + '</span>';
}

/* positions in the template's order, then any others the data has */
export function orderPositions(list) {
  var have = Array.from(new Set(list));
  return POSITION_ORDER.filter(function (p) { return have.indexOf(p) !== -1; })
    .concat(have.filter(function (p) { return POSITION_ORDER.indexOf(p) === -1; }).sort());
}
