/* Notes the transaction pages share, written from config.json instead of typed into each page:
     [data-season-range]   the page's first and last season ("2020-2026")
     #excluded-note        the league's hidden managers and their seasons (removed when it has none)
     #waiver-system        how waiver claims worked by season (ESPN's FAAB setting, seasons[].faab) */

import { esc } from '../core/site.js';

export function andList(xs) { return xs.length < 2 ? xs.join('') : xs.slice(0, -1).join(', ') + ' and ' + xs[xs.length - 1]; }

/* consecutive seasons as ranges: [2020, 2021, 2022, 2024] -> "2020-2022, 2024" */
export function seasonRanges(list) {
  var s = list.slice().sort(function (a, b) { return a - b; }), out = [];
  for (var i = 0; i < s.length; i++) {
    var j = i;
    while (j + 1 < s.length && s[j + 1] === s[j] + 1) j++;
    out.push(j > i ? s[i] + '-' + s[j] : String(s[i]));
    i = j;
  }
  return out.join(', ');
}

export function excludedText(mgr) {
  var hidden = mgr.all.filter(function (m) { return m.hidden; });
  if (!hidden.length) return '';
  var their = Array.from(new Set([].concat.apply([], hidden.map(function (m) { return m.seasons || []; })))).sort();
  return '<strong>Excluded:</strong> ' + esc(andList(hidden.map(function (m) { return m.name; })))
    + (their.length ? ' (' + their.join(', ') + (their.length === 1 ? ' only' : '') + ')' : '') + ', same as the rest of the site.';
}

export function waiverSystemText(cfg, seasons) {
  var info = function (s) { return (cfg.seasons || []).find(function (x) { return x.season === s; }) || {}; };
  var faab = seasons.filter(function (s) { return info(s).faab; });
  var priority = seasons.filter(function (s) { return !info(s).faab; });
  if (faab.length && priority.length) {
    return '<strong>Scoring systems changed over time:</strong> FAAB bidding only in ' + seasonRanges(faab) + '. <em>'
      + seasonRanges(priority) + ' ran on reverse-order waiver priority</em>, where a successful claim sends you to the back '
      + 'of the line. Since "cost" isn\'t comparable across those two systems, this page measures pure output instead.';
  }
  if (faab.length) {
    return '<strong>Waiver system:</strong> FAAB bidding every season. Bids aren\'t part of this page; it measures pure output instead.';
  }
  return '<strong>Waiver system:</strong> <em>every season ran on reverse-order waiver priority</em>, where a successful claim '
    + 'sends you to the back of the line. This page measures pure output.';
}

export function methodNotes(cfg, mgr, seasons) {
  var range = !seasons.length ? '' : seasons.length === 1 ? String(seasons[0]) : seasons[0] + '-' + seasons[seasons.length - 1];
  document.querySelectorAll('[data-season-range]').forEach(function (el) { el.textContent = range; });
  var ex = document.getElementById('excluded-note');
  if (ex) {
    var text = excludedText(mgr);
    if (text) ex.innerHTML = text; else ex.remove();
  }
  var ws = document.getElementById('waiver-system');
  if (ws) ws.innerHTML = waiverSystemText(cfg, seasons);
}
