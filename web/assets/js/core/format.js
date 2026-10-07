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

/* Python's round(x, d): the float's exact decimal value, ties to even. The engine's Stage A views
   rounded with it, so pages that rebuild those numbers from a page model round the same way. */
export function pyRound(x, d) {
  if (x === null || x === undefined || !isFinite(x)) return x === undefined ? null : x;
  var neg = x < 0, parts = Math.abs(x).toFixed(100).split('.');
  var digits = parts[0] + parts[1].slice(0, d), rest = parts[1].slice(d);
  var up = rest[0] > '5' || (rest[0] === '5' && (/[1-9]/.test(rest.slice(1)) || Number(digits.slice(-1)) % 2 === 1));
  var n = (BigInt(digits) + (up ? 1n : 0n)).toString().padStart(d + 1, '0');
  var v = Number(d ? n.slice(0, n.length - d) + '.' + n.slice(n.length - d) : n);
  return neg ? -v : v;
}

/* numpy's floor(x * 10^d + 0.5) / 10^d, the engine's round_half_up */
export function halfUp(x, d) {
  if (x === null || x === undefined) return null;
  var f = Math.pow(10, d);
  return Math.floor(x * f + 0.5 + 1e-9) / f;
}
