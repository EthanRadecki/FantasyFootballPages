/* Number and record formats shared by every page. */

export function fixed(x, places) {
  return x == null || isNaN(x) ? '' : Number(x).toFixed(places);
}

/* +1.25 / -0.40 / 0.00 */
export function signed(x, places) {
  if (x == null || isNaN(x)) return '';
  var v = Number(x);
  return (v > 0 ? '+' : '') + v.toFixed(places);
}

/* 12-2, or 12-2-1 with a tie */
export function record(w, l, t) {
  return w + '-' + l + (t ? '-' + t : '');
}

/* "seven seasons", "12 seasons" */
var WORDS = ['zero', 'one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight', 'nine', 'ten',
             'eleven', 'twelve'];
export function count(n, noun) {
  return (n < WORDS.length ? WORDS[n] : String(n)) + ' ' + noun + (n === 1 ? '' : 's');
}

/* The league's seasons as "2020-2026" (or one year). */
export function seasonRange(cfg) {
  var s = (cfg.seasons || []).map(function (x) { return x.season; });
  if (!s.length) return '';
  return s.length === 1 ? String(s[0]) : s[0] + '-' + s[s.length - 1];
}
