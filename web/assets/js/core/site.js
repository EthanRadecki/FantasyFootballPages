/* Where the site lives. Every path in config.json and in the page data (data/v1/..., images/...) is
   relative to the site root; url() turns one into a URL that works from any page, at the root or in
   pages/, and from a preview folder such as /next/. */

export const ROOT = new URL('../../../', import.meta.url);

export function url(path) {
  return new URL(String(path).replace(/^\/+/, ''), ROOT).href;
}

/* The query string as a plain object (?manager=Jane%20Doe -> {manager: 'Jane Doe'}). */
export function params() {
  return Object.fromEntries(new URLSearchParams(window.location.search));
}

/* Text for an HTML attribute or element body. */
export function esc(value) {
  return String(value == null ? '' : value)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}
