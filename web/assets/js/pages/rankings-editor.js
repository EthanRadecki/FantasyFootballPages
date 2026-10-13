/* Rankings Editor (pages/rankings-editor.html): write a week's weekly rankings on the site.

   Reads config.json, data/v1/editor/vocab.json (names the formatter marks) and
   data/v1/editor/week.json (the week to write and each manager's numbers); reads and saves the
   week's editorial file in the league's repository through core/editorial-store.js (signed in with a
   GitHub token kept only in this browser). Save draft commits the file with "[skip ci]" (a draft is
   not on the site, so nothing to deploy); Publish sets "status": "published" and commits it, and
   that push deploys the week. What is typed is also kept in this browser until it is saved. */

import { config, load } from '../core/data.js';
import { esc } from '../core/site.js';
import { drawNav, drawFooter } from '../core/nav.js';
import { managers } from '../core/managers.js';
import { formatBlurb, problems as textProblems } from '../core/blurbs.js';
import { githubStore, repoFromLocation } from '../core/editorial-store.js';
import { build, editable, isDraft, problems, serialize } from './rankings-week.js';

var cfg, M, vocab, weekInfo, store;
var cur = null;          // {name, original, sha, snapshot, state, expected}
var timer = null;

var $ = function (id) { return document.getElementById(id); };

function say(text, kind) {
  var el = $('reMessage');
  el.className = 're-message' + (kind ? ' re-' + kind : '');
  el.innerHTML = text;
}

function keyOf(name) {
  var m = M.find(name);
  return m ? m.key : null;
}

function fmt(x, places) { return x == null ? '' : Number(x).toFixed(places == null ? 1 : places); }

function autosaveKey() { return 'pf-editor:' + store.repo + ':' + cur.name; }

function storageDo(fn, fallback) { try { return fn(window.localStorage); } catch (e) { return fallback; } }

function applyAccent(season) {
  var theme = cfg.theme || {};
  var hex = (theme.season_accents || {})[season] || (theme.season_colors || {})[season];
  if (!hex || !/^#[0-9a-f]{6}$/i.test(hex)) return;
  var n = parseInt(hex.slice(1), 16);
  document.documentElement.style.setProperty('--accent', hex);
  document.documentElement.style.setProperty('--accent-rgb', [n >> 16, (n >> 8) & 255, n & 255].join(','));
}

// ------------------------------------------------------------------ sign in

function showSignIn(message) {
  $('reSignin').hidden = false;
  $('reEditor').hidden = true;
  $('reRepo').value = store.repo || '';
  if (message) $('reSigninMsg').textContent = message;
}

function signIn() {
  var token = $('reToken').value.trim(), repo = $('reRepo').value.trim();
  if (!token || !/^[\w.-]+\/[\w.-]+$/.test(repo)) {
    $('reSigninMsg').textContent = 'Paste the token and the repository as owner/name.';
    return;
  }
  store.signIn(token, repo);
  $('reToken').value = '';
  start();
}

function start() {
  $('reSigninMsg').textContent = 'Checking the token…';
  store.check().then(function (who) {
    if (!who.canWrite) {
      store.signOut();
      showSignIn('This token cannot save to ' + store.repo + '. It needs Contents: Read and write on that repository.');
      return;
    }
    $('reSignin').hidden = true;
    $('reEditor').hidden = false;
    $('reWho').textContent = 'Signed in as ' + who.login + ' · ' + store.repo;
    return listWeeks();
  }).catch(function (e) {
    store.signOut();
    showSignIn(e.message);
  });
}

// ------------------------------------------------------------------ weeks

function listWeeks() {
  var dir = weekInfo.repo.editorial_dir;
  return store.list(dir).then(function (names) {
    var weeks = names.filter(function (n) { return /^\d{4}_week\d{2}\.json$/.test(n); }).sort().reverse();
    var sel = $('reWeek');
    var label = function (n) { var m = /^(\d{4})_week(\d{2})/.exec(n); return m[1] + ' Week ' + Number(m[2]); };
    var next = weekInfo.file;
    var opts = weeks.slice(0, 30);
    if (next && opts.indexOf(next) < 0) opts.unshift(next);
    sel.innerHTML = opts.map(function (n) {
      return '<option value="' + esc(n) + '">' + esc(label(n)) + (weeks.indexOf(n) < 0 ? ' (not started)' : '') +
        '</option>';
    }).join('');
    var first = next || opts[0];
    if (!first) { say('No ranked weeks yet. ' + esc(weekInfo.why_none || ''), 'warn'); return; }
    sel.value = first;
    return openWeek(first);
  });
}

function openWeek(name) {
  if (cur && dirty() && !window.confirm('Leave this week? Unsaved changes stay in this browser.')) {
    $('reWeek').value = cur.name;
    return;
  }
  say('Loading ' + esc(name) + '…');
  $('reCards').innerHTML = '';
  $('reMotw').hidden = true;
  return Promise.all([store.read(weekInfo.repo.editorial_dir + '/' + name),
                      store.read(weekInfo.repo.snapshot_dir + '/' + name)]).then(function (res) {
    if (!res[0]) {
      cur = null;
      notStarted(name, !!res[1]);
      return;
    }
    var original = JSON.parse(res[0].text);
    var snapshot = res[1] ? JSON.parse(res[1].text) : null;
    cur = { name: name, original: original, sha: res[0].sha, snapshot: snapshot,
            state: editable(original, vocab),
            expected: (snapshot && snapshot.teams || original.teams || []).map(function (t) { return t.manager; }) };
    applyAccent(String(original.season));
    offerRestore();
    render();
    say(isDraft(original) ? 'Draft: not on the site until you publish it.' : 'Published: saving updates the live page.');
  }).catch(function (e) { say(esc(e.message), 'error'); });
}

function notStarted(name, hasSnapshot) {
  $('reStatus').textContent = 'Not started';
  $('reStatus').className = 're-status re-status-none';
  $('reActions').hidden = true;
  $('reChecks').innerHTML = '';
  say((hasSnapshot ? 'This week has its numbers but no editorial file yet. ' : 'This week is not started yet. ') +
      'Start it to take the week’s numbers now and create the draft (the Tuesday morning update does this ' +
      'by itself). <button type="button" class="re-btn" id="reStart">Start week</button>', 'warn');
  $('reStart').addEventListener('click', function () {
    say('Starting…');
    store.startWeek().then(function () {
      say('Started. The update takes about 8 minutes (<a href="' + esc(store.actionsUrl()) +
          '" target="_blank" rel="noopener">follow it on GitHub</a>); then reload this page.', 'ok');
    }).catch(function (e) {
      say(esc(e.message) + ' (Start week needs the token’s Actions: Read and write permission.)', 'error');
    });
  });
}

// ------------------------------------------------------------------ autosave

/* the state as text, an untouched empty matchup of the week counting as none */
function stateText(state) {
  var m = state.motw;
  var empty = !m || (!m.team_a && !m.team_b && !String(m.source || '').trim());
  return JSON.stringify({ teams: state.teams, motw: empty ? null : m });
}

function snapshotState() { return stateText(cur.state); }

function dirty() { return !!cur && snapshotState() !== stateText(editable(cur.original, vocab)); }

function autosave() {
  if (!cur) return;
  var key = autosaveKey();
  storageDo(function (s) {
    if (dirty()) s.setItem(key, JSON.stringify({ at: Date.now(), sha: cur.sha, state: cur.state }));
    else s.removeItem(key);
  });
}

function offerRestore() {
  var saved = storageDo(function (s) { return JSON.parse(s.getItem(autosaveKey()) || 'null'); }, null);
  var box = $('reRestore');
  box.hidden = true;
  if (!saved || stateText(saved.state) === snapshotState()) return;
  box.hidden = false;
  box.innerHTML = 'You have unsaved changes to this week from ' + esc(new Date(saved.at).toLocaleString()) +
    ' in this browser. <button type="button" class="re-btn" id="reRestoreYes">Restore them</button> ' +
    '<button type="button" class="re-btn re-btn-quiet" id="reRestoreNo">Discard</button>';
  $('reRestoreYes').onclick = function () { cur.state = saved.state; box.hidden = true; render(); };
  $('reRestoreNo').onclick = function () {
    storageDo(function (s) { s.removeItem(autosaveKey()); });
    box.hidden = true;
  };
}

// ------------------------------------------------------------------ render

function numbers(key) {
  if (!weekInfo || cur.name !== weekInfo.file) return null;
  return (weekInfo.managers || []).find(function (m) { return m.key === key; }) || null;
}

function snapTeam(name) {
  var k = keyOf(name);
  return (cur.snapshot && cur.snapshot.teams || []).find(function (t) { return keyOf(t.manager) === k; }) || null;
}

function statsHtml(t) {
  var k = keyOf(t.manager), n = numbers(k), s = snapTeam(t.manager), parts = [];
  if (n) {
    parts.push('<b>' + esc(n.record) + '</b> · ' + fmt(n.ppg, 2) + ' PPG' + (n.streak ? ' · ' + esc(n.streak) : '') +
               (n.prev_rank ? ' · last week #' + n.prev_rank : ''));
    var g = n.last_game;
    if (g) {
      parts.push('Week ' + g.week + ': <b>' + esc(g.result) + '</b> ' + fmt(g.points, 2) + ' to ' + fmt(g.opponent_points, 2) +
                 ' vs ' + esc(M.short(g.opponent_key)) + ' · ' + fmt(g.left_on_bench, 1) + ' left on the bench' +
                 (g.top_starters && g.top_starters.length ? ' · ' + g.top_starters.map(function (p) {
                   return esc(p.player) + ' ' + fmt(p.points, 1); }).join(', ') : ''));
    }
    var x = n.next_game;
    if (x) {
      parts.push('Week ' + cur.original.week + ' vs ' + esc(M.short(x.opponent_key)) + ': projected ' + fmt(x.proj, 1) +
                 ' to ' + fmt(x.opponent_proj, 1) + ' · all-time ' + x.h2h.w + '-' + x.h2h.l + (x.h2h.t ? '-' + x.h2h.t : ''));
    }
  }
  if (s && (s.proj_ppg_ros != null || s.sos_rank != null)) {
    parts.push('Rest of season ' + fmt(s.proj_ppg_ros, 1) + ' projected PPG' +
               (s.sos_rank != null ? ' · schedule rank ' + s.sos_rank + ' (1 = hardest)' : ''));
  }
  return parts.map(function (p) { return '<div>' + p + '</div>'; }).join('');
}

function cardHtml(t, i) {
  var k = keyOf(t.manager), color = M.color(k) || 'inherit';
  var shots = ((cur.original.teams || []).find(function (o) { return o.manager === t.manager; }) || {}).screenshots || [];
  return '<article class="re-card glass" data-i="' + i + '">' +
    '<header class="re-card-head">' +
      '<div class="re-rank"><button type="button" class="re-up" aria-label="Move up">▲</button>' +
      '<input type="number" min="1" class="re-rank-input" value="' + esc(t.rank) + '" aria-label="Rank">' +
      '<button type="button" class="re-down" aria-label="Move down">▼</button></div>' +
      '<h2 class="re-name" style="color:' + esc(color) + '">' + esc(M.name(k) || t.manager) + '</h2>' +
    '</header>' +
    '<div class="re-stats">' + statsHtml(t) + '</div>' +
    '<label class="re-label">Blurb</label>' +
    '<textarea class="re-text" rows="7" spellcheck="true">' + esc(t.source) + '</textarea>' +
    (shots.length ? '<div class="re-hint">Screenshots: ' + shots.map(function (s) {
      return '<code>[[img:' + esc(s.id) + ']]</code>'; }).join(' ') + '</div>' : '') +
    '<label class="re-label">Synopsis <span class="re-hint-inline">(empty = the key sentence)</span></label>' +
    '<input type="text" class="re-syn" value="' + esc(t.synopsis) + '">' +
    '<div class="re-preview-label">Preview</div>' +
    '<div class="re-preview rank-blurb open"></div>' +
    '<ul class="re-warn"></ul>' +
  '</article>';
}

function render() {
  var draft = isDraft(cur.original);
  $('reStatus').textContent = draft ? 'Draft' : 'Published';
  $('reStatus').className = 're-status ' + (draft ? 're-status-draft' : 're-status-live');
  $('reActions').hidden = false;
  $('reSave').textContent = draft ? 'Save draft' : 'Save changes (live)';
  $('rePublish').hidden = !draft;
  cur.state.teams.sort(function (a, b) { return (a.rank || 99) - (b.rank || 99); });
  $('reCards').innerHTML = cur.state.teams.map(cardHtml).join('');
  Array.prototype.forEach.call(document.querySelectorAll('.re-card'), wireCard);
  renderMotw();
  refresh();
}

function wireCard(card) {
  var t = cur.state.teams[Number(card.dataset.i)];
  card.querySelector('.re-text').addEventListener('input', function (e) { t.source = e.target.value; changed(card, t); });
  card.querySelector('.re-syn').addEventListener('input', function (e) { t.synopsis = e.target.value; changed(card, t); });
  card.querySelector('.re-rank-input').addEventListener('change', function (e) {
    t.rank = parseInt(e.target.value, 10) || null;
    autosave();
    render();
  });
  card.querySelector('.re-up').addEventListener('click', function () { move(t, -1); });
  card.querySelector('.re-down').addEventListener('click', function () { move(t, 1); });
  preview(card, t);
}

function move(t, by) {
  var other = cur.state.teams.find(function (o) { return o.rank === t.rank + by; });
  if (!other || !t.rank) return;
  other.rank = t.rank;
  t.rank += by;
  autosave();
  render();
  var el = document.querySelector('.re-card[data-i="' + cur.state.teams.indexOf(t) + '"]');
  if (el) el.scrollIntoView({ block: 'center' });
}

function preview(card, t) {
  var f = formatBlurb(t.source, vocab, true);
  card.querySelector('.re-preview').innerHTML = f.html || '<span class="re-empty">Nothing written yet.</span>';
  card.querySelector('.re-syn').placeholder = f.synopsis ? 'Key sentence: ' + f.synopsis : '';
  card.querySelector('.re-warn').innerHTML = textProblems(t.source).filter(function (p) { return p !== 'empty'; })
    .map(function (p) { return '<li>' + esc(p) + '</li>'; }).join('');
}

function changed(card, t) {
  preview(card, t);
  clearTimeout(timer);
  timer = setTimeout(function () { autosave(); refresh(); }, 300);
}

function renderMotw() {
  var box = $('reMotw');
  box.hidden = false;
  var m = cur.state.motw || (cur.state.motw = { team_a: '', team_b: '', source: '' });
  var opts = function (sel) {
    return '<option value="">Choose a manager</option>' + cur.state.teams.map(function (t) {
      return '<option value="' + esc(t.manager) + '"' + (t.manager === sel ? ' selected' : '') + '>' +
        esc(M.name(keyOf(t.manager)) || t.manager) + '</option>';
    }).join('');
  };
  box.innerHTML = '<h2>Matchup of the Week</h2>' +
    '<div class="re-motw-pick"><select id="reMotwA">' + opts(m.team_a) + '</select><span>vs</span>' +
    '<select id="reMotwB">' + opts(m.team_b) + '</select></div>' +
    '<label class="re-label">Write-up <span class="re-hint-inline">(mark the key sentence **like this**)</span></label>' +
    '<textarea class="re-text" id="reMotwText" rows="6">' + esc(m.source) + '</textarea>' +
    '<div class="re-preview-label">Preview</div><div class="re-preview motw-blurb" id="reMotwPreview"></div>';
  var draw = function () {
    $('reMotwPreview').innerHTML = formatBlurb(m.source, vocab, false).html || '<span class="re-empty">Nothing written yet.</span>';
  };
  $('reMotwA').onchange = function (e) { m.team_a = e.target.value; autosave(); refresh(); };
  $('reMotwB').onchange = function (e) { m.team_b = e.target.value; autosave(); refresh(); };
  $('reMotwText').oninput = function (e) {
    m.source = e.target.value; draw();
    clearTimeout(timer); timer = setTimeout(function () { autosave(); refresh(); }, 300);
  };
  draw();
}

function built(status) { return build(cur.original, cur.state, vocab, status); }

function refresh() {
  if (!cur) return;
  var p = problems(built('published'), cur.expected, keyOf);
  var el = $('reChecks');
  el.innerHTML = (p.errors.length ? '<div class="re-errors"><b>Before publishing:</b><ul>' + p.errors.map(function (e) {
    return '<li>' + esc(e) + '</li>'; }).join('') + '</ul></div>' : '<div class="re-ready">Ready to publish.</div>') +
    (p.warnings.length ? '<details class="re-warnings"><summary>' + p.warnings.length + ' note' +
      (p.warnings.length === 1 ? '' : 's') + '</summary><ul>' + p.warnings.map(function (w) {
        return '<li>' + esc(w) + '</li>'; }).join('') + '</ul></details>' : '');
  $('rePublish').disabled = p.errors.length > 0;
}

// ------------------------------------------------------------------ save and publish

function save(status) {
  var draft = isDraft(cur.original);
  var ed = built(status || (draft ? 'draft' : undefined));
  if (status === 'published') {
    var p = problems(ed, cur.expected, keyOf);
    if (p.errors.length) { refresh(); say('Fix the items above before publishing.', 'error'); return; }
    if (!window.confirm('Publish ' + $('reWeek').selectedOptions[0].textContent + '? It goes live on the site in about 8 minutes.' +
                        (p.warnings.length ? '\n\n' + p.warnings.length + ' note(s): ' + p.warnings.slice(0, 5).join('; ') : ''))) return;
  }
  var label = cur.original.season + ' week ' + cur.original.week + ' rankings';
  var message = status === 'published' ? 'Publish ' + label + ' (rankings editor)'
    : draft ? 'Draft ' + label + ' (rankings editor) [skip ci]' : 'Update ' + label + ' (rankings editor)';
  var path = weekInfo.repo.editorial_dir + '/' + cur.name;
  say('Saving…');
  $('reSave').disabled = $('rePublish').disabled = true;
  store.write(path, serialize(ed), cur.sha, message).then(function (res) {
    cur.sha = res.sha;
    cur.original = ed;
    cur.state = editable(ed, vocab);
    storageDo(function (s) { s.removeItem(autosaveKey()); });
    render();
    var link = res.commit ? ' (<a href="' + esc(res.commit) + '" target="_blank" rel="noopener">commit</a>)' : '';
    if (status === 'published' || !draft) {
      say((status === 'published' ? 'Published.' : 'Saved.') + ' The site updates in about 8 minutes (<a href="' +
          esc(store.actionsUrl()) + '" target="_blank" rel="noopener">deploy</a>)' + link + '.', 'ok');
    } else {
      say('Draft saved at ' + esc(new Date().toLocaleTimeString()) + link + '. It is not on the site until you publish it.', 'ok');
    }
  }).catch(function (e) {
    say(esc(e.message), 'error');
  }).then(function () { $('reSave').disabled = false; refresh(); });
}

// ------------------------------------------------------------------ start

config().then(function (c) {
  cfg = c;
  M = managers(cfg);
  drawNav(cfg, 'rankings-editor');
  drawFooter(cfg);
  return Promise.all([load('data/v1/editor/vocab.json'), load('data/v1/editor/week.json')]);
}).then(function (res) {
  vocab = res[0];
  weekInfo = res[1];
  store = githubStore({ repo: weekInfo.repo.name || repoFromLocation(window.location), branch: weekInfo.repo.branch });
  $('reHeroSub').textContent = cfg.league.name + (weekInfo.week ? ' · ' + weekInfo.season + ' Week ' + weekInfo.week + ' is next' : '');
  $('reSigninBtn').addEventListener('click', signIn);
  $('reToken').addEventListener('keydown', function (e) { if (e.key === 'Enter') signIn(); });
  $('reSignout').addEventListener('click', function () {
    if (cur && dirty() && !window.confirm('Sign out? Unsaved changes stay in this browser.')) return;
    store.signOut();
    showSignIn('Signed out.');
  });
  $('reWeek').addEventListener('change', function (e) { openWeek(e.target.value); });
  $('reReload').addEventListener('click', function () { if (cur) { var n = cur.name; cur = null; openWeek(n); } });
  $('reSave').addEventListener('click', function () { save(); });
  $('rePublish').addEventListener('click', function () { save('published'); });
  window.addEventListener('beforeunload', function (e) { if (dirty()) { e.preventDefault(); e.returnValue = ''; } });
  if (store.signedIn()) start();
  else showSignIn();
}).catch(function (e) {
  console.error(e);
  say('The editor could not load its data: ' + esc(e.message), 'error');
  $('reSignin').hidden = true;
});
