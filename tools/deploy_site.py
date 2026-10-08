"""Assemble and check the folder GitHub Pages serves (milestone M1, engine/publish/deploy.py).

    python tools/deploy_site.py sanity --dist dist [--previous URL_OR_FILE ...]
    python tools/deploy_site.py assemble --out _site --dist dist [--root web|legacy] [--next DIR]

`sanity` checks a fresh engine build and writes its deploy-stats.json; with --previous
(the last deploy's deploy-stats.json; the first one that loads is used, so the M0
location /next/deploy-stats.json can follow the root one) it also checks that no season
lost games and the live week did not go backwards. When none can be fetched (the first
deploy) the comparisons are skipped with a note. `assemble` with --root web (M2, the
default; else SITE_ROOT) writes the new site (dist/next/) at the root, the build files
beside it and redirects at /next/, and checks each file against the build; with --root
legacy it writes the engine build as before M2 (the Stage A site, the new site at /next/)
and checks the root byte for byte against the build and that every committed site file is
in it. Both exit 1 on any problem.
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
    a.add_argument("--root", choices=deploy.ROOTS, help="what the root serves (default: SITE_ROOT, else web)")
    a.add_argument("--league", action="append", default=[], metavar="PATH=DIST",
                   help="another league's build (DIST) to publish at /PATH/ (repeatable)")
    args = ap.parse_args(argv)

    if args.cmd == "sanity":
        dist = Path(args.dist)
        problems = deploy.sanity(dist, load_previous(args.previous))
        now = deploy.stats(dist)
        (dist / deploy.STATS).write_text(json.dumps(now, indent=1) + "\n", encoding="utf-8")
        print(f"games by season: {now['games']}; current: {now['current']}; "
              f"{len(now['visible_managers'])} visible managers")
    else:
        out, mode = Path(args.out), deploy.root_mode(args.root)
        extra = [(deploy.league_path(x.split("=", 1)[0]), Path(x.split("=", 1)[1])) for x in args.league]
        if mode == "web":
            counts = deploy.assemble_web(out, Path(args.dist))
            print(f"assembled {out}: {counts['root']} files at the root (the new site), "
                  f"{counts['next']} redirects at /next/")
        else:
            counts = deploy.assemble(REPO, out, Path(args.dist), Path(args.next) if args.next else None)
            print(f"assembled {out}: {counts['root']} files at the root (the Stage A site on engine data), "
                  f"{counts['next']} at /next/")
        for path, dist in extra:
            n = deploy.assemble_web(out / path, dist, redirects=False)
            print(f"assembled {out / path}: {n['root']} files (league at /{path}/)")
        problems = (deploy.check_web_root(out, Path(args.dist), leagues=tuple(p for p, _ in extra)) if mode == "web"
                    else deploy.check_root(REPO, out, Path(args.dist), leagues=tuple(p for p, _ in extra)))
        for path, dist in extra:
            problems += [f"/{path}/: {p}" for p in deploy.check_web_root(out / path, dist, redirects=False)]
    for p in problems:
        print(f"FAIL  {p}")
    print("OK" if not problems else f"{len(problems)} problem(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
