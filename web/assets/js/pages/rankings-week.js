/* The rankings editor's week logic, without the page: building the editorial file from what was
   typed, the checks before publishing, and writing the file the way the engine writes it.

   problems() is the twin of engine/publish/rankings.py problems() (engine/tests/test_rankings_editor.py
   runs both on the same weeks), so the editor refuses exactly what `engine rankings publish` refuses. */

import { formatBlurb, toSource } from '../core/blurbs.js';

export var MOTW = 'matchup_of_the_week';

/* The file as the engine writes it (json.dumps(..., ensure_ascii=False, indent=1) plus a newline). */
export function serialize(ed) {
  return JSON.stringify(ed, null, 1) + '\n';
}

export function isDraft(ed) { return !!ed && ed.status === 'draft'; }

/* (errors, warnings) for a week about to be published; expected = the snapshot's managers;
   key(name) -> manager key or null. */
export function problems(ed, expected, key) {
  var errors = [], warnings = [];
  var teams = ed.teams || [], keys = [];
  teams.forEach(function (t) {
    var k = key(t.manager);
    if (k == null) errors.push('unknown manager ' + JSON.stringify(t.manager == null ? null : t.manager));
    else if (keys.indexOf(k) >= 0) errors.push(t.manager + ' is listed twice');
    keys.push(k);
  });
  if (expected && expected.length) {
    var missing = expected.filter(function (m) { return keys.indexOf(key(m)) < 0; });
    if (missing.length) errors.push('not ranked: ' + missing.join(', '));
  }
  var seen = new Map();
  teams.forEach(function (t) {
    var r = t.rank;
    if (!seen.has(r)) seen.set(r, []);
    seen.get(r).push(t.manager);
  });
  var shared = false;
  seen.forEach(function (who, r) {
    if (who.length > 1) { shared = true; errors.push('rank ' + r + ' given to ' + who.join(', ')); }
  });
  var ints = teams.map(function (t) { return t.rank; }).filter(function (r) { return Number.isInteger(r); })
    .sort(function (a, b) { return a - b; });
  var ok = ints.length === teams.length && ints.every(function (r, i) { return r === i + 1; });
  if (!shared && !ok) errors.push('ranks must be 1 to ' + teams.length + ', once each');
  if (teams.length && !teams.some(function (t) { return String(t.blurb || '').trim(); })) {
    errors.push('no blurbs written yet');
  }
  teams.forEach(function (t) {
    if (!String(t.blurb || '').trim()) warnings.push(t.manager + ': empty blurb');
    if (!String(t.synopsis || '').trim()) warnings.push(t.manager + ': empty synopsis');
  });
  var m = ed[MOTW];
  if (!m) warnings.push('no matchup of the week');
  else {
    var a = key(m.team_a), b = key(m.team_b);
    if (a == null || b == null) errors.push('matchup of the week names an unknown manager');
    else if (a === b) errors.push('matchup of the week names the same manager twice');
    if (!String(m.blurb || '').trim()) warnings.push('matchup of the week: empty blurb');
  }
  if (JSON.stringify(ed).indexOf(String.fromCharCode(0x2014)) >= 0) warnings.push('contains an em dash');
  return { errors: errors, warnings: warnings };
}

/* What the editor shows for a loaded file: per manager the plain text to edit (toSource) and the
   synopsis box (empty when the synopsis is the key sentence anyway, which is what an empty box
   saves), plus the matchup of the week. Without vocab the synopsis is shown as written. */
export function editable(ed, vocab) {
  return {
    teams: (ed.teams || []).map(function (t) {
      var source = toSource(t.blurb || '', true), syn = t.synopsis || '';
      if (vocab && syn && formatBlurb(source, vocab, true).synopsis === syn) syn = '';
      return { manager: t.manager, rank: t.rank, source: source, synopsis: syn };
    }),
    motw: ed[MOTW] ? { team_a: ed[MOTW].team_a, team_b: ed[MOTW].team_b,
                       source: toSource(ed[MOTW].blurb || '', false) } : null,
  };
}

/* The editorial file from the original and the edited state. A blurb whose text did not change keeps
   its markup as written (older weeks were formatted by hand, some left plain); a changed one, or an
   untagged one in a draft (written by hand as plain text), is formatted. An empty synopsis box means
   "the key sentence". The file's own fields are kept (no empty fields added); teams keep the file's
   order unless a rank changed, then they come in rank order. status: 'draft', 'published', or
   undefined to keep the file's own. */
export function build(original, state, vocab, status) {
  var before = editable(original);
  var draft = isDraft(original);
  var byName = new Map((original.teams || []).map(function (t) { return [t.manager, t]; }));
  var ORDER = ['manager', 'rank', 'synopsis', 'blurb', 'screenshots'];
  var moved = false;
  var teams = state.teams.map(function (s) {
    var orig = byName.get(s.manager) || { manager: s.manager };
    var was = before.teams.find(function (t) { return t.manager === s.manager; }) || { source: '', synopsis: '' };
    if (s.rank !== orig.rank) moved = true;
    var f = formatBlurb(s.source, vocab, true);
    var blurb = s.source !== was.source || (draft && !/</.test(orig.blurb || '')) ? f.html : (orig.blurb || '');
    var typed = String(s.synopsis || '').trim();
    var synopsis = typed || (s.source !== was.source || !orig.synopsis ? f.synopsis : orig.synopsis);
    var vals = { manager: s.manager, rank: s.rank, synopsis: synopsis, blurb: blurb };
    var row = {};
    ORDER.concat(Object.keys(orig)).forEach(function (k) {
      if (k in row) return;
      if (k in vals && (k in orig || vals[k] !== '')) row[k] = vals[k];
      else if (k in orig) row[k] = orig[k];
    });
    return row;
  });
  var origOrder = (original.teams || []).map(function (t) { return t.manager; });
  if (moved || teams.length !== origOrder.length) {
    teams.sort(function (a, b) { return (a.rank || 99) - (b.rank || 99); });
  } else {
    teams.sort(function (a, b) { return origOrder.indexOf(a.manager) - origOrder.indexOf(b.manager); });
  }

  var out = {};
  Object.keys(original).forEach(function (k) { if (k !== 'teams' && k !== MOTW) out[k] = original[k]; });
  if (status) {
    var ordered = {};
    Object.keys(out).forEach(function (k) {
      if (k !== 'status') ordered[k] = out[k];
      if (k === 'week') ordered.status = status;
    });
    out = ordered;
  }
  out.teams = teams;
  if (state.motw && state.motw.team_a && state.motw.team_b) {
    var om = original[MOTW] || {};
    var m = {};
    Object.keys(om).forEach(function (k) { m[k] = om[k]; });
    m.team_a = state.motw.team_a;
    m.team_b = state.motw.team_b;
    var wasM = before.motw ? before.motw.source : '';
    m.blurb = state.motw.source !== wasM || !/</.test(om.blurb || '') ? formatBlurb(state.motw.source, vocab, false).html
      : om.blurb;
    if (!m.blurb) delete m.blurb;
    out[MOTW] = { team_a: m.team_a, team_b: m.team_b };
    Object.keys(m).forEach(function (k) { if (k !== 'team_a' && k !== 'team_b') out[MOTW][k] = m[k]; });
  }
  // the original file's key order: teams before the matchup of the week when it was so
  var keys = Object.keys(original);
  if (keys.indexOf(MOTW) >= 0 && keys.indexOf('teams') > keys.indexOf(MOTW) && out[MOTW]) {
    var t = out.teams; delete out.teams; out.teams = t;
  }
  return out;
}
