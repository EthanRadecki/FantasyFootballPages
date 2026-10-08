"""The change report (engine/publish/changes.py).

    python tools/change_report.py [--dist dist] [--site . | --site https://...] [--models]

Compares each legacy view in an engine build (`dist`, built with --verify so its
verify.json carries the build's summaries) with the site that is live (`site`: a
folder, by default the repo root, or the site's URL, whose files are downloaded
first) and writes dist/changes.html and dist/changes.json. The deploy publishes them
beside the build. Prints one line per page. --models compares the page models (data/v1/) instead
of the legacy views (the deploy's mode from M2 on).
"""

from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine.publish import changes  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--dist", default="dist")
    ap.add_argument("--site", default=".", help="the live site: a folder or a URL")
    ap.add_argument("--models", action="store_true", help="compare the page models (data/v1/), not the legacy views")
    args = ap.parse_args(argv)
    dist = Path(args.dist)
    with tempfile.TemporaryDirectory() as tmp:
        site = Path(args.site)
        if args.site.startswith(("http://", "https://")):
            site = Path(tmp)
            print(f"fetched {changes.fetch(args.site, dist, site, models=args.models)} files from {args.site}")
        rep = changes.write(dist, site, models=args.models)
    if rep["previous"] is not None:
        print(f"compared with the live build {rep['previous'].get('id')}")
    for line in changes.summary_lines(rep):
        print(line)
    if rep["unassigned"]:
        print(f"files without a page in the report: {', '.join(rep['unassigned'])}")
    print(f"wrote {dist / 'changes.html'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
