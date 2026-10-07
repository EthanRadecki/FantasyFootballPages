/* Transaction Analysis: the hub page linking the transaction sub-pages. No data file; the text and the
   cards come from config.json. Ported from the Stage A page with the same layout (decision 7.14):
     seasons    every season the sub-pages cover (finished plus the live one, decision 7.8)
     excluded   the league's hidden managers and their seasons, when it has any
     cards      one per transaction sub-page the league has */

import { config } from '../core/data.js';
import { managers } from '../core/managers.js';
import { drawNav, drawFooter, drawSubnav } from '../core/nav.js';
import { url } from '../core/site.js';
import { count } from '../core/format.js';
import { excludedText } from './transaction-notes.js';

config().then(function (cfg) {
  var mgr = managers(cfg);
  drawNav(cfg, 'transaction-analysis');
  drawSubnav(cfg, 'transaction-analysis');
  drawFooter(cfg);

  var seasons = (cfg.seasons || []).map(function (s) { return s.season; });
  var range = function (dash) { return !seasons.length ? '' : seasons.length === 1 ? String(seasons[0]) : seasons[0] + dash + seasons[seasons.length - 1]; };
  var provider = cfg.league.provider === 'espn' ? 'ESPN' : String(cfg.league.provider || 'the provider');
  document.getElementById('hub-sub').textContent = 'Every draft pick, waiver claim, drop, and trade across ' + count(seasons.length, 'season')
    + ' (' + range('-') + "), sourced directly from " + provider + "'s transaction log.";
  document.getElementById('hub-scope').innerHTML = '<strong>Draft picks</strong>, <em>waiver/free agent adds</em>, <em>drops</em>, and '
    + '<em>trades</em>: everything that happens after the initial draft, across ' + count(seasons.length, 'season') + ' (' + range('&ndash;') + ').';
  var li = document.getElementById('hub-excluded'), excluded = excludedText(mgr);
  if (excluded) li.innerHTML = excluded; else li.remove();
  document.querySelectorAll('.season-range').forEach(function (el) { el.textContent = range('-'); });

  // one card per sub-page the league has
  document.querySelectorAll('.subpage-card[data-page]').forEach(function (card) {
    var page = cfg.pages.find(function (p) { return p.id === card.dataset.page; });
    if (page) card.href = url(page.href || page.path);
    else card.remove();
  });
}).catch(function (err) { console.error(err); });
