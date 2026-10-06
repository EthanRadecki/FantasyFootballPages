"""Assemble and check the folder GitHub Pages serves (milestone M0, engine/publish/deploy.py).

    python tools/deploy_site.py sanity --dist dist [--previous URL_OR_FILE]
    python tools/deploy_site.py assemble --out _site [--dist dist]

`sanity` checks a fresh engine build and writes its deploy-stats.json; with --previous
(the last deploy's /next/deploy-stats.json) it also checks that no season lost games
and the live week did not go backwards. A previous file that cannot be fetched (the
first deploy) is skipped with a note. `assemble` writes the committed site at the root
and the engine build at /next/, then checks the root byte for byte against the repo.
Both exit 1 on any problem.
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


def load_previous(where: str | None) -> dict | None:
    if not where:
        return None
    try:
        if where.startswith(("http://", "https://")):
            with urllib.request.urlopen(where, timeout=30) as r:
                return json.loads(r.read().decode("utf-8"))
        return json.loads(Path(where).read_text(encoding="utf-8"))
    except Exception as exc:          # first deploy, or the preview is not up: nothing to compare with
        print(f"note: no previous deploy stats ({exc}); comparisons skipped")
        return None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("sanity")
    s.add_argument("--dist", required=True)
    s.add_argument("--previous")
    a = sub.add_parser("assemble")
    a.add_argument("--out", required=True)
    a.add_argument("--dist")
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
        counts = deploy.assemble(REPO, out, Path(args.dist) if args.dist else None)
        problems = deploy.check_root(REPO, out)
        print(f"assembled {out}: {counts['root']} site files at the root, {counts['next']} files at /next/")
    for p in problems:
        print(f"FAIL  {p}")
    print("OK" if not problems else f"{len(problems)} problem(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
