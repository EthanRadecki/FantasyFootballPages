/* The chapter rail of the long analysis pages: a row of dots beside the content (one per section,
   the one in view highlighted) when the window leaves room for it, else a "Jump to" button that
   opens the same list as a sheet. Markup and classes as on the Stage A pages: #chapter-rail with
   .chapter-rail-item links, .jump-fab, #jump-sheet with links; each link's data-target is a
   section id. Styles stay in each page's stylesheet, as they were. */

var MIN_GAP = 150;   // free pixels right of the content before the rail shows

export function chapterRail() {
  var rail = document.getElementById('chapter-rail');
  var fab = document.querySelector('.jump-fab');
  var sheet = document.getElementById('jump-sheet');
  var content = document.querySelector('.content');
  if (!rail || !content) return;

  function toggleSheet(open) { if (sheet) sheet.classList.toggle('open', open); }
  if (fab) fab.addEventListener('click', function () { toggleSheet(true); });
  if (sheet) {
    sheet.addEventListener('click', function (e) {
      if (e.target === sheet || e.target.closest('a')) toggleSheet(false);
    });
  }

  function positionRail() {
    var rect = content.getBoundingClientRect();
    if (window.innerWidth - rect.right >= MIN_GAP) {
      rail.style.left = (rect.right + 28) + 'px';
      rail.classList.add('visible');
      if (fab) fab.classList.remove('visible');
    } else {
      rail.classList.remove('visible');
      if (fab) fab.classList.add('visible');
    }
  }
  positionRail();
  window.addEventListener('resize', positionRail);
  window.addEventListener('load', positionRail);

  var items = Array.from(document.querySelectorAll('.chapter-rail-item, .jump-sheet a'));
  var targets = Array.from(new Set(items.map(function (i) { return i.dataset.target; })))
    .map(function (id) { return document.getElementById(id); }).filter(Boolean);
  if (!targets.length || !window.IntersectionObserver) return;
  var observer = new IntersectionObserver(function (entries) {
    entries.forEach(function (entry) {
      if (entry.isIntersecting) {
        items.forEach(function (i) { i.classList.toggle('active', i.dataset.target === entry.target.id); });
      }
    });
  }, { rootMargin: '-15% 0px -70% 0px', threshold: 0 });
  targets.forEach(function (t) { observer.observe(t); });
}
