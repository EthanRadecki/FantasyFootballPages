/* Managers as config.json describes them: name, short name, colors, logo, hidden. Pages key every
   record by manager key and look names and colors up here, so nothing about a league's managers is
   written into the site. */

import { url } from './site.js';

export function managers(cfg) {
  var list = cfg.managers || [];
  var byKey = new Map(list.map(function (m) { return [m.key, m]; }));
  var byName = new Map();
  list.forEach(function (m) {
    [m.name, m.slug, m.short].concat(m.aliases || []).forEach(function (n) {
      if (n) byName.set(String(n).toLowerCase(), m);
    });
  });
  return {
    all: list,
    visible: list.filter(function (m) { return !m.hidden; }),
    get: function (key) { return byKey.get(key) || null; },
    find: function (nameOrSlug) { return byName.get(String(nameOrSlug || '').toLowerCase()) || null; },
    name: function (key) { var m = byKey.get(key); return m ? m.name : key; },
    short: function (key) { var m = byKey.get(key); return m ? m.short : key; },
    color: function (key, shade) {
      var m = byKey.get(key);
      return m && m.colors ? m.colors[shade || 'dark'] : null;
    },
    logo: function (key) { var m = byKey.get(key); return m && m.logo ? url(m.logo) : null; },
  };
}
