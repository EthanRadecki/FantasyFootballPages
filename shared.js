/* ══════════════════════════════════════
   Preach Fantasy - Shared JS
   ══════════════════════════════════════ */

function openMobileMenu() {
  document.getElementById('mobile-menu').classList.add('active');
}

function closeMobileMenu() {
  document.getElementById('mobile-menu').classList.remove('active');
}

function openLightbox(src, alt) {
  var lb = document.getElementById('lightbox');
  if (!lb) return;
  var img = document.getElementById('lightbox-img');
  img.src = src;
  img.alt = alt || '';
  lb.classList.add('active');
  document.body.style.overflow = 'hidden';
}

function closeLightbox() {
  var lb = document.getElementById('lightbox');
  if (!lb) return;
  lb.classList.remove('active');
  document.body.style.overflow = '';
}

document.addEventListener('keydown', function(e) {
  if (e.key === 'Escape') {
    closeLightbox();
    closeMobileMenu();
  }
});

/* A page's season range ("2020-2026"): every <span data-season-range> shows the first and
   last of the page's PAGE_SEASONS, which the build writes from the data. */
document.addEventListener('DOMContentLoaded', function() {
  if (typeof PAGE_SEASONS === 'undefined' || !PAGE_SEASONS.length) return;
  var text = PAGE_SEASONS[0] + '-' + PAGE_SEASONS[PAGE_SEASONS.length - 1];
  document.querySelectorAll('[data-season-range]').forEach(function(el) { el.textContent = text; });
});

/* A season's label on a filter: "2026 (live)" for the page's PAGE_LIVE_SEASON, else the year. */
function seasonLabel(s) {
  var live = typeof PAGE_LIVE_SEASON === 'undefined' ? null : PAGE_LIVE_SEASON;
  return live !== null && String(s) === String(live) ? s + ' (live)' : String(s);
}
