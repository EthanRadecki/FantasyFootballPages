// Runs web/assets/js/pages/rankings-week.js on a JSON job from stdin (engine/tests/test_rankings_editor.py).
// job: {lookup: {lowercase name: key}, files: {name: text}, checks: [{ed, expected}], vocab, builds: [{original, state, status}]}
import { serialize, problems, build, editable } from '../../../web/assets/js/pages/rankings-week.js';

let raw = '';
process.stdin.setEncoding('utf8');
process.stdin.on('data', (c) => { raw += c; });
process.stdin.on('end', () => {
  const job = JSON.parse(raw);
  const key = (n) => { const k = job.lookup[String(n == null ? '' : n).trim().toLowerCase()]; return k === undefined ? null : k; };
  const out = {
    serialized: Object.fromEntries(Object.entries(job.files).map(([n, t]) => [n, serialize(JSON.parse(t)) === t])),
    problems: job.checks.map((c) => problems(c.ed, c.expected, key)),
    unchanged: Object.fromEntries(Object.entries(job.files).map(([n, t]) => {
      const ed = JSON.parse(t);
      return [n, serialize(build(ed, editable(ed, job.vocab), job.vocab)) === t];
    })),
    builds: job.builds.map((b) => build(b.original, b.state, job.vocab, b.status)),
  };
  process.stdout.write(JSON.stringify(out));
});
