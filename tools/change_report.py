"""The M1 change report (engine/publish/changes.py).

    python tools/change_report.py [--dist dist] [--site .]

Compares each legacy view in an engine build (`dist`, built with --verify so its
verify.json carries the build's summaries) with the file the live site serves
(`site`, the repo root) and writes dist/changes.html and dist/changes.json. The
deploy publishes them at /next/changes.html. Prints one line per page.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine.publish import changes  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--dist", default="dist")
    ap.add_argument("--site", default=".")
    args = ap.parse_args(argv)
    rep = changes.write(Path(args.dist), Path(args.site))
    for line in changes.summary_lines(rep):
        print(line)
    if rep["unassigned"]:
        print(f"files without a page in the report: {', '.join(rep['unassigned'])}")
    print(f"wrote {Path(args.dist) / 'changes.html'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
