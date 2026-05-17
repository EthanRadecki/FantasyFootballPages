/* ══════════════════════════════════════
   Preach Fantasy - Shared JS
   ══════════════════════════════════════ */

/* ── MOBILE MENU ── */
function openMobileMenu() {
  document.getElementById('mobile-menu').classList.add('active');
}

function closeMobileMenu() {
  document.getElementById('mobile-menu').classList.remove('active');
}

// Close mobile menu when clicking outside
document.addEventListener('click', function(e) {
  const menu = document.getElementById('mobile-menu');
  if (menu && e.target === menu) {
    closeMobileMenu();
  }
});

/* ── LIGHTBOX ── */
function openLightbox(src, alt) {
  const lb = document.getElementById('lightbox');
  if (!lb) return;
  const img = document.getElementById('lightbox-img');
  img.src = src;
  img.alt = alt || '';
  lb.classList.add('active');
  document.body.style.overflow = 'hidden';
}

function closeLightbox() {
  const lb = document.getElementById('lightbox');
  if (!lb) return;
  lb.classList.remove('active');
  document.body.style.overflow = '';
}

// Escape key closes lightbox and mobile menu
document.addEventListener('keydown', function(e) {
  if (e.key === 'Escape') {
    closeLightbox();
    closeMobileMenu();
  }
});
