"""Assemble and check the folder GitHub Pages serves (milestone M1, engine/publish/deploy.py).

    python tools/deploy_site.py sanity --dist dist [--previous URL_OR_FILE ...]
    python tools/deploy_site.py assemble --out _site --dist dist [--next DIR]

`sanity` checks a fresh engine build and writes its deploy-stats.json; with --previous
(the last deploy's deploy-stats.json; the first one that loads is used, so the M0
location /next/deploy-stats.json can follow the root one) it also checks that no season
lost games and the live week did not go backwards. When none can be fetched (the first
deploy) the comparisons are skipped with a note. `assemble` writes the engine build at
the root (and a preview build at /next/ with --next), then checks the root byte for byte
against the build and that every committed site file is in it. Both exit 1 on any problem.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine.publish import deploy  # noqa: E402

REPO = Path(__file__).resolve().parents[1]


def load_previous(places: list[str] | None) -> dict | None:
    for where in places or []:
        found = load_one(where)
        if found is not None:
            print(f"comparing with the last deploy's stats from {where}")
            return found
    if places:
        print("note: no previous deploy stats; comparisons skipped (the first deploy)")
    return None


def load_one(where: str) -> dict | None:
    try:
        if where.startswith(("http://", "https://")):
            with urllib.request.urlopen(where, timeout=30) as r:
                return json.loads(r.read().decode("utf-8"))
        return json.loads(Path(where).read_text(encoding="utf-8"))
    except Exception as exc:          # first deploy, or the preview is not up: nothing to compare with
        print(f"note: no deploy stats at {where} ({exc})")
        return None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("sanity")
    s.add_argument("--dist", required=True)
    s.add_argument("--previous", action="append", help="the last deploy's deploy-stats.json (repeatable)")
    a = sub.add_parser("assemble")
    a.add_argument("--out", required=True)
    a.add_argument("--dist", required=True)
    a.add_argument("--next", help="a second build to publish at /next/ (the Stage B preview)")
    args = ap.parse_args(argv)

    if args.cmd == "sanity":
        dist = Path(args.dist)
        problems = deploy.sanity(dist, load_previous(args.previous))
        now = deploy.stats(dist)
        (dist / deploy.STATS).write_text(json.dumps(now, indent=1) + "\n", encoding="utf-8")
        print(f"games by season: {now['games']}; current: {now['current']}; "
              f"{len(now['visible_managers'])} visible managers")
    else:
        out = Path(args.out)
        counts = deploy.assemble(REPO, out, Path(args.dist), Path(args.next) if args.next else None)
        problems = deploy.check_root(REPO, out, Path(args.dist))
        print(f"assembled {out}: {counts['root']} files at the root (the engine build), {counts['next']} at /next/")
    for p in problems:
        print(f"FAIL  {p}")
    print("OK" if not problems else f"{len(problems)} problem(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
