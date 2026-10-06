/* The one data loader every page uses (docs/PUBLISH_PLAN.md, Stage B foundations).

   config() fetches config.json once, never from the browser cache, so a new build is seen at once.
   load(path) fetches a data file tagged with the build id (?v=<build>), so a page never mixes files
   from two builds. show() draws a section's loading, empty and error states the same way on every
   page. */

import { url, esc } from './site.js';

let configPromise = null;

function getJSON(href, init) {
  return fetch(href, init).then(function (r) {
    if (!r.ok) throw new Error(r.status + ' ' + r.statusText + ' (' + href + ')');
    return r.json();
  });
}

export function config() {
  if (!configPromise) configPromise = getJSON(url('config.json'), { cache: 'no-cache' });
  return configPromise;
}

export function load(path) {
  return config().then(function (cfg) {
    return getJSON(url(path) + '?v=' + encodeURIComponent(cfg.build && cfg.build.id || ''));
  });
}

/* A section's state: 'loading', 'empty' (no data yet for this league or season), or 'error'. */
export function show(el, state, message) {
  if (!el) return;
  var text = message || { loading: 'Loading…', empty: 'Nothing to show yet.',
                          error: 'This section could not be loaded.' }[state];
  var box = '<div class="data-state data-state-' + state + '">' + esc(text) + '</div>';
  el.innerHTML = el.tagName === 'TBODY' ? '<tr><td colspan="99">' + box + '</td></tr>' : box;
}

/* Fill `el` from a promise: the loading state first, then draw(data) (which returns false when
   there is nothing to show), or the error state, with the error in the console. */
export function fill(el, promise, draw) {
  show(el, 'loading');
  return Promise.resolve(promise).then(function (data) {
    el.innerHTML = '';
    if (draw(data, el) === false) show(el, 'empty');
  }).catch(function (err) {
    console.error(err);
    show(el, 'error');
  });
}
