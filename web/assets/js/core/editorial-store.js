/* Where the rankings editor reads and saves a league's editorial files.

   Today: the league's GitHub repository, through the GitHub REST API, signed in with a fine-grained
   personal access token limited to that repository (Contents: read and write; Actions: read and
   write for "Start week"). The token is kept only in this browser (localStorage) and is sent only to
   api.github.com. Anyone can open the editor page; only someone with a token for the repository can
   save (decision 7.10: the product later swaps this module for its own sign-in and a save service,
   with the same methods, and the page stays as it is).

   A store has: signedIn(), signIn(token), signOut(), check(), read(path), list(dir),
   write(path, text, sha, message), startWeek(), and `repo` / `branch`. */

var API = 'https://api.github.com';
var TOKEN_KEY = 'pf-editor-token';
var REPO_KEY = 'pf-editor-repo';

function storage(fn, fallback) {
  try { return fn(window.localStorage); } catch (e) { return fallback; }
}

/* owner/repo from the site's address (owner.github.io/repo/...), when the build did not say. */
export function repoFromLocation(loc) {
  var host = String(loc.hostname || '');
  if (!/\.github\.io$/i.test(host)) return null;
  var owner = host.split('.')[0];
  var first = String(loc.pathname || '/').split('/').filter(Boolean)[0];
  return owner + '/' + (first && !/\.html?$/i.test(first) ? first : host);
}

function utf8ToBase64(text) {
  var bytes = new TextEncoder().encode(text), bin = '';
  for (var i = 0; i < bytes.length; i += 0x8000) bin += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
  return btoa(bin);
}

function base64ToUtf8(b64) {
  var bin = atob(String(b64).replace(/\s/g, '')), bytes = new Uint8Array(bin.length);
  for (var i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
  return new TextDecoder().decode(bytes);
}

export class StoreError extends Error {
  constructor(message, status) { super(message); this.status = status; }
}

export function githubStore(opts) {
  var repo = opts.repo || storage(function (s) { return s.getItem(REPO_KEY); }, null);
  var branch = opts.branch || 'main';
  var token = storage(function (s) { return s.getItem(TOKEN_KEY); }, null);

  function call(method, path, body) {
    if (!repo) return Promise.reject(new StoreError('No repository set.', 0));
    var headers = { Accept: 'application/vnd.github+json', 'X-GitHub-Api-Version': '2022-11-28' };
    if (token) headers.Authorization = 'Bearer ' + token;
    if (body) headers['Content-Type'] = 'application/json';
    return fetch(API + path.replace('{repo}', repo), {
      method: method, headers: headers, body: body ? JSON.stringify(body) : undefined, cache: 'no-store',
    }).then(function (r) {
      if (r.status === 204) return null;
      return r.json().catch(function () { return null; }).then(function (data) {
        if (!r.ok) {
          var msg = (data && data.message) || r.statusText;
          if (r.status === 401) msg = 'GitHub did not accept the token (expired or mistyped). Sign in again.';
          if (r.status === 409) msg = 'This file changed since you opened it (saved from somewhere else). Reload to get the newest version; your text is kept in this browser.';
          throw new StoreError(msg, r.status);
        }
        return data;
      });
    });
  }

  function contentsPath(path) {
    return '/repos/{repo}/contents/' + path.split('/').map(encodeURIComponent).join('/');
  }

  return {
    get repo() { return repo; },
    branch: branch,
    signedIn: function () { return !!token; },
    signIn: function (t, r) {
      token = String(t || '').trim() || null;
      if (r) repo = String(r).trim();
      storage(function (s) { s.setItem(TOKEN_KEY, token || ''); if (r) s.setItem(REPO_KEY, repo); });
    },
    signOut: function () {
      token = null;
      storage(function (s) { s.removeItem(TOKEN_KEY); });
    },
    /* {login, canWrite}: the token works and may push to the repository. */
    check: function () {
      return Promise.all([call('GET', '/user'), call('GET', '/repos/{repo}')]).then(function (res) {
        return { login: res[0] && res[0].login, canWrite: !!(res[1] && res[1].permissions && res[1].permissions.push) };
      });
    },
    /* {text, sha} or null when the file does not exist. */
    read: function (path) {
      return call('GET', contentsPath(path) + '?ref=' + encodeURIComponent(branch)).then(function (d) {
        if (d.content || !d.download_url) return { text: base64ToUtf8(d.content || ''), sha: d.sha };
        return fetch(d.download_url, { cache: 'no-store' }).then(function (r) { return r.text(); })
          .then(function (text) { return { text: text, sha: d.sha }; });
      }).catch(function (e) { if (e.status === 404) return null; throw e; });
    },
    /* the file names in a folder ([] when it does not exist) */
    list: function (dir) {
      return call('GET', contentsPath(dir) + '?ref=' + encodeURIComponent(branch)).then(function (d) {
        return (Array.isArray(d) ? d : []).filter(function (f) { return f.type === 'file'; })
          .map(function (f) { return f.name; });
      }).catch(function (e) { if (e.status === 404) return []; throw e; });
    },
    /* commit `text` to `path` on the branch; sha = the version it replaces (null for a new file), so a
       newer version is never overwritten. Returns the new sha and the commit's address. */
    write: function (path, text, sha, message) {
      var body = { message: message, content: utf8ToBase64(text), branch: branch };
      if (sha) body.sha = sha;
      return call('PUT', contentsPath(path), body).then(function (d) {
        return { sha: d.content.sha, commit: d.commit && d.commit.html_url };
      });
    },
    /* run the deploy with "Start the next rankings week" ticked */
    startWeek: function (workflow) {
      return call('POST', '/repos/{repo}/actions/workflows/' + encodeURIComponent(workflow || 'deploy.yml') +
                  '/dispatches', { ref: branch, inputs: { start_week: 'true' } });
    },
    actionsUrl: function () { return 'https://github.com/' + repo + '/actions'; },
  };
}
