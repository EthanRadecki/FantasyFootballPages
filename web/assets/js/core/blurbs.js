/* Weekly rankings blurb formatter: plain text in, the page's highlight markup out.

   The JavaScript twin of engine/publish/blurbs.py (the rules are in its docstring); both are
   tested on the same cases (engine/tests/golden/blurbs/cases.json), so a blurb formats the same
   in the editor's preview and in the build. Change both together.

   vocab: data/v1/editor/vocab.json ({managers: [{key, color, names}], teams, players}). */

var POSITIONS = ['QB', 'RB', 'WR', 'TE'];
var ABBREVIATIONS = ['Jr', 'Sr', 'St', 'Mr', 'Mrs', 'Ms', 'Dr', 'vs', 'No', 'Jan', 'Feb', 'Aug', 'Sept', 'Oct',
                     'Nov', 'Dec'];
var NUMBER = /(?:[0-9]{1,3}(?:,[0-9]{3})+|[0-9]+)(?:\.[0-9]+)?(?:%|st|nd|rd|th)?/g;
var IMG = /\[\[img:[^\]\s]+\]\]/g;
var KEY = /\*\*([\s\S]+?)\*\*/g;
var PH0 = 0xE100;                          // placeholders: one private-use character per marked span
var KEY_OPEN = '', KEY_CLOSE = '';
var WORD = /[\p{L}\p{N}_]/u;
var SUFFIX = /\s+(?:Jr\.?|Sr\.?|II|III|IV|V)$/;

function isWord(c) { return !!c && WORD.test(c); }
function isSpace(c) { return /\s/.test(c); }
function cpLen(s) { return Array.from(s).length; }
function reEscape(s) { return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'); }

export function escape(text) {
  return text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

export function unescape(text) {
  text = text.replace(/&#(\d+);/g, function (m, d) { return String.fromCodePoint(parseInt(d, 10)); });
  text = text.replace(/&#[xX]([0-9a-fA-F]+);/g, function (m, h) { return String.fromCodePoint(parseInt(h, 16)); });
  [['&lt;', '<'], ['&gt;', '>'], ['&quot;', '"'], ['&apos;', "'"], ['&nbsp;', ' '], ['&amp;', '&']]
    .forEach(function (kv) { text = text.split(kv[0]).join(kv[1]); });
  return text;
}

/* Straight quotes to curly: an opening one after a space, an opening bracket or a dash, or at the start. */
export function curly(text) {
  var out = '';
  for (var i = 0; i < text.length; i++) {
    var c = text[i], prev = i ? text[i - 1] : ' ';
    var opening = isSpace(prev) || '([{-–'.indexOf(prev) >= 0 || prev === KEY_OPEN;
    if (c === "'") out += opening && i + 1 < text.length && !isSpace(text[i + 1]) ? '‘' : '’';
    else if (c === '"') out += opening ? '“' : '”';
    else out += c;
  }
  return out;
}

function Spans() { this.html = []; this.plain = []; }
Spans.prototype.add = function (markup, plain) {
  this.html.push(markup); this.plain.push(plain);
  return String.fromCharCode(PH0 + this.html.length - 1);
};
Spans.prototype.restore = function (text, plain) {
  var src = plain ? this.plain : this.html;
  return text.replace(/[-]/g, function (c) { return src[c.charCodeAt(0) - PH0]; });
};

function compareTerms(a, b) {
  var d = cpLen(b[0]) - cpLen(a[0]);
  if (d) return d;
  var x = Array.from(a[0]), y = Array.from(b[0]);
  for (var i = 0; i < Math.min(x.length, y.length); i++) {
    var p = x[i].codePointAt(0), q = y[i].codePointAt(0);
    if (p !== q) return p - q;
  }
  return x.length - y.length;
}

function replaceTerms(text, terms, spans, ignoreCase) {
  terms.slice().sort(compareTerms).forEach(function (t) {
    var term = t[0], tag = t[1];
    if (!term) return;
    var pat = new RegExp(reEscape(term), ignoreCase ? 'giu' : 'gu');
    var close = '</' + tag.slice(1, tag.indexOf(' ')) + '>';
    var out = '', pos = 0, m;
    var first = Array.from(term)[0], last = Array.from(term).pop();
    while ((m = pat.exec(text)) !== null) {
      var s = m.index, e = s + m[0].length;
      if (s < pos) continue;
      if (isWord(first) && s > 0 && isWord(text[s - 1])) continue;
      if (isWord(last) && e < text.length && isWord(text[e])) continue;
      out += text.slice(pos, s) + spans.add(tag + m[0] + close, m[0]);
      pos = e;
    }
    text = out + text.slice(pos);
  });
  return text;
}

/* QB, RB, WR, TE as words, and inside plurals and ranks: "WRs", "QB11", "RB2". */
function positions(text, spans) {
  return text.replace(/QB|RB|WR|TE/g, function (m, s) {
    var e = s + m.length, prev = s ? text[s - 1] : ' ', n0 = text[e], n1 = text[e + 1];
    if (isWord(prev)) return m;
    if (n0 && isWord(n0) && !/[0-9]/.test(n0) && !(n0 === 's' && (n1 === undefined || !isWord(n1)))) return m;
    return spans.add('<mark class="hl-pos-' + m + '">' + m + '</mark>', m);
  });
}

function numbers(text, spans) {
  return text.replace(NUMBER, function (m, s) {
    var prev = s ? text[s - 1] : ' ', e = s + m.length, nxt = e < text.length ? text[e] : ' ';
    if (isWord(prev) || '#$.'.indexOf(prev) >= 0 || isWord(nxt)) return m;
    return spans.add('<strong class="hl-stat">' + m + '</strong>', m);
  });
}

/* Index just past the first sentence's closing punctuation, or null when the text is one sentence. */
export function firstSentenceEnd(text) {
  var re = /[.!?]+[’”")\]]*/g, m;
  var end = text.replace(/\s+$/, '').length;
  while ((m = re.exec(text)) !== null) {
    var e = m.index + m[0].length;
    if (e < text.length && !isSpace(text[e])) continue;
    if (e >= end) return null;
    if (m[0][0] === '.') {
      var w = (/([A-Za-z.]+)$/.exec(text.slice(0, m.index)) || ['', ''])[1];
      if (ABBREVIATIONS.indexOf(w) >= 0 || /^(?:[A-Z]\.)*[A-Z]$/.test(w)) continue;
    }
    return e;
  }
  return null;
}

export function playerNames(vocab) {
  var names = (vocab.players || []).map(function (p) { return String(p).trim(); })
    .filter(function (p) { return p.indexOf(' ') >= 0; });
  var full = new Set(names), short = new Map();
  names.forEach(function (p) {
    var s = p.replace(SUFFIX, '');
    if (s !== p && s.indexOf(' ') >= 0) short.set(s, (short.get(s) || 0) + 1);
  });
  short.forEach(function (n, s) { if (n === 1 && !full.has(s)) full.add(s); });
  return Array.from(full);
}

function terms(vocab) {
  var teams = (vocab.teams || []).map(function (t) { return [curly(escape(t)), '<em class="hl-team">']; });
  var players = playerNames(vocab).map(function (p) { return [curly(escape(p)), '<mark class="hl-player">']; });
  var managers = [];
  (vocab.managers || []).forEach(function (m) {
    var tag = m.color ? '<mark class="hl-manager" style="color:' + m.color + ';">' : '<mark class="hl-manager">';
    (m.names || []).forEach(function (n) { managers.push([curly(escape(n)), tag]); });
  });
  return { teams: teams, players: players, managers: managers };
}

/* Plain text (as typed) -> {html, synopsis}. autoKey: a manager's blurb takes its first sentence as
   the key sentence unless **one** is marked. */
export function formatBlurb(text, vocab, autoKey) {
  if (autoKey === undefined) autoKey = true;
  text = String(text == null ? '' : text).replace(/\s+/g, ' ').trim();
  if (!text) return { html: '', synopsis: '' };
  var spans = new Spans();
  text = text.replace(IMG, function (m) { return spans.add(m, ''); });   // kept in the blurb, not the synopsis
  var explicit = new RegExp(KEY.source).test(text);
  text = text.replace(KEY, function (m, inner) { return KEY_OPEN + inner.trim() + KEY_CLOSE; });
  text = curly(escape(text));
  var t = terms(vocab || {});
  text = replaceTerms(text, t.teams, spans, true);
  text = replaceTerms(text, t.players, spans, true);
  text = replaceTerms(text, t.managers, spans, false);
  text = positions(text, spans);
  text = numbers(text, spans);
  if (!explicit && autoKey) {
    var end = firstSentenceEnd(text);
    text = end === null ? KEY_OPEN + text + KEY_CLOSE : KEY_OPEN + text.slice(0, end) + KEY_CLOSE + text.slice(end);
  }
  var key = new RegExp(KEY_OPEN + '([\\s\\S]*?)' + KEY_CLOSE).exec(text);
  var synopsis = key ? unescape(spans.restore(key[1], true)).replace(/\s+/g, ' ').trim() : '';
  var html = spans.restore(text).split(KEY_OPEN).join('<strong class="hl-key">').split(KEY_CLOSE).join('</strong>');
  return { html: html, synopsis: synopsis };
}

function unwrapKey(s) {
  var open = '<strong class="hl-key">', i = s.indexOf(open);
  if (i < 0) return s;
  var depth = 1, j = i + open.length, re = /<(\/?)strong\b[^>]*>/g, m;
  re.lastIndex = j;
  while ((m = re.exec(s)) !== null) {
    depth += m[1] ? -1 : 1;
    if (depth === 0) return s.slice(0, i) + '**' + s.slice(j, m.index) + '**' + s.slice(m.index + m[0].length);
  }
  return s;
}

/* A published blurb back to editable plain text (the key sentence marked **like this** unless it is
   the first sentence the formatter picks anyway). */
export function toSource(html, autoKey) {
  if (autoKey === undefined) autoKey = true;
  var s = unescape(unwrapKey(String(html == null ? '' : html)).replace(/<[^>]+>/g, ''));
  s = s.replace(/\s+/g, ' ').trim();
  if (autoKey && s.indexOf('**') === 0 && s.split('**').length === 3) {
    var close = s.indexOf('**', 2) - 2;
    var plain = s.slice(2, close + 2) + s.slice(close + 4);
    var end = firstSentenceEnd(plain);
    if (end === close || (end === null && close === plain.length)) return plain;
  }
  return s;
}

/* Warnings the editor shows beside a blurb. */
export function problems(text) {
  var out = [];
  text = String(text == null ? '' : text);
  if (text.indexOf(String.fromCharCode(0x2014)) >= 0) out.push('em dash: use a comma, colon or parentheses');
  if ((text.split('**').length - 1) % 2) out.push('unclosed ** key sentence marker');
  if (!text.trim()) out.push('empty');
  return out;
}
