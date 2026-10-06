"""Fail if the Stage B site template (web/) carries any league's data.

    python tools/check_web.py [web] [leagues]

web/ must hold no league facts (docs/ARCHITECTURE.md: "Site template; contains zero league
data"): every page reads names, colors and logos from config.json. This scans every text file
in web/ for each league's name, its managers' names, short names, slugs and keys, team names
from league.yaml, and the managers' hex colors, and lists every hit. Names match as whole words,
case-sensitive; colors without case.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

TEXT = {".html", ".js", ".css", ".json", ".svg", ".txt", ".md"}


def league_terms(yaml_path: Path) -> tuple[set[str], set[str]]:
    """(names, colors) league.yaml makes league data."""
    from engine.publish.config_json import short_name

    cfg = yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {}
    names, colors = set(), set()
    league = cfg.get("league") or {}
    if league.get("name"):
        names.add(str(league["name"]))
    for m in cfg.get("managers") or []:
        for v in (m.get("name"), m.get("id"), *(m.get("aliases") or [])):
            if v:
                names.add(str(v))
        if m.get("name"):
            names.add(short_name(str(m["name"])))
        for c in (m.get("colors") or {}).values():
            if isinstance(c, str) and c.startswith("#"):
                colors.add(c.lower())
    return {n for n in names if len(n) >= 3}, colors


def scan(web: Path, leagues: Path) -> list[str]:
    names, colors = set(), set()
    for y in sorted(leagues.glob("*/league.yaml")):
        n, c = league_terms(y)
        names |= n
        colors |= c
    name_re = re.compile(r"(?<![\w-])(" + "|".join(sorted(map(re.escape, names), key=len, reverse=True)) + r")(?![\w-])") \
        if names else None
    hits = []
    for path in sorted(p for p in web.rglob("*") if p.is_file() and p.suffix.lower() in TEXT):
        for lineno, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), start=1):
            found = set(name_re.findall(line)) if name_re else set()
            found |= {c for c in colors if c in line.lower()}
            for f in sorted(found):
                hits.append(f"{path.relative_to(web.parent).as_posix()}:{lineno}: league data in the template: {f}")
    return hits


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    web = Path(argv[0] if argv else "web")
    leagues = Path(argv[1] if len(argv) > 1 else "leagues")
    if not web.is_dir():
        print(f"no {web}/; nothing to check")
        return 0
    hits = scan(web, leagues)
    for h in hits:
        print(h)
    print(f"{len(hits)} league reference(s) in {web}/" if hits else f"OK: no league data in {web}/")
    return 1 if hits else 0


if __name__ == "__main__":
    sys.exit(main())
