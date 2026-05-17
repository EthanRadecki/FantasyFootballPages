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
