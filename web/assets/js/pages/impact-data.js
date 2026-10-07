/* Position Impact and Life Without Defense data: data/v1/position-impact.json and
   data/v1/dst-impact.json are the Stage A payloads (engine/publish/pages/impact.py, shape_payloads)
   keyed by manager key; the pages' scripts read them keyed by name. Every manager key, as a value
   or an object key, becomes the manager's display name; order is kept, so ties sort as on the
   Stage A pages. Pure: no DOM, so it can be checked on its own against the Stage A files. */

var KEY = /^m_[0-9a-f]{12}$/;

export function byName(model, name) {
  var walk = function (v) {
    if (Array.isArray(v)) return v.map(walk);
    if (v && typeof v === 'object') {
      var out = {};
      Object.keys(v).forEach(function (k) { if (k !== 'meta') out[KEY.test(k) ? name(k) : k] = walk(v[k]); });
      return out;
    }
    return typeof v === 'string' && KEY.test(v) ? name(v) : v;
  };
  return walk(model);
}

/* "1st", "2nd", "3rd", "4th" */
export function ordinal(n) {
  var s = ['th', 'st', 'nd', 'rd'], v = n % 100;
  return n + (s[(v - 20) % 10] || s[v] || s[0]);
}

/* positions grouped by the pick the draft analysis uses: [[1, ['QB', 'TE', 'K', 'D/ST']], [2, ['RB', 'WR']]] */
export function picksByNth(nth, positions) {
  var groups = {};
  positions.forEach(function (p) { if (nth[p]) (groups[nth[p]] = groups[nth[p]] || []).push(p); });
  return Object.keys(groups).map(Number).sort(function (a, b) { return a - b; }).map(function (n) { return [n, groups[n]]; });
}
