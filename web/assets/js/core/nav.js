/* The nav bar and mobile menu, drawn from config.json's page list (pages a league switched off, or
   has no data for, are not in it), the league name and its logo. Markup and classes match the
   Stage A pages, so site.css styles them unchanged. */

import { url, esc } from './site.js';

function href(page) {
  return url(page.href || page.path);
}

/* arrow: write the sub-page arrow into the link text (the mobile menu); the desktop nav's stylesheet
   draws its own (.nav-links a.nav-sub::before), so there the text has none (it showed two) */
function links(cfg, current, arrow) {
  return cfg.pages.filter(function (p) { return p.nav; }).map(function (p) {
    var cls = [p.parent ? 'nav-sub' : '', p.id === current ? 'active' : ''].filter(Boolean).join(' ');
    return '<a href="' + esc(href(p)) + '"' + (cls ? ' class="' + cls + '"' : '') + '>' +
      (p.parent && arrow ? '&#8627; ' : '') + esc(p.title) + '</a>';
  }).join('\n');
}

export function drawNav(cfg, current) {
  var home = cfg.pages.find(function (p) { return p.id === 'home'; });
  var logo = cfg.league.logo ? url(cfg.league.logo) : '';
  var nav = document.getElementById('site-nav');
  if (nav) {
    nav.innerHTML =
      '<a href="' + esc(home ? href(home) : url('index.html')) + '" class="nav-brand">' +
      (logo ? '<img src="' + esc(logo) + '" alt="" onerror="this.remove()">' : '') + '<span>' + esc(cfg.league.name) + '</span></a>' +
      '<div class="nav-links">' + links(cfg, current, false) + '</div>' +
      '<button class="nav-hamburger" aria-label="Menu"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" ' +
      'stroke-width="2" stroke-linecap="round"><line x1="3" y1="6" x2="21" y2="6"/><line x1="3" y1="12" x2="21" ' +
      'y2="12"/><line x1="3" y1="18" x2="21" y2="18"/></svg></button>';
  }
  var menu = document.getElementById('mobile-menu');
  if (menu) {
    menu.innerHTML = '<div class="mobile-menu-inner"><button class="mobile-menu-close" aria-label="Close">&#10005;</button>' +
      links(cfg, current, true) + '</div>';
    menu.addEventListener('click', function (e) { if (e.target === menu) menu.classList.remove('active'); });
    menu.querySelector('.mobile-menu-close').addEventListener('click', function () { menu.classList.remove('active'); });
    var burger = nav && nav.querySelector('.nav-hamburger');
    if (burger) burger.addEventListener('click', function () { menu.classList.add('active'); });
  }
  // the browser tab: the league's current logo and "<Page> | <League>" (the home page shows the league name)
  var icon = document.querySelector('link[rel="icon"]') || document.head.appendChild(Object.assign(
    document.createElement('link'), { rel: 'icon', type: 'image/png' }));
  if (logo) icon.href = logo;
  else icon.remove();
  var page = cfg.pages.find(function (p) { return p.id === current; });
  document.title = page && page.id !== 'home' ? page.title + ' | ' + cfg.league.name : cfg.league.name;
}

/* The footer: league name, first season and the site credit league.yaml gives, if any. */
export function drawFooter(cfg) {
  var el = document.getElementById('site-footer');
  if (!el) return;
  var credit = cfg.league.credit;
  el.innerHTML = '<p>' + esc(cfg.league.name) + ' · Est. ' + esc(cfg.league.first_season) +
    (credit && credit.name ? ' · Built by ' + (credit.url ? '<a href="' + esc(credit.url) + '" target="_blank">' +
      esc(credit.name) + '</a>' : esc(credit.name)) : '') + '</p>';
}

/* A section's pill row (the draft pages today): the section's main page and its sub-pages, from
   config.json's page list, the current page marked. Drawn into #page-subnav; hidden when the
   section has a single page. */
export function drawSubnav(cfg, current) {
  var el = document.getElementById('page-subnav');
  if (!el) return;
  var page = cfg.pages.find(function (p) { return p.id === current; });
  var root = page && (page.parent || page.id);
  var family = cfg.pages.filter(function (p) { return p.id === root || p.parent === root; });
  if (family.length < 2) { el.style.display = 'none'; return; }
  el.innerHTML = family.map(function (p) {
    return '<a href="' + esc(href(p)) + '" class="draft-subnav-pill' + (p.id === current ? ' current' : '') + '">' +
      esc(p.title) + '</a>';
  }).join('\n');
}
