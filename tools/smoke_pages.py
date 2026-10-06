"""Headless page test: open every page in Chromium and fail on JavaScript errors or a blank page.

    python tools/smoke_pages.py [root] [--screenshots DIR] [--stub-cdn] [pages ...]

`root` (default: the repo root) is served over HTTP, and each page in the site's page
list (engine/publish/site.py) is opened in headless Chromium. A page fails when it throws
an uncaught error, logs a console error, or renders almost no text. Resources that fail
to load (an external image, say) are listed but do not fail the run: missing local files
are tools/check_paths.py's job. --screenshots saves a full-page PNG of each page so a run
can be compared with the last one. --stub-cdn answers Chart.js and d3 from local stubs,
for machines without internet access (CI loads the real libraries).

Needs `pip install playwright` and `python -m playwright install chromium`.
"""

from __future__ import annotations

import argparse
import functools
import http.server
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine.publish.site import PAGES  # noqa: E402

MIN_TEXT = 200          # characters of visible text a rendered page must have
SETTLE_MS = 1500        # wait after the network goes quiet, for charts and late renders
CDN_HOSTS = ("cdnjs.cloudflare.com", "cdn.jsdelivr.net", "unpkg.com", "d3js.org")
STUB = """
(function(){
  function deep(){ return new Proxy(function(){}, {get:(t,k)=> k in t ? t[k] : (t[k]=deep()),
                                                   set:(t,k,v)=>{t[k]=v;return true;}, apply:()=>deep()}); }
  function Chart(ctx, cfg){ this.config=cfg||{}; this.data=(cfg&&cfg.data)||{datasets:[]}; this.options=(cfg&&cfg.options)||{}; }
  Chart.prototype.destroy=function(){}; Chart.prototype.update=function(){}; Chart.prototype.resize=function(){};
  Chart.defaults = deep(); Chart.register=function(){}; Chart.getChart=function(){return null;};
  window.Chart = Chart; window.d3 = deep();
})();
"""


def serve(root: Path) -> tuple[http.server.ThreadingHTTPServer, int]:
    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *a):
            pass
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Quiet, directory=str(root)))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, httpd.server_address[1]


def check(root: Path, pages: list[str], shots: Path | None, stub_cdn: bool) -> list[dict]:
    from playwright.sync_api import sync_playwright

    httpd, port = serve(root)
    results = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            for path in pages:
                page = browser.new_page(viewport={"width": 1400, "height": 1000})
                errors, failed = [], []
                if stub_cdn:
                    page.add_init_script(STUB)
                    page.route(lambda url: any(h in url for h in CDN_HOSTS),
                               lambda route: route.fulfill(status=200, content_type="application/javascript",
                                                           body="/* stubbed */"))
                page.on("pageerror", lambda e, errors=errors: errors.append(f"uncaught: {e}"))
                page.on("console", lambda m, errors=errors, failed=failed: (
                    failed.append(m.text) if m.type == "error" and ("Failed to load resource" in m.text
                                                                    or "net::ERR" in m.text)
                    else errors.append(f"console: {m.text}") if m.type == "error" else None))
                page.on("requestfailed", lambda r, failed=failed: failed.append(f"{r.url} ({r.failure})"))
                try:
                    page.goto(f"http://127.0.0.1:{port}/{path}", wait_until="networkidle", timeout=60000)
                    page.wait_for_timeout(SETTLE_MS)
                    text = page.evaluate("document.body ? document.body.innerText.length : 0")
                    if shots:
                        shots.mkdir(parents=True, exist_ok=True)
                        name = path.replace("/", "_").replace("?", "_").replace("=", "-").replace("%20", "_")
                        page.screenshot(path=str(shots / f"{name}.png"), full_page=True)
                except Exception as exc:          # a page that never loads is a failure, not a crash
                    errors.append(f"load: {exc}")
                    text = 0
                if text < MIN_TEXT:
                    errors.append(f"blank: only {text} characters of text")
                results.append({"page": path, "errors": errors, "failed": failed, "text": text})
                page.close()
            browser.close()
    finally:
        httpd.shutdown()
    return results


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("root", nargs="?", default=".", help="folder to serve (default: the repo root)")
    ap.add_argument("pages", nargs="*", help="pages to open (default: the site's page list)")
    ap.add_argument("--screenshots", help="folder for one PNG per page")
    ap.add_argument("--stub-cdn", action="store_true", help="answer Chart.js and d3 from local stubs")
    ap.add_argument("-v", "--verbose", action="store_true", help="also list the resources that did not load")
    args = ap.parse_args(argv)
    root = Path(args.root)
    pages = args.pages or [p["path"] for p in PAGES if (root / p["path"]).is_file()]
    results = check(root, pages, Path(args.screenshots) if args.screenshots else None, args.stub_cdn)
    bad = 0
    for r in results:
        status = "FAIL" if r["errors"] else "PASS"
        bad += bool(r["errors"])
        print(f"{status}  {r['page']}: {r['text']} characters"
              + (f", {len(r['failed'])} resources did not load" if r["failed"] else ""))
        for e in r["errors"][:5]:
            print(f"      {e[:300]}")
        for f in (r["failed"][:5] if args.verbose else []):
            print(f"      (not loaded: {f[:200]})")
    print(f"\n{len(results) - bad} of {len(results)} pages passed")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
