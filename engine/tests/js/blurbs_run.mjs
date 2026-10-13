// Runs web/assets/js/core/blurbs.js on a JSON job read from stdin and prints the results
// (engine/tests/test_blurbs.py compares them with engine/publish/blurbs.py).
// job: {vocab, items: [{text, auto_key}], sources: [{html, auto_key}]}
import { formatBlurb, toSource } from '../../../web/assets/js/core/blurbs.js';

let raw = '';
process.stdin.setEncoding('utf8');
process.stdin.on('data', (c) => { raw += c; });
process.stdin.on('end', () => {
  const job = JSON.parse(raw);
  const out = {
    formatted: job.items.map((i) => formatBlurb(i.text, job.vocab, i.auto_key)),
    sources: job.sources.map((s) => toSource(s.html, s.auto_key)),
  };
  process.stdout.write(JSON.stringify(out));
});
