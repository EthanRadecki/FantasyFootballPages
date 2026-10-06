/* A table sorted by clicking its headers, as the Stage A leaderboards behave: the first click on a
   column sorts it best-first (A to Z for text), the next click reverses it; the sorted header shows
   an arrow, the others the two-way arrow.

   columns: [{label, value: row -> number or string, text: true for text columns}]
   draw(row) returns the row's <tr> inner HTML. */

import { esc } from '../core/site.js';

export function sortTable(table, rows, columns, draw, initial) {
  var state = { col: initial ? initial.col : 0, asc: initial ? !!initial.asc : false };
  var thead = table.querySelector('thead') || table.appendChild(document.createElement('thead'));
  var tbody = table.querySelector('tbody') || table.appendChild(document.createElement('tbody'));
  thead.innerHTML = '<tr>' + columns.map(function (c, i) {
    return '<th data-col="' + i + '">' + esc(c.label) + ' <span class="sort-arrow">&#8645;</span></th>';
  }).join('') + '</tr>';

  function render() {
    var c = columns[state.col];
    var sorted = rows.slice().sort(function (a, b) {
      var x = c.value(a), y = c.value(b);
      var d = c.text ? String(x).localeCompare(String(y)) : (x == null ? -Infinity : x) - (y == null ? -Infinity : y);
      return state.asc ? d : -d;
    });
    tbody.innerHTML = sorted.map(function (r) { return '<tr>' + draw(r) + '</tr>'; }).join('');
    thead.querySelectorAll('th').forEach(function (th, i) {
      var arrow = th.querySelector('.sort-arrow');
      th.classList.toggle('sorted', i === state.col);
      arrow.textContent = i === state.col ? (state.asc ? '▲' : '▼') : '⇅';
    });
  }

  thead.addEventListener('click', function (e) {
    var th = e.target.closest('th');
    if (!th) return;
    var i = Number(th.dataset.col);
    if (i === state.col) state.asc = !state.asc;
    else { state.col = i; state.asc = !!columns[i].text; }
    render();
  });
  render();
}
