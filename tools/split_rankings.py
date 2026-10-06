"""Split the site's weekly rankings files into editorial files and frozen snapshots.

    python tools/split_rankings.py leagues/preach/league.yaml [--site .]

Stage A only (PR A8b, decision 7.9). Until milestone M1 the weekly rankings are
still written on the PC into data/rankings/<season>_weekNN.json; this tool
imports every such file into
    leagues/<league>/editorial/rankings/<season>_weekNN.json   rank, synopsis, blurb, screenshots,
                                                               label, matchup of the week, ...
    leagues/<league>/snapshots/rankings/<season>_weekNN.json   the computed fields as published
                                                               (only weeks that have any)
and copies the playoff previews (<season>_playoff_<round>.json) into the editorial
folder as they are. `engine build` merges them back with the derived fields
(record, PPG, last score, streak, prev_rank, rank_change, avg_rank) and the
manifest. Run it after each weekly PC update; it rewrites a file only when its
content changed. From M1 on, `engine rankings new` writes the snapshot and an
editorial draft instead, and this tool is retired.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine.publish.rankings import (EDITORIAL_DIR, PREVIEW_FILE, SNAPSHOT_DIR, WEEK_FILE,  # noqa: E402
                                     read_json, split, write_json)


def _write(path: Path, data, counts: dict) -> None:
    if path.is_file() and read_json(path) == data:
        counts["unchanged"] += 1
        return
    counts["new" if not path.is_file() else "updated"] += 1
    write_json(path, data)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("path", help="league.yaml")
    p.add_argument("--site", default=".", help="folder holding the site (default: repo root)")
    args = p.parse_args(argv)
    league = Path(args.path).parent
    src = Path(args.site) / "data" / "rankings"
    counts = {"new": 0, "updated": 0, "unchanged": 0}
    n = 0
    for f in sorted(src.glob("*.json")):
        if WEEK_FILE.match(f.name):
            ed, snap = split(read_json(f))
            _write(league / EDITORIAL_DIR / f.name, ed, counts)
            if snap is not None:
                _write(league / SNAPSHOT_DIR / f.name, snap, counts)
            n += 1
        elif PREVIEW_FILE.match(f.name):
            _write(league / EDITORIAL_DIR / f.name, read_json(f), counts)
            n += 1
    print(f"{n} rankings files in {src}: {counts['new']} files written new, {counts['updated']} updated, "
          f"{counts['unchanged']} unchanged")
    return 0


if __name__ == "__main__":
    sys.exit(main())
